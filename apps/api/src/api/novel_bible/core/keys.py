"""개체 이름 정규화와 사실 안정 키.

안정 키는 명제가 가리키는 상태 하나의 이름이다 — 같은 상태면 어느 화·어느 개정에서 다시 뽑혀도, 어느 소설이든 같은 키가 된다.
키는 이름에서만 나오고 개체 표를 보지 않는다(개체 표에 그 이름이 언제 생겼는지에 따라 키가 달라지면 안 된다). 상태가 값을
갖는 종류(생사·출입·속성)는 값이 키에 들지 않아 값이 바뀌어도 같은 상태로 묶이고, 대상이 개체인 종류(소지·능력·관계)는 대상이
키에 들어 "무엇을 가졌는가"마다 따로 상태가 된다. 정규화는 채팅 기억의 사실 키와 같은 규칙(`normalize_part`)이다 — 키 값
자체는 채팅 기억 키와 무관하다."""

import uuid

from api.chat.memory_facts import normalize_part
from api.novel_bible.core.types import Proposition

# 키 공간을 다른 uuid5 와 가르는 고정 이름 공간. 바꾸면 저장된 모든 키가 달라진다.
_FACT_KEY_NAMESPACE = uuid.UUID("6b3f0a52-1d9c-4a37-9e0b-2f4c8d1e7a90")
_TARGETED_KINDS = frozenset({"possession", "ability", "relation"})


def normalize_name(text: str | None) -> str:
    return normalize_part(text)


def fact_key(proposition: Proposition) -> uuid.UUID:
    target = proposition.value if proposition.kind in _TARGETED_KINDS else ""
    parts = (proposition.kind, proposition.subject, proposition.attribute or "", target)
    return uuid.uuid5(_FACT_KEY_NAMESPACE, "\x1f".join(normalize_name(part) for part in parts))
