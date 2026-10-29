"""정본 기억의 사건 슬롯 표 — 화 안의 사건 노드와 회상 사건의 부분 순서 관계. 공통 칸·삭제 규칙은 `novel_bible.py` 모듈
docstring 과 `NovelBibleItem`."""

import uuid
from typing import Any

from sqlalchemy import ARRAY, CheckConstraint, ForeignKey, Index, Integer, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from api.db.models.novel import _sql_in_list
from api.db.models.novel_bible import NovelBibleItem, item_table_args
from api.novel_bible.ids import EventActuality, EventRelationKind


class NovelBibleEvent(NovelBibleItem, Base):
    """화 안의 사건 하나. `ordinal` 은 화 안 차례(첫 앵커 블록 순)이고, `anchor_block_ids` 는 이 사건이 걸친 원고 블록이다(FK
    없음). `scene_key` 는 장면 구성안의 장면 id 이고 비어 있으면 화 전체가 한 장면이다.

    `actuality` 는 사건이 이야기 안에서 실제로 일어났는가 — `present`(지금 이야기)·`flashback`(지난 일이 실제로 일어남)·
    `dream_or_imagined`(꿈·상상·환각·극중극, 일어나지 않음). `uses` 는 `[{"actor": 개체 id, "thing": 개체 id}]` 꼴이다."""

    __tablename__ = "novel_bible_events"

    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("novel_bible_events.id", ondelete="SET NULL"), nullable=True, sort_order=-1
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    scene_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    actuality: Mapped[EventActuality] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    anchor_block_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), nullable=False)
    present_entity_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(Uuid), nullable=False, server_default=text("'{}'::uuid[]")
    )
    mentioned_entity_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(Uuid), nullable=False, server_default=text("'{}'::uuid[]")
    )
    uses: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))

    __table_args__ = (
        *item_table_args("novel_bible_events"),
        CheckConstraint("ordinal >= 1", name="ck_novel_bible_events_ordinal"),
        CheckConstraint(f"actuality IN ({_sql_in_list(EventActuality)})", name="ck_novel_bible_events_actuality"),
        CheckConstraint("cardinality(anchor_block_ids) >= 1", name="ck_novel_bible_events_anchor"),
    )


class NovelBibleEventRelation(NovelBibleItem, Base):
    """회상 사건 하나와 다른 사건 사이의 앞뒤(부분 순서). 회상 사건(`from_event_id`)은 같은 화의 사건이고, 대상은 사건이 아니라
    그 사건의 첫 블록(`to_anchor_block_id`, FK 없음)으로 가리켜 읽을 때 사건으로 푼다 — 대상 화가 지워지면 "대상 사건 없음 = 미정"
    이 된다. `to_chapter_id` 는 조회 범위를 좁히는 사본이고 FK 가 없다."""

    __tablename__ = "novel_bible_event_relations"

    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("novel_bible_event_relations.id", ondelete="SET NULL"), nullable=True, sort_order=-1
    )
    from_event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("novel_bible_events.id", ondelete="CASCADE"), nullable=False
    )
    relation: Mapped[EventRelationKind] = mapped_column(Text, nullable=False)
    to_anchor_block_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    to_chapter_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    __table_args__ = (
        *item_table_args("novel_bible_event_relations"),
        CheckConstraint(
            f"relation IN ({_sql_in_list(EventRelationKind)})", name="ck_novel_bible_event_relations_relation"
        ),
        # 사건 DELETE 때 FK 검사(cascade)용.
        Index("ix_novel_bible_event_relations_from_event_id", "from_event_id"),
    )
