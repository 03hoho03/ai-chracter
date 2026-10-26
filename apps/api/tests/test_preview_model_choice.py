"""빌더 미리보기에서 고른 글쓰기 모델 — 시작 요청의 모델 쿼리, 세션 상태의 모델 칸, 그 모델로 도는 생성·차감·판정.

시작 요청이 고른 모델은 세션 상태에 본문과 나란한 칸으로 남고, 전송마다 채팅방과 같은 함수로 지금 쓸 모델을 정한다(상위 모델
스위치가 꺼지면 Gemini). 그 한 값으로 생성 세트·생성 호출·차감 가격·판정 세트(모델 배정 표의 그 모델 칸)가 함께 정해진다.
모델을 바꾸려면 새 시작 요청으로 새 세션을 연다. 기본(Gemini) 세션이 바뀌기 전과 같은지는
`test_preview_session_characterization.py` 가 본다.
"""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat import router as chat_router
from api.chat import turn_engine, turn_prompt
from api.chat.preview_session import get_preview_session
from api.chat.prompt_builder import (
    EndingJudgmentResult,
    ImageMatchJudgmentResult,
    PromptSetNotFoundError,
    SceneJudgmentResult,
    StatRuleJudgmentResult,
)
from api.core import clover, rate_limit_gate
from api.core.config import settings
from api.core.redis import redis_client
from api.db.models import AssetStatus
from api.db.models.clover import CloverLedger
from api.db.models.prompt import PromptRoute, PromptSet
from api.llm import model_access
from api.llm.client import LLMCallContext, LLMClient
from api.llm.routing import resolve_backend
from factories import (
    _clear_llm_override,
    _login_as,
    _make_asset,
    _make_user_with_clover_lot,
    _override_llm_client,
    _parse_sse_events,
    _preview_character_payload,
    _preview_story_payload,
)

FIXED_SETTINGS: dict[str, Any] = {
    "gemini_model_name": "fixture-gemini-base",
    "anthropic_haiku_model_id": "fixture-anthropic-haiku",
    "anthropic_sonnet_model_id": "fixture-anthropic-sonnet",
    "anthropic_opus_model_id": "fixture-anthropic-opus",
    "identity_gate_enabled": False,
    "payments_enabled": False,
    "stat_judgment_model": "haiku",
    "ending_judgment_model": "haiku",
    "image_judgment_model": "haiku",
}

# 운영처럼 채팅 생성과 채팅·미리보기 판정 호출 위치를 Anthropic 직결로 둔 배정(미리보기 생성 줄은 없다).
DIRECT_ASSIGNMENT = {
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

ANSWERS: dict[type, Any] = {
    StatRuleJudgmentResult: StatRuleJudgmentResult(fired_rule_ids=[]),
    EndingJudgmentResult: EndingJudgmentResult(triggered=False),
    ImageMatchJudgmentResult: ImageMatchJudgmentResult(matched_image_entity_id=None),
    SceneJudgmentResult: SceneJudgmentResult(place=None, time=None),
}


def fix_settings(monkeypatch: pytest.MonkeyPatch, *, premium: bool) -> None:
    for name, value in FIXED_SETTINGS.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(settings, "llm_call_site_backends", dict(DIRECT_ASSIGNMENT))
    monkeypatch.setattr(settings, "chat_premium_models_enabled", premium)


class RecordingLLM(LLMClient):
    """받은 호출마다 (호출 위치, 실린 모델, 실린 부를 모델, 그 호출이 갈 구현, 그 구현이 보낼 모델 id)를 적는다."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, str | None, str, str]] = []

    def _record(self, usage: LLMCallContext) -> None:
        backend, sent = resolve_backend(usage.call_site, usage.model or "gemini", usage.call_model)
        self.calls.append((usage.call_site, usage.model, usage.call_model, backend, sent))

    def call(self, call_site: str) -> tuple[str, str | None, str | None, str, str]:
        [found] = [call for call in self.calls if call[0] == call_site]
        return found

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


def record_charges(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int, str]]:
    """차감 본문이 받은 (모델, 가격, 사용처 종류)."""
    seen: list[tuple[str, int, str]] = []
    real = rate_limit_gate.charge_chat_turn

    async def _recording(*args: Any, **kwargs: Any) -> Any:
        seen.append((kwargs["model"], kwargs["price"], kwargs["usage"].kind))
        return await real(*args, **kwargs)

    monkeypatch.setattr(rate_limit_gate, "charge_chat_turn", _recording)
    monkeypatch.setattr(chat_router, "charge_chat_turn", _recording)
    return seen


def record_turns(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """턴 골격이 받은 (생성 세트의 모델, 차감 영수증의 모델)."""
    seen: list[tuple[str, str]] = []
    real = turn_engine.run_turn

    def _recording(inp: Any, **kwargs: Any) -> Any:
        seen.append((inp.generation_set.model, inp.charge.model))
        return real(inp, **kwargs)

    monkeypatch.setattr(chat_router, "run_turn", _recording)
    return seen


def record_stat_sets(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """판정 세트 고르기가 스탯 칸에 고른 세트의 모델."""
    seen: list[str] = []
    real = turn_prompt.judgment_prompt_sets

    async def _recording(**kwargs: Any) -> Any:
        sets = await real(**kwargs)
        seen.append(sets.stat[0].model)
        return sets

    monkeypatch.setattr(chat_router, "judgment_prompt_sets", _recording)
    return seen


async def ledger(db_session: AsyncSession, user_id: uuid.UUID) -> list[list[Any]]:
    rows = await db_session.execute(
        select(CloverLedger.kind, CloverLedger.amount).where(CloverLedger.user_id == user_id)
    )
    return sorted([kind, amount] for kind, amount in rows.all())


async def stored_state(session_id: str) -> dict[str, Any]:
    """Redis 에 저장된 세션 상태 JSON 그대로(칸 순서 포함)."""
    raw = await redis_client.get(f"preview-session:{session_id}")
    assert isinstance(raw, str)
    state: dict[str, Any] = json.loads(raw)
    return state


async def put_rows(db_session: AsyncSession, room_model: str, rows: dict[str, tuple[str, str]]) -> None:
    """스토리 레인 `room_model` 칸에 단계 → (부를 모델, 경로) 행을 Haiku 체인으로 둔다."""
    db_session.add_all(
        PromptRoute(
            lane="story", room_model=room_model, stage=stage, chain_model="haiku", call_model=model, backend=backend
        )
        for stage, (model, backend) in rows.items()
    )
    await db_session.commit()


async def start(
    db_client: httpx.AsyncClient, db_session: AsyncSession, *, model: str | None, lane: str = "story"
) -> tuple[uuid.UUID, httpx.Response]:
    """새 회원으로 로그인해 미리보기 세션을 시작한다(스토리는 장면 헤더·미디어 북 칸·게이트 1 엔딩을 켠 초안)."""
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
    params = {} if model is None else {"model": model}
    return user.id, await db_client.post("/preview-sessions", json=payload, params=params)


async def send(db_client: httpx.AsyncClient, session_id: str, fake: LLMClient) -> httpx.Response:
    _override_llm_client(fake)
    try:
        return await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "행복해지자"})
    finally:
        _clear_llm_override()


# ── 시작 요청 ─────────────────────────────────────────────────────────────────────────────


async def test_starting_with_a_premium_model_keeps_it_beside_the_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """고른 모델은 세션 상태의 본문 옆 칸에 남는다 — 본문(초안)은 감싸지 않아 모델 칸을 모르는 코드도 그대로 읽는다."""
    fix_settings(monkeypatch, premium=True)

    _, opus = await start(db_client, db_session, model="opus")
    _, default = await start(db_client, db_session, model=None)

    assert opus.status_code == default.status_code == 201
    opus_state = await stored_state(opus.json()["previewSessionId"])
    default_state = await stored_state(default.json()["previewSessionId"])
    assert opus_state["chatModel"] == "opus"
    # 기본 모델 세션의 상태는 모델 칸이 생기기 전과 같은 JSON 이다(칸을 싣지 않는다).
    assert "chatModel" not in default_state
    assert list(opus_state) == [*default_state, "chatModel"]
    loaded = await get_preview_session(opus.json()["previewSessionId"])
    assert loaded is not None and loaded.payload.name == "잃어버린 도시"


async def test_starting_with_a_premium_model_without_access_is_refused(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """상위 모델 스위치가 꺼져 있으면 채팅방에서 모델을 고를 때와 같은 403 이다."""
    fix_settings(monkeypatch, premium=False)

    _, resp = await start(db_client, db_session, model="opus")

    assert resp.status_code == 403
    assert resp.json()["detail"] == {"code": "CHAT_MODEL_NOT_ALLOWED"}


async def test_starting_with_a_model_the_chat_cannot_pick_is_rejected(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    fix_settings(monkeypatch, premium=True)

    _, resp = await start(db_client, db_session, model="sonnet")

    assert resp.status_code == 422


async def test_picking_another_model_opens_a_fresh_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """모델을 바꾸는 길은 새 시작 요청이다 — 새 세션은 첫 턴 상태에서 고른 모델로 시작하고, 앞 세션은 그대로 남는다."""
    fix_settings(monkeypatch, premium=True)
    _, first = await start(db_client, db_session, model=None)
    first_id = first.json()["previewSessionId"]
    assert (await send(db_client, first_id, RecordingLLM())).status_code == 200

    _, second = await start(db_client, db_session, model="opus")

    second_id = second.json()["previewSessionId"]
    before, after = await stored_state(first_id), await stored_state(second_id)
    assert second_id != first_id
    assert (before.get("chatModel"), before["turnCount"], len(before["messages"])) == (None, 1, 3)
    assert (after.get("chatModel"), after["turnCount"], len(after["messages"])) == ("opus", 0, 1)


# ── 전송: 생성·차감·판정이 같은 실효 모델을 본다 ────────────────────────────────────────────────


@pytest.mark.parametrize("lane", ["story", "character"])
async def test_an_opus_session_turn_generates_and_charges_with_opus(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, lane: str
) -> None:
    """Opus 세션의 턴은 그 레인의 Opus 생성 세트로 조립해, 채팅 생성의 배정을 물려받은 경로(운영에서 Anthropic 직결)로 Opus 를
    부르고, Opus 턴 가격으로 깎는다. 판정은 배정 표가 비어 있으면 판정 모델 설정 그대로다."""
    fix_settings(monkeypatch, premium=True)
    user_id, started = await start(db_client, db_session, model="opus", lane=lane)
    charges, turns = record_charges(monkeypatch), record_turns(monkeypatch)
    fake = RecordingLLM()

    resp = await send(db_client, started.json()["previewSessionId"], fake)

    assert resp.status_code == 200
    assert _parse_sse_events(resp.text)[-1]["type"] == "done"
    assert charges == [("opus", clover.MODEL_PRICES["opus"].chat_turn, "preview")]
    assert turns == [("opus", "opus")]
    assert fake.call("preview_generate") == ("preview_generate", "opus", None, "anthropic", "fixture-anthropic-opus")
    assert {call[1:] for call in fake.calls if call[0] != "preview_generate"} <= {
        ("gemini", None, "anthropic", "fixture-anthropic-haiku")
    }
    assert await ledger(db_session, user_id) == [["chat_spend", -clover.MODEL_PRICES["opus"].chat_turn]]


@pytest.mark.parametrize(
    ("switch", "expected_model", "expected_price", "expected_stat_call"),
    [
        pytest.param(True, "opus", clover.MODEL_PRICES["opus"].chat_turn, "opus", id="switch-on"),
        pytest.param(False, "gemini", clover.MODEL_PRICES["gemini"].chat_turn, None, id="switch-off"),
    ],
)
async def test_an_opus_session_turns_to_gemini_for_judgments_and_charge_when_the_switch_is_off(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    switch: bool,
    expected_model: str,
    expected_price: int,
    expected_stat_call: str | None,
) -> None:
    """스위치를 켠 채 Opus 로 시작한 세션도, 전송 때 스위치가 꺼져 있으면 채팅방처럼 Gemini 로 돈다 — 생성·차감은 물론 판정도
    Opus 칸의 행이 아니라 Gemini 칸(행 없음 → 판정 모델 설정)이다."""
    fix_settings(monkeypatch, premium=True)
    _, started = await start(db_client, db_session, model="opus")
    await put_rows(db_session, "opus", {"stat_judgment": ("opus", "anthropic")})
    monkeypatch.setattr(settings, "chat_premium_models_enabled", switch)
    charges, stat_sets = record_charges(monkeypatch), record_stat_sets(monkeypatch)
    fake = RecordingLLM()

    resp = await send(db_client, started.json()["previewSessionId"], fake)

    assert resp.status_code == 200
    assert charges == [(expected_model, expected_price, "preview")]
    assert fake.call("preview_generate")[1] == expected_model
    assert fake.call("preview_stat_judgment")[2] == expected_stat_call
    assert stat_sets == ["haiku"]


async def test_a_model_query_on_a_message_does_not_change_the_session_model(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """세션 모델은 시작 요청에서만 정한다 — 전송 요청에 모델 쿼리를 실어도 저장된 모델 칸·그 턴의 생성·차감은 시작 때 모델이다."""
    fix_settings(monkeypatch, premium=True)
    _, started = await start(db_client, db_session, model="opus")
    session_id = started.json()["previewSessionId"]
    charges, turns = record_charges(monkeypatch), record_turns(monkeypatch)
    fake = RecordingLLM()

    _override_llm_client(fake)
    try:
        resp = await db_client.post(
            f"/preview-sessions/{session_id}/messages", json={"content": "행복해지자"}, params={"model": "gemini"}
        )
    finally:
        _clear_llm_override()

    assert resp.status_code == 200
    state = await stored_state(session_id)
    assert (state.get("chatModel"), state["turnCount"]) == ("opus", 1)
    assert charges == [("opus", clover.MODEL_PRICES["opus"].chat_turn, "preview")]
    assert turns == [("opus", "opus")]
    assert fake.call("preview_generate")[1] == "opus"


async def test_one_preview_turn_reads_the_effective_model_once_for_sets_generation_and_charge(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """허용 판정이 요청 중간에 바뀌어도 판정 세트·생성·차감은 한 번 읽은 같은 값을 쓴다."""
    fix_settings(monkeypatch, premium=True)
    _, started = await start(db_client, db_session, model="opus")
    await put_rows(db_session, "opus", {"stat_judgment": ("opus", "anthropic")})
    answers = [True, False]
    asked: list[bool] = []

    async def _flipping(db: Any, user: Any) -> bool:
        answer = answers[len(asked)] if len(asked) < len(answers) else False
        asked.append(answer)
        return answer

    monkeypatch.setattr(model_access, "has_chat_premium_access", _flipping)
    charges, turns = record_charges(monkeypatch), record_turns(monkeypatch)
    fake = RecordingLLM()

    resp = await send(db_client, started.json()["previewSessionId"], fake)

    assert resp.status_code == 200
    assert asked == [True]
    assert charges == [("opus", clover.MODEL_PRICES["opus"].chat_turn, "preview")]
    assert turns == [("opus", "opus")]
    assert fake.call("preview_stat_judgment")[2] == "opus"


@pytest.mark.parametrize("session_model", ["opus", "gemini"])
async def test_preview_judgments_call_the_model_of_their_own_row(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, session_model: str
) -> None:
    """미리보기 판정도 채팅방과 같은 해석으로 (레인, 고른 모델, 단계) 칸의 행을 따른다 — 스탯과 엔딩 칸에 서로 다른 모델을 두면
    각 판정이 자기 칸의 모델로 가고, 장면 헤더는 자기 행이 없어 스탯 칸을 물려받는다. Gemini 세션에는 Opus 칸의 행이 쓰이지 않는다."""
    fix_settings(monkeypatch, premium=True)
    _, started = await start(db_client, db_session, model=session_model)
    await put_rows(
        db_session,
        "opus",
        {
            "stat_judgment": ("opus", "anthropic"),
            "ending_judgment": ("sonnet", "anthropic"),
            "media_book_image": ("haiku", "anthropic"),
        },
    )
    fake = RecordingLLM()

    resp = await send(db_client, started.json()["previewSessionId"], fake)

    assert resp.status_code == 200
    judged = {call[0]: call[2:] for call in fake.calls if call[0] != "preview_generate"}
    if session_model == "opus":
        assert judged == {
            "preview_stat_judgment": ("opus", "anthropic", "fixture-anthropic-opus"),
            "preview_scene_judgment": ("opus", "anthropic", "fixture-anthropic-opus"),
            "preview_ending_judgment": ("sonnet", "anthropic", "fixture-anthropic-sonnet"),
            "preview_media_book_image": ("haiku", "anthropic", "fixture-anthropic-haiku"),
        }
    else:
        assert set(judged.values()) == {(None, "anthropic", "fixture-anthropic-haiku")}
        assert len(judged) == 4


async def test_an_opus_session_without_an_opus_chain_fails_before_the_stream_without_charging(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """그 레인의 Opus 생성 세트가 없으면 차감 게이트 앞에서 실패한다 — 스트림도 차감도 없다."""
    fix_settings(monkeypatch, premium=True)
    user_id, started = await start(db_client, db_session, model="opus")
    await db_session.execute(
        update(PromptSet).where(PromptSet.lane == "story", PromptSet.model == "opus").values(status="archived")
    )
    await db_session.commit()
    charges = record_charges(monkeypatch)
    fake = RecordingLLM()

    with pytest.raises(PromptSetNotFoundError, match="opus"):
        await send(db_client, started.json()["previewSessionId"], fake)

    assert charges == []
    assert fake.calls == []
    assert await ledger(db_session, user_id) == []
