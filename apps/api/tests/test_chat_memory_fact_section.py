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
- 이름 정확 조회: 상시 몫 뒤·관련 몫 앞에, 장면 인물(이번 사용자 메시지·직전 응답에 이름이 나온 방 인물, 사용자 제외)이 주어거나
  관계 대상인 행을 렌더 순서로 420자(상시 몫 끝 210자 + 같은 크기)까지 싣는다. 값·속성에 이름이 나오는 것만으로는 걸리지 않고,
  지식 범위 필터가 뺀 행은 이름이 나와도 돌아오지 않는다. 섹션 최대는 여전히 머리글 + 700자다.
- 줄: 관계 `- 주어 → 대상: 값`, 사실 `- 주어 · 속성: 값`. 반증은 줄 앞에 표지, 주장은 끝에 말한 사람(사용자가 내놓은 주장은
  회상 섹션과 같은 사용자 꼬리표, 말한 인물이 없으면 회상 섹션과 같은 인물 꼬리표), 아는 사람이 있으면 그 뒤에 `(이름·이름만 앎)`.
- 키별 최신 행이 확인되지 않은 주장이고 사용자 꼬리표가 붙지 않으면(인물·서술이 말로만 전한 것) 그 키는 싣지 않는다 — 옛 값이
  되살아나지 않고, 지식 범위 필터와 무관하게 걸린다. 확인된 행·반증 행·사용자 주장은 싣는다.
- 섹션은 대화 기록 뒤, 회상 섹션 앞(캐시 블록 셋째)이다. 턴 기록(`chat_turns.memory_facts`)에 실은 사실의 id·글자 수를 줄
  순서로 남기고, 리플레이는 그 id 로 줄을 다시 렌더한다. 사실 읽기가 실패하면 섹션 없이 턴을 계속한다.
- 지식 범위 필터 스위치(`memory_knowledge_filter`)가 켜져 있으면 키별 최신 행 중 아는 사람이 이번 장면에 없는 행을 고르기 전에
  뺀다(빠진 자리는 다음 후보가 채운다). 스토리 방은 아는 사람이 정해진 행이 있을 때만 미디어 북 인물을 한 번 읽는다. 사실 주입이
  꺼져 있으면 필터가 켜져 있어도 프롬프트·SQL 이 같다. 켠 턴은 직전 응답의 대사 따옴표 안에만 나온 이름을 장면 인물로 세지
  않는다. 장면 인물의 이름 출처는 사실 행뿐이다(장면 행의 아는 사람 칸은 회상의 가림에만 쓴다).
- 임베딩 회상 스위치(`memory_embed_recall`)가 켜져 있으면 관련 몫은 명사 순위와, 회상과 같은 질의 임베딩으로 잰 사실 임베딩
  거리 순위(지금 모델·차원, 거리 상한 안)를 RRF 로 합친 순서다. 거리 순위는 지식 범위 필터를 지난 행 사이에서만 매긴다. 벡터
  쪽이 비면 명사 단독과 같다."""

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
from api.chat.memory_knowledge import USER_INSTRUCTION_WORD
from api.chat.memory_nouns import episode_nouns
from api.chat.memory_window import CurrentSummary, load_current_summary
from api.chat.prompt_builder import MemorySummaryResult, PromptLane, StatRuleJudgmentResult, load_active_prompt_set
from api.chat.router import _resolve_starting_setup
from api.chat.turn_prompt import GenerationPrompt, InjectedPersona, InjectedTurnState, build_room_prompt
from api.content.author_macros import FALLBACK_USER_NAME
from api.core.config import settings
from api.db.models import (
    ChatMemoryEpisode,
    ChatMemoryFact,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    ChatRoomMemorySnapshot,
)
from api.db.models.chat import FACT_VALUE_MAX, ChatTurn
from api.llm.chat_models import ChatModelId
from api.llm.client import LLMCallContext, LLMClient, SegmentedPrompt
from api.llm.voyage import VoyageEmbeddingClient
from factories import (
    PRODUCTION_ENV_NAMES,
    Room,
    VoyageStub,
    _clear_llm_override,
    _count_queries,
    _make_memory_embedding,
    _make_memory_episode,
    _make_memory_fact,
    _memory_scope_covers_gemini,
    _open_room,
    _override_llm_client,
    _parse_sse_events,
    _room_messages,
    load_production_env,
)
from replay.logs import ReplayRefusedError
from replay.state import RestoredTurn, turn_fact_lines

# 머리글 줄(줄바꿈까지) — 사실 섹션 문안이 우선순위 문장에서 회상 섹션 이름을 부르므로 이름만으로는 섹션 위치를 가를 수 없다.
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


def _sized(index: int, length: int, *, word: str = "", importance: int = 3, subject: str = "유나") -> dict[str, Any]:
    """줄 길이가 정확히 `length` 인 평범한 사실. 값의 낱말은 행마다 달라 다른 행과 명사가 겹치지 않는다(`word` 를 주면 그
    낱말이 값 앞에 붙는다)."""
    attribute = f"취향{index}"
    # 값 상한을 넘는 몫은 속성에 덧붙인다(값만 늘리면 DB 에 넣을 수 없는 행이 된다).
    over = length - len(f"- {subject} · {attribute}: ") - FACT_VALUE_MAX
    if over > 0:
        attribute = attribute.ljust(len(attribute) + over, "다")
    head = f"- {subject} · {attribute}: "
    value = (f"{word} 취미{index}" if word else f"취미{index}").ljust(length - len(head), "가")
    return _fields(subject, attribute, value, importance=importance)


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
    corrected = _fields("유나", "오디션", "봄")

    assert [fact_line(row) for row in _select(_rows(disproved, again))] == [
        "- (사실 아님으로 밝혀짐) 유나 · 오디션: 겨울"
    ]
    assert [fact_line(row) for row in _select(_rows(disproved, corrected))] == ["- 유나 · 오디션: 봄"]


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
    model: ChatModelId = "gemini",
    turn_state: InjectedTurnState | None = None,
    embedding_client: VoyageEmbeddingClient | None = None,
) -> GenerationPrompt:
    """그 방의 생성 프롬프트. `model` 은 방의 글쓰기 모델 — 라우트처럼 그 모델의 세트로 조립한다."""
    chat_room = await db_session.get(ChatRoom, room.room_id)
    assert chat_room is not None
    setup = await _resolve_starting_setup(db_session, chat_room)
    prompt_set, sections = await load_active_prompt_set(db_session, lane=lane, model=model)
    history = await _room_messages(db_session, room.room_id)
    return await build_room_prompt(
        db_session,
        chat_room,
        setup,
        history,
        user_content,
        None,
        prompt_set,
        sections,
        turn_state=turn_state,
        embedding_client=embedding_client,
    )


def _facts_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "memory_facts_inject", True)
    _memory_scope_covers_gemini(monkeypatch)


def _section(prompt: str) -> str:
    start = prompt.index(HEADER)
    end = prompt.find("\n\n", start)
    return prompt[start:] if end == -1 else prompt[start:end]


_AUDITION = _fields("유나", "오디션", "겨울", truth_status="claimed", asserted_by="user")
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


async def _plant_scenes(db_session: AsyncSession, room: Room, snapshot_id: uuid.UUID) -> None:
    """"밀알당" 을 물으면 회상에 걸리는 장면 하나와 걸리지 않는 잡담 장면 다섯을 심는다."""
    turn_one = room.turns[1]
    scenes = [
        *[(f"잡담 {i}", f"평범한 하루 {i}번째.", [f"일상{i}"]) for i in range(5)],
        ("밀알당에 간 날", "태민이랑 밀알당에서 소금빵을 먹었다.", ["밀알당", "소금빵"]),
    ]
    for ordinal, (title, detail, nouns) in enumerate(scenes):
        db_session.add(
            _make_memory_episode(
                room.room_id,
                snapshot_id,
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


async def test_facts_section_follows_history_and_precedes_recall(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """켜면 사실 섹션 하나가 대화 기록 뒤·회상 섹션 앞에 더해질 뿐 나머지는 꺼졌을 때와 같다."""
    room, snapshots = await _fact_room(db_client, db_session)
    await _plant(db_session, room, snapshots[2], [_AUDITION, _FRIENDS])
    await _plant_scenes(db_session, room, snapshots[2])
    monkeypatch.setattr(settings, "memory_episodes_recall", True)
    _memory_scope_covers_gemini(monkeypatch)
    off = await _build(db_session, room, "밀알당 기억나?")
    _facts_on(monkeypatch)
    on = await _build(db_session, room, "밀알당 기억나?")

    section = _section(on.prompt)
    assert section.endswith("\n- 민수 → 지아: 소꿉친구\n- 유나 · 오디션: 겨울 (사용자의 말)")
    assert on.prompt.replace(section + "\n\n", "", 1) == off.prompt
    last_history_line = room.turns[8][1].content
    assert (
        on.prompt.index(last_history_line)
        < on.prompt.index(HEADER)
        < on.prompt.index(RECALL_HEADER)
        < on.prompt.rindex("밀알당 기억나?")
    )


@pytest.mark.parametrize("lane", ["story", "character"])
async def test_recall_on_with_facts_off_never_names_the_facts_section(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    lane: PromptLane,
) -> None:
    """회상만 켜고 사실 주입은 끈 턴 — 회상 섹션은 실리지만 프롬프트 어디에도 사실 섹션 이름이 없다. 실리지 않은 섹션을 우선순위
    문장이 가리키면 모델이 없는 정보를 찾는다."""
    room, snapshots = await _fact_room(db_client, db_session, lane=lane)
    await _plant(db_session, room, snapshots[2], [_AUDITION, _FRIENDS])
    await _plant_scenes(db_session, room, snapshots[2])
    monkeypatch.setattr(settings, "memory_episodes_recall", True)
    monkeypatch.setattr(settings, "memory_facts_inject", False)
    _memory_scope_covers_gemini(monkeypatch)

    built = await _build(db_session, room, "밀알당 기억나?", lane=lane)

    assert RECALL_HEADER in built.prompt
    assert "밀알당에서 소금빵" in built.prompt
    assert HEADER.strip() not in built.prompt
    assert built.memory_facts == ()


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
    assert _section(built.prompt).endswith("\n- 유나 · 오디션: 겨울 (사용자의 말)")
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
    monkeypatch.setattr(memory_fact_section, "fact_rows_statement", lambda room_id, cursor: sa.text("SELECT 1/0"))
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


@pytest.mark.parametrize(
    ("user_label", "tail"),
    [
        pytest.param("나레이터 상대", " (사용자의 말)", id="speaker-is-the-set-label"),
        pytest.param("다른 라벨", " (나레이터 상대의 말)", id="speaker-is-not-the-set-label"),
    ],
)
def test_replay_turn_state_renders_fact_lines_with_the_set_line_label(user_label: str, tail: str) -> None:
    """리플레이의 턴 상태는 조립할 세트의 대화 줄 라벨로 사실 줄을 렌더한다 — 운영 조립이 그 라벨로 말한 주장을 사용자 주장으로
    읽으므로, 라벨을 넘기지 않으면 같은 턴이 다른 꼬리표로 다시 만들어진다. 라벨이 다른 세트에서는 그 표기가 인물 이름이다."""
    restored = RestoredTurn(
        turn=1,
        history=[],
        user_message=ChatMessage(),
        shortcut_entity_id=None,
        memory_note="",
        summary=None,
        recall_lines="",
        fact_rows=_rows(_claim(speaker="나레이터 상대")),
        stats_by_id={},
        stats_by_name={},
        sources={},
    )

    state = restored.turn_state({}, None, user_label=user_label)

    assert state.fact_lines == f"- 유나 · 오디션: 겨울{tail}"


# --- 지식 범위 필터 ---------------------------------------------------------------------------
# 아는 사람이 이번 장면(이번 사용자 메시지·직전 응답에 이름이 나온 인물, 사용자 제외)에 없는 비밀 행은 고르기 전에 뺀다. 경계
# 규칙 자체는 `test_chat_memory_knowledge.py` 가 보고, 여기서는 고르기와의 순서와 조립·SQL·실패 흡수를 본다.


def test_filter_runs_before_selection_so_the_next_row_takes_the_freed_room() -> None:
    """비밀 줄(100자)이 렌더 순서 맨 앞이면 150자 줄이 셋만 들어간다. 필터가 그 줄을 빼면 넷째 줄이 그 자리를 채운다 — 고른 뒤에
    빼면 셋만 남는다. 결과는 비밀 행을 처음부터 넣지 않고 고른 것과 같다."""
    head = "- 유나 · 비밀: "
    tail = " (유나·사용자만 앎)"
    secret = _fields("유나", "비밀", "가" * (100 - len(head) - len(tail)), known_by=["유나", "사용자"], importance=5)
    rows = _rows(secret, *_fillers(6))
    assert len(fact_line(rows[0])) == 100

    unfiltered = select_fact_rows(rows, query="", names=[], current_turn=TURN)
    filtered = select_fact_rows(rows, query="", names=[], current_turn=TURN, keep=lambda row: row is not rows[0])

    assert [row.attribute for row in unfiltered] == ["비밀", "취향0", "취향1", "취향2"]
    assert [row.attribute for row in filtered] == ["취향0", "취향1", "취향2", "취향3"]
    assert filtered == _select(rows[1:])


def test_filtered_latest_value_does_not_bring_back_an_older_value_of_the_same_key() -> None:
    """키의 지금 값이 비밀이라 빠지면 그 키는 통째로 빠진다 — 앞의 공개 값이 지금 값처럼 되살아나지 않는다."""
    rows = _rows(_fields("유나", "전학", "안 감"), _fields("유나", "전학", "다음 달에 감", known_by=["유나"]))
    assert select_fact_rows(rows, query="", names=[], current_turn=TURN, keep=lambda row: not row.known_by) == []


_SECRET = _fields("유나", "전학", "다음 달에 간다", known_by=["유나", "사용자"])
_SECRET_LINE = "- 유나 · 전학: 다음 달에 간다 (유나·사용자만 앎)"


def _filter_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "memory_knowledge_filter", True)
    _memory_scope_covers_gemini(monkeypatch)


async def _set_last_response(db_session: AsyncSession, room: Room, content: str) -> None:
    last = room.turns[max(room.turns)][1]
    await db_session.execute(sa.update(ChatMessage).where(ChatMessage.id == last.id).values(content=content))
    await db_session.commit()


@pytest.mark.parametrize("lane", ["story", "character"])
async def test_secret_drops_unless_someone_who_knows_is_in_the_scene(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, lane: PromptLane
) -> None:
    """프로필 이름 없는 방(사용자는 대화 줄 라벨 "사용자" 로 적힌다). 민수만 나온 턴에는 유나의 비밀이 빠지고 공개 관계는 남는다.
    이번 메시지나 직전 응답에 유나가 나오면 남는다. 필터를 끄면 지금처럼 늘 실린다."""
    room, snapshots = await _fact_room(db_client, db_session, lane=lane)
    await _plant(db_session, room, snapshots[2], [_SECRET, _FRIENDS])
    _facts_on(monkeypatch)
    _filter_on(monkeypatch)

    others = _section((await _build(db_session, room, "민수는 뭐 해?", lane=lane)).prompt)
    assert _SECRET_LINE not in others and "- 민수 → 지아: 소꿉친구" in others
    assert _SECRET_LINE in _section((await _build(db_session, room, "유나는 뭐 해?", lane=lane)).prompt)
    await _set_last_response(db_session, room, "유나가 고개를 들었다.")
    assert _SECRET_LINE in _section((await _build(db_session, room, "그래서?", lane=lane)).prompt)

    monkeypatch.setattr(settings, "memory_knowledge_filter", False)
    await _set_last_response(db_session, room, "바람이 분다.")
    assert _SECRET_LINE in _section((await _build(db_session, room, "민수는 뭐 해?", lane=lane)).prompt)


async def test_profile_name_is_the_user_not_a_scene_person(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """그 턴 대화 프로필 이름(하늘)이 사용자다 — 메시지에 하늘이 나와도 하늘만 아는 쪽으로는 비밀이 남지 않는다."""
    room, snapshots = await _fact_room(db_client, db_session)
    await _plant(db_session, room, snapshots[2], [_fields("유나", "전학", "다음 달에 간다", known_by=["유나", "하늘"])])
    _facts_on(monkeypatch)
    _filter_on(monkeypatch)
    state = InjectedTurnState(
        summary=await load_current_summary(db_session, room.room_id),
        memory_note="",
        stats={},
        persona=InjectedPersona(name="하늘", gender=None, description=""),
    )

    built = await _build(db_session, room, "하늘이는 민수랑 같이 있어", turn_state=state)
    assert HEADER not in built.prompt and built.memory_facts == ()
    kept = await _build(db_session, room, "하늘이는 유나랑 같이 있어", turn_state=state)
    assert "전학" in _section(kept.prompt)


async def test_name_only_inside_the_reply_dialogue_is_not_a_scene_person(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """필터를 켠 턴 — 직전 응답에서 유나가 대사 안에만 나오면 유나의 비밀이 빠지고, 서술에도 나오면 남는다."""
    room, snapshots = await _fact_room(db_client, db_session)
    await _plant(db_session, room, snapshots[2], [_SECRET, _FRIENDS])
    _facts_on(monkeypatch)
    _filter_on(monkeypatch)

    await _set_last_response(db_session, room, "“유나는 어디 있어?” 민수가 물었다.")
    assert _SECRET_LINE not in _section((await _build(db_session, room, "그래서?")).prompt)
    await _set_last_response(db_session, room, "“유나는 어디 있어?” 민수가 유나를 찾았다.")
    assert _SECRET_LINE in _section((await _build(db_session, room, "그래서?")).prompt)


async def test_scene_known_by_is_not_a_name_source_for_the_fact_section(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """장면 행의 아는 사람 칸은 사실 섹션의 장면 인물 출처가 아니다 — 장면 칸에 유나·지아를 채워도 필터를 켠 사실 섹션이 바이트까지
    같다(회상은 꺼 두어 사실 섹션만 본다)."""
    room, snapshots = await _fact_room(db_client, db_session)
    await _plant(db_session, room, snapshots[2], [_SECRET, _FRIENDS])
    await _plant_scenes(db_session, room, snapshots[2])
    _facts_on(monkeypatch)
    _filter_on(monkeypatch)
    before = await _build(db_session, room, "지아는 뭐 해?")

    await db_session.execute(
        sa.update(ChatMemoryEpisode)
        .where(ChatMemoryEpisode.chat_room_id == room.room_id)
        .values(known_by=["유나", "지아"])
    )
    await db_session.commit()
    after = await _build(db_session, room, "지아는 뭐 해?")

    assert _SECRET_LINE not in _section(before.prompt)
    assert after.prompt == before.prompt


async def _statements(db_session: AsyncSession, room: Room, user_content: str, *, lane: PromptLane = "story") -> int:
    with _count_queries() as count:
        await _build(db_session, room, user_content, lane=lane)
        return count()


@pytest.mark.parametrize("lane", ["story", "character"])
async def test_filter_adds_no_statements_with_or_without_a_secret(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, lane: PromptLane
) -> None:
    """필터는 읽은 사실 행만으로 판정하므로 켜도 SQL 문을 더하지 않는다 — 아는 사람이 정해진 행이 있든 없든, 스토리·캐릭터 방
    모두 꺼짐과 문 수가 같다. 판정은 승자 행의 아는 사람 원소가 장면에 나오는가뿐이고 그 원소는 이미 사실 행에서 이름 출처에
    들어 있어, 미디어 북 인물이나 작품 이름을 더 읽어도 판정이 바뀌지 않고 실패 지점만 는다."""
    room, snapshots = await _fact_room(db_client, db_session, lane=lane)
    await _plant(db_session, room, snapshots[2], [_FRIENDS])
    _facts_on(monkeypatch)

    async def off_and_on() -> tuple[int, int]:
        monkeypatch.setattr(settings, "memory_knowledge_filter", False)
        off = await _statements(db_session, room, "민수는 뭐 해?", lane=lane)
        _filter_on(monkeypatch)
        return off, await _statements(db_session, room, "민수는 뭐 해?", lane=lane)

    public_off, public_on = await off_and_on()
    assert public_on == public_off
    await _plant(db_session, room, snapshots[2], [_SECRET], start=1)
    secret_off, secret_on = await off_and_on()
    assert secret_on == secret_off


@pytest.mark.parametrize("lane", ["story", "character"])
async def test_filter_on_with_facts_off_keeps_prompt_and_statements(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, lane: PromptLane
) -> None:
    """사실 주입이 꺼져 있으면 필터를 켜도 생성 프롬프트가 바이트까지 같고, 이름 출처를 읽지 않아 SQL 문 수도 같다."""
    room, snapshots = await _fact_room(db_client, db_session, lane=lane)
    await _plant(db_session, room, snapshots[2], [_SECRET, _FRIENDS])
    with _count_queries() as count_off:
        off = await _build(db_session, room, "민수는 뭐 해?", lane=lane)
        statements_off = count_off()
    _filter_on(monkeypatch)
    with _count_queries() as count_on:
        on = await _build(db_session, room, "민수는 뭐 해?", lane=lane)
        statements_on = count_on()

    assert HEADER not in on.prompt
    assert on.prompt == off.prompt
    assert statements_on == statements_off


def test_production_env_turns_the_knowledge_filter_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """운영 env 는 필터 스위치를 넣어 켜 둔다 — 사실 주입이 꺼져 있어도 회상 가림의 장면 인물 판정이 대사 안 이름을 빼고 센다."""
    assert "MEMORY_KNOWLEDGE_FILTER" in PRODUCTION_ENV_NAMES
    assert load_production_env(monkeypatch).memory_knowledge_filter


# --- 이름 정확 조회 ------------------------------------------------------------------------------
# 장면 인물은 이번 사용자 메시지·직전 응답에 이름이 나온 방 인물(사용자 제외, `memory_knowledge.scene_people`)이다. 순수 함수
# 테스트는 장면 인물(정규형)을 직접 준다. 150자 줄 여섯(중요도 5)이 렌더 순서 앞에 서면 상시 몫은 첫 줄(150자)에서 멈춘다.

_MINSU = frozenset({"민수"})


def _scene_select(
    rows: list[ChatMemoryFact], scene: frozenset[str], query: str = "", **extra: Any
) -> list[ChatMemoryFact]:
    return select_fact_rows(rows, query=query, names=[], current_turn=TURN, scene=scene, **extra)


def test_exact_share_follows_the_constant_share_and_comes_before_relevance() -> None:
    """민수 줄(100자)과 등대 줄(449자)은 둘 다 렌더 순서 맨 끝이다. 장면에 민수가 없으면 등대가 관련으로 들어와 600자다.
    민수가 나오면 상시 첫 줄 뒤에 민수 줄이 먼저 들어오고(251자) 등대 줄은 701자로 넘쳐 빠진 채, 남은 자리를 렌더 순서로 채운다.
    정확 조회가 상시보다 앞이면 상시 몫이 첫 줄을 못 실어(100 + 1 + 150 > 210) 등대가 들어오고, 관련 뒤면 등대가 먼저 자리를
    차지한다 — 두 순서 모두 이 결과와 다르다."""
    named = _sized(10, 100, subject="민수", importance=1)
    lighthouse = _sized(11, 449, word="등대", importance=1)
    rows = _rows(named, lighthouse, *_fillers(6))

    without_name = _scene_select(rows, frozenset(), "등대 기억나?")
    assert [row.attribute for row in without_name] == ["취향0", lighthouse["attribute"]]
    picked = _scene_select(rows, _MINSU, "등대 기억나?")
    assert [row.attribute for row in picked] == ["취향0", "취향1", "취향2", named["attribute"]]


@pytest.mark.parametrize(
    ("spare", "pulled"),
    [pytest.param(0, True, id="exactly-at-the-share-end"), pytest.param(1, False, id="one-char-over")],
)
def test_exact_share_stops_at_its_end(spare: int, pulled: bool) -> None:
    """정확 조회 몫의 끝은 상한의 (상시 비율 + 정확 조회 비율)이다(상시 몫처럼 섹션 첫 줄부터 센 누적 글자). 상시 첫 줄 150자 +
    줄바꿈 뒤 민수 줄이 그 끝에 정확히 닿으면 실리고, 한 글자 넘으면 빠진다 — 남은 자리 채우기는 렌더 순서라 맨 끝의 민수 줄까지
    가지 못한다."""
    share_end = (
        memory_fact_section.CONSTANT_RATIO + memory_fact_section.EXACT_RATIO
    ) * memory_fact_section.RENDER_MAX_CHARS
    named = _sized(10, int(share_end) - 151 + spare, subject="민수", importance=1)
    rows = _rows(named, *_fillers(6))

    assert (named["value"] in _values(_scene_select(rows, _MINSU))) is pulled


def test_exact_share_stops_at_the_first_name_line_that_overflows() -> None:
    """정확 조회 몫도 다음 줄이 넘치면 그 자리에서 멈춘다. 상시 첫 줄 뒤 민수의 270자 줄은 몫 끝(420)을 한 글자 넘어 빠지고, 그 뒤의
    50자 민수 줄은 자리가 있어도 정확 조회로 싣지 않는다 — 남은 자리는 렌더 순서로 앞의 150자 줄들이 채운다."""
    long_line = _sized(10, 270, subject="민수", importance=2)
    short_line = _sized(11, 50, subject="민수", importance=1)
    rows = _rows(long_line, short_line, *_fillers(6))

    picked = _scene_select(rows, _MINSU)

    assert [row.attribute for row in picked] == ["취향0", "취향1", "취향2", "취향3"]


def test_protagonist_named_every_turn_still_leaves_room_for_a_relevant_row() -> None:
    """모든 행의 주어가 장면 인물(유나)인 방 — 정확 조회 몫이 상시 첫 줄 뒤 150자 한 줄(누적 301)에서 멈추고(다음 줄이면 452 >
    420), 그 뒤 관련 몫으로 등대 줄(100자)이 들어온다. 정확 조회가 상한 끝까지 채우면 150자 줄 넷(603)이 자리를 차지해 등대 줄이
    넘친다."""
    lighthouse = _sized(20, 100, word="등대", importance=1)
    rows = _rows(lighthouse, *_fillers(6))

    picked = _scene_select(rows, frozenset({"유나"}), "등대 기억나?")

    assert [row.attribute for row in picked] == ["취향0", "취향1", "취향2", "취향20"]


def test_exact_lookup_matches_the_subject_or_the_relation_target_only() -> None:
    """관계 150자 여섯(중요도 5)이 앞에 서면 지아 → 민수 관계는 렌더 순서로는 빠진다. 민수(대상)나 지아(주어)가 장면에 나오면
    들어온다. 값에 민수가 들어 있을 뿐인 유나의 사실은 이름이 나와도 정확 조회로 들어오지 않는다."""
    fillers = [
        _fields(
            "유나", f"인물{i}", f"관계{i}".ljust(150 - len(f"- 유나 → 인물{i}: "), "가"), kind="relation", importance=5
        )
        for i in reversed(range(6))
    ]
    target = _fields("지아", "민수", "짝사랑", kind="relation", importance=1)
    mention = _fields("유나", "친구", "민수랑 제일 친함", importance=1)
    rows = _rows(target, mention, *fillers)
    assert len(fact_line(rows[2])) == 150

    assert target["value"] not in _values(_scene_select(rows, frozenset()))
    for scene in (_MINSU, frozenset({"지아"})):
        picked = _values(_scene_select(rows, scene))
        assert target["value"] in picked and mention["value"] not in picked


def test_exact_lookup_never_brings_back_a_row_the_filter_dropped() -> None:
    """민수의 비밀(지아만 앎)은 민수가 장면에 나와도 필터가 빼면 정확 조회로 돌아오지 않는다 — 정확 조회는 필터를 지난 행
    사이에서만 고른다. 같은 장면의 민수 공개 줄은 들어오고, 결과는 비밀 행 없이 고른 것과 같다."""
    secret = _fields("민수", "비밀", "지아한테만 말한 고백", known_by=["지아"], importance=1)
    named = _sized(10, 100, subject="민수", importance=1)
    rows = _rows(secret, named, *_fillers(6))

    picked = _scene_select(rows, _MINSU, keep=lambda row: not row.known_by)

    assert secret["value"] not in _values(picked)
    assert named["value"] in _values(picked)
    assert picked == _scene_select(rows[1:], _MINSU)


async def test_name_in_the_previous_response_pulls_rows_up_to_the_computed_maximum(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """직전 응답에 민수가 나오면(이번 메시지 "그래서?" 에는 이름도 관련 명사도 없다) 렌더 순서로는 빠지는 민수 줄(247자)이
    상시 첫 줄 뒤에 들어오고, 남은 자리를 150자 줄 둘이 채워 정확히 700자 — 섹션은 계산한 최대(머리글 + 700)에 닿고 넘지
    않는다. 정확 조회가 없으면 150자 넷(603자)이다."""
    _, sections = await load_active_prompt_set(db_session, lane="story")
    [body] = [section.body for section in sections if section.slot == "memory_facts"]
    maximum = len(body.replace("{memory_fact_lines}", "")) + memory_fact_section.RENDER_MAX_CHARS
    room, snapshots = await _fact_room(db_client, db_session)
    named = _sized(10, 247, subject="민수", importance=1)
    await _plant(db_session, room, snapshots[2], [named, *_fillers(6)])
    await _set_last_response(db_session, room, "민수가 웃었다.")
    _facts_on(monkeypatch)

    built = await _build(db_session, room, "그래서?")

    section = _section(built.prompt)
    assert named["value"] in section
    assert len(built.memory_facts) == 4
    assert len(section) == maximum


async def test_room_exact_lookup_runs_after_the_knowledge_filter(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """필터를 켠 방에서 직전 응답에 민수만 나오면 민수의 공개 줄은 정확 조회로 들어오고, 지아만 아는 민수의 비밀은 이름이
    나와도 빠진다."""
    room, snapshots = await _fact_room(db_client, db_session)
    secret = _fields("민수", "비밀", "지아한테만 말한 고백", known_by=["지아"], importance=1)
    named = _sized(10, 100, subject="민수", importance=1)
    await _plant(db_session, room, snapshots[2], [secret, named, *_fillers(6)])
    await _set_last_response(db_session, room, "민수가 웃었다.")
    _facts_on(monkeypatch)
    _filter_on(monkeypatch)

    section = _section((await _build(db_session, room, "그래서?")).prompt)

    assert named["value"] in section
    assert secret["value"] not in section


async def test_the_user_is_not_looked_up_by_name(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """그 턴 대화 프로필 이름(하늘)은 사용자라 직전 응답에 나와도 하늘의 줄을 정확 조회로 끌어오지 않는다(필터를 끈 방에서도).
    프로필이 없는 턴이면 하늘은 방의 한 인물이라 끌어온다."""
    room, snapshots = await _fact_room(db_client, db_session)
    named = _sized(10, 100, subject="하늘", importance=1)
    await _plant(db_session, room, snapshots[2], [named, *_fillers(6)])
    await _set_last_response(db_session, room, "하늘이 웃었다.")
    _facts_on(monkeypatch)
    summary = await load_current_summary(db_session, room.room_id)
    as_user = InjectedTurnState(
        summary=summary, memory_note="", stats={}, persona=InjectedPersona(name="하늘", gender=None, description="")
    )
    no_profile = InjectedTurnState(summary=summary, memory_note="", stats={}, persona=None)

    assert named["value"] not in _section((await _build(db_session, room, "그래서?", turn_state=as_user)).prompt)
    assert named["value"] in _section((await _build(db_session, room, "그래서?", turn_state=no_profile)).prompt)


# --- 임베딩 관련 몫(RRF) ------------------------------------------------------------------------
# 거리는 호출부가 거리 상한으로 거른 값이다. 순수 함수 테스트는 행에 id 를 직접 준다(세션 없이 만든 행은 id 가 없다).


def _with_ids(rows: list[ChatMemoryFact]) -> list[ChatMemoryFact]:
    for row in rows:
        row.id = uuid.uuid4()
    return rows


def test_vector_neighbour_enters_the_relevant_share_like_a_noun_hit() -> None:
    """질의와 명사가 겹치지 않아도 벡터 이웃은 관련 몫으로 들어온다 — 등대를 꺼냈을 때와 같은 결과다. 벡터 쪽이 비면 명사 단독과
    같다."""
    rows = _with_ids(_rows(_LIGHTHOUSE, *_fillers(6)))

    by_vector = select_fact_rows(rows, query="", names=[], current_turn=TURN, distances={rows[0].id: 0.1})

    assert by_vector == _select(rows, "등대 기억나?")
    assert select_fact_rows(rows, query="", names=[], current_turn=TURN, distances={}) == _select(rows)


def test_noun_and_vector_hits_compete_for_the_relevant_room_noun_first_on_a_tie() -> None:
    """상시 한 줄 뒤 관련 몫에 400자 줄이 하나만 들어간다. 명사 1위(등대)와 벡터 1위(수국)가 1/61 로 같으면 명사 쪽이 들어간다 —
    관련 몫 순서가 두 목록의 RRF 라 벡터 목록만으로 고르지 않는다. 등대 줄이 벡터로도 가까우면(두 목록 합) 같은 결과다."""
    lighthouse = _sized(20, 400, word="등대", importance=1)
    garden = _sized(21, 400, word="수국", importance=1)
    rows = _with_ids(_rows(lighthouse, garden, *_fillers(6)))

    picked = select_fact_rows(rows, query="등대 기억나?", names=[], current_turn=TURN, distances={rows[1].id: 0.1})

    assert [row.attribute for row in picked] == ["취향0", lighthouse["attribute"]]


def test_vector_rank_never_brings_back_a_row_the_filter_dropped() -> None:
    """필터가 뺀 비밀 행이 질의와 가장 가까워도 관련 몫으로 되돌아오지 않는다 — 거리 순위는 필터를 지난 행 사이에서만 매긴다.
    결과는 비밀 행 없이 고른 것과 같다."""
    secret = _fields("유나", "비밀", "등대 아래 묻은 편지", known_by=["유나"], importance=1)
    rows = _with_ids(_rows(secret, _LIGHTHOUSE, *_fillers(6)))

    picked = select_fact_rows(
        rows,
        query="",
        names=[],
        current_turn=TURN,
        keep=lambda row: not row.known_by,
        distances={rows[0].id: 0.0, rows[1].id: 0.3},
    )

    assert secret["value"] not in _values(picked)
    assert _LIGHTHOUSE["value"] in _values(picked)
    assert picked == select_fact_rows(rows[1:], query="", names=[], current_turn=TURN, distances={rows[1].id: 0.3})


async def test_fact_section_uses_the_turn_query_embedding_and_its_model_and_dims(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """회상과 사실 섹션이 둘 다 켜져 있어도 질의 임베딩은 한 번이다. 질의와 가까운 등대 행이 명사 겹침 없이 사실 섹션에 들어오고,
    같은 모델의 다른 차원 행이 섞여도 거리 읽기가 실패하지 않는다(섞이면 명사 단독으로 떨어져 등대 행이 빠진다). 다른 모델로만
    가까운 사물함 행은 들어오지 않는다 — 그 행은 렌더 순서로는 빠지는 자리라, 모델로 거르지 않으면 관련 몫으로 들어온다."""
    room, snapshots = await _fact_room(db_client, db_session)
    ids = await _plant(db_session, room, snapshots[2], [_LIGHTHOUSE, *_fillers(6), _LOCKER])
    db_session.add_all(
        [
            _make_memory_embedding(
                room.room_id, fact_id=ids[0], model="voyage-test", dims=3, embedding=[1.0, 0.5, 0.5]
            ),
            _make_memory_embedding(room.room_id, fact_id=ids[1], model="voyage-test", dims=2, embedding=[1.0, 0.5]),
            _make_memory_embedding(
                room.room_id, fact_id=ids[2], model="other-model", dims=3, embedding=[1.0, 0.5, 0.5]
            ),
            _make_memory_embedding(
                room.room_id, fact_id=ids[-1], model="other-model", dims=3, embedding=[1.0, 0.5, 0.5]
            ),
        ]
    )
    await db_session.commit()
    _facts_on(monkeypatch)
    monkeypatch.setattr(settings, "memory_episodes_recall", True)
    monkeypatch.setattr(settings, "memory_embed_recall", True)
    stub = VoyageStub()
    client = VoyageEmbeddingClient(
        api_key="test-key", model="voyage-test", dims=3, transport=stub.transport(), retry_delays=(0.0, 0.0)
    )

    noun_only = await _build(db_session, room, "오늘 날씨 좋다")
    chat_room = await db_session.get(ChatRoom, room.room_id)
    assert chat_room is not None
    setup = await _resolve_starting_setup(db_session, chat_room)
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story")
    history = await _room_messages(db_session, room.room_id)
    built = await build_room_prompt(
        db_session, chat_room, setup, history, "오늘 날씨 좋다", None, prompt_set, sections, embedding_client=client
    )

    assert _LIGHTHOUSE["value"] not in _section(noun_only.prompt)
    assert _LIGHTHOUSE["value"] in _section(built.prompt)
    assert _LOCKER["value"] not in _section(built.prompt)
    assert str(ids[0]) in [entry["factId"] for entry in built.memory_facts]
    assert len(stub.bodies) == 1


async def test_fact_vector_side_never_reaches_past_the_turn_cursor(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """지난 턴을 그때의 요약(턴 4 커서)으로 다시 조립하면, 그 뒤에 접힌 턴 6 스냅샷의 사실은 질의와 가장 가까워도 싣지 않는다."""
    room, snapshots = await _fact_room(db_client, db_session)
    await _plant(db_session, room, snapshots[2], [_LIGHTHOUSE, *_fillers(6)])
    [later] = await _plant(db_session, room, snapshots[6], [_LOCKER], start=10)
    db_session.add(
        _make_memory_embedding(room.room_id, fact_id=later, model="voyage-test", dims=3, embedding=[1.0, 0.5, 0.5])
    )
    await db_session.commit()
    _facts_on(monkeypatch)
    monkeypatch.setattr(settings, "memory_embed_recall", True)
    stub = VoyageStub()
    client = VoyageEmbeddingClient(
        api_key="test-key", model="voyage-test", dims=3, transport=stub.transport(), retry_delays=(0.0, 0.0)
    )
    cursor = room.turns[4][1]
    then = InjectedTurnState(
        summary=CurrentSummary(cursor=(cursor.created_at, cursor.id), text="턴 4 까지의 요약"),
        memory_note="",
        stats={},
        persona=None,
    )
    chat_room = await db_session.get(ChatRoom, room.room_id)
    assert chat_room is not None
    setup = await _resolve_starting_setup(db_session, chat_room)
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story")
    history = await _room_messages(db_session, room.room_id)

    built = await build_room_prompt(
        db_session,
        chat_room,
        setup,
        history,
        "오늘 날씨 좋다",
        None,
        prompt_set,
        sections,
        turn_state=then,
        embedding_client=client,
    )

    assert len(stub.bodies) == 1
    assert _LOCKER["value"] not in _section(built.prompt)


# --- 인물의 확인되지 않은 말 -------------------------------------------------------------------
# 확인되지 않은 주장(`claimed`) 중 사용자 꼬리표가 붙지 않는 행(인물·서술이 말로만 전한 것)은 섹션에 싣지 않는다 — 꼬리표가
# 있어도 생성 모델이 사실로 굳힌다. 키별 최신 뒤에서 빼므로 그런 행이 키의 지금 값이면 그 키가 통째로 빠지고 옛 값이 되살아나지
# 않는다. 지식 범위 필터와 별도 판정이라 필터가 꺼져 있어도 걸린다. 확인된 행·반증 행·사용자 주장은 그대로 싣는다.

_HANEUL = "하늘"


def _claim(value: str = "겨울", **extra: Any) -> dict[str, Any]:
    return _fields("유나", "오디션", value, truth_status="claimed", **{"asserted_by": "character", **extra})


def test_character_claim_as_the_latest_value_drops_its_key_without_reviving_the_older_value() -> None:
    """앞에 확인된 겨울, 뒤에 민수가 말한 봄 — 그 키는 섹션에서 빠진다. 앞 값을 지금 값처럼 싣지 않는다."""
    rows = _rows(_fields("유나", "오디션", "겨울"), _claim("봄", speaker="민수"), _FRIENDS)

    assert _values(_select(rows)) == ["소꿉친구"]


@pytest.mark.parametrize(
    ("fields", "line"),
    [
        pytest.param(_claim(speaker="민수"), None, id="claimed-by-a-named-character"),
        pytest.param(_claim(), None, id="claimed-by-an-unnamed-character"),
        pytest.param(_claim(asserted_by="narration"), None, id="claimed-in-narration"),
        pytest.param(_claim(asserted_by="user"), "- 유나 · 오디션: 겨울 (사용자의 말)", id="claimed-by-the-user"),
        pytest.param(
            _claim(speaker=" 하늘 "), "- 유나 · 오디션: 겨울 (사용자의 말)", id="claimed-under-the-user-name"
        ),
        pytest.param(
            _fields("유나", "오디션", "겨울", asserted_by="character", speaker="민수"),
            "- 유나 · 오디션: 겨울",
            id="confirmed-by-a-character",
        ),
        pytest.param(
            _fields("유나", "오디션", "겨울", truth_status="disproved", asserted_by="character", speaker="민수"),
            "- (사실 아님으로 밝혀짐) 유나 · 오디션: 겨울",
            id="disproved-by-a-character",
        ),
    ],
)
def test_only_unverified_claims_without_the_user_tail_drop(fields: dict[str, Any], line: str | None) -> None:
    """빠지는지는 줄의 꼬리표와 같은 판정이다 — 사용자 꼬리표가 붙는 주장(사용자가 내놓았거나 사용자의 이야기 속 이름으로 말한
    것)은 남고, 남은 줄은 꼬리표가 그대로다."""
    picked = select_fact_rows(_rows(fields), query="", names=[], current_turn=TURN, user_name=_HANEUL)

    assert [fact_line(row, user_name=_HANEUL) for row in picked] == ([line] if line else [])


def test_exact_lookup_and_the_vector_rank_never_bring_back_a_character_claim() -> None:
    """민수가 장면에 나와도 민수가 주어인 인물 주장은 정확 조회로 들어오지 않고, 질의와 가장 가까워도 관련 몫으로 들어오지
    않는다 — 네 몫 모두 그 행을 뺀 뒤에서 고른다. 결과는 그 행 없이 고른 것과 같다."""
    claim = _sized(10, 100, subject="민수", importance=1) | {"truth_status": "claimed", "asserted_by": "character"}
    rows = _with_ids(_rows(claim, _LIGHTHOUSE, *_fillers(6)))
    distances = {rows[0].id: 0.0, rows[1].id: 0.3}

    picked = _scene_select(rows, _MINSU, distances=distances)

    assert claim["value"] not in _values(picked)
    assert picked == _scene_select(rows[1:], _MINSU, distances={rows[1].id: 0.3})


@pytest.mark.parametrize(
    ("knowledge_filter", "secret"),
    [
        pytest.param(False, False, id="filter-off"),
        pytest.param(True, False, id="filter-on-without-known-by-rows"),
        pytest.param(True, True, id="filter-on-with-a-secret"),
    ],
)
async def test_character_claims_drop_from_the_room_section_whatever_the_knowledge_filter(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    knowledge_filter: bool,
    secret: bool,
) -> None:
    """사실 주입이 켜진 턴이면 지식 범위 필터가 꺼져 있어도, 켜졌지만 아는 사람이 정해진 행이 없어 필터 판정이 없어도 인물 주장은
    빠진다."""
    room, snapshots = await _fact_room(db_client, db_session)
    planted = [_claim(speaker="민수"), _FRIENDS]
    if secret:
        planted.append(_fields("민수", "비밀", "전학", known_by=["민수"]))
    await _plant(db_session, room, snapshots[2], planted)
    _facts_on(monkeypatch)
    monkeypatch.setattr(settings, "memory_knowledge_filter", knowledge_filter)

    built = await _build(db_session, room, "민수야 오디션 언제야?")

    lines = _section(built.prompt).splitlines()
    assert "- 민수 → 지아: 소꿉친구" in lines
    assert not any("오디션" in line for line in lines)


async def test_replay_renders_a_recorded_character_claim_as_it_was(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """리플레이는 기록한 행을 고르지 않고 돌려준다 — 이 거름이 생기기 전 턴에 실린 인물 주장도 그때처럼 그 인물의 말로 렌더한다."""
    room, snapshots = await _fact_room(db_client, db_session)
    [claim_id] = await _plant(db_session, room, snapshots[2], [_claim(speaker="민수")])

    rows = await memory_fact_section.fact_rows_from_record(db_session, [{"factId": str(claim_id)}])

    assert memory_fact_section.fact_lines(rows, user_name=None) == "- 유나 · 오디션: 겨울 (민수의 말)"


# --- 대화 프로필 이름이 없는 방의 사용자 말 -----------------------------------------------------------
# 프로필 이름이 없는 방에서 사실 추출은 말한 사람 칸에 사용자를 대화 줄 라벨이나 `{{user}}` 대체어나 추출 지시문 낱말로 적는다 —
# 요약·장면 인물이 사용자로 보는 표기와 같다. 그 표기로 적힌 주장도 사용자 주장이라 사용자 꼬리표를 달고 섹션에 남아야 한다.
# 프로필 이름만 견주면 인물 주장으로 읽혀 섹션에서 빠진다.


async def _unnamed_section(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, speaker: str
) -> list[str]:
    """프로필 이름이 없는 방에 `speaker` 가 말한 오디션 주장과 확인된 관계 한 줄을 심고 조립한 사실 섹션의 줄."""
    room, snapshots = await _fact_room(db_client, db_session)
    await _plant(db_session, room, snapshots[2], [_claim(speaker=speaker), _FRIENDS])
    _facts_on(monkeypatch)
    summary = await load_current_summary(db_session, room.room_id)
    state = InjectedTurnState(summary=summary, memory_note="", stats={}, persona=None)
    built = await _build(db_session, room, "오디션 언제야?", turn_state=state)
    return _section(built.prompt).splitlines()


async def _user_label(db_session: AsyncSession) -> str:
    """조립이 쓰는 세트(스토리 레인·gemini)의 대화 줄 라벨."""
    prompt_set, _ = await load_active_prompt_set(db_session, lane="story", model="gemini")
    return prompt_set.user_label


@pytest.mark.parametrize("form", ["label", "fallback", "instruction"])
async def test_unnamed_room_keeps_a_claim_spoken_under_a_user_form_with_the_user_tail(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, form: str
) -> None:
    """프로필 이름이 없는 방에서 추출이 사용자를 대화 줄 라벨·`{{user}}` 대체어·지시문 낱말로 적은 주장은 사용자가 한 말이다 —
    섹션에 남고 사용자 꼬리표가 붙는다. 표기는 사실 키와 같은 정규화로 견주므로 앞뒤 공백이 붙어도 같다."""
    speaker = {
        "label": await _user_label(db_session),
        "fallback": FALLBACK_USER_NAME,
        "instruction": USER_INSTRUCTION_WORD,
    }[form]

    lines = await _unnamed_section(db_client, db_session, monkeypatch, f" {speaker} ")

    assert "- 유나 · 오디션: 겨울 (사용자의 말)" in lines


@pytest.mark.parametrize(
    ("speaker", "line"),
    [
        pytest.param(_HANEUL, "- 유나 · 오디션: 겨울 (사용자의 말)", id="spoken-under-the-profile-name"),
        pytest.param("민수", None, id="spoken-by-another-character"),
    ],
)
async def test_named_room_still_reads_the_speaker_against_the_profile_name(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    speaker: str,
    line: str | None,
) -> None:
    """프로필 이름이 있는 방은 그대로다 — 그 이름이 말한 주장은 사용자 꼬리표로 남고, 다른 인물이 말한 주장은 빠진다."""
    room, snapshots = await _fact_room(db_client, db_session)
    await _plant(db_session, room, snapshots[2], [_claim(speaker=speaker), _FRIENDS])
    _facts_on(monkeypatch)
    summary = await load_current_summary(db_session, room.room_id)
    persona = InjectedPersona(name=_HANEUL, gender=None, description="")
    state = InjectedTurnState(summary=summary, memory_note="", stats={}, persona=persona)

    built = await _build(db_session, room, "오디션 언제야?", turn_state=state)

    lines = _section(built.prompt).splitlines()
    assert "- 민수 → 지아: 소꿉친구" in lines
    assert [x for x in lines if "오디션" in x] == ([line] if line else [])


async def test_named_room_also_reads_a_claim_spoken_under_the_line_label_as_the_user(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """프로필 이름이 있는 방에서도 추출은 사용자 줄을 대화 줄 라벨로 적을 수 있다 — 그 표기로 말한 주장도 사용자 꼬리표로
    남는다. 요약 접기·장면 인물과 같은 사용자 표기로 판정한다."""
    room, snapshots = await _fact_room(db_client, db_session)
    await _plant(db_session, room, snapshots[2], [_claim(speaker=await _user_label(db_session)), _FRIENDS])
    _facts_on(monkeypatch)
    summary = await load_current_summary(db_session, room.room_id)
    persona = InjectedPersona(name=_HANEUL, gender=None, description="")
    state = InjectedTurnState(summary=summary, memory_note="", stats={}, persona=persona)

    built = await _build(db_session, room, "오디션 언제야?", turn_state=state)

    assert "- 유나 · 오디션: 겨울 (사용자의 말)" in _section(built.prompt).splitlines()


async def test_unnamed_room_still_drops_a_character_whose_name_only_contains_the_user_label(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """사용자 표기는 말한 사람 칸 전체와 견준다 — 이름에 라벨이 들어 있을 뿐인 인물(라벨 뒤에 낱말이 붙은 이름)은 사용자가
    아니라 그 인물이고, 그 인물의 확인되지 않은 주장은 섹션에서 빠진다."""
    label = await _user_label(db_session)

    lines = await _unnamed_section(db_client, db_session, monkeypatch, f"{label}의 친구")

    assert "- 민수 → 지아: 소꿉친구" in lines
    assert not any("오디션" in x for x in lines)


# --- 기억 사용 범위(글쓰기 모델) ----------------------------------------------------------------

_GENERATION_MEMORY_SWITCHES = (
    "memory_episodes_recall",
    "memory_facts_inject",
    "memory_knowledge_filter",
    "memory_embed_recall",
    "memory_summary_secret_marking",
)


def _memory_switches(monkeypatch: pytest.MonkeyPatch, on: bool) -> None:
    for name in _GENERATION_MEMORY_SWITCHES:
        monkeypatch.setattr(settings, name, on)


async def _memory_room(db_client: httpx.AsyncClient, db_session: AsyncSession, lane: PromptLane) -> Room:
    """사실 행과 "밀알당" 장면이 있는 방 — 스위치가 동작하면 사실 섹션과 회상 섹션이 둘 다 실린다."""
    room, snapshots = await _fact_room(db_client, db_session, lane=lane)
    await _plant(db_session, room, snapshots[2], [_AUDITION, _FRIENDS])
    await _plant_scenes(db_session, room, snapshots[2])
    return room


async def _built_and_statements(
    db_session: AsyncSession, room: Room, *, lane: PromptLane, model: ChatModelId, stub: VoyageStub
) -> tuple[GenerationPrompt, int]:
    client = VoyageEmbeddingClient(
        api_key="test-key", model="voyage-test", dims=3, transport=stub.transport(), retry_delays=(0.0, 0.0)
    )
    with _count_queries() as count:
        built = await _build(db_session, room, "밀알당 기억나?", lane=lane, model=model, embedding_client=client)
        return built, count()


@pytest.mark.parametrize("lane", ["story", "character"])
@pytest.mark.parametrize("model", ["gemini", "sonnet"])
async def test_memory_switches_do_nothing_in_a_room_written_by_a_model_outside_the_scope(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    lane: PromptLane,
    model: ChatModelId,
) -> None:
    """기본 범위(Opus 방뿐)에서 Gemini·Sonnet 방은 기억 스위치를 다 켜도 다 끈 턴과 프롬프트 바이트·SQL 문 수가 같고, 질의 임베딩도
    부르지 않는다 — 측정하지 않은 모델 방에 기억이 실려 나가지 않게."""
    monkeypatch.setattr(settings, "memory_model_scope", [("story", "opus"), ("character", "opus")])
    room = await _memory_room(db_client, db_session, lane)
    stub = VoyageStub()

    _memory_switches(monkeypatch, False)
    off, off_statements = await _built_and_statements(db_session, room, lane=lane, model=model, stub=stub)
    _memory_switches(monkeypatch, True)
    on, on_statements = await _built_and_statements(db_session, room, lane=lane, model=model, stub=stub)

    assert on.prompt == off.prompt
    assert HEADER not in on.prompt and RECALL_HEADER not in on.prompt
    assert (on.memory_facts, on.memory_recall) == ((), ())
    assert on_statements == off_statements
    assert stub.bodies == []


@pytest.mark.parametrize("lane", ["story", "character"])
async def test_memory_switches_work_in_an_opus_room_under_the_default_scope(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, lane: PromptLane
) -> None:
    """같은 방을 Opus 세트로 조립하면 기본 범위 안이라 사실 섹션과 회상 섹션이 실리고 질의 임베딩을 한 번 부른다."""
    monkeypatch.setattr(settings, "memory_model_scope", [("story", "opus"), ("character", "opus")])
    room = await _memory_room(db_client, db_session, lane)
    stub = VoyageStub()
    _memory_switches(monkeypatch, True)

    built, _ = await _built_and_statements(db_session, room, lane=lane, model="opus", stub=stub)

    assert HEADER in built.prompt and RECALL_HEADER in built.prompt
    assert "- 민수 → 지아: 소꿉친구" in _section(built.prompt)
    assert len(stub.bodies) == 1


@pytest.mark.parametrize("lane", ["story", "character"])
async def test_an_opus_room_builds_the_same_prompt_as_when_every_writing_model_is_in_the_scope(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, lane: PromptLane
) -> None:
    """범위 제한이 없던 코드는 모든 글쓰기 모델이 범위 안인 것과 같다. 기본 범위의 Opus 방은 기억 스위치를 다 켰을 때 그 넓은
    범위로 조립한 턴과 프롬프트 바이트·SQL 문 수·질의 임베딩 호출 수가 같다 — 범위 제한이 Opus 방의 프롬프트를 바꾸지 않는다.
    스위치를 끈 턴과는 달라야 기능이 실제로 켜진 채 비교한 것이다."""
    room = await _memory_room(db_client, db_session, lane)

    async def _build_under(scope: list[tuple[str, str]], *, on: bool) -> tuple[GenerationPrompt, int, int]:
        monkeypatch.setattr(settings, "memory_model_scope", scope)
        _memory_switches(monkeypatch, on)
        stub = VoyageStub()
        built, statements = await _built_and_statements(db_session, room, lane=lane, model="opus", stub=stub)
        return built, statements, len(stub.bodies)

    default_scope = [("story", "opus"), ("character", "opus")]
    every_model = [(each_lane, model) for each_lane in ("story", "character") for model in ("gemini", "sonnet", "opus")]
    scoped, scoped_statements, scoped_embeds = await _build_under(default_scope, on=True)
    unscoped, unscoped_statements, unscoped_embeds = await _build_under(every_model, on=True)
    switched_off, _, _ = await _build_under(default_scope, on=False)

    assert scoped.prompt == unscoped.prompt
    assert (scoped.memory_facts, scoped.memory_recall) == (unscoped.memory_facts, unscoped.memory_recall)
    assert scoped_statements == unscoped_statements
    assert scoped_embeds == unscoped_embeds == 1
    assert scoped.prompt != switched_off.prompt
    assert HEADER in scoped.prompt and RECALL_HEADER in scoped.prompt


async def test_a_lane_scoped_entry_leaves_the_other_lane_of_the_same_model_out(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """범위가 스토리 Opus 방뿐이면 캐릭터 Opus 방은 스위치를 다 켜도 다 끈 턴과 같다."""
    monkeypatch.setattr(settings, "memory_model_scope", [("story", "opus")])
    room = await _memory_room(db_client, db_session, "character")
    stub = VoyageStub()

    _memory_switches(monkeypatch, False)
    off, off_statements = await _built_and_statements(db_session, room, lane="character", model="opus", stub=stub)
    _memory_switches(monkeypatch, True)
    on, on_statements = await _built_and_statements(db_session, room, lane="character", model="opus", stub=stub)

    assert on.prompt == off.prompt
    assert on_statements == off_statements
    assert stub.bodies == []


async def test_injected_memory_lines_are_dropped_outside_the_scope(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """지난 턴을 다시 조립하는 측정 도구가 회상·사실 줄을 주입해도, 범위 밖 방이면 스위치를 끈 턴처럼 싣지 않는다."""
    monkeypatch.setattr(settings, "memory_model_scope", [("story", "opus"), ("character", "opus")])
    room = await _memory_room(db_client, db_session, "story")
    chat_room = await db_session.get(ChatRoom, room.room_id)
    assert chat_room is not None
    summary = await load_current_summary(db_session, room.room_id)
    assert summary is not None
    state = InjectedTurnState(
        summary=summary,
        memory_note="",
        stats={},
        persona=None,
        recall_lines="- 주입한 회상 줄",
        fact_lines="- 주입한 사실 줄",
    )
    _memory_switches(monkeypatch, True)

    outside = await _build(db_session, room, "밀알당 기억나?", model="gemini", turn_state=state)
    inside = await _build(db_session, room, "밀알당 기억나?", model="opus", turn_state=state)

    assert "주입한" not in outside.prompt
    assert "- 주입한 회상 줄" in inside.prompt and "- 주입한 사실 줄" in inside.prompt
