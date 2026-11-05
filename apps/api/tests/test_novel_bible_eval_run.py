"""정본 기억 측정 하네스의 전 경로 — 합성 세트 읽기 → 격리 DB 에 심기 → 확정과 워커 대신 `run_until_idle` → 결과 수집 →
지표·구간 → 보고서, 그리고 원장의 멈춤 선과 로컬 DB 가드.

모델은 가짜 해석기다. 명세에서 정답 출력을 만들고, 일부러 틀린 출력(사건 빠뜨림·없는 인용·첫 시도 스키마 실패·사실의 불변 표시
뒤집기·심지 않은 사실·지식의 앎 주체와 명제 주어 뒤바꾸기)을 섞어 지표가 그 틀림을 세는지 본다. 가짜 해석기는 사건·사실·지식
세 슬롯을 내므로 화마다 호출이 셋이고, 모호 후보 판정이 있는 화는 후보마다 하나 더다 — 이 픽스처에서는 1화(1화 앎의 출처가
서술되지 않은 후보)와 경고 기대 탐침(순서 미정 후보)이다. 원고는 합성 문장이다."""

import json
from pathlib import Path
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import api.novel_bible.entry as entry
from api.core.config import settings
from api.db.models import ChatMemoryFact, Novel, NovelChapter, User
from api.db.models.novel_bible import NovelBibleAdaptationCandidate, NovelBibleEvidence
from api.db.models.novel_bible_events import NovelBibleEventRelation
from api.novel_bible.core.types import BibleSnapshot, Proposal, RenderedPrompt
from api.novel_bible.ids import OperationKey
from memory_eval.ledger import EXIT_BUDGET, Ledger
from novel_bible_eval import labels
from novel_bible_eval.__main__ import _outcomes, _parser, _run, extract, main, synthetic
from novel_bible_eval.fake_llm import FakeLLM, Faults
from novel_bible_eval.run import BudgetHalt, ChapterOutcome, Meter, extract_chapters, run_set
from novel_bible_eval.seed import EVAL_EMAIL_DOMAIN, seed_novel
from novel_bible_eval.spec import EvalSet, load_set
from novel_bible_fakes import FakeRule, savepoint_factory

FIXTURE = Path(__file__).parent / "fixtures" / "novel_bible_eval" / "small_set.json"
NOVEL = "synthetic-1"
T = TypeVar("T", bound=BaseModel)


class _Cut(BaseException):
    """Ctrl-C 처럼 코어가 작업 실패로 삼키지 않는 끊김."""


class _CutAfter(FakeLLM):
    """`calls` 번 부른 뒤의 호출에서 끊긴다."""

    def __init__(self, eval_set: Any, *, calls: int) -> None:
        super().__init__(eval_set)
        self._limit = calls

    async def structured(
        self, prompt: RenderedPrompt, schema: type[T], *, records: list[dict[str, Any]], stage: OperationKey
    ) -> T:
        if self.calls == self._limit:
            raise _Cut
        return await super().structured(prompt, schema, records=records, stage=stage)


@pytest.fixture(autouse=True)
def _bible_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novel_bible_enabled", True)


def _statuses(outcomes: list[ChapterOutcome]) -> list[tuple[int, str | None, str]]:
    return [(outcome.ordinal, outcome.probe, outcome.status) for outcome in outcomes]


# 합성 세트를 실제 규칙으로 확정한 끝 상태 — 기본 화 셋과 비충돌·경고 기대 탐침은 커밋되고 충돌 탐침 하나만 막힌다.
_WITH_THE_CONFLICT_PROBE_BLOCKED = [
    (1, None, "committed"), (2, None, "committed"), (3, None, "committed"),
    (4, "dead-returns", "blocked"), (4, "unrelated-memory", "committed"), (4, "harbor-memory", "committed"),
    (4, "rumor", "committed"),
]


async def test_the_fake_run_seeds_confirms_drains_and_reports_what_it_got_wrong(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    eval_set = load_set(FIXTURE)
    fake = FakeLLM(
        eval_set,
        faults=Faults(
            omit=frozenset({(NOVEL, "1", 1)}), misquote=frozenset({(NOVEL, "2", 0)}),
            schema_failure=frozenset({(NOVEL, "3")}), flip_immutable=frozenset({(NOVEL, "3", 0)}),
            extra_fact=frozenset({(NOVEL, "1")}),
        ),
    )
    meter = Meter()
    run_dir = tmp_path / "run"
    code = await synthetic(
        savepoint_factory(db_session), meter.wrap(fake.resolver()), eval_set, run_dir, adapter="fake", meter=meter,
        slots=fake.slots,
    )
    assert code == 0

    outcomes = [ChapterOutcome.model_validate(row) for row in json.loads((run_dir / "outcomes.json").read_text())]
    # 충돌 탐침은 2화에 숨진 인물이 4화 주선 장면에 나오는 화라 실제 규칙이 사망 뒤 등장으로 막는다. 나머지는 막지 않는다.
    assert _statuses(outcomes) == _WITH_THE_CONFLICT_PROBE_BLOCKED
    assert outcomes[3].block_rules == ["exit_then_appearance"]
    # 경고 기대 탐침은 숨진 인물이 관계 없는 회상 속에 살아 있다가 그 뒤 주선 장면에 나오는 화다. 그 삶이 죽음과 순서가 미정이라
    # 차단 대신 순서 미정 경고가 난다.
    assert "order_undetermined" in outcomes[4].warning_rules
    # 탐침 화는 묶음 삭제로 지웠고 그 화의 정본 기억 확정도 함께 사라졌다.
    assert all(outcome.rows_left == 0 for outcome in outcomes if outcome.probe is not None)
    eval_chapters = (
        select(func.count())
        .select_from(NovelChapter)
        .join(Novel, Novel.id == NovelChapter.novel_id)
        .join(User, User.id == Novel.user_id)
        .where(User.email.like(f"%@{EVAL_EMAIL_DOMAIN}"))
    )
    assert await db_session.scalar(eval_chapters) == 3

    report = json.loads((run_dir / "report.json").read_text())
    assert report["slots"] == ["events", "facts", "knowledge"]
    events = report["metrics"]["recall.events"]["repeats"][0]
    assert (events["k"], events["n"]) == (6, 8)  # 빠뜨린 1 + 인용이 틀려 버린 1
    # 사실은 원자 명제 단위다. 3화의 불변 속성은 불변 표시를 뒤집어 내 맞히지 못했고, 1화에는 심지 않은 사실이 하나 더 있다.
    facts = report["metrics"]["recall.facts"]["repeats"][0]
    assert (facts["k"], facts["n"]) == (4, 5)
    precision = report["metrics"]["precision.facts"]["repeats"][0]
    assert (precision["k"], precision["n"]) == (4, 6)
    assert report["metrics"]["precision.facts"]["pass"] is None  # 합성 세트의 사실 정밀도는 합격선이 없다
    quote = report["metrics"]["quote_rate"]
    assert (quote["k"], quote["n"]) == (20, 21)  # 사건 기본 6 + 탐침 5, 사실 기본 6 + 탐침 1, 지식 2 / 거기에 사건 인용 실패 1
    schema = report["metrics"]["schema_failure_rate"]
    # 기본 3화·탐침 4 에 슬롯 셋씩 + 3화 첫 호출의 재시도 + 경고 기대 탐침의 판정 하나. 1화 앎의 출처 후보는 그 앎이 드러나는
    # 사건을 빠뜨려 이 실행에서는 나지 않는다.
    assert (schema["k"], schema["n"]) == (1, 23)
    false_positive = report["metrics"]["block_false_positive"]
    assert (false_positive["k"], false_positive["n"]) == (0, 5)
    assert false_positive["upper"] == pytest.approx(1 - 0.05 ** (1 / 5))
    assert false_positive["pass"] is True
    assert (report["metrics"]["block_recall"]["k"], report["metrics"]["block_recall"]["n"]) == (1, 1)
    assert (report["metrics"]["warning_recall"]["k"], report["metrics"]["warning_recall"]["n"]) == (1, 1)
    # 1화·3화에 심은 지식 둘을 바른 방향으로 냈다. 1화 앎이 드러나는 문단을 덮은 사건은 빠뜨렸지만 지식 제안은 남는다.
    knowledge = report["metrics"]["recall.knowledge"]["repeats"][0]
    assert (knowledge["k"], knowledge["n"]) == (2, 2)
    direction = report["metrics"]["direction_error"]["repeats"][0]
    assert (direction["k"], direction["n"]) == (0, 2)
    markdown = (run_dir / "report.md").read_text()  # cite-ok: 문서가 아니라 하네스가 쓴 출력 파일 이름
    assert "block_false_positive" in markdown and "recall.events" in markdown


async def test_blocked_base_chapters_count_as_false_positives_and_leave_their_probes_out(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    def chapters_three_and_four(snapshot: BibleSnapshot) -> tuple[object, ...]:
        events = snapshot.events or ()
        return tuple(e.id for e in events if e.id in snapshot.new_ids and e.chapter_ordinal in (3, 4))

    rule = FakeRule(pick=chapters_three_and_four, rule="exit_then_appearance", slots=frozenset({"events"}))  # type: ignore[arg-type]
    monkeypatch.setattr(entry, "RULES", [rule])
    eval_set = load_set(FIXTURE)
    fake = FakeLLM(eval_set)
    meter = Meter()
    outcomes = await run_set(savepoint_factory(db_session), meter.wrap(fake.resolver()), eval_set, slots=fake.slots)
    assert [outcome.status for outcome in outcomes if outcome.probe is None] == ["committed", "committed", "blocked"]
    assert outcomes[2].block_rules == ["exit_then_appearance"]

    from novel_bible_eval import metrics

    summary = metrics.blocking(eval_set, outcomes)
    # 3화에 기대는 탐침은 소문 탐침 하나라 그것만 빠진다. 차단된 기본 화 1 + 1·2화에만 기대는 비충돌 탐침의 차단 1 / 기본 3 +
    # 그 탐침 1
    assert (summary.false_positive.k, summary.false_positive.n) == (2, 4)
    assert summary.excluded == {"non_conflict": 1}
    assert summary.undeterminable


async def test_a_swapped_knower_and_subject_through_the_real_knowledge_slot_is_one_direction_error(
    db_session: AsyncSession,
) -> None:
    # 1화에 심은 지식 하나(도윤이 서하의 등불 소지를 안다)를 실제 지식 슬롯의 검증·확정을 지난 작업 제안에서 센다. 3화의 지식
    # (서하가 등대의 세워진 때를 안다)은 그대로 둔다. 바르게 내면 방향 오류 0/2·재현 2/2, 1화 지식의 앎 주체와 명제 주어를 뒤바꿔
    # 내면 방향 오류 1/2·재현 1/2 이다.
    from novel_bible_eval import metrics

    eval_set = load_set(FIXTURE)
    factory = savepoint_factory(db_session)
    counted: dict[str, tuple[list[tuple[int, int]], list[tuple[int, int]]]] = {}
    for name, faults in (("clean", Faults()), ("swapped", Faults(swap_knower=frozenset({(NOVEL, "1", 0)})))):
        fake = FakeLLM(eval_set, faults=faults)
        assert "knowledge" in fake.slots
        outcomes = await run_set(factory, Meter().wrap(fake.resolver()), eval_set, slots=fake.slots)
        assert _statuses(outcomes) == _WITH_THE_CONFLICT_PROBE_BLOCKED
        direction = metrics.direction_error(eval_set, outcomes)
        assert direction is not None
        recall = metrics.recall(eval_set, outcomes)["knowledge"]
        counted[name] = ([(r.k, r.n) for r in direction], [(r.k, r.n) for r in recall])
    assert counted == {"clean": ([(0, 2)], [(2, 2)]), "swapped": ([(1, 2)], [(1, 2)])}


async def test_the_fake_answers_carry_the_planted_relation_differences_and_proposition_subject_kind(
    db_session: AsyncSession,
) -> None:
    # 가짜 해석기가 명세의 회상 관계·원작과 다른 곳·플레이와 다른 곳·지식 명제의 주어 종류를 내고, 실제 슬롯의 검증과 확정을
    # 지나 정본 기억 행이 된다 — 표지(`P1`·`S`)는 문안에 실린 앞 화 사건·원작·플레이 목록에서 찾은 것이라, 심기가 원작·방·화
    # 순서를 틀리면 여기서 빠진다.
    eval_set = load_set(FIXTURE)
    fake = FakeLLM(eval_set)
    outcomes = await run_set(savepoint_factory(db_session), Meter().wrap(fake.resolver()), eval_set, slots=fake.slots)
    assert _statuses(outcomes) == _WITH_THE_CONFLICT_PROBE_BLOCKED
    # 3화 회상 사건이 1화 첫 주선 사건보다 앞이다.
    relations = (
        await db_session.execute(
            select(NovelBibleEventRelation.relation, NovelChapter.ordinal)
            .join(NovelChapter, NovelChapter.id == NovelBibleEventRelation.to_chapter_id)
        )
    ).all()
    assert [tuple(row) for row in relations] == [("before", 1)]
    # 2화 지도 소지는 플레이와, 3화 등대지기 눈 색은 원작과 다르다 — 각색 후보가 하나씩이다.
    origins = (await db_session.scalars(select(NovelBibleAdaptationCandidate.origin))).all()
    assert sorted(origins) == ["play", "source_canon"]
    # 3화 지식의 명제 주어(등대)는 사물이다. 인물로 내면 같은 이름의 다른 개체·다른 명제 키가 된다.
    (knowledge,) = [job for job in outcomes[2].jobs if job.slot == "knowledge"]
    assert knowledge.proposal is not None
    items = Proposal.model_validate(knowledge.proposal).items
    assert [(item.proposition.subject, item.proposition.subject_kind) for item in items if item.proposition] == [
        ("등대", "object")
    ]


async def test_the_halt_line_stops_the_run_before_the_call_that_would_cross_it(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    eval_set = load_set(FIXTURE)
    # 호출 하나가 단가표로 $20 — 출력 800만 토큰 × $2.50/100만.
    fake = FakeLLM(eval_set, model="gemini-3.5-flash-lite", prompt_tokens=0, output_tokens=8_000_000)
    ledger = Ledger(tmp_path / "ledger.jsonl", cap_usd=120, halt_usd=90, bundle="ci")
    meter = Meter(ledger=ledger, estimate_usd=20)
    run_dir = tmp_path / "run"
    code = await synthetic(
        savepoint_factory(db_session), meter.wrap(fake.resolver()), eval_set, run_dir, adapter="fake", meter=meter,
        slots=fake.slots,
    )
    assert code == EXIT_BUDGET
    # 1화의 세 슬롯 호출과 판정 하나로 $80 — 2화 첫 호출은 견적을 더하면 $100 이라 부르기 전에 멈춘다
    assert fake.calls == 4
    rows = ledger.rows()
    assert [row["bundleCumulativeUsd"] for row in rows] == pytest.approx([20, 40, 60, 80])
    report = json.loads((run_dir / "report.json").read_text())
    assert "멈춤 선" in report["halted"]
    outcomes = json.loads((run_dir / "outcomes.json").read_text())
    assert [row["ordinal"] for row in outcomes] == [1]


async def test_the_label_set_extraction_confirms_the_first_chapters_of_an_existing_novel(
    db_session: AsyncSession,
) -> None:
    eval_set = load_set(FIXTURE)
    factory = savepoint_factory(db_session)
    async with factory() as session, session.begin():
        seeded = await seed_novel(session, eval_set.novels[0])
    fake = FakeLLM(eval_set)
    outcomes = await extract_chapters(factory, Meter().wrap(fake.resolver()), seeded.novel_id, count=2)
    assert [(outcome.ordinal, outcome.status) for outcome in outcomes] == [(1, "committed"), (2, "committed")]
    assert all(job.proposal is not None for outcome in outcomes for job in outcome.jobs)


def test_the_entry_point_refuses_a_database_that_is_not_local(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://app:secret@db.internal:5432/app")
    with pytest.raises(SystemExit, match="로컬 DB"):
        main(["synthetic", "--set", str(tmp_path / "missing.json"), "--run-dir", str(tmp_path / "run"),
              "--adapter", "gemini", "--bundle", "b1"])
    assert not (tmp_path / "run").exists()


async def test_a_call_whose_model_the_price_table_does_not_know_stops_the_run(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    eval_set = load_set(FIXTURE)
    fake = FakeLLM(eval_set, model="unpriced-synthetic-model")
    meter = Meter(ledger=Ledger(tmp_path / "ledger.jsonl", cap_usd=60, halt_usd=50, bundle="ci"), estimate_usd=1)
    with pytest.raises(BudgetHalt, match="단가"):
        await run_set(savepoint_factory(db_session), meter.wrap(fake.resolver()), eval_set, slots=fake.slots)
    assert fake.calls == 1  # 원가를 모르는 호출을 다시 부르지 않는다


async def test_a_ledger_write_that_fails_for_any_reason_stops_the_run(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_set = load_set(FIXTURE)
    fake = FakeLLM(eval_set)
    ledger = Ledger(tmp_path / "ledger.jsonl", cap_usd=60, halt_usd=50, bundle="ci")

    def unwritable(**_: object) -> None:
        raise OSError("합성 쓰기 실패")

    monkeypatch.setattr(ledger, "append", unwritable)
    meter = Meter(ledger=ledger, estimate_usd=1)
    with pytest.raises(BudgetHalt, match="합성 쓰기 실패"):
        await run_set(savepoint_factory(db_session), meter.wrap(fake.resolver()), eval_set, slots=fake.slots)
    assert fake.calls == 1  # 원장에 적지 못한 호출을 작업 재시도로 다시 부르지 않는다


async def test_an_interrupted_run_still_writes_the_chapters_it_finished(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    eval_set = load_set(FIXTURE)
    fake = _CutAfter(eval_set, calls=7)  # 1화 세 슬롯과 판정 하나, 2화 세 슬롯 — 3화 첫 호출에서 끊긴다
    meter = Meter()
    run_dir = tmp_path / "run"
    with pytest.raises(_Cut):
        await synthetic(
            savepoint_factory(db_session), meter.wrap(fake.resolver()), eval_set, run_dir, adapter="fake",
            meter=meter, slots=fake.slots,
        )
    assert [row["ordinal"] for row in json.loads((run_dir / "outcomes.json").read_text())] == [1, 2]
    report = json.loads((run_dir / "report.json").read_text())
    assert "_Cut" in report["halted"]
    assert report["metrics"]["block_false_positive"]["pass"] is None


async def test_a_halted_extraction_still_writes_the_chapters_it_finished(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    eval_set = load_set(FIXTURE)
    factory = savepoint_factory(db_session)
    async with factory() as session, session.begin():
        seeded = await seed_novel(session, eval_set.novels[0])
    # 호출 하나가 $20 이고 1화는 세 슬롯과 판정 하나, 2화는 세 슬롯이라, $140 뒤 셋째 화의 첫 호출은 견적을 더하면 $160 이라
    # 부르기 전에 멈춘다.
    fake = FakeLLM(eval_set, model="gemini-3.5-flash-lite", prompt_tokens=0, output_tokens=8_000_000)
    meter = Meter(ledger=Ledger(tmp_path / "ledger.jsonl", cap_usd=170, halt_usd=150, bundle="ci"), estimate_usd=20)
    code = await extract(
        factory, meter.wrap(fake.resolver()), seeded.novel_id, tmp_path / "labels", adapter="fake", count=3
    )
    assert code == EXIT_BUDGET
    written = json.loads((tmp_path / "labels" / "extract-fake.json").read_text())
    assert [(row["ordinal"], row["status"]) for row in written["outcomes"]] == [(1, "committed"), (2, "committed")]
    # 결과 파일만 본 사람도 앞 두 화에서 멈춘 결과인지 안다.
    assert "멈춤 선" in written["halted"]
    assert [outcome.ordinal for outcome in _outcomes(tmp_path / "labels" / "extract-fake.json")] == [1, 2]


async def test_a_halted_extraction_leaves_that_adapters_label_verdict_undetermined_through_sheet_and_score(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 두 어댑터가 같은 앞 두 화를 낸다. 하나는 끝까지 돌았고 하나는 셋째 화에서 원장 멈춤으로 끊겼다. 라벨은 전부 맞음·받침이라
    # 갈리는 것은 멈춤뿐이다 — 앞 화 일부만 담긴 추출의 핵심 사실 정밀도로 합격을 내지 않는다.
    eval_set = load_set(FIXTURE)
    factory = savepoint_factory(db_session)
    monkeypatch.setattr("novel_bible_eval.__main__.async_session_factory", factory)
    async with factory() as session, session.begin():
        whole = await seed_novel(session, eval_set.novels[0])
        cut = await seed_novel(session, eval_set.novels[0])
    out = tmp_path / "labels"
    finished = await extract(factory, Meter().wrap(FakeLLM(eval_set).resolver()), whole.novel_id, out,
                             adapter="whole", count=2)
    assert finished == 0
    # 호출 하나가 $20 이고 1화는 세 슬롯과 판정 하나, 2화는 세 슬롯이라, 셋째 화의 첫 호출은 견적을 더하면 $160 이라 부르기 전에
    # 멈춘다.
    fake = FakeLLM(eval_set, model="gemini-3.5-flash-lite", prompt_tokens=0, output_tokens=8_000_000)
    meter = Meter(ledger=Ledger(tmp_path / "ledger.jsonl", cap_usd=170, halt_usd=150, bundle="ci"), estimate_usd=20)
    assert await extract(factory, meter.wrap(fake.resolver()), cut.novel_id, out, adapter="cut", count=3) == EXIT_BUDGET

    await _run(_parser().parse_args([
        "sheet", "--extract", f"whole={out / 'extract-whole.json'}", f"cut={out / 'extract-cut.json'}", "--out", str(out),
    ]))
    rows = labels.sheet_claims((out / "sheet.html").read_text(encoding="utf-8"))
    verdicts = {row["id"]: {"verdict": "correct", "quotes": ["supported"] * len(row["quotes"])} for row in rows}
    result = out / "labels-result.json"
    result.write_text(json.dumps({"labels": verdicts, "missing": {}}), encoding="utf-8")
    await _run(_parser().parse_args(["score", "--key", str(out / "claims-key.json"), "--labels", str(result),
                                     "--out", str(out)]))

    report = json.loads((out / "label-report.json").read_text())["adapters"]
    assert report["whole"]["core_fact_precision"]["pass"] is True
    core = report["cut"]["core_fact_precision"]
    assert (core["value"], core["pass"], core.get("undetermined")) == (1.0, None, "멈춘 실행")
    # 보고서만 본 사람도 어느 어댑터가 왜 멈췄는지 안다.
    assert report["whole"]["halted"] is None
    assert "멈춤 선" in report["cut"]["halted"]


async def test_the_fake_answers_the_judge_so_no_candidate_fails_for_want_of_an_answer(db_session: AsyncSession) -> None:
    # 모호 후보 판정도 같은 해석기로 간다. 경고 기대 탐침의 순서 미정 경고가 판정 후보라, 가짜 해석기가 판정 출력을 내지 못하면
    # 판정 실패 경고가 붙는다. 가짜 해석기는 판단하지 않고 늘 모르겠다고 답한다 — 순서 미정 경고는 후보 경고로만 남는다.
    eval_set = load_set(FIXTURE)
    fake = FakeLLM(eval_set)
    meter = Meter()
    outcomes = await run_set(savepoint_factory(db_session), meter.wrap(fake.resolver()), eval_set, slots=fake.slots)
    assert _statuses(outcomes) == _WITH_THE_CONFLICT_PROBE_BLOCKED
    assert ("conflicts.judge", None) in meter.attempts
    assert [rule for outcome in outcomes for rule in outcome.warning_rules if rule in ("judge_failed", "llm_conflict")] == []
    assert "order_undetermined" in outcomes[4].warning_rules


async def test_the_fake_points_its_play_difference_at_the_row_the_app_keeps_for_that_key(db_session: AsyncSession) -> None:
    # 같은 사실 키의 채팅 기억 행이 둘이면 앱은 뒤에 접힌 행 하나만 싣는다. 명세의 플레이 차이는 그 이긴 행을 가리키고, 가짜
    # 해석기는 문안에 실린 줄에서 그 행의 표지를 찾아 낸다 — 각색 후보의 근거가 이긴 행이다. 진 행은 명세 끝에 두었지만 1화에
    # 접혀 먼저다. 1화에 먼저 접힌 다른 키의 관계 행이 있어 문안의 표지 차례(관계 `P1`, 지도 `P2`)가 명세 차례와 다르다.
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    (kept,) = raw["novels"][0]["play"]
    raw["novels"][0]["play"] += [
        {"visible_from": 1, "subject": "도윤", "object": "서하", "value": "길동무"},
        {**kept, "visible_from": 1, "value": "구겨진 지도"},
    ]
    eval_set = EvalSet.model_validate(raw)
    fake = FakeLLM(eval_set)
    outcomes = await run_set(savepoint_factory(db_session), Meter().wrap(fake.resolver()), eval_set, slots=fake.slots)
    assert _statuses(outcomes) == _WITH_THE_CONFLICT_PROBE_BLOCKED
    shown = (
        await db_session.scalars(
            select(ChatMemoryFact.value)
            .join(NovelBibleEvidence, NovelBibleEvidence.chat_memory_fact_id == ChatMemoryFact.id)
            .where(NovelBibleEvidence.origin == "chat_memory")
        )
    ).all()
    assert list(shown) == [kept["value"]]
