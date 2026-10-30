"""턴 기록(`chat_turns`)을 쓰는 자리 — 방의 턴이 응답과 같은 커밋에 기록 한 행을 남기는지, 재생성이 어떤 값을 이어받는지.

규칙(결과를 보기 전에 적었다):
- 보내기·수정은 턴마다 한 행. 이번 턴의 모델·차감·LLM 호출, 이 턴에 쓴 스탯의 `[before, after]`, 도달한 엔딩, 보내기의
  단축어를 싣는다.
- 재생성은 대체되는 응답에 기록이 있을 때만 한 행. 모델·차감·LLM 호출은 이 재생성의 것이고, `turn_number`·`stat_changes`·
  `ending_entity_id`·`shortcut_entity_id` 는 대체되는 기록의 값 그대로다. 재생성은 스탯을 다시 판정하지 않으므로 방에 남아
  있는 스탯 효과는 원 턴의 것이고, 다음 재생성이 그 효과를 되돌릴 근거가 이 기록뿐이라서다. 대체되는 응답에 기록이 없으면
  (기록을 쓰기 전에 보낸 턴) 아무것도 쓰지 않는다 — 빈 효과로 쓰면 "원 턴이 실제로 아무것도 안 바꿨다"와 구별되지 않는다.
- 미리보기는 방이 없어 쓰지 않는다.
- 단계별 배정 스냅샷(`stage_routes`)은 그 레인의 단계마다 한 칸이다(스토리 8, 캐릭터 5). 배정 표가 비면 생성은 출처 `room`(방
  모델·그 세트), 나머지는 출처 `env`(그 단계의 모델 설정 이름과 그 모델의 세트)로 채운다. 재생성도 이 재생성에서 새로 푼 값이다
  (대체되는 기록에서 물려받지 않는다).

LLM 호출 칸은 공급자 구현이 호출 컨텍스트의 사용량 목록에 더한 것이다. 여기서는 가짜 LLM 이 공급자 대신 그 목록에 더해,
턴이 생성·판정 호출 전부에 같은 목록을 넘기는지를 본다. 공급자 구현이 실제로 더하는지는 아래 공급자 절이 SDK 경계만 가짜로
두고 따로 본다.

생성 칸에는 처음으로 글이 든 델타가 온 때까지의 지연 둘(정수 ms)이 붙는다. `firstTokenMs` 는 턴을 시작한 때(생성
프롬프트 조립·질의 임베딩 전)부터, `streamFirstTokenMs` 는 생성 스트림을 연 때부터다. 기억 기능을 켜서 늘어나는 지연은
조립·질의 임베딩이라 스트림을 열기 전에 생기므로, 앞의 값으로 그 증가분을 보고 뒤의 값으로 생성 호출(공급자 왕복) 쪽
지연과 가른다.
판정·질의 임베딩 칸에는 붙지 않는다. 글이 든 델타가 하나도 없이 끝난 생성은 잴 첫 글자가 없으므로 둘 다 싣지 않는다.
시각은 턴 엔진의 단조 시계를 가짜로 바꿔 정한다 — 생성 프롬프트 조립과 가짜 LLM 이 각자 정해진 만큼 시계를 옮겨, 두 값이
늘 다르게 나온다(시작점을 잘못 잡으면 값으로 드러난다)."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat import router as chat_router
from api.chat import turn_engine, turn_prompt
from api.chat.prompt_builder import load_active_prompt_set
from api.chat.prompt_stages import RoutingLane
from api.chat.prompt_builder import (
    EndingJudgmentResult,
    ImageMatchJudgmentResult,
    MemorySummaryResult,
    StatRuleJudgmentResult,
)
from api.core import clover
from api.core.config import settings
from api.db.models import ChatMessage, ChatMessageRole, ChatRoom, Ending, StartingSetup, StatDef
from api.db.models.chat import ChatTurn
from api.db.models.clover import CloverLedger
from api.db.models.story import Shortcut
from api.llm import anthropic_api
from api.llm.anthropic_api import AnthropicLLMClient
from api.llm.chat_models import ChatModelId, backend_model_id
from api.llm.client import CallUsage, LLMCallContext, LLMClient, LLMClientError
from factories import (
    _add_named_media_cell,
    _add_room_situational_image,
    _FakeProviderSdks,
    _clear_llm_override,
    _login_as,
    _make_chat_turn,
    _make_paying_user,
    _make_user_with_clover_lot,
    _open_room,
    _override_llm_client,
    _parse_sse_events,
    _preview_character_payload,
)


class _FakeClock:
    """턴 엔진의 단조 시계 대신. 값은 가짜 LLM 이 옮기는 대로만 바뀐다."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


_CLOCK = _FakeClock()
# 기본 가짜 LLM 이 첫 델타 앞에서 옮기는 시간. 이진 소수로 정확히 떨어지는 값이라 ms 로 바꿔도 반올림이 끼지 않는다.
_SINK_FIRST_TOKEN_SECONDS = 0.125
_SINK_STREAM_FIRST_TOKEN_MS = 125
# 방 턴의 생성 프롬프트 조립(질의 임베딩 포함)이 걸리는 시간. 스트림 쪽 값과 겹치지 않게 고른다.
_ASSEMBLY_SECONDS = 0.5
_ASSEMBLY_MS = 500
_SINK_FIRST_TOKEN_MS = _ASSEMBLY_MS + _SINK_STREAM_FIRST_TOKEN_MS


@pytest.fixture(autouse=True)
def _fake_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    _CLOCK.now = 1000.0
    monkeypatch.setattr(turn_engine, "_clock", _CLOCK)

    async def _slow_build_room_prompt(*args: Any, **kwargs: Any) -> Any:
        _CLOCK.now += _ASSEMBLY_SECONDS
        return await turn_prompt.build_room_prompt(*args, **kwargs)

    # 라우트가 이름을 가져다 쓰므로 라우트 모듈의 이름을 바꿔 끼운다.
    monkeypatch.setattr(chat_router, "build_room_prompt", _slow_build_room_prompt)


class _SinkLLMClient(LLMClient):
    """생성은 고정 응답, 스탯 판정은 규칙 a1(+5), 엔딩은 `ending` 대로 답한다. 공급자 구현처럼 호출 컨텍스트의 사용량
    목록에 호출 한 건씩 더하고, 모델 이름에 `tag` 를 붙여 어느 요청의 호출인지 가른다."""

    def __init__(self, *, tag: str, ending: bool = False) -> None:
        self._tag = tag
        self._ending = ending

    def _sink(self, usage: LLMCallContext) -> None:
        if usage.usage_sink is not None:
            usage.usage_sink.append(
                CallUsage(
                    call_site=usage.call_site,
                    model=f"{self._tag}-model",
                    prompt_tokens=100,
                    cached_tokens=10,
                    cache_write_tokens=None,
                    output_tokens=7,
                    thoughts_tokens=0,
                )
            )

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        _CLOCK.now += _SINK_FIRST_TOKEN_SECONDS
        yield f"{self._tag} 응답"
        self._sink(usage)

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self._sink(usage)
        if response_schema is StatRuleJudgmentResult:
            return StatRuleJudgmentResult(fired_rule_ids=["a1"])
        if response_schema is EndingJudgmentResult:
            return EndingJudgmentResult(triggered=self._ending)
        if response_schema is ImageMatchJudgmentResult:
            return ImageMatchJudgmentResult(matched_image_entity_id=None)
        return MemorySummaryResult(summary="요약")


def _calls(tag: str, *call_sites: str) -> list[dict[str, Any]]:
    return [
        {
            "callSite": call_site,
            "model": f"{tag}-model",
            "promptTokens": 100,
            "cachedTokens": 10,
            "cacheWriteTokens": None,
            "outputTokens": 7,
            "thoughtsTokens": 0,
            **(
                {"firstTokenMs": _SINK_FIRST_TOKEN_MS, "streamFirstTokenMs": _SINK_STREAM_FIRST_TOKEN_MS}
                if call_site == "chat_generate"
                else {}
            ),
        }
        for call_site in call_sites
    ]


class _ScriptedLLMClient(_SinkLLMClient):
    """생성이 `(앞서 흐르는 초, 델타)` 차례대로 시계를 옮기며 델타를 낸다. 판정은 기본 가짜 LLM 그대로다."""

    def __init__(self, *, tag: str, steps: list[tuple[float, str]]) -> None:
        super().__init__(tag=tag)
        self._steps = steps

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        for seconds, delta in self._steps:
            _CLOCK.now += seconds
            yield delta
        self._sink(usage)


async def _post(
    client: httpx.AsyncClient, method: str, path: str, body: dict[str, object] | None, fake: LLMClient
) -> None:
    _override_llm_client(fake)
    try:
        response = await client.request(method, path, json=body)
    finally:
        _clear_llm_override()
    assert response.status_code == 200, response.text
    assert _parse_sse_events(response.text)[-1]["type"] == "done", response.text


async def _records(db_session: AsyncSession, room_id: uuid.UUID) -> list[ChatTurn]:
    db_session.expire_all()
    return list(
        (
            await db_session.scalars(
                sa.select(ChatTurn).where(ChatTurn.chat_room_id == room_id).order_by(ChatTurn.created_at, ChatTurn.id)
            )
        ).all()
    )


async def _last_assistant_id(db_session: AsyncSession, room_id: uuid.UUID) -> uuid.UUID:
    message_id = await db_session.scalar(
        sa.select(ChatMessage.id)
        .where(ChatMessage.chat_room_id == room_id, ChatMessage.role == ChatMessageRole.ASSISTANT)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
    )
    assert message_id is not None
    return message_id


async def _setup_of(db_session: AsyncSession, room_id: uuid.UUID) -> StartingSetup:
    version_id, setup_entity_id = (
        await db_session.execute(
            sa.select(ChatRoom.content_version_id, ChatRoom.starting_setup_entity_id).where(ChatRoom.id == room_id)
        )
    ).one()
    setup = await db_session.scalar(
        sa.select(StartingSetup).where(
            StartingSetup.content_version_id == version_id, StartingSetup.entity_id == setup_entity_id
        )
    )
    assert setup is not None
    return setup


async def _stat_entity_id(db_session: AsyncSession, room_id: uuid.UUID) -> str:
    setup = await _setup_of(db_session, room_id)
    stat_entity_id = await db_session.scalar(sa.select(StatDef.entity_id).where(StatDef.starting_setup_id == setup.id))
    assert stat_entity_id is not None
    return str(stat_entity_id)


async def _add_ending(db_session: AsyncSession, room_id: uuid.UUID) -> uuid.UUID:
    """첫 턴부터 판정하는 규칙 없는 엔딩 하나."""
    setup = await _setup_of(db_session, room_id)
    ending = Ending(
        entity_id=uuid.uuid4(),
        starting_setup_id=setup.id,
        name="떠남",
        turn_count_gate=1,
        judgment_prompt="떠났는가?",
        epilogue="그렇게 마을을 떠났다.",
        order=1,
    )
    db_session.add(ending)
    await db_session.commit()
    return ending.entity_id


async def _add_shortcut(db_session: AsyncSession, room_id: uuid.UUID) -> uuid.UUID:
    version_id = await db_session.scalar(sa.select(ChatRoom.content_version_id).where(ChatRoom.id == room_id))
    assert version_id is not None
    shortcut = Shortcut(
        entity_id=uuid.uuid4(),
        content_version_id=version_id,
        name="수색",
        description="주변을 수색한다",
        prompt="플레이어가 주변을 자세히 수색하는 상황을 묘사하라",
    )
    db_session.add(shortcut)
    await db_session.commit()
    return shortcut.entity_id


async def _spend_ledger_id(db_session: AsyncSession, user_id: uuid.UUID) -> uuid.UUID:
    """그 사용자의 채팅 차감 원장 행 하나. 기본 모델 턴에도 하루 무료분이 없어 턴 기록이 이 행을 가리킨다."""
    [ledger_id] = (
        await db_session.scalars(
            sa.select(CloverLedger.id).where(CloverLedger.user_id == user_id, CloverLedger.kind == "chat_spend")
        )
    ).all()
    return ledger_id


def _row(record: ChatTurn) -> dict[str, Any]:
    return {
        "assistant_message_id": record.assistant_message_id,
        "kind": record.kind,
        "turn_number": record.turn_number,
        "chat_model": record.chat_model,
        "charge_source": record.charge_source,
        "clover_amount": record.clover_amount,
        "spend_ledger_id": record.spend_ledger_id,
        "shortcut_entity_id": record.shortcut_entity_id,
        "llm_calls": record.llm_calls,
        "stat_changes": record.stat_changes,
        "ending_entity_id": record.ending_entity_id,
        "stage_routes": record.stage_routes,
    }


# 배정 표가 빈 Gemini 방에서 단계마다 읽는 모델 설정의 이름. 테스트 설정은 판정·요약 모델이 모두 Gemini 라 체인·부를 모델·
# 경로가 모두 gemini 이고 세트는 그 레인의 Gemini 활성 세트 하나다.
_ENV_STAGES: dict[RoutingLane, list[tuple[str, str]]] = {
    "story": [
        ("stat_judgment", "STAT_JUDGMENT_MODEL"),
        ("scene_judgment", "STAT_JUDGMENT_MODEL"),
        ("ending_judgment", "ENDING_JUDGMENT_MODEL"),
        ("media_book_image", "IMAGE_JUDGMENT_MODEL"),
        ("memory_summary", "MEMORY_SUMMARY_MODEL"),
        ("memory_episode", "MEMORY_EPISODE_MODEL"),
        ("memory_fact", "MEMORY_FACT_MODEL"),
    ],
    "character": [
        ("situational_image", "IMAGE_JUDGMENT_MODEL"),
        ("memory_summary", "MEMORY_SUMMARY_MODEL"),
        ("memory_episode", "MEMORY_EPISODE_MODEL"),
        ("memory_fact", "MEMORY_FACT_MODEL"),
    ],
}


async def _empty_table_stage_routes(db_session: AsyncSession, lane: RoutingLane) -> list[dict[str, Any]]:
    gemini_set, _ = await load_active_prompt_set(db_session, lane=lane, model="gemini")
    common = {"lane": lane, "chainModel": "gemini", "promptSetId": str(gemini_set.id), "callModel": "gemini"}
    return [
        {**common, "stage": "chat_generate", "backend": "gemini", "source": "room"},
        *(
            {**common, "stage": stage, "backend": "gemini", "source": "env", "sourceDetail": setting}
            for stage, setting in _ENV_STAGES[lane]
        ),
    ]


# ── 보내기·수정 ─────────────────────────────────────────────────────────────────────────


async def test_story_send_writes_one_record_with_the_turns_model_charge_calls_stats_ending_and_shortcut(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=0, lane="story", paid_turns=1)
    stat_id = await _stat_entity_id(db_session, room.room_id)
    ending_id = await _add_ending(db_session, room.room_id)
    shortcut_id = await _add_shortcut(db_session, room.room_id)
    # 칸이 하나 있어야 칸 판정 호출이 나간다(가짜 LLM 은 어느 칸도 고르지 않는다).
    version_id = await db_session.scalar(sa.select(ChatRoom.content_version_id).where(ChatRoom.id == room.room_id))
    assert version_id is not None
    await _add_named_media_cell(db_session, version_id, room.user_id, "민아", "교실")
    await db_session.commit()

    await _post(
        db_client,
        "POST",
        f"/chat-rooms/{room.room_id}/messages",
        {"content": "/수색", "shortcutId": str(shortcut_id)},
        _SinkLLMClient(tag="send", ending=True),
    )

    [record] = await _records(db_session, room.room_id)
    # 스탯·칸 판정은 동시에 부르므로 호출 위치로 줄 세워 본다.
    assert _row(record) | {"llm_calls": sorted(record.llm_calls, key=lambda call: call["callSite"])} == {
        "assistant_message_id": await _last_assistant_id(db_session, room.room_id),
        "kind": "send",
        "turn_number": 1,
        "chat_model": "gemini",
        "charge_source": "clover",
        "clover_amount": clover.CLOVER_MODEL_PRICES["gemini"].chat_turn,
        "spend_ledger_id": await _spend_ledger_id(db_session, room.user_id),
        "shortcut_entity_id": shortcut_id,
        "llm_calls": _calls(
            "send", "chat_ending_judgment", "chat_generate", "chat_media_book_image", "chat_stat_judgment"
        ),
        "stat_changes": {stat_id: [73, 78]},
        "ending_entity_id": ending_id,
        "stage_routes": await _empty_table_stage_routes(db_session, "story"),
    }


async def test_clover_charged_send_records_the_charge_and_its_ledger_row(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user_with_clover_lot(
        db_session, clover_balance=100, clover_spend_confirmed_on=clover.kst_today(datetime.now(UTC))
    )
    room = await _open_room(db_client, db_session, turns=0, user=user)
    await _add_room_situational_image(db_session, room.room_id)

    await _post(
        db_client, "POST", f"/chat-rooms/{room.room_id}/messages", {"content": "안녕"}, _SinkLLMClient(tag="send")
    )

    ledger_id = await db_session.scalar(
        sa.select(CloverLedger.id).where(CloverLedger.user_id == user.id, CloverLedger.kind == "chat_spend")
    )
    [record] = await _records(db_session, room.room_id)
    assert (record.kind, record.charge_source, record.clover_amount, record.spend_ledger_id) == (
        "send",
        "clover",
        clover.CLOVER_MODEL_PRICES["gemini"].chat_turn,
        ledger_id,
    )
    # 캐릭터 방은 스탯·엔딩이 없고 판정은 상황 이미지 하나다.
    assert (record.stat_changes, record.ending_entity_id, record.shortcut_entity_id) == ({}, None, None)
    assert record.llm_calls == _calls("send", "chat_generate", "chat_situational_image")
    assert record.stage_routes == await _empty_table_stage_routes(db_session, "character")


async def test_each_send_and_edit_writes_one_record(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    room = await _open_room(db_client, db_session, turns=1, lane="story", paid_turns=3)
    stat_id = await _stat_entity_id(db_session, room.room_id)

    await _post(
        db_client, "POST", f"/chat-rooms/{room.room_id}/messages", {"content": "약속을 지킨다"}, _SinkLLMClient(tag="a")
    )
    await _post(
        db_client, "POST", f"/chat-rooms/{room.room_id}/messages", {"content": "또 지킨다"}, _SinkLLMClient(tag="b")
    )
    # 둘째 보내기의 사용자 메시지를 고친다 — 그 뒤 응답이 지워지고 3번째 턴을 새로 만든다.
    edited_id = await db_session.scalar(
        sa.select(ChatMessage.id).where(ChatMessage.chat_room_id == room.room_id, ChatMessage.content == "또 지킨다")
    )
    await _post(
        db_client,
        "PATCH",
        f"/chat-rooms/{room.room_id}/messages/{edited_id}",
        {"content": "고쳐 말하면, 지킨다"},
        _SinkLLMClient(tag="c"),
    )

    # 한 트랜잭션 안의 테스트라 `created_at` 이 모두 같다 — 턴 번호와 종류로 줄 세운다.
    records = sorted(await _records(db_session, room.room_id), key=lambda r: (r.turn_number, r.kind))
    assert [(r.kind, r.turn_number, r.stat_changes) for r in records] == [
        ("send", 2, {stat_id: [73, 78]}),
        # 수정은 지운 턴의 스탯을 되돌린 뒤 판정하므로 78 에서 시작한다.
        ("edit", 3, {stat_id: [78, 83]}),
        ("send", 3, {stat_id: [78, 83]}),
    ]
    assert records[1].assistant_message_id == await _last_assistant_id(db_session, room.room_id)
    assert records[1].llm_calls == _calls("c", "chat_generate", "chat_stat_judgment")


async def test_first_token_latency_counts_from_turn_start_and_from_stream_start_to_the_first_delta_with_text(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """조립 0.5초 뒤 스트림을 열고, 빈 델타(0.125초)·첫 글자(0.25초)·끝(2.25초)이 온다. 빈 델타는 화면에 아무것도
    띄우지 않으므로 첫 글자가 아니다. 턴 시작부터는 750, 스트림 시작부터는 250 이다 — 마지막 델타 시각을 쓰면 2750·2250,
    빈 델타를 세면 625·125, 턴 시작을 스트림 시작으로 잡으면 둘 다 250 이 나와 값으로 갈린다. 판정 칸에는 생성 지연이
    붙지 않는다."""
    room = await _open_room(db_client, db_session, turns=1, lane="story", paid_turns=1)

    await _post(
        db_client,
        "POST",
        f"/chat-rooms/{room.room_id}/messages",
        {"content": "약속을 지킨다"},
        _ScriptedLLMClient(tag="send", steps=[(0.125, ""), (0.125, "첫 "), (2.0, "끝")]),
    )

    [record] = await _records(db_session, room.room_id)
    by_site = {call["callSite"]: call for call in record.llm_calls}
    generate_call = by_site["chat_generate"]
    latencies = (generate_call.get("firstTokenMs"), generate_call.get("streamFirstTokenMs"))
    assert [(type(value), value) for value in latencies] == [(int, 750), (int, 250)]
    assert [site for site, call in by_site.items() if {"firstTokenMs", "streamFirstTokenMs"} & call.keys()] == [
        "chat_generate"
    ]


@pytest.mark.parametrize("steps", [pytest.param([], id="no-delta"), pytest.param([(0.25, "")], id="only-empty-delta")])
async def test_generation_that_ends_without_text_records_no_first_token_latency(
    db_client: httpx.AsyncClient, db_session: AsyncSession, steps: list[tuple[float, str]]
) -> None:
    """글 없이 정상 종료한 생성은 잴 첫 글자가 없다. 0 이나 종료 시각으로 채우면 분포에 가짜 빠른 값이 섞이므로 두 키를 다 뺀다.
    생성 칸 자체는 남는다(호출은 과금됐다)."""
    room = await _open_room(db_client, db_session, turns=1, lane="story", paid_turns=1)

    await _post(
        db_client,
        "POST",
        f"/chat-rooms/{room.room_id}/messages",
        {"content": "약속을 지킨다"},
        _ScriptedLLMClient(tag="send", steps=steps),
    )

    [record] = await _records(db_session, room.room_id)
    [generate_call] = [call for call in record.llm_calls if call["callSite"] == "chat_generate"]
    assert {"firstTokenMs", "streamFirstTokenMs"} & generate_call.keys() == set()


# ── 재생성 ─────────────────────────────────────────────────────────────────────────────


async def _seed_record_for_last_reply(db_session: AsyncSession, room_id: uuid.UUID, **values: Any) -> ChatTurn:
    """마지막 응답에 모든 칸이 이번 재생성과 다른 값인 기록을 둔다 — 어느 칸을 어디서 가져왔는지가 값으로 갈린다."""
    record = _make_chat_turn(
        room_id,
        assistant_message_id=await _last_assistant_id(db_session, room_id),
        **{
            "kind": "send",
            "turn_number": 7,
            "chat_model": "opus",
            "charge_source": "clover",
            "clover_amount": 9,
            "spend_ledger_id": uuid.uuid4(),
            "shortcut_entity_id": uuid.uuid4(),
            "llm_calls": _calls("old", "chat_generate"),
            "stat_changes": {str(uuid.uuid4()): [10, 20]},
            "ending_entity_id": uuid.uuid4(),
            "stage_routes": [{"stage": "chat_generate", "source": "row"}],
            **values,
        },
    )
    db_session.add(record)
    await db_session.commit()
    return record


async def test_regenerate_inherits_turn_stats_ending_and_shortcut_from_the_replaced_record(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=1, lane="story", paid_turns=1)
    old = await _seed_record_for_last_reply(db_session, room.room_id)

    await _post(db_client, "POST", f"/chat-rooms/{room.room_id}/regenerate", None, _SinkLLMClient(tag="regen"))

    [new] = [r for r in await _records(db_session, room.room_id) if r.id != old.id]
    assert _row(new) == {
        "assistant_message_id": await _last_assistant_id(db_session, room.room_id),
        "kind": "regenerate",
        "turn_number": 7,
        "chat_model": "gemini",
        "charge_source": "clover",
        "clover_amount": clover.CLOVER_MODEL_PRICES["gemini"].chat_turn,
        "spend_ledger_id": await _spend_ledger_id(db_session, room.user_id),
        "shortcut_entity_id": old.shortcut_entity_id,
        "llm_calls": _calls("regen", "chat_generate"),
        "stat_changes": old.stat_changes,
        "ending_entity_id": old.ending_entity_id,
        "stage_routes": await _empty_table_stage_routes(db_session, "story"),
    }


async def test_regenerate_without_a_replaced_record_writes_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=1, lane="story", paid_turns=1)

    await _post(db_client, "POST", f"/chat-rooms/{room.room_id}/regenerate", None, _SinkLLMClient(tag="regen"))

    assert await _records(db_session, room.room_id) == []


async def test_regenerating_a_regeneration_keeps_the_first_records_values(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=1, lane="story", paid_turns=2)
    first = await _seed_record_for_last_reply(db_session, room.room_id)

    await _post(db_client, "POST", f"/chat-rooms/{room.room_id}/regenerate", None, _SinkLLMClient(tag="r1"))
    await _post(db_client, "POST", f"/chat-rooms/{room.room_id}/regenerate", None, _SinkLLMClient(tag="r2"))

    last_reply_id = await _last_assistant_id(db_session, room.room_id)
    [last] = [r for r in await _records(db_session, room.room_id) if r.assistant_message_id == last_reply_id]
    assert (last.kind, last.turn_number, last.stat_changes, last.ending_entity_id, last.shortcut_entity_id) == (
        "regenerate",
        first.turn_number,
        first.stat_changes,
        first.ending_entity_id,
        first.shortcut_entity_id,
    )
    assert last.llm_calls == _calls("r2", "chat_generate")


async def test_regenerating_an_earlier_reply_after_deleting_later_turns_keeps_that_replys_turn_number(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """마지막 응답을 지워도 턴 수를 줄이지 않던 옛 이미지의 삭제가 뒤 턴을 지운 방에서는 앞 응답이 마지막 메시지가 돼도 방
    `turn_count` 가 지운 턴까지 센 값 그대로다. 재생성 기록은 그 값이 아니라 대체되는 응답이 속한 턴 번호여야 한다 — 다음
    재생성이 이 기록을 보고 "방의 마지막 턴"인지 가른다."""
    room = await _open_room(db_client, db_session, turns=2, lane="story", paid_turns=1)
    _, first_reply = room.turns[1]
    second_user, second_reply = room.turns[2]
    dropped = [second_reply.id, second_user.id]
    db_session.add(_make_chat_turn(room.room_id, assistant_message_id=first_reply.id, turn_number=1))
    db_session.add(_make_chat_turn(room.room_id, assistant_message_id=second_reply.id, turn_number=2))
    await db_session.commit()
    await db_session.execute(sa.delete(ChatMessage).where(ChatMessage.id.in_(dropped)))
    await db_session.commit()

    await _post(db_client, "POST", f"/chat-rooms/{room.room_id}/regenerate", None, _SinkLLMClient(tag="regen"))

    turn_count = await db_session.scalar(sa.select(ChatRoom.turn_count).where(ChatRoom.id == room.room_id))
    assert turn_count == 2
    last_reply_id = await _last_assistant_id(db_session, room.room_id)
    [new] = [r for r in await _records(db_session, room.room_id) if r.assistant_message_id == last_reply_id]
    assert (new.kind, new.turn_number) == ("regenerate", 1)


# ── 미리보기 ────────────────────────────────────────────────────────────────────────────


async def test_preview_turn_writes_no_record(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = await _make_paying_user(db_session, turns=1)
    await db_session.commit()
    await _login_as(db_client, user.id)
    started = await db_client.post("/preview-sessions", json=_preview_character_payload())
    assert started.status_code == 201, started.text
    before = await db_session.scalar(sa.select(sa.func.count()).select_from(ChatTurn))

    await _post(
        db_client,
        "POST",
        f"/preview-sessions/{started.json()['previewSessionId']}/messages",
        {"content": "안녕"},
        _SinkLLMClient(tag="preview"),
    )

    assert await db_session.scalar(sa.select(sa.func.count()).select_from(ChatTurn)) == before


# ── 공급자 구현이 사용량 목록에 더하는 자리 ─────────────────────────────────────────────────


async def _drain(client: LLMClient, usage: LLMCallContext) -> None:
    async for _ in client.generate("프롬프트", "지시", usage=usage):
        pass


@pytest.mark.parametrize("provider", ["gemini", "bedrock", "anthropic"])
async def test_each_provider_adds_a_finished_stream_to_the_usage_sink(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    sdks = _FakeProviderSdks(monkeypatch)
    client: LLMClient
    if provider == "gemini":
        client = sdks.gemini
        expected = CallUsage("chat_generate", settings.gemini_model_name, 100, 10, None, 7, 3)
    elif provider == "bedrock":
        client = sdks.bedrock
        expected = CallUsage("chat_generate", backend_model_id("bedrock", "sonnet"), 100, 20, 30, 9, 0)
    else:

        async def _no_record(*_: Any, **__: Any) -> None:
            return None

        monkeypatch.setattr(anthropic_api, "record_usage", _no_record)
        anthropic_client = AnthropicLLMClient()
        monkeypatch.setattr(
            anthropic_client, "_client", SimpleNamespace(messages=SimpleNamespace(create=sdks._bedrock_create))
        )
        client = anthropic_client
        expected = CallUsage("chat_generate", backend_model_id("anthropic", "sonnet"), 100, 20, 30, 9, 0)
    sink: list[CallUsage] = []

    model: ChatModelId = "gemini" if provider == "gemini" else "sonnet"
    await _drain(
        client, LLMCallContext(call_site="chat_generate", user_id=None, room_id=None, model=model, usage_sink=sink)
    )

    assert sink == [expected]
    # 사용량 집계도 그대로 모듈 전역 이름으로 불린다(리플레이가 그 이름을 바꿔 끼운다).
    if provider != "anthropic":
        assert sdks.recorded[-1][0] == "chat_generate"


async def test_gemini_structured_call_adds_to_the_usage_sink_before_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    sdks = _FakeProviderSdks(monkeypatch)

    async def _generate_content(**_: Any) -> SimpleNamespace:
        # 파싱 결과가 스키마가 아니어도(판정 실패) 응답을 받은 호출은 과금됐으니 남는다.
        return SimpleNamespace(
            parsed=None,
            prompt_feedback=None,
            candidates=[],
            text="",
            usage_metadata=SimpleNamespace(
                prompt_token_count=40,
                cached_content_token_count=None,
                candidates_token_count=5,
                thoughts_token_count=None,
            ),
        )

    monkeypatch.setattr(sdks.gemini._client.aio.models, "generate_content", _generate_content, raising=False)
    sink: list[CallUsage] = []
    with pytest.raises(LLMClientError):
        await sdks.gemini.generate_structured(
            "프롬프트",
            StatRuleJudgmentResult,
            usage=LLMCallContext(call_site="chat_stat_judgment", user_id=None, room_id=None, usage_sink=sink),
        )

    assert [(c.call_site, c.prompt_tokens, c.cached_tokens, c.output_tokens) for c in sink] == [
        ("chat_stat_judgment", 40, None, 5)
    ]


def test_usage_sink_does_not_change_call_context_equality() -> None:
    """사용량 목록은 호출의 귀속이 아니라 모으는 자리라 비교·해시에 들지 않는다 — 목록을 실은 컨텍스트도 해시할 수 있다."""
    plain = LLMCallContext(call_site="chat_generate", user_id=None, room_id=None)
    with_sink = LLMCallContext(call_site="chat_generate", user_id=None, room_id=None, usage_sink=[])
    assert plain == with_sink
    assert hash(plain) == hash(with_sink)
