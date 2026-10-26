import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class WorkBundle(Base):
    """작가가 자기 작품·소설을 사적으로 정리하는 묶음. 스튜디오 안에서 본인에게만 보이고 독자에게 노출하지 않는다.

    묶음은 작품 행에 칸을 두지 않고 따로 둔다 — 작품 행에는 소설화 허락 같은 권리 칸이 있어, 재분류가 그 행을 UPDATE 하면
    권리 칸이 있는 행의 갱신 시각·잠금이 정리 동작에 끌려 다닌다.

    🔴 탈퇴는 `users` 행을 지우지 않고(소프트 삭제) 회원 소유 표를 하나씩 지우므로 `owner_user_id` 의 CASCADE 는 탈퇴에서
    돌지 않는다. 탈퇴 파기(`auth/withdrawal.py` 의 `erase_account`)가 묶음을 직접 지운다 — 이 표가 남아 있는 동안 그 줄을
    빼면 탈퇴한 회원이 직접 쓴 묶음 이름이 남는다."""

    __tablename__ = "work_bundles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # 앞뒤 공백을 뺀 1~40자는 요청 스키마가 지킨다(DB 에 CHECK 를 두지 않는다).
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # 이름 바꾸기·항목 넣기·빼기가 실제로 무언가를 바꿀 때 민다. 작품 행의 시각은 건드리지 않는다.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # 내 묶음 목록(`updated_at` 내림차순)과 회원별 묶음 수 세기.
    __table_args__ = (Index("ix_work_bundles_owner_user_id_updated_at", "owner_user_id", "updated_at"),)


class WorkBundleItem(Base):
    """묶음 하나에 든 작품 하나. 작품(캐릭터·스토리)이면 `content_id`, 소설이면 `novel_id` 중 정확히 하나만 값이 있다.

    두 칸 모두 ON DELETE CASCADE 라 초안 삭제·소설 삭제처럼 작품 행이 하드 삭제되면 소속 행도 DB 가 지운다. 행이 남는 경우
    (운영 삭제된 작품, 숨긴 소설, 소설화 허용을 잃은 계정의 소설)는 목록과 항목 수가 거른다.

    🔴 "정확히 하나" CHECK 와 아래 부분 유니크 둘은 `alembic check` 가 비교하지 않는다 — 행위 테스트가 지킨다."""

    __tablename__ = "work_bundle_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    bundle_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("work_bundles.id", ondelete="CASCADE"), nullable=False
    )
    content_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("contents.id", ondelete="CASCADE"), nullable=True
    )
    novel_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("novels.id", ondelete="CASCADE"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("num_nonnulls(content_id, novel_id) = 1", name="ck_work_bundle_items_exactly_one_work"),
        # 한 묶음 안에서 같은 작품은 한 번만. 다른 묶음에는 같은 작품이 들어갈 수 있다(태그처럼).
        # 열 순서는 작품 id 가 앞이다 — 작품·소설 행을 지울 때 CASCADE 가 `content_id = ?`·`novel_id = ?` 로 소속 행을
        # 찾으므로, 묶음 id 가 앞이면 그 조회에 인덱스가 맞지 않아 순차 스캔이 된다.
        Index(
            "ux_work_bundle_items_content_id_bundle_id",
            "content_id",
            "bundle_id",
            unique=True,
            postgresql_where=content_id.is_not(None),
        ),
        Index(
            "ux_work_bundle_items_novel_id_bundle_id",
            "novel_id",
            "bundle_id",
            unique=True,
            postgresql_where=novel_id.is_not(None),
        ),
        # 묶음별 항목 조회와 묶음 삭제 CASCADE.
        Index("ix_work_bundle_items_bundle_id_created_at", "bundle_id", "created_at"),
    )
