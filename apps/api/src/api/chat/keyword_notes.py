import unicodedata

from api.db.models.story import KeywordNote


def normalize_keyword_text(text: str) -> str:
    """키워드와 대화 글을 비교하기 전에 같은 모양으로 맞춘다. 맥에서 친 한글은 자모로 풀린 NFD 로 올 수 있어 NFC 로
    합치고, 영문 대소문자를 가리지 않게 `casefold` 로 접는다(소문자화보다 넓다 — `ß` 를 `ss` 로 접는다). 저장 검증의
    중복 판정도 이 함수를 쓴다 — 매칭에서 같은 키워드를 저장에서 다른 키워드로 보면 한 노트에 같은 키워드가 둘 남는다."""
    return unicodedata.normalize("NFC", text).casefold()


def match_keyword_notes(user_input: str, notes: list[KeywordNote]) -> list[KeywordNote]:
    """trigger_keywords 중 하나라도 user_input에
    포함되면 매칭. starting_setup_id 스코프(null=스토리 전체, 특정 시작설정 한정)로
    후보 목록을 좁히는 건 호출부(DB 조회)의 책임이고, 이 함수는 그렇게 좁혀진
    notes에 대해 키워드 매칭만 수행한다."""
    return [note for note in notes if any(keyword in user_input for keyword in note.trigger_keywords)]
