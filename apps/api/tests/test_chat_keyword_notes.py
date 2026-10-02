import unicodedata
import uuid

from api.chat.keyword_notes import ScanTurn, match_keyword_notes, recent_scan_turns, select_keyword_notes
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.story import KeywordNote


def _note(
    trigger_keywords: list[str],
    *,
    info_text: str = "info",
    exclude_keywords: list[str] | None = None,
    sticky_turns: int = 0,
    always_on: bool = False,
    order: int = 0,
    entity_id: uuid.UUID | None = None,
) -> KeywordNote:
    # 엔진은 아래 필드를 전부 읽는다. 세션 없이 만든 ORM 객체는 지정하지 않은 속성이 None 이라 빠뜨리면 안 된다.
    return KeywordNote(
        entity_id=entity_id or uuid.uuid4(),
        starting_setup_id=None,
        info_text=info_text,
        trigger_keywords=trigger_keywords,
        name="",
        order=order,
        exclude_keywords=exclude_keywords or [],
        sticky_turns=sticky_turns,
        always_on=always_on,
    )


def _a(content: str) -> ChatMessage:
    return ChatMessage(role=ChatMessageRole.ASSISTANT, content=content)


def _u(content: str) -> ChatMessage:
    return ChatMessage(role=ChatMessageRole.USER, content=content)


def _turn(assistant_text: str, *user_texts: str) -> ScanTurn:
    return ScanTurn(assistant_text=assistant_text, user_texts=user_texts)


# ── 턴 묶기 ─────────────────────────────────────────────────────────────────────────────────────


def test_first_turn_scans_opening_as_previous_ai_response() -> None:
    assert recent_scan_turns([_a("O")], "U1", depth=5) == [_turn("O", "U1")]


def test_room_without_opening_has_no_previous_ai_response() -> None:
    assert recent_scan_turns([], "U1", depth=5) == [_turn("", "U1")]
    assert recent_scan_turns([_u("U0")], "U1", depth=5) == [_turn("", "U0", "U1")]


def test_failed_turn_joins_next_turn_and_keeps_last_read_ai_response() -> None:
    history = [_a("O"), _u("U0"), _a("A0"), _u("U1"), _a("A1"), _u("U2")]

    assert recent_scan_turns(history, "U3", depth=1) == [_turn("A1", "U2", "U3"), _turn("A0", "U1")]


def test_consecutive_failed_turns_all_join_the_current_turn() -> None:
    history = [_a("O"), _u("U1"), _a("A1"), _u("U2"), _u("U3")]

    assert recent_scan_turns(history, "U4", depth=0) == [_turn("A1", "U2", "U3", "U4")]


def test_consecutive_ai_responses_scan_only_the_last_one() -> None:
    history = [_a("O"), _u("U1"), _a("A1"), _a("A1-again")]

    assert recent_scan_turns(history, "U2", depth=1) == [_turn("A1-again", "U2"), _turn("O", "U1")]


def test_regenerate_input_rebuilds_the_original_turn_including_failed_message() -> None:
    # 재생성 호출부는 대상 사용자 메시지를 뺀 앞부분과 그 메시지 본문을 넘긴다.
    history = [_a("O"), _u("U1"), _a("A1"), _u("U2")]

    assert recent_scan_turns(history, "U3", depth=0) == [_turn("A1", "U2", "U3")]


def test_edit_input_joins_failed_message_right_before_the_edited_one() -> None:
    # 편집 호출부는 편집 지점 앞까지와 편집본을 넘긴다. 바로 앞이 응답 없는 사용자 메시지면 함께 묶인다.
    history = [_a("O"), _u("U1"), _a("A1"), _u("U2")]

    assert recent_scan_turns(history, "edited", depth=1) == [_turn("A1", "U2", "edited"), _turn("O", "U1")]


def test_depth_limits_how_many_past_turns_are_returned() -> None:
    history = [_a("O"), _u("U1"), _a("A1"), _u("U2"), _a("A2")]

    assert recent_scan_turns(history, "U3", depth=0) == [_turn("A2", "U3")]
    assert recent_scan_turns(history, "U3", depth=1) == [_turn("A2", "U3"), _turn("A1", "U2")]
    assert len(recent_scan_turns(history, "U3", depth=5)) == 3


def test_media_tags_are_removed_from_history_but_not_from_current_message() -> None:
    cell_id = uuid.uuid4()
    history = [_a(f"앞 {{{{img::{cell_id}}}}} 뒤"), _u("{{img::도희/웃음}}")]

    [turn] = recent_scan_turns(history, "{{img::도희/웃음}}", depth=0)

    assert str(cell_id) not in turn.assistant_text
    assert turn.user_texts[0] == ""
    assert turn.user_texts[1] == "{{img::도희/웃음}}"


# ── 노트 고르기 ─────────────────────────────────────────────────────────────────────────────────


def test_no_note_fires_without_keyword() -> None:
    assert select_keyword_notes([_note(["마법사"])], [_turn("", "오늘 날씨가 좋다")]) == []


def test_keyword_in_user_message_fires() -> None:
    note = _note(["마법사", "현자"])

    assert select_keyword_notes([note], [_turn("", "그는 현자였다")]) == [note]


def test_keyword_in_previous_ai_response_fires() -> None:
    note = _note(["마법사"])

    assert select_keyword_notes([note], [_turn("마법사가 나타났다", "누구야?")]) == [note]


def test_keyword_matching_ignores_letter_case() -> None:
    note = _note(["USB"])

    assert select_keyword_notes([note], [_turn("", "usb 를 꽂았다")]) == [note]


def test_keyword_matching_treats_decomposed_hangul_as_composed() -> None:
    note = _note(["마법사"])
    decomposed = unicodedata.normalize("NFD", "저 마법사는 누구야")
    assert decomposed != "저 마법사는 누구야"

    assert select_keyword_notes([note], [_turn("", decomposed)]) == [note]


def test_keyword_split_across_two_texts_does_not_fire() -> None:
    note = _note(["마법사"])

    assert select_keyword_notes([note], [_turn("그는 마법", "사였다")]) == []
    assert select_keyword_notes([note], [_turn("", "그는 마법", "사였다")]) == []


def test_sticky_note_stays_exactly_sticky_turns_after_match() -> None:
    note = _note(["마법사"], sticky_turns=2)
    turns = [_turn("", "c"), _turn("", "b"), _turn("", "마법사")]

    assert select_keyword_notes([note], turns) == [note]


def test_sticky_note_drops_one_turn_after_its_range() -> None:
    note = _note(["마법사"], sticky_turns=2)
    turns = [_turn("", "d"), _turn("", "c"), _turn("", "b"), _turn("", "마법사")]

    assert select_keyword_notes([note], turns) == []


def test_note_without_sticky_turns_ignores_previous_turn() -> None:
    note = _note(["마법사"])

    assert select_keyword_notes([note], [_turn("", "b"), _turn("", "마법사")]) == []


def test_exclude_keyword_in_current_turn_blocks_matching_note() -> None:
    note = _note(["마법사"], exclude_keywords=["가짜"])

    assert select_keyword_notes([note], [_turn("", "가짜 마법사다")]) == []


def test_exclude_keyword_in_previous_ai_response_blocks_note() -> None:
    note = _note(["마법사"], exclude_keywords=["가짜"])

    assert select_keyword_notes([note], [_turn("그건 가짜야", "마법사?")]) == []


def test_exclude_keyword_matching_ignores_letter_case() -> None:
    note = _note(["마법사"], exclude_keywords=["Fake"])

    assert select_keyword_notes([note], [_turn("", "FAKE 마법사")]) == []


def test_exclude_keyword_in_current_turn_blocks_sticky_note() -> None:
    note = _note(["마법사"], exclude_keywords=["가짜"], sticky_turns=2)
    turns = [_turn("", "가짜다"), _turn("", "마법사")]

    assert select_keyword_notes([note], turns) == []


def test_exclude_keyword_in_current_turn_blocks_always_on_note() -> None:
    note = _note([], exclude_keywords=["가짜"], always_on=True)

    assert select_keyword_notes([note], [_turn("", "가짜다")]) == []


def test_match_in_past_turn_with_exclude_keyword_does_not_start_sticky_range() -> None:
    note = _note(["마법사"], exclude_keywords=["가짜"], sticky_turns=2)
    turns = [_turn("", "c"), _turn("", "가짜 마법사")]

    assert select_keyword_notes([note], turns) == []


def test_sticky_note_returns_after_turn_with_exclude_keyword() -> None:
    note = _note(["마법사"], exclude_keywords=["가짜"], sticky_turns=2)
    turns = [_turn("", "c"), _turn("", "가짜다"), _turn("", "마법사")]

    assert select_keyword_notes([note], turns) == [note]


def test_blank_exclude_keyword_does_not_block_every_turn() -> None:
    note = _note(["마법사"], exclude_keywords=["", " "])

    assert select_keyword_notes([note], [_turn("", "마법사")]) == [note]


def test_always_on_note_loads_without_keyword() -> None:
    note = _note([], always_on=True)

    assert select_keyword_notes([note], [_turn("", "아무 말")]) == [note]


def test_blank_trigger_keyword_never_fires() -> None:
    note = _note(["", "  "])

    assert select_keyword_notes([note], [_turn("무엇이든", "아무 말")]) == []


def test_note_with_blank_info_is_not_loaded_even_when_always_on() -> None:
    keyword_note = _note(["마법사"], info_text="  ")
    always_note = _note([], info_text="\n", always_on=True)

    assert select_keyword_notes([keyword_note, always_note], [_turn("", "마법사")]) == []


def test_only_first_five_fired_notes_by_order_are_loaded() -> None:
    notes = [_note(["열쇠"], order=order) for order in (5, 3, 0, 4, 1, 2)]

    selected = select_keyword_notes(notes, [_turn("", "열쇠")])

    assert [note.order for note in selected] == [0, 1, 2, 3, 4]


def test_same_order_is_broken_by_entity_id() -> None:
    low = _note(["열쇠"], entity_id=uuid.UUID(int=1))
    high = _note(["열쇠"], entity_id=uuid.UUID(int=2))

    assert select_keyword_notes([high, low], [_turn("", "열쇠")]) == [low, high]


def test_always_on_notes_come_first_and_do_not_count_toward_five() -> None:
    always = [_note([], always_on=True, order=order) for order in (10, 11, 12)]
    fired = [_note(["열쇠"], order=order) for order in range(6)]

    selected = select_keyword_notes([*fired, *always], [_turn("", "열쇠")])

    assert selected == [*always, *fired[:5]]


def test_match_keyword_notes_walks_back_as_far_as_longest_sticky_range() -> None:
    note = _note(["마법사"], sticky_turns=2)
    history = [_a("O"), _u("마법사"), _a("A1"), _u("U2"), _a("A2")]

    assert match_keyword_notes([note], history, "U3") == [note]
    assert match_keyword_notes([note], [*history, _u("U3"), _a("A3")], "U4") == []
