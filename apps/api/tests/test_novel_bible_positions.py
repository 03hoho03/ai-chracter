"""이야기 순서 — 주선 사건은 (화 번호, 화 안 차례) 점이고, 회상 사건은 관계로 구간을 얻고, 꿈·상상 사건은 위치가 없다.
`precedes` 는 참·거짓·미정 셋을 낸다. 차단 규칙은 참일 때만 막으므로 미정을 참이나 거짓으로 접으면 안 된다."""

import uuid

from api.novel_bible.core.positions import precedes, story_positions
from api.novel_bible.core.types import EventRow, RelationRow
from api.novel_bible.ids import EventActuality, EventRelationKind


def _event(chapter: int, ordinal: int, actuality: EventActuality = "present") -> EventRow:
    return EventRow(
        id=uuid.uuid4(), chapter_id=uuid.uuid4(), chapter_ordinal=chapter, ordinal=ordinal, actuality=actuality,
        anchor_block_ids=(uuid.uuid4(),),
    )


def _relation(source: EventRow, kind: EventRelationKind, target: EventRow) -> RelationRow:
    return RelationRow(
        id=uuid.uuid4(), chapter_id=source.chapter_id, from_event_id=source.id, relation=kind,
        to_anchor_block_id=target.anchor_block_ids[0], to_chapter_id=target.chapter_id,
    )


def test_main_line_events_follow_chapter_then_order_within_the_chapter() -> None:
    first, later_same_chapter, next_chapter = _event(2, 1), _event(2, 3), _event(3, 1)
    positions = story_positions([first, later_same_chapter, next_chapter], [])
    assert precedes(positions[first.id], positions[later_same_chapter.id]) is True
    assert precedes(positions[later_same_chapter.id], positions[next_chapter.id]) is True
    assert precedes(positions[next_chapter.id], positions[first.id]) is False
    # 같은 점은 앞서지 않는다(거짓이지 미정이 아니다).
    assert precedes(positions[first.id], positions[first.id]) is False


def test_a_flashback_before_a_main_event_precedes_it_even_at_the_boundary() -> None:
    earlier, target, memory = _event(1, 1), _event(2, 1), _event(5, 1, "flashback")
    positions = story_positions([earlier, target, memory], [_relation(memory, "before", target)])
    assert precedes(positions[memory.id], positions[target.id]) is True
    assert precedes(positions[target.id], positions[memory.id]) is False
    # 위 끝만 정해져 있어 더 앞의 사건과는 순서를 모른다.
    assert precedes(positions[earlier.id], positions[memory.id]) is None


def test_a_flashback_after_a_main_event_follows_it() -> None:
    target, later, memory = _event(2, 1), _event(4, 1), _event(5, 1, "flashback")
    positions = story_positions([target, later, memory], [_relation(memory, "after", target)])
    assert precedes(positions[target.id], positions[memory.id]) is True
    assert precedes(positions[memory.id], positions[later.id]) is None


def test_two_relations_narrow_a_flashback_to_the_gap_between_them() -> None:
    lower, upper, outside, memory = _event(2, 1), _event(4, 1), _event(6, 1), _event(7, 1, "flashback")
    relations = [_relation(memory, "after", lower), _relation(memory, "before", upper)]
    positions = story_positions([lower, upper, outside, memory], relations)
    assert precedes(positions[lower.id], positions[memory.id]) is True
    assert precedes(positions[memory.id], positions[outside.id]) is True


def test_an_overlapping_flashback_sits_on_its_target() -> None:
    before, target, memory = _event(1, 1), _event(3, 1), _event(5, 1, "flashback")
    positions = story_positions([before, target, memory], [_relation(memory, "overlap", target)])
    assert precedes(positions[before.id], positions[memory.id]) is True
    assert precedes(positions[memory.id], positions[target.id]) is False


def test_a_flashback_without_relations_or_with_a_missing_target_is_undetermined() -> None:
    main = _event(3, 1)
    loose = _event(5, 1, "flashback")
    orphan = _event(5, 2, "flashback")
    gone_target = _event(2, 1)  # 현재 사건 목록에 없다 — 대상 화가 지워졌거나 다시 확정됐다.
    positions = story_positions([main, loose, orphan], [_relation(orphan, "before", gone_target)])
    for memory in (loose, orphan):
        assert precedes(positions[memory.id], positions[main.id]) is None
        assert precedes(positions[main.id], positions[memory.id]) is None


def test_dream_events_have_no_position() -> None:
    main, dream = _event(1, 1), _event(4, 1, "dream_or_imagined")
    positions = story_positions([main, dream], [])
    assert positions[dream.id] is None
    assert precedes(positions[main.id], positions[dream.id]) is None
    assert precedes(positions[dream.id], positions[main.id]) is None
