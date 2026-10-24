"""빌더 미리보기 세션의 기본(Gemini) 턴 — 시작·전송·판정 넷·차감·세션 상태를 특성 기대값으로 고정한다.

기대값 파일(`fixtures/preview_session_characterization.json`)은 미리보기가 모델을 고를 수 있게 되기 전 코드에서 만들었다. 그 코드의
src 를 `sys.path` 맨 앞에 두고 이 모듈의 `observe_preview` 를 시나리오마다 돌려 그대로 적었다. 그래서 이 모듈은 그때 코드에도 있던
이름만 쓴다. 기대값을 다시 만들어야 한다면 같은 방식으로 그 전 코드에서 만들어야 한다 — 지금 코드로 만들면 대조가 항진명제가 된다.

시나리오: 초안 둘(스토리 — 스탯 하나·게이트 1 엔딩·미디어 북 칸 하나·장면 헤더 켬, 캐릭터) × 판정 모델 설정과 배정 세 벌(전부
Gemini, 전부 Haiku 에 배정 없음, 전부 Haiku 에 채팅·미리보기 판정 호출 위치를 Anthropic 직결로 둔 배정) × 상위 모델 스위치 켬·꺼짐 ×
시작 요청의 모델 쿼리 없음·`gemini`. 모델 쿼리를 모르던 코드는 쿼리를 무시하므로, 쿼리 `gemini` 의 기대값은 쿼리 없음과 같다.

시나리오마다 적는 것(무작위 id·시각은 자리표시로 바꾼다):

- 시작 응답의 상태와 칸 이름, 시작 직후와 턴 뒤의 Redis 세션 JSON 문자열 그대로,
- 전송 응답의 상태와 SSE 이벤트 전부,
- 판정 세트 칸마다 고른 세트의 모델, 가짜 LLM 이 받은 (호출 위치, 실린 모델, 실린 부를 모델, 그 호출이 갈 구현과 모델 id) 순서,
- 차감 본문이 받은 (모델, 가격, 사용처 종류)와 원장 행,
- 전송 요청 동안 실행된 DB 문장 수와 Redis 명령 수 — 배정 표 캐시를 미리 데우고, 배정 표 키 명령은 세지 않는다(표를 읽는 것은
  지금 코드에만 있는 일이다).

출력에 영향을 주는 설정은 `FIXED_SETTINGS`·`PROFILES` 리터럴로 고정한다 — env 나 로컬 `.env` 값에 기대지 않는다.
"""

import json
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat import router as chat_router
from api.chat import turn_prompt
from api.chat.prompt_builder import (
    EndingJudgmentResult,
    ImageMatchJudgmentResult,
    SceneJudgmentResult,
    StatRuleJudgmentResult,
)
from api.chat.prompt_routing_cache import PROMPT_ROUTES_CACHE_KEY, load_prompt_routes
from api.chat.prompt_set_cache import ACTIVE_PROMPT_SET_KEY_PREFIX
from api.core import rate_limit_gate
from api.core.config import settings
from api.core.redis import redis_client
from api.db.models import AssetStatus
from api.db.models.clover import CloverLedger
from api.llm.client import LLMCallContext, LLMClient
from api.llm.routing import resolve_backend
from factories import (
    _clear_llm_override,
    _count_queries,
    _login_as,
    _make_asset,
    _make_user_with_clover_lot,
    _override_llm_client,
    _parse_sse_events,
    _preview_character_payload,
    _preview_story_payload,
)

FIXTURE = Path(__file__).parent / "fixtures" / "preview_session_characterization.json"

FIXED_SETTINGS: dict[str, Any] = {
    "gemini_model_name": "fixture-gemini-base",
    "bedrock_haiku_model_id": "fixture-bedrock-haiku",
    "bedrock_opus_model_id": "fixture-bedrock-opus",
    "anthropic_haiku_model_id": "fixture-anthropic-haiku",
    "anthropic_opus_model_id": "fixture-anthropic-opus",
    "identity_gate_enabled": False,
    "payments_enabled": False,
    "preview_session_ttl_seconds": 86400,
}

JUDGMENT_MODEL_SETTINGS = ("stat_judgment_model", "ending_judgment_model", "image_judgment_model")

_DIRECT_ASSIGNMENT = {
    call_site: "anthropic"
    for call_site in (
        "chat_generate",
        "chat_stat_judgment",
        "chat_ending_judgment",
        "chat_media_book_image",
        "preview_stat_judgment",
        "preview_ending_judgment",
        "preview_media_book_image",
    )
}

# 프로필 이름 → (판정 모델, 호출 위치 배정).
PROFILES: dict[str, tuple[str, dict[str, str]]] = {
    "gemini": ("gemini", {}),
    "haiku-bedrock": ("haiku", {}),
    "haiku-direct": ("haiku", _DIRECT_ASSIGNMENT),
}
LANES = ("story", "character")
SWITCHES = (True, False)
QUERIES = (None, "gemini")
SLOTS = ("stat", "ending", "image")


def scenario_id(profile: str, lane: str, switch: bool, query: str | None) -> str:
    return f"{profile}-{lane}-{'on' if switch else 'off'}-{query or 'none'}"


SCENARIOS = [
    (profile, lane, switch, query) for profile in PROFILES for lane in LANES for switch in SWITCHES for query in QUERIES
]

ANSWERS: dict[type, Any] = {
    StatRuleJudgmentResult: StatRuleJudgmentResult(fired_rule_ids=[]),
    EndingJudgmentResult: EndingJudgmentResult(triggered=False),
    ImageMatchJudgmentResult: ImageMatchJudgmentResult(matched_image_entity_id=None),
    SceneJudgmentResult: SceneJudgmentResult(place=None, time=None),
}


def fix_settings(monkeypatch: pytest.MonkeyPatch, *, profile: str, premium: bool) -> None:
    for name, value in FIXED_SETTINGS.items():
        monkeypatch.setattr(settings, name, value)
    model, assignment = PROFILES[profile]
    for name in JUDGMENT_MODEL_SETTINGS:
        monkeypatch.setattr(settings, name, model)
    monkeypatch.setattr(settings, "llm_call_site_backends", dict(assignment))
    monkeypatch.setattr(settings, "chat_premium_models_enabled", premium)


class RecordingLLM(LLMClient):
    """생성은 고정 응답, 구조화 호출은 "아무것도 바뀌지 않음". 받은 호출과 그 호출이 갈 경로를 순서대로 적는다."""

    def __init__(self) -> None:
        self.calls: list[list[Any]] = []

    def _record(self, usage: LLMCallContext) -> None:
        model = usage.model or "gemini"
        backend, sent = resolve_backend(usage.call_site, model, usage.call_model)
        self.calls.append([usage.call_site, usage.model, usage.call_model, backend, sent])

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self._record(usage)
        yield "응답"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self._record(usage)
        return ANSWERS[response_schema]


class RedisRecorder:
    """`redis_client.execute_command` 를 감싸 명령을 센다. 배정 표 키 명령은 세지 않는다."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.other = 0
        self.prompt_set: list[list[str]] = []
        real: Any = redis_client.execute_command

        async def _execute(*args: Any, **options: Any) -> Any:
            command = str(args[0]).upper() if args else ""
            key = str(args[1]) if len(args) > 1 else ""
            if key != PROMPT_ROUTES_CACHE_KEY:
                self.other += 1
                if key.startswith(ACTIVE_PROMPT_SET_KEY_PREFIX):
                    self.prompt_set.append([command, key.removeprefix(ACTIVE_PROMPT_SET_KEY_PREFIX)])
            return await real(*args, **options)

        monkeypatch.setattr(redis_client, "execute_command", _execute)


def record_judgment_sets(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    seen: list[dict[str, str]] = []
    real = turn_prompt.judgment_prompt_sets

    async def _recording(**kwargs: Any) -> Any:
        sets = await real(**kwargs)
        seen.append({slot: getattr(sets, slot)[0].model for slot in SLOTS})
        return sets

    monkeypatch.setattr(chat_router, "judgment_prompt_sets", _recording)
    return seen


def record_charges(monkeypatch: pytest.MonkeyPatch) -> list[list[Any]]:
    """차감 본문(`charge_chat_turn`)이 받은 (모델, 가격, 사용처 종류). 게이트가 어느 모듈에 있든 그 모듈이 부르는 이름을 감싼다."""
    seen: list[list[Any]] = []
    real = rate_limit_gate.charge_chat_turn

    async def _recording(*args: Any, **kwargs: Any) -> Any:
        seen.append([kwargs["model"], kwargs["price"], kwargs["usage"].kind])
        return await real(*args, **kwargs)

    monkeypatch.setattr(rate_limit_gate, "charge_chat_turn", _recording)
    monkeypatch.setattr(chat_router, "charge_chat_turn", _recording)
    return seen


_UUID = re.compile(r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?")


def normalize(text: str) -> str:
    """무작위 id 는 처음 나온 순서대로 `<id-n>`, 시각은 `<time>` 으로 바꾼다 — 같은 id 가 어디에 다시 나오는지는 남는다."""
    seen: dict[str, str] = {}

    def _id(match: re.Match[str]) -> str:
        return seen.setdefault(match.group(0), f"<id-{len(seen)}>")

    return _UUID.sub(_id, _TIMESTAMP.sub("<time>", text))


async def session_json(key: str) -> str:
    raw = await redis_client.get(key)
    assert isinstance(raw, str), raw
    return raw


async def ledger(db_session: AsyncSession, user_id: uuid.UUID) -> list[list[Any]]:
    rows = await db_session.execute(
        select(CloverLedger.kind, CloverLedger.amount).where(CloverLedger.user_id == user_id)
    )
    return sorted([kind, amount] for kind, amount in rows.all())


async def observe_preview(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    *,
    profile: str,
    lane: str,
    switch: bool,
    query: str | None,
) -> dict[str, Any]:
    fix_settings(monkeypatch, profile=profile, premium=switch)
    user = await _make_user_with_clover_lot(db_session, clover_balance=1000)
    await db_session.commit()
    if lane == "story":
        asset = await _make_asset(db_session, owner_user_id=user.id, status=AssetStatus.READY)
        await db_session.commit()
        _, payload = _preview_story_payload(asset.id)
        payload["sceneHeaderEnabled"] = True
    else:
        payload = _preview_character_payload()
    await _login_as(db_client, user.id)
    params = {} if query is None else {"model": query}
    started = await db_client.post("/preview-sessions", json=payload, params=params)
    session_key = f"preview-session:{started.json()['previewSessionId']}"
    state_at_start = await session_json(session_key)
    await load_prompt_routes(db_session)
    await db_session.commit()

    sets = record_judgment_sets(monkeypatch)
    charges = record_charges(monkeypatch)
    fake = RecordingLLM()
    redis = RedisRecorder(monkeypatch)
    _override_llm_client(fake)
    try:
        with _count_queries() as statements:
            resp = await db_client.post(
                f"/preview-sessions/{started.json()['previewSessionId']}/messages", json={"content": "행복해지자"}
            )
            db_statements = statements()
    finally:
        _clear_llm_override()
    redis_commands = redis.other
    state_after = await session_json(session_key)
    events = _parse_sse_events(resp.text) if resp.status_code == 200 else []
    return {
        "start_status": started.status_code,
        "start_fields": sorted(started.json()),
        "state_at_start": normalize(state_at_start),
        "status": resp.status_code,
        "events": normalize(json.dumps(events, ensure_ascii=False)),
        "state_after": normalize(state_after),
        "slots": sets,
        "llm_calls": fake.calls,
        "charges": charges,
        "ledger": await ledger(db_session, user.id),
        "prompt_set_redis": redis.prompt_set,
        "db_statements": db_statements,
        "redis_commands": redis_commands,
    }


@pytest.fixture(scope="module")
def expected() -> Iterator[dict[str, Any]]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert data["fixed_settings"] == json.loads(json.dumps(FIXED_SETTINGS))
    assert data["profiles"] == json.loads(json.dumps(PROFILES))
    assert sorted(data["scenarios"]) == sorted(scenario_id(*case) for case in SCENARIOS)
    yield data["scenarios"]


@pytest.mark.parametrize(("profile", "lane", "switch", "query"), SCENARIOS, ids=[scenario_id(*c) for c in SCENARIOS])
async def test_default_preview_turn_matches_the_characterization(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    expected: dict[str, Any],
    profile: str,
    lane: str,
    switch: bool,
    query: str | None,
) -> None:
    observed = await observe_preview(
        db_client, db_session, monkeypatch, profile=profile, lane=lane, switch=switch, query=query
    )

    assert observed == expected[scenario_id(profile, lane, switch, query)]
