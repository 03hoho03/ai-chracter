"""개체 이름 정규화, 사실 안정 키(명제 키)와 상태 키.

명제 키는 명제 하나의 이름이다 — 같은 명제는 어느 화·어느 개정에서 다시 뽑혀도 같은 키다. 주어는 개체 id 이고, 대상 칸은
대상이 개체인 종류(소지·능력·관계)면 대상 개체 id, 나머지(생사·출입·속성)는 정규화한 값이다. 유지 여부도 키에 든다 — 얻음과
잃음, 삶과 죽음은 다른 명제다. 지식 행은 이 키로 사실 행에 읽을 때 이어지고, 같은 화를 다시 확정하면 새 행이 같은 키의 앞
행을 대체한다.

개체 id 가 들어도 키는 확정 순서에 기대지 않는다 — 연결 단계가 이름마다 개체를 찾거나 만들어, 한 소설에서 (종류, 정규 이름)은
언제나 같은 개체다. 속성 값은 인물 이름이어도 개체에 잇지 않고 정규화한 값을 쓴다. 값이 "이미 있는" 개체와 맞을 때만 개체 id
를 쓰면, 같은 명제가 그 이름의 개체가 먼저 생겼느냐에 따라 다른 키를 받는다.

상태 키는 저장하지 않고 계산한다 — 생사·출입·속성은 (주어, 종류, 술어), 소지·능력·관계는 (주어, 종류, 술어, 대상). 같은 상태
키의 행 중 이야기 순서로 가장 늦은 것이 그 상태의 값이다(사건 시점 질의가 이것으로 묶는다).

정규화는 채팅 기억의 사실 키와 같은 규칙(`normalize_part`)이다 — 키 값 자체는 채팅 기억 키와 무관하다.

명제를 만드는 규칙(값이 종류에 맞는가, 값을 어떻게 다듬는가, 주어·대상을 어느 종류의 개체로 잇는가)도 여기 한 곳에 둔다. 사실
슬롯과 지식 슬롯이 같은 명제를 같은 키로 받으려면 두 슬롯이 이 규칙을 똑같이 써야 하는데, 슬롯은 서로 import 하지 않는다 —
슬롯마다 사본을 두면 한쪽만 고쳐져 같은 명제의 키가 갈린다."""

import json
import uuid
from typing import get_args

from api.chat.memory_facts import normalize_part
from api.novel_bible.core.types import EntityName, FactRow, Proposition
from api.novel_bible.ids import EntityKind, FactKind, LifeValue, PresenceValue

# 키 공간을 다른 uuid5 와 가르는 고정 이름 공간. 바꾸면 저장된 모든 키가 달라진다.
_FACT_KEY_NAMESPACE = uuid.UUID("6b3f0a52-1d9c-4a37-9e0b-2f4c8d1e7a90")
# 대상이 개체인 종류와 그 대상 개체의 종류 — 대상 칸이 개체 id 이고 상태 키에도 대상이 든다.
VALUE_ENTITY_KINDS: dict[FactKind, EntityKind] = {"possession": "object", "ability": "ability", "relation": "character"}
TARGETED_KINDS: frozenset[FactKind] = frozenset(VALUE_ENTITY_KINDS)
# 값이 정해진 목록 안에 있어야 하는 종류.
_CLOSED_VALUES: dict[FactKind, frozenset[str]] = {
    "life": frozenset(get_args(LifeValue)),
    "presence": frozenset(get_args(PresenceValue)),
}
# 술어가 속성·관계 이름인 종류.
_NAMED_PREDICATE: frozenset[FactKind] = frozenset({"attribute", "relation"})

# (주어 개체, 종류, 술어, 대상 개체 — 대상이 개체인 종류만, 나머지는 None)
StateKey = tuple[uuid.UUID, FactKind, str, uuid.UUID | None]


def normalize_name(text: str | None) -> str:
    return normalize_part(text)


def predicate_norm(kind: FactKind, attribute: str | None) -> str:
    """생사·출입·소지·능력은 종류 이름 그대로, 속성·관계는 정규화한 속성·관계 이름."""
    return normalize_name(attribute) if kind in ("attribute", "relation") else kind


def fact_key(subject: uuid.UUID, kind: FactKind, predicate: str, object_token: str, holds: bool) -> uuid.UUID:
    """같은 명제는 어느 화·어느 개정에서 다시 뽑혀도 같은 키다. 유지 여부가 다르면(얻음·잃음) 다른 명제다."""
    # 술어·값은 자유 서술이라 구분 문자를 품을 수 있어, 칸마다 따옴표로 감싸고 안을 이스케이프하는 JSON 배열로 잇는다.
    parts = [str(subject), kind, predicate, object_token, "1" if holds else "0"]
    return uuid.uuid5(_FACT_KEY_NAMESPACE, json.dumps(parts, ensure_ascii=False, separators=(",", ":")))


def proposition_key(proposition: Proposition, subject: uuid.UUID, value_entity: uuid.UUID | None) -> uuid.UUID:
    """연결을 마친 명제의 키. 대상이 개체인 종류는 대상 개체 id(`value_entity`)를, 나머지는 정규화한 값을 대상 칸에 쓴다."""
    if proposition.kind in TARGETED_KINDS:
        assert value_entity is not None  # 작업 저장 전에 대상 이름이 없는 항목은 버린다
        token = str(value_entity)
    else:
        token = normalize_name(proposition.value)
    predicate = predicate_norm(proposition.kind, proposition.attribute)
    return fact_key(subject, proposition.kind, predicate, token, proposition.holds)


def state_key(fact: FactRow) -> StateKey:
    return (
        fact.subject_entity_id, fact.kind, fact.predicate_norm,
        fact.value_entity_id if fact.kind in TARGETED_KINDS else None,
    )


def proposition_problem(kind: FactKind, attribute: str | None, value: str, holds: bool) -> str | None:
    """명제를 버릴 사유 — 생사·출입 값이 정해진 값이 아님, 값이 빔, 유지가 거짓일 수 없는 종류(생사·출입·속성), 속성·관계
    이름이 빔. 사유 이름은 `Proposal.dropped` 의 열쇠다."""
    norm = normalize_name(value)
    closed = _CLOSED_VALUES.get(kind)
    if closed is not None and norm not in closed:
        return "value_invalid"
    if not norm:
        return "value_empty"
    if not holds and kind not in TARGETED_KINDS:
        return "holds_invalid"
    if kind in _NAMED_PREDICATE and not normalize_name(attribute):
        return "attribute_missing"
    return None


def make_proposition(
    subject: str, subject_kind: EntityKind, kind: FactKind, attribute: str | None, value: str, holds: bool
) -> Proposition:
    """검증을 지난 명제 칸을 다듬는다 — 생사·출입 값은 정규화한 값, 나머지 값과 이름은 앞뒤 공백만 뺀다. 속성·관계가 아니면
    속성 이름을 비운다."""
    return Proposition(
        subject=subject.strip(), subject_kind=subject_kind, kind=kind,
        attribute=(attribute or "").strip() if kind in _NAMED_PREDICATE else None,
        value=normalize_name(value) if kind in _CLOSED_VALUES else value.strip(), holds=holds,
    )


def proposition_names(proposition: Proposition) -> dict[str, tuple[EntityName, ...]]:
    """코어가 개체로 풀 명제의 이름 — 주어는 명제의 주어 종류로 `subject`, 대상이 개체인 종류면 대상을 그 종류의 대상 개체로
    `value`."""
    names: dict[str, tuple[EntityName, ...]] = {
        "subject": (EntityName(kind=proposition.subject_kind, name=proposition.subject),)
    }
    if proposition.kind in VALUE_ENTITY_KINDS:
        names["value"] = (EntityName(kind=VALUE_ENTITY_KINDS[proposition.kind], name=proposition.value),)
    return names
