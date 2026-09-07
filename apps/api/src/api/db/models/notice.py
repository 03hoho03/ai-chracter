import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Text, Uuid, false, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class Notice(Base):
    """goal-prompt.md §3-1, techspec.md §3-1.

    `published`를 `published_at IS NOT NULL`로 대신하지 않는다 — 숨김 → 재게시 시
    원래 게시일이 유지돼야 목록 정렬과 "언제 고지했는가"가 흔들리지 않는다.
    `published_at`은 최초 게시 시각이고 숨김으로 되돌려도 지우지 않는다.
    `LegalDocument`(`db/models/legal.py`)도 `status`와 `published_at`을 따로 둔 같은
    이유다.

    `legal_documents`처럼 `status: Text`를 쓰지 않고 `Boolean`을 쓴다 — 공지의 상태는
    게시/숨김 둘뿐이고 늘어날 축이 보이지 않는다. 늘어나면 그때 Text로 바꾼다.
    """

    __tablename__ = "notices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # `published_at.desc()`·`published.is_(True)` 참조는 위 컬럼 정의가 먼저 실행돼
    # 클래스 바디 네임스페이스에 바인딩된 뒤라야 동작한다 — 그래서 __table_args__를
    # 컬럼들 다음에 둔다(`db/models/moderation.py`의 `AdminActionLog` 참고).
    # `postgresql_where=published`(bare 컬럼 참조)는 alembic autogenerate가 생성한
    # 마이그레이션 소스에 `MappedColumn` 객체의 repr을 그대로 박아 SyntaxError를
    # 냈다(실측) — `.is_(True)`로 명시적 불리언 식을 만들어야 렌더러가 `sa.text(...)`로
    # 정상 변환한다.
    __table_args__ = (
        Index(
            "ix_notices_published_at", published_at.desc(), postgresql_where=published.is_(True)
        ),
    )
