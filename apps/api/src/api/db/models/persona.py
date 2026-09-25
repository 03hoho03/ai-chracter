import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class UserPersona(Base):
    """유저의 "대화 프로필" — 유저당 최대 10개.

    길이·금지 문자와 성별 허용값은 요청 스키마가 강제한다 — 여기는 저장만 한다.
    `gender`는 Postgres ENUM이 아니라 Text다(`prompt_sets.status` 선례, ENUM 3종 함정 회피).
    NULL이 "선택 안 함"이고 값은 `"male"`/`"female"`뿐이다.

    기본 프로필은 이 테이블의 플래그가 아니라 `users.default_persona_id` 컬럼 하나로 둔다 —
    "유저당 기본은 최대 1개"가 구조적으로 성립한다. 그래서
    `users ↔ user_personas`가 순환 FK가 되고, `users` 쪽 FK가 `use_alter`다(`User` 참고).

    `relationship()`·`ondelete`는 선언하지 않는다(리포 규약) — 방·기본 참조를 끊는 순서는
    호출부가 직접 지킨다(프로필 삭제, 회원 탈퇴).
    """

    __tablename__ = "user_personas"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    gender: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 목록 조회·개수 세기(상한 10개)가 전부 `user_id`로 거른다.
    __table_args__ = (Index("ix_user_personas_user_id", "user_id"),)
