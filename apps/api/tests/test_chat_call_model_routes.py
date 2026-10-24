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
)
from api.core.config import settings
from api.db.models import AssetStatus, ChatMessage, ChatMessageRole, ChatRoom
from api.db.models.story import StoryVersionDetail
from api.llm import anthropic_api as anthropic_module
from api.llm import bedrock as bedrock_module
from api.llm import gemini as gemini_module
from api.llm.anthropic_api import AnthropicLLMClient
from api.llm.bedrock import BedrockLLMClient
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
