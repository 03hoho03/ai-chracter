"""화별 장면 구성안과 구성 흐름 원고의 입력 — 승인한 전체 구성안의 화 하나를 근거로 장면 구성안을 짜고, 승인한 장면 구성안으로 그 화의
원고를 쓴다. 구성 흐름 화의 다시 만들기도 같은 장면 구성안으로 이 모듈의 입력을 쓴다.

**원문은 화의 근거 구간에서만 나온다.** 화 근거는 전체 구성안이 쓴 구간 선택의 include 구간 안에만 있다(구성안 검증이 지킨다). 그래서
근거마다 그것이 든 include 구간을 관문(`source.py`)의 `read_source` 로 통째로 읽어 저장된 해시와 대조한 뒤 근거 양 끝 사이만 잘라
쓴다 — 구간 사이(고르지 않은 대화)는 읽지 않는다. 장면 근거는 화 근거 안에만 있고(편집 검증이 지킨다), 원고·다시 만들기는 장면 근거
구간만 읽는다. 맥락(context)은 지금 승인한 구간 선택의 맥락 구간을 번호 없는 연속성 참고 줄로 따로 싣는다.

**쓸 수 있는가**(요청은 차감 전 거절, 실행은 `source_changed` 실패·환불 — 실패는 모두 `SourceChangedError` 계열이다):
- 승인한 전체 구성안이 있고 그 화 키가 있다. 그 구성안의 근거 include 구간이 지금 승인한 구간 선택에 그대로 있다(구간을 더한 선택은
  막지 않는다 — 포함 비교).
- 장면 구성안이 근거로 삼은 구성안 판에서의 그 화 근거가 지금 승인한 구성안의 그 화 근거와 같다. 다른 화를 고친 구성안은 장면 구성안을
  낡게 하지 않는다.
- 그 화가 아직 원고가 되지 않았다. 원고는 구성안 화 순서대로만 쓴다(앞 화는 모두 원고이고 뒤 화는 아직 원고가 아니어야 한다 — 화 번호가 생성 순서로만 늘기
  때문이다).
- 화 근거가 이미 화가 된 대화와 겹치지 않는다(승인 뒤 옛 흐름으로 이어 쓴 경우), 근거 구간 원문이 고를 때와 같다, 입력 견적이 상한 안이다.

**장면 근거 저장**: 장면 근거는 메시지 id 와 그 `created_at` 을 함께 둔다 — 원고가 된 화의 "이미 쓴 구간"을 화의 첫·끝 사이 통째가
아니라 장면이 쓴 구간으로 잠그는 데(`selection.locked_ranges`) 메시지를 다시 읽지 않고 키를 쓴다."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_window import MessageKey
from api.chat.prompt_builder import load_active_prompt_set
from api.core.config import settings
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.novel import Novel, NovelChapter, NovelEpisodeOutline, NovelOutline
from api.db.models.prompt import PromptSet
from api.llm.chat_models import ChatModelId
from api.novelize.episodes import chapter_max_turns
from api.novelize.inputs import (
    ChapterInput,
    NovelPromptSource,
    SourceChangedError,
    _character_notes,
    _previous_excerpt,
    _previous_summaries,
    _version_id,
    load_novel_prompt_source,
    load_work_setting,
    next_ordinal,
    require_protagonist_name,
)
from api.novelize.outline import InputTooLargeError, SectionLockedError, SelectionMissingError, selection_still_holds
from api.novelize.prompts import (
    NovelizeEpisodeOutlineResult,
    NovelizePrompt,
    build_novelize_chapter_prompt,
    build_novelize_episode_outline_prompt,
)
from api.novelize.schemas import (
    CHAPTER_TITLE_MAX_LENGTH,
    CHARACTER_NAME_MAX_LENGTH,
    EPISODE_OUTLINE_SCENES_MAX_COUNT,
    OUTLINE_GOAL_MAX_LENGTH,
    OUTLINE_SUMMARY_MAX_LENGTH,
    SCENE_CHARACTERS_MAX_COUNT,
    NovelSceneInput,
    NovelSceneOutlineStatus,
)
from api.novelize.selection import (
    hits_locked,
    latest_approved_selection,
    locked_ranges,
    section_key,
    selection_sections,
    stored_basis_key,
)
from api.novelize.source import (
    SourceRange,
    SourceTurn,
    format_context_lines,
    format_turn_lines,
    group_turns,
    message_key,
    novel_prompt_names,
    read_source,
    room_message_keys,
    segment_hash,
)
from api.novelize.text import looks_like_refusal

# 소설 제목 줄 — 화 생성 입력과 같은 글자다(`inputs.py`).
_WRITE_NOVEL_TITLE = "이번에는 소설 제목도 쓴다."
_SKIP_NOVEL_TITLE = "소설 제목은 쓰지 않는다."


class OutlineMissingError(SourceChangedError):
    """승인한 전체 구성안이 없다."""


class EpisodeNotFoundError(SourceChangedError):
    """승인한 전체 구성안에 그 화 키가 없다."""


class OutlineStaleError(SourceChangedError):
    """승인한 전체 구성안이 낡았다(근거 include 구간이 지금 구간 선택에서 빠졌거나 바뀌었다)."""


class EpisodeWrittenError(SourceChangedError):
    """그 화를 이미 원고로 쓴 화가 있다."""


class EpisodeOutOfOrderError(SourceChangedError):
    """구성안에서 그 화보다 앞의 화가 아직 원고가 아니다."""


class EpisodeOutlineMissingError(SourceChangedError):
    """그 화에 승인한 장면 구성안이 없다."""


class EpisodeOutlineStaleError(SourceChangedError):
    """장면 구성안이 근거로 삼은 화 근거가 지금 승인한 구성안의 그 화 근거와 다르다."""


class MalformedScenesError(Exception):
    """모델이 낸 장면 구성안을 쓸 수 없다(장면 수가 범위 밖, 턴 번호가 범위·순서 밖, 빈 제목·내용)."""


class RefusedScenesError(Exception):
    """모델이 장면 구성안 대신 거절·안내문을 냈다."""


class ScenesInvalidError(Exception):
    """사용자가 고친 장면 목록이 규칙을 어긴다. `reason` 은 화면이 문구를 고를 코드다."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class EpisodeRange:
    """화 근거 구간 하나 — 양 끝 키와 그 사이 메시지(키 순)."""

    start: MessageKey
    end: MessageKey
    messages: list[ChatMessage]


@dataclass(frozen=True)
class SceneSpan:
    """장면 구성안 원문 줄의 턴 하나가 가리키는 메시지 — 그 턴이 든 화 근거 구간 순번, 턴의 첫 메시지, 턴의 모델 응답."""

    range_index: int
    first: ChatMessage
    last: ChatMessage


@dataclass(frozen=True)
class EpisodeSource:
    """관문으로 읽어 검사를 마친 화 하나의 원문. `spans[n-1]` 이 원문 줄의 `[턴 n]` 이다."""

    outline: NovelOutline
    episode: dict[str, Any]
    ranges: list[EpisodeRange]
    spans: list[SceneSpan]
    turn_lines: str
    context_lines: str


@dataclass(frozen=True)
class EpisodeOutlineInput:
    prompt: NovelizePrompt
    source: EpisodeSource


def find_episode(outline: NovelOutline, key: uuid.UUID) -> dict[str, Any] | None:
    return next((episode for episode in outline.episodes if episode["key"] == str(key)), None)


async def latest_approved_outline(db: AsyncSession, novel_id: uuid.UUID) -> NovelOutline | None:
    outline: NovelOutline | None = await db.scalar(
        select(NovelOutline)
        .where(NovelOutline.novel_id == novel_id, NovelOutline.approved_at.is_not(None))
        .order_by(NovelOutline.revision.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return outline


async def written_episodes(db: AsyncSession, novel_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """원고가 된 구성안 화 — 화 키 → 그 화. 화는 장면 구성안 리비전을 가리키므로 그 리비전의 화 키로 거슬러 본다."""
    rows = await db.execute(
        select(NovelEpisodeOutline.episode_key, NovelChapter.id)
        .join(NovelEpisodeOutline, NovelEpisodeOutline.id == NovelChapter.episode_outline_id)
        .where(NovelChapter.novel_id == novel_id, NovelEpisodeOutline.novel_id == novel_id)
    )
    return {str(key): chapter_id for key, chapter_id in rows.all()}


async def approved_episode(
    db: AsyncSession, novel_id: uuid.UUID, key: uuid.UUID
) -> tuple[NovelOutline, dict[str, Any]]:
    """지금 승인한 구성안과 그 화. 없으면 `OutlineMissingError`·`EpisodeNotFoundError`."""
    outline = await latest_approved_outline(db, novel_id)
    if outline is None:
        raise OutlineMissingError(f"novel={novel_id} 승인한 구성안이 없다")
    episode = find_episode(outline, key)
    if episode is None:
        raise EpisodeNotFoundError(f"novel={novel_id} 구성안에 화 {key} 가 없다")
    return outline, episode


async def episode_basis_holds(db: AsyncSession, novel_id: uuid.UUID, outline_id: uuid.UUID, key: uuid.UUID) -> bool:
    """구성안 판 `outline_id` 에서 정한 화 `key` 의 근거가 지금도 쓸 수 있는가 — 지금 승인한 구성안이 낡지 않았고, 그 판에도 그 화가
    있으며 근거가 `outline_id` 판의 근거와 같다."""
    return await _basis_holds_in(db, await _usable_approved_outline(db, novel_id), outline_id, key)


async def _usable_approved_outline(db: AsyncSession, novel_id: uuid.UUID) -> NovelOutline | None:
    """지금 승인한 구성안 — 없거나 낡았으면(근거 include 구간이 지금 승인한 구간 선택에 없으면) None."""
    latest = await latest_approved_outline(db, novel_id)
    if latest is None or not await selection_still_holds(db, novel_id, latest.selection_id):
        return None
    return latest


async def _basis_holds_in(
    db: AsyncSession, usable: NovelOutline | None, outline_id: uuid.UUID, key: uuid.UUID
) -> bool:
    """`episode_basis_holds` 의 판정 — `usable` 은 `_usable_approved_outline` 의 결과다."""
    current = None if usable is None else find_episode(usable, key)
    if usable is None or current is None:
        return False
    if outline_id == usable.id:
        return True
    base = await db.get(NovelOutline, outline_id)
    episode = None if base is None else find_episode(base, key)
    return episode is not None and episode["basis"] == current["basis"]


async def episode_progress(
    db: AsyncSession, novel_id: uuid.UUID, keys: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[uuid.UUID | None, NovelSceneOutlineStatus]]:
    """화 키마다 (그 화 키를 원고로 쓴 화, 장면 구성안 상태). 상태는 그 화의 가장 최근 장면 구성안 판으로 정한다 — 없으면 none, 낡았으면
    (`episode_basis_holds` 와 같은 판정) stale, 아니면 승인 여부. 화 수만큼 따로 조회하지 않게 소설 단위로 한 번에 읽는다."""
    rows = await db.scalars(
        select(NovelEpisodeOutline)
        .distinct(NovelEpisodeOutline.episode_key)
        .where(NovelEpisodeOutline.novel_id == novel_id, NovelEpisodeOutline.episode_key.in_(keys))
        .order_by(NovelEpisodeOutline.episode_key, NovelEpisodeOutline.revision.desc())
        .execution_options(populate_existing=True)
    )
    latest = {row.episode_key: row for row in rows.all()}
    usable = await _usable_approved_outline(db, novel_id)
    written = await written_episodes(db, novel_id)
    progress: dict[uuid.UUID, tuple[uuid.UUID | None, NovelSceneOutlineStatus]] = {}
    for key in keys:
        row = latest.get(key)
        status: NovelSceneOutlineStatus
        if row is None:
            status = "none"
        elif not await _basis_holds_in(db, usable, row.outline_id, key):
            status = "stale"
        else:
            status = "draft" if row.approved_at is None else "approved"
        progress[key] = (written.get(str(key)), status)
    return progress


async def _require_usable_episode(
    db: AsyncSession, novel: Novel, key: uuid.UUID
) -> tuple[NovelOutline, dict[str, Any]]:
    """지금 승인한 구성안의 그 화 — 구성안이 낡지 않았고 그 화가 아직 원고가 아니어야 한다."""
    outline, episode = await approved_episode(db, novel.id, key)
    if not await selection_still_holds(db, novel.id, outline.selection_id):
        raise OutlineStaleError(f"novel={novel.id} 승인한 구성안이 낡았다")
    if str(key) in await written_episodes(db, novel.id):
        raise EpisodeWrittenError(f"novel={novel.id} 화 {key} 는 이미 원고가 됐다")
    return outline, episode


def _stored_basis(first: ChatMessage, last: ChatMessage) -> dict[str, str]:
    return {
        "start_message_id": str(first.id),
        "start_message_created_at": first.created_at.isoformat(),
        "end_message_id": str(last.id),
        "end_message_created_at": last.created_at.isoformat(),
    }


async def _context_lines(db: AsyncSession, novel: Novel, room_id: uuid.UUID, chat_set: PromptSet) -> str:
    """지금 승인한 구간 선택의 맥락 구간 원문 줄. 구간마다 저장된 해시와 대조한다(다르면 `SourceChangedError`)."""
    selection = await latest_approved_selection(db, novel.id)
    if selection is None:
        raise SelectionMissingError(f"novel={novel.id} 승인한 구간 선택이 없다")
    blocks: list[Sequence[ChatMessage]] = []
    for row in await selection_sections(db, selection.id):
        if row.mode != "context":
            continue
        messages = await read_source(db, room_id, [SourceRange(*section_key(row))])
        if segment_hash(messages) != row.source_hash:
            raise SourceChangedError(f"novel={novel.id} 맥락 구간 {row.id} 의 원문이 바뀌었다")
        blocks.append(messages)
    return format_context_lines(blocks, **_line_labels(novel, chat_set))


async def check_context_sections(db: AsyncSession, novel: Novel, room_id: uuid.UUID) -> None:
    """지금 승인한 구간 선택의 맥락 구간 원문이 고를 때와 같은지 본다(다르면 `SourceChangedError`) — 맥락을 싣는 요청이 차감 전에
    부른다. 실행이 같은 검사로 실패·환불만 되풀이하지 않게."""
    chat_set, _ = await load_active_prompt_set(db, lane=novel.content_type)
    await _context_lines(db, novel, room_id, chat_set)


def _line_labels(novel: Novel, chat_set: PromptSet) -> dict[str, Any]:
    """원문 줄의 이름·라벨 — 대화가 쓰던 라벨이라 채팅 세트에서 읽는다(화 생성 입력과 같다)."""
    return {
        "names": novel_prompt_names(protagonist_name=novel.protagonist_name or "", character_name=novel.character_name),
        "user_label": chat_set.user_label,
        "assistant_label": chat_set.story_assistant_label
        if novel.content_type == "story"
        else chat_set.character_assistant_label,
    }


async def _episode_ranges(
    db: AsyncSession, novel: Novel, room_id: uuid.UUID, outline: NovelOutline, episode: dict[str, Any], *, verify: bool
) -> list[EpisodeRange]:
    """화 근거 구간들을 그것이 든 include 구간째 관문으로 읽어 근거 양 끝 사이만 잘라 돌려준다. `verify` 면 include 구간 해시를
    대조하고 근거가 이미 화가 된 대화와 겹치지 않는지 본다."""
    rows = [row for row in await selection_sections(db, outline.selection_id) if row.mode == "include"]
    ids = {uuid.UUID(b[end]) for b in episode["basis"] for end in ("start_message_id", "end_message_id")}
    keys = await room_message_keys(db, room_id, ids)
    if len(keys) != len(ids):
        raise SourceChangedError(f"novel={novel.id} 화 근거의 메시지가 사라졌다")
    bounds = [(keys[uuid.UUID(b["start_message_id"])], keys[uuid.UUID(b["end_message_id"])]) for b in episode["basis"]]
    if verify and hits_locked([("include", start, end) for start, end in bounds], await locked_ranges(db, novel.id)):
        raise SectionLockedError(f"novel={novel.id} 화 근거가 이미 화가 됐다")
    read: dict[uuid.UUID, list[ChatMessage]] = {}
    ranges: list[EpisodeRange] = []
    for start, end in bounds:
        row = next((r for r in rows if section_key(r)[0] <= start and end <= section_key(r)[1]), None)
        if row is None:
            raise SourceChangedError(f"novel={novel.id} 화 근거가 include 구간 밖이다")
        if row.id not in read:
            read[row.id] = await read_source(db, room_id, [SourceRange(*section_key(row))])
            if verify and segment_hash(read[row.id]) != row.source_hash:
                raise SourceChangedError(f"novel={novel.id} 구간 {row.id} 의 원문이 바뀌었다")
        ranges.append(EpisodeRange(start, end, [m for m in read[row.id] if start <= message_key(m) <= end]))
    return ranges


def _spans(ranges: Sequence[EpisodeRange]) -> tuple[list[SourceTurn], list[SceneSpan]]:
    """턴은 근거 구간마다 묶는다 — 이어 붙여 묶으면 앞 구간 끝의 응답 없는 사용자 말이 다음 구간 첫 응답과 한 턴이 된다."""
    turns: list[SourceTurn] = []
    spans: list[SceneSpan] = []
    for index, episode_range in enumerate(ranges):
        for turn in group_turns(episode_range.messages):
            turns.append(turn)
            spans.append(SceneSpan(index, turn.users[0] if turn.users else turn.assistant, turn.assistant))
    return turns, spans


async def load_episode_source(
    db: AsyncSession, novel: Novel, outline: NovelOutline, episode: dict[str, Any], chat_set: PromptSet
) -> EpisodeSource:
    """화 하나의 원문을 관문으로 읽어 검사하고 원문 줄을 만든다(모듈 docstring 의 쓸 수 있는가 중 원문 쪽)."""
    if novel.chat_room_id is None:
        raise SelectionMissingError(f"novel={novel.id} 방이 없다")
    ranges = await _episode_ranges(db, novel, novel.chat_room_id, outline, episode, verify=True)
    turns, spans = _spans(ranges)
    if not turns:
        raise SourceChangedError(f"novel={novel.id} 화 근거에 모델 응답이 없다")
    labels = _line_labels(novel, chat_set)
    turn_lines = format_turn_lines(turns, **labels)
    context_lines = await _context_lines(db, novel, novel.chat_room_id, chat_set)
    estimated = len(turn_lines) + len(context_lines)
    if estimated > settings.novelize_outline_max_input_tokens:
        raise InputTooLargeError(estimated, settings.novelize_outline_max_input_tokens)
    return EpisodeSource(outline, episode, ranges, spans, turn_lines, context_lines)


async def load_scene_outline_source(
    db: AsyncSession, novel: Novel, key: uuid.UUID, *, outline_id: uuid.UUID | None
) -> EpisodeSource:
    """장면 구성안의 원문. `outline_id` 는 작업이 값을 치른 구성안 판이고(요청 때는 None — 지금 승인한 판), 그 판의 그 화 근거가 지금도
    쓸 수 있어야 한다."""
    outline, episode = await _require_usable_episode(db, novel, key)
    if outline_id is not None and outline_id != outline.id:
        if not await episode_basis_holds(db, novel.id, outline_id, key):
            raise OutlineStaleError(f"novel={novel.id} 화 {key} 의 근거가 바뀌었다")
        outline = await db.get_one(NovelOutline, outline_id)
        episode = find_episode(outline, key) or episode
    chat_set, _ = await load_active_prompt_set(db, lane=novel.content_type)
    return await load_episode_source(db, novel, outline, episode, chat_set)


def _episode_outline_text(episode: dict[str, Any]) -> str:
    lines = [f"제목: {episode['title']}", f"줄거리: {episode['summary']}"]
    if episode.get("goal"):
        lines.append(f"목표: {episode['goal']}")
    return "\n".join(lines)


async def build_episode_outline_input(
    db: AsyncSession, novel: Novel, key: uuid.UUID, *, outline_id: uuid.UUID, model: ChatModelId
) -> EpisodeOutlineInput:
    """장면 구성안 작업 실행의 입력 — 그 화 근거 원문 줄(1부터 번호), 구성안의 그 화(제목·줄거리·목표), 작품 설정·설정 노트·인물 메모·
    지난 화 요약·연속성 참고."""
    protagonist = require_protagonist_name(novel)
    source = await load_scene_outline_source(db, novel, key, outline_id=outline_id)
    prompt_source = await load_novel_prompt_source(db, novel, model=model)
    prompt = build_novelize_episode_outline_prompt(
        chat_set=prompt_source.chat_set,
        chat_sections=prompt_source.chat_sections,
        sections=prompt_source.sections,
        is_story_chat=novel.content_type == "story",
        work_setting=await load_work_setting(db, novel, await _version_id(db, novel)),
        user_name=protagonist,
        setting_notes=novel.setting_notes,
        episode_outline=_episode_outline_text(source.episode),
        turn_lines=source.turn_lines,
        character_notes=await _character_notes(db, novel.id),
        previous_summaries=await _previous_summaries(db, novel.id, before_ordinal=None),
        context_lines=source.context_lines,
    )
    return EpisodeOutlineInput(prompt=prompt, source=source)


def _fold(spans: Sequence[SceneSpan]) -> list[dict[str, str]]:
    """연속한 턴들을 화 근거 구간마다 하나의 메시지 구간으로 접는다 — 두 구간에 걸친 장면은 구간마다 따로 적혀 구간 사이를 덮지 않는다."""
    folded: list[tuple[ChatMessage, ChatMessage]] = []
    for index, span in enumerate(spans):
        if index > 0 and spans[index - 1].range_index == span.range_index:
            folded[-1] = (folded[-1][0], span.last)
        else:
            folded.append((span.first, span.last))
    return [_stored_basis(first, last) for first, last in folded]


def _characters(names: Sequence[str]) -> list[str]:
    picked: list[str] = []
    for name in names:
        name = name.strip()[:CHARACTER_NAME_MAX_LENGTH]
        if name and name not in picked:
            picked.append(name)
    return picked[:SCENE_CHARACTERS_MAX_COUNT]


def model_scenes(result: NovelizeEpisodeOutlineResult, spans: Sequence[SceneSpan]) -> list[dict[str, Any]]:
    """모델이 낸 장면 구성안을 저장할 장면 목록으로 바꾼다. 장면마다 새 장면 id 를 주고, 턴 번호를 메시지 구간으로 바꾸며, 글은 앞뒤
    공백을 걷고 길이 상한에서 자른다.

    쓸 수 없으면 `MalformedScenesError` — 장면 수가 `[1, 장면 수 상한]` 밖, 턴 번호가 1~턴 수 밖이거나 시작 > 끝, 앞 장면의 끝 턴 이하에서
    시작(겹침·순서 뒤바뀜), 제목·내용이 빔. 턴을 건너뛴 장면 사이는 받는다(이야기 밖 말만 있는 턴은 빼도 된다). 첫·끝 장면의 내용이
    거절·안내문으로 보이면 `RefusedScenesError`."""
    scenes = result.scenes
    if not 1 <= len(scenes) <= EPISODE_OUTLINE_SCENES_MAX_COUNT:
        raise MalformedScenesError(f"장면 수 {len(scenes)} 가 범위 밖이다")
    out: list[dict[str, Any]] = []
    previous_end = 0
    for scene in scenes:
        if not previous_end < scene.start_turn <= scene.end_turn <= len(spans):
            raise MalformedScenesError(f"턴 범위 {scene.start_turn}~{scene.end_turn} 가 맞지 않다")
        title = scene.title.strip()[:CHAPTER_TITLE_MAX_LENGTH]
        summary = scene.summary.strip()[:OUTLINE_SUMMARY_MAX_LENGTH]
        if not title or not summary:
            raise MalformedScenesError("제목이나 내용이 비었다")
        out.append(
            {
                "id": str(uuid.uuid4()),
                "title": title,
                "summary": summary,
                "purpose": scene.purpose.strip()[:OUTLINE_GOAL_MAX_LENGTH],
                "characters": _characters(scene.characters),
                "flashback": scene.flashback,
                "basis": _fold(spans[scene.start_turn - 1 : scene.end_turn]),
            }
        )
        previous_end = scene.end_turn
    if looks_like_refusal([scene["summary"] for scene in out]):
        raise RefusedScenesError("장면 내용이 거절문으로 보인다")
    return out


async def episode_ranges_for_edit(
    db: AsyncSession, novel: Novel, key: uuid.UUID
) -> tuple[NovelOutline, list[EpisodeRange]]:
    """편집 검증에 쓰는 지금 승인한 구성안과 그 화의 근거 구간(해시·잠금은 보지 않는다 — 저장은 무과금이고 원고 요청이 다시 본다)."""
    if novel.chat_room_id is None:
        raise SelectionMissingError(f"novel={novel.id} 방이 없다")
    outline, episode = await approved_episode(db, novel.id, key)
    return outline, await _episode_ranges(db, novel, novel.chat_room_id, outline, episode, verify=False)


async def checked_scenes(
    db: AsyncSession,
    room_id: uuid.UUID,
    ranges: Sequence[EpisodeRange],
    base_ids: set[str],
    scenes: Sequence[NovelSceneInput],
) -> list[dict[str, Any]]:
    """사용자가 고친 장면 목록을 검증해 저장할 꼴로 바꾼다. 어기면 `ScenesInvalidError(reason)`:

    - `unknown_id`: 장면 id 가 기준 리비전에 없거나 두 장면이 같은 id 다(새 장면은 id 를 비워 보내 새 id 를 받는다).
    - `basis_not_found`: 근거의 양 끝 메시지가 이 방에 없다(지워졌다).
    - `basis_outside_episode`: 근거 구간이 그 화의 근거 구간 하나 안에 있지 않거나 시작 > 끝이다 — 다른 화, 맥락 구간, 고르지 않은
      대화는 장면 근거가 될 수 없다.
    - `basis_overlap`: 한 장면 안의 근거가 키 순이 아니거나, 근거가 다른 장면과 겹친다.
    - `basis_splits_turn`: 근거가 턴 경계에서 시작·끝나지 않는다 — 시작은 그 화 근거 구간의 첫 메시지이거나 모델 응답 바로 뒤 메시지,
      끝은 모델 응답이어야 한다(턴을 메시지 단위로 나누면 원고가 턴으로 묶을 때 끝의 사용자 말이 버려진다).

    장면 차례는 자유다(회상 장면을 앞에 둘 수 있다). 화 근거 안에서 장면 근거가 비는 턴은 원고에 쓰지 않는다(장면을 뺀 것이다)."""
    ids: list[str] = []
    for scene in scenes:
        if scene.id is not None and (scene.id not in base_ids or scene.id in ids):
            raise ScenesInvalidError("unknown_id")
        ids.append(scene.id if scene.id is not None else str(uuid.uuid4()))

    wanted = {b.start_message_id for s in scenes for b in s.basis} | {b.end_message_id for s in scenes for b in s.basis}
    found = await room_message_keys(db, room_id, wanted)
    if len(found) != len(wanted):
        raise ScenesInvalidError("basis_not_found")
    all_ranges: list[tuple[MessageKey, MessageKey]] = []
    stored: list[list[dict[str, str]]] = []
    for scene in scenes:
        previous: MessageKey | None = None
        basis: list[dict[str, str]] = []
        for entry in scene.basis:
            start, end = found[entry.start_message_id], found[entry.end_message_id]
            episode_range = next((r for r in ranges if r.start <= start and end <= r.end), None)
            if start > end or episode_range is None:
                raise ScenesInvalidError("basis_outside_episode")
            if previous is not None and start <= previous:
                raise ScenesInvalidError("basis_overlap")
            previous = end
            all_ranges.append((start, end))
            messages = episode_range.messages
            ids_in_range = [message.id for message in messages]
            first, last = ids_in_range.index(entry.start_message_id), ids_in_range.index(entry.end_message_id)
            if messages[last].role != ChatMessageRole.ASSISTANT or (
                first > 0 and messages[first - 1].role != ChatMessageRole.ASSISTANT
            ):
                raise ScenesInvalidError("basis_splits_turn")
            basis.append(_stored_basis(messages[first], messages[last]))
        stored.append(basis)
    all_ranges.sort()
    if any(later[0] <= earlier[1] for earlier, later in pairwise(all_ranges)):
        raise ScenesInvalidError("basis_overlap")
    return [
        {
            "id": scene_id,
            "title": scene.title,
            "summary": scene.summary,
            "purpose": scene.purpose,
            "characters": _characters(scene.characters),
            "flashback": scene.flashback,
            "basis": basis,
        }
        for scene_id, scene, basis in zip(ids, scenes, stored, strict=True)
    ]


async def latest_episode_outline(
    db: AsyncSession, novel_id: uuid.UUID, key: uuid.UUID, *, approved: bool = False
) -> NovelEpisodeOutline | None:
    query = select(NovelEpisodeOutline).where(
        NovelEpisodeOutline.novel_id == novel_id, NovelEpisodeOutline.episode_key == key
    )
    if approved:
        query = query.where(NovelEpisodeOutline.approved_at.is_not(None))
    row: NovelEpisodeOutline | None = await db.scalar(
        query.order_by(NovelEpisodeOutline.revision.desc()).limit(1).execution_options(populate_existing=True)
    )
    return row


# ── 원고 ─────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SceneSource:
    """원고가 쓸 장면들의 원문 — 장면 근거 구간을 키 순으로 읽은 메시지와 턴, 장면 차례대로 (장면 id, 근거 원문 글자 수), 장면 계획."""

    messages: list[ChatMessage]
    turns: list[SourceTurn]
    scenes: list[tuple[str, int]]
    scene_plan: str


async def _basis_turns(
    db: AsyncSession, room_id: uuid.UUID, start: MessageKey, end: MessageKey
) -> tuple[list[ChatMessage], list[SourceTurn]]:
    """근거 구간 하나를 관문으로 읽어 턴으로 묶는다. 원고의 턴 상한 판정(장면 근거)과 구성안 화의 턴 수(화 근거)가 이 한 곳으로 세어,
    화면이 구성안 단계에서 본 턴 수와 원고 요청이 막는 턴 수가 같은 세기가 된다."""
    read = await read_source(db, room_id, [SourceRange(start, end)])
    return read, group_turns(read)


async def episode_turn_counts(
    db: AsyncSession, room_id: uuid.UUID | None, episodes: Sequence[dict[str, Any]]
) -> list[int | None]:
    """구성안 화마다 근거 구간 안의 턴(모델 응답) 수 — 장면 구성안이 그 화 근거를 빠짐없이 덮을 때 원고 턴 상한 판정이 세는 수다. 방이
    없거나 근거 양 끝 메시지 중 하나라도 사라진 화는 셀 수 없어 None 이다(0 으로 세면 쓸 수 있는 화처럼 보인다)."""
    if room_id is None:
        return [None] * len(episodes)
    ids = {uuid.UUID(b[end]) for e in episodes for b in e["basis"] for end in ("start_message_id", "end_message_id")}
    keys = await room_message_keys(db, room_id, ids)
    counts: list[int | None] = []
    for episode in episodes:
        ends = [(uuid.UUID(b["start_message_id"]), uuid.UUID(b["end_message_id"])) for b in episode["basis"]]
        if any(start not in keys or end not in keys for start, end in ends):
            counts.append(None)
            continue
        total = 0
        for start, end in ends:
            total += len((await _basis_turns(db, room_id, keys[start], keys[end]))[1])
        counts.append(total)
    return counts


async def load_scene_source(db: AsyncSession, room_id: uuid.UUID, scenes: Sequence[dict[str, Any]]) -> SceneSource:
    """장면 근거 구간만 관문으로 읽는다. 턴 번호는 근거 구간을 키 순으로 늘어놓고 1부터 세고, 장면 계획은 장면 차례대로 그 번호를 적는다."""
    keyed = sorted((stored_basis_key(basis), index) for index, scene in enumerate(scenes) for basis in scene["basis"])
    messages: list[ChatMessage] = []
    turns: list[SourceTurn] = []
    numbers: dict[int, list[tuple[int, int]]] = {}
    weights = [0] * len(scenes)
    for (start, end), index in keyed:
        read, grouped = await _basis_turns(db, room_id, start, end)
        if not read or message_key(read[0]) != start or message_key(read[-1]) != end:
            raise SourceChangedError("장면 근거의 양 끝 메시지가 사라졌다")
        if grouped:
            numbers.setdefault(index, []).append((len(turns) + 1, len(turns) + len(grouped)))
        messages += read
        turns += grouped
        weights[index] += sum(len(message.content) for message in read)
    plan = []
    for n, scene in enumerate(scenes, start=1):
        head = f"장면 {n}. {scene['title']}" + (" (회상)" if scene.get("flashback") else "")
        spans = ", ".join(f"턴 {a}" if a == b else f"턴 {a}~{b}" for a, b in numbers.get(n - 1, []))
        lines = [head, f"- 근거: {spans}", f"- 일어나는 일: {scene['summary']}"]
        if scene.get("purpose"):
            lines.append(f"- 이 장면의 몫: {scene['purpose']}")
        if scene.get("characters"):
            lines.append(f"- 등장인물: {', '.join(scene['characters'])}")
        plan.append("\n".join(lines))
    return SceneSource(
        messages=messages,
        turns=turns,
        scenes=[(scene["id"], weight) for scene, weight in zip(scenes, weights, strict=True)],
        scene_plan="\n\n".join(plan),
    )


@dataclass(frozen=True)
class OutlineChapterSource:
    """원고 요청·실행이 검사를 마친 원고 입력 재료."""

    episode_outline: NovelEpisodeOutline
    episode: EpisodeSource
    scenes: SceneSource


async def load_outline_chapter_source(
    db: AsyncSession,
    novel: Novel,
    key: uuid.UUID,
    *,
    episode_outline_id: uuid.UUID | None,
) -> OutlineChapterSource:
    """원고의 원문. `episode_outline_id` 는 작업이 값을 치른 장면 구성안 리비전이고(요청 때는 None — 그 화의 지금 승인한 판), 그 판이
    근거로 삼은 화 근거가 지금도 같아야 한다. 구성안 화 순서도 여기서 본다."""
    outline, episode = await _require_usable_episode(db, novel, key)
    # 원고가 된 화는 구성안의 맨 앞부터 이어져야 한다 — 앞 화가 모두 원고이고 뒤 화는 아직 원고가 아니다. 원고가 된 화를 구성안
    # 편집으로 뒤로 옮긴 뒤 앞 화를 쓰면 화 번호(생성 순서)가 구성안 순서와 어긋나 바로잡을 수 없다.
    written = await written_episodes(db, novel.id)
    keys = [episode["key"] for episode in outline.episodes]
    position = keys.index(str(key))
    if any(earlier not in written for earlier in keys[:position]) or any(
        later in written for later in keys[position + 1 :]
    ):
        raise EpisodeOutOfOrderError(f"novel={novel.id} 화 {key} 가 구성안 순서대로가 아니다")
    episode_outline = (
        await latest_episode_outline(db, novel.id, key, approved=True)
        if episode_outline_id is None
        else await db.get(NovelEpisodeOutline, episode_outline_id)
    )
    if episode_outline is None or episode_outline.approved_at is None:
        raise EpisodeOutlineMissingError(f"novel={novel.id} 화 {key} 에 승인한 장면 구성안이 없다")
    if not await episode_basis_holds(db, novel.id, episode_outline.outline_id, key):
        raise EpisodeOutlineStaleError(f"novel={novel.id} 화 {key} 의 장면 구성안이 낡았다")
    chat_set, _ = await load_active_prompt_set(db, lane=novel.content_type)
    source = await load_episode_source(db, novel, outline, episode, chat_set)
    assert novel.chat_room_id is not None  # 원문을 읽었으면 방이 있다
    return OutlineChapterSource(
        episode_outline, source, await load_scene_source(db, novel.chat_room_id, episode_outline.scenes)
    )


def chapter_turn_cap_exceeded(scenes: SceneSource, model: ChatModelId) -> bool:
    """원고 하나가 쓸 턴 수가 그 모델의 턴 상한(작업 시간 상한에서 나온 값)을 넘는가."""
    return len(scenes.turns) > chapter_max_turns(model)


async def _chapter_prompt(
    db: AsyncSession,
    novel: Novel,
    prompt_source: NovelPromptSource,
    scenes: SceneSource,
    context_lines: str,
    *,
    before_ordinal: int | None,
    is_first: bool,
) -> tuple[NovelizePrompt, uuid.UUID | None]:
    protagonist = require_protagonist_name(novel)
    version_id = await _version_id(db, novel)
    writes_title = is_first and novel.title_edited_at is None
    prompt = build_novelize_chapter_prompt(
        chat_set=prompt_source.chat_set,
        chat_sections=prompt_source.chat_sections,
        sections=prompt_source.sections,
        is_story_chat=novel.content_type == "story",
        work_setting=await load_work_setting(db, novel, version_id),
        user_name=protagonist,
        setting_notes=novel.setting_notes,
        previous_excerpt=await _previous_excerpt(db, novel.id, before_ordinal=before_ordinal),
        turn_lines=format_turn_lines(scenes.turns, **_line_labels(novel, prompt_source.chat_set)),
        character_notes=await _character_notes(db, novel.id),
        previous_summaries=await _previous_summaries(db, novel.id, before_ordinal=before_ordinal),
        episode_count=1,
        episode_chars=settings.novelize_episode_target_chars,
        novel_title_rule=_WRITE_NOVEL_TITLE if writes_title else _SKIP_NOVEL_TITLE,
        scene_plan=scenes.scene_plan,
        context_lines=context_lines,
    )
    return prompt, version_id


def _chapter_input(
    prompt: NovelizePrompt,
    room_id: uuid.UUID,
    scenes: SceneSource,
    episode_outline_id: uuid.UUID,
    *,
    is_first: bool,
    novel: Novel,
    version_id: uuid.UUID | None,
) -> ChapterInput:
    return ChapterInput(
        prompt=prompt,
        room_id=room_id,
        assistant_count=len(scenes.turns),
        source_hash=segment_hash(scenes.messages),
        episode_count=1,
        writes_novel_title=is_first and novel.title_edited_at is None,
        content_version_id=version_id,
        episode_outline_id=episode_outline_id,
        scene_weights=tuple(scenes.scenes),
    )


async def build_outline_chapter_input(
    db: AsyncSession, novel: Novel, key: uuid.UUID, *, episode_outline_id: uuid.UUID, model: ChatModelId
) -> ChapterInput:
    """구성 흐름 원고 작업 실행의 입력 — 요청 때와 같은 검사를 다시 하고, 장면이 쓰는 턴과 장면 계획·연속성 참고로 화 하나를 쓰게 한다."""
    prompt_source = await load_novel_prompt_source(db, novel, model=model)
    source = await load_outline_chapter_source(db, novel, key, episode_outline_id=episode_outline_id)
    assert novel.chat_room_id is not None  # 원문을 읽었으면 방이 있다
    is_first = await next_ordinal(db, novel.id) == 1
    prompt, version_id = await _chapter_prompt(
        db, novel, prompt_source, source.scenes, source.episode.context_lines, before_ordinal=None, is_first=is_first
    )
    return _chapter_input(
        prompt,
        novel.chat_room_id,
        source.scenes,
        source.episode_outline.id,
        is_first=is_first,
        novel=novel,
        version_id=version_id,
    )


async def build_outline_regenerate_input(
    db: AsyncSession, novel: Novel, chapter: NovelChapter, *, model: ChatModelId
) -> ChapterInput:
    """구성 흐름 화 다시 만들기의 입력 — 그 화가 쓴 장면 구성안 리비전의 장면 근거를 다시 읽어 화를 만든 때의 해시와 대조하고(다르면
    `SourceChangedError`), 같은 장면 계획으로 그 화를 다시 쓰게 한다. 구성안·선택이 그 뒤 바뀌었어도 막지 않는다 — 이미 쓴 구간은 다시
    고를 수 없어 그 화의 근거는 그대로다."""
    if novel.chat_room_id is None or chapter.episode_outline_id is None:
        raise SourceChangedError(f"chapter={chapter.id} 방이나 장면 구성안이 없다")
    episode_outline = await db.get(NovelEpisodeOutline, chapter.episode_outline_id)
    if episode_outline is None:
        raise SourceChangedError(f"chapter={chapter.id} 장면 구성안이 지워졌다")
    scenes = await load_scene_source(db, novel.chat_room_id, episode_outline.scenes)
    if segment_hash(scenes.messages) != chapter.source_hash:
        raise SourceChangedError(f"chapter={chapter.id} 장면 원문이 바뀌었다")
    prompt_source = await load_novel_prompt_source(db, novel, model=model)
    context_lines = await _context_lines(db, novel, novel.chat_room_id, prompt_source.chat_set)
    is_first = chapter.ordinal == 1
    prompt, version_id = await _chapter_prompt(
        db, novel, prompt_source, scenes, context_lines, before_ordinal=chapter.ordinal, is_first=is_first
    )
    return _chapter_input(
        prompt, novel.chat_room_id, scenes, episode_outline.id, is_first=is_first, novel=novel, version_id=version_id
    )
