"""슬롯이 자기 표 밖에서 읽는 것(`CoreReadView`)의 구현 — 확정 하나에 묶인 원고·장면 구성안 힌트·아는 개체·원작 정본·플레이
사실."""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_facts import fact_rows_statement
from api.chat.memory_knowledge import latest_by_key
from api.db.models.chat import ChatMemoryFact
from api.db.models.novel import (
    NovelChapter,
    NovelChapterRevision,
    NovelCharacter,
    NovelEpisodeOutline,
    NovelSceneBlock,
)
from api.db.models.novel_bible import NovelBibleCommit, NovelBibleEntity
from api.novel_bible.core.contracts import Registry
from api.novel_bible.core.types import (
    CommitRef,
    EntityName,
    Manuscript,
    ManuscriptBlock,
    PlayFact,
    SceneHint,
    SourceCanon,
    SourceCanonRef,
)
from api.novelize.scenes import revision_scene_groups
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
    # 확정 때 소설의 방(확정 행에 남은 것). 그 뒤 방이 지워져도 확정이 읽을 방은 바뀌지 않는다 — 행이 사라졌으면 비어 읽힌다.
    chat_room_id: uuid.UUID | None = None
    # `play_facts` 가 마지막으로 돌려준 행. 작업이 추출 캐시 열쇠에 이 행들의 방·행 id 를 넣는다(`core/jobs.py`).
    served_play_facts: tuple[PlayFact, ...] = field(default=(), init=False)
    # `source_canon` 이 마지막으로 돌려준 원작. 작업이 추출 캐시 열쇠에 그 버전 id·노트 id 를 넣는다(`core/jobs.py`).
    served_source_canon: SourceCanon | None = field(default=None, init=False)

    async def manuscript(self) -> Manuscript:
        revision = await self.session.get(NovelChapterRevision, self.commit.chapter_revision_id)
        assert revision is not None  # 개정이 지워지면 확정 행도 CASCADE 로 사라져 작업을 받지 못한다
        return manuscript_of(revision)

    async def scene_hints(self) -> list[SceneHint]:
        """확정 개정의 장면마다 장면 id·제목·회상 표시·블록. 블록을 장면으로 읽는 규칙과 제목은 소설 생성 쪽 읽기
        (`revision_scene_groups`)를 그대로 쓰고, 회상 표시만 같은 장면 구성안 판에서 더 읽는다(같은 장면 id 가 여러 판에
        있으면 가장 최근 판). 회상 표시가 없는 옛 판의 장면은 회상이 아니다."""
        revision = await self.session.get(NovelChapterRevision, self.commit.chapter_revision_id)
        assert revision is not None  # 개정이 지워지면 확정 행도 CASCADE 로 사라져 작업을 받지 못한다
        groups = await revision_scene_groups(self.session, self.commit.chapter_id, revision.block_ids)
        if not groups:
            return []
        outline_ids = select(NovelSceneBlock.episode_outline_id).where(
            NovelSceneBlock.chapter_id == self.commit.chapter_id, NovelSceneBlock.block_id.in_(revision.block_ids)
        )
        outlines = await self.session.scalars(
            select(NovelEpisodeOutline)
            .where(NovelEpisodeOutline.id.in_(outline_ids))
            .order_by(NovelEpisodeOutline.revision)
        )
        flashback = {scene["id"]: bool(scene.get("flashback")) for outline in outlines.all() for scene in outline.scenes}
        return [
            SceneHint(scene_key=scene_id, title=title, flashback=flashback.get(scene_id, False), block_ids=tuple(blocks))
            for scene_id, title, blocks in groups
        ]

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
        self.served_source_canon = await self.registry.source.load(self.session, self.commit.novel_id, self.source_ref)
        return self.served_source_canon

    async def play_facts(self) -> list[PlayFact] | None:
        """그 방에서 이 화의 끝 메시지까지 접힌 채팅 기억 사실을 키마다 이긴 행 하나로 줄인 것. 읽기(`fact_rows_statement`)와
        키별 최신 규칙(`latest_by_key` — 같은 값을 반증한 앞 행이 뒤의 같은 값 행을 이긴다)은 채팅의 사실 섹션과 같다.

        반증 행도 표시(`disproved`)를 달아 싣는다 — 채팅 사실 섹션도 반증 행을 표지와 함께 싣는다. "플레이에서 그 값이 아니었다"도
        플레이의 사실이라, 소설이 그 값을 쓰면 그 차이가 각색 후보가 된다. 무엇을 싣는지가 채팅 섹션과 다른 곳은 둘이다. 채팅
        섹션은 사용자가 아닌 쪽의 주장을 빼지만(꼬리표를 붙여도 생성 모델이 사실로 굳힌다) 여기서는 주장도 표시(`claimed`)를 달아
        싣는다 — 이 입력은 추출 모델이 차이를 견주는 데만 쓰고, 주장에서 나온 각색 후보는 차단이 아니라 잡음의 대가가 작다. 아는
        사람 거름도 하지 않는다 — 그것은 채팅 턴이 장면 인물에게 무엇을 보여 줄지의 거름이고, 여기서 묻는 것은 플레이에서 무엇이
        그랬나다.

        채팅 기억 스위치(추출·주입·거름 따위)를 보지 않는다. 그 스위치는 채팅 턴이 기억을 쓰고 읽는지를 정할 뿐이고, 이미 쌓인
        행은 스위치와 무관하게 플레이에서 있었던 일이다. 읽는 두 함수도 방·커서·행만 받는다. 방이 없거나 행이 없으면 None 이다."""
        if self.chat_room_id is None:
            return None
        chapter = await self.session.get(NovelChapter, self.commit.chapter_id)
        assert chapter is not None  # 화가 지워지면 확정 행도 CASCADE 로 사라져 작업을 받지 못한다
        cursor = (chapter.end_message_created_at, chapter.end_message_id)
        rows: list[ChatMemoryFact] = list(
            (await self.session.scalars(fact_rows_statement(self.chat_room_id, cursor))).all()
        )
        facts = [
            PlayFact(
                chat_room_id=row.chat_room_id, chat_memory_fact_id=row.id, chat_fact_key=row.fact_key,
                subject=row.subject, object=row.object, attribute=row.attribute, value=row.value,
                claimed=row.truth_status == "claimed", disproved=row.truth_status == "disproved",
            )
            for _, row in latest_by_key(rows)
        ]
        self.served_play_facts = tuple(facts)
        return facts or None


def source_ref_of(commit: NovelBibleCommit) -> SourceCanonRef | None:
    if commit.source_content_version_id is None or commit.source_input_hash is None:
        return None
    return SourceCanonRef(content_version_id=commit.source_content_version_id, input_hash=commit.source_input_hash)
