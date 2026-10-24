"""측정 하네스 CLI 의 인상(Reflective) 묶음 — 운영과 같은 입력 뽑기, 후보 문안으로 인상 다시 만들기, 길이 집계, 문장 판정.

유료 호출이 나는 두 명령(`impression-proto`·`impression-judge`)은 `--dry-run` 이 견적만 내고, 실제 호출은 `--allow-paid` 와 원장
상한·멈춤 선·승인 묶음을 모두 줘야 돈다. 이번 실행 전체 견적이 묶음 여유를 넘으면 첫 호출 전에 멈춘다. 표준출력에는 개수·길이·
비율·원가만 나간다 — 인상 글과 입력 줄은 결과 파일에만 있다."""

import argparse
import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from memory_eval.cli_common import _db_url, _ledger, _print, _write, paid
from memory_eval.ledger import BudgetExceededError, Ledger


def _limit(book: Ledger, args: argparse.Namespace, total_usd: float) -> None:
    limit = args.cap_usd if args.halt_usd is None else min(args.cap_usd, args.halt_usd)
    if book.bundle_usd() + total_usd > limit:
        raise BudgetExceededError(
            f"묶음 {args.bundle} 누적 ${book.bundle_usd():.4f} + 이번 전체 견적 ${total_usd:.4f} 가 상한·멈춤 선 ${limit:.4f} 를 넘는다"
        )


def _with_ledger(estimate: dict[str, Any], args: argparse.Namespace, total_usd: float) -> dict[str, Any]:
    book = _ledger(args)
    estimate["ledgerSpentUsd"] = book.total_usd()
    if args.cap_usd is not None:
        estimate["bundleSpentUsd"] = book.bundle_usd()
        estimate["capUsd"] = args.cap_usd
        estimate["headroomUsd"] = args.cap_usd - book.bundle_usd() - total_usd
    return estimate


def cmd_impression_inputs(args: argparse.Namespace) -> int:
    """방마다 운영과 같은 인상 입력을 묶음 단위로 뽑는다(DB 읽기만). 실행 명령의 `DATABASE_URL` 이 그 방이 있는 DB 다."""
    from memory_eval import impression_proto as ip
    from memory_eval.runtime import make_engine

    async def run() -> tuple[list[Any], list[dict[str, Any]]]:
        engine, factory = make_engine(_db_url(writes=False))
        try:
            inputs: list[Any] = []
            skipped: list[dict[str, Any]] = []
            async with factory() as session:
                for room in args.room:
                    got, missed = await ip.load_room_inputs(session, uuid.UUID(room), every=args.every)
                    inputs += got
                    skipped += missed
            return inputs, skipped
        finally:
            await engine.dispose()

    inputs, skipped = asyncio.run(run())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for item in inputs:
            handle.write(json.dumps(item.to_json(), ensure_ascii=False) + "\n")
    _print(
        {
            "out": str(args.out),
            "every": args.every,
            "groups": len(inputs),
            "skipped": skipped,
            "episodeLines": sum(len(i.episode_lines) for i in inputs),
            "factLines": sum(len(i.fact_lines) for i in inputs),
            "withheldEpisodes": sum(i.withheld_episodes for i in inputs),
            "withheldFacts": sum(i.withheld_facts for i in inputs),
            "emptyGroups": sum(1 for i in inputs if not i.episode_lines and not i.fact_lines),
        }
    )
    return 0


def _pick(items: list[Any], groups: str | None) -> list[Any]:
    if not groups:
        return items
    wanted = {int(g) for g in groups.split(",") if g.strip()}
    return [item for item in items if item.group_index in wanted]


def cmd_impression_proto(args: argparse.Namespace) -> int:
    """후보 문안으로 인상을 다시 만든다. `--dry-run` 은 견적만, `--allow-paid` 는 운영 인상 호출과 같은 경로(앱의 Anthropic 직결
    구현, 인상 모델 설정 Haiku)로 실제 호출."""
    from memory_eval import impression_proto as ip

    from api.core.config import settings

    items = _pick(ip.load_inputs(args.inputs), args.groups)
    # 입력 줄이 하나도 없는 묶음은 운영도 모델을 부르지 않는다.
    items = [item for item in items if item.episode_lines or item.fact_lines]
    sections, candidate_sha = ip.load_candidate(args.candidate)
    model = settings.anthropic_haiku_model_id
    done = {
        str(r["key"])
        for r in ip.read_rows(args.out)
        if r.get("candidateSha") == candidate_sha and r.get("status") == "ok"
    }
    estimate = ip.estimate(
        items, sections, model=model, tokens_per_char=args.tokens_per_char, output_tokens=args.output_tokens, done=done
    )
    estimate |= {"candidateSha": candidate_sha, "model": model, "items": len(items)}
    if args.dry_run or not args.allow_paid:
        _print(_with_ledger(estimate, args, estimate["totalUsd"]))
        return 0

    from api.llm.anthropic_api import AnthropicLLMClient
    from memory_eval.judge_agreement import without_usage_store

    book = _ledger(args)
    _limit(book, args, estimate["totalUsd"])

    async def run() -> int:
        with without_usage_store():
            return await ip.run_generation(
                items,
                sections,
                candidate_sha=candidate_sha,
                client=AnthropicLLMClient(),
                ledger=book,
                out_path=args.out,
                stage=args.label,
                call_estimate_usd=estimate["perCallMaxUsd"],
            )

    made = asyncio.run(run())
    rows = [r for r in ip.read_rows(args.out) if r.get("candidateSha") == candidate_sha]
    _print({"made": made, "bundleSpentUsd": book.bundle_usd(), "lengths": ip.length_report(rows)})
    return 0


def cmd_impression_metrics(args: argparse.Namespace) -> int:
    from memory_eval import impression_proto as ip

    rows = ip.read_rows(args.results)
    if args.candidate_sha:
        rows = [r for r in rows if r.get("candidateSha") == args.candidate_sha]
    _print(ip.length_report(rows))
    return 0


def cmd_impression_judge(args: argparse.Namespace) -> int:
    """인상 문장마다 근거·설정 어긋남을 판정한다. 문항은 `--items`(대조군 등 정답이 붙은 파일) 또는 `--results`+`--inputs`+
    `--settings`(생성 결과를 입력·방 작가 설정과 이은 것). `--dry-run` 은 견적만, `--allow-paid` 는 실제 호출, 둘 다 없으면 남은
    결과로 집계만."""
    from memory_eval import impression_proto as ip

    from api.core.config import settings

    template = json.loads(args.wording.read_text(encoding="utf-8"))["template"]
    ip.check_template(template)
    if args.items is not None:
        items = ip.load_items(args.items)
    else:
        if args.results is None or args.inputs is None or args.settings is None:
            raise SystemExit("--items 가 없으면 --results·--inputs·--settings 를 함께 준다")
        rows = ip.read_rows(args.results)
        if args.candidate_sha:
            rows = [r for r in rows if r.get("candidateSha") == args.candidate_sha]
        items = ip.items_from_results(
            rows, ip.load_inputs(args.inputs), json.loads(args.settings.read_text(encoding="utf-8"))
        )
    done = {(r["itemId"], r["promptSha"]) for r in ip.read_rows(args.out)}
    estimate = ip.judge_estimate(
        items,
        template,
        model=args.judge_model,
        tokens_per_char=args.tokens_per_char,
        output_tokens=args.output_tokens,
        done=done,
    )
    if args.dry_run:
        _print(_with_ledger(estimate, args, estimate["ceilingUsd"]))
        return 0
    if args.allow_paid:
        book = _ledger(args)
        _limit(book, args, estimate["ceilingUsd"])
        judge = ip.OpusImpressionJudge(
            settings.anthropic_direct_api_key,
            book,
            stage=args.label,
            call_estimate_usd=estimate["perCallMaxUsd"],
            model=args.judge_model,
        )
        asyncio.run(ip.judge_items(items, judge, template=template, out_path=args.out, concurrency=args.concurrency))
    wanted = {(item.item_id, ip.sha256_text(ip.render_judge_prompt(template, item))) for item in items}
    judged = [r for r in ip.read_rows(args.out) if (r["itemId"], r["promptSha"]) in wanted]
    report = ip.judge_report(judged) | {"pendingItems": len(wanted) - len(judged), "judgeModel": args.judge_model}
    _write(args.out.with_suffix(".report.json"), report)
    _print(report)
    return 0


def register(sub: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    from memory_eval import impression_proto as ip
    from memory_eval.judge_agreement import DEFAULT_TOKENS_PER_CHAR

    p = sub.add_parser(
        "impression-inputs", help="방마다 운영과 같은 인상 입력(공개 장면·사실 행)을 묶음 단위로 뽑는다(DB 읽기만)"
    )
    p.add_argument("--room", action="append", required=True, help="방 id(여러 번)")
    p.add_argument("--every", type=int, required=True, help="인상 하나가 덮는 접기 수(N)")
    p.add_argument("--out", type=Path, required=True, help="입력 JSONL")
    p.set_defaults(fn=cmd_impression_inputs)

    p = sub.add_parser("impression-proto", help="후보 문안으로 인상을 다시 만든다(운영 인상 호출과 같은 경로)")
    paid(p)
    p.add_argument("--inputs", type=Path, nargs="+", required=True)
    p.add_argument("--candidate", type=Path, required=True, help="후보 문안 JSON {sections: [...]}")
    p.add_argument("--groups", help="쓸 묶음 번호(쉼표, 기본 전부)")
    p.add_argument("--out", type=Path, required=True, help="결과 JSONL(이어 쓴다)")
    p.add_argument(
        "--tokens-per-char", type=float, default=DEFAULT_TOKENS_PER_CHAR, help="견적 자리값: 글자당 입력 토큰"
    )
    p.add_argument("--output-tokens", type=int, default=500, help="견적 자리값: 호출당 출력 토큰")
    p.add_argument("--label", default="impression-proto", help="원장 단계 이름")
    p.set_defaults(fn=cmd_impression_proto)

    p = sub.add_parser("impression-metrics", help="인상 결과의 길이 집계(글은 내지 않는다)")
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--candidate-sha", help="이 후보 문안의 줄만")
    p.set_defaults(fn=cmd_impression_metrics)

    p = sub.add_parser("impression-judge", help="인상 문장마다 근거·작가 설정 어긋남 판정(대조군이면 관문까지)")
    paid(p)
    p.add_argument("--items", type=Path, help="판정 문항 JSON(정답이 붙으면 대조군 관문을 낸다)")
    p.add_argument("--results", type=Path, help="impression-proto 결과 JSONL")
    p.add_argument("--inputs", type=Path, nargs="+", help="impression-inputs 결과 JSONL")
    p.add_argument("--settings", type=Path, help="방 id → 작가 설정 글 JSON")
    p.add_argument("--candidate-sha", help="이 후보 문안의 결과만")
    p.add_argument("--wording", type=Path, required=True, help='판정 문안 JSON {"template": ...}(공개 저장소 밖)')
    p.add_argument("--out", type=Path, required=True, help="판정 JSONL(이어 쓴다). 집계는 같은 이름의 .report.json")
    p.add_argument("--judge-model", default=ip.JUDGE_MODEL)
    p.add_argument("--concurrency", type=int, default=4, help="동시에 판정하는 문항 수")
    p.add_argument(
        "--tokens-per-char", type=float, default=DEFAULT_TOKENS_PER_CHAR, help="견적 자리값: 글자당 입력 토큰"
    )
    p.add_argument("--output-tokens", type=int, default=2000, help="견적 자리값: 호출당 출력(사고 포함) 토큰")
    p.add_argument("--label", default="impression-judge", help="원장 단계 이름")
    p.set_defaults(fn=cmd_impression_judge)
