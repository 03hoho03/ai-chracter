"""소설 전체 구성안 — 입력 조립, 모델 응답을 화 목록으로 바꾸기, 사용자가 고친 화 목록의 검증, 구성안이 낡았는지 판정.

**입력은 지금 승인된 구간 선택에서만 나온다.** 원문은 관문(`source.py`)의 `read_source` 로 구간마다 읽고 구간 사이는 읽지 않는다 —
사용자가 고르지 않은 대화(exclude)는 이 모듈 어디에도 들어오지 않는다. include 구간은 번호 붙은 원문 줄(`[턴 n]`, 구간을 건너 이어
센다)로, 맥락(context) 구간은 번호 없는 연속성 참고 줄로 따로 싣는다. 읽을 때 구간마다 저장된 해시와 다시 대조하고(다르면 원문이
바뀐 것), include 구간이 이미 화가 된 대화와 겹치지 않는지 다시 본다 — 승인한 선택은 고치지 않으므로 승인 뒤에 생긴 화나 원문 변경을
여기서 잡는다. 요청(차감 전)과 실행(모델 호출 전) 두 곳에서 같은 함수를 부른다.

**화 수**: 모델이 정하고 서버가 `[1, 구성안 화 수 상한]` 으로 검증한다. 프롬프트에는 상한과 함께 원문 분량 산식(`episodes.py` 의
`episode_count` 와 같은 글자 × 비율 ÷ 화 목표 길이)으로 본 안내값을 싣는다 — 그 산식은 상한이 아니라 안내값으로만 쓰고, 묶음 하나의
화 수 상한으로 자르지 않는다(구성안은 고른 대화 전체를 나눈다).

**입력 상한**: 원문 줄(include·맥락) 글자 수를 입력 토큰 견적으로 치고 설정 상한을 넘으면 모델을 부르지 않는다. 조용히 잘라 보내지
않는다 — 요청은 차감 전에 "구간을 줄여 달라"로 거절된다.

**낡음**: 구성안은 근거로 삼은 선택 판(`selection_id`)을 기억한다. 그 판의 include 구간이 지금 승인된 선택에 같은 양 끝·include·해시로
모두 있으면 아직 쓸 수 있다(구간을 더한 선택은 낡게 하지 않는다). 하나라도 빠지면 사용자가 그 대화를 빼거나 바꾼 것이라 낡았다. 맥락
구간은 화의 근거가 아니고 다음 단계가 그때의 선택에서 맥락을 다시 읽으므로 이 비교에 넣지 않는다."""

import uuid
from collections.abc import Sequence
from itertools import pairwise
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_window import MessageKey
from api.core.config import settings
from api.db.models.chat import ChatMessageRole
from api.db.models.novel import Novel, NovelSourceSection
from api.llm.chat_models import ChatModelId
from api.novelize.episodes import source_chars
from api.novelize.inputs import (
    SourceChangedError,
    _character_notes,
    _previous_summaries,
    _version_id,
    load_novel_label_set,
    load_novel_prompt_source,
    load_work_setting,
    require_protagonist_name,
)
from api.novelize.prompts import NovelizeOutlineResult, NovelizePrompt, build_novelize_outline_prompt
from api.novelize.schemas import (
    CHAPTER_TITLE_MAX_LENGTH,
    OUTLINE_GOAL_MAX_LENGTH,
    OUTLINE_SUMMARY_MAX_LENGTH,
    NovelOutlineEpisodeInput,
)
from api.novelize.selection import (
    hits_locked,
    latest_approved_selection,
    locked_ranges,
    section_key,
    selection_sections,
)
from api.novelize.source import (
    SourceRange,
    SourceTurn,
    format_context_lines,
    format_turn_lines,
    group_turns,
    novel_prompt_names,
    read_source,
    room_message_keys,
    segment_hash,
)
from api.novelize.text import looks_like_refusal


class SelectionMissingError(SourceChangedError):
    """승인한 구간 선택이 없다(또는 방이 지워져 원문이 없다)."""


class SectionLockedError(SourceChangedError):
    """승인한 선택의 include 구간이 그 뒤에 생긴 화와 겹친다."""


class InputTooLargeError(SourceChangedError):
    """고른 원문의 입력 견적이 상한을 넘는다."""

    def __init__(self, estimated: int, cap: int) -> None:
        super().__init__(f"입력 견적 {estimated} 이 상한 {cap} 을 넘는다")
        self.estimated = estimated
        self.cap = cap


class MalformedOutlineError(Exception):
    """모델이 낸 구성안을 쓸 수 없다(화 수가 범위 밖, 턴 번호가 범위·순서 밖, 빈 제목·줄거리)."""


class RefusedOutlineError(Exception):
    """모델이 구성안 대신 거절·안내문을 냈다."""


class OutlineInvalidError(Exception):
    """사용자가 고친 화 목록이 규칙을 어긴다. `reason` 은 화면이 문구를 고를 코드다."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class TurnSpan:
    """원문 줄의 턴 하나가 가리키는 메시지 — 그 턴이 든 include 구간 순번(키 순), 턴의 첫 메시지(사용자 메시지가 있으면 그 첫 것),
    턴의 모델 응답."""

    section: int
    first_id: uuid.UUID
    last_id: uuid.UUID


@dataclass(frozen=True)
class OutlineSource:
    """관문으로 읽어 검사를 마친 구성안 원문. `spans[n-1]` 이 원문 줄의 `[턴 n]` 이다."""

    novel_id: uuid.UUID
    selection_id: uuid.UUID
    turns: list[SourceTurn]
    spans: list[TurnSpan]
    turn_lines: str
    context_lines: str
    episode_hint: int
    estimated_tokens: int


@dataclass(frozen=True)
class OutlineInput:
    prompt: NovelizePrompt
    source: OutlineSource


def episode_hint(chars: int) -> int:
    """원문 `chars` 글자의 화 수 안내값 — 글자 × 비율 ÷ 화 목표 길이를 반올림(0.5 는 올림)해 1 과 구성안 화 수 상한 사이로 자른다.
    산식은 묶음 생성의 화 수(`episodes.episode_count`)와 같고 그쪽처럼 `Decimal` 로 계산하지만, 묶음 하나의 화 수 상한으로는 자르지
    않는다."""
    raw = Decimal(chars) * Decimal(str(settings.novelize_source_ratio)) / Decimal(settings.novelize_episode_target_chars)
    rounded = int(raw.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return max(1, min(settings.novelize_outline_max_episodes, rounded))


def _include_rows(rows: Sequence[NovelSourceSection]) -> list[NovelSourceSection]:
    return [row for row in rows if row.mode == "include"]


async def load_outline_source(db: AsyncSession, novel: Novel) -> OutlineSource:
    """지금 승인된 선택의 원문을 관문으로 읽어 검사하고 원문 줄을 만든다. 실패는 모두 `SourceChangedError` 계열이다 — 승인 선택 없음
    (`SelectionMissingError`), include 구간이 화와 겹침(`SectionLockedError`), 저장된 해시와 지금 원문이 다름(`SourceChangedError`),
    입력 견적이 상한 초과(`InputTooLargeError`). 요청은 이것들을 차감 전 거절로, 실행은 실패·환불로 바꾼다."""
    selection = await latest_approved_selection(db, novel.id)
    if selection is None or novel.chat_room_id is None:
        raise SelectionMissingError(f"novel={novel.id} 승인한 구간 선택이나 방이 없다")
    room_id = novel.chat_room_id
    rows = await selection_sections(db, selection.id)
    if hits_locked([(row.mode, *section_key(row)) for row in rows], await locked_ranges(db, novel.id)):
        raise SectionLockedError(f"novel={novel.id} include 구간이 이미 화가 됐다")

    include_turns: list[SourceTurn] = []
    spans: list[TurnSpan] = []
    context_messages: list[Any] = []
    include_index = 0
    for row in rows:
        messages = await read_source(db, room_id, [SourceRange(*section_key(row))])
        if segment_hash(messages) != row.source_hash:
            raise SourceChangedError(f"novel={novel.id} 구간 {row.id} 의 원문이 바뀌었다")
        if row.mode == "context":
            context_messages.append(messages)
            continue
        # 턴은 구간마다 묶는다 — 이어 붙여 묶으면 앞 구간 끝의 응답 없는 사용자 말이 다음 구간의 첫 응답과 한 턴이 된다.
        for turn in group_turns(messages):
            include_turns.append(turn)
            first = turn.users[0] if turn.users else turn.assistant
            spans.append(TurnSpan(section=include_index, first_id=first.id, last_id=turn.assistant.id))
        include_index += 1
    if not include_turns:
        raise SourceChangedError(f"novel={novel.id} include 구간에 모델 응답이 없다")

    names = novel_prompt_names(protagonist_name=novel.protagonist_name or "", character_name=novel.character_name)
    label_set = await load_novel_label_set(db)
    is_story = novel.content_type == "story"
    assistant_label = label_set.story_assistant_label if is_story else label_set.character_assistant_label
    turn_lines = format_turn_lines(include_turns, names=names, user_label=label_set.user_label, assistant_label=assistant_label)
    context_lines = format_context_lines(
        context_messages, names=names, user_label=label_set.user_label, assistant_label=assistant_label
    )
    estimated = len(turn_lines) + len(context_lines)
    if estimated > settings.novelize_outline_max_input_tokens:
        raise InputTooLargeError(estimated, settings.novelize_outline_max_input_tokens)
    return OutlineSource(
        novel_id=novel.id,
        selection_id=selection.id,
        turns=include_turns,
        spans=spans,
        turn_lines=turn_lines,
        context_lines=context_lines,
        episode_hint=episode_hint(source_chars(include_turns, names)),
        estimated_tokens=estimated,
    )


async def build_outline_input(db: AsyncSession, novel: Novel, *, model: ChatModelId) -> OutlineInput:
    """작업 실행의 입력 — `load_outline_source` 에 고른 모델의 소설 체인 문안과 작품 설정·설정 노트·인물 메모·지난 화 요약을 더해
    렌더한다. 지난 화 요약은 이미 쓴 화에서 온 것이라 이어지는 구성의 재료로 싣는다(이미 쓴 구간은 고를 수 없다)."""
    protagonist = require_protagonist_name(novel)
    source = await load_outline_source(db, novel)
    prompt_source = await load_novel_prompt_source(db, model=model)
    prompt = build_novelize_outline_prompt(
        label_set=prompt_source.label_set,
        sections=prompt_source.sections,
        is_story_chat=novel.content_type == "story",
        work_setting=await load_work_setting(db, novel, await _version_id(db, novel)),
        user_name=protagonist,
        setting_notes=novel.setting_notes,
        turn_lines=source.turn_lines,
        max_episodes=settings.novelize_outline_max_episodes,
        episode_hint=source.episode_hint,
        character_notes=await _character_notes(db, novel.id),
        previous_summaries=await _previous_summaries(db, novel.id, before_ordinal=None),
        context_lines=source.context_lines,
    )
    return OutlineInput(prompt=prompt, source=source)


def _basis(spans: Sequence[TurnSpan]) -> list[dict[str, str]]:
    """연속한 턴들을 include 구간마다 하나의 메시지 구간으로 접는다 — 두 구간에 걸친 화는 구간마다 따로 적혀, 구간 사이(고르지 않은
    대화)를 덮지 않는다."""
    ranges: list[dict[str, str]] = []
    for index, span in enumerate(spans):
        if index > 0 and spans[index - 1].section == span.section:
            ranges[-1]["end_message_id"] = str(span.last_id)
        else:
            ranges.append({"start_message_id": str(span.first_id), "end_message_id": str(span.last_id)})
    return ranges


def outline_episodes(result: NovelizeOutlineResult, spans: Sequence[TurnSpan]) -> list[dict[str, Any]]:
    """모델이 낸 구성안을 저장할 화 목록으로 바꾼다. 화마다 새 화 키를 주고, 턴 번호를 메시지 구간으로 바꾸며, 글은 앞뒤 공백을 걷고
    길이 상한에서 자른다.

    쓸 수 없으면 `MalformedOutlineError` — 화 수가 `[1, 상한]` 밖, 턴 번호가 1~턴 수 밖이거나 시작 > 끝, 앞 화의 끝 턴 이하에서
    시작(겹침·순서 뒤바뀜), 제목·줄거리가 빔. 턴을 건너뛴 화 사이는 받는다(이야기 밖 말만 있는 턴은 어느 화에도 안 넣어도 된다).
    첫·끝 화의 줄거리가 거절·안내문으로 보이면 `RefusedOutlineError`."""
    episodes = result.episodes
    if not 1 <= len(episodes) <= settings.novelize_outline_max_episodes:
        raise MalformedOutlineError(f"화 수 {len(episodes)} 가 범위 밖이다")
    out: list[dict[str, Any]] = []
    previous_end = 0
    for episode in episodes:
        if not previous_end < episode.start_turn <= episode.end_turn <= len(spans):
            raise MalformedOutlineError(f"턴 범위 {episode.start_turn}~{episode.end_turn} 가 맞지 않다")
        title = episode.title.strip()[:CHAPTER_TITLE_MAX_LENGTH]
        summary = episode.summary.strip()[:OUTLINE_SUMMARY_MAX_LENGTH]
        if not title or not summary:
            raise MalformedOutlineError("제목이나 줄거리가 비었다")
        out.append(
            {
                "key": str(uuid.uuid4()),
                "title": title,
                "summary": summary,
                "goal": episode.goal.strip()[:OUTLINE_GOAL_MAX_LENGTH],
                "basis": _basis(spans[episode.start_turn - 1 : episode.end_turn]),
            }
        )
        previous_end = episode.end_turn
    if looks_like_refusal([episode["summary"] for episode in out]):
        raise RefusedOutlineError("줄거리가 거절문으로 보인다")
    return out


async def selection_still_holds(db: AsyncSession, novel_id: uuid.UUID, selection_id: uuid.UUID) -> bool:
    """`selection_id` 판의 include 구간이 지금 승인된 선택에 같은 양 끝·include·해시로 모두 있는가(모듈 docstring 의 낡음)."""
    current = await latest_approved_selection(db, novel_id)
    if current is None:
        return False
    if current.id == selection_id:
        return True
    present = {(section_key(row), row.source_hash) for row in _include_rows(await selection_sections(db, current.id))}
    return all(
        (section_key(row), row.source_hash) in present
        for row in _include_rows(await selection_sections(db, selection_id))
    )


async def checked_episodes(
    db: AsyncSession,
    room_id: uuid.UUID,
    selection_id: uuid.UUID,
    base_keys: set[str],
    episodes: Sequence[NovelOutlineEpisodeInput],
) -> list[dict[str, Any]]:
    """사용자가 고친 화 목록을 검증해 저장할 꼴로 바꾼다. 어기면 `OutlineInvalidError(reason)`:

    - `too_many_episodes`: 화 수가 구성안 화 수 상한을 넘는다.
    - `unknown_key`: 화 키가 기준 리비전에 없거나 두 화가 같은 키다(새 화는 키를 비워 보내 새 키를 받는다).
    - `basis_not_found`: 근거의 양 끝 메시지가 이 방에 없다(지워졌다).
    - `basis_outside_include`: 근거 구간이 그 구성안이 쓴 선택의 include 구간 하나 안에 있지 않거나 시작 > 끝이다 — 고르지 않은
      대화나 맥락 구간은 화의 근거가 될 수 없다.
    - `basis_overlap`: 한 화 안의 근거가 키 순이 아니거나, 근거가 다른 화와 겹친다.
    - `basis_splits_turn`: 근거가 턴 경계에서 시작·끝나지 않는다 — 시작은 그 include 구간의 첫 메시지이거나 모델 응답 바로 뒤
      메시지, 끝은 모델 응답이어야 한다. 턴(사용자 말과 그 응답)을 메시지 단위로 두 화에 나누면 다음 단계가 턴으로 묶을 때 끝에
      남은 사용자 말이 버려져, 고른 말이 조용히 빠진다. 끝이 응답이므로 화마다 응답이 하나 이상 있다.

    화의 순서는 자유다(회상 화를 앞에 둘 수 있다). 턴 경계는 근거가 든 include 구간을 관문으로 다시 읽어 본다."""
    if len(episodes) > settings.novelize_outline_max_episodes:
        raise OutlineInvalidError("too_many_episodes")
    keys: list[str] = []
    for episode in episodes:
        key = str(episode.key) if episode.key is not None else None
        if key is not None and (key not in base_keys or key in keys):
            raise OutlineInvalidError("unknown_key")
        keys.append(key if key is not None else str(uuid.uuid4()))

    wanted = {r.start_message_id for e in episodes for r in e.basis} | {r.end_message_id for e in episodes for r in e.basis}
    found = await room_message_keys(db, room_id, wanted)
    if len(found) != len(wanted):
        raise OutlineInvalidError("basis_not_found")
    sections = [section_key(row) for row in _include_rows(await selection_sections(db, selection_id))]
    all_ranges: list[tuple[MessageKey, MessageKey]] = []
    section_messages: dict[int, list[Any]] = {}
    for episode in episodes:
        previous: MessageKey | None = None
        for basis in episode.basis:
            start, end = found[basis.start_message_id], found[basis.end_message_id]
            index = next((i for i, (lo, hi) in enumerate(sections) if lo <= start and end <= hi), None)
            if start > end or index is None:
                raise OutlineInvalidError("basis_outside_include")
            if previous is not None and start <= previous:
                raise OutlineInvalidError("basis_overlap")
            previous = end
            all_ranges.append((start, end))
            if index not in section_messages:
                section_messages[index] = await read_source(db, room_id, [SourceRange(*sections[index])])
            ids = [message.id for message in section_messages[index]]
            first, last = ids.index(basis.start_message_id), ids.index(basis.end_message_id)
            messages = section_messages[index]
            if messages[last].role != ChatMessageRole.ASSISTANT or (
                first > 0 and messages[first - 1].role != ChatMessageRole.ASSISTANT
            ):
                raise OutlineInvalidError("basis_splits_turn")
    all_ranges.sort()
    if any(later[0] <= earlier[1] for earlier, later in pairwise(all_ranges)):
        raise OutlineInvalidError("basis_overlap")

    return [
        {
            "key": key,
            "title": episode.title,
            "summary": episode.summary,
            "goal": episode.goal,
            "basis": [
                {"start_message_id": str(b.start_message_id), "end_message_id": str(b.end_message_id)} for b in episode.basis
            ],
        }
        for key, episode in zip(keys, episodes, strict=True)
    ]


def stored_episode_keys(episodes: Sequence[dict[str, Any]]) -> set[str]:
    return {str(episode["key"]) for episode in episodes}

