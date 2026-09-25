import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, SmallInteger, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class AssetKind(str, enum.Enum):
    ORIGINAL = "original"
    BLURRED = "blurred"
    THUMBNAIL = "thumbnail"
    GENERATED = "generated"


class AssetStatus(str, enum.Enum):
    """Row is created pending at presigned-upload
    time, and flipped to ready once POST /assets/{id}/complete confirms the S3
    object exists."""

    PENDING = "pending"
    READY = "ready"


class Asset(Base):
    """Row is created (status=pending) when a presigned
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
    # nullable(백필할 과거 값이 없다 — 이 컬럼이
    # 생기기 전 생성 자산은 style을 남기지 않았다). plain Text인 이유(native enum이
    # 아닌 이유)는 `kind`/`status`와 달리 style이 "내부 상태기계"가 아니라 "외부
    # 계약값"이기 때문이다 — style 목록이 이미 4종→7종으로 완전 교체된 적이 있어 "다음
    # 개편"이 실증됐다. enum이면 ① 멤버 추가를 autogenerate가 감지 못 하고 ② Postgres에
    # `DROP VALUE`가 없어 멤버 제거가 사실상 불가능해 옛 4종이 과거 행 보존 때문에
    # 타입에 영구히 남고 개편마다 쌓이며 ③ `.name`(대문자)이 DB에 저장돼 와이어값
    # (소문자)과 대소문자가 갈린다.
    style: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 요청 행을 기록하기 전에 생성된 자산은 요청 행이
    # 없어 nullable이다.
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("image_generation_requests.id"), nullable=True
    )


class ImageGenerationRequest(Base):
    """`assets`가 아니라 별도 테이블인 이유
    둘: ① `requested_count`가 2면 같은 프롬프트가 두 asset 행에 중복된다, ②
    이미지가 안 나온 요청(차단·실패)은 asset 행 자체가 없어 기록할 자리가 없다.

    쓰기 모델은 접수 시 INSERT(status=pending), 종료 시 UPDATE 1회다 — 이 모델
    자체는 그 쓰기 경로를 구현하지 않는다.
    """

    __tablename__ = "image_generation_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    style: Mapped[str] = mapped_column(Text, nullable=False)
    aspect_ratio: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    requested_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # native enum이 아니라 Text인 이유는 위 `Asset.style`과 같다 — 값이 늘 때
    # 마이그레이션 없이 넓히기 위해서다. 값: pending / succeeded / blocked / failed.
    status: Mapped[str] = mapped_column(Text, nullable=False)
    completed_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    blocked_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    input_error_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # `created_at.desc()` 참조는 위 컬럼 정의가 먼저 실행돼 클래스 바디 네임스페이스에
    # 바인딩된 뒤라야 동작한다 — 그래서 __table_args__를 컬럼들 다음에 둔다
    # (`db/models/inquiry.py`의 `Inquiry` 참고).
    __table_args__ = (
        Index("ix_image_generation_requests_owner_user_id_created_at", "owner_user_id", created_at.desc()),
        Index("ix_image_generation_requests_created_at", created_at.desc()),
    )
