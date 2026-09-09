import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class PromptSet(Base):
    """prompt-db-goal-prompt.md §4-1. 프롬프트 문안 전체의 버전 헤더 + 화자 라벨.

    `status`는 Postgres enum이 아니라 Text다(`legal_documents` 선례) — draft/published
    외 값이 늘 여지가 있다. `version`은 draft일 때 null이고 게시 시점에 서버가 자동
    증가 정수 문자열을 부여한다(D-15). 부분 유니크 인덱스 2개(마이그레이션에서 생성)로
    무결성을 지킨다 — 초안은 전역 최대 1개, published 버전 중복 금지.

    `story_example_label`("서술자")과 `story_assistant_label`("진행자")이 둘로 갈리는
    것은 표류가 아니라 실측된 현재 동작이다(§1-1) — 전개 예시에서만 다른 라벨을 쓴다.

    `relationship()`은 선언하지 않는다(리포 규약) — `prompt_sections`와의 관계는 순수
    FK로만 두고 삭제 순서는 호출부가 직접 지킨다.
    """

    __tablename__ = "prompt_sets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    user_label: Mapped[str] = mapped_column(Text, nullable=False)
    story_assistant_label: Mapped[str] = mapped_column(Text, nullable=False)
    story_example_label: Mapped[str] = mapped_column(Text, nullable=False)
    character_assistant_label: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # `status == "draft"`/`published_at.desc()` 참조는 위 컬럼 정의가 먼저 실행돼 클래스
    # 바디 네임스페이스에 바인딩된 뒤라야 동작한다(`db/models/notice.py`의 `Notice` 참고).
    # bare `Mapped` 컬럼을 `postgresql_where`에 그대로 주면 autogenerate가 생성하는
    # 마이그레이션 소스에 `MappedColumn` 객체 repr이 박혀 `SyntaxError`가 난다(실측) —
    # `== "draft"`로 명시적 불리언 식을 만들어야 렌더러가 `sa.text(...)`로 정상 변환한다.
    __table_args__ = (
        Index("ix_prompt_sets_draft", "status", unique=True, postgresql_where=status == "draft"),
        Index(
            "ix_prompt_sets_version_published",
            "version",
            unique=True,
            postgresql_where=status == "published",
        ),
        Index("ix_prompt_sets_published_at", published_at.desc()),
    )


class PromptSection(Base):
    """prompt-db-goal-prompt.md §4-1. 순서 있는 문안 조각.

    `channel`/`scope`/`slot`/`variant`는 전부 Text다 — 값이 늘 여지가 있다. `variant`는
    nullable 금지, 기본값 `''`다 — Postgres UNIQUE는 NULL끼리 중복으로 보지 않으므로
    nullable이면 `(set, channel, slot, NULL)` 행이 무한히 들어가 유니크가 무력화된다.

    `order` 유니크는 여기 두지 않는다 — 같은 자리에 들어가는 `variant` 여러 행(템플릿
    4종 등)이 같은 `order`를 공유해 단순 유니크가 성립하지 않는다. 그 검사는 게시
    검증(§9-2 R-6, `(channel, variant)` 안에서)이 맡는다 — 복합 유니크로 우회하면
    `alembic check`가 비교하지 않는 사각지대에 들어간다.

    **유니크 키에 `scope`를 넣는다.** 목표 문서 §4-1의 문면은
    `UNIQUE(prompt_set_id, channel, slot, variant)`(scope 미포함)이지만, 그 문서 §4-2가
    직접 확정한 시드 표를 `(channel, slot, variant)`만으로 묶어 보면 **충돌 그룹이
    둘**이다 — `('system', 'self_definition', '')`가 `scope=story`/`character` 두 행,
    `('publish_filter', 'intro_instruction', '')`가 `scope=character`/`story` 두 행(실제
    시드로 재현 확인). scope를 빼면 이 네 행이 유니크 위반으로 삽입 불가능하다(dev
    Postgres에서 실측: `duplicate key value violates unique constraint`). scope를
    포함한 5열 키로는 충돌이 없다. 문서의 두 확정 사항이 서로 모순돼 실행 가능한
    쪽(§4-2의 시드 표)을 따르고 이 사실을 보고한다.

    `relationship()`은 선언하지 않는다(리포 규약) — 세트 삭제 시 이 테이블 →
    `prompt_sets` 순서를 호출부가 직접 지킨다.
    """

    __tablename__ = "prompt_sections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    prompt_set_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("prompt_sets.id"), nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    slot: Mapped[str] = mapped_column(Text, nullable=False)
    variant: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    conditional: Mapped[bool] = mapped_column(Boolean, nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        Index(
            "ix_prompt_sections_set_channel_scope_slot_variant",
            "prompt_set_id",
            "channel",
            "scope",
            "slot",
            "variant",
            unique=True,
        ),
        Index("ix_prompt_sections_set_channel_order", "prompt_set_id", "channel", "order"),
    )
