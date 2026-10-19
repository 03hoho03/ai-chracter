import uuid
from datetime import datetime

from sqlalchemy import ARRAY, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Text, Uuid, false, func, text
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class LegalDocument(Base):
    """`kind`/`status`는 Postgres enum이 아니라 Text다 — 값이 늘어날
    여지가 있고(`notifications.type`이 이미 이 선례), admin_action_logs.action_type도
    같은 이유로 Text를 쓴다. `version`은 draft일 때 null이고 게시 시점에 부여된다.

    `status` 는 `draft`·`published`·`withdrawn` 셋이다. `withdrawn` 은 시행 전에 철회한 게시본이고 행은 남긴다.
    `published_at` 은 게시(공지) 시각, `effective_at` 은 그 판이 현행이 되는 시행 시각이다. 초안이 아닌 행은
    `effective_at` 이 반드시 있다(CHECK). 현행판·시행 예정 판을 고르는 규칙은 `api/legal/documents.py` 한 곳에 있다.

    부분 유니크 인덱스 2개(마이그레이션에서 생성)로 무결성을 지킨다 — kind별 초안 최대
    1개, 게시본·철회본을 통틀어 같은 (kind, version) 금지(철회한 판의 버전 이름은 다시 쓰지 않는다).

    `change_notice_markdown` 은 그 판의 변경 안내다. 초안에서 운영자가 본문과 함께 쓰고, 게시하면 게시본 행으로 복제된다.
    본문의 "주요 변경 내용" 절은 법적 기준본의 일부라 따로 남는다 — 안내는 재동의 화면이 전문보다 먼저 보여 주는 요약이다.

    `reconsent_scopes` 는 이 판이 다시 받는 동의 단위(`terms`·`collection`·`transfer`, `api/legal/consents.py`)다. 약관은
    `terms`, 처리방침은 `collection`·`transfer` 를 각각 걸 수 있고 정책 문서는 걸 수 없다(게시 경로가 검사한다).
    `requires_reconsent` 는 이 칸이 비어 있지 않음과 같다(CHECK). 이 칸을 모르는 이전 이미지가 배포 겹침·롤백 동안 그
    불리언으로 판정하므로 둘을 함께 쓴다.
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
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    change_notice_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    reconsent_scopes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]"), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_legal_documents_kind_draft", "kind", unique=True, postgresql_where=status == "draft"
        ),
        Index(
            "ix_legal_documents_kind_version_released",
            "kind",
            "version",
            unique=True,
            postgresql_where=status.in_(("published", "withdrawn")),
        ),
        CheckConstraint(
            "status = 'draft' OR effective_at IS NOT NULL", name="ck_legal_documents_effective_at_released"
        ),
        CheckConstraint(
            "requires_reconsent = (cardinality(reconsent_scopes) > 0)",
            name="ck_legal_documents_requires_reconsent_matches_scopes",
        ),
    )


class UserLegalConsent(Base):
    """회원이 법무 문서의 어느 판에 어떤 동의 단위로 동의했는지를 쌓는 이력. 가입 때 세 단위, 재동의 때 동의한 단위마다
    한 행을 더하고 고치지 않는다. `users` 의 버전·동의 시각 칸은 마지막 동의만 남기는 빠른 판정용이라 덮어쓰이므로, 과거
    판에 동의했다는 기록은 이 테이블에만 남는다.

    탈퇴하면 `erase_account` 가 그 회원의 행을 지운다. FK 둘 다 `ondelete` 를 두지 않는다 — 회원 행과 게시본 행은 지우지
    않으므로 연쇄 삭제가 일어날 일이 없고, 파기는 탈퇴 경로가 회원 행을 잠근 채 직접 한다."""

    __tablename__ = "user_legal_consents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    legal_document_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("legal_documents.id"), nullable=False)
    consent: Mapped[str] = mapped_column(Text, nullable=False)
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "consent IN ('terms', 'collection', 'transfer')", name="ck_user_legal_consents_consent"
        ),
    )
