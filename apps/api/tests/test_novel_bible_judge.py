"""정본 기억 모호 후보 판정 — 구조 규칙이 가르지 못해 후보 표시(`judge`)를 실은 경고(순서 미정 J1·속성 표면 차이 J2·앎 출처
불명 J3)를 모델에 물어 경고만 덧붙인다.

판정은 확정을 막지도 실패시키지도 않는다. 판정 단계가 돌려주는 타입이 경고뿐이고, 호출 실패·기한 초과는 판정 실패 경고가
된다. 확정 하나에 최대 10건(J1 → J3 → J2, 같은 규칙 안은 화 번호 순)을 부르고, 넘친 J1·J2 는 판정 없이 경고만 남기며 J3 은
버린다. 앎 출처 불명은 판정이 충돌이라 할 때만 남는다.

확정 경로 테스트는 가짜 슬롯(원고의 합성 문법으로 항목을 만든다)과 실제 규칙 목록에, 앞 화 사실과 새 화 사실 한 쌍에 J1·J2
후보를 내는 표지 규칙을 더해 돈다. 앎 출처 불명(J3)은 실제 규칙이 낸다. 모델은 가짜 어댑터다(유료 호출 없음). 시간은 가짜
시계와 짧게 줄인 기한으로 보고 실제로 기한만큼 기다리지 않는다. 원고는 합성 문장이다."""

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar, get_type_hints

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.novel_bible import NovelBibleCommit, NovelBibleFinding
from api.db.models.prompt import PromptSection
from api.novel_bible.core.confirm import Actor, confirm
from api.novel_bible.core.contracts import (
    AdapterCallError,
    AdapterCapabilities,
    BibleModelAdapter,
    Judge,
    PromptSource,
    Rule,
)
from api.novel_bible.core.pipeline import run_until_idle
from api.novel_bible.core.sweep import BIBLE_TASK_TIMEOUT_SECONDS
from api.novel_bible.core.types import (
    BibleSnapshot,
    CommitRef,
    FindingDraft,
    JudgeCandidate,
    RenderedPrompt,
    WarningDraft,
)
from api.novel_bible.ids import FindingRule, OperationKey, SlotId, WarningRule
from api.novel_bible.rules import RULES
from api.novel_bible.rules.judge import (
    JUDGE_BUDGET_SECONDS,
    JUDGE_CALL_SECONDS,
    JUDGE_MAX_CANDIDATES,
    JudgeVerdict,
    build_judge,
)
from novel_bible_fakes import FakeAdapter, SessionFactory, add_chapter, full_registry, make_novel, savepoint_factory

T = TypeVar("T", bound=BaseModel)
Verdict = Literal["conflict", "no_conflict", "unsure"]
Answer = Callable[[str], Awaitable[JudgeVerdict]]


# ── 가짜 시계·어댑터·표지 규칙 ────────────────────────────────────────


@dataclass
class _Clock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now


def _always(verdict: Verdict) -> Answer:
    async def answer(candidate: str) -> JudgeVerdict:
        return JudgeVerdict(verdict=verdict, reason="합성 이유")

    return answer


@dataclass
class _Adapter:
    """추출은 가짜 슬롯이 원고 문법으로 하므로 가짜 어댑터의 빈 출력을 그대로 쓰고, 판정은 `answer` 가 정한다. 판정 호출마다
    받은 프롬프트 본문(후보 글)을 남기고, 해석기가 받은 연산 이름도 남긴다."""

    answer: Answer
    extraction: FakeAdapter = field(default_factory=FakeAdapter)
    judged: list[str] = field(default_factory=list)
    operations: list[OperationKey] = field(default_factory=list)
    id: str = "fake"
    capabilities: AdapterCapabilities = field(
        default_factory=lambda: AdapterCapabilities(structured=True, with_instruction=True, max_input_chars=100_000)
    )

    async def prompt_source(self, session: AsyncSession) -> PromptSource:
        source = await self.extraction.prompt_source(session)
        conflicts = [
            PromptSection(
                prompt_set_id=source.prompt_set_id, channel="novel_bible_conflicts", scope="both", slot=slot, variant="",
                body=body, conditional=False, order=order,
            )
            for order, (slot, body) in enumerate((("instruction", "합성 판정 지시문"), ("candidate", "{candidate}")))
        ]
        return PromptSource(prompt_set_id=source.prompt_set_id, sections=[*source.sections, *conflicts])

    async def structured(
        self, prompt: RenderedPrompt, schema: type[T], *, records: list[dict[str, Any]], stage: OperationKey
    ) -> T:
        if stage != "conflicts.judge":
            return await self.extraction.structured(prompt, schema, records=records, stage=stage)
        self.judged.append(prompt.prompt)
        verdict = await self.answer(prompt.prompt)
        return schema.model_validate(verdict.model_dump())

    def resolver(self) -> Callable[[OperationKey], BibleModelAdapter]:
        def resolve(operation: OperationKey) -> BibleModelAdapter:
            self.operations.append(operation)
            return self

        return resolve


@dataclass
class _Mark:
    """앞 화 사실과 새 화 사실 한 쌍에 판정 후보 경고 하나를 낸다 — 이름과 후보 표시는 실제 후보 규칙과 같다."""

    rule: FindingRule
    mark: str
    slots: frozenset[SlotId] = frozenset({"facts"})

    def check(self, snapshot: BibleSnapshot) -> list[FindingDraft]:
        assert snapshot.facts is not None
        old = [fact for fact in snapshot.facts if fact.id not in snapshot.new_ids]
        new = [fact for fact in snapshot.facts if fact.id in snapshot.new_ids]
        if not old or not new:
            return []
        return [
            FindingDraft(
                severity="warning", rule=self.rule, item_ids=(old[0].id, new[0].id), payload={"judge": self.mark}
            )
        ]


@dataclass
class _Blocks:
    """새 화 사실 하나에 차단 하나를 낸다."""

    rule: FindingRule = "immutable_attribute_mismatch"
    slots: frozenset[SlotId] = frozenset({"facts"})

    def check(self, snapshot: BibleSnapshot) -> list[FindingDraft]:
        assert snapshot.facts is not None
        new = [fact.id for fact in snapshot.facts if fact.id in snapshot.new_ids]
        return [FindingDraft(severity="block", rule=self.rule, item_ids=(new[0],))] if new else []


def _j1() -> Rule:
    return _Mark("order_undetermined", "J1")


def _j2() -> Rule:
    return _Mark("attribute_surface_differs", "J2")


# ── 합성 화 ─────────────────────────────────────────────────────────

# 1화: 하나의 성격이 서술된다. 2화: 하나의 성격이 다르게 서술되고, 1화 장면에 없던 둘이 1화의 사실을 안다 — 실제 규칙이 앎 출처
# 불명(J3) 하나를 낸다(가짜 슬롯의 사건에는 등장 인물이 없어 앎 주체가 그 사실 장면에 없던 것으로 읽힌다).
FIRST = ("사건: 하나가 정원에 선다.", "사실: 하나|attribute|성격|차분함|참")
SECOND = (
    "사건: 둘이 마당을 쓴다.", "사실: 하나|attribute|성격|거침|참", "앎: 둘|knows|하나|attribute|성격|차분함",
)
SYSTEM = Actor(kind="system")


async def _story(db: AsyncSession, rules: Sequence[Rule], judge: Judge | None) -> uuid.UUID:
    """1화를 판정 없이 확정한 뒤 2화를 `rules`·`judge` 로 확정하고 2화 확정 id 를 돌려준다."""
    novel = await make_novel(db)
    registry = full_registry()
    factory = savepoint_factory(db)
    commit_id = uuid.uuid4()
    for ordinal, paragraphs in ((1, FIRST), (2, SECOND)):
        chapter, revision = await add_chapter(db, novel.id, ordinal, "\n\n".join(paragraphs))
        result = await confirm(
            db, registry, novel_id=novel.id, chapter_id=chapter.id, revision_id=revision.id, actor=SYSTEM
        )
        commit_id = result.commit_id
        last = ordinal == 2
        await run_until_idle(
            factory, registry, list(rules) if last else [], FakeAdapter().resolver(), judge=judge if last else None
        )
    return commit_id


async def _status(db: AsyncSession, commit_id: uuid.UUID) -> str | None:
    status: str | None = await db.scalar(select(NovelBibleCommit.status).where(NovelBibleCommit.id == commit_id))
    return status


async def _findings(db: AsyncSession, commit_id: uuid.UUID) -> list[NovelBibleFinding]:
    rows = await db.scalars(select(NovelBibleFinding).where(NovelBibleFinding.commit_id == commit_id))
    return sorted(rows.all(), key=lambda row: (row.severity, row.rule, str(row.payload.get("judge"))))


def _summary(rows: Sequence[NovelBibleFinding]) -> list[tuple[str, str, str | None]]:
    """(등급, 이름, 후보 표시) — 판정이 만든 행의 후보 표시는 그 판정이 다룬 후보의 표시다."""
    return [(row.severity, row.rule, row.payload.get("judge")) for row in rows]


# ── 확정 경로 ───────────────────────────────────────────────────────


async def test_a_conflict_on_every_candidate_commits_with_warnings_only(db_session: AsyncSession) -> None:
    """가짜 판정이 모든 후보에 충돌이라 해도 확정은 커밋되고 차단은 0 이다 — 후보 경고는 그대로, 후보마다 모델 판정의 충돌
    경고가 하나씩 덧붙는다(판정·이유·후보 규칙을 싣는다). 판정은 `conflicts.judge` 연산의 어댑터로 부른다."""
    adapter = _Adapter(_always("conflict"))
    commit_id = await _story(db_session, [*RULES, _j1(), _j2()], build_judge(adapter.resolver()))

    assert await _status(db_session, commit_id) == "committed"
    rows = await _findings(db_session, commit_id)
    assert _summary(rows) == [
        ("warning", "attribute_surface_differs", "J2"),
        ("warning", "knowledge_source_unclear", "J3"),
        ("warning", "llm_conflict", "J1"),
        ("warning", "llm_conflict", "J2"),
        ("warning", "llm_conflict", "J3"),
        ("warning", "order_undetermined", "J1"),
    ]
    conflicts = {row.payload["judge"]: row.payload for row in rows if row.rule == "llm_conflict"}
    assert {mark: (p["rule"], p["verdict"], p["reason"]) for mark, p in conflicts.items()} == {
        "J1": ("order_undetermined", "conflict", "합성 이유"),
        "J2": ("attribute_surface_differs", "conflict", "합성 이유"),
        "J3": ("knowledge_source_unclear", "conflict", "합성 이유"),
    }
    candidates = {row.payload["judge"]: row.payload["items"] for row in rows if row.rule != "llm_conflict"}
    assert {mark: p["items"] for mark, p in conflicts.items()} == candidates
    assert adapter.operations == ["conflicts.judge"]
    assert len(adapter.judged) == 3


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        pytest.param(AdapterCallError("llm_error", retryable=True), "llm_error", id="adapter_error"),
        pytest.param(RuntimeError("합성 실패"), "internal", id="unexpected"),
    ],
)
async def test_a_judge_that_raises_still_commits_with_judge_failed(
    db_session: AsyncSession, failure: Exception, code: str
) -> None:
    """판정 호출이 예외를 내도 확정은 커밋된다. 후보마다 판정 실패 경고(후보 규칙과 실패 사유)가 남고, J1·J2 후보 경고는
    그대로, J3 은 충돌 판정이 없으므로 후보 경고가 남지 않는다."""

    async def answer(candidate: str) -> JudgeVerdict:
        raise failure

    commit_id = await _story(db_session, [*RULES, _j1(), _j2()], build_judge(_Adapter(answer).resolver()))

    assert await _status(db_session, commit_id) == "committed"
    rows = await _findings(db_session, commit_id)
    assert _summary(rows) == [
        ("warning", "attribute_surface_differs", "J2"),
        ("warning", "judge_failed", "J1"),
        ("warning", "judge_failed", "J2"),
        ("warning", "judge_failed", "J3"),
        ("warning", "order_undetermined", "J1"),
    ]
    assert {(row.payload["rule"], row.payload["failure"]) for row in rows if row.rule == "judge_failed"} == {
        ("order_undetermined", code), ("attribute_surface_differs", code), ("knowledge_source_unclear", code)
    }


async def test_a_judge_that_uses_its_whole_limit_every_time_hits_the_deadline_and_still_commits(
    db_session: AsyncSession,
) -> None:
    """가짜 판정이 매번 받은 시간을 다 쓰고 끊긴다(가짜 시계를 호출 상한만큼 밀고 시간 초과를 낸다). 총 기한(240초)은 호출
    두 번에 다 차고, 그 뒤 후보는 부르지 않고 판정 실패(후보 규칙과 `deadline`)로 끝난다. 확정은 작업 상한 안에 커밋된다."""
    assert JUDGE_BUDGET_SECONDS == BIBLE_TASK_TIMEOUT_SECONDS - 60 == 2 * JUDGE_CALL_SECONDS
    clock = _Clock()

    async def answer(candidate: str) -> JudgeVerdict:
        clock.now += JUDGE_CALL_SECONDS
        raise TimeoutError

    adapter = _Adapter(answer)
    judge = build_judge(adapter.resolver(), clock=clock)
    commit_id = await _story(db_session, [*RULES, _j1(), _j1(), _j2()], judge)

    assert await _status(db_session, commit_id) == "committed"
    assert clock.now <= BIBLE_TASK_TIMEOUT_SECONDS
    assert len(adapter.judged) == 2
    failed = [
        (row.payload["rule"], row.payload["failure"])
        for row in await _findings(db_session, commit_id)
        if row.rule == "judge_failed"
    ]
    assert sorted(failed) == sorted(
        [
            ("order_undetermined", "timeout"),
            ("order_undetermined", "deadline"),
            ("knowledge_source_unclear", "deadline"),
            ("attribute_surface_differs", "deadline"),
        ]
    )
    # 부른 두 후보는 J1 둘이다(J1 → J3 → J2 차례) — J3·J2 후보 글은 모델에 가지 않았다.
    assert all("규칙: order_undetermined" in prompt for prompt in adapter.judged)


@pytest.mark.parametrize(
    ("verdict", "expected"),
    [
        pytest.param("conflict", [("warning", "knowledge_source_unclear", "J3"), ("warning", "llm_conflict", "J3")],
                     id="conflict"),
        pytest.param("no_conflict", [], id="no_conflict"),
        pytest.param("unsure", [], id="unsure"),
    ],
)
async def test_knowledge_source_unclear_stays_only_when_the_judge_calls_it_a_conflict(
    db_session: AsyncSession, verdict: Verdict, expected: list[tuple[str, str, str]]
) -> None:
    """앎 출처 불명은 오탐이 커 판정이 충돌이라 할 때만 남는다 — 충돌이 아니거나 모르겠다면 경고가 하나도 남지 않는다."""
    commit_id = await _story(db_session, RULES, build_judge(_Adapter(_always(verdict)).resolver()))

    assert await _status(db_session, commit_id) == "committed"
    assert _summary(await _findings(db_session, commit_id)) == expected


async def test_a_judge_stage_that_breaks_leaves_the_candidates_unjudged_and_commits(db_session: AsyncSession) -> None:
    """판정 함수 자체가 예외를 내도(호출 실패를 경고로 바꾸기 전에 깨진 경우) 확정은 실패하지 않는다 — 후보 경고가 판정 없이
    그대로 남고 커밋된다."""

    async def broken(
        session_factory: SessionFactory, commit: CommitRef, candidates: Sequence[JudgeCandidate]
    ) -> list[WarningDraft]:
        raise RuntimeError("합성 고장")

    commit_id = await _story(db_session, [*RULES, _j1()], broken)

    assert await _status(db_session, commit_id) == "committed"
    assert _summary(await _findings(db_session, commit_id)) == [
        ("warning", "knowledge_source_unclear", "J3"), ("warning", "order_undetermined", "J1"),
    ]


async def test_judge_warnings_ride_along_on_a_blocked_commit(db_session: AsyncSession) -> None:
    """차단 결과가 있어도 판정은 돌고 그 결과는 경고로만 덧붙는다 — 확정은 구조 규칙의 차단 때문에 `blocked` 이고, 차단 행은
    구조 규칙이 낸 하나뿐이다."""
    adapter = _Adapter(_always("conflict"))
    commit_id = await _story(db_session, [_Blocks(), _j1()], build_judge(adapter.resolver()))

    assert await _status(db_session, commit_id) == "blocked"
    assert _summary(await _findings(db_session, commit_id)) == [
        ("block", "immutable_attribute_mismatch", None),
        ("warning", "llm_conflict", "J1"),
        ("warning", "order_undetermined", "J1"),
    ]


async def test_the_candidate_input_carries_chapters_kinds_lines_cut_quotes_and_order(db_session: AsyncSession) -> None:
    """후보 글은 코어가 조립한다 — 규칙 이름, 항목마다 화 번호·종류·한 줄 서술·근거 블록에서 위치로 잘라 낸 원고 구절, 두
    항목의 이야기 순서."""
    adapter = _Adapter(_always("unsure"))
    await _story(db_session, RULES, build_judge(adapter.resolver()))

    (prompt,) = adapter.judged
    lines = prompt.splitlines()
    assert lines == [
        "규칙: knowledge_source_unclear",
        "항목 1: 2화 · 앎",
        "서술: 둘 이(가) 아는 것: 하나 — 속성 성격: 차분함",
        f"근거: {SECOND[2]}",
        "항목 2: 1화 · 사실",
        "서술: 하나 — 속성 성격: 차분함",
        f"근거: {FIRST[1]}",
        "순서: 항목 2 가 앞선다",
    ]


# ── 판정 단계 하나 ─────────────────────────────────────────────────

_REF = CommitRef(
    commit_id=uuid.uuid4(), novel_id=uuid.uuid4(), chapter_id=uuid.uuid4(), chapter_revision_id=uuid.uuid4(),
    chapter_ordinal=9, scope="character",
)
_RULE_OF: dict[str, WarningRule] = {
    "J1": "order_undetermined", "J2": "attribute_surface_differs", "J3": "knowledge_source_unclear"
}


def _candidate(mark: str, earlier: int) -> JudgeCandidate:
    warning = WarningDraft(rule=_RULE_OF[mark], item_ids=(uuid.uuid4(), uuid.uuid4()), payload={"judge": mark})
    return JudgeCandidate(warning=warning, chapters=(earlier, 9), text=f"합성 후보 {mark} {earlier}화")


async def test_at_most_ten_candidates_are_judged_in_rule_then_chapter_order(db_session: AsyncSession) -> None:
    """후보 12건을 섞어 넘긴다 — J1 여덟(앞 화 1~8), J3 셋(1~3), J2 하나. 부르는 차례는 J1 → J3 → J2, 같은 규칙 안은 화 번호
    순이고 10건에서 멈춘다. 넘친 J3(3화)은 버리고, 넘친 J2 는 판정 없이 후보 경고만 남긴다."""
    j1 = [_candidate("J1", earlier) for earlier in (5, 2, 8, 1, 7, 3, 6, 4)]
    j3 = [_candidate("J3", earlier) for earlier in (3, 1, 2)]
    j2 = [_candidate("J2", 1)]
    adapter = _Adapter(_always("conflict"))
    shuffled = [j2[0], *j3[:1], *j1[:4], *j3[1:], *j1[4:]]

    warnings = await build_judge(adapter.resolver())(savepoint_factory(db_session), _REF, shuffled)

    def by_chapter(candidates: list[JudgeCandidate]) -> list[JudgeCandidate]:
        return sorted(candidates, key=lambda candidate: candidate.chapters)

    expected = [*by_chapter(j1), *by_chapter(j3)][:JUDGE_MAX_CANDIDATES]
    assert JUDGE_MAX_CANDIDATES == 10
    assert {warning.severity for warning in warnings} == {"warning"}
    assert adapter.judged == [candidate.text for candidate in expected]
    conflicts = [warning.item_ids for warning in warnings if warning.rule == "llm_conflict"]
    assert conflicts == [candidate.warning.item_ids for candidate in expected]
    kept = [warning.item_ids for warning in warnings if warning.rule != "llm_conflict"]
    assert sorted(kept) == sorted(candidate.warning.item_ids for candidate in [*expected, *j2])
    dropped = by_chapter(j3)[-1].warning.item_ids
    assert all(warning.item_ids != dropped for warning in warnings)


async def test_each_call_is_cut_at_its_own_limit_and_the_rest_wait_for_nothing(db_session: AsyncSession) -> None:
    """모델이 답하지 않는다(끝없이 기다린다). 기한을 줄여(총 1초, 호출당 0.25초) 실제 시간으로 본다 — 호출마다 자기 상한에서
    끊기고(첫 실패는 시간 초과), 총 기한이 차면 남은 후보는 부르지 않고 `deadline` 으로 끝난다. 판정 단계 전체가 총 기한 안에
    돌아온다."""

    async def answer(candidate: str) -> JudgeVerdict:
        await asyncio.Event().wait()
        raise AssertionError("닿지 않는다")

    adapter = _Adapter(answer)
    judge = build_judge(adapter.resolver(), budget_seconds=1.0, call_seconds=0.25)
    candidates = [_candidate("J1", earlier) for earlier in range(1, 6)]

    started = time.monotonic()
    async with asyncio.timeout(10):
        warnings = await judge(savepoint_factory(db_session), _REF, candidates)
    elapsed = time.monotonic() - started

    failures = [warning.payload["failure"] for warning in warnings if warning.rule == "judge_failed"]
    assert len(failures) == len(candidates)
    assert failures[0] == "timeout"
    assert failures[-1] == "deadline"
    assert 1 <= len(adapter.judged) < len(candidates)
    assert elapsed < 4


def test_the_judge_stage_can_only_return_warnings() -> None:
    """판정 결과는 어떤 경우에도 차단 사유가 되지 않는다 — 판정 단계의 반환 타입은 경고 목록이고, 그 타입은 차단 등급도 차단
    이름도 받지 않는다."""
    assert get_type_hints(Judge.__call__)["return"] == list[WarningDraft]
    with pytest.raises(ValidationError):
        WarningDraft.model_validate({"severity": "block", "rule": "llm_conflict", "item_ids": ()})
    with pytest.raises(ValidationError):
        WarningDraft.model_validate({"rule": "immutable_attribute_mismatch", "item_ids": ()})
