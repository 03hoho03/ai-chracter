"""판정·요약·추출 호출이 모델 배정 표가 정한 모델로 실제로 가는 것 — 빈 표의 특성 기대값부터.

라우터(`RoutingLLMClient`)와 세 공급자 구현을 그대로 두고 SDK 자리만 가짜로 바꿔 끼운다. 그래서 적는 것은 호출마다 그 구현의
SDK 가 받은 모델 id, 그 구현이 사용량을 기록한 (호출 위치, 모델 id) — 사용량 해시 필드의 앞 두 칸이다 — 그리고 측정 덤프 줄의
모델 칸과, 라우터가 "모델을 고를 수 없는 호출에 다른 모델이 실려 왔다"고 남긴 경고 수다. 덤프 줄의 프롬프트 본문은 적지 않는다.

기대값 파일(`fixtures/chat_call_model_characterization.json`)은 판정·요약 호출이 표의 부를 모델을 받기 전 코드에서 만들었다. 그
코드의 src 를 `sys.path` 맨 앞에 두고 이 모듈의 `observe` 를 시나리오마다 돌려 그대로 적었다. 그래서 `observe` 와 그 도우미는
그때 코드에도 있던 이름만 쓴다. 기대값을 다시 만들어야 한다면 같은 방식으로 그 전 코드에서 만들어야 한다 — 지금 코드로 만들면
대조가 항진명제가 된다.

시나리오: 스토리 방(장면 헤더를 켠 작품, 칸 하나·게이트 1 엔딩 하나)의 보내기·재생성·수정, 캐릭터 방(상황 이미지 하나)의 30턴
보내기(요약 접기와 장면·사실 기억 추출이 뒤따른다)와 재생성, 각각 Gemini 방과 Opus 방(상위 모델 스위치 켬). 그리고 빌더 스토리
미리보기 한 턴. 판정·요약 모델 설정과 배정은 세 벌 — 전부 Gemini, 전부 Haiku 에 배정 없음(Bedrock), 전부 Haiku 에 판정·요약
호출 위치를 Anthropic 직결로 둔 배정(운영과 같은 모양).

출력에 영향을 주는 설정은 `FIXED_SETTINGS`·`PROFILES` 리터럴로 고정한다 — env 나 로컬 `.env` 값에 기대지 않는다.
"""

import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import (
    EndingJudgmentResult,
    ImageMatchJudgmentResult,
    MemoryEpisodeResult,
    MemoryFactResult,
    MemorySummaryResult,
    SceneJudgmentResult,
    StatRuleJudgmentResult,
    load_active_prompt_set,
)
from api.chat import memory_fold
from api.chat.prompt_stages import LANE_STAGES, RoutingLane
from api.core import clover
from api.core.config import settings
from api.db.models import AssetStatus, ChatMessage, ChatMessageRole, ChatRoom
from api.db.models.chat import ChatRoomMemorySnapshot, ChatTurn
from api.db.models.prompt import PromptRoute
from api.db.models.story import StoryVersionDetail
from api.llm import anthropic_api as anthropic_module
from api.llm import bedrock as bedrock_module
from api.llm import gemini as gemini_module
from api.llm.anthropic_api import AnthropicLLMClient
from api.llm.bedrock import BedrockLLMClient
from api.llm.chat_models import PromptSetModelId
from api.llm.client import LLMCallContext, LLMClient
from api.llm.gemini import GeminiLLMClient
from api.llm.routing import RoutingLLMClient
from factories import (
    _add_room_cell_and_endings,
    _add_room_situational_image,
    _clear_llm_override,
    _login_as,
    _make_asset,
    _make_user_with_clover_lot,
    _open_room,
    _override_llm_client,
    _parse_sse_events,
    _preview_story_payload,
)

FIXTURE = Path(__file__).parent / "fixtures" / "chat_call_model_characterization.json"

FIXED_SETTINGS: dict[str, Any] = {
    "gemini_model_name": "fixture-gemini-base",
    "gemini_stat_judgment_model_name": "fixture-gemini-stat",
    "gemini_ending_judgment_model_name": "fixture-gemini-ending",
    "gemini_image_judgment_model_name": None,
    "gemini_seed": None,
    "bedrock_sonnet_model_id": "fixture-bedrock-sonnet",
    "bedrock_opus_model_id": "fixture-bedrock-opus",
    "bedrock_haiku_model_id": "fixture-bedrock-haiku",
    "anthropic_sonnet_model_id": "fixture-anthropic-sonnet",
    "anthropic_opus_model_id": "fixture-anthropic-opus",
    "anthropic_haiku_model_id": "fixture-anthropic-haiku",
    "anthropic_chat_effort": "low",
    "anthropic_structured_effort": "low",
    "chat_premium_models_enabled": True,
    "memory_window_generation": True,
    "memory_window_ending_judgment": True,
    "memory_window_image_judgment": True,
    "memory_episodes_extract": True,
    "memory_facts_extract": True,
    "memory_episodes_recall": False,
    "memory_facts_inject": False,
    "memory_knowledge_filter": False,
    "memory_summary_secret_marking": False,
    "memory_embed_write": False,
    "memory_embed_recall": False,
    "identity_gate_enabled": False,
    "payments_enabled": False,
}

JUDGMENT_MODEL_SETTINGS = (
    "stat_judgment_model",
    "ending_judgment_model",
    "image_judgment_model",
    "memory_summary_model",
    "memory_episode_model",
    "memory_fact_model",
)

# 운영처럼 판정·요약·추출 호출 위치(채팅·미리보기)와 상위 모델 글쓰기 호출을 Anthropic 직결로 둔 배정.
_DIRECT_ASSIGNMENT = {
    call_site: "anthropic"
    for call_site in (
        "chat_generate",
        "replay_generate",
        "novelize_chapter",
        "chat_stat_judgment",
        "chat_ending_judgment",
        "chat_situational_image",
        "chat_media_book_image",
        "chat_memory_summary",
        "chat_memory_episode",
        "chat_memory_fact",
        "preview_stat_judgment",
        "preview_ending_judgment",
        "preview_media_book_image",
    )
}

# 프로필 이름 → (판정·요약 모델, 호출 위치 배정).
PROFILES: dict[str, tuple[str, dict[str, str]]] = {
    "gemini": ("gemini", {}),
    "haiku-bedrock": ("haiku", {}),
    "haiku-direct": ("haiku", _DIRECT_ASSIGNMENT),
}

ROOM_SURFACES = ("story-send", "story-regenerate", "story-edit", "character-send", "character-regenerate")
ROOM_MODELS = ("gemini", "opus")

SCENARIOS: list[tuple[str, str, str]] = [
    *((profile, surface, room) for profile in PROFILES for surface in ROOM_SURFACES for room in ROOM_MODELS),
    *((profile, "preview-story", "gemini") for profile in PROFILES),
]


def scenario_id(profile: str, surface: str, room: str) -> str:
    return f"{profile}-{surface}-{room}"


def fix_settings(monkeypatch: pytest.MonkeyPatch, profile: str, dump_path: Path) -> None:
    for name, value in FIXED_SETTINGS.items():
        monkeypatch.setattr(settings, name, value)
    model, assignment = PROFILES[profile]
    for name in JUDGMENT_MODEL_SETTINGS:
        monkeypatch.setattr(settings, name, model)
    monkeypatch.setattr(settings, "llm_call_site_backends", dict(assignment))
    monkeypatch.setattr(settings, "prompt_dump_path", str(dump_path))


# ── 공급자 SDK 자리의 가짜 ─────────────────────────────────────────────────────────────────

# 구조화 호출의 응답. 판정은 모두 "아무것도 바뀌지 않음", 요약은 고정 문장, 추출은 빈 목록이다.
ANSWERS: dict[type, Any] = {
    StatRuleJudgmentResult: StatRuleJudgmentResult(fired_rule_ids=[]),
    EndingJudgmentResult: EndingJudgmentResult(triggered=False),
    ImageMatchJudgmentResult: ImageMatchJudgmentResult(matched_image_entity_id=None),
    SceneJudgmentResult: SceneJudgmentResult(place=None, time=None),
    MemorySummaryResult: MemorySummaryResult(summary="요약"),
    MemoryEpisodeResult: MemoryEpisodeResult(episodes=[]),
    MemoryFactResult: MemoryFactResult(facts=[]),
}


def _claude_usage() -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=1,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
        output_tokens=1,
        output_tokens_details=None,
    )


class ProviderSdks:
    """세 구현을 실제 클래스로 만들고 SDK 자리만 바꿔 끼운다. 받은 것을 적는다.

    - `sent`: (구현, SDK 가 받은 모델 id)
    - `recorded`: (구현, 사용량 기록의 호출 위치, 모델 id) — 사용량 해시 필드의 앞 두 칸과 같은 값이다
    - `answers`: 구조화 호출이 돌려줄 응답(스키마 → 값). 테스트가 바꿀 수 있다."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.sent: list[tuple[str, str]] = []
        self.recorded: list[tuple[str, str, str]] = []
        self.answers: dict[type, Any] = dict(ANSWERS)

        def recorder(backend: str) -> Callable[..., Awaitable[None]]:
            async def record_usage(call_site: str, model: str, usage_metadata: object | None) -> None:
                self.recorded.append((backend, call_site, model))

            return record_usage

        monkeypatch.setattr(gemini_module, "record_usage", recorder("gemini"))
        monkeypatch.setattr(bedrock_module, "record_usage", recorder("bedrock"))
        monkeypatch.setattr(anthropic_module, "record_usage", recorder("anthropic"))

        def parse(message: Any, schema: type, provider: str, label: str) -> Any:
            return self.answers[schema]

        monkeypatch.setattr(bedrock_module, "parse_structured", parse)
        monkeypatch.setattr(anthropic_module, "parse_structured", parse)

        self.gemini = GeminiLLMClient(api_key="test-key")
        monkeypatch.setattr(
            self.gemini,
            "_client",
            SimpleNamespace(
                aio=SimpleNamespace(
                    models=SimpleNamespace(
                        generate_content_stream=self._gemini_stream, generate_content=self._gemini_structured
                    )
                )
            ),
        )
        self.bedrock = BedrockLLMClient()
        monkeypatch.setattr(
            self.bedrock, "_client", SimpleNamespace(messages=SimpleNamespace(create=self._claude("bedrock")))
        )
        self.anthropic = AnthropicLLMClient()
        monkeypatch.setattr(
            self.anthropic, "_client", SimpleNamespace(messages=SimpleNamespace(create=self._claude("anthropic")))
        )

    async def _gemini_stream(self, **kwargs: Any) -> AsyncIterator[SimpleNamespace]:
        self.sent.append(("gemini", kwargs["model"]))

        async def chunks() -> AsyncIterator[SimpleNamespace]:
            yield SimpleNamespace(
                text="응답",
                candidates=[SimpleNamespace(finish_reason="STOP")],
                usage_metadata=None,
                prompt_feedback=None,
            )

        return chunks()

    async def _gemini_structured(self, **kwargs: Any) -> SimpleNamespace:
        self.sent.append(("gemini", kwargs["model"]))
        return SimpleNamespace(parsed=self.answers[kwargs["config"].response_schema], usage_metadata=None)

    def _claude(self, backend: str) -> Callable[..., Awaitable[Any]]:
        async def create(**kwargs: Any) -> Any:
            self.sent.append((backend, kwargs["model"]))
            if not kwargs.get("stream"):
                return SimpleNamespace(usage=_claude_usage(), stop_reason="end_turn", content=[])

            async def stream() -> AsyncIterator[SimpleNamespace]:
                yield SimpleNamespace(type="message_start", message=SimpleNamespace(usage=_claude_usage()))
                yield SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="응답"))
                yield SimpleNamespace(
                    type="message_delta",
                    delta=SimpleNamespace(stop_reason="end_turn"),
                    usage=SimpleNamespace(
                        output_tokens=1,
                        input_tokens=None,
                        cache_read_input_tokens=None,
                        cache_creation_input_tokens=None,
                    ),
                )

            return stream()

        return create

    def client(self) -> RoutingLLMClient:
        return RoutingLLMClient(
            self.gemini, factories={"bedrock": lambda: self.bedrock, "anthropic": lambda: self.anthropic}
        )


class RoutingWarnings(logging.Handler):
    """라우터가 "모델을 고를 수 없는 호출에 다른 모델이 실려 왔다"고 남긴 경고를 센다."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:
        self.count += 1


@pytest.fixture
def routing_warnings() -> Iterator[RoutingWarnings]:
    handler = RoutingWarnings()
    logger = logging.getLogger("api.llm.routing")
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)


# ── 시나리오 ───────────────────────────────────────────────────────────────────────────────


async def _enable_scene_header(db_session: AsyncSession, room_id: uuid.UUID) -> None:
    version_id = await db_session.scalar(select(ChatRoom.content_version_id).where(ChatRoom.id == room_id))
    await db_session.execute(
        update(StoryVersionDetail)
        .where(StoryVersionDetail.content_version_id == version_id)
        .values(scene_header_enabled=True)
    )
    await db_session.commit()


async def _last_user_message_id(db_session: AsyncSession, room_id: uuid.UUID) -> uuid.UUID:
    message_id = await db_session.scalar(
        select(ChatMessage.id)
        .where(ChatMessage.chat_room_id == room_id, ChatMessage.role == ChatMessageRole.USER)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
    )
    assert message_id is not None
    return message_id


async def prepare(
    db_client: httpx.AsyncClient, db_session: AsyncSession, surface: str, room_model: str
) -> tuple[str, str, dict[str, object] | None]:
    """시나리오의 방(또는 미리보기 세션)을 만들고 보낼 요청 (메서드, 경로, 본문)을 돌려준다."""
    user = await _make_user_with_clover_lot(db_session, clover_balance=1000)
    await db_session.commit()
    if surface == "preview-story":
        asset = await _make_asset(db_session, owner_user_id=user.id, status=AssetStatus.READY)
        await db_session.commit()
        await _login_as(db_client, user.id)
        _, payload = _preview_story_payload(asset.id)
        payload["sceneHeaderEnabled"] = True
        started = await db_client.post("/preview-sessions", json=payload)
        assert started.status_code == 201, started.text
        return "POST", f"/preview-sessions/{started.json()['previewSessionId']}/messages", {"content": "행복해지자"}

    lane, action = surface.split("-")
    turns = 30 if surface == "character-send" else 1
    room = await _open_room(db_client, db_session, turns=turns, lane=lane, user=user)
    if lane == "story":
        await _add_room_cell_and_endings(db_session, room.room_id, (1,))
        await _enable_scene_header(db_session, room.room_id)
    else:
        await _add_room_situational_image(db_session, room.room_id)
    await db_session.execute(update(ChatRoom).where(ChatRoom.id == room.room_id).values(chat_model=room_model))
    await db_session.commit()
    if action == "send":
        return "POST", f"/chat-rooms/{room.room_id}/messages", {"content": "골목으로 가자"}
    if action == "regenerate":
        return "POST", f"/chat-rooms/{room.room_id}/regenerate", None
    target = await _last_user_message_id(db_session, room.room_id)
    return "PATCH", f"/chat-rooms/{room.room_id}/messages/{target}", {"content": "고쳐 말하면, 골목으로 가자"}


def _dump_lines(dump_path: Path) -> list[list[Any]]:
    """덤프 줄마다 (종류, 호출 위치, 고른 모델, 보낸 모델 id). 프롬프트·지시문 본문은 읽지 않는다."""
    if not dump_path.exists():
        return []
    lines = []
    for raw in dump_path.read_text(encoding="utf-8").splitlines():
        record = json.loads(raw)
        lines.append([record["kind"], record.get("callSite"), record.get("chatModel"), record["model"]])
    return sorted(lines, key=json.dumps)


async def observe(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    warnings: RoutingWarnings,
    *,
    profile: str,
    surface: str,
    room_model: str,
    sdks: ProviderSdks | None = None,
) -> dict[str, Any]:
    dump_path = tmp_path / "dump.jsonl"
    fix_settings(monkeypatch, profile, dump_path)
    method, path, body = await prepare(db_client, db_session, surface, room_model)
    if sdks is None:
        sdks = ProviderSdks(monkeypatch)
    _override_llm_client(sdks.client())
    try:
        resp = await db_client.request(method, path, json=body)
    finally:
        _clear_llm_override()
    events = _parse_sse_events(resp.text) if resp.status_code == 200 else []
    return {
        "status": resp.status_code,
        "last_event": events[-1]["type"] if events else None,
        "sent": sorted([list(item) for item in sdks.sent], key=json.dumps),
        "recorded": sorted([list(item) for item in sdks.recorded], key=json.dumps),
        "dump": _dump_lines(dump_path),
        "routing_warnings": warnings.count,
    }


@pytest.fixture(scope="module")
def expected() -> Iterator[dict[str, Any]]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert data["fixed_settings"] == json.loads(json.dumps(FIXED_SETTINGS))
    assert data["profiles"] == json.loads(json.dumps(PROFILES))
    assert sorted(data["scenarios"]) == sorted(scenario_id(*case) for case in SCENARIOS)
    yield data["scenarios"]


@pytest.mark.parametrize(("profile", "surface", "room_model"), SCENARIOS, ids=[scenario_id(*c) for c in SCENARIOS])
async def test_empty_route_table_calls_match_the_characterization(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    routing_warnings: RoutingWarnings,
    expected: dict[str, Any],
    profile: str,
    surface: str,
    room_model: str,
) -> None:
    observed = await observe(
        db_client,
        db_session,
        monkeypatch,
        tmp_path,
        routing_warnings,
        profile=profile,
        surface=surface,
        room_model=room_model,
    )

    assert observed == expected[scenario_id(profile, surface, room_model)]


# ── 행이 있는 표: 판정·요약·추출 호출이 행의 부를 모델로 간다 ─────────────────────────────────────


def route(lane: str, room_model: str, stage: str, call_model: str, backend: str) -> PromptRoute:
    """Haiku 체인을 읽고 `call_model` 을 `backend` 로 부르는 행."""
    return PromptRoute(
        lane=lane, room_model=room_model, stage=stage, chain_model="haiku", call_model=call_model, backend=backend
    )


async def put_routes(db_session: AsyncSession, routes: list[PromptRoute]) -> None:
    db_session.add_all(routes)
    await db_session.commit()


def with_row_calls(base: dict[str, Any], row_calls: dict[str, tuple[str, str]]) -> dict[str, Any]:
    """빈 표의 특성 기대값에서 행이 적용된 호출 위치만 (구현, 모델 id) 를 바꾼 기대값. SDK 가 받은 id 와 덤프 줄의 모델 칸도 같은
    값으로 바뀐다."""
    recorded = [
        [row_calls[call_site][0], call_site, row_calls[call_site][1]] if call_site in row_calls else [b, call_site, m]
        for b, call_site, m in base["recorded"]
    ]
    dump = [
        [kind, call_site, chat_model, row_calls[call_site][1] if call_site in row_calls else model]
        for kind, call_site, chat_model, model in base["dump"]
    ]
    return {
        **base,
        "recorded": sorted(recorded, key=json.dumps),
        "sent": sorted([[b, m] for b, _, m in recorded], key=json.dumps),
        "dump": sorted(dump, key=json.dumps),
    }


# 스토리 방의 판정 넷 — 단계 → (부를 모델, 경로), 호출 위치 → 기대하는 (구현, 보낸 id). 엔딩은 Gemini 로 되돌리는 행이라 Gemini
# 구현이 판정 종류의 Gemini 모델 스위치를 그대로 적용한다.
STORY_ROWS = {
    "stat_judgment": ("opus", "anthropic"),
    "scene_judgment": ("sonnet", "anthropic"),
    "ending_judgment": ("gemini", "gemini"),
    "media_book_image": ("sonnet", "anthropic"),
}
STORY_ROW_CALLS = {
    "chat_stat_judgment": ("anthropic", "fixture-anthropic-opus"),
    "chat_scene_judgment": ("anthropic", "fixture-anthropic-sonnet"),
    "chat_ending_judgment": ("gemini", "fixture-gemini-ending"),
    "chat_media_book_image": ("anthropic", "fixture-anthropic-sonnet"),
}
# 캐릭터 방의 그림 판정과 접기·두 추출.
CHARACTER_ROWS = {
    "situational_image": ("opus", "anthropic"),
    "memory_summary": ("sonnet", "anthropic"),
    "memory_episode": ("gemini", "gemini"),
    "memory_fact": ("opus", "anthropic"),
}
CHARACTER_ROW_CALLS = {
    "chat_situational_image": ("anthropic", "fixture-anthropic-opus"),
    "chat_memory_summary": ("anthropic", "fixture-anthropic-sonnet"),
    "chat_memory_episode": ("gemini", "fixture-gemini-base"),
    "chat_memory_fact": ("anthropic", "fixture-anthropic-opus"),
}
_LANE_STAGE_NAMES: dict[str, tuple[str, ...]] = {lane: tuple(stages) for lane, stages in LANE_STAGES.items()}
_OTHER_ROOM = {"gemini": "opus", "opus": "gemini"}
_OTHER_LANE = {"story": "character", "character": "story"}
_LANE_CASES = {
    "story": ("story-edit", STORY_ROWS, STORY_ROW_CALLS),
    "character": ("character-send", CHARACTER_ROWS, CHARACTER_ROW_CALLS),
}


@pytest.mark.parametrize("room_model", ROOM_MODELS)
@pytest.mark.parametrize("lane", ["story", "character"])
@pytest.mark.parametrize("rows_at", ["own-cell", "other-room", "other-lane"])
async def test_judgment_summary_and_extraction_calls_go_to_the_model_their_row_calls(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    routing_warnings: RoutingWarnings,
    expected: dict[str, Any],
    room_model: str,
    lane: str,
    rows_at: str,
) -> None:
    """행이 있는 칸의 호출은 행의 부를 모델로, 행이 고른 구현에 가고, SDK 가 받은 id·사용량 기록의 모델 칸·덤프 줄의 모델 칸이
    모두 그 모델의 id 다. 라우터는 경고를 남기지 않는다(라우터와 구현이 같은 모델을 본다). 다른 방 모델이나 다른 레인의 칸에 둔
    행은 이 턴의 호출을 바꾸지 않는다."""
    surface, rows, row_calls = _LANE_CASES[lane]
    rows_lane = _OTHER_LANE[lane] if rows_at == "other-lane" else lane
    rows_room = _OTHER_ROOM[room_model] if rows_at == "other-room" else room_model
    # 다른 레인에 둘 때는 그 레인에 있는 단계의 행만 둔다(캐릭터 레인에는 스탯·장면 헤더·엔딩·미디어 북 단계가 없다).
    await put_routes(
        db_session,
        [
            route(rows_lane, rows_room, stage, *pair)
            for stage, pair in rows.items()
            if stage in _LANE_STAGE_NAMES[rows_lane]
        ],
    )

    observed = await observe(
        db_client,
        db_session,
        monkeypatch,
        tmp_path,
        routing_warnings,
        profile="haiku-direct",
        surface=surface,
        room_model=room_model,
    )

    base = expected[scenario_id("haiku-direct", surface, room_model)]
    assert observed == (with_row_calls(base, row_calls) if rows_at == "own-cell" else base)


async def test_an_empty_summary_from_the_row_model_is_tagged_with_the_backend_it_went_to(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    routing_warnings: RoutingWarnings,
) -> None:
    """요약 칸의 행이 Gemini 로 부르고 env 의 요약 모델은 Anthropic 직결 Haiku 일 때, 빈 요약 실패의 공급자 태그는 요약이 실제로
    간 Gemini 다."""
    await put_routes(db_session, [route("character", "gemini", "memory_summary", "gemini", "gemini")])
    # 구현은 만들 때 기본 모델 설정을 읽으므로 설정을 먼저 고정한다.
    fix_settings(monkeypatch, "haiku-direct", tmp_path / "dump.jsonl")
    sdks = ProviderSdks(monkeypatch)
    sdks.answers[MemorySummaryResult] = MemorySummaryResult(summary="   ")
    tags: list[str] = []
    monkeypatch.setattr(memory_fold, "capture_dependency_failure", lambda exc, *, dependency: tags.append(dependency))

    observed = await observe(
        db_client,
        db_session,
        monkeypatch,
        tmp_path,
        routing_warnings,
        profile="haiku-direct",
        surface="character-send",
        room_model="gemini",
        sdks=sdks,
    )

    assert ["gemini", "chat_memory_summary", "fixture-gemini-base"] in observed["recorded"]
    assert tags == ["gemini"]


async def test_summary_regeneration_calls_the_model_of_the_summary_row(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """요약 다시 만들기도 요약 칸 행의 부를 모델로 부른다."""
    fix_settings(monkeypatch, "haiku-direct", tmp_path / "dump.jsonl")
    monkeypatch.setattr(settings, "memory_items_visible", True)
    await put_routes(db_session, [route("character", "gemini", "memory_summary", "sonnet", "anthropic")])
    user = await _make_user_with_clover_lot(db_session, clover_balance=1000)
    room = await _open_room(db_client, db_session, turns=25, user=user)
    for turn, text in ((10, "앞 요약"), (20, "AI가 접은 요약")):
        assistant = room.turns[turn][1]
        db_session.add(
            ChatRoomMemorySnapshot(
                chat_room_id=room.room_id,
                cursor_created_at=assistant.created_at,
                cursor_message_id=assistant.id,
                summary_text=text,
                source="auto",
            )
        )
        await db_session.commit()
    sdks = ProviderSdks(monkeypatch)
    _override_llm_client(sdks.client())
    try:
        resp = await db_client.post(
            f"/chat-rooms/{room.room_id}/memory/summary/regenerate",
            json={"version": 0, "expectedCost": clover.MEMORY_SUMMARY_REGENERATE_COST},
        )
    finally:
        _clear_llm_override()

    assert resp.status_code == 200, resp.text
    assert sdks.recorded == [("anthropic", "chat_memory_summary", "fixture-anthropic-sonnet")]
    assert sdks.sent == [("anthropic", "fixture-anthropic-sonnet")]


# ── 빈 표·건너뛴 행에서는 호출에 부를 모델이 실리지 않는다 ─────────────────────────────────────────


class UsageCapture(LLMClient):
    """라우터 앞에서 호출마다 받은 `LLMCallContext` 를 모으고 그대로 넘긴다."""

    def __init__(self, inner: LLMClient) -> None:
        self.inner = inner
        self.usages: list[LLMCallContext] = []

    def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.usages.append(usage)
        return self.inner.generate(prompt, system_instruction, stop_sequences, usage=usage)

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.usages.append(usage)
        return await self.inner.generate_structured(prompt, response_schema, images, usage=usage)


@pytest.mark.parametrize("table", ["empty", "skipped-rows"])
@pytest.mark.parametrize(("surface", "room_model"), [(s, r) for profile, s, r in SCENARIOS if profile == "gemini"])
async def test_no_call_carries_a_call_model_when_no_row_applies(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    routing_warnings: RoutingWarnings,
    expected: dict[str, Any],
    surface: str,
    room_model: str,
    table: str,
) -> None:
    """표가 비었거나, 행이 있어도 지금 env 배정으로는 그 경로로 갈 수 없어 건너뛰면(배정 없는 env 에서 Anthropic 직결 행) 모든
    호출의 `call_model` 이 None 이고 호출은 빈 표의 특성 기대값과 같다."""
    if table == "skipped-rows":
        await put_routes(
            db_session,
            [
                route(lane, room_model, stage, "opus", "anthropic")
                for lane, stages in _LANE_STAGE_NAMES.items()
                for stage in stages
                if stage != "chat_generate"
            ],
        )
    fix_settings(monkeypatch, "gemini", tmp_path / "dump.jsonl")
    sdks = ProviderSdks(monkeypatch)
    capture = UsageCapture(sdks.client())
    monkeypatch.setattr(sdks, "client", lambda: capture)

    observed = await observe(
        db_client,
        db_session,
        monkeypatch,
        tmp_path,
        routing_warnings,
        profile="gemini",
        surface=surface,
        room_model=room_model,
        sdks=sdks,
    )

    assert observed == expected[scenario_id("gemini", surface, room_model)]
    assert len(capture.usages) == len(observed["recorded"])
    assert {usage.call_model for usage in capture.usages} == {None}


# ── 턴 기록의 단계별 배정과, 행이 적용된 호출의 덤프 키 ──────────────────────────────────────────


async def _set_id(db_session: AsyncSession, lane: RoutingLane, model: PromptSetModelId) -> str:
    prompt_set, _ = await load_active_prompt_set(db_session, lane=lane, model=model)
    return str(prompt_set.id)


_DUMP_ROUTE_KEYS = ("promptSetId", "chainModel", "routeSource")


@pytest.mark.parametrize("generation_row", ["applied", "skipped"])
async def test_a_room_turn_records_each_stages_route_and_dumps_set_keys_only_for_calls_a_row_applied_to(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    generation_row: str,
) -> None:
    """Opus 스토리 방의 수정 한 턴(엔딩 판정까지 부른다). 생성 행(Opus 를 Anthropic 직결로)과 스탯 행(Haiku 체인, Opus 를
    Anthropic 직결로)만 둔다.

    턴 기록에는 스토리 레인의 단계 여덟이 차례대로 한 칸씩 남는다 — 스탯은 자기 행, 장면 헤더는 스탯 행을 물려받음(물려준 단계와
    함께), 나머지 판정·요약·추출은 모델 설정. 칸마다 읽은 세트의 id 가 실린다. 생성 행은 생성 호출 위치의 env 배정이 Anthropic
    직결이면 쓰이고, 배정을 빼면 경로가 어긋나 건너뛰어 방 모델의 기본 경로(Bedrock)로 가며 건너뛴 행과 이유가 남는다.

    덤프는 행이 적용된 호출의 줄에만 세트 id·체인·출처 키를 더한다. 건너뛴 생성 행과 모델 설정으로 간 판정 줄에는 없다."""
    dump_path = tmp_path / "dump.jsonl"
    fix_settings(monkeypatch, "haiku-direct", dump_path)
    if generation_row == "skipped":
        assignment = dict(_DIRECT_ASSIGNMENT)
        del assignment["chat_generate"]
        monkeypatch.setattr(settings, "llm_call_site_backends", assignment)
    method, path, body = await prepare(db_client, db_session, "story-edit", "opus")
    room_id = uuid.UUID(path.split("/")[2])
    await put_routes(
        db_session,
        [
            PromptRoute(
                lane="story",
                room_model="opus",
                stage="chat_generate",
                chain_model=None,
                call_model="opus",
                backend="anthropic",
            ),
            route("story", "opus", "stat_judgment", "opus", "anthropic"),
        ],
    )
    sdks = ProviderSdks(monkeypatch)
    _override_llm_client(sdks.client())
    try:
        resp = await db_client.request(method, path, json=body)
    finally:
        _clear_llm_override()
    assert resp.status_code == 200, resp.text
    assert _parse_sse_events(resp.text)[-1]["type"] == "done"

    opus_set = await _set_id(db_session, "story", "opus")
    haiku_set = await _set_id(db_session, "story", "haiku")
    generation: dict[str, object] = {
        "lane": "story",
        "stage": "chat_generate",
        "chainModel": "opus",
        "promptSetId": opus_set,
    }
    if generation_row == "applied":
        generation |= {"callModel": "opus", "backend": "anthropic", "source": "row"}
    else:
        generation |= {
            "callModel": "opus",
            "backend": "bedrock",
            "source": "room",
            "skipped": {"stage": "chat_generate", "reason": "backend-mismatch"},
        }
    stat_row = {
        "lane": "story",
        "chainModel": "haiku",
        "promptSetId": haiku_set,
        "callModel": "opus",
        "backend": "anthropic",
    }
    env = {
        "lane": "story",
        "chainModel": "haiku",
        "promptSetId": haiku_set,
        "callModel": "haiku",
        "backend": "anthropic",
    }
    db_session.expire_all()
    [stage_routes] = (
        await db_session.scalars(select(ChatTurn.stage_routes).where(ChatTurn.chat_room_id == room_id))
    ).all()
    assert stage_routes == [
        generation,
        {**stat_row, "stage": "stat_judgment", "source": "row"},
        {**stat_row, "stage": "scene_judgment", "source": "inherited", "sourceDetail": "stat_judgment"},
        {**env, "stage": "ending_judgment", "source": "env", "sourceDetail": "ENDING_JUDGMENT_MODEL"},
        {**env, "stage": "media_book_image", "source": "env", "sourceDetail": "IMAGE_JUDGMENT_MODEL"},
        {**env, "stage": "memory_summary", "source": "env", "sourceDetail": "MEMORY_SUMMARY_MODEL"},
        {**env, "stage": "memory_episode", "source": "env", "sourceDetail": "MEMORY_EPISODE_MODEL"},
        {**env, "stage": "memory_fact", "source": "env", "sourceDetail": "MEMORY_FACT_MODEL"},
    ]

    dumped = {}
    for raw in dump_path.read_text(encoding="utf-8").splitlines():
        line = json.loads(raw)
        dumped[(line["kind"], line.get("callSite"))] = {key: line[key] for key in _DUMP_ROUTE_KEYS if key in line}
    applied_generation = {"promptSetId": opus_set, "chainModel": "opus", "routeSource": "row"}
    assert dumped == {
        ("generation", None): applied_generation if generation_row == "applied" else {},
        ("judgment", "chat_stat_judgment"): {"promptSetId": haiku_set, "chainModel": "haiku", "routeSource": "row"},
        ("judgment", "chat_scene_judgment"): {
            "promptSetId": haiku_set,
            "chainModel": "haiku",
            "routeSource": "inherited",
        },
        ("judgment", "chat_ending_judgment"): {},
        ("judgment", "chat_media_book_image"): {},
    }
