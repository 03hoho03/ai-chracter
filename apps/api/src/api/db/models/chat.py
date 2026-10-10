import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from api.db.models.moderation import ReportStatus
from api.db.models.payment import _sql_in_list


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
    # 방이 고른 글쓰기 모델의 레지스트리 id(`llm/chat_models.py`). NULL 이 기본 모델(Gemini)이다. 값 제약을 두지 않는다 —
    # 레지스트리에서 내린 모델의 옛 값이 남아도 행이 살아 있어야 하고, 그 값은 턴마다 쓸 수 있는 모델로 다시 판정한다
    # (`llm/model_access.py` 의 `effective_model`). 바꾸는 경로는 `PUT /chat-rooms/{id}/model` 하나다.
    chat_model: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 프로필 삭제의 `UPDATE chat_rooms SET persona_id=NULL WHERE persona_id=…`가 전체
    # 스캔이 되지 않게 한다. Postgres 는 FK 열에 인덱스를 자동으로 만들지 않으므로
    # `user_id`·`content_id` 도 직접 건다. 같은 작품의 내 방들(방 응답·작품 접근 판정)은
    # 두 열을 함께 거르고 내 방 목록·탈퇴는 `user_id` 만 거르므로 앞 열이 `user_id` 인
    # 복합 하나로 둘 다 받는다. 작품 하나의 방 전부를 고치는 버전 일괄 승격은
    # `content_id` 만 거르므로 단일 인덱스를 따로 둔다.
    __table_args__ = (
        Index("ix_chat_rooms_persona_id", "persona_id"),
        Index("ix_chat_rooms_user_id_content_id", "user_id", "content_id"),
        Index("ix_chat_rooms_content_id", "content_id"),
    )


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
    # 이미지 판정 결과의 entity_id — 캐릭터 방이면 상황별 이미지, 스토리 방이면 미디어 북 칸의
    # entity_id 다. assistant 메시지에만 채워진다. FK 없음 — entity_id는 버전 간 복제돼 유니크가
    # 아니고, 방 종류에 따라 가리키는 테이블도 달라 형제 컬럼과 같은 다형 참조 관례를 따른다.
    image_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)

    # 턴마다의 히스토리 로드·방 조회·방 목록의 마지막 메시지가 전부 "한 방의 메시지를 `(created_at, id)` 순으로"
    # 찾는다. 없으면 그 조회마다 플랫폼 전체 메시지를 순차 스캔한다(FK 는 Postgres 에서 인덱스를 만들지 않는다).
    __table_args__ = (Index("ix_chat_messages_chat_room_id_created_at_id", "chat_room_id", "created_at", "id"),)


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


class StoryMediaExposure(Base):
    """스토리 미디어 북 보관함: 사용자 + 스토리별로 대화에 나온 칸을 쌓는다. `CharacterImageExposure`
    와 같은 규칙 — 그 칸을 노출한 메시지를 재생성·편집·삭제해도, 방을 초기화하거나 지워도 행을
    지우지 않는다.

    `cell_entity_id` 는 칸의 entity_id 이고 FK 가 없다 — 칸 행은 버전마다 복제돼 entity_id 가
    유일하지 않고, 버전이 바뀌어도 같은 칸으로 쌓여야 한다."""

    __tablename__ = "story_media_exposures"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)
    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("contents.id"), primary_key=True)
    cell_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    first_exposed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


ChatTurnKind = Literal["send", "edit", "regenerate"]
ChatTurnChargeSource = Literal["free", "clover", "skipped"]


class ChatTurn(Base):
    """턴이 남긴 응답 하나 = 한 행. 그 응답을 만든 글쓰기 모델, 그 턴의 차감, LLM 호출별 토큰 사용량, 그 응답에 귀속된
    스탯 변화·도달한 엔딩을 숫자와 id 로만 남긴다 — 프롬프트·응답 글은 싣지 않는다. 방 턴의 쓰기
    구간이 응답과 같은 커밋에 행을 넣는다(`chat/turn_store.py` 의 `RoomTurnStore` — 어느 경로가 어떤 값을 쓰는지도 거기 있다).

    미리보기 턴은 방 행이 없어 `chat_room_id` 를 채울 수 없으므로 기록하지 않는다.

    - `assistant_message_id` 는 유니크지만 FK 가 없다 — 재생성·편집·메시지 삭제·초기화가 메시지 행을 실제로 지우고,
      배포 겹침 구간의 옛 이미지도 그 경로를 그대로 돈다.
    - `spend_ledger_id` 는 클로버 원장 행 id 의 사본이고 FK 가 없다 — 턴 쓰기가 원장 행에 FK 확인 잠금을 걸지 않게 하고,
      차감의 사용처는 `clover_spend_usages` 가 맡으므로 여기서는 그와 잇는 조인 키로만 쓴다.
    - `turn_number` 는 이 응답이 속한 턴이다. 재생성 행은 대체한 응답 기록의 값을 이어받는다.
    - `llm_calls` 는 `[{callSite, model, promptTokens, cachedTokens, cacheWriteTokens, outputTokens, thoughtsTokens}]`,
      `stat_changes` 는 `{statEntityId: [before, after]}` 다.

    응답이 재생성·수정·메시지 삭제로 지워져도 그 행은 방이 지워지거나 초기화될 때까지 남는다. 그래서 한 방 안에서
    `(chat_room_id, turn_number)` 는 유일하지 않고(수정 뒤 같은 턴 번호가 둘, 재생성 체인은 같은 `stat_changes` 를
    복사한 행이 여럿), `stat_changes` 를 방 단위로 합치면 이중 계산이 된다 — 기록은 메시지 id 로 찾는다.

    방 삭제·탈퇴는 `delete_chat_rooms` 가 방 행보다 먼저 이 행을 지운다(`ON DELETE CASCADE` 가 없다). 초기화도 그 방의
    행을 지운다 — 방 행은 남아 FK 와는 무관하고, 지운 대화의 기록을 남기지 않으려는 것이다. `kind`·`charge_source` 는
    native enum 이 아니라 Text 이고 위 Literal 이 값 범위다."""

    __tablename__ = "chat_turns"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    chat_room_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chat_rooms.id"), nullable=False)
    assistant_message_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    kind: Mapped[ChatTurnKind] = mapped_column(Text, nullable=False)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # 영수증에 찍히는 와이어 id(`gemini`·`sonnet`·`opus` 등) — 방의 `chat_model` 과 달리 그 턴에 실제로 쓴 모델이다.
    chat_model: Mapped[str] = mapped_column(Text, nullable=False)
    charge_source: Mapped[ChatTurnChargeSource] = mapped_column(Text, nullable=False)
    clover_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    spend_ledger_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    shortcut_entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    llm_calls: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    stat_changes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    ending_entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 🔴 `alembic check`는 CHECK 제약을 비교하지 않는다 — 두 CHECK 의 검증은 행위 테스트가 유일하다.
    # 인덱스의 앞 열은 방 삭제·초기화의 DELETE 와 방 DELETE 의 FK 확인이 이 테이블을 방으로 찾기 위한 것이다(Postgres 는
    # FK 열에 인덱스를 만들지 않는다). 뒤 열은 한 방의 기록을 턴 순서로 읽는 조회(턴당 원가 측정)를 받는다.
    __table_args__ = (
        UniqueConstraint("assistant_message_id", name="ux_chat_turns_assistant_message_id"),
        CheckConstraint(f"kind IN ({_sql_in_list(ChatTurnKind)})", name="ck_chat_turns_kind"),
        CheckConstraint(
            f"charge_source IN ({_sql_in_list(ChatTurnChargeSource)})", name="ck_chat_turns_charge_source"
        ),
        Index("ix_chat_turns_chat_room_id_turn_number", "chat_room_id", "turn_number"),
    )


DiscardedResponseKind = Literal["regenerate", "edit"]


class DiscardedResponse(Base):
    """재생성·편집으로 AI 응답이 실제로 지워진 한 번 = 한 행. 응답 품질 불만의 암묵 신호를 SQL로
    세기 위한 기록이라 응답 원문은 저장하지 않는다.

    `discarded_count`는 그 행동이 지운 AI 응답 수다 — 재생성은 항상 1, 편집은 편집한 메시지 뒤에서
    지워진 AI 응답 수. 0개를 지운 행동은 행을 만들지 않으므로 CHECK가 1 이상을 강제한다.

    방 삭제·탈퇴는 이 행을 지우지 않는다(`delete_chat_rooms`의 자식 목록에 없는 것이 의도다).
    방이 사라지면 `chat_room_id`만 `SET NULL`로 비고 행과 `user_id`는 남는다 — 지표가 방 삭제로
    줄면 안 되기 때문이다. `kind`는 native enum이 아니라 Text이고 위 Literal이 값 범위다(값이 늘
    때 마이그레이션 없이 넓히기 위해서다)."""

    __tablename__ = "discarded_responses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    chat_room_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("chat_rooms.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[DiscardedResponseKind] = mapped_column(Text, nullable=False)
    discarded_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 🔴 `alembic check`는 CHECK 제약을 비교하지 않는다 — 검증은 행위 테스트가 유일하다.
    # 집계(일별 재생성 수·사용자별 재생성률)는 테이블 전체를 읽으므로 집계용 인덱스는 두지 않는다.
    # `chat_room_id` 인덱스는 방 DELETE마다 Postgres가 이 테이블에서 그 방을 가리키는 행을 찾아
    # 비우는 조회를 위한 것이다 — 없으면 재생성할 때마다 늘어나는 이 테이블을 방 하나 지울 때마다
    # 처음부터 훑는다.
    __table_args__ = (
        CheckConstraint("discarded_count >= 1", name="ck_discarded_responses_count_positive"),
        Index("ix_discarded_responses_chat_room_id", "chat_room_id"),
    )


ChatMessageReportReason = Literal[
    "inappropriate",
    "minor_safety",
    "hateful",
    "out_of_character",
    "repetitive",
    "broken",
    "other",
]


class ChatMessageReport(Base):
    """AI 응답 신고. 신고 metadata와 대화 사본(증거)의 수명을 분리한 댓글 신고(`CommentReport`)와 같은
    구조다 — 증거는 접수 시 복사해 두고 90일이 지나면 조회에서 빠지며 파기 작업이 칸을 비운다.

    `chat_room_id`·`chat_message_id`는 `SET NULL`이다. 재생성·메시지 삭제·편집·방 초기화·방 삭제가
    신고된 메시지를 지워도 신고와 증거 사본은 남아야 하고, 지우는 쪽이 이 테이블을 몰라도 FK
    위반으로 실패하지 않아야 한다. 그래서 대상 메시지를 가리키는 칸이 NULL일 수 있고, 증거
    칸만으로 무엇이 신고됐는지 읽혀야 한다.

    같은 회원이 같은 메시지를 두 번 신고하면 유니크 제약이 막는다. 이 제약은 Postgres 기본값인
    NULLS DISTINCT여야 한다 — NULLS NOT DISTINCT면 한 회원이 신고한 메시지 둘이 지워져
    `chat_message_id`가 둘 다 NULL이 되는 순간 그 DELETE가 유니크 위반으로 실패한다.

    `reason`은 native enum이 아니라 Text이고 위 Literal이 값 범위다(베타 피드백으로 사유가 바뀌어도
    마이그레이션 없이 넓히기 위해서다). `status`는 작품·댓글 신고와 같은 `report_status` 타입을
    쓴다. 메모 길이 제한은 요청 스키마가 강제한다."""

    __tablename__ = "chat_message_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    reporter_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    chat_room_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("chat_rooms.id", ondelete="SET NULL"), nullable=True
    )
    chat_message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[ChatMessageReportReason] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, name="report_status"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 신고된 AI 응답 본문과, 그보다 앞선 가장 최근 사용자 메시지(없으면 NULL — 오프닝 신고).
    evidence_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_user_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now() + interval '90 days'"), nullable=False
    )
    evidence_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 유니크의 열 순서가 (메시지, 신고자)인 것은 이 인덱스가 메시지 DELETE의 `SET NULL` 조회도
    # 받게 하기 위해서다 — 재생성은 매번 메시지를 지우므로, 메시지가 앞 열이 아니면 그때마다 이
    # 테이블을 처음부터 훑는다. 유일성의 뜻은 열 순서와 무관하다.
    __table_args__ = (
        UniqueConstraint(
            "chat_message_id", "reporter_user_id", name="ux_chat_message_reports_message_reporter"
        ),
        Index("ix_chat_message_reports_status_created", "status", "created_at", "id"),
        Index("ix_chat_message_reports_evidence_expires", "evidence_expires_at"),
    )
