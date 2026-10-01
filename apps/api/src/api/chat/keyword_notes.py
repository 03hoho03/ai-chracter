"""키워드북 노트를 이번 턴 프롬프트에 실을지 고르는 순수 함수.

스캔 글은 "직전 AI 응답 + 이번 사용자 메시지"다. 턴은 AI 응답을 경계로 묶는다 — 응답 없이 남은 사용자 메시지(생성이
실패한 턴)는 다음 사용자 메시지와 한 턴이 되므로, 직전 AI 응답은 사용자가 마지막으로 읽은 응답이고 유지 턴은 성공한
응답 수로 센다. 적용 범위(시작설정) 필터는 호출부가 노트를 좁힐 때 한다.
"""

import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from api.content.media_tags import strip_media_tags
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.story import KeywordNote

# 한 턴에 키워드로 열리는 노트 수. 넘치면 목록 아래쪽(`order` 가 큰 쪽)이 빠진다. 상시 노트는 따로 센다.
MAX_TRIGGERED_KEYWORD_NOTES = 5


def normalize_keyword_text(text: str) -> str:
    """키워드와 대화 글을 비교하기 전에 같은 모양으로 맞춘다. 맥에서 친 한글은 자모로 풀린 NFD 로 올 수 있어 NFC 로
    합치고, 영문 대소문자를 가리지 않게 `casefold` 로 접는다(소문자화보다 넓다 — `ß` 를 `ss` 로 접는다). 저장 검증의
    중복 판정도 이 함수를 쓴다 — 매칭에서 같은 키워드를 저장에서 다른 키워드로 보면 한 노트에 같은 키워드가 둘 남는다."""
    return unicodedata.normalize("NFC", text).casefold()


@dataclass(frozen=True)
class ScanTurn:
    """한 턴의 스캔 글. 글마다 따로 검사한다 — 이어 붙이면 두 글의 경계를 걸친 가짜 일치가 생긴다."""

    # 그 턴 사용자 메시지들 앞의 가장 가까운 AI 응답(첫 턴이면 오프닝). 앞에 응답이 없으면 "".
    assistant_text: str
    # 그 턴의 사용자 메시지들(응답 없이 남은 것 포함). 이번 턴이면 마지막이 이번 사용자 메시지다.
    user_texts: tuple[str, ...]


def recent_scan_turns(history: Sequence[ChatMessage], user_content: str, depth: int) -> list[ScanTurn]:
    """`[0]` 이 이번 턴, `[j]` 가 j 턴 전인 스캔 턴 목록(최대 `depth + 1` 개).

    히스토리 글은 모델이 받는 사본과 같게 미디어 북 태그를 지운다 — 태그 속 칸 id 의 16진 조각이나 인물 이름이 키워드에
    걸리면 모델이 보지 못한 글로 노트가 열린다. 이번 사용자 메시지는 모델에게도 그대로 가므로 그대로 본다. 연속된 AI
    응답의 앞쪽(사이의 사용자 메시지가 지워진 것)은 어느 턴의 직전 응답도 아니라 보지 않는다."""
    messages = [(message.role, strip_media_tags(message.content)) for message in history]
    messages.append((ChatMessageRole.USER, user_content))
    turns: list[ScanTurn] = []
    i = len(messages) - 1
    while i >= 0 and len(turns) <= depth:
        user_texts: list[str] = []
        while i >= 0 and messages[i][0] == ChatMessageRole.USER:
            user_texts.insert(0, messages[i][1])
            i -= 1
        if not user_texts:
            i -= 1
            continue
        assistant_text = messages[i][1] if i >= 0 else ""
        turns.append(ScanTurn(assistant_text=assistant_text, user_texts=tuple(user_texts)))
        i -= 1
    return turns


def _keyword_set(keywords: Iterable[str]) -> set[str]:
    # 공백뿐인 키워드는 거의 모든 글에 들어 있어(빈 문자열은 모든 글에 들어 있다) 매 턴 걸린다 — 저장 검증이 막기
    # 전에 저장된 값이나 미리보기 본문이 이런 키워드를 가질 수 있어 여기서도 버린다.
    return {normalize_keyword_text(keyword) for keyword in keywords if keyword.strip()}


def _hits(keywords: set[str], turn: tuple[str, list[str]]) -> bool:
    assistant_text, user_texts = turn
    return any(keyword in assistant_text or any(keyword in text for text in user_texts) for keyword in keywords)


def select_keyword_notes(notes: Sequence[KeywordNote], turns: Sequence[ScanTurn]) -> list[KeywordNote]:
    """이번 턴에 실을 노트 — 상시 노트(`order` 순) 뒤에 키워드로 열린 노트(`order` 순 앞 다섯 개).

    - 금지 키워드가 이번 턴 스캔 글에 있으면 그 노트는 유지 중이든 상시든 빠진다. 과거 턴에 트리거와 금지 키워드가 함께
      있었으면 그 턴의 일치는 무효라 유지의 출발점이 되지 않는다.
    - 유지 턴 k 인 노트는 이번 턴부터 k 턴 전까지 중 한 턴에서 일치하면 실린다(`turns[0..k]`). 대화가 그만큼 길지 않으면
      있는 턴까지만 본다.
    - 상시 노트는 트리거 키워드와 유지 턴을 무시한다. 스토리당 상시 노트 수는 저장 검증이 제한한다.
    - 정보가 공백뿐인 노트는 싣지 않는다(빈 줄만 실린다). 저장은 이런 노트를 받아 주고 발행이 막는다."""
    scanned = [
        (normalize_keyword_text(turn.assistant_text), [normalize_keyword_text(text) for text in turn.user_texts])
        for turn in turns
    ]
    always_on: list[KeywordNote] = []
    triggered: list[KeywordNote] = []
    for note in sorted(notes, key=lambda note: (note.order, note.entity_id)):
        if not note.info_text.strip():
            continue
        excludes = _keyword_set(note.exclude_keywords)
        if _hits(excludes, scanned[0]):
            continue
        if note.always_on:
            always_on.append(note)
            continue
        triggers = _keyword_set(note.trigger_keywords)
        for turn in scanned[: note.sticky_turns + 1]:
            if _hits(triggers, turn) and not _hits(excludes, turn):
                triggered.append(note)
                break
    return always_on + triggered[:MAX_TRIGGERED_KEYWORD_NOTES]


def match_keyword_notes(user_input: str, notes: list[KeywordNote]) -> list[KeywordNote]:
    """trigger_keywords 중 하나라도 user_input에
    포함되면 매칭. starting_setup_id 스코프(null=스토리 전체, 특정 시작설정 한정)로
    후보 목록을 좁히는 건 호출부(DB 조회)의 책임이고, 이 함수는 그렇게 좁혀진
    notes에 대해 키워드 매칭만 수행한다."""
    return [note for note in notes if any(keyword in user_input for keyword in note.trigger_keywords)]
