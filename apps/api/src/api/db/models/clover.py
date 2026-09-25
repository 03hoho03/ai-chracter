import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class CloverLedger(Base):
    """**append-only다 — UPDATE·DELETE를 하지 않는다.** 보존은 무한 누적이고 삭제 배치를
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
    # 값이 늘 때 마이그레이션 없이 넓히기 위해서다. 값은 `core/clover.py`의 `CloverKind`
    # Literal이 강제 지점이다.
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    # 지금 채우는 것은 어드민 지급/회수·출석·미션 청구뿐이고 나머지는 NULL이다.
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


class CloverLot(Base):
    """지급 1건 = 로트 1행. `remaining`이 소진 순서
    (만료 임박 우선)대로 줄어드는 잔여량이고, `users.clover_balance`는 이 테이블
    `remaining` 합의 캐시다(불변식: `SUM(remaining) == clover_balance`).

    🔴 `id`는 `clover_ledger.id`(Python `default=uuid.uuid4`만 있음)와 달리 DB
    `server_default=gen_random_uuid()`를 건다 — 로트는 ORM(지급 경로)과 raw SQL(마이그레이션
    백필·만료 배치) 양쪽에서 INSERT되므로, 기본값을 DB에 둬야 어느 쪽에서 넣어도 안전하다.
    `clover_ledger`는 로트를 도입할 때 범위 밖으로 둬서 맞춰 바꾸지 않았다.

    `kind`는 원장의 `CloverKind`(core/clover.py)와 값 범위가 다르다 — 로트는 지급에만
    생기므로(소모·회수·소멸류는 로트를 새로 만들지 않는다) `attendance_grant`·`mission_grant`·
    `admin_grant`·`chat_refund`·`image_refund`, 그리고 백필 전용 값 `legacy_balance`
    (마이그레이션이 기존 `clover_balance`를 로트로 편입할 때만 쓴다)로 값이 갈린다. 같은
    타입을 재사용하지 않는다.
    """

    __tablename__ = "clover_lots"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", name="fk_clover_lots_user_id"), nullable=False
    )
    # 지급 당시 금액. 불변 — `remaining`만 소진에 따라 줄어든다.
    granted_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining: Mapped[int] = mapped_column(Integer, nullable=False)
    # NULL = 무기한(어드민 수동 지급·환불). 값이 있으면 그 시각(KST 자정 기준)에
    # 소멸 대상이다 — 진실은 만료 배치이고 이 컬럼은 배치가 아직 안 돈
    # 구간에서만 "만료 예정"을 뜻한다.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # CHECK 제약 두 개(`remaining >= 0`·`remaining <= granted_amount`)는 alembic
    # 1.18.5의 autogenerate/compare가 CHECK를 다루지 않아 `alembic check`가 검증하지
    # 못한다(`db/models/story.py`의 `EndingRule` docstring과 같은 함정) — 유일한 검증은
    # `pytest.raises(IntegrityError)` 행위 테스트다.
    #
    # 인덱스는 처음 설계가 "2개"(`remaining > 0` 부분 인덱스,
    # `(user_id, expires_at, created_at)`)였지만 하나로 겸한다 — 두 조회(소진:
    # `ORDER BY expires_at ASC NULLS LAST, created_at ASC` / 회수:
    # `ORDER BY created_at DESC`)가 **행을 고르는 조건**(`user_id = :u AND remaining > 0`)을
    # 공유하고, 그 조건이 곧 이 부분 인덱스이기 때문이다. 즉 인덱스가 먹는 것은 조회 범위이지
    # 정렬이 아니다.
    #
    # 🔴 회수의 `created_at DESC`는 이 인덱스로 정렬이 해결되지 **않는다** — B-tree 역순
    # 스캔은 `expires_at DESC, created_at DESC`를 내지 순수 `created_at DESC`가 아니고,
    # 로트마다 `expires_at`이 섞이는 것이 정상이다(무기한 NULL + 만료일 여럿). 플래너가
    # 범위를 좁힌 뒤 Sort로 보정하며, 유저당 활성 로트가 10행 미만이라 그 정렬 비용이
    # 무시할 수준이라서 별도 인덱스를 만들지 않는 것이다. 로트 수가 그 가정을 벗어나면
    # `(user_id, created_at DESC) WHERE remaining > 0`을 따로 두는 것이 다음 수순이다.
    __table_args__ = (
        CheckConstraint("remaining >= 0", name="ck_clover_lots_remaining_non_negative"),
        CheckConstraint(
            "remaining <= granted_amount", name="ck_clover_lots_remaining_le_granted_amount"
        ),
        Index(
            "ix_clover_lots_user_id_expires_at_created_at",
            "user_id",
            "expires_at",
            "created_at",
            postgresql_where=remaining > 0,
        ),
    )
