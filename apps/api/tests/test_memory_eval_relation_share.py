"""요약 `[관계]` 칸 비율 집계 — 합성 요약으로 칸 있음·비어 있지 않음·글자 몫을 레인·모델별로 세고, 여러 DB 에 같은 스냅샷이
복사돼 있으면 먼저 준 출처에서 한 번만 센다. DB 읽기는 같은 이름의 임시 테이블을 세션에 만들어 그대로 돌린다."""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from memory_eval.relation_share import load_snapshots, relation_share

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _snap(room: str, lane: str, model: str, order: int, summary: str) -> dict[str, Any]:
    return {
        "room": room,
        "lane": lane,
        "model": model,
        "cursorCreatedAt": T0 + timedelta(minutes=order),
        "cursorId": f"{room}-m{order}",
        "summary": summary,
    }


STORY_A = [
    _snap("r1", "story", "opus", 1, "[지금] 가나\n[관계] 가나다라\n[지난 일] 가나"),
    # 한 줄에 이어 쓴 칸 — 문장 끝 뒤의 머리글도 칸이다.
    _snap("r1", "story", "opus", 2, "[지금] 가나다. [관계] 가나다라마바. [지난 일] 가"),
    _snap("r2", "story", "opus", 1, "[지금] 가나\n[지난 일] 가나다라"),
]
CHARACTER_A = [
    _snap("r3", "character", "opus", 1, "[지금] 가\n[관계]\n[지난 일] 가나다"),
]


def test_counts_presence_non_empty_and_share_per_lane_and_model() -> None:
    report = relation_share([("A", STORY_A + CHARACTER_A)])
    story = report["groups"]["A|story|opus"]
    assert story["snapshots"] == 3
    assert story["rooms"] == 2
    assert story["present"] == 2
    assert story["nonEmpty"] == 2
    assert story["presentRate"] == pytest.approx(2 / 3)
    shares = [4 / (2 + 4 + 2), 7 / (4 + 7 + 1), 0.0]
    assert story["share"]["mean"] == pytest.approx(sum(shares) / 3)
    assert story["share"]["min"] == 0.0
    assert story["share"]["max"] == pytest.approx(7 / 12)
    assert story["share"]["pooled"] == pytest.approx((4 + 7) / (8 + 12 + 6))
    character = report["groups"]["A|character|opus"]
    assert character["present"] == 1
    assert character["nonEmpty"] == 0


def test_last_snapshot_per_room_is_reported_separately() -> None:
    story = relation_share([("A", STORY_A)])["groups"]["A|story|opus"]
    assert story["last"]["rooms"] == 2
    assert story["last"]["present"] == 1
    assert story["last"]["share"]["mean"] == pytest.approx((7 / 12 + 0.0) / 2)


def test_a_snapshot_copied_into_a_later_source_is_counted_once_under_the_first() -> None:
    copied = [dict(s) for s in STORY_A[:1]]
    other = _snap("r1", "story", "opus", 1, "[지금] 가\n[관계] 가\n[지난 일] 가")
    report = relation_share([("A", STORY_A), ("B", [*copied, other])])
    assert report["groups"]["B|story|opus"]["snapshots"] == 1
    assert report["duplicatesSkipped"] == 1
    # 출처를 합친 줄도 레인·모델별로 나온다.
    assert report["groups"]["*|story|opus"]["snapshots"] == 4


def test_flags_unknown_headers_and_text_before_the_first_header() -> None:
    odd = [_snap("r1", "story", "opus", 1, "머리\n[다른 칸] 가\n[관계] 가")]
    story = relation_share([("A", odd)])["groups"]["A|story|opus"]
    assert story["unknownHeaderSnapshots"] == 1
    assert story["noHeaderSnapshots"] == 1


def test_report_holds_no_room_ids_or_summary_text() -> None:
    text = str(relation_share([("A", STORY_A + CHARACTER_A)]))
    for leaked in ("r1", "r2", "r3", "가나다"):
        assert leaked not in text


@pytest.fixture
async def snapshot_tables() -> AsyncIterator[asyncpg.Connection]:
    url = make_url(os.environ["DATABASE_URL"])
    connection = await asyncpg.connect(
        host=url.host, port=url.port, user=url.username, password=url.password, database=url.database
    )
    try:
        await connection.execute(
            "CREATE TEMP TABLE contents (id text PRIMARY KEY, type text NOT NULL);"
            "CREATE TEMP TABLE chat_rooms (id text PRIMARY KEY, content_id text NOT NULL, chat_model text);"
            "CREATE TEMP TABLE chat_room_memory_snapshots (chat_room_id text NOT NULL,"
            " cursor_created_at timestamptz NOT NULL, cursor_message_id text NOT NULL, summary_text text NOT NULL);"
            "INSERT INTO contents VALUES ('c1', 'STORY'), ('c2', 'CHARACTER');"
            "INSERT INTO chat_rooms VALUES ('r1', 'c1', 'opus'), ('r2', 'c2', NULL);"
        )
        await connection.executemany(
            "INSERT INTO chat_room_memory_snapshots VALUES ($1, $2, $3, $4)",
            [
                ("r1", T0 + timedelta(minutes=2), "m2", "[관계] 둘"),
                ("r1", T0 + timedelta(minutes=1), "m1", "[관계] 하나"),
                ("r2", T0, "m0", "[지금] 셋"),
            ],
        )
        yield connection
    finally:
        await connection.close()


async def test_loads_snapshots_with_lane_and_model_in_cursor_order(snapshot_tables: asyncpg.Connection) -> None:
    rows = await load_snapshots(snapshot_tables)
    assert [(r["room"], r["lane"], r["model"], r["cursorId"]) for r in rows] == [
        ("r1", "story", "opus", "m1"),
        ("r1", "story", "opus", "m2"),
        ("r2", "character", "default", "m0"),
    ]
