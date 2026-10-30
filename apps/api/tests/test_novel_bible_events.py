"""정본 기억 사건 슬롯 — 원고에서 사건과 회상 사건의 앞뒤 관계를 뽑아 사건 표에 쓴다.

입력은 확정 개정의 문단(장면 경계 표시 포함), 장면 구성안의 장면 제목·회상 표시, 아는 개체, 앞 화의 주선 사건 목록이다.
장면 구성안이 없는 화는 화 전체가 장면 하나이고 회상 여부는 모델 출력으로만 정한다. 검증은 항목 하나씩 버리고 출력 전체를
버리지 않는다. 쓰기는 자기 표(사건·회상 관계)뿐이고, 화를 다시 확정하면 그 화의 사건·관계가 만료된다.

원고·장면 제목은 합성 문장이고 모델은 가짜 어댑터다(정해 둔 출력을 차례로 돌려준다)."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import NovelChapter, NovelChapterRevision
from api.db.models.novel import NovelEpisodeOutline, NovelOutline, NovelSceneBlock
from api.db.models.novel_bible import NovelBibleCommit, NovelBibleEntity, NovelBibleExpiration, NovelBibleRevision
from api.db.models.novel_bible_events import NovelBibleEvent, NovelBibleEventRelation
from api.db.models.novel_bible_facts import NovelBibleFact
from api.db.models.novel_bible_knowledge import NovelBibleKnowledge
from api.db.models.prompt import PromptSection
from api.novel_bible.core.confirm import Actor, confirm
from api.novel_bible.core.contracts import (
    AdapterCapabilities,
    BibleModelAdapter,
    PromptSource,
    Registry,
)
from api.novel_bible.core.pipeline import run_until_idle
from api.novel_bible.core.positions import Bound, Interval, precedes, story_positions
from api.novel_bible.core.queries import bible_at, revision_at
from api.novel_bible.core.types import (
    CommitRef,
    EntityName,
    EventRow,
    Manuscript,
    ManuscriptBlock,
    RelationRow,
    RenderedPrompt,
    SceneHint,
)
from api.novel_bible.core.views import CommitView
from api.novel_bible.ids import EventActuality, OperationKey
from api.novel_bible.registry import REGISTRY
from api.novel_bible.slots.events.schema import EventsOutput
from api.novel_bible.slots.events.slot import EventsInput, EventsSlot, PriorEvent
from novel_bible_fakes import add_chapter, add_revision, make_novel, plant_revision, savepoint_factory

T = TypeVar("T", bound=BaseModel)
SYSTEM = Actor(kind="system")
CHANNEL = "novel_bible_events"


# ── 합성 입력 ────────────────────────────────────────────────────────


def _manuscript(*texts: str) -> Manuscript:
    blocks = tuple(
        ManuscriptBlock(index=number, block_id=uuid.uuid4(), text=text) for number, text in enumerate(texts, start=1)
    )
    return Manuscript(revision_id=uuid.uuid4(), blocks=blocks)


def _event(
    key: str, paragraphs: list[int], quote: tuple[int, str], *, actuality: EventActuality = "present",
    present: list[str] | None = None, mentioned: list[str] | None = None, uses: list[dict[str, str]] | None = None,
    summary: str = "합성 요지",
) -> dict[str, Any]:
    return {
        "key": key, "summary": summary, "paragraphs": paragraphs, "actuality": actuality,
        "present": present or [], "mentioned": mentioned or [], "uses": uses or [],
        "quote": {"paragraph": quote[0], "text": quote[1]},
    }


def _output(events: list[dict[str, Any]], relations: list[dict[str, str]] | None = None) -> EventsOutput:
    return EventsOutput.model_validate({"events": events, "relations": relations or []})


def _input(
    manuscript: Manuscript, *, scenes: list[SceneHint] | None = None, prior: list[PriorEvent] | None = None,
    known: list[EntityName] | None = None,
) -> EventsInput:
    return EventsInput(manuscript=manuscript, scenes=scenes or [], known=known or [], prior=prior or [])


def _view(db: AsyncSession, chapter: NovelChapter, revision: NovelChapterRevision) -> CommitView:
    ref = CommitRef(
        commit_id=uuid.uuid4(), novel_id=chapter.novel_id, chapter_id=chapter.id, chapter_revision_id=revision.id,
        chapter_ordinal=chapter.ordinal, scope="character",
    )
    return CommitView(db, Registry(extracting={}, source=None), ref, None)


async def _outline(
    db: AsyncSession, chapter: NovelChapter, scenes: list[dict[str, Any]], assignment: dict[uuid.UUID, str],
    *, revision: int = 1,
) -> NovelEpisodeOutline:
    """장면 구성안 한 판과 블록마다 장면 행. `assignment` 에 없는 블록은 수정으로 생긴 새 블록처럼 행이 없다."""
    outline = NovelOutline(
        novel_id=chapter.novel_id, revision=revision, source="generate", selection_id=uuid.uuid4(), episodes=[]
    )
    db.add(outline)
    await db.flush()
    episode = NovelEpisodeOutline(
        novel_id=chapter.novel_id, outline_id=outline.id, episode_key=uuid.uuid4(), revision=revision,
        source="generate", scenes=scenes,
    )
    db.add(episode)
    await db.flush()
    db.add_all(
        NovelSceneBlock(block_id=block_id, chapter_id=chapter.id, episode_outline_id=episode.id, scene_id=scene_id)
        for block_id, scene_id in assignment.items()
    )
    await db.flush()
    return episode


# ── 입력 ────────────────────────────────────────────────────────────


async def test_the_input_marks_scene_boundaries_and_gives_only_titles_and_flashback_marks(
    db_session: AsyncSession,
) -> None:
    novel = await make_novel(db_session)
    body = "첫째 문단이다.\n\n둘째 문단이다.\n\n셋째 문단이다.\n\n넷째 문단이다."
    chapter, revision = await add_chapter(db_session, novel.id, 1, body)
    b1, b2, b3, b4 = revision.block_ids
    scenes = [
        {"id": "s1", "title": "정원의 오후", "flashback": False, "summary": "구성안 내용 문장"},
        {"id": "s2", "title": "어린 날", "flashback": True, "summary": "구성안 내용 문장"},
    ]
    # 넷째 블록은 행이 없다 — 앞 블록의 장면으로 읽는다.
    await _outline(db_session, chapter, scenes, {b1: "s1", b2: "s1", b3: "s2"})

    slot_input = await EventsSlot().build_input(db_session, _view(db_session, chapter, revision))

    assert isinstance(slot_input, EventsInput)
    assert slot_input.scenes == [
        SceneHint(scene_key="s1", title="정원의 오후", flashback=False, block_ids=(b1, b2)),
        SceneHint(scene_key="s2", title="어린 날", flashback=True, block_ids=(b3, b4)),
    ]
    values = EventsSlot().prompt_values(slot_input)
    assert values["manuscript"] == (
        "[장면 1]\n[1] 첫째 문단이다.\n[2] 둘째 문단이다.\n[장면 2]\n[3] 셋째 문단이다.\n[4] 넷째 문단이다."
    )
    assert values["scene_hints"] == "장면 1. 정원의 오후\n장면 2. 어린 날 (회상)"
    assert all("구성안 내용 문장" not in value for value in values.values())


async def test_flashback_marks_come_from_the_latest_outline_and_an_old_outline_without_marks_is_not_flashback(
    db_session: AsyncSession,
) -> None:
    """같은 장면 id 가 여러 판에 있으면 판 번호가 가장 큰 판의 회상 표시를 쓰고, 회상 표시 칸이 없는 옛 판의 장면은 회상이
    아니다. 깨지는 시나리오: 옛 판이 이기면 고친 판에서 회상으로 바꾼 장면이 현재 사건으로 남고, 칸이 없는 판을 회상으로 읽으면
    옛 화의 사건이 전부 회상으로 올라간다."""
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, "첫째 문단이다.\n\n둘째 문단이다.\n\n셋째 문단이다.")
    b1, b2, b3 = revision.block_ids
    # 새 판을 먼저 넣는다 — 넣은 차례가 아니라 판 번호가 이겨야 한다.
    await _outline(db_session, chapter, [{"id": "s1", "title": "정원", "flashback": True}], {b2: "s1"}, revision=2)
    await _outline(
        db_session, chapter, [{"id": "s1", "title": "정원", "flashback": False}, {"id": "s2", "title": "옛 판 장면"}],
        {b1: "s1", b3: "s2"}, revision=1,
    )

    hints = await _view(db_session, chapter, revision).scene_hints()

    assert hints == [
        SceneHint(scene_key="s1", title="정원", flashback=True, block_ids=(b1, b2)),
        SceneHint(scene_key="s2", title="옛 판 장면", flashback=False, block_ids=(b3,)),
    ]


def test_the_known_entities_hint_is_one_sorted_line_per_entity_with_its_kind_and_aliases() -> None:
    """아는 개체는 개체마다 한 줄 `- 이름 (종류)` 에 별칭 꼬리이고, 같은 줄은 한 번만 글자 순으로 싣는다. 깨지는 시나리오: 줄
    꼴이 바뀌면 그 꼴을 설명하는 문안 지시문과 어긋나, 모델이 종류·별칭 꼬리를 이름으로 옮겨 다른 개체가 생긴다."""
    one = EntityName(kind="character", name="하나", aliases=("큰언니", "하나야"))
    known = [EntityName(kind="object", name="열쇠"), one, EntityName(kind="ability", name="비행"), one]

    values = EventsSlot().prompt_values(_input(_manuscript("합성 문단."), known=known))

    assert values["known_entities"] == "- 비행 (능력)\n- 열쇠 (사물)\n- 하나 (인물) — 별칭: 큰언니, 하나야"


async def test_a_chapter_without_a_scene_outline_reads_as_one_scene_without_hints(db_session: AsyncSession) -> None:
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, "첫째 문단이다.\n\n둘째 문단이다.")

    slot_input = await EventsSlot().build_input(db_session, _view(db_session, chapter, revision))

    assert isinstance(slot_input, EventsInput)
    assert slot_input.scenes == []
    values = EventsSlot().prompt_values(slot_input)
    assert values["manuscript"] == "[1] 첫째 문단이다.\n[2] 둘째 문단이다."
    assert values["scene_hints"] == ""


async def test_prior_events_are_the_current_main_line_events_of_earlier_chapters(db_session: AsyncSession) -> None:
    novel = await make_novel(db_session)
    first, first_revision = await add_chapter(db_session, novel.id, 1, "가 문단.\n\n나 문단.\n\n다 문단.")
    second, second_revision = await add_chapter(db_session, novel.id, 2, "라 문단.")
    third, third_revision = await add_chapter(db_session, novel.id, 3, "마 문단.")
    bible = await plant_revision(db_session, novel.id, first.id, first_revision.id)
    common = {"novel_id": novel.id, "created_revision_id": bible.id}
    a, b, c = first_revision.block_ids
    db_session.add_all(
        [
            NovelBibleEvent(chapter_id=first.id, ordinal=1, actuality="present", summary="앞 화 주선 사건",
                            anchor_block_ids=[a, b], **common),
            NovelBibleEvent(chapter_id=first.id, ordinal=2, actuality="flashback", summary="앞 화 회상 사건",
                            anchor_block_ids=[b], **common),
            NovelBibleEvent(chapter_id=first.id, ordinal=3, actuality="dream_or_imagined", summary="앞 화 꿈 사건",
                            anchor_block_ids=[c], **common),
            NovelBibleEvent(chapter_id=first.id, ordinal=4, actuality="present", summary="앞 화 두번째 주선 사건",
                            anchor_block_ids=[c], **common),
            NovelBibleEvent(chapter_id=third.id, ordinal=1, actuality="present", summary="뒤 화 주선 사건",
                            anchor_block_ids=third_revision.block_ids, **common),
        ]
    )
    await db_session.flush()

    slot_input = await EventsSlot().build_input(db_session, _view(db_session, second, second_revision))

    assert isinstance(slot_input, EventsInput)
    assert slot_input.prior == [
        PriorEvent(label="P1", chapter_id=first.id, chapter_ordinal=1, summary="앞 화 주선 사건", target_block_id=a),
        PriorEvent(label="P2", chapter_id=first.id, chapter_ordinal=1, summary="앞 화 두번째 주선 사건",
                   target_block_id=c),
    ]
    assert EventsSlot().prompt_values(slot_input)["prior_events"] == (
        "P1. 1화 — 앞 화 주선 사건\nP2. 1화 — 앞 화 두번째 주선 사건"
    )


async def test_a_relation_target_block_is_one_that_only_the_target_event_covers(db_session: AsyncSession) -> None:
    """앞 화 사건끼리 문단을 함께 덮으면 관계 대상 블록은 대상 사건만 덮는 첫 블록이고, 그런 블록이 없는 사건은 대상 블록이
    없다. 깨지는 시나리오: 대상 사건의 첫 블록을 저장하면 읽는 쪽이 그 블록을 덮는 앞 차례 사건으로 풀어, 회상의 끝이 더 이른
    점으로 조여진다."""
    novel = await make_novel(db_session)
    first, first_revision = await add_chapter(db_session, novel.id, 1, "가 문단.\n\n나 문단.\n\n다 문단.\n\n라 문단.")
    second, second_revision = await add_chapter(db_session, novel.id, 2, "마 문단.")
    bible = await plant_revision(db_session, novel.id, first.id, first_revision.id)
    common = {"novel_id": novel.id, "chapter_id": first.id, "created_revision_id": bible.id, "actuality": "present"}
    a, b, c, d = first_revision.block_ids
    db_session.add_all(
        [
            NovelBibleEvent(ordinal=1, summary="앞 사건", anchor_block_ids=[a, b], **common),
            NovelBibleEvent(ordinal=2, summary="겹친 사건", anchor_block_ids=[b, c], **common),
            NovelBibleEvent(ordinal=3, summary="가려진 사건", anchor_block_ids=[c], **common),
            NovelBibleEvent(ordinal=4, summary="뒤 사건", anchor_block_ids=[d], **common),
        ]
    )
    await db_session.flush()

    slot_input = await EventsSlot().build_input(db_session, _view(db_session, second, second_revision))

    assert isinstance(slot_input, EventsInput)
    assert [prior.target_block_id for prior in slot_input.prior] == [a, c, None, d]
    target = slot_input.prior[1].target_block_id
    assert target is not None
    head = await revision_at(db_session, novel.id, None)
    events = [row for row in await EventsSlot().read(db_session, novel.id, head) if isinstance(row, EventRow)]
    recalled = EventRow(
        id=uuid.uuid4(), chapter_id=second.id, chapter_ordinal=2, ordinal=1, actuality="flashback",
        anchor_block_ids=tuple(second_revision.block_ids),
    )
    relation = RelationRow(
        id=uuid.uuid4(), chapter_id=second.id, from_event_id=recalled.id, relation="before", to_anchor_block_id=target,
        to_chapter_id=first.id,
    )
    # 겹친 사건(1화 2번째)의 점에서 위 끝이 닫힌다 — 앞 사건(1화 1번째)으로 풀리지 않는다.
    assert story_positions([*events, recalled], [relation])[recalled.id] == Interval(None, Bound((1, 2), exclusive=True))


# ── 검증 ────────────────────────────────────────────────────────────


def test_validation_drops_bad_events_one_by_one_and_orders_the_rest_by_first_paragraph() -> None:
    manuscript = _manuscript("하나가 문을 연다.", "둘이 들어온다.", "셋이 웃는다.")
    names = [f"인물{n}" for n in range(25)]
    output = _output(
        [
            _event("e1", [3], (3, "셋이 웃는다"), present=["셋", " "], mentioned=names),
            _event("e2", [1, 2], (2, "둘이 들어온다"), present=["하나", "둘"],
                   uses=[{"actor": "하나", "thing": "열쇠", "thing_kind": "object"},
                         {"actor": "", "thing": "문", "thing_kind": "object"}]),
            _event("e3", [], (1, "하나가")),
            _event("e4", [1, 4], (1, "하나가")),
            _event("e5", [1], (2, "둘이")),
            _event("e6", [2], (2, "없는 구절")),
        ]
    )

    proposal = EventsSlot().validate(_input(manuscript), output)

    assert proposal.dropped == {"paragraphs_invalid": 2, "quote_outside_event": 1, "quote_not_found": 1}
    first, second = proposal.items
    assert [draft.fields["ordinal"] for draft in proposal.items] == [1, 2]
    assert first.covers_blocks == (manuscript.blocks[0].block_id, manuscript.blocks[1].block_id)
    assert first.quotes[0].block_id == manuscript.blocks[1].block_id
    assert [name.name for name in first.names["present"]] == ["하나", "둘"]
    assert [(n.kind, n.name) for n in first.names["use_actors"]] == [("character", "하나")]
    assert [(n.kind, n.name) for n in first.names["use_things"]] == [("object", "열쇠")]
    assert [name.name for name in second.names["present"]] == ["셋"]
    assert [name.name for name in second.names["mentioned"]] == names[:20]
    assert all(draft.table == "event" and draft.fields["scene_key"] is None for draft in proposal.items)


def test_validation_takes_flashback_from_the_scene_outline_but_never_demotes_the_model() -> None:
    manuscript = _manuscript("지금 문단.", "지금 둘째 문단.", "옛날 문단.", "옛날 둘째 문단.")
    blocks = [block.block_id for block in manuscript.blocks]
    scenes = [
        SceneHint(scene_key="s1", title="지금", flashback=False, block_ids=(blocks[0], blocks[1])),
        SceneHint(scene_key="s2", title="옛날", flashback=True, block_ids=(blocks[2], blocks[3])),
    ]
    output = _output(
        [
            _event("now", [1], (1, "지금 문단"), actuality="present"),
            _event("told", [2], (2, "지금 둘째"), actuality="flashback"),
            _event("past", [3, 4], (3, "옛날 문단"), actuality="present"),
            _event("dream", [4], (4, "옛날 둘째"), actuality="dream_or_imagined"),
        ]
    )

    proposal = EventsSlot().validate(_input(manuscript, scenes=scenes), output)

    stored = [(draft.fields["scene_key"], draft.fields["actuality"]) for draft in proposal.items]
    assert stored == [("s1", "present"), ("s1", "flashback"), ("s2", "flashback"), ("s2", "dream_or_imagined")]


def test_without_a_scene_outline_the_model_alone_decides_flashback_and_dreams() -> None:
    manuscript = _manuscript("지금 문단.", "옛날 문단.", "꿈 문단.")
    output = _output(
        [
            _event("now", [1], (1, "지금"), actuality="present"),
            _event("past", [2], (2, "옛날"), actuality="flashback"),
            _event("dream", [3], (3, "꿈"), actuality="dream_or_imagined"),
        ]
    )

    proposal = EventsSlot().validate(_input(manuscript), output)

    assert [draft.fields["actuality"] for draft in proposal.items] == ["present", "flashback", "dream_or_imagined"]


def test_validation_resolves_relation_targets_to_blocks_and_drops_bad_relations() -> None:
    manuscript = _manuscript("지금 문단.", "옛날 문단.")
    target_chapter, target_block = uuid.uuid4(), uuid.uuid4()
    prior = [
        PriorEvent(label="P1", chapter_id=target_chapter, chapter_ordinal=1, summary="앞 사건",
                   target_block_id=target_block),
        PriorEvent(label="P2", chapter_id=target_chapter, chapter_ordinal=1, summary="가려진 사건", target_block_id=None),
    ]
    output = _output(
        [_event("now", [1], (1, "지금")), _event("past", [2], (2, "옛날"), actuality="flashback")],
        [
            {"event": "past", "relation": "before", "target": "P1"},
            {"event": "now", "relation": "after", "target": "P1"},
            {"event": "nowhere", "relation": "before", "target": "P1"},
            {"event": "past", "relation": "overlap", "target": "P9"},
            {"event": "past", "relation": "after", "target": "P2"},
        ],
    )

    proposal = EventsSlot().validate(_input(manuscript, prior=prior), output)

    assert proposal.dropped == {
        "relation_not_flashback": 1, "relation_event_unknown": 1, "relation_target_unknown": 1,
        "relation_target_ambiguous": 1,
    }
    relations = [draft for draft in proposal.items if draft.table == "event_relation"]
    events = {draft.local_key: draft for draft in proposal.items if draft.table == "event"}
    assert len(relations) == 1
    relation = relations[0]
    assert events[relation.fields["event"]].fields["actuality"] == "flashback"
    assert (relation.fields["relation"], relation.fields["to_anchor_block_id"], relation.fields["to_chapter_id"]) == (
        "before", str(target_block), str(target_chapter)
    )
    assert relation.quotes == events[relation.fields["event"]].quotes


# ── 확정 한 바퀴 ─────────────────────────────────────────────────────


def _sections(prompt_set_id: uuid.UUID) -> list[PromptSection]:
    slots = [("instruction", "합성 지시문", False), ("manuscript", "{manuscript}", False),
             ("scene_hints", "{scene_hints}", True), ("known_entities", "{known_entities}", True),
             ("prior_events", "{prior_events}", True)]
    return [
        PromptSection(prompt_set_id=prompt_set_id, channel=CHANNEL, scope="both", slot=slot, variant="", body=body,
                      conditional=conditional, order=order)
        for order, (slot, body, conditional) in enumerate(slots)
    ]


@dataclass
class ScriptedAdapter:
    """정해 둔 출력을 호출마다 차례로 돌려주고, 받은 문안을 남긴다."""

    outputs: list[dict[str, Any]]
    prompts: list[RenderedPrompt] = field(default_factory=list)
    prompt_set_id: uuid.UUID = field(default_factory=uuid.uuid4)
    id: str = "scripted"
    capabilities: AdapterCapabilities = field(
        default_factory=lambda: AdapterCapabilities(structured=True, with_instruction=True, max_input_chars=100_000)
    )

    async def prompt_source(self, session: AsyncSession) -> PromptSource:
        return PromptSource(prompt_set_id=self.prompt_set_id, sections=_sections(self.prompt_set_id))

    async def structured(
        self, prompt: RenderedPrompt, schema: type[T], *, records: list[dict[str, Any]], stage: OperationKey
    ) -> T:
        self.prompts.append(prompt)
        return schema.model_validate(self.outputs.pop(0))

    def resolver(self) -> Callable[[OperationKey], BibleModelAdapter]:
        return lambda operation: self


def _registry() -> Registry:
    return Registry(extracting={"events": EventsSlot()}, source=None)


async def _confirm_and_run(
    db: AsyncSession, chapter: NovelChapter, revision: NovelChapterRevision, adapter: ScriptedAdapter
) -> uuid.UUID:
    result = await confirm(
        db, _registry(), novel_id=chapter.novel_id, chapter_id=chapter.id, revision_id=revision.id, actor=SYSTEM
    )
    await run_until_idle(savepoint_factory(db), _registry(), [], adapter.resolver())
    return result.commit_id


async def _status(db: AsyncSession, commit_id: uuid.UUID) -> str | None:
    status: str | None = await db.scalar(select(NovelBibleCommit.status).where(NovelBibleCommit.id == commit_id))
    return status


async def _entity_id(db: AsyncSession, novel_id: uuid.UUID, kind: str, name: str) -> uuid.UUID | None:
    entity_id: uuid.UUID | None = await db.scalar(
        select(NovelBibleEntity.id).where(
            NovelBibleEntity.novel_id == novel_id, NovelBibleEntity.kind == kind, NovelBibleEntity.name_norm == name
        )
    )
    return entity_id


async def _events(db: AsyncSession, chapter_id: uuid.UUID) -> list[NovelBibleEvent]:
    return list(
        (
            await db.scalars(
                select(NovelBibleEvent).where(NovelBibleEvent.chapter_id == chapter_id).order_by(NovelBibleEvent.ordinal)
            )
        ).all()
    )


FIRST_BODY = "하나가 정원에서 검을 든다.\n\n둘이 하나를 부른다.\n\n하나는 날아오르는 꿈을 꾼다."
SECOND_BODY = "둘이 시장에 간다.\n\n둘은 어린 날 정원을 떠올린다."


def _first_output() -> dict[str, Any]:
    return {
        "events": [
            _event("e1", [1, 2], (1, "하나가 정원에서"), present=["하나", "둘"], mentioned=["셋"],
                   uses=[{"actor": "하나", "thing": "검", "thing_kind": "object"}], summary="정원의 만남"),
            _event("e2", [3], (3, "날아오르는 꿈"), actuality="dream_or_imagined", present=["하나"],
                   summary="하나의 꿈"),
        ],
        "relations": [],
    }


def _second_output(relation: str = "before") -> dict[str, Any]:
    return {
        "events": [
            _event("e1", [1], (1, "시장에 간다"), present=["둘"], summary="시장 나들이"),
            _event("e2", [2], (2, "어린 날 정원을"), actuality="flashback", mentioned=["하나"], summary="정원 회상"),
        ],
        "relations": [{"event": "e2", "relation": relation, "target": "P1"}],
    }


async def test_a_confirmed_chapter_commits_its_events_with_linked_entities_and_actuality(
    db_session: AsyncSession,
) -> None:
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, FIRST_BODY)
    adapter = ScriptedAdapter([_first_output()])

    commit_id = await _confirm_and_run(db_session, chapter, revision, adapter)

    assert await _status(db_session, commit_id) == "committed"
    main, dream = await _events(db_session, chapter.id)
    one = await _entity_id(db_session, novel.id, "character", "하나")
    two = await _entity_id(db_session, novel.id, "character", "둘")
    three = await _entity_id(db_session, novel.id, "character", "셋")
    sword = await _entity_id(db_session, novel.id, "object", "검")
    assert (main.ordinal, main.actuality, main.scene_key, main.summary) == (1, "present", None, "정원의 만남")
    assert main.anchor_block_ids == revision.block_ids[:2]
    assert main.present_entity_ids == [one, two] and main.mentioned_entity_ids == [three]
    assert main.uses == [{"actor": str(one), "thing": str(sword)}]
    assert (dream.ordinal, dream.actuality, dream.anchor_block_ids) == (2, "dream_or_imagined", revision.block_ids[2:])
    # 이 슬롯은 사건 표 밖에 쓰지 않는다.
    for model in (NovelBibleFact, NovelBibleKnowledge, NovelBibleEventRelation):
        assert await db_session.scalar(select(func.count()).select_from(model).where(model.novel_id == novel.id)) == 0


async def test_a_flashback_relation_points_at_the_earlier_event_and_orders_story_time(
    db_session: AsyncSession,
) -> None:
    novel = await make_novel(db_session)
    first, first_revision = await add_chapter(db_session, novel.id, 1, FIRST_BODY)
    second, second_revision = await add_chapter(db_session, novel.id, 2, SECOND_BODY)
    adapter = ScriptedAdapter([_first_output(), _second_output()])
    await _confirm_and_run(db_session, first, first_revision, adapter)

    commit_id = await _confirm_and_run(db_session, second, second_revision, adapter)

    assert await _status(db_session, commit_id) == "committed"
    # 앞 화 목록에는 주선 사건만 있다 — 꿈 사건은 회상 관계의 대상이 될 수 없다.
    assert "P1. 1화 — 정원의 만남" in adapter.prompts[1].prompt
    assert "하나의 꿈" not in adapter.prompts[1].prompt
    earlier, _ = await _events(db_session, first.id)
    _, recalled = await _events(db_session, second.id)
    relation = await db_session.scalar(
        select(NovelBibleEventRelation).where(NovelBibleEventRelation.novel_id == novel.id)
    )
    assert relation is not None
    assert (relation.from_event_id, relation.relation) == (recalled.id, "before")
    assert (relation.to_anchor_block_id, relation.to_chapter_id) == (first_revision.block_ids[0], first.id)

    snapshot = await bible_at(db_session, novel.id, _registry(), revision_no=None)
    assert snapshot.events is not None and snapshot.relations is not None
    positions = story_positions(snapshot.events, snapshot.relations)
    assert precedes(positions[recalled.id], positions[earlier.id]) is True


async def test_reconfirming_a_chapter_expires_its_events_and_relations(db_session: AsyncSession) -> None:
    novel = await make_novel(db_session)
    first, first_revision = await add_chapter(db_session, novel.id, 1, FIRST_BODY)
    second, second_revision = await add_chapter(db_session, novel.id, 2, SECOND_BODY)
    adapter = ScriptedAdapter([_first_output(), _second_output("before"), _second_output("overlap")])
    await _confirm_and_run(db_session, first, first_revision, adapter)
    await _confirm_and_run(db_session, second, second_revision, adapter)
    old_ids = {event.id for event in await _events(db_session, second.id)}
    old_relation = await db_session.scalar(
        select(NovelBibleEventRelation.id).where(NovelBibleEventRelation.novel_id == novel.id)
    )
    replacement = await add_revision(db_session, second.id, SECOND_BODY + "\n\n둘이 집에 돌아온다.")

    commit_id = await _confirm_and_run(db_session, second, replacement, adapter)

    assert await _status(db_session, commit_id) == "committed"
    head = await revision_at(db_session, novel.id, None)
    expired = (
        await db_session.execute(
            select(NovelBibleExpiration.item_table, NovelBibleExpiration.item_id, NovelBibleExpiration.reason).where(
                NovelBibleExpiration.revision_id == head.id
            )
        )
    ).all()
    assert {(row.item_table, row.item_id, row.reason) for row in expired} == {
        *(("event", event_id, "chapter_replaced") for event_id in old_ids),
        ("event_relation", old_relation, "chapter_replaced"),
    }
    slot = EventsSlot()
    now = await slot.read(db_session, novel.id, head)
    before = await slot.read(db_session, novel.id, await revision_at(db_session, novel.id, head.revision_no - 1))
    now_second = {row.id for row in now if isinstance(row, EventRow) and row.chapter_id == second.id}
    assert now_second and not now_second & old_ids
    assert {row.id for row in before if isinstance(row, EventRow) and row.chapter_id == second.id} == old_ids
    assert [row.relation for row in now if isinstance(row, RelationRow)] == ["overlap"]
    current = await slot.current_item_ids(db_session, novel.id, second.id, head)
    assert {item_id for table, item_id in current if table == "event"} == now_second
    revisions = await db_session.scalar(
        select(func.count()).select_from(NovelBibleRevision).where(NovelBibleRevision.novel_id == novel.id)
    )
    assert revisions == 3


async def test_a_same_text_reconfirm_reuses_the_extraction_unless_a_scene_flashback_mark_changed(
    db_session: AsyncSession,
) -> None:
    """아는 개체가 바뀌어도 본문·블록이 같은 재확정은 추출을 다시 쓰고, 장면 구성안의 회상 표시만 바뀐 같은 본문은 다시 뽑는다.
    깨지는 시나리오: 장면 힌트를 캐시 열쇠에서 빼면 회상으로 올리기 전의 옛 현실성을 재사용하고, 아는 개체를 열쇠에 넣으면 다른
    화가 커밋될 때마다 같은 본문도 다시 뽑는다."""
    novel = await make_novel(db_session)
    body = "하나가 정원에 선다.\n\n하나가 웃는다."
    chapter, revision = await add_chapter(db_session, novel.id, 1, body)
    episode = await _outline(
        db_session, chapter, [{"id": "s1", "title": "정원", "flashback": False}], dict.fromkeys(revision.block_ids, "s1")
    )
    output = {"events": [_event("e1", [1, 2], (1, "하나가 정원에"), present=["하나"])], "relations": []}
    adapter = ScriptedAdapter([output, output])
    # 첫 확정이 개체를 만들어 다음 확정의 아는 개체 힌트가 바뀐다.
    await _confirm_and_run(db_session, chapter, revision, adapter)
    same = await add_revision(db_session, chapter.id, body, block_ids=revision.block_ids)

    reused = await _confirm_and_run(db_session, chapter, same, adapter)

    assert await _status(db_session, reused) == "committed"
    assert len(adapter.prompts) == 1

    episode.scenes = [{"id": "s1", "title": "정원", "flashback": True}]
    await db_session.flush()
    marked = await add_revision(db_session, chapter.id, body, block_ids=revision.block_ids)

    fresh = await _confirm_and_run(db_session, chapter, marked, adapter)

    assert await _status(db_session, fresh) == "committed"
    assert len(adapter.prompts) == 2 and "장면 1. 정원 (회상)" in adapter.prompts[1].prompt
    rows = await EventsSlot().read(db_session, novel.id, await revision_at(db_session, novel.id, None))
    assert [row.actuality for row in rows if isinstance(row, EventRow)] == ["flashback"]


def test_the_registry_holds_the_events_slot() -> None:
    assert isinstance(REGISTRY.extracting["events"], EventsSlot)
