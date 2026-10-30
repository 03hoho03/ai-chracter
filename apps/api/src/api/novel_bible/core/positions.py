"""이야기 순서 — 사건마다 이야기 시간 위의 위치와, 두 위치 사이의 앞섬(참·거짓·미정).

주선 사건(`present`)은 점 (화 번호, 화 안 차례)이다. 화 번호는 바뀌지 않는다. 회상 사건은 관계로 구간을 얻는다 — `before t`
면 위 끝이 t(배타), `after t` 면 아래 끝이 t(배타), `overlap t` 면 아래·위 끝이 모두 t 다. t 는 관계 대상 블록을 덮는 현재
주선 사건이고, 그런 사건이 없으면(대상 화가 지워졌거나 다시 확정돼 그 블록을 덮는 사건이 없다) 그 관계는 끝을 정하지 않는다.
관계가 없는 회상은 양쪽이 열려 있다. 꿈·상상 사건은 위치가 없다 — 어떤 앞섬도 미정이다."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from api.novel_bible.core.types import EventRow, RelationRow

Point = tuple[int, int]


@dataclass(frozen=True)
class Bound:
    point: Point
    exclusive: bool


@dataclass(frozen=True)
class Interval:
    """이야기 시간 위의 구간. 끝이 None 이면 그쪽으로 열려 있다."""

    lower: Bound | None
    upper: Bound | None


def _point(event: EventRow) -> Point:
    return (event.chapter_ordinal, event.ordinal)


def _tighter_upper(current: Bound | None, new: Bound) -> Bound:
    if current is None or new.point < current.point:
        return new
    if new.point == current.point and new.exclusive:
        return new
    return current


def _tighter_lower(current: Bound | None, new: Bound) -> Bound:
    if current is None or new.point > current.point:
        return new
    if new.point == current.point and new.exclusive:
        return new
    return current


def story_positions(
    events: Sequence[EventRow], relations: Sequence[RelationRow]
) -> dict[uuid.UUID, Interval | None]:
    """사건 id 마다 위치. 관계 대상은 `events` 안에서 대상 블록을 덮는 주선 사건 중 차례가 가장 앞선 것으로 푼다."""
    covering: dict[uuid.UUID, EventRow] = {}
    for event in sorted((e for e in events if e.actuality == "present"), key=_point, reverse=True):
        for block in event.anchor_block_ids:
            covering[block] = event
    positions: dict[uuid.UUID, Interval | None] = {}
    for event in events:
        if event.actuality == "present":
            point = Bound(_point(event), exclusive=False)
            positions[event.id] = Interval(point, point)
        elif event.actuality == "flashback":
            lower: Bound | None = None
            upper: Bound | None = None
            for relation in relations:
                target = covering.get(relation.to_anchor_block_id)
                if relation.from_event_id != event.id or target is None:
                    continue
                at = _point(target)
                if relation.relation == "before":
                    upper = _tighter_upper(upper, Bound(at, exclusive=True))
                elif relation.relation == "after":
                    lower = _tighter_lower(lower, Bound(at, exclusive=True))
                else:
                    upper = _tighter_upper(upper, Bound(at, exclusive=False))
                    lower = _tighter_lower(lower, Bound(at, exclusive=False))
            positions[event.id] = Interval(lower, upper)
        else:
            positions[event.id] = None
    return positions


def _ends_before(upper: Bound | None, lower: Bound | None) -> bool:
    if upper is None or lower is None:
        return False
    if upper.point != lower.point:
        return upper.point < lower.point
    return upper.exclusive or lower.exclusive


def precedes(a: Interval | None, b: Interval | None) -> bool | None:
    """참: a 의 위 끝이 b 의 아래 끝보다 앞(같은 점이면 한쪽이라도 배타). 거짓: b 가 a 를 그렇게 앞서거나 둘이 같은 한 점.
    미정: 그 밖(위치가 없거나 구간이 겹칠 수 있다)."""
    if a is None or b is None:
        return None
    if _ends_before(a.upper, b.lower):
        return True
    if _ends_before(b.upper, a.lower):
        return False
    if a.lower is not None and a.lower == a.upper == b.lower == b.upper:
        return False
    return None
