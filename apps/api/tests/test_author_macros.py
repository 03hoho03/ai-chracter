"""작가 글 속 `{{user}}`·`{{char}}` 치환과, 그 자리에 들어갈 이름의 금지 문자 규칙.

치환은 모델로 가는 프롬프트(서버)와 화면(웹)에서 따로 일어나므로 같은 입력 표를 웹 테스트도 읽는다 — 두
구현이 갈라지면 모델이 부른 이름과 화면에 보이는 이름이 달라진다."""

import json
from pathlib import Path

import pytest

from api.content.author_macros import (
    FALLBACK_USER_NAME,
    default_user_name_error,
    expand_author_macros,
    user_name_error,
)

# 치환 표는 웹 테스트와 함께 읽는 JSON 하나다 — 한쪽에만 행을 더하면 두 구현이 갈라져도 모른다.
_CASES = json.loads((Path(__file__).parent / "fixtures" / "author_macro_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("text", "user_name", "char_name", "expected"),
    [
        pytest.param(row["text"], row["userName"], row["charName"], row["expected"], id=row["id"])
        for row in _CASES["expand"]
    ],
)
def test_expand_author_macros(text: str, user_name: str, char_name: str | None, expected: str) -> None:
    assert expand_author_macros(text, user_name=user_name, char_name=char_name) == expected


def test_fallback_name_rows_use_the_exported_fallback() -> None:
    """표의 대체어 행이 시험하는 이름이 실제 대체어와 같아야 그 행이 의미가 있다."""
    (row,) = [row for row in _CASES["expand"] if row["id"] == "fallback-name"]
    assert row["userName"] == FALLBACK_USER_NAME


# 채팅 렌더러에서 표기가 되는 문자는 이름이 글에 끼어들면 이름 밖의 작가 글까지 지문·코드·목록으로 바꾼다.
_REJECTED_NAMES = [
    pytest.param("지:훈", id="colon"),
    pytest.param("지\n훈", id="newline"),
    pytest.param("지\r훈", id="carriage-return"),
    pytest.param("*지훈*", id="star"),
    pytest.param("`지훈`", id="backtick"),
    pytest.param("지훈\\", id="backslash"),
    pytest.param("&#42;지훈", id="decimal-character-reference"),
    pytest.param("&#x2a;지훈", id="hex-character-reference"),
    pytest.param("&ast;지훈", id="named-character-reference"),
    pytest.param("> 지훈", id="quote-marker"),
    pytest.param(">", id="lone-quote-marker"),
    pytest.param("- 지훈", id="dash-list-marker"),
    pytest.param("+", id="lone-plus-list-marker"),
    pytest.param("1. 지훈", id="ordered-list-marker"),
    pytest.param("3)", id="lone-paren-list-marker"),
    pytest.param("~~~지훈", id="tilde-fence"),
    pytest.param("---", id="dash-rule"),
    pytest.param("_ _ _", id="underscore-rule"),
]

_ACCEPTED_NAMES = [
    pytest.param("지훈", id="hangul"),
    pytest.param("민_수_", id="underscore"),
    pytest.param(">_<", id="emoticon-starting-with-angle"),
    pytest.param("김-민", id="inner-dash"),
    pytest.param("별~", id="tilde"),
    pytest.param("~~민~~", id="double-tilde"),
    pytest.param("R&B", id="ampersand"),
    pytest.param("1.5", id="decimal-number"),
    pytest.param("#민", id="hash"),
    pytest.param("[민]", id="bracket"),
    pytest.param("<민>", id="angle"),
    pytest.param("--", id="two-dashes"),
    pytest.param("{지훈}", id="braces"),
]


@pytest.mark.parametrize("name", _REJECTED_NAMES)
def test_user_name_error_rejects_notation_characters(name: str) -> None:
    assert user_name_error(name) is not None
    assert default_user_name_error(name) is not None


@pytest.mark.parametrize("name", _ACCEPTED_NAMES)
def test_user_name_error_accepts_plain_names(name: str) -> None:
    assert user_name_error(name) is None


@pytest.mark.parametrize("name", ["{지훈}", "{{char}}", "지}"])
def test_default_user_name_error_also_rejects_braces(name: str) -> None:
    """작품 기본 이름은 작가가 글과 함께 쓰는 칸이라, 매크로나 이미지 태그를 이름 속에 숨겨 넣지 못하게 한다."""
    assert default_user_name_error(name) is not None


def test_default_user_name_error_accepts_empty() -> None:
    """비워 두면 대체어를 쓴다는 뜻이다."""
    assert default_user_name_error("") is None
