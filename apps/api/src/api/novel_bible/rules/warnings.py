"""경고 규칙 — 커밋을 막지 않고 검사 결과 행으로만 남는다(차단된 확정에도 남는다). 판정 호출이 필요한 두 이름(모델 판정의
충돌·판정 실패)은 판정 단계가 낸다.

차단 식에서 갈라지는 경고(순서 미정·시작이 서술되지 않음·돌아올 수 있는 떠남·닫힌 값이 아닌 속성 차이)는 차단 규칙과 같은
판정 함수(`rules/blocking.py`)를 쓴다. 판정 후보인 경고는 결과에 후보 표시(`judge`)를 싣는다 — 순서 미정은 J1, 속성 표면
차이는 J2, 앎의 출처 불명은 J3. 차단 식에서 갈라진 경고는 그 차단 규칙 이름(`rule`)을 싣는다 — 근거 확인에 실패해 낮춘 차단이
원래 규칙 이름을 싣는 것과 같은 칸이다."""

import uuid

from api.novel_bible.core.positions import precedes
from api.novel_bible.core.types import BibleSnapshot, FactRow, FindingDraft, KnowledgeRow
from api.novel_bible.ids import FindingRule, SlotId
from api.novel_bible.rules.blocking import (
    Order,
    attribute_pairs,
    exit_cases,
    knowledge_cases,
    main_uses,
    use_cases,
)

_EXIT_SLOTS: frozenset[SlotId] = frozenset({"facts", "events"})


class OrderUndetermined:
    """차단 식(사망 뒤 등장·얻기 전 사용·일어나기 전 앎)의 다른 조건은 맞는데 순서가 미정이다 — 시작 사건이 없거나, 사망 뒤
    등장을 끄는 되살아남·돌아옴이 모두 죽음과의 순서가 미정이다(그때는 그 행들을 `revivals` 로 싣는다).

    읽는 슬롯은 사실·사건이다. 일어나기 전 앎 갈래는 지식 슬롯이 등록돼 있을 때만 본다 — 지식 슬롯을 뺀 등록부에서 앞 두 갈래까지
    건너뛰지 않게."""

    rule: FindingRule = "order_undetermined"
    slots: frozenset[SlotId] = _EXIT_SLOTS

    def check(self, snapshot: BibleSnapshot) -> list[FindingDraft]:
        findings = [
            FindingDraft(
                severity="warning", rule=self.rule, item_ids=(case.exit.id, case.appearance.id),
                payload={"rule": "exit_then_appearance", "judge": "J1", "revivals": [str(r) for r in case.revivals]},
            )
            for case in exit_cases(snapshot)
            if case.undetermined
        ]
        for case in (*use_cases(snapshot), *knowledge_cases(snapshot)):
            if case.verdict == "undetermined":
                findings.append(
                    FindingDraft(severity="warning", rule=self.rule, item_ids=case.items(),
                                 payload={"rule": case.rule, "judge": "J1"})
                )
        return findings


class ReturnUnstated:
    """돌아올 수 있는 떠남(`departed`·`from_here`) 뒤 돌아옴 서술(`present`·`onset`) 없는 주선 등장. 장면 단위 퇴장 뒤 등장은
    결과가 없다 — 그 퇴장은 장면과 함께 끝난다."""

    rule: FindingRule = "return_unstated"
    slots: frozenset[SlotId] = _EXIT_SLOTS

    def check(self, snapshot: BibleSnapshot) -> list[FindingDraft]:
        return [
            FindingDraft(severity="warning", rule=self.rule, item_ids=(case.exit.id, case.appearance.id))
            for case in exit_cases(snapshot, departures=True)
        ]


class OnsetUnstated:
    """얻기 전 사용·일어나기 전 앎의 순서 조건은 참인데 획득·사실 중 "이미 참이던 상태"로 서술된 것이 있다. 일어나기 전 앎
    갈래는 지식 슬롯이 등록돼 있을 때만 본다."""

    rule: FindingRule = "onset_unstated"
    slots: frozenset[SlotId] = _EXIT_SLOTS

    def check(self, snapshot: BibleSnapshot) -> list[FindingDraft]:
        return [
            FindingDraft(severity="warning", rule=self.rule, item_ids=case.items(), payload={"rule": case.rule})
            for case in (*use_cases(snapshot), *knowledge_cases(snapshot))
            if case.verdict == "onset_unstated"
        ]


class UseWithoutAcquisition:
    """이번 확정의 주선 사용인데 그 (행위자, 대상)을 지닌다는 사실이 정본에 없다."""

    rule: FindingRule = "use_without_acquisition"
    slots: frozenset[SlotId] = _EXIT_SLOTS

    def check(self, snapshot: BibleSnapshot) -> list[FindingDraft]:
        return [
            FindingDraft(
                severity="warning", rule=self.rule, item_ids=(use.event.id,),
                payload={"actor": str(use.actor), "thing": str(use.thing)},
            )
            for use in main_uses(snapshot)
            if not use.acquisitions and use.event.id in snapshot.new_ids
        ]


class UseAfterLoss:
    """같은 (행위자, 대상)을 잃은 사실 l 이 실제 사건에서 주선 사용보다 앞서고, 그 사이 다시 지닌다는 사실이 없다. 다시 지님 g 의
    창은 사망 뒤 등장의 되살아남 창과 같다 — 잃음보다 앞서지 않고 사용보다 늦지 않다(사용과 같은 사건에서 되찾은 것도 친다)."""

    rule: FindingRule = "use_after_loss"
    slots: frozenset[SlotId] = _EXIT_SLOTS

    def check(self, snapshot: BibleSnapshot) -> list[FindingDraft]:
        if snapshot.facts is None:
            return []
        order = Order.of(snapshot)
        findings: list[FindingDraft] = []
        for use in main_uses(snapshot):
            used_at = order.at(use.event.id)
            for lost in snapshot.facts:
                if not self._loses(lost, use.actor, use.thing) or not order.actual(lost.valid_from_event_id):
                    continue
                lost_at = order.start(lost)
                if precedes(lost_at, used_at) is not True or not order.touches_new(use.event.id, lost.id):
                    continue
                regained = any(
                    held.valid_from_event_id is not None
                    and order.actual(held.valid_from_event_id)
                    and precedes(order.start(held), lost_at) is not True
                    and precedes(used_at, order.start(held)) is not True
                    for held in use.acquisitions
                )
                if not regained:
                    findings.append(
                        FindingDraft(severity="warning", rule=self.rule, item_ids=(use.event.id, lost.id))
                    )
        return findings

    @staticmethod
    def _loses(fact: FactRow, actor: uuid.UUID, thing: uuid.UUID) -> bool:
        return (
            fact.subject_entity_id == actor and fact.kind in ("possession", "ability")
            and fact.value_entity_id == thing and not fact.holds
        )


class KnowledgeSourceUnclear:
    """이번 확정의 `knows` 앎 k 에서, 그 명제 키의 가장 이른 주선 사실 사건 e_f 가 알게 된 사건보다 앞서는데 앎 주체가 e_f 에
    없고, 정본에 같은 키를 그 전에(같은 사건 포함) 아는 다른 인물 지식도 없다. 판정 후보(J3)다 — 전달 사건을 구조로 추적하지
    않아 이 조건만으로는 오탐이 크다. 작품 범위 사실이 있는 키는 처음부터 참이라 보지 않는다."""

    rule: FindingRule = "knowledge_source_unclear"
    slots: frozenset[SlotId] = frozenset({"knowledge", "facts", "events"})

    def check(self, snapshot: BibleSnapshot) -> list[FindingDraft]:
        if snapshot.knowledge is None or snapshot.facts is None:
            return []
        order = Order.of(snapshot)
        findings: list[FindingDraft] = []
        for known in snapshot.knowledge:
            if known.kind != "knows" or known.id not in snapshot.new_ids:
                continue
            first = self._earliest(order, [fact for fact in snapshot.facts if fact.fact_key == known.fact_key])
            if first is None:
                continue
            known_at = order.at(known.known_since_event_id)
            if precedes(order.at(first.valid_from_event_id), known_at) is not True:
                continue
            witness = order.events[first.valid_from_event_id] if first.valid_from_event_id else None
            if witness is not None and known.knower_entity_id in witness.present_entity_ids:
                continue
            if any(self._told(order, other, known) for other in snapshot.knowledge):
                continue
            findings.append(
                FindingDraft(severity="warning", rule=self.rule, item_ids=(known.id, first.id), payload={"judge": "J3"})
            )
        return findings

    @staticmethod
    def _earliest(order: Order, facts: list[FactRow]) -> FactRow | None:
        if not facts or any(fact.scope == "work" for fact in facts):
            return None
        main = [fact for fact in facts if order.main(fact.valid_from_event_id)]
        return min(main, key=lambda fact: _point(order, fact), default=None)

    @staticmethod
    def _told(order: Order, other: KnowledgeRow, known: KnowledgeRow) -> bool:
        if other.kind != "knows" or other.fact_key != known.fact_key or other.knower_entity_id == known.knower_entity_id:
            return False
        if other.known_since_event_id is None:
            return False
        if other.known_since_event_id == known.known_since_event_id:
            return True
        return precedes(order.at(other.known_since_event_id), order.at(known.known_since_event_id)) is True


def _point(order: Order, fact: FactRow) -> tuple[int, int]:
    start = order.at(fact.valid_from_event_id)
    assert start is not None and start.lower is not None  # 주선 사건은 늘 점이다
    return start.lower.point


class EvidenceUnverified:
    """차단 조건은 맞는데 관련 항목의 원고 근거를 지금 개정 글에서 다시 확인하지 못했다. 근거 확인은 DB 의 개정 글을 읽어야
    해서 스냅숏만 받는 규칙이 할 수 없다 — 검사 틀(`core/pipeline.py` 의 `_check`)이 차단 결과마다 확인하고 맞지 않으면 이
    이름으로 낮춘다. 이 규칙 자체는 결과를 내지 않고, 규칙 목록이 경고 이름을 빠짐없이 싣게 한다."""

    rule: FindingRule = "evidence_unverified"
    slots: frozenset[SlotId] = frozenset()

    def check(self, snapshot: BibleSnapshot) -> list[FindingDraft]:
        return []


class AttributeSurfaceDiffers:
    """같은 주어·술어에서 한쪽 이상이 불변인 속성 값이 다른데 불변 속성 모순 차단은 아니다 — 자유 서술 값, 개체를 가리키는 값,
    한쪽만 불변, 갈래가 다른 닫힌 값. 판정 후보(J2)다."""

    rule: FindingRule = "attribute_surface_differs"
    slots: frozenset[SlotId] = frozenset({"facts"})

    def check(self, snapshot: BibleSnapshot) -> list[FindingDraft]:
        return [
            FindingDraft(severity="warning", rule=self.rule, item_ids=pair.items, payload={"judge": "J2"})
            for pair in attribute_pairs(snapshot)
            if not pair.closed
        ]


WARNING_RULES = (
    OrderUndetermined(), ReturnUnstated(), OnsetUnstated(), UseWithoutAcquisition(), UseAfterLoss(),
    KnowledgeSourceUnclear(), EvidenceUnverified(), AttributeSurfaceDiffers(),
)
