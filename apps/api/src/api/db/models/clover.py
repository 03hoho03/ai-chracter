import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class CloverLedger(Base):
    """clover-techspec.md CT-2 (clover-goal-prompt.md CL-6·CL-7·CL-8).

    **append-only다 — UPDATE·DELETE를 하지 않는다.** 보존은 무한 누적이고 삭제 배치를
    만들지 않는다. 한 행 = 잔액이 변한 한 번이고, `balance_after`가 그 직후 잔액이다.
    """

    __tablename__ = "clover_ledger"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", name="fk_clover_ledger_user_id"), nullable=False
    )
    # 부호 있는 증감. 지급은 양수, 소모·회수·소멸은 음수. 0은 쓰지 않는다.
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    # 이 행이 적용된 **직후** 잔액. 조건부 UPDATE의 RETURNING이 이미 돌려주는 값이라 비용이
    # 0이고, 이게 있어야 원장과 잔액 컬럼의 어긋남을 러닝합 재계산 없이 한 행만 보고 판정할
    # 수 있다.
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    # native enum이 아니라 Text인 이유는 `Asset.style`·`ImageGenerationRequest.status`와 같다 —
    # 값이 늘 때 마이그레이션 없이 넓히기 위해서다. 값은 clover-techspec.md §2-2의 표:
    # admin_grant · admin_revoke · attendance_grant · chat_spend · image_spend ·
    # chat_refund · image_refund · withdrawal_burn.
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    # clover-goal-prompt.md CL-8. 지금 채우는 것은 어드민 지급/회수뿐이고 나머지는 NULL이다.
    # Postgres는 NULL을 중복으로 치지 않으므로 평범한 unique 인덱스가 "값이 있는 것만 유일"이
    # 된다.
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # `created_at.desc()` 참조는 위 컬럼 정의가 먼저 실행돼 클래스 바디 네임스페이스에
    # 바인딩된 뒤라야 동작한다 — 그래서 __table_args__를 컬럼들 다음에 둔다
    # (`db/models/media.py`의 `ImageGenerationRequest` 참고).
    __table_args__ = (
        Index("ix_clover_ledger_user_id_created_at", "user_id", created_at.desc()),
        Index("ux_clover_ledger_idempotency_key", "idempotency_key", unique=True),
    )
