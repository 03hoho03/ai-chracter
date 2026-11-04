"""정본 기억 사실 슬롯 — 원고에서 상태·속성·관계 명제를 뽑아 사실 표에 쓴다.

입력은 확정 개정의 문단(번호만 — 장면 표시 없음), 아는 개체, 이미 정본인 불변 속성, 원작 정본, 플레이 사실(채팅 기억)이다. 장면
구성안은 사실 입력에 넣지 않는다. 플레이 사실은 채팅 기억 스위치와 무관하게 읽고, 방이 없으면 그 섹션이 빠진다. 검증은 항목 하나씩
버린다. 원작·플레이와 다른 사실은 정본(`confirmed`)으로 커밋되고 각색 후보가 따로 남는다 — 차단이 아니다.

원고·채팅 기억·원작 글은 합성 문장이고 모델은 가짜 어댑터다(연산마다 정해 둔 출력을 차례로 돌려준다)."""

import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, TypeVar, get_args

import pytest
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models import ChatMemoryFact, ChatRoomMemorySnapshot, Novel, NovelChapter, NovelChapterRevision
from api.db.models.novel_bible import (
    ENTITY_NAME_MAX,
    NovelBibleAdaptationCandidate,
    NovelBibleCommit,
    NovelBibleEntity,
    NovelBibleEvidence,
    NovelBibleExpiration,
    NovelBibleFinding,
    NovelBibleJob,
)
from api.db.models.novel_bible_events import NovelBibleEvent
from api.db.models.novel_bible_facts import NovelBibleFact
from api.db.models.novel_bible_knowledge import NovelBibleKnowledge
from api.db.models.prompt import PromptSection
from api.novel_bible.core.confirm import Actor, confirm
from api.novel_bible.core.contracts import AdapterCapabilities, BibleModelAdapter, PromptSource, Registry, Slot
from api.novel_bible.core.keys import StateKey, fact_key, state_key
from api.novel_bible.core.jobs import NAME_TOO_LONG
from api.novel_bible.core.known import KIND_LABELS
from api.novel_bible.core.pipeline import run_until_idle
from api.novel_bible.core.queries import facts_true_at, revision_at
from api.novel_bible.core.quotes import quote_hash, verify_quote
from api.novel_bible.core.types import (
    CommitRef,
    EntityName,
    FactRow,
    Manuscript,
    ManuscriptBlock,
    PlayFact,
    Proposal,
    QuoteOut,
    RenderedPrompt,
    SideQuote,
    SourceCanon,
    SourceCanonRef,
)
from api.novel_bible.core.views import CommitView
from api.novel_bible.ids import EntityKind, FactKind, FactScope, OperationKey
from api.novel_bible.registry import REGISTRY
from api.novel_bible.slots.events.slot import EventsInput, EventsSlot
from api.novel_bible.slots.facts.schema import FactsOutput
from api.novel_bible.slots.facts.slot import FactsInput, FactsSlot, KnownAttribute
from factories import _make_bare_chat_room, _make_memory_fact
from novel_bible_fakes import FakeSource, add_chapter, add_revision, make_novel, savepoint_factory

T = TypeVar("T", bound=BaseModel)
SYSTEM = Actor(kind="system")


# ── 합성 입력 ────────────────────────────────────────────────────────


def _manuscript(*texts: str) -> Manuscript:
    blocks = tuple(
        ManuscriptBlock(index=number, block_id=uuid.uuid4(), text=text) for number, text in enumerate(texts, start=1)
    )
    return Manuscript(revision_id=uuid.uuid4(), blocks=blocks)


def _fact(
    subject: str, kind: FactKind, value: str, quote: tuple[int, str], *, attribute: str | None = None,
    holds: bool = True, immutable: bool = False, onset: bool = False, scope: FactScope = "from_here",
    source: tuple[str, str] | None = None, play: str | None = None, subject_kind: EntityKind = "character",
) -> dict[str, Any]:
    return {
        "subject": subject, "subject_kind": subject_kind, "kind": kind, "attribute": attribute, "value": value,
        "holds": holds,
        "immutable": immutable, "onset": onset, "scope": scope,
        "quote": {"paragraph": quote[0], "text": quote[1]},
        "source_difference": {"label": source[0], "quote": source[1]} if source else None,
        "play_difference": {"ref": play} if play else None,
    }


def _output(*facts: dict[str, Any]) -> FactsOutput:
    return FactsOutput.model_validate({"facts": list(facts)})


def _input(
    manuscript: Manuscript, *, known: list[EntityName] | None = None,
    known_attributes: list[KnownAttribute] | None = None, source: SourceCanon | None = None,
    play: list[PlayFact] | None = None,
) -> FactsInput:
    return FactsInput(
        manuscript=manuscript, known=known or [], known_attributes=known_attributes or [], source=source, play=play
    )


def _play(subject: str, value: str, *, target: str | None = None, attribute: str | None = None,
          claimed: bool = False, disproved: bool = False) -> PlayFact:
    return PlayFact(
        chat_room_id=uuid.uuid4(), chat_memory_fact_id=uuid.uuid4(), chat_fact_key=f"합성|{subject}|{value}",
        subject=subject, object=target, attribute=attribute, value=value, claimed=claimed, disproved=disproved,
    )


def _canon(work_setting: str, *notes: str) -> SourceCanon:
    return SourceCanon(
        ref=SourceCanonRef(content_version_id=uuid.uuid4(), input_hash="합성 해시"),
        work_setting=work_setting,
        keyword_notes={uuid.uuid4(): note for note in notes},
    )


# ── 렌더 값 ─────────────────────────────────────────────────────────


def test_the_prompt_values_number_paragraphs_and_label_the_source_and_play_facts() -> None:
    """문단은 장면 표시 없이 `[번호] 글`, 아는 개체는 개체마다 한 줄, 정본 불변 속성은 `- 주어 (종류) · 속성: 값`, 원작은 표지
    `[S]`·`[K1]` 로 시작하는 덩이, 플레이 사실은 `P1.` 표지 줄이고 주장·반증은 끝 꼬리로 가른다. 깨지는 시나리오: 꼴이 바뀌면 그
    꼴을 설명하는 지시문과 어긋나 모델이 표지·문단 번호를 틀리게 내거나, 반증된 값을 플레이에서 참이던 값으로 읽거나, 같은 이름의
    인물·사물 불변 속성이 한 주어의 것으로 읽힌다."""
    canon = _canon("합성 작품 설정 글.", "첫 합성 노트.", "둘째 합성 노트.")
    slot_input = _input(
        _manuscript("첫째 문단이다.", "둘째 문단이다."),
        known=[EntityName(kind="object", name="열쇠"), EntityName(kind="character", name="하나", aliases=("큰언니",))],
        known_attributes=[KnownAttribute(subject="하나", subject_kind="character", attribute="눈 색", value="갈색"),
                          KnownAttribute(subject="둘", subject_kind="character", attribute="혈액형", value="A"),
                          KnownAttribute(subject="하나", subject_kind="object", attribute="재질", value="나무")],
        source=canon,
        play=[_play("민수", "연인", target="지아"), _play("지아", "기사", attribute="직업", claimed=True),
              _play("민수", "바다 마을", attribute="고향", disproved=True)],
    )

    values = FactsSlot().prompt_values(slot_input)

    assert values["manuscript"] == "[1] 첫째 문단이다.\n[2] 둘째 문단이다."
    assert values["known_entities"] == "- 열쇠 (사물)\n- 하나 (인물) — 별칭: 큰언니"
    assert values["known_attributes"] == "- 둘 (인물) · 혈액형: A\n- 하나 (사물) · 재질: 나무\n- 하나 (인물) · 눈 색: 갈색"
    assert values["source_canon"] == "[S] 합성 작품 설정 글.\n\n[K1] 첫 합성 노트.\n\n[K2] 둘째 합성 노트."
    assert values["play_facts"] == "P1. 민수 → 지아: 연인\nP2. 지아 · 직업: 기사 (주장)\nP3. 민수 · 고향: 바다 마을 (반증)"


def test_both_slots_render_the_known_entities_hint_as_the_same_text() -> None:
    """사건·사실 슬롯의 아는 개체 힌트는 같은 글이다 — 개체마다 한 줄, 같은 줄은 한 번, 글자 순, 별칭은 끝 꼬리. 깨지는
    시나리오: 두 슬롯이 꼴을 따로 들고 있으면 한쪽만 고쳐져, 같은 꼴을 설명하는 두 채널 지시문 중 하나가 어긋난다."""
    one = EntityName(kind="character", name="하나", aliases=("큰언니", "하나야"))
    known = [
        EntityName(kind="object", name="열쇠"), one, EntityName(kind="ability", name="비행"), one,
        EntityName(kind="character", name="둘"), EntityName(kind="object", name="열쇠", aliases=("작은 열쇠",)),
    ]
    manuscript = _manuscript("합성 문단.")

    facts = FactsSlot().prompt_values(_input(manuscript, known=known))["known_entities"]
    events = EventsSlot().prompt_values(EventsInput(manuscript=manuscript, scenes=[], known=known, prior=[]))

    assert facts == (
        "- 둘 (인물)\n- 비행 (능력)\n- 열쇠 (사물)\n- 열쇠 (사물) — 별칭: 작은 열쇠\n- 하나 (인물) — 별칭: 큰언니, 하나야"
    )
    assert events["known_entities"] == facts
    assert FactsSlot().prompt_values(_input(manuscript))["known_entities"] == ""


def test_the_known_entities_hint_labels_every_entity_kind_in_both_slots() -> None:
    """개체 종류 전부에 표지가 있다. 깨지는 시나리오: 종류를 넓히고 표지를 빠뜨리면 그 종류의 개체가 하나라도 생긴 소설은 이후
    모든 확정의 두 슬롯 렌더가 실패한다 — 아는 개체 힌트는 소설의 개체 전부를 싣고, 타입 검사는 사전 키가 다 있는지 보지 않는다."""
    kinds = get_args(EntityKind)
    assert set(KIND_LABELS) == set(kinds)
    known = [EntityName(kind=kind, name=f"합성{number}") for number, kind in enumerate(kinds)]
    manuscript = _manuscript("합성 문단.")

    facts = FactsSlot().prompt_values(_input(manuscript, known=known))["known_entities"]
    events = EventsSlot().prompt_values(EventsInput(manuscript=manuscript, scenes=[], known=known, prior=[]))

    assert facts == events["known_entities"]
    assert facts.splitlines() == [f"- 합성{number} ({KIND_LABELS[kind]})" for number, kind in enumerate(kinds)]


def test_without_a_source_or_play_facts_those_values_are_empty() -> None:
    values = FactsSlot().prompt_values(_input(_manuscript("합성 문단.")))

    assert values["source_canon"] == ""
    assert values["play_facts"] == ""
    assert values["known_attributes"] == ""


# ── 검증 ────────────────────────────────────────────────────────────


def test_validation_drops_bad_facts_one_by_one() -> None:
    manuscript = _manuscript("하나가 검을 받는다.", "하나가 숨을 거둔다.")
    output = _output(
        _fact("하나", "possession", "검", (1, "검을 받는다"), onset=True),
        _fact("하나", "possession", "검", (1, "원고에 없는 구절")),
        _fact("하나", "possession", "검", (9, "검을 받는다")),
        _fact("하나", "life", "asleep", (2, "숨을 거둔다")),
        _fact("하나", "presence", "lost", (2, "숨을 거둔다")),
        _fact("하나", "attribute", "크다", (2, "숨을 거둔다"), attribute="키", holds=False),
        _fact("하나", "relation", "둘", (2, "숨을 거둔다"), attribute=" "),
        _fact("하나", "attribute", "크다", (2, "숨을 거둔다"), attribute=None),
        _fact("하나", "possession", "검", (2, "숨을 거둔다"), immutable=True),
        _fact("하나", "attribute", " ", (2, "숨을 거둔다"), attribute="키"),
        _fact("하나", "life", " Dead ", (2, "숨을 거둔다"), onset=True),
    )

    proposal = FactsSlot().validate(_input(manuscript), output)

    assert [(item.proposition.kind, item.proposition.value) for item in proposal.items if item.proposition] == [
        ("possession", "검"), ("life", "dead"),
    ]
    assert proposal.dropped == {
        "quote_not_found": 2, "value_invalid": 2, "holds_invalid": 1, "attribute_missing": 2,
        "immutable_not_attribute": 1, "value_empty": 1,
    }


def test_validation_stores_onset_false_in_work_scope_and_puts_immutable_attributes_in_work_scope() -> None:
    """작품 전체 범위에는 시작 자리가 없어 `onset` 을 거짓으로 고쳐 남기고, 불변 속성은 작품 전체 범위로 둔다. 깨지는 시나리오:
    그대로 두면 DB CHECK(작품 범위의 시작·작품 범위 밖의 불변)에 걸려 확정 전체가 커밋 단계에서 실패한다."""
    manuscript = _manuscript("둘은 원래 키가 크다.", "하나가 검을 받는다.")
    output = _output(
        _fact("둘", "attribute", "크다", (1, "키가 크다"), attribute="키", immutable=True, onset=True,
              scope="scene"),
        _fact("하나", "ability", "비행", (2, "검을 받는다"), onset=True, scope="work"),
        _fact("하나", "possession", "검", (2, "검을 받는다"), onset=True, scope="scene"),
    )

    proposal = FactsSlot().validate(_input(manuscript), output)

    assert [(item.fields["immutable"], item.fields["onset"], item.fields["scope"]) for item in proposal.items] == [
        (True, False, "work"), (False, False, "work"), (False, True, "scene"),
    ]
    assert proposal.dropped == {}


def test_a_fact_anchors_at_its_quote_block_and_names_only_entity_valued_targets() -> None:
    """앵커는 인용 블록이고 주어는 인물로, 대상이 개체인 종류(소지·능력·관계)만 대상을 개체 이름으로 둔다. 속성 값은 인물
    이름이어도 개체 이름으로 두지 않는다. 깨지는 시나리오: 속성 값을 개체로 이으면 같은 명제의 안정 키가 그 이름의 개체가
    먼저 생겼느냐에 따라 달라진다."""
    manuscript = _manuscript("하나가 검을 받고 하늘을 난다.", "하나는 둘의 동생이고 친부는 셋이다.")
    output = _output(
        _fact("하나", "possession", "검", (1, "검을 받고"), onset=True),
        _fact("하나", "ability", "비행", (1, "하늘을 난다"), onset=True),
        _fact("하나", "relation", "둘", (2, "둘의 동생"), attribute="동생"),
        _fact("하나", "attribute", "셋", (2, "친부는 셋"), attribute="친부", immutable=True, scope="work"),
        _fact("하나", "presence", "gone_for_good", (2, "둘의 동생")),
    )

    proposal = FactsSlot().validate(_input(manuscript), output)

    first, second = (block.block_id for block in manuscript.blocks)
    assert [item.anchor_block for item in proposal.items] == [first, first, second, second, second]
    assert all(item.names["subject"] == (EntityName(kind="character", name="하나"),) for item in proposal.items)
    assert [item.names.get("value", ()) for item in proposal.items] == [
        (EntityName(kind="object", name="검"),), (EntityName(kind="ability", name="비행"),),
        (EntityName(kind="character", name="둘"),), (), (),
    ]
    presence = proposal.items[4].proposition
    assert presence is not None and (presence.kind, presence.value, presence.attribute) == (
        "presence", "gone_for_good", None
    )


def test_a_fact_subject_is_named_with_the_kind_the_model_gave_and_the_proposition_carries_it() -> None:
    """주어 개체 이름은 모델이 낸 주어 종류로 만들고, 같은 종류가 명제에도 실린다. 깨지는 시나리오: 이름만 종류를 따르고 명제가
    모르면, 같은 명제를 명제 꼴로 내는 지식 슬롯이 주어를 인물로 풀어 사물 주어 사실과 키가 어긋난다."""
    manuscript = _manuscript("검은 오래되어 날이 무디다.", "하나는 검을 쥔다.")
    output = _output(
        _fact("검", "attribute", "무딤", (1, "날이 무디다"), attribute="날", subject_kind="object"),
        _fact("하나", "possession", "검", (2, "검을 쥔다")),
    )

    proposal = FactsSlot().validate(_input(manuscript), output)

    blunt, holding = proposal.items
    assert blunt.names["subject"] == (EntityName(kind="object", name="검"),)
    assert blunt.proposition is not None and blunt.proposition.subject_kind == "object"
    assert holding.names["subject"] == (EntityName(kind="character", name="하나"),)
    assert holding.proposition is not None and holding.proposition.subject_kind == "character"


def test_a_proposal_stored_before_the_subject_kind_reads_its_subject_as_a_character() -> None:
    """주어 종류 칸이 생기기 전에 저장된 제안은 주어를 인물로 읽는다. 깨지는 시나리오: 칸을 필수로 두면 작업 행에 남은 옛 제안이
    재사용·연결 때 검증 오류로 깨져 확정이 실패한다."""
    manuscript = _manuscript("하나가 검을 받는다.")
    proposal = FactsSlot().validate(_input(manuscript), _output(_fact("하나", "possession", "검", (1, "검을 받는다"))))
    stored = proposal.model_dump(mode="json")
    for item in stored["items"]:
        del item["proposition"]["subject_kind"]

    read = Proposal.model_validate(stored)

    assert read == proposal
    assert read.items[0].proposition is not None and read.items[0].proposition.subject_kind == "character"


def test_differences_become_side_quotes_and_a_bad_difference_drops_only_itself() -> None:
    """원작 차이는 그 표지 글 안의 구간·해시로, 플레이 차이는 그 채팅 기억 행으로 남는다. 표지가 없거나 구절이 그 글에 없으면
    차이만 버리고 사실은 남긴다. 깨지는 시나리오: 사실째 버리면 원고가 정본인데 원작과 다르다는 이유로 정본이 빠진다."""
    manuscript = _manuscript("하나의 눈은 갈색이다.")
    canon = _canon("하나의 눈은 푸른색이다.", "노트에는 하나가 왼손잡이라고 적혀 있다.")
    note_id = next(iter(canon.keyword_notes))
    play = [_play("하나", "검정", attribute="눈 색")]
    quote = (1, "눈은 갈색")
    output = _output(
        _fact("하나", "attribute", "갈색", quote, attribute="눈 색", source=("S", "푸른색"), play="P1"),
        _fact("하나", "attribute", "오른손잡이", quote, attribute="주로 쓰는 손", source=(" K1 ", "왼손잡이")),
        _fact("하나", "attribute", "갈색", quote, attribute="눈", source=("K2", "왼손잡이"), play="P9"),
        _fact("하나", "attribute", "갈색", quote, attribute="눈빛", source=("S", "원작에 없는 구절")),
    )

    proposal = FactsSlot().validate(_input(manuscript, source=canon, play=play), output)

    assert len(proposal.items) == 4
    version = canon.ref.content_version_id
    start = canon.work_setting.index("푸른색")
    assert proposal.items[0].side_quotes == (
        SideQuote(origin="source_canon", content_version_id=version, source_field="work_setting",
                  char_start=start, char_end=start + 3, quote_sha256=quote_hash("푸른색")),
        SideQuote(origin="play", chat_room_id=play[0].chat_room_id, chat_memory_fact_id=play[0].chat_memory_fact_id,
                  chat_fact_key=play[0].chat_fact_key),
    )
    note_start = canon.keyword_notes[note_id].index("왼손잡이")
    assert proposal.items[1].side_quotes == (
        SideQuote(origin="source_canon", content_version_id=version, source_field="keyword_note",
                  keyword_note_id=note_id, char_start=note_start, char_end=note_start + 4,
                  quote_sha256=quote_hash("왼손잡이")),
    )
    assert proposal.items[2].side_quotes == () and proposal.items[3].side_quotes == ()
    assert proposal.dropped == {"source_difference_dropped": 2, "play_difference_dropped": 1}


def test_without_a_source_or_play_facts_every_difference_is_dropped() -> None:
    manuscript = _manuscript("하나의 눈은 갈색이다.")
    output = _output(_fact("하나", "attribute", "갈색", (1, "눈은 갈색"), attribute="눈 색", source=("S", "갈색"),
                           play="P1"))

    proposal = FactsSlot().validate(_input(manuscript), output)

    assert len(proposal.items) == 1 and proposal.items[0].side_quotes == ()
    assert proposal.dropped == {"source_difference_dropped": 1, "play_difference_dropped": 1}


@pytest.mark.parametrize(
    ("text", "quote", "found"),
    [
        pytest.param("하나의 눈은 푸른색이다.", "푸른색", "푸른색", id="exact"),
        pytest.param("하나의 눈은 푸른색이다.", unicodedata.normalize("NFD", "푸른색"), "푸른색", id="decomposed-hangul"),
        pytest.param("하나의 눈은\n  푸른색이다.", " 눈은 푸른색 ", "눈은\n  푸른색", id="collapsed-whitespace"),
        pytest.param("하나의 눈은 푸른색이다.", " ", None, id="whitespace-only"),
        pytest.param("하나의 눈은 푸른색이다.", "원작에 없는 구절", None, id="missing"),
    ],
)
def test_a_source_difference_quote_follows_the_manuscript_quote_rules_and_hashes_the_source_span(
    text: str, quote: str, found: str | None
) -> None:
    """원작 차이 구절은 원고 인용과 같은 규칙으로 찾는다 — 조합형·공백 차이는 찾고 공백만인 구절은 버린다. 구간과 해시는 찾은
    원문 구간의 글이다. 깨지는 시나리오: 두 근거의 찾기 규칙이 갈리면 같은 구절이 원고에서는 남고 원작에서는 버려져 측정의 차이
    버림률이 부풀고, 모델 글로 해시를 내면 저장된 원작 근거를 원작 글로 대 볼 때 맞지 않는다."""
    manuscript = _manuscript(text)
    output = _output(_fact("하나", "attribute", "갈색", (1, "하나의"), attribute="눈 색", source=("S", quote)))

    proposal = FactsSlot().validate(_input(manuscript, source=_canon(text)), output)
    in_manuscript = verify_quote(manuscript, QuoteOut(paragraph=1, text=quote))

    (item,) = proposal.items
    if found is None:
        assert (item.side_quotes, in_manuscript) == ((), None)
        assert proposal.dropped == {"source_difference_dropped": 1}
        return
    start = text.index(found)
    (side,) = item.side_quotes
    assert (side.char_start, side.char_end, side.quote_sha256) == (start, start + len(found), quote_hash(found))
    assert in_manuscript is not None
    assert (in_manuscript.char_start, in_manuscript.char_end, in_manuscript.quote_sha256) == (
        side.char_start, side.char_end, side.quote_sha256,
    )


# ── 입력 ────────────────────────────────────────────────────────────


def _view(
    db: AsyncSession, chapter: NovelChapter, revision: NovelChapterRevision, *, room_id: uuid.UUID | None = None
) -> CommitView:
    ref = CommitRef(
        commit_id=uuid.uuid4(), novel_id=chapter.novel_id, chapter_id=chapter.id, chapter_revision_id=revision.id,
        chapter_ordinal=chapter.ordinal, scope="character",
    )
    return CommitView(db, Registry(extracting={}, source=None), ref, None, room_id)


async def _snapshot(db: AsyncSession, room_id: uuid.UUID, at: datetime) -> ChatRoomMemorySnapshot:
    snapshot = ChatRoomMemorySnapshot(
        chat_room_id=room_id, cursor_created_at=at, cursor_message_id=uuid.uuid4(), summary_text="합성 요약",
        source="auto",
    )
    db.add(snapshot)
    await db.flush()
    return snapshot


async def _room_with_facts(db: AsyncSession, novel_id: uuid.UUID, chapter: NovelChapter) -> list[ChatMemoryFact]:
    """방 하나와 그 방의 채팅 기억 사실. 화 시작보다 앞에 접힌 스냅샷에 관계 하나, 화 도중(시작과 끝 사이)에 접힌 스냅샷에 같은
    키의 새 값·주장·반증·아는 사람이 정해진 행(장면 인물이 아닌 이름), 화 끝 뒤에 접힌 스냅샷에 하나. 앞의 둘이 화 끝까지 접힌
    것이다. 차례는 `[앞 관계, 새 값, 주장, 반증, 화 끝 뒤, 아는 사람]`."""
    room = await _make_bare_chat_room(db)
    novel = await db.get(Novel, novel_id)
    assert novel is not None
    novel.chat_room_id = room.id
    early = await _snapshot(db, room.id, chapter.start_message_created_at - timedelta(hours=1))
    during = await _snapshot(db, room.id, chapter.end_message_created_at - timedelta(hours=1))
    assert chapter.start_message_created_at < during.cursor_created_at < chapter.end_message_created_at
    after = await _snapshot(db, room.id, chapter.end_message_created_at + timedelta(hours=1))
    rows = [
        _make_memory_fact(room.id, early.id, ordinal=0, value="소꿉친구"),
        _make_memory_fact(room.id, during.id, ordinal=0, value="연인"),
        _make_memory_fact(room.id, during.id, ordinal=1, kind="fact", subject="지아", object=None, attribute="직업",
                          fact_key="fact|지아|직업", value="기사", truth_status="claimed", asserted_by="character"),
        _make_memory_fact(room.id, during.id, ordinal=2, kind="fact", subject="민수", object=None, attribute="고향",
                          fact_key="fact|민수|고향", value="바다 마을", truth_status="disproved"),
        _make_memory_fact(room.id, after.id, ordinal=0, kind="fact", subject="지아", object=None, attribute="나이",
                          fact_key="fact|지아|나이", value="스물"),
        _make_memory_fact(room.id, during.id, ordinal=3, kind="fact", subject="지아", object=None, attribute="비밀",
                          fact_key="fact|지아|비밀", value="왕녀", known_by=["세라"]),
    ]
    db.add_all(rows)
    await db.flush()
    return rows


async def test_the_input_reads_play_facts_folded_up_to_the_chapter_end_one_per_key(db_session: AsyncSession) -> None:
    """플레이 사실은 화의 끝 메시지까지 접힌 채팅 기억 사실(화 시작 전과 화 도중에 접힌 것) 중 키마다 이긴 행이고, 주장과
    반증은 표시해 싣는다. 장면 구성안은 싣지 않는다. 깨지는 시나리오: 화 끝 뒤의 대화를 읽으면 그 화 뒤에 일어난 일이 각색 후보
    근거가 되고, 화 시작까지만 읽으면 그 화 동안 쌓인 플레이 사실이 통째로 빠지며, 키별 최신으로 줄이지 않으면 옛 값과 새 값이
    함께 실린다."""
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, "민수와 지아가 정원에 있다.\n\n지아가 웃는다.")
    rows = await _room_with_facts(db_session, novel.id, chapter)

    slot_input = await FactsSlot().build_input(db_session, _view(db_session, chapter, revision, room_id=novel.chat_room_id))

    assert isinstance(slot_input, FactsInput)
    assert slot_input.play is not None
    assert [(fact.chat_memory_fact_id, fact.value, fact.claimed, fact.disproved) for fact in slot_input.play] == [
        (rows[1].id, "연인", False, False), (rows[2].id, "기사", True, False), (rows[3].id, "바다 마을", False, True),
        (rows[5].id, "왕녀", False, False),
    ]
    assert slot_input.play[0].chat_room_id == novel.chat_room_id
    assert slot_input.play[0].chat_fact_key == "relation|민수|지아"
    assert slot_input.source is None
    values = FactsSlot().prompt_values(slot_input)
    assert values["manuscript"] == "[1] 민수와 지아가 정원에 있다.\n[2] 지아가 웃는다."
    assert values["play_facts"] == (
        "P1. 민수 → 지아: 연인\nP2. 지아 · 직업: 기사 (주장)\nP3. 민수 · 고향: 바다 마을 (반증)\nP4. 지아 · 비밀: 왕녀"
    )


async def test_a_novel_without_a_room_or_without_chat_memory_rows_has_no_play_facts(db_session: AsyncSession) -> None:
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, "합성 문단이다.")
    room = await _make_bare_chat_room(db_session)

    without_room = await FactsSlot().build_input(db_session, _view(db_session, chapter, revision))
    empty_room = await FactsSlot().build_input(db_session, _view(db_session, chapter, revision, room_id=room.id))

    assert isinstance(without_room, FactsInput) and isinstance(empty_room, FactsInput)
    assert without_room.play is None and empty_room.play is None


# ── 확정 한 바퀴 ─────────────────────────────────────────────────────

_EVENT_SLOTS = [("instruction", "합성 지시문", False), ("manuscript", "{manuscript}", False),
                ("scene_hints", "{scene_hints}", True), ("known_entities", "{known_entities}", True),
                ("prior_events", "{prior_events}", True)]
_FACT_SLOTS = [("instruction", "합성 지시문", False), ("manuscript", "원고\n{manuscript}", False),
               ("known_entities", "아는 개체\n{known_entities}", True),
               ("known_attributes", "정본 불변 속성\n{known_attributes}", True),
               ("source_canon", "원작 정본\n{source_canon}", True),
               ("play_facts", "플레이 사실\n{play_facts}", True)]


def _sections(prompt_set_id: uuid.UUID) -> list[PromptSection]:
    return [
        PromptSection(prompt_set_id=prompt_set_id, channel=channel, scope="both", slot=slot, variant="", body=body,
                      conditional=conditional, order=order)
        for channel, slots in (("novel_bible_events", _EVENT_SLOTS), ("novel_bible_facts", _FACT_SLOTS))
        for order, (slot, body, conditional) in enumerate(slots)
    ]


@dataclass
class ScriptedAdapter:
    """연산마다 정해 둔 출력을 호출마다 차례로 돌려주고, 받은 문안을 연산마다 남긴다."""

    outputs: dict[OperationKey, list[dict[str, Any]]]
    prompts: dict[OperationKey, list[RenderedPrompt]] = field(default_factory=dict)
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
        self.prompts.setdefault(stage, []).append(prompt)
        return schema.model_validate(self.outputs[stage].pop(0))

    def resolver(self) -> Callable[[OperationKey], BibleModelAdapter]:
        return lambda operation: self


def _registry(*, events: bool = True, source: FakeSource | None = None) -> Registry:
    slots: list[Slot] = [EventsSlot(), FactsSlot()] if events else [FactsSlot()]
    return Registry(extracting={slot.id: slot for slot in slots}, source=source)


async def _confirm_and_run(
    db: AsyncSession, chapter: NovelChapter, revision: NovelChapterRevision, adapter: ScriptedAdapter,
    registry: Registry,
) -> uuid.UUID:
    result = await confirm(
        db, registry, novel_id=chapter.novel_id, chapter_id=chapter.id, revision_id=revision.id, actor=SYSTEM
    )
    await run_until_idle(savepoint_factory(db), registry, [], adapter.resolver())
    return result.commit_id


async def _status(db: AsyncSession, commit_id: uuid.UUID) -> str | None:
    status: str | None = await db.scalar(select(NovelBibleCommit.status).where(NovelBibleCommit.id == commit_id))
    return status


async def _entity(db: AsyncSession, novel_id: uuid.UUID, kind: str, name: str) -> uuid.UUID:
    entity_id = await db.scalar(
        select(NovelBibleEntity.id).where(
            NovelBibleEntity.novel_id == novel_id, NovelBibleEntity.kind == kind, NovelBibleEntity.name_norm == name
        )
    )
    assert entity_id is not None
    return entity_id


async def _facts(db: AsyncSession, chapter_id: uuid.UUID) -> list[NovelBibleFact]:
    statement = select(NovelBibleFact).where(NovelBibleFact.chapter_id == chapter_id)
    return list((await db.scalars(statement.order_by(NovelBibleFact.kind))).all())


def _event(key: str, paragraphs: list[int], quote: tuple[int, str], present: list[str]) -> dict[str, Any]:
    return {
        "key": key, "summary": "합성 요지", "paragraphs": paragraphs, "actuality": "present", "present": present,
        "mentioned": [], "uses": [], "quote": {"paragraph": quote[0], "text": quote[1]},
    }


BODY = "하나가 검을 받는다.\n\n하나는 숲으로 떠난다.\n\n둘은 원래 키가 크다."


def _events_output() -> dict[str, Any]:
    return {"events": [_event("e1", [1], (1, "검을 받는다"), ["하나"]),
                       _event("e2", [2, 3], (2, "숲으로 떠난다"), ["하나", "둘"])], "relations": []}


def _facts_output() -> dict[str, Any]:
    return {"facts": [
        _fact("하나", "possession", "검", (1, "검을 받는다"), onset=True),
        _fact("하나", "presence", "departed", (2, "숲으로 떠난다"), onset=True),
        _fact("둘", "attribute", "크다", (3, "키가 크다"), attribute="키", immutable=True, scope="work"),
    ]}


async def test_a_confirmed_chapter_commits_facts_with_keys_onset_scope_and_their_events(
    db_session: AsyncSession,
) -> None:
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, BODY)
    adapter = ScriptedAdapter({"events.extract": [_events_output()], "facts.extract": [_facts_output()]})

    commit_id = await _confirm_and_run(db_session, chapter, revision, adapter, _registry())

    assert await _status(db_session, commit_id) == "committed"
    attribute, possession, presence = await _facts(db_session, chapter.id)
    first, second = (
        await db_session.scalars(
            select(NovelBibleEvent.id).where(NovelBibleEvent.chapter_id == chapter.id).order_by(NovelBibleEvent.ordinal)
        )
    ).all()
    one = await _entity(db_session, novel.id, "character", "하나")
    two = await _entity(db_session, novel.id, "character", "둘")
    sword = await _entity(db_session, novel.id, "object", "검")
    assert (possession.subject_entity_id, possession.value_entity_id, possession.holds, possession.onset,
            possession.scope, possession.valid_from_event_id) == (one, sword, True, True, "from_here", first)
    assert possession.fact_key == fact_key(one, "possession", "possession", str(sword), True)
    assert (presence.value_norm, presence.onset, presence.valid_from_event_id, presence.value_entity_id) == (
        "departed", True, second, None
    )
    assert (attribute.subject_entity_id, attribute.predicate_norm, attribute.value_norm, attribute.immutable,
            attribute.onset, attribute.scope, attribute.value_entity_id, attribute.valid_from_event_id) == (
        two, "키", "크다", True, False, "work", None, second
    )
    assert attribute.fact_key == fact_key(two, "attribute", "키", "크다", True)
    assert {fact.status for fact in (attribute, possession, presence)} == {"confirmed"}
    evidence = (
        await db_session.execute(
            select(NovelBibleEvidence.item_id, NovelBibleEvidence.origin, NovelBibleEvidence.block_id).where(
                NovelBibleEvidence.item_table == "fact"
            )
        )
    ).all()
    assert {(row.item_id, row.origin, row.block_id) for row in evidence} == {
        (possession.id, "manuscript_block", revision.block_ids[0]),
        (presence.id, "manuscript_block", revision.block_ids[1]),
        (attribute.id, "manuscript_block", revision.block_ids[2]),
    }
    # 사실 슬롯은 사실 표 밖의 항목 표에 쓰지 않는다(사건은 사건 슬롯이 썼다).
    assert await db_session.scalar(
        select(func.count()).select_from(NovelBibleKnowledge).where(NovelBibleKnowledge.novel_id == novel.id)
    ) == 0
    # 장면 구성안·원작·플레이가 없는 화 — 그 섹션은 빠진다.
    prompt = adapter.prompts["facts.extract"][0].prompt
    assert "원작 정본" not in prompt and "플레이 사실" not in prompt and "정본 불변 속성" not in prompt
    assert "[장면" not in prompt


async def test_a_fact_about_a_thing_commits_under_an_object_entity_not_a_character(db_session: AsyncSession) -> None:
    """사물이 주어인 사실은 사물 개체에 붙고, 같은 이름의 인물 개체를 만들지 않는다. 깨지는 시나리오: 주어를 늘 인물로 만들면
    사물 이름의 인물 개체가 생겨, 그 소설의 이후 아는 개체 힌트에 그 이름이 인물로 실린다."""
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, "검은 오래되어 날이 무디다.")
    output = {"facts": [_fact("검", "attribute", "무딤", (1, "날이 무디다"), attribute="날", subject_kind="object")]}

    commit_id = await _confirm_and_run(
        db_session, chapter, revision, ScriptedAdapter({"facts.extract": [output]}), _registry(events=False)
    )

    assert await _status(db_session, commit_id) == "committed"
    (fact,) = await _facts(db_session, chapter.id)
    sword = await _entity(db_session, novel.id, "object", "검")
    assert fact.subject_entity_id == sword
    assert fact.fact_key == fact_key(sword, "attribute", "날", "무딤", True)
    kinds = (await db_session.scalars(select(NovelBibleEntity.kind).where(NovelBibleEntity.novel_id == novel.id))).all()
    assert kinds == ["object"]


async def test_a_fact_whose_subject_or_target_name_is_over_the_limit_is_dropped_and_a_long_attribute_value_stays(
    db_session: AsyncSession,
) -> None:
    """사실의 개체 이름 칸은 주어와 대상(소지·능력·관계) 둘뿐이고 둘 다 코어가 개체 하나로 푸는 칸이라, 정규화한 이름이 개체 이름
    상한을 넘으면 그 항목을 버리고 확정은 이어진다. 상한과 같은 길이는 남는다. 속성 값은 개체에 잇지 않아 길어도 남는다. 깨지는
    시나리오: 대상 이름이 코어가 개체 하나로 푸는 칸 밖에 있으면 코어가 그 이름만 빼고 항목을 남겨 대상 없는 소지 사실이 연결에서
    확정 전체를 실패시키고, 속성 값을 개체 이름으로 두면 긴 속성 값 하나로 그 값이 이름 목록처럼 빠진다."""
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, "하나가 검을 받는다.")
    too_long, at_limit = "가" * (ENTITY_NAME_MAX + 1), "나" * ENTITY_NAME_MAX
    quote = (1, "검을 받는다")
    output = {"facts": [
        _fact(too_long, "life", "alive", quote),
        _fact("하나", "possession", too_long, quote),
        _fact("하나", "relation", too_long, quote, attribute="친구"),
        _fact(at_limit, "life", "alive", quote),
        _fact("하나", "attribute", too_long, quote, attribute="별명"),
    ]}

    commit_id = await _confirm_and_run(
        db_session, chapter, revision, ScriptedAdapter({"facts.extract": [output]}), _registry(events=False)
    )

    assert await _status(db_session, commit_id) == "committed"
    proposal = await db_session.scalar(
        select(NovelBibleJob.proposal).where(NovelBibleJob.commit_id == commit_id, NovelBibleJob.slot == "facts")
    )
    assert proposal is not None and proposal["dropped"] == {NAME_TOO_LONG: 3}
    assert [(fact.kind, fact.value) for fact in await _facts(db_session, chapter.id)] == [
        ("attribute", too_long), ("life", "alive"),
    ]
    names = set(
        await db_session.scalars(select(NovelBibleEntity.name_norm).where(NovelBibleEntity.novel_id == novel.id))
    )
    assert names == {"하나", at_limit}


async def test_reconfirming_expires_the_chapters_facts_and_a_new_row_supersedes_the_same_key(
    db_session: AsyncSession,
) -> None:
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, BODY)
    adapter = ScriptedAdapter({"facts.extract": [_facts_output(), _facts_output()]})
    await _confirm_and_run(db_session, chapter, revision, adapter, _registry(events=False))
    old = {fact.fact_key: fact.id for fact in await _facts(db_session, chapter.id)}
    replacement = await add_revision(db_session, chapter.id, BODY + "\n\n하나가 돌아온다.")

    commit_id = await _confirm_and_run(db_session, chapter, replacement, adapter, _registry(events=False))

    assert await _status(db_session, commit_id) == "committed"
    head = await revision_at(db_session, novel.id, None)
    expired = (
        await db_session.execute(
            select(NovelBibleExpiration.item_table, NovelBibleExpiration.item_id).where(
                NovelBibleExpiration.revision_id == head.id
            )
        )
    ).all()
    assert {(row.item_table, row.item_id) for row in expired} == {("fact", item_id) for item_id in old.values()}
    current = await FactsSlot().read(db_session, novel.id, head)
    assert all(isinstance(row, FactRow) for row in current)
    assert {row.fact_key for row in current if isinstance(row, FactRow)} == set(old)
    new_rows = [fact for fact in await _facts(db_session, chapter.id) if fact.id not in old.values()]
    assert {fact.supersedes_id for fact in new_rows} == set(old.values())
    assert all(old[fact.fact_key] == fact.supersedes_id for fact in new_rows)
    assert {item_id for _, item_id in await FactsSlot().current_item_ids(db_session, novel.id, chapter.id, head)} == {
        fact.id for fact in new_rows
    }
    # 앞 리비전 시점에는 옛 행이 현재다.
    before = await FactsSlot().read(db_session, novel.id, await revision_at(db_session, novel.id, head.revision_no - 1))
    assert {row.id for row in before} == set(old.values())


async def test_known_attributes_are_current_immutable_attributes_of_entities_named_in_the_chapter(
    db_session: AsyncSession,
) -> None:
    """정본 불변 속성 힌트는 지금 머리의 다른 화 불변 속성 중 주어 이름(별칭 포함)이 이 화 원고에 나오는 것뿐이다. 깨지는
    시나리오: 가변 속성이나 이 화에 안 나오는 인물의 속성까지 실으면 힌트가 화마다 커지고, 불변 속성이 빠지면 같은 값을 다른
    표기로 내 표기 차이 경고가 늘며, 이 화 자신의 행을 실으면 값을 고쳐 다시 확정할 때 곧 만료될 옛 값이 같은 표기로 쓰라는
    힌트가 된다."""
    novel = await make_novel(db_session)
    first, first_revision = await add_chapter(db_session, novel.id, 1, "하나는 갈색 눈이다.\n\n둘은 키가 크다.")
    output = {"facts": [
        _fact("하나", "attribute", "갈색", (1, "갈색 눈"), attribute="눈 색", immutable=True, scope="work"),
        _fact("하나", "attribute", "나무", (1, "하나는"), attribute="재질", immutable=True, scope="work",
              subject_kind="object"),
        _fact("둘", "attribute", "크다", (2, "키가 크다"), attribute="키", scope="from_here"),
    ]}
    adapter = ScriptedAdapter({"facts.extract": [output]})
    await _confirm_and_run(db_session, first, first_revision, adapter, _registry(events=False))
    second, second_revision = await add_chapter(db_session, novel.id, 2, "하나와 둘이 걷는다.")
    third, third_revision = await add_chapter(db_session, novel.id, 3, "셋이 혼자 걷는다.")

    named = await FactsSlot().build_input(db_session, _view(db_session, second, second_revision))
    unnamed = await FactsSlot().build_input(db_session, _view(db_session, third, third_revision))
    edited = await add_revision(db_session, first.id, "하나는 푸른 눈이다.\n\n둘은 키가 크다.")
    own = await FactsSlot().build_input(db_session, _view(db_session, first, edited))

    assert isinstance(named, FactsInput) and isinstance(unnamed, FactsInput) and isinstance(own, FactsInput)
    assert named.known_attributes == [
        KnownAttribute(subject="하나", subject_kind="character", attribute="눈 색", value="갈색"),
        KnownAttribute(subject="하나", subject_kind="object", attribute="재질", value="나무"),
    ]
    assert unnamed.known_attributes == []
    assert own.known_attributes == []
    assert {name.name for name in named.known} >= {"하나", "둘"}


async def test_source_and_play_differences_become_adaptation_candidates_and_the_fact_stays_confirmed(
    db_session: AsyncSession,
) -> None:
    """원작·플레이와 다른 소설 사실은 정본 그대로 커밋되고, 출처마다 각색 후보 행과 그 근거(원작 위치, 채팅 기억 행 id·키)가
    남는다. 차단도 경고도 아니다."""
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, "민수와 지아는 남매다.")
    rows = await _room_with_facts(db_session, novel.id, chapter)
    source = FakeSource(note="원작에서 민수와 지아는 소꿉친구다.")
    output = {"facts": [_fact("민수", "relation", "지아", (1, "남매다"), attribute="남매", source=("S", "소꿉친구"),
                              play="P1")]}
    adapter = ScriptedAdapter({"facts.extract": [output]})

    commit_id = await _confirm_and_run(db_session, chapter, revision, adapter, _registry(events=False, source=source))

    assert await _status(db_session, commit_id) == "committed"
    (fact,) = await _facts(db_session, chapter.id)
    assert fact.status == "confirmed"
    prompt = adapter.prompts["facts.extract"][0].prompt
    assert "[S] 원작에서 민수와 지아는 소꿉친구다." in prompt and "P1. 민수 → 지아: 연인" in prompt
    candidates = (
        await db_session.execute(
            select(NovelBibleAdaptationCandidate.origin, NovelBibleAdaptationCandidate.fact_key,
                   NovelBibleAdaptationCandidate.fact_id, NovelBibleAdaptationCandidate.status)
        .where(NovelBibleAdaptationCandidate.novel_id == novel.id)
        )
    ).all()
    assert sorted(candidates) == [("play", fact.fact_key, fact.id, "open"), ("source_canon", fact.fact_key, fact.id, "open")]
    side = (
        await db_session.execute(
            select(NovelBibleEvidence).where(NovelBibleEvidence.item_id == fact.id,
                                             NovelBibleEvidence.origin != "manuscript_block")
        )
    ).scalars().all()
    by_origin = {row.origin: row for row in side}
    start = source.note.index("소꿉친구")
    assert (by_origin["source_canon"].content_version_id, by_origin["source_canon"].source_field,
            by_origin["source_canon"].char_start, by_origin["source_canon"].quote_sha256) == (
        source.version_id, "work_setting", start, quote_hash("소꿉친구")
    )
    assert (by_origin["chat_memory"].chat_room_id, by_origin["chat_memory"].chat_memory_fact_id,
            by_origin["chat_memory"].chat_fact_key) == (novel.chat_room_id, rows[1].id, "relation|민수|지아")
    assert await db_session.scalar(
        select(func.count()).select_from(NovelBibleFinding).where(NovelBibleFinding.commit_id == commit_id)
    ) == 0


async def test_reconfirming_expires_the_chapters_adaptation_candidates(db_session: AsyncSession) -> None:
    """원작·플레이 차이가 있는 화를 다시 확정하면 그 화의 앞 각색 후보가 만료되고, 새 확정이 새 사실 행에 단 후보만 현재다.
    깨지는 시나리오: 만료되지 않으면 고친 원고가 더는 원작·플레이와 다르지 않아도 옛 후보가 열린 채 남고, 같은 차이가 확정마다
    후보를 하나씩 더 쌓는다."""
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, "민수와 지아는 남매다.")
    await _room_with_facts(db_session, novel.id, chapter)
    registry = _registry(events=False, source=FakeSource(note="원작에서 민수와 지아는 소꿉친구다."))
    output = {"facts": [_fact("민수", "relation", "지아", (1, "남매다"), attribute="남매", source=("S", "소꿉친구"),
                              play="P1")]}
    adapter = ScriptedAdapter({"facts.extract": [output, output]})
    await _confirm_and_run(db_session, chapter, revision, adapter, registry)
    candidates = select(NovelBibleAdaptationCandidate).where(NovelBibleAdaptationCandidate.novel_id == novel.id)
    old = {row.id for row in (await db_session.scalars(candidates)).all()}
    assert len(old) == 2
    replacement = await add_revision(db_session, chapter.id, "민수와 지아는 남매다.\n\n둘이 웃는다.")

    commit_id = await _confirm_and_run(db_session, chapter, replacement, adapter, registry)

    assert await _status(db_session, commit_id) == "committed"
    head = await revision_at(db_session, novel.id, None)
    expired = (
        await db_session.execute(
            select(NovelBibleExpiration.item_id, NovelBibleExpiration.reason).where(
                NovelBibleExpiration.revision_id == head.id, NovelBibleExpiration.item_table == "adaptation_candidate"
            )
        )
    ).all()
    assert {(row.item_id, row.reason) for row in expired} == {(item_id, "chapter_replaced") for item_id in old}
    new = [row for row in (await db_session.scalars(candidates)).all() if row.id not in old]
    (fact,) = [fact for fact in await _facts(db_session, chapter.id) if fact.created_revision_id == head.id]
    assert sorted((row.origin, row.fact_id, row.created_revision_id) for row in new) == [
        ("play", fact.id, head.id), ("source_canon", fact.id, head.id),
    ]


async def test_a_same_text_reconfirm_reuses_the_extraction_unless_the_play_facts_changed(
    db_session: AsyncSession,
) -> None:
    """본문·블록이 같은 재확정은 아는 개체·정본 불변 속성 힌트가 바뀌어도 추출을 다시 쓰고, 채팅 기억 행이 바뀌면 다시 뽑는다.
    깨지는 시나리오: 플레이 사실을 힌트로 두면 되감기·잊기 뒤에도 옛 플레이로 뽑은 각색 후보를 재사용하고, 정본 불변 속성을
    열쇠에 넣으면 다른 화가 만든 속성 때문에 같은 본문도 다시 뽑는다."""
    novel = await make_novel(db_session)
    body = "민수와 지아는 남매다.\n\n지아는 원래 눈이 갈색이다."
    chapter, revision = await add_chapter(db_session, novel.id, 1, body)
    rows = await _room_with_facts(db_session, novel.id, chapter)
    output = {"facts": [_fact("민수", "relation", "지아", (1, "남매다"), attribute="남매", play="P1"),
                        _fact("지아", "attribute", "갈색", (2, "눈이 갈색"), attribute="눈 색", immutable=True)]}
    other = {"facts": [_fact("지아", "attribute", "갈색", (1, "눈이 갈색"), attribute="눈 색", immutable=True)]}
    adapter = ScriptedAdapter({"facts.extract": [output, other, output]})
    # 첫 확정이 개체를, 다른 화의 확정이 불변 속성을 만들어 다음 확정의 두 힌트가 바뀐다.
    await _confirm_and_run(db_session, chapter, revision, adapter, _registry(events=False))
    second, second_revision = await add_chapter(db_session, novel.id, 2, "지아는 원래 눈이 갈색이다.")
    await _confirm_and_run(db_session, second, second_revision, adapter, _registry(events=False))
    same = await add_revision(db_session, chapter.id, body, block_ids=revision.block_ids)

    reused = await _confirm_and_run(db_session, chapter, same, adapter, _registry(events=False))

    assert await _status(db_session, reused) == "committed"
    assert len(adapter.prompts["facts.extract"]) == 2

    await db_session.execute(delete(ChatMemoryFact).where(ChatMemoryFact.id == rows[1].id))
    await db_session.flush()
    rewound = await add_revision(db_session, chapter.id, body, block_ids=revision.block_ids)

    fresh = await _confirm_and_run(db_session, chapter, rewound, adapter, _registry(events=False))

    assert await _status(db_session, fresh) == "committed"
    assert len(adapter.prompts["facts.extract"]) == 3
    prompt = adapter.prompts["facts.extract"][2].prompt
    assert "P1. 민수 → 지아: 소꿉친구" in prompt and "- 지아 (인물) · 눈 색: 갈색" in prompt


async def test_a_reconfirm_extracts_again_when_a_play_fact_is_rewritten_with_the_same_text_as_a_new_row(
    db_session: AsyncSession,
) -> None:
    """같은 플레이 사실이 같은 글의 새 채팅 기억 행으로 다시 쓰이면(되감기 뒤 다시 접힘) 본문이 같은 재확정도 추출을 다시 하고,
    새 근거는 새 행을 가리킨다. 깨지는 시나리오: 열쇠가 렌더 글만 보면 지워진 행 id 를 근거로 든 앞 제안을 재사용해, 그 근거가
    태어날 때부터 소실로 읽힌다."""
    novel = await make_novel(db_session)
    body = "민수와 지아는 남매다."
    chapter, revision = await add_chapter(db_session, novel.id, 1, body)
    rows = await _room_with_facts(db_session, novel.id, chapter)
    output = {"facts": [_fact("민수", "relation", "지아", (1, "남매다"), attribute="남매", play="P1")]}
    adapter = ScriptedAdapter({"facts.extract": [output, output]})
    await _confirm_and_run(db_session, chapter, revision, adapter, _registry(events=False))
    room_id, snapshot_id, ordinal, old_id = rows[1].chat_room_id, rows[1].snapshot_id, rows[1].ordinal, rows[1].id
    await db_session.execute(delete(ChatMemoryFact).where(ChatMemoryFact.id == old_id))
    rewritten = _make_memory_fact(room_id, snapshot_id, ordinal=ordinal, value="연인")
    db_session.add(rewritten)
    await db_session.flush()
    same = await add_revision(db_session, chapter.id, body, block_ids=revision.block_ids)

    commit_id = await _confirm_and_run(db_session, chapter, same, adapter, _registry(events=False))

    assert await _status(db_session, commit_id) == "committed"
    first, second = (prompt.prompt.split("플레이 사실\n", 1)[1] for prompt in adapter.prompts["facts.extract"])
    assert first == second and first.startswith("P1. 민수 → 지아: 연인\n")
    head = await revision_at(db_session, novel.id, None)
    pointed = await db_session.scalar(
        select(NovelBibleEvidence.chat_memory_fact_id).where(
            NovelBibleEvidence.origin == "chat_memory", NovelBibleEvidence.created_revision_id == head.id
        )
    )
    assert pointed == rewritten.id != old_id


async def test_a_play_evidence_survives_the_chat_memory_row_it_points_at(db_session: AsyncSession) -> None:
    """채팅 기억 행이 되감기·잊기로 사라져도 커밋된 사실과 근거 행은 그대로이고, 근거가 가리키던 행이 없다는 것으로 소실을
    읽는다(소실 칸은 없다). 깨지는 시나리오: 근거가 채팅 기억 행을 FK 로 가리키면 되감기가 정본 행을 지우거나 막힌다."""
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, "민수와 지아는 남매다.")
    rows = await _room_with_facts(db_session, novel.id, chapter)
    output = {"facts": [_fact("민수", "relation", "지아", (1, "남매다"), attribute="남매", play="P1")]}
    await _confirm_and_run(
        db_session, chapter, revision, ScriptedAdapter({"facts.extract": [output]}), _registry(events=False)
    )

    await db_session.execute(delete(ChatRoomMemorySnapshot).where(ChatRoomMemorySnapshot.id == rows[1].snapshot_id))
    await db_session.flush()

    pointed = await db_session.scalar(
        select(NovelBibleEvidence.chat_memory_fact_id).where(NovelBibleEvidence.origin == "chat_memory",
                                                             NovelBibleEvidence.novel_id == novel.id)
    )
    assert pointed == rows[1].id
    assert await db_session.scalar(select(ChatMemoryFact.id).where(ChatMemoryFact.id == pointed)) is None
    head = await revision_at(db_session, novel.id, None)
    assert len(await FactsSlot().read(db_session, novel.id, head)) == 1


async def test_facts_true_at_an_event_group_a_gain_and_a_loss_under_one_state_key(db_session: AsyncSession) -> None:
    """얻음과 잃음은 안정 키가 다르지만 상태 키는 같아, 사건 시점 질의가 이야기 순서로 가장 늦은 행을 그 상태의 값으로 낸다."""
    novel = await make_novel(db_session)
    body = "하나가 검을 받는다.\n\n하나가 검을 잃고 숨을 거둔다."
    chapter, revision = await add_chapter(db_session, novel.id, 1, body)
    events = {"events": [_event("e1", [1], (1, "검을 받는다"), ["하나"]),
                         _event("e2", [2], (2, "숨을 거둔다"), ["하나"])], "relations": []}
    facts = {"facts": [
        _fact("하나", "possession", "검", (1, "검을 받는다"), onset=True),
        _fact("하나", "possession", "검", (2, "검을 잃고"), holds=False, onset=True),
        _fact("하나", "life", "dead", (2, "숨을 거둔다"), onset=True),
    ]}
    adapter = ScriptedAdapter({"events.extract": [events], "facts.extract": [facts]})
    await _confirm_and_run(db_session, chapter, revision, adapter, _registry())
    first, second = (
        await db_session.scalars(
            select(NovelBibleEvent.id).where(NovelBibleEvent.chapter_id == chapter.id).order_by(NovelBibleEvent.ordinal)
        )
    ).all()
    gained, lost = sorted(
        (fact for fact in await _facts(db_session, chapter.id) if fact.kind == "possession"), key=lambda f: not f.holds
    )
    assert gained.fact_key != lost.fact_key

    at_first = await facts_true_at(db_session, novel.id, _registry(), event_id=first)
    at_second = await facts_true_at(db_session, novel.id, _registry(), event_id=second)

    one = await _entity(db_session, novel.id, "character", "하나")
    sword = await _entity(db_session, novel.id, "object", "검")
    holding: StateKey = (one, "possession", "possession", sword)
    life: StateKey = (one, "life", "life", None)
    assert at_first.states[holding].id == gained.id and life not in at_first.states
    assert at_second.states[holding].id == lost.id and not at_second.states[holding].holds
    assert at_second.states[life].value_norm == "dead" and at_second.states[life].onset
    assert state_key(at_second.states[holding]) == holding


def _memory_switches() -> list[str]:
    return [
        name for name, info in type(settings).model_fields.items()
        if name.startswith("memory_") and info.annotation is bool
    ]


async def _commit_projection(db: AsyncSession, novel_id: uuid.UUID) -> dict[str, Any]:
    """커밋된 행을 새로 만든 id 없이 비교할 수 있게 — 개체는 이름으로, 근거는 위치·출처로."""
    names = dict((await db.execute(select(NovelBibleEntity.id, NovelBibleEntity.name))).tuples().all())
    facts = (await db.scalars(select(NovelBibleFact).where(NovelBibleFact.novel_id == novel_id))).all()
    evidence = (await db.scalars(select(NovelBibleEvidence).where(NovelBibleEvidence.novel_id == novel_id))).all()
    candidates = (
        await db.scalars(
            select(NovelBibleAdaptationCandidate.origin).where(NovelBibleAdaptationCandidate.novel_id == novel_id)
        )
    ).all()
    return {
        "facts": sorted(
            (names[fact.subject_entity_id], fact.kind, fact.predicate_norm, fact.value, fact.value_norm, fact.holds,
             fact.immutable, fact.onset, fact.scope, fact.status)
            for fact in facts
        ),
        "evidence": sorted(
            (row.origin, str(row.block_id), row.char_start, row.char_end, row.quote_sha256,
             str(row.chat_memory_fact_id), row.chat_fact_key)
            for row in evidence
        ),
        "candidates": sorted(candidates),
    }


async def test_chat_memory_switches_change_neither_the_facts_input_nor_the_committed_rows(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """같은 채팅 기억 행을 심어 둔 채 채팅 기억 스위치를 전부 끄고 한 번, 전부 켜고 한 번 확정한다(둘 사이에 확정을 되돌려 같은
    상태에서 시작). 렌더 글과 커밋된 행이 같고, 아는 사람이 정해진 행도 두 렌더에 다 실린다. 깨지는 시나리오: 읽기가 채팅 기억
    스위치(추출·주입·지식 범위 거름 따위)를 보면 스위치를 끈 환경에서 플레이 사실 섹션이 비거나 줄어 각색 후보가 사라지고, 지식
    범위 스위치에 묶여 아는 사람이 정해진 행을 빼면 켠 환경에서만 그 차이가 후보가 되지 못한다."""
    switches = _memory_switches()
    assert len(switches) >= 10
    novel = await make_novel(db_session)
    chapter, revision = await add_chapter(db_session, novel.id, 1, "민수와 지아는 남매다.")
    await _room_with_facts(db_session, novel.id, chapter)
    output = {"facts": [_fact("민수", "relation", "지아", (1, "남매다"), attribute="남매", play="P1"),
                        _fact("지아", "attribute", "기사", (1, "지아는"), attribute="직업", play="P2")]}

    seen: list[tuple[str, dict[str, Any]]] = []
    for value in (False, True):
        for name in switches:
            monkeypatch.setattr(settings, name, value)
        adapter = ScriptedAdapter({"facts.extract": [output]})
        savepoint = await db_session.begin_nested()
        commit_id = await _confirm_and_run(db_session, chapter, revision, adapter, _registry(events=False))
        assert await _status(db_session, commit_id) == "committed"
        seen.append((adapter.prompts["facts.extract"][0].prompt, await _commit_projection(db_session, novel.id)))
        await savepoint.rollback()

    (off_prompt, off_rows), (on_prompt, on_rows) = seen
    assert "플레이 사실\nP1. 민수 → 지아: 연인\nP2. 지아 · 직업: 기사 (주장)" in off_prompt
    assert "P4. 지아 · 비밀: 왕녀" in off_prompt and "P4. 지아 · 비밀: 왕녀" in on_prompt
    assert on_prompt == off_prompt
    assert len([row for row in off_rows["evidence"] if row[0] == "chat_memory"]) == 2
    assert off_rows["candidates"] == ["play", "play"]
    assert on_rows == off_rows


def test_the_registry_holds_the_facts_slot() -> None:
    assert isinstance(REGISTRY.extracting["facts"], FactsSlot)
