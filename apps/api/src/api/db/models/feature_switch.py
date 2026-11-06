"""어드민이 켜고 끄는 기능 스위치의 덮어쓰기(`feature_switch_overrides`)와 그 변경 이력(`feature_switch_changes`).

덮어쓰기 행이 있는 스위치는 그 값으로 돌고, 없으면 `.env`(`Settings`) 값으로 돈다 — 읽는 쪽은 `core/feature_switches.py`.
이름 칸은 Text 다. 어느 스위치가 버튼 대상인지는 그 모듈의 이름 목록이 정하고, 읽을 때 목록 밖 이름의 행은 건너뛴다 — 다음
이미지에서 버튼 대상이 줄어도 남은 행 때문에 읽기가 깨지지 않게 DB 에는 이름 제약을 두지 않는다.

운영자 칸은 감사 로그(`admin_action_logs.admin_id`)와 같이 어드민 계정을 FK 로 가리키고 `ON DELETE` 를 두지 않는다 — 덮어쓰기나
이력을 남긴 계정은 지울 수 없고, 누가 바꿨는지는 기록이 남는 한 남는다.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class FeatureSwitchOverride(Base):
    """스위치 하나의 지금 덮어쓰기. 행이 없으면 덮어쓰기 없음(`.env` 값)이고, 덮어쓰기 지우기는 행 DELETE 다. 누가 언제
    마지막으로 바꿨는지만 담는다 — 지나간 값은 `feature_switch_changes` 에 있다."""

    __tablename__ = "feature_switch_overrides"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[bool] = mapped_column(Boolean, nullable=False)
    admin_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("admin_users.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class FeatureSwitchChange(Base):
    """덮어쓰기를 바꾸거나 지운 한 번 = 한 행, 쌓기만 한다. 전·후 칸의 NULL 은 덮어쓰기 없음이다(지우기는 후가 NULL).
    `env_value` 는 그 순간의 `.env` 값이라, 덮어쓰기가 없던 쪽의 실효 값을 나중에 `.env` 가 바뀐 뒤에도 알 수 있다. NULL 은
    기록한 판이 그 이름의 `.env` 칸을 몰랐다는 뜻이다 — 다른 판이 남긴, 이 판이 다루지 않는 이름의 덮어쓰기를 지운 행이다.

    사유는 비울 수 없다 — 비었거나 스페이스(U+0020)만 있는 사유는 CHECK 가 막는다. Postgres `btrim` 은 스페이스만 깎아 탭·줄바꿈·
    전각 공백만 있는 사유는 통과시키므로, 그런 사유는 어드민 API 가 먼저 거른다. 🔴 `alembic check` 는 CHECK 를 비교하지 않아
    `pytest.raises(IntegrityError)` 행위 테스트가 유일한 검증이다."""

    __tablename__ = "feature_switch_changes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    before_override: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    after_override: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    env_value: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    admin_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("admin_users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (CheckConstraint("btrim(reason) <> ''", name="ck_feature_switch_changes_reason_not_blank"),)
