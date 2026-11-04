"""사실 슬롯의 모델 출력 꼴(구조화 호출의 응답 스키마).

길이·범위 제약을 두지 않는다 — 공급자마다 스키마로 받는 제약이 달라, 상한과 범위는 검증이 항목 단위로 버린다. 값 목록 칸은
`ids.py` 의 Literal 을 써서 DB CHECK 와 같은 출처에서 나온다. `value` 는 종류마다 허용 값이 달라 글로 받고, 생사·출입 값은 검증이
그 Literal 로 본다.

문안 지시문이 모델에게 전해야 하는 뜻(검증으로는 잡을 수 없다):
- 생사(`life`)는 생사 자체가 서술될 때만 낸다. 장면에 있다는 것만으로 `alive` 를 내면, 그 사실이 되살아남으로 읽혀 사망 뒤 등장
  검사가 꺼진다. 장면에 있음은 출입 `present` 로 내고, 돌아왔다고 서술될 때만 `onset` 이 참이다.
- `gone_for_good` 은 원고가 영구 퇴장으로 서술한 것(추방·사라짐·"다시는 돌아오지 않았다")뿐이다. 그 장면을 떠난 것은
  `departed` 에 `scope="scene"`, 여행·이사처럼 돌아올 수 있는 떠남은 `departed` 에 `scope="from_here"`.
- `onset` 은 이 장면에서 상태가 시작됐다고 서술됐을 때만 참이다. 이미 지니던 것·이미 그랬던 것을 여기서 처음 서술했으면
  거짓이다 — 늦게 드러난 기존 상태를 "얻기 전 사용"·"일어나기 전 앎"으로 막지 않게 하는 칸이다.
- `subject_kind` 는 주어가 인물·사물·능력 중 무엇인가다. 개체는 (종류, 이름)으로 갈려, 인물을 사물로 내면 같은 이름의 다른
  개체가 생기고 그 사실은 그 인물의 상태에서 빠진다. 아는 개체 힌트에 있는 이름이면 거기 적힌 종류를 그대로 쓰게 해야 한다."""

from pydantic import BaseModel

from api.novel_bible.core.types import QuoteOut
from api.novel_bible.ids import EntityKind, FactKind, FactScope


class SourceDifference(BaseModel):
    label: str  # 원작 글의 표지(S 는 작품 설정, K1 … 은 키워드 노트)
    quote: str  # 그 글에서 그대로 옮긴 구절


class PlayDifference(BaseModel):
    ref: str  # 플레이 사실 목록의 표지(P1 …)


class ExtractedFact(BaseModel):
    subject: str
    subject_kind: EntityKind  # 주어가 인물·사물·능력 중 무엇인가
    kind: FactKind
    attribute: str | None  # 속성 이름(attribute) · 관계 이름(relation), 나머지는 null
    value: str  # life: alive|dead, presence: present|departed|gone_for_good, 나머지는 대상·값
    holds: bool  # 소지·능력·관계를 잃거나 끝났으면 false
    immutable: bool  # 바뀔 수 없는 속성(attribute 만)
    # 이 장면에서 상태가 시작됨(얻음·배움·일어남·돌아옴) — 이미 참이던 상태를 여기서 처음 서술했으면 false
    onset: bool
    scope: FactScope
    quote: QuoteOut
    source_difference: SourceDifference | None
    play_difference: PlayDifference | None


class FactsOutput(BaseModel):
    facts: list[ExtractedFact]
