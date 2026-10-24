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
from api.chat.prompt_builder import PromptSetNotFoundError, StatRuleJudgmentResult
from api.chat.prompt_routing import PromptRoutes, RouteRow, RouteRowInput, parse_route_row
from api.chat.prompt_routing_cache import PROMPT_ROUTES_CACHE_KEY, load_prompt_routes
from api.chat.prompt_set_cache import ACTIVE_PROMPT_SET_KEY_PREFIX
from api.chat.prompt_stages import LANE_STAGES, RoutingLane
from api.chat.turn_prompt import JudgmentSlot
from api.core import clover
from api.core.config import settings
from api.core.redis import redis_client
from api.db.models.chat import ChatMessage, ChatMessageRole, ChatRoom
from api.db.models.clover import CloverLedger
from api.db.models.prompt import PromptRoute, PromptSection, PromptSet
from api.llm import model_access
from api.llm.chat_models import ChatRoomModelId
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


# ── 판정 세트 고르기가 배정 표를 따른다 ───────────────────────────────────────────────────────

ALL_SLOTS: tuple[JudgmentSlot, ...] = ("stat", "scene", "ending", "image", "summary", "episode", "fact")


def _set(model: str) -> tuple[PromptSet, list[PromptSection]]:
    return PromptSet(model=model), []


class FakeSetStore:
    """모델마다 같은 세트 객체를 돌려주는 캐시·읽기. 두 번 고른 결과를 `is` 로 견줄 수 있게 캐시가 읽은 객체를 그대로 담는다."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.sets = {model: _set(model) for model in ("gemini", "haiku", "sonnet", "opus")}
        self.cache: dict[str, tuple[PromptSet, list[PromptSection]]] = {}
        self.looked_up: list[str] = []
        self.loads: list[str] = []

        async def _cached(lane: Any, *, model: str) -> Any:
            self.looked_up.append(model)
            return self.cache.get(model)

        async def _store(lane: Any, prompt_set: Any, sections: Any, *, model: str) -> None:
            assert prompt_set is self.sets[model][0]
            self.cache[model] = self.sets[model]

        monkeypatch.setattr(turn_prompt, "get_cached_active_prompt_set", _cached)
        monkeypatch.setattr(turn_prompt, "set_cached_active_prompt_set", _store)

    async def load(self, model: str) -> tuple[PromptSet, list[PromptSection]]:
        self.loads.append(model)
        return self.sets[model]


def _row(
    stage: str,
    *,
    lane: str = "story",
    room_model: str = "opus",
    chain_model: str | None = "haiku",
    call_model: str = "gemini",
    backend: str = "gemini",
) -> RouteRow:
    """해석이 쓰는 행. 기본은 Gemini 로 부르면서 다른 체인을 읽는 행이다 — 경로가 배정 없는 env 와 같아 건너뛰어지지 않는다."""
    row = parse_route_row(
        RouteRowInput(
            lane=lane, room_model=room_model, stage=stage, chain_model=chain_model, call_model=call_model, backend=backend
        )
    )
    assert row is not None
    return row


_MIXED_MODELS = {
    "stat_judgment_model": "haiku",
    "ending_judgment_model": "gemini",
    "image_judgment_model": "haiku",
    "memory_summary_model": "sonnet",
    "memory_episode_model": "gemini",
    "memory_fact_model": "sonnet",
}


@pytest.mark.parametrize("models", ["gemini", "mixed"])
@pytest.mark.parametrize("lane", LANES)
@pytest.mark.parametrize("room_model", ["gemini", "opus"])
async def test_empty_table_hands_every_slot_the_same_object_as_the_env_rule(
    monkeypatch: pytest.MonkeyPatch, models: str, lane: RoutingLane, room_model: ChatRoomModelId
) -> None:
    """빈 표의 짝 — 표와 방 모델을 넘긴 호출과 넘기지 않은 호출이 칸마다 같은 객체를 내고, 세트 조회 순서도 같다."""
    fix_settings(monkeypatch, profile="gemini", premium=True)
    if models == "mixed":
        for name, value in _MIXED_MODELS.items():
            monkeypatch.setattr(settings, name, value)
    store = FakeSetStore(monkeypatch)
    gemini_set = store.sets["gemini"]

    without = await turn_prompt.judgment_prompt_sets(lane=lane, gemini_set=gemini_set, load=store.load)
    lookups_without = list(store.looked_up)
    store.cache.clear()
    store.looked_up.clear()
    store.loads.clear()
    with_table = await turn_prompt.judgment_prompt_sets(
        lane=lane, gemini_set=gemini_set, load=store.load, routes=PromptRoutes.empty(), room_model=room_model
    )

    for slot in ALL_SLOTS:
        assert getattr(with_table, slot) is getattr(without, slot), slot
        assert with_table.call_model(slot) is None
    assert store.looked_up == lookups_without
    assert with_table.scene is with_table.stat
    if models == "gemini":
        assert lookups_without == []
        assert all(getattr(with_table, slot) is gemini_set for slot in ALL_SLOTS)
    else:
        assert sorted(store.loads) == ["haiku", "sonnet"]
        assert with_table.ending is gemini_set
        assert with_table.image is with_table.stat


@pytest.mark.parametrize("impression_model", ["gemini", "haiku"])
@pytest.mark.parametrize("table", ["empty", "rows"])
@pytest.mark.parametrize("lane", LANES)
async def test_impression_slot_follows_its_env_setting_whatever_the_table_holds(
    monkeypatch: pytest.MonkeyPatch, impression_model: str, table: str, lane: RoutingLane
) -> None:
    """인상 생성은 장기 기억 인상 기능이 아직 다듬어지는 중이라 단계 표 밖에 둔다 — 표가 비었든, 그 레인의 모든 단계에 다른 체인을
    고르는 행이 있든 인상 칸은 인상 모델 설정의 세트이고, 부를 모델은 실리지 않는다(None 이면 호출은 지금 경로로 간다)."""
    fix_settings(monkeypatch, profile="gemini", premium=True)
    monkeypatch.setattr(settings, "memory_impression_model", impression_model)
    store = FakeSetStore(monkeypatch)
    rows = (
        []
        if table == "empty"
        else [_row(stage, lane=lane, chain_model="sonnet") for stage in LANE_STAGES[lane] if stage != "chat_generate"]
    )

    sets = await turn_prompt.judgment_prompt_sets(
        lane=lane,
        gemini_set=store.sets["gemini"],
        load=store.load,
        routes=PromptRoutes.from_rows(rows),
        room_model="opus",
    )

    assert sets.impression is store.sets[impression_model]
    assert sets.call_model("impression") is None
    assert "impression" not in sets.routes
    if table == "rows":
        # 같은 표가 기억 요약 칸에는 실제로 쓰였다 — 인상 칸만 표를 보지 않는다는 대조다.
        assert sets.summary is store.sets["sonnet"]
        assert sets.call_model("summary") == "gemini"


async def test_a_row_picks_the_chain_of_its_own_cell_only(monkeypatch: pytest.MonkeyPatch) -> None:
    fix_settings(monkeypatch, profile="gemini", premium=True)
    store = FakeSetStore(monkeypatch)
    routes = PromptRoutes.from_rows(
        [
            _row("stat_judgment", chain_model="haiku"),
            _row("ending_judgment", chain_model="sonnet"),
            _row("media_book_image", chain_model="haiku"),
            _row("memory_summary", chain_model="sonnet"),
            _row("memory_episode", chain_model="haiku"),
            _row("memory_fact", chain_model="opus"),
        ]
    )
    gemini_set = store.sets["gemini"]

    opus = await turn_prompt.judgment_prompt_sets(
        lane="story", gemini_set=gemini_set, load=store.load, routes=routes, room_model="opus"
    )
    gemini = await turn_prompt.judgment_prompt_sets(
        lane="story", gemini_set=gemini_set, load=store.load, routes=routes, room_model="gemini"
    )
    character = await turn_prompt.judgment_prompt_sets(
        lane="character", gemini_set=gemini_set, load=store.load, routes=routes, room_model="opus"
    )

    assert {slot: getattr(opus, slot)[0].model for slot in ALL_SLOTS} == {
        "stat": "haiku",
        "scene": "haiku",
        "ending": "sonnet",
        "image": "haiku",
        "summary": "sonnet",
        "episode": "haiku",
        "fact": "opus",
    }
    # 장면 헤더는 자기 행이 없어 스탯 판정 행을 물려받는다.
    assert opus.scene is opus.stat
    assert opus.routes["scene"].source == "inherited"
    assert opus.call_model("stat") == "gemini" and opus.call_model("scene") == "gemini"
    for other in (gemini, character):
        assert all(getattr(other, slot) is gemini_set for slot in ALL_SLOTS)
        assert all(other.call_model(slot) is None for slot in ALL_SLOTS)
    # 같은 모델의 세트는 한 번만 읽는다.
    assert sorted(store.loads) == ["haiku", "opus", "sonnet"]


async def test_scene_judgment_follows_its_own_row_over_the_stat_row(monkeypatch: pytest.MonkeyPatch) -> None:
    fix_settings(monkeypatch, profile="gemini", premium=True)
    store = FakeSetStore(monkeypatch)
    routes = PromptRoutes.from_rows([_row("scene_judgment", room_model="gemini", chain_model="haiku")])

    sets = await turn_prompt.judgment_prompt_sets(
        lane="story", gemini_set=store.sets["gemini"], load=store.load, routes=routes, room_model="gemini"
    )

    assert sets.scene[0].model == "haiku"
    assert sets.stat is store.sets["gemini"]
    assert sets.routes["scene"].source == "row" and sets.routes["stat"].source == "env"


async def test_the_image_slot_reads_the_image_stage_of_the_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    """스토리의 그림 판정은 미디어 북 칸, 캐릭터는 상황 이미지다. 다른 레인의 그림 단계 행은 그 레인 칸에 닿지 않는다."""
    fix_settings(monkeypatch, profile="gemini", premium=True)
    store = FakeSetStore(monkeypatch)
    routes = PromptRoutes.from_rows(
        [
            _row("media_book_image", lane="story", chain_model="haiku"),
            _row("situational_image", lane="character", chain_model="sonnet"),
        ]
    )
    gemini_set = store.sets["gemini"]

    story = await turn_prompt.judgment_prompt_sets(
        lane="story", gemini_set=gemini_set, load=store.load, routes=routes, room_model="opus"
    )
    character = await turn_prompt.judgment_prompt_sets(
        lane="character", gemini_set=gemini_set, load=store.load, routes=routes, room_model="opus"
    )

    assert story.image[0].model == "haiku"
    assert character.image[0].model == "sonnet"
    assert story.stat is gemini_set and character.stat is gemini_set


async def test_a_row_the_env_can_no_longer_serve_falls_back_to_the_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """행의 경로가 지금 env 배정으로 푼 경로와 다르면 그 행을 건너뛰고 env 규칙의 세트를 읽는다."""
    fix_settings(monkeypatch, profile="gemini", premium=True)
    store = FakeSetStore(monkeypatch)
    routes = PromptRoutes.from_rows([_row("stat_judgment", chain_model="haiku", call_model="haiku", backend="anthropic")])

    sets = await turn_prompt.judgment_prompt_sets(
        lane="story", gemini_set=store.sets["gemini"], load=store.load, routes=routes, room_model="opus"
    )

    assert sets.stat is store.sets["gemini"]
    skipped = sets.routes["stat"].skipped
    assert skipped is not None and skipped.reason == "backend-mismatch"
    assert sets.call_model("stat") is None
    assert store.loads == []


async def test_a_lane_outside_the_chat_lanes_is_a_caller_bug(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeSetStore(monkeypatch)

    with pytest.raises(ValueError, match="novel"):
        await turn_prompt.judgment_prompt_sets(lane="novel", gemini_set=store.sets["gemini"], load=store.load)


# ── 방 턴: 실효 모델 한 번, 판정 세트와 차감이 같은 값 ─────────────────────────────────────────


async def put_rows(db_session: AsyncSession, *rows: RouteRow) -> None:
    for row in rows:
        db_session.add(
            PromptRoute(
                lane=row.lane,
                room_model=row.room_model,
                stage=row.stage,
                chain_model=row.chain_model,
                call_model=row.call_model,
                backend=row.backend,
            )
        )
    await db_session.commit()


@pytest.mark.parametrize(
    ("stored", "switch", "expected_stat", "expected_ledger"),
    [
        pytest.param("opus", True, "haiku", [["chat_spend", -clover.CHAT_TURN_COST_OPUS]], id="opus-on"),
        pytest.param("opus", False, "gemini", [], id="opus-off"),
        pytest.param("gemini", True, "gemini", [], id="gemini-room"),
    ],
)
@pytest.mark.parametrize("surface", SURFACES)
async def test_judgment_sets_and_the_charge_follow_the_effective_room_model(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    stored: str,
    switch: bool,
    expected_stat: str,
    expected_ledger: list[list[Any]],
    surface: str,
) -> None:
    """Opus 방 칸의 행은 스위치가 켜져 Opus 로 도는 턴에만 쓰인다. 스위치를 끈 Opus 저장 방은 판정 세트도 차감도 Gemini 방
    칸이다 — 저장값이 아니라 지금 쓸 모델로 표를 본다."""
    fix_settings(monkeypatch, profile="gemini", premium=switch)
    room_id, user_id = await open_room(db_client, db_session, lane="story", stored=stored)
    await put_rows(db_session, _row("stat_judgment", room_model="opus", chain_model="haiku"))
    sets = record_judgment_sets(monkeypatch)
    fake = RecordingLLM()

    resp = await turn_request(db_client, db_session, fake, room_id, surface)

    assert resp.status_code == 200
    assert _parse_sse_events(resp.text)[-1]["type"] == "done"
    assert [slots["stat"] for slots in sets] == [expected_stat]
    assert await ledger(db_session, user_id) == expected_ledger
    generation = [model for site, model in fake.calls if site == "chat_generate"]
    assert generation == ["opus" if expected_ledger else "gemini"]


@pytest.mark.parametrize("surface", SURFACES)
async def test_one_request_reads_the_effective_room_model_once_for_the_sets_and_the_charge(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, surface: str
) -> None:
    """허용 판정이 요청 중간에 바뀌어도 판정 세트와 차감은 한 번 읽은 같은 값을 쓴다."""
    fix_settings(monkeypatch, profile="gemini", premium=True)
    room_id, user_id = await open_room(db_client, db_session, lane="story", stored="opus")
    await put_rows(db_session, _row("stat_judgment", room_model="opus", chain_model="haiku"))
    answers = [True, False]
    asked: list[bool] = []

    async def _flipping(db: Any, user: Any) -> bool:
        answer = answers[len(asked)] if len(asked) < len(answers) else False
        asked.append(answer)
        return answer

    monkeypatch.setattr(model_access, "has_chat_premium_access", _flipping)
    sets = record_judgment_sets(monkeypatch)
    fake = RecordingLLM()

    resp = await turn_request(db_client, db_session, fake, room_id, surface)

    assert resp.status_code == 200
    assert asked == [True]
    assert [slots["stat"] for slots in sets] == ["haiku"]
    assert await ledger(db_session, user_id) == [["chat_spend", -clover.CHAT_TURN_COST_OPUS]]
    assert [model for site, model in fake.calls if site == "chat_generate"] == ["opus"]


async def test_a_row_whose_chain_is_gone_fails_before_the_stream_without_charging(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """행이 가리킨 체인의 게시본이 저장 뒤 사라졌으면 판정 세트가 없을 때와 같다 — 스트림 전 오류이고 깎지 않는다."""
    fix_settings(monkeypatch, profile="gemini", premium=True)
    room_id, user_id = await open_room(db_client, db_session, lane="story", stored="opus")
    await put_rows(db_session, _row("memory_summary", room_model="opus", chain_model="haiku"))
    await db_session.execute(
        update(PromptSet).where(PromptSet.lane == "story", PromptSet.model == "haiku").values(status="archived")
    )
    await db_session.commit()
    fake = RecordingLLM()

    with pytest.raises(PromptSetNotFoundError, match="haiku"):
        await turn_request(db_client, db_session, fake, room_id, "send")

    assert fake.calls == []
    assert await ledger(db_session, user_id) == []


@pytest.mark.parametrize("warm", [True, False], ids=["hit", "miss"])
async def test_one_turn_reads_the_route_table_once(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    expected: dict[str, Any],
    warm: bool,
) -> None:
    """빈 표에서 한 턴은 배정 표 캐시를 한 번 본다. 데운 캐시면 DB 문장 수가 표를 읽기 전과 같고, 식은 캐시면 표 SELECT 하나가
    더해지고 캐시를 채운다."""
    fix_settings(monkeypatch, profile="gemini", premium=True)
    room_id, _ = await open_room(db_client, db_session, lane="story", stored="gemini")
    if warm:
        await load_prompt_routes(db_session)
        await db_session.commit()
    redis = RedisRecorder(monkeypatch)

    with _count_queries() as statements:
        resp = await turn_request(db_client, db_session, RecordingLLM(), room_id, "send")
        db_statements = statements()

    assert resp.status_code == 200
    base = expected[scenario_id("gemini", "story", "gemini", True, "send")]
    assert redis.route_table == (["GET"] if warm else ["GET", "SET"])
    assert db_statements == base["db_statements"] + (0 if warm else 1)
    assert redis.other == base["redis_commands"]
