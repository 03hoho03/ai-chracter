"""κ 용 판정 — 사람이 라벨한 주장을 판정 모델에도 사람 라벨과 같은 범주(주장 판정 하나 + 인용마다 받침 여부)로 매기게 하고,
사람과 모델의 일치(Cohen's κ)를 주장 단위로 센다.

- 판정기는 라벨 시트가 보이는 것만 받는다 — 슬롯, 코어가 만든 주장 한 줄, 그 주장의 인용. 어느 어댑터의 주장인지는 모른다.
  판정 문안은 이 모듈의 상수다. 측정 도구의 문안이라 운영 문안 세트에 두지 않는다.
- 판정 모델은 싼 것부터 — Gemini 로 먼저 돌려 κ 를 보고, 그다음 Haiku. 한 판정 파일은 한 모델의 판정이다(주장마다 모델을 섞으면
  κ 가 어느 모델의 것인지 흐려진다). 사고는 끈 조건에서 잰다. 앱의 구조화 호출이 Haiku 5.x 에는 사고 끔을 싣고, Gemini 에는 사고
  설정을 싣지 않아 모델 기본값을 따른다 — 그래서 호출 기록에 사고 토큰이 나오면 그 모델로는 이어 부르지 않고 멈춘다.
- 호출은 측정 원장을 지난다(`Meter` 가 감싼 어댑터 — 호출마다 견적으로 자리를 잡고 원가를 적으며, 멈춤 선에 닿을 호출은 부르기
  전에 멈춘다). 멈춰도 그때까지 받은 판정이 파일에 남고, 같은 파일로 다시 돌리면 판정이 없는 주장만 부른다.
- κ 는 두 갈래다. 주 지표는 이진 — 맞음이고 인용이 모두 받침인가 / 나머지. 참고로 3범주 — 맞음(인용 모두 받침)·틀림(방향 틀림
  포함)·근거 없음(맞음이지만 받치지 않는 인용이 있거나 판단 불가). 사람과 판정을 같은 함수로 접는다. 구간은 주장을 복원 추출로
  다시 뽑는 부트스트랩(2,000회, 시드 고정)이다."""

import hashlib
import math
import random
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from api.novel_bible.adapters.table import AdapterId
from api.novel_bible.core.contracts import AdapterCallError, BibleModelAdapter
from api.novel_bible.core.types import RenderedPrompt

from novel_bible_eval.labels import Claim, Label, LabeledClaim, QuoteMark, Verdict
from novel_bible_eval.metrics import cohen_kappa

# 판정 모델 이름 → 그 모델을 부르는 어댑터. 싼 것부터 적는다.
JUDGE_MODELS: dict[str, AdapterId] = {"gemini": "gemini", "haiku": "haiku"}
INSTRUCTION = """너는 소설 원고에서 뽑은 주장 하나를 검토한다. 주장은 원고 속 인물·사물·능력에 대한 사실, 인물이 아는 것이나 믿는 것,
또는 장면에서 일어난 사건이다. 주장 아래에 그 주장의 근거로 원고에서 잘라 낸 인용이 번호를 달고 실린다.

판정(verdict)은 하나를 고른다.
- correct: 주장이 원고의 내용으로 맞다.
- wrong: 주장이 원고의 내용과 다르다.
- direction: 아는 것·믿는 것 주장에서, 아는 사람과 그 앎의 대상이 뒤바뀌었거나 아는 사람이 다른 인물이다. 아는 것·믿는 것
  주장이 아니면 고르지 않는다.
- unknown: 인용만으로는 맞는지 틀린지 판단할 수 없다.

인용마다(quotes, 인용 번호 차례로 하나씩) 그 인용이 주장을 받치는지 고른다.
- supported: 그 인용을 읽으면 주장이 성립한다.
- unsupported: 그 인용이 주장을 성립시키지 않는다.

reason 에는 판단 이유를 한 문장으로 쓴다."""
# 호출 기록의 문안 세트 칸 — 판정 문안의 해시라, 문안이 바뀌면 기록만 보고도 어느 문안으로 판정했는지 가른다.
_PROMPT_ID = uuid.UUID(hashlib.sha256(INSTRUCTION.encode("utf-8")).hexdigest()[:32])
_SLOT_NAMES = {"facts": "사실", "knowledge": "아는 것·믿는 것", "events": "사건"}
# 주장 하나를 부르는 횟수 상한 — 정본 기억 작업이 한 작업을 세 번까지 시도하는 것과 같다.
_TRIES = 3
_ROUNDS = 2_000


class JudgeAnswer(BaseModel):
    verdict: Verdict
    quotes: list[QuoteMark]
    reason: str


class JudgeRun(BaseModel):
    """판정 파일(`judge-<모델>.json`). `answers` 는 주장 id → 사람 라벨과 같은 꼴의 판정(메모 칸에 판정 이유), `failures` 는 세 번
    다 실패한 주장의 마지막 실패 사유, `halted` 는 멈춤·끊김 까닭(끝까지 돌았으면 None)."""

    model: str
    halted: str | None = None
    answers: dict[str, Label] = {}
    failures: dict[str, str] = {}


class ThinkingOnError(Exception):
    """판정 호출이 사고 토큰을 냈다 — 사고를 끈 조건의 판정이 아니다."""


def render(claim: Claim) -> RenderedPrompt:
    quotes = "\n".join(f"[{number}] {quote}" for number, quote in enumerate(claim.quotes, start=1))
    prompt = f"종류: {_SLOT_NAMES[claim.slot]}\n주장: {claim.line}\n인용:\n{quotes}"
    return RenderedPrompt(system_instruction=INSTRUCTION, prompt=prompt, prompt_set_id=_PROMPT_ID)


async def judge_claims(adapter: BibleModelAdapter, claims: Sequence[Claim], run: JudgeRun) -> None:
    """판정이 없는 주장마다 부르고 받은 판정을 `run` 에 바로 넣는다 — 원장 멈춤으로 끊겨도 그때까지의 판정이 남는다. 실패한
    호출과 인용 칸 수가 주장과 다른 답(사람 라벨과 같은 범주가 아니다)은 다시 부르고, 세 번 다 안 되면 `failures` 에 남긴다."""
    for claim in claims:
        if claim.id in run.answers:
            continue
        failure = ""
        for _ in range(_TRIES):
            records: list[dict[str, Any]] = []
            try:
                answer = await adapter.structured(render(claim), JudgeAnswer, records=records, stage="conflicts.judge")
            except AdapterCallError as error:
                failure = error.code
                if error.retryable:
                    continue
                break
            finally:
                thoughts = sum(int(record.get("thoughtsTokens") or 0) for record in records)
                if thoughts:
                    raise ThinkingOnError(f"판정 호출이 사고 토큰 {thoughts} 을 냈다 — 사고를 끄는 모델로 다시 돌린다")
            if len(answer.quotes) == len(claim.quotes):
                run.answers[claim.id] = Label(verdict=answer.verdict, quotes=list(answer.quotes), memo=answer.reason)
                run.failures.pop(claim.id, None)
                break
            failure = "quote_count"
        if claim.id not in run.answers:
            run.failures[claim.id] = failure


def read_run(path: Path) -> JudgeRun:
    return JudgeRun.model_validate_json(path.read_text(encoding="utf-8"))


def write_run(run: JudgeRun, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(run.model_dump_json(indent=2), encoding="utf-8")


def binary(label: Label) -> str:
    """맞음이고 인용이 모두 받침인가 — 어댑터별 정밀도가 그 어댑터의 인용으로 맞음을 세는 것과 같은 기준을 주장 전체의 인용에
    건다."""
    supported = bool(label.quotes) and all(mark == "supported" for mark in label.quotes)
    return "correct" if label.verdict == "correct" and supported else "other"


def three(label: Label) -> str:
    if binary(label) == "correct":
        return "correct"
    return "wrong" if label.verdict in ("wrong", "direction") else "unsupported"


def _bootstrap(pairs: Sequence[tuple[str, str]], rng: random.Random) -> tuple[float, float]:
    values = []
    for _ in range(_ROUNDS):
        sample = [pairs[rng.randrange(len(pairs))] for _ in pairs]
        values.append(cohen_kappa([human for human, _ in sample], [model for _, model in sample]))
    values.sort()
    last = len(values) - 1
    return (values[math.floor(0.025 * last)], values[math.ceil(0.975 * last)])


@dataclass(frozen=True)
class KappaSummary:
    """`n` 은 사람 라벨과 판정이 모두 있는 주장 수, `unjudged` 는 판정이 없는 주장 수. 비교할 주장이 없으면 κ 와 구간이 None."""

    n: int
    unjudged: int
    binary: float | None
    binary_bootstrap: tuple[float, float] | None
    three: float | None
    three_bootstrap: tuple[float, float] | None


def kappa(labeled: Sequence[LabeledClaim], answers: Mapping[str, Label], *, seed: int = 0) -> KappaSummary:
    pairs = [(row.label, answers[row.claim.id]) for row in labeled if row.claim.id in answers]
    unjudged = len(labeled) - len(pairs)
    if not pairs:
        return KappaSummary(0, unjudged, None, None, None, None)
    folded = {fold: [(fold(human), fold(model)) for human, model in pairs] for fold in (binary, three)}
    rng = random.Random(seed)
    values = {
        fold: (cohen_kappa([h for h, _ in rows], [m for _, m in rows]), _bootstrap(rows, rng))
        for fold, rows in folded.items()
    }
    return KappaSummary(len(pairs), unjudged, *values[binary], *values[three])
