"""장면 인물 집합과 지식 범위 필터 — 아는 사람이 이번 장면에 없는 비밀 사실을 사실 섹션 후보에서 뺀다. DB·LLM 을 쓰지 않는
순수 함수라 매 턴 조립(`chat/memory_fact_section.py`)과 지난 턴을 다시 계산하는 측정 도구가 같은 함수를 부른다.

방 이름: 방 사실 행의 주어·관계 대상·말한 사람·아는 사람 원소와, 호출부가 더 주는 이름이다. 매 턴 조립은 더 주지 않는다 —
필터 판정은 아는 사람 원소가 장면에 나오는가뿐이고 그 원소는 이미 사실 행에서 들어오므로, 미디어 북 인물이나 작품 이름을 더해도
판정이 바뀌지 않는다. 키워드북 키워드는 이름인지 사물인지 가를 수 없어 쓰지 않는다. 사실 키와 같은 정규화(`normalize_part`)를
하고, 2자 미만은 흔한 글자라 아무 턴에나 걸리므로 버린다.

사용자는 장면 인물에서 뺀다. 생성 모델이 연기하는 쪽은 사용자가 아니라 사용자의 앎은 누출 위험이 아니고, 진행자는 사용자를
이름으로 자주 불러 사용자를 세면 그런 턴마다 다른 인물만 있는 장면에서도 사용자에게 털어놓은 비밀이 남는다. 사용자 표기는
대화 프로필 이름(있으면)과, 프로필 이름이 없을 때 추출이 사용자를 적을 수 있는 표기 셋 — 대화 줄 라벨, `{{user}}` 대체어,
사실 추출 지시문이 사용자를 부르는 낱말 — 이다. 추출 지시문은 이름이 없을 때 쓸 표기를 정하지 않아 모델이 이 중 무엇이든 쓴다.

장면 인물: 방 이름 중 정규화한 이번 턴 사용자 메시지나 직전 응답에 부분 문자열로 나오는 것. 어절 토큰 일치는 "유나한테서"처럼
조사가 두 겹이면 놓친다. 부분 문자열의 오탐은 장면 인물을 넓혀 행을 남기는 쪽(필터가 없을 때의 동작 쪽)으로만 틀린다. 두 글은
따로 본다 — 이어 붙이면 경계를 걸친 가짜 일치가 생긴다.

필터: 아는 사람이 정해진 행은 그 이름 중 하나가 장면 인물일 때만 남는다. 정해지지 않은 행(공개이거나 알 수 없음)은 늘 남는다.
장면 인물에 사용자가 없으므로 사용자만 아는 비밀은 늘 빠진다."""

from collections.abc import Iterable

from api.chat.memory_facts import normalize_part
from api.content.author_macros import FALLBACK_USER_NAME
from api.db.models.chat import ChatMemoryFact

# 사실 추출 지시문이 사용자를 부르는 낱말 — 프로필 이름이 없는 방에서 추출이 아는 사람·말한 사람에 이 낱말을 그대로 적을 수 있다.
USER_INSTRUCTION_WORD = "사용자 인물"
MIN_NAME_CHARS = 2


def user_names(persona_name: str | None, user_label: str) -> frozenset[str]:
    """사용자로 볼 표기(정규화) — 프로필 이름(있으면)·대화 줄 라벨·`{{user}}` 대체어·지시문 낱말."""
    forms = (persona_name, user_label, FALLBACK_USER_NAME, USER_INSTRUCTION_WORD)
    return frozenset(normalized for normalized in (normalize_part(form) for form in forms) if normalized)


def room_names(rows: Iterable[ChatMemoryFact], extra: Iterable[str], *, users: frozenset[str]) -> frozenset[str]:
    """방 이름(정규화, 2자 이상, 사용자 표기 제외). `rows` 는 그 턴에 읽은 방 사실 행 전부, `extra` 는 호출부의 이름 출처다."""
    raw: list[str | None] = list(extra)
    for row in rows:
        raw += [row.subject, row.object if row.kind == "relation" else None, row.speaker, *(row.known_by or ())]
    names = (normalize_part(name) for name in raw)
    return frozenset(name for name in names if len(name) >= MIN_NAME_CHARS and name not in users)


def scene_people(names: Iterable[str], texts: Iterable[str]) -> frozenset[str]:
    """`names`(정규화한 방 이름) 중 `texts`(이번 사용자 메시지·직전 응답) 하나에라도 부분 문자열로 나오는 것."""
    normalized = [normalize_part(text) for text in texts]
    return frozenset(name for name in names if any(name in text for text in normalized))


def known_in_scene(row: ChatMemoryFact, scene: frozenset[str]) -> bool:
    """이 행을 사실 섹션 후보로 남기는가 — 아는 사람이 정해지지 않았거나, 아는 사람 중 하나가 장면 인물이다."""
    if not row.known_by:
        return True
    return any(normalize_part(name) in scene for name in row.known_by)
