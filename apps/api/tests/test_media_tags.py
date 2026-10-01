"""미디어 북 이미지 태그(`{{img::인물/장면}}` 이름 형태, `{{img::<칸 id>}}` id 형태)의 순수 함수.

빌더 글에는 사람이 읽는 이름 형태로 저장되고, 화면으로 나가기 전에 서버가 칸 id 형태로 바꾸며(없는 이름은
지운다), 모델로 가는 사본에서는 두 형태를 모두 지운다. 이 표는 미리보기 첫 메시지를 그리는 FE 쪽 같은
규칙과도 대조된다 — 두 구현이 갈라지면 미리보기와 실채팅이 다르게 보인다."""

import json
import unicodedata
import uuid
from pathlib import Path

import pytest

from api.content.media_tags import media_tag_refs, normalize_media_tags, strip_media_tags

# 정규화·삭제 표는 웹 테스트와 함께 읽는 JSON 하나다 — 한쪽에만 행을 더하면 두 구현이 갈라져도 모른다.
_CASES = json.loads((Path(__file__).parent / "fixtures" / "media_tag_cases.json").read_text(encoding="utf-8"))

_CELLS = {(cell["person"], cell["scene"]): uuid.UUID(cell["cellId"]) for cell in _CASES["cells"]}
_MINA_CLASSROOM = _CELLS[("민아", "교실")]
_MINA_ROOFTOP = _CELLS[("민아", "옥상")]


def _tag(cell_id: uuid.UUID) -> str:
    return "{{img::" + str(cell_id) + "}}"


@pytest.mark.parametrize(
    ("text", "expected_text", "expected_refs"),
    [
        pytest.param(row["text"], row["expectedText"], {uuid.UUID(i) for i in row["expectedCellIds"]}, id=row["id"])
        for row in _CASES["normalize"]
    ],
)
def test_normalize_media_tags(text: str, expected_text: str, expected_refs: set[uuid.UUID]) -> None:
    assert normalize_media_tags(text, _CELLS) == (expected_text, expected_refs)


def test_nfd_row_input_is_really_decomposed() -> None:
    """편집기가 표를 NFC 로 되돌려 저장하면 NFD 행이 이름 형태 행과 같아져 아무것도 시험하지 않는다."""
    (row,) = [row for row in _CASES["normalize"] if row["id"] == "nfd-names"]
    assert unicodedata.normalize("NFC", row["text"]) != row["text"]


def test_normalize_media_tags_matches_cell_names_given_in_nfd_or_with_spaces() -> None:
    """미리보기 페이로드처럼 정규화되지 않은 이름으로 만든 표도 같은 칸을 찾는다."""
    cells = {(" " + unicodedata.normalize("NFD", "민아"), "교실 "): _MINA_CLASSROOM}
    assert normalize_media_tags("{{img::민아/교실}}", cells) == (_tag(_MINA_CLASSROOM), {_MINA_CLASSROOM})


def test_normalize_media_tags_folds_the_line_left_by_a_deleted_tag() -> None:
    assert normalize_media_tags("앞 문단\n\n{{img::수아/교실}}\n\n뒤 문단", _CELLS) == ("앞 문단\n\n뒤 문단", set())


@pytest.mark.parametrize(
    ("text", "expected"),
    [pytest.param(row["text"], row["expected"], id=row["id"]) for row in _CASES["strip"]],
)
def test_strip_media_tags(text: str, expected: str) -> None:
    assert strip_media_tags(text) == expected


def test_strip_media_tags_returns_tagless_text_byte_for_byte() -> None:
    text = "  첫 줄  \n\n\n\t둘째 줄\r\n\n"
    assert strip_media_tags(text) == text


def test_media_tag_refs_returns_only_id_form_cells() -> None:
    text = f"{_tag(_MINA_CLASSROOM)} {{{{img::민아/옥상}}}} {_tag(_MINA_ROOFTOP)} {_tag(_MINA_CLASSROOM)}"
    assert media_tag_refs(text) == {_MINA_CLASSROOM, _MINA_ROOFTOP}


def test_media_tag_refs_of_text_without_tags_is_empty() -> None:
    assert media_tag_refs("{{img::민아/교실}} {{user}}") == set()
