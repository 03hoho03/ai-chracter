"""정본 기억 측정 하네스의 전 경로 — 합성 세트 읽기 → 격리 DB 에 심기 → 확정과 워커 대신 `run_until_idle` → 결과 수집 →
지표·구간 → 보고서, 그리고 원장의 멈춤 선과 로컬 DB 가드.

모델은 가짜 해석기다. 명세에서 정답 출력을 만들고, 일부러 틀린 출력(사건 빠뜨림·없는 인용·첫 시도 스키마 실패)을 섞어 지표가
그 틀림을 세는지 본다. 원고는 합성 문장이다."""

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import api.novel_bible.entry as entry
from api.core.config import settings
from api.db.models import Novel, NovelChapter, User
from api.novel_bible.core.types import BibleSnapshot
from memory_eval.ledger import EXIT_BUDGET, Ledger
from novel_bible_eval.__main__ import main, synthetic
from novel_bible_eval.fake_llm import FakeLLM, Faults
from novel_bible_eval.run import BudgetHalt, ChapterOutcome, Meter, extract_chapters, run_set
from novel_bible_eval.seed import EVAL_EMAIL_DOMAIN, seed_novel
from novel_bible_eval.spec import load_set
from novel_bible_fakes import FakeRule, savepoint_factory

FIXTURE = Path(__file__).parent / "fixtures" / "novel_bible_eval" / "small_set.json"
NOVEL = "synthetic-1"


@pytest.fixture(autouse=True)
def _bible_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novel_bible_enabled", True)


def _statuses(outcomes: list[ChapterOutcome]) -> list[tuple[int, str | None, str]]:
    return [(outcome.ordinal, outcome.probe, outcome.status) for outcome in outcomes]


async def test_the_fake_run_seeds_confirms_drains_and_reports_what_it_got_wrong(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    eval_set = load_set(FIXTURE)
    fake = FakeLLM(
        eval_set,
        faults=Faults(
            omit=frozenset({(NOVEL, "1", 1)}), misquote=frozenset({(NOVEL, "2", 0)}),
            schema_failure=frozenset({(NOVEL, "3")}),
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
    assert _statuses(outcomes) == [
        (1, None, "committed"), (2, None, "committed"), (3, None, "committed"),
        (4, "dead-returns", "committed"), (4, "unrelated-memory", "committed"), (4, "harbor-memory", "committed"),
        (4, "rumor", "committed"),
    ]
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
    assert report["slots"] == ["events"]
    events = report["metrics"]["recall.events"]["repeats"][0]
    assert (events["k"], events["n"]) == (6, 8)  # 빠뜨린 1 + 인용이 틀려 버린 1
    quote = report["metrics"]["quote_rate"]
    assert (quote["k"], quote["n"]) == (10, 11)  # 기본 6 + 탐침 4 / 거기에 인용 실패 1
    schema = report["metrics"]["schema_failure_rate"]
    assert (schema["k"], schema["n"]) == (1, 8)
    false_positive = report["metrics"]["block_false_positive"]
    assert (false_positive["k"], false_positive["n"]) == (0, 5)
    assert false_positive["upper"] == pytest.approx(1 - 0.05 ** (1 / 5))
    assert false_positive["pass"] is True
    assert (report["metrics"]["block_recall"]["k"], report["metrics"]["block_recall"]["n"]) == (0, 1)
    # 지식 슬롯이 등록부에 없으면 방향 오류 지표도 없다.
    assert "direction_error" not in report["metrics"]
    markdown = (run_dir / "report.md").read_text()  # cite-ok: 문서가 아니라 하네스가 쓴 출력 파일 이름
    assert "block_false_positive" in markdown and "recall.events" in markdown


async def test_blocked_base_chapters_count_as_false_positives_and_leave_their_probes_out(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    def chapters_two_and_four(snapshot: BibleSnapshot) -> tuple[object, ...]:
        events = snapshot.events or ()
        return tuple(e.id for e in events if e.id in snapshot.new_ids and e.chapter_ordinal in (2, 4))

    rule = FakeRule(pick=chapters_two_and_four, rule="exit_then_appearance", slots=frozenset({"events"}))  # type: ignore[arg-type]
    monkeypatch.setattr(entry, "RULES", [rule])
    eval_set = load_set(FIXTURE)
    fake = FakeLLM(eval_set)
    meter = Meter()
    outcomes = await run_set(savepoint_factory(db_session), meter.wrap(fake.resolver()), eval_set, slots=fake.slots)
    assert [outcome.status for outcome in outcomes if outcome.probe is None] == ["committed", "blocked", "committed"]
    assert outcomes[1].block_rules == ["exit_then_appearance"]

    from novel_bible_eval import metrics

    summary = metrics.blocking(eval_set, outcomes)
    # 차단된 기본 화 1 + 짝 화 1 만 기대는 비충돌 탐침의 차단 1 / 기본 3 + 그 탐침 1
    assert (summary.false_positive.k, summary.false_positive.n) == (2, 4)
    assert summary.excluded == {"conflict": 1, "warning": 1, "non_conflict": 1}
    assert summary.undeterminable


async def test_the_halt_line_stops_the_run_before_the_call_that_would_cross_it(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    eval_set = load_set(FIXTURE)
    # 호출 하나가 단가표로 $20 — 출력 800만 토큰 × $2.50/100만.
    fake = FakeLLM(eval_set, model="gemini-3.5-flash-lite", prompt_tokens=0, output_tokens=8_000_000)
    ledger = Ledger(tmp_path / "ledger.jsonl", cap_usd=60, halt_usd=50, bundle="ci")
    meter = Meter(ledger=ledger, estimate_usd=20)
    run_dir = tmp_path / "run"
    code = await synthetic(
        savepoint_factory(db_session), meter.wrap(fake.resolver()), eval_set, run_dir, adapter="fake", meter=meter,
        slots=fake.slots,
    )
    assert code == EXIT_BUDGET
    assert fake.calls == 2  # $40 뒤의 셋째 호출은 견적을 더하면 $60 이라 부르기 전에 멈춘다
    rows = ledger.rows()
    assert [row["bundleCumulativeUsd"] for row in rows] == pytest.approx([20, 40])
    report = json.loads((run_dir / "report.json").read_text())
    assert "멈춤 선" in report["halted"]
    outcomes = json.loads((run_dir / "outcomes.json").read_text())
    assert [row["ordinal"] for row in outcomes] == [1, 2]


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
