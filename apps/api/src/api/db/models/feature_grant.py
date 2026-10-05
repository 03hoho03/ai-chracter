import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import DateTime, ForeignKey, Index, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base

# 계정별로 허용해야 쓸 수 있는 기능의 이름. `feature` 컬럼은 native enum 이 아니라 Text 라 값이 늘어도
# 마이그레이션이 필요 없고, 값 범위는 이 Literal 이 파이썬 쪽에서만 강제한다.
FeatureName = Literal["novelize"]


class UserFeatureGrant(Base):
    """계정 하나에 기능 하나를 허용한 사실. 행이 있으면 허용, 없으면 미허용이다 — 회수는 행 DELETE 이고,
    누가 언제 켜고 껐는지는 `admin_action_logs` 에 남는다(행에 이력을 쌓지 않는다).

    행이 있다고 곧 쓸 수 있는 것은 아니다. 실제 접근은 전역 스위치와 env 허용 명단까지 함께 보는
    판정 함수(`novelize/access.py`)가 정한다 — 이 테이블은 그 조건 중 하나다.

    탈퇴하면 지운다(`auth/withdrawal.py` 의 `erase_account`). 운영자 계정 쪽(`granted_by`)은
    지우지 않는다."""

    __tablename__ = "user_feature_grants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    feature: Mapped[FeatureName] = mapped_column(Text, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    granted_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("admin_users.id"), nullable=False)

    # 한 계정에 같은 기능은 한 행뿐이다. 다시 허용하면 이 인덱스에 막혀 첫 허용 행이 그대로 남는다.
    __table_args__ = (Index("ux_user_feature_grants_user_id_feature", "user_id", "feature", unique=True),)
