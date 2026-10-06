"""소설화 호출의 입력 조립 — 작품 설정, 묶음 생성 프롬프트(원문 구간·직전 화 끝 발췌·설정 노트·지난 화 요약·인물
메모·화 수), 문단 수정 프롬프트.

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
from api.db.models.novel import Novel, NovelBatch, NovelChapter, NovelChapterRevision, NovelCharacter, NovelJob
from api.db.models.story import StoryVersionDetail
from api.novelize.prompts import NovelizePrompt, build_novelize_chapter_prompt, build_novelize_revise_prompt
from api.novelize.episodes import episode_count
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


# 화 수 지시 슬롯의 소설 제목 줄. 소설 제목은 첫 묶음에서만 쓰고, 사용자가 고친 제목이 있으면 쓰지 않는다.
_WRITE_NOVEL_TITLE = "이번에는 소설 제목도 쓴다."
_SKIP_NOVEL_TITLE = "소설 제목은 쓰지 않는다."


@dataclass(frozen=True)
class ChapterInput:
    """묶음 생성·다시 만들기 한 번의 입력. 성공하면 구간 모양(`assistant_count`·`source_hash`)을 묶음과 화 행에 저장한다.
    `episode_count` 는 지시한 화 수(생성은 작업에 실린 값, 다시 만들기는 묶음의 지금 화 수), `writes_novel_title` 은
    이번 출력의 소설 제목을 소설에 쓸지다."""

    prompt: NovelizePrompt
    room_id: uuid.UUID
    assistant_count: int
    source_hash: str
    episode_count: int
    writes_novel_title: bool


class SourceChangedError(Exception):
    """작업을 만든 뒤 원문 구간이 달라졌다(방 삭제, 끝 메시지 삭제, 재생성할 장의 원문 편집). 실패·환불한다."""


async def build_chapter_input(db: AsyncSession, job: NovelJob, novel: Novel) -> ChapterInput:
    """묶음 생성·다시 만들기 작업의 입력을 만든다. 원문을 지금 다시 읽어 작업의 시작·끝 메시지가 그대로 있는지 확인하고,
    다시 만들기면 묶음에 저장된 해시와 비교한다(생성은 요청 때 검사했지만 그 사이에도 원문이 바뀔 수 있다)."""
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

    first_ordinal: int | None = None
    if job.kind == "chapter_regenerate":
        batch = await regenerate_batch(db, job)
        if batch is None or batch.source_hash != source_hash:
            raise SourceChangedError(f"job={job.id} 다시 만들 묶음의 원문이 바뀌었다")
        first_ordinal = await db.scalar(
            select(func.min(NovelChapter.ordinal)).where(NovelChapter.batch_id == batch.id)
        )
        count = int(
            await db.scalar(select(func.count()).select_from(NovelChapter).where(NovelChapter.batch_id == batch.id))
            or 0
        )
    else:
        count = job.episode_count_target or 1
    # 첫 묶음 = 앞에 화가 없다(다시 만들기는 묶음 첫 화가 1화).
    is_first = first_ordinal == 1 if first_ordinal is not None else await next_ordinal(db, novel.id) == 1
    writes_novel_title = is_first and novel.title_edited_at is None

    previous_excerpt = await _previous_excerpt(db, novel.id, before_ordinal=first_ordinal)
    # 작업이 상위 모델이어도 기본 모델(Gemini) 세트를 읽는다 — 모델별 세트에는 소설 장 채널이 없고, 장 지시·등급 규칙은
    # 모델과 무관하게 이 세트의 것이다. 바뀌는 것은 생성 모델뿐이다(`runner.py`).
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
        character_notes=await _character_notes(db, novel.id),
        previous_summaries=await _previous_summaries(db, novel.id, before_ordinal=first_ordinal),
        episode_count=count,
        episode_chars=settings.novelize_episode_target_chars,
        novel_title_rule=_WRITE_NOVEL_TITLE if writes_novel_title else _SKIP_NOVEL_TITLE,
    )
    return ChapterInput(
        prompt=prompt,
        room_id=novel.chat_room_id,
        assistant_count=len(turns),
        source_hash=source_hash,
        episode_count=count,
        writes_novel_title=writes_novel_title,
    )


async def regenerate_batch(db: AsyncSession, job: NovelJob) -> NovelBatch | None:
    """다시 만들기 작업의 대상 묶음. 작업 생성이 `batch_id` 를 싣지만, 그 칸이 생기기 전에 만든 작업은 가리키는 화의
    묶음이다. 묶음이 지워졌으면 None."""
    batch_id = job.batch_id
    if batch_id is None and job.chapter_id is not None:
        batch_id = await db.scalar(select(NovelChapter.batch_id).where(NovelChapter.id == job.chapter_id))
    return await db.get(NovelBatch, batch_id) if batch_id is not None else None


async def _previous_summaries(db: AsyncSession, novel_id: uuid.UUID, *, before_ordinal: int | None) -> str:
    """지난 화 요약 전부를 오래된 순으로 한 줄씩. 다시 만들기면 그 묶음 앞 화까지다. 요약이 없는 화(요약 칸이 생기기
    전 장)는 뺀다. 글자 상한을 넘으면 오래된 줄부터 빼고, 한 줄만 남았는데도 넘으면 그 줄의 뒤쪽만 남긴다 — 가까운 화가
    이어 쓰기에 더 쓸모 있다."""
    query = select(NovelChapter.ordinal, NovelChapter.summary).where(
        NovelChapter.novel_id == novel_id, NovelChapter.summary.is_not(None), NovelChapter.summary != ""
    )
    if before_ordinal is not None:
        query = query.where(NovelChapter.ordinal < before_ordinal)
    lines = [f"{ordinal}화: {summary}" for ordinal, summary in (await db.execute(query.order_by(NovelChapter.ordinal)))]
    limit = settings.novelize_previous_summaries_max_chars
    while len(lines) > 1 and len("\n".join(lines)) > limit:
        lines.pop(0)
    text = "\n".join(lines)
    return text[-limit:] if len(text) > limit else text


async def _character_notes(db: AsyncSession, novel_id: uuid.UUID) -> str:
    """인물 메모 — 메모를 적은 인물만, 만든 순서로 한 줄씩. 별칭이 있으면 이름 뒤 괄호에 붙여 같은 인물임을 알린다."""
    rows = await db.scalars(
        select(NovelCharacter)
        .where(NovelCharacter.novel_id == novel_id, NovelCharacter.memo != "")
        .order_by(NovelCharacter.created_at, NovelCharacter.id)
    )
    lines: list[str] = []
    for character in rows:
        memo = character.memo.strip()
        if not memo:
            continue
        aliases = f"({', '.join(character.aliases)})" if character.aliases else ""
        lines.append(f"{character.name}{aliases}: {memo}")
    return "\n".join(lines)


async def _previous_excerpt(db: AsyncSession, novel_id: uuid.UUID, *, before_ordinal: int | None) -> str:
    """바로 앞 화의 현재 개정 끝 발췌. 생성이면 마지막 화, 다시 만들기면 그 묶음 첫 화 바로 앞 화다. 앞 화가 없으면 빈 값."""
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
