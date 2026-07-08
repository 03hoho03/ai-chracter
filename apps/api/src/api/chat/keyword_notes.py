from api.db.models.story import KeywordNote


def match_keyword_notes(user_input: str, notes: list[KeywordNote]) -> list[KeywordNote]:
    """techspec-chat-story.md §3 / FR-39 — trigger_keywords 중 하나라도 user_input에
    포함되면 매칭. starting_setup_id 스코프(null=스토리 전체, 특정 시작설정 한정)로
    후보 목록을 좁히는 건 호출부(DB 조회)의 책임이고, 이 함수는 그렇게 좁혀진
    notes에 대해 키워드 매칭만 수행한다."""
    return [note for note in notes if any(keyword in user_input for keyword in note.trigger_keywords)]
