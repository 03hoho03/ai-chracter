"""지식 슬롯의 모델 출력 꼴(구조화 호출의 응답 스키마).

길이·범위 제약을 두지 않는다 — 공급자마다 스키마로 받는 제약이 달라, 상한과 범위는 검증이 항목 단위로 버린다. 값 목록 칸은
`ids.py` 의 Literal 을 써서 DB CHECK 와 같은 출처에서 나온다. 명제 칸(`about`)은 사실 슬롯의 사실과 같은 칸이고 같은 규칙으로
검증된다 — 같은 명제면 같은 안정 키를 받아 앎이 사실에 이어진다. 코어의 명제 타입을 그대로 쓰지 않는 것은 그 타입의 주어 종류에
기본값(인물)이 있어서다 — 응답 스키마에서 기본값이 있는 칸은 생략할 수 있는 칸이 되어, 사물에 대한 앎이 인물에 대한 명제로 바뀐다.

문안 지시문이 모델에게 전해야 하는 뜻(검증으로는 잡을 수 없다):
- `knower` 는 아는(믿는) 인물이고, `about.subject` 는 그 앎이 무엇에 대한 것인가의 주어다 — 둘은 다른 칸이다. "둘은 하나가 검을
  가진 것을 안다"는 `knower="둘"`, `about.subject="하나"` 다. 자기 자신에 대한 앎만 두 칸이 같다. 뒤바꾸면 엉뚱한 인물이 아는
  사람이 되고 명제도 다른 사람의 것이 되는데, 둘 다 원고에 나오는 이름이라 검증이 가를 수 없다.
- `knows` 는 원고에서 참인 것을 아는 것, `believes` 는 참인지 원고가 말하지 않거나 거짓인 것을 믿는(추측하는) 것이다. 믿음의
  명제는 원고의 사실과 달라도 그대로 쓴다. 명제는 사실 하나뿐이다 — "A 는 B 가 X 를 안다고 믿는다" 같은 앎에 대한 앎은 내지
  않는다.
- 꿈·상상 장면 안에서 알게 된 것도 낸다. 그 장면이 꿈이라는 것은 사건 쪽이 가진다.
- `about.subject_kind` 와 대상 이름의 규칙은 사실 슬롯의 사실과 같다(아는 개체 힌트에 있는 이름이면 거기 적힌 종류)."""

from pydantic import BaseModel

from api.novel_bible.core.types import QuoteOut
from api.novel_bible.ids import EntityKind, FactKind, KnowledgeKind


class KnownProposition(BaseModel):
    subject: str  # 명제의 주어 — 아는 사람이 아니다
    subject_kind: EntityKind  # 주어가 인물·사물·능력 중 무엇인가
    kind: FactKind
    attribute: str | None  # 속성 이름(attribute) · 관계 이름(relation), 나머지는 null
    value: str  # life: alive|dead, presence: present|departed|gone_for_good, 나머지는 대상·값
    holds: bool  # 소지·능력·관계를 잃거나 끝났으면 false


class ExtractedKnowledge(BaseModel):
    knower: str  # 아는(믿는) 인물 — 명제의 주어가 아니다
    kind: KnowledgeKind
    about: KnownProposition
    quote: QuoteOut  # 앎·믿음이 드러나거나 생기는 구절


class KnowledgeOutput(BaseModel):
    items: list[ExtractedKnowledge]
