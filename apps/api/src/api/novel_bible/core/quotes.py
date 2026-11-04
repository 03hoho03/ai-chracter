"""근거 인용의 실재 검증 — 인용이 원고 블록 글 안에 있는지, 저장된 근거(블록·구간·해시)가 지금도 그 개정의 글과 맞는지.

모델이 옮긴 인용은 유니코드 조합형(분해형 한글 자모 따위)이나 공백(여러 칸·줄바꿈·전각 공백)만 원문과 다를 수 있다. 그런
차이만으로 있는 인용을 버리면 근거 없는 항목으로 잘못 세어지므로 정규화한 글에서 다시 찾는다. 다만 저장하는 구간과 해시는
모델이 낸 글이 아니라 원문에서 찾은 구간의 원문 글로 낸다 — 차단 판정이 개정 본문을 다시 나눠 그 구간의 해시를 맞춰 보므로,
모델 글로 해시를 내면 정규화로 찾은 인용은 그 대조에서 늘 떨어져 그 근거에 기댄 차단이 경고로 낮아진다.

원고 밖의 글(사실 슬롯이 원작 정본에서 찾는 차이 구절)도 같은 찾기(`locate_quote`)를 쓴다. 규칙이 갈리면 같은 모양의 구절이
원고에서는 찾아지고 원작에서는 버려져, 측정에서 두 근거의 버림률을 견줄 수 없다."""

import hashlib
import itertools
import unicodedata
import uuid
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.novel import NovelChapterRevision
from api.db.models.novel_bible import NovelBibleEvidence
from api.novel_bible.core.types import Manuscript, QuoteOut, VerifiedQuote
from api.novelize.text import split_paragraphs


def quote_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# 찾는 글의 문자 하나가 나온 원문 구간(시작, 끝).
_Span = tuple[int, int]


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _starts_fresh(char: str) -> bool:
    """분해했을 때 첫 문자가 결합 부호가 아닌 문자 — 그 앞에서만 정규화 묶음을 끊는다. 결합 부호 앞에서 끊으면 그 뒤의 결합
    부호가 앞 글자와 합쳐지거나 순서를 바꾸는 것을 놓친다."""
    return unicodedata.combining(unicodedata.normalize("NFD", char)[0]) == 0


def _nfc_with_spans(text: str) -> tuple[str, list[_Span]]:
    """NFC 정규화한 글과, 그 글의 문자마다 그 문자를 낸 원문 구간. 정규화가 서로 영향을 주는 문자열(분해형 한글 자모, 기본
    문자와 결합 부호)은 한 묶음으로 정규화하고, 묶음에서 나온 문자는 모두 묶음 전체의 원문 구간을 가리킨다."""
    cuts = [0]
    for index in range(1, len(text)):
        head, char = text[cuts[-1] : index], text[index]
        if _starts_fresh(char) and _nfc(head + char) == _nfc(head) + _nfc(char):
            cuts.append(index)
    cuts.append(len(text))
    chunks: list[str] = []
    spans: list[_Span] = []
    for start, end in itertools.pairwise(cuts):
        chunk = _nfc(text[start:end])
        chunks.append(chunk)
        spans.extend([(start, end)] * len(chunk))
    return "".join(chunks), spans


def _collapse_whitespace(text: str, spans: list[_Span]) -> tuple[str, list[_Span]]:
    """이어진 공백을 한 칸으로 줄인 글과 그 문자마다의 원문 구간. 줄인 한 칸은 이어진 공백의 첫 칸 구간을 가리킨다 — 인용은
    앞뒤 공백을 걷고 찾으므로 찾은 자리의 양 끝은 공백이 아니고, 안쪽 공백의 구간은 쓰이지 않는다."""
    chars: list[str] = []
    collapsed: list[_Span] = []
    for char, span in zip(text, spans, strict=True):
        if char.isspace():
            if chars and chars[-1] == " ":
                continue
            char = " "
        chars.append(char)
        collapsed.append(span)
    return "".join(chars), collapsed


def locate_quote(text: str, quote: str) -> tuple[int, int] | None:
    """`quote` 가 `text` 안에 있는 원문 구간(시작, 끝). NFC 정규화한 두 글에서 그대로 찾고, 없으면 두 글의 이어진 공백을 한
    칸으로 줄여(인용은 앞뒤 공백도 걷어) 다시 찾는다. 정규화로 길이가 바뀌어도 찾은 자리를 원문 위치로 되돌린다. 구간의 해시는
    부르는 쪽이 `text[시작:끝]`(원문 글)로 낸다.

    공백만인 인용은 None 이다 — 거의 모든 글에 띄어쓰기가 있어, 찾아 주면 근거 없는 항목도 인용 검증을 지난다."""
    if not quote.strip():
        return None
    normalized, spans = _nfc_with_spans(text)
    target = _nfc(quote)
    start = normalized.find(target)
    if start < 0:
        normalized, spans = _collapse_whitespace(normalized, spans)
        target = " ".join(target.split())
        start = normalized.find(target) if target else -1
        if start < 0:
            return None
    return spans[start][0], spans[start + len(target) - 1][1]


def verify_quote(manuscript: Manuscript, quote: QuoteOut) -> VerifiedQuote | None:
    """`quote.paragraph` 번 문단에서 `quote.text` 를 `locate_quote` 로 찾아 원문 구간과 그 원문 글의 해시를 낸다. 문단이 없거나
    구절이 그 문단에 없으면(공백만인 인용 포함) None."""
    if not 1 <= quote.paragraph <= len(manuscript.blocks):
        return None
    block = manuscript.blocks[quote.paragraph - 1]
    span = locate_quote(block.text, quote.text)
    if span is None:
        return None
    start, end = span
    return VerifiedQuote(
        block_id=block.block_id, char_start=start, char_end=end, quote_sha256=quote_hash(block.text[start:end])
    )


def _matches(body: str, block_ids: list[uuid.UUID], quote: VerifiedQuote) -> bool:
    if quote.block_id not in block_ids:
        return False
    paragraphs = split_paragraphs(body)
    index = block_ids.index(quote.block_id)
    return index < len(paragraphs) and quote_hash(paragraphs[index][quote.char_start : quote.char_end]) == (
        quote.quote_sha256
    )


async def manuscript_evidence_verified(
    session: AsyncSession,
    item_ids: set[uuid.UUID],
    new_quotes: Mapping[uuid.UUID, tuple[VerifiedQuote, ...]],
    new_revision_id: uuid.UUID,
) -> dict[uuid.UUID, bool]:
    """항목마다 원고 근거 중 하나 이상이 지금 그 개정의 글과 맞는가. 이번 확정의 새 항목은 `new_quotes`(확정 개정 기준)로,
    정본에 있던 항목은 저장된 근거 행으로 본다. 개정이 지워졌으면 맞지 않는 것이다."""
    quotes: dict[uuid.UUID, list[tuple[uuid.UUID, VerifiedQuote]]] = {
        item_id: [(new_revision_id, quote) for quote in new_quotes[item_id]]
        for item_id in item_ids
        if item_id in new_quotes
    }
    stored = (
        await session.execute(
            select(
                NovelBibleEvidence.item_id,
                NovelBibleEvidence.chapter_revision_id,
                NovelBibleEvidence.block_id,
                NovelBibleEvidence.char_start,
                NovelBibleEvidence.char_end,
                NovelBibleEvidence.quote_sha256,
            ).where(
                NovelBibleEvidence.item_id.in_(item_ids - set(new_quotes)),
                NovelBibleEvidence.origin == "manuscript_block",
            )
        )
    ).all()
    for row in stored:
        assert row.chapter_revision_id is not None and row.block_id is not None  # 원고 근거 CHECK 가 보장한다
        assert row.char_start is not None and row.char_end is not None and row.quote_sha256 is not None
        quote = VerifiedQuote(
            block_id=row.block_id, char_start=row.char_start, char_end=row.char_end, quote_sha256=row.quote_sha256
        )
        quotes.setdefault(row.item_id, []).append((row.chapter_revision_id, quote))
    revision_ids = {revision_id for pairs in quotes.values() for revision_id, _ in pairs}
    revisions = {
        row.id: (row.body, list(row.block_ids))
        for row in (
            await session.execute(
                select(NovelChapterRevision.id, NovelChapterRevision.body, NovelChapterRevision.block_ids).where(
                    NovelChapterRevision.id.in_(revision_ids)
                )
            )
        ).all()
    }
    return {
        item_id: any(
            revision_id in revisions and _matches(*revisions[revision_id], quote)
            for revision_id, quote in quotes.get(item_id, [])
        )
        for item_id in item_ids
    }
