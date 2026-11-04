"""정본 기억 등록부와 규칙 목록. 등록부는 슬롯 id 넷을 모두 담고 규칙 목록은 아직 비어 있다. 슬롯 하나를 뺀 등록부로도 확정이
도는지(남은 슬롯의 결과가 같은지)는 지식 슬롯 테스트의 슬롯 독립 확정이 본다."""

from typing import get_args

from api.novel_bible.ids import SlotId
from api.novel_bible.registry import REGISTRY
from api.novel_bible.rules import RULES
from novel_bible_fakes import FakeSource, events_slot, fake_registry


def test_the_registry_holds_every_slot_id_the_job_table_accepts() -> None:
    """깨지는 시나리오: 슬롯 id 를 하나 더 늘리고 등록부에 싣지 않으면 그 슬롯은 작업이 만들어지지 않아 조용히 꺼진 채로 돈다."""
    assert set(REGISTRY.ids()) == set(get_args(SlotId))


def test_no_rule_is_registered_before_its_code_arrives() -> None:
    assert list(RULES) == []


def test_registry_ids_cover_the_extracting_slots_and_the_source() -> None:
    assert fake_registry(events_slot()).ids() == frozenset({"events"})
    assert fake_registry(events_slot(), source=FakeSource()).ids() == frozenset({"events", "source"})
