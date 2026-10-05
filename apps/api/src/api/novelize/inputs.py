"""소설화 호출의 입력 조립 — 작품 설정, 장 생성 프롬프트(원문 구간·직전 장 끝 발췌·설정 노트), 문단 수정 프롬프트.

모두 읽기만 하고 쓰지 않는다. 작업 실행이 짧은 세션 하나에서 부르고, 세션을 닫은 뒤에 모델을 부른다."""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_window import MessageKey
from api.chat.prompt_builder import load_active_prompt_set
from api.content.media_tags import strip_media_tags
from api.core.config import settings
from api.db.models.character import CharacterVersionDetail
from api.db.models.chat import ChatMessageRole, ChatRoom
from api.db.models.content import Content
from api.db.models.novel import Novel, NovelChapter, NovelChapterRevision, NovelJob
from api.db.models.story import StoryVersionDetail
from api.novelize.prompts import NovelizePrompt, build_novelize_chapter_prompt, build_novelize_revise_prompt
from api.novelize.source import format_turn_lines, group_turns, load_segment, novel_prompt_names, segment_hash
from api.novelize.text import ending_excerpt, split_paragraphs


class ProtagonistNameMissingError(Exception):
    """소설의 주인공 이름 칸이 비어 장을 만들 수 없다. 장 본문은 사용자 쪽 인물을 이름으로 불러야 하는데, 대화 프로필
    이름도 작품 기본 이름도 없으면 칸이 빈 채로 만들어진다. 장 생성 요청은 차감 전에 이것으로 422 를 내고 이름을
    받는다."""


def require_protagonist_name(novel: Novel) -> str:
    name = (novel.protagonist_name or "").strip()
    if not name:
        raise ProtagonistNameMissingError(f"novel={novel.id} 주인공 이름이 없다")
    return name


async def _version_id(db: AsyncSession, novel: Novel) -> uuid.UUID | None:
    """작품 설정을 읽을 버전 — 방이 있으면 그 방이 고정한 버전(대화가 실제로 쓴 설정), 방이 지워졌으면 원작의 지금
    발행본. 원작마저 지워졌거나 발행본이 없으면 None."""
    if novel.chat_room_id is not None:
        version_id = await db.scalar(select(ChatRoom.content_version_id).where(ChatRoom.id == novel.chat_room_id))
        if version_id is not None:
            return version_id
    return await db.scalar(select(Content.current_published_version_id).where(Content.id == novel.content_id))


async def load_work_setting(db: AsyncSession, novel: Novel) -> str:
    """작품 설정 원문. 캐릭터는 `이름: {캐릭터명}` 한 줄 + 캐릭터 프롬프트, 스토리는 세계관 설정 + 빈 줄 + 규칙(빈
    값은 뺀다). 스토리의 대화 응답 지시문·사용자 목표·프롤로그는 넣지 않는다 — 대화용 지시가 많아 소설 문체를 흔들 수
    있어서이고, 넣을지는 스토리 방으로 하는 본 시험에서 다시 본다. 이미지 태그를 지운 뒤 작가 글의 이름 자리를
    소설 주인공 이름으로 바꾼다. 읽을 버전이 없으면 빈 문자열."""
    version_id = await _version_id(db, novel)
    if version_id is None:
        return ""
    if novel.content_type == "story":
        story = await db.get(StoryVersionDetail, version_id)
        parts = [story.setting_text, story.rules] if story is not None else []
        raw = "\n\n".join(part.strip() for part in parts if part and part.strip())
    else:
        character = await db.get(CharacterVersionDetail, version_id)
        raw = f"이름: {character.name}\n{character.character_prompt}" if character is not None else ""
    names = novel_prompt_names(protagonist_name=novel.protagonist_name or "", character_name=novel.character_name)
    return names.expand(strip_media_tags(raw))


async def current_revision(db: AsyncSession, chapter_id: uuid.UUID) -> NovelChapterRevision | None:
    """장의 현재 개정 = 번호가 가장 큰 개정."""
    revision: NovelChapterRevision | None = await db.scalar(
        select(NovelChapterRevision)
        .where(NovelChapterRevision.chapter_id == chapter_id)
        .order_by(NovelChapterRevision.revision_no.desc())
        .limit(1)
    )
    return revision


@dataclass(frozen=True)
class ChapterInput:
    """장 생성·재생성 한 번의 입력. 성공하면 구간 모양(`assistant_count`·`source_hash`)을 장 행에 저장한다."""

    prompt: NovelizePrompt
    room_id: uuid.UUID
    assistant_count: int
    source_hash: str


class SourceChangedError(Exception):
    """작업을 만든 뒤 원문 구간이 달라졌다(방 삭제, 끝 메시지 삭제, 재생성할 장의 원문 편집). 실패·환불한다."""


async def build_chapter_input(db: AsyncSession, job: NovelJob, novel: Novel) -> ChapterInput:
    """장 생성·재생성 작업의 입력을 만든다. 원문을 지금 다시 읽어 작업의 시작·끝 메시지가 그대로 있는지 확인하고,
    재생성이면 장에 저장된 해시와 비교한다(장 생성은 요청 때 검사했지만 그 사이에도 원문이 바뀔 수 있다)."""
    protagonist = require_protagonist_name(novel)
    if (
        novel.chat_room_id is None
        or job.start_message_id is None
        or job.start_message_created_at is None
        or job.end_message_id is None
        or job.end_message_created_at is None
    ):
        raise SourceChangedError(f"job={job.id} 원문 방 또는 구간이 없다")
    start_key: MessageKey = (job.start_message_created_at, job.start_message_id)
    end_key: MessageKey = (job.end_message_created_at, job.end_message_id)
    segment = await load_segment(db, novel.chat_room_id, start_key, end_key)
    if (
        not segment
        or segment[0].id != job.start_message_id
        or segment[-1].id != job.end_message_id
        or segment[-1].role != ChatMessageRole.ASSISTANT
    ):
        raise SourceChangedError(f"job={job.id} 구간의 시작·끝 메시지가 사라졌다")
    source_hash = segment_hash(segment)

    chapter: NovelChapter | None = None
    if job.kind == "chapter_regenerate":
        chapter = await db.get(NovelChapter, job.chapter_id) if job.chapter_id is not None else None
        if chapter is None or chapter.source_hash != source_hash:
            raise SourceChangedError(f"job={job.id} 재생성할 장의 원문이 바뀌었다")

    previous_excerpt = await _previous_excerpt(db, novel.id, before_ordinal=chapter.ordinal if chapter else None)
    prompt_set, sections = await load_active_prompt_set(db, lane=novel.content_type)
    is_story = novel.content_type == "story"
    turns = group_turns(segment)
    names = novel_prompt_names(protagonist_name=protagonist, character_name=novel.character_name)
    assistant_label = prompt_set.story_assistant_label if is_story else prompt_set.character_assistant_label
    prompt = build_novelize_chapter_prompt(
        prompt_set=prompt_set,
        sections=sections,
        is_story_chat=is_story,
        work_setting=await load_work_setting(db, novel),
        user_name=protagonist,
        setting_notes=novel.setting_notes,
        previous_excerpt=previous_excerpt,
        turn_lines=format_turn_lines(
            turns, names=names, user_label=prompt_set.user_label, assistant_label=assistant_label
        ),
    )
    return ChapterInput(
        prompt=prompt, room_id=novel.chat_room_id, assistant_count=len(turns), source_hash=source_hash
    )


async def _previous_excerpt(db: AsyncSession, novel_id: uuid.UUID, *, before_ordinal: int | None) -> str:
    """바로 앞 장의 현재 개정 끝 발췌. 새 장이면 마지막 장, 재생성이면 그 장 바로 앞 장이다. 앞 장이 없으면 빈 값."""
    query = select(NovelChapter.id).where(NovelChapter.novel_id == novel_id)
    if before_ordinal is not None:
        query = query.where(NovelChapter.ordinal < before_ordinal)
    chapter_id = await db.scalar(query.order_by(NovelChapter.ordinal.desc()).limit(1))
    if chapter_id is None:
        return ""
    revision = await current_revision(db, chapter_id)
    return ending_excerpt(revision.body, settings.novelize_previous_excerpt_chars) if revision else ""


@dataclass(frozen=True)
class ReviseInput:
    prompt: NovelizePrompt
    paragraphs: list[str]
    first_index: int
    last_index: int


async def build_revise_input(db: AsyncSession, job: NovelJob, novel: Novel) -> ReviseInput:
    """문단 수정 작업의 입력. 기준 개정 본문을 문단으로 나눠 범위와 함께 싣는다. 방이 지워졌어도 작품 설정은 원작
    발행본에서 읽어 수정할 수 있다."""
    base = await db.get(NovelChapterRevision, job.base_revision_id) if job.base_revision_id is not None else None
    if base is None or job.paragraph_start is None or job.paragraph_end is None:
        raise ValueError(f"job={job.id} 문단 수정의 기준 개정이나 범위가 없다")
    paragraphs = split_paragraphs(base.body)
    _, sections = await load_active_prompt_set(db, lane=novel.content_type)
    prompt = build_novelize_revise_prompt(
        sections=sections,
        is_story_chat=novel.content_type == "story",
        work_setting=await load_work_setting(db, novel),
        setting_notes=novel.setting_notes,
        paragraphs=paragraphs,
        first_index=job.paragraph_start,
        last_index=job.paragraph_end,
        user_request=job.instruction or "",
    )
    return ReviseInput(
        prompt=prompt, paragraphs=paragraphs, first_index=job.paragraph_start, last_index=job.paragraph_end
    )


async def next_ordinal(db: AsyncSession, novel_id: uuid.UUID) -> int:
    return int(await db.scalar(select(func.coalesce(func.max(NovelChapter.ordinal), 0)).where(NovelChapter.novel_id == novel_id)) or 0) + 1
