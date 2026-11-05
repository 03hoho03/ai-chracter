"""결정적 매처 — 추출 제안이 심은 정답을 맞혔는가. 모델을 부르지 않는다.

- 사건: 문단이 겹치고 현실성이 같다.
- 사실: 주어 종류(인물·사물·능력)와 주어 이름(또는 그 별칭)이 같고, 사실 종류(생사·출입·소지·능력·속성·관계)가 같고, 속성·관계
  이름이 명세의 이름이나 그 다른 표기 중 하나이고, 값이 명세의 허용 표기 중 하나이고, 유지 여부와 불변 표시가 같다. 주어
  종류까지 보는 것은 앱이 개체를 (종류, 정규 이름)으로 가르기 때문이다 — 같은 이름을 다른 종류로 낸 명제는 앱에서 다른 개체의
  명제라 그 인물의 차단 비교에 쓰이지 않으므로, 맞음으로 세면 재현율이 부푼다. 제안 하나가 원자 명제 하나다. 불변 표시까지 보는
  것은 그 표시가 불변 속성 불일치 차단(`immutable_attribute_mismatch`)이 읽을 사실인지를 정해서다 — 바뀌는 속성을 불변으로 내면
  다른 화에서 값이 바뀐 것을 막고, 불변 속성을 바뀌는 것으로 내면 그 충돌을 놓친다.
- 지식: 앎 주체·앎 종류가 같고 명제가 위 사실 규칙으로 맞는다(앎 주체는 앱에서 늘 인물이다).
- 회상 관계: 맞춘 회상 사건이 낸 관계의 종류가 같고, 대상 블록이 대상 화에서 추출된 사건 중 심은 대상 사건과 짝인 사건의
  블록이다 — 앱은 그 화에 저장된(=추출된) 주선 사건마다 앞 차례 사건이 덮지 않는 첫 블록을 대상 블록으로 주므로
  (`relation_anchor`), 블록을 그 규칙으로 추출 사건에 되풀고 그 사건이 사건 매처로 대상 정답과 짝인지 본다. 추출 경계가 정답
  경계와 달라도 바른 사건을 짚으면 맞고, 대상 블록이 대상 정답의 문단 안에 있어도 다른 사건의 블록이면 틀리다.
- 각색 후보: 맞춘 사실이 심은 차이의 원작 글(작품 설정·그 차례의 노트)이나 플레이 행을 근거로 단다. 노트·플레이 행은 심기가
  돌려준 행 id 로 되짚는다.

이름·값은 코어가 개체·안정 키를 만들 때와 같은 정규화로 견준다. 정답 하나에는 제안 하나만 대응한다(먼저 맞는 것)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from api.novel_bible.core.keys import normalize_name, predicate_norm
from api.novel_bible.core.types import Proposal, Proposition, SideQuote

from novel_bible_eval.run import ChapterOutcome
from novel_bible_eval.spec import PlantedEvent, PlantedFact, PlantedKnowledge, relation_anchor

Aliases = Mapping[str, Sequence[str]]


@dataclass(frozen=True)
class ExtractedRelation:
    kind: str
    target_block: str


@dataclass(frozen=True)
class ExtractedEvent:
    paragraphs: frozenset[int]
    actuality: str
    relations: tuple[ExtractedRelation, ...] = ()


@dataclass(frozen=True)
class ExtractedFact:
    proposition: Proposition
    immutable: bool = False
    side_quotes: tuple[SideQuote, ...] = ()


@dataclass(frozen=True)
class ExtractedKnowledge:
    knower: str
    kind: str
    proposition: Proposition


@dataclass(frozen=True)
class Extracted:
    events: tuple[ExtractedEvent, ...]
    facts: tuple[ExtractedFact, ...]
    knowledge: tuple[ExtractedKnowledge, ...]


def extracted(outcome: ChapterOutcome) -> Extracted:
    """확정 하나의 성공한 작업 제안에서 매처가 읽는 꼴만 꺼낸다. 사건의 블록은 개정의 차례로 문단 번호가 된다. 회상 관계는 그
    관계를 낸 사건에 붙인다(대상은 블록 id 그대로 — 다른 화의 블록이라 화 결과를 함께 봐야 푼다)."""
    order = {block: number for number, block in enumerate(outcome.block_ids, start=1)}
    events: list[ExtractedEvent] = []
    facts: list[ExtractedFact] = []
    knowledge: list[ExtractedKnowledge] = []
    for job in outcome.jobs:
        if job.proposal is None:
            continue
        items = Proposal.model_validate(job.proposal).items
        relations: dict[str, list[ExtractedRelation]] = {}
        for item in items:
            if item.table == "event_relation":
                relations.setdefault(str(item.fields.get("event")), []).append(
                    ExtractedRelation(str(item.fields.get("relation")), str(item.fields.get("to_anchor_block_id")))
                )
        for item in items:
            if item.table == "event":
                paragraphs = frozenset(order[str(block)] for block in item.covers_blocks if str(block) in order)
                events.append(
                    ExtractedEvent(paragraphs, str(item.fields.get("actuality", "present")),
                                   tuple(relations.get(item.local_key, ())))
                )
            elif item.table == "fact" and item.proposition is not None:
                facts.append(ExtractedFact(item.proposition, item.fields.get("immutable") is True, item.side_quotes))
            elif item.table == "knowledge" and item.proposition is not None and item.names.get("knower"):
                knower = item.names["knower"][0].name
                knowledge.append(ExtractedKnowledge(knower, str(item.fields.get("kind")), item.proposition))
    return Extracted(tuple(events), tuple(facts), tuple(knowledge))


def _same(name: str, planted: str, aliases: Aliases) -> bool:
    return normalize_name(name) in {normalize_name(n) for n in (planted, *aliases.get(planted, ()))}


def _proposition_fits(
    proposition: Proposition, kind: str, attributes: Sequence[str | None], values: Sequence[str], holds: bool
) -> bool:
    """`attributes` 는 명세의 속성·관계 이름과 그 다른 표기들이다."""
    return (
        proposition.kind == kind
        and predicate_norm(proposition.kind, proposition.attribute)
        in {predicate_norm(proposition.kind, attribute) for attribute in attributes}
        and normalize_name(proposition.value) in {normalize_name(value) for value in values}
        and proposition.holds == holds
    )


def paired_events(planted: Sequence[PlantedEvent], found: Sequence[ExtractedEvent]) -> dict[int, int]:
    """정답 차례 → 대응한 제안 차례."""
    paired: dict[int, int] = {}
    for number, event in enumerate(planted):
        hit = next(
            (
                index for index, candidate in enumerate(found)
                if index not in paired.values() and candidate.actuality == event.actuality
                and candidate.paragraphs & set(event.paragraphs)
            ),
            None,
        )
        if hit is not None:
            paired[number] = hit
    return paired


def matched_events(planted: Sequence[PlantedEvent], found: Sequence[ExtractedEvent]) -> int:
    return len(paired_events(planted, found))


def _fact_fits(fact: PlantedFact, candidate: ExtractedFact, aliases: Aliases) -> bool:
    return (
        candidate.proposition.subject_kind == fact.subject_kind
        and _same(candidate.proposition.subject, fact.subject, aliases)
        and _proposition_fits(
            candidate.proposition, fact.kind, (fact.attribute, *fact.attribute_aliases), fact.values, fact.holds
        )
        and candidate.immutable == fact.immutable
    )


def matched_facts(planted: Sequence[PlantedFact], found: Sequence[ExtractedFact], aliases: Aliases) -> int:
    used: set[int] = set()
    for fact in planted:
        hit = next(
            (index for index, candidate in enumerate(found) if index not in used and _fact_fits(fact, candidate, aliases)),
            None,
        )
        if hit is not None:
            used.add(hit)
    return len(used)


def _target_event(found: Sequence[ExtractedEvent], paragraph: int) -> int | None:
    """대상 블록(문단)을 앱 대상 규칙으로 그 화의 추출 주선 사건 차례로 되푼다 — 그 블록을 대상으로 받는 사건이 없으면 None."""
    return next(
        (index for index, event in enumerate(found)
         if event.actuality == "present" and relation_anchor(found, index) == paragraph),
        None,
    )


def relation_counts(
    planted: Sequence[PlantedEvent], found: Sequence[ExtractedEvent], targets: Mapping[str, tuple[int, int]],
    chapters: Sequence[Sequence[PlantedEvent]], found_chapters: Mapping[int, Sequence[ExtractedEvent]],
) -> tuple[int, int]:
    """(관계가 맞은 수, 맞춘 회상 사건의 심은 관계 수). `targets` 는 블록 id → (화 번호, 문단 번호) — 같은 소설·반복의 기본
    화 결과에서 푼다. `chapters` 는 기본 화마다 사건 정답, `found_chapters` 는 화 번호 → 그 화에서 추출·저장된 사건이다. 관계가
    맞으려면 그 회상 사건에 대응한 제안이 같은 종류의 관계를 내고, 그 대상 블록을 대상 화의 추출 사건으로 되풀면 대상 정답과
    짝인 사건이어야 한다."""
    right = total = 0
    for number, hit in paired_events(planted, found).items():
        relation = planted[number].relation
        if relation is None:
            continue
        total += 1
        prior = found_chapters.get(relation.chapter, ())
        wanted = paired_events(chapters[relation.chapter - 1], prior).get(relation.event - 1)
        right += wanted is not None and any(
            out.kind == relation.kind
            and (place := targets.get(out.target_block)) is not None
            and place[0] == relation.chapter
            and _target_event(prior, place[1]) == wanted
            for out in found[hit].relations
        )
    return right, total


def _points_at(fact: PlantedFact, side: SideQuote, play_rows: Sequence[str], notes: Sequence[str]) -> bool:
    """근거가 그 사실에 심은 차이의 원작 글·플레이 행인가. 원작 표지는 작품 설정 `S`, 노트 `K1`·`K2` …(심은 차례)다."""
    if fact.play_difference is not None and side.origin == "play":
        return str(side.chat_memory_fact_id) == play_rows[fact.play_difference - 1]
    if (source := fact.source_difference) is None or side.origin != "source_canon":
        return False
    if source.label == "S":
        return side.source_field == "work_setting"
    return side.source_field == "keyword_note" and str(side.keyword_note_id) == notes[int(source.label[1:]) - 1]


def difference_counts(
    planted: Sequence[PlantedFact], found: Sequence[ExtractedFact], aliases: Aliases, *, origin: str,
    play_rows: Sequence[str], notes: Sequence[str],
) -> tuple[int, int]:
    """(맞춘 차이, 심은 차이) — `origin` 은 `source_canon`(원작) 또는 `play`. 차이는 그 사실 정답에 대응하는 제안 사실이 그
    차이의 원작 글·플레이 행을 근거로 달았을 때 맞다."""
    wanted = [
        fact for fact in planted
        if (fact.source_difference if origin == "source_canon" else fact.play_difference) is not None
    ]
    used: set[int] = set()
    for fact in wanted:
        hit = next(
            (
                index for index, candidate in enumerate(found)
                if index not in used and _fact_fits(fact, candidate, aliases)
                and any(side.origin == origin and _points_at(fact, side, play_rows, notes)
                        for side in candidate.side_quotes)
            ),
            None,
        )
        if hit is not None:
            used.add(hit)
    return len(used), len(wanted)


def _skeleton(planted: PlantedKnowledge, candidate: ExtractedKnowledge) -> bool:
    """이름을 뺀 골격 — 앎 종류와 명제의 종류·술어(다른 표기 포함)·값·유지 여부."""
    return candidate.kind == planted.kind and _proposition_fits(
        candidate.proposition, planted.fact_kind, (planted.attribute, *planted.attribute_aliases), planted.values,
        planted.holds,
    )


def _direction(planted: PlantedKnowledge, candidate: ExtractedKnowledge, aliases: Aliases) -> str | None:
    """명제 주어는 그 자리에 와야 할 개체의 종류로 냈을 때만 그 개체다 — 앱이 개체를 (종류, 정규 이름)으로 가른다. 바른 짝과
    앎 주체만 틀린 짝은 심은 명제 주어의 종류, 뒤바뀜은 명제 주어 자리에 온 심은 앎 주체의 종류(늘 인물)다. 어느 것도 아니면
    방향 오류 분모에 들지 않는다."""
    knower, subject, kind = candidate.knower, candidate.proposition.subject, candidate.proposition.subject_kind
    names_the_subject = kind == planted.subject_kind and _same(subject, planted.subject, aliases)
    if _same(knower, planted.knower, aliases) and names_the_subject:
        return "correct"
    if kind == "character" and _same(knower, planted.subject, aliases) and _same(subject, planted.knower, aliases):
        return "swapped"
    if names_the_subject:
        return "wrong_knower"
    return None


def matched_knowledge(planted: Sequence[PlantedKnowledge], found: Sequence[ExtractedKnowledge], aliases: Aliases) -> int:
    used: set[int] = set()
    for knowledge in planted:
        hit = next(
            (
                index for index, candidate in enumerate(found)
                if index not in used and _skeleton(knowledge, candidate)
                and _direction(knowledge, candidate, aliases) == "correct"
            ),
            None,
        )
        if hit is not None:
            used.add(hit)
    return len(used)


def _planted_order(knowledge: PlantedKnowledge) -> tuple[Any, ...]:
    return (knowledge.knower, knowledge.subject, knowledge.kind, knowledge.fact_kind, knowledge.attribute or "",
            tuple(knowledge.values), knowledge.holds)


def _found_order(candidate: ExtractedKnowledge) -> tuple[Any, ...]:
    proposition = candidate.proposition
    return (candidate.knower, candidate.kind, proposition.subject, proposition.kind, proposition.attribute or "",
            proposition.value, proposition.holds)


def direction_counts(
    planted: Sequence[PlantedKnowledge], found: Sequence[ExtractedKnowledge], aliases: Aliases
) -> tuple[int, int]:
    """(분모 D, 분자 E). D 는 골격이 같은 심은 지식(앎 주체 ≠ 명제 주어)에 대응한 제안 — 이름이 바르거나, 앎 주체와 명제 주어가
    뒤바뀌었거나, 명제 주어는 맞고 앎 주체만 틀린 것. E 는 D 중 뒤의 둘이라 E ⊂ D 가 정의로 성립한다. 정답 하나에는 제안 하나만
    대응한다. 자기 자신에 대한 앎은 뒤바뀜이 정의되지 않아 뺀다.

    짝은 화 안에서 전역으로 세 번에 나눠 맺는다 — 모든 정답의 바른 짝을 먼저, 남은 것끼리 뒤바뀜, 그다음 앎 주체만 틀림. 정답
    하나씩 바른 짝부터 찾으면, 같은 명제를 두 인물이 아는 화에서 앞 정답이 뒤 정답의 바른 짝을 제 쪽의 앎 주체 오류로 먼저
    가져가 정답을 적은 순서에 따라 오류 수가 갈린다. 각 번은 정답과 제안을 내용 순으로 늘어놓고 돌므로 입력 순서가 결과를
    바꾸지 않는다."""
    targets = sorted((k for k in planted if not _same(k.subject, k.knower, aliases)), key=_planted_order)
    candidates = sorted(found, key=_found_order)
    paired: dict[int, str] = {}  # 정답 차례 → 맺은 방향
    used: set[int] = set()
    for wanted in ("correct", "swapped", "wrong_knower"):
        for number, knowledge in enumerate(targets):
            if number in paired:
                continue
            hit = next(
                (
                    index for index, candidate in enumerate(candidates)
                    if index not in used and _skeleton(knowledge, candidate)
                    and _direction(knowledge, candidate, aliases) == wanted
                ),
                None,
            )
            if hit is not None:
                used.add(hit)
                paired[number] = wanted
    return len(paired), sum(direction != "correct" for direction in paired.values())
