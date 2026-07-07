import enum
import uuid
from decimal import Decimal

from sqlalchemy import ARRAY, CheckConstraint, Enum, ForeignKey, Integer, Numeric, Text, Uuid
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
    """techspec-db-schema.md §5. 1:1 extension of content_versions for type='story'."""

    __tablename__ = "story_version_details"

    content_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("content_versions.id"), primary_key=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    one_liner: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_asset_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("assets.id"), nullable=False)
    prompt_template: Mapped[StoryPromptTemplate] = mapped_column(
        Enum(StoryPromptTemplate, name="story_prompt_template"), nullable=False
    )
    setting_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    development_example: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)


class StartingSetup(Base):
    """techspec-db-schema.md §5. entity_id pattern (§1 원칙 4), order-sensitive list (§1 원칙 2)."""

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
    """techspec-db-schema.md §5. Stats are independent per starting_setup, not shared."""

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
    order: Mapped[int] = mapped_column(Integer, nullable=False)


class KeywordNote(Base):
    """techspec-db-schema.md §5. entity_id pattern; starting_setup_id null = applies to
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
    """techspec-db-schema.md §5. entity_id pattern; scoped to the whole work (content_version_id)."""

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
    """techspec-db-schema.md §5. entity_id pattern, order-sensitive list (§1 원칙 2)."""

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
    """techspec-db-schema.md §5. Only one level of nesting is allowed: this table has no
    self-referential FK, so a group can never contain another group."""

    __tablename__ = "ending_rule_groups"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    ending_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("endings.id"), nullable=False)
    next_op: Mapped[LogicalOp | None] = mapped_column(Enum(LogicalOp, name="logical_op"), nullable=True)
    order: Mapped[int] = mapped_column(Integer, nullable=False)


class EndingRule(Base):
    """techspec-db-schema.md §5. A rule belongs to an ending directly (top-level) or to a
    rule group, never both/neither — enforced by a CHECK constraint rather than app-level
    validation alone. `stat_def_entity_id` references a stat_def's entity_id (§1 원칙 4),
    not its physical id, so the reference survives republish-cloning across versions."""

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
