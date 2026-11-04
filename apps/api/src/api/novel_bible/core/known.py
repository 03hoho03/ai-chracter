"""여러 슬롯이 같은 꼴로 싣는 아는 개체 힌트의 글.

사건·사실 슬롯이 이 글을 렌더 값 `known_entities` 로 싣고, 두 채널의 문안 지시문이 같은 꼴을 설명한다. 꼴을 슬롯마다 따로 두면
한쪽만 고쳐져 그쪽 지시문과 어긋나므로 여기 한 곳에 둔다. 힌트라 추출 캐시 열쇠에 들지 않는다."""

from collections.abc import Iterable

from api.novel_bible.core.types import EntityName
from api.novel_bible.ids import EntityKind

# 개체 종류마다 줄에 보이는 표지. 종류가 늘면 여기 더한다 — 빠진 종류의 개체가 하나라도 있는 소설은 그 뒤 모든 확정의 렌더가
# 실패한다(아는 개체는 소설의 개체 전부다).
KIND_LABELS: dict[EntityKind, str] = {"character": "인물", "object": "사물", "ability": "능력"}


def known_entities_text(names: Iterable[EntityName]) -> str:
    """개체마다 한 줄 `- 이름 (인물)`(종류 자리는 `KIND_LABELS` 의 표지), 별칭이 있으면 끝에 ` — 별칭: a, b`. 같은 줄은 한 번만
    싣고 글자 순으로 정렬해 줄바꿈으로 잇는다. 모델이 주어·대상 이름을 낼 때는 이름만 써야 한다 — 괄호의 종류나 별칭 꼬리를
    함께 옮기면 그 글 그대로 다른 개체가 생긴다."""
    return "\n".join(sorted({_line(name) for name in names}))


def _line(name: EntityName) -> str:
    aliases = f" — 별칭: {', '.join(name.aliases)}" if name.aliases else ""
    return f"- {name.name} ({KIND_LABELS[name.kind]}){aliases}"
