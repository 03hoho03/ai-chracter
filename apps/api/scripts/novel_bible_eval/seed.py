"""명세 한 권을 격리 DB 에 앱이 읽는 행 사슬 그대로 심는다. 반복마다 새로 심어 새 소설이 된다 — 추출 캐시가 소설 단위라 반복끼리
제안을 나눠 갖지 않는다.

- 원작(명세에 있으면): 작가 회원 → 작품 → 발행한 버전 → 캐릭터·스토리 상세 → 작품 버전 단위 키워드 노트(시작설정 없음), 작품의
  지금 발행본이 그 버전이다. 소설의 원작 칸이 그 작품을 가리킨다.
- 플레이(명세에 있으면): 소설 회원이 그 버전으로 논 채팅 방 → 행이 접힌 화마다 요약 스냅숏 하나 → 채팅 기억 사실 행. 소설이 그
  방에서 나온 것으로 잇는다 — 원작 정본 슬롯도 방이 고정한 같은 버전을 읽는다.
- 화: 화 하나짜리 묶음(묶음 번호 = 화 번호 — 탐침 화를 묶음 삭제로 지울 수 있다), 화, 첫 개정. 화 구간 시각은 고정 기준 시각에서
  화 번호 차례로 오른다. 플레이 사실은 화 끝 커서까지 접힌 스냅숏에서 읽히므로, 어느 행이 어느 화부터 보이는지가 명세대로
  정해진다. 메시지 id 는 합성 값이다 — 측정은 채팅 원문을 읽지 않는다.
- 장면 구성안(화에 있으면): 소설의 전체 구성안 한 판 → 그 화의 장면 구성안(장면 id·제목·회상 표시) → 블록마다 장면 행, 그리고 화
  행이 그 장면 구성안을 가리킨다. 정본 기억은 장면 행에서 장면 구성안의 제목·회상 표시를 읽는다. 구간 선택은 심지 않는다 —
  전체 구성안이 FK 없이 가리키기만 하고 정본 기억은 읽지 않는다.

회원은 이메일이 예약 도메인(`.invalid`)이라 실제 주소와 겹치지 않는다."""

import uuid
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_facts import fact_key
from api.db.models import (
    CharacterVersionDetail,
    ChatMemoryFact,
    ChatRoom,
    ChatRoomMemorySnapshot,
    Content,
    ContentType,
    ContentVersion,
    ContentVisibility,
    KeywordNote,
    ModerationStatus,
    Novel,
    NovelBatch,
    NovelChapter,
    NovelEpisodeOutline,
    NovelOutline,
    NovelSceneBlock,
    StoryPromptTemplate,
    StoryVersionDetail,
    User,
)
from api.novelize.blocks import build_revision, fresh_ids

from novel_bible_eval.spec import ChapterSpec, NovelSpec, PlayRow, SceneSpec, SourceSpec

# 측정 회원이 동의한 것으로 치는 약관·처리방침 판. 동의 게이트를 타는 경로를 부르지 않으므로 값은 꼴만 맞으면 된다.
_LEGAL_VERSION = "2026-09-06"
EVAL_EMAIL_DOMAIN = "novel-bible-eval.invalid"
# 화 구간 시각의 기준. n화는 기준 + n시간에 끝나고 그보다 `_CHAPTER_SPAN` 앞에 시작한다.
_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
_CHAPTER_SPAN = timedelta(minutes=50)


@dataclass(frozen=True)
class SeededChapter:
    ordinal: int
    chapter_id: uuid.UUID
    batch_id: uuid.UUID | None  # 묶음 없는 옛 화(사람 라벨용 사본)는 None
    revision_id: uuid.UUID
    block_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class SeededNovel:
    key: str
    novel_id: uuid.UUID
    chapters: tuple[SeededChapter, ...]


def _chapter_end(ordinal: int) -> datetime:
    return _EPOCH + timedelta(hours=ordinal)


def _folded_at(visible_from: int) -> datetime:
    """`visible_from` 화 구간 한가운데 — 앞 화 끝보다 뒤라 앞 화에는 안 보이고, 그 화 시작보다도 뒤라 화 끝이 아니라 화 시작을
    커서로 읽는 잘못이 있으면 그 화에서 빠진다."""
    return _chapter_end(visible_from) - _CHAPTER_SPAN / 2


async def _member(session: AsyncSession, nickname: str) -> User:
    agreed = datetime.now(UTC)
    user = User(
        email=f"eval-{uuid.uuid4()}@{EVAL_EMAIL_DOMAIN}", nickname=nickname, birth_date=date(2000, 1, 1),
        terms_agreed_at=agreed, privacy_agreed_at=agreed, transfer_agreed_at=agreed,
        terms_version=_LEGAL_VERSION, privacy_version=_LEGAL_VERSION, transfer_version=_LEGAL_VERSION,
    )
    session.add(user)
    await session.flush()
    return user


async def _seed_source(session: AsyncSession, spec: SourceSpec) -> tuple[uuid.UUID, uuid.UUID]:
    """(작품 id, 발행한 버전 id). 작품 설정은 스토리면 세계관 설정, 캐릭터면 캐릭터 프롬프트 칸에 둔다 — 앱이 원작 글을 그
    칸에서 읽는다."""
    author = await _member(session, "측정 작가")
    story = spec.kind == "story"
    content = Content(
        creator_user_id=author.id, type=ContentType.STORY if story else ContentType.CHARACTER, hashtags=[],
        visibility=ContentVisibility.PUBLIC, moderation_status=ModerationStatus.NORMAL,
    )
    session.add(content)
    await session.flush()
    version = ContentVersion(
        content_id=content.id, version_number=1, published_at=datetime.now(UTC), detail_description="합성 원작"
    )
    session.add(version)
    await session.flush()
    if story:
        session.add(
            StoryVersionDetail(
                content_version_id=version.id, name=spec.name, one_liner=spec.name,
                prompt_template=StoryPromptTemplate.BASIC, setting_text=spec.setting,
            )
        )
    else:
        session.add(
            CharacterVersionDetail(
                content_version_id=version.id, name=spec.name, one_liner=spec.name, intro="합성 인트로",
                example_dialogues=[], character_prompt=spec.setting,
            )
        )
    session.add_all(
        KeywordNote(
            entity_id=uuid.uuid4(), content_version_id=version.id, info_text=note, trigger_keywords=[spec.name],
            order=order,
        )
        for order, note in enumerate(spec.notes)
    )
    content.current_published_version_id = version.id
    await session.flush()
    return content.id, version.id


async def _seed_play(
    session: AsyncSession, user_id: uuid.UUID, content_id: uuid.UUID, version_id: uuid.UUID, rows: Sequence[PlayRow]
) -> uuid.UUID:
    """방 하나와, 행이 접힌 화마다 스냅숏 하나·그 행들(명세 차례대로). 사실 키는 채팅 기억과 같은 규칙으로 만든다."""
    room = ChatRoom(user_id=user_id, content_id=content_id, content_version_id=version_id)
    session.add(room)
    await session.flush()
    for visible_from in sorted({row.visible_from for row in rows}):
        at, message_id = _folded_at(visible_from), uuid.uuid4()
        snapshot = ChatRoomMemorySnapshot(
            chat_room_id=room.id, cursor_created_at=at, cursor_message_id=message_id, summary_text="합성 요약",
            source="auto",
        )
        session.add(snapshot)
        await session.flush()
        folded = [row for row in rows if row.visible_from == visible_from]
        session.add_all(
            ChatMemoryFact(
                chat_room_id=room.id, snapshot_id=snapshot.id, ordinal=ordinal,
                kind="fact" if row.object is None else "relation", subject=row.subject, object=row.object,
                attribute=row.attribute,
                fact_key=fact_key("fact" if row.object is None else "relation", row.subject, row.object or row.attribute),
                value=row.value, truth_status=row.truth_status, asserted_by=row.asserted_by, importance=3,
                start_created_at=at, start_message_id=message_id, end_created_at=at, end_message_id=message_id,
                start_turn=1, end_turn=1,
            )
            for ordinal, row in enumerate(folded)
        )
        await session.flush()
    return room.id


async def _seed_scenes(
    session: AsyncSession, chapter: NovelChapter, block_ids: Sequence[uuid.UUID], scenes: Sequence[SceneSpec]
) -> None:
    """장면 구성안의 장면은 정본 기억이 읽는 칸(id·제목·회상 표시)만 둔다. 전체 구성안은 소설에 한 판만 두고 화마다 그 판에
    잇는다 — 앱도 한 판의 화마다 장면 구성안을 만든다."""
    outline_id = await session.scalar(select(NovelOutline.id).where(NovelOutline.novel_id == chapter.novel_id).limit(1))
    if outline_id is None:
        outline = NovelOutline(
            novel_id=chapter.novel_id, revision=1, source="generate", selection_id=uuid.uuid4(), episodes=[]
        )
        session.add(outline)
        await session.flush()
        outline_id = outline.id
    planned = [{"id": str(uuid.uuid4()), "title": scene.title, "flashback": scene.flashback} for scene in scenes]
    episode = NovelEpisodeOutline(
        novel_id=chapter.novel_id, outline_id=outline_id, episode_key=uuid.uuid4(), revision=1, source="generate",
        scenes=planned,
    )
    session.add(episode)
    await session.flush()
    chapter.episode_outline_id = episode.id
    starts = [scene.start for scene in scenes]
    session.add_all(
        NovelSceneBlock(
            block_id=block_id, chapter_id=chapter.id, episode_outline_id=episode.id,
            scene_id=planned[bisect_right(starts, number) - 1]["id"],
        )
        for number, block_id in enumerate(block_ids, start=1)
    )
    await session.flush()


async def add_chapter(session: AsyncSession, novel_id: uuid.UUID, ordinal: int, spec: ChapterSpec) -> SeededChapter:
    end = _chapter_end(ordinal)
    segment = {
        "start_message_id": uuid.uuid4(), "start_message_created_at": end - _CHAPTER_SPAN,
        "end_message_id": uuid.uuid4(), "end_message_created_at": end, "assistant_message_count": 1,
        "source_hash": "0" * 64,
    }
    batch = NovelBatch(novel_id=novel_id, ordinal=ordinal, target_episode_count=1, **segment)
    session.add(batch)
    await session.flush()
    chapter = NovelChapter(novel_id=novel_id, ordinal=ordinal, batch_id=batch.id, episode_index=0, **segment)
    session.add(chapter)
    await session.flush()
    revision = build_revision(
        chapter_id=chapter.id, revision_no=1, body=spec.body, source="manual_edit", block_ids=fresh_ids(spec.body)
    )
    session.add(revision)
    await session.flush()
    if spec.scenes is not None:
        await _seed_scenes(session, chapter, revision.block_ids, spec.scenes)
    return SeededChapter(ordinal, chapter.id, batch.id, revision.id, tuple(revision.block_ids))


async def seed_novel(session: AsyncSession, spec: NovelSpec) -> SeededNovel:
    """회원·원작·방·소설·기본 화 전부(flush). 커밋은 호출부가 한다. 원작이 없는 명세면 소설의 원작 칸은 행이 없는 id 라 원작
    입력 없이 확정된다."""
    reader = await _member(session, "측정")
    content_id, room_id = uuid.uuid4(), None
    if spec.source is not None:
        content_id, version_id = await _seed_source(session, spec.source)
        if spec.play:
            room_id = await _seed_play(session, reader.id, content_id, version_id, spec.play)
    character = spec.source is None or spec.source.kind == "character"
    title = "합성 원작" if spec.source is None else spec.source.name
    novel = Novel(
        user_id=reader.id, chat_room_id=room_id, content_id=content_id,
        content_type="character" if character else "story", content_title=title,
        character_name=("합성 인물" if spec.source is None else spec.source.name) if character else None,
    )
    session.add(novel)
    await session.flush()
    chapters = [
        await add_chapter(session, novel.id, ordinal, chapter)
        for ordinal, chapter in enumerate(spec.chapters, start=1)
    ]
    return SeededNovel(spec.key, novel.id, tuple(chapters))
