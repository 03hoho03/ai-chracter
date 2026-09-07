import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class InquiryCategory(str, enum.Enum):
    ACCOUNT = "account"
    BUG = "bug"
    CONTENT = "content"
    SUGGESTION = "suggestion"
    OTHER = "other"


class InquiryStatus(str, enum.Enum):
    PENDING = "pending"
    ANSWERED = "answered"


class Inquiry(Base):
    """goal-prompt.md §3-2, techspec.md §3-2.

    D-11: 답변은 별도 `inquiry_replies` 테이블이 아니라 `reply_body`/`replied_by_admin_id`/
    `answered_at` 컬럼 3개로 둔다. 인터뷰 프리뷰에는 테이블로 적었으나, 왕복 1회 모델에서
    1:N 테이블은 쓰이지 않는 유연성이다. 다회 왕복이 실제로 필요해지면 그때 테이블로
    승격한다.

    Postgres ENUM 컬럼(`category`/`status`)은 `.value`(소문자)가 아니라 `.name`(대문자)이
    저장된다 — raw SQL을 쓸 일이 생기면 대문자를 쓴다(`apps/api/CLAUDE.md` §모델 규약).
    """

    __tablename__ = "inquiries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    category: Mapped[InquiryCategory] = mapped_column(
        Enum(InquiryCategory, name="inquiry_category"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("assets.id"), nullable=True
    )
    status: Mapped[InquiryStatus] = mapped_column(Enum(InquiryStatus, name="inquiry_status"), nullable=False)
    reply_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    replied_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id"), nullable=True
    )
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # `created_at.desc()` 참조는 위 컬럼 정의가 먼저 실행돼 클래스 바디 네임스페이스에
    # 바인딩된 뒤라야 동작한다 — 그래서 __table_args__를 컬럼들 다음에 둔다
    # (`db/models/moderation.py`의 `AdminActionLog` 참고).
    __table_args__ = (
        Index("ix_inquiries_user_id_created_at", "user_id", created_at.desc()),
        Index("ix_inquiries_status_created_at", "status", created_at.desc()),
    )
