"""슬롯을 모으는 유일한 곳. 슬롯을 빼면 그 슬롯의 작업이 만들어지지 않고, 그 슬롯에 기대는 연결 칸은 미정으로 커밋되며, 그
슬롯을 읽는 규칙은 건너뛴다. 슬롯 코드가 들어올 때마다 여기에 한 줄씩 더한다 — 그 전까지 확정은 작업 없이 만들어진다."""

from api.novel_bible.core.contracts import Registry
from api.novel_bible.slots.source.slot import SourceCanonSlot

REGISTRY = Registry(extracting={}, source=SourceCanonSlot())
