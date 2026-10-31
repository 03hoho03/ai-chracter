"""근거 인용의 실재 검증 — 인용이 원고 블록 글 안에 그대로 있는지, 저장된 근거(블록·구간·해시)가 지금도 그 개정의 글과
맞는지."""

import hashlib
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


def verify_quote(manuscript: Manuscript, quote: QuoteOut) -> VerifiedQuote | None:
    """`quote.paragraph` 번 문단에서 `quote.text` 를 찾아 구간·해시를 낸다. 문단이 없거나 구절이 그 문단에 없으면 None."""
    if not quote.text or not 1 <= quote.paragraph <= len(manuscript.blocks):
        return None
    block = manuscript.blocks[quote.paragraph - 1]
    start = block.text.find(quote.text)
    if start < 0:
        return None
    return VerifiedQuote(
        block_id=block.block_id, char_start=start, char_end=start + len(quote.text), quote_sha256=quote_hash(quote.text)
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
