"""판정기 일치율 — 측정 서버 덤프의 판정 줄(`kind: "judgment"`)을 같은 프롬프트·같은 응답 스키마로 판정 모델마다 여러 번 다시
보내 결과가 얼마나 같은지 잰다. 합격 판정은 후보 판정기(기본 Haiku) 하나로 한다: 호출 위치마다 자기 반복 일치율, 재시도 뒤 구조화
실패, 카운트다운 층마다 기대 방향의 감소 비율, 망친 입력 대조군 반응률. 다른 모델(예: Gemini)을 함께 부르면 후보와의 교차 일치율을
참고로 내지만 판정에 쓰지 않는다.

자기 반복 일치율은 아무 일도 없는 줄(스탯 빈 집합·엔딩 거짓·그림 없음)이 대부분이면 판정기가 무엇이든 높게 나온다. 그래서 어느
모델이든 한 번이라도 발동한 줄만으로 다시 계산한 값을 함께 내고 둘 다 하한을 넘어야 합격이며, 발동한 줄이 정한 수보다 적으면
판정을 미룬다. 가장 잦은 결과가 어떻게 퍼졌는지(빈 스탯 집합·엔딩 참·그림 선택의 비율)도 같이 적는다.

호출은 앱의 공급자 구현(`GeminiLLMClient`·`AnthropicLLMClient`)을 그대로 거친다 — 모델 고르기(판정 종류의 모델 설정), Haiku 의
사고 끔·구조화 깊이, 타임아웃, 출력 상한, 실패 정규화가 운영 판정과 같아야 측정한 것이 운영 판정기다. 그래서 모델마다 앱 설정
몇 칸만 호출 동안 덮어쓰고(Gemini 는 판정 종류별 Gemini 모델명, Haiku 는 판정 종류별 판정 모델) 나머지는 앱 기본값·실행 env 를
따른다. 측정 호출이 로컬 사용량 집계(Redis)에 섞이지 않게 실제 실행에서는 그 기록만 끈다.

일치의 단위(정규화한 결과가 같으면 일치):
- 스탯: 발동한 규칙 id 들의 집합. 프롬프트에 없던 규칙 id 는 앱이 적용하지 않으니 지운다.
- 엔딩: `triggered` 참·거짓(엔딩마다 판정 줄이 따로라 줄 하나가 엔딩 하나다).
- 그림: 고른 id. 프롬프트에 없는 id 는 앱이 후보 밖으로 버리므로 "고르지 않음"과 같게 친다.

자기 반복 일치율 = 줄마다 같은 모델의 성공 결과 쌍 중 같은 쌍의 비율을 줄에 대해 평균. 교차 일치율 = 줄마다 두 모델 결과를 하나씩
짝지은 모든 쌍 중 같은 쌍의 비율을 평균. 두 값이 같은 쌍 단위라 서로 견줄 수 있다.

대조군 반응 = 망친 입력이 노린 방향으로 최빈 결과가 바뀐 것만 — 스탯은 카운트다운 규칙 id 가 새로 듦, 엔딩은 거짓에서 참, 그림은
고르지 않음에서 고름. 원래 줄이 이미 그 상태면 잴 수 없어 반응률에서 빼고, 반대 방향 변화(그 상태에서 벗어남)는 따로 센다.

구조화 실패 = 앱과 같이 한 번 더 불러도 쓸 만한 판정이 없는 경우(스키마 해석 불가·출력 상한 도달·정책 거절이나 차단).
첫 시도의 구조화 실패 수는 따로 낸다. 전송 오류·시간 초과·429 는 판정기의 품질이 아니라 따로 세고, 다시 실행하면 그 호출만
다시 부른다."""

import contextlib
import dataclasses
import hashlib
import json
import math
import random
import re
from collections import Counter
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import combinations, product
from pathlib import Path
from typing import Any, Literal, TypeVar, cast

from pydantic import BaseModel

from api.chat.prompt_builder import EndingJudgmentResult, ImageMatchJudgmentResult, StatRuleJudgmentResult
from api.core.config import settings
from api.llm.client import (
    CallUsage,
    LLMCallContext,
    LLMCallSite,
    LLMClient,
    LLMClientError,
    LLMPolicyViolationError,
    is_retryable_judgment_failure,
)

from memory_eval.judge_sample import branch_dump_name
from memory_eval.ledger import Ledger, cost_usd

T = TypeVar("T", bound=BaseModel)
JudgmentKind = Literal["stat", "ending", "image"]
FakeAnswer = Callable[[str, str, str], Mapping[str, Any] | Exception]

# 범위의 호출 위치 → 판정 종류. 미리보기 판정은 운영 사용자 대화가 아니라 넣지 않는다.
CALL_SITE_KINDS: dict[str, JudgmentKind] = {
    "chat_stat_judgment": "stat",
    "chat_ending_judgment": "ending",
    "chat_situational_image": "image",
    "chat_media_book_image": "image",
}
SCHEMAS: dict[str, type[BaseModel]] = {
    "StatRuleJudgmentResult": StatRuleJudgmentResult,
    "EndingJudgmentResult": EndingJudgmentResult,
    "ImageMatchJudgmentResult": ImageMatchJudgmentResult,
}
KIND_SCHEMA: dict[JudgmentKind, str] = {
    "stat": "StatRuleJudgmentResult",
    "ending": "EndingJudgmentResult",
    "image": "ImageMatchJudgmentResult",
}

COUNTDOWN_STAT = "상영회까지"
_USAGE_HOOK = "record_usage"
# 사전 등록 합격선의 기본값(실행 인자로 바꿀 수 있다). 근거는 표본 크기다 — 호출 위치마다 줄 수십 개 × 반복 5회라 줄 하나의
# 흔들림이 일치율을 몇 %p 씩 움직인다.
DEFAULT_MIN_SELF_AGREEMENT = 0.90
DEFAULT_MIN_FIRED_LINES = 5
DEFAULT_MAX_QUIET_DECREMENT = 0.10
DEFAULT_MIN_DECREMENT = 0.80
DEFAULT_MIN_CONTROL_REACTION = 0.80
# 견적의 자리값. 호출당 토큰은 `--limit 1` 실측(요약의 `measuredTokensPerChar`)으로 바꾼다.
DEFAULT_TOKENS_PER_CHAR = 1.0
DEFAULT_OUTPUT_TOKENS = 60

Status = Literal["ok", "structured_failure", "call_error"]

_RULE_LINE = re.compile(r"^- ([a-z]+\d+): ")
_STAT_HEADER = re.compile(r"^(.+?) / 범위 \[")


@dataclass(frozen=True)
class JudgmentLine:
    line_id: str
    room_id: str | None
    turn: int
    call_site: str
    schema: str
    prompt: str
    # 망친 입력 대조군이면 그 이름과 원래 줄 id. 대조군 줄은 일치율 집계에 넣지 않는다.
    control: str | None = None
    base_id: str | None = None
    # 같은 (방, 턴, 호출 위치, 프롬프트) 줄이 덤프에 더 있던 수. 측정 서버는 다시 부른 판정을 시도마다 한 줄씩 남긴다.
    duplicates: int = 0
    # 덤프를 만든 서버가 이 판정에 실제로 보낸 모델 id. 재판정 모델과 다르면 이 프롬프트는 그 모델의 판정 문안으로 조립됐을
    # 수 있다(판정 문안은 판정 모델마다 활성 세트를 따로 읽는다).
    dump_model: str | None = None

    @property
    def kind(self) -> JudgmentKind:
        return CALL_SITE_KINDS[self.call_site]

    @property
    def prompt_sha(self) -> str:
        return hashlib.sha256(self.prompt.encode("utf-8")).hexdigest()


def load_lines(
    paths: Sequence[Path], *, call_sites: set[str] | None = None, name: Callable[[Path], str] | None = None
) -> list[JudgmentLine]:
    """덤프 파일들에서 범위 안 판정 줄만 읽는다. 줄 id 는 `<파일 이름>:<파일 안 줄 번호>` 라 다시 실행해도 같다(덤프는 이어
    쓰기만 한다). 파일 이름이 서로 같은 덤프 묶음(프로브마다 같은 이름)은 `name` 으로 줄 id 의 파일 부분을 따로 정한다. 지시문을 따로 실은 판정 줄이나 호출 위치와 다른 스키마는 거부한다 — 이 도구는 운영 판정과 같은 호출(지시문
    없는 구조화)만 다시 보낸다.

    같은 (방, 턴, 호출 위치, 프롬프트) 줄은 처음 줄 하나로 합친다. 측정 서버는 판정을 부르기 전에 덤프하므로 다시 부른 판정
    (재생성의 스탯 재판정)이 시도마다 한 줄이고, 합치지 않으면 같은 입력이 표본에 두 번 든다."""
    names = [p.name if name is None else name(p) for p in paths]
    if len(set(names)) != len(names):
        raise SystemExit(f"덤프 파일 이름이 겹친다(줄 id 가 겹친다): {names}")
    lines: dict[tuple[str | None, int, str, str], JudgmentLine] = {}
    for path, file_name in zip(paths, names, strict=True):
        for index, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw.strip():
                continue
            record = json.loads(raw)
            if record.get("kind") != "judgment":
                continue
            call_site = str(record["callSite"])
            if call_site not in CALL_SITE_KINDS or (call_sites is not None and call_site not in call_sites):
                continue
            line_id = f"{file_name}:{index}"
            if "systemInstruction" in record:
                raise SystemExit(f"{line_id}: 지시문을 따로 실은 판정 줄은 다시 보내지 않는다")
            schema = str(record["schema"])
            if schema != KIND_SCHEMA[CALL_SITE_KINDS[call_site]]:
                raise SystemExit(f"{line_id}: {call_site} 의 스키마가 {schema} 다")
            line = JudgmentLine(
                line_id=line_id,
                room_id=record.get("roomId"),
                turn=int(record["turn"]),
                call_site=call_site,
                schema=schema,
                prompt=str(record["prompt"]),
                dump_model=record.get("model"),
            )
            key = (line.room_id, line.turn, line.call_site, line.prompt_sha)
            seen = lines.get(key)
            lines[key] = line if seen is None else dataclasses.replace(seen, duplicates=seen.duplicates + 1)
    return list(lines.values())


def dump_models(lines: Sequence[JudgmentLine]) -> dict[str, dict[str, int]]:
    """호출 위치마다 덤프 줄의 판정 모델 id 분포(대조군 줄은 원래 줄과 같아 뺀다)."""
    out: dict[str, Counter[str]] = {}
    for line in lines:
        if line.control is None:
            out.setdefault(line.call_site, Counter())[str(line.dump_model)] += 1
    return {site: dict(sorted(counter.items())) for site, counter in sorted(out.items())}


def _dump_file(line_id: str) -> str:
    return line_id.rsplit(":", 1)[0]


def _control_matches(lines: Sequence[JudgmentLine], name: str, base: Mapping[str, Any]) -> list[JudgmentLine]:
    """원래 줄 찾기. `lineId`(`<덤프 파일 이름>:<줄 번호>`)는 그 줄 하나, `branch` + `callSite` 는 엔딩 갈래 덤프 파일의 그 호출
    위치 줄, 방·턴·호출 위치는 한 덤프 파일 안에서만 — 같은 방·같은 턴이 여러 덤프에 있으면(엔딩 갈래) `--dumps` 순서가 원래
    줄을 정하게 되므로 거부한다."""
    if "lineId" in base:
        return [line for line in lines if line.line_id == base["lineId"]]
    if "branch" in base:
        file = branch_dump_name(str(base["branch"]))
        return [line for line in lines if _dump_file(line.line_id) == file and line.call_site == base["callSite"]]
    matches = [
        line
        for line in lines
        if line.room_id == base["roomId"] and line.turn == int(base["turn"]) and line.call_site == base["callSite"]
    ]
    files = sorted({_dump_file(line.line_id) for line in matches})
    if len(files) > 1:
        raise SystemExit(f"대조군 {name}: 방·턴이 같은 줄이 여러 덤프에 있다({files}) — lineId 나 branch 로 집는다")
    return matches


def control_lines(lines: Sequence[JudgmentLine], spec: Sequence[Mapping[str, Any]]) -> list[JudgmentLine]:
    """망친 입력 대조군. 항목마다 원래 줄(`_control_matches`, 같은 자리에 여럿이면 순번 `nth`)을 찾아 글자 바꾸기를 적용한 새 줄을
    만든다. 바꿀 글자가 프롬프트에 정확히 한 번 있어야 한다 — 없거나 여럿이면 어느 자리를 망쳤는지 모르는 대조군이 된다."""
    out: list[JudgmentLine] = []
    for item in spec:
        name = str(item["id"])
        base = item["base"]
        matches = _control_matches(lines, name, base)
        nth = int(base.get("nth", 0))
        if nth >= len(matches):
            raise SystemExit(f"대조군 {name}: 원래 줄이 없다({base})")
        source = matches[nth]
        prompt = source.prompt
        for old, new in item["replace"]:
            count = prompt.count(old)
            if count != 1:
                raise SystemExit(f"대조군 {name}: 바꿀 글자가 프롬프트에 {count}번 있다(정확히 한 번이어야 한다)")
            prompt = prompt.replace(old, new)
        out.append(
            JudgmentLine(
                line_id=f"control:{name}",
                room_id=source.room_id,
                turn=source.turn,
                call_site=source.call_site,
                schema=source.schema,
                prompt=prompt,
                control=name,
                base_id=source.line_id,
            )
        )
    return out


# ---------------------------------------------------------------- 정규화


def prompt_rule_ids(prompt: str) -> set[str]:
    return {m.group(1) for line in prompt.splitlines() if (m := _RULE_LINE.match(line))}


def stat_rule_ids(prompt: str, stat_name: str) -> set[str]:
    """그 스탯 줄(`이름 / 범위 [...] / 설명`) 바로 아래 규칙 줄의 id. 스탯 블록은 빈 줄이나 다른 줄에서 끝난다."""
    found: set[str] = set()
    current: str | None = None
    for line in prompt.splitlines():
        header = _STAT_HEADER.match(line)
        if header:
            current = header.group(1)
            continue
        rule = _RULE_LINE.match(line)
        if rule and current is not None:
            if current == stat_name:
                found.add(rule.group(1))
            continue
        current = None
    return found


def normalize(line: JudgmentLine, parsed: BaseModel) -> Any:
    """일치를 따질 결과 값(JSON 으로 남길 수 있는 꼴)."""
    if isinstance(parsed, StatRuleJudgmentResult):
        return sorted(set(parsed.fired_rule_ids) & prompt_rule_ids(line.prompt))
    if isinstance(parsed, EndingJudgmentResult):
        return parsed.triggered
    if isinstance(parsed, ImageMatchJudgmentResult):
        chosen = parsed.matched_image_entity_id
        return chosen if chosen and chosen in line.prompt else None
    raise TypeError(f"모르는 판정 결과: {type(parsed).__name__}")


# ---------------------------------------------------------------- 판정 모델


@dataclass(frozen=True)
class JudgeModel:
    label: str
    model_id: str
    client: LLMClient
    # 호출 동안 덮어쓸 앱 설정.
    overrides: Mapping[str, Any] = field(default_factory=dict)
    # 판정 줄의 응답 스키마 대신 보낼 스키마(같은 판정기를 스키마만 바꿔 견줄 때). 판정 줄 스키마의 하위 클래스여야 정규화가 같다.
    response_schema: type[BaseModel] | None = None


@contextlib.contextmanager
def setting_overrides(overrides: Mapping[str, Any]) -> Iterator[None]:
    missing = [name for name in overrides if not hasattr(settings, name)]
    if missing:
        raise SystemExit(f"이 코드에 없는 설정: {missing}")
    saved = {name: getattr(settings, name) for name in overrides}
    try:
        for name, value in overrides.items():
            setattr(settings, name, value)
        yield
    finally:
        for name, value in saved.items():
            setattr(settings, name, value)


def gemini_overrides(model_name: str) -> dict[str, Any]:
    return {
        "stat_judgment_model": "gemini",
        "ending_judgment_model": "gemini",
        "image_judgment_model": "gemini",
        "gemini_stat_judgment_model_name": model_name,
        "gemini_ending_judgment_model_name": model_name,
        "gemini_image_judgment_model_name": model_name,
    }


def haiku_overrides() -> dict[str, Any]:
    return {"stat_judgment_model": "haiku", "ending_judgment_model": "haiku", "image_judgment_model": "haiku"}


@contextlib.contextmanager
def without_usage_store() -> Iterator[None]:
    """공급자 구현의 로컬 사용량 기록(Redis)을 이 측정 동안만 끈다. 원가는 원장이 따로 남긴다."""
    from api.llm import anthropic_api, gemini

    async def _skip(*_args: Any, **_kwargs: Any) -> None:
        return None

    # 두 모듈이 `from ... import record_usage` 로 이름을 붙잡아 두어 모듈 속성을 바꾼다(타입 검사가 재수출하지 않은 이름이라
    # 이름을 문자열로 다룬다).
    modules = (gemini, anthropic_api)
    saved = [getattr(module, _USAGE_HOOK) for module in modules]
    for module in modules:
        setattr(module, _USAGE_HOOK, _skip)
    try:
        yield
    finally:
        for module, original in zip(modules, saved, strict=True):
            setattr(module, _USAGE_HOOK, original)


def real_models(labels: Sequence[str], *, gemini_model: str) -> list[JudgeModel]:
    """실제 공급자 구현. Haiku 는 앱의 Anthropic 직결 구현이고 실제 id 는 앱 설정의 Haiku id 다 — 사고 끔과 구조화 깊이는
    그 구현이 모델 id 와 앱 설정(`anthropic_structured_effort`)으로 정한다."""
    from api.llm.anthropic_api import AnthropicLLMClient
    from api.llm.gemini import GeminiLLMClient

    models: list[JudgeModel] = []
    for label in labels:
        if label == "gemini":
            models.append(
                JudgeModel(
                    label="gemini",
                    model_id=gemini_model,
                    client=GeminiLLMClient(),
                    overrides=gemini_overrides(gemini_model),
                )
            )
        elif label == "haiku":
            models.append(
                JudgeModel(
                    label="haiku",
                    model_id=settings.anthropic_haiku_model_id,
                    client=AnthropicLLMClient(),
                    overrides=haiku_overrides(),
                )
            )
        else:
            raise SystemExit(f"모르는 판정 모델: {label} (gemini·haiku)")
    return models


# ---------------------------------------------------------------- 견적·호출


def parse_tokens_per_char(raw: str | None) -> dict[str, float]:
    """`1.0` 이면 모든 모델, `gemini=0.7,haiku=1.1` 이면 모델마다. 빠진 모델은 기본 자리값."""
    if raw is None or not raw.strip():
        return {}
    if "=" not in raw:
        return {"*": float(raw)}
    return {key.strip(): float(value) for key, value in (part.split("=") for part in raw.split(",") if part.strip())}


def _tpc(rates: Mapping[str, float], label: str) -> float:
    return rates.get(label, rates.get("*", DEFAULT_TOKENS_PER_CHAR))


def call_estimate_usd(
    line: JudgmentLine, model: JudgeModel, *, rates: Mapping[str, float], output_tokens: int
) -> float:
    return cost_usd(
        model.model_id,
        input_tokens=math.ceil(len(line.prompt) * _tpc(rates, model.label)),
        cached_tokens=0,
        cache_write_tokens=0,
        output_tokens=output_tokens,
        thoughts_tokens=0,
    )


def estimate(
    lines: Sequence[JudgmentLine],
    models: Sequence[JudgeModel],
    reps: int,
    *,
    rates: Mapping[str, float],
    output_tokens: int,
) -> dict[str, Any]:
    """호출 수 = 줄 수 × 반복 수 × 모델 수. 원가 = 모델마다 Σ(프롬프트 글자 × 글자당 토큰) × 반복 + 출력 자리값."""
    per_model: dict[str, Any] = {}
    total = 0.0
    for model in models:
        usd = sum(call_estimate_usd(line, model, rates=rates, output_tokens=output_tokens) for line in lines) * reps
        per_model[model.label] = {
            "modelId": model.model_id,
            "calls": len(lines) * reps,
            "tokensPerChar": _tpc(rates, model.label),
            "usd": usd,
        }
        total += usd
    by_site = Counter(line.call_site for line in lines)
    return {
        "lines": len(lines),
        "linesByCallSite": dict(sorted(by_site.items())),
        "controls": sum(1 for line in lines if line.control is not None),
        "reps": reps,
        "calls": len(lines) * reps * len(models),
        "promptChars": sum(len(line.prompt) for line in lines),
        "outputTokensPerCall": output_tokens,
        "perModel": per_model,
        "totalUsd": total,
    }


def _status(exc: LLMClientError) -> Status:
    if isinstance(exc, LLMPolicyViolationError):
        return "structured_failure"
    # 원인 없는 기본 타입 = 응답을 받았지만 스키마로 읽히지 않았다(출력 상한에서 끝난 응답 포함).
    if exc.__cause__ is None and type(exc) is LLMClientError:
        return "structured_failure"
    return "call_error"


def read_calls(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(raw) for raw in path.read_text(encoding="utf-8").splitlines() if raw.strip()]


def check_prompt_shas(lines: Sequence[JudgmentLine], rows: Sequence[Mapping[str, Any]]) -> None:
    """결과 줄의 프롬프트 sha 가 지금 읽은 줄의 sha 와 같은지 본다. 줄 id 는 덤프 파일 이름과 줄 번호라, 덤프를 같은 이름으로
    다시 만들면 다른 프롬프트의 옛 결과가 같은 키로 읽힌다 — 하나라도 다르거나 sha 가 없으면 멈춘다."""
    shas = {line.line_id: line.prompt_sha for line in lines}
    stale = sorted(
        {
            str(row["key"])
            for row in rows
            if str(row["lineId"]) in shas and row.get("promptSha") != shas[str(row["lineId"])]
        }
    )
    if stale:
        raise SystemExit(
            f"결과 파일에 지금 덤프와 프롬프트가 다른 호출 결과가 {len(stale)}건 있다(첫 키 {stale[0]}) — 결과 폴더를 따로 쓴다"
        )


def latest_calls(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """같은 호출 키가 여럿이면(전송 오류 뒤 다시 실행) 마지막 줄."""
    latest: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        latest[str(row["key"])] = row
    return latest


async def run_calls(
    lines: Sequence[JudgmentLine],
    models: Sequence[JudgeModel],
    reps: int,
    *,
    ledger: Ledger,
    calls_path: Path,
    stage: str,
    rates: Mapping[str, float],
    output_tokens: int,
    order_seed: int | None = None,
) -> int:
    """아직 결과가 없는 (줄, 모델, 반복) 호출을 하나씩 차례로(동시에 부르지 않고) 부른다. 전송 오류로 끝난 호출만 다시 부른다.
    호출마다 원장 여유를 먼저 보고(넘을 것 같으면 `BudgetExceededError` 로 멈춘다), 끝나면 공급자가 보고한 토큰으로 원장에 한 줄,
    결과 파일에 한 줄.

    순서는 `order_seed` 가 없으면 줄 → 모델 → 반복이다: 한 줄 안에서 한 모델(판)의 반복을 모두 부른 뒤 다음 모델로 넘어간다. 그래서
    가까운 시각에 부른 호출끼리 더 닮는 공급자 쪽 시간 상관이 있으면, 같은 모델의 반복끼리는 그 상관을 나눠 갖고 모델 사이 쌍은
    덜 나눠 가져 자기 반복 일치율과 모델 사이 일치율의 차이가 모델 차이로 읽힌다. `order_seed` 를 주면 (줄, 모델, 반복) 호출 키
    전체를 그 씨앗으로 한 번 섞어 부른다 — 시간 상관이 모든 쌍에 고르게 퍼진다. 같은 씨앗은 같은 순서다(이어 돌릴 때 이미 결과가
    있는 키는 섞은 순서에서 건너뛴다).

    첫 시도가 앱이 곧바로 다시 부르는 실패(`is_retryable_judgment_failure`)면 같은 호출 안에서 한 번 더 부르고, 결과 줄에는
    마지막 시도의 상태와 첫 시도의 상태(`firstStatus`)·시도 수를 남긴다. 그래서 구조화 실패는 다시 부른 뒤에도 실패한 것이다.
    앱에서 이 재시도는 재생성의 스탯 재판정에만 있고 보내기·수정의 판정은 다시 부르지 않는다 — 첫 시도 실패 수를 따로 내는
    이유다."""
    previous = read_calls(calls_path)
    check_prompt_shas(lines, previous)
    done = {key for key, row in latest_calls(previous).items() if row["status"] != "call_error"}
    calls_path.parent.mkdir(parents=True, exist_ok=True)
    made = 0
    plan = [(line, model, rep) for line in lines for model in models for rep in range(reps)]
    if order_seed is not None:
        random.Random(order_seed).shuffle(plan)
    for line, model, rep in plan:
        line_schema = SCHEMAS[line.schema]
        schema = model.response_schema or line_schema
        key = f"{line.line_id}|{model.label}|{rep}"
        if key in done:
            continue
        ledger.check_headroom(call_estimate_usd(line, model, rates=rates, output_tokens=output_tokens))
        sink: list[CallUsage] = []
        usage = LLMCallContext(call_site=cast(LLMCallSite, line.call_site), user_id=None, room_id=None, usage_sink=sink)
        status: Status = "ok"
        first_status: Status | None = None
        result: Any = None
        extra: dict[str, Any] = {}
        error: str | None = None
        attempts = 0
        with setting_overrides(model.overrides):
            while True:
                attempts += 1
                try:
                    parsed = await model.client.generate_structured(line.prompt, schema, usage=usage)
                    status, error = "ok", None
                    result = normalize(line, parsed)
                    # 바꿔 보낸 스키마가 더한 칸(판정 이유 등)은 일치를 따지지 않고 결과 옆에 남긴다.
                    extra = parsed.model_dump(exclude=set(line_schema.model_fields))
                except LLMClientError as exc:
                    status = _status(exc)
                    error = type(exc).__name__
                    # 앱의 판정 재시도와 같은 분류로 한 번만 다시 부른다(파싱 실패·5xx·시간 초과가 아닌 전송 오류).
                    if attempts == 1 and is_retryable_judgment_failure(exc):
                        first_status = status
                        continue
                break
        for call in sink:
            ledger.append(
                stage=stage,
                call_site=line.call_site,
                model=call.model,
                input_tokens=call.prompt_tokens or 0,
                cached_tokens=call.cached_tokens or 0,
                cache_write_tokens=call.cache_write_tokens or 0,
                output_tokens=call.output_tokens or 0,
                thoughts_tokens=call.thoughts_tokens or 0,
                note=f"judge-agreement {key}",
            )
        row = {
            "key": key,
            "lineId": line.line_id,
            "model": model.label,
            "modelId": sink[0].model if sink else model.model_id,
            "rep": rep,
            "promptSha": line.prompt_sha,
            "status": status,
            "error": error,
            "attempts": attempts,
            "firstStatus": first_status or status,
            "result": result,
            **({"extra": extra} if extra else {}),
            "promptChars": len(line.prompt),
            "inputTokens": sum(c.prompt_tokens or 0 for c in sink),
            "outputTokens": sum(c.output_tokens or 0 for c in sink),
            "thoughtsTokens": sum(c.thoughts_tokens or 0 for c in sink),
        }
        with calls_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        made += 1
    return made


# ---------------------------------------------------------------- 집계


def _key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def self_agreement(values: Sequence[Any]) -> float | None:
    pairs = list(combinations([_key(v) for v in values], 2))
    if not pairs:
        return None
    return sum(a == b for a, b in pairs) / len(pairs)


def cross_agreement(left: Sequence[Any], right: Sequence[Any]) -> float | None:
    if not left or not right:
        return None
    lk, rk = [_key(v) for v in left], [_key(v) for v in right]
    return sum(a == b for a in lk for b in rk) / (len(lk) * len(rk))


def _mean(values: Sequence[float | None]) -> tuple[float | None, int]:
    kept = [v for v in values if v is not None]
    return (sum(kept) / len(kept) if kept else None), len(kept)


def _modal(values: Sequence[Any]) -> str | None:
    if not values:
        return None
    return Counter(_key(v) for v in values).most_common(1)[0][0]


def fired(kind: JudgmentKind, value: Any) -> bool:
    """판정 결과가 무엇을 일으켰나 — 스탯은 규칙이 하나라도, 엔딩은 참이면, 그림은 id 를 골랐으면 일으킨 것이다."""
    if kind == "stat":
        return bool(value)
    if kind == "ending":
        return value is True
    return value is not None


# 호출 위치마다 최빈 결과 분포의 이름 — 스탯은 빈 집합 비율, 엔딩은 참 비율, 그림은 고른 비율.
_MODAL_RATE: dict[JudgmentKind, str] = {"stat": "emptyRate", "ending": "trueRate", "image": "chosenRate"}


def modal_distribution(kind: JudgmentKind, per_line: Sequence[Sequence[Any]]) -> dict[str, Any]:
    """결과가 하나라도 있는 줄마다 최빈 결과를 고르고, 그것이 스탯 빈 집합·엔딩 참·그림 고름인 줄의 비율. 일치율이 높아도 이
    비율이 한쪽으로 쏠려 있으면 그 일치율은 대부분 "아무 일도 없음"끼리 맞은 것이다."""
    modals = [json.loads(m) for values in per_line if (m := _modal(values)) is not None]
    if kind == "stat":
        hits = sum(1 for m in modals if not m)
    else:
        hits = sum(1 for m in modals if fired(kind, m))
    return {"lines": len(modals), _MODAL_RATE[kind]: hits / len(modals) if modals else None}


# ---------------------------------------------------------------- 다수결 (기존 반복 기록으로, 호출 없음)

MajorityVote = Literal["ruleSet", "appliedChange"]
MAJORITY_METRICS = ("ruleSet", "appliedChange", "direction", "fired")
DEFAULT_MAJORITY_VOTES = 3
MAJORITY_BIAS_NOTE = (
    "plug-in 어림은 다수결 이득(majority - single)을 부풀린다: 참 분포가 반반이라 참 이득이 0 이어도 반복 3회 어림의 기대 이득은"
    " 약 +0.045(11/243)다. 문턱과 견주기 전에 이 편향을 깎아 읽는다."
)
_SHORT_RULE_ID = re.compile(r"^([a-z]+)(\d+)$")


def applied_change(rule_ids: Sequence[str], deltas: Mapping[str, float]) -> dict[str, float]:
    """발동 규칙 id 들을 앱이 값에 반영하는 변화로 — 스탯(짧은 id 의 글자 부분)마다 |폭| 이 가장 큰 규칙 하나, 같으면 작가
    순서(숫자 부분)가 앞선 것의 폭(`chat/stats.py` 의 `apply_rule_judgment_with_events` 와 같은 고르기). 시작 값이 판정 줄에
    없어 최소·최대로 자르지는 않는다. 폭 표에 없는 id 는 멈춘다 — 빼면 변화량이 조용히 달라진다."""
    best: dict[str, tuple[float, int]] = {}
    for rule_id in rule_ids:
        match = _SHORT_RULE_ID.match(rule_id)
        if match is None or rule_id not in deltas:
            raise SystemExit(f"규칙 id {rule_id!r} 의 폭이 폭 표에 없다")
        stat, order = match.group(1), int(match.group(2))
        delta = float(deltas[rule_id])
        seen = best.get(stat)
        if seen is None or (abs(delta), -order) > (abs(seen[0]), -seen[1]):
            best[stat] = (delta, order)
    return {stat: _plain(delta) for stat, (delta, _order) in sorted(best.items())}


def _plain(number: float) -> float:
    return int(number) if float(number).is_integer() else number


def _sign(number: float) -> int:
    return (number > 0) - (number < 0)


def _majority_distribution(probabilities: Mapping[str, float], k: int) -> dict[str, float]:
    """결과 분포 `probabilities` 에서 독립으로 `k` 표를 뽑았을 때 최빈 결과의 분포. 최빈이 여럿이면 그중 먼저 뽑힌 것(뽑는 순서가
    무작위라 동률 결과 중 하나를 고르게 고르는 것과 같다)."""
    outcomes = list(probabilities)
    out: dict[str, float] = dict.fromkeys(outcomes, 0.0)
    for draw in product(range(len(outcomes)), repeat=k):
        weight = math.prod(probabilities[outcomes[i]] for i in draw)
        counts = Counter(draw)
        top = max(counts.values())
        winner = next(i for i in draw if counts[i] == top)
        out[outcomes[winner]] += weight
    return out


def _agreement(distribution: Mapping[str, float], project: Callable[[Any], Any]) -> float:
    """두 독립 판정이 투영한 값에서 같을 확률 — 투영 값마다 확률을 모아 제곱해 더한다."""
    classes: dict[str, float] = {}
    for outcome, weight in distribution.items():
        projected = _key(project(json.loads(outcome)))
        classes[projected] = classes.get(projected, 0.0) + weight
    return sum(weight * weight for weight in classes.values())


def majority_agreement(
    calls: Sequence[Mapping[str, Any]],
    *,
    model: str,
    k: int = DEFAULT_MAJORITY_VOTES,
    vote: MajorityVote = "ruleSet",
    deltas: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """이미 남은 반복 기록으로 "k 번 불러 최빈 결과를 판정으로 쓰면" 판정끼리 얼마나 같아지는지를 plug-in 으로 어림한다(호출 없음).

    줄마다 그 모델의 성공 결과(같은 키는 마지막 줄)로 결과 분포를 만들고, 그 분포에서 독립으로 뽑은 단일 판정 둘이 같을 확률과
    k 표 다수결 판정 둘이 같을 확률을 낸 뒤 줄에 대해 평균한다. 둘 다 같은 plug-in 이라 서로 견줄 수 있다 — 다만 반복 몇 번의 경험
    분포를 참 분포로 쓰므로 실제보다 일치가 높게 나오는 쪽으로 치우친다(반복이 적을수록 더). 기존 `self_agreement` 는 복원 없는
    쌍이라 이 단일 판정 값과 같지 않다.

    다수결 이득(다수결 일치 − 단일 일치)도 부풀린다. 참 분포가 두 결과 반반이면 세 표 다수결의 참 이득은 0 인데, 반복 3회로 만든
    경험 분포는 4분의 3 확률로 (2/3, 1/3) 이 되고 그때 어림 이득이 44/729 라 기대값이 11/243(약 +0.045)이다. 이득을 문턱과 견줄
    때는 이만큼을 먼저 깎아 읽는다 — 결과의 `biasNote` 칸에 같은 말을 싣는다.

    표는 `vote` 공간에서 던진다 — 규칙 집합(`ruleSet`) 또는 앱 반영 변화량(`appliedChange`, 스탯마다 반영되는 폭). 그 다수결 결과를
    지표마다 투영해 견준다: 규칙 집합(표를 변화량으로 던졌으면 없음), 앱 반영 변화량, 방향(스탯마다 폭의 부호), 발동 여부. 변화량·
    방향은 폭 표(`deltas`, 짧은 규칙 id → 폭)가 있어야 낸다 — 짧은 id 는 판정 줄마다 다시 매기는 글자라, 한 표는 스탯 줄 구성이 같은
    줄들(한 작품의 덤프)에만 맞는다.

    스탯 판정 결과(규칙 id 목록)만 센다 — 엔딩·그림 결과와 망친 입력 대조군 줄(`control:`)은 뺀다. 성공 결과가 둘 미만인 줄은
    `skippedLines` 로만 센다."""
    if k < 1:
        raise SystemExit(f"표 수는 1 이상이다: {k}")
    if vote == "appliedChange" and deltas is None:
        raise SystemExit("앱 반영 변화량으로 표를 던지려면 폭 표가 있어야 한다")
    per_line: dict[str, list[Any]] = {}
    for row in latest_calls(calls).values():
        line_id = str(row["lineId"])
        if row["model"] != model or row["status"] != "ok" or line_id.startswith("control:"):
            continue
        if not isinstance(row["result"], list):
            continue
        per_line.setdefault(line_id, []).append(row["result"])

    def to_vote(result: list[str]) -> Any:
        return applied_change(result, deltas) if vote == "appliedChange" and deltas is not None else sorted(result)

    projections: dict[str, Callable[[Any], Any] | None] = {
        "ruleSet": (lambda value: value) if vote == "ruleSet" else None,
        "appliedChange": None,
        "direction": None,
        "fired": bool,
    }
    if deltas is not None:
        change = (lambda value: value) if vote == "appliedChange" else (lambda value: applied_change(value, deltas))
        projections["appliedChange"] = change
        projections["direction"] = lambda value: {stat: _sign(delta) for stat, delta in change(value).items()}

    scores: dict[str, list[tuple[float, float]]] = {name: [] for name in MAJORITY_METRICS}
    skipped = 0
    for line_id in sorted(per_line):
        results = per_line[line_id]
        if len(results) < 2:
            skipped += 1
            continue
        counts = Counter(_key(to_vote(result)) for result in results)
        single = {outcome: count / len(results) for outcome, count in counts.items()}
        majority = _majority_distribution(single, k)
        for name, project in projections.items():
            if project is not None:
                scores[name].append((_agreement(single, project), _agreement(majority, project)))
    metrics: dict[str, Any] = {}
    for name in MAJORITY_METRICS:
        pairs = scores[name]
        if projections[name] is None:
            metrics[name] = None
            continue
        metrics[name] = {
            "single": sum(a for a, _ in pairs) / len(pairs) if pairs else None,
            "majority": sum(b for _, b in pairs) / len(pairs) if pairs else None,
            "lines": len(pairs),
        }
    return {
        "model": model,
        "k": k,
        "vote": vote,
        "biasNote": MAJORITY_BIAS_NOTE,
        "lines": len(per_line) - skipped,
        "skippedLines": skipped,
        "metrics": metrics,
    }


def _control_target(kind: JudgmentKind, value: Any, countdown_ids: set[str]) -> bool:
    """망친 입력이 노린 상태 — 스탯은 카운트다운 규칙 id 가 듦, 엔딩은 참, 그림(상황 이미지·미디어 북 칸)은 고른 id 가 있음."""
    if kind == "stat":
        return bool(set(value) & countdown_ids)
    return fired(kind, value)


def load_strata(path: Path | None) -> dict[tuple[str | None, int], dict[str, Any]]:
    """카운트다운 층 표: [{roomId, turn, stratum, expectDecrement}]. 대본 설계와, 재판정 전에 사람이 생성 응답을 읽고 정한 값이다."""
    if path is None:
        return {}
    return {(entry.get("roomId"), int(entry["turn"])): entry for entry in json.loads(path.read_text(encoding="utf-8"))}


def _all_pass(values: Sequence[bool | None]) -> bool | None:
    """하나라도 불합격이면 불합격, 아니고 하나라도 보류면 보류, 모두 합격이면 합격(빈 목록은 보류)."""
    if any(v is False for v in values):
        return False
    if not values or any(v is None for v in values):
        return None
    return True


def summarize(
    lines: Sequence[JudgmentLine],
    calls: Sequence[Mapping[str, Any]],
    *,
    candidate: str = "haiku",
    baseline: str | None = None,
    min_self: float = DEFAULT_MIN_SELF_AGREEMENT,
    min_fired_lines: int = DEFAULT_MIN_FIRED_LINES,
    strata: Mapping[tuple[str | None, int], Mapping[str, Any]] | None = None,
    countdown_stat: str = COUNTDOWN_STAT,
    max_quiet_decrement: float = DEFAULT_MAX_QUIET_DECREMENT,
    min_decrement: float = DEFAULT_MIN_DECREMENT,
    min_control_reaction: float = DEFAULT_MIN_CONTROL_REACTION,
) -> dict[str, Any]:
    """합격 판정은 후보 판정기 하나로 한다 — 호출 위치마다 자기 반복 일치율(전체 줄·발동한 줄 모두 하한 이상)과 구조화 실패
    0, 카운트다운 층마다 기대 방향의 감소 비율, 대조군 반응률. `baseline` 을 주면 그 모델과의 교차 일치율을 참고로 함께 낸다(판정에
    쓰지 않는다)."""
    check_prompt_shas(lines, calls)
    latest = latest_calls(calls)
    ok: dict[tuple[str, str], list[Any]] = {}
    counts: dict[tuple[str, str], Counter[str]] = {}
    by_id = {line.line_id: line for line in lines}
    models: list[str] = []
    for row in latest.values():
        line = by_id.get(str(row["lineId"]))
        if line is None:
            continue
        label = str(row["model"])
        if label not in models:
            models.append(label)
        if line.control is None:
            counter = counts.setdefault((line.call_site, label), Counter())
            counter[str(row["status"])] += 1
            if row.get("firstStatus", row["status"]) == "structured_failure":
                counter["first_structured_failure"] += 1
        if row["status"] == "ok":
            ok.setdefault((line.line_id, label), []).append(row["result"])
    models.sort()

    main_lines = [line for line in lines if line.control is None]
    per_site: dict[str, Any] = {}
    for site in sorted({line.call_site for line in main_lines}):
        site_lines = [line for line in main_lines if line.call_site == site]
        kind = site_lines[0].kind
        fired_lines = [
            line
            for line in site_lines
            if any(fired(kind, value) for label in models for value in ok.get((line.line_id, label), []))
        ]
        entry: dict[str, Any] = {"lines": len(site_lines), "firedLines": len(fired_lines), "models": {}}
        for label in models:
            agreement, n = _mean([self_agreement(ok.get((line.line_id, label), [])) for line in site_lines])
            fired_agreement, fired_n = _mean(
                [self_agreement(ok.get((line.line_id, label), [])) for line in fired_lines]
            )
            c = counts.get((site, label), Counter())
            entry["models"][label] = {
                "selfAgreement": agreement,
                "selfAgreementLines": n,
                "firedSelfAgreement": fired_agreement,
                "firedSelfAgreementLines": fired_n,
                "modal": modal_distribution(kind, [ok.get((line.line_id, label), []) for line in site_lines]),
                "ok": c["ok"],
                "structuredFailures": c["structured_failure"],
                "firstAttemptStructuredFailures": c["first_structured_failure"],
                "callErrors": c["call_error"],
            }
        if baseline is not None and baseline in models and candidate in models:
            # 교차와 두 자기 반복을 같은 줄 집합(두 모델 모두 성공이 둘 이상인 줄)으로 낸다 — 한쪽만 빠진 줄이 섞이면 서로 다른
            # 줄에서 낸 값을 견주게 된다.
            common = [
                line
                for line in site_lines
                if len(ok.get((line.line_id, candidate), [])) >= 2 and len(ok.get((line.line_id, baseline), [])) >= 2
            ]
            cross, n = _mean(
                [
                    cross_agreement(ok.get((line.line_id, candidate), []), ok.get((line.line_id, baseline), []))
                    for line in common
                ]
            )
            base_self, base_n = _mean([self_agreement(ok.get((line.line_id, baseline), [])) for line in common])
            cand_self, cand_n = _mean([self_agreement(ok.get((line.line_id, candidate), [])) for line in common])
            entry["cross"] = {
                "pair": f"{candidate}-{baseline}",
                "agreement": cross,
                "lines": n,
                "baselineSelfAgreement": base_self,
                "baselineSelfAgreementLines": base_n,
                "candidateSelfAgreement": cand_self,
                "candidateSelfAgreementLines": cand_n,
            }
        entry["verdict"] = _site_verdict(entry, candidate, min_self=min_self, min_fired_lines=min_fired_lines)
        per_site[site] = entry

    countdown: dict[str, Any] = {}
    for line in main_lines:
        if line.call_site != "chat_stat_judgment" or strata is None:
            continue
        stratum = strata.get((line.room_id, line.turn))
        if stratum is None:
            continue
        ids = stat_rule_ids(line.prompt, countdown_stat)
        if not ids:
            continue
        name = str(stratum["stratum"])
        bucket = countdown.setdefault(
            name, {"expectDecrement": stratum.get("expectDecrement"), "lines": 0, "models": {}}
        )
        bucket["lines"] += 1
        for label in models:
            results = ok.get((line.line_id, label), [])
            m = bucket["models"].setdefault(label, {"results": 0, "decrements": 0})
            m["results"] += len(results)
            m["decrements"] += sum(1 for r in results if set(r) & ids)
    for bucket in countdown.values():
        for m in bucket["models"].values():
            m["decrementRate"] = m["decrements"] / m["results"] if m["results"] else None
        bucket["verdict"] = _countdown_verdict(
            bucket, candidate, max_quiet_decrement=max_quiet_decrement, min_decrement=min_decrement
        )

    controls: dict[str, Any] = {}
    for line in lines:
        if line.control is None or line.base_id is None:
            continue
        reacted: dict[str, bool | None] = {}
        opposite: dict[str, bool | None] = {}
        countdown_ids = stat_rule_ids(line.prompt, countdown_stat)
        for label in models:
            base = _modal(ok.get((line.base_id, label), []))
            changed = _modal(ok.get((line.line_id, label), []))
            if base is None or changed is None:
                reacted[label] = opposite[label] = None
                continue
            was = _control_target(line.kind, json.loads(base), countdown_ids)
            now = _control_target(line.kind, json.loads(changed), countdown_ids)
            # 원래 줄이 이미 기대 상태면 기대 방향 변화는 일어날 수 없다 — 반응을 잴 수 없어 반응률에서 뺀다.
            reacted[label] = None if was else now
            opposite[label] = was and not now
        controls[line.control] = {
            "callSite": line.call_site,
            "baseLine": line.base_id,
            "reacted": reacted,
            "opposite": opposite,
        }
    reaction: dict[str, Any] = {}
    for label in models:
        seen = [c["reacted"][label] for c in controls.values() if c["reacted"].get(label) is not None]
        flipped = sum(1 for c in controls.values() if c["opposite"].get(label))
        reaction[label] = {
            "controls": len(seen),
            "reacted": sum(seen),
            "opposite": flipped,
            "rate": sum(seen) / len(seen) if seen else None,
        }
    rate = reaction.get(candidate, {}).get("rate")
    reaction["verdict"] = {
        "pass": None if rate is None else rate >= min_control_reaction,
        "rule": f"{candidate} 대조군 반응률 >= {min_control_reaction:.2f}",
    }

    overall = _all_pass(
        [entry["verdict"]["pass"] for entry in per_site.values()]
        + [bucket["verdict"]["pass"] for bucket in countdown.values() if bucket["expectDecrement"] is not None]
        + ([reaction["verdict"]["pass"]] if controls else [])
    )
    return {
        "models": models,
        "candidate": candidate,
        "baseline": baseline,
        "thresholds": {
            "minSelfAgreement": min_self,
            "minFiredLines": min_fired_lines,
            "maxQuietDecrement": max_quiet_decrement,
            "minDecrement": min_decrement,
            "minControlReaction": min_control_reaction,
        },
        "callSites": per_site,
        "countdown": countdown,
        "controls": controls,
        "controlReaction": reaction,
        "verdict": {"pass": overall},
    }


def _site_verdict(entry: Mapping[str, Any], candidate: str, *, min_self: float, min_fired_lines: int) -> dict[str, Any]:
    rule = f"{candidate} 구조화 실패 0, 발동한 줄 >= {min_fired_lines}, 자기 반복 일치율(전체 줄·발동한 줄 모두) >= {min_self:.2f}"

    def verdict(passed: bool | None, reason: str) -> dict[str, Any]:
        return {"pass": passed, "reason": reason, "rule": rule}

    model = entry["models"].get(candidate)
    if model is None:
        return verdict(None, f"{candidate} 결과가 없다")
    # 빠진 호출을 채운다고 구조화 실패가 없어지지는 않으니 보류 판정보다 앞서 본다.
    if model["structuredFailures"] > 0:
        return verdict(False, f"구조화 실패 {model['structuredFailures']}건")
    if model["callErrors"] > 0:
        return verdict(None, f"전송 오류 {model['callErrors']}건이 남았다 — 다시 실행해 그 호출만 채운다")
    if model["selfAgreementLines"] < entry["lines"]:
        return verdict(
            None, f"성공이 둘 이상인 줄 {model['selfAgreementLines']} 개 < 줄 {entry['lines']} 개 — 빠진 호출을 채운다"
        )
    if entry["firedLines"] < min_fired_lines:
        return verdict(None, f"발동한 줄 {entry['firedLines']} 개 < {min_fired_lines} — 표본을 늘린다")
    whole, fired_only = model["selfAgreement"], model["firedSelfAgreement"]
    if whole is None or fired_only is None:
        return verdict(None, "자기 반복 일치율을 낼 결과가 모자라다")
    if whole >= min_self and fired_only >= min_self:
        return verdict(True, "하한 이상")
    return verdict(False, f"자기 반복 일치율 전체 {whole:.3f} · 발동한 줄 {fired_only:.3f}")


def _countdown_verdict(
    bucket: Mapping[str, Any], candidate: str, *, max_quiet_decrement: float, min_decrement: float
) -> dict[str, Any]:
    """시간이 움직이지 않은 층(`expectDecrement` 거짓)은 감소 비율 상한, 움직인 층(참)은 하한. 기대값이 없는 층은 판정하지 않는다."""
    expect = bucket["expectDecrement"]
    rate = bucket["models"].get(candidate, {}).get("decrementRate")
    if expect is None:
        return {"pass": None, "rule": "기대값 없음(분포만)"}
    if expect:
        return {"pass": None if rate is None else rate >= min_decrement, "rule": f"감소 비율 >= {min_decrement:.2f}"}
    return {
        "pass": None if rate is None else rate <= max_quiet_decrement,
        "rule": f"감소 비율 <= {max_quiet_decrement:.2f}",
    }


def line_table(lines: Sequence[JudgmentLine], calls: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """판정 줄마다 모델별 결과 목록(반복 순서). 프롬프트 본문은 싣지 않는다."""
    latest = latest_calls(calls)
    out = []
    for line in lines:
        results: dict[str, list[Any]] = {}
        for row in sorted(latest.values(), key=lambda r: (str(r["model"]), int(r["rep"]))):
            if row["lineId"] == line.line_id:
                results.setdefault(str(row["model"]), []).append(
                    row["result"] if row["status"] == "ok" else {"status": row["status"]}
                )
        out.append(
            {
                "lineId": line.line_id,
                "roomId": line.room_id,
                "turn": line.turn,
                "callSite": line.call_site,
                "control": line.control,
                "baseLine": line.base_id,
                "promptChars": len(line.prompt),
                "results": results,
            }
        )
    return out


def measured_tokens_per_char(calls: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """성공·구조화 실패 호출의 입력 토큰 ÷ 프롬프트 글자 수(모델별). 견적 자리값을 이것으로 바꾼다."""
    tokens: Counter[str] = Counter()
    chars: Counter[str] = Counter()
    for row in latest_calls(calls).values():
        if row["status"] == "call_error" or not row.get("inputTokens"):
            continue
        tokens[str(row["model"])] += int(row["inputTokens"])
        chars[str(row["model"])] += int(row["promptChars"])
    return {label: tokens[label] / chars[label] for label in tokens if chars[label]}


class FakeJudgeLLM(LLMClient):
    """절차 확인용 가짜 판정기. `answer` 가 (프롬프트, 응답 스키마 이름, 호출 위치) → 결과 dict 또는 올릴 예외를 돌려준다(없으면
    "아무 일도 없음"). 사용량은 프롬프트 글자 수만큼의 입력 토큰으로 보고한다."""

    def __init__(self, model_id: str, answer: FakeAnswer | None = None) -> None:
        self.model_id = model_id
        self.answer = answer
        self.calls = 0

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        raise RuntimeError("가짜 판정기는 생성을 하지 않는다")
        yield ""  # pragma: no cover

    async def generate_structured(
        self,
        prompt: str,
        response_schema: type[T],
        images: list[tuple[bytes, str]] | None = None,
        *,
        usage: LLMCallContext,
    ) -> T:
        self.calls += 1
        if usage.usage_sink is not None:
            usage.usage_sink.append(
                CallUsage(
                    call_site=usage.call_site,
                    model=self.model_id,
                    prompt_tokens=len(prompt),
                    cached_tokens=0,
                    cache_write_tokens=0,
                    output_tokens=5,
                    thoughts_tokens=0,
                )
            )
        answer = (
            self.answer(prompt, response_schema.__name__, usage.call_site)
            if self.answer is not None
            else _FAKE_DEFAULTS[response_schema.__name__]
        )
        if isinstance(answer, Exception):
            raise answer
        return response_schema.model_validate(answer)


_FAKE_DEFAULTS: dict[str, dict[str, Any]] = {
    "StatRuleJudgmentResult": {"fired_rule_ids": []},
    "EndingJudgmentResult": {"triggered": False},
    "ImageMatchJudgmentResult": {"matched_image_entity_id": None},
}
