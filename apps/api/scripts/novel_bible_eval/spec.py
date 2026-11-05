"""합성 심기 세트의 명세 — 원고 문단과 그 화에 심은 정답(사건·사실·지식), 그리고 탐침.

정답은 명세 자체다. 원고는 문단 목록이고 화 본문은 문단을 빈 줄로 이은 글이라, 정답이 가리키는 문단 번호(1부터)가 그대로
확정 개정의 블록 차례가 된다. 탐침은 기본 화 뒤에 한 화로 붙였다 지우는 화이고, `depends_on` 은 그 탐침이 기대는 기본 화(짝
사실을 심은 화, 회상 관계가 가리키는 화, 탐침의 개체를 처음 소개한 화)다 — 그중 하나라도 정본에 들지 못하면 그 탐침은 막힐 수
없거나 막히지 않을 수밖에 없어 지표에서 뺀다.

슬롯이 아직 등록부에 없어도 명세는 그 슬롯의 정답을 받는다 — 슬롯이 들어오면 같은 세트로 그 슬롯의 지표가 생긴다.

소설마다 합성 원작(작품 설정·키워드 노트)과 합성 플레이(채팅 기억 사실 행)를 둘 수 있고, 화마다 장면 구성안을 둘 수 있다 — 심기가
앱이 읽는 행 그대로 심어, 사실 슬롯이 원작·플레이와 다른 곳을 짚는지와 사건 슬롯이 구성안의 회상 표시를 읽는지를 잰다. 원작과
다른 곳·플레이와 다른 곳·회상 관계의 정답은 그 사실·사건 정답에 붙는다."""

from bisect import bisect_right
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, model_validator

from api.chat.memory_facts import fact_key
from api.chat.memory_knowledge import latest_by_key
from api.db.models.chat import ChatMemoryFact, FactAssertedBy, FactTruthStatus
from api.novel_bible.core.keys import normalize_name, predicate_norm
from api.novel_bible.ids import (
    BlockingRule,
    EntityKind,
    EventActuality,
    EventRelationKind,
    FactKind,
    KnowledgeKind,
    WarningRule,
)
from api.novel_bible.rules.blocking import closed_value
from api.novelize.text import split_paragraphs

ProbeKind = Literal["conflict", "warning", "non_conflict"]

# 비충돌 탐침의 세부 종류 — 갈래마다 고정한 목록이다. 보고서가 세부 종류별로 오탐을 묶을 수 있게 하고, 원고 작성자가 목록 밖의
# 종류를 지어내지 않게 한다. 이름은 원고 명세(JSON)에 그대로 적는 값이다.
_MIRROR_SUBKINDS = (  # A — 차단 규칙의 예외를 거울처럼 비춘 화
    "dead_in_flashback",  # 회상 속 죽은 인물의 등장
    "outline_only_flashback",  # 장면 구성안만 회상이라고 한 장면
    "mention_only",  # 말로만 언급됨
    "revival_or_return",  # 되살아남·돌아옴
    "ability_in_belief",  # 믿음 속 능력
    "innate_ability",  # 타고난 능력
    "knowledge_after_fact",  # 사실보다 뒤의 앎
    "false_belief",  # 거짓 믿음
    "same_value_other_spelling",  # 불변 속성의 같은 값 다른 표기
    "immutable_differs_from_source",  # 원작과 다른 불변 속성
)
_SURFACE_SUBKINDS = (  # B — 규칙이 오탐을 낼 만하다고 앞서 찾아 둔 표면
    "scene_exit_then_next_chapter",  # 장면 단위 퇴장 뒤 다음 화 등장
    "dead_in_dream",  # 꿈 속 죽은 인물
    "late_revealed_existing",  # 늦게 드러난 기존 소지·관계
    "temporary_appearance_change",  # 일시 변화한 외형(변장·염색)
)
# C — 규칙 목록이 아니라 소설 서술 기법에서 고른 서사 장치. 앞 아홉이 처음 고정한 것이고, 뒤 열은 웹소설에서 흔해 정본 기억이
# 사망·불변 속성·앎의 순서를 잘못 읽기 쉬운 장치로 더한 것이다.
_DEVICE_SUBKINDS = (
    "epithet_only",  # 호칭·별명·직함으로만 불림
    "retold_from_another_view",  # 다른 인물 시점으로 앞 사건을 다시 서술
    "learned_by_letter_or_message",  # 편지·기록·전언으로 알게 됨
    "speculation_or_rumor",  # 대사 속 추측·소문
    "figure_of_speech",  # 비유·관용 표현
    "plan_or_hypothetical",  # 계획·가정·조건
    "character_lie",  # 인물의 거짓말
    "time_skip_summary",  # 시간 건너뛰기 요약
    "identity_or_birth_reveal",  # 정체·출생 반전
    "body_possession",  # 빙의 — 원래 몸 주인이 죽은 뒤 그 이름으로 계속 등장
    "regression",  # 회귀 — 주인공이 죽고 과거로 돌아와 등장
    "returned_as_ghost_or_undead",  # 유령·언데드로 돌아온 인물의 등장
    "foreknowledge",  # 회귀자·예언자의 미래 앎
    "appearance_explained_later",  # 같은 화 안에서 등장이 먼저, 해명이 나중
    "death_retold_in_retrospect",  # 사망을 회고로 다시 서술
    "same_name_other_thing",  # 같은 이름의 다른 사물
    "two_valued_immutable",  # 한 술어에 값이 둘인 불변 속성(오드아이)
    "ending_told_first",  # 화 첫머리에 결말을 먼저 말하는 서술
    "letter_grade_immutable",  # 등급 A·B 같은 글자 값의 불변 속성
)
NON_CONFLICT_SUBKINDS: dict[str, tuple[str, ...]] = {
    "A": _MIRROR_SUBKINDS, "B": _SURFACE_SUBKINDS, "C": _DEVICE_SUBKINDS,
}
# 비충돌 탐침의 네 갈래 — 위 셋과, 규칙·예외 목록을 받지 않은 작성자가 쓴 자유 화(D). 자유 화는 세부 종류가 없다. 보고서가
# 갈래마다 따로 센다.
NON_CONFLICT_GROUPS = frozenset({*NON_CONFLICT_SUBKINDS, "D"})
# 닫힌 값 불변 속성 모순 — 기대 갈래와 두 값(`ClosedPair`)을 함께 적는 충돌 규칙.
_CLOSED_RULE = "immutable_attribute_mismatch"


class _Spec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PlantedRelation(_Spec):
    """회상 사건이 앞 화의 주선 사건과 어떤 앞뒤인가. `chapter` 는 대상 사건의 기본 화 번호, `event` 는 그 화 사건 정답의 차례
    (문단·화 번호처럼 1부터). 대상은 주선 사건이어야 한다 — 사건 슬롯이 문안에 싣는 앞 화 사건 목록이 주선 사건뿐이라, 회상을
    가리키는 관계는 모델이 낼 수 없다. 주선(`present`) 정답은 회상 장면에서 시작할 수 없으므로(화 검증) 앱도 주선으로 저장한다."""

    kind: EventRelationKind
    chapter: int
    event: int


class PlantedEvent(_Spec):
    paragraphs: list[int]
    actuality: EventActuality = "present"
    present: list[str] = []
    summary: str = ""
    relation: PlantedRelation | None = None

    @model_validator(mode="after")
    def _relation_is_for_a_flashback(self) -> "PlantedEvent":
        if self.relation is not None and self.actuality != "flashback":
            raise ValueError("회상 관계는 회상 사건 정답에만 둔다(사건 슬롯이 회상이 아닌 사건의 관계를 버린다)")
        return self


def _aliases_need_an_attribute(attribute: str | None, aliases: list[str]) -> None:
    if aliases and attribute is None:
        raise ValueError("속성·관계 이름의 다른 표기는 그 이름이 있는 정답에만 둔다")


class SourceDifference(_Spec):
    """원작과 다른 사실의 정답 — 원작 글의 표지(작품 설정 `S`, 키워드 노트 `K1`·`K2` … 심은 차례)와 그 글에서 그대로 옮긴
    구절. 사실 슬롯 출력의 같은 이름 칸과 같은 꼴이다."""

    label: str
    quote: str


class PlantedFact(_Spec):
    """`values` 는 맞다고 칠 값 표기 전부(정규화해서 견준다), `attribute_aliases` 는 속성·관계 이름의 다른 허용 표기다.
    `subject_kind`·`immutable` 은 사실 슬롯 출력의 같은 이름 칸과 같은 뜻이다 — 불변 표시는 속성에만 둔다(슬롯 검증이 속성이 아닌
    불변 사실을 버리므로 그런 정답은 맞힐 수 없다). `play_difference` 는 이 사실과 다른 플레이 행의 차례(소설의 `play`, 1부터)다."""

    subject: str
    subject_kind: EntityKind = "character"
    kind: FactKind
    attribute: str | None = None
    attribute_aliases: list[str] = []
    values: list[str]
    holds: bool = True
    immutable: bool = False
    paragraph: int
    source_difference: SourceDifference | None = None
    play_difference: int | None = None

    @model_validator(mode="after")
    def _immutable_is_an_attribute(self) -> "PlantedFact":
        if self.immutable and self.kind != "attribute":
            raise ValueError("불변 표시는 속성 정답에만 둔다")
        _aliases_need_an_attribute(self.attribute, self.attribute_aliases)
        return self


class PlantedKnowledge(_Spec):
    """`subject_kind` 는 명제 주어의 종류(인물·사물·능력)다 — 개체가 (종류, 이름)으로 갈려, 종류가 다르면 같은 이름이라도 다른
    개체·다른 명제 키가 되므로 정답마다 적는다."""

    knower: str
    kind: KnowledgeKind
    subject: str
    subject_kind: EntityKind
    fact_kind: FactKind
    attribute: str | None = None
    attribute_aliases: list[str] = []
    values: list[str]
    holds: bool = True
    paragraph: int

    @model_validator(mode="after")
    def _aliases_name_an_attribute(self) -> "PlantedKnowledge":
        _aliases_need_an_attribute(self.attribute, self.attribute_aliases)
        return self


class SceneSpec(_Spec):
    """장면 구성안의 장면 하나 — 제목, 회상 표시, 그 장면이 시작하는 문단 번호. 장면은 다음 장면의 시작 문단 앞까지다."""

    title: str
    flashback: bool = False
    start: int


class ChapterSpec(_Spec):
    """`scenes` 가 None 이면 장면 구성안이 없는 화다 — 앱이 화 전체를 장면 하나로 읽는다. 사건의 장면은 첫 문단의 장면이고,
    사건 슬롯은 구성안이 회상이라고 한 장면에서 시작하는 `present` 사건을 늘 `flashback` 으로 저장한다 — 그런 사건을 `present`
    로 적은 정답은 어느 어댑터도 맞힐 수 없어 받지 않는다."""

    paragraphs: list[str]
    scenes: list[SceneSpec] | None = None
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
        if self.scenes is not None:
            starts = [scene.start for scene in self.scenes]
            if not starts or starts[0] != 1 or starts != sorted(set(starts)) or starts[-1] > count:
                raise ValueError("장면 구성안은 첫 문단에서 시작하고, 장면 시작 문단은 화 안에서 오르는 차례여야 한다")
            if any(
                event.actuality == "present" and self.scenes[self.scene_index(min(event.paragraphs))].flashback
                for event in self.events
            ):
                raise ValueError("주선 사건 정답이 회상 장면에서 시작한다 — 사건 슬롯은 그 사건을 회상으로 저장한다")
        return self

    def scene_index(self, paragraph: int) -> int:
        """그 문단이 든 장면의 차례(0부터). 장면은 시작 문단부터 다음 장면의 시작 문단 앞까지다."""
        assert self.scenes is not None
        return bisect_right([scene.start for scene in self.scenes], paragraph) - 1

    @property
    def body(self) -> str:
        return "\n\n".join(self.paragraphs)


class ClosedPair(_Spec):
    """닫힌 값 불변 속성 모순 탐침이 기대하는 갈래와 두 값(앞 화에 심은 값, 탐침의 값 — 심은 표기 그대로). 갈래는 규칙의 닫힌 값
    판정(`closed_value`)이 내는 꼴이다: 숫자는 `number:단위`(단위가 없으면 `number:`), 사전 값은 `enum:범주`(혈액형·색). 그 판정으로
    두 값이 같은 갈래의 다른 값으로 읽혀야 한다 — 아니면 규칙이 막을 수 없는 탐침이라 차단 재현율의 분모를 그르친다."""

    category: str
    values: tuple[str, str]

    @model_validator(mode="after")
    def _the_rule_reads_a_clash(self) -> "ClosedPair":
        read = [closed_value(normalize_name(value)) for value in self.values]
        if any(value is None or value[0] != self.category for value in read) or read[0] == read[1]:
            raise ValueError(f"두 값이 닫힌 값 갈래 {self.category} 의 서로 다른 값으로 읽히지 않는다")
        return self


class ProbeSpec(_Spec):
    """충돌 탐침은 막아야 할 차단 규칙, 경고 기대 탐침은 나야 할 경고 이름을 `expected_rule` 에 둔다. 닫힌 값 불변 속성 모순을
    기대하는 충돌 탐침은 `closed` 에 기대 갈래와 두 값을 함께 둔다. 비충돌 탐침은 규칙이 없고 `group` 이 네 갈래 중 하나이며,
    자유 화(D)가 아니면 `subkind` 가 그 갈래 목록의 세부 종류 하나다. 충돌·경고 탐침의 `group` 은 보고서가 종류별로 묶는 이름이라
    세부 종류를 따로 두지 않는다."""

    key: str
    kind: ProbeKind
    group: str
    subkind: str | None = None
    expected_rule: str | None = None
    closed: ClosedPair | None = None
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
            if self.subkind not in NON_CONFLICT_SUBKINDS.get(self.group, (None,)):
                raise ValueError(f"갈래 {self.group} 탐침의 세부 종류가 아니다: {self.subkind}(자유 화는 세부 종류가 없다)")
        elif self.expected_rule not in allowed:
            raise ValueError(f"{self.kind} 탐침이 기대할 수 없는 규칙: {self.expected_rule}")
        elif self.subkind is not None:
            raise ValueError("충돌·경고 기대 탐침은 세부 종류를 두지 않는다 — 종류는 group 에 적는다")
        if (self.expected_rule == _CLOSED_RULE) != (self.closed is not None):
            raise ValueError("닫힌 값 불변 속성 모순을 기대하는 탐침만, 그리고 반드시 기대 갈래와 두 값을 둔다")
        return self


class SourceSpec(_Spec):
    """합성 원작 — 작품 종류·이름·작품 설정 글·작품 버전 단위 키워드 노트. 캐릭터 원작의 작품 설정은 앱이 `이름: …` 줄을 앞에
    붙여 읽는다. 노트는 심은 차례대로 표지 `K1`·`K2` … 를 받는다 — 빈 노트는 원작 슬롯이 건너뛰어 뒤 노트의 표지가 밀리므로
    받지 않는다."""

    kind: Literal["character", "story"]
    name: str
    setting: str
    notes: list[str] = []

    @model_validator(mode="after")
    def _notes_have_text(self) -> "SourceSpec":
        if any(not note.strip() for note in self.notes):
            raise ValueError("빈 키워드 노트는 표지를 밀어 원작 차이 정답이 엇갈린다")
        return self

    def texts(self) -> dict[str, str]:
        """표지마다 원작 글 — 작품 설정 `S`(비면 없음), 노트 `K1`·`K2` …(사실 슬롯이 문안에 싣는 표지와 같다)."""
        texts = {"S": self.setting} if self.setting.strip() else {}
        texts.update({f"K{number}": note for number, note in enumerate(self.notes, start=1)})
        return texts


class PlayRow(_Spec):
    """합성 채팅 기억 사실 한 행 — 관계(`object` 가 대상 인물)나 속성(`attribute`) 중 하나. `visible_from` 은 그 행이 접힌 화다 —
    심기가 그 화 구간 안에서 접힌 스냅숏에 넣어, 그 화부터 화 끝까지 접힌 플레이 사실로 실린다."""

    visible_from: int
    subject: str
    object: str | None = None
    attribute: str | None = None
    value: str
    truth_status: FactTruthStatus = "confirmed"
    asserted_by: FactAssertedBy = "user"

    @model_validator(mode="after")
    def _relation_or_attribute(self) -> "PlayRow":
        if (self.object is None) == (self.attribute is None):
            raise ValueError("플레이 행은 대상(관계)과 속성 중 하나만 둔다")
        return self

    @property
    def chat_kind(self) -> str:
        return "fact" if self.object is None else "relation"

    @property
    def chat_fact_key(self) -> str:
        """채팅 기억과 같은 규칙의 사실 키 — 앱은 이 키마다 이긴 행 하나만 싣는다."""
        return fact_key(self.chat_kind, self.subject, self.object or self.attribute)


class NovelSpec(_Spec):
    """`aliases` 는 이름마다 같은 개체로 칠 다른 이름들 — 매처가 주어·앎 주체 이름을 견줄 때 쓴다. `source`·`play` 는 합성
    원작과 합성 플레이다. 플레이 행은 방에 들고 방은 원작 버전에 묶이므로, 플레이는 원작이 있을 때만 둔다."""

    key: str
    aliases: dict[str, list[str]] = {}
    source: SourceSpec | None = None
    play: list[PlayRow] = []
    chapters: list[ChapterSpec]
    probes: list[ProbeSpec] = []

    @model_validator(mode="after")
    def _probes_lean_on_existing_chapters(self) -> "NovelSpec":
        if not self.chapters:
            raise ValueError("소설에 기본 화가 없다")
        if any(not 1 <= n <= len(self.chapters) for probe in self.probes for n in probe.depends_on):
            raise ValueError("탐침이 없는 기본 화에 기댄다")
        if self.play and self.source is None:
            raise ValueError("플레이 행은 원작이 있는 소설에만 둔다")
        if any(not 1 <= row.visible_from <= len(self.chapters) for row in self.play):
            raise ValueError("플레이 행이 없는 기본 화에서 접힌다")
        return self

    @model_validator(mode="after")
    def _answers_point_at_what_the_slots_are_shown(self) -> "NovelSpec":
        """회상 관계는 그 화 앞 기본 화의 주선 사건(탐침이면 기대는 화의 것), 원작 차이는 있는 원작 글의 구절, 플레이 차이는 그
        화 끝까지 보이는 플레이 행 중 앱이 싣는 행(`play_shown`)을 가리켜야 한다 — 아니면 슬롯 문안에 그 표지가 없어 맞힐 수 없는
        정답이다."""
        texts = self.source.texts() if self.source is not None else {}
        for ordinal, chapter, leans_on in self._numbered_chapters():
            for event in chapter.events:
                if (relation := event.relation) is None:
                    continue
                reachable = 1 <= relation.chapter < ordinal and (leans_on is None or relation.chapter in leans_on)
                targets = self.chapters[relation.chapter - 1].events if reachable else []
                if not 1 <= relation.event <= len(targets) or targets[relation.event - 1].actuality != "present":
                    raise ValueError(f"{ordinal}화 회상 관계가 앞 화(탐침이면 기대는 화)의 주선 사건을 가리키지 않는다")
            for fact in chapter.facts:
                differs = fact.source_difference
                if differs is not None and not (differs.quote.strip() and differs.quote in texts.get(differs.label, "")):
                    raise ValueError(f"{ordinal}화 원작 차이가 원작 글 {differs.label} 의 구절이 아니다")
                row = fact.play_difference
                if row is not None and not (1 <= row <= len(self.play) and self.play[row - 1].visible_from <= ordinal):
                    raise ValueError(f"{ordinal}화 플레이 차이가 그 화까지 보이는 플레이 행을 가리키지 않는다")
                if row is not None and row - 1 not in self.play_shown(ordinal):
                    raise ValueError(f"{ordinal}화 플레이 차이가 같은 키의 다른 행에 진 행을 가리킨다 — 앱은 키마다 이긴 행만 싣는다")
        return self

    @model_validator(mode="after")
    def _probes_lean_on_their_people_and_pairs(self) -> "NovelSpec":
        """탐침은 그 개체를 처음 소개한 기본 화와 짝 사실이 든 기본 화에도 기대야 한다(회상 관계가 가리키는 화는 위에서 본다) —
        빠지면 그 화가 정본에 못 든 반복에서도 탐침이 표본에 남아 오탐이 0 쪽으로 기운다. 정답에서 구할 수 있는 만큼만 본다.
        개체는 정답에 나오는 이름(사건 등장 인물, 사실 주어, 앎 주체, 지식 명제 주어 — 별칭은 그 이름으로)이다. 짝 사실은 탐침의
        사실·지식 명제와 주어·종류·술어가 같은(소지·능력은 같은 것을 가리키는) 기본 화 사실, 그리고 탐침 사건에 나오는 인물의
        생사·출입 사실이다. 사용처럼 명세에 정답 칸이 없는 짝은 작성자 몫이다."""
        names = {normalize_name(alias): normalize_name(name) for name, aliases in self.aliases.items() for alias in aliases}

        def entity(text: str) -> str:
            return names.get(normalize_name(text), normalize_name(text))

        for probe in self.probes:
            chapter = probe.chapter
            wanted = {
                slot
                for fact in chapter.facts
                for slot in _fact_slots(entity(fact.subject), fact.kind, fact.attribute, fact.values)
            }
            wanted |= {
                slot
                for known in chapter.knowledge
                for slot in _fact_slots(entity(known.subject), known.fact_kind, known.attribute, known.values)
            }
            wanted |= {
                (entity(person), kind, kind, "")
                for event in chapter.events
                for person in event.present
                for kind in ("life", "presence")
            }
            people = _named(chapter, entity)
            required: set[int] = set()
            for ordinal, base in enumerate(self.chapters, start=1):
                held = {
                    slot
                    for fact in base.facts
                    for slot in _fact_slots(entity(fact.subject), fact.kind, fact.attribute, fact.values)
                }
                introduced = people & _named(base, entity)
                if held & wanted or introduced:
                    required.add(ordinal)
                people -= introduced
            if missing := sorted(required - set(probe.depends_on)):
                raise ValueError(
                    f"탐침 {probe.key} 이 기대는 화에 {missing} 화가 빠졌다 — 탐침의 개체를 처음 소개한 화와 짝 사실이 든 화에 기댄다"
                )
        return self

    def play_shown(self, ordinal: int) -> frozenset[int]:
        """그 화 끝까지 접힌 플레이 행 중 앱이 싣는 행의 차례(0부터) — 키마다 이긴 행 하나. 심기가 접는 차례(보이기 시작하는 화
        순, 같은 화 안은 명세 차례)로 놓고 앱의 키별 이김 규칙(`latest_by_key` — 마지막 행, 단 같은 값을 반증한 앞 행이 있으면 그
        행)을 그대로 돌린다."""
        folded = sorted(
            (index for index, row in enumerate(self.play) if row.visible_from <= ordinal),
            key=lambda index: self.play[index].visible_from,
        )
        rows = [
            ChatMemoryFact(fact_key=self.play[index].chat_fact_key, value=self.play[index].value,
                           truth_status=self.play[index].truth_status)
            for index in folded
        ]
        return frozenset(folded[order] for order, _ in latest_by_key(rows))

    def _numbered_chapters(self) -> Iterator[tuple[int, ChapterSpec, list[int] | None]]:
        """(화 번호, 화, 탐침이면 기대는 기본 화). 탐침은 기본 화 뒤 한 화로 붙는다."""
        for ordinal, chapter in enumerate(self.chapters, start=1):
            yield ordinal, chapter, None
        for probe in self.probes:
            yield len(self.chapters) + 1, probe.chapter, probe.depends_on


def _fact_slots(subject: str, kind: FactKind, attribute: str | None, values: list[str]) -> set[tuple[str, str, str, str]]:
    """짝을 찾는 사실 자리 — (주어, 종류, 술어, 소지·능력이면 그 것). 생사·출입·속성·관계는 값이 달라도 짝이다."""
    head = (subject, kind, predicate_norm(kind, attribute))
    if kind in ("possession", "ability"):
        return {(*head, normalize_name(value)) for value in values}
    return {(*head, "")}


def _named(chapter: ChapterSpec, entity: Callable[[str], str]) -> set[str]:
    """화 정답에 나오는 개체 이름 — 사건 등장 인물, 사실 주어, 앎 주체, 지식 명제 주어."""
    names = {person for event in chapter.events for person in event.present}
    names |= {fact.subject for fact in chapter.facts}
    names |= {name for known in chapter.knowledge for name in (known.knower, known.subject)}
    return {entity(name) for name in names}


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
