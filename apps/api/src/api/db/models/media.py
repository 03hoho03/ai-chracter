import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class AssetKind(str, enum.Enum):
    ORIGINAL = "original"
    BLURRED = "blurred"
    THUMBNAIL = "thumbnail"
    GENERATED = "generated"


class AssetStatus(str, enum.Enum):
    """techspec-backend-media.md §1: row is created pending at presigned-upload
    time, and flipped to ready once POST /assets/{id}/complete confirms the S3
    object exists."""

    PENDING = "pending"
    READY = "ready"


class Asset(Base):
    """techspec-db-schema.md §9. Row is created (status=pending) when a presigned
    upload URL is issued, and flipped to status=ready once upload completes."""

    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[AssetKind] = mapped_column(Enum(AssetKind, name="asset_kind"), nullable=False)
    status: Mapped[AssetStatus] = mapped_column(
        Enum(AssetStatus, name="asset_status"), nullable=False, default=AssetStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # image-style-7-goal-prompt.md IS-6: nullable(백필할 과거 값이 없다 — 이 컬럼이
    # 생기기 전 생성 자산은 style을 남기지 않았다). plain Text인 이유(native enum이
    # 아닌 이유)는 `kind`/`status`와 달리 style이 "내부 상태기계"가 아니라 "외부
    # 계약값"이기 때문이다 — 이번 런 자체가 4종→7종 완전 교체라 "다음 개편"이 이미
    # 실증됐다. enum이면 ① 멤버 추가를 autogenerate가 감지 못 하고 ② Postgres에
    # `DROP VALUE`가 없어 멤버 제거가 사실상 불가능해 옛 4종이 과거 행 보존 때문에
    # 타입에 영구히 남고 개편마다 쌓이며 ③ `.name`(대문자)이 DB에 저장돼 와이어값
    # (소문자)과 대소문자가 갈린다.
    style: Mapped[str | None] = mapped_column(Text, nullable=True)
