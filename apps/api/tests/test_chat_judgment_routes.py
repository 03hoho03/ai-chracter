"""방 턴의 판정·요약 세트가 모델 배정 표를 따르는 것 — 빈 표의 특성 기대값부터.

기대값 파일(`fixtures/chat_judgment_sets_characterization.json`)은 판정 세트 고르기가 모델 배정 표를 읽기 전 코드에서 만들었다.
그 코드의 src 를 `sys.path` 맨 앞에 두고 이 모듈의 `observe_turn` 을 시나리오마다 돌려 그대로 적었다. 그래서 이 모듈은 그때
코드에도 있던 이름만 쓴다. 기대값을 다시 만들어야 한다면 같은 방식으로 그 전 코드에서 만들어야 한다 — 지금 코드로 만들면 대조가
항진명제가 된다.

시나리오: 레인 둘(스토리·캐릭터) × 방(저장 Gemini 스위치 켜짐, 저장 Opus 스위치 켜짐, 저장 Opus 스위치 꺼짐) × 경로 셋(보내기·
재생성·수정) × 판정·요약 모델 설정 두 벌(전부 Gemini, 전부 Haiku). 시나리오마다 적는 것:

- 판정 세트 칸마다 고른 세트의 모델(장면 헤더 칸이 생기기 전 칸 여섯만),
- 프롬프트 세트 캐시 키를 건드린 Redis 명령의 순서(어느 모델 세트를 몇 번 찾고 채웠는가),
- 요청 동안 실행된 DB 문장 수와 Redis 명령 수 — 배정 표 캐시를 미리 데운 상태에서 잰다. 테스트 픽스처가 매 테스트 전에 그 캐시를
  지우므로 데우지 않으면 첫 요청이 배정 표를 DB 에서 읽는다. Redis 수에는 배정 표 키 명령을 넣지 않는다(표를 읽는 것은 지금
  코드에만 있는 일이라 따로 단언한다),
- 가짜 LLM 이 받은 (호출 위치, 실린 모델) 순서, 원장 행, 응답 상태와 마지막 이벤트.

출력에 영향을 주는 설정은 `FIXED_SETTINGS` 리터럴로 고정한다 — env 나 로컬 `.env` 값에 기대지 않는다.
"""

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat import router as chat_router
from api.chat import turn_prompt
from api.chat.prompt_builder import StatRuleJudgmentResult
from api.chat.prompt_routing_cache import PROMPT_ROUTES_CACHE_KEY, load_prompt_routes
from api.chat.prompt_set_cache import ACTIVE_PROMPT_SET_KEY_PREFIX
from api.core.config import settings
from api.core.redis import redis_client
from api.db.models.chat import ChatMessage, ChatMessageRole, ChatRoom
from api.db.models.clover import CloverLedger
from api.llm.client import LLMCallContext, LLMClient
from factories import (
    _clear_llm_override,
    _count_queries,
    _make_user_with_clover_lot,
    _open_room,
    _override_llm_client,
    _parse_sse_events,
)

FIXTURE = Path(__file__).parent / "fixtures" / "chat_judgment_sets_characterization.json"

JUDGMENT_MODEL_SETTINGS = (
    "stat_judgment_model",
    "ending_judgment_model",
    "image_judgment_model",
    "memory_summary_model",
    "memory_episode_model",
    "memory_fact_model",
)

FIXED_SETTINGS: dict[str, Any] = {
    "llm_call_site_backends": {},
    "memory_window_generation": True,
    "memory_window_ending_judgment": True,
    "memory_window_image_judgment": True,
    "memory_episodes_extract": False,
    "memory_facts_extract": False,
    "memory_episodes_recall": False,
    "memory_facts_inject": False,
    "memory_knowledge_filter": False,
    "memory_summary_secret_marking": False,
    "memory_embed_write": False,
    "memory_embed_recall": False,
    "memory_items_visible": False,
    "memory_model_scope": [("story", "opus"), ("character", "opus")],
    "identity_gate_enabled": False,
    "payments_enabled": False,
}

PROFILES = ("gemini", "haiku")
LANES = ("story", "character")
# (저장된 방 모델, 상위 모델 스위치)
ROOMS = (("gemini", True), ("opus", True), ("opus", False))
SURFACES = ("send", "regenerate", "edit")
SLOTS = ("stat", "ending", "image", "summary", "episode", "fact")


def scenario_id(profile: str, lane: str, stored: str, switch: bool, surface: str) -> str:
    return f"{profile}-{lane}-{stored}-{'on' if switch else 'off'}-{surface}"


SCENARIOS = [
    (profile, lane, stored, switch, surface)
    for profile in PROFILES
    for lane in LANES
    for stored, switch in ROOMS
    for surface in SURFACES
]


def fix_settings(monkeypatch: pytest.MonkeyPatch, *, profile: str, premium: bool) -> None:
    for name, value in FIXED_SETTINGS.items():
        monkeypatch.setattr(settings, name, value)
    for name in JUDGMENT_MODEL_SETTINGS:
        monkeypatch.setattr(settings, name, profile)
    monkeypatch.setattr(settings, "chat_premium_models_enabled", premium)


class RecordingLLM(LLMClient):
    """생성은 고정 응답, 구조화 호출은 스탯 판정의 "변화 없음". 받은 (호출 위치, 실린 모델)을 순서대로 적는다."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.structured_prompts: list[tuple[str, str]] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.calls.append((usage.call_site, usage.model))
        yield "응답"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.calls.append((usage.call_site, usage.model))
        self.structured_prompts.append((usage.call_site, prompt))
        return StatRuleJudgmentResult(fired_rule_ids=[])


class RedisRecorder:
    """`redis_client.execute_command` 를 감싸 명령을 센다. 배정 표 키 명령은 따로 센다."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.other = 0
        self.route_table: list[str] = []
        self.prompt_set: list[tuple[str, str]] = []
        real: Any = redis_client.execute_command

        async def _execute(*args: Any, **options: Any) -> Any:
            command = str(args[0]).upper() if args else ""
            key = str(args[1]) if len(args) > 1 else ""
            if key == PROMPT_ROUTES_CACHE_KEY:
                self.route_table.append(command)
            else:
                self.other += 1
                if key.startswith(ACTIVE_PROMPT_SET_KEY_PREFIX):
                    self.prompt_set.append((command, key.removeprefix(ACTIVE_PROMPT_SET_KEY_PREFIX)))
            return await real(*args, **options)

        monkeypatch.setattr(redis_client, "execute_command", _execute)


def record_judgment_sets(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    """라우터가 부르는 판정 세트 고르기의 결과를 칸마다 세트 모델로 적는다(인자는 그대로 넘긴다)."""
    seen: list[dict[str, str]] = []
    real = turn_prompt.judgment_prompt_sets

    async def _recording(**kwargs: Any) -> Any:
        sets = await real(**kwargs)
        seen.append({slot: getattr(sets, slot)[0].model for slot in SLOTS})
        return sets

    monkeypatch.setattr(chat_router, "judgment_prompt_sets", _recording)
    return seen


async def open_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, *, lane: str, stored: str
) -> tuple[uuid.UUID, uuid.UUID]:
    user = await _make_user_with_clover_lot(db_session, clover_balance=1000)
    await db_session.commit()
    room = await _open_room(db_client, db_session, turns=1, lane=lane, user=user)
    await db_session.execute(update(ChatRoom).where(ChatRoom.id == room.room_id).values(chat_model=stored))
    await db_session.commit()
    return room.room_id, user.id


async def last_user_message_id(db_session: AsyncSession, room_id: uuid.UUID) -> uuid.UUID:
    message_id = await db_session.scalar(
        select(ChatMessage.id)
        .where(ChatMessage.chat_room_id == room_id, ChatMessage.role == ChatMessageRole.USER)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
    )
    assert message_id is not None
    return message_id


async def turn_request(
    db_client: httpx.AsyncClient, db_session: AsyncSession, fake: LLMClient, room_id: uuid.UUID, surface: str
) -> httpx.Response:
    """보내기·재생성·수정 요청 하나. 수정 대상 메시지는 요청 전에 읽는다(재는 구간 밖)."""
    target = await last_user_message_id(db_session, room_id) if surface == "edit" else None
    _override_llm_client(fake)
    try:
        if surface == "send":
            return await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
        if surface == "regenerate":
            return await db_client.post(f"/chat-rooms/{room_id}/regenerate")
        return await db_client.patch(f"/chat-rooms/{room_id}/messages/{target}", json={"content": "고친 말"})
    finally:
        _clear_llm_override()


async def ledger(db_session: AsyncSession, user_id: uuid.UUID) -> list[list[Any]]:
    rows = await db_session.execute(
        select(CloverLedger.kind, CloverLedger.amount).where(CloverLedger.user_id == user_id)
    )
    return sorted([kind, amount] for kind, amount in rows.all())


async def observe_turn(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    *,
    profile: str,
    lane: str,
    stored: str,
    switch: bool,
    surface: str,
) -> dict[str, Any]:
    fix_settings(monkeypatch, profile=profile, premium=switch)
    room_id, user_id = await open_room(db_client, db_session, lane=lane, stored=stored)
    await load_prompt_routes(db_session)
    await db_session.commit()
    sets = record_judgment_sets(monkeypatch)
    fake = RecordingLLM()
    redis = RedisRecorder(monkeypatch)
    with _count_queries() as statements:
        resp = await turn_request(db_client, db_session, fake, room_id, surface)
        db_statements = statements()
    events = _parse_sse_events(resp.text) if resp.status_code == 200 else []
    return {
        "status": resp.status_code,
        "last_event": events[-1]["type"] if events else None,
        "slots": sets,
        "prompt_set_redis": [list(item) for item in redis.prompt_set],
        "db_statements": db_statements,
        "redis_commands": redis.other,
        "llm_calls": [list(call) for call in fake.calls],
        "ledger": await ledger(db_session, user_id),
    }


@pytest.fixture(scope="module")
def expected() -> Iterator[dict[str, Any]]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert data["fixed_settings"] == json.loads(json.dumps(FIXED_SETTINGS))
    assert sorted(data["scenarios"]) == sorted(scenario_id(*case) for case in SCENARIOS)
    yield data["scenarios"]


@pytest.mark.parametrize(
    ("profile", "lane", "stored", "switch", "surface"), SCENARIOS, ids=[scenario_id(*case) for case in SCENARIOS]
)
async def test_empty_route_table_turn_matches_the_characterization(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    expected: dict[str, Any],
    profile: str,
    lane: str,
    stored: str,
    switch: bool,
    surface: str,
) -> None:
    observed = await observe_turn(
        db_client, db_session, monkeypatch, profile=profile, lane=lane, stored=stored, switch=switch, surface=surface
    )

    assert observed == expected[scenario_id(profile, lane, stored, switch, surface)]
