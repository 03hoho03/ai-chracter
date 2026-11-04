"""정본 기억의 지식 슬롯 표. 공통 칸·삭제 규칙은 `novel_bible.py` 모듈 docstring 과 `NovelBibleItem`."""

import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from api.db.models.novel import _sql_in_list
from api.db.models.novel_bible import NovelBibleItem, item_table_args
from api.novel_bible.ids import KnowledgeKind


class NovelBibleKnowledge(NovelBibleItem, Base):
    """인물(`knower_entity_id`)이 명제 하나를 안다(`knows`)거나 믿는다(`believes`). `fact_key` 는 그 명제의 안정 키로, 사실 행이
    없어도 계산된다. `proposition` 은 명제 칸(주어 개체 id·종류·술어·값·유지) — 믿음의 내용이고 키를 다시 계산할 때 쓴다.
    `known_since_event_id` 는 알게 된 같은 화 사건이고, 비어 있으면 미정이다."""

    __tablename__ = "novel_bible_knowledge"

    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("novel_bible_knowledge.id", ondelete="SET NULL"), nullable=True, sort_order=-1
    )
    knower_entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("novel_bible_entities.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[KnowledgeKind] = mapped_column(Text, nullable=False)
    fact_key: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    proposition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    known_since_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("novel_bible_events.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        *item_table_args("novel_bible_knowledge"),
        CheckConstraint(f"kind IN ({_sql_in_list(KnowledgeKind)})", name="ck_novel_bible_knowledge_kind"),
        Index("ix_novel_bible_knowledge_knower", "knower_entity_id"),
        Index("ix_novel_bible_knowledge_novel_key", "novel_id", "fact_key"),
        Index(
            "ix_novel_bible_knowledge_known_since",
            "known_since_event_id",
            postgresql_where=text("known_since_event_id IS NOT NULL"),
        ),
    )
