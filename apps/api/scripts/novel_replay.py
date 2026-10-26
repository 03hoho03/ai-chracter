"""측정 서버가 남긴 소설 덤프의 호출을 다시 보낸다 — 같은 슬롯 값에서 현행 갈래와 한 축만 바꾼 갈래의 출력을 모으고, 그 출력에서
기계 지표(형식 유효율·길이·누출 표지)를 센다.

    cd apps/api
    # 현행 갈래만 시험 실행(호출 0) — 덤프의 세트 섹션과 슬롯 값으로 다시 렌더한 바이트가 덤프의 sha 와 같은지 본다
    uv run --env-file .env python scripts/novel_replay.py run --dump <run>/novel-dump.jsonl \\
        --ledger <run>/replay/ledger.jsonl --limit-calls 0 --limit-usd 0
    # 변형 갈래 하나(축은 하나만): 세트(id 또는 그 모델 체인의 초안) · 모델
    ... --set <세트 id> --arm b ...
    ... --set draft --model sonnet --arm draft ...
    ... --model opus --arm opus ...
    # 실제 호출(비용이 든다)
    ... --reps 2 --limit-calls 40 --limit-usd 5 --execute
    # 리포트(DB·LLM 없음, 개수·비율만)
    uv run --env-file .env python scripts/novel_replay.py report --ledger '<run>/replay/*.jsonl' \\
        --dump <run>/novel-dump.jsonl --marker <표지> [--format json] [--out <run>/replay/report.md]

입력은 측정 서버가 `NOVEL_PROMPT_DUMP_PATH` 로 남긴 덤프다(`novelize/prompt_dump.py`). 대상은 화 생성·전체 구성안·장면 구성안
세 채널이고 그 밖의 줄은 거른다. 줄마다 그 줄의 소설 세트 섹션을 `--env-file` 로 준 DB 에서 읽어 운영 렌더러(`prompts._render`)로
다시 렌더한다 — 그 DB 가 로컬(localhost 류)이 아니면 무엇이든 읽기 전에 거부한다. 실제 사용자 대화를 생성 모델에 다시 보내지
않기 위해서다. 다시 렌더한 지시문·본문이 덤프의 sha 와 둘 다 같고, 현행 갈래가 보낼 모델 id 가 덤프의 모델 id(`callModel`)와
같아야 그 줄을 부른다 — 모델이 다르면 대조군이 측정 때와 다른 모델로 불려 갈래 비교가 무너진다. 다른 줄은 실패로 남기고
나머지만 부르며, `--stop-on-mismatch` 면 한 줄이라도 다를 때 아무것도 부르지 않는다.

갈래:
- 현행(window): 덤프의 세트·작업 모델 그대로.
- 세트 축(`--set`): 같은 슬롯 값을 그 세트의 섹션으로 렌더한다. 원문 줄의 화자 라벨과 화 목표 글자 수처럼 렌더 전에 정해진 값은
  슬롯 값 안에 있어 바뀌지 않는다. 세트는 그 세트의 모델 체인으로 부른다(초안은 (레인, 모델)마다 있어 `--model` 을 함께 준다).
  기록에는 섹션 지문(어드민 초안 지문과 같은 함수)을 남긴다 — 초안은 나중에 바뀌므로 그때 무엇으로 불렀는지를 원장이 담는다.
- 모델 축(`--model`): 현행 갈래와 같은 바이트를 그 모델로 부른다.

호출 위치는 운영 소설 호출 위치(`novelize_*`) 그대로다 — 라우팅·출력 상한·사고 설정이 운영과 같다. 사용량은 이 도구를 돌리는
로컬 DB 에만 쌓인다.

원장(`--ledger`, jsonl 하나)에 갈래마다 plan·call 기록과 상한 기록을 붙여 쓴다. 원장의 앞 호출 원가는 이번 `--limit-usd` 에 들어간다
(채팅 리플레이의 장부 규칙 — 원가를 모르는 호출은 그 모델의 상한 추정). 원가 상한은 호출마다 부르기 전에 건다: 누적 원가에 그
호출의 최악 견적(입력 추정과 출력 상한)을 더해 상한을 넘으면 부르지 않고 멈춘 자리를 원장에 남긴다. 공용 장부는 원가를 호출이 끝난
뒤에 더하므로 그것만으로는 마지막 한 호출만큼 상한을 넘을 수 있어서다. 시험 실행은 누적 원가에 전체 최악 견적을 더한 값이 상한을
넘으면 경고 줄을 낸다. 같은 (작업, 갈래, 반복) 호출이 원장에 이미 있으면 부르지 않는다. 원장의 모델 칸(`sentModel`)은 공급자가 사용량과 함께 돌려준 실제 모델 id 이고, 판 번호(`setSemver`)는 세트 id 로 판 표를
이어 읽은 값이다(서빙 경로는 판 표를 읽지 않아 덤프에 없다). 원장에는 출력 본문이 실리므로 저장소에 올리지 않는 측정 디렉터리
(`apps/api/probe-runs/`) 아래에 둔다. 리포트에는 개수·비율·판 번호·모델 id 만 싣는다.

종료 코드: 0 정상 · 1 입력 파일 없음 · 2 재렌더·모델이 덤프와 다르거나 거부된 줄(세트가 없음 등)이 있음·이미 부른 호출, 인자 오류도
argparse 가 2 · 3 원장이 이미 원가 상한 이상.
"""

import argparse
import asyncio
import hashlib
import json
import re
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import groupby
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

import novel_replay_metrics as metrics
from api.admin.prompt_semver import draft_fingerprint, section_contents, semvers_of
from api.chat.prompt_builder import PromptRenderError
from api.core.config import settings
from api.llm.call_policy import BackendId
from api.llm.chat_models import ChatModelId, parse_chat_model_id
from api.llm.client import LLMCallContext, LLMCallSite, LLMClient, structured_model
from api.llm.dependencies import get_llm_client
from api.llm.pricing import MODEL_PRICES, estimate_cost_usd
from api.llm.routing import resolve_backend
from api.novelize.prompts import _render
from replay.assemble import CHARS_PER_TOKEN
from replay.budget import CallBudget, ledger_paths, sum_ledger
from replay.calls import SentCall, _cost, _tokens, capture_usage
from replay.local_db import ensure_local_database
from replay.logs import ReplayRefusedError
from replay.prompt_sets import ChosenSet, draft_set, set_by_id

# 대상 채널 — 채널 이름이 곧 운영 호출 위치 이름이다.
_CALL_SITES: dict[str, LLMCallSite] = {
    "novelize_chapter": "novelize_chapter",
    "novelize_outline": "novelize_outline",
    "novelize_episode_outline": "novelize_episode_outline",
}
TARGET_CHANNELS = tuple(_CALL_SITES)
_ARM_NAME = re.compile(r"[\w.-]+")

# 소설 호출이 실제로 갈 구현의 출력 상한(원고 상한) — 원가를 모르고 끝난 호출을 상한에 셀 때 쓴다. 호출마다 설정에서 읽는다.
_OUTPUT_CAP: dict[BackendId, Callable[[], int]] = {
    "gemini": lambda: settings.gemini_novelize_max_output_tokens,
    "bedrock": lambda: settings.bedrock_chapter_max_tokens,
    "anthropic": lambda: settings.anthropic_chapter_max_tokens,
}

Variant = Literal["window", "set", "model"]


@dataclass(frozen=True)
class ArmSpec:
    variant: Literal["set", "model"]
    arm: str
    set_id: uuid.UUID | None = None
    set_draft: bool = False
    model: ChatModelId | None = None


@dataclass(frozen=True)
class NovelCall:
    """부를 호출 하나 — 덤프 줄 번호와 작업 id, 갈래, 렌더한 지시문·본문, 응답 스키마(화 생성은 None)."""

    line: int
    job_id: str
    channel: str
    call_site: LLMCallSite
    variant: Variant
    arm: str
    chain_model: ChatModelId
    schema: type[BaseModel] | None
    system_instruction: str
    prompt: str

    def sent_model(self) -> str:
        """이 호출이 보낼 실제 모델 id — 덤프와 같은 해석(라우터의 구현 고르기, Gemini 는 소설화 모델 설정)."""
        backend, sent = resolve_backend(self.call_site, self.chain_model)
        return structured_model(self.call_site, sent) if backend == "gemini" else sent

    def cost_ceiling_usd(self) -> float:
        """원가를 모르고 끝난 호출을 상한에 셀 값 — 입력 추정과 출력 상한을 다 쓴 경우. 단가표에 없는 모델이면 단가표에서 가장 비싼
        모델로 센다(채팅 리플레이와 같은 규칙)."""
        tokens = round((len(self.prompt) + len(self.system_instruction)) / CHARS_PER_TOKEN)
        output = _OUTPUT_CAP[resolve_backend(self.call_site, self.chain_model)[0]]()
        cost = estimate_cost_usd(
            self.sent_model(), input_tokens=tokens, cached_tokens=0, output_tokens=output, thoughts_tokens=0
        )
        if cost is not None:
            return cost
        return max(
            estimate_cost_usd(model, input_tokens=tokens, cached_tokens=0, output_tokens=output, thoughts_tokens=0)
            or 0.0
            for model in MODEL_PRICES
        )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="소설 덤프의 호출을 같은 입력으로 다시 보내고 기계 지표를 센다")
    sub = ap.add_subparsers(dest="command", required=True)
    run_ap = sub.add_parser("run", help="재렌더 단언 후 현행·변형 갈래를 부른다(기본 시험 실행)")
    run_ap.add_argument("--dump", required=True, help="측정 서버의 소설 덤프(NOVEL_PROMPT_DUMP_PATH)")
    run_ap.add_argument("--channel", action="append", choices=TARGET_CHANNELS, help="대상 채널(여럿 가능, 기본 셋 다)")
    run_ap.add_argument("--set", help="세트 축: 소설 세트 id 또는 draft(--model 체인의 초안)")
    run_ap.add_argument("--model", choices=list(get_args(ChatModelId)), help="모델 축(같은 바이트를 이 모델로)")
    run_ap.add_argument("--arm", help="변형 갈래 이름(축을 줄 때 필수)")
    run_ap.add_argument("--skip-window-calls", action="store_true", help="현행 갈래는 단언에만 쓰고 변형 갈래만 부른다")
    run_ap.add_argument(
        "--stop-on-mismatch", action="store_true", help="재렌더가 다른 줄이 하나라도 있으면 아무것도 부르지 않는다"
    )
    run_ap.add_argument("--reps", type=int, default=1)
    run_ap.add_argument("--limit-calls", type=int, required=True, help="이 실행의 실호출 하드 상한")
    run_ap.add_argument("--limit-usd", type=float, required=True, help="원장 포함 실제 원가 누적 상한(달러)")
    run_ap.add_argument("--ledger", required=True, help="원장 jsonl — 기록을 붙여 쓰고 앞 호출 원가를 상한에 넣는다")
    run_ap.add_argument("--execute", action="store_true", help="LLM 을 실제로 부른다(비용이 든다)")
    report_ap = sub.add_parser("report", help="원장의 호출 출력에서 기계 지표를 센다(DB·LLM 없음)")
    report_ap.add_argument("--ledger", required=True, help="원장 glob(재귀 **)")
    report_ap.add_argument("--dump", required=True, help="원장을 만든 소설 덤프 — 줄의 슬롯 값을 누출 표지 판정에 쓴다")
    report_ap.add_argument("--marker", action="append", default=[], help="입력에 심은 누출 표지 문자열(여럿 가능)")
    report_ap.add_argument("--format", choices=("md", "json"), default="md")
    report_ap.add_argument("--out", help="리포트 파일(없으면 표준 출력)")
    return ap


def _arm_from_args(ap: argparse.ArgumentParser, args: argparse.Namespace) -> ArmSpec | None:
    """축은 하나만 받는다 — 두 축을 함께 바꾸면 출력 차이가 어느 쪽 때문인지 가릴 수 없다. 예외는 초안이다: 초안은 (레인, 모델)마다
    있어 모델을 함께 줘야 고를 수 있다."""
    if args.set is None and args.model is None:
        if args.arm is not None:
            ap.error("--arm 은 변형 축(--set·--model)과 함께만 준다")
        if args.skip_window_calls:
            ap.error("--skip-window-calls 는 변형 축과 함께만 준다")
        return None
    if args.arm is None:
        ap.error("변형 축을 주면 --arm 으로 갈래 이름을 붙인다")
    if not _ARM_NAME.fullmatch(args.arm) or args.arm == "window":
        ap.error(f"갈래 이름은 글자·숫자·._- 로만, window 는 쓸 수 없다: {args.arm}")
    if args.set is None:
        return ArmSpec(variant="model", arm=args.arm, model=args.model)
    if args.set == "draft":
        if args.model is None:
            ap.error("--set draft 는 --model 로 초안의 모델 체인을 고른다")
        return ArmSpec(variant="set", arm=args.arm, set_draft=True, model=args.model)
    if args.model is not None:
        ap.error("세트 id 를 주면 그 세트의 모델로 부른다 — --model 은 초안을 고를 때만 함께 준다")
    try:
        set_id = uuid.UUID(args.set)
    except ValueError:
        ap.error(f"--set 은 세트 id 또는 draft: {args.set}")
    return ArmSpec(variant="set", arm=args.arm, set_id=set_id)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.command == "run":
        if args.reps < 1:
            ap.error("--reps 는 1 이상")
        if args.limit_calls < 0 or args.limit_usd < 0:
            ap.error("--limit-calls·--limit-usd 는 0 이상")
        args.arm_spec = _arm_from_args(ap, args)
    return args


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def target_lines(dump: Path, channels: tuple[str, ...]) -> list[tuple[int, dict[str, Any]]]:
    """대상 채널 줄과 그 줄 번호(1부터, 파일 그대로 — 리포트가 이 번호로 슬롯 값을 찾는다)."""
    return [
        (number, record)
        for number, record in enumerate(_read_jsonl(dump), start=1)
        if record.get("channel") in channels
    ]


class _SetReader:
    """줄마다 같은 세트를 다시 읽지 않게 세트와 그 판 번호·섹션 지문을 한 번만 읽는다."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._sets: dict[uuid.UUID, ChosenSet] = {}
        self._drafts: dict[ChatModelId, ChosenSet] = {}
        self._facts: dict[uuid.UUID, dict[str, Any]] = {}

    async def by_id(self, set_id: uuid.UUID) -> ChosenSet:
        if set_id not in self._sets:
            self._sets[set_id] = await set_by_id(self.db, set_id, lane="novel")
        return self._sets[set_id]

    async def draft(self, model: ChatModelId) -> ChosenSet:
        if model not in self._drafts:
            self._drafts[model] = await draft_set(self.db, lane="novel", model=model)
        return self._drafts[model]

    async def facts(self, chosen: ChosenSet) -> dict[str, Any]:
        prompt_set = chosen.prompt_set
        if prompt_set.id not in self._facts:
            semvers = await semvers_of(self.db, [prompt_set.id])
            self._facts[prompt_set.id] = {
                "novelSetId": str(prompt_set.id),
                "setStatus": prompt_set.status,
                "setRule": chosen.rule,
                "setSemver": semvers.get(prompt_set.id),
                "sectionsSha256": draft_fingerprint(section_contents(prompt_set, chosen.sections)),
            }
        return self._facts[prompt_set.id]


def _render_call(
    chosen: ChosenSet, record: dict[str, Any], *, line: int, variant: Variant, arm: str, chain_model: ChatModelId
) -> NovelCall:
    channel: str = record["channel"]
    rendered = _render(
        chosen.sections,
        channel=channel,
        is_story_chat=record["scope"] == "story",
        values=record["values"],
        with_rating=bool(record["withRating"]),
    )
    return NovelCall(
        line=line,
        job_id=str(record["jobId"]),
        channel=channel,
        call_site=_CALL_SITES[channel],
        variant=variant,
        arm=arm,
        chain_model=chain_model,
        schema=metrics.STRUCTURED_SCHEMAS.get(channel),
        system_instruction=rendered.system_instruction,
        prompt=rendered.prompt,
    )


def _check_record(record: dict[str, Any]) -> tuple[uuid.UUID, ChatModelId]:
    """덤프 줄이 이 도구가 다시 렌더할 수 있는 모양인지 — 아니면 `ReplayRefusedError`."""
    channel = record["channel"]
    if record.get("callSite") != channel:
        raise ReplayRefusedError(f"호출 위치 {record.get('callSite')!r} 가 채널 {channel!r} 과 다르다")
    schema = metrics.STRUCTURED_SCHEMAS.get(channel)
    if record.get("schema") != (schema.__name__ if schema is not None else None):
        raise ReplayRefusedError(f"응답 스키마 {record.get('schema')!r} 가 채널 {channel!r} 의 것이 아니다")
    values = record.get("values")
    if not isinstance(values, dict) or not all(isinstance(v, str) for v in values.values()):
        raise ReplayRefusedError("슬롯 값이 글자 사전이 아니다")
    if record.get("scope") not in ("story", "character"):
        raise ReplayRefusedError(f"원작 종류 {record.get('scope')!r} 를 모른다")
    try:
        set_id = uuid.UUID(str(record.get("novelSetId")))
    except ValueError:
        raise ReplayRefusedError("소설 세트 id 가 없다") from None
    job_model = record.get("jobModel")
    model = parse_chat_model_id(job_model) if job_model is not None else "gemini"
    if model is None:
        raise ReplayRefusedError(f"작업 모델 {job_model!r} 를 모른다")
    return set_id, model


def _plan(call: NovelCall, record: dict[str, Any], set_facts: dict[str, Any]) -> dict[str, Any]:
    system_sha, prompt_sha = _sha256(call.system_instruction), _sha256(call.prompt)
    return {
        "kind": "plan",
        "at": datetime.now(UTC).isoformat(),
        "line": call.line,
        "jobId": call.job_id,
        "branch": record.get("branch"),
        "channel": call.channel,
        "callSite": call.call_site,
        "variant": call.variant,
        "arm": call.arm,
        "jobModel": record.get("jobModel"),
        "chainModel": call.chain_model,
        "callModel": call.sent_model(),
        "dumpCallModel": record.get("callModel"),
        **set_facts,
        "systemSha256": system_sha,
        "promptSha256": prompt_sha,
        "dumpSystemSha256": record.get("systemSha256"),
        "dumpPromptSha256": record.get("promptSha256"),
        "matchesDump": (system_sha, prompt_sha) == (record.get("systemSha256"), record.get("promptSha256")),
        "costCeilingUsd": round(call.cost_ceiling_usd(), 6),
    }


async def assemble_line(
    sets: _SetReader, line: int, record: dict[str, Any], arm: ArmSpec | None
) -> tuple[list[dict[str, Any]], list[NovelCall], bool]:
    """덤프 한 줄의 plan 기록들, 부를 호출들, 통과 여부. 현행 갈래가 덤프와 같을 때(렌더 바이트와 보낼 모델 id 둘 다)만 변형 갈래를
    만든다 — 다르면 슬롯 값과 세트 id 가 그 호출을 정한다는 전제나 대조군의 모델이 깨진 것이라 변형 갈래와 비교할 수 없다."""
    head = {"kind": "plan", "line": line, "jobId": record.get("jobId"), "channel": record.get("channel")}
    try:
        set_id, job_model = _check_record(record)
        window_set = await sets.by_id(set_id)
        window = _render_call(window_set, record, line=line, variant="window", arm="window", chain_model=job_model)
    except (ReplayRefusedError, PromptRenderError) as refused:
        return (
            [{**head, "arm": "window", "variant": "window", "matchesDump": False, "refused": str(refused)}],
            [],
            False,
        )
    window_plan = _plan(window, record, await sets.facts(window_set))
    window_plan["callModelMatchesDump"] = window_plan["callModel"] == window_plan["dumpCallModel"]
    if not (window_plan["matchesDump"] and window_plan["callModelMatchesDump"]):
        return [window_plan], [], False
    if arm is None:
        return [window_plan], [window], True
    try:
        if arm.variant == "model":
            assert arm.model is not None
            chosen, chain_model = window_set, arm.model
        else:
            if arm.set_draft:
                assert arm.model is not None
                chosen = await sets.draft(arm.model)
            else:
                assert arm.set_id is not None
                chosen = await sets.by_id(arm.set_id)
            parsed = parse_chat_model_id(chosen.prompt_set.model)
            if parsed is None:
                raise ReplayRefusedError(
                    f"세트 {chosen.prompt_set.id} 의 모델 {chosen.prompt_set.model} 은 글쓰기 모델이 아니다"
                )
            chain_model = parsed
        variant = _render_call(chosen, record, line=line, variant=arm.variant, arm=arm.arm, chain_model=chain_model)
    except (ReplayRefusedError, PromptRenderError) as refused:
        arm_head = {**head, "arm": arm.arm, "variant": arm.variant, "matchesDump": False, "refused": str(refused)}
        return [window_plan, arm_head], [], False
    return [window_plan, _plan(variant, record, await sets.facts(chosen))], [window, variant], True


async def _call(
    client: LLMClient, sent: list[SentCall], item: NovelCall, rep: int, budget: CallBudget
) -> dict[str, Any]:
    sent.clear()
    started = time.perf_counter()
    usage = LLMCallContext(call_site=item.call_site, user_id=None, room_id=None, model=item.chain_model)
    chunks: list[str] = []
    error: str | None = None
    try:
        if item.schema is None:
            async for delta in client.generate(item.prompt, item.system_instruction, usage=usage):
                chunks.append(delta)
        else:
            result = await client.generate_structured_with_instruction(
                item.prompt, item.schema, system_instruction=item.system_instruction, usage=usage
            )
            chunks.append(result.model_dump_json())
    except Exception as exc:  # 기록하고 다음 호출로 — 실패(정책 차단·스키마 위반 등)도 결과다
        error = f"{type(exc).__name__}: {str(exc)[:500]}"
    last = sent[-1] if sent else None
    tokens = _tokens(last.usage_metadata) if last is not None else None
    sent_model = last.model if last is not None else None
    output = "".join(chunks)
    record: dict[str, Any] = {
        "kind": "call",
        "at": datetime.now(UTC).isoformat(),
        "line": item.line,
        "jobId": item.job_id,
        "channel": item.channel,
        "variant": item.variant,
        "arm": item.arm,
        "rep": rep,
        "callSite": last.call_site if last is not None else item.call_site,
        "chainModel": item.chain_model,
        "sentModel": sent_model,
        "tokens": tokens,
        "costUsd": _cost(sent_model, tokens),
        "costCeilingUsd": item.cost_ceiling_usd(),
        "latencyMs": round((time.perf_counter() - started) * 1000, 1),
        "promptSha256": _sha256(item.prompt),
        "outputChars": len(output),
        "outputSha256": _sha256(output),
        "output": output,
        "error": error,
    }
    budget.charge(record)
    record["cumulativeChargedUsd"] = round(budget.spent_usd, 6)
    return record


def _taken_calls(ledger: Path, keys: set[tuple[str, str, int]]) -> list[tuple[str, str, int]]:
    """원장에 이미 있는, 이번에 부를 (작업, 갈래, 반복) 호출. 갈래끼리는 (작업, 반복)으로 짝을 지으므로 같은 칸에 둘이 있으면
    어느 것과 짝지을지 정해지지 않는다."""
    return [
        (r["jobId"], r["arm"], r["rep"])
        for r in _read_jsonl(ledger)
        if r.get("kind") == "call" and (r.get("jobId"), r.get("arm"), r.get("rep")) in keys
    ]


async def run(
    args: argparse.Namespace, db: AsyncSession, *, client_factory: Callable[[], LLMClient] = get_llm_client
) -> int:
    """`run` 하위 명령 본체. 세션은 부른 쪽이 연 것을 받고 읽기만 한다. LLM 클라이언트는 실제로 부를 때만 만든다."""
    dump, ledger = Path(args.dump), Path(args.ledger)
    if not dump.is_file():  # noqa: ASYNC240 — 한 번 쓰는 CLI
        print(f"파일이 없다: --dump {dump}")
        return 1
    ledger.parent.mkdir(parents=True, exist_ok=True)
    arm: ArmSpec | None = args.arm_spec
    lines = target_lines(dump, tuple(args.channel or TARGET_CHANNELS))
    calling = [name for name in ("window", arm.arm if arm else None) if name is not None]
    if args.skip_window_calls:
        calling.remove("window")
    keys = {(str(r.get("jobId")), name, rep) for _, r in lines for name in calling for rep in range(args.reps)}
    taken = _taken_calls(ledger, keys)
    if taken:
        print(f"원장에 같은 (작업, 갈래, 반복) 호출이 이미 있다 — 다시 부르면 한 칸에 출력이 둘이 된다: {taken[:5]}")
        return 2

    sets = _SetReader(db)
    calls: list[NovelCall] = []
    failed: list[int] = []
    for number, record in lines:
        plans, items, passed = await assemble_line(sets, number, record, arm)
        for plan in plans:
            _append(ledger, {**plan, "execute": args.execute, "reps": args.reps})
            shown = ("line", "channel", "arm", "matchesDump", "callModelMatchesDump", "setSemver", "refused")
            summary = {k: plan.get(k) for k in shown}
            print(json.dumps(summary, ensure_ascii=False))
        if not passed:
            failed.append(number)
            continue
        calls.extend(item for item in items if item.arm in calling)
    if failed and args.stop_on_mismatch:
        print(f"재렌더·모델이 덤프와 다르거나 거부된 줄 {failed} — --stop-on-mismatch 라 아무것도 부르지 않는다")
        return 2
    spent = sum_ledger([ledger]).charged_usd if ledger.is_file() else 0.0  # noqa: ASYNC240 — 한 번 쓰는 CLI
    planned = min(len(calls) * args.reps, args.limit_calls)
    worst = sum(item.cost_ceiling_usd() for item in calls) * args.reps
    print(
        json.dumps(
            {
                "lines": len(lines),
                "failedLines": failed,
                "plannedCalls": planned,
                "worstUsd": round(worst, 6),
                "ledgerChargedUsd": round(spent, 6),
            },
            ensure_ascii=False,
        )
    )
    if spent + worst > args.limit_usd:
        print(
            f"경고: 원장 누적 ${spent:.4f} 에 최악 견적 ${worst:.4f} 를 더하면 원가 상한 ${args.limit_usd} 를 넘는다"
            " — 실행하면 상한 앞에서 멈춘다"
        )
    code = 2 if failed else 0
    if not args.execute:
        print("시험 실행 — LLM 을 부르지 않았다(--execute 로 실행)")
        return code
    if spent >= args.limit_usd:
        print(f"원장 누적 ${spent:.4f} 가 이미 상한 ${args.limit_usd} 이상이다 — 부르지 않는다")
        return 3
    client = client_factory()
    budget = CallBudget(args.limit_calls, usd_limit=args.limit_usd, spent_usd=spent)
    with capture_usage() as sent:
        for _line, group in groupby(calls, key=lambda item: item.line):
            items = list(group)
            for rep in range(args.reps):
                for item in items:
                    ceiling = item.cost_ceiling_usd()
                    if budget.spent_usd + ceiling > args.limit_usd or not budget.take():
                        exhausted = {
                            **budget.exhausted(),
                            "line": item.line,
                            "jobId": item.job_id,
                            "arm": item.arm,
                            "costCeilingUsd": round(ceiling, 6),
                        }
                        _append(ledger, {**exhausted, "rep": rep})
                        print(json.dumps({"calls": budget.used, "cumulativeChargedUsd": round(budget.spent_usd, 6)}))
                        return code
                    _append(ledger, await _call(client, sent, item, rep, budget))
    print(json.dumps({"calls": budget.used, "cumulativeChargedUsd": round(budget.spent_usd, 6)}))
    return code


def report(args: argparse.Namespace) -> int:
    """`report` 하위 명령 — 원장의 호출 출력에서 갈래·채널별 기계 지표를 센다. 출력 본문과 표지 글자는 싣지 않는다."""
    paths = ledger_paths(args.ledger)
    dump = Path(args.dump)
    if not paths or not dump.is_file():
        print(f"원장({args.ledger}) 이나 덤프({args.dump}) 가 없다")
        return 1
    rows = metrics.summarize(metrics.load_calls(paths, dump), args.marker)
    if args.format == "json":
        text = json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
    else:
        text = metrics.render_markdown(rows, markers=len(args.marker))
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


async def _main(args: argparse.Namespace) -> int:
    # 전역 엔진은 쓰지 않는다 — 처음 쓴 이벤트 루프에 묶이는 풀이라, 실행마다 새 루프를 여는 도구는 연결을 남기지 않는 엔진을
    # 따로 연다. 이 세션은 읽기만 하고 끝에 되돌린다.
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with AsyncSession(engine) as db:
            try:
                return await run(args, db)
            finally:
                await db.rollback()
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    # 운영 DB 거부를 무엇보다 먼저 건다 — 인자 검사 전이라도 DB 가 로컬이 아니면 이 도구를 쓸 일이 없다.
    ensure_local_database(settings.database_url, tool="novel_replay.py")
    args = parse_args(argv)
    if args.command == "report":
        return report(args)
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
