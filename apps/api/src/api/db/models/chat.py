import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, Numeric, Text, Uuid, false, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class ChatMessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatRoom(Base):
    """Pinned to the content_version it was created against
    (기획 요구: "이미 생성된 대화방은 생성 시점 버전에 고정")."""

    __tablename__ = "chat_rooms"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("contents.id"), nullable=False)
    content_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("content_versions.id"), nullable=False
    )
    starting_setup_entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    turn_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    ending_reached: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    ending_entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    ending_reached_at_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version_auto_upgraded: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 방이 고른 대화 프로필 — **참조**다(스냅샷 아님).
    # NULL이 "선택 없음"이고 그때 생성 프롬프트는 현행과 바이트까지 같다. 프로필을
    # 지우면 호출부가 이 값을 NULL로 먼저 끊는다(`ondelete` 없음).
    persona_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("user_personas.id", name="fk_chat_rooms_persona_id"), nullable=True
    )
    # 사용자가 직접 쓰는 기억 노트. 요약을 만드는 코드는 이 컬럼을 쓰지 않는다 — LLM이 고쳐 쓰지
    # 못하는 칸이라는 약속이 이 분리로만 지켜진다. 방과 함께 사라지고 새 방에 승계하지 않는다.
    memory_note: Mapped[str] = mapped_column(Text, server_default="", nullable=False)
    # 요약 쪽 상태(스냅샷)가 바뀔 때마다 1씩 오르는 방 단위 카운터. 백그라운드 요약 커밋과 사용자
    # 요약 편집은 읽을 때의 값이 그대로일 때만 쓰고, 되감기·초기화·삭제는 무조건 올려 그 사이
    # 진행 중이던 요약을 무효로 만든다. 노트 저장은 올리지 않는다(노트 저장이 요약 편집을 충돌로
    # 만들지 않게).
    memory_version: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    # 메시지 편집·삭제로 요약 스냅샷이 실제로 한 행 이상 지워진 마지막 시각. 기억 패널이 "요약이
    # 되돌아갔다"는 알림을 한 번 띄우는 기준이다. 초기화는 되감기 안내 대상이 아니라 NULL로 둔다.
    memory_rolled_back_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 프로필 삭제의 `UPDATE chat_rooms SET persona_id=NULL WHERE persona_id=…`가 전체
    # 스캔이 되지 않게 한다.
    __table_args__ = (Index("ix_chat_rooms_persona_id", "persona_id"),)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    chat_room_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chat_rooms.id"), nullable=False)
    role: Mapped[ChatMessageRole] = mapped_column(
        Enum(ChatMessageRole, name="chat_message_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 메시지 순서는 이 값 하나로 정한다. `now()`는 트랜잭션 시작 시각이라 한 트랜잭션에 넣은
    # 메시지들이 같은 값을 갖고 순서가 힙의 물리 위치에 맡겨진다 — 문장 실행 시각을 쓴다.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )
    # 상황이미지 매칭 결과의 entity_id. FK 없음 — entity_id는 버전 간
    # 복제돼 유니크가 아니고 형제 컬럼과 같은 다형 참조 관례. 캐릭터 챗 assistant 메시지에만
    # 채워지고 스토리 챗은 항상 NULL.
    image_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


class ChatRoomMemorySnapshot(Base):
    """방의 롤링 요약 한 판. 윈도우 밖으로 접힌 대화를 요약한 텍스트와, 그 요약이 덮는 마지막
    메시지의 키(커서)를 함께 둔다. 방마다 여러 행이 쌓이고 커서가 가장 큰 행이 현재 요약이다.

    커서는 메시지 정렬과 같은 `(created_at, id)` 튜플이다 — `created_at`이 같은 메시지가 있어도
    경계가 한 메시지로 정해진다. `cursor_message_id`에 FK를 걸지 않는다: 커서 이하 메시지를
    지우는 경로(편집·삭제·재생성·초기화·방 삭제·탈퇴)는 같은 트랜잭션에서 이 행부터 지워야 하고,
    그러면 가리킬 메시지가 사라진 행은 남지 않는다.

    `previous_text`는 사용자가 이 행의 요약을 고쳤을 때 고치기 직전 값이고(되돌리기 한 단계),
    `previous_source`는 그 값의 출처다 — AI가 접은 요약을 고쳤다 되돌리면 다시 AI 요약으로 보인다.
    둘은 함께 채워지고 함께 비워진다.
    `source`는 `"auto"`(요약 호출이 만든 행)·`"user"`(사용자가 고친 행)뿐이고 Postgres ENUM이
    아니라 Text다 — 허용값은 이 행을 쓰는 코드와 응답 스키마가 강제한다.

    `relationship()`·`ondelete`는 선언하지 않는다(저장소 규약) — 위 경로들이 이 행을 직접
    지운다.
    """

    __tablename__ = "chat_room_memory_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    chat_room_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chat_rooms.id"), nullable=False)
    cursor_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cursor_message_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    previous_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 현재 요약(커서 최대 행)과 되감기의 "커서 ≥ 지운 메시지 키" 삭제가 전부 이 순서로 찾는다.
    __table_args__ = (
        Index(
            "ix_chat_room_memory_snapshots_room_cursor",
            "chat_room_id",
            "cursor_created_at",
            "cursor_message_id",
        ),
    )


class ChatRoomStat(Base):
    """The chat room's current value for a stat_defs entity_id
    (referenced by entity_id, not id, so it keeps matching across a version switch)."""

    __tablename__ = "chat_room_stats"

    chat_room_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_rooms.id"), primary_key=True
    )
    stat_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    current_value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)


class StoryEndingUnlock(Base):
    """엔딩 컬렉션: accumulates per user+starting_setup,
    never deleted/replaced once a row exists for a given ending."""

    __tablename__ = "story_ending_unlocks"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)
    starting_setup_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    ending_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    first_reached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CharacterImageExposure(Base):
    """이미지 보관함: accumulates per user+character,
    never revoked — not when the message that exposed the image is regenerated, edited or
    deleted, and not on room reset or deletion. No code path deletes these rows; the
    room-scoped state that IS torn down is ChatRoomStat."""

    __tablename__ = "character_image_exposures"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)
    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("contents.id"), primary_key=True)
    image_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    first_exposed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
