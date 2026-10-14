"""매 턴 사실 섹션 — 방의 관계·사실 기억을 키마다 지금 값으로 줄여 생성 프롬프트의 사실 섹션에 싣는다(LLM 호출 없음).

규칙(결과를 보기 전에 적었다):
- 사실 주입 스위치(`memory_facts_inject`)와 생성 윈도우가 둘 다 켜져 있고 방에 요약 커서가 있을 때만 사실을 읽는다. 아니면
  사실 SELECT 도 없고 프롬프트는 스위치가 생기기 전과 바이트까지 같다.
- 읽는 행은 그 턴 요약 커서 이하에서 접힌 스냅샷의 행뿐이다(커서 뒤는 원문 윈도우로 이미 실린다). 키마다 가장 늦게 쓴 행이
  이기되, 같은 값의 반증 행이 앞에 있으면 그 반증 행이 이긴다(반증된 값은 뒤의 같은 값 주장으로 되살아나지 않는다). 값이 다른
  새 행은 옛 값의 반증 행에 가려지지 않는다.
- 렌더 순서는 관계 → 아는 사람이 정해진 사실 → 반증 → 그 밖, 묶음 안은 중요도가 높은 쪽, 같으면 나중에 쓴 쪽이 먼저다.
- 고르기: 줄을 이어 붙인 글(줄바꿈 포함)이 700자를 넘지 않게. 렌더 순서로 210자까지(상시 몫) 싣고, 이번 턴 사용자 메시지와
  드문 명사가 겹치는 행(장면 회상과 같은 토큰·점수, 임계 0.6, 행 5개 미만이면 없음)을 700자까지, 남은 자리는 상시가 멈춘
  곳부터 렌더 순서로 다시 채운다. 다음 줄이 넘치면 그 자리에서 멈춘다(뒤의 짧은 줄로 건너뛰지 않는다). 실린 행은 렌더 순서로
  쓴다.
- 줄: 관계 `- 주어 → 대상: 값`, 사실 `- 주어 · 속성: 값`. 반증은 줄 앞에 표지, 주장은 끝에 말한 사람(사용자가 내놓은 주장은
  회상 섹션과 같은 사용자 꼬리표, 말한 인물이 없으면 회상 섹션과 같은 인물 꼬리표), 아는 사람이 있으면 그 뒤에 `(이름·이름만 앎)`.
- 섹션은 대화 기록 뒤, 회상 섹션 앞(캐시 블록 셋째)이다. 턴 기록(`chat_turns.memory_facts`)에 실은 사실의 id·글자 수를 줄
  순서로 남기고, 리플레이는 그 id 로 줄을 다시 렌더한다. 사실 읽기가 실패하면 섹션 없이 턴을 계속한다."""

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat import memory_fact_section, memory_recall
from api.chat.memory_fact_section import fact_line, select_fact_rows
from api.chat.memory_facts import fact_key
from api.chat.memory_nouns import episode_nouns
from api.chat.memory_window import CurrentSummary, load_current_summary
from api.chat.prompt_builder import MemorySummaryResult, PromptLane, StatRuleJudgmentResult, load_active_prompt_set
from api.chat.router import _resolve_starting_setup
from api.chat.turn_prompt import GenerationPrompt, InjectedPersona, InjectedTurnState, build_room_prompt
from api.core.config import settings
from api.db.models import ChatMemoryFact, ChatMessage, ChatMessageRole, ChatRoom, ChatRoomMemorySnapshot
from api.db.models.chat import FACT_VALUE_MAX, ChatTurn
from api.llm.client import LLMCallContext, LLMClient, SegmentedPrompt
from factories import (
    Room,
    _clear_llm_override,
    _count_queries,
    _make_memory_episode,
    _make_memory_fact,
    _open_room,
    _override_llm_client,
    _parse_sse_events,
    _room_messages,
)
from replay.logs import ReplayRefusedError
from replay.state import turn_fact_lines

# 머리글 줄(줄바꿈까지) — 두 섹션 문안이 서로의 이름을 우선순위 문장에서 부르므로 이름만으로는 섹션 위치를 가를 수 없다.
HEADER = "[관계와 사실]\n"
RECALL_HEADER = "[지난 기억 — 참고]\n"
TURN = 9


# --- 행 만들기 ------------------------------------------------------------------------------


def _fields(subject: str, target: str, value: str, *, kind: str = "fact", **extra: Any) -> dict[str, Any]:
    """사실 행 칸(방·스냅샷·순번·원문 범위 제외). 키는 사실 추출과 같은 규칙으로 만든다."""
    return {
        "kind": kind,
        "subject": subject,
        "object": target if kind == "relation" else None,
        "attribute": None if kind == "relation" else target,
        "fact_key": fact_key(kind, subject, target),
        "value": value,
        "truth_status": "confirmed",
        "asserted_by": "narration",
        "speaker": None,
        "known_by": None,
        "importance": 3,
        "end_turn": 1,
        **extra,
    }


def _sized(index: int, length: int, *, word: str = "", importance: int = 3) -> dict[str, Any]:
    """줄 길이가 정확히 `length` 인 평범한 사실. 값의 낱말은 행마다 달라 다른 행과 명사가 겹치지 않는다(`word` 를 주면 그
    낱말이 값 앞에 붙는다)."""
    attribute = f"취향{index}"
    # 값 상한을 넘는 몫은 속성에 덧붙인다(값만 늘리면 DB 에 넣을 수 없는 행이 된다).
    over = length - len(f"- 유나 · {attribute}: ") - FACT_VALUE_MAX
    if over > 0:
        attribute = attribute.ljust(len(attribute) + over, "다")
    head = f"- 유나 · {attribute}: "
    value = (f"{word} 취미{index}" if word else f"취미{index}").ljust(length - len(head), "가")
    return _fields("유나", attribute, value, importance=importance)


def _rows(*fields: dict[str, Any]) -> list[ChatMemoryFact]:
    """쓴 순서대로의 사실 행(세션 없이 만든 ORM 객체)."""
    return [ChatMemoryFact(**f) for f in fields]


def _values(rows: list[ChatMemoryFact]) -> list[str]:
    return [row.value for row in rows]


def _select(rows: list[ChatMemoryFact], query: str = "") -> list[ChatMemoryFact]:
    return select_fact_rows(rows, query=query, names=[], current_turn=TURN)


# --- 줄 렌더 --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "line"),
    [
        pytest.param(
            _fields("민수", "지아", "소꿉친구", kind="relation"), "- 민수 → 지아: 소꿉친구", id="confirmed-relation"
        ),
        pytest.param(_fields("유나", "오디션", "겨울"), "- 유나 · 오디션: 겨울", id="confirmed-fact"),
        pytest.param(
            _fields("유나", "오디션", "겨울", truth_status="claimed", asserted_by="character", speaker="민수"),
            "- 유나 · 오디션: 겨울 (민수의 말)",
            id="claimed-by-named-character",
        ),
        pytest.param(
            _fields("유나", "오디션", "겨울", truth_status="claimed", asserted_by="character"),
            "- 유나 · 오디션: 겨울 (인물의 말)",
            id="claimed-without-speaker",
        ),
        pytest.param(
            _fields("유나", "오디션", "겨울", truth_status="claimed", asserted_by="user", speaker="하늘"),
            "- 유나 · 오디션: 겨울 (사용자의 말)",
            id="claimed-by-user",
        ),
        pytest.param(
            _fields("유나", "오디션", "겨울", truth_status="disproved", asserted_by="character", speaker="민수"),
            "- (사실 아님으로 밝혀짐) 유나 · 오디션: 겨울",
            id="disproved",
        ),
        pytest.param(
            _fields("유나", "오디션", "겨울", known_by=["유나"]), "- 유나 · 오디션: 겨울 (유나만 앎)", id="known-by-one"
        ),
        pytest.param(
            _fields("유나", "오디션", "겨울", known_by=["유나", "민수"]),
            "- 유나 · 오디션: 겨울 (유나·민수만 앎)",
            id="known-by-several",
        ),
        pytest.param(
            _fields(
                "유나",
                "오디션",
                "겨울",
                truth_status="claimed",
                asserted_by="character",
                speaker="민수",
                known_by=["민수"],
            ),
            "- 유나 · 오디션: 겨울 (민수의 말) (민수만 앎)",
            id="claimed-and-known",
        ),
    ],
)
def test_fact_line_tags(fields: dict[str, Any], line: str) -> None:
    assert fact_line(ChatMemoryFact(**fields)) == line


def test_assertion_tails_reuse_the_recall_constants(monkeypatch: pytest.MonkeyPatch) -> None:
    """사용자·인물 꼬리표는 회상 줄과 같은 상수다 — 두 섹션 문안이 같은 꼬리표를 설명하므로 한쪽만 바뀌면 설명과 줄이 어긋난다.
    회상 모듈의 상수를 바꾸면 사실 줄도 따라 바뀌어야 한다(같은 글을 따로 적어 둔 사본이면 따라오지 않는다)."""
    monkeypatch.setattr(memory_recall, "USER_ASSERTION_TAIL", " (바뀐 사용자 꼬리표)")
    monkeypatch.setattr(memory_recall, "CHARACTER_ASSERTION_TAIL", " (바뀐 인물 꼬리표)")
    user = _fields("유나", "오디션", "겨울", truth_status="claimed", asserted_by="user")
    character = _fields("유나", "오디션", "겨울", truth_status="claimed", asserted_by="character")
    assert fact_line(ChatMemoryFact(**user)) == "- 유나 · 오디션: 겨울 (바뀐 사용자 꼬리표)"
    assert fact_line(ChatMemoryFact(**character)) == "- 유나 · 오디션: 겨울 (바뀐 인물 꼬리표)"


def test_claim_spoken_under_the_user_name_gets_the_user_tail() -> None:
    """추출이 사용자 말을 사용자의 이야기 속 이름을 가진 인물의 말로 적어도(`asserted_by` 가 인물) 사용자 꼬리표다. 이름은 사실
    키와 같은 정규화(대소문자·공백)로 견주고, 다른 인물 이름은 그대로 그 인물의 말이다."""
    spoken = _fields("유나", "오디션", "겨울", truth_status="claimed", asserted_by="character", speaker=" Haneul ")
    assert fact_line(ChatMemoryFact(**spoken), user_name="haneul") == "- 유나 · 오디션: 겨울 (사용자의 말)"
    assert fact_line(ChatMemoryFact(**spoken), user_name="민수") == "- 유나 · 오디션: 겨울 ( Haneul 의 말)"
    assert fact_line(ChatMemoryFact(**spoken)) == "- 유나 · 오디션: 겨울 ( Haneul 의 말)"


# --- 키별 최신 · 렌더 순서 ---------------------------------------------------------------------


def test_same_key_keeps_only_the_latest_row() -> None:
    """같은 키의 행이 셋이면 마지막 하나만 실린다. 키는 정규화한 값이라 대소문자·공백이 달라도 같은 키다."""
    rows = _rows(
        _fields("유나", "오디션", "봄"),
        _fields("유나", "오디션", "여름"),
        _fields("유나", "오디션 ", "겨울"),
        _fields("민수", "오디션", "가을"),
    )
    assert sorted(_values(_select(rows))) == ["가을", "겨울"]


def test_disproved_value_does_not_come_back_but_a_corrected_value_does() -> None:
    disproved = _fields("유나", "오디션", "겨울", truth_status="disproved")
    again = _fields("유나", "오디션", "겨울", truth_status="claimed", asserted_by="character", speaker="민수")
    corrected = _fields("유나", "오디션", "봄", truth_status="claimed", asserted_by="character", speaker="민수")

    assert [fact_line(row) for row in _select(_rows(disproved, again))] == [
        "- (사실 아님으로 밝혀짐) 유나 · 오디션: 겨울"
    ]
    assert [fact_line(row) for row in _select(_rows(disproved, corrected))] == ["- 유나 · 오디션: 봄 (민수의 말)"]


def test_render_order_groups_then_importance_then_recency() -> None:
    """관계(중요도 1)가 먼저, 아는 사람이 있는 사실, 반증, 그 밖. 그 밖 묶음은 중요도, 같으면 나중에 쓴 쪽이 먼저다."""
    rows = _rows(
        _fields("유나", "일정", "그밖-중요5-먼저", importance=5),
        _fields("유나", "취미", "그밖-중요2", importance=2),
        _fields("유나", "비밀", "반증", truth_status="disproved", importance=5),
        _fields("유나", "약속", "아는사람", known_by=["민수"], importance=1),
        _fields("유나", "민수", "관계", kind="relation", importance=1),
        _fields("유나", "버릇", "그밖-중요5-나중", importance=5),
    )
    assert _values(_select(rows)) == ["관계", "아는사람", "반증", "그밖-중요5-나중", "그밖-중요5-먼저", "그밖-중요2"]


# --- 글자 상한 ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("seventh", "kept"),
    [
        # 100자 여섯 줄 + 줄바꿈 다섯 = 605, 줄바꿈 하나를 더해 일곱째 94자면 정확히 700.
        pytest.param(94, 7, id="exactly-700"),
        pytest.param(95, 6, id="one-char-over"),
    ],
)
def test_cap_cuts_in_render_order_and_stops_at_the_first_overflow(seventh: int, kept: int) -> None:
    """일곱째 줄이 넘치면 거기서 멈춘다 — 그 뒤의 짧은 줄(중요도가 가장 낮다)은 들어갈 자리가 있어도 싣지 않는다."""
    tiny = _fields("유나", "꼬리", "끝", importance=1)
    # 같은 중요도는 나중에 쓴 쪽이 먼저라, 렌더 순서(100자 여섯 → 일곱째)의 거꾸로 쓴다.
    sized = [_sized(6, seventh), *[_sized(i, 100) for i in reversed(range(6))]]
    picked = _select(_rows(tiny, *sized))

    assert [row.attribute for row in picked] == [f"취향{i}" for i in range(kept)]
    text = "\n".join(fact_line(row) for row in picked)
    assert len(text) == (700 if kept == 7 else 605)


# --- 관련 선택 ---------------------------------------------------------------------------------

_LIGHTHOUSE = _fields("유나", "약속 장소", "등대 앞에서 만나기로 함", importance=1)
_LOCKER = _fields("유나", "사물함", "자물쇠 비밀번호는 0417", importance=1)


def _fillers(count: int, length: int = 150) -> list[dict[str, Any]]:
    """중요도 5 의 긴 사실 `count` 개(렌더 순서로 앞에 선다). 쓴 순서의 거꾸로가 렌더 순서다."""
    return [_sized(i, length, importance=5) for i in reversed(range(count))]


def test_relevant_row_enters_from_outside_the_constant_share() -> None:
    """150자 여섯 줄이면 렌더 순서로는 넷(603자)에서 멈춰 중요도 1 의 등대 줄이 빠진다. 사용자가 등대(이 방에서 한 행에만 나오는
    명사)를 꺼내면 상시 한 줄 뒤에 관련으로 들어오고, 남은 자리를 렌더 순서로 채운 결과에서도 렌더 순서(맨 끝)로 쓴다."""
    rows = _rows(_LIGHTHOUSE, *_fillers(6))

    assert _LIGHTHOUSE["value"] not in _values(_select(rows))
    picked = _select(rows, "등대 기억나?")
    assert [row.attribute for row in picked] == ["취향0", "취향1", "취향2", "취향3", "약속 장소"]


def test_common_noun_in_the_query_pulls_nothing() -> None:
    """학교가 일곱 행 중 둘(비율 0.29 > 0.2)에 나오면 질의에서 빠져, 학교를 꺼내도 렌더 순서로만 고른다. 빼지 않았다면 두 행의
    점수가 0.7·(ln(8/3)+1)/(ln(8/2)+1) + 중요도 0.05 ≈ 0.63 으로 임계를 넘어 실린다. 같은 배치에서 그 행의 드문 명사(만나기)를
    꺼내면 실리므로, 학교가 빠진 까닭은 배치가 아니라 흔한 명사 제외다."""
    school = _fields("유나", "약속 장소", "학교 앞에서 만나기로 함", importance=5)
    rows = _rows(school, _sized(5, 150, word="학교", importance=5), *_fillers(5))
    assert school["value"] not in _values(_select(rows))
    assert _values(_select(rows, "학교 기억나?")) == _values(_select(rows))
    assert school["value"] in _values(_select(rows, "만나기로 했지?"))


@pytest.mark.parametrize(
    ("fillers", "pulled"), [pytest.param(3, False, id="four-rows"), pytest.param(4, True, id="five-rows")]
)
def test_rooms_with_fewer_than_five_rows_get_no_relevant_rows(fillers: int, pulled: bool) -> None:
    """270자 줄 셋이면 두 줄에서 멈춰 등대 줄이 빠진다. 행이 넷이면 관련 선택이 없고, 다섯이면 등대 줄이 들어온다."""
    rows = _rows(_LIGHTHOUSE, *[_sized(i, 270, importance=5) for i in reversed(range(fillers))])
    assert (_LIGHTHOUSE["value"] in _values(_select(rows, "등대 기억나?"))) is pulled


# --- 방 프롬프트 ----------------------------------------------------------------------------


async def _fact_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, *, lane: str = "story"
) -> tuple[Room, dict[int, uuid.UUID]]:
    """8턴짜리 방에 스냅샷 셋(턴 2·4·6 응답까지 접힘)을 심고 (방, 턴 → 스냅샷 id) 를 돌려준다."""
    room = await _open_room(db_client, db_session, turns=8, lane=lane)
    snapshots: dict[int, uuid.UUID] = {}
    for turn in (2, 4, 6):
        assistant = room.turns[turn][1]
        snapshot = ChatRoomMemorySnapshot(
            chat_room_id=room.room_id,
            cursor_created_at=assistant.created_at,
            cursor_message_id=assistant.id,
            summary_text=f"턴 {turn} 까지의 요약",
            source="auto",
        )
        db_session.add(snapshot)
        await db_session.flush()
        snapshots[turn] = snapshot.id
    await db_session.commit()
    return room, snapshots


async def _plant(
    db_session: AsyncSession, room: Room, snapshot_id: uuid.UUID, fields: list[dict[str, Any]], *, start: int = 0
) -> list[uuid.UUID]:
    rows = [
        _make_memory_fact(room.room_id, snapshot_id, ordinal=start + i, start_turn=f["end_turn"], **f)
        for i, f in enumerate(fields)
    ]
    db_session.add_all(rows)
    await db_session.commit()
    return [row.id for row in rows]


async def _build(
    db_session: AsyncSession,
    room: Room,
    user_content: str,
    *,
    lane: PromptLane = "story",
    turn_state: InjectedTurnState | None = None,
) -> GenerationPrompt:
    chat_room = await db_session.get(ChatRoom, room.room_id)
    assert chat_room is not None
    setup = await _resolve_starting_setup(db_session, chat_room)
    prompt_set, sections = await load_active_prompt_set(db_session, lane=lane)
    history = await _room_messages(db_session, room.room_id)
    return await build_room_prompt(
        db_session, chat_room, setup, history, user_content, None, prompt_set, sections, turn_state=turn_state
    )


def _facts_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "memory_facts_inject", True)


def _section(prompt: str) -> str:
    start = prompt.index(HEADER)
    end = prompt.find("\n\n", start)
    return prompt[start:] if end == -1 else prompt[start:end]


_AUDITION = _fields("유나", "오디션", "겨울", truth_status="claimed", asserted_by="character", speaker="민수")
_FRIENDS = _fields("민수", "지아", "소꿉친구", kind="relation")


async def test_facts_off_keeps_generation_prompt_bytes_and_reads_no_facts(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """스위치가 꺼져 있으면 사실 행이 있어도 없을 때와 같은 프롬프트, 같은 SQL 문 수다."""
    room, snapshots = await _fact_room(db_client, db_session)
    await _plant(db_session, room, snapshots[2], [_AUDITION, _FRIENDS])
    with _count_queries() as with_facts_count:
        with_facts = await _build(db_session, room, "오디션 언제야?")
        statements_with_facts = with_facts_count()
    await db_session.execute(sa.delete(ChatMemoryFact).where(ChatMemoryFact.chat_room_id == room.room_id))
    await db_session.commit()
    with _count_queries() as without_facts_count:
        without_facts = await _build(db_session, room, "오디션 언제야?")
        statements_without_facts = without_facts_count()

    assert HEADER not in with_facts.prompt
    assert with_facts.prompt == without_facts.prompt
    assert statements_with_facts == statements_without_facts
    assert with_facts.memory_facts == ()


async def test_facts_section_follows_history_and_precedes_recall(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """켜면 사실 섹션 하나가 대화 기록 뒤·회상 섹션 앞에 더해질 뿐 나머지는 꺼졌을 때와 같다."""
    room, snapshots = await _fact_room(db_client, db_session)
    await _plant(db_session, room, snapshots[2], [_AUDITION, _FRIENDS])
    turn_one = room.turns[1]
    scenes = [
        *[(f"잡담 {i}", f"평범한 하루 {i}번째.", [f"일상{i}"]) for i in range(5)],
        ("밀알당에 간 날", "태민이랑 밀알당에서 소금빵을 먹었다.", ["밀알당", "소금빵"]),
    ]
    for ordinal, (title, detail, nouns) in enumerate(scenes):
        db_session.add(
            _make_memory_episode(
                room.room_id,
                snapshots[2],
                ordinal=ordinal,
                start_created_at=turn_one[0].created_at,
                start_message_id=turn_one[0].id,
                end_created_at=turn_one[1].created_at,
                end_message_id=turn_one[1].id,
                title=title,
                detail=detail,
                nouns=episode_nouns(nouns, title, detail),
                asserted_by="narration",
            )
        )
    await db_session.commit()
    monkeypatch.setattr(settings, "memory_episodes_recall", True)
    off = await _build(db_session, room, "밀알당 기억나?")
    _facts_on(monkeypatch)
    on = await _build(db_session, room, "밀알당 기억나?")

    section = _section(on.prompt)
    assert section.endswith("\n- 민수 → 지아: 소꿉친구\n- 유나 · 오디션: 겨울 (민수의 말)")
    assert on.prompt.replace(section + "\n\n", "", 1) == off.prompt
    last_history_line = room.turns[8][1].content
    assert (
        on.prompt.index(last_history_line)
        < on.prompt.index(HEADER)
        < on.prompt.index(RECALL_HEADER)
        < on.prompt.rindex("밀알당 기억나?")
    )


async def test_facts_keep_first_two_cache_blocks_identical(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, snapshots = await _fact_room(db_client, db_session)
    await _plant(db_session, room, snapshots[2], [_AUDITION, _FRIENDS])
    off = await _build(db_session, room, "오디션 언제야?")
    _facts_on(monkeypatch)
    on = await _build(db_session, room, "오디션 언제야?")

    assert isinstance(off.prompt, SegmentedPrompt) and isinstance(on.prompt, SegmentedPrompt)
    assert on.prompt.segments[0:2] == off.prompt.segments[0:2]
    assert HEADER in on.prompt.segments[2] and HEADER not in off.prompt.segments[2]


async def test_rewind_brings_back_the_previous_value(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """턴 6 스냅샷이 같은 키의 값을 바꿨으면 지금 값만 실리고, 그 스냅샷이 되감기로 지워지면(사실 행은 함께 지워진다) 다음 읽기에
    앞 값이 돌아온다."""
    room, snapshots = await _fact_room(db_client, db_session)
    await _plant(db_session, room, snapshots[2], [_fields("유나", "오디션", "봄")])
    await _plant(db_session, room, snapshots[6], [_fields("유나", "오디션", "겨울")])
    _facts_on(monkeypatch)

    now = _section((await _build(db_session, room, "오디션 언제야?")).prompt)
    assert now.endswith("\n- 유나 · 오디션: 겨울") and "오디션: 봄" not in now

    await db_session.execute(sa.delete(ChatRoomMemorySnapshot).where(ChatRoomMemorySnapshot.id == snapshots[6]))
    await db_session.commit()
    assert _section((await _build(db_session, room, "오디션 언제야?")).prompt).endswith("\n- 유나 · 오디션: 봄")


async def test_facts_section_never_exceeds_its_computed_maximum(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """최대값 = 실제 머리글(DB 의 사실 섹션 본문에서 자리표시자를 뺀 것) + 렌더 상한 700. 정확히 700자를 채우는 행을 심으면
    섹션이 정확히 그 길이다."""
    _, sections = await load_active_prompt_set(db_session, lane="story")
    [body] = [section.body for section in sections if section.slot == "memory_facts"]
    maximum = len(body.replace("{memory_fact_lines}", "")) + memory_fact_section.RENDER_MAX_CHARS

    room, snapshots = await _fact_room(db_client, db_session)
    await _plant(db_session, room, snapshots[2], [_sized(6, 94), *[_sized(i, 100) for i in reversed(range(6))]])
    _facts_on(monkeypatch)
    built = await _build(db_session, room, "오디션 언제야?")
    assert len(built.memory_facts) == 7
    assert len(_section(built.prompt)) == maximum


async def test_facts_never_reach_past_the_turn_cursor(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """지난 턴을 그때의 요약(턴 4 커서)으로 다시 조립하면 그 뒤에 접힌 턴 6 스냅샷의 사실은 싣지 않는다 — 그때는 없던 사실이다."""
    room, snapshots = await _fact_room(db_client, db_session)
    await _plant(db_session, room, snapshots[2], [_fields("유나", "오디션", "봄")])
    await _plant(db_session, room, snapshots[6], [_fields("유나", "생일", "삼월")])
    _facts_on(monkeypatch)

    now = _section((await _build(db_session, room, "생일 언제야?")).prompt)
    assert "- 유나 · 생일: 삼월" in now and "- 유나 · 오디션: 봄" in now

    cursor = room.turns[4][1]
    then = InjectedTurnState(
        summary=CurrentSummary(cursor=(cursor.created_at, cursor.id), text="턴 4 까지의 요약"),
        memory_note="",
        stats={},
        persona=None,
    )
    past = _section((await _build(db_session, room, "생일 언제야?", turn_state=then)).prompt)
    assert "생일" not in past and past.endswith("\n- 유나 · 오디션: 봄")


async def test_facts_disabled_when_generation_window_is_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, snapshots = await _fact_room(db_client, db_session)
    await _plant(db_session, room, snapshots[2], [_AUDITION, _FRIENDS])
    _facts_on(monkeypatch)
    monkeypatch.setattr(settings, "memory_window_generation", False)
    with _count_queries() as count:
        built = await _build(db_session, room, "오디션 언제야?")
        statements = count()
    monkeypatch.setattr(settings, "memory_facts_inject", False)
    with _count_queries() as count_off:
        await _build(db_session, room, "오디션 언제야?")
    assert HEADER not in built.prompt
    assert built.memory_facts == ()
    assert statements == count_off()


async def test_character_lane_gets_the_facts_section_too(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, snapshots = await _fact_room(db_client, db_session, lane="character")
    await _plant(db_session, room, snapshots[2], [_AUDITION])
    _facts_on(monkeypatch)
    built = await _build(db_session, room, "오디션 언제야?", lane="character")
    assert _section(built.prompt).endswith("\n- 유나 · 오디션: 겨울 (민수의 말)")
    assert len(built.memory_facts) == 1


async def test_room_prompt_uses_the_persona_name_for_the_user_tail(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """조립은 그 턴 대화 프로필의 이름을 사용자 이름으로 넘긴다 — 그 이름이 말한 주장은 사용자 꼬리표다."""
    room, snapshots = await _fact_room(db_client, db_session)
    claim = _fields("유나", "오디션", "겨울", truth_status="claimed", asserted_by="character", speaker="하늘")
    await _plant(db_session, room, snapshots[2], [claim])
    _facts_on(monkeypatch)
    summary = await load_current_summary(db_session, room.room_id)
    state = InjectedTurnState(
        summary=summary, memory_note="", stats={}, persona=InjectedPersona(name="하늘", gender=None, description="")
    )
    built = await _build(db_session, room, "오디션 언제야?", turn_state=state)
    assert _section(built.prompt).endswith("\n- 유나 · 오디션: 겨울 (사용자의 말)")


# --- 턴 기록 · 실패 흡수 · 리플레이 -------------------------------------------------------------


class _PromptCapture(LLMClient):
    """생성 프롬프트를 모으고 고정 응답을 낸다. 판정은 아무 규칙도 고르지 않는다."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.prompts.append(prompt)
        yield "응답"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        if response_schema is StatRuleJudgmentResult:
            return StatRuleJudgmentResult(fired_rule_ids=[])
        return MemorySummaryResult(summary="요약")


async def _send(
    client: httpx.AsyncClient, method: str, path: str, body: dict[str, object] | None, fake: LLMClient
) -> None:
    _override_llm_client(fake)
    try:
        response = await client.request(method, path, json=body)
    finally:
        _clear_llm_override()
    assert response.status_code == 200, response.text
    assert _parse_sse_events(response.text)[-1]["type"] == "done", response.text


async def _records(db_session: AsyncSession, room_id: uuid.UUID) -> dict[str, ChatTurn]:
    """방의 턴 기록을 종류별로(한 테스트 안에서는 `created_at` 이 같아 순서로는 가를 수 없다)."""
    records = (
        await db_session.scalars(
            sa.select(ChatTurn).where(ChatTurn.chat_room_id == room_id).execution_options(populate_existing=True)
        )
    ).all()
    by_kind: dict[str, ChatTurn] = {record.kind: record for record in records}
    assert len(by_kind) == len(records)
    return by_kind


async def _relevance_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> tuple[Room, dict[str, uuid.UUID], list[uuid.UUID]]:
    """150자 사실 여섯(렌더 순서로 앞 넷만 실린다)과 중요도 1 의 등대·자물쇠 줄. (방, 이름 → id, 앞 넷의 id 렌더 순서)."""
    room, snapshots = await _fact_room(db_client, db_session)
    ids = await _plant(db_session, room, snapshots[2], [_LIGHTHOUSE, _LOCKER, *_fillers(6)])
    fillers_in_render_order = list(reversed(ids[2:]))[:4]
    return room, {"lighthouse": ids[0], "locker": ids[1]}, fillers_in_render_order


async def test_send_regenerate_and_edit_record_their_own_facts(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """세 경로 모두 그 턴에 다시 고른 사실을 줄 순서로 자기 기록 행에 남긴다 — 재생성은 앞 기록을 물려받지 않고, 수정은 고친
    글로 관련 행을 고른다. 글자 수는 줄 길이다."""
    room, ids, fillers = await _relevance_room(db_client, db_session)
    _facts_on(monkeypatch)
    fake = _PromptCapture()

    await _send(db_client, "POST", f"/chat-rooms/{room.room_id}/messages", {"content": "등대 기억나?"}, fake)
    await _send(db_client, "POST", f"/chat-rooms/{room.room_id}/regenerate", None, fake)
    user_id = await db_session.scalar(
        sa.select(ChatMessage.id)
        .where(ChatMessage.chat_room_id == room.room_id, ChatMessage.role == ChatMessageRole.USER)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
    )
    await _send(
        db_client, "PATCH", f"/chat-rooms/{room.room_id}/messages/{user_id}", {"content": "자물쇠 기억나?"}, fake
    )

    records = await _records(db_session, room.room_id)
    as_ids = {kind: [entry["factId"] for entry in record.memory_facts] for kind, record in records.items()}
    expected_head = [str(fact_id) for fact_id in fillers]
    assert as_ids == {
        "send": [*expected_head, str(ids["lighthouse"])],
        "regenerate": [*expected_head, str(ids["lighthouse"])],
        "edit": [*expected_head, str(ids["locker"])],
    }
    send = records["send"].memory_facts
    assert [entry["chars"] for entry in send] == [
        150,
        150,
        150,
        150,
        len("- 유나 · 약속 장소: 등대 앞에서 만나기로 함"),
    ]
    assert all(set(entry) == {"factId", "chars"} for record in records.values() for entry in record.memory_facts)
    assert all(HEADER in prompt for prompt in fake.prompts)


async def test_fact_read_failure_is_absorbed_and_the_turn_finishes(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """사실 읽기가 DB 오류(실제로 실패한 문장)로 끝나면 섹션 없이 턴을 마치고 경고·승격을 남긴다. 요청 세션은 다음 문장을 계속
    쓸 수 있어야 한다(턴 기록까지 커밋된다)."""
    room, snapshots = await _fact_room(db_client, db_session)
    await _plant(db_session, room, snapshots[2], [_AUDITION])
    _facts_on(monkeypatch)
    monkeypatch.setattr(memory_fact_section, "_fact_statement", lambda room_id, cursor: sa.text("SELECT 1/0"))
    captured: list[str] = []
    monkeypatch.setattr(
        memory_fact_section, "capture_dependency_failure", lambda exc, *, dependency: captured.append(dependency)
    )
    fake = _PromptCapture()
    with caplog.at_level(logging.WARNING):
        await _send(db_client, "POST", f"/chat-rooms/{room.room_id}/messages", {"content": "오디션 언제야?"}, fake)

    assert HEADER not in fake.prompts[-1]
    assert captured == ["db"]
    assert any("사실" in record.getMessage() for record in caplog.records)
    assert [record.memory_facts for record in (await _records(db_session, room.room_id)).values()] == [[]]


async def test_fact_selection_failure_is_absorbed_and_the_turn_finishes(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """DB 가 아닌 곳(고르기·렌더)에서 난 예외도 SSE 로 새지 않는다 — 섹션 없이 턴을 마치고 스택이 실린 경고와 승격 하나를 남긴다."""
    room, snapshots = await _fact_room(db_client, db_session)
    await _plant(db_session, room, snapshots[2], [_AUDITION])
    _facts_on(monkeypatch)

    def broken(*_args: object, **_kwargs: object) -> list[ChatMemoryFact]:
        raise ValueError("고르기 실패")

    monkeypatch.setattr(memory_fact_section, "select_fact_rows", broken)
    captured: list[str] = []
    monkeypatch.setattr(
        memory_fact_section, "capture_dependency_failure", lambda exc, *, dependency: captured.append(dependency)
    )
    fake = _PromptCapture()
    with caplog.at_level(logging.WARNING):
        await _send(db_client, "POST", f"/chat-rooms/{room.room_id}/messages", {"content": "오디션 언제야?"}, fake)

    assert HEADER not in fake.prompts[-1]
    assert len(captured) == 1 and captured != ["db"]
    [warning] = [record for record in caplog.records if "사실" in record.getMessage()]
    assert warning.exc_info is not None and warning.exc_info[0] is ValueError
    assert [record.memory_facts for record in (await _records(db_session, room.room_id)).values()] == [[]]


async def test_replay_rebuilds_fact_lines_from_turn_record(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """리플레이는 지금 행으로 다시 고르지 않고 그 턴 기록의 id 로 줄을 다시 렌더한다 — 턴 뒤에 같은 키의 새 값이 쓰여도 그 턴의
    프롬프트를 바이트까지 다시 만든다. 기록한 사실이 사라졌으면 그 턴은 다시 만들 수 없다고 거부한다."""
    room, ids, _ = await _relevance_room(db_client, db_session)
    _facts_on(monkeypatch)
    before = await _room_messages(db_session, room.room_id)
    fake = _PromptCapture()
    await _send(db_client, "POST", f"/chat-rooms/{room.room_id}/messages", {"content": "등대 기억나?"}, fake)
    record = (await _records(db_session, room.room_id))["send"]

    snapshot_id = await db_session.scalar(
        sa.select(ChatMemoryFact.snapshot_id).where(ChatMemoryFact.id == ids["lighthouse"])
    )
    assert snapshot_id is not None
    await _plant(
        db_session, room, snapshot_id, [_fields("유나", "약속 장소", "등대 말고 정류장", importance=1)], start=19
    )

    lines = await turn_fact_lines(db_session, record.assistant_message_id)
    chat_room = await db_session.get(ChatRoom, room.room_id)
    assert chat_room is not None
    summary = await load_current_summary(db_session, room.room_id)
    setup = await _resolve_starting_setup(db_session, chat_room)
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story")
    state = InjectedTurnState(summary=summary, memory_note="", stats={}, persona=None, fact_lines=lines)
    replayed = await build_room_prompt(
        db_session, chat_room, setup, before, "등대 기억나?", None, prompt_set, sections, turn_state=state
    )
    selected_now = await build_room_prompt(
        db_session, chat_room, setup, before, "등대 기억나?", None, prompt_set, sections
    )

    assert replayed.prompt == fake.prompts[0]
    assert selected_now.prompt != fake.prompts[0]

    await db_session.execute(sa.delete(ChatMemoryFact).where(ChatMemoryFact.id == ids["lighthouse"]))
    await db_session.commit()
    with pytest.raises(ReplayRefusedError):
        await turn_fact_lines(db_session, record.assistant_message_id)

    # 리플레이의 사실 주입 스위치가 꺼져 있으면 사실 섹션을 싣지 않으므로 사라진 사실은 거부할 이유가 아니다.
    monkeypatch.setattr(settings, "memory_facts_inject", False)
    assert await turn_fact_lines(db_session, record.assistant_message_id) == ""


async def test_replay_of_a_turn_without_facts_gets_no_lines(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, _ = await _fact_room(db_client, db_session)
    await _send(db_client, "POST", f"/chat-rooms/{room.room_id}/messages", {"content": "안녕"}, _PromptCapture())
    record = (await _records(db_session, room.room_id))["send"]
    _facts_on(monkeypatch)
    assert await turn_fact_lines(db_session, record.assistant_message_id) == ""
    assert await turn_fact_lines(db_session, uuid.uuid4()) == ""
