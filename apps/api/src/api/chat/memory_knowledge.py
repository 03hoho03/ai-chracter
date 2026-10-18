"""장면 인물 집합과 지식 범위 필터 — 아는 사람이 이번 장면에 없는 비밀 사실을 사실 섹션 후보에서 빼고, 그 비밀과 근거가 겹치는
장면을 회상에서 가린다. DB·LLM 을 쓰지 않는 순수 함수라 매 턴 조립(`chat/memory_fact_section.py`·`chat/memory_recall.py`)과 지난
턴을 다시 계산하는 측정 도구가 같은 함수를 부른다. 두 섹션이 같은 키별 최신·같은 장면 인물을 쓰도록 여기 둔다(사실 섹션이 회상을
import 하므로 어느 한쪽에 두면 순환이 된다).

방 이름: 방 사실 행의 주어·관계 대상·말한 사람·아는 사람 원소와, 호출부가 더 주는 이름이다. 사실 섹션은 더 주지 않는다 —
필터 판정은 아는 사람 원소가 장면에 나오는가뿐이고 그 원소는 이미 사실 행에서 들어오므로, 미디어 북 인물이나 작품 이름을 더해도
판정이 바뀌지 않는다. 회상의 가림은 후보 장면 행의 아는 사람 원소를 더 준다 — 사실 행이 없거나 그 인물의 사실 행이 없는 방에서도
장면 칸의 인물이 턴에 나오면 장면 인물이어야 그 장면을 판정할 수 있다. 더한 이름은 사실 행의 아는 사람 원소가 아니므로 사실
쪽 판정은 바뀌지 않는다. 키워드북 키워드는 이름인지 사물인지 가를 수 없어 쓰지 않는다. 사실 키와 같은 정규화(`normalize_part`)를
하고, 2자 미만은 흔한 글자라 아무 턴에나 걸리므로 버린다. 요약 접기의 비밀 표기 슬롯에 싣는 인물 이름 목록(`room_people`)도 같은
출처·같은 거름을 쓰되 원래 표기를 지키고, 접기가 작품 이름과 미디어 북 인물을 더 준다(첫 접기에는 사실 행이 아직 없다).

사용자는 장면 인물에서 뺀다. 생성 모델이 연기하는 쪽은 사용자가 아니라 사용자의 앎은 누출 위험이 아니고, 진행자는 사용자를
이름으로 자주 불러 사용자를 세면 그런 턴마다 다른 인물만 있는 장면에서도 사용자에게 털어놓은 비밀이 남는다. 사용자 표기는
대화 프로필 이름(있으면)과, 프로필 이름이 없을 때 추출이 사용자를 적을 수 있는 표기 셋 — 대화 줄 라벨, `{{user}}` 대체어,
사실 추출 지시문이 사용자를 부르는 낱말 — 이다. 추출 지시문은 이름이 없을 때 쓸 표기를 정하지 않아 모델이 이 중 무엇이든 쓴다.

장면 인물: 방 이름 중 정규화한 이번 턴 사용자 메시지나 직전 응답에 부분 문자열로 나오는 것. 어절 토큰 일치는 "유나한테서"처럼
조사가 두 겹이면 놓친다. 부분 문자열의 오탐은 장면 인물을 넓혀 행을 남기는 쪽(필터가 없을 때의 동작 쪽)으로만 틀린다. 두 글은
따로 본다 — 이어 붙이면 경계를 걸친 가짜 일치가 생긴다.

언급: 지식 범위 필터 스위치를 켠 턴은 직전 응답의 대사 따옴표(`"…"`·`“…”`·`「…」`·`『…』`, 소설 본문 처리가 대사로 떼는 따옴표와
같다) 안을 지우고 남은 서술 조각만 본다 — 인물이 말로 꺼낸 이름은 그 사람이 장면에 있다는 뜻이 아니다. 작은따옴표는 속마음이라
대사로 보지 않는다. 지운 앞뒤 조각은 따로 본다(이어 붙이면 경계를 걸친 가짜 이름이 생긴다). 짝이 맞지 않는 따옴표는 대사로 보지
않아 그 이름은 센다 — 틀리면 장면 인물을 넓히는 쪽이다. 이번 사용자 메시지는 따옴표 안이어도 센다(사용자가 장면을 정한다).
스위치가 꺼지면 이 규칙도 꺼져 장면 인물이 이 규칙이 생기기 전과 같다.

필터: 아는 사람이 정해진 행은 그 이름 중 하나가 장면 인물일 때만 남는다. 정해지지 않은 행(공개이거나 알 수 없음)은 늘 남는다.
장면 인물에 사용자가 없으므로 사용자만 아는 비밀은 늘 빠진다. 장면 행의 아는 사람 칸도 같은 판정(`known_in_scene`)을 쓴다.

키별 최신: 같은 키의 마지막 행이 이기되, 같은 키에 같은 값의 반증 행이 앞에 있으면 그 반증 행이 이긴다 — 반증된 값이 뒤의
같은 값 주장으로 되살아나지 않게. 값이 다른 새 행은 옛 값의 반증 행에 가려지지 않는다(정정). 사실 추출이 추출 입력의 기존 키
목록을 만드는 규칙(`chat/memory_facts.py` 의 `existing_key_lines`)과 같다. 필터는 이긴 행에 건다.

회상 줄의 가림: 두 가림의 합집합이다. 하나는 장면 행 자신의 아는 사람 칸 — 칸이 차 있고 그 원소를 아는 사람이 장면 인물에 하나도
없으면 가린다(칸이 빈 옛 행은 이 가림이 없다). 다른 하나는 사실 행에서 끌어낸 것 — 키별 최신 행이 필터를 지나지 못하는 키(가려진
키)의 모든 행(옛 행 포함, 옛 행과만 겹치는 장면도 같은 비밀을 담는다)의 근거 메시지 범위와 양 끝 포함으로 겹치는 장면을 가린다.
키의 최신 행이 공개면 옛 행이 비밀이었어도 가리지 않는다. 범위 겹침은 거칠어 공개 내용이 함께 든 장면도 가려지고, 사실 추출이
비밀을 놓치거나 아직 따라잡지 못한 구간의 장면은 이쪽으로는 가려지지 않는다."""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from api.chat.keyword_notes import recent_scan_turns
from api.chat.memory_facts import normalize_part
from api.chat.memory_window import MessageKey
from api.chat.prompt_builder import PromptNames
from api.content.author_macros import FALLBACK_USER_NAME
from api.db.models.chat import ChatMemoryFact, ChatMessage

# 사실 추출 지시문이 사용자를 부르는 낱말 — 프로필 이름이 없는 방에서 추출이 아는 사람·말한 사람에 이 낱말을 그대로 적을 수 있다.
USER_INSTRUCTION_WORD = "사용자 인물"
MIN_NAME_CHARS = 2
# 대사 따옴표 한 쌍(안에 같은 닫는 따옴표가 없는 가장 짧은 것). 작은따옴표는 속마음이라 넣지 않는다.
_DIALOGUE = re.compile(r'"[^"]*"|“[^”]*”|「[^」]*」|『[^』]*』')


@dataclass(frozen=True)
class KnowledgeScope:
    """장면 인물을 셀 때 호출부가 넘기는 이름 출처 — 그 턴 생성 프롬프트 세트의 대화 줄 라벨(사용자 표기) — 와, 직전 응답의 대사
    따옴표 안에만 나온 이름을 세지 않을지(지식 범위 필터 스위치를 켠 턴). 지식 범위 필터와 이름 정확 조회와 회상의 가림이 같은
    장면 인물을 쓴다."""

    user_label: str
    ignore_quoted_reply_names: bool = False


def user_names(persona_name: str | None, user_label: str) -> frozenset[str]:
    """사용자로 볼 표기(정규화) — 프로필 이름(있으면)·대화 줄 라벨·`{{user}}` 대체어·지시문 낱말."""
    forms = (persona_name, user_label, FALLBACK_USER_NAME, USER_INSTRUCTION_WORD)
    return frozenset(normalized for normalized in (normalize_part(form) for form in forms) if normalized)


def _raw_names(rows: Iterable[ChatMemoryFact], extra: Iterable[str | None]) -> list[str | None]:
    """이름 출처를 차례로 — 호출부 이름, 그다음 행마다 주어·관계 대상·말한 사람·아는 사람 원소. 사실의 속성은 이름이 아니다."""
    raw: list[str | None] = list(extra)
    for row in rows:
        raw += [row.subject, row.object if row.kind == "relation" else None, row.speaker, *(row.known_by or ())]
    return raw


def room_names(rows: Iterable[ChatMemoryFact], extra: Iterable[str], *, users: frozenset[str]) -> frozenset[str]:
    """방 이름(정규화, 2자 이상, 사용자 표기 제외). `rows` 는 그 턴에 읽은 방 사실 행 전부, `extra` 는 호출부의 이름 출처다."""
    names = (normalize_part(name) for name in _raw_names(rows, extra))
    return frozenset(name for name in names if len(name) >= MIN_NAME_CHARS and name not in users)


def room_people(rows: Iterable[ChatMemoryFact], extra: Iterable[str | None], *, users: frozenset[str]) -> list[str]:
    """요약에 줄 방 인물 이름 목록 — `room_names` 와 같은 출처·같은 거름(정규형 2자 이상, 사용자 표기 제외)이지만 출처 순서대로
    처음 나온 **원래 표기**(앞뒤 공백만 지운다)를 남긴다. 요약 모델이 아는 사람을 이 이름 꼴 그대로 적게 하려는 목록이라 정규형을
    주면 대소문자·띄어쓰기가 바뀐 이름이 적힌다. 같은 이름인지는 정규형으로 본다."""
    people: list[str] = []
    seen: set[str] = set()
    for name in _raw_names(rows, extra):
        key = normalize_part(name)
        if len(key) < MIN_NAME_CHARS or key in users or key in seen:
            continue
        seen.add(key)
        people.append((name or "").strip())
    return people


def scene_people(names: Iterable[str], texts: Iterable[str]) -> frozenset[str]:
    """`names`(정규화한 방 이름) 중 `texts`(이번 사용자 메시지·직전 응답) 하나에라도 부분 문자열로 나오는 것."""
    normalized = [normalize_part(text) for text in texts]
    return frozenset(name for name in names if any(name in text for text in normalized))


def known_in_scene(known_by: Sequence[str] | None, scene: frozenset[str]) -> bool:
    """아는 사람 목록이 `known_by` 인 행(사실 행이나 장면 행)을 남기는가 — 아는 사람이 정해지지 않았거나, 아는 사람 중 하나가
    장면 인물이다."""
    if not known_by:
        return True
    return any(normalize_part(name) in scene for name in known_by)


def scene_for_turn(
    rows: Sequence[ChatMemoryFact],
    scope: KnowledgeScope,
    *,
    history: Sequence[ChatMessage],
    user_content: str,
    names: PromptNames,
    extra: Iterable[str] = (),
) -> frozenset[str]:
    """이번 턴의 장면 인물(정규형). `rows` 는 그 턴에 읽은 방 사실 행 전부, `history` 는 방의 전체 대화, `extra` 는 사실 행
    밖의 이름 출처(회상 후보 장면의 아는 사람 원소)다. 직전 응답은 키워드북·회상과 같은 스캔 글(이미지 태그를 지우고
    `{{user}}`·`{{char}}` 를 이름으로 바꾼 것)이고, `scope` 가 그렇게 받으면 대사 따옴표 안을 지운 서술 조각들이다."""
    previous_response = recent_scan_turns(history, user_content, 0, names=names)[0].assistant_text
    replies = _DIALOGUE.split(previous_response) if scope.ignore_quoted_reply_names else [previous_response]
    users = user_names(names.persona_name, scope.user_label)
    return scene_people(room_names(rows, extra, users=users), (user_content, *replies))


def latest_by_key(rows: Sequence[ChatMemoryFact]) -> list[tuple[int, ChatMemoryFact]]:
    """키마다 이긴 행 하나와 그 행의 쓴 순번(`rows` 는 쓴 순서, 규칙은 모듈 설명)."""
    groups: dict[str, list[tuple[int, ChatMemoryFact]]] = {}
    for order, row in enumerate(rows):
        groups.setdefault(row.fact_key, []).append((order, row))
    winners: list[tuple[int, ChatMemoryFact]] = []
    for members in groups.values():
        winner = members[-1]
        if winner[1].truth_status != "disproved":
            value = normalize_part(winner[1].value)
            disproved = [m for m in members if m[1].truth_status == "disproved" and normalize_part(m[1].value) == value]
            if disproved:
                winner = disproved[-1]
        winners.append(winner)
    return winners


def hidden_fact_keys(rows: Sequence[ChatMemoryFact], scene: frozenset[str]) -> frozenset[str]:
    """키별 최신 행이 필터를 지나지 못하는 키 — 사실 섹션의 지식 범위 필터가 이번 턴 빼는 키와 같다."""
    return frozenset(row.fact_key for _, row in latest_by_key(rows) if not known_in_scene(row.known_by, scene))


def hidden_ranges(rows: Sequence[ChatMemoryFact], scene: frozenset[str]) -> list[tuple[MessageKey, MessageKey]]:
    """가려진 키의 모든 행(옛 행 포함)의 근거 메시지 범위 (시작 키, 끝 키), 쓴 순서로. 회상이 이 범위와 겹치는 장면을 뺀다 —
    옛 행과만 겹치는 장면도 같은 비밀을 담고 있다."""
    keys = hidden_fact_keys(rows, scene)
    return [
        ((row.start_created_at, row.start_message_id), (row.end_created_at, row.end_message_id))
        for row in rows
        if row.fact_key in keys
    ]


def overlaps(a: tuple[MessageKey, MessageKey], b: tuple[MessageKey, MessageKey]) -> bool:
    """두 메시지 범위(양 끝 포함)가 한 메시지라도 겹치는가."""
    return a[0] <= b[1] and b[0] <= a[1]
