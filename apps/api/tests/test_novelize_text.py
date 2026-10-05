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


@pytest.mark.parametrize(
    "paragraph",
    [
        # "-다니다 + 띄어쓰기"는 "-다가"의 준말로 쓰는 순수 서술이다. 높임 어미는 문장 끝에서만 센다.
        pytest.param("골목을 떠돌아다니다 지친 그는 어쩔 수 없이 벤치에 앉았다.", id="danida-mid-sentence"),
        # 따옴표 없이 옮긴 방송 멘트의 높임말과 서술의 "수 없었다"는 다른 문장이다.
        pytest.param(
            "라디오에서 늦은 밤 DJ의 목소리가 흘러나왔다. 오늘 밤도 함께해 주셔서 감사합니다. 지수는 웃음을 참을 수 없었다.",
            id="unquoted-broadcast",
        ),
        # 따옴표 없이 옮긴 편지는 한 문장에 높임 어미와 "수 없"이 함께 있어도, 같은 문단의 3인칭 서술이 소설임을 보여 준다.
        pytest.param(
            "편지는 짧았다. 그동안 고마웠어요. 더는 기다릴 수 없을 것 같아요. 민준은 편지를 접었다.",
            id="unquoted-letter",
        ),
        # 큰따옴표 대사가 문단 안에서 줄을 바꿔도 대사 전체가 지워져야 한다.
        pytest.param('"정말 미안해요.\n저는 갈 수 없어요." 그녀가 말했다.', id="dialogue-across-line-break"),
        pytest.param('"저는 갈 수 없어요.\n정말 미안해요."', id="dialogue-across-line-break-alone"),
        # 아래 둘은 "-다" 로 끝나는 서술 문장이 없는 문단(명사로 끝나는 단상)이라 어미·문장 규칙만으로 걸러야 한다.
        pytest.param("어쩔 수 없이 떠돌아다니다 멈춘 곳, 낡은 벤치 위.", id="danida-without-plain-sentence"),
        pytest.param(
            "오늘 밤도 함께해 주셔서 감사합니다. 그 목소리에, 참을 수 없는 그리움.", id="polite-and-cannot-apart"
        ),
    ],
)
def test_narration_with_polite_words_is_not_a_refusal(paragraph: str) -> None:
    """정상 소설 서술이 거절로 잡히면 기다린 결과가 버려지고 같은 원문에서 되풀이해 실패한다. 그래서 판정은 놓침보다
    오탐을 더 피한다 — 처음·끝 문단 하나만 두고도 거절로 보지 않아야 하는 모양들이다."""
    assert not looks_like_refusal([paragraph])
