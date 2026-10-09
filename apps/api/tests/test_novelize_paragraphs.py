"""새로 생성한 화 본문의 긴 문단 재분할 — 글자 불변, 대사 분리, 화법 동사 보호, 문턱 아래 문단 불변. 끝에 장 생성 결과에
재분할이 걸리고 거절 판정은 그 전 본문으로 하는지 한 벌 본다. 본문은 모두 직접 지은 합성 문장이다."""

import re
import uuid
from collections.abc import AsyncIterator
from typing import Any

from api.llm.client import LLMCallContext, LLMClient, T
from api.novelize import runner
from api.novelize.inputs import ChapterInput
from api.novelize.paragraphs import LONG_PARAGRAPH_CHARS, resplit_long_paragraphs
from api.novelize.prompts import NovelizePrompt
from api.novelize.text import clean_chapter_body, looks_like_refusal, split_paragraphs
from factories import _batch_output

# 대사와 서술을 한 문단에 몰아 쓴 빽빽한 문단(공백 포함 300자 남짓).
_DENSE = (
    "서진은 문을 열었다. 복도에는 비 냄새가 고여 있었고, 형광등 하나가 끊어질 듯 깜빡였다. "
    '"도윤아, 거기 있어?" 대답은 없었다. 그는 신발을 벗다 말고 한참 서 있었다. '
    '"도윤아!" 이번에는 조금 더 크게 불렀다. 안쪽 방에서 무언가 떨어지는 소리가 났다. '
    '"왜 불러. 자고 있었는데." 도윤이 머리를 긁적이며 나왔다. 서진은 대답 대신 젖은 우산을 내밀었다. '
    "도윤은 우산과 서진의 얼굴을 번갈아 보다가 결국 웃음을 터뜨렸다. 창밖에서는 빗소리가 점점 굵어지고 있었다."
)
# 따옴표 대사가 없는 긴 서술 문단(공백 포함 340자 남짓).
_NARRATION = (
    "그날 밤 서진은 잠들지 못했다. 천장의 얼룩이 자꾸만 사람 얼굴처럼 보였다. 그는 몸을 돌려 벽을 보았다. "
    "벽 너머에서는 도윤이 뒤척이는 소리가 났다. 둘은 같은 비를 듣고 있었을 것이다. 새벽 세 시가 지나자 빗소리가 "
    "조금 잦아들었다. 서진은 결국 일어나 부엌으로 갔다. 냉장고 불빛이 바닥을 하얗게 갈랐다. 그는 물 한 잔을 따라 "
    "식탁에 앉았다. 식탁 위에는 도윤이 남긴 쪽지가 있었다. 쪽지에는 내일 아침 일찍 나간다는 말만 적혀 있었다. "
    "서진은 쪽지를 접었다가 다시 폈다. 글씨가 평소보다 삐뚤었다. 그는 그 삐뚤어진 글씨를 한참 들여다보았다. "
    "창밖이 희부옇게 밝아 올 때까지 그는 그 자리에 있었다."
)
# 모델이 문단을 잘 나눠 쓴 성긴 본문 — 문단마다 문턱 아래이고, 대사와 서술이 섞인 문단·서너 문장 문단도 있다.
_AIRY = (
    "비가 내리는 저녁이었다. 서진은 가방을 내려놓고 창가에 섰다.\n\n"
    '"늦었네." 도윤이 잔을 밀어 주었다. "기다렸어?"\n\n'
    "서진은 고개를 저었다. 잔은 아직 따뜻했다. 그는 두 손으로 잔을 감쌌다. 창밖으로 버스 한 대가 지나갔다.\n\n"
    "* * *\n\n"
    '다음 날 아침, 식탁에는 쪽지 한 장만 남아 있었다. "먼저 갈게." 하고 적힌 글씨가 삐뚤었다.'
)


def _strip_whitespace(text: str) -> str:
    return re.sub(r"\s", "", text)


def _paragraphs(text: str) -> list[str]:
    return text.split("\n\n")


# ── 불변식 ───────────────────────────────────────────────────────────────────
def test_only_whitespace_changes_and_paragraphs_are_separated_by_one_blank_line() -> None:
    body = clean_chapter_body("\n\n".join([_DENSE, "* * *", _NARRATION, _AIRY]))

    result = resplit_long_paragraphs(body)

    assert _strip_whitespace(result) == _strip_whitespace(body)
    assert result != body
    assert clean_chapter_body(result) == result


def test_every_piece_of_a_long_paragraph_with_sentence_ends_fits_under_the_threshold() -> None:
    for paragraph in (_DENSE, _NARRATION):
        assert len(paragraph) > LONG_PARAGRAPH_CHARS
        pieces = _paragraphs(resplit_long_paragraphs(paragraph))
        assert len(pieces) > 1
        assert max(len(piece) for piece in pieces) <= LONG_PARAGRAPH_CHARS


def test_long_narration_is_cut_into_even_pieces_rather_than_full_pieces_and_a_stub() -> None:
    """479자 서술은 세 조각이면 문턱 아래로 들어간다 — 문턱까지 채운 두 조각 뒤에 80자 꼬리를 남기지 않고 고르게 나눈다."""
    paragraph = ("비가 내렸다. " * 60).strip()

    pieces = _paragraphs(resplit_long_paragraphs(paragraph))

    assert len(pieces) == 3
    assert min(len(piece) for piece in pieces) > LONG_PARAGRAPH_CHARS // 2


# ── 대사 분리와 화법 동사 보호 ───────────────────────────────────────────────
def test_quoted_lines_in_a_long_paragraph_become_their_own_paragraphs() -> None:
    pieces = _paragraphs(resplit_long_paragraphs(_DENSE))

    assert '"도윤아, 거기 있어?"' in pieces
    assert '"도윤아!"' in pieces
    # 따옴표 안의 두 문장은 한 대사라 자르지 않는다.
    assert '"왜 불러. 자고 있었는데."' in pieces
    assert pieces[0] == "서진은 문을 열었다. 복도에는 비 냄새가 고여 있었고, 형광등 하나가 끊어질 듯 깜빡였다."


def test_a_quote_followed_by_a_speech_verb_or_particle_stays_with_it() -> None:
    lines = [
        '"이제 그만하자." 하고 서진이 먼저 말했다.',
        '"알았어." 라며 도윤이 등을 돌렸다.',
        '"정말이야?" 하는 목소리가 떨렸다.',
        '"가자"라며 그가 손을 내밀었다.',
        "「여기서 기다려.」 라고 적힌 쪽지가 문에 붙어 있었다.",
    ]
    paragraph = " ".join(lines + ["둘은 그 뒤로 한동안 아무 말도 하지 않았다. 비는 밤새 그치지 않았다."] * 3)
    assert len(paragraph) > LONG_PARAGRAPH_CHARS

    pieces = _paragraphs(resplit_long_paragraphs(paragraph))

    for line in lines:
        assert any(line in piece for piece in pieces), line
    assert not any(piece.startswith(("하고", "라며", "하는", "라고")) for piece in pieces)


def test_conjugated_speech_tails_stay_with_their_quote() -> None:
    lines = [
        '"그만해!" 하더니 그는 문을 쾅 닫았다.',
        '"가자." 했지만 아무도 움직이지 않았다.',
        '"배고파." 하길래 라면을 끓였다.',
        '"정말?" 하니 그가 웃었다.',
        '"사랑." 이란 말이 그렇게 무거운 줄 몰랐다.',
        '"괜찮아." 라면서 그는 고개를 돌렸다.',
    ]
    filler = "서진은 창밖을 오래 바라보았다. " * 7
    for line in lines:
        paragraph = filler + line + " " + filler.strip()
        assert len(paragraph) > LONG_PARAGRAPH_CHARS

        pieces = _paragraphs(resplit_long_paragraphs(paragraph))

        assert any(line in piece for piece in pieces), line


def test_a_new_sentence_after_a_quote_is_still_cut_even_if_it_starts_like_a_tail() -> None:
    """'하지만'·'하늘'처럼 '하'로 시작하지만 화법 꼬리가 아닌 말 앞에서는 대사를 떼어 낸다."""
    filler = "서진은 창밖을 오래 바라보았다. " * 7
    for after in ("하지만 아무도 대답하지 않았다.", "하늘은 여전히 흐렸다.", "한참 뒤에야 문이 열렸다."):
        paragraph = filler + '"가자." ' + after + " " + filler.strip()

        pieces = _paragraphs(resplit_long_paragraphs(paragraph))

        assert '"가자."' in pieces, after


def test_a_curly_quote_or_corner_bracket_line_is_dialogue_too() -> None:
    paragraph = (
        "서진은 편지를 다시 읽었다. " * 10 + "“돌아오지 마.” 그 한 줄이 마지막이었다. 「잘 지내.」 서명은 없었다."
    )

    pieces = _paragraphs(resplit_long_paragraphs(paragraph))

    assert "“돌아오지 마.”" in pieces
    assert "「잘 지내.」" in pieces


def test_an_inner_thought_in_single_quotes_is_not_cut_inside_nor_pulled_out() -> None:
    thought = "‘아니야. 아직은 아니야. 조금만 더 기다리자.’"
    paragraph = "서진은 창밖을 보았다. " * 8 + thought + " 그는 다시 고개를 숙였다."

    pieces = _paragraphs(resplit_long_paragraphs(paragraph))

    assert any(thought in piece for piece in pieces)
    assert thought not in pieces


def test_nothing_after_an_unclosed_quote_is_cut() -> None:
    paragraph = (
        "서진은 우산을 접었다. " * 10
        + '"잠깐만. 아직 할 말이 남았어. 그러니까 가지 마. '
        + ("비가 다시 쏟아졌다. " * 5).strip()
    )
    assert len(paragraph) > LONG_PARAGRAPH_CHARS

    result = resplit_long_paragraphs(paragraph)

    assert _strip_whitespace(result) == _strip_whitespace(paragraph)
    assert _paragraphs(result)[-1].endswith(paragraph[paragraph.index('"잠깐만.') :])


def test_a_stray_straight_quote_does_not_flip_the_later_dialogue_inside_out() -> None:
    """인치 표기처럼 짝 없는 곧은 큰따옴표 하나가 앞에 있으면, 뒤의 대사를 여닫음이 뒤집힌 채 읽어 대사 한가운데를
    자르게 된다. 그 따옴표 뒤로는 자르지 않는다."""
    filler = "서진은 창밖을 오래 바라보았다. " * 7
    dialogue = '"안녕. 오랜만이야. 잘 지냈어?"'
    paragraph = '그는 27" 모니터를 켰다. ' + filler + dialogue + " 그가 물었다. " + filler.strip()
    assert len(paragraph) > LONG_PARAGRAPH_CHARS

    pieces = _paragraphs(resplit_long_paragraphs(paragraph))

    assert any(dialogue in piece for piece in pieces)
    assert _strip_whitespace("".join(pieces)) == _strip_whitespace(paragraph)


def test_a_line_break_inside_a_long_paragraph_is_a_place_to_cut() -> None:
    paragraph = "서진은 쪽지를 읽었다\n" + ("도윤은 대답하지 않았다 " * 16).strip()
    assert len(paragraph) > LONG_PARAGRAPH_CHARS

    pieces = _paragraphs(resplit_long_paragraphs(paragraph))

    assert pieces[0] == "서진은 쪽지를 읽었다"


def test_a_long_sentence_without_an_end_is_left_over_the_threshold() -> None:
    paragraph = "서진은 비에 젖은 골목을 따라 " * 20 + "걸었다."

    assert resplit_long_paragraphs(paragraph) == paragraph


# ── 건드리지 않는 것 ─────────────────────────────────────────────────────────
def test_an_airy_body_comes_back_unchanged() -> None:
    assert resplit_long_paragraphs(_AIRY) == _AIRY


def test_the_threshold_is_inclusive_a_paragraph_at_it_stays_and_one_over_it_splits() -> None:
    """대사가 섞인 문단이라 다시 나누면 반드시 모양이 바뀐다 — 서술만 있는 문단은 문턱 아래면 한 조각으로 다시 묶여
    문턱을 무시해도 같은 결과가 나온다."""
    opening = '"가자." '
    at_threshold = opening + ("비가 내렸다. " * 40)[: LONG_PARAGRAPH_CHARS - len(opening) - 1] + "."
    over_threshold = at_threshold[:-1] + "다."
    assert (len(at_threshold), len(over_threshold)) == (LONG_PARAGRAPH_CHARS, LONG_PARAGRAPH_CHARS + 1)

    assert resplit_long_paragraphs(at_threshold) == at_threshold
    assert len(_paragraphs(resplit_long_paragraphs(over_threshold))) > 1
    # 긴 문단이 함께 있어 본문 전체가 다시 나뉠 때도 문턱 길이 문단은 그대로 남는다.
    beside_long = resplit_long_paragraphs(at_threshold + "\n\n" + _NARRATION)
    assert _paragraphs(beside_long)[0] == at_threshold


def test_short_paragraphs_and_scene_breaks_around_a_long_one_keep_their_places() -> None:
    body = "\n\n".join(["짧은 첫 문단이다.", _NARRATION, "* * *", "짧은 끝 문단이다."])

    pieces = _paragraphs(resplit_long_paragraphs(body))

    assert pieces[0] == "짧은 첫 문단이다."
    assert pieces[-2:] == ["* * *", "짧은 끝 문단이다."]
    assert "\n\n".join(pieces[1:-2]).replace("\n\n", " ") == _NARRATION


def test_empty_and_short_bodies_come_back_unchanged() -> None:
    for body in ("", "비가 내렸다.", '"가자." 그가 말했다.'):
        assert resplit_long_paragraphs(body) == body


# ── 장 생성에 걸린 자리 ──────────────────────────────────────────────────────
class _OneShotLLM(LLMClient):
    def __init__(self, output: str) -> None:
        self.output = output

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        yield self.output

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        raise AssertionError("장 생성은 구조화 호출을 쓰지 않는다")

    async def generate_structured_with_instruction(
        self, prompt: str, response_schema: type[T], *, system_instruction: str, usage: LLMCallContext
    ) -> T:
        raise AssertionError("장 생성은 구조화 호출을 쓰지 않는다")


async def _generated_body(output: str) -> str:
    chapter_input = ChapterInput(
        prompt=NovelizePrompt(system_instruction="지시", prompt="원문"),
        room_id=uuid.uuid4(),
        assistant_count=1,
        source_hash="hash",
        episode_count=1,
        writes_novel_title=False,
    )
    usage = LLMCallContext(call_site="novelize_chapter", user_id=None, room_id=None)
    parsed = await runner._generate_batch(_OneShotLLM(output), chapter_input, usage)
    (episode,) = parsed.episodes
    return episode.body


async def test_a_generated_episode_is_saved_with_its_long_paragraphs_resplit() -> None:
    raw = "[턴 1] " + _DENSE + "\n\n\n\n" + _NARRATION

    body = await _generated_body(_batch_output(raw))

    assert body == resplit_long_paragraphs(clean_chapter_body(raw))
    assert len(split_paragraphs(body)) > 2


async def test_refusal_is_judged_on_the_body_before_it_is_resplit() -> None:
    """따옴표 없이 옮긴 높임말 편지로 시작하는 긴 첫 문단. 같은 문단의 3인칭 서술 덕에 거절이 아닌데, 다시 나눈 뒤의
    첫 조각(편지만)으로 판정하면 거절로 오판해 멀쩡한 화를 버리고 환불한다."""
    letter = (
        "죄송하지만 저는 더 이상 이곳에 머무를 수 없습니다. 그동안 베풀어 주신 마음은 잊지 않겠습니다. "
        "부디 저를 찾지 말아 주세요. 이 편지가 마지막 인사가 될 것 같습니다. 언젠가 다시 뵐 수 있기를 바랍니다. "
        "아이들에게는 제가 먼 곳으로 일하러 갔다고만 전해 주세요. 정말 감사했습니다. 늘 건강하시기를 빕니다. "
    )
    first = letter + "편지는 거기서 끝나 있었다. 서진은 편지를 접어 주머니에 넣었다. 창밖에서는 비가 그쳐 가고 있었다."
    raw = first + "\n\n" + _NARRATION
    first_piece = _paragraphs(resplit_long_paragraphs(first))[0]
    assert not looks_like_refusal(split_paragraphs(clean_chapter_body(raw)))
    assert looks_like_refusal([first_piece])

    body = await _generated_body(_batch_output(raw))

    assert split_paragraphs(body)[0] == first_piece
