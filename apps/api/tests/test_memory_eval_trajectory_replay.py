"""지난 턴 궤적 재조립의 상태 재구성 규칙 — 턴 경계, 그 턴이 본 스냅샷, 스냅샷 순서·수 교차 확인, 섹션 자르기."""

import datetime as dt

import pytest

from api.db.models import ChatMessageRole
from api.db.models.prompt import PromptSection
from memory_eval.trajectory_replay import (
    check_snapshot_count,
    check_snapshot_order,
    section_header,
    section_text,
    snapshot_counts,
    snapshots_seen_at,
    turn_user_indices,
)

U, A = ChatMessageRole.USER, ChatMessageRole.ASSISTANT


def test_turns_start_after_opening_and_skip_unanswered_user_message() -> None:
    # 오프닝, 턴 1, 응답 없는 사용자 메시지(유실 턴), 턴 2
    assert turn_user_indices([A, U, A, U, U, A]) == [1, 4]


def _log() -> list[dict[str, object]]:
    """접기가 턴 30·40 응답 뒤에 일어난 넣기 기록(얼리기 줄 포함)."""
    rows: list[dict[str, object]] = [
        {"turn": t, "snapshots": 0 if t < 30 else (1 if t < 40 else 2)} for t in range(1, 46)
    ]
    rows.append({"turn": 45, "frozen": "tpl", "fingerprint": {}})
    return rows


def test_fold_after_response_is_seen_from_the_next_turn() -> None:
    counts = snapshot_counts(_log())
    assert snapshots_seen_at(1, counts) == 0
    assert snapshots_seen_at(30, counts) == 0
    assert snapshots_seen_at(31, counts) == 1
    assert snapshots_seen_at(40, counts) == 1
    assert snapshots_seen_at(41, counts) == 2


def test_missing_log_line_refuses() -> None:
    counts = snapshot_counts(_log())
    assert snapshots_seen_at(46, counts) == 2  # 얼리기 줄은 스냅샷 칸이 없어 같은 턴의 넣기 줄을 덮지 않는다
    with pytest.raises(SystemExit, match="턴 46"):
        snapshots_seen_at(47, counts)


def test_snapshot_count_cross_check_refuses_disagreement() -> None:
    check_snapshot_count(31, from_log=1, created_before=1)
    with pytest.raises(SystemExit, match="턴 31"):
        check_snapshot_count(31, from_log=1, created_before=2)


def test_snapshot_order_must_agree_between_creation_and_cursor() -> None:
    t0 = dt.datetime(2026, 10, 14, tzinfo=dt.UTC)
    created = [t0, t0 + dt.timedelta(seconds=1)]
    check_snapshot_order(created, [(t0, "a"), (t0 + dt.timedelta(seconds=5), "b")])
    with pytest.raises(SystemExit, match="생성 순과 커서 순"):
        check_snapshot_order(created, [(t0 + dt.timedelta(seconds=5), "b"), (t0, "a")])


def test_section_text_skips_header_mentioned_inside_another_section() -> None:
    prompt = "앞\n\n[회상]\n[사실] 과 다르면 사실을 따른다\n- 장면\n\n[사실]\n- 줄 하나\n\n끝"
    assert section_text(prompt, "[사실]") == "[사실]\n- 줄 하나"
    assert section_text(prompt, "[회상]") == "[회상]\n[사실] 과 다르면 사실을 따른다\n- 장면"
    assert section_text("앞\n\n[회상]\n[사실] 과 다르면\n\n끝", "[사실]") == ""


def _section(slot: str, body: str, scope: str = "story") -> PromptSection:
    return PromptSection(channel="generation", scope=scope, slot=slot, body=body)


def test_section_header_is_the_single_first_line() -> None:
    assert section_header([_section("memory_facts", "[사실]\n{memory_fact_lines}")], "memory_facts") == "[사실]"
    two = [_section("memory_facts", "[사실]\n{x}"), _section("memory_facts", "[다른]\n{x}", scope="character")]
    with pytest.raises(SystemExit, match="하나가 아니다"):
        section_header(two, "memory_facts")
    with pytest.raises(SystemExit, match="머리글이 아니다"):
        section_header([_section("memory_facts", "{memory_fact_lines}")], "memory_facts")
