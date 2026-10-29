"""정본 기억의 사실 슬롯 표. 공통 칸·삭제 규칙은 `novel_bible.py` 모듈 docstring 과 `NovelBibleItem`."""

import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from api.db.models.novel import _sql_in_list
from api.db.models.novel_bible import NovelBibleItem, item_table_args
from api.novel_bible.ids import FactKind, FactScope, LifeValue, PresenceValue


class NovelBibleFact(NovelBibleItem, Base):
    """주어 개체에 대한 명제 하나 — 생사·출입·소지·능력·속성·관계. `fact_key` 는 같은 명제면 어느 화·어느 개정에서 다시
    뽑혀도 같은 안정 키다(채팅 기억의 사실 키와는 무관하다).

    대상이 개체인 종류(소지·능력·관계)만 `value_entity_id` 로 개체를 가리킨다. 속성 값은 이름이어도 개체에 잇지 않는다 — 이으면
    개체 표에 그 이름이 언제 생겼는지에 따라 같은 명제의 키가 달라진다. `holds` 가 거짓인 행(잃음)은 소지·능력·관계에만 있다.
    `immutable` 은 작품 전체 범위의 속성에만, `onset`(이 장면에서 상태가 시작됨)은 작품 전체 범위가 아닌 행에만 선다.

    `valid_from_event_id` 는 상태가 시작된 같은 화 사건이고, 비어 있으면 미정이다. 끝을 적는 칸은 없다 — 끝은 나중 화에서
    드러나는데 앞 행을 고칠 수 없으므로, 같은 상태의 다음 행으로 파생한다."""

    __tablename__ = "novel_bible_facts"

    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("novel_bible_facts.id", ondelete="SET NULL"), nullable=True, sort_order=-1
    )
    fact_key: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    subject_entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("novel_bible_entities.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[FactKind] = mapped_column(Text, nullable=False)
    predicate_norm: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_norm: Mapped[str] = mapped_column(Text, nullable=False)
    value_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("novel_bible_entities.id", ondelete="CASCADE"), nullable=True
    )
    holds: Mapped[bool] = mapped_column(Boolean, nullable=False)
    immutable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    onset: Mapped[bool] = mapped_column(Boolean, nullable=False)
    scope: Mapped[FactScope] = mapped_column(Text, nullable=False)
    valid_from_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("novel_bible_events.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        *item_table_args("novel_bible_facts"),
        CheckConstraint(f"kind IN ({_sql_in_list(FactKind)})", name="ck_novel_bible_facts_kind"),
        CheckConstraint(f"scope IN ({_sql_in_list(FactScope)})", name="ck_novel_bible_facts_scope"),
        CheckConstraint(
            "NOT immutable OR (kind = 'attribute' AND scope = 'work')", name="ck_novel_bible_facts_immutable"
        ),
        CheckConstraint("holds OR kind IN ('possession', 'ability', 'relation')", name="ck_novel_bible_facts_holds"),
        CheckConstraint(
            f"kind <> 'life' OR value_norm IN ({_sql_in_list(LifeValue)})", name="ck_novel_bible_facts_life"
        ),
        CheckConstraint(
            f"kind <> 'presence' OR value_norm IN ({_sql_in_list(PresenceValue)})",
            name="ck_novel_bible_facts_presence",
        ),
        CheckConstraint("NOT (onset AND scope = 'work')", name="ck_novel_bible_facts_onset"),
        CheckConstraint(
            "(kind IN ('possession', 'ability', 'relation')) = (value_entity_id IS NOT NULL)",
            name="ck_novel_bible_facts_value_entity",
        ),
        Index("ix_novel_bible_facts_novel_key", "novel_id", "fact_key"),
        Index("ix_novel_bible_facts_subject", "subject_entity_id"),
        Index(
            "ix_novel_bible_facts_value_entity",
            "value_entity_id",
            postgresql_where=text("value_entity_id IS NOT NULL"),
        ),
        Index(
            "ix_novel_bible_facts_valid_from",
            "valid_from_event_id",
            postgresql_where=text("valid_from_event_id IS NOT NULL"),
        ),
    )
