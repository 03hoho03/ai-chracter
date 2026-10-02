"""판정 리플레이 — 스탯·그림·엔딩 판정과 발행 심사를 모델·사고 설정별로 반복 호출해 JSONL 로 남긴다.

    cd apps/api
    # 1) 호출 없이 렌더만: 판정별 프롬프트 글자 수·예상 호출 수·예상 원가
    uv run --env-file .env python scripts/replay_judgments.py --prompt-snapshot SNAPSHOT.json --dry-run
    # 2) 사고 끔(thinking_budget=0)이 모델마다 받아들여지는지 — 모델당 3회
    REDIS_URL=redis://localhost:6388/7 uv run --env-file .env python scripts/replay_judgments.py \\
        --prompt-snapshot SNAPSHOT.json --probe-thinking --limit-calls 6
    # 3) 측정
    REDIS_URL=redis://localhost:6388/7 uv run --env-file .env python scripts/replay_judgments.py \\
        --prompt-snapshot SNAPSHOT.json --images-dir <그림이 있는 체크아웃>/apps/api/scripts/seed_content/images \\
        --limit-calls 536 --concurrency 2 --out probe-runs/judgment-replay.jsonl

`--prompt-snapshot` 은 운영 활성 세트의 판정·심사 채널 섹션을 떠 둔 JSON 이다(모양은 `judgment_replay/prompts.py`).
렌더는 이 문안으로만 한다 — 저장소 마이그레이션 문안은 운영 게시본과 다를 수 있다.

**`--limit-calls` 는 이 프로세스가 보내는 Gemini 호출 수의 하드 상한이다.** 넘는 호출은 보내지 않고 멈추며, 어디까지
돌았는지 마지막 줄에 찍는다. 설정 순서·회차 순서대로 돌아 멈춰도 앞 설정은 온전하다. 운영과 같은 API 키를 쓰면 운영
RPM 을 함께 먹으므로 `--concurrency` 는 1~2 로 둔다.

호출은 서버 클라이언트(`GeminiLLMClient.generate_structured`)를 그대로 지나므로 사용량이 그 프로세스의 `REDIS_URL`
집계에도 쌓인다 — 개발 Redis 의 집계를 섞지 않으려면 위처럼 쓰지 않는 Redis DB 번호를 준다. 집계 기록은 이벤트 루프에
묶이므로 이 스크립트는 `asyncio.run` 을 한 번만 부른다.

발행 심사 이미지는 시드 그림(`scripts/seed_content/images/`, gitignore)을 쓴다. 비어 있는 체크아웃이면 그림이 있는
체크아웃의 경로를 `--images-dir` 로 준다. 그림이 하나라도 없으면 호출 전에 멈춘다.
"""

import argparse
import asyncio
import json
import statistics
import sys
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from judgment_replay.prompts import read_prompt_snapshot
from judgment_replay.runner import (
    BASELINE_CONFIG,
    CONFIGS,
    CallBudget,
    ReplayConfig,
    install_usage_capture,
    probe_thinking,
    run_replay,
)
from judgment_replay.scenes import KINDS, JudgmentKind, ReplayInput, build_inputs

from api.llm.gemini import GeminiLLMClient
from api.llm.pricing import MODEL_PRICES

DEFAULT_IMAGES_DIR = Path(__file__).parent / "seed_content" / "images"
# 운영 스탯 판정의 prompt_tokens ÷ 글자 수로 잰 띠(이 저장소 판정 프롬프트, 한국어 위주). 이미지 토큰은 넣지 않는다.
TOKENS_PER_CHAR = (0.59, 0.67)
# 사고를 뺀 출력 토큰 가정 — 스키마 JSON 하나 크기. 사고 토큰은 실측 전이라 넣지 않는다(출력 단가로 더해진다).
ASSUMED_OUTPUT_TOKENS: dict[JudgmentKind, int] = {"stat": 60, "image": 25, "ending": 8, "publish": 30}


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prompt-snapshot", type=Path, required=True)
    parser.add_argument("--images-dir", type=Path, default=DEFAULT_IMAGES_DIR)
    parser.add_argument(
        "--out", type=Path, default=None, help="JSONL 경로(기본 probe-runs/judgment-replay-<시각>.jsonl)"
    )
    parser.add_argument("--dry-run", action="store_true", help="렌더만 하고 호출하지 않는다")
    parser.add_argument("--probe-thinking", action="store_true", help="모델별 사고 끔 수용 확인만 한다")
    parser.add_argument("--limit-calls", type=int, default=None, help="Gemini 호출 하드 상한(실호출 시 필수)")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--only", nargs="+", choices=KINDS, default=list(KINDS))
    parser.add_argument("--configs", nargs="+", choices=list(CONFIGS), default=list(CONFIGS))
    parser.add_argument("--reps", type=int, default=3, help="스탯·그림·엔딩 반복 횟수")
    parser.add_argument("--publish-reps", type=int, default=2, help="발행 심사 반복 횟수")
    args = parser.parse_args(argv)
    if not args.dry_run and args.limit_calls is None:
        parser.error("실호출에는 --limit-calls 가 필요하다")
    if args.concurrency < 1:
        parser.error("--concurrency 는 1 이상")
    return args


def _reps(args: argparse.Namespace) -> dict[JudgmentKind, int]:
    return {kind: (args.publish_reps if kind == "publish" else args.reps) for kind in KINDS if kind in args.only}


def _dry_run_report(inputs: list[ReplayInput], configs: list[ReplayConfig], reps: dict[JudgmentKind, int]) -> str:
    low, high = TOKENS_PER_CHAR
    lines = [
        "| 판정 | 입력 | 글자 수 최소 / 평균 / 최대 | 입력 토큰 추정(평균) | 이미지 | 회차 | 설정 | 예상 호출 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    total_calls = 0
    cost_by_config = dict.fromkeys((c.name for c in configs), 0.0)
    for kind in KINDS:
        group = [item for item in inputs if item.kind == kind]
        if not group or kind not in reps:
            continue
        chars = [len(item.prompt) for item in group]
        mean = statistics.fmean(chars)
        calls = len(group) * reps[kind] * len(configs)
        total_calls += calls
        images = sum(len(item.image_paths) for item in group)
        lines.append(
            f"| {kind} | {len(group)} | {min(chars):,} / {mean:,.0f} / {max(chars):,} | "
            f"{mean * low:,.0f}~{mean * high:,.0f} | {images} | {reps[kind]} | {len(configs)} | {calls} |"
        )
        for config in configs:
            price = MODEL_PRICES[config.model]
            input_tokens = sum(chars) * (low + high) / 2
            per_rep = (
                input_tokens * price.input_usd_per_million
                + len(group) * ASSUMED_OUTPUT_TOKENS[kind] * price.output_usd_per_million
            ) / 1_000_000
            cost_by_config[config.name] += per_rep * reps[kind]
    lines.append(f"| 합계 |  |  |  |  |  |  | {total_calls} |")
    lines += ["", "| 설정 | 예상 원가(USD, 이미지·사고 토큰 제외) |", "|---|---|"]
    lines += [f"| {name} | {cost:.4f} |" for name, cost in cost_by_config.items()]
    lines.append(f"| 합계 | {sum(cost_by_config.values()):.4f} |")
    return "\n".join(lines)


def _sink(handle: TextIO) -> Any:
    def write(record: dict[str, Any]) -> None:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()

    return write


async def _run(args: argparse.Namespace) -> int:
    snapshot = read_prompt_snapshot(args.prompt_snapshot)
    configs = [CONFIGS[name] for name in args.configs]
    reps = _reps(args)
    inputs = [item for item in build_inputs(snapshot, images_dir=args.images_dir) if item.kind in reps]

    if args.dry_run:
        print(f"렌더 세트: {snapshot.set_ids}")
        print(_dry_run_report(inputs, configs, reps))
        missing = sorted({str(p) for item in inputs for p in item.image_paths if not p.is_file()})
        if missing:
            print(f"\n없는 이미지 {len(missing)}개 — 실호출 전에 --images-dir 를 고쳐야 한다: {missing[:3]}…")
        return 0

    absent = sorted({str(p) for item in inputs for p in item.image_paths if not p.is_file()})
    if absent and not args.probe_thinking:
        print(f"없는 이미지가 있어 호출하지 않는다: {absent}", file=sys.stderr)
        return 2

    run_id = uuid.uuid4().hex[:12]
    out: Path = args.out or Path("probe-runs") / f"judgment-replay-{datetime.now(UTC):%Y%m%dT%H%M%S}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    client = GeminiLLMClient()
    install_usage_capture(client)
    budget = CallBudget(args.limit_calls)
    with out.open("a", encoding="utf-8") as handle:
        sink = _sink(handle)
        if args.probe_thinking:
            models = list(dict.fromkeys(config.model for config in configs))
            sink({"kind": "run", "run_id": run_id, "mode": "probe", "models": models, "limit": args.limit_calls})
            result = await probe_thinking(client, models, budget=budget, sink=sink, run_id=run_id)
        else:
            planned = sum(reps[item.kind] for item in inputs) * len(configs)
            sink(
                {
                    "kind": "run",
                    "run_id": run_id,
                    "mode": "replay",
                    "baseline": BASELINE_CONFIG,
                    "configs": [config.name for config in configs],
                    "reps": reps,
                    "inputs": len(inputs),
                    "planned_calls": planned,
                    "limit": args.limit_calls,
                    "prompt_sets": snapshot.set_ids,
                }
            )
            result = await run_replay(
                client,
                inputs,
                configs,
                reps=reps,
                budget=budget,
                concurrency=args.concurrency,
                sink=sink,
                run_id=run_id,
            )
    status = (
        f"{result.stopped_by_errors} 실패가 연달아 나서 멈춤"
        if result.stopped_by_errors
        else "상한에 걸려 멈춤"
        if result.stopped_by_limit
        else "완료"
    )
    print(f"{status}: 호출 {result.calls}회 (상한 {args.limit_calls}) → {out}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_run(_parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
