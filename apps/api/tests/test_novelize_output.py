"""묶음 출력 파서 — 형식이 맞으면 화 목록이, 어긋나면 예외가 나온다. 순수 함수라 DB 없이 본다."""

import pytest

from api.novelize.output import MalformedOutputError, ParsedEpisode, parse_batch_output
from factories import _batch_output, _episode_text

_BODY_1 = "비가 내리는 저녁이었다.\n\n서진은 창가에 섰다."
_BODY_2 = "다음 날 아침이 밝았다."


def test_two_episodes_with_a_novel_title_are_read_in_order() -> None:
    text = (
        "===소설 제목===\n빗소리의 계절\n"
        "===1화===\n제목: 비 오는 저녁\n요약: 서진이 도윤을 만났다. 둘은 말없이 앉았다.\n등장인물: 서진, 도윤, 서진\n---\n"
        f"{_BODY_1}\n"
        "===2화===\n제목: 아침\n요약: 날이 밝았다.\n등장인물:\n---\n"
        f"{_BODY_2}\n"
    )

    parsed = parse_batch_output(text)

    assert parsed.novel_title == "빗소리의 계절"
    assert parsed.episodes == (
        ParsedEpisode(
            title="비 오는 저녁",
            summary="서진이 도윤을 만났다. 둘은 말없이 앉았다.",
            characters=("서진", "도윤"),
            body=_BODY_1,
        ),
        ParsedEpisode(title="아침", summary="날이 밝았다.", characters=(), body=_BODY_2),
    )


def test_without_a_novel_title_block_the_title_is_none() -> None:
    parsed = parse_batch_output(_batch_output(_BODY_1))
    assert parsed.novel_title is None
    assert [e.body for e in parsed.episodes] == [_BODY_1]


def test_blank_lines_and_surrounding_spaces_between_structural_lines_are_tolerated() -> None:
    """모델이 구조 줄 사이에 빈 줄을 넣거나 줄 앞뒤에 공백을 붙이는 것은 뜻이 없다 — 받는다. 본문 줄의 들여쓰기는
    그대로 둔다(본문 후처리는 호출부가 한다)."""
    text = "\n\n  ===1화===  \n\n제목 : 저녁\n\n 요약: 비가 왔다.\n등장인물: 서진 \n\n  ---\n  첫 줄\n둘째 줄\n\n"

    (episode,) = parse_batch_output(text).episodes

    assert (episode.title, episode.summary, episode.characters) == ("저녁", "비가 왔다.", ("서진",))
    assert episode.body == "첫 줄\n둘째 줄"


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("", id="empty"),
        pytest.param("그냥 본문만 썼다.\n\n두 번째 문단.", id="no-structure"),
        pytest.param("알겠습니다. 소설로 옮겨 보겠습니다.\n" + _episode_text(_BODY_1), id="preamble"),
        pytest.param(_episode_text(_BODY_1, number=2), id="starts-at-2"),
        pytest.param(_episode_text(_BODY_1) + "\n" + _episode_text(_BODY_2, number=3), id="skips-a-number"),
        pytest.param(_episode_text(_BODY_1) + "\n" + _episode_text(_BODY_2, number=1), id="repeats-a-number"),
        pytest.param("===1화===\n제목: 저녁\n등장인물: 서진\n---\n본문", id="missing-summary"),
        pytest.param("===1화===\n요약: 비\n제목: 저녁\n등장인물: 서진\n---\n본문", id="fields-out-of-order"),
        pytest.param("===1화===\n제목: 저녁\n요약: 비\n---\n본문", id="missing-characters"),
        pytest.param("===1화===\n제목: 저녁\n요약: 비\n등장인물: 서진\n본문", id="missing-separator"),
        pytest.param("===1화===\n제목:\n요약: 비\n등장인물: 서진\n---\n본문", id="empty-title"),
        pytest.param("===1화===\n제목: 저녁\n요약:  \n등장인물: 서진\n---\n본문", id="empty-summary"),
        pytest.param("===1화===\n제목: 저녁\n요약: 비\n등장인물: 서진\n", id="ends-before-separator"),
        pytest.param("===1 화===\n제목: 저녁\n요약: 비\n등장인물: 서진\n---\n본문", id="malformed-header"),
        pytest.param(_episode_text("첫 문단\n---\n장면 전환"), id="separator-inside-body"),
        pytest.param(_episode_text("첫 문단\n===막간===\n둘째"), id="header-like-line-inside-body"),
        pytest.param("===소설 제목===\n\n===1화===\n제목: 저녁\n요약: 비\n등장인물: 서진\n---\n본문", id="empty-novel-title"),
        pytest.param(_episode_text(_BODY_1) + "\n===소설 제목===\n늦은 제목", id="novel-title-after-episodes"),
        pytest.param("===소설 제목===\n제목만 있다", id="title-without-episodes"),
    ],
)
def test_output_off_the_format_is_malformed(text: str) -> None:
    with pytest.raises(MalformedOutputError):
        parse_batch_output(text)
