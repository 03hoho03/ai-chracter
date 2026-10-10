"""소설 장의 원문 — 대화방 메시지 구간을 읽고, 해시하고, 프롬프트에 싣는 원문 줄로 만든다.

장은 원문 사본을 두지 않고 구간의 양 끝 메시지 키(`(created_at, id)`)만 기억한다. 그래서 장을 만들 때마다 방에서 그
구간을 다시 읽고, 그 사이 원문이 바뀌었는지는 해시로 가린다. 메시지 순서는 언제나 `(created_at, id)` 키 순이다 — 같은
시각의 메시지가 있어도 순서가 하나로 정해지고, 방 메시지 인덱스가 이 순서다."""

import hashlib
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_window import MessageKey
from api.chat.prompt_builder import PromptNames, _turn_text
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.novel import NovelChapter

_KEY_ORDER = (ChatMessage.created_at.asc(), ChatMessage.id.asc())


def message_key(message: ChatMessage) -> MessageKey:
    return (message.created_at, message.id)


async def load_segment(
    db: AsyncSession, room_id: uuid.UUID, start_key: MessageKey, end_key: MessageKey
) -> list[ChatMessage]:
    """방의 메시지 중 키가 `start_key` 이상 `end_key` 이하인 것을 키 순으로 읽는다(양 끝 포함)."""
    key = tuple_(ChatMessage.created_at, ChatMessage.id)
    # 비교 오른쪽은 `tuple_` 이 아니라 평범한 튜플이다 — `tuple_` 끼리 비교하면 mypy 가 결과를 bool 로 본다.
    rows = await db.scalars(
        select(ChatMessage)
        .where(ChatMessage.chat_room_id == room_id, key >= start_key, key <= end_key)
        .order_by(*_KEY_ORDER)
    )
    return list(rows.all())


async def load_candidates(
    db: AsyncSession, room_id: uuid.UUID, start_key: MessageKey, max_turns: int
) -> list[ChatMessage]:
    """장 경계 후보 — `start_key` 이상인 메시지를 키 순으로, 모델 응답을 `max_turns` 개 셀 때까지 읽는다. 마지막 응답
    뒤에 붙은 사용자 메시지(아직 응답이 없는 것)는 넣지 않는다. 장의 끝은 모델 응답이어야 하기 때문이다.

    방이 길어도 한 번에 다 읽지 않으려고 키 커서로 조금씩 읽는다(장 하나는 상한 N턴이라 보통 한두 번이면 끝난다)."""
    if max_turns < 1:
        return []
    batch = max_turns * 2 + 2
    picked: list[ChatMessage] = []
    assistants = 0
    cursor: MessageKey | None = None
    key = tuple_(ChatMessage.created_at, ChatMessage.id)
    while True:
        query = select(ChatMessage).where(ChatMessage.chat_room_id == room_id)
        query = query.where(key > cursor) if cursor is not None else query.where(key >= start_key)
        rows = list((await db.scalars(query.order_by(*_KEY_ORDER).limit(batch))).all())
        for message in rows:
            picked.append(message)
            if message.role == ChatMessageRole.ASSISTANT:
                assistants += 1
                if assistants == max_turns:
                    return picked
        if len(rows) < batch:
            break
        cursor = message_key(rows[-1])
    while picked and picked[-1].role == ChatMessageRole.USER:
        picked.pop()
    return picked


async def next_chapter_start(
    db: AsyncSession, room_id: uuid.UUID, last_chapter: NovelChapter | None
) -> ChatMessage | None:
    """다음 장이 시작할 메시지. 첫 장이면 방의 첫 메시지(보통 오프닝), 아니면 마지막 장 끝 키보다 뒤의 첫 메시지다.
    새로 시작할 메시지가 없으면 None.

    "끝 메시지보다 늦은"을 시각만이 아니라 `(created_at, id)` 키로 비교한다 — 끝 메시지와 같은 시각에 들어간 메시지가
    있어도 빠지거나 두 장에 겹치지 않는다. 끝 키는 장 행에 저장해 둔 값이라, 끝 메시지가 지워졌어도 기준이 그대로다.
    방을 초기화하면 옛 메시지가 모두 지워지고 새 오프닝이 그 뒤 시각으로 들어가므로 다음 장은 새 오프닝부터다."""
    query = select(ChatMessage).where(ChatMessage.chat_room_id == room_id)
    if last_chapter is not None:
        end_key = (last_chapter.end_message_created_at, last_chapter.end_message_id)
        query = query.where(tuple_(ChatMessage.created_at, ChatMessage.id) > end_key)
    message: ChatMessage | None = await db.scalar(query.order_by(*_KEY_ORDER).limit(1))
    return message


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

