"""정본 기억 측정 하네스의 사람 라벨 원고 — 텍스트 파일 폴더에서 격리 DB 안 새 소설 사본을 어댑터 수만큼 만들고, 사본마다 앞
화들을 확정하는 추출의 가드(이미 확정이 있는 소설 거절)·화 부족 판정 불가·결과에 싣는 시도 기록·원가·차단 상태.

원고는 합성 세트의 문장을 텍스트 파일로 옮긴 것이다 — 실제 소설 원문이 아니다. 모델은 가짜 해석기다."""

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import api.novel_bible.entry as entry
from api.core.config import settings
from api.db.models import Content, Novel, NovelChapter, NovelChapterRevision, NovelSceneBlock
from api.db.models.novel_bible import NovelBibleCommit
from api.novel_bible.core.types import BibleSnapshot
from api.novelize.text import split_paragraphs
from novel_bible_eval import labels, text_copy
from novel_bible_eval.__main__ import _parser, _run, extract, main
from novel_bible_eval.fake_llm import FakeLLM, Faults
from novel_bible_eval.report import label_report
from novel_bible_eval.run import Meter
from novel_bible_eval.spec import EvalSet
from novel_bible_fakes import FakeRule, savepoint_factory

FIXTURE = Path(__file__).parent / "fixtures" / "novel_bible_eval" / "small_set.json"
NOVEL = "synthetic-1"


@pytest.fixture(autouse=True)
def _bible_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novel_bible_enabled", True)


def _plain_set() -> EvalSet:
    """합성 세트에서 원작·플레이·장면 구성안과 그 차이 정답을 걷어 낸 것 — 텍스트 사본은 원작·방·장면 구성안이 없다."""
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    book = raw["novels"][0]
    book["source"], book["play"] = None, []
    for chapter in book["chapters"]:
        chapter["scenes"] = None
        for fact in chapter.get("facts", []):
            fact.pop("source_difference", None)
            fact.pop("play_difference", None)
    return EvalSet.model_validate(raw)


def _write_folder(folder: Path, eval_set: EvalSet, *, title: str | None = "합성 제목") -> list[list[str]]:
    """화마다 `01.txt`…, 빈 줄로 문단을 가른다. 첫 화는 BOM 과 CRLF 로 써서 읽기가 둘을 걷는지 본다."""
    folder.mkdir(parents=True)
    chapters = [chapter.paragraphs for chapter in eval_set.novels[0].chapters]
    for number, paragraphs in enumerate(chapters, start=1):
        body = "\n\n".join(paragraphs) + "\n"
        if number == 1:
            (folder / f"{number:02d}.txt").write_bytes(("﻿" + body.replace("\n", "\r\n")).encode("utf-8"))
        else:
            (folder / f"{number:02d}.txt").write_text(body, encoding="utf-8")
    if title is not None:
        (folder / "meta.txt").write_text(f"{title}\n합성 둘째 줄\n", encoding="utf-8")
    return chapters


def test_a_text_folder_reads_into_numbered_chapters_of_paragraphs(tmp_path: Path) -> None:
    eval_set = _plain_set()
    chapters = _write_folder(tmp_path / "book", eval_set)
    (tmp_path / "book" / "notes.md").write_text("합성 메모", encoding="utf-8")  # 화 파일 꼴이 아니면 읽지 않는다
    read = text_copy.read_text_dir(tmp_path / "book")
    assert read.title == "합성 제목"
    assert [list(paragraphs) for paragraphs in read.chapters] == chapters
    _write_folder(tmp_path / "untitled", eval_set, title=None)
    assert text_copy.read_text_dir(tmp_path / "untitled").title == "untitled"


@pytest.mark.parametrize(
    ("files", "message"),
    [
        pytest.param({"01.txt": "합성 문단", "03.txt": "합성 문단"}, "빠진 화", id="gap"),
        pytest.param({"1.txt": "합성 문단", "01.txt": "합성 문단"}, "겹친", id="same-number-twice"),
        pytest.param({"01.txt": "합성 문단", "02.txt": " \n\n "}, "02.txt", id="empty-chapter"),
        pytest.param({"meta.txt": "합성 제목"}, "화 파일", id="no-chapter"),
    ],
)
def test_a_text_folder_that_would_copy_the_wrong_chapters_is_refused(
    tmp_path: Path, files: dict[str, str], message: str
) -> None:
    for name, body in files.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        text_copy.read_text_dir(tmp_path)


async def _copies(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *adapters: str
) -> tuple[Any, dict[str, Any], list[list[str]]]:
    factory = savepoint_factory(db_session)
    monkeypatch.setattr("novel_bible_eval.__main__.async_session_factory", factory)
    chapters = _write_folder(tmp_path / "book", _plain_set())
    run_dir = tmp_path / "run"
    code = await _run(_parser().parse_args([
        "copy-text", "--text-dir", str(tmp_path / "book"), "--adapters", *adapters, "--run-dir", str(run_dir),
    ]))
    assert code == 0
    copies = json.loads((run_dir / "copies.json").read_text(encoding="utf-8"))
    return factory, copies, chapters


async def test_copy_text_makes_one_sourceless_roomless_novel_per_adapter_with_the_text_as_chapters(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, copies, chapters = await _copies(db_session, monkeypatch, tmp_path, "alpha", "beta")
    assert sorted(copies) == ["alpha", "beta"]
    assert copies["alpha"] != copies["beta"]
    for novel_id in copies.values():
        novel = await db_session.get(Novel, novel_id)
        assert novel is not None
        assert (novel.title, novel.chat_room_id) == ("합성 제목", None)
        # 원작 칸은 행이 없는 id 다 — 확정이 원작 입력 없이 돈다.
        assert await db_session.get(Content, novel.content_id) is None
        bodies = (
            await db_session.execute(
                select(NovelChapter.ordinal, NovelChapterRevision.body)
                .join(NovelChapterRevision, NovelChapterRevision.chapter_id == NovelChapter.id)
                .where(NovelChapter.novel_id == novel.id)
                .order_by(NovelChapter.ordinal)
            )
        ).all()
        assert [(row.ordinal, split_paragraphs(row.body)) for row in bodies] == [
            (number, paragraphs) for number, paragraphs in enumerate(chapters, start=1)
        ]
        # 장면 구성안이 없어 화 전체가 한 장면으로 읽힌다.
        scenes = select(func.count()).select_from(NovelSceneBlock).join(
            NovelChapter, NovelChapter.id == NovelSceneBlock.chapter_id
        ).where(NovelChapter.novel_id == novel.id)
        assert await db_session.scalar(scenes) == 0


async def test_a_text_copy_confirms_without_source_or_room_and_its_result_carries_attempts_cost_and_blocks(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    factory, copies, _ = await _copies(db_session, monkeypatch, tmp_path, "alpha")
    eval_set = _plain_set()
    fake = FakeLLM(eval_set, faults=Faults(schema_failure=frozenset({(NOVEL, "2")})))
    meter = Meter()
    out = tmp_path / "labels"
    code = await extract(factory, meter.wrap(fake.resolver()), copies["alpha"], out, adapter="alpha", count=3, meter=meter)
    assert code == 0
    commits = (
        await db_session.execute(
            select(NovelBibleCommit.status, NovelBibleCommit.source_content_version_id, NovelBibleCommit.chat_room_id)
            .where(NovelBibleCommit.novel_id == copies["alpha"])
        )
    ).all()
    assert sorted(tuple(row) for row in commits) == [("committed", None, None)] * 3

    written = json.loads((out / "extract-alpha.json").read_text(encoding="utf-8"))
    assert written["halted"] is None
    # 세 화에 슬롯 셋씩 + 2화 첫 호출의 재시도 + 1화 판정 하나. 시도 기록이 스키마 실패율의 재료다.
    assert len(written["attempts"]) == 11
    assert written["attempts"].count(["events.extract", "schema_invalid"]) == 1
    # 작업 행의 호출 기록이라 실패한 시도도 든다. 판정 호출은 작업 행에 남지 않는다.
    assert written["cost"]["calls"] == 10
    assert written["blocked"] == {}
    assert len(written["quote"]) == 3


async def test_extract_refuses_a_novel_that_already_has_canon_commits_and_keeps_the_earlier_result(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 같은 소설로 두 번째 어댑터를 돌리면 확정 입구가 같은 개정을 그대로 돌려 첫 어댑터의 작업을 모은다 — 오류 없이 틀린 결과다.
    factory, copies, _ = await _copies(db_session, monkeypatch, tmp_path, "alpha")
    eval_set = _plain_set()
    out = tmp_path / "labels"
    first = Meter()
    await extract(factory, first.wrap(FakeLLM(eval_set).resolver()), copies["alpha"], out, adapter="alpha", count=2,
                  meter=first)
    before = (out / "extract-alpha.json").read_text(encoding="utf-8")
    second = FakeLLM(eval_set)
    meter = Meter()
    with pytest.raises(SystemExit, match="이미 정본 기억 확정"):
        await extract(factory, meter.wrap(second.resolver()), copies["alpha"], out, adapter="alpha", count=2,
                      meter=meter)
    assert second.calls == 0
    assert (out / "extract-alpha.json").read_text(encoding="utf-8") == before


async def test_an_extraction_that_ends_with_fewer_chapters_than_asked_is_undetermined_in_the_label_report(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 사본은 세 화뿐인데 네 화를 요청했다. 앞 화 일부만 담긴 추출로 핵심 사실 정밀도의 합격을 내지 않는다.
    factory, copies, _ = await _copies(db_session, monkeypatch, tmp_path, "alpha", "beta")
    eval_set = _plain_set()
    out = tmp_path / "labels"
    for adapter, count in (("alpha", 3), ("beta", 4)):
        meter = Meter()
        assert await extract(factory, meter.wrap(FakeLLM(eval_set).resolver()), copies[adapter], out,
                             adapter=adapter, count=count, meter=meter) == 0
    short = json.loads((out / "extract-beta.json").read_text(encoding="utf-8"))
    assert "화 부족" in short["halted"] and "4화" in short["halted"]
    assert json.loads((out / "extract-alpha.json").read_text(encoding="utf-8"))["halted"] is None

    await _run(_parser().parse_args([
        "sheet", "--extract", f"alpha={out / 'extract-alpha.json'}", f"beta={out / 'extract-beta.json'}",
        "--out", str(out),
    ]))
    rows = labels.sheet_claims((out / "sheet.html").read_text(encoding="utf-8"))
    verdicts = {row["id"]: {"verdict": "correct", "quotes": ["supported"] * len(row["quotes"])} for row in rows}
    result = out / "labels-result.json"
    result.write_text(json.dumps({"labels": verdicts, "missing": {}}), encoding="utf-8")
    await _run(_parser().parse_args(["score", "--key", str(out / "claims-key.json"), "--labels", str(result),
                                     "--out", str(out)]))
    report = json.loads((out / "label-report.json").read_text(encoding="utf-8"))["adapters"]
    assert report["alpha"]["core_fact_precision"]["pass"] is True
    core = report["beta"]["core_fact_precision"]
    assert (core["value"], core["pass"], core["undetermined"]) == (1.0, None, "멈춘 실행")
    # 라벨 보고서는 추출의 인용 실재율·스키마 실패율·원가와, 오탐과 따로 차단을 싣는다.
    alpha = report["alpha"]
    assert (alpha["quote_rate"]["k"], alpha["quote_rate"]["n"]) == (15, 15)  # 사건 8·사실 5·지식 2
    assert (alpha["schema_failure_rate"]["k"], alpha["schema_failure_rate"]["n"]) == (0, 10)
    assert alpha["cost"]["calls"] == 9
    assert alpha["blocked"] == {}


async def test_a_blocked_chapter_counts_as_extracted_and_is_reported_apart_from_false_positives(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 막힌 화도 검사까지 끝난 확정이다 — 그 화의 제안을 라벨하므로 화 부족이 아니다. 막은 규칙은 추출 결과와 라벨 보고서에
    # 그대로 실린다.
    def chapter_two(snapshot: BibleSnapshot) -> tuple[object, ...]:
        events = snapshot.events or ()
        return tuple(e.id for e in events if e.id in snapshot.new_ids and e.chapter_ordinal == 2)

    rule = FakeRule(pick=chapter_two, rule="exit_then_appearance", slots=frozenset({"events"}))  # type: ignore[arg-type]
    monkeypatch.setattr(entry, "RULES", [rule])
    factory, copies, _ = await _copies(db_session, monkeypatch, tmp_path, "alpha")
    meter = Meter()
    out = tmp_path / "labels"
    assert await extract(factory, meter.wrap(FakeLLM(_plain_set()).resolver()), copies["alpha"], out, adapter="alpha",
                         count=3, meter=meter) == 0
    path = out / "extract-alpha.json"
    written = json.loads(path.read_text(encoding="utf-8"))
    assert [(row["ordinal"], row["status"]) for row in written["outcomes"]] == [
        (1, "committed"), (2, "blocked"), (3, "committed")
    ]
    assert (written["halted"], written["blocked"]) == (None, {"2": ["exit_then_appearance"]})
    summary = labels.ExtractionSummary.model_validate_json(path.read_text(encoding="utf-8"))
    report = label_report([], {"alpha": None}, {"alpha": summary})["adapters"]["alpha"]
    assert report["blocked"] == {2: ["exit_then_appearance"]}


def test_copy_text_refuses_a_database_that_is_not_local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://app:secret@db.internal:5432/app")
    with pytest.raises(SystemExit, match="로컬 DB"):
        main(["copy-text", "--text-dir", str(tmp_path), "--adapters", "alpha", "--run-dir", str(tmp_path / "run")])
    assert not (tmp_path / "run").exists()
