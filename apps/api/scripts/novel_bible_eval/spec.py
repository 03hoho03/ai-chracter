"""합성 심기 세트의 명세 — 원고 문단과 그 화에 심은 정답(사건·사실·지식), 그리고 탐침.

정답은 명세 자체다. 원고는 문단 목록이고 화 본문은 문단을 빈 줄로 이은 글이라, 정답이 가리키는 문단 번호(1부터)가 그대로
확정 개정의 블록 차례가 된다. 탐침은 기본 화 뒤에 한 화로 붙였다 지우는 화이고, `depends_on` 은 그 탐침이 기대는 기본 화(짝
사실을 심은 화, 회상 관계가 가리키는 화, 탐침의 개체를 처음 소개한 화)다 — 그중 하나라도 정본에 들지 못하면 그 탐침은 막힐 수
없거나 막히지 않을 수밖에 없어 지표에서 뺀다.

슬롯이 아직 등록부에 없어도 명세는 그 슬롯의 정답을 받는다 — 슬롯이 들어오면 같은 세트로 그 슬롯의 지표가 생긴다."""

from pathlib import Path
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, model_validator

from api.novel_bible.ids import BlockingRule, EventActuality, FactKind, KnowledgeKind, WarningRule
from api.novelize.text import split_paragraphs

ProbeKind = Literal["conflict", "warning", "non_conflict"]
# 비충돌 탐침의 네 갈래 — 규칙 예외 거울, 앞서 찾은 표면, 서사 장치, 규칙을 모르는 이가 쓴 자유 화. 보고서가 갈래마다 따로 센다.
NON_CONFLICT_GROUPS = frozenset({"A", "B", "C", "D"})


class _Spec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PlantedEvent(_Spec):
    paragraphs: list[int]
    actuality: EventActuality = "present"
    present: list[str] = []
    summary: str = ""


class PlantedFact(_Spec):
    """`values` 는 맞다고 칠 값 표기 전부(정규화해서 견준다)."""

    subject: str
    kind: FactKind
    attribute: str | None = None
    values: list[str]
    holds: bool = True
    paragraph: int


class PlantedKnowledge(_Spec):
    knower: str
    kind: KnowledgeKind
    subject: str
    fact_kind: FactKind
    attribute: str | None = None
    values: list[str]
    holds: bool = True
    paragraph: int


class ChapterSpec(_Spec):
    paragraphs: list[str]
    events: list[PlantedEvent] = []
    facts: list[PlantedFact] = []
    knowledge: list[PlantedKnowledge] = []

    @model_validator(mode="after")
    def _paragraphs_in_range(self) -> "ChapterSpec":
        if not self.paragraphs or split_paragraphs(self.body) != self.paragraphs:
            raise ValueError("문단은 비지 않아야 하고, 빈 줄로 이으면 그대로 같은 문단들로 다시 나뉘어야 한다")
        count = len(self.paragraphs)
        pointed = [n for event in self.events for n in event.paragraphs]
        pointed += [fact.paragraph for fact in self.facts] + [known.paragraph for known in self.knowledge]
        if any(not event.paragraphs for event in self.events) or not all(1 <= n <= count for n in pointed):
            raise ValueError(f"정답이 이 화의 문단(1~{count}) 밖을 가리킨다")
        return self

    @property
    def body(self) -> str:
        return "\n\n".join(self.paragraphs)


class ProbeSpec(_Spec):
    """충돌 탐침은 막아야 할 차단 규칙, 경고 기대 탐침은 나야 할 경고 이름을 `expected_rule` 에 둔다. 비충돌 탐침은 규칙이 없고
    `group` 이 네 갈래 중 하나다. 충돌·경고 탐침의 `group` 은 보고서가 종류별로 묶는 이름이다."""

    key: str
    kind: ProbeKind
    group: str
    expected_rule: str | None = None
    depends_on: list[int]
    chapter: ChapterSpec

    @model_validator(mode="after")
    def _rule_fits_kind(self) -> "ProbeSpec":
        allowed: tuple[str, ...] = {
            "conflict": get_args(BlockingRule), "warning": get_args(WarningRule), "non_conflict": (),
        }[self.kind]
        if self.kind == "non_conflict":
            if self.expected_rule is not None or self.group not in NON_CONFLICT_GROUPS:
                raise ValueError("비충돌 탐침은 규칙을 기대하지 않고 갈래가 A·B·C·D 중 하나다")
        elif self.expected_rule not in allowed:
            raise ValueError(f"{self.kind} 탐침이 기대할 수 없는 규칙: {self.expected_rule}")
        return self


class NovelSpec(_Spec):
    """`aliases` 는 이름마다 같은 개체로 칠 다른 이름들 — 매처가 주어·앎 주체 이름을 견줄 때 쓴다."""

    key: str
    aliases: dict[str, list[str]] = {}
    chapters: list[ChapterSpec]
    probes: list[ProbeSpec] = []

    @model_validator(mode="after")
    def _probes_lean_on_existing_chapters(self) -> "NovelSpec":
        if not self.chapters:
            raise ValueError("소설에 기본 화가 없다")
        if any(not 1 <= n <= len(self.chapters) for probe in self.probes for n in probe.depends_on):
            raise ValueError("탐침이 없는 기본 화에 기댄다")
        return self


class EvalSet(_Spec):
    """`note` 는 세트가 합성이라는 것과 출처를 적는 머리말이다(JSON 에 주석이 없어 칸으로 둔다)."""

    note: str
    novels: list[NovelSpec]

    @model_validator(mode="after")
    def _keys_unique(self) -> "EvalSet":
        novel_keys = [novel.key for novel in self.novels]
        probe_keys = [probe.key for novel in self.novels for probe in novel.probes]
        if len(set(novel_keys)) != len(novel_keys) or len(set(probe_keys)) != len(probe_keys):
            raise ValueError("소설 키와 탐침 키는 세트 안에서 겹치지 않아야 한다")
        return self

    def novel(self, key: str) -> NovelSpec:
        return next(novel for novel in self.novels if novel.key == key)


def load_set(path: Path) -> EvalSet:
    return EvalSet.model_validate_json(path.read_text(encoding="utf-8"))
