import enum
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class StoryPromptTemplate(str, enum.Enum):
    BASIC = "basic"
    EMOTIONAL = "emotional"
    SIMULATION = "simulation"
    CUSTOM = "custom"


class LogicalOp(str, enum.Enum):
    AND = "and"
    OR = "or"


class EndingRuleOperator(str, enum.Enum):
    GTE = "gte"
    LTE = "lte"
    EQ = "eq"
    GT = "gt"
    LT = "lt"


class StoryVersionDetail(Base):
    """1:1 extension of content_versions for type='story'.

    `thumbnail_asset_id` is nullable for the same reason as
    `CharacterVersionDetail.thumbnail_asset_id`: a brand-new draft
    (`POST /contents`) has no image yet — publish validation is what requires it.
    """

    __tablename__ = "story_version_details"

    content_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("content_versions.id"), primary_key=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    one_liner: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("assets.id"), nullable=True
    )
    prompt_template: Mapped[StoryPromptTemplate] = mapped_column(
        Enum(StoryPromptTemplate, name="story_prompt_template"), nullable=False
    )
    setting_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    development_example: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # `development_example`(자유 텍스트)의 후속 — 입출력 쌍
    # 목록으로 받는다. 마이그레이션 리비전 ①이 기존 33건을 파싱해 채우고, `development_example`
    # 컬럼 자체는 그것을 지우는 리비전 ②가 나오기 전까지 그대로 살아 있다.
    development_examples: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    # 크랙의 `user's role and goal:`/`Rule:`에 대응.
    # 필수로 만들지 않는다 — 기존 33건이 비어 있는 채로 발행돼 있다.
    user_goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    rules: Mapped[str | None] = mapped_column(Text, nullable=True)


class StartingSetup(Base):
    """entity_id pattern, order-sensitive list."""

    __tablename__ = "starting_setups"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    content_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("content_versions.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    prologue: Mapped[str] = mapped_column(Text, nullable=False)
    opening_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    playguide: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_replies: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    order: Mapped[int] = mapped_column(Integer, nullable=False)


class StatDef(Base):
    """Stats are independent per starting_setup, not shared."""

    __tablename__ = "stat_defs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    starting_setup_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("starting_setups.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    icon: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[str] = mapped_column(Text, nullable=False)
    min_value: Mapped[int] = mapped_column(Integer, nullable=False)
    max_value: Mapped[int] = mapped_column(Integer, nullable=False)
    initial_value: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # 매 턴 결정적으로 더해지는 값(감소는 음수). None 이면 종전대로 LLM 판단에만 맡긴다.
    # "매 턴 반드시 1씩 줄어든다" 같은 제약을 description 산문으로만 두면 판정 LLM 이 조용히
    # 건너뛰거나 거꾸로 올리는 일이 실제로 있었고(2026-08-07 실측), 그 카운터에 걸린 엔딩은
    # 도달 가능성이 통째로 흔들린다 — 그래서 카운터는 판단 대상이 아니라 시스템이 굴린다.
    per_turn_delta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order: Mapped[int] = mapped_column(Integer, nullable=False)


class KeywordNote(Base):
    """entity_id pattern; starting_setup_id null = applies to
    the whole story rather than a single starting setup."""

    __tablename__ = "keyword_notes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    content_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("content_versions.id"), nullable=False
    )
    starting_setup_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("starting_setups.id"), nullable=True
    )
    info_text: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_keywords: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)


class Shortcut(Base):
    """entity_id pattern; scoped to the whole work (content_version_id)."""

    __tablename__ = "shortcuts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    content_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("content_versions.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)


class Ending(Base):
    """entity_id pattern, order-sensitive list."""

    __tablename__ = "endings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    starting_setup_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("starting_setups.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    turn_count_gate: Mapped[int] = mapped_column(Integer, nullable=False)
    judgment_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    epilogue: Mapped[str | None] = mapped_column(Text, nullable=True)
    hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    order: Mapped[int] = mapped_column(Integer, nullable=False)


class EndingRuleGroup(Base):
    """Only one level of nesting is allowed: this table has no
    self-referential FK, so a group can never contain another group.

    이 결정을 검증하던 `test_migrations.py`의 `test_ending_rule_groups_has_no_self_referential_fk`는
    2026-09-08에 삭제했다 — FK 존재 여부는 `alembic check`가 모델↔마이그레이션 일치로 비교하므로,
    모델에 자기참조 FK가 생기면 마이그레이션과의 drift로 잡힌다. 다만 그건 model↔migration
    일치를 지키는 것뿐이고 "1단만 허용"이라는 설계 규칙 자체를 앞으로도 못 바꾸게 잠그는 건 아니다.
    """

    __tablename__ = "ending_rule_groups"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    ending_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("endings.id"), nullable=False)
    next_op: Mapped[LogicalOp | None] = mapped_column(Enum(LogicalOp, name="logical_op"), nullable=True)
    order: Mapped[int] = mapped_column(Integer, nullable=False)


class EndingRule(Base):
    """A rule belongs to an ending directly (top-level) or to a
    rule group, never both/neither — enforced by `ck_ending_rules_exactly_one_parent`
    (a CHECK constraint) rather than app-level validation alone. `stat_def_entity_id`
    references a stat_def's entity_id, not its physical id, so the reference
    survives republish-cloning across versions.

    이 결정을 검증하던 `test_migrations.py`의
    `test_ending_rules_has_exactly_one_parent_check_constraint`는 2026-09-08에
    `alembic check` 중복이라 삭제했었다 — 그런데 alembic 1.18.5의 autogenerate/compare 에는
    CHECK 제약 비교자가 없어(`CheckConstraint`를 아예 다루지 않는다) `alembic check`는
    이 제약을 검증하지 못한다. 지금 `ck_ending_rules_exactly_one_parent`를 검증하는 건
    `tests/test_story_models.py`의 `test_ending_rule_rejects_both_ending_and_group_set`과
    `test_ending_rule_rejects_neither_ending_nor_group_set` 두 개뿐이다.
    """

    __tablename__ = "ending_rules"
    __table_args__ = (
        CheckConstraint(
            "(ending_id IS NOT NULL) <> (rule_group_id IS NOT NULL)",
            name="ck_ending_rules_exactly_one_parent",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    ending_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("endings.id"), nullable=True)
    rule_group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ending_rule_groups.id"), nullable=True
    )
    stat_def_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    operator: Mapped[EndingRuleOperator] = mapped_column(
        Enum(EndingRuleOperator, name="ending_rule_operator"), nullable=False
    )
    threshold: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    next_op: Mapped[LogicalOp | None] = mapped_column(Enum(LogicalOp, name="logical_op"), nullable=True)
    order: Mapped[int] = mapped_column(Integer, nullable=False)


class MediaBookPerson(Base):
    """미디어 북의 인물 축 한 줄. entity_id 패턴, 순서 있는 목록.

    이름 중복은 DB 제약으로 막지 않는다. 한 저장 요청 안에서 두 인물의 이름을 맞바꾸면 행을 하나씩
    고치는 도중 잠깐 같은 이름이 둘이 되어 UNIQUE 가 500 을 낸다 — 중복 검사는 요청 검증(422)이 한다.
    """

    __tablename__ = "media_book_people"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    content_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("content_versions.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False)

    # 칸은 축을 entity_id 로 가리키므로 한 버전에서 entity_id 가 두 줄이면 칸이 어느 줄인지 갈린다.
    __table_args__ = (
        UniqueConstraint("content_version_id", "entity_id", name="ux_media_book_people_version_entity"),
    )


class MediaBookScene(Base):
    """미디어 북의 장면 축 한 줄. `MediaBookPerson` 과 같은 모양이고, 이름 중복을 DB 에서 막지 않는
    이유도 같다."""

    __tablename__ = "media_book_scenes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    content_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("content_versions.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("content_version_id", "entity_id", name="ux_media_book_scenes_version_entity"),
    )


class MediaBookCell(Base):
    """미디어 북의 칸 하나 — 인물 × 장면 자리에 놓인 이미지 한 장. entity_id 패턴.

    `person_entity_id`·`scene_entity_id` 는 축 행의 물리 id 가 아니라 entity_id 값이라 버전을 복제할 때
    그대로 복사한다(물리 id 를 가리키는 키워드북의 시작설정 참조는 복제 때 다시 이어 줘야 한다).
    FK 는 걸지 않는다. 축의 `(content_version_id, entity_id)` UNIQUE 를 대상으로 복합 FK 를 걸 수도
    있지만, 같은 버전 안의 entity_id 참조에는 FK 를 두지 않는 기존 관례(`EndingRule.stat_def_entity_id`
    가 같은 버전의 스탯을 그렇게 가리킨다)를 따른다 — 복합 FK 는 이 스키마에 아직 없고, 걸면 저장·복제·
    삭제가 "축 먼저 넣고 칸 먼저 지운다"는 순서를 지켜야 한다. 대가로 DB 는 가리키는 축이 실제로 있는지
    모른다 — 고아 칸은 저장 요청 검증(칸이 가리키는 축이 같은 페이로드에 있어야 한다)이 막는다.

    `blurred_asset_id` 는 발행할 때 채운다(초안 칸에는 블러본이 아직 없다). `situation_description`·
    `unlock_hint` 는 비어 있어도 되는 작성자 입력이라 NULL 대신 빈 문자열을 기본값으로 둔다.
    """

    __tablename__ = "media_book_cells"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    content_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("content_versions.id"), nullable=False
    )
    person_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    scene_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    image_asset_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("assets.id"), nullable=False)
    blurred_asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("assets.id"), nullable=True)
    situation_description: Mapped[str] = mapped_column(Text, server_default="", nullable=False)
    unlock_hint: Mapped[str] = mapped_column(Text, server_default="", nullable=False)
    exclude_from_chat: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)

    # 좌표 UNIQUE 는 "칸 하나에 이미지 한 장"의 마지막 방어다. 한 저장 요청에 "칸 삭제 + 같은 자리에
    # 새 칸"이 함께 실리면 insert 가 delete 보다 먼저 나갈 때 이 제약에 걸리므로, 쓰기 경로는
    # 삭제를 먼저 flush 한 뒤 insert 한다.
    __table_args__ = (
        UniqueConstraint("content_version_id", "entity_id", name="ux_media_book_cells_version_entity"),
        UniqueConstraint(
            "content_version_id",
            "person_entity_id",
            "scene_entity_id",
            name="ux_media_book_cells_version_person_scene",
        ),
    )
