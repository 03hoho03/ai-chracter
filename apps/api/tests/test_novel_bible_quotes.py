"""근거 인용 찾기 — 모델이 옮긴 구절을 그 문단 글에서 찾아 블록·구간·해시를 낸다.

유니코드 조합형 차이(NFC)와 공백 차이(여러 칸·줄바꿈·전각 공백)만 다른 인용은 찾는다. 저장하는 구간과 해시는 모델이 낸 글이
아니라 원문에서 찾은 구간의 원문 글로 낸다 — 차단 판정의 근거 실재 검증이 개정 본문을 다시 문단으로 나눠 그 구간의 해시를
맞추므로, 모델 글로 해시를 내면 정규화로 찾은 인용은 그 검증에서 늘 떨어져 그 근거에 기댄 차단이 경고로 낮아진다. 그래서
찾은 경우마다 그 검증과 같은 계산이 맞는지 함께 본다. 원문에 없는 인용은 여전히 버린다. 픽스처는 합성 문장이다."""

import unicodedata
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.novel_bible.core.quotes import manuscript_evidence_verified, quote_hash, verify_quote
from api.novel_bible.core.types import Manuscript, ManuscriptBlock, QuoteOut, VerifiedQuote
from api.novel_bible.core.views import manuscript_of
from api.novelize.text import split_paragraphs
from novel_bible_fakes import add_chapter, make_novel


def _nfd(text: str) -> str:
    return unicodedata.normalize("NFD", text)


def _manuscript(body: str) -> Manuscript:
    blocks = tuple(
        ManuscriptBlock(index=number, block_id=uuid.uuid4(), text=text)
        for number, text in enumerate(split_paragraphs(body), start=1)
    )
    return Manuscript(revision_id=uuid.uuid4(), blocks=blocks)


def _found(body: str, paragraph: int, text: str) -> tuple[Manuscript, VerifiedQuote]:
    manuscript = _manuscript(body)
    verified = verify_quote(manuscript, QuoteOut(paragraph=paragraph, text=text))
    assert verified is not None
    return manuscript, verified


def _span(manuscript: Manuscript, verified: VerifiedQuote) -> str:
    block = next(block for block in manuscript.blocks if block.block_id == verified.block_id)
    return block.text[verified.char_start : verified.char_end]


def _stored_evidence_holds(body: str, manuscript: Manuscript, verified: VerifiedQuote) -> bool:
    """차단 판정의 근거 실재 검증과 같은 계산 — 본문을 다시 문단으로 나눠 그 블록 순번의 구간 해시를 맞춘다."""
    index = [block.block_id for block in manuscript.blocks].index(verified.block_id)
    paragraph = split_paragraphs(body)[index]
    return quote_hash(paragraph[verified.char_start : verified.char_end]) == verified.quote_sha256


def test_an_exact_quote_is_found_at_its_place() -> None:
    body = "첫 문단은 비어 있지 않다.\n\n그는 문을 열고 밖으로 나갔다."

    manuscript, verified = _found(body, 2, "문을 열고")

    assert (verified.block_id, verified.char_start, verified.char_end) == (manuscript.blocks[1].block_id, 3, 8)
    assert verified.quote_sha256 == quote_hash("문을 열고")
    assert _stored_evidence_holds(body, manuscript, verified)


def test_a_composed_quote_is_found_in_a_decomposed_paragraph_and_the_span_is_the_paragraphs_own_text() -> None:
    # 앞말까지 분해형이라 정규화하면 앞이 줄어든다 — 정규화한 글의 위치를 그대로 쓰면 구간이 어긋난다.
    paragraph = _nfd("앞말이 길다. 그는 문을 열었다. 뒷말")
    body = f"첫 문단.\n\n{paragraph}"

    manuscript, verified = _found(body, 2, "문을 열었다")

    assert _span(manuscript, verified) == _nfd("문을 열었다")
    assert verified.char_start == paragraph.index(_nfd("문을 열었다"))
    assert verified.quote_sha256 == quote_hash(_nfd("문을 열었다")) != quote_hash("문을 열었다")
    assert _stored_evidence_holds(body, manuscript, verified)


def test_a_decomposed_quote_is_found_in_a_composed_paragraph_and_hashes_the_composed_text() -> None:
    body = "그는 문을 열었다. 바람이 들어왔다."

    manuscript, verified = _found(body, 1, _nfd("바람이 들어왔다"))

    assert (verified.char_start, verified.char_end) == (11, 19)
    assert verified.quote_sha256 == quote_hash("바람이 들어왔다") != quote_hash(_nfd("바람이 들어왔다"))
    assert _stored_evidence_holds(body, manuscript, verified)


def test_a_letter_with_several_combining_marks_is_normalized_as_one_piece() -> None:
    # 겹친 결합 부호는 앞 글자와 함께 정규화해야 한다 — 부호를 하나씩 따로 정규화하면 뒤 부호가 앞 글자와 합쳐지지 않는다.
    body = "표시 a\u0335\u0301 뒤"

    manuscript, verified = _found(body, 1, unicodedata.normalize("NFC", "a\u0335\u0301 뒤"))

    assert _span(manuscript, verified) == "a\u0335\u0301 뒤"
    assert _stored_evidence_holds(body, manuscript, verified)


@pytest.mark.parametrize(
    ("paragraph", "quote", "span"),
    [
        pytest.param(
            "그는  문을\n열고   나갔다. 그리고 웃었다.",
            "문을 열고 나갔다.",
            "문을\n열고   나갔다.",
            id="runs-in-paragraph",
        ),
        pytest.param(
            "그는\u3000문을 열었다. 끝.", "그는 문을 열었다.", "그는\u3000문을 열었다.", id="full-width-space"
        ),
        pytest.param("그는 문을 열고 나갔다.", "문을   열고\t나갔다", "문을 열고 나갔다", id="runs-in-quote"),
        pytest.param("문을 열었다. 끝.", " 문을 열었다.\n", "문을 열었다.", id="outer-whitespace-of-quote"),
    ],
)
def test_a_quote_that_differs_only_in_whitespace_is_found_and_the_span_is_the_paragraphs_own_text(
    paragraph: str, quote: str, span: str
) -> None:
    body = f"첫 문단.\n\n{paragraph}"

    manuscript, verified = _found(body, 2, quote)

    assert _span(manuscript, verified) == span
    assert verified.char_start == paragraph.index(span)
    assert verified.quote_sha256 == quote_hash(span)
    assert _stored_evidence_holds(body, manuscript, verified)


def test_composition_and_whitespace_differences_together_map_back_to_the_original_span() -> None:
    prefix = _nfd("가나다라") + "   "
    span = _nfd("문을") + "\n \u3000" + _nfd("열었다")
    paragraph = prefix + span + _nfd(" 그 뒤")
    body = f"첫 문단.\n\n{paragraph}\n\n끝 문단."

    manuscript, verified = _found(body, 2, "문을 열었다")

    assert (verified.char_start, verified.char_end) == (len(prefix), len(prefix) + len(span))
    assert verified.quote_sha256 == quote_hash(span)
    assert _stored_evidence_holds(body, manuscript, verified)


@pytest.mark.parametrize(
    ("paragraph", "quote"),
    [
        pytest.param(2, "창문을 닫았다", id="different-words"),
        pytest.param(1, "문을 열었다", id="in-another-paragraph"),
        pytest.param(3, "첫 문단", id="paragraph-out-of-range"),
        pytest.param(2, "문을열었다", id="missing-space-is-not-a-whitespace-run"),
        pytest.param(2, "ＡＢ", id="full-width-letters-are-not-folded"),
        pytest.param(2, "   ", id="whitespace-only"),
        pytest.param(2, "", id="empty"),
    ],
)
def test_a_quote_that_is_not_in_its_paragraph_is_still_dropped(paragraph: int, quote: str) -> None:
    manuscript = _manuscript("첫 문단이다.\n\n그는 AB 문을 열었다.")

    assert verify_quote(manuscript, QuoteOut(paragraph=paragraph, text=quote)) is None


async def test_a_quote_found_through_normalization_passes_the_evidence_check_that_guards_blocking(
    db_session: AsyncSession,
) -> None:
    # 저장된 개정 본문으로 차단 전 근거 검증을 한 바퀴 돈다. 같은 구간에 모델 글의 해시를 붙인 근거는 그 검증에서 떨어진다 —
    # 정규화로 찾은 인용의 해시를 원문 구간에서 내지 않으면 그 근거가 실재하지 않는 것으로 읽힌다는 대조다.
    novel = await make_novel(db_session)
    quote = "그는 문을 열었다."
    _, revision = await add_chapter(
        db_session, novel.id, 1, f"첫 문단.\n\n{_nfd('앞말이 길다.')}  {_nfd('그는')}\n문을   열었다."
    )
    verified = verify_quote(manuscript_of(revision), QuoteOut(paragraph=2, text=quote))
    assert verified is not None
    model_hashed = verified.model_copy(update={"quote_sha256": quote_hash(quote)})
    kept, mismatched = uuid.uuid4(), uuid.uuid4()

    result = await manuscript_evidence_verified(
        db_session, {kept, mismatched}, {kept: (verified,), mismatched: (model_hashed,)}, revision.id
    )

    assert result == {kept: True, mismatched: False}
