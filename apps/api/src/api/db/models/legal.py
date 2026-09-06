import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Text, Uuid, false, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class LegalDocument(Base):
    """techspec.md §1-4. `kind`/`status`는 Postgres enum이 아니라 Text다 — 값이 늘어날
    여지가 있고(`notifications.type`이 이미 이 선례), admin_action_logs.action_type도
    같은 이유로 Text를 쓴다. `version`은 draft일 때 null이고 게시 시점에 부여된다.

    부분 유니크 인덱스 2개(마이그레이션에서 생성)로 무결성을 지킨다 — kind별 초안 최대
    1개, published끼리 같은 (kind, version) 금지.
    """

    __tablename__ = "legal_documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    requires_reconsent: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "ix_legal_documents_kind_draft", "kind", unique=True, postgresql_where=status == "draft"
        ),
        Index(
            "ix_legal_documents_kind_version_published",
            "kind",
            "version",
            unique=True,
            postgresql_where=status == "published",
        ),
    )
