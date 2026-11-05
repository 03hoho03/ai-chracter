"""어드민 기능 스위치 덮어쓰기 — 읽는 순서(고정 맵 → 프로세스 맵 → `settings`), 표에서 다시 읽기와 그 실패, 요청·워커 작업
시작 때의 고정, api·워커 기동 때의 첫 적재. 끝의 시험들은 실제 라우트의 읽기 지점(클로버 정지·결제와 본인인증 판정·채팅 턴의
기억 접기 예약)이 덮어쓰기를 따르고, 한 요청 안에서는 시작 값을 보는지 본다."""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Mapping
from types import MappingProxyType

import httpx
import pytest
from fastapi import BackgroundTasks, FastAPI
from fastapi.sse import EventSourceResponse
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.chat import router as chat_router
from api.core import feature_switches
from api.core.config import Settings, settings
from api.core.feature_switches import (
    FEATURE_SWITCH_NAMES,
    READ_ONLY_SWITCH_REASONS,
    FeatureSwitchName,
    keep_switch_overrides_fresh,
    pinned_context,
    refresh_switch_overrides,
    switch_on,
)
from api.db.models import AdminUser, FeatureSwitchChange, FeatureSwitchOverride, User
from api.llm.client import LLMCallContext
from api.novelize import worker
from factories import (
    _clear_llm_override,
    _eventually,
    _FakeLLMClient,
    _login_as,
    _make_user_with_clover_lot,
    _NeverCalledLLMClient,
    _open_room,
    _override_llm_client,
    _parse_sse_events,
    _true,
)


def _set_process_overrides(overrides: Mapping[FeatureSwitchName, bool]) -> None:
    """갱신 태스크가 맵을 갈아 끼운 뒤와 같은 상태를 만든다. 표에서 읽어 오는 길은 `refresh_switch_overrides` 시험이 따로 본다."""
    feature_switches._process_overrides = MappingProxyType(dict(overrides))


def _payments_novelize_clover() -> tuple[bool, bool, bool]:
    return switch_on("payments_enabled"), switch_on("novelize_enabled"), switch_on("clover_ledger_paused")


async def _admin_id(db_session: AsyncSession) -> uuid.UUID:
    admin = AdminUser(email=f"admin-{uuid.uuid4()}@example.com", password_hash="unused")
    db_session.add(admin)
    await db_session.flush()
    return admin.id


def test_every_switch_is_a_boolean_settings_field() -> None:
    """깨지는 시나리오: 이름을 잘못 적거나 참/거짓이 아닌 칸을 목록에 넣어, 덮어쓰기가 없는 스위치를 읽는 순간 `settings` 에서
    AttributeError 가 나거나 참/거짓이 아닌 값이 조건문에 들어간다."""
    fields = Settings.model_fields
    assert [name for name in FEATURE_SWITCH_NAMES if name not in fields or fields[name].annotation is not bool] == []


def test_every_boolean_settings_field_is_either_a_button_or_read_only_once() -> None:
    """참/거짓 `Settings` 칸은 모두 버튼 대상이거나 읽기 전용 중 한쪽에만 있다. 깨지는 시나리오: 새 스위치 칸을 더하고 어느
    쪽에도 넣지 않아 어드민 현황판에서 그 스위치가 조용히 빠지거나, 두 목록에 함께 들어가 읽기 전용 이유가 붙은 채 버튼이
    생긴다."""
    booleans = [name for name, field in Settings.model_fields.items() if field.annotation is bool]
    classified = [*FEATURE_SWITCH_NAMES, *READ_ONLY_SWITCH_REASONS]
    assert sorted(classified) == sorted(booleans)


def test_without_overrides_a_switch_follows_settings_patched_at_any_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """덮어쓰기가 없으면 부르는 순간의 `settings` 값이다. 깨지는 시나리오: `.env` 값을 처음 읽을 때 복사해 두어, 테스트가
    `monkeypatch.setattr(settings, ...)` 로 바꾼 값이 먹지 않는다."""
    monkeypatch.setattr(settings, "novelize_enabled", True)
    assert switch_on("novelize_enabled") is True
    monkeypatch.setattr(settings, "novelize_enabled", False)
    assert switch_on("novelize_enabled") is False


def test_a_pinned_map_is_read_alone_and_the_process_map_only_without_a_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    """고정된 컨텍스트는 고정한 순간의 맵만 본다 — 그 뒤 프로세스 맵에 생긴 덮어쓰기도, 사라진 덮어쓰기도 보지 않는다. 고정이
    없으면 지금의 프로세스 맵이고, 거짓 덮어쓰기는 참인 `settings` 를 이긴다. 깨지는 시나리오: 프로세스 맵을 고정 맵보다 먼저
    보거나, 고정 맵에 없는 이름을 프로세스 맵에서 찾아 한 작업 안에서 값이 바뀐다. 또는 고정이 띄우는 쪽 컨텍스트에 새어
    루프 자신이 옛 맵에 묶인다."""
    monkeypatch.setattr(settings, "payments_enabled", False)
    monkeypatch.setattr(settings, "novelize_enabled", False)
    monkeypatch.setattr(settings, "clover_ledger_paused", True)
    _set_process_overrides({"payments_enabled": True})
    context = pinned_context()

    _set_process_overrides({"payments_enabled": False, "novelize_enabled": True, "clover_ledger_paused": False})

    assert context.run(_payments_novelize_clover) == (True, False, True)
    assert _payments_novelize_clover() == (False, True, False)


async def test_refresh_reflects_the_table_and_drops_deleted_rows(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """다시 읽으면 표의 행이 그대로 맵이 되고, 지운 행의 스위치는 `settings` 로 돌아간다. 이 코드가 모르는 이름의 행(버튼
    대상에서 빠진 스위치가 남긴 행)이 섞여 있어도 나머지는 읽힌다. 깨지는 시나리오: 맵을 갈아 끼우지 않고 합쳐 지운 덮어쓰기가
    계속 먹거나, 모르는 이름 하나 때문에 읽기 전체가 실패해 기동이 멈춘다."""
    monkeypatch.setattr(settings, "payments_enabled", False)
    monkeypatch.setattr(settings, "novelize_enabled", False)
    monkeypatch.setattr(settings, "clover_ledger_paused", True)
    admin_id = await _admin_id(db_session)
    db_session.add_all(
        [
            FeatureSwitchOverride(name="payments_enabled", value=True, admin_id=admin_id),
            FeatureSwitchOverride(name="clover_ledger_paused", value=False, admin_id=admin_id),
            FeatureSwitchOverride(name="novel_bible_enabled", value=True, admin_id=admin_id),
        ]
    )
    await db_session.flush()
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    await refresh_switch_overrides(factory)
    assert _payments_novelize_clover() == (True, False, False)

    await db_session.execute(delete(FeatureSwitchOverride).where(FeatureSwitchOverride.name == "payments_enabled"))
    await refresh_switch_overrides(factory)
    assert _payments_novelize_clover() == (False, False, False)


async def test_a_failed_refresh_keeps_the_previous_overrides(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """DB 를 못 읽으면 직전 맵을 그대로 쓴다 — 한 번 부른 갱신은 예외를 올리고(기동 때는 그래서 기동이 실패한다), 주기 갱신은
    경고만 남기고 다음 간격에 다시 본다. 깨지는 시나리오: 실패한 갱신이 맵을 비워 덮어쓰기로 켠 클로버 정지가 DB 장애 동안
    `.env` 값으로 풀리거나, 실패 한 번에 주기 갱신이 죽어 그 뒤 저장이 이 프로세스에 영영 보이지 않는다."""
    monkeypatch.setattr(settings, "clover_ledger_paused", False)
    _set_process_overrides({"clover_ledger_paused": True})
    # 닫힌 포트 — 연결이 바로 거절된다.
    broken = create_async_engine("postgresql+asyncpg://postgres:postgres@127.0.0.1:1/unreachable", poolclass=NullPool)
    broken_factory = async_sessionmaker(broken, expire_on_commit=False)
    monkeypatch.setattr(feature_switches, "REFRESH_INTERVAL_SECONDS", 0.01)
    caplog.set_level(logging.WARNING, logger=feature_switches.__name__)

    def warnings() -> int:
        return sum(1 for record in caplog.records if record.name == feature_switches.__name__)

    try:
        with pytest.raises(OSError):
            await refresh_switch_overrides(broken_factory)
        assert switch_on("clover_ledger_paused") is True

        refresher = asyncio.create_task(keep_switch_overrides_fresh(broken_factory))
        try:
            await _eventually(lambda: _true(warnings() >= 2))
            assert not refresher.done()
            assert switch_on("clover_ledger_paused") is True
        finally:
            refresher.cancel()
            with pytest.raises(asyncio.CancelledError):
                await refresher
    finally:
        await broken.dispose()


async def test_a_request_keeps_the_overrides_it_started_with_until_it_ends(monkeypatch: pytest.MonkeyPatch) -> None:
    """요청 도중 프로세스 맵이 바뀌어도 그 요청의 SSE 본문과 응답 뒤 작업은 시작 순간의 맵을 본다. 요청이 끝나면 고정이 풀려
    지금의 맵이 보인다. 시험 앱은 `main.app` 의 미들웨어 구성을 그대로 쓴다. 깨지는 시나리오: 고정 미들웨어가 빠지거나
    제너레이터 안에서 늦게 고정해, 한 턴의 앞뒤(또는 턴과 그 뒤 접기)가 서로 다른 스위치 값으로 돈다. 또는 고정이 풀리지 않아
    그 뒤의 일이 옛 맵에 묶인다."""
    from api import main

    monkeypatch.setattr(settings, "payments_enabled", False)
    monkeypatch.setattr(settings, "novelize_enabled", False)
    _set_process_overrides({"payments_enabled": True})
    seen: list[tuple[str, bool, bool]] = []

    def record(where: str) -> None:
        seen.append((where, switch_on("payments_enabled"), switch_on("novelize_enabled")))

    probe = FastAPI()
    probe.user_middleware = list(main.app.user_middleware)

    @probe.post("/probe", response_class=EventSourceResponse)
    async def stream(background_tasks: BackgroundTasks) -> AsyncIterator[dict[str, str]]:
        record("stream")
        # 요청 도중 갱신 태스크가 맵을 갈아 끼웠다.
        _set_process_overrides({"novelize_enabled": True})
        await asyncio.sleep(0)
        record("stream-after-refresh")
        background_tasks.add_task(record, "background")
        yield {"type": "done"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=probe), base_url="http://testserver") as client:
        response = await client.post("/probe")

    assert response.status_code == 200
    assert seen == [
        ("stream", True, False),
        ("stream-after-refresh", True, False),
        ("background", True, False),
    ]
    assert (switch_on("payments_enabled"), switch_on("novelize_enabled")) == (False, True)


async def test_a_worker_job_keeps_the_overrides_it_was_started_with(monkeypatch: pytest.MonkeyPatch) -> None:
    """워커가 띄운 작업은 작업 도중 맵이 바뀌어도 띄운 순간의 맵을 본다. 루프 쪽은 지금의 맵을 본다. 깨지는 시나리오: 작업이
    루프의 컨텍스트를 그대로 물려받아(루프는 고정이 없다) 장 생성 도중 갱신된 맵을 읽어 한 작업 안의 값이 섞인다."""
    monkeypatch.setattr(settings, "payments_enabled", False)
    monkeypatch.setattr(settings, "novelize_enabled", False)
    _set_process_overrides({"payments_enabled": True})
    started = asyncio.Event()
    finish = asyncio.Event()
    seen: list[tuple[bool, bool]] = []

    def payments_novelize() -> tuple[bool, bool]:
        return switch_on("payments_enabled"), switch_on("novelize_enabled")

    async def claim(_factory: object, _limit: int) -> list[uuid.UUID]:
        return [uuid.uuid4()]

    async def run(_factory: object, _llm: object, _job_id: uuid.UUID) -> None:
        seen.append(payments_novelize())
        started.set()
        await finish.wait()
        seen.append(payments_novelize())

    monkeypatch.setattr(worker, "claim_candidates", claim)
    monkeypatch.setattr(worker, "run_job", run)
    active: set[asyncio.Task[None]] = set()

    assert await worker._poll(async_sessionmaker(), _NeverCalledLLMClient(), active, 1, asyncio.Event())
    await asyncio.wait_for(started.wait(), 5)
    # 작업 도중 갱신 태스크가 맵을 갈아 끼웠다.
    _set_process_overrides({"novelize_enabled": True})
    finish.set()
    await asyncio.wait_for(asyncio.gather(*active), 5)

    assert seen == [(True, False), (True, False)]
    assert payments_novelize() == (False, True)


async def test_lifespan_loads_switch_overrides_after_the_guard_and_before_serving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """api 는 클로버 단위 가드 바로 뒤에 덮어쓰기를 다 읽고 나서 요청을 받고, 내려갈 때 주기 갱신을 취소한다. 깨지는 시나리오:
    첫 적재를 기다리지 않아 새 색의 첫 요청들이 덮어쓰기로 켠 클로버 정지가 풀린 채 서빙되거나, 갱신 태스크가 남아 내려간
    뒤에도 DB 를 친다."""
    from api import main

    steps: list[str] = []
    refresher_started = asyncio.Event()
    refresher_cancelled = asyncio.Event()

    def step(name: str) -> object:
        async def run(_factory: object) -> None:
            steps.append(name)

        return run

    async def keep_fresh(_factory: object) -> None:
        refresher_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            refresher_cancelled.set()
            raise

    monkeypatch.setattr(main, "assert_clover_unit_matches", step("guard"))
    monkeypatch.setattr(main, "refresh_switch_overrides", step("first-load"))
    monkeypatch.setattr(main, "rebuild_suspended_user_markers", step("markers"))
    monkeypatch.setattr(main, "expire_stale_jobs_after_startup", step("cleanup"))
    monkeypatch.setattr(main, "keep_switch_overrides_fresh", keep_fresh)

    async with main.lifespan(main.app):
        steps.append("serving")
        await asyncio.wait_for(refresher_started.wait(), 5)

    assert steps[:2] == ["guard", "first-load"]
    assert steps.index("first-load") < steps.index("serving")
    assert refresher_cancelled.is_set()


async def test_lifespan_does_not_start_when_the_first_load_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """첫 적재가 실패하면 기동이 실패한다. 깨지는 시나리오: 실패를 삼키고 `.env` 값으로 요청을 받아, 덮어쓰기로 막아 둔
    기능이 그 프로세스에서만 열린다."""
    from api import main

    started: list[str] = []

    async def guard(_factory: object) -> None:
        started.append("guard")

    async def unreadable(_factory: object) -> None:
        raise ConnectionRefusedError("DB 가 안 된다")

    async def later(_factory: object) -> None:
        started.append("later")

    monkeypatch.setattr(main, "assert_clover_unit_matches", guard)
    monkeypatch.setattr(main, "refresh_switch_overrides", unreadable)
    monkeypatch.setattr(main, "rebuild_suspended_user_markers", later)
    monkeypatch.setattr(main, "expire_stale_jobs_after_startup", later)
    monkeypatch.setattr(main, "keep_switch_overrides_fresh", later)

    with pytest.raises(ConnectionRefusedError):
        async with main.lifespan(main.app):
            started.append("serving")

    assert started == ["guard"]


async def test_the_worker_loads_switch_overrides_before_taking_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    """소설화 워커도 가드 뒤에 덮어쓰기를 다 읽고 나서 작업을 받고, 끝날 때 주기 갱신을 취소한다. 깨지는 시나리오: 워커가 첫
    바퀴의 작업을 `.env` 값으로 띄우거나, 갱신 태스크가 남아 프로세스가 끝나지 않는다."""
    steps: list[str] = []
    refresher_started = asyncio.Event()
    refresher_cancelled = asyncio.Event()

    def step(name: str) -> object:
        async def run(_factory: object) -> None:
            steps.append(name)

        return run

    async def keep_fresh(_factory: object) -> None:
        refresher_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            refresher_cancelled.set()
            raise

    async def serve(_factory: object, _llm: object) -> None:
        steps.append("serve")
        await asyncio.wait_for(refresher_started.wait(), 5)

    class _Engine:
        async def dispose(self) -> None:
            steps.append("dispose")

    monkeypatch.setattr(worker, "assert_clover_unit_matches", step("guard"))
    monkeypatch.setattr(worker, "refresh_switch_overrides", step("first-load"))
    monkeypatch.setattr(worker, "get_llm_client", _NeverCalledLLMClient)
    monkeypatch.setattr(worker, "keep_switch_overrides_fresh", keep_fresh)
    monkeypatch.setattr(worker, "serve", serve)
    monkeypatch.setattr(worker, "engine", _Engine())

    await worker._main()

    assert steps == ["guard", "first-load", "serve", "dispose"]
    assert refresher_cancelled.is_set()


@pytest.mark.parametrize("reason", [pytest.param("", id="empty"), pytest.param("   ", id="spaces")])
async def test_a_change_without_a_reason_is_rejected(db_session: AsyncSession, reason: str) -> None:
    """이력의 사유는 비울 수 없다(CHECK 는 `alembic check` 가 비교하지 않아 이 시험이 유일한 검증이다)."""
    admin_id = await _admin_id(db_session)
    db_session.add(
        FeatureSwitchChange(
            name="payments_enabled",
            before_override=None,
            after_override=True,
            env_value=False,
            reason=reason,
            admin_id=admin_id,
        )
    )
    with pytest.raises(IntegrityError, match="ck_feature_switch_changes_reason_not_blank"):
        await db_session.flush()


async def test_a_change_with_a_reason_is_kept(db_session: AsyncSession) -> None:
    admin_id = await _admin_id(db_session)
    db_session.add(
        FeatureSwitchChange(
            name="payments_enabled",
            before_override=True,
            after_override=None,
            env_value=False,
            reason=" 결제 점검 끝 ",
            admin_id=admin_id,
        )
    )
    await db_session.flush()


# ── 실제 라우트의 읽기 지점 ─────────────────────────────────────────────────────


async def _balance(db_session: AsyncSession, user_id: uuid.UUID) -> int:
    balance = await db_session.scalar(
        select(User.clover_balance).where(User.id == user_id).execution_options(populate_existing=True)
    )
    assert balance is not None
    return balance


async def test_a_clover_pause_override_stops_a_grant_route_while_the_env_is_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """덮어쓰기로 켠 클로버 정지는 `.env` 가 꺼져 있어도 지급 라우트의 의존성에서 503 이다. 깨지는 시나리오: 정지 검사가
    `.env` 값만 읽어, 잔액을 옮기려고 어드민에서 정지를 켰는데 미션 보상이 계속 지급된다(이 회원은 미션을 달성하지 않아 검사가
    덮어쓰기를 못 보면 422 다)."""
    monkeypatch.setattr(settings, "clover_ledger_paused", False)
    _set_process_overrides({"clover_ledger_paused": True})
    user = await _make_user_with_clover_lot(db_session, clover_balance=1000)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.post("/me/clover/missions/first_message/claim")

    assert resp.status_code == 503, resp.text
    assert resp.json()["detail"]["code"] == "CLOVER_PAUSED"


async def test_a_clover_pause_override_lets_a_paid_chat_turn_through_while_the_env_is_on(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """덮어쓰기로 끈 클로버 정지는 `.env` 가 켜져 있어도 유료 턴의 게이트와 차감(`spend`)을 둘 다 지나게 한다 — 한 요청의 두
    검사가 같은 값을 본다. 깨지는 시나리오: 정지 검사가 `.env` 값을 읽어, 어드민에서 정지를 풀었는데 유료 턴이 계속 503 이다."""
    monkeypatch.setattr(settings, "clover_ledger_paused", True)
    _set_process_overrides({"clover_ledger_paused": False})
    room = await _open_room(db_client, db_session, turns=1, paid_turns=1)
    _override_llm_client(_FakeLLMClient(tokens=["안녕"]))
    try:
        resp = await db_client.post(f"/chat-rooms/{room.room_id}/messages", json={"content": "새 메시지"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200, resp.text
    assert [event["type"] for event in _parse_sse_events(resp.text)][-1] == "done"
    assert await _balance(db_session, room.user_id) == 0


async def test_payment_and_identity_judgments_follow_overrides_read_from_the_table(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """결제·본인인증 실효 판정은 표에서 읽어 온 덮어쓰기를 `.env` 보다 먼저 본다 — 켜는 쪽과 끄는 쪽 모두. 깨지는 시나리오:
    판정이 `.env` 값만 읽어, 어드민에서 결제를 켰는데 충전 허브가 닫힌 채이거나 본인인증 게이트를 껐는데 미인증 회원이 계속
    막힌다."""
    for key in (
        "portone_store_id",
        "portone_payment_channel_key",
        "portone_identity_channel_key",
        "portone_api_secret",
        "portone_webhook_secret",
        "identity_ci_hmac_key",
    ):
        monkeypatch.setattr(settings, key, f"{key}-test")
    monkeypatch.setattr(settings, "payments_enabled", False)
    monkeypatch.setattr(settings, "identity_gate_enabled", True)
    admin_id = await _admin_id(db_session)
    db_session.add_all(
        [
            FeatureSwitchOverride(name="payments_enabled", value=True, admin_id=admin_id),
            FeatureSwitchOverride(name="identity_gate_enabled", value=False, admin_id=admin_id),
        ]
    )
    await db_session.flush()
    await refresh_switch_overrides(async_sessionmaker(bind=db_session.bind, expire_on_commit=False))

    body = (await db_client.get("/clover/products")).json()

    assert (body["paymentsEnabled"], body["identityGateEnabled"]) == (True, False)


class _RefreshedMidTurnLLMClient(_FakeLLMClient):
    """응답을 쓰기 시작할 때 갱신 태스크가 프로세스 맵을 `refreshed` 로 갈아 끼운 것처럼 만든다."""

    def __init__(self, refreshed: Mapping[FeatureSwitchName, bool]) -> None:
        super().__init__(tokens=["안녕"])
        self.refreshed = refreshed

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        _set_process_overrides(self.refreshed)
        async for token in super().generate(prompt, system_instruction, stop_sequences, usage=usage):
            yield token


async def test_a_chat_turn_keeps_the_memory_switch_it_started_with(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """채팅 턴(SSE)은 응답을 쓰는 도중 덮어쓰기가 바뀌어도, 커밋 뒤의 접기 예약과 응답 뒤의 접기 작업까지 시작 순간의 값을
    본다. 요청이 끝나면 바뀐 값이 보인다. 깨지는 시나리오: 접기 예약이 `.env` 값만 읽어 어드민에서 켠 생성 윈도우의 방에 접기가
    예약되지 않거나, 턴 도중의 갱신을 읽어 같은 턴의 프롬프트는 요약 윈도우로 짓고 접기는 빼먹는다."""
    monkeypatch.setattr(settings, "memory_window_generation", False)
    _set_process_overrides({"memory_window_generation": True})
    seen_by_fold: list[bool] = []

    async def recording_fold(*_args: object, **_kwargs: object) -> None:
        seen_by_fold.append(switch_on("memory_window_generation"))

    monkeypatch.setattr(chat_router, "fold_memory", recording_fold)
    room = await _open_room(db_client, db_session, turns=1, paid_turns=1)
    _override_llm_client(_RefreshedMidTurnLLMClient({"memory_window_generation": False}))
    try:
        resp = await db_client.post(f"/chat-rooms/{room.room_id}/messages", json={"content": "새 메시지"})
    finally:
        _clear_llm_override()

    assert resp.status_code == 200, resp.text
    assert [event["type"] for event in _parse_sse_events(resp.text)][-1] == "done"
    assert seen_by_fold == [True]
    assert switch_on("memory_window_generation") is False
