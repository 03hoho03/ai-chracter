"""정본 기억 충돌 검사 규칙 — 차단 넷(사망·영구 퇴장 뒤 등장, 얻기 전 사용, 일어나기 전 앎, 불변 속성 모순)과 판정 호출이
필요 없는 경고들을 실제 확정 경로로 본다.

화마다 합성 원고를 확정하고, 가짜 어댑터가 그 화의 사건·사실·지식 출력을 돌려준다(모델을 부르지 않는다). 실제 슬롯이 검증·
연결해 커밋하고, 마지막 화의 확정 상태와 검사 결과 행을 본다. "막는다"와 "막지 않는다"는 같은 원고 문장을 쓰고 출력 칸 값
하나(현실성·시작 서술·범위·불변·관계·등장/언급)만 다르게 둔다 — 규칙식의 그 조건을 지우면 "막지 않는다" 쪽이 차단으로
바뀌게. 사망 뒤 등장 픽스처는 실제 추출이 함께 내는 사실(같은 사건의 출석·생사, 등장 사건의 단순 출석, 회상 속 삶)을 심는다.

원고·원작 글은 모두 합성 문장이다."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    Content,
    ContentType,
    ContentVersion,
    ContentVisibility,
    ModerationStatus,
    Novel,
    NovelChapter,
    NovelChapterRevision,
    StoryPromptTemplate,
    StoryVersionDetail,
)
from api.db.models.novel import NovelEpisodeOutline, NovelOutline, NovelSceneBlock
from api.db.models.novel_bible import (
    NovelBibleAdaptationCandidate,
    NovelBibleCommit,
    NovelBibleEvidence,
    NovelBibleFinding,
    NovelBibleRevision,
)
from api.db.models.novel_bible_events import NovelBibleEvent
from api.db.models.novel_bible_facts import NovelBibleFact
from api.db.models.novel_bible_knowledge import NovelBibleKnowledge
from api.db.models.prompt import PromptSection
from api.novel_bible.core.confirm import Actor, confirm
from api.novel_bible.core.contracts import AdapterCapabilities, BibleModelAdapter, PromptSource, Registry, Rule, Slot
from api.novel_bible.core.keys import normalize_name
from api.novel_bible.core.pipeline import run_until_idle
from api.novel_bible.core.types import BibleSnapshot, FactRow, RenderedPrompt
from api.novel_bible.ids import EventActuality, FactKind, FactScope, KnowledgeKind, OperationKey, SlotId
from api.novel_bible.registry import REGISTRY
from api.novel_bible.rules import RULES
from novel_bible_fakes import add_chapter, add_revision, make_novel, savepoint_factory

T = TypeVar("T", bound=BaseModel)
SYSTEM = Actor(kind="system")


# ── 합성 화 ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Ev:
    """사건 하나 — 걸친 문단 번호(1부터, 인용은 첫 문단 전체), 등장·언급 인물, 사용(행위자, 대상, 대상 종류)."""

    paragraphs: tuple[int, ...]
    present: tuple[str, ...] = ()
    actuality: EventActuality = "present"
    mentioned: tuple[str, ...] = ()
    uses: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class Fa:
    """사실 하나 — 인용은 그 문단 전체."""

    paragraph: int
    subject: str
    kind: FactKind
    value: str
    attribute: str | None = None
    holds: bool = True
    immutable: bool = False
    onset: bool = False
    scope: FactScope = "from_here"
    source: tuple[str, str] | None = None


@dataclass(frozen=True)
class Kn:
    paragraph: int
    knower: str
    kind: KnowledgeKind
    subject: str
    fact_kind: FactKind
    value: str
    attribute: str | None = None


@dataclass(frozen=True)
class Rel:
    """회상 관계 — 이 화의 몇 번째 사건(1부터)이 앞 화 사건 목록의 표지(P1 …)와 어떤 관계인가."""

    event: int
    relation: str
    target: str


@dataclass(frozen=True)
class Chapter:
    ordinal: int
    paragraphs: tuple[str, ...]
    events: tuple[Ev, ...] = ()
    facts: tuple[Fa, ...] = ()
    knowledge: tuple[Kn, ...] = ()
    relations: tuple[Rel, ...] = ()

    def outputs(self) -> dict[OperationKey, dict[str, Any]]:
        def quote(number: int) -> dict[str, Any]:
            return {"paragraph": number, "text": self.paragraphs[number - 1]}

        events = [
            {
                "key": f"e{number}", "summary": "합성 요지", "paragraphs": list(event.paragraphs),
                "actuality": event.actuality, "present": list(event.present), "mentioned": list(event.mentioned),
                "uses": [{"actor": actor, "thing": thing, "thing_kind": kind} for actor, thing, kind in event.uses],
                "quote": quote(event.paragraphs[0]),
            }
            for number, event in enumerate(self.events, start=1)
        ]
        relations = [
            {"event": f"e{relation.event}", "relation": relation.relation, "target": relation.target}
            for relation in self.relations
        ]
        facts = [
            {
                "subject": fact.subject, "subject_kind": "character", "kind": fact.kind, "attribute": fact.attribute,
                "value": fact.value, "holds": fact.holds, "immutable": fact.immutable, "onset": fact.onset,
                "scope": fact.scope, "quote": quote(fact.paragraph),
                "source_difference": {"label": fact.source[0], "quote": fact.source[1]} if fact.source else None,
                "play_difference": None,
            }
            for fact in self.facts
        ]
        knowledge = [
            {
                "knower": item.knower, "kind": item.kind,
                "about": {"subject": item.subject, "subject_kind": "character", "kind": item.fact_kind, "attribute": item.attribute,
                          "value": item.value, "holds": True},
                "quote": quote(item.paragraph),
            }
            for item in self.knowledge
        ]
        return {
            "events.extract": {"events": events, "relations": relations},
            "facts.extract": {"facts": facts},
            "knowledge.extract": {"items": knowledge},
        }


_CHANNELS: dict[str, list[tuple[str, str, bool]]] = {
    "novel_bible_events": [("instruction", "합성 지시문", False), ("manuscript", "{manuscript}", False),
                           ("scene_hints", "{scene_hints}", True), ("known_entities", "{known_entities}", True),
                           ("prior_events", "{prior_events}", True)],
    "novel_bible_facts": [("instruction", "합성 지시문", False), ("manuscript", "{manuscript}", False),
                          ("known_entities", "{known_entities}", True),
                          ("known_attributes", "{known_attributes}", True),
                          ("source_canon", "{source_canon}", True), ("play_facts", "{play_facts}", True)],
    "novel_bible_knowledge": [("instruction", "합성 지시문", False), ("manuscript", "{manuscript}", False),
                              ("known_entities", "{known_entities}", True)],
}


@dataclass
class _Adapter:
    """연산마다 정해 둔 출력 하나를 돌려준다."""

    outputs: dict[OperationKey, dict[str, Any]]
    prompt_set_id: uuid.UUID = field(default_factory=uuid.uuid4)
    id: str = "scripted"
    capabilities: AdapterCapabilities = field(
        default_factory=lambda: AdapterCapabilities(structured=True, with_instruction=True, max_input_chars=100_000)
    )

    async def prompt_source(self, session: AsyncSession) -> PromptSource:
        sections = [
            PromptSection(prompt_set_id=self.prompt_set_id, channel=channel, scope="both", slot=slot, variant="",
                          body=body, conditional=conditional, order=order)
            for channel, slots in _CHANNELS.items()
            for order, (slot, body, conditional) in enumerate(slots)
        ]
        return PromptSource(prompt_set_id=self.prompt_set_id, sections=sections)

    async def structured(
        self, prompt: RenderedPrompt, schema: type[T], *, records: list[dict[str, Any]], stage: OperationKey
    ) -> T:
        return schema.model_validate(self.outputs[stage])

    def resolver(self) -> Callable[[OperationKey], BibleModelAdapter]:
        return lambda operation: self


_EXTRACTING: tuple[SlotId, ...] = ("events", "facts", "knowledge")


def _registry(*slot_ids: SlotId) -> Registry:
    """실제 등록부의 부분집합(기본은 원작을 뺀 추출 슬롯 셋)."""
    wanted = slot_ids or _EXTRACTING
    extracting: dict[SlotId, Slot] = {key: slot for key, slot in REGISTRY.extracting.items() if key in wanted}
    return Registry(extracting=extracting, source=REGISTRY.source if "source" in wanted else None)


@dataclass(frozen=True)
class Confirmed:
    commit_id: uuid.UUID
    chapter: NovelChapter
    revision: NovelChapterRevision


async def _run(
    db: AsyncSession, chapter: NovelChapter, revision: NovelChapterRevision, spec: Chapter, *,
    registry: Registry | None = None, rules: list[Rule] | None = None,
) -> Confirmed:
    registry = registry or _registry()
    result = await confirm(
        db, registry, novel_id=chapter.novel_id, chapter_id=chapter.id, revision_id=revision.id, actor=SYSTEM
    )
    await run_until_idle(
        savepoint_factory(db), registry, list(RULES) if rules is None else rules, _Adapter(spec.outputs()).resolver()
    )
    return Confirmed(result.commit_id, chapter, revision)


async def _confirm(
    db: AsyncSession, novel_id: uuid.UUID, spec: Chapter, *, registry: Registry | None = None,
    rules: list[Rule] | None = None,
) -> Confirmed:
    chapter, revision = await add_chapter(db, novel_id, spec.ordinal, "\n\n".join(spec.paragraphs))
    return await _run(db, chapter, revision, spec, registry=registry, rules=rules)


async def _status(db: AsyncSession, commit_id: uuid.UUID) -> str | None:
    status: str | None = await db.scalar(select(NovelBibleCommit.status).where(NovelBibleCommit.id == commit_id))
    return status


async def _findings(db: AsyncSession, commit_id: uuid.UUID) -> list[NovelBibleFinding]:
    rows = await db.scalars(select(NovelBibleFinding).where(NovelBibleFinding.commit_id == commit_id))
    return sorted(rows.all(), key=lambda row: (row.severity, row.rule))


async def _rules_of(db: AsyncSession, commit_id: uuid.UUID) -> list[tuple[str, str]]:
    return [(row.severity, row.rule) for row in await _findings(db, commit_id)]


async def _story(db: AsyncSession, *chapters: Chapter, registry: Registry | None = None) -> tuple[Novel, Confirmed]:
    """앞 화들을 차례로 확정하고(모두 커밋돼야 한다) 마지막 화의 확정을 돌려준다."""
    novel = await make_novel(db)
    last: Confirmed | None = None
    for number, spec in enumerate(chapters):
        last = await _confirm(db, novel.id, spec, registry=registry)
        if number < len(chapters) - 1:
            assert await _status(db, last.commit_id) == "committed", f"{spec.ordinal}화 확정이 커밋되지 않았다"
    assert last is not None
    return novel, last


async def _canon_size(db: AsyncSession, novel_id: uuid.UUID) -> tuple[int, int, int, int]:
    counts = []
    for model in (NovelBibleRevision, NovelBibleEvent, NovelBibleFact, NovelBibleKnowledge):
        counts.append(int(await db.scalar(select(func.count()).select_from(model).where(model.novel_id == novel_id)) or 0))
    return counts[0], counts[1], counts[2], counts[3]


async def _assert_blocked(
    db: AsyncSession, novel: Novel, confirmed: Confirmed, rule: str, before: tuple[int, int, int, int]
) -> NovelBibleFinding:
    """차단: 확정은 `blocked`, 차단 결과 행이 그 규칙 하나, 결과 행의 항목에 이번 확정의 새 항목이 있고, 정본은 그대로다."""
    assert await _status(db, confirmed.commit_id) == "blocked"
    blocks = [row for row in await _findings(db, confirmed.commit_id) if row.severity == "block"]
    assert [row.rule for row in blocks] == [rule]
    assert blocks[0].payload["items"]
    assert await _canon_size(db, novel.id) == before
    return blocks[0]


# ── 사망·영구 퇴장 뒤 등장(exit_then_appearance) ────────────────────────

DEATH = "하나가 마지막 숨을 내쉰다."
EXILE = "하나가 성문 밖으로 쫓겨난다."
LEAVE = "하나가 방을 나선다."
APPEAR = "하나가 마당 문을 열고 들어선다."
GARDEN = "둘이 정원에 물을 준다."
SWEEP = "둘이 마당을 쓴다."
RECALL = "살아서 웃던 하나의 얼굴이 떠오른다."
BREATH = "하나의 가슴이 다시 오르내린다."
LONG_AGO = "둘은 하나가 오래전에 세상을 떠났다고 말한다."


def _death(*extra: Fa, ordinal: int = 3) -> Chapter:
    return Chapter(ordinal, (DEATH,), events=(Ev((1,), ("하나",)),),
                   facts=(Fa(1, "하나", "life", "dead", onset=True), *extra))


def _exile(*extra: Fa, ordinal: int = 3) -> Chapter:
    return Chapter(ordinal, (EXILE,), events=(Ev((1,), ("하나",)),),
                   facts=(Fa(1, "하나", "presence", "gone_for_good", onset=True), *extra))


def _appearance(
    *extra: Fa, ordinal: int = 5, actuality: EventActuality = "present", present: tuple[str, ...] = ("하나",),
    mentioned: tuple[str, ...] = (), returned: bool = False, uses: tuple[tuple[str, str, str], ...] = (),
) -> Chapter:
    """등장 화 — 등장 사건에는 실제 추출이 함께 내는 단순 출석(`present`, 돌아옴 서술이면 `onset`)이 늘 붙는다."""
    return Chapter(
        ordinal, (APPEAR,),
        events=(Ev((1,), present, actuality=actuality, mentioned=mentioned, uses=uses),),
        facts=(Fa(1, "하나", "presence", "present", onset=returned), *extra),
    )


async def _blocks_exit(db: AsyncSession, *chapters: Chapter) -> NovelBibleFinding:
    novel = await make_novel(db)
    for spec in chapters[:-1]:
        confirmed = await _confirm(db, novel.id, spec)
        assert await _status(db, confirmed.commit_id) == "committed"
    before = await _canon_size(db, novel.id)
    last = await _confirm(db, novel.id, chapters[-1])
    return await _assert_blocked(db, novel, last, "exit_then_appearance", before)


@pytest.mark.parametrize(
    "exit_chapter",
    [
        pytest.param(_death(), id="death"),
        pytest.param(_exile(), id="gone_for_good"),
        # 같은 사건: 추방 장면에 서 있는 그 인물의 출석, 숨을 거두는 장면의 삶이 퇴장·사망과 같은 사건에 함께 있다.
        pytest.param(_exile(Fa(1, "하나", "presence", "present")), id="same_event_presence"),
        pytest.param(_death(Fa(1, "하나", "life", "alive")), id="same_event_alive"),
    ],
)
async def test_an_appearance_after_a_death_or_a_permanent_exit_blocks(
    db_session: AsyncSession, exit_chapter: Chapter
) -> None:
    """5화 등장 사건에는 단순 출석이 함께 있다. 퇴장·사망과 같은 사건에 붙은 출석·삶은 되살아남·돌아옴이 아니다. 깨지는
    시나리오: 되살아남 창이 같은 사건의 행이나 등장 사건의 단순 출석을 받아들이면 실제 추출이 늘 함께 내는 사실 때문에 차단이
    꺼진다."""
    finding = await _blocks_exit(db_session, exit_chapter, _appearance())
    assert len(finding.payload["items"]) == 2


async def test_a_plain_presence_at_the_appearance_does_not_count_as_a_return_but_a_stated_return_does(
    db_session: AsyncSession,
) -> None:
    """같은 등장 문장에서 출석의 `onset` 하나만 다르다. 깨지는 시나리오: 출입의 돌아옴에 `onset` 을 요구하지 않으면 단순 출석이
    돌아옴으로 읽혀 영구 퇴장 뒤 등장이 막히지 않는다."""
    await _blocks_exit(db_session, _exile(), _appearance(returned=False))
    _, confirmed = await _story(db_session, _exile(), _appearance(returned=True))
    assert await _status(db_session, confirmed.commit_id) == "committed"
    assert await _rules_of(db_session, confirmed.commit_id) == []


@pytest.mark.parametrize(
    ("variant", "blocked"),
    [
        pytest.param({}, True, id="present"),
        pytest.param({"actuality": "flashback"}, False, id="flashback_by_model"),
        pytest.param({"actuality": "dream_or_imagined"}, False, id="dream"),
        pytest.param({"present": (), "mentioned": ("하나",)}, False, id="mentioned_only"),
    ],
)
async def test_an_appearance_in_a_flashback_a_dream_or_by_mention_only_does_not_block(
    db_session: AsyncSession, variant: dict[str, Any], blocked: bool
) -> None:
    """같은 등장 문장에서 현실성이나 등장/언급 칸 하나만 다르다. 깨지는 시나리오: 등장 사건의 주선 여부나 등장 인물 조건을
    빼면 회상·꿈 속 등장, 이름만 불린 인물이 사망 뒤 등장으로 막힌다."""
    if blocked:
        await _blocks_exit(db_session, _death(), _appearance(**variant))
        return
    _, confirmed = await _story(db_session, _death(), _appearance(**variant))
    assert await _status(db_session, confirmed.commit_id) == "committed"
    assert await _rules_of(db_session, confirmed.commit_id) == []


async def _outline(db: AsyncSession, chapter: NovelChapter, block_ids: list[uuid.UUID], *, flashback: bool) -> None:
    outline = NovelOutline(
        novel_id=chapter.novel_id, revision=1, source="generate", selection_id=uuid.uuid4(), episodes=[]
    )
    db.add(outline)
    await db.flush()
    episode = NovelEpisodeOutline(
        novel_id=chapter.novel_id, outline_id=outline.id, episode_key=uuid.uuid4(), revision=1, source="generate",
        scenes=[{"id": "s1", "title": "합성 장면", "flashback": flashback}],
    )
    db.add(episode)
    await db.flush()
    db.add_all(
        NovelSceneBlock(block_id=block_id, chapter_id=chapter.id, episode_outline_id=episode.id, scene_id="s1")
        for block_id in block_ids
    )
    await db.flush()


@pytest.mark.parametrize("flashback", [False, True])
async def test_a_scene_the_outline_alone_marks_as_flashback_does_not_block(
    db_session: AsyncSession, flashback: bool
) -> None:
    """모델은 지금 이야기라고 냈고 장면 구성안의 회상 표시 하나만 다르다. 깨지는 시나리오: 구성안의 회상 표시가 사건 현실성에
    오르지 않으면 모델이 놓친 회상 속 등장이 사망 뒤 등장으로 막힌다."""
    novel = await make_novel(db_session)
    death = await _confirm(db_session, novel.id, _death())
    assert await _status(db_session, death.commit_id) == "committed"
    spec = _appearance()
    chapter, revision = await add_chapter(db_session, novel.id, spec.ordinal, APPEAR)
    await _outline(db_session, chapter, list(revision.block_ids), flashback=flashback)
    confirmed = await _run(db_session, chapter, revision, spec)
    assert await _status(db_session, confirmed.commit_id) == ("committed" if flashback else "blocked")


@pytest.mark.parametrize(
    ("actuality", "revival_ordinal", "blocked"),
    [
        pytest.param("present", 4, False, id="present"),
        pytest.param("dream_or_imagined", 4, True, id="dream"),
        pytest.param("present", 7, True, id="revival_after_the_appearance"),
    ],
)
async def test_a_revival_between_the_death_and_the_appearance_lifts_the_block_unless_it_is_a_dream(
    db_session: AsyncSession, actuality: EventActuality, revival_ordinal: int, blocked: bool
) -> None:
    """3화 죽음 → 되살아남 화 → 5화 등장 순서로 확정한다. 4화 되살아남의 두 판은 그 사건의 현실성 하나만 다르고, 4화·7화 두
    판은 되살아남의 화 번호 하나만 다르다(7화는 5화보다 먼저 확정되고, 되살아남이 그 화 사건 자체에 있어 7화는 커밋된다).
    깨지는 시나리오: 되살아남 사건이 실제로 일어났는지(`actual`)를 보지 않으면 꿈 속 되살아남이 사망 뒤 등장 차단을 끈다.
    되살아남이 등장보다 늦지 않은지를 보지 않으면, 등장보다 뒤 화에 서술된 되살아남이 앞 등장의 차단을 끈다."""
    revival = Chapter(revival_ordinal, (BREATH,), events=(Ev((1,), ("하나",), actuality=actuality),),
                      facts=(Fa(1, "하나", "life", "alive", onset=True),))
    if blocked:
        await _blocks_exit(db_session, _death(), revival, _appearance())
        return
    _, confirmed = await _story(db_session, _death(), revival, _appearance())
    assert await _status(db_session, confirmed.commit_id) == "committed"
    assert await _rules_of(db_session, confirmed.commit_id) == []


@pytest.mark.parametrize("scope", ["from_here", "work"])
async def test_alive_all_along_stated_at_the_appearance_itself_does_not_block(
    db_session: AsyncSession, scope: FactScope
) -> None:
    """등장 사건 자체에 "알고 보니 살아 있었다"(`alive`, `onset=false`)가 있다 — 범위 칸 하나만 다른 두 판 모두 결과가 없다.
    깨지는 시나리오: 생사의 되살아남에도 `onset` 을 요구하거나 등장 사건 자체를 창에서 빼면, 죽은 줄 알았던 인물이 살아
    돌아오는 원고를 확정할 수 없다. 되살아남의 자리를 그 사실이 놓인 등장 사건 대신 작품 범위의 시작(어느 화보다 앞)으로
    읽으면, 모델이 "처음부터 살아 있었다"를 작품 범위로 낸 같은 원고가 죽음보다 앞선 삶으로 읽혀 막힌다."""
    _, confirmed = await _story(db_session, _death(), _appearance(Fa(1, "하나", "life", "alive", scope=scope)))
    assert await _status(db_session, confirmed.commit_id) == "committed"
    assert await _rules_of(db_session, confirmed.commit_id) == []


def _recall_chapter(relation: Rel | None, *, scope: FactScope = "from_here") -> Chapter:
    """4화 — 지금 이야기 사건 하나와 하나가 살아 있던 회상 사건 하나. 앞 화 사건 목록은 P1 = 2화 정원 사건, P2 = 3화 죽음."""
    return Chapter(
        4, (SWEEP, RECALL),
        events=(Ev((1,), ("둘",)), Ev((2,), (), actuality="flashback", mentioned=("하나",))),
        facts=(Fa(2, "하나", "life", "alive", scope=scope),),
        relations=(relation,) if relation else (),
    )


_GARDEN = Chapter(2, (GARDEN,), events=(Ev((1,), ("둘",)),))


async def test_alive_in_a_flashback_before_the_death_still_blocks(db_session: AsyncSession) -> None:
    """죽음 앞 회상(관계 `before` 2화 사건) 속 삶은 죽음보다 앞서 끝나 되살아남이 아니다."""
    await _blocks_exit(db_session, _GARDEN, _death(), _recall_chapter(Rel(2, "before", "P1")), _appearance(ordinal=6))


@pytest.mark.parametrize("scope", ["from_here", "work"])
async def test_alive_in_a_flashback_without_relation_warns_order_undetermined_instead_of_blocking(
    db_session: AsyncSession, scope: FactScope
) -> None:
    """관계 없는 회상 속 삶 — 왼쪽 "죽음 앞 회상"과 관계 칸 하나만 다르다. 차단을 끄되 침묵하지 않고 순서 미정 경고와 판정
    후보를 남긴다. 삶의 범위가 작품 전체여도 같다. 깨지는 시나리오: 죽음과의 순서가 미정인 되살아남을 순서가 알려진 것과 같이
    다루면, 죽은 인물을 떠올린 회상 하나 때문에 그 인물의 사망 뒤 등장이 영영 조용해진다. 작품 범위 삶의 자리를 회상 사건 대신
    어느 화보다 앞으로 읽으면 같은 회상이 죽음보다 앞선 삶이 되어 경고 대신 차단이 난다."""
    novel, confirmed = await _story(
        db_session, _GARDEN, _death(), _recall_chapter(None, scope=scope), _appearance(ordinal=6)
    )
    assert await _status(db_session, confirmed.commit_id) == "committed"
    (finding,) = await _findings(db_session, confirmed.commit_id)
    assert (finding.severity, finding.rule) == ("warning", "order_undetermined")
    assert finding.payload["rule"] == "exit_then_appearance"
    assert finding.payload["judge"] == "J1"
    alive = await db_session.scalar(
        select(NovelBibleFact.id).where(NovelBibleFact.novel_id == novel.id, NovelBibleFact.value_norm == "alive")
    )
    assert finding.payload["revivals"] == [str(alive)]


async def test_alive_in_a_flashback_after_the_death_does_not_block(db_session: AsyncSession) -> None:
    """회상 사건에 앵커한 "알고 보니 살아 있었다"(죽음 사건과 관계 `after`) — 위 두 짝과 관계 칸 하나만 다르다."""
    _, confirmed = await _story(
        db_session, _GARDEN, _death(), _recall_chapter(Rel(2, "after", "P2")), _appearance(ordinal=6)
    )
    assert await _status(db_session, confirmed.commit_id) == "committed"
    assert await _rules_of(db_session, confirmed.commit_id) == []


async def test_a_death_shown_only_in_a_placed_flashback_does_not_block_a_later_appearance(
    db_session: AsyncSession,
) -> None:
    """3화 죽음 사건이 회상이다(관계 `before` 2화 사건 — 위치를 갖게 하려고 둔다). 차단 짝과는 죽음 사건의 현실성이 다르다.
    깨지는 시나리오: 퇴장 사건이 지금 이야기인지 보지 않으면, 위치가 정해진 회상 속 죽음 뒤의 등장이 사망 뒤 등장으로 막힌다 —
    꿈이나 관계 없는 회상 속 죽음은 위치가 없어 이 조건 없이도 순서 검사가 거른다."""
    death = Chapter(3, (DEATH,), events=(Ev((1,), ("하나",), actuality="flashback"),),
                    facts=(Fa(1, "하나", "life", "dead", onset=True),), relations=(Rel(1, "before", "P1"),))
    _, confirmed = await _story(db_session, _GARDEN, death, _appearance())
    assert await _status(db_session, confirmed.commit_id) == "committed"
    assert await _rules_of(db_session, confirmed.commit_id) == []


async def test_an_appearance_in_a_flashback_placed_after_the_death_does_not_block(db_session: AsyncSession) -> None:
    """5화 등장 사건이 회상이다(관계 `after` 3화 죽음). 위치가 죽음 뒤로 정해져도 회상 속 등장은 지금 이야기가 아니다. 깨지는
    시나리오: 등장 사건이 지금 이야기인지 보지 않으면 죽음 뒤에 놓인 회상 속 등장이 사망 뒤 등장으로 막힌다 — 관계 없는 회상·꿈
    속 등장은 위치가 없어 이 조건 없이도 순서 검사가 거른다."""
    appearance = Chapter(5, (APPEAR,), events=(Ev((1,), ("하나",), actuality="flashback"),),
                         facts=(Fa(1, "하나", "presence", "present"),), relations=(Rel(1, "after", "P2"),))
    _, confirmed = await _story(db_session, _GARDEN, _death(), appearance)
    assert await _status(db_session, confirmed.commit_id) == "committed"
    assert await _rules_of(db_session, confirmed.commit_id) == []


@pytest.mark.parametrize(
    ("scope", "appearance_ordinal", "expected"),
    [
        pytest.param("from_here", 1, [], id="earlier_appearance"),
        pytest.param("work", 1, [], id="earlier_appearance_work_scope"),
        pytest.param("work", 5, [("block", "exit_then_appearance")], id="later_appearance_work_scope"),
    ],
)
async def test_a_death_stated_for_the_whole_work_stands_at_the_event_that_states_it(
    db_session: AsyncSession, scope: FactScope, appearance_ordinal: int, expected: list[tuple[str, str]]
) -> None:
    """3화 지금 이야기 사건이 하나의 오래전 죽음을 사망으로 낸다. 1화 등장과의 두 판은 사망의 범위 칸 하나만 다르고 둘 다
    결과가 없다. 5화 등장 판은 작품 범위 사망도 그것이 서술된 사건 뒤의 등장은 여전히 막는지 본다. 깨지는 시나리오: 작품 범위
    사망을 어느 화보다 앞선 퇴장으로 읽으면, 과거에 놓인 1화 장면을 모델이 지금 이야기로 표시한 원고에서 3화 확정이 막히고
    1화를 다시 확정해도 같은 차단이 난다."""
    long_dead = Chapter(3, (LONG_AGO,), events=(Ev((1,), ("둘",)),), facts=(Fa(1, "하나", "life", "dead", scope=scope),))
    chapters = sorted([long_dead, _appearance(ordinal=appearance_ordinal)], key=lambda spec: spec.ordinal)
    _, confirmed = await _story(db_session, *chapters)
    assert await _status(db_session, confirmed.commit_id) == ("blocked" if expected else "committed")
    assert await _rules_of(db_session, confirmed.commit_id) == expected


@pytest.mark.parametrize(
    ("value", "scope", "expected"),
    [
        pytest.param("gone_for_good", "from_here", [("block", "exit_then_appearance")], id="gone_for_good"),
        pytest.param("departed", "from_here", [("warning", "return_unstated")], id="departed_from_here"),
        pytest.param("departed", "scene", [], id="departed_scene"),
        # 범위만 장면으로 다른 영구 퇴장 — 장면 범위 사실은 그 장면과 함께 끝나 퇴장으로 세지 않는다.
        pytest.param("gone_for_good", "scene", [], id="gone_for_good_scene"),
    ],
)
async def test_a_departure_that_may_return_warns_and_leaving_the_scene_says_nothing(
    db_session: AsyncSession, value: str, scope: FactScope, expected: list[tuple[str, str]]
) -> None:
    """같은 떠남 문장에서 출입 값과 범위만 다르다. 장면 단위 퇴장(방을 나감) 뒤 다음 화 등장은 결과가 없고, 돌아올 수 있는
    떠남 뒤 돌아옴 서술 없는 등장은 경고다. 깨지는 시나리오: 장면 단위 퇴장을 퇴장으로 세면 거의 모든 화가 경고·차단을 단다."""
    leave = Chapter(3, (LEAVE,), events=(Ev((1,), ("하나",)),),
                    facts=(Fa(1, "하나", "presence", value, onset=True, scope=scope),))
    _, confirmed = await _story(db_session, leave, _appearance())
    assert await _rules_of(db_session, confirmed.commit_id) == expected


async def test_a_belief_that_the_dead_is_alive_is_not_a_fact(db_session: AsyncSession) -> None:
    """믿음은 지식 행이라 사망 뒤 등장 규칙이 읽지 않는다 — 죽은 인물이 살아 있다고 믿는 장면은 결과가 없다."""
    belief = Chapter(5, ("둘은 하나가 살아 있다고 믿는다.",), events=(Ev((1,), ("둘",)),),
                     knowledge=(Kn(1, "둘", "believes", "하나", "life", "alive"),))
    _, confirmed = await _story(db_session, _death(), belief)
    assert await _status(db_session, confirmed.commit_id) == "committed"
    assert await _rules_of(db_session, confirmed.commit_id) == []


# ── 원작과 다름 — 각색 후보는 차단이 아니다 ──────────────────────────────

_SETTING = "합성 작품 설정 — 하나는 끝까지 살아 있다. 하나의 혈액형은 B형이다."


async def _story_novel(db: AsyncSession) -> Novel:
    novel = await make_novel(db)
    content = Content(
        creator_user_id=novel.user_id, type=ContentType.STORY, hashtags=[], visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db.add(content)
    await db.flush()
    version = ContentVersion(
        content_id=content.id, version_number=1, published_at=datetime.now(UTC), detail_description="설명"
    )
    db.add(version)
    await db.flush()
    db.add(StoryVersionDetail(content_version_id=version.id, name="스토리", one_liner="한줄",
                              prompt_template=StoryPromptTemplate.BASIC, setting_text=_SETTING))
    content.current_published_version_id = version.id
    novel.content_id, novel.content_type, novel.character_name = content.id, "story", None
    await db.flush()
    return novel


@pytest.mark.parametrize(
    "spec",
    [
        pytest.param(
            Chapter(3, (DEATH,), events=(Ev((1,), ("하나",)),),
                    facts=(Fa(1, "하나", "life", "dead", onset=True, source=("S", "하나는 끝까지 살아 있다")),)),
            id="death_against_source",
        ),
        pytest.param(
            Chapter(1, ("하나의 혈액형은 A형이다.",), events=(Ev((1,), ("하나",)),),
                    facts=(Fa(1, "하나", "attribute", "A형", attribute="혈액형", immutable=True,
                              source=("S", "하나의 혈액형은 B형이다")),)),
            id="blood_type_against_source",
        ),
    ],
)
async def test_a_novel_fact_that_differs_from_the_source_commits_as_an_adaptation_candidate(
    db_session: AsyncSession, spec: Chapter
) -> None:
    """원작과 다른 소설 사실은 각색 후보 행만 남기고 소설 사실 그대로 커밋된다 — 규칙 입력에 원작이 들어가지 않는다."""
    novel = await _story_novel(db_session)
    confirmed = await _confirm(db_session, novel.id, spec, registry=_registry(*_EXTRACTING, "source"))
    assert await _status(db_session, confirmed.commit_id) == "committed"
    assert await _rules_of(db_session, confirmed.commit_id) == []
    candidates = await db_session.scalar(
        select(func.count()).select_from(NovelBibleAdaptationCandidate).where(
            NovelBibleAdaptationCandidate.novel_id == novel.id
        )
    )
    assert candidates == 1


# ── 얻기 전 사용(use_before_acquisition) ─────────────────────────────

SWING = "하나가 검을 휘두른다."
HOLD = "하나의 손에 검이 들린다."
FLAME_USE = "하나가 불꽃을 일으킨다."
FLAME = "하나에게 불꽃의 힘이 깃든다."


def _use(*, actuality: EventActuality = "present", ordinal: int = 2) -> Chapter:
    return Chapter(ordinal, (SWING,), events=(Ev((1,), ("하나",), actuality=actuality, uses=(("하나", "검", "object"),)),))


def _hold(*, onset: bool, ordinal: int = 4, actuality: EventActuality = "present") -> Chapter:
    return Chapter(ordinal, (HOLD,), events=(Ev((1,), ("하나",), actuality=actuality),),
                   facts=(Fa(1, "하나", "possession", "검", onset=onset),))


async def test_using_a_sword_before_the_chapter_that_acquires_it_blocks(db_session: AsyncSession) -> None:
    novel = await make_novel(db_session)
    used = await _confirm(db_session, novel.id, _use())
    assert await _status(db_session, used.commit_id) == "committed"
    before = await _canon_size(db_session, novel.id)
    confirmed = await _confirm(db_session, novel.id, _hold(onset=True))
    await _assert_blocked(db_session, novel, confirmed, "use_before_acquisition", before)


async def test_a_sword_first_described_as_long_held_warns_onset_unstated(db_session: AsyncSession) -> None:
    """4화에서야 "오래 지니던 검"으로 처음 서술된 기존 소지 — 차단 짝과 `onset` 하나만 다르다. 깨지는 시나리오: 시작 서술을
    보지 않으면 늦게 드러난 기존 소지가 얻기 전 사용으로 막힌다."""
    _, confirmed = await _story(db_session, _use(), _hold(onset=False))
    assert await _status(db_session, confirmed.commit_id) == "committed"
    assert await _rules_of(db_session, confirmed.commit_id) == [("warning", "onset_unstated")]


@pytest.mark.parametrize(("scope", "blocked"), [("from_here", True), ("work", False)])
async def test_an_innate_ability_is_not_acquired_later(db_session: AsyncSession, scope: FactScope, blocked: bool) -> None:
    """타고난 능력(`scope='work'`)은 작품 처음부터 참이다 — 같은 문장에서 범위 하나만 다르다."""
    novel = await make_novel(db_session)
    use = Chapter(2, (FLAME_USE,), events=(Ev((1,), ("하나",), uses=(("하나", "불꽃", "ability"),)),))
    assert await _status(db_session, (await _confirm(db_session, novel.id, use)).commit_id) == "committed"
    gained = Chapter(4, (FLAME,), events=(Ev((1,), ("하나",)),),
                     facts=(Fa(1, "하나", "ability", "불꽃", onset=True, scope=scope),))
    before = await _canon_size(db_session, novel.id)
    confirmed = await _confirm(db_session, novel.id, gained)
    if blocked:
        await _assert_blocked(db_session, novel, confirmed, "use_before_acquisition", before)
    else:
        assert await _status(db_session, confirmed.commit_id) == "committed"
        assert await _rules_of(db_session, confirmed.commit_id) == []


@pytest.mark.parametrize(("use_actuality", "hold_actuality"), [
    pytest.param("flashback", "present", id="use_in_flashback"),
    pytest.param("dream_or_imagined", "present", id="use_in_dream"),
    pytest.param("present", "dream_or_imagined", id="acquired_in_dream"),
])
async def test_a_use_or_an_acquisition_outside_the_main_line_does_not_block(
    db_session: AsyncSession, use_actuality: EventActuality, hold_actuality: EventActuality
) -> None:
    """차단 짝과 사용 사건이나 획득 사건의 현실성 하나만 다르다."""
    _, confirmed = await _story(
        db_session, _use(actuality=use_actuality), _hold(onset=True, actuality=hold_actuality)
    )
    assert await _status(db_session, confirmed.commit_id) == "committed"
    assert await _rules_of(db_session, confirmed.commit_id) == []


async def test_a_believed_ability_is_not_a_fact(db_session: AsyncSession) -> None:
    belief = Chapter(2, ("하나는 자기가 불꽃을 다룬다고 믿는다.",), events=(Ev((1,), ("하나",)),),
                     knowledge=(Kn(1, "하나", "believes", "하나", "ability", "불꽃"),))
    gained = Chapter(4, (FLAME,), events=(Ev((1,), ("하나",)),),
                     facts=(Fa(1, "하나", "ability", "불꽃", onset=True),))
    _, confirmed = await _story(db_session, belief, gained)
    assert await _status(db_session, confirmed.commit_id) == "committed"
    assert await _rules_of(db_session, confirmed.commit_id) == []


async def test_a_use_without_any_acquisition_warns_only_when_the_use_is_new(db_session: AsyncSession) -> None:
    """획득 사실이 없는 사용은 그 사용을 낸 확정에서만 경고한다 — 다음 화 확정은 그 사용을 다시 들추지 않는다."""
    novel = await make_novel(db_session)
    used = await _confirm(db_session, novel.id, _use())
    assert await _status(db_session, used.commit_id) == "committed"
    assert await _rules_of(db_session, used.commit_id) == [("warning", "use_without_acquisition")]
    later = await _confirm(db_session, novel.id, Chapter(3, (GARDEN,), events=(Ev((1,), ("둘",)),)))
    assert await _rules_of(db_session, later.commit_id) == []


@pytest.mark.parametrize(
    ("held_when_lost", "regained", "expected"),
    [
        pytest.param(False, False, [("warning", "use_after_loss")], id="lost"),
        pytest.param(False, True, [], id="regained"),
        # 잃는 사건에 "지니던 검"(소지, 시작 서술 없음)이 함께 있다 — 그 장면에 들고 있던 것이지 다시 지님이 아니다.
        pytest.param(True, False, [("warning", "use_after_loss")], id="held_in_the_losing_scene"),
    ],
)
async def test_using_a_lost_sword_warns_unless_it_was_regained(
    db_session: AsyncSession, held_when_lost: bool, regained: bool, expected: list[tuple[str, str]]
) -> None:
    """잃는 화에 소지 행 하나가 더 있는 판도 다시 지님이 없는 판과 같은 경고다. 깨지는 시나리오: 다시 지님을 잃음과 같은
    사건에서도 받으면, 실제 추출이 잃는 장면에 함께 내는 소지 행 때문에 잃은 뒤 사용 경고가 사라진다."""
    gained = Chapter(1, ("하나가 대장간에서 검을 받는다.",), events=(Ev((1,), ("하나",)),),
                     facts=(Fa(1, "하나", "possession", "검", onset=True),))
    held = (Fa(1, "하나", "possession", "검"),) if held_when_lost else ()
    lost = Chapter(2, ("하나가 강물에 검을 떨어뜨린다.",), events=(Ev((1,), ("하나",)),),
                   facts=(*held, Fa(1, "하나", "possession", "검", holds=False, onset=True)))
    regain = (Fa(1, "하나", "possession", "검", onset=True),) if regained else ()
    use = Chapter(3, (SWING,), events=(Ev((1,), ("하나",), uses=(("하나", "검", "object"),)),), facts=regain)
    _, confirmed = await _story(db_session, gained, lost, use)
    assert await _rules_of(db_session, confirmed.commit_id) == expected


# ── 일어나기 전 앎(knowledge_before_fact) ────────────────────────────

KNOW = "둘은 하나가 검을 가졌다는 것을 안다."
SON = "하나가 왕의 아들이 된다."
KNOW_SON = "둘은 하나가 왕의 아들이라는 것을 안다."


def _knows(*, kind: KnowledgeKind = "knows", actuality: EventActuality = "present", with_event: bool = True) -> Chapter:
    return Chapter(2, (KNOW,), events=(Ev((1,), ("둘",), actuality=actuality),) if with_event else (),
                   knowledge=(Kn(1, "둘", kind, "하나", "possession", "검"),))


async def test_knowing_before_the_chapter_where_it_happens_blocks(db_session: AsyncSession) -> None:
    novel = await make_novel(db_session)
    known = await _confirm(db_session, novel.id, _knows())
    assert await _status(db_session, known.commit_id) == "committed"
    before = await _canon_size(db_session, novel.id)
    confirmed = await _confirm(db_session, novel.id, _hold(onset=True))
    await _assert_blocked(db_session, novel, confirmed, "knowledge_before_fact", before)


@pytest.mark.parametrize("variant", [
    pytest.param({"kind": "believes"}, id="believes"),
    pytest.param({"actuality": "flashback"}, id="known_in_flashback"),
    pytest.param({"actuality": "dream_or_imagined"}, id="known_in_dream"),
])
async def test_a_belief_or_knowledge_outside_the_main_line_does_not_block(
    db_session: AsyncSession, variant: dict[str, Any]
) -> None:
    """차단 짝과 앎 종류나 알게 된 사건의 현실성 하나만 다르다 — 꿈 속에서 알게 된 앎은 그 꿈 사건에 이어 저장된다."""
    _, confirmed = await _story(db_session, _knows(**variant), _hold(onset=True))
    assert await _status(db_session, confirmed.commit_id) == "committed"
    assert await _rules_of(db_session, confirmed.commit_id) == []


async def test_knowing_a_fact_anchored_in_a_dream_does_not_block(db_session: AsyncSession) -> None:
    """사실이 꿈·상상 사건에 앵커했다 — 차단 짝과 사실 사건의 현실성 하나만 다르다."""
    _, confirmed = await _story(db_session, _knows(), _hold(onset=True, actuality="dream_or_imagined"))
    assert await _status(db_session, confirmed.commit_id) == "committed"
    assert await _rules_of(db_session, confirmed.commit_id) == []


async def test_knowledge_without_any_fact_does_nothing(db_session: AsyncSession) -> None:
    _, confirmed = await _story(db_session, _knows())
    assert await _status(db_session, confirmed.commit_id) == "committed"
    assert await _rules_of(db_session, confirmed.commit_id) == []


@pytest.mark.parametrize(("onset", "expected"), [(True, "block"), (False, "warning")])
async def test_knowing_a_relation_first_described_later_warns_onset_unstated(
    db_session: AsyncSession, onset: bool, expected: str
) -> None:
    """4화에서야 처음 서술된 기존 관계("사실 왕의 아들")를 2화에서 앎 — 같은 문장에서 `onset` 하나만 다르다."""
    know = Chapter(2, (KNOW_SON,), events=(Ev((1,), ("둘",)),),
                   knowledge=(Kn(1, "둘", "knows", "하나", "relation", "왕", attribute="아들"),))
    son = Chapter(4, (SON,), events=(Ev((1,), ("하나", "왕")),),
                  facts=(Fa(1, "하나", "relation", "왕", attribute="아들", onset=onset),))
    _, confirmed = await _story(db_session, know, son)
    rule = "knowledge_before_fact" if expected == "block" else "onset_unstated"
    assert await _rules_of(db_session, confirmed.commit_id) == [(expected, rule)]


async def test_knowing_without_a_known_since_event_warns_order_undetermined(db_session: AsyncSession) -> None:
    """2화에 사건이 하나도 없어 알게 된 사건이 미정(NULL)이다 — 순서를 모르므로 차단 대신 순서 미정 경고."""
    _, confirmed = await _story(db_session, _knows(with_event=False), _hold(onset=True))
    assert await _status(db_session, confirmed.commit_id) == "committed"
    (finding,) = await _findings(db_session, confirmed.commit_id)
    assert (finding.rule, finding.payload["rule"], finding.payload["judge"]) == (
        "order_undetermined", "knowledge_before_fact", "J1"
    )


@pytest.mark.parametrize(("witnessed", "expected"), [(False, [("warning", "knowledge_source_unclear")]), (True, [])])
async def test_knowing_a_fact_from_a_scene_the_knower_missed_is_a_judge_candidate(
    db_session: AsyncSession, witnessed: bool, expected: list[tuple[str, str]]
) -> None:
    """사실이 먼저(2화)이고 4화에 앎. 앎 주체가 그 사실 사건에 있었는지 하나만 다르다. 이것은 차단이 아니라 판정 후보다."""
    present = ("하나", "둘") if witnessed else ("하나",)
    held = Chapter(2, (HOLD,), events=(Ev((1,), present),), facts=(Fa(1, "하나", "possession", "검", onset=True),))
    know = Chapter(4, (KNOW,), events=(Ev((1,), ("둘",)),),
                   knowledge=(Kn(1, "둘", "knows", "하나", "possession", "검"),))
    _, confirmed = await _story(db_session, held, know)
    assert await _status(db_session, confirmed.commit_id) == "committed"
    assert await _rules_of(db_session, confirmed.commit_id) == expected
    if expected:
        (finding,) = await _findings(db_session, confirmed.commit_id)
        assert finding.payload["judge"] == "J3"


# ── 불변 속성 모순(immutable_attribute_mismatch) ──────────────────────


def _attribute(ordinal: int, sentence: str, attribute: str, value: str, *, immutable: bool = True,
               scope: FactScope = "from_here") -> Chapter:
    return Chapter(ordinal, (sentence,), events=(Ev((1,), ("하나",)),),
                   facts=(Fa(1, "하나", "attribute", value, attribute=attribute, immutable=immutable, scope=scope),))


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param(("혈액형", "A형"), ("혈액형", "B형"), id="blood_type"),
        pytest.param(("태어난 해", "1990년"), ("태어난 해", "1992년"), id="birth_year"),
    ],
)
async def test_two_immutable_closed_values_that_differ_block(
    db_session: AsyncSession, first: tuple[str, str], second: tuple[str, str]
) -> None:
    novel = await make_novel(db_session)
    one = await _confirm(db_session, novel.id, _attribute(1, f"하나의 {first[0]}은 {first[1]}이다.", *first))
    assert await _status(db_session, one.commit_id) == "committed"
    before = await _canon_size(db_session, novel.id)
    six = await _confirm(db_session, novel.id, _attribute(6, f"하나의 {second[0]}은 {second[1]}이다.", *second))
    await _assert_blocked(db_session, novel, six, "immutable_attribute_mismatch", before)


async def test_reconfirming_the_same_chapter_does_not_collide_with_its_own_earlier_value(
    db_session: AsyncSession,
) -> None:
    novel = await make_novel(db_session)
    first = await _confirm(db_session, novel.id, _attribute(1, "하나의 혈액형은 A형이다.", "혈액형", "A형"))
    assert await _status(db_session, first.commit_id) == "committed"
    spec = _attribute(1, "하나의 혈액형은 B형이다.", "혈액형", "B형")
    revision = await add_revision(db_session, first.chapter.id, spec.paragraphs[0])
    again = await _run(db_session, first.chapter, revision, spec)
    assert await _status(db_session, again.commit_id) == "committed"
    assert await _rules_of(db_session, again.commit_id) == []


HAIR_BLACK = "하나의 머리색은 검정이다."
HAIR_RED = "하나의 머리색은 빨강이다."


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        pytest.param(
            _attribute(1, HAIR_BLACK, "머리색", "검정"), _attribute(6, HAIR_RED, "머리색", "빨강"),
            [("block", "immutable_attribute_mismatch")], id="both_immutable_colors",
        ),
        # 일시 변화한 외형(변장·염색): 한쪽만 불변이면 차단 없이 경고.
        pytest.param(
            _attribute(1, HAIR_BLACK, "머리색", "검정"),
            _attribute(6, HAIR_RED, "머리색", "빨강", immutable=False, scope="scene"),
            [("warning", "attribute_surface_differs")], id="temporary_dye",
        ),
        pytest.param(
            _attribute(1, HAIR_BLACK, "머리색", "검정", immutable=False),
            _attribute(6, HAIR_RED, "머리색", "빨강", immutable=False), [], id="both_mutable",
        ),
        pytest.param(
            _attribute(1, HAIR_BLACK, "머리색", "검정"), _attribute(6, "하나의 머리색은 검은색이다.", "머리색", "검은색"),
            [], id="same_color_spelled_differently",
        ),
        pytest.param(
            _attribute(1, "하나의 성격은 차분함이다.", "성격", "차분함"),
            _attribute(6, "하나의 성격은 거침이다.", "성격", "거침"),
            [("warning", "attribute_surface_differs")], id="free_text",
        ),
        # 개체를 가리키는 값의 반전: 1화 "친부 = 셋" → 6화 "사실 친부는 넷".
        pytest.param(
            _attribute(1, "하나의 친부는 셋이다.", "친부", "셋"), _attribute(6, "하나의 친부는 사실 넷이다.", "친부", "넷"),
            [("warning", "attribute_surface_differs")], id="entity_valued_reversal",
        ),
        pytest.param(
            _attribute(1, "하나의 성별은 남자다.", "성별", "남자"), _attribute(6, "하나의 성별은 여자다.", "성별", "여자"),
            [("warning", "attribute_surface_differs")], id="gender_not_in_the_dictionary",
        ),
        pytest.param(
            _attribute(1, "하나의 키는 170cm이다.", "키", "170cm"), _attribute(6, "하나의 키는 67in이다.", "키", "67in"),
            [("warning", "attribute_surface_differs")], id="numbers_in_different_units",
        ),
    ],
)
async def test_attribute_differences_block_only_when_both_are_immutable_closed_values(
    db_session: AsyncSession, first: Chapter, second: Chapter, expected: list[tuple[str, str]]
) -> None:
    """깨지는 시나리오: 한쪽만 불변이어도 막으면 변장·염색이 막히고, 자유 서술·개체 참조·성별 값을 막으면 정체·출생 반전
    원고를 확정할 수 없다."""
    _, confirmed = await _story(db_session, first, second)
    assert await _rules_of(db_session, confirmed.commit_id) == expected


# ── 공통 ────────────────────────────────────────────────────────────


async def test_a_block_whose_canon_evidence_no_longer_matches_its_block_becomes_a_warning(
    db_session: AsyncSession,
) -> None:
    """정본 사망 사실의 원고 근거 블록을 그 개정에 없는 블록으로 조작한다. 차단 조건은 맞지만 근거를 다시 확인할 수 없어 경고로
    낮추고 원래 규칙 이름을 남긴다."""
    novel = await make_novel(db_session)
    death = await _confirm(db_session, novel.id, _death())
    assert await _status(db_session, death.commit_id) == "committed"
    dead = await db_session.scalar(select(NovelBibleFact.id).where(NovelBibleFact.novel_id == novel.id))
    await db_session.execute(
        update(NovelBibleEvidence).where(NovelBibleEvidence.item_id == dead).values(block_id=uuid.uuid4())
    )
    confirmed = await _confirm(db_session, novel.id, _appearance())
    assert await _status(db_session, confirmed.commit_id) == "committed"
    (finding,) = await _findings(db_session, confirmed.commit_id)
    assert (finding.severity, finding.rule, finding.payload["rule"]) == (
        "warning", "evidence_unverified", "exit_then_appearance"
    )


async def test_a_conflict_already_in_canon_does_not_block_a_chapter_that_is_not_part_of_it(
    db_session: AsyncSession,
) -> None:
    """3화 사망과 5화 등장이 규칙 없이 이미 정본에 있다. 7화 확정은 그 쌍에 끼지 않으므로 결과가 없다."""
    novel = await make_novel(db_session)
    for spec in (_death(), _appearance()):
        planted = await _confirm(db_session, novel.id, spec, rules=[])
        assert await _status(db_session, planted.commit_id) == "committed"
    confirmed = await _confirm(db_session, novel.id, Chapter(7, (GARDEN,), events=(Ev((1,), ("둘",)),)))
    assert await _status(db_session, confirmed.commit_id) == "committed"
    assert await _rules_of(db_session, confirmed.commit_id) == []


async def test_a_reserved_status_row_is_not_part_of_the_check(db_session: AsyncSession) -> None:
    """사망 사실이 확정이 아닌 예약 상태(제안)면 검사 스냅숏에 들지 않는다."""
    novel = await make_novel(db_session)
    death = await _confirm(db_session, novel.id, _death())
    assert await _status(db_session, death.commit_id) == "committed"
    await db_session.execute(
        update(NovelBibleFact).where(NovelBibleFact.novel_id == novel.id).values(status="proposed")
    )
    confirmed = await _confirm(db_session, novel.id, _appearance())
    assert await _status(db_session, confirmed.commit_id) == "committed"
    assert await _rules_of(db_session, confirmed.commit_id) == []


async def test_a_blocked_commit_keeps_its_warnings_too(db_session: AsyncSession) -> None:
    """차단된 확정에도 경고 결과 행이 남는다."""
    novel = await make_novel(db_session)
    death = await _confirm(db_session, novel.id, _death())
    assert await _status(db_session, death.commit_id) == "committed"
    confirmed = await _confirm(db_session, novel.id, _appearance(uses=(("하나", "활", "object"),)))
    assert await _status(db_session, confirmed.commit_id) == "blocked"
    assert await _rules_of(db_session, confirmed.commit_id) == [
        ("block", "exit_then_appearance"), ("warning", "use_without_acquisition")
    ]


_INDEPENDENCE = (
    Chapter(1, ("하나의 성격은 차분함이다.", "하나가 대장간에서 반지를 받는다."),
            events=(Ev((1, 2), ("하나",)),),
            facts=(Fa(1, "하나", "attribute", "차분함", attribute="성격", immutable=True),
                   Fa(2, "하나", "possession", "반지", onset=True))),
    Chapter(2, ("하나의 성격은 거침이다.", "하나가 활을 쏜다.", "둘은 하나가 반지를 받은 것을 안다."),
            events=(Ev((1, 2), ("하나",), uses=(("하나", "활", "object"),)), Ev((3,), ("둘",))),
            facts=(Fa(1, "하나", "attribute", "거침", attribute="성격", immutable=True),),
            knowledge=(Kn(3, "둘", "knows", "하나", "possession", "반지"),)),
)


@pytest.mark.parametrize("dropped", ["events", "facts", "knowledge"])
async def test_dropping_a_slot_skips_only_the_rules_that_read_it(db_session: AsyncSession, dropped: SlotId) -> None:
    """같은 두 화를 실제 등록부의 추출 슬롯 셋과, 하나를 뺀 부분집합으로 확정한다. 뺀 슬롯을 읽는 규칙은 결과를 내지 않고
    나머지 규칙의 결과는 같다. 깨지는 시나리오: 규칙이 선언하지 않은 슬롯의 빈 칸을 읽거나, 검사 틀이 선언한 슬롯을 보지 않으면
    슬롯 하나를 뺀 등록부에서 확정이 실패하거나 다른 결과가 나온다."""
    outcomes: dict[str, list[tuple[str, str]]] = {}
    for label, slot_ids in [("full", _EXTRACTING), ("partial", tuple(s for s in _EXTRACTING if s != dropped))]:
        _, confirmed = await _story(db_session, *_INDEPENDENCE, registry=_registry(*slot_ids))
        assert await _status(db_session, confirmed.commit_id) == "committed"
        outcomes[label] = await _rules_of(db_session, confirmed.commit_id)
    assert outcomes["full"] == [
        ("warning", "attribute_surface_differs"), ("warning", "knowledge_source_unclear"),
        ("warning", "use_without_acquisition"),
    ]
    reads: dict[str, frozenset[SlotId]] = {rule.rule: rule.slots for rule in RULES}
    assert outcomes["partial"] == [found for found in outcomes["full"] if dropped not in reads[found[1]]]


# ── 닫힌 값 사전 ────────────────────────────────────────────────────


def _fact_row(value: str, *, subject: uuid.UUID, immutable: bool = True) -> FactRow:
    return FactRow(
        id=uuid.uuid4(), chapter_id=uuid.uuid4(), fact_key=uuid.uuid4(), subject_entity_id=subject, kind="attribute",
        predicate_norm="속성", value=value, value_norm=normalize_name(value), value_entity_id=None, holds=True,
        immutable=immutable, onset=False, scope="work", valid_from_event_id=None,
    )


def _attribute_rules(first: str, second: str) -> list[str]:
    """같은 주어·술어의 불변 속성 두 값(둘째가 이번 확정의 새 항목)에 사실만 읽는 두 규칙이 내는 결과 이름."""
    subject = uuid.uuid4()
    old, new = _fact_row(first, subject=subject), _fact_row(second, subject=subject)
    snapshot = BibleSnapshot(events=None, relations=None, facts=(old, new), knowledge=None, new_ids=frozenset({new.id}))
    return sorted(
        finding.rule
        for rule in RULES
        if rule.rule in ("immutable_attribute_mismatch", "attribute_surface_differs")
        for finding in rule.check(snapshot)
    )


def _dictionary() -> dict[str, tuple[str, str]]:
    from api.novel_bible.rules.blocking import CLOSED_ATTRIBUTE_VALUES

    return dict(CLOSED_ATTRIBUTE_VALUES)


def test_the_closed_value_dictionary_has_two_categories_and_keys_in_normal_form() -> None:
    dictionary = _dictionary()
    assert {category for category, _ in dictionary.values()} == {"혈액형", "색"}
    assert all(key == normalize_name(key) for key in dictionary)


def test_gender_is_not_a_closed_value() -> None:
    """위장 신분이 드러나는 반전("알고 보니 여자였다")이 차단 표면이 되지 않게 성별은 사전에 넣지 않는다."""
    dictionary = _dictionary()
    for value in ("남자", "여자", "남성", "여성", "남", "여", "male", "female", "man", "woman"):
        assert normalize_name(value) not in dictionary


def test_common_spellings_share_one_canonical_value() -> None:
    dictionary = _dictionary()
    assert dictionary["a"] == dictionary["a형"] == ("혈액형", "A")
    assert dictionary["ab형"] == ("혈액형", "AB")
    assert dictionary["검정"] == dictionary["검은색"] == ("색", "검정")
    assert dictionary["흰색"] == dictionary["하양"] == ("색", "하양")


def _dictionary_entries() -> list[tuple[str, str, str]]:
    try:
        return [(key, category, value) for key, (category, value) in _dictionary().items()]
    except ImportError:
        return [("(사전 없음)", "", "")]


@pytest.mark.parametrize(("surface", "category", "canonical"), _dictionary_entries())
def test_every_dictionary_entry_blocks_a_different_value_of_its_category_and_not_its_own(
    surface: str, category: str, canonical: str
) -> None:
    """항목마다 합성 값 두 쌍: 같은 범주의 다른 정규 값과는 차단, 같은 정규 값의 다른 표기와는 결과가 없다."""
    dictionary = _dictionary()
    other = next(key for key, (cat, value) in dictionary.items() if cat == category and value != canonical)
    same = next(key for key, (cat, value) in dictionary.items() if (cat, value) == (category, canonical))
    assert _attribute_rules(other, surface) == ["immutable_attribute_mismatch"]
    assert _attribute_rules(same, surface) == []


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        pytest.param("1990년", "1992년", ["immutable_attribute_mismatch"], id="years"),
        pytest.param("170cm", "170 cm", [], id="space_before_the_unit"),
        pytest.param("1.50m", "1.5m", [], id="same_number"),
        pytest.param("+3", "-3", ["immutable_attribute_mismatch"], id="signs"),
        pytest.param("170cm", "170kg", ["attribute_surface_differs"], id="units_differ"),
        pytest.param("12개월가량", "13개월가량", ["attribute_surface_differs"], id="unit_longer_than_three"),
        pytest.param("١٢", "١٣", ["attribute_surface_differs"], id="not_arabic_digits"),
        pytest.param("A형", "170cm", ["attribute_surface_differs"], id="categories_differ"),
    ],
)
def test_numbers_are_closed_values_with_their_unit(first: str, second: str, expected: list[str]) -> None:
    assert _attribute_rules(first, second) == expected


def test_one_mutable_side_or_a_value_outside_the_dictionary_only_warns() -> None:
    subject = uuid.uuid4()
    old, new = _fact_row("A형", subject=subject), _fact_row("B형", subject=subject, immutable=False)
    snapshot = BibleSnapshot(events=None, relations=None, facts=(old, new), knowledge=None, new_ids=frozenset({new.id}))
    (warning,) = [finding for rule in RULES for finding in rule.check(snapshot)]
    assert (warning.severity, warning.rule, warning.payload["judge"]) == ("warning", "attribute_surface_differs", "J2")
