"""소설 본문 텍스트 처리 — 문단 나누기, 직전 장 끝 발췌, 장 본문 후처리, 본문형 거절 판정. DB 를 타지 않는다."""

import pytest

from api.novelize.text import clean_chapter_body, ending_excerpt, looks_like_refusal, split_paragraphs


def test_split_paragraphs_uses_blank_lines_and_keeps_single_line_breaks() -> None:
    body = "첫 문단\n이어지는 줄\n\n  \n둘째 문단  \n\n\n\n셋째"
    assert split_paragraphs(body) == ["첫 문단\n이어지는 줄", "둘째 문단", "셋째"]
    assert split_paragraphs("  \n\n ") == []


def test_ending_excerpt_takes_whole_paragraphs_from_the_end_closest_to_the_target() -> None:
    """문단 중간에서 자르지 않고, 끝에서부터 문단을 더해 목표 길이에 가장 가까운 묶음을 고른다."""
    paragraphs = ["가" * 500, "나" * 300, "다" * 300, "라" * 300]
    body = "\n\n".join(paragraphs)
    # 끝에서 1개 300, 2개 602, 3개 904, 4개 1406 → 목표 1000 에 가장 가까운 것은 3개(904).
    assert ending_excerpt(body, 1000) == "\n\n".join(paragraphs[-3:])
    # 목표가 작으면 마지막 문단 하나 — 길어도 자르지 않는다.
    assert ending_excerpt(body, 10) == "라" * 300
    assert ending_excerpt("", 1000) == ""


def test_clean_chapter_body_strips_leaked_turn_markers_and_normalizes_paragraphs() -> None:
    """원문 줄에 붙였던 `[턴 n]` 이 본문에 새어 나오면 표시만 걷어 내고 글은 남긴다."""
    raw = "\n\n[턴 1] 비가 내렸다.\n\n\n\n[턴 12]도윤이 돌아봤다. [턴 3] 그리고 웃었다.\n  \n"
    assert clean_chapter_body(raw) == "비가 내렸다.\n\n도윤이 돌아봤다. 그리고 웃었다."


@pytest.mark.parametrize(
    "paragraphs",
    [
        pytest.param(["죄송하지만 이 요청은 콘텐츠 정책상 작성해 드릴 수 없습니다."], id="ko-only"),
        pytest.param(["비가 내렸다.", "이 장면은 가이드라인 때문에 더 자세히 쓰기 어렵습니다."], id="ko-trailing-note"),
        pytest.param(["요청하신 내용은 도와드릴 수 없어요. 다른 장면을 원하시면 알려 주세요.", "비가 내렸다."], id="ko-leading"),
        pytest.param(["I'm sorry, but I can't help with that request."], id="en"),
    ],
)
def test_refusal_is_a_polite_cannot_sentence_outside_quotes_at_either_end(paragraphs: list[str]) -> None:
    assert looks_like_refusal(paragraphs)


@pytest.mark.parametrize(
    "paragraphs",
    [
        pytest.param(['"죄송합니다, 그건 도와드릴 수 없어요." 서진이 고개를 숙였다.'], id="quoted-dialogue"),
        pytest.param(["도윤은 더는 버틸 수 없었다. 결국 문을 열었다."], id="plain-narration-cannot"),
        pytest.param(["비가 내렸다.", "그녀는 웃으며 고맙다고 했다.", "끝."], id="ordinary"),
        pytest.param(
            ["비가 내렸다.", "죄송하지만 이 요청은 작성할 수 없습니다.", "도윤이 웃었다."], id="middle-is-not-checked"
        ),
        pytest.param([], id="empty"),
    ],
)
def test_story_text_is_not_a_refusal(paragraphs: list[str]) -> None:
    """소설 속 인물의 사과·거절 대사나 '할 수 없었다' 같은 서술은 거절이 아니다. 판정은 처음과 끝 문단만 본다."""
    assert not looks_like_refusal(paragraphs)
