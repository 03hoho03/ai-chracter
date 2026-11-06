"""오라클 실행 — 가짜 해석기가 명세 정답의 모든 칸(사실의 시작 서술·범위, 사건의 사용 포함)을 그대로 내게 하고 합성 세트를 실제
확정·검사 경로로 돌려, 세트 자체의 결함을 한 표로 내는지 본다. 추출이 정답과 같으므로 막힌 기본 화, 기대 규칙으로 안 막힌 충돌
탐침, 기대 경고를 안 낸 경고 기대 탐침, 막힌 비충돌 탐침, 놓친 정답은 모두 세트(또는 규칙) 쪽 결함이다. 원고는 합성 문장이다."""

import copy
import json
from pathlib import Path
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.novel_bible.core.types import RenderedPrompt
from api.novel_bible.ids import OperationKey
from novel_bible_eval import __main__ as entry_point
from novel_bible_eval import compare
from novel_bible_eval.fake_llm import FakeLLM, Faults
from novel_bible_eval.oracle import SetDefects, defects_markdown, set_defects
from novel_bible_eval.report import synthetic_report
from novel_bible_eval.run import ChapterOutcome, JobOutcome, Meter, run_set
from novel_bible_eval.spec import EvalSet, load_set
from novel_bible_fakes import savepoint_factory

FIXTURE = Path(__file__).parent / "fixtures" / "novel_bible_eval" / "oracle_set.json"
T = TypeVar("T", bound=BaseModel)


@pytest.fixture(autouse=True)
def _bible_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novel_bible_enabled", True)


def _raw() -> dict[str, Any]:
    raw: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return copy.deepcopy(raw)


async def _run(db_session: AsyncSession, eval_set: EvalSet, *, oracle: bool = True) -> list[ChapterOutcome]:
    fake = FakeLLM(eval_set, oracle=oracle)
    return await run_set(savepoint_factory(db_session), Meter().wrap(fake.resolver()), eval_set, slots=fake.slots)


def _rows(defects: SetDefects) -> set[tuple[str, str]]:
    return {(row.category, row.where) for row in defects.rows}


async def test_the_oracle_run_over_a_sound_set_blocks_every_conflict_and_finds_no_set_defect(
    db_session: AsyncSession,
) -> None:
    eval_set = load_set(FIXTURE)
    outcomes = await _run(db_session, eval_set)
    by_probe = {outcome.probe: outcome for outcome in outcomes if outcome.probe is not None}
    assert [outcome.status for outcome in outcomes if outcome.probe is None] == ["committed"] * 3
    # 사용을 내야 얻기 전 사용이, 사실의 시작 서술을 내야 일어나기 전 앎이 막힌다.
    assert by_probe["early-lamp"].block_rules == ["use_before_acquisition"]
    assert by_probe["early-knowing"].block_rules == ["knowledge_before_fact"]
    assert by_probe["dead-walks"].block_rules == ["exit_then_appearance"]
    # 돌아옴은 시작 서술이 있어야 영구 퇴장을 되돌리고, 장면 단위 퇴장은 범위가 장면이어야 돌아옴 미서술 경고가 나지 않는다.
    assert by_probe["came-back"].status == "committed"
    assert by_probe["stepped-out"].status == "committed"
    assert "return_unstated" not in by_probe["stepped-out"].warning_rules
    # 이미 지니던 것으로 서술한 소지(시작 서술 거짓)를 먼저 쓰면 차단 대신 시작 미서술 경고다.
    assert "onset_unstated" in by_probe["old-compass"].warning_rules

    defects = set_defects(eval_set, outcomes)
    assert defects.rows == []
    assert defects.notes == []
    assert {slot: [(ratio.k, ratio.n) for ratio in ratios] for slot, ratios in defects.recall.items()} == {
        "events": [(7, 7)], "facts": [(4, 4)], "knowledge": [(1, 1)],
    }
    assert defects.unfilled_total == {"onset": 0, "scope": 0, "uses": 0}
    assert "세트 결함 0건" in defects_markdown(defects)


async def test_the_ci_fake_leaves_onset_scope_and_uses_out_so_the_same_set_shows_those_probes_as_defects(
    db_session: AsyncSession,
) -> None:
    # CI 용 가짜 해석기는 정답 일부만 낸다(시작 서술 늘 거짓, 범위는 불변 여부로만, 사용 없음). 같은 세트를 그 모드로 돌리면 그
    # 칸에 기대는 탐침이 결함으로 잡힌다 — 오라클 모드가 그 칸을 실제로 낸다는 대조다.
    eval_set = load_set(FIXTURE)
    defects = set_defects(eval_set, await _run(db_session, eval_set, oracle=False))
    assert _rows(defects) == {
        ("conflict_missed", "oracle-1 탐침 early-lamp"),
        ("conflict_missed", "oracle-1 탐침 early-knowing"),
        ("warning_missed", "oracle-1 탐침 old-compass"),
        ("non_conflict_blocked", "oracle-1 탐침 came-back"),
    }


def test_the_oracle_refuses_injected_faults() -> None:
    with pytest.raises(ValueError, match="오라클"):
        FakeLLM(load_set(FIXTURE), oracle=True, faults=Faults(extra_fact=frozenset({("oracle-1", "1")})))


async def test_a_base_chapter_with_an_appearance_after_a_planted_death_shows_as_a_blocked_base_chapter(
    db_session: AsyncSession,
) -> None:
    raw = _raw()
    raw["novels"][0]["chapters"][2]["events"][0]["present"].append("주원")  # 2화에 숨진 인물이 3화 주선 장면에 선다
    eval_set = EvalSet.model_validate(raw)
    defects = set_defects(eval_set, await _run(db_session, eval_set))
    (blocked,) = [row for row in defects.rows if row.category == "blocked_base"]
    assert blocked.where == "oracle-1 3화 반복 1"
    assert "exit_then_appearance" in blocked.detail
    # 앞선 정본 항목은 화·내용으로, 막힌 확정의 새 항목은 행이 없어 새 항목으로 적는다.
    assert blocked.items == ("2화 사실 주원 · life: dead", "이번 화 새 항목")
    # 3화에 기대는 탐침은 정본 불완전이라 판정에 쓰지 못한 확정으로 따로 센다.
    assert {row.where for row in defects.rows if row.category == "unjudged"} == {
        "oracle-1 탐침 early-knowing", "oracle-1 탐침 came-back", "oracle-1 탐침 stepped-out",
    }
    markdown = defects_markdown(defects)
    assert "(a) 막힌 기본 화" in markdown and "2화 사실 주원" in markdown


async def test_a_conflict_probe_whose_acquisition_leaves_onset_unwritten_is_flagged_with_that_unfilled_field(
    db_session: AsyncSession,
) -> None:
    raw = _raw()
    del raw["novels"][0]["probes"][0]["chapter"]["facts"][0]["onset"]  # 얻기 전 사용 탐침의 획득 사실
    eval_set = EvalSet.model_validate(raw)
    defects = set_defects(eval_set, await _run(db_session, eval_set))
    (row,) = defects.rows
    assert (row.category, row.where) == ("conflict_missed", "oracle-1 탐침 early-lamp")
    assert "use_before_acquisition" in row.detail and "onset_unstated" in row.detail
    assert row.unfilled == ("탐침 사실 1 onset",)
    assert defects.unfilled_total == {"onset": 1, "scope": 0, "uses": 0}
    assert "정답 칸 미기입" in defects_markdown(defects)


async def test_an_answer_the_slot_drops_shows_as_a_missed_answer_and_lowers_that_slots_recall(
    db_session: AsyncSession,
) -> None:
    # 사실 슬롯은 유지가 거짓인 생사 사실을 버린다. 명세는 그 정답을 받으므로, 오라클이 그대로 내도 놓친 정답으로 남는다.
    raw = _raw()
    raw["novels"][0]["chapters"][1]["facts"][0]["holds"] = False
    eval_set = EvalSet.model_validate(raw)
    defects = set_defects(eval_set, await _run(db_session, eval_set))
    missed = [row for row in defects.rows if row.category == "answer_missed"]
    assert [(row.where, row.detail) for row in missed] == [("oracle-1 2화 반복 1", "facts 사실 1(주원 life: dead)")]
    assert [(ratio.k, ratio.n) for ratio in defects.recall["facts"]] == [(3, 4)]
    # 숨짐이 정본에 없으니 사망 뒤 등장 탐침도 막히지 않는다.
    assert ("conflict_missed", "oracle-1 탐침 dead-walks") in _rows(defects)


def test_the_oracle_command_needs_no_ledger_and_refuses_one(tmp_path: Path) -> None:
    parser = entry_point._parser()
    base = ["synthetic", "--set", str(FIXTURE), "--run-dir", str(tmp_path / "run")]
    assert parser.parse_args([*base, "--oracle"]).oracle is True
    with pytest.raises(SystemExit, match="원장"):
        entry_point._check_synthetic_args(parser.parse_args(base))
    with pytest.raises(SystemExit, match="오라클"):
        entry_point._check_synthetic_args(parser.parse_args([*base, "--oracle", "--ledger", str(tmp_path / "l.jsonl")]))


async def test_the_oracle_command_runs_the_set_with_the_fake_and_writes_the_report_and_the_defect_table(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(entry_point, "async_session_factory", savepoint_factory(db_session))

    def no_paid_resolver() -> None:
        raise AssertionError("오라클 실행은 실제 해석기를 만들지 않는다")

    monkeypatch.setattr(entry_point, "build_resolver", no_paid_resolver)
    run_dir = tmp_path / "run"
    args = entry_point._parser().parse_args(["synthetic", "--oracle", "--set", str(FIXTURE), "--run-dir", str(run_dir)])
    assert await entry_point._run(args) == 0
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert (report["adapter"], report["oracle"]) == ("oracle", True)
    # 호출 기록의 모델 칸도 `oracle` 이다 — 가짜의 기본 모델 id 가 실측 모델처럼 찍히지 않는다. 단가표에 없어 원가는 0 이다.
    assert {(row["backend"], row["model"]) for row in report["models"]} == {("fake", "oracle")}
    assert report["cost"]["usd"] == 0
    markdown = (run_dir / "report.md").read_text(encoding="utf-8")  # cite-ok: 문서가 아니라 하네스가 쓴 출력 파일 이름
    assert "오라클 실행 — 추출 정확도가 아니라 세트·규칙 정합 확인" in markdown.splitlines()[2]
    defects = (run_dir / "set-defects.md").read_text(encoding="utf-8")  # cite-ok: 하네스가 쓴 출력 파일 이름
    assert "세트 결함 0건" in defects


class _Cut(BaseException):
    """Ctrl-C·DB 오류처럼 실행을 끊는다 — 코어의 작업 실행은 `Exception` 을 작업 실패로 삼키므로 그 밖의 예외다."""


class _CutAtProbe(FakeLLM):
    """명세 정답을 그대로 내다가 `marker` 글이 든 문안(첫 탐침)에서 끊는다."""

    def __init__(self, eval_set: EvalSet, marker: str) -> None:
        super().__init__(eval_set, oracle=True)
        self._marker = marker

    async def structured(
        self, prompt: RenderedPrompt, schema: type[T], *, records: list[dict[str, Any]], stage: OperationKey
    ) -> T:
        if self._marker in prompt.prompt:
            raise _Cut("탐침 단계에서 끊김")
        return await super().structured(prompt, schema, records=records, stage=stage)


async def test_an_oracle_run_cut_off_at_the_probes_writes_an_undeterminable_defect_table_not_zero_defects(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    # 기본 화는 모두 깨끗하게 돌고 탐침 단계에서 끊긴다 — 있는 결과만 보면 결함 행이 없지만, 돌지 않은 탐침이 어느 갈래에도 없다.
    eval_set = load_set(FIXTURE)
    fake = _CutAtProbe(eval_set, eval_set.novels[0].probes[0].chapter.paragraphs[0])
    meter = Meter()
    run_dir = tmp_path / "run"
    with pytest.raises(_Cut):  # 예외가 올라가므로 프로세스도 0 이 아닌 값으로 끝난다
        await entry_point.synthetic(
            savepoint_factory(db_session), meter.wrap(fake.resolver()), eval_set, run_dir, adapter="oracle",
            meter=meter, slots=fake.slots, oracle=True,
        )
    defects = (run_dir / "set-defects.md").read_text(encoding="utf-8")  # cite-ok: 하네스가 쓴 출력 파일 이름
    head = defects.splitlines()[:6]
    assert any("판정 불가" in line and line.startswith("#") for line in head)
    assert any("_Cut" in line for line in head)
    assert "세트 결함 0건" not in defects


async def test_a_run_folder_with_a_paid_result_refuses_the_oracle_and_one_with_an_oracle_result_refuses_a_paid_run(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    factory = savepoint_factory(db_session)
    monkeypatch.setattr(entry_point, "async_session_factory", factory)
    paid_dir = tmp_path / "paid"
    paid_dir.mkdir()
    paid = json.dumps({"adapter": "gemini", "oracle": False})
    (paid_dir / "report.json").write_text(paid, encoding="utf-8")
    args = entry_point._parser().parse_args(["synthetic", "--oracle", "--set", str(FIXTURE), "--run-dir", str(paid_dir)])
    with pytest.raises(SystemExit, match="유료"):
        await entry_point._run(args)
    assert (paid_dir / "report.json").read_text(encoding="utf-8") == paid
    assert not (paid_dir / "outcomes.json").exists()

    oracle_dir = tmp_path / "oracle"
    oracle_dir.mkdir()
    (oracle_dir / "report.json").write_text(json.dumps({"adapter": "oracle", "oracle": True}), encoding="utf-8")
    eval_set = load_set(FIXTURE)
    meter = Meter()
    with pytest.raises(SystemExit, match="오라클"):
        await entry_point.synthetic(
            factory, meter.wrap(FakeLLM(eval_set).resolver()), eval_set, oracle_dir, adapter="gemini", meter=meter,
        )
    assert not (oracle_dir / "outcomes.json").exists()


def test_the_compare_commands_refuse_oracle_results(tmp_path: Path) -> None:
    eval_set = load_set(FIXTURE)
    report = tmp_path / "report.json"
    report.write_text(json.dumps(synthetic_report(eval_set, [], [], adapter="oracle", oracle=True)), encoding="utf-8")
    real = tmp_path / "real.json"
    real.write_text(json.dumps(synthetic_report(eval_set, [], [], adapter="gemini")), encoding="utf-8")
    with pytest.raises(SystemExit, match="오라클"):
        compare.main(["adapters", "--report", f"gemini={real}", f"oracle={report}", "--out", str(tmp_path / "out")])
    # 결과 묶음에는 보고서의 표지가 없다 — 호출 기록의 모델 칸(`oracle`)으로 알아본다.
    oracle_call = {"stage": "facts.extract", "backend": "fake", "model": "oracle"}
    outcome = ChapterOutcome(
        novel="oracle-1", repeat=1, ordinal=1, probe=None, status="committed", block_rules=[], warning_rules=[],
        block_ids=[], jobs=[JobOutcome(slot="facts", status="done", attempts=1, failure_code=None, proposal=None,
                                       calls=[oracle_call])],
    )
    outcomes = tmp_path / "outcomes.json"
    outcomes.write_text(json.dumps([outcome.model_dump(mode="json")]), encoding="utf-8")
    with pytest.raises(SystemExit, match="오라클"):
        compare.main([
            "removal", "--set", str(FIXTURE), "--before", str(outcomes), "--after", str(outcomes),
            "--removed", "enum:직업/창고지기", "--out", str(tmp_path / "out"),
        ])


async def test_a_base_chapter_with_several_blocks_counts_as_one_blocked_chapter_and_its_blocks_apart(
    db_session: AsyncSession,
) -> None:
    raw = _raw()
    for event in raw["novels"][0]["chapters"][2]["events"]:  # 2화에 숨진 인물이 3화 두 주선 장면에 모두 선다
        event["present"].append("주원")
    eval_set = EvalSet.model_validate(raw)
    defects = set_defects(eval_set, await _run(db_session, eval_set))
    (blocked,) = [row for row in defects.rows if row.category == "blocked_base"]
    assert blocked.where == "oracle-1 3화 반복 1"
    assert "차단 2건" in blocked.detail
    assert defects.base_blocks == 2
    assert "(a) 막힌 기본 화 1(차단 2건)" in defects_markdown(defects)


async def test_a_warning_probe_that_is_blocked_is_a_defect_even_with_its_expected_warning(
    db_session: AsyncSession,
) -> None:
    raw = _raw()
    probe = raw["novels"][0]["probes"][5]  # 시작 미서술 경고를 기대하는 old-compass
    probe["chapter"]["events"][0]["present"].append("주원")  # 2화에 숨진 인물이 나침반 장면에 선다
    probe["depends_on"] = [1, 2]
    eval_set = EvalSet.model_validate(raw)
    outcomes = await _run(db_session, eval_set)
    (compass,) = [outcome for outcome in outcomes if outcome.probe == "old-compass"]
    assert compass.status == "blocked" and "onset_unstated" in compass.warning_rules
    defects = set_defects(eval_set, outcomes)
    assert _rows(defects) == {("warning_missed", "oracle-1 탐침 old-compass")}
    (row,) = defects.rows
    assert "exit_then_appearance" in row.detail


async def test_a_warning_on_a_non_conflict_probe_is_counted_for_reference_not_as_a_defect(
    db_session: AsyncSession,
) -> None:
    raw = _raw()
    del raw["novels"][0]["chapters"][2]["facts"][0]["scope"]  # 장면 단위 퇴장의 범위를 빠뜨려 기본값(이 장면부터)이 된다
    eval_set = EvalSet.model_validate(raw)
    defects = set_defects(eval_set, await _run(db_session, eval_set))
    assert defects.rows == []
    (note,) = defects.notes
    assert (note.category, note.where) == ("non_conflict_warned", "oracle-1 탐침 stepped-out")
    assert "return_unstated" in note.detail and "3화 사실 1 scope" in note.unfilled
    markdown = defects_markdown(defects)
    assert "세트 결함 0건" in markdown and "경고를 낸 비충돌 탐침 1" in markdown


async def test_a_warning_probe_expecting_a_warning_only_a_conflict_verdict_keeps_is_outside_the_oracle(
    db_session: AsyncSession,
) -> None:
    # 앎 출처 불명은 판정 모델이 충돌이라 할 때만 남는다. 오라클의 판정은 늘 "모르겠다"라 이 경고를 낼 수 없다 — 세트 결함이 아니다.
    raw = _raw()
    raw["novels"][0]["probes"].append({
        "key": "heard-of-death", "kind": "warning", "group": "knowledge_source", "expected_rule": "knowledge_source_unclear",
        "depends_on": [1, 2, 3],
        "chapter": {
            "paragraphs": ["서진은 주원이 다리에서 숨졌다는 것을 알고 있었다."],
            "events": [{"paragraphs": [1], "present": ["서진"], "uses": [], "summary": "서진이 주원의 죽음을 안다"}],
            "knowledge": [
                {"knower": "서진", "kind": "knows", "subject": "주원", "subject_kind": "character", "fact_kind": "life",
                 "values": ["dead"], "paragraph": 1}
            ],
        },
    })
    eval_set = EvalSet.model_validate(raw)
    defects = set_defects(eval_set, await _run(db_session, eval_set))
    assert defects.rows == []
    (note,) = defects.notes
    assert (note.category, note.where) == ("outside_oracle", "oracle-1 탐침 heard-of-death")
    assert "오라클 판정 밖" in defects_markdown(defects)
