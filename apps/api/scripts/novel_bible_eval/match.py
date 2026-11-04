"""결정적 매처 — 추출 제안이 심은 정답을 맞혔는가. 모델을 부르지 않는다.

- 사건: 문단이 겹치고 현실성이 같다.
- 사실: 주어 이름(또는 그 별칭)이 같고, 종류·술어가 같고, 값이 명세의 허용 표기 중 하나이고, 유지 여부와 불변 표시가 같다.
  제안 하나가 원자 명제 하나다. 불변 표시까지 보는 것은 그 표시가 불변 속성 불일치 차단(`immutable_attribute_mismatch`)이 읽을
  사실인지를 정해서다 — 바뀌는 속성을 불변으로 내면 다른 화에서 값이 바뀐 것을 막고, 불변 속성을 바뀌는 것으로 내면 그 충돌을
  놓친다.
- 지식: 앎 주체·앎 종류가 같고 명제가 위 사실 규칙으로 맞는다.

이름·값은 코어가 개체·안정 키를 만들 때와 같은 정규화로 견준다. 정답 하나에는 제안 하나만 대응한다(먼저 맞는 것)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from api.novel_bible.core.keys import normalize_name, predicate_norm
from api.novel_bible.core.types import Proposal, Proposition

from novel_bible_eval.run import ChapterOutcome
from novel_bible_eval.spec import PlantedEvent, PlantedFact, PlantedKnowledge

Aliases = Mapping[str, Sequence[str]]


@dataclass(frozen=True)
class ExtractedEvent:
    paragraphs: frozenset[int]
    actuality: str


@dataclass(frozen=True)
class ExtractedFact:
    proposition: Proposition
    immutable: bool = False


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
    """확정 하나의 성공한 작업 제안에서 매처가 읽는 꼴만 꺼낸다. 사건의 블록은 개정의 차례로 문단 번호가 된다."""
    order = {block: number for number, block in enumerate(outcome.block_ids, start=1)}
    events: list[ExtractedEvent] = []
    facts: list[ExtractedFact] = []
    knowledge: list[ExtractedKnowledge] = []
    for job in outcome.jobs:
        if job.proposal is None:
            continue
        for item in Proposal.model_validate(job.proposal).items:
            if item.table == "event":
                paragraphs = frozenset(order[str(block)] for block in item.covers_blocks if str(block) in order)
                events.append(ExtractedEvent(paragraphs, str(item.fields.get("actuality", "present"))))
            elif item.table == "fact" and item.proposition is not None:
                facts.append(ExtractedFact(item.proposition, item.fields.get("immutable") is True))
            elif item.table == "knowledge" and item.proposition is not None and item.names.get("knower"):
                knower = item.names["knower"][0].name
                knowledge.append(ExtractedKnowledge(knower, str(item.fields.get("kind")), item.proposition))
    return Extracted(tuple(events), tuple(facts), tuple(knowledge))


def _same(name: str, planted: str, aliases: Aliases) -> bool:
    return normalize_name(name) in {normalize_name(n) for n in (planted, *aliases.get(planted, ()))}


def _proposition_fits(
    proposition: Proposition, kind: str, attribute: str | None, values: Sequence[str], holds: bool
) -> bool:
    return (
        proposition.kind == kind
        and predicate_norm(proposition.kind, proposition.attribute) == predicate_norm(proposition.kind, attribute)
        and normalize_name(proposition.value) in {normalize_name(value) for value in values}
        and proposition.holds == holds
    )


def matched_events(planted: Sequence[PlantedEvent], found: Sequence[ExtractedEvent]) -> int:
    used: set[int] = set()
    for event in planted:
        hit = next(
            (
                index for index, candidate in enumerate(found)
                if index not in used and candidate.actuality == event.actuality
                and candidate.paragraphs & set(event.paragraphs)
            ),
            None,
        )
        if hit is not None:
            used.add(hit)
    return len(used)


def matched_facts(planted: Sequence[PlantedFact], found: Sequence[ExtractedFact], aliases: Aliases) -> int:
    used: set[int] = set()
    for fact in planted:
        hit = next(
            (
                index for index, candidate in enumerate(found)
                if index not in used and _same(candidate.proposition.subject, fact.subject, aliases)
                and _proposition_fits(candidate.proposition, fact.kind, fact.attribute, fact.values, fact.holds)
                and candidate.immutable == fact.immutable
            ),
            None,
        )
        if hit is not None:
            used.add(hit)
    return len(used)


def _skeleton(planted: PlantedKnowledge, candidate: ExtractedKnowledge) -> bool:
    """이름을 뺀 골격 — 앎 종류와 명제의 종류·술어·값·유지 여부."""
    return candidate.kind == planted.kind and _proposition_fits(
        candidate.proposition, planted.fact_kind, planted.attribute, planted.values, planted.holds
    )


def _direction(planted: PlantedKnowledge, candidate: ExtractedKnowledge, aliases: Aliases) -> str | None:
    knower, subject = candidate.knower, candidate.proposition.subject
    if _same(knower, planted.knower, aliases) and _same(subject, planted.subject, aliases):
        return "correct"
    if _same(knower, planted.subject, aliases) and _same(subject, planted.knower, aliases):
        return "swapped"
    if _same(subject, planted.subject, aliases):
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
