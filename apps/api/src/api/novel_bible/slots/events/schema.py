"""사건 슬롯의 모델 출력 꼴(구조화 호출의 응답 스키마).

길이·범위 제약을 두지 않는다 — 공급자마다 스키마로 받는 제약이 달라, 상한과 범위는 검증이 항목 단위로 자르거나 버린다. 값
목록 칸은 `ids.py` 의 Literal 을 써서 DB CHECK 와 같은 출처에서 나온다."""

from typing import Literal

from pydantic import BaseModel

from api.novel_bible.core.types import QuoteOut
from api.novel_bible.ids import EventActuality, EventRelationKind


class ThingUse(BaseModel):
    actor: str
    thing: str
    thing_kind: Literal["object", "ability"]


class ExtractedEvent(BaseModel):
    key: str  # 이 출력 안에서만 쓰는 이름 — 회상 관계가 사건을 가리킬 때 쓴다
    summary: str
    paragraphs: list[int]  # 이 사건이 걸친 문단 번호(1부터)
    # 지금 이야기 · 회상(지난 일이 실제로 일어남) · 꿈·상상·환각·극중극(일어나지 않음)
    actuality: EventActuality
    present: list[str]  # 그 장면에 살아서 말하거나 행동하는 인물
    mentioned: list[str]  # 말로만 언급되거나 회상·생각·꿈 속에만 있는 인물
    uses: list[ThingUse]
    quote: QuoteOut


class ExtractedRelation(BaseModel):
    event: str  # 이 화의 회상 사건 key
    relation: EventRelationKind
    target: str  # 앞 화 사건 목록의 표지(P1 …)


class EventsOutput(BaseModel):
    events: list[ExtractedEvent]
    relations: list[ExtractedRelation]
