"""최종 짝 비교를 돌리기 위한 하네스 보강 — 서버 회상 순수 함수를 오프라인 회상 검색 함수로 꽂는 어댑터, 두 검색 함수의 행
단위 대조, DB 에서 읽은 장면의 "검색 대상이 되는 첫 턴" 계산, 서버 로그의 회상 실패 경고 세기."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from memory_eval.probe import recall_warning_count
from memory_eval.prototype_recall import retrieve_e
from memory_eval.recall_offline import Episode, compare_rows
from memory_eval.server_recall import available_from_turns, export_rows, retrieve_server


def _filler(count: int, *, start: int, available: int) -> list[Episode]:
    return [
        Episode(
            id=f"f{start + i}",
            start_turn=10 + start + i,
            end_turn=11 + start + i,
            title=f"채움{start + i}",
            detail=f"채움{start + i} 장면",
            asserted_by="narration",
            nouns=(f"채움{start + i}", "장면"),
            available_from_turn=available,
        )
        for i in range(count)
    ]


def test_server_adapter_matches_prototype_on_stored_nouns() -> None:
    gold = Episode(
        id="G",
        start_turn=20,
        end_turn=22,
        title="모래시계 장면",
        detail="부원이 모래시계 를 동아리방 선반에 올려 두었다.",
        asserted_by="narration",
        nouns=("모래시계", "동아리방", "선반", "부원", "올려", "두었다"),
        importance=4,
        available_from_turn=31,
    )
    episodes = [gold, *_filler(6, start=0, available=41)]
    kw: dict[str, Any] = {
        "user_text": "모래시계 어디 뒀더라?",
        "previous_assistant": "세빈이 고개를 든다.",
        "current_turn": 51,
    }
    server = retrieve_server(episodes, **kw)
    proto = retrieve_e(episodes, **kw)
    assert [(r.episode_id, r.injected) for r in server] == [(r.episode_id, r.injected) for r in proto]
    assert [r.episode_id for r in server if r.injected] == ["G"]
    for a, b in zip(server, proto, strict=True):
        assert a.score == pytest.approx(b.score, abs=1e-9)


def test_server_adapter_uses_stored_nouns_as_is() -> None:
    """서버는 저장된 명사만 본다 — 제목·본문에만 있고 저장 명사에 없는 낱말로는 찾지 못한다(시제품은 본문에서 다시 뽑는다)."""
    hidden = Episode(
        id="H",
        start_turn=20,
        end_turn=22,
        title="탬버린",
        detail="탬버린 을 흔들었다.",
        asserted_by="narration",
        nouns=("흔들었다",),
        available_from_turn=31,
    )
    episodes = [hidden, *_filler(6, start=0, available=41)]
    kw: dict[str, Any] = {"user_text": "탬버린 기억나?", "previous_assistant": "", "current_turn": 51}
    assert [r.episode_id for r in retrieve_server(episodes, **kw)] == []
    assert [r.episode_id for r in retrieve_e(episodes, **kw)] == ["H"]


def test_server_adapter_orders_snapshots_by_available_turn() -> None:
    """직전 응답으로 찾는 경로는 가장 최근 스냅샷 둘의 낱말을 뺀다 — 스냅샷 순서가 검색 대상이 되는 첫 턴 순서여야 한다."""
    old = Episode("O", 20, 22, "어항", "어항 을 닦았다.", "narration", nouns=("어항",), available_from_turn=31)
    newer = Episode("N", 60, 62, "그네", "그네 를 탔다.", "narration", nouns=("그네",), available_from_turn=71)
    episodes = [
        old,
        newer,
        *_filler(3, start=0, available=41),
        *_filler(3, start=10, available=61),
        *_filler(2, start=20, available=71),
    ]
    kw: dict[str, Any] = {
        "user_text": "그때 그거 말이야",
        "previous_assistant": "어항 옆에 그네 가 보였다.",
        "current_turn": 81,
    }
    assert [r.episode_id for r in retrieve_server(episodes, **kw)] == ["O"]
    # 같은 장면을 스냅샷 순서만 바꿔(그네 장면을 가장 오래된 스냅샷으로) 넣으면 그네도 후보가 된다.
    swapped = [*episodes[:1], Episode("N", 60, 62, "그네", "그네 를 탔다.", "narration", nouns=("그네",),
                                      available_from_turn=11), *episodes[2:]]  # fmt: skip
    assert sorted(r.episode_id for r in retrieve_server(swapped, **kw)) == ["N", "O"]


def _rows(**overrides: object) -> list[dict[str, object]]:
    base: dict[str, object] = {
        "checkpoint": 300,
        "item_id": "obj01",
        "kind": "question",
        "injected": ["a", "b"],
        "top10": ["a", "b", "c"],
        "scores": {"a": 0.9, "b": 0.8, "c": 0.1},
    }
    return [base | overrides]


def test_compare_rows_identical() -> None:
    result = compare_rows(_rows(), _rows())
    assert (result["rows"], result["matched"], result["rate"], result["mismatches"]) == (1, 1, 1.0, [])


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        pytest.param({"injected": ["b", "a"]}, "injected", id="injected-order"),
        pytest.param({"top10": ["a", "c", "b"]}, "top10", id="top10-order"),
        pytest.param({"scores": {"a": 0.9 + 2e-6, "b": 0.8, "c": 0.1}}, "scores", id="score-beyond-tolerance"),
        pytest.param({"scores": {"a": 0.9, "b": 0.8}}, "scores", id="score-keys"),
    ],
)
def test_compare_rows_flags_each_field(overrides: dict[str, object], field: str) -> None:
    result = compare_rows(_rows(), _rows(**overrides))
    assert result["matched"] == 0
    assert result["mismatches"] == [{"checkpoint": 300, "item": "obj01", "kind": "question", "fields": [field]}]


def test_compare_rows_tolerates_tiny_score_noise() -> None:
    assert compare_rows(_rows(), _rows(scores={"a": 0.9 + 5e-7, "b": 0.8, "c": 0.1}))["matched"] == 1


def test_compare_rows_requires_the_same_row_keys() -> None:
    with pytest.raises(SystemExit):
        compare_rows(_rows(), _rows(item_id="obj02"))


def _key(minute: int) -> tuple[datetime, uuid.UUID]:
    return datetime(2026, 10, 12, tzinfo=UTC) + timedelta(minutes=minute), uuid.UUID(int=minute)


def test_available_from_turns_counts_assistant_messages_up_to_cursor() -> None:
    # 어시스턴트 메시지(오프닝 제외) 키 = 분 2,4,6,...,20 (10턴). 스냅샷 커서는 6턴째·10턴째 사용자 메시지 직후 응답.
    assistant = [_key(2 * t) for t in range(1, 11)]
    cursors = [_key(12), _key(20)]
    assert available_from_turns(cursors, assistant) == {cursors[0]: 7, cursors[1]: 11}


def test_available_from_turns_uses_key_order_not_minutes_only() -> None:
    at = datetime(2026, 10, 12, tzinfo=UTC)
    assistant = [(at, uuid.UUID(int=1)), (at, uuid.UUID(int=3))]
    cursor = (at, uuid.UUID(int=2))
    assert available_from_turns([cursor], assistant) == {cursor: 2}


def test_recall_warning_count_counts_only_the_recall_failure_line() -> None:
    log = "\n".join(
        [
            "INFO:     127.0.0.1 - POST /chat-rooms/x/messages 200",
            "대화방 abc 장면 기억 회상을 읽지 못해 이번 턴은 회상 없이 조립한다: boom",
            "Traceback (most recent call last):",
            '  File "/x/api/chat/memory_recall.py", line 1, in _recall',
            "RuntimeError: boom",
            "대화방 abc 장면 기억 회상을 읽지 못해 이번 턴은 회상 없이 조립한다: again",
            "대화방 abc 장면 기억 추출을 읽지 못해",
        ]
    )
    assert recall_warning_count(log) == 2
    assert recall_warning_count("") == 0


def _fact_warning(room: str, why: str) -> list[str]:
    """서버가 사실 섹션 조립 실패를 받아 섹션 없이 조립할 때 남기는 경고 줄과 그 스택(서버 문구 그대로)."""
    return [
        f"대화방 {room} 관계·사실 기억을 읽지 못해 이번 턴은 사실 섹션 없이 조립한다: {why}",
        "Traceback (most recent call last):",
        '  File "/app/src/api/chat/memory_fact_section.py", line 9, in facts_for_turn',
        f"RuntimeError: {why}",
    ]


def test_fact_injection_failure_warnings_are_counted_per_arm_from_every_attempt_server_log(tmp_path: Path) -> None:
    from memory_eval.probe import injection_warnings_by_arm

    def attempt(name: str, lines: list[str] | None) -> dict[str, str]:
        folder = tmp_path / name
        folder.mkdir()
        if lines is not None:
            (folder / "server.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"folder": str(folder)}

    recall_line = "대화방 r 장면 기억 회상을 읽지 못해 이번 턴은 회상 없이 조립한다: x"
    # 백그라운드 추출 실패는 주입 실패가 아니다.
    extract_line = "대화방 r 사실 기억 추출 실패 — 다음 턴 뒤에 다시 시도한다: x"
    rows = [
        {"arm": "B2", "item": "sec01", "attempts": [
            attempt("b1", ["INFO: 200", *_fact_warning("r", "a")]),
            attempt("b2", [*_fact_warning("r", "b"), *_fact_warning("r", "c"), extract_line]),
        ]},
        {"arm": "B2", "item": "sec02", "attempts": [attempt("b3", None)]},
        {"arm": "A2", "item": "sec01", "attempts": [attempt("a1", [recall_line, extract_line])]},
    ]  # fmt: skip
    assert injection_warnings_by_arm(rows) == {
        "A2": {"probes": 1, "fact": 0, "recall": 1, "probesWithFactWarning": 0, "missingLogs": 0},
        "B2": {"probes": 2, "fact": 3, "recall": 0, "probesWithFactWarning": 1, "missingLogs": 1},
    }


def test_export_rows_make_episodes_searchable_from_the_turn_after_the_fold_that_wrote_them() -> None:
    """검색 대상이 되는 첫 턴은 그 장면을 쓴 스냅샷이 만들어진 시각까지 들어온 진행자 메시지 수 + 1 이다 — 커서가 덮은 끝이
    아니다(30턴에 접힌 스냅샷의 커서는 10턴 근처에 있다)."""
    from types import SimpleNamespace

    start = datetime(2026, 10, 12, tzinfo=UTC)
    assistant = [start + timedelta(minutes=2 * t) for t in range(1, 41)]  # 1~40턴 응답
    episode = SimpleNamespace(
        id=uuid.UUID(int=7), snapshot_id=uuid.UUID(int=70), ordinal=0, start_turn=1, end_turn=10, title="t",
        detail="d", asserted_by="narration", nouns=["n"], keywords=[], importance=3,
    )  # fmt: skip
    folded_at_30 = start + timedelta(minutes=60, seconds=5)
    [row] = export_rows([(episode, folded_at_30)], assistant)
    assert row["available_from_turn"] == 31
    assert (row["id"], row["end_turn"], row["nouns"]) == (str(uuid.UUID(int=7)), 10, ["n"])
