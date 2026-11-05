"""차단 규칙 넷 — 사망·영구 퇴장 뒤 등장, 얻기 전 사용, 일어나기 전 앎, 불변 속성 모순.

규칙은 스냅숏의 읽기 행(사건·회상 관계·사실·지식)만 읽는다. 이야기 순서는 코어의 위치(`core/positions.py`)로 보고, 차단은 앞섬이
참일 때만이다. 같은 식에서 차단만 빠지는 갈래(순서 미정·시작이 서술되지 않음·돌아올 수 있는 떠남·닫힌 값이 아닌 속성 차이)는
경고 규칙(`rules/warnings.py`)이 같은 판정 함수로 낸다 — 판정을 두 벌 두면 차단과 경고의 경계가 갈린다.

결과는 이번 확정의 새 항목이 하나라도 낀 것만 낸다(검사 틀도 한 번 더 거른다). 차단 결과의 항목은 근거를 다시 확인할 항목이다 —
검사 틀이 그 항목 모두의 원고 근거를 다시 맞춰 보고, 하나라도 맞지 않으면 차단을 경고로 낮춘다.

현실성: 주선(`main`)은 지금 이야기, 실제(`actual`)는 지금 이야기와 회상이다. 꿈·상상 사건은 둘 다 아니다. 작품 범위 사실은 어느
사건보다 앞에서 시작한 것으로 친다(`Order.start`) — 다만 사망·영구 퇴장 뒤 등장은 퇴장·되살아남을 범위와 무관하게 그 사실이 놓인
사건의 자리로 본다. 그 규칙은 퇴장이 서술된 사건과 등장 사건 사이의 앞섬을 묻기 때문이다: 등장 사건에서 "알고 보니 살아 있었다"가
작품 범위로 나와도 그 등장을 막지 않고, 작품 범위의 "오래전에 죽었다"가 그 서술보다 앞 화의 등장을 막지 않는다."""

import re
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations
from typing import Literal

from api.novel_bible.core.positions import Bound, Interval, precedes, story_positions
from api.novel_bible.core.types import BibleSnapshot, EventRow, FactRow, FindingDraft
from api.novel_bible.ids import BlockingRule, FindingRule, SlotId

# 작품 범위 사실의 시작 — 어떤 화 번호보다 앞선 한 점이라 그 사실은 어느 사건보다 먼저 참이다.
_WORK_START: tuple[int, int] = (-(2**62), 0)
_WORK = Interval(Bound(_WORK_START, exclusive=False), Bound(_WORK_START, exclusive=False))


@dataclass(frozen=True)
class Order:
    """스냅숏 하나의 사건 현실성과 이야기 위치."""

    events: dict[uuid.UUID, EventRow]
    positions: dict[uuid.UUID, Interval | None]
    new_ids: frozenset[uuid.UUID]

    @classmethod
    def of(cls, snapshot: BibleSnapshot) -> "Order":
        events = snapshot.events or ()
        return cls(
            events={event.id: event for event in events},
            positions=story_positions(events, snapshot.relations or ()),
            new_ids=snapshot.new_ids,
        )

    def main(self, event_id: uuid.UUID | None) -> bool:
        event = self.events.get(event_id) if event_id is not None else None
        return event is not None and event.actuality == "present"

    def actual(self, event_id: uuid.UUID | None) -> bool:
        event = self.events.get(event_id) if event_id is not None else None
        return event is not None and event.actuality in ("present", "flashback")

    def at(self, event_id: uuid.UUID | None) -> Interval | None:
        return self.positions.get(event_id) if event_id is not None else None

    def start(self, fact: FactRow) -> Interval | None:
        return _WORK if fact.scope == "work" else self.at(fact.valid_from_event_id)

    def touches_new(self, *ids: uuid.UUID) -> bool:
        return not self.new_ids.isdisjoint(ids)


# ── 사망·영구 퇴장 뒤 등장 ──────────────────────────────────────────────


@dataclass(frozen=True)
class ExitCase:
    """퇴장 사실 d 와 그 뒤 주선 등장 a. `undetermined` 면 순서가 미정이라 차단 대신 경고다 — d 의 시작 사건이 없거나, 차단을
    끄는 되살아남·돌아옴(`revivals`)이 모두 퇴장과의 순서가 미정이다."""

    exit: FactRow
    appearance: EventRow
    undetermined: bool
    revivals: tuple[uuid.UUID, ...] = ()


def _is_exit(fact: FactRow, *, departures: bool) -> bool:
    if fact.scope == "scene":
        return False
    if departures:
        return fact.kind == "presence" and fact.value_norm == "departed" and fact.scope == "from_here"
    return (fact.kind, fact.value_norm) in (("life", "dead"), ("presence", "gone_for_good"))


def _undoes(revival: FactRow, exit_fact: FactRow) -> bool:
    """r 이 d 를 되돌리는 값인가 — 생사는 삶, 출입은 돌아옴이 서술된(`onset`) 출석. 생사에 `onset` 을 요구하지 않는 것은 등장
    사건에서 "알고 보니 살아 있었다"를 받기 위해서다. 출입은 등장 사건의 단순 출석이 돌아옴으로 읽히지 않게 요구한다."""
    if (revival.subject_entity_id, revival.kind) != (exit_fact.subject_entity_id, exit_fact.kind):
        return False
    if exit_fact.kind == "life":
        return revival.value_norm == "alive"
    return revival.value_norm == "present" and revival.onset


def exit_cases(snapshot: BibleSnapshot, *, departures: bool = False) -> Iterator[ExitCase]:
    """사망·영구 퇴장 사실(`departures` 면 돌아올 수 있는 떠남)과 그 주어가 등장한 주선 사건의 짝 중 차단 식이 참이거나 순서만
    미정인 것. 되살아남 창 r 은 실제 사건에서, 퇴장과 다른 사건에서, 퇴장보다 앞서지 않고 등장보다 늦지 않은 것이다 — 퇴장과
    같은 사건의 출석·삶은 그 장면에 서 있던 것이지 되돌림이 아니다. 퇴장 d 와 되살아남 r 의 자리는 범위와 무관하게 그 사실의
    시작 사건이다. 돌아올 수 있는 떠남은 순서 미정 갈래가 없다(되돌림이 하나라도 있으면 결과 없음)."""
    if snapshot.facts is None or snapshot.events is None:
        return
    order = Order.of(snapshot)
    for exit_fact in snapshot.facts:
        if not _is_exit(exit_fact, departures=departures):
            continue
        exit_event = exit_fact.valid_from_event_id
        if exit_event is not None and not order.main(exit_event):
            continue
        for appearance in snapshot.events:
            if not order.main(appearance.id) or exit_fact.subject_entity_id not in appearance.present_entity_ids:
                continue
            if not order.touches_new(exit_fact.id, appearance.id):
                continue
            if exit_event is None:
                if not departures:
                    yield ExitCase(exit_fact, appearance, undetermined=True)
                continue
            exit_at, appear_at = order.at(exit_event), order.at(appearance.id)
            if precedes(exit_at, appear_at) is not True:
                continue
            revivals = [
                revival
                for revival in snapshot.facts
                if _undoes(revival, exit_fact)
                and order.actual(revival.valid_from_event_id)
                and revival.valid_from_event_id != exit_event
                and precedes(order.at(revival.valid_from_event_id), exit_at) is not True
                and precedes(appear_at, order.at(revival.valid_from_event_id)) is not True
            ]
            if not revivals:
                yield ExitCase(exit_fact, appearance, undetermined=False)
            elif not departures and not any(precedes(order.at(r.valid_from_event_id), exit_at) is False for r in revivals):
                yield ExitCase(exit_fact, appearance, undetermined=True, revivals=tuple(r.id for r in revivals))


# ── 얻기 전 사용 · 일어나기 전 앎 ────────────────────────────────────────

Verdict = Literal["block", "onset_unstated", "undetermined"]


@dataclass(frozen=True)
class PriorCase:
    """사용 u(또는 앎 k)와 그것이 기대는 사실들(획득 A 또는 같은 명제 F). `block` 은 모든 사실이 이 장면에서 시작됐다고
    서술됐고 모두 u·k 보다 뒤의 주선 사건에서다. `onset_unstated` 는 순서는 같은데 이미 참이던 상태로 서술된 사실이 있다.
    `undetermined` 는 시작이 모두 서술됐는데 순서를 모르는 사실(시작 사건 없음)이 있다."""

    rule: BlockingRule
    anchor: uuid.UUID
    facts: tuple[FactRow, ...]
    verdict: Verdict
    order: Order

    def block_items(self) -> tuple[uuid.UUID, ...]:
        """근거를 다시 확인할 항목 — u·k 와 가장 이른 사실, 그리고 이번 확정의 새 사실(검사 틀이 새 항목이 낀 결과만 남긴다)."""
        earliest = min(self.facts, key=self._point)
        new = [fact.id for fact in self.facts if fact is not earliest and fact.id in self.order.new_ids]
        return (self.anchor, earliest.id, *new)

    def items(self) -> tuple[uuid.UUID, ...]:
        return (self.anchor, *(fact.id for fact in self.facts))

    def _point(self, fact: FactRow) -> tuple[int, int]:
        start = self.order.start(fact)
        assert start is not None and start.lower is not None  # 차단 판정은 모든 사실이 주선 사건의 점일 때만이다
        return start.lower.point


def _starts_after(order: Order, anchor: Interval | None, facts: Sequence[FactRow]) -> bool | None:
    """모든 사실이 작품 범위가 아니고 주선 사건에서 시작해 `anchor` 보다 뒤인가 — 참·거짓·미정(시작 사건 없음, 앞섬 미정)."""
    result: bool | None = True
    for fact in facts:
        if fact.scope == "work":
            return False
        if fact.valid_from_event_id is None:
            result = None
            continue
        if not order.main(fact.valid_from_event_id):
            return False
        after = precedes(anchor, order.start(fact))
        if after is False:
            return False
        if after is None:
            result = None
    return result


def _verdict(order: Order, anchor: Interval | None, facts: Sequence[FactRow]) -> Verdict | None:
    after = _starts_after(order, anchor, facts)
    stated = all(fact.onset for fact in facts)
    if after is True:
        return "block" if stated else "onset_unstated"
    if after is None and stated:
        return "undetermined"
    return None


@dataclass(frozen=True)
class Use:
    event: EventRow
    actor: uuid.UUID
    thing: uuid.UUID
    acquisitions: tuple[FactRow, ...]


def main_uses(snapshot: BibleSnapshot) -> Iterator[Use]:
    """주선 사건의 사용마다 같은 (행위자, 대상)을 지금 지닌다는 소지·능력 사실들."""
    if snapshot.facts is None or snapshot.events is None:
        return
    order = Order.of(snapshot)
    for event in snapshot.events:
        if not order.main(event.id):
            continue
        for actor, thing in dict.fromkeys(event.uses):
            acquisitions = tuple(
                fact for fact in snapshot.facts
                if fact.subject_entity_id == actor and fact.kind in ("possession", "ability")
                and fact.value_entity_id == thing and fact.holds
            )
            yield Use(event, actor, thing, acquisitions)


def use_cases(snapshot: BibleSnapshot) -> Iterator[PriorCase]:
    order = Order.of(snapshot)
    for use in main_uses(snapshot):
        if not use.acquisitions or not order.touches_new(use.event.id, *(f.id for f in use.acquisitions)):
            continue
        verdict = _verdict(order, order.at(use.event.id), use.acquisitions)
        if verdict is not None:
            yield PriorCase("use_before_acquisition", use.event.id, use.acquisitions, verdict, order)


def knowledge_cases(snapshot: BibleSnapshot) -> Iterator[PriorCase]:
    """`knows` 앎마다 같은 명제 키의 사실들. 알게 된 사건이 있으면 주선이어야 하고(회상·꿈 속 앎은 결과 없음), 없으면 순서
    미정이다. 시작 서술(`onset`)은 사실에만 건다 — 이미 알던 것을 늦게 서술하면 알게 된 사건이 늦어질 뿐이다."""
    if snapshot.knowledge is None or snapshot.facts is None or snapshot.events is None:
        return
    order = Order.of(snapshot)
    for known in snapshot.knowledge:
        if known.kind != "knows":
            continue
        if known.known_since_event_id is not None and not order.main(known.known_since_event_id):
            continue
        facts = tuple(fact for fact in snapshot.facts if fact.fact_key == known.fact_key)
        if not facts or not order.touches_new(known.id, *(fact.id for fact in facts)):
            continue
        verdict = _verdict(order, order.at(known.known_since_event_id), facts)
        if verdict is not None:
            yield PriorCase("knowledge_before_fact", known.id, facts, verdict, order)


# ── 불변 속성 모순 ────────────────────────────────────────────────────

# 닫힌 값 사전 — 정규 표기(사실 값의 정규화 `value_norm` 과 같은 꼴) → (범주, 정규 값). 두 값이 같은 범주에 들고 정규 값이 다를
# 때만 불변 속성 모순으로 막는다. 성별은 넣지 않는다 — 위장 신분이 드러나는 반전("알고 보니 여자였다")이 그대로 차단 표면이
# 된다. 초록·파랑 어느 쪽으로도 읽히는 "푸른색"과, 보라와 다홍 사이인 "자주색"은 넣지 않는다 — 다른 색으로 읽힐 수 있는 값이
# 들면 같은 색의 두 표기가 막힌다.
CLOSED_ATTRIBUTE_VALUES: dict[str, tuple[str, str]] = {
    **{surface: ("혈액형", "A") for surface in ("a", "a형", "에이형")},
    **{surface: ("혈액형", "B") for surface in ("b", "b형", "비형")},
    **{surface: ("혈액형", "O") for surface in ("o", "o형", "오형")},
    **{surface: ("혈액형", "AB") for surface in ("ab", "ab형", "에이비형")},
    **{surface: ("색", "검정") for surface in ("검정", "검정색", "검은색", "까만색", "흑색", "black")},
    **{surface: ("색", "하양") for surface in ("하양", "흰색", "하얀색", "백색", "white")},
    **{surface: ("색", "빨강") for surface in ("빨강", "빨간색", "붉은색", "적색", "red")},
    **{surface: ("색", "파랑") for surface in ("파랑", "파란색", "청색", "blue")},
    **{surface: ("색", "노랑") for surface in ("노랑", "노란색", "황색", "yellow")},
    **{surface: ("색", "초록") for surface in ("초록", "초록색", "녹색", "green")},
    **{surface: ("색", "갈색") for surface in ("갈색", "밤색", "brown")},
    **{surface: ("색", "회색") for surface in ("회색", "잿빛", "gray", "grey")},
    **{surface: ("색", "보라") for surface in ("보라", "보라색", "purple")},
}

# 아라비아 숫자와 세 글자 이하 단위. 정규화한 값은 공백이 한 칸으로 줄어 있다.
_NUMBER = re.compile(r"^([+-]?\d+(?:\.\d+)?)\s*(\S{0,3})$", re.ASCII)

ClosedValue = tuple[str, Decimal | str]


def closed_value(value_norm: str) -> ClosedValue | None:
    """닫힌 값이면 (갈래, 비교 값) — 숫자는 단위가 갈래이고, 사전 값은 범주가 갈래다. 자유 서술(개체를 가리키는 값 포함)은 None."""
    number = _NUMBER.match(value_norm)
    if number is not None:
        return f"number:{number.group(2)}", Decimal(number.group(1))
    known = CLOSED_ATTRIBUTE_VALUES.get(value_norm)
    if known is not None:
        return f"enum:{known[0]}", known[1]
    return None


@dataclass(frozen=True)
class AttributePair:
    """같은 주어·술어의 속성 두 값(한쪽 이상 불변, 정규화 값이 다름). `closed` 면 둘 다 불변이고 같은 갈래의 다른 닫힌 값이다."""

    items: tuple[uuid.UUID, uuid.UUID]
    closed: bool


def attribute_pairs(snapshot: BibleSnapshot) -> Iterator[AttributePair]:
    """닫힌 값으로 같은 값(같은 색의 두 표기, 단위 앞 공백)이면 결과가 없다. 항목은 앞선 정본 항목, 이번 확정 항목 차례다."""
    if snapshot.facts is None:
        return
    attributes = [fact for fact in snapshot.facts if fact.kind == "attribute"]
    for first, second in combinations(attributes, 2):
        if (first.subject_entity_id, first.predicate_norm) != (second.subject_entity_id, second.predicate_norm):
            continue
        if not (first.immutable or second.immutable) or first.value_norm == second.value_norm:
            continue
        if snapshot.new_ids.isdisjoint((first.id, second.id)):
            continue
        one, two = closed_value(first.value_norm), closed_value(second.value_norm)
        if one is not None and one == two:
            continue
        older, newer = sorted((first, second), key=lambda fact: fact.id in snapshot.new_ids)
        closed = first.immutable and second.immutable and one is not None and two is not None and one[0] == two[0]
        yield AttributePair((older.id, newer.id), closed)


# ── 규칙 ───────────────────────────────────────────────────────────


class ExitThenAppearance:
    """사망·영구 퇴장 뒤의 주선 등장."""

    rule: FindingRule = "exit_then_appearance"
    slots: frozenset[SlotId] = frozenset({"facts", "events"})

    def check(self, snapshot: BibleSnapshot) -> list[FindingDraft]:
        return [
            FindingDraft(severity="block", rule=self.rule, item_ids=(case.exit.id, case.appearance.id))
            for case in exit_cases(snapshot)
            if not case.undetermined
        ]


class UseBeforeAcquisition:
    """그 소지·능력을 이 장면에서 얻었다고 서술된 모든 사실보다 앞선 주선 사용."""

    rule: FindingRule = "use_before_acquisition"
    slots: frozenset[SlotId] = frozenset({"facts", "events"})

    def check(self, snapshot: BibleSnapshot) -> list[FindingDraft]:
        return [
            FindingDraft(severity="block", rule=self.rule, item_ids=case.block_items())
            for case in use_cases(snapshot)
            if case.verdict == "block"
        ]


class KnowledgeBeforeFact:
    """그 일이 일어났다고 서술되기 전에 이미 안다. "그 자리에 없었는데 안다"는 막지 않는다 — 전달을 구조로 추적하지 않는다."""

    rule: FindingRule = "knowledge_before_fact"
    slots: frozenset[SlotId] = frozenset({"knowledge", "facts", "events"})

    def check(self, snapshot: BibleSnapshot) -> list[FindingDraft]:
        return [
            FindingDraft(severity="block", rule=self.rule, item_ids=case.block_items())
            for case in knowledge_cases(snapshot)
            if case.verdict == "block"
        ]


class ImmutableAttributeMismatch:
    """둘 다 불변인 같은 주어·술어 속성이 같은 갈래의 다른 닫힌 값이다. 회상도 예외가 아니다(시점과 무관)."""

    rule: FindingRule = "immutable_attribute_mismatch"
    slots: frozenset[SlotId] = frozenset({"facts"})

    def check(self, snapshot: BibleSnapshot) -> list[FindingDraft]:
        return [
            FindingDraft(severity="block", rule=self.rule, item_ids=pair.items)
            for pair in attribute_pairs(snapshot)
            if pair.closed
        ]


BLOCKING_RULES = (ExitThenAppearance(), UseBeforeAcquisition(), KnowledgeBeforeFact(), ImmutableAttributeMismatch())
