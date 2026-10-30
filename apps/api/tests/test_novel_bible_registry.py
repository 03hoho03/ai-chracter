"""정본 기억 등록부와 규칙 목록. 슬롯 코드가 들어오기 전이라 둘 다 비어 있고, 운영 이미지는 "슬롯이 빠진 엔진"을 그대로
싣는다 — 확정은 작업 없이 만들어진다."""

from typing import get_args

from api.novel_bible.ids import SlotId
from api.novel_bible.registry import REGISTRY
from api.novel_bible.rules import RULES
from novel_bible_fakes import FakeSource, events_slot, fake_registry


def test_registered_slots_are_ids_the_job_table_accepts() -> None:
    assert set(REGISTRY.ids()) <= set(get_args(SlotId))


def test_no_slot_or_rule_is_registered_before_their_code_arrives() -> None:
    assert dict(REGISTRY.extracting) == {}
    assert REGISTRY.source is None
    assert list(RULES) == []


def test_registry_ids_cover_the_extracting_slots_and_the_source() -> None:
    assert fake_registry(events_slot()).ids() == frozenset({"events"})
    assert fake_registry(events_slot(), source=FakeSource()).ids() == frozenset({"events", "source"})
