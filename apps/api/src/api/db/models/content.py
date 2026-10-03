import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Text,
    Uuid,
    false,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class ContentType(str, enum.Enum):
    CHARACTER = "character"
    STORY = "story"


class ContentTarget(str, enum.Enum):
    FEMALE = "female"
    MALE = "male"
    ALL = "all"


class ContentVisibility(str, enum.Enum):
    PUBLIC = "public"
    LINK = "link"
    PRIVATE = "private"


class ModerationStatus(str, enum.Enum):
    NORMAL = "normal"
    RESTRICTED = "restricted"
    DELETED = "deleted"


class Genre(Base):
    """Master data, seeded via migration."""

    __tablename__ = "genres"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class Content(Base):
    """Shared character/story content header.

    `current_published_version_id` -> content_versions.id is declared with use_alter
    because content_versions.content_id -> contents.id creates a table-creation cycle
    between contents and content_versions; use_alter defers this FK to a post-create
    ALTER TABLE (same pattern as users/assets, see auth.py).

    `genre_id`/`target` are nullable even though the registration tab treats them as
    required (publish validation enforces that) — a brand-new draft
    (`POST /contents`) has neither set yet, so the DB must allow the empty state.
    """

    __tablename__ = "contents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    type: Mapped[ContentType] = mapped_column(Enum(ContentType, name="content_type"), nullable=False)
    creator_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    genre_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("genres.id"), nullable=True)
    target: Mapped[ContentTarget | None] = mapped_column(
        Enum(ContentTarget, name="content_target"), nullable=True
    )
    hashtags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    visibility: Mapped[ContentVisibility] = mapped_column(
        Enum(ContentVisibility, name="content_visibility"), nullable=False
    )
    moderation_status: Mapped[ModerationStatus] = mapped_column(
        Enum(ModerationStatus, name="moderation_status"), nullable=False
    )
    # 작가 계정 정지가 이 작품을 이용제한으로 내렸는가. 정지 해제는 이 표식이 선 작품만 정상으로 되돌린다 — 신고·관리자
    # 조치로 제한된 작품, 정지 전부터 제한이던 작품은 해제 뒤에도 그대로다. 정지가 세우고, 작품 단위 조치(제한·삭제·
    # 해제)와 이의 수용이 내린다. 신고 반려는 상태를 바꾸지 않으므로 내리지 않는다.
    restricted_by_suspension: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    current_published_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "content_versions.id", use_alter=True, name="fk_contents_current_published_version_id"
        ),
        nullable=True,
    )
    # 초안이 현재 발행본과 달라졌는지. 타임스탬프로는 판정할 수 없어 명시적 플래그다 —
    # `ContentVersion`에 `updated_at`이 없고, 초안의 자식 행들(상황이미지·시작설정 등)은 별도
    # 테이블이라 편집해도 버전 행을 건드리지 않는다. 자동저장이 세우고 발행·편집취소가 내린다.
    has_unpublished_changes: Mapped[bool] = mapped_column(
        Boolean, server_default=false(), nullable=False
    )
    comments_enabled: Mapped[bool] = mapped_column(Boolean, server_default=true(), nullable=False)
    pinned_comment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("comments.id", use_alter=True, name="fk_contents_pinned_comment_id"),
        nullable=True,
    )
    view_count: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    like_count: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    chat_count: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 표식은 제한 상태에서만 설 수 있다. 삭제·해제·이의 수용에서 표식 내리기를 빠뜨리면 여기서 IntegrityError 로 터진다
    # (이미 제한인 작품을 다시 제한하는 경우의 누락은 상태가 그대로라 못 잡는다 — 그건 행위 테스트가 본다).
    # 🔴 `alembic check` 는 CHECK 제약을 비교하지 않는다 — 검증은 행위 테스트가 유일하다.
    __table_args__ = (
        CheckConstraint(
            "NOT restricted_by_suspension OR moderation_status = 'RESTRICTED'",
            name="ck_contents_suspension_flag_only_when_restricted",
        ),
    )


class ContentVersion(Base):
    """Immutable snapshot; draft = the row with published_at IS NULL."""

    __tablename__ = "content_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("contents.id"), nullable=False)
    version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detail_description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Favorite(Base):
    __tablename__ = "favorites"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)
    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("contents.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Like(Base):
    __tablename__ = "likes"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)
    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("contents.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ContentChatParticipant(Base):
    """작품과 대화를 시작한 적이 있는 (작품, 사용자) 쌍. `contents.chat_count` 는 이 표의 행 수다.

    방은 하드 삭제되므로 방 행으로는 "이 사람이 이미 셌는가" 를 판정할 수 없다 — 방을 지우고 다시 만들면 또 세게
    된다. 그래서 쌍을 따로 남기고, 이 행을 처음 넣었을 때만 수를 올린다. 방을 지워도 이 행과 수는 남는다. 작가 본인은
    넣지 않는다.

    복합 PK 가 "쌍당 한 번" 의 유일한 방어선이다(삽입은 `ON CONFLICT DO NOTHING`) — `alembic check` 는 복합 PK
    구성을 비교하지 않으므로 검증은 행위 테스트가 한다.

    `ondelete` 는 두지 않는다(저장소 규약). 회원은 탈퇴해도 행이 남는 소프트 삭제라 FK 동작이 일어날 일이 없고,
    탈퇴 파기(`erase_account`)가 그 회원의 행을 직접 지운다 — 수는 내리지 않는다. 작품 행을 지우는 경로는 발행된
    적 없는 초안 삭제뿐인데, 방은 발행본이 있어야 만들어지므로 그 작품에는 이 행이 생기지 않는다."""

    __tablename__ = "content_chat_participants"

    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("contents.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class HomeCuration(Base):
    """홈 첫 화면에 유형(캐릭터·스토리)마다 한 편씩 거는 운영자 지정작. 행이 없으면 그 유형은 지정이 없다.

    유형이 PK 라 유형마다 한 행뿐이고, 지정을 바꾸는 쓰기는 `INSERT … ON CONFLICT (content_type) DO UPDATE` 한
    문장이다. 지정 작품의 유형이 칸의 유형과 같은지는 DB 가 아니라 지정 API 가 확인한다.

    지정 작품이 나중에 이용제한·비공개가 돼도 행은 그대로 둔다 — 홈은 읽을 때 공개 목록과 같은 조건으로 걸러
    안 보이게 하고, 제한이 풀리면 조치 경로가 이 표를 몰라도 다시 보인다.

    `ondelete` 는 두지 않는다(저장소 규약). 지정 API 는 공개 목록에 실린 작품만 받는데 그런 작품은 발행본이 있고,
    작품 행을 지우는 경로는 발행된 적 없는 초안 삭제뿐이라 지정 작품이 지워질 일이 없다. 그런 경로가 새로 생기면
    조용히 비는 대신 FK 위반으로 드러난다."""

    __tablename__ = "home_curations"

    content_type: Mapped[ContentType] = mapped_column(Enum(ContentType, name="content_type"), primary_key=True)
    content_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("contents.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
