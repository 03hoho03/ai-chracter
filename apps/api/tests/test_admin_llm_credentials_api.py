"""어드민 Claude 자격 목록 API — 조회·추가·수정·키 교체·순서 저장·켜기·끄기·삭제·확인 호출·목록 사용.

조직 조회와 확인 호출은 `get_anthropic_credential_probe` 를, 알림은 `get_credential_notifier` 를 갈아 끼운다(가짜 조사는 응답
헤더 대신 정규화한 조직 id 를 돌려준다). 로그·사용량 줄을 보는 테스트만 실제 SDK 를 쓰고 전송 계층을 바꿔 낀다. 설정은 로컬
env 파일과 무관하게 여기서 고정한다.

켜기 조건은 시각이 아니라 판(`state_version`)과 확인 회차로 가른다 — 테스트 트랜잭션 안에서는 `now()` 가 같아 시각으로는
어느 것도 가를 수 없고, 판은 운영과 테스트에서 같은 답을 낸다."""

import asyncio
import base64
import json
import logging
import time
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import anthropic
import httpx
import httpx2
import pytest
import sqlalchemy as sa
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin import llm_credentials as admin_llm_credentials
from api.core.config import settings
from api.core.field_crypto import FieldKeyring
from api.core.redis import redis_client
from api.db.models.llm_credential import LlmCredential, LlmCredentialCheck, LlmCredentialSettings
from api.db.models.moderation import AdminActionLog
from api.llm import credential_notify, credential_pool, credential_probe, credential_usage, credentials
from api.llm.claude_messages import to_usage
from api.llm.credential_notify import get_credential_notifier
from api.llm.credential_pool import GENERATION_KEY
from api.llm.credential_probe import (
    CheckCallResult,
    CredentialProbeError,
    get_anthropic_credential_probe,
)
from api.llm.credential_usage import CredentialSpend, SpendTarget, read_credential_spend, record_credential_spend
from api.llm.credentials import (
    CheckGroup,
    CredentialStoreError,
    ProbeFailureKind,
    credential_write,
    decrypt_secret,
    new_credential,
    secret_fingerprint,
)
from api.main import app
from factories import (
    FAKE_ANTHROPIC_ORG,
    FAKE_API_KEY,
    FAKE_CREDENTIAL_KEYRING,
    FAKE_OTHER_API_KEY,
    FAKE_ROTATED_KEYRING,
    _capture_credential_alerts,
    _create_admin,
    _login_as_admin,
    _settle_credential_tasks,
)

_BASE = "/admin/llm-credentials"
_ORG = FAKE_ANTHROPIC_ORG
_OTHER_ORG = "org-test-0002"
_OUTSIDE_ORG = "org-outside-0009"
# env 롤백 키(직결 키) — 목록 항목의 어느 키와도 다르다. 같은 경우는 테스트가 따로 정한다.
_ENV_KEY = "sk-ant-test-env-rollback-0000000000000000"
_IDS = {
    "opus": "claude-opus-5-5",
    "sonnet": "claude-sonnet-5-5",
    "haiku_writer": "claude-haiku-5-5",
    "haiku": "claude-haiku-5-5",
}
_ID_SETTINGS = {
    "opus": "anthropic_opus_model_id",
    "sonnet": "anthropic_sonnet_model_id",
    "haiku_writer": "anthropic_haiku_writer_model_id",
    "haiku": "anthropic_haiku_model_id",
}
_AXES_IN_ORDER = ["opus", "sonnet", "haiku_writer", "haiku"]

_LIST_FIELDS = {"storeConfigured", "notificationsConfigured", "poolEnabled", "listRevision", "modelIds", "credentials"}
_CREDENTIAL_FIELDS = {
    "id",
    "provider",
    "label",
    "position",
    "state",
    "stateReason",
    "stateVersion",
    "stateChangedAt",
    "accountRef",
    "organizationVerified",
    "secretLast4",
    "secretFingerprint",
    "sameAsEnvKey",
    "creditUsd",
    "creditSince",
    "alertPct",
    "createdAt",
    "updatedAt",
    "checks",
    "runtimeAxes",
    "enableBlocker",
    "spend",
}
_CHECK_FIELDS = {
    "run",
    "modelAxis",
    "sentModelId",
    "passed",
    "errorKind",
    "checkedAt",
    "isCurrentSecret",
    "isCurrentModelId",
    "isCurrentStateVersion",
    "isRuntimeBasis",
}


@pytest.fixture(autouse=True)
def store_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setattr(settings, "llm_credential_encryption_keys", FAKE_CREDENTIAL_KEYRING)
    monkeypatch.setattr(settings, "llm_credential_allowed_accounts", f"anthropic:{_ORG},anthropic:{_OTHER_ORG}")
    monkeypatch.setattr(settings, "llm_credential_discord_webhook_url", "https://discord.invalid/api/webhooks/0/t")
    monkeypatch.setattr(settings, "anthropic_direct_api_key", _ENV_KEY)
    for axis, name in _ID_SETTINGS.items():
        monkeypatch.setattr(settings, name, _IDS[axis])
    monkeypatch.setattr(settings, "anthropic_chat_effort", "low")
    monkeypatch.setattr(settings, "anthropic_structured_effort", "low")
    monkeypatch.setattr(settings, "anthropic_chat_timeout_ms", 45_000)
    return monkeypatch


@pytest.fixture(autouse=True)
async def _no_real_webhook_post(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """이 파일에서는 어떤 Claude 자격 알림도 실제 웹훅(위 `discord.invalid`)으로 나가지 않는다. 라우트의 알림은 `notes` 가 받고,
    추정 잔액 임계처럼 라우트 밖에서 쏘는 알림은 그것을 기대하는 테스트가 `_capture_credential_alerts` 로 받는다. 그 밖에서 보내려
    하면 여기 남아 테스트가 끝날 때 실패한다 — 쏘고 잊은 전송 태스크가 다음 테스트로 새지도 않는다."""
    attempted: list[str] = []

    async def refuse(message: str) -> None:
        attempted.append(message)

    monkeypatch.setattr(credential_notify, "send_credential_notification", refuse)
    yield
    await _settle_credential_tasks()
    assert attempted == [], f"잡지 않은 Claude 자격 알림이 웹훅으로 나가려 했다: {attempted}"


class FakeProbe:
    """조직 조회는 `organization`(또는 `organization_error`)을, 확인은 모델 id 별 `results`(없으면 `default`)를 돌려준다.
    `during_check` 는 첫 확인 호출 도중 한 번 돈다 — 호출을 기다리는 동안 생긴 변경을 흉내 낸다."""

    def __init__(self) -> None:
        self.organization: str | None = _ORG
        self.organization_error: ProbeFailureKind | None = None
        self.default = CheckCallResult(error_kind=None, organization=_ORG)
        self.results: dict[str, CheckCallResult] = {}
        self.lookups: list[str] = []
        self.calls: list[CheckGroup] = []
        self.during_check: Callable[[], Awaitable[None]] | None = None

    async def organization_of(self, api_key: str) -> str | None:
        self.lookups.append(api_key)
        if self.organization_error is not None:
            raise CredentialProbeError(self.organization_error)
        return self.organization

    async def check(self, api_key: str, group: CheckGroup, *, credential_id: uuid.UUID) -> CheckCallResult:
        self.calls.append(group)
        hook, self.during_check = self.during_check, None
        if hook is not None:
            await hook()
        return self.results.get(group.model_id, self.default)


@pytest.fixture
def probe() -> Iterator[FakeProbe]:
    fake = FakeProbe()
    app.dependency_overrides[get_anthropic_credential_probe] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_anthropic_credential_probe, None)


@pytest.fixture
def notes() -> Iterator[list[str]]:
    sent: list[str] = []
    app.dependency_overrides[get_credential_notifier] = lambda: sent.append
    yield sent
    app.dependency_overrides.pop(get_credential_notifier, None)


@pytest.fixture
async def admin_id(db_client: httpx.AsyncClient, db_session: AsyncSession) -> uuid.UUID:
    payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, payload)
    admin = payload["id"]
    assert isinstance(admin, uuid.UUID)
    return admin


async def _create(client: httpx.AsyncClient, label: str = "운영 계정", key: str = FAKE_API_KEY, **extra: Any) -> Any:
    resp = await client.post(_BASE, json={"provider": "anthropic", "label": label, "apiKey": key, **extra})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _check(client: httpx.AsyncClient, credential_id: str) -> Any:
    resp = await client.post(f"{_BASE}/{credential_id}/check")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _allow_another_check(credential_id: str) -> None:
    """분당 1회 제한을 그 항목만 푼다 — 같은 테스트에서 확인을 다시 부르려는 것이다."""
    await redis_client.delete(f"rate_limit:llm_credential_check:{credential_id}")


async def _listing(client: httpx.AsyncClient) -> Any:
    resp = await client.get(_BASE)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _row(db_session: AsyncSession, credential_id: str | uuid.UUID) -> LlmCredential:
    row = await db_session.scalar(
        sa.select(LlmCredential)
        .where(LlmCredential.id == uuid.UUID(str(credential_id)))
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return row


async def _checks(db_session: AsyncSession, credential_id: str | uuid.UUID) -> list[LlmCredentialCheck]:
    rows = await db_session.scalars(
        sa.select(LlmCredentialCheck)
        .where(LlmCredentialCheck.credential_id == uuid.UUID(str(credential_id)))
        .order_by(LlmCredentialCheck.run, LlmCredentialCheck.model_axis)
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def _audits(db_session: AsyncSession) -> list[AdminActionLog]:
    rows = await db_session.scalars(
        sa.select(AdminActionLog)
        .where(AdminActionLog.action_type.like("llm-credential-%"))
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def _ready(client: httpx.AsyncClient, label: str = "운영 계정", key: str = FAKE_API_KEY) -> Any:
    """확인을 통과하고 켜진 항목."""
    created = await _create(client, label, key)
    await _check(client, created["id"])
    resp = await client.post(f"{_BASE}/{created['id']}/enable")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _insert_row(db_session: AsyncSession, **overrides: Any) -> LlmCredential:
    """라우트를 거치지 않은 항목 — 라우트로는 만들 수 없는 행(Bedrock 등)을 둔다."""
    position = await db_session.scalar(sa.select(sa.func.coalesce(sa.func.max(LlmCredential.position), 0) + 1))
    assert position is not None
    credential = new_credential(
        FieldKeyring.parse(FAKE_CREDENTIAL_KEYRING),
        provider="anthropic",
        label="직접 넣은 계정",
        secret=FAKE_API_KEY,
        account_ref=None,
        position=position,
        credit_micro_usd=None,
        alert_pct=20,
    )
    for name, value in overrides.items():
        setattr(credential, name, value)
    db_session.add(credential)
    await db_session.flush()
    return credential


# ── 인증·저장소 설정 ──────────────────────────────────────────────────────────────
_SOME_ID = "00000000-0000-4000-8000-000000000001"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        pytest.param("GET", _BASE, None, id="list"),
        pytest.param("POST", _BASE, {"provider": "anthropic", "label": "x", "apiKey": FAKE_API_KEY}, id="create"),
        pytest.param("PATCH", f"{_BASE}/{_SOME_ID}", {"label": "x"}, id="update"),
        pytest.param("PUT", f"{_BASE}/{_SOME_ID}/secret", {"apiKey": FAKE_API_KEY}, id="secret"),
        pytest.param("PUT", f"{_BASE}/order", {"baseListRevision": 0, "ids": []}, id="order"),
        pytest.param("POST", f"{_BASE}/{_SOME_ID}/enable", None, id="enable"),
        pytest.param("POST", f"{_BASE}/{_SOME_ID}/disable", None, id="disable"),
        pytest.param("DELETE", f"{_BASE}/{_SOME_ID}", None, id="delete"),
        pytest.param("POST", f"{_BASE}/{_SOME_ID}/check", None, id="check"),
        pytest.param("PUT", f"{_BASE}/pool", {"enabled": True}, id="pool"),
    ],
)
async def test_every_route_refuses_a_request_without_an_admin_session(
    db_client: httpx.AsyncClient, probe: FakeProbe, method: str, path: str, body: dict[str, Any] | None
) -> None:
    resp = await db_client.request(method, path, json=body)

    assert resp.status_code == 401
    assert probe.lookups == [] and probe.calls == []


@pytest.mark.parametrize("missing", ["llm_credential_encryption_keys", "llm_credential_allowed_accounts"])
async def test_writes_that_need_the_store_are_503_without_keyring_or_allowlist(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin_id: uuid.UUID,
    probe: FakeProbe,
    notes: list[str],
    store_env: pytest.MonkeyPatch,
    missing: str,
) -> None:
    """키를 암호화할 키나 넣을 수 있는 계정이 없으면 키를 받는 일(추가·교체·확인)과 목록 사용 켜기가 503 이다 — 키를
    붙여넣기 전에, 조직 조회 전에 막는다."""
    existing = await _insert_row(db_session)
    store_env.setattr(settings, missing, "")

    responses = [
        await db_client.post(_BASE, json={"provider": "anthropic", "label": "x", "apiKey": FAKE_API_KEY}),
        await db_client.put(f"{_BASE}/{existing.id}/secret", json={"apiKey": FAKE_API_KEY}),
        await db_client.post(f"{_BASE}/{existing.id}/check"),
        await db_client.put(f"{_BASE}/pool", json={"enabled": True}),
    ]

    assert [(r.status_code, r.json()["detail"]["rule"]) for r in responses] == [(503, "store-not-configured")] * 4
    assert probe.lookups == [] and probe.calls == [] and notes == []


async def test_list_works_without_the_store_and_says_so(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin_id: uuid.UUID,
    notes: list[str],
    store_env: pytest.MonkeyPatch,
) -> None:
    """저장소 설정이 없어도 조회와 되돌리기 쪽(메타 수정·끄기·순서 저장·목록 사용 끄기·삭제)은 된다 — 끄기·삭제가 막히면
    되돌릴 길이 없다. 조회는 저장소·알림이 꺼져 있다고 알린다."""
    existing = await _insert_row(db_session, state="active", state_reason=None)
    for name in ("llm_credential_encryption_keys", "llm_credential_allowed_accounts", "llm_credential_discord_webhook_url"):
        store_env.setattr(settings, name, "")

    listing = await _listing(db_client)
    responses = [
        await db_client.patch(f"{_BASE}/{existing.id}", json={"label": "바꾼 이름"}),
        await db_client.post(f"{_BASE}/{existing.id}/disable"),
        await db_client.put(
            f"{_BASE}/order", json={"baseListRevision": listing["listRevision"], "ids": [str(existing.id)]}
        ),
        await db_client.put(f"{_BASE}/pool", json={"enabled": False}),
        await db_client.delete(f"{_BASE}/{existing.id}"),
    ]

    assert (listing["storeConfigured"], listing["notificationsConfigured"]) == (False, False)
    assert len(listing["credentials"]) == 1
    assert [r.status_code for r in responses] == [200, 200, 200, 200, 204]


# ── 추가 ───────────────────────────────────────────────────────────────────────
async def test_create_stores_an_encrypted_secret_and_returns_no_secret_material(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """붙여넣은 키의 앞뒤 공백을 지운 값을 암호화해 저장하고, 응답에는 끝 4자리와 지문만 싣는다. 공백을 지우지 않으면 같은
    키의 지문이 콘솔에서 계산한 값·env 키의 지문과 어긋난다."""
    body = await _create(db_client, key=f"  {FAKE_API_KEY}\n", creditUsd="50.5", alertPct=30)

    row = await _row(db_session, body["id"])
    assert decrypt_secret(FieldKeyring.parse(FAKE_CREDENTIAL_KEYRING), row) == FAKE_API_KEY
    assert FAKE_API_KEY.encode() not in row.secret_ciphertext
    assert (row.key_id, row.secret_last4, row.secret_fingerprint) == (
        "k1",
        FAKE_API_KEY[-4:],
        secret_fingerprint(FAKE_API_KEY),
    )
    assert (row.credit_micro_usd, row.alert_pct) == (50_500_000, 30)
    assert row.credit_since is not None
    assert probe.lookups == [FAKE_API_KEY]
    assert (body["secretLast4"], body["secretFingerprint"], body["creditUsd"], body["alertPct"]) == (
        FAKE_API_KEY[-4:],
        secret_fingerprint(FAKE_API_KEY),
        "50.50",
        30,
    )
    assert FAKE_API_KEY not in json.dumps(body)


async def test_create_assigns_the_next_position_and_bumps_the_list_revision(
    db_client: httpx.AsyncClient, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """추가는 목록 끝에 붙고 목록 판을 올린다. 삭제는 번호를 다시 매기지 않아 다음 추가는 남은 최대 다음이다."""
    before = (await _listing(db_client))["listRevision"]
    first = await _create(db_client, "첫째 계정")
    probe.organization = _OTHER_ORG
    second = await _create(db_client, "둘째 계정", FAKE_OTHER_API_KEY)
    await db_client.delete(f"{_BASE}/{first['id']}")
    probe.organization = None
    third = await _create(db_client, "셋째 계정")

    assert [first["position"], second["position"], third["position"]] == [1, 2, 3]
    assert (await _listing(db_client))["listRevision"] == before + 4


async def test_new_credential_starts_disabled(
    db_client: httpx.AsyncClient, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """새 항목은 꺼진 채 들어온다 — 확인 호출이 통과한 뒤에 운영자가 켠다."""
    body = await _create(db_client)

    assert (body["state"], body["stateReason"], body["stateVersion"]) == ("disabled", "admin", 0)
    assert body["enableBlocker"] == "check-required"
    assert body["checks"] == []
    assert notes == [
        f"[Claude 자격] 추가 — anthropic · 운영 계정 · 지문 {secret_fingerprint(FAKE_API_KEY)} · 1번째 · 꺼진 채(확인 호출 뒤 켜기)"
    ]


async def test_create_rejects_an_organization_outside_the_allowlist_and_alerts(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """허용 목록 밖 조직의 키는 저장하지 않고, 그 시도를 알린다(어드민 세션이 털렸을 때의 신호). 조직 id 는 응답·알림에
    싣지 않는다."""
    probe.organization = _OUTSIDE_ORG

    resp = await db_client.post(_BASE, json={"provider": "anthropic", "label": "x", "apiKey": FAKE_API_KEY})

    assert resp.status_code == 422
    assert resp.json()["detail"]["rule"] == "account-not-allowed"
    assert _OUTSIDE_ORG not in resp.text
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(LlmCredential)) == 0
    assert notes == ["[Claude 자격] 허용 목록 밖 조직의 키를 넣으려 했다 — 저장하지 않았다"]
    assert await _audits(db_session) == []


async def test_create_without_an_organization_header_saves_an_unverified_credential(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """토큰 세기 응답에 조직 헤더가 없으면 조직 미확인으로 저장하고, 확인 호출이 헤더로 채울 때까지 켤 수 없다."""
    probe.organization = None

    body = await _create(db_client)

    assert (body["accountRef"], body["organizationVerified"], body["enableBlocker"]) == (
        None,
        False,
        "organization-unverified",
    )
    assert (await _row(db_session, body["id"])).account_ref is None
    (note,) = notes
    assert note.endswith("\n조직 헤더가 없어 조직 미확인 — 확인 호출에서 다시 대조한다")


async def test_create_with_an_allowed_organization_header_saves_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    body = await _create(db_client)

    assert (body["accountRef"], body["organizationVerified"]) == (_ORG, True)
    assert (await _row(db_session, body["id"])).account_ref == _ORG


async def test_create_rejects_a_second_credential_for_the_same_organization(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """한 조직은 목록에 한 번 — 같은 계정의 키 둘은 소진도 같이 되어 순서대로 쓰는 뜻이 없다."""
    await _create(db_client)

    resp = await db_client.post(_BASE, json={"provider": "anthropic", "label": "y", "apiKey": FAKE_OTHER_API_KEY})

    assert (resp.status_code, resp.json()["detail"]["rule"]) == (409, "account-already-listed")
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(LlmCredential)) == 1


@pytest.mark.parametrize("kind", ["auth", "credit", "limit", "permission", "model-not-found", "rejected"])
async def test_upstream_rejections_refuse_the_save(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin_id: uuid.UUID,
    probe: FakeProbe,
    notes: list[str],
    kind: ProbeFailureKind,
) -> None:
    """거절된 키는 저장하지 않고 그 이유를 알려 준다(크레딧·한도 거절도 — 충전한 뒤 다시 넣는다)."""
    probe.organization_error = kind

    resp = await db_client.post(_BASE, json={"provider": "anthropic", "label": "x", "apiKey": FAKE_API_KEY})

    assert resp.status_code == 422
    assert {k: resp.json()["detail"][k] for k in ("rule", "reason")} == {"rule": "credential-rejected", "reason": kind}
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(LlmCredential)) == 0
    assert notes == []


async def test_upstream_unavailability_is_503(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    probe.organization_error = "unavailable"

    resp = await db_client.post(_BASE, json={"provider": "anthropic", "label": "x", "apiKey": FAKE_API_KEY})

    assert (resp.status_code, resp.json()["detail"]["rule"]) == (503, "upstream-unavailable")
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(LlmCredential)) == 0


@pytest.mark.parametrize(
    "key",
    [
        pytest.param(FAKE_API_KEY[:20] + "\n" + FAKE_API_KEY[20:], id="newline-inside"),
        pytest.param(FAKE_API_KEY[:20] + "\x00" + FAKE_API_KEY[20:], id="nul-inside"),
        pytest.param(FAKE_API_KEY[:20] + " " + FAKE_API_KEY[20:], id="space-inside"),
        pytest.param(FAKE_API_KEY[:20] + "키" + FAKE_API_KEY[20:], id="non-ascii"),
        pytest.param("sk-ant-short", id="too-short"),
    ],
)
async def test_key_with_a_control_character_is_rejected_before_any_call(
    db_client: httpx.AsyncClient, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str], key: str
) -> None:
    """키 형식(공백 없는 인쇄 가능 ASCII 20~256자)이 아니면 조직 조회 전에 422 다 — 줄바꿈·제어 문자가 섞인 값이 SDK 헤더로
    가면 하위 계층이 그 값을 오류 문장에 싣는다. 응답에는 값을 싣지 않는다."""
    resp = await db_client.post(_BASE, json={"provider": "anthropic", "label": "x", "apiKey": key})

    assert (resp.status_code, resp.json()["detail"]["rule"]) == (422, "secret-format")
    assert probe.lookups == []
    assert FAKE_API_KEY[20:] not in resp.text


async def test_bedrock_is_refused_by_the_schema(
    db_client: httpx.AsyncClient, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    resp = await db_client.post(_BASE, json={"provider": "bedrock", "label": "x", "apiKey": FAKE_API_KEY})

    assert resp.status_code == 422
    assert probe.lookups == []
    assert FAKE_API_KEY not in resp.text


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        pytest.param("POST", _BASE, {"provider": "anthropic", "apiKey": FAKE_API_KEY}, id="missing-field"),
        pytest.param(
            "POST",
            _BASE,
            {"provider": "anthropic", "label": "x", "apiKey": FAKE_API_KEY, "alertPct": "many"},
            id="wrong-type",
        ),
        pytest.param("POST", _BASE, {"provider": "anthropic", "label": "x", "apiKey": [FAKE_API_KEY]}, id="key-as-list"),
        pytest.param(
            "POST",
            _BASE,
            {"provider": "anthropic", "label": "x", "apiKey": FAKE_API_KEY[:20] + "\t" + FAKE_API_KEY[20:]},
            id="secret-format",
        ),
        pytest.param("POST", _BASE, {"provider": "bedrock", "label": "x", "apiKey": FAKE_API_KEY}, id="bedrock"),
        pytest.param("PUT", f"{_BASE}/{_SOME_ID}/secret", {"apiKey": FAKE_API_KEY, "extra": 1, "x": []}, id="valid-body-for-an-unknown-id"),
        pytest.param("PUT", f"{_BASE}/{_SOME_ID}/secret", {"key": FAKE_API_KEY}, id="secret-missing-field"),
    ],
)
async def test_validation_errors_do_not_echo_the_pasted_key(
    db_client: httpx.AsyncClient,
    admin_id: uuid.UUID,
    probe: FakeProbe,
    notes: list[str],
    method: str,
    path: str,
    body: dict[str, Any],
) -> None:
    """FastAPI 의 기본 검증 오류는 오류마다 입력값을(칸이 빠지면 본문 전체를) 되돌려 싣는다 — 키를 붙여넣은 요청이 형식
    오류로 거부되면 그 키가 응답으로 돌아간다. 이 라우터는 입력값·문맥을 지운 오류만 낸다."""
    probe.organization = None
    resp = await db_client.request(method, path, json=body)

    assert resp.status_code in (404, 422)
    assert FAKE_API_KEY not in resp.text
    assert FAKE_API_KEY[-12:] not in resp.text
    detail = resp.json()["detail"]
    if isinstance(detail, list):
        assert all(set(error) == {"type", "loc", "msg"} for error in detail)


# ── 수정 ───────────────────────────────────────────────────────────────────────
async def test_update_changes_metadata_and_restarts_credit_since(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """충전액을 바꾸면 그 기준 시각을 다시 잡고, 라벨만 바꾸면 그대로 둔다. 시계에 기대지 않으려고 기준 시각을 고정 과거
    값으로 넣어 두고 그 값과 견준다."""
    created = await _create(db_client, creditUsd=50, alertPct=20)
    past = datetime(2026, 1, 1, tzinfo=UTC)
    await db_session.execute(
        sa.update(LlmCredential)
        .where(LlmCredential.id == uuid.UUID(created["id"]))
        .values(credit_since=past)
        .execution_options(synchronize_session=False)
    )

    renamed = await db_client.patch(f"{_BASE}/{created['id']}", json={"label": "바꾼 이름"})
    assert renamed.status_code == 200
    assert (await _row(db_session, created["id"])).credit_since == past

    recharged = await db_client.patch(f"{_BASE}/{created['id']}", json={"creditUsd": "80.00", "alertPct": 25})
    assert recharged.status_code == 200
    row = await _row(db_session, created["id"])
    assert (row.label, row.credit_micro_usd, row.alert_pct) == ("바꾼 이름", 80_000_000, 25)
    assert row.credit_since != past
    assert (recharged.json()["creditUsd"], recharged.json()["alertPct"]) == ("80.00", 25)
    assert "충전액 50.00 → 80.00 달러" in notes[-1] and "임계 20 → 25%" in notes[-1]


async def test_update_can_clear_the_credit(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """충전액 칸을 null 로 보내면 지운다(보내지 않은 칸은 그대로다)."""
    created = await _create(db_client, creditUsd="10", alertPct=40)

    resp = await db_client.patch(f"{_BASE}/{created['id']}", json={"creditUsd": None})

    assert resp.status_code == 200
    row = await _row(db_session, created["id"])
    assert (row.credit_micro_usd, row.credit_since, row.alert_pct) == (None, None, 40)
    assert (resp.json()["creditUsd"], resp.json()["creditSince"]) == (None, None)


# ── 키 교체 ─────────────────────────────────────────────────────────────────────
async def test_secret_replace_reencrypts_and_updates_fingerprint_and_last4(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin_id: uuid.UUID,
    probe: FakeProbe,
    notes: list[str],
    store_env: pytest.MonkeyPatch,
) -> None:
    """키 교체는 지금 맨 앞 키로 암호화하고 지문·끝 4자리를 새 키로 바꾼다. 상태와 판은 그대로다."""
    created = await _create(db_client)
    store_env.setattr(settings, "llm_credential_encryption_keys", FAKE_ROTATED_KEYRING)

    resp = await db_client.put(f"{_BASE}/{created['id']}/secret", json={"apiKey": FAKE_OTHER_API_KEY})

    assert resp.status_code == 200
    row = await _row(db_session, created["id"])
    assert row.key_id == "k2"
    assert decrypt_secret(FieldKeyring.parse(FAKE_ROTATED_KEYRING), row) == FAKE_OTHER_API_KEY
    assert (resp.json()["secretLast4"], resp.json()["secretFingerprint"]) == (
        FAKE_OTHER_API_KEY[-4:],
        secret_fingerprint(FAKE_OTHER_API_KEY),
    )
    assert (row.state, row.state_version) == ("disabled", 0)
    assert probe.lookups == [FAKE_API_KEY, FAKE_OTHER_API_KEY]
    assert notes[-1] == (
        f"[Claude 자격] 키 교체 — anthropic · 운영 계정 · 지문 {secret_fingerprint(FAKE_API_KEY)} → "
        f"{secret_fingerprint(FAKE_OTHER_API_KEY)} · 확인 호출 전까지 미확인\n쓰지 않을 키면 콘솔에서 폐기한다"
    )


async def test_secret_replace_rejects_another_organization(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """한 항목은 한 계정이다 — 다른 조직의 키로 바꾸면 그 항목의 충전액·사용액이 다른 계정에 붙는다(그것은 삭제 + 추가)."""
    created = await _create(db_client)
    probe.organization = _OTHER_ORG

    resp = await db_client.put(f"{_BASE}/{created['id']}/secret", json={"apiKey": FAKE_OTHER_API_KEY})

    assert (resp.status_code, resp.json()["detail"]["rule"]) == (422, "account-mismatch")
    row = await _row(db_session, created["id"])
    assert (row.secret_fingerprint, row.account_ref) == (secret_fingerprint(FAKE_API_KEY), _ORG)


async def test_secret_replace_fills_an_unverified_organization_when_the_header_arrives(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    probe.organization = None
    created = await _create(db_client)
    probe.organization = _ORG

    resp = await db_client.put(f"{_BASE}/{created['id']}/secret", json={"apiKey": FAKE_OTHER_API_KEY})

    assert resp.status_code == 200
    assert (resp.json()["accountRef"], resp.json()["organizationVerified"]) == (_ORG, True)


async def test_secret_replace_without_an_organization_header_clears_the_organization(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """새 키의 응답에 조직 헤더가 없으면 옛 조직 표지를 지운다 — 남기면 다른 조직의 키로 바꾼 항목이 확인된 것으로 보인다.
    확인 호출이 헤더로 다시 채울 때까지 켤 수 없다."""
    created = await _create(db_client)
    probe.organization = None

    resp = await db_client.put(f"{_BASE}/{created['id']}/secret", json={"apiKey": FAKE_OTHER_API_KEY})

    assert resp.status_code == 200
    assert (resp.json()["accountRef"], resp.json()["organizationVerified"]) == (None, False)
    assert (await _row(db_session, created["id"])).account_ref is None
    enable = await db_client.post(f"{_BASE}/{created['id']}/enable")
    assert (enable.status_code, enable.json()["detail"]["rule"]) == (409, "organization-unverified")
    assert "\n조직 미확인으로 돌아감" in notes[-1]


async def test_secret_replace_refuses_to_fill_an_organization_already_listed(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """미확인 항목의 새 키가 이미 목록에 있는 조직이면 채우지 않고 409 다. 그 항목은 그대로다."""
    await _create(db_client, "첫째 계정")
    probe.organization = None
    unverified = await _create(db_client, "둘째 계정", FAKE_OTHER_API_KEY)
    probe.organization = _ORG

    resp = await db_client.put(f"{_BASE}/{unverified['id']}/secret", json={"apiKey": FAKE_API_KEY})

    assert (resp.status_code, resp.json()["detail"]["rule"]) == (409, "account-already-listed")
    row = await _row(db_session, unverified["id"])
    assert (row.secret_fingerprint, row.account_ref) == (secret_fingerprint(FAKE_OTHER_API_KEY), None)


async def test_secret_replace_makes_earlier_checks_stale(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """확인 기록은 그때 키의 지문에 묶인다 — 키를 바꾸면 옛 키로 한 확인은 켜기에 세지 않는다."""
    created = await _create(db_client)
    await _check(db_client, created["id"])

    replaced = await db_client.put(f"{_BASE}/{created['id']}/secret", json={"apiKey": FAKE_OTHER_API_KEY})
    enable = await db_client.post(f"{_BASE}/{created['id']}/enable")

    assert {item["isCurrentSecret"] for item in replaced.json()["checks"]} == {False}
    assert (enable.status_code, enable.json()["detail"]["rule"]) == (409, "check-required")


async def test_replacing_with_the_same_key_rewrites_only_the_ciphertext_and_keeps_earlier_checks(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin_id: uuid.UUID,
    probe: FakeProbe,
    notes: list[str],
    store_env: pytest.MonkeyPatch,
) -> None:
    """암호화 키를 잃어 저장한 키를 읽을 수 없게 된 항목은 같은 키를 다시 붙여넣어 살린다. 지문과 판이 그대로라 잃기 전의
    확인이 지금 키의 확인으로 남아 바로 켤 수 있고, 알림은 키가 바뀐 것처럼 미확인이라 하거나 폐기를 권하지 않는다 — 그
    키는 계속 쓰는 키다."""
    lost_keyring = "k9:" + base64.urlsafe_b64encode(b"\x09" * 32).decode()
    store_env.setattr(settings, "llm_credential_encryption_keys", lost_keyring)
    created = await _create(db_client)
    await _check(db_client, created["id"])
    store_env.setattr(settings, "llm_credential_encryption_keys", FAKE_CREDENTIAL_KEYRING)

    resp = await db_client.put(f"{_BASE}/{created['id']}/secret", json={"apiKey": FAKE_API_KEY})

    assert resp.status_code == 200
    row = await _row(db_session, created["id"])
    assert decrypt_secret(FieldKeyring.parse(FAKE_CREDENTIAL_KEYRING), row) == FAKE_API_KEY
    assert {item["isCurrentSecret"] for item in resp.json()["checks"]} == {True}
    enable = await db_client.post(f"{_BASE}/{created['id']}/enable")
    assert enable.status_code == 200
    replaced = [note for note in notes if note.startswith("[Claude 자격] 키 교체")]
    assert replaced == [
        f"[Claude 자격] 키 교체 — anthropic · 운영 계정 · 지문 {secret_fingerprint(FAKE_API_KEY)} · 같은 키 — 암호문만 다시 씀"
    ]


async def test_replacing_with_the_same_key_skips_the_organization_lookup_and_keeps_the_organization(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """같은 키는 같은 조직이다 — 조직 조회를 부르지 않고 조직 표지를 그대로 둔다. 불렀다면 헤더 없는 응답이 표지를 지워
    확인 호출 전까지 켤 수 없게 된다. 알림과 감사는 같은 키라는 한 문구뿐이다."""
    created = await _create(db_client)
    await _check(db_client, created["id"])
    probe.organization = None

    resp = await db_client.put(f"{_BASE}/{created['id']}/secret", json={"apiKey": FAKE_API_KEY})

    assert resp.status_code == 200
    assert probe.lookups == [FAKE_API_KEY]
    assert (resp.json()["accountRef"], resp.json()["organizationVerified"]) == (_ORG, True)
    enable = await db_client.post(f"{_BASE}/{created['id']}/enable")
    assert enable.status_code == 200
    same = f"anthropic · 운영 계정 · 지문 {secret_fingerprint(FAKE_API_KEY)} · 같은 키 — 암호문만 다시 씀"
    assert [note for note in notes if note.startswith("[Claude 자격] 키 교체")] == [f"[Claude 자격] 키 교체 — {same}"]
    audits = [
        log.reason_text for log in await _audits(db_session) if log.action_type == "llm-credential-secret-replace"
    ]
    assert audits == [same]


async def test_secret_replace_refuses_bedrock(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """Bedrock 항목의 키 교체는 아직 없다 — 확인 호출과 같은 규칙으로 422 이고 비밀·조직은 그대로다. 막지 않으면 Anthropic
    키가 Bedrock 항목의 비밀 자리에 들어간다. 조직 조회(외부 호출)보다 먼저 막는다."""
    bedrock = await _insert_row(db_session, provider="bedrock", region="us-east-1", account_ref="123456789012")
    before = (bedrock.key_id, bedrock.secret_ciphertext, bedrock.secret_fingerprint)
    probe.organization = None

    resp = await db_client.put(f"{_BASE}/{bedrock.id}/secret", json={"apiKey": FAKE_OTHER_API_KEY})

    assert (resp.status_code, resp.json()["detail"]["rule"]) == (422, "provider-not-available")
    assert probe.lookups == []
    row = await _row(db_session, bedrock.id)
    assert (row.key_id, row.secret_ciphertext, row.secret_fingerprint) == before
    assert row.account_ref == "123456789012"
    assert notes == []


async def test_secret_replace_rechecks_the_provider_after_locking_the_row(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin_id: uuid.UUID,
    probe: FakeProbe,
    notes: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """잠근 뒤에도 공급자를 다시 본다. 지금은 행의 공급자를 바꾸는 경로가 없어 DB 를 직접 고쳐 흉내 낸다 — 그런 경로가 생겼을
    때 조회 전 읽기만 믿으면 조회를 기다리는 사이 Bedrock 이 된 행의 비밀 자리에 Anthropic 키가 들어간다."""
    created = await _create(db_client)

    async def lookup_while_the_row_becomes_bedrock(api_key: str) -> str | None:
        await db_session.execute(
            sa.update(LlmCredential)
            .where(LlmCredential.id == uuid.UUID(created["id"]))
            .values(provider="bedrock", region="us-east-1")
            .execution_options(synchronize_session=False)
        )
        return _ORG

    monkeypatch.setattr(probe, "organization_of", lookup_while_the_row_becomes_bedrock)

    resp = await db_client.put(f"{_BASE}/{created['id']}/secret", json={"apiKey": FAKE_OTHER_API_KEY})

    assert (resp.status_code, resp.json()["detail"]["rule"]) == (422, "provider-not-available")
    assert (await _row(db_session, created["id"])).secret_fingerprint == secret_fingerprint(FAKE_API_KEY)


async def test_secret_replace_clears_the_organization_when_another_key_landed_after_the_skipped_lookup(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin_id: uuid.UUID,
    probe: FakeProbe,
    notes: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """잠그지 않은 읽기에서 같은 키라 조회를 건너뛰었는데 잠근 뒤 보니 그 사이 다른 키(다른 조직)로 바뀌어 있으면, 붙여넣은
    키의 조직을 모르므로 헤더 없는 응답처럼 조직 표지를 지운다 — 남기면 그 다른 조직의 표지가 붙여넣은 키에 붙는다. 같은
    키인지는 조회를 건너뛴 판정이 아니라 잠근 행으로 다시 가린다."""
    created = await _create(db_client)
    real_get = admin_llm_credentials._get
    reads: list[bool] = []

    async def read_then_another_key_lands(
        db: AsyncSession, credential_id: uuid.UUID, *, lock: bool = False
    ) -> LlmCredential:
        credential = await real_get(db, credential_id, lock=lock)
        reads.append(lock)
        if reads == [False]:
            await db_session.execute(
                sa.update(LlmCredential)
                .where(LlmCredential.id == credential_id)
                .values(secret_fingerprint=secret_fingerprint(FAKE_OTHER_API_KEY), account_ref=_OTHER_ORG)
                .execution_options(synchronize_session=False)
            )
        return credential

    monkeypatch.setattr(admin_llm_credentials, "_get", read_then_another_key_lands)

    resp = await db_client.put(f"{_BASE}/{created['id']}/secret", json={"apiKey": FAKE_API_KEY})

    assert resp.status_code == 200
    assert probe.lookups == [FAKE_API_KEY]
    assert (await _row(db_session, created["id"])).account_ref is None
    old, new = secret_fingerprint(FAKE_OTHER_API_KEY), secret_fingerprint(FAKE_API_KEY)
    assert notes[-1].startswith(f"[Claude 자격] 키 교체 — anthropic · 운영 계정 · 지문 {old} → {new} · ")
    assert notes[-1].endswith("\n조직 미확인으로 돌아감")


# ── 순서 ───────────────────────────────────────────────────────────────────────
async def _three(client: httpx.AsyncClient, probe: FakeProbe) -> list[str]:
    ids = [(await _create(client, "가 계정"))["id"]]
    probe.organization = _OTHER_ORG
    ids.append((await _create(client, "나 계정", FAKE_OTHER_API_KEY))["id"])
    probe.organization = None
    ids.append((await _create(client, "다 계정"))["id"])
    return ids


async def test_reorder_swaps_positions_in_one_save(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """한 번의 저장으로 위치를 서로 바꾼다 — 위치는 즉시 검사하는 유일 칸이라 바로 최종값을 매기면 도중에 겹친다."""
    a, b, c = await _three(db_client, probe)
    revision = (await _listing(db_client))["listRevision"]

    resp = await db_client.put(f"{_BASE}/order", json={"baseListRevision": revision, "ids": [c, a, b]})

    assert resp.status_code == 200, resp.text
    assert [(item["id"], item["position"]) for item in resp.json()["credentials"]] == [(c, 1), (a, 2), (b, 3)]
    assert resp.json()["listRevision"] == revision + 1
    assert notes[-1] == "[Claude 자격] 순서 — 다 계정 → 가 계정 → 나 계정"
    audits = [log.reason_text for log in await _audits(db_session) if log.action_type == "llm-credential-reorder"]
    assert audits == [f"순서: 다 계정 → 가 계정 → 나 계정 (판 {revision + 1})"]


async def test_reorder_with_a_stale_list_revision_is_409(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """화면이 본 목록과 지금 목록이 다르면(그 사이 추가·삭제·순서 저장) 덮어쓰지 않는다."""
    a, b, c = await _three(db_client, probe)
    revision = (await _listing(db_client))["listRevision"]

    resp = await db_client.put(f"{_BASE}/order", json={"baseListRevision": revision - 1, "ids": [c, b, a]})

    assert (resp.status_code, resp.json()["detail"]["rule"]) == (409, "stale-list-revision")
    assert [item["id"] for item in (await _listing(db_client))["credentials"]] == [a, b, c]


@pytest.mark.parametrize("change", ["missing", "extra", "duplicated"])
async def test_reorder_must_name_every_credential_exactly_once(
    db_client: httpx.AsyncClient, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str], change: str
) -> None:
    a, b, c = await _three(db_client, probe)
    revision = (await _listing(db_client))["listRevision"]
    ids = {"missing": [c, a], "extra": [c, a, b, str(uuid.uuid4())], "duplicated": [c, a, a, b]}[change]

    resp = await db_client.put(f"{_BASE}/order", json={"baseListRevision": revision, "ids": ids})

    assert (resp.status_code, resp.json()["detail"]["rule"]) == (422, "order-mismatch")
    assert [item["id"] for item in (await _listing(db_client))["credentials"]] == [a, b, c]


# ── 켜기·끄기 ─────────────────────────────────────────────────────────────────────
async def test_enable_needs_a_passing_check_taken_at_the_current_state_version(
    db_client: httpx.AsyncClient, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """끄면 판이 올라 그 전의 확인은 세지 않는다 — 다시 확인해야 켤 수 있다. 같은 테스트 트랜잭션 안이라 시각은 모두 같고,
    판으로만 갈린다."""
    created = await _create(db_client)
    await _check(db_client, created["id"])
    first = await db_client.post(f"{_BASE}/{created['id']}/enable")
    await db_client.post(f"{_BASE}/{created['id']}/disable")

    refused = await db_client.post(f"{_BASE}/{created['id']}/enable")
    await _allow_another_check(created["id"])
    await _check(db_client, created["id"])
    second = await db_client.post(f"{_BASE}/{created['id']}/enable")

    assert (first.status_code, first.json()["state"], first.json()["stateVersion"]) == (200, "active", 1)
    assert (refused.status_code, refused.json()["detail"]["rule"]) == (409, "check-required")
    assert (second.status_code, second.json()["stateVersion"]) == (200, 3)


async def test_a_check_started_before_a_state_change_does_not_count(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """확인 호출을 기다리는 동안 상태가 바뀌면(여기서는 소진) 그 회차는 시작할 때의 판을 남겨 켜기에 세지 않는다 — 충전하지
    않은 계정을 켰다가 바로 다시 떨어지는 왕복을 막는다."""
    created = await _create(db_client)

    async def exhaust() -> None:
        await db_session.execute(
            sa.update(LlmCredential)
            .where(LlmCredential.id == uuid.UUID(created["id"]))
            .values(state="exhausted", state_reason="credit", state_version=LlmCredential.state_version + 1)
            .execution_options(synchronize_session=False)
        )

    probe.during_check = exhaust
    checked = await _check(db_client, created["id"])
    enable = await db_client.post(f"{_BASE}/{created['id']}/enable")

    assert {row.state_version for row in await _checks(db_session, created["id"])} == {0}
    assert {item["isCurrentStateVersion"] for item in checked["credential"]["checks"]} == {False}
    assert (enable.status_code, enable.json()["detail"]["rule"]) == (409, "check-required")


async def test_enable_refuses_after_a_check_reported_an_organization_mismatch(
    db_client: httpx.AsyncClient, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """한 축이라도 응답 조직이 어긋났으면 다른 축이 통과했어도 켜지 않는다 — 보안 신호다."""
    created = await _create(db_client)
    probe.results[_IDS["sonnet"]] = CheckCallResult(error_kind=None, organization=_OTHER_ORG)
    await _check(db_client, created["id"])

    enable = await db_client.post(f"{_BASE}/{created['id']}/enable")

    assert (enable.status_code, enable.json()["detail"]["rule"]) == (409, "organization-mismatch")


async def test_enable_refuses_an_unverified_organization(
    db_client: httpx.AsyncClient, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    probe.organization = None
    probe.default = CheckCallResult(error_kind=None, organization=None)
    created = await _create(db_client)
    await _check(db_client, created["id"])

    enable = await db_client.post(f"{_BASE}/{created['id']}/enable")

    assert (enable.status_code, enable.json()["detail"]["rule"]) == (409, "organization-unverified")


async def test_enable_refuses_an_organization_removed_from_the_allowlist(
    db_client: httpx.AsyncClient, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str], store_env: pytest.MonkeyPatch
) -> None:
    """env 허용 목록에서 조직을 빼면 그 항목은 다시 켤 수 없다."""
    created = await _create(db_client)
    await _check(db_client, created["id"])
    store_env.setattr(settings, "llm_credential_allowed_accounts", f"anthropic:{_OTHER_ORG}")

    enable = await db_client.post(f"{_BASE}/{created['id']}/enable")

    assert (enable.status_code, enable.json()["detail"]["rule"]) == (409, "account-not-allowed")


async def test_disable_bumps_the_state_version(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """끄기는 판을 올린다. 이미 꺼진 항목을 다시 끄면 아무것도 바꾸지 않는다(감사·알림 없음)."""
    ready = await _ready(db_client)
    first = await db_client.post(f"{_BASE}/{ready['id']}/disable")
    sent = len(notes)
    again = await db_client.post(f"{_BASE}/{ready['id']}/disable")

    assert (first.json()["state"], first.json()["stateReason"], first.json()["stateVersion"]) == ("disabled", "admin", 2)
    assert (again.status_code, again.json()["stateVersion"]) == (200, 2)
    assert len(notes) == sent
    assert [log.action_type for log in await _audits(db_session)].count("llm-credential-disable") == 1


async def test_enabling_an_active_credential_is_a_no_op(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    ready = await _ready(db_client)
    sent = len(notes)

    again = await db_client.post(f"{_BASE}/{ready['id']}/enable")

    assert (again.status_code, again.json()["stateVersion"]) == (200, 1)
    assert len(notes) == sent
    assert [log.action_type for log in await _audits(db_session)].count("llm-credential-enable") == 1


# ── 삭제 ───────────────────────────────────────────────────────────────────────
async def test_delete_removes_the_row_and_its_checks_and_bumps_the_list_revision(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """삭제는 행을 지운다(남는 행에 암호문이 남지 않게) — 확인 기록도 함께. 행이 사라지므로 감사 로그가 유일한 흔적이다."""
    created = await _create(db_client)
    await _check(db_client, created["id"])
    revision = (await _listing(db_client))["listRevision"]

    resp = await db_client.delete(f"{_BASE}/{created['id']}")

    assert resp.status_code == 204
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(LlmCredential)) == 0
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(LlmCredentialCheck)) == 0
    assert (await _listing(db_client))["listRevision"] == revision + 1
    fingerprint = secret_fingerprint(FAKE_API_KEY)
    deleted = [log.reason_text for log in await _audits(db_session) if log.action_type == "llm-credential-delete"]
    assert deleted == [f"anthropic · 운영 계정 · 지문 {fingerprint}"]
    assert notes[-1].startswith(f"[Claude 자격] 삭제 — anthropic · 운영 계정 · 지문 {fingerprint}")
    assert notes[-1].endswith("\n목록이 비었다 — 런타임은 env 키 경로로 돈다")
    missing = await db_client.delete(f"{_BASE}/{created['id']}")
    assert missing.status_code == 404


async def test_delete_message_warns_not_to_revoke_the_env_rollback_key(
    db_client: httpx.AsyncClient, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str], store_env: pytest.MonkeyPatch
) -> None:
    """지운 항목의 키가 env 롤백 키와 같으면 콘솔에서 폐기하지 말라고 알린다 — env 되돌리기 경로가 같은 키를 쓴다."""
    store_env.setattr(settings, "anthropic_direct_api_key", FAKE_API_KEY)
    created = await _create(db_client)

    await db_client.delete(f"{_BASE}/{created['id']}")

    assert "\nenv 롤백 키와 같은 키다 — 콘솔에서 폐기하지 마라(env 되돌리기 경로가 같은 키를 쓴다)" in notes[-1]
    assert "쓰지 않을 키면" not in notes[-1]


async def test_delete_message_suggests_revoking_other_keys(
    db_client: httpx.AsyncClient, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    created = await _create(db_client)

    await db_client.delete(f"{_BASE}/{created['id']}")

    assert "\n쓰지 않을 키면 콘솔에서 폐기한다" in notes[-1]
    assert "폐기하지 마라" not in notes[-1]


# ── 확인 호출 ─────────────────────────────────────────────────────────────────────
async def test_check_records_one_row_per_axis_with_the_current_fingerprint_run_and_state_version(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """한 번의 확인이 축마다 한 행을 같은 회차로 남긴다 — 확인을 시작할 때의 판과 키 지문, 실제로 보낸 모델 id 를 함께."""
    created = await _create(db_client)

    body = await _check(db_client, created["id"])

    rows = await _checks(db_session, created["id"])
    fingerprint = secret_fingerprint(FAKE_API_KEY)
    assert sorted(
        (r.model_axis, r.run, r.state_version, r.secret_fingerprint, r.sent_model_id, r.passed, r.organization_header)
        for r in rows
    ) == sorted((axis, 1, 0, fingerprint, _IDS[axis], True, _ORG) for axis in _AXES_IN_ORDER)
    assert body["calls"] == 3
    assert [item["modelAxis"] for item in body["credential"]["checks"]] == _AXES_IN_ORDER
    assert {
        (item["isCurrentSecret"], item["isCurrentModelId"], item["isCurrentStateVersion"])
        for item in body["credential"]["checks"]
    } == {(True, True, True)}
    assert body["credential"]["enableBlocker"] is None
    assert notes[-1] == (
        f"[Claude 자격] 확인 — anthropic · 운영 계정 · 지문 {fingerprint} · opus 통과 · sonnet 통과 · haiku_writer 통과 · "
        "haiku 통과"
    )


async def test_check_runs_are_numbered_per_credential(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """회차는 항목마다 따로 1 부터 매기고, 한 번의 확인이 쓴 행은 모든 축이 같은 회차다 — 축마다 따로 매기면 축마다 최신이
    서로 다른 확인에서 와서 "한 번의 확인"이 깨진다."""
    first = await _create(db_client, "첫째 계정")
    probe.organization = _OTHER_ORG
    probe.default = CheckCallResult(error_kind=None, organization=_OTHER_ORG)
    second = await _create(db_client, "둘째 계정", FAKE_OTHER_API_KEY)
    # 앞선 확인이 한 축만 남긴 회차가 있다(그때 모델 라인업이 달랐다).
    db_session.add(
        LlmCredentialCheck(
            credential_id=uuid.UUID(second["id"]),
            run=5,
            state_version=0,
            model_axis="opus",
            sent_model_id="claude-opus-5-0",
            secret_fingerprint=secret_fingerprint(FAKE_OTHER_API_KEY),
            passed=True,
            error_kind=None,
        )
    )
    await db_session.flush()
    probe.default = CheckCallResult(error_kind=None, organization=_ORG)
    await _check(db_client, first["id"])
    probe.default = CheckCallResult(error_kind=None, organization=_OTHER_ORG)
    await _check(db_client, second["id"])

    assert {r.run for r in await _checks(db_session, first["id"])} == {1}
    second_runs = Counter(r.run for r in await _checks(db_session, second["id"]))
    assert second_runs == Counter({5: 1, 6: 4})


async def test_shared_model_id_is_called_once_and_recorded_for_each_axis(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """같은 실제 id 를 쓰는 축(기본 설정의 Haiku 글쓰기·판정)은 한 번만 부르고 그 결과를 축마다 남긴다."""
    created = await _create(db_client)

    body = await _check(db_client, created["id"])

    assert [group.model_id for group in probe.calls] == [_IDS["opus"], _IDS["sonnet"], _IDS["haiku"]]
    assert body["calls"] == 3
    rows = {r.model_axis: r.sent_model_id for r in await _checks(db_session, created["id"])}
    assert rows["haiku_writer"] == rows["haiku"] == _IDS["haiku"]


async def test_second_check_within_a_minute_is_429(
    db_client: httpx.AsyncClient, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """확인 호출은 항목마다 분당 한 번이다(호출마다 실제 비용이 든다). 넘으면 부르지 않는다."""
    created = await _create(db_client)
    await _check(db_client, created["id"])
    calls = len(probe.calls)

    again = await db_client.post(f"{_BASE}/{created['id']}/check")

    assert again.status_code == 429
    detail = again.json()["detail"]
    assert (detail["code"], detail["window"]) == ("LLM_CREDENTIAL_CHECK_LIMIT", "llm-credential-check")
    assert 0 < detail["retryAfterSeconds"] <= 60
    assert len(probe.calls) == calls


async def test_check_fails_an_axis_whose_response_organization_differs(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """응답의 조직이 저장된 조직과 다르면 그 축은 실패이고, 보안 신호로 따로 알린다."""
    created = await _create(db_client)
    probe.results[_IDS["sonnet"]] = CheckCallResult(error_kind=None, organization=_OTHER_ORG)

    await _check(db_client, created["id"])

    rows = {r.model_axis: r for r in await _checks(db_session, created["id"])}
    assert (rows["sonnet"].passed, rows["sonnet"].error_kind, rows["sonnet"].organization_header) == (
        False,
        "organization-mismatch",
        _OTHER_ORG,
    )
    assert {axis for axis, row in rows.items() if row.passed} == {"opus", "haiku_writer", "haiku"}
    assert "[Claude 자격] 확인 응답의 조직이 저장된 조직과 다르다 — 운영 계정" in notes
    assert all(_OTHER_ORG not in note and _ORG not in note for note in notes)


async def test_check_passes_a_verified_credential_whose_responses_carry_no_organization_header(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """조직이 저장 때 확인된 항목은 응답에 조직 헤더가 없어도 통과다 — 규칙은 "다르면 실패"뿐이고, 헤더가 없는 것은 다른
    조직이라는 증거가 아니다. 다만 그 통과는 응답 조직을 대조하지 않아 조직 불일치를 풀지 못하므로, 알림·감사 문구가 헤더가
    없었다고 적는다."""
    created = await _create(db_client)
    probe.default = CheckCallResult(error_kind=None, organization=None)

    await _check(db_client, created["id"])

    assert {(r.passed, r.error_kind) for r in await _checks(db_session, created["id"])} == {(True, None)}
    assert (await _row(db_session, created["id"])).account_ref == _ORG
    plain = "통과(조직 헤더 없음)"
    assert notes[-1] == (
        f"[Claude 자격] 확인 — anthropic · 운영 계정 · 지문 {secret_fingerprint(FAKE_API_KEY)} · opus {plain} · "
        f"sonnet {plain} · haiku_writer {plain} · haiku {plain}"
    )


async def test_transient_check_errors_keep_earlier_passes_at_runtime_but_never_count_for_turning_on(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """켜진 항목을 확인하다 Anthropic 이 잠깐 429·과부하를 내면 그 회차는 축마다 일시 오류로 남되, 런타임은 그 축의 이전
    통과를 그대로 쓴다 — 항목이 후보에서 빠지지 않는다. 알림·감사 문구는 그 축이 이전 결과를 유지한다고 말한다. 켜기와 목록
    사용 켜기는 최신 회차의 확정 통과를 요구하므로 그 회차로는 켜지 않는다."""
    ready = await _ready(db_client)
    probe.default = CheckCallResult(error_kind="unavailable", organization=None)
    await _allow_another_check(ready["id"])

    body = await _check(db_client, ready["id"])

    row = await _row(db_session, ready["id"])
    assert credentials.passed_axes(row, await _checks(db_session, ready["id"])) == frozenset(_AXES_IN_ORDER)
    kept = "일시 오류(이전 결과 유지)"
    results = f"opus {kept} · sonnet {kept} · haiku_writer {kept} · haiku {kept}"
    assert notes[-1] == f"[Claude 자격] 확인 — anthropic · 운영 계정 · 지문 {secret_fingerprint(FAKE_API_KEY)} · {results}"
    assert body["credential"]["enableBlocker"] == "check-required"
    pool = await db_client.put(f"{_BASE}/pool", json={"enabled": True})
    assert (pool.status_code, pool.json()["detail"]["axes"]) == (409, _AXES_IN_ORDER)


async def test_listing_adds_the_runtime_basis_row_under_a_transient_latest_check(
    db_client: httpx.AsyncClient, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """화면이 런타임과 같은 답을 내도록, 축마다 최신 기록이 일시 오류면 그 아래 지금 키의 결론(런타임이 그 축에 쓰는 기록)을
    바로 뒤에 하나 더 싣는다. 최신 기록이 이미 그 결론이면 행 하나이고, 일시 오류 아래에 결론이 없으면 최신 기록 하나만
    런타임 기록이 아닌 채로 싣는다."""
    ready = await _ready(db_client)
    probe.results[_IDS["haiku"]] = CheckCallResult(error_kind="unavailable", organization=None)
    await _allow_another_check(ready["id"])
    await _check(db_client, ready["id"])
    probe.results.clear()
    probe.organization = _OTHER_ORG
    probe.default = CheckCallResult(error_kind="unavailable", organization=None)
    never_concluded = await _create(db_client, "둘째 계정", FAKE_OTHER_API_KEY)
    await _check(db_client, never_concluded["id"])

    first, second = (await _listing(db_client))["credentials"]

    assert [(c["modelAxis"], c["run"], c["errorKind"], c["isRuntimeBasis"]) for c in first["checks"]] == [
        ("opus", 2, None, True),
        ("sonnet", 2, None, True),
        ("haiku_writer", 2, "unavailable", False),
        ("haiku_writer", 1, None, True),
        ("haiku", 2, "unavailable", False),
        ("haiku", 1, None, True),
    ]
    assert [(c["modelAxis"], c["run"], c["isRuntimeBasis"]) for c in second["checks"]] == [
        (axis, 1, False) for axis in _AXES_IN_ORDER
    ]
    assert (first["runtimeAxes"], second["runtimeAxes"]) == (_AXES_IN_ORDER, [])


async def test_an_uncleared_organization_mismatch_drops_the_item_from_runtime_enable_and_pool_on(
    db_client: httpx.AsyncClient, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """확인에서 Haiku 응답의 조직이 어긋난 뒤 다음 확인에서 Haiku 만 429 를 내고 나머지가 통과하면, 어긋난 축이 다시 통과하지
    않았으므로 서버가 계산한 런타임 축(`runtimeAxes`)은 비고, 켜기는 조직 불일치로 막히고, 목록 사용 켜기도 어느 축도 덮였다고
    보지 않는다 — 셋이 같은 조직 규칙을 쓴다. Haiku 가 다시 통과하면 풀린다."""
    ready = await _ready(db_client)
    probe.results[_IDS["haiku"]] = CheckCallResult(error_kind=None, organization=_OTHER_ORG)
    await _allow_another_check(ready["id"])
    await _check(db_client, ready["id"])
    probe.results[_IDS["haiku"]] = CheckCallResult(error_kind="unavailable", organization=None)
    await _allow_another_check(ready["id"])
    await _check(db_client, ready["id"])

    (item,) = (await _listing(db_client))["credentials"]
    pool = await db_client.put(f"{_BASE}/pool", json={"enabled": True})
    probe.results.clear()
    await _allow_another_check(ready["id"])
    cleared = (await _check(db_client, ready["id"]))["credential"]

    assert (item["runtimeAxes"], item["enableBlocker"]) == ([], "organization-mismatch")
    assert (pool.status_code, pool.json()["detail"]["axes"]) == (409, _AXES_IN_ORDER)
    assert (cleared["runtimeAxes"], cleared["enableBlocker"]) == (_AXES_IN_ORDER, None)


async def test_returning_to_an_earlier_key_counts_its_earlier_checks_again(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """키를 A 에서 B 로 바꾼 뒤 B 의 첫 확인이 429 뿐이면 B 는 어느 축도 받지 않고, 알림은 일시 오류 축이 이 키로 한 이전 결과가
    없어 아직 쓰지 않는다고 말한다(옛 키 A 의 통과가 이어지는 것처럼 읽히지 않게). 다시 A 로 되돌리면 확인 기록이 지문으로 그때의
    키에 묶이므로 A 로 한 예전 확인이 다시 지금 키의 확인으로 세어 런타임이 바로 A 를 쓰고, 알림도 미확인이 아니라 그렇게 말한다."""
    ready = await _ready(db_client)
    key_a, key_b = secret_fingerprint(FAKE_API_KEY), secret_fingerprint(FAKE_OTHER_API_KEY)
    assert (await db_client.put(f"{_BASE}/{ready['id']}/secret", json={"apiKey": FAKE_OTHER_API_KEY})).status_code == 200
    probe.default = CheckCallResult(error_kind="unavailable", organization=None)
    await _allow_another_check(ready["id"])
    under_b = (await _check(db_client, ready["id"]))["credential"]
    transient_note = notes[-1]

    back = await db_client.put(f"{_BASE}/{ready['id']}/secret", json={"apiKey": FAKE_API_KEY})

    unused = "일시 오류(이 키로 한 이전 결과 없음 — 이 모델은 아직 쓰지 않는다)"
    assert transient_note == (
        f"[Claude 자격] 확인 — anthropic · 운영 계정 · 지문 {key_b} · opus {unused} · sonnet {unused} · "
        f"haiku_writer {unused} · haiku {unused}"
    )
    assert under_b["runtimeAxes"] == []
    assert back.status_code == 200
    assert notes[-1] == (
        f"[Claude 자격] 키 교체 — anthropic · 운영 계정 · 지문 {key_b} → {key_a} · 이 키로 한 이전 확인이 다시 센다\n"
        "쓰지 않을 키면 콘솔에서 폐기한다"
    )
    assert back.json()["runtimeAxes"] == _AXES_IN_ORDER
    row = await _row(db_session, ready["id"])
    assert credentials.passed_axes(row, await _checks(db_session, ready["id"])) == frozenset(_AXES_IN_ORDER)


async def test_check_on_an_unverified_credential_fails_a_later_axis_whose_header_differs_from_the_first(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """미확인 항목의 확인에서는 첫 허용 헤더가 그 확인의 기준이 된다 — 뒤 응답이 다른 허용 조직이면 그 축은 불일치다. 둘 다
    허용 목록 안이라 허용 검사만으로는 갈리지 않는다."""
    probe.organization = None
    created = await _create(db_client)
    probe.results[_IDS["sonnet"]] = CheckCallResult(error_kind=None, organization=_OTHER_ORG)

    await _check(db_client, created["id"])

    rows = {r.model_axis: r for r in await _checks(db_session, created["id"])}
    assert (rows["opus"].passed, rows["sonnet"].error_kind) == (True, "organization-mismatch")
    assert (await _row(db_session, created["id"])).account_ref == _ORG


async def test_check_does_not_fill_the_organization_when_the_key_changed_during_the_calls(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """호출을 기다리는 동안 키가 바뀌었으면 응답의 조직을 채우지 않는다 — 그 헤더는 옛 키의 조직이라 새 키의 조직이라는
    증거가 아니다. 기록은 시작할 때의 지문으로 남아 새 키의 확인으로 세지 않는다."""
    probe.organization = None
    created = await _create(db_client)

    async def replace_key() -> None:
        await db_session.execute(
            sa.update(LlmCredential)
            .where(LlmCredential.id == uuid.UUID(created["id"]))
            .values(secret_fingerprint=secret_fingerprint(FAKE_OTHER_API_KEY))
            .execution_options(synchronize_session=False)
        )

    probe.during_check = replace_key
    await _check(db_client, created["id"])

    assert (await _row(db_session, created["id"])).account_ref is None
    assert {r.secret_fingerprint for r in await _checks(db_session, created["id"])} == {
        secret_fingerprint(FAKE_API_KEY)
    }
    assert not [note for note in notes if note.endswith("\n조직 확인됨")]


async def test_check_fills_an_unverified_organization_from_the_response_header(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    probe.organization = None
    created = await _create(db_client)

    body = await _check(db_client, created["id"])

    assert (body["credential"]["accountRef"], body["credential"]["organizationVerified"]) == (_ORG, True)
    assert (await _row(db_session, created["id"])).account_ref == _ORG
    assert notes[-1].endswith("\n조직 확인됨")
    enable = await db_client.post(f"{_BASE}/{created['id']}/enable")
    assert enable.status_code == 200


async def test_check_does_not_fill_an_organization_outside_the_allowlist_and_alerts(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """미확인 항목의 응답 조직이 허용 목록 밖이면 채우지 않고 그 축을 실패로 남기며, 보안 신호로 알린다."""
    probe.organization = None
    created = await _create(db_client)
    probe.default = CheckCallResult(error_kind=None, organization=_OUTSIDE_ORG)

    await _check(db_client, created["id"])

    assert {(r.passed, r.error_kind) for r in await _checks(db_session, created["id"])} == {
        (False, "account-not-allowed")
    }
    assert (await _row(db_session, created["id"])).account_ref is None
    assert "[Claude 자격] 확인 응답의 조직이 허용 목록 밖이다 — 운영 계정" in notes
    assert all(_OUTSIDE_ORG not in note for note in notes)


async def test_check_refuses_to_fill_an_organization_already_listed(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """미확인 항목의 응답 조직이 이미 목록에 있는 조직이면 채우지 않고 그 축들을 `account-already-listed` 로 남긴다."""
    await _create(db_client, "첫째 계정")
    probe.organization = None
    unverified = await _create(db_client, "둘째 계정", FAKE_OTHER_API_KEY)

    body = await _check(db_client, unverified["id"])

    assert {(r.passed, r.error_kind) for r in await _checks(db_session, unverified["id"])} == {
        (False, "account-already-listed")
    }
    assert body["credential"]["accountRef"] is None
    assert (await _row(db_session, unverified["id"])).account_ref is None


async def test_check_without_any_organization_header_keeps_the_credential_unenableable_and_alerts(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """저장·확인 둘 다 조직 헤더가 없으면 모델 접근은 통과로 남기되 항목은 미확인이라 켤 수 없고, 그 사실을 알린다."""
    probe.organization = None
    probe.default = CheckCallResult(error_kind=None, organization=None)
    created = await _create(db_client)

    await _check(db_client, created["id"])

    assert {r.passed for r in await _checks(db_session, created["id"])} == {True}
    assert "[Claude 자격] 저장·확인 둘 다 조직 헤더가 없다 — 운영 계정 은 켤 수 없다" in notes
    enable = await db_client.post(f"{_BASE}/{created['id']}/enable")
    assert (enable.status_code, enable.json()["detail"]["rule"]) == (409, "organization-unverified")


async def test_check_on_a_credential_deleted_during_the_calls_is_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """호출을 기다리는 동안 항목이 지워졌으면 확인 기록을 남기지 않고 404 다."""
    created = await _create(db_client)

    async def delete() -> None:
        await db_session.execute(
            sa.delete(LlmCredential)
            .where(LlmCredential.id == uuid.UUID(created["id"]))
            .execution_options(synchronize_session=False)
        )

    probe.during_check = delete
    resp = await db_client.post(f"{_BASE}/{created['id']}/check")

    assert resp.status_code == 404
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(LlmCredentialCheck)) == 0


async def test_check_alerts_an_organization_mismatch_even_when_the_credential_was_deleted_during_the_calls(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """응답이 다른 조직을 보였다는 보안 신호는 기록 쓰기가 404 로 끝나도 나간다 — 그 키가 다른 조직의 키라는 사실은 항목이
    사라져도 그대로다. 변경 알림(확인 결과)은 쓰기가 성공했을 때만이라 나가지 않는다."""
    created = await _create(db_client)
    probe.results[_IDS["sonnet"]] = CheckCallResult(error_kind=None, organization=_OTHER_ORG)

    async def delete() -> None:
        await db_session.execute(
            sa.delete(LlmCredential)
            .where(LlmCredential.id == uuid.UUID(created["id"]))
            .execution_options(synchronize_session=False)
        )

    probe.during_check = delete
    resp = await db_client.post(f"{_BASE}/{created['id']}/check")

    assert resp.status_code == 404
    assert notes[1:] == ["[Claude 자격] 확인 응답의 조직이 저장된 조직과 다르다 — 운영 계정"]


async def test_check_refuses_bedrock(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    bedrock = await _insert_row(db_session, provider="bedrock", region="us-east-1")

    resp = await db_client.post(f"{_BASE}/{bedrock.id}/check")

    assert (resp.status_code, resp.json()["detail"]["rule"]) == (422, "provider-not-available")
    assert probe.calls == []


async def test_check_on_an_unreadable_secret_is_409(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin_id: uuid.UUID,
    probe: FakeProbe,
    notes: list[str],
    store_env: pytest.MonkeyPatch,
) -> None:
    """저장한 키를 지금 키링으로 읽을 수 없으면(그 키를 잃음) 부르지 않고 409 다 — 키를 다시 붙여넣어야 한다."""
    created = await _create(db_client)
    store_env.setattr(settings, "llm_credential_encryption_keys", FAKE_ROTATED_KEYRING.split(",", 1)[0])

    resp = await db_client.post(f"{_BASE}/{created['id']}/check")

    assert (resp.status_code, resp.json()["detail"]["rule"]) == (409, "secret-unreadable")
    assert probe.calls == []
    assert await _checks(db_session, created["id"]) == []


def _sdk_backed(monkeypatch: pytest.MonkeyPatch, *, failing_model: str | None = None) -> list[httpx2.Request]:
    """실제 조사를 쓰고 SDK 의 전송 계층만 바꿔 낀다 — 토큰 세기는 허용 조직 헤더로, 확인은 메시지 하나로 답한다."""
    seen: list[httpx2.Request] = []
    message = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "m",
        "content": [{"type": "text", "text": "네"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 12, "output_tokens": 3, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        headers = {"anthropic-organization-id": _ORG}
        if request.url.path.endswith("count_tokens"):
            return httpx2.Response(200, json={"input_tokens": 3}, headers=headers)
        if json.loads(request.content)["model"] == failing_model:
            return httpx2.Response(402, json={"type": "error", "error": {"type": "billing_error", "message": "m"}})
        return httpx2.Response(200, json=message, headers=headers)

    real = anthropic.AsyncAnthropic

    def build(**kwargs: Any) -> anthropic.AsyncAnthropic:
        return real(**kwargs, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))

    monkeypatch.setattr(credential_probe, "AsyncAnthropic", build)
    return seen


async def test_check_writes_a_usage_log_line_per_call(
    db_client: httpx.AsyncClient,
    admin_id: uuid.UUID,
    notes: list[str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """확인 호출은 사용량 기록·호출 위치를 만들지 않고, 실제 호출마다 고정 토큰 줄 하나를 남긴다(실패면 종류만)."""
    _sdk_backed(monkeypatch, failing_model=_IDS["sonnet"])
    created = await _create(db_client)
    caplog.set_level(logging.WARNING, logger="api.llm.credential_probe")

    await _check(db_client, created["id"])

    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("anthropic_credential_check_usage")]
    prefix = f"anthropic_credential_check_usage credential_id={created['id']}"
    assert lines == [
        f"{prefix} model={_IDS['opus']} input_tokens=12 output_tokens=3 cache_read_tokens=0 cache_write_tokens=0",
        f"{prefix} model={_IDS['sonnet']} outcome=credit",
        f"{prefix} model={_IDS['haiku']} input_tokens=12 output_tokens=3 cache_read_tokens=0 cache_write_tokens=0",
    ]


# ── 목록 사용 ─────────────────────────────────────────────────────────────────────
async def test_pool_on_requires_every_axis_covered_by_a_current_check(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """목록 사용은 모든 축이 켜진 항목의 지금 키·지금 모델 id 확인 통과로 덮일 때만 켠다."""
    empty = await db_client.put(f"{_BASE}/pool", json={"enabled": True})
    probe.results[_IDS["haiku"]] = CheckCallResult(error_kind="credit", organization=_ORG)
    ready = await _ready(db_client)
    partial = await db_client.put(f"{_BASE}/pool", json={"enabled": True})
    probe.results.clear()
    await _allow_another_check(ready["id"])
    await _check(db_client, ready["id"])

    on = await db_client.put(f"{_BASE}/pool", json={"enabled": True})

    assert (empty.status_code, empty.json()["detail"]["rule"], empty.json()["detail"]["axes"]) == (
        409,
        "pool-uncovered",
        _AXES_IN_ORDER,
    )
    assert partial.json()["detail"]["axes"] == ["haiku_writer", "haiku"]
    assert (on.status_code, on.json()["poolEnabled"]) == (200, True)
    assert notes[-1] == "[Claude 자격] 목록 사용 켬"
    assert (await db_session.scalar(sa.select(LlmCredentialSettings.pool_enabled))) is True


async def test_pool_on_after_a_model_id_change_needs_new_checks(
    db_client: httpx.AsyncClient, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str], store_env: pytest.MonkeyPatch
) -> None:
    """모델 id 설정을 바꾸면 옛 id 로 한 확인으로는 목록 사용을 켤 수 없다 — 항목마다 새 id 로 다시 확인해야 한다."""
    ready = await _ready(db_client)
    store_env.setattr(settings, "anthropic_opus_model_id", "claude-opus-6-0")

    refused = await db_client.put(f"{_BASE}/pool", json={"enabled": True})
    await _allow_another_check(ready["id"])
    await _check(db_client, ready["id"])
    on = await db_client.put(f"{_BASE}/pool", json={"enabled": True})

    assert (refused.status_code, refused.json()["detail"]["axes"]) == (409, ["opus"])
    assert on.status_code == 200


async def test_pool_off_always_works(
    db_client: httpx.AsyncClient, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str], store_env: pytest.MonkeyPatch
) -> None:
    """끄기는 되돌리기 첫 단계라 저장소 설정 없이도 된다."""
    await _ready(db_client)
    assert (await db_client.put(f"{_BASE}/pool", json={"enabled": True})).status_code == 200
    store_env.setattr(settings, "llm_credential_encryption_keys", "")

    off = await db_client.put(f"{_BASE}/pool", json={"enabled": False})

    assert (off.status_code, off.json()["poolEnabled"]) == (200, False)
    assert notes[-1] == "[Claude 자격] 목록 사용 끔"


# ── env 롤백 키 표지 ──────────────────────────────────────────────────────────────
async def test_same_as_env_key_flag_follows_the_current_env_key(
    db_client: httpx.AsyncClient, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str], store_env: pytest.MonkeyPatch
) -> None:
    """env 롤백 키와 같은 키인지는 저장 때가 아니라 볼 때의 env 키로 계산한다."""
    store_env.setattr(settings, "anthropic_direct_api_key", FAKE_API_KEY)
    created = await _create(db_client)
    store_env.setattr(settings, "anthropic_direct_api_key", FAKE_OTHER_API_KEY)

    listing = await _listing(db_client)

    assert created["sameAsEnvKey"] is True
    assert listing["credentials"][0]["sameAsEnvKey"] is False
    assert notes[0].endswith("\nenv 롤백 키와 같은 키다 — 이 항목을 지우거나 교체해도 콘솔에서 폐기하지 마라")


# ── 감사·알림 ─────────────────────────────────────────────────────────────────────
async def test_every_change_writes_one_audit_row_and_one_notification(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """성공한 변경마다 감사 한 행과 알림 한 건이다. 감사 행은 대상 칸이 비어 회원 상세가 읽지 않는다."""
    created = await _create(db_client)
    await _check(db_client, created["id"])
    await db_client.post(f"{_BASE}/{created['id']}/enable")
    await db_client.put(f"{_BASE}/pool", json={"enabled": True})
    await db_client.put(f"{_BASE}/pool", json={"enabled": False})
    await db_client.patch(f"{_BASE}/{created['id']}", json={"alertPct": 30})
    await db_client.put(f"{_BASE}/{created['id']}/secret", json={"apiKey": FAKE_OTHER_API_KEY})
    await db_client.post(f"{_BASE}/{created['id']}/disable")
    revision = (await _listing(db_client))["listRevision"]
    await db_client.put(f"{_BASE}/order", json={"baseListRevision": revision, "ids": [created["id"]]})
    await db_client.delete(f"{_BASE}/{created['id']}")

    audits = await _audits(db_session)
    assert Counter(log.action_type for log in audits) == Counter(
        [
            "llm-credential-add",
            "llm-credential-check",
            "llm-credential-enable",
            "llm-credential-pool-on",
            "llm-credential-pool-off",
            "llm-credential-update",
            "llm-credential-secret-replace",
            "llm-credential-disable",
            "llm-credential-reorder",
            "llm-credential-delete",
        ]
    )
    assert all(
        (log.admin_id, log.target_user_id, log.target_content_id, log.target_novel_id) == (admin_id, None, None, None)
        for log in audits
    )
    assert len(notes) == 10


async def _flow(client: httpx.AsyncClient, db_session: AsyncSession) -> list[str]:
    """추가 → 확인 → 키 교체 → 삭제를 거치며 남는 비밀 표지(원문·암호문 hex·base64 둘)를 모은다."""
    created = await _create(client)
    first_blob = (await _row(db_session, created["id"])).secret_ciphertext
    await _check(client, created["id"])
    await client.put(f"{_BASE}/{created['id']}/secret", json={"apiKey": FAKE_OTHER_API_KEY})
    second_blob = (await _row(db_session, created["id"])).secret_ciphertext
    await client.delete(f"{_BASE}/{created['id']}")
    secrets = [FAKE_API_KEY, FAKE_OTHER_API_KEY]
    for blob in (first_blob, second_blob):
        secrets += [blob.hex(), blob[:31].hex(), base64.b64encode(blob).decode(), base64.urlsafe_b64encode(blob).decode()]
    return secrets


async def test_audit_rows_carry_no_secret_material(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    secrets = await _flow(db_client, db_session)

    texts = [log.reason_text for log in await _audits(db_session)]
    assert len(texts) == 4
    assert not [secret for secret in secrets for text in texts if secret in text]


async def test_notifications_carry_no_secret_material(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """알림은 외부 채널이라 원문·암호문은 물론 조직 id 도 싣지 않는다."""
    secrets = await _flow(db_client, db_session) + [_ORG]

    assert len(notes) == 4
    assert not [secret for secret in secrets for note in notes if secret in note]


async def test_audit_and_notifications_never_carry_the_key_last4(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """끝 4자리는 화면 힌트로만 쓴다 — 원문의 부분 문자열이라 원문 탐색으로는 잡히지 않아 따로 본다."""
    await _flow(db_client, db_session)

    texts = [log.reason_text for log in await _audits(db_session)] + notes
    for last4 in (FAKE_API_KEY[-4:], FAKE_OTHER_API_KEY[-4:]):
        assert not [text for text in texts if last4 in text]


# ── 노출 ───────────────────────────────────────────────────────────────────────
async def test_responses_never_carry_secret_material(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """모든 라우트 응답에 키 원문·암호문(hex·표준 base64·URL base64)이 없다."""
    created = await _create(db_client)
    first_blob = (await _row(db_session, created["id"])).secret_ciphertext
    texts = [json.dumps(created)]
    texts.append((await db_client.post(f"{_BASE}/{created['id']}/check")).text)
    texts.append((await db_client.post(f"{_BASE}/{created['id']}/enable")).text)
    texts.append((await db_client.put(f"{_BASE}/pool", json={"enabled": True})).text)
    texts.append((await db_client.patch(f"{_BASE}/{created['id']}", json={"label": "새 이름"})).text)
    texts.append((await db_client.put(f"{_BASE}/{created['id']}/secret", json={"apiKey": FAKE_OTHER_API_KEY})).text)
    second_blob = (await _row(db_session, created["id"])).secret_ciphertext
    texts.append((await db_client.post(f"{_BASE}/{created['id']}/disable")).text)
    revision = (await _listing(db_client))["listRevision"]
    texts.append((await db_client.put(f"{_BASE}/order", json={"baseListRevision": revision, "ids": [created["id"]]})).text)
    texts.append((await db_client.get(_BASE)).text)
    texts.append((await db_client.delete(f"{_BASE}/{created['id']}")).text)

    secrets = [FAKE_API_KEY, FAKE_OTHER_API_KEY]
    for blob in (first_blob, second_blob):
        secrets += [blob[:31].hex(), base64.b64encode(blob)[:40].decode(), base64.urlsafe_b64encode(blob)[:40].decode()]
    assert not [secret for secret in secrets for text in texts if secret in text]


async def test_credential_response_has_exactly_these_fields(
    db_client: httpx.AsyncClient, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """응답 칸 집합이 정확히 이것이다 — 키 id 처럼 비밀이 아닌 값의 새 칸은 비밀 문자열 탐색으로는 잡히지 않는다."""
    created = await _create(db_client)
    checked = await _check(db_client, created["id"])
    listing = await _listing(db_client)

    assert set(checked) == {"credential", "calls"}
    assert set(listing) == _LIST_FIELDS
    assert set(listing["modelIds"]) == set(_AXES_IN_ORDER)
    for credential in (created, checked["credential"], listing["credentials"][0]):
        assert set(credential) == _CREDENTIAL_FIELDS
    assert {frozenset(item) for item in listing["credentials"][0]["checks"]} == {frozenset(_CHECK_FIELDS)}


def _chain_texts(exc: BaseException) -> list[str]:
    """오류 추적이 걷는 규칙대로 — 원인, 원인이 없고 감추지 않았으면 맥락 — 사슬의 모든 문장."""
    texts: list[str] = []
    current: BaseException | None = exc
    while current is not None:
        texts.append(f"{type(current).__name__}: {current!s} {current!r}")
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return texts


async def test_check_violation_on_a_state_update_leaks_no_ciphertext(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin_id: uuid.UUID,
    probe: FakeProbe,
    notes: list[str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """상태만 바꾸는 UPDATE 라도 CHECK 를 어기면 드라이버 오류의 DETAIL 이 위반한 행 전체(암호문 앞부분 hex 포함)를 싣는다.
    끄기가 쓰는 사유 상수를 CHECK 밖 값으로 바꿔 실제 위반을 내고, 올라온 예외는 클래스 이름·SQLSTATE 만의 500 이고 사슬과
    로그에 암호문이 없음을 본다(유일 위반이 아니라 409 로 바꾸지 않는다 — 버그는 오류 추적에 남아야 한다)."""
    created = await _insert_row(db_session, state="active", state_reason=None)
    blob = created.secret_ciphertext
    monkeypatch.setattr(credentials, "ADMIN_DISABLED_REASON", "bogus")
    caplog.set_level(logging.DEBUG)

    with pytest.raises(CredentialStoreError) as caught:
        await db_client.post(f"{_BASE}/{created.id}/disable")

    assert str(caught.value) == "IntegrityError sqlstate=23514"
    texts = [*_chain_texts(caught.value), caplog.text]
    for marker in (blob[:31].hex(), "\\x" + blob[:31].hex()):
        assert not [text for text in texts if marker in text]


async def test_duplicate_account_race_is_409_without_ciphertext(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin_id: uuid.UUID,
    probe: FakeProbe,
    notes: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """같은 조직 두 행이 사전 검사를 지나 유일 인덱스에서 부딪혀도(동시 저장의 경쟁) 사유 없는 409 이고, 응답·예외 사슬에
    암호문과 조직 id 가 없다."""
    await _create(db_client)

    async def nothing_listed(*_: Any, **__: Any) -> bool:
        return False

    monkeypatch.setattr(admin_llm_credentials, "_organization_listed", nothing_listed)
    raised: list[BaseException] = []
    real = credential_write

    @asynccontextmanager
    async def recording(db: AsyncSession) -> AsyncIterator[None]:
        try:
            async with real(db):
                yield
        except BaseException as exc:
            raised.append(exc)
            raise

    monkeypatch.setattr(admin_llm_credentials, "credential_write", recording)

    resp = await db_client.post(_BASE, json={"provider": "anthropic", "label": "y", "apiKey": FAKE_OTHER_API_KEY})

    assert (resp.status_code, resp.json()["detail"]["rule"]) == (409, "conflict")
    assert _ORG not in resp.text
    (exc,) = raised
    texts = [*_chain_texts(exc), resp.text]
    assert not [text for text in texts if _ORG in text or "\\x" in text or FAKE_OTHER_API_KEY in text]


async def test_logs_carry_no_secret_material(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin_id: uuid.UUID,
    notes: list[str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SDK·전송 계층·앱 로거를 DEBUG 로 열고 추가·교체·확인을 실제 SDK 로 돌려도 로그에 키 원문과 env 키 지문이 없다."""
    _sdk_backed(monkeypatch)
    for name in ("anthropic", "httpx", "httpx2", "api"):
        caplog.set_level(logging.DEBUG, logger=name)

    created = await _create(db_client)
    await db_client.put(f"{_BASE}/{created['id']}/secret", json={"apiKey": FAKE_OTHER_API_KEY})
    await _check(db_client, created["id"])

    for marker in (FAKE_API_KEY, FAKE_OTHER_API_KEY, _ENV_KEY, secret_fingerprint(_ENV_KEY)):
        assert marker not in caplog.text


# ── 런타임 캐시 무효화 ───────────────────────────────────────────────────────────────────
async def _generation() -> int:
    return int(await redis_client.get(GENERATION_KEY) or 0)


_Request = Callable[[], Awaitable[httpx.Response]]


async def _prepare_write(route: str, client: httpx.AsyncClient) -> _Request:
    """그 라우트가 실제로 무엇을 바꾸는 요청 하나를 준비한다(준비가 만든 변경은 세지 않는다)."""
    if route == "add":
        return lambda: client.post(_BASE, json={"provider": "anthropic", "label": "새 계정", "apiKey": FAKE_API_KEY})
    if route in ("pool", "disable"):
        ready = await _ready(client)
        if route == "pool":
            return lambda: client.put(f"{_BASE}/pool", json={"enabled": True})
        return lambda: client.post(f"{_BASE}/{ready['id']}/disable")
    created = await _create(client)
    path = f"{_BASE}/{created['id']}"
    if route == "order":
        revision = (await _listing(client))["listRevision"]
        return lambda: client.put(f"{_BASE}/order", json={"baseListRevision": revision, "ids": [created["id"]]})
    if route == "update":
        return lambda: client.patch(path, json={"label": "바꾼 이름"})
    if route == "secret":
        return lambda: client.put(f"{path}/secret", json={"apiKey": FAKE_OTHER_API_KEY})
    if route == "enable":
        await _check(client, created["id"])
        return lambda: client.post(f"{path}/enable")
    if route == "delete":
        return lambda: client.delete(path)
    assert route == "check"
    return lambda: client.post(f"{path}/check")


@pytest.mark.parametrize(
    "route", ["add", "order", "pool", "update", "secret", "enable", "disable", "delete", "check"]
)
async def test_every_admin_write_invalidates_the_snapshot(
    db_client: httpx.AsyncClient, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str], route: str
) -> None:
    """커밋된 변경마다 런타임 목록 캐시의 세대를 한 번 올린다 — 끈 항목·바꾼 순서가 다음 호출부터 바로 보인다."""
    request = await _prepare_write(route, db_client)
    before = await _generation()

    resp = await request()

    assert resp.status_code in (200, 201, 204), resp.text
    assert await _generation() == before + 1


async def test_admin_request_that_changes_nothing_leaves_the_snapshot_alone(
    db_client: httpx.AsyncClient, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """바뀐 것이 없는 요청(이미 켜진 항목 켜기·같은 라벨·이미 꺼진 목록 사용 끄기)은 무효화할 것도 없다."""
    ready = await _ready(db_client)
    before = await _generation()

    await db_client.post(f"{_BASE}/{ready['id']}/enable")
    await db_client.patch(f"{_BASE}/{ready['id']}", json={"label": ready["label"]})
    await db_client.put(f"{_BASE}/pool", json={"enabled": False})

    assert await _generation() == before


class _BrokenGenerationRedis:
    def __init__(self, hang: bool) -> None:
        self.hang = hang

    async def incr(self, *args: Any) -> int:
        if self.hang:
            await asyncio.sleep(5)
        raise RedisConnectionError("redis is down")


@pytest.mark.parametrize("hang", [pytest.param(False, id="error"), pytest.param(True, id="timeout")])
async def test_admin_write_survives_an_invalidation_failure(
    db_client: httpx.AsyncClient,
    admin_id: uuid.UUID,
    probe: FakeProbe,
    notes: list[str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    hang: bool,
) -> None:
    """변경은 이미 커밋됐다 — 무효화가 실패하거나 답하지 않아도 응답은 성공이고 알림도 간다. 옛 스냅숏은 캐시 수명 안에서 저절로
    맞춰진다."""
    monkeypatch.setattr(credential_pool, "redis_client", _BrokenGenerationRedis(hang))
    created = await _create(db_client)

    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="api.admin.llm_credentials"):
        resp = await db_client.patch(f"{_BASE}/{created['id']}", json={"label": "바꾼 이름"})

    assert resp.status_code == 200
    assert time.monotonic() - started < 2.0
    assert notes[-1].startswith("[Claude 자격] 수정 — ")
    assert any("캐시 무효화 실패" in record.getMessage() for record in caplog.records)


# ── 추정 사용액 ──────────────────────────────────────────────────────────────────────
async def test_check_calls_add_to_the_item_spend(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """확인 호출도 그 계정의 크레딧을 쓴다 — 받아들여진 호출마다 원가를 그 항목의 추정 사용액에 쌓는다(호출 경로 스위치와 무관).
    거절된 호출은 과금되지 않아 쌓지 않는다. 입력 12·출력 3: Opus 12×4 + 3×20 = 108, Haiku 5.5 12×0.1 + 3×0.5 = 2.7 → 3
    마이크로달러."""
    probe.default = CheckCallResult(error_kind=None, organization=_ORG, usage=to_usage(12, 0, 0, 3))
    probe.results[_IDS["sonnet"]] = CheckCallResult(error_kind="credit", organization=None)
    created = await _create(db_client, creditUsd=50)

    checked = await _check(db_client, created["id"])

    row = await _row(db_session, created["id"])
    assert await read_credential_spend([SpendTarget.of_row(row)]) == {
        row.id: CredentialSpend(spent_micro_usd=111, calls=2, unpriced_calls=0, unpriced_model=None)
    }
    assert checked["credential"]["spend"]["calls"] == 2


_SPEND_FIELDS = {"spentUsd", "remainingUsd", "belowAlert", "calls", "unpricedCalls", "unpricedModel"}


async def test_admin_list_shows_spend_remaining_and_unpriced_calls(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin_id: uuid.UUID,
    probe: FakeProbe,
    notes: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """충전액이 있는 항목은 그 기준 이후의 추정 사용액·남은 액·임계 아래 여부·호출 수·단가 없는 호출을 싣는다. 충전액이 없는
    항목은 비운다. Opus 입력 100만·출력 10만 = 4 + 2 = 6 달러, 남은 44 달러는 50 달러의 90% 임계 아래다(그래서 임계 알림이 한
    번 간다)."""
    threshold_alerts = _capture_credential_alerts(monkeypatch)
    created = await _create(db_client, creditUsd=50, alertPct=90)
    plain = await _insert_row(db_session)
    target = SpendTarget.of_row(await _row(db_session, created["id"]))
    await record_credential_spend(target, "claude-opus-5-5", to_usage(1_000_000, 0, 0, 100_000))
    await record_credential_spend(target, "claude-unknown-model-0", to_usage(10, 0, 0, 1))

    listing = await _listing(db_client)

    by_id = {item["id"]: item for item in listing["credentials"]}
    spend = by_id[created["id"]]["spend"]
    assert set(spend) == _SPEND_FIELDS
    assert spend == {
        "spentUsd": "6.00",
        "remainingUsd": "44.00",
        "belowAlert": True,
        "calls": 2,
        "unpricedCalls": 1,
        "unpricedModel": "claude-unknown-model-0",
    }
    assert by_id[str(plain.id)]["spend"] is None
    await _settle_credential_tasks()
    assert [alert.split(" — ")[0] for alert in threshold_alerts] == ["[Claude 자격] 추정 잔액이 임계 아래"]


async def test_admin_list_survives_an_unreadable_spend_store(
    db_client: httpx.AsyncClient, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """사용액을 읽지 못해도 조회는 뜨고 사용액 칸만 비운다."""
    created = await _create(db_client, creditUsd=50)

    class _Broken:
        def pipeline(self, transaction: bool = True) -> Any:
            raise RedisConnectionError("redis is down")

    monkeypatch.setattr(credential_usage, "redis_client", _Broken())
    listing = await _listing(db_client)

    assert [item["spend"] for item in listing["credentials"] if item["id"] == created["id"]] == [None]


# ── 사용액 기준 다시 잡기 ──────────────────────────────────────────────────────────────
_PAST = datetime(2026, 1, 1, tzinfo=UTC)


async def _with_past_basis(db_session: AsyncSession, credential_id: str) -> None:
    """기준 시각을 고정 과거 값으로 — 시계에 기대지 않고 "다시 잡혔다"를 그 값과의 차이로 본다."""
    await db_session.execute(
        sa.update(LlmCredential)
        .where(LlmCredential.id == uuid.UUID(credential_id))
        .values(credit_since=_PAST)
        .execution_options(synchronize_session=False)
    )


async def _update_audits(db_session: AsyncSession) -> list[str]:
    return [log.reason_text for log in await _audits(db_session) if log.action_type == "llm-credential-update"]


async def test_same_credit_sent_with_a_label_change_keeps_the_credit_basis(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """화면이 충전액 칸을 늘 실어 보내도 값이 같고 플래그가 없으면 기준은 그대로다 — 라벨만 고쳤는데 사용액이 지워지면 안 된다.
    라벨까지 같으면 바뀐 것이 없어 감사·알림·무효화가 없다."""
    created = await _create(db_client, creditUsd=50)
    await _with_past_basis(db_session, created["id"])
    subject = f"anthropic · 새 이름 · 지문 {secret_fingerprint(FAKE_API_KEY)}"
    notes.clear()
    before = await _generation()

    renamed = await db_client.patch(f"{_BASE}/{created['id']}", json={"label": "새 이름", "creditUsd": "50.00"})
    assert renamed.status_code == 200
    assert (await _row(db_session, created["id"])).credit_since == _PAST
    assert notes == [f"[Claude 자격] 수정 — {subject} · 라벨 운영 계정 → 새 이름"]
    assert await _update_audits(db_session) == [f"{subject} · 라벨 운영 계정 → 새 이름"]
    assert await _generation() == before + 1

    again = await db_client.patch(f"{_BASE}/{created['id']}", json={"label": "새 이름", "creditUsd": "50.00"})
    assert again.status_code == 200
    assert (await _row(db_session, created["id"])).credit_since == _PAST
    assert len(notes) == 1 and len(await _update_audits(db_session)) == 1
    assert await _generation() == before + 1


async def test_reset_flag_restarts_the_basis_with_the_same_credit(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin_id: uuid.UUID,
    probe: FakeProbe,
    notes: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """콘솔 잔액이 우연히 이전 충전액과 같아도 플래그로 기준을 지금으로 다시 잡는다 — 사용액이 새 기준에서 0 부터 세고, 옛 기준에서
    이미 보낸 잔액 임계 알림이 다시 무장된다. Opus 입력 100만·출력 10만 = 6 달러라 50 달러의 90% 임계 아래로 내려간다."""
    threshold_alerts = _capture_credential_alerts(monkeypatch)
    created = await _create(db_client, creditUsd=50, alertPct=90)
    await _with_past_basis(db_session, created["id"])
    old_target = SpendTarget.of_row(await _row(db_session, created["id"]))
    await record_credential_spend(old_target, "claude-haiku-5-5", to_usage(1000, 0, 0, 200))
    await record_credential_spend(old_target, "claude-opus-5-5", to_usage(1_000_000, 0, 0, 100_000))
    await _settle_credential_tasks()
    assert len(threshold_alerts) == 1
    subject = f"anthropic · 운영 계정 · 지문 {secret_fingerprint(FAKE_API_KEY)}"
    notes.clear()
    before = await _generation()

    resp = await db_client.patch(f"{_BASE}/{created['id']}", json={"creditUsd": "50.00", "resetCreditBasis": True})

    assert resp.status_code == 200, resp.text
    row = await _row(db_session, created["id"])
    assert row.credit_micro_usd == 50_000_000 and row.credit_since is not None and row.credit_since != _PAST
    assert notes == [f"[Claude 자격] 수정 — {subject} · 사용액 기준 다시 잡음(충전액 50.00 달러)"]
    assert await _update_audits(db_session) == [f"{subject} · 사용액 기준 다시 잡음(충전액 50.00 달러)"]
    assert await _generation() == before + 1
    assert (resp.json()["spend"]["calls"], resp.json()["spend"]["spentUsd"]) == (0, "0.00")
    assert await read_credential_spend([old_target]) == {
        row.id: CredentialSpend(spent_micro_usd=6_000_200, calls=2, unpriced_calls=0, unpriced_model=None)
    }

    await record_credential_spend(SpendTarget.of_row(row), "claude-opus-5-5", to_usage(1_000_000, 0, 0, 100_000))
    await _settle_credential_tasks()
    assert len(threshold_alerts) == 2


@pytest.mark.parametrize(
    "cleared", [pytest.param(False, id="without-a-credit"), pytest.param(True, id="credit-cleared-in-the-same-request")]
)
async def test_reset_flag_without_a_credit_is_refused(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    admin_id: uuid.UUID,
    probe: FakeProbe,
    notes: list[str],
    cleared: bool,
) -> None:
    """다시 잡을 충전액이 없으면 효과 없는 명시 요청을 조용히 성공시키지 않고 409 다 — 같은 요청의 다른 칸도 반영되지 않는다."""
    created = await (_create(db_client, creditUsd=50) if cleared else _create(db_client))
    row = await _row(db_session, created["id"])
    kept = (row.label, row.credit_micro_usd, row.credit_since)
    notes.clear()
    before = await _generation()
    body: dict[str, Any] = {"label": "바뀌면 안 되는 이름", "resetCreditBasis": True}
    if cleared:
        body["creditUsd"] = None

    resp = await db_client.patch(f"{_BASE}/{created['id']}", json=body)

    assert resp.status_code == 409
    assert resp.json()["detail"] == {"rule": "credit-basis-missing", "message": "충전액이 없어 기준을 다시 잡을 수 없습니다."}
    row = await _row(db_session, created["id"])
    assert (row.label, row.credit_micro_usd, row.credit_since) == kept
    assert notes == [] and await _update_audits(db_session) == []
    assert await _generation() == before


async def test_reset_flag_with_a_changed_credit_records_one_change(
    db_client: httpx.AsyncClient, db_session: AsyncSession, admin_id: uuid.UUID, probe: FakeProbe, notes: list[str]
) -> None:
    """값도 바뀌었으면 기준은 어차피 다시 잡히므로 변경 줄은 충전액 하나로 충분하다."""
    created = await _create(db_client, creditUsd=50)
    await _with_past_basis(db_session, created["id"])
    subject = f"anthropic · 운영 계정 · 지문 {secret_fingerprint(FAKE_API_KEY)}"
    notes.clear()

    resp = await db_client.patch(f"{_BASE}/{created['id']}", json={"creditUsd": "80.00", "resetCreditBasis": True})

    assert resp.status_code == 200
    assert (await _row(db_session, created["id"])).credit_since != _PAST
    assert notes == [f"[Claude 자격] 수정 — {subject} · 충전액 50.00 → 80.00 달러"]
    assert await _update_audits(db_session) == [f"{subject} · 충전액 50.00 → 80.00 달러"]
