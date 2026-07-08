import uuid

from api.chat.keyword_notes import match_keyword_notes
from api.db.models.story import KeywordNote


def _note(trigger_keywords: list[str], starting_setup_id: uuid.UUID | None = None) -> KeywordNote:
    return KeywordNote(
        entity_id=uuid.uuid4(),
        starting_setup_id=starting_setup_id,
        info_text="info",
        trigger_keywords=trigger_keywords,
    )


def test_match_keyword_notes_no_match() -> None:
    notes = [_note(["마법사"]), _note(["기사단"])]

    assert match_keyword_notes("오늘 날씨가 좋다", notes) == []


def test_match_keyword_notes_single_match() -> None:
    wizard_note = _note(["마법사"])
    knight_note = _note(["기사단"])

    result = match_keyword_notes("저 마법사는 누구야?", [wizard_note, knight_note])

    assert result == [wizard_note]


def test_match_keyword_notes_multiple_matches() -> None:
    wizard_note = _note(["마법사"])
    knight_note = _note(["기사단"])
    unrelated_note = _note(["용"])

    result = match_keyword_notes("마법사와 기사단이 함께 싸웠다", [wizard_note, knight_note, unrelated_note])

    assert result == [wizard_note, knight_note]


def test_match_keyword_notes_matches_on_any_of_multiple_trigger_keywords() -> None:
    note = _note(["마법사", "현자"])

    assert match_keyword_notes("그는 현자였다", [note]) == [note]
