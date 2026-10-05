"""실험 스크립트 `experiments/filmclub_longturn/longturn_metrics.py` — 측정 방 턴 로그의 기계 집계.

작품 글은 DB 에서 내보낸 파일로만 읽고, 노트 발동은 실채팅 함수로 다시 계산한다. 아래 테스트는 그 연결(내보내기 →
재계산)과, 사람 턴·프로브 턴·유실 턴을 분모에서 빼는 일, 사용량 줄을 턴에 붙이는 일, 출처 귀속 규칙을 본다.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.story import (
    KeywordNote,
    MediaBookCell,
    MediaBookPerson,
    MediaBookScene,
    SituationNote,
    StatDef,
    StoryVersionDetail,
)
from experiments.filmclub_longturn import longturn_metrics as m
from factories import _make_asset, _story_with_setup

KST = timezone(timedelta(hours=9))
COUNTDOWN_ID = str(uuid.uuid4())
DOHEE_ID = str(uuid.uuid4())
CELL_ID = str(uuid.uuid4())
STATUS = "```\n장소 | 동아리방\n시간 | {day}요일 밤\n함께 | 강도희\n지금 | 회의\n```"


def _rule(stat: str, op: str, value: float, next_op: str | None = None) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "kind": "rule",
        "next_op": next_op,
        "stat_id": stat,
        "operator": op,
        "threshold": value,
    }


def _frame_data() -> dict[str, Any]:
    return {
        "versionId": str(uuid.uuid4()),
        "name": "조감독",
        "defaultUserName": "",
        "settingText": "설정 글. 편집실은 열한 시에 닫는다.",
        "examples": ["*도희가 펜을 멈춘다.* 그러니까 제일 어렵다는 거지. 대사가 있으면 대사 뒤에 숨기라도 하잖아?"],
        "setup": {"id": str(uuid.uuid4()), "name": "첫 기획 회의", "prologue": "프롤로그", "openingMessage": "오프닝"},
        "stats": [
            {"id": DOHEE_ID, "name": "도희 호감도", "min": 0, "max": 100, "initial": 20},
            {"id": COUNTDOWN_ID, "name": "상영회까지", "min": 0, "max": 42, "initial": 42},
        ],
        "situationNotes": [
            {
                "id": str(uuid.uuid4()),
                "name": "준비 초반",
                "infoText": "준비 기간이다.",
                "conditionRules": [_rule(COUNTDOWN_ID, "gt", 28.0)],
            },
            {
                "id": str(uuid.uuid4()),
                "name": "촬영 기간",
                "infoText": "촬영 기간이다.",
                "conditionRules": [_rule(COUNTDOWN_ID, "gt", 7.0, "and"), _rule(COUNTDOWN_ID, "lte", 28.0)],
            },
            {
                "id": str(uuid.uuid4()),
                "name": "도희가 곁을 허락함",
                "infoText": "도희가 곁을 허락한다.",
                "conditionRules": [_rule(DOHEE_ID, "gte", 45.0)],
            },
        ],
        "keywordNotes": [
            {
                "id": str(uuid.uuid4()),
                "name": "편집실",
                "infoText": "편집실은 밤 열한 시에 문을 잠근다고 경비가 말한다.",
                "triggerKeywords": ["편집실"],
                "excludeKeywords": [],
                "stickyTurns": 0,
                "alwaysOn": False,
                "order": 0,
            },
        ],
        "cells": {CELL_ID: "도희/기획 회의"},
    }


def _turn(
    n: int, sent: datetime, *, countdown: float, dohee: float = 20.0, reply: str | None = None, **extra: Any
) -> dict[str, Any]:
    return {
        "kind": "turn",
        "http": 200,
        "sentAt": sent.replace(tzinfo=None).isoformat(timespec="seconds"),
        "seconds": 5.0,
        "userText": extra.pop("userText", f"발화 {n}"),
        "reply": reply if reply is not None else f"응답 {n}.\n\n" + STATUS.format(day="월"),
        "roomAfter": {"turnCount": n, "stats": {"도희 호감도": dohee, "상영회까지": countdown}},
        **extra,
    }


def _rows(start: datetime) -> list[dict[str, Any]]:
    return [
        {"kind": "meta", "roomId": "room-1"},
        {
            "kind": "opening",
            "messages": ["오프닝\n\n" + STATUS.format(day="월")],
            "roomAfter": {"turnCount": 0, "stats": {"도희 호감도": 20.0, "상영회까지": 30.0}},
        },
        {"kind": "noteUpdate", "note": "도희 = 감독", "length": 7, "sha256": "abc"},
        _turn(
            1,
            start,
            countdown=30.0,
            userText="편집실 가 볼게요",
            reply="*도희가 고개를 든다.* 편집실은 밤 열한 시에 문을 잠근다고 경비가 말한다. 사흘 뒤에 보자.\n\n"
            + STATUS.format(day="목"),
            imageId=CELL_ID,
        ),
        _turn(2, start + timedelta(seconds=30), countdown=27.0, dohee=46.0, tag="넘김", shortcut="며칠 뒤로"),
        {
            "kind": "turn",
            "http": 200,
            "sentAt": (start + timedelta(seconds=60)).isoformat(timespec="seconds"),
            "userText": "유실",
            "reply": "",
            "failure": "error: x",
            "roomAfter": {"turnCount": 2, "stats": {}},
        },
        _turn(3, start + timedelta(seconds=90), countdown=27.0, dohee=46.0, source="human"),
        _turn(4, start + timedelta(seconds=120), countdown=27.0, dohee=46.0, tag="프로브"),
    ]


def test_build_turns_recomputes_notes_and_keeps_excluded_turns_out_of_the_denominator() -> None:
    frame = m.Frame(_frame_data())

    _, turns = m.build_turns(_rows(datetime(2026, 10, 5, 15, 0, 0)), frame)

    assert [(t["turn"], t["scored"], t["lost"], t["source"], t["probe"]) for t in turns] == [
        (1, True, False, "simulator", False),
        (2, True, False, "simulator", False),
        (3, False, True, "simulator", False),
        (3, False, False, "human", False),
        (4, False, False, "simulator", True),
    ]
    first, second = turns[0], turns[1]
    # 노트 갱신 줄은 바로 뒤 턴에 붙는다.
    assert first["noteUpdate"] == {"length": 7, "sha256": "abc"}
    assert second["noteUpdate"] is None
    # 상황 노트는 판정 전 스탯으로 고른다: 1턴은 30(준비 초반), 2턴은 1턴 뒤 값 30 → 아직 준비 초반, 호감 20.
    assert first["stage"] == ["준비 초반"] and second["stage"] == ["준비 초반"]
    assert turns[2]["stage"] == ["촬영 기간"]
    assert turns[2]["situationNotes"] == ["촬영 기간", "도희가 곁을 허락함"]
    # 2턴은 직전 응답(1턴)에 키워드가 있어 열린다. 응답에 노트 문장을 15자 이상 옮긴 것은 1턴뿐이다.
    assert first["keywordNotes"] == ["편집실"] and second["keywordNotes"] == ["편집실"]
    assert first["keywordEcho"] == ["편집실"] and second["keywordEcho"] == []
    assert first["countdownDelta"] == 0.0 and second["countdownDelta"] == -3.0
    assert [p["days"] for p in first["dayPhrases"]] == [3]
    assert first["weekday"] == "목" and first["weekdayStep"] == 3
    assert first["image"] == "도희/기획 회의"
    assert second["shortcut"] == "며칠 뒤로" and second["tag"] == "넘김"


def test_situation_note_stage_names_come_from_the_rules_not_a_list() -> None:
    frame = m.Frame(_frame_data())

    assert frame.stage_names == {"준비 초반", "촬영 기간"}
    assert frame.active_situation_notes({"상영회까지": 28.0, "도희 호감도": 44.0}) == ["촬영 기간"]
    assert frame.active_situation_notes({"상영회까지": 28.5, "도희 호감도": 45.0}) == [
        "준비 초반",
        "도희가 곁을 허락함",
    ]


def _usage(at: datetime, room: str, site: str = "chat_generate", prompt: int = 1000) -> str:
    stamp = at.strftime("%Y-%m-%dT%H:%M:%S.") + "123+0900"
    return (
        f"{stamp} WARNING gemini_usage call_site={site} model=gemini-3.5-flash-lite prompt_tokens={prompt} "
        f"cached_content_tokens=None candidates_tokens=100 thoughts_tokens=None total_tokens={prompt + 100} "
        f"user_id=u room_id={room}"
    )


def test_usage_lines_attach_to_the_latest_turn_sent_before_them() -> None:
    start = datetime(2026, 10, 5, 15, 0, 0, tzinfo=KST)
    frame = m.Frame(_frame_data())
    _, turns = m.build_turns(_rows(start.replace(tzinfo=None)), frame)
    lines = [
        _usage(start - timedelta(seconds=5), "room-1"),
        _usage(start + timedelta(seconds=3), "room-1"),
        _usage(start + timedelta(seconds=4), "room-1", "chat_stat_judgment", 500),
        _usage(start + timedelta(seconds=3), "other-room"),
        # 응답 뒤 백그라운드 요약 접기는 다음 턴을 보내기 전이라 1턴 몫이다.
        _usage(start + timedelta(seconds=25), "room-1", "chat_memory_summary", 3000),
        f"{(start + timedelta(seconds=31)).strftime('%Y-%m-%dT%H:%M:%S')}.000+0900 WARNING 대화방 room-1 스탯 판정 실패 — "
        "이번 턴의 스탯·엔딩 판정을 건너뛴다: LLMClientError('timed out')",
    ]

    records = m.parse_server_log(lines, "room-1")
    before = m.attach_log(turns, records, KST)
    m.summarize_log(turns)

    assert len(before) == 1
    first = turns[0]
    assert [u["callSite"] for u in first["usage"]] == ["chat_generate", "chat_stat_judgment", "chat_memory_summary"]
    expected = (1000 * 0.30 + 100 * 2.50) / 1_000_000
    assert first["usage"][0]["costUsd"] == pytest.approx(expected)
    assert turns[1]["logFailures"] == [{"failure": "stat_judgment", "timeout": True}]


def test_bin_summary_covers_every_fifty_turns() -> None:
    start = datetime(2026, 10, 5, 15, 0, 0)
    rows = [
        {
            "kind": "opening",
            "messages": ["오프닝"],
            "roomAfter": {"turnCount": 0, "stats": {"도희 호감도": 20.0, "상영회까지": 42.0}},
        }
    ]
    rows += [_turn(n, start + timedelta(seconds=20 * n), countdown=42.0 - n // 10) for n in range(1, 121)]
    _, turns = m.build_turns(rows, m.Frame(_frame_data()))
    m.summarize_log(turns)

    summary = m.bin_summary(turns)

    assert [b["bin"] for b in summary] == ["1-50", "51-100", "101-150"]
    assert summary[2]["turns"] == list(range(101, 121))
    assert summary[0]["countdown"]["first"] == 42.0 and summary[0]["countdown"]["last"] == 37.0
    assert summary[0]["countdown"]["decreasedTurns"] == [10, 20, 30, 40, 50]
    assert summary[0]["status"]["scored"] == 50 and summary[0]["status"]["formatBroken"] == []


def test_regress_turn_reproduces_story_guide_fields() -> None:
    reply = "혼자다.\n\n```\n장소 | 기숙사 로비\n시간 | 월요일 밤\n함께 | \n지금 | 유나의 답장 확인하기\n```"

    got = m.regress_turn(reply, "답장 봐요", "직전", "오프닝", [])

    assert got["fmt_ok"] is False and got["pos_end"] is True and got["dup"] == []
    assert got["together"] == {"도희": False, "유나": False, "세빈": False}


def test_attribution_reads_note_and_summary_from_the_snapshot_and_the_rest_from_the_dump() -> None:
    key = {"probeTurn": 101, "keywords": ["빨간 우산"]}
    snapshot = {"turn": 99, "note": "세빈에게 빨간 우산 빌림", "summary": "[지금] 화요일"}
    prompt = "설정…\n노트: 세빈에게 빨간 우산 빌림\n요약: [지금] 화요일\n대화: 우산 얘기"

    in_note = m.attribute(key, prompt, snapshot, ["설정"])
    in_window = m.attribute({"probeTurn": 101, "keywords": ["우산 얘기"]}, prompt, snapshot, [])
    mismatch = m.attribute(key, prompt.replace("[지금] 화요일", "[지금] 수요일"), snapshot, [])
    nowhere = m.attribute({"probeTurn": 101, "keywords": ["카메라"]}, prompt, snapshot, [])

    assert in_note["places"] == ["노트"] and in_note["staticTextHit"] is False
    assert in_window["places"] == ["원문 윈도"]
    assert mismatch["unattributable"] == "덤프에서 요약 원문을 찾지 못함"
    assert nowhere["places"] == ["어디에도 없음"]
    assert m.latest_snapshot([{"turn": 50}, snapshot, {"turn": 102}], 101) == snapshot


def test_visible_tail_renders_names_and_image_labels_without_log_only_fields() -> None:
    frame = m.Frame(_frame_data())
    rows = [
        _turn(1, datetime(2026, 10, 5), countdown=30.0, reply="{{user}}, 앉아.\n\n{{img::" + CELL_ID + "}}", tag="넘김")
    ]

    text = "\n".join(m.visible_tail(rows, frame, 30))

    assert "당신, 앉아." in text and "[그림: 도희/기획 회의]" in text
    assert "넘김" not in text and "{{" not in text


async def test_export_frame_reads_the_version_rows(db_session: AsyncSession) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="오프닝 {{user}}")
    version_id = content.current_published_version_id
    assert version_id is not None
    detail = await db_session.get(StoryVersionDetail, version_id)
    assert detail is not None
    detail.development_examples = [{"userLine": "u", "assistantLine": "예시 응답"}]
    countdown = uuid.uuid4()
    db_session.add(
        StatDef(
            entity_id=countdown,
            starting_setup_id=setup.id,
            name="상영회까지",
            icon="i",
            color="c",
            min_value=0,
            max_value=42,
            initial_value=42,
            description="d",
            order=0,
        )
    )
    db_session.add(
        SituationNote(
            entity_id=uuid.uuid4(),
            starting_setup_id=setup.id,
            name="준비 초반",
            info_text="준비",
            order=0,
            condition_rules=[_rule(str(countdown), "gt", 28.0)],
        )
    )
    db_session.add(
        KeywordNote(
            entity_id=uuid.uuid4(),
            content_version_id=version_id,
            starting_setup_id=None,
            info_text="정보",
            trigger_keywords=["편집실"],
            name="편집실",
            order=0,
        )
    )
    db_session.add(
        KeywordNote(
            entity_id=uuid.uuid4(),
            content_version_id=version_id,
            starting_setup_id=setup.id,
            info_text="다른",
            trigger_keywords=["x"],
            name="다른",
            order=1,
        )
    )
    person, scene = uuid.uuid4(), uuid.uuid4()
    db_session.add(MediaBookPerson(entity_id=person, content_version_id=version_id, name="도희", order=0))
    db_session.add(MediaBookScene(entity_id=scene, content_version_id=version_id, name="기획 회의", order=0))
    asset = await _make_asset(db_session, owner_user_id=user_id)
    cell = uuid.uuid4()
    db_session.add(
        MediaBookCell(
            entity_id=cell,
            content_version_id=version_id,
            person_entity_id=person,
            scene_entity_id=scene,
            image_asset_id=asset.id,
            situation_description="s",
        )
    )
    await db_session.flush()

    data = await m.export_frame(db_session, version_id)

    assert data["setup"]["openingMessage"] == "오프닝 {{user}}"
    assert data["examples"] == ["예시 응답"]
    assert [s["name"] for s in data["stats"]] == ["상영회까지"]
    assert data["situationNotes"][0]["conditionRules"][0]["operator"] == "gt"
    assert [n["name"] for n in data["keywordNotes"]] == ["편집실", "다른"]
    assert data["cells"] == {str(cell): "도희/기획 회의"}
    # 내보낸 파일로 다시 만든 Frame 이 같은 노트를 고른다(내보내기 ↔ 재계산 연결).
    frame = m.Frame(json.loads(json.dumps(data)))
    assert frame.active_situation_notes({"상영회까지": 30.0}) == ["준비 초반"]


def test_probe_check_applies_exclusions_then_category_rotation_then_earliest_turn() -> None:
    texts = {t: f"턴 {t} 글" for t in range(1, 101)}
    texts[15] += " 빨간 우산을 빌렸다"
    texts[20] += " 목요일 정류장 촬영"
    texts[30] += " 은색 열쇠를 받았다"
    texts[90] += " 은색 열쇠 다시"
    texts[25] += " 편집실 열쇠"
    candidates = [
        {"category": "물건", "sourceTurn": 30, "keywords": ["은색 열쇠"]},  # 직전 29턴(90)에 다시 나옴
        {"category": "물건", "sourceTurn": 25, "keywords": ["편집실"]},  # 작품 글에 있음
        {"category": "물건", "sourceTurn": 5, "keywords": ["우산"]},  # 구간 밖(11~61)
        {"category": "장소·일정", "sourceTurn": 20, "keywords": ["정류장"]},
        {"category": "약속", "sourceTurn": 15, "keywords": ["빨간 우산"]},
    ]

    report = m.check_probe_candidates(candidates, texts, ["편집실은 열한 시에 닫는다"], 101, "물건")

    assert report["window"] == [11, 61]
    assert [c["excluded"] for c in report["candidates"][:3]] == [
        ["직전 29턴에 다시 나옴"],
        ["작품 글에 있음"],
        ["구간 밖", "원천 턴에 핵심어 없음"],
    ]
    # 물건에 남는 후보가 없어 다음 범주(장소·일정)로 넘어간다 — 약속의 15턴이 더 이르지만 범주 순서가 먼저다.
    assert report["chosen"]["category"] == "장소·일정" and report["chosen"]["sourceTurn"] == 20
    rotated = m.check_probe_candidates(candidates, texts, [], 101, "약속")
    assert rotated["categoryOrder"][0] == "약속" and rotated["chosen"]["sourceTurn"] == 15


def test_visible_tail_note_is_the_last_memory_snapshot_of_the_room_not_the_last_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 정기 교대는 일시 정지 바로 뒤라 스냅숏 파일의 마지막 줄은 노트가 없는 정지 줄이다.
    log = tmp_path / "room.jsonl"
    log.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in _rows(datetime(2026, 10, 5, 15))) + "\n")
    frame = tmp_path / "frame.json"
    frame.write_text(json.dumps(_frame_data(), ensure_ascii=False))
    snapshots = tmp_path / "snap.jsonl"
    rows = [
        {"kind": "memorySnapshot", "roomId": "room-1", "turn": 3, "note": "도희: 편집 담당", "summary": "요약"},
        {"kind": "memorySnapshot", "roomId": "other-room", "turn": 9, "note": "다른 방 노트", "summary": ""},
        {"kind": "pause", "roomId": "room-1", "turnCount": 50, "trigger": "pause-at"},
        {"kind": "roomStatic", "roomId": "room-1", "shortcuts": []},
    ]
    snapshots.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")

    m.main(["visible-tail", "--log", str(log), "--frame", str(frame), "--snapshots", str(snapshots), "--n", "2"])

    out = capsys.readouterr().out
    assert out.rstrip().splitlines()[-2] == "도희: 편집 담당"
    assert "다른 방 노트" not in out and "요약" not in out


def _call(ts: datetime, turn: int | None, site: str, ms: int, error: str | None = None, room: str = "room-1") -> str:
    return json.dumps(
        {
            "ts": ts.isoformat(),
            "kind": "llm_call",
            "turn": turn,
            "callSite": site,
            "model": "gemini-3.5-flash-lite",
            "roomId": room,
            "elapsedMs": ms,
            "ok": error is None,
            "errorType": error,
        }
    )


def test_trace_calls_without_a_turn_are_kept_apart_instead_of_crashing(tmp_path: Path) -> None:
    # 턴이 끝난 뒤 백그라운드로 도는 기억 요약 호출은 턴 번호 없이(null) 남는다.
    at = datetime(2026, 10, 5, 15, 0, 0, tzinfo=KST)
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        "\n".join(
            [
                _call(at, 1, "chat_generate", 2000),
                _call(at + timedelta(seconds=20), None, "chat_memory_summary", 4000),
                _call(at + timedelta(seconds=50), None, "chat_memory_summary", 300, "ReadTimeout"),
                _call(at, None, "chat_memory_summary", 1, room="other-room"),
            ]
        )
        + "\n"
    )

    by_turn, background = m.trace_calls(trace, "room-1")

    assert [c["callSite"] for c in by_turn[1]] == ["chat_generate"]
    assert [(c["callSite"], c["elapsedMs"], c["errorType"]) for c in background] == [
        ("chat_memory_summary", 4000, None),
        ("chat_memory_summary", 300, "ReadTimeout"),
    ]
    summary = m.background_summary(background)
    assert summary["chat_memory_summary"]["n"] == 2
    assert summary["chat_memory_summary"]["errors"] == {"ReadTimeout": 1}


def test_timeouts_are_counted_from_the_trace_error_type_per_call_site() -> None:
    # httpx 읽기 타임아웃은 메시지가 빈 문자열이라 서버 로그 실패 줄에는 타임아웃 낱말이 없다 — trace 의 예외 이름으로 센다.
    start = datetime(2026, 10, 5, 15, 0, 0)
    rows = _rows(start)[:4]
    _, turns = m.build_turns(rows, m.Frame(_frame_data()))
    m.summarize_log(turns)
    ok = {"elapsedMs": 900, "ok": True, "errorType": None}
    turns[0]["calls"] = [
        {"callSite": "chat_generate", **ok},
        {"callSite": "chat_stat_judgment", "elapsedMs": 30000, "ok": False, "errorType": "ReadTimeout"},
        {"callSite": "chat_media_book_image", "elapsedMs": 50, "ok": False, "errorType": "ClientError"},
    ]

    (summary,) = m.bin_summary(turns)

    assert summary["callFailures"] == {
        "chat_stat_judgment": {"ReadTimeout": 1},
        "chat_media_book_image": {"ClientError": 1},
    }
    assert summary["callTimeouts"] == {"chat_stat_judgment": 1}
    deadline = (
        "2026-10-05T15:00:31.000+0900 WARNING 대화방 room-1 판정 실패 — 이번 턴의 판정을 건너뛴다: "
        "Gemini generate_structured() call failed: 504 DEADLINE_EXCEEDED. {}"
    )
    assert m.parse_server_log([deadline], "room-1")[0]["timeout"] is True


def test_lost_attempt_and_the_next_turn_with_the_same_number_split_trace_calls_by_time() -> None:
    # 유실 턴과 그다음 성공 턴은 같은 턴 번호(3)를 갖고 trace 의 turn 도 둘 다 3이다 — 지연이 두 번 들어가면 안 된다.
    start = datetime(2026, 10, 5, 15, 0, 0)
    _, turns = m.build_turns(_rows(start), m.Frame(_frame_data()))
    m.summarize_log(turns)
    at = start.replace(tzinfo=KST).astimezone(timezone.utc)

    def call(seconds: int, site: str, error: str | None = None) -> dict[str, Any]:
        stamp = (at + timedelta(seconds=seconds)).isoformat()
        return {"callSite": site, "elapsedMs": 1000, "ok": error is None, "errorType": error, "ts": stamp}

    by_turn = {
        1: [call(2, "chat_generate")],
        3: [call(62, "chat_generate", "ReadTimeout"), call(92, "chat_generate"), call(93, "chat_stat_judgment")],
    }

    m.attach_calls(turns, by_turn, KST)

    lost, retried = turns[2], turns[3]
    assert lost["turn"] == retried["turn"] == 3 and lost["attempt"] != retried["attempt"]
    assert [c["callSite"] for c in lost["calls"]] == ["chat_generate"]
    assert [c["callSite"] for c in retried["calls"]] == ["chat_generate", "chat_stat_judgment"]
    (summary,) = m.bin_summary(turns)
    assert summary["callLatencyMs"]["chat_generate"]["n"] == 3


def _shortcut_rows() -> list[dict[str, Any]]:
    rows = _rows(datetime(2026, 10, 5, 15, 0, 0))[:2]
    rows.append(_turn(1, datetime(2026, 10, 5, 15, 0, 0), countdown=30.0, userText=None, shortcut="동아리방 들르기"))
    return rows


def test_shortcut_turn_uses_the_shortcut_prompt_as_the_user_text_for_keyword_notes() -> None:
    # 드라이버는 은폐 때문에 단축어 턴의 사용자 글을 비워 두지만, 서버는 단축어 원문을 사용자 메시지로 받아 키워드를 맞춘다.
    snapshots: list[dict[str, Any]] = [
        {
            "kind": "roomStatic",
            "roomId": "room-1",
            "shortcuts": [{"id": "s1", "name": "동아리방 들르기", "prompt": "{{user}}가 편집실에 들른다"}],
            "names": {"personaName": None, "defaultUserName": "민준", "charName": None},
        },
        {"kind": "roomStatic", "roomId": "other-room", "shortcuts": [], "names": {}},
    ]
    texts = m.shortcut_texts(snapshots, "room-1")
    assert texts == {"동아리방 들르기": "민준이 편집실에 들른다"}

    _, turns = m.build_turns(_shortcut_rows(), m.Frame(_frame_data()), texts)

    assert turns[0]["keywordNotes"] == ["편집실"]
    with pytest.raises(ValueError, match="동아리방 들르기"):
        m.build_turns(_shortcut_rows(), m.Frame(_frame_data()))


def test_visible_tail_shows_the_shortcut_name_and_the_image_label_of_each_turn() -> None:
    rows = _shortcut_rows()
    rows[-1]["imageLabel"] = "도희/기획 회의"

    text = "\n".join(m.visible_tail(rows, m.Frame(_frame_data()), 30))

    assert "나: [단축어: 동아리방 들르기]" in text and "None" not in text
    assert "[그림: 도희/기획 회의]" in text
