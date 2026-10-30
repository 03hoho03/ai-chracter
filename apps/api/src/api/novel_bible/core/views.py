"""슬롯이 자기 표 밖에서 읽는 것(`CoreReadView`)의 구현 — 확정 하나에 묶인 원고·아는 개체·원작 정본."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.novel import NovelChapterRevision, NovelCharacter
from api.db.models.novel_bible import NovelBibleCommit, NovelBibleEntity
from api.novel_bible.core.contracts import Registry
from api.novel_bible.core.types import (
    CommitRef,
    EntityName,
    Manuscript,
    ManuscriptBlock,
    SourceCanon,
    SourceCanonRef,
)
from api.novelize.text import split_paragraphs


def manuscript_of(revision: NovelChapterRevision) -> Manuscript:
    paragraphs = split_paragraphs(revision.body)
    blocks = tuple(
        ManuscriptBlock(index=number, block_id=block_id, text=text)
        for number, (block_id, text) in enumerate(zip(revision.block_ids, paragraphs, strict=True), start=1)
    )
    return Manuscript(revision_id=revision.id, blocks=blocks)


@dataclass
class CommitView:
    session: AsyncSession
    registry: Registry
    commit: CommitRef
    source_ref: SourceCanonRef | None

    async def manuscript(self) -> Manuscript:
        revision = await self.session.get(NovelChapterRevision, self.commit.chapter_revision_id)
        assert revision is not None  # 개정이 지워지면 확정 행도 CASCADE 로 사라져 작업을 받지 못한다
        return manuscript_of(revision)

    async def known_entities(self) -> list[EntityName]:
        """정본 기억 개체와 인물 카드의 이름·별칭. 힌트라 추출 캐시 열쇠에 들지 않는다."""
        entities = (
            await self.session.execute(
                select(NovelBibleEntity.kind, NovelBibleEntity.name, NovelBibleEntity.aliases).where(
                    NovelBibleEntity.novel_id == self.commit.novel_id
                )
            )
        ).all()
        cards = (
            await self.session.execute(
                select(NovelCharacter.name, NovelCharacter.aliases).where(
                    NovelCharacter.novel_id == self.commit.novel_id
                )
            )
        ).all()
        names = [EntityName(kind=row.kind, name=row.name, aliases=tuple(row.aliases)) for row in entities]
        names += [EntityName(kind="character", name=row.name, aliases=tuple(row.aliases)) for row in cards]
        return names

    async def source_canon(self) -> SourceCanon | None:
        if self.registry.source is None or self.source_ref is None:
            return None
        return await self.registry.source.load(self.session, self.source_ref)


def source_ref_of(commit: NovelBibleCommit) -> SourceCanonRef | None:
    if commit.source_content_version_id is None or commit.source_input_hash is None:
        return None
    return SourceCanonRef(content_version_id=commit.source_content_version_id, input_hash=commit.source_input_hash)
