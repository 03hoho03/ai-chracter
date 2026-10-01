"""미디어 북 이미지 태그(`{{img::인물/장면}}` 이름 형태, `{{img::<칸 id>}}` id 형태)의 순수 함수.

빌더 글에는 사람이 읽는 이름 형태로 저장되고, 화면으로 나가기 전에 서버가 칸 id 형태로 바꾸며(없는 이름은
지운다), 모델로 가는 사본에서는 두 형태를 모두 지운다. 이 표는 미리보기 첫 메시지를 그리는 FE 쪽 같은
규칙과도 대조된다 — 두 구현이 갈라지면 미리보기와 실채팅이 다르게 보인다."""

import unicodedata
import uuid

import pytest

from api.content.media_tags import media_tag_refs, normalize_media_tags, strip_media_tags

_MINA_CLASSROOM = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_MINA_ROOFTOP = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002")
_UNKNOWN = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000009")

_CELLS = {("민아", "교실"): _MINA_CLASSROOM, ("민아", "옥상"): _MINA_ROOFTOP}


def _tag(cell_id: uuid.UUID) -> str:
    return "{{img::" + str(cell_id) + "}}"


@pytest.mark.parametrize(
    ("text", "expected_text", "expected_refs"),
    [
        pytest.param("{{img::민아/교실}}", _tag(_MINA_CLASSROOM), {_MINA_CLASSROOM}, id="name-form"),
        pytest.param(
            "앞 {{img::민아/교실}} 뒤 {{img::민아/옥상}}",
            f"앞 {_tag(_MINA_CLASSROOM)} 뒤 {_tag(_MINA_ROOFTOP)}",
            {_MINA_CLASSROOM, _MINA_ROOFTOP},
            id="two-tags-in-a-line",
        ),
        pytest.param("{{img:: 민아 / 교실 }}", _tag(_MINA_CLASSROOM), {_MINA_CLASSROOM}, id="spaces-around-names"),
        pytest.param(
            "{{img::" + unicodedata.normalize("NFD", "민아/교실") + "}}",
            _tag(_MINA_CLASSROOM),
            {_MINA_CLASSROOM},
            id="nfd-names",
        ),
        pytest.param("앞 {{img::수아/교실}} 뒤", "앞  뒤", set(), id="unknown-person-deleted"),
        pytest.param("앞 {{img::민아/복도}} 뒤", "앞  뒤", set(), id="unknown-scene-deleted"),
        pytest.param(_tag(_MINA_ROOFTOP), _tag(_MINA_ROOFTOP), {_MINA_ROOFTOP}, id="known-id-form-kept"),
        pytest.param(
            "{{img::" + str(_MINA_ROOFTOP).upper() + "}}",
            _tag(_MINA_ROOFTOP),
            {_MINA_ROOFTOP},
            id="upper-case-id-form-canonicalised",
        ),
        pytest.param("앞 " + _tag(_UNKNOWN) + " 뒤", "앞  뒤", set(), id="unknown-id-form-deleted"),
        # 슬래시가 하나면 한쪽 이름이 비어도 이름 형태 태그다 — 빈 이름의 칸은 없으므로 지운다.
        pytest.param("앞 {{img::/교실}} 뒤", "앞  뒤", set(), id="empty-person-deleted"),
        pytest.param("앞 {{img::민아/}} 뒤", "앞  뒤", set(), id="empty-scene-deleted"),
        pytest.param("앞 {{img:: / }} 뒤", "앞  뒤", set(), id="both-names-blank-deleted"),
        pytest.param("{{img::민아}}", "{{img::민아}}", set(), id="no-slash-is-not-a-tag"),
        pytest.param("{{img::민아/교실/밤}}", "{{img::민아/교실/밤}}", set(), id="two-slashes-is-not-a-tag"),
        pytest.param("{{img::민아/교실", "{{img::민아/교실", set(), id="half-tag-is-not-a-tag"),
        pytest.param("{{img::}}", "{{img::}}", set(), id="empty-body-is-not-a-tag"),
        pytest.param("{{user}}와 {{char}}", "{{user}}와 {{char}}", set(), id="other-braces-untouched"),
    ],
)
def test_normalize_media_tags(text: str, expected_text: str, expected_refs: set[uuid.UUID]) -> None:
    assert normalize_media_tags(text, _CELLS) == (expected_text, expected_refs)


def test_normalize_media_tags_matches_cell_names_given_in_nfd_or_with_spaces() -> None:
    """미리보기 페이로드처럼 정규화되지 않은 이름으로 만든 표도 같은 칸을 찾는다."""
    cells = {(" " + unicodedata.normalize("NFD", "민아"), "교실 "): _MINA_CLASSROOM}
    assert normalize_media_tags("{{img::민아/교실}}", cells) == (_tag(_MINA_CLASSROOM), {_MINA_CLASSROOM})


def test_normalize_media_tags_folds_the_line_left_by_a_deleted_tag() -> None:
    assert normalize_media_tags("앞 문단\n\n{{img::수아/교실}}\n\n뒤 문단", _CELLS) == ("앞 문단\n\n뒤 문단", set())


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("{{img::민아/교실}}", "", id="name-form-alone"),
        pytest.param(_tag(_MINA_CLASSROOM), "", id="id-form-alone"),
        pytest.param("앞 {{img::민아/교실}} 뒤", "앞  뒤", id="mid-line-only-the-tag-goes"),
        pytest.param(f"앞{_tag(_UNKNOWN)}뒤", "앞뒤", id="id-form-mid-line"),
        pytest.param("앞 문단\n\n{{img::민아/교실}}\n\n뒤 문단", "앞 문단\n\n뒤 문단", id="tag-line-between-blank-lines"),
        pytest.param("앞 문단\n{{img::민아/교실}}\n뒤 문단", "앞 문단\n뒤 문단", id="tag-line-without-blank-lines"),
        pytest.param("앞 문단\n\n  {{img::민아/교실}}  \n\n뒤 문단", "앞 문단\n\n뒤 문단", id="tag-line-with-spaces"),
        pytest.param(
            "앞 문단\n\n{{img::민아/교실}}\n" + _tag(_MINA_ROOFTOP) + "\n\n뒤 문단",
            "앞 문단\n\n뒤 문단",
            id="two-tag-lines-in-a-row",
        ),
        pytest.param("{{img::민아/교실}}\n\n본문", "본문", id="leading-tag-line"),
        pytest.param("본문\n\n{{img::민아/교실}}\n", "본문", id="trailing-tag-line"),
        pytest.param("앞 문단\n\n\n뒤 문단", "앞 문단\n\n\n뒤 문단", id="existing-blank-lines-kept"),
        pytest.param(
            "앞 문단\n\n\n중간 {{img::민아/교실}}\n\n\n뒤 문단",
            "앞 문단\n\n\n중간 \n\n\n뒤 문단",
            id="blank-lines-kept-when-the-tag-line-keeps-text",
        ),
        pytest.param("앞 {{img::/교실}}{{img::민아/}} 뒤", "앞  뒤", id="name-forms-with-a-blank-side"),
        pytest.param("{{img::민아}} {{img::민아/교실", "{{img::민아}} {{img::민아/교실", id="non-tags-untouched"),
        pytest.param("{{user}}\n\n{{char}}", "{{user}}\n\n{{char}}", id="other-braces-untouched"),
        pytest.param("", "", id="empty"),
    ],
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
