"""소설화 원문 관문 — 소설화 코드가 대화방 메시지를 읽는 유일한 곳. 구간을 읽고, 해시하고, 프롬프트에 싣는 원문 줄로 만든다.

사용자가 소설에서 빼기로 한 구간이 모델에 가지 않는다는 약속은 원문을 읽는 곳이 하나일 때만 지킬 수 있다. 그래서 메시지 SELECT 는
이 모듈의 `_room_messages` 한 함수만 만들고, 원문 글을 읽는 공개 함수는 `read_source` 하나다 — 읽을 구간(양 끝 키)을 받아 그
구간들만 읽고 구간 사이는 읽지 않는다. 다른 소설화 모듈은 메시지·기억 표를 직접 건드리지 않는다(구조 테스트가 지킨다).

옛 흐름(마지막 화 끝 다음부터 이어 쓰기)은 구간 선택이 없으므로 "지금 그대로의 연속 구간 하나"로 이 관문을 부른다
(`load_segment`·`load_candidates`). 구간 선택이 있으면 저장된 구간 행이 읽을 구간이다(`section_ranges`).

장은 원문 사본을 두지 않고 구간의 양 끝 메시지 키(`(created_at, id)`)만 기억한다. 그래서 장을 만들 때마다 방에서 그
구간을 다시 읽고, 그 사이 원문이 바뀌었는지는 해시로 가린다. 메시지 순서는 언제나 `(created_at, id)` 키 순이다 — 같은
시각의 메시지가 있어도 순서가 하나로 정해지고, 방 메시지 인덱스가 이 순서다."""

import hashlib
import json
import uuid
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import Select, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_window import MessageKey
from api.chat.prompt_builder import PromptNames, _turn_text
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.novel import NovelChapter, NovelSourceSection, NovelSourceSectionMode

_KEY_ORDER = (ChatMessage.created_at.asc(), ChatMessage.id.asc())


def message_key(message: ChatMessage) -> MessageKey:
    return (message.created_at, message.id)


@dataclass(frozen=True)
class SourceRange:
    """읽을 구간 하나 — 키가 `start` 이상 `end` 이하인 메시지(양 끝 포함). `end` 가 None 이면 방 끝까지다."""

    start: MessageKey
    end: MessageKey | None


def _room_messages(
    room_id: uuid.UUID,
    *,
    from_key: MessageKey | None = None,
    after: MessageKey | None = None,
    through: MessageKey | None = None,
    role: ChatMessageRole | None = None,
    ids: Collection[uuid.UUID] | None = None,
    newest_first: bool = False,
) -> Select[tuple[ChatMessage]]:
    """방의 메시지를 키 순으로 고르는 SELECT — 이 관문에서 메시지 표를 읽는 질의는 모두 이것을 거친다. `from_key` 이상·`after`
    초과·`through` 이하로 키를 자르고, `role` 이면 그 역할만, `ids` 면 그 id 들만 남긴다. `newest_first` 면 키 역순이다."""
    key = tuple_(ChatMessage.created_at, ChatMessage.id)
    # 비교 오른쪽은 `tuple_` 이 아니라 평범한 튜플이다 — `tuple_` 끼리 비교하면 mypy 가 결과를 bool 로 본다.
    query = select(ChatMessage).where(ChatMessage.chat_room_id == room_id)
    if from_key is not None:
        query = query.where(key >= from_key)
    if after is not None:
        query = query.where(key > after)
    if through is not None:
        query = query.where(key <= through)
    if role is not None:
        query = query.where(ChatMessage.role == role)
    if ids is not None:
        query = query.where(ChatMessage.id.in_(ids))
    if newest_first:
        return query.order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
    return query.order_by(*_KEY_ORDER)


async def read_source(
    db: AsyncSession, room_id: uuid.UUID, ranges: Sequence[SourceRange], *, turn_cap: int | None = None
) -> list[ChatMessage]:
    """방 원문을 `ranges` 의 구간들만 넘긴 순서대로 읽어 잇는다. 구간 사이의 메시지는 읽지 않는다.

    `turn_cap` 이 있으면 모델 응답을 구간을 건너 이어 세어 그 수에 닿는 응답에서 멈추고, 끝까지 가도 닿지 않으면 끝에 남은
    응답 없는 사용자 메시지를 뺀다(장의 끝은 모델 응답이어야 한다). 상한이 1 미만이면 빈 목록이다. 상한이 있을 때는 방이 길어도
    한 번에 다 읽지 않으려고 키 커서로 조금씩 읽는다(장 하나는 상한 N턴이라 보통 한두 번이면 끝난다)."""
    if turn_cap is not None and turn_cap < 1:
        return []
    picked: list[ChatMessage] = []
    assistants = 0
    for source_range in ranges:
        if turn_cap is None:
            picked += (await db.scalars(_room_messages(room_id, from_key=source_range.start, through=source_range.end))).all()
            continue
        batch = turn_cap * 2 + 2
        cursor: MessageKey | None = None
        while True:
            query = (
                _room_messages(room_id, after=cursor, through=source_range.end)
                if cursor is not None
                else _room_messages(room_id, from_key=source_range.start, through=source_range.end)
            )
            rows = list((await db.scalars(query.limit(batch))).all())
            for message in rows:
                picked.append(message)
                if message.role == ChatMessageRole.ASSISTANT:
                    assistants += 1
                    if assistants == turn_cap:
                        return picked
            if len(rows) < batch:
                break
            cursor = message_key(rows[-1])
    if turn_cap is not None:
        while picked and picked[-1].role == ChatMessageRole.USER:
            picked.pop()
    return picked


def section_ranges(sections: Iterable[NovelSourceSection], *, mode: NovelSourceSectionMode) -> list[SourceRange]:
    """저장된 구간 선택의 구간 행 중 `mode` 인 것을 키 순의 읽을 구간으로 바꾼다. mode 를 반드시 고르게 한 것은 소설 본문의
    근거(include)와 앞뒤 맥락(context)을 빌더가 서로 다른 자리에 싣게 하려는 것이다 — 한 목록으로 받으면 맥락으로만 보낸 대화가
    본문 근거에 섞인다. 고르지 않은 나머지(exclude)는 행이 없으므로 어느 mode 로도 나오지 않는다."""
    ordered = sorted(
        (s for s in sections if s.mode == mode), key=lambda s: (s.start_message_created_at, s.start_message_id)
    )
    return [
        SourceRange(
            (s.start_message_created_at, s.start_message_id), (s.end_message_created_at, s.end_message_id)
        )
        for s in ordered
    ]


async def load_segment(
    db: AsyncSession, room_id: uuid.UUID, start_key: MessageKey, end_key: MessageKey
) -> list[ChatMessage]:
    """옛 흐름의 구간 읽기 — 방의 메시지 중 키가 `start_key` 이상 `end_key` 이하인 것을 키 순으로(양 끝 포함). 구간 선택이
    없는 묶음은 연속 구간 하나라 관문에 그 구간 하나를 넘긴다."""
    return await read_source(db, room_id, [SourceRange(start_key, end_key)])


async def load_candidates(
    db: AsyncSession, room_id: uuid.UUID, start_key: MessageKey, max_turns: int
) -> list[ChatMessage]:
    """옛 흐름의 장 경계 후보 — `start_key` 이상인 메시지를 키 순으로, 모델 응답을 `max_turns` 개 셀 때까지 읽는다. 마지막
    응답 뒤에 붙은 사용자 메시지(아직 응답이 없는 것)는 넣지 않는다. 장의 끝은 모델 응답이어야 하기 때문이다."""
    return await read_source(db, room_id, [SourceRange(start_key, None)], turn_cap=max_turns)


async def next_chapter_start(
    db: AsyncSession, room_id: uuid.UUID, last_chapter: NovelChapter | None
) -> ChatMessage | None:
    """다음 장이 시작할 메시지. 첫 장이면 방의 첫 메시지(보통 오프닝), 아니면 마지막 장 끝 키보다 뒤의 첫 메시지다.
    새로 시작할 메시지가 없으면 None.

    "끝 메시지보다 늦은"을 시각만이 아니라 `(created_at, id)` 키로 비교한다 — 끝 메시지와 같은 시각에 들어간 메시지가
    있어도 빠지거나 두 장에 겹치지 않는다. 끝 키는 장 행에 저장해 둔 값이라, 끝 메시지가 지워졌어도 기준이 그대로다.
    방을 초기화하면 옛 메시지가 모두 지워지고 새 오프닝이 그 뒤 시각으로 들어가므로 다음 장은 새 오프닝부터다."""
    after = None if last_chapter is None else (last_chapter.end_message_created_at, last_chapter.end_message_id)
    message: ChatMessage | None = await db.scalar(_room_messages(room_id, after=after).limit(1))
    return message


async def room_message_keys(
    db: AsyncSession, room_id: uuid.UUID, message_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, MessageKey]:
    """`message_ids` 중 이 방의 메시지인 것의 키. 다른 방이나 없는 id 는 결과에 없다 — 호출자가 빠진 id 로 소유를 판정한다."""
    if not message_ids:
        return {}
    rows = (await db.scalars(_room_messages(room_id, ids=message_ids))).all()
    return {message.id: message_key(message) for message in rows}


async def last_message_key(db: AsyncSession, room_id: uuid.UUID) -> MessageKey | None:
    """방의 마지막 메시지 키. 메시지가 없으면 None."""
    message: ChatMessage | None = await db.scalar(_room_messages(room_id, newest_first=True).limit(1))
    return None if message is None else message_key(message)


async def first_message_key_after(db: AsyncSession, room_id: uuid.UUID, after: MessageKey | None) -> MessageKey | None:
    """키가 `after` 보다 뒤인 첫 메시지의 키(`after` 가 None 이면 방의 첫 메시지). 없으면 None."""
    message: ChatMessage | None = await db.scalar(_room_messages(room_id, after=after).limit(1))
    return None if message is None else message_key(message)


async def count_turns_from(db: AsyncSession, room_id: uuid.UUID, start_key: MessageKey) -> int:
    """`start_key` 부터 방 끝까지의 턴(AI 응답) 수. 끝에 응답 없이 남은 사용자 메시지는 묶음이 될 수 없어 세지 않는다."""
    replies = _room_messages(room_id, from_key=start_key, role=ChatMessageRole.ASSISTANT).subquery()
    turns = await db.scalar(select(func.count()).select_from(replies))
    return int(turns or 0)


def segment_hash(messages: Sequence[ChatMessage]) -> str:
    """구간 원문의 해시(sha256 hex). 메시지마다 `[역할, 원문]` 을 키 순으로 나열한 JSON 을 해시한다.

    역할을 넣는 것은 같은 글이 화자만 바뀌어도 소설 입력이 달라지기 때문이다. 메시지 id 는 넣지 않는다 — 지키려는
    것은 "같은 입력으로 다시 만든다"이지 같은 행이 아니다. 원문은 이름 치환 전 글자다 — 주인공 이름을 바꾸는 것은
    원문 변경이 아니고, 치환 결과를 넣으면 이름만 바꿔도 재생성이 영구히 막힌다. 이미지 태그도 원문 그대로 넣는다.
    구분자를 고정하는 것은 JSON 모양이 라이브러리 기본값에 따라 바뀌어 같은 원문의 해시가 달라지지 않게 하려는 것이다."""
    payload = json.dumps(
        [[message.role.value, message.content] for message in messages], ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RangeShape:
    """구간 하나의 모양 — 모델 응답 수와 원문 해시(`segment_hash`)."""

    assistant_message_count: int
    source_hash: str


async def range_shape(db: AsyncSession, room_id: uuid.UUID, source_range: SourceRange) -> RangeShape:
    """`source_range` 를 지금 방 원문으로 다시 읽은 모양. 구간 밖은 읽지 않으므로 다른 곳의 원문이 바뀌어도 값이 같다."""
    messages = await read_source(db, room_id, [source_range])
    return RangeShape(
        assistant_message_count=sum(1 for m in messages if m.role == ChatMessageRole.ASSISTANT),
        source_hash=segment_hash(messages),
    )


@dataclass(frozen=True)
class SourceTurn:
    """턴 하나 = 모델 응답 하나와 그 앞의 사용자 메시지들. 구간 첫머리의 오프닝은 사용자 메시지가 없는 턴이다."""

    users: tuple[ChatMessage, ...]
    assistant: ChatMessage


def group_turns(messages: Sequence[ChatMessage]) -> list[SourceTurn]:
    """키 순 메시지를 턴으로 묶는다. 사용자 메시지는 그 뒤에 오는 모델 응답과 같은 턴이고, 끝에 남은 응답 없는 사용자
    메시지는 버린다."""
    turns: list[SourceTurn] = []
    pending: list[ChatMessage] = []
    for message in messages:
        if message.role == ChatMessageRole.USER:
            pending.append(message)
            continue
        turns.append(SourceTurn(users=tuple(pending), assistant=message))
        pending = []
    return turns


def format_turn_lines(
    turns: Sequence[SourceTurn], *, names: PromptNames, user_label: str, assistant_label: str
) -> str:
    """프롬프트의 원문 줄. 메시지마다 첫 줄 앞에 `[턴 n] 라벨: ` 을 붙이고(같은 턴의 메시지는 같은 n, 1부터) 둘째
    줄부터는 그대로 둔다. 줄은 줄바꿈 하나로 잇는다. 장 생성과 장 경계 제안이 같은 함수를 써서 두 호출의 n 이 같은
    턴을 가리킨다.

    본문은 이미지 태그를 지운 뒤 모델 응답 줄만 작가 글 이름(`{{user}}`·`{{char}}`)을 바꾼다. 사용자 줄에 남은
    `{{user}}` 는 사용자가 친 글자라 그대로 둔다(대화 프롬프트와 같은 규칙). `names` 의 사용자 이름은 소설 주인공
    이름이다."""
    lines: list[str] = []
    for n, turn in enumerate(turns, start=1):
        for user in turn.users:
            lines.append(f"[턴 {n}] {user_label}: {_turn_text(user, names, strip_tags=True)}")
        lines.append(f"[턴 {n}] {assistant_label}: {_turn_text(turn.assistant, names, strip_tags=True)}")
    return "\n".join(lines)


def novel_prompt_names(*, protagonist_name: str, character_name: str | None) -> PromptNames:
    """소설 프롬프트의 이름 — 작가 글의 `{{user}}` 를 대화 프로필이 아니라 소설 주인공 이름으로 바꾼다. 주인공 이름은
    소설을 만들 때 대화 프로필 이름으로 미리 채운 칸이라, 사용자가 고치지 않았으면 대화 때와 같은 이름이다. 스토리는
    캐릭터 이름이 없어 `{{char}}` 를 글자 그대로 둔다."""
    return PromptNames(persona_name=protagonist_name, char_name=character_name)

