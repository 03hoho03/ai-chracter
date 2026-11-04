"""`analyze_chat_probe.reply_flags` 가 응답 속 코드 펜스를 다루는 규칙.

작품 규칙이 응답 끝에 상태창을 ``` 코드 블록으로 붙이게 하는 작품이 있다(튜토리얼 시드 `tutorial-filmclub.json`). 그 블록을
문장으로 읽으면 마지막 문장이 늘 닫는 펜스라 완결 응답이 전부 절단·장면 열림으로 잡힌다. 아카이브 대화록에는 펜스가 하나도 없어
특성화 대조(`test_analyze_chat_probe_characterization.py`)로는 이 경로가 잡히지 않는다."""

import pytest

from analyze_chat_probe import WINDOWS, _parroted, reply_flags

STATUS_BLOCK = "```\n장소 | 학생회관 동아리방\n시간 | 9월 30일 화요일 밤\n함께 | 강도희, 민유나\n지금 | 대본 회의\n```"


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(f"*도희가 펜을 멈춘다.* 일부러.\n\n{STATUS_BLOCK}", id="block-at-the-end"),
        pytest.param(f"일부러.\n\n{STATUS_BLOCK}\n\n", id="blank-lines-after-the-block"),
        pytest.param(f"일부러.\n\n{STATUS_BLOCK}\n{STATUS_BLOCK}", id="two-blocks-at-the-end"),
        pytest.param("일부러.\n~~~\n장소 | 동아리방\n~~~", id="tilde-fence"),
    ],
)
def test_a_complete_reply_ending_in_a_closed_fence_block_is_not_truncated(reply: str) -> None:
    assert reply.rstrip().endswith(("```", "~~~"))
    assert not reply_flags(reply, "").truncated


def test_a_reply_cut_before_its_status_block_is_truncated() -> None:
    assert reply_flags(f"*도희가 펜을 멈춘다.* 일부러 그\n\n{STATUS_BLOCK}", "").truncated


def test_a_closed_block_in_the_middle_stays_and_the_body_after_it_is_judged() -> None:
    """중간 블록 뒤의 본문이 마지막 문장이다 — 첫 블록부터 끝까지 떼면 잘린 뒤 본문을 놓친다."""
    assert reply_flags(f"앞 문장.\n\n{STATUS_BLOCK}\n\n뒤에 이어", "").truncated
    assert not reply_flags(f"앞 문장.\n\n{STATUS_BLOCK}\n\n뒤에 이어진다.", "").truncated


def test_an_unclosed_fence_is_truncated_even_when_its_last_line_ends_with_a_period() -> None:
    """닫는 줄 없이 끝난 응답은 블록을 쓰다 멈춘 것이다. 마지막 줄이 종결 부호로 끝나도 절단이다."""
    assert reply_flags("일부러.\n\n```\n장소 | 학생회관 동아리방.", "").truncated
    # 여는 줄보다 짧은 펜스는 닫는 줄이 아니다.
    assert reply_flags("일부러.\n\n````\n장소 | 동아리방\n```", "").truncated


def test_the_scene_closing_judgment_reads_the_last_sentence_before_the_status_block() -> None:
    """장면 이동형 열기도 마지막 문장을 본다 — 블록째 보면 마지막 문장이 ``` 라 닫힌 장면도 늘 열림이 된다."""
    closed = reply_flags(f"도희가 대본을 덮자 동아리방에 정적만이 남는다.\n\n{STATUS_BLOCK}", "")
    unclosed = reply_flags("도희가 대본을 덮자 동아리방에 정적만이 남는다.\n\n```\n장소 | 학생회관", "")

    assert (closed.scene_open, closed.truncated) == (False, False)
    assert (unclosed.scene_open, unclosed.truncated) == (False, True)


def test_length_and_sentence_count_leave_the_status_block_out_and_report_its_length_apart() -> None:
    """길이·문장 수는 끝의 상태창을 뗀 본문으로 세고, 뗀 꼬리(블록과 그 앞 빈 줄)의 글자 수는 따로 낸다 — 둘을 더하면 응답 전체다.
    뗀 것이 없으면 꼬리 공백까지 응답 그대로 센다(펜스 없는 대화록의 길이가 바뀌지 않는다)."""
    body = "일부러. 펜을 멈춘다."
    reply = f"{body}\n\n{STATUS_BLOCK}"
    flags = reply_flags(reply, "")
    plain = reply_flags(f"{body}\n", "")
    middle = f"앞 문장.\n{STATUS_BLOCK}\n뒤 문장."
    unclosed = "일부러.\n\n```\n장소 | 동아리방"

    assert (flags.length, flags.sentence_count, flags.status_block_length) == (len(body), 2, len(f"\n\n{STATUS_BLOCK}"))
    assert (plain.length, plain.sentence_count, plain.status_block_length) == (len(body) + 1, 2, 0)
    assert (reply_flags(middle, "").length, reply_flags(middle, "").status_block_length) == (len(middle), 0)
    assert (reply_flags(unclosed, "").length, reply_flags(unclosed, "").status_block_length) == (4, len(unclosed) - 4)


def test_parroting_windows_cover_the_body_only_so_a_keyword_in_the_status_block_is_not_parroting() -> None:
    """되받기의 세 창도 상태창을 뗀 본문에 둔다. 본문이 짧으면 앞 250자·앞 30% 창이 상태창 줄까지 덮어 그 낱말을 되받기로 센다.
    첫 대본 턴의 표지는 "상황"이다."""
    status_only = "가.\n```\n지금 | 상황\n" + "다음 장면 준비" * 6 + "\n```"
    in_body = f"상황이 이상하다.\n\n{STATUS_BLOCK}"

    assert [_parroted(status_only, 0, window) for window in WINDOWS] == [False, False, False]
    assert [_parroted(in_body, 0, window) for window in WINDOWS] == [True, True, True]

