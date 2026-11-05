"""모호 후보 판정 — 구조 규칙이 가르지 못한 후보 경고를 모델에 물어 경고만 덧붙인다.

후보는 셋이다. 순서 미정(J1), 속성 표면 차이(J2), 앎 출처 불명(J3). 확정 하나에 `JUDGE_MAX_CANDIDATES` 건까지 J1 → J3 → J2,
같은 규칙 안은 화 번호 순으로 부른다. 넘친 후보는 부르지 않는다 — J1·J2 는 후보 경고만 남기고, J3 은 버린다. J3 은 전달 사건을
구조로 추적하지 않아 오탐이 커서 판정이 충돌이라 할 때만 남기기 때문이다.

판정이 충돌이면 후보 경고에 모델 판정의 충돌 경고(`llm_conflict` — 판정·이유·후보 규칙)를 덧붙인다. 충돌이 아니거나 모르겠다면
J1·J2 는 후보 경고만, J3 은 아무것도 남기지 않는다. 호출이 실패하면 판정 실패 경고(`judge_failed` — 후보 규칙과 실패 사유)를
남긴다. 판정 단계 자체가 깨지면(후보 조립의 읽기 실패나 판정 함수의 결함) 검사 틀이 `unjudged` 로 후보마다 같은 꼴의 판정
실패(`internal`)를 남긴다 — 후보 경고만 남기면 "판정 못 함"이 "충돌 아님 판정"과 같은 행이 되고, 충돌 판정 때만 남기로 한 J3 이
판정 없이 남는다. 판정 단계가 돌려주는 타입은 경고 목록이라 판정은 어떤 경우에도 확정을 막지 못하고, 호출 실패를 예외로 올리지
않아 확정을 실패시키지도 않는다.

시간: 확정 하나의 판정 호출 전체에 `JUDGE_BUDGET_SECONDS`(작업 상한보다 60초 짧다), 호출마다 `min(JUDGE_CALL_SECONDS, 남은
기한)`. 기한이 차면 남은 후보는 부르지 않고 실패 사유 `deadline` 으로 끝낸다. 머리 비교에서 져 같은 작업 실행 안에서 다시 검사하면
검사 틀이 넘긴, 앞 판정 단계에 이미 쓴 시간(`spent`)을 빼고 남은 기한만 쓴다 — 그래서 판정 10건이 호출마다 상한을 다 쓰고 커밋이
머리 비교에서 져도 확정 처리가 작업 상한 안에 끝나, 만료 정리가 확정을 연결부터 되풀이하는 일이 정상 경로에서 생기지 않는다.

호출은 `conflicts.judge` 연산에 배정된 어댑터로 간다. 어댑터는 추출과 같은 구조화 호출(지시문을 따로 싣는 것)을 쓰고 호출 기록
원소를 남긴다 — 사고를 끄는 것도 그 구조화 경로의 몫이다."""

import asyncio
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat.prompt_builder import PromptRenderError
from api.novel_bible.core.contracts import (
    AdapterCallError,
    AdapterResolver,
    BibleModelAdapter,
    Judge,
    PromptSource,
)
from api.novel_bible.core.render import render
from api.novel_bible.core.sweep import BIBLE_TASK_TIMEOUT_SECONDS
from api.novel_bible.core.types import CommitRef, FindingDraft, JudgeCandidate, WarningDraft
from api.novel_bible.ids import JobFailure

logger = logging.getLogger(__name__)

JUDGE_MAX_CANDIDATES = 10
JUDGE_BUDGET_SECONDS = BIBLE_TASK_TIMEOUT_SECONDS - 60
JUDGE_CALL_SECONDS = 120
CHANNEL = "novel_bible_conflicts"
# 규칙 차례 — 순서 미정, 앎 출처 불명, 속성 표면 차이.
_RULE_ORDER = {"J1": 0, "J3": 1, "J2": 2}
# 판정이 충돌이라 할 때만 후보 경고를 남기는 후보.
_KEPT_ONLY_ON_CONFLICT = frozenset({"J3"})

# 판정 실패 사유 — 어댑터가 올린 사유, 총 기한 초과(`deadline`), 호출 하나의 상한 초과(`timeout`), 문안 렌더 실패, 그 밖.
JudgeFailure = JobFailure | Literal["deadline", "timeout"]


class JudgeVerdict(BaseModel):
    verdict: Literal["conflict", "no_conflict", "unsure"]
    reason: str


def _mark(warning: WarningDraft) -> str:
    return str(warning.payload["judge"])


def _failed(warning: WarningDraft, failure: JudgeFailure) -> WarningDraft:
    return WarningDraft(
        rule="judge_failed", item_ids=warning.item_ids,
        payload={"rule": warning.rule, "judge": _mark(warning), "failure": failure},
    )


def _outcome(warning: WarningDraft, verdict: JudgeVerdict | None, failure: JudgeFailure | None) -> list[WarningDraft]:
    """후보 경고 하나의 결과. `verdict`·`failure` 가 모두 없으면 넘쳐서 부르지 않은 후보다."""
    conflict = verdict is not None and verdict.verdict == "conflict"
    kept = [warning] if conflict or _mark(warning) not in _KEPT_ONLY_ON_CONFLICT else []
    if verdict is None and failure is None:
        return kept
    if failure is not None:
        return [*kept, _failed(warning, failure)]
    assert verdict is not None
    if not conflict:
        return kept
    return [
        *kept,
        WarningDraft(
            rule="llm_conflict", item_ids=warning.item_ids,
            payload={"rule": warning.rule, "judge": _mark(warning), "verdict": verdict.verdict,
                     "reason": verdict.reason},
        ),
    ]


@dataclass(frozen=True)
class _ModelJudge:
    resolver: AdapterResolver
    budget_seconds: float
    call_seconds: float
    clock: Callable[[], float]

    async def __call__(
        self, session_factory: async_sessionmaker[AsyncSession], commit: CommitRef, candidates: Sequence[JudgeCandidate],
        *, spent: float,
    ) -> list[WarningDraft]:
        ordered = sorted(candidates, key=lambda candidate: (_RULE_ORDER[_mark(candidate.warning)], candidate.chapters))
        called, overflow = ordered[:JUDGE_MAX_CANDIDATES], ordered[JUDGE_MAX_CANDIDATES:]
        warnings = [warning for candidate in overflow for warning in _outcome(candidate.warning, None, None)]
        if not called:
            return warnings
        budget = self.budget_seconds - spent
        started = self.clock()
        adapter = self.resolver("conflicts.judge")
        records: list[dict[str, Any]] = []
        source: PromptSource | None = None
        source_failure: JudgeFailure | None = None
        try:
            async with session_factory() as session:
                source = await adapter.prompt_source(session)
        except AdapterCallError as error:
            source_failure = error.code
        except Exception:
            logger.exception("정본 기억 판정 문안을 읽지 못했다(확정 %s)", commit.commit_id)
            source_failure = "internal"
        for candidate in called:
            remaining = budget - (self.clock() - started)
            verdict: JudgeVerdict | None = None
            if source is None:
                failure = source_failure
            elif remaining <= 0:
                failure = "deadline"
            else:
                verdict, failure = await _call(
                    adapter, source, commit, candidate, records, min(self.call_seconds, remaining)
                )
                # 남은 기한이 호출 상한보다 짧아 끊겼으면 총 기한이 찬 것이다.
                if failure == "timeout" and self.clock() - started >= budget:
                    failure = "deadline"
            warnings += _outcome(candidate.warning, verdict, failure)
        if records:
            logger.info("정본 기억 확정 %s 의 판정 호출 %d 건", commit.commit_id, len(records))
        return warnings

    def unjudged(self, candidates: Sequence[FindingDraft]) -> list[WarningDraft]:
        return [
            warning
            for finding in candidates
            for warning in _outcome(WarningDraft.model_validate(finding.model_dump()), None, "internal")
        ]


def build_judge(
    resolver: AdapterResolver, *, budget_seconds: float = JUDGE_BUDGET_SECONDS,
    call_seconds: float = JUDGE_CALL_SECONDS, clock: Callable[[], float] = time.monotonic,
) -> Judge:
    """`resolver` 가 `conflicts.judge` 에 배정한 어댑터로 부르는 판정. 기한·시계는 테스트가 줄이거나 바꿔 끼운다."""
    return _ModelJudge(resolver, budget_seconds, call_seconds, clock)


async def _call(
    adapter: BibleModelAdapter, source: PromptSource, commit: CommitRef, candidate: JudgeCandidate, records: list[dict[str, Any]],
    limit: float,
) -> tuple[JudgeVerdict | None, JudgeFailure | None]:
    try:
        prompt = render(source, channel=CHANNEL, scope=commit.scope, values={"candidate": candidate.text})
        async with asyncio.timeout(limit):
            verdict = await adapter.structured(prompt, JudgeVerdict, records=records, stage="conflicts.judge")
    except TimeoutError:
        return None, "timeout"
    except AdapterCallError as error:
        return None, error.code
    except PromptRenderError:
        logger.warning("정본 기억 판정 문안을 렌더하지 못했다(확정 %s, 채널 %s)", commit.commit_id, CHANNEL)
        return None, "prompt_missing"
    except Exception:
        logger.exception("정본 기억 판정 호출 실패(확정 %s)", commit.commit_id)
        return None, "internal"
    return verdict, None
