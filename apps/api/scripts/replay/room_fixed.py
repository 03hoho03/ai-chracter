"""방 고정값 — 측정 드라이버가 방을 만들 때(그리고 다시 기준을 잡을 때마다) DB 에서 읽어 `roomStatic` 줄에 남기고,
리플레이가 실행 때 DB 지금 값과 대조하는 값.

드라이버는 실행 중 작품 버전·생성 모델·대화 프로필을 바꾸지 않는다. 그래서 측정 뒤 이 값들이 바뀌었다면 그 방을
리플레이하면 측정 때와 다른 조건으로 조립하게 된다 — 리플레이는 대조가 어긋나면 거부한다. API 는 작품 버전 id 를
주지 않고 프로필 본문도 방 응답에 없어서 DB 를 직접 읽는다."""

import uuid
from dataclasses import dataclass
from typing import Any, ClassVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.router import InjectedPersona
from api.content.author_macros import resolve_user_name
from api.db.models.chat import ChatRoom
from api.db.models.persona import UserPersona
from api.db.models.story import StartingSetup, StoryVersionDetail


@dataclass(frozen=True)
class RoomFixed:
    """`persona` 는 조립에 쓰이는 프로필 칸 전부다. `pinned_starting_setup_id` 는 방 버전의 시작 설정 물리 행 id —
    드라이버가 자기 DB 와 서버가 같은 DB 인지 볼 때 쓴다(물리 UUID 라 다른 DB 에서 우연히 맞을 수 없다)."""

    # `roomStatic` 줄에 남는 키. 드라이버 기록과 리플레이 읽기가 이 목록 하나를 본다.
    RECORD_KEYS: ClassVar[tuple[str, ...]] = (
        "contentVersionId",
        "startingSetupEntityId",
        "pinnedStartingSetupId",
        "chatModel",
        "personaId",
        "personaName",
        "defaultUserName",
        "userName",
        "persona",
    )

    content_version_id: uuid.UUID
    starting_setup_entity_id: uuid.UUID | None
    pinned_starting_setup_id: uuid.UUID | None
    # 방 칸에 저장된 모델 그대로(None 이 기본 모델). 서버가 그 턴에 실제로 쓴 모델은 프롬프트 덤프에 있다.
    chat_model: str | None
    persona_id: uuid.UUID | None
    persona_name: str | None
    default_user_name: str
    persona: InjectedPersona | None

    @property
    def user_name(self) -> str:
        """`{{user}}` 자리에 들어가는 이름 — 서버의 치환과 같은 함수로 고른다."""
        return resolve_user_name(self.persona_name, self.default_user_name)

    def as_record(self) -> dict[str, Any]:
        persona = self.persona
        return {
            "contentVersionId": str(self.content_version_id),
            "startingSetupEntityId": _str_or_none(self.starting_setup_entity_id),
            "pinnedStartingSetupId": _str_or_none(self.pinned_starting_setup_id),
            "chatModel": self.chat_model,
            "personaId": _str_or_none(self.persona_id),
            "personaName": self.persona_name,
            "defaultUserName": self.default_user_name,
            "userName": self.user_name,
            "persona": None
            if persona is None
            else {"name": persona.name, "gender": persona.gender, "description": persona.description},
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "RoomFixed | None":
        """`roomStatic` 줄에서 다시 읽는다. 이 값을 기록하기 전의 옛 로그면 None — 호출부가 DB 지금 값을 쓰고
        "고정값 기록 없음"을 남긴다."""
        if "contentVersionId" not in record:
            return None
        persona = record.get("persona")
        return cls(
            content_version_id=uuid.UUID(record["contentVersionId"]),
            starting_setup_entity_id=_uuid_or_none(record.get("startingSetupEntityId")),
            pinned_starting_setup_id=_uuid_or_none(record.get("pinnedStartingSetupId")),
            chat_model=record.get("chatModel"),
            persona_id=_uuid_or_none(record.get("personaId")),
            persona_name=record.get("personaName"),
            default_user_name=record.get("defaultUserName") or "",
            persona=None
            if persona is None
            else InjectedPersona(
                name=persona["name"], gender=persona.get("gender"), description=persona["description"]
            ),
        )


def _str_or_none(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None


def _uuid_or_none(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None


async def load_room_fixed(db: AsyncSession, room_id: uuid.UUID) -> RoomFixed | None:
    """방이 없으면 None. 스토리 방만 다룬다 — 작품 기본 이름을 스토리 상세에서 읽는다. 읽기만 하고 세션에 아무것도
    남기지 않는다(리플레이는 받은 세션을 되돌리지 않고 그대로 쓴다)."""
    room = await db.scalar(select(ChatRoom).where(ChatRoom.id == room_id))
    if room is None:
        return None
    detail = await db.scalar(
        select(StoryVersionDetail).where(StoryVersionDetail.content_version_id == room.content_version_id)
    )
    if detail is None:
        raise ValueError(f"대화방 {room_id} 은 스토리 방이 아니다 — 캐릭터 방은 다루지 않는다")
    pinned = None
    if room.starting_setup_entity_id is not None:
        # 서버가 방의 시작 설정을 찾는 규칙과 같다: 방 버전 안에서 entity_id 로.
        pinned = await db.scalar(
            select(StartingSetup.id).where(
                StartingSetup.content_version_id == room.content_version_id,
                StartingSetup.entity_id == room.starting_setup_entity_id,
            )
        )
    persona_row = (
        await db.scalar(select(UserPersona).where(UserPersona.id == room.persona_id))
        if room.persona_id is not None
        else None
    )
    persona = (
        None
        if persona_row is None
        else InjectedPersona(name=persona_row.name, gender=persona_row.gender, description=persona_row.description)
    )
    return RoomFixed(
        content_version_id=room.content_version_id,
        starting_setup_entity_id=room.starting_setup_entity_id,
        pinned_starting_setup_id=pinned,
        chat_model=room.chat_model,
        persona_id=room.persona_id,
        persona_name=persona.name if persona is not None else None,
        default_user_name=detail.default_user_name,
        persona=persona,
    )


def diff_fixed(recorded: RoomFixed, current: RoomFixed) -> list[str]:
    """기록값과 지금 값이 다른 항목을 `"키: 기록 … ≠ 지금 …"` 꼴로. 작품 버전·시작 설정(entity_id)·생성 모델·프로필
    id·`{{user}}` 이름만 본다. 프로필 성별·설명은 리플레이가 기록값으로 조립하므로 대조하지 않는다 — 본문까지 대조하면
    기록을 쓰는지 DB 를 읽는지가 결과로 구분되지 않는다. 시작 설정 물리 행 id 는 같은 DB 확인용이라 여기서 보지 않는다."""
    pairs: list[tuple[str, object, object]] = [
        ("contentVersionId", recorded.content_version_id, current.content_version_id),
        ("startingSetupEntityId", recorded.starting_setup_entity_id, current.starting_setup_entity_id),
        ("chatModel", recorded.chat_model, current.chat_model),
        ("personaId", recorded.persona_id, current.persona_id),
        ("userName", recorded.user_name, current.user_name),
    ]
    return [f"{key}: 기록 {before} ≠ 지금 {after}" for key, before, after in pairs if before != after]
