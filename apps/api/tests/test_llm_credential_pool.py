"""Claude 자격 목록의 런타임 읽기 — 후보 판정(순수 함수), Redis 스냅숏 캐시와 세대 번호, Redis 장애 때 DB 직접 읽기, 목록 사용
판정, 프로세스 안 복호화와 SDK 클라이언트 캐시 키.

후보 판정은 DB 없이 행 객체를 생성자로만 채워 본다. 캐시 테스트는 풀의 세션을 테스트 커넥션 위의 SAVEPOINT 로 열어 셋업과 같은
트랜잭션을 보게 하고, Redis 는 테스트 Redis 를 그대로 쓴다(키는 `conftest.py` 가 매 테스트 전에 지운다). Redis 장애는 가짜 클라이언트를
풀에 넘겨 낸다."""

import asyncio
import base64
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest
import sqlalchemy as sa
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core import redis as core_redis
from api.core.config import settings
from api.core.field_crypto import FieldKeyring
from api.core.redis import redis_client
from api.db import session as db_session_module
from api.db.models.llm_credential import ClaudeModelAxis, LlmCredential, LlmCredentialCheck
from api.llm.chat_models import backend_model_id
from api.llm.client import LLMClientError
from api.llm.credential_accounts import AccountProvider
from api.llm.credential_pool import (
    GENERATION_KEY,
    SNAPSHOT_KEY,
    CredentialPool,
    PoolCredential,
    invalidate_pool_snapshot,
    load_pool_snapshot,
    pool_candidates,
    to_pool_credential,
)
from api.llm.credentials import CLAUDE_AXES, RejectionKind, new_credential, passed_axes, replace_secret
from factories import (
    FAKE_ANTHROPIC_ORG,
    FAKE_API_KEY,
    FAKE_CREDENTIAL_KEYRING,
    FAKE_OTHER_API_KEY,
    _add_llm_credential,
    _add_llm_credential_check,
    _cancel_credential_tasks,
    _capture_credential_alerts,
    _set_llm_credential_pool,
    _settle_credential_tasks,
)

_ORG = FAKE_ANTHROPIC_ORG
_OTHER_ORG = "org-test-0002"
_THIRD_ORG = "org-test-0003"
_OUTSIDE_ORG = "org-outside-0009"
_AWS = "123456789012"
_ALLOWED: frozenset[tuple[AccountProvider, str]] = frozenset(
    {("anthropic", _ORG), ("anthropic", _OTHER_ORG), ("anthropic", _THIRD_ORG), ("aws", _AWS)}
)


@pytest.fixture(autouse=True)
def store_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_credential_encryption_keys", FAKE_CREDENTIAL_KEYRING)
    monkeypatch.setattr(
        settings,
        "llm_credential_allowed_accounts",
        f"anthropic:{_ORG},anthropic:{_OTHER_ORG},anthropic:{_THIRD_ORG},aws:{_AWS}",
    )


# ── 후보 판정 (순수 함수) ─────────────────────────────────────────────────────────────
def _row(*, secret: str = FAKE_API_KEY, account_ref: str | None = _ORG, position: int = 1, **row: Any) -> LlmCredential:
    """세션 없이 채운 켜진 Anthropic 항목."""
    credential = new_credential(
        FieldKeyring.parse(FAKE_CREDENTIAL_KEYRING),
        provider="anthropic",
        label=f"계정 {position}",
        secret=secret,
        account_ref=account_ref,
        position=position,
        credit_micro_usd=None,
        alert_pct=20,
    )
    credential.state, credential.state_reason = "active", None
    for name, value in row.items():
        setattr(credential, name, value)
    return credential


def _checks(
    credential: LlmCredential,
    run: int,
    axes: tuple[ClaudeModelAxis, ...] = CLAUDE_AXES,
    *,
    fingerprint: str | None = None,
    error_kind: Any = None,
    state_version: int | None = None,
    sent_model_id: str | None = None,
    header: str | None = _ORG,
) -> list[LlmCredentialCheck]:
    """축마다 한 행. 보낸 id 는 따로 주지 않으면 지금 설정의 그 축 id 다. 통과 행에는 응답 조직 헤더(`header`, 기본은 상수
    `_ORG`)를 싣는다 — 헤더 없는 통과는 조직을 대조하지 않은 통과다."""
    return [
        LlmCredentialCheck(
            credential_id=credential.id,
            run=run,
            state_version=credential.state_version if state_version is None else state_version,
            model_axis=axis,
            sent_model_id=sent_model_id or backend_model_id("anthropic", axis),
            secret_fingerprint=fingerprint or credential.secret_fingerprint,
            passed=error_kind is None,
            error_kind=error_kind,
            organization_header=header if error_kind is None else None,
        )
        for axis in axes
    ]


def _candidate_axes(
    credential: LlmCredential,
    checks: list[LlmCredentialCheck],
    allowed: frozenset[tuple[AccountProvider, str]] = _ALLOWED,
) -> list[ClaudeModelAxis]:
    """행과 그 확인 기록을 스냅숏 항목으로 옮긴 뒤, 그 항목이 후보가 되는 축(축 순서)."""
    item = to_pool_credential(credential, checks)
    return [axis for axis in CLAUDE_AXES if pool_candidates([item], axis, allowed)]


def test_candidates_follow_position_and_skip_items_that_are_not_active() -> None:
    rows = [
        _row(position=3, account_ref=_THIRD_ORG, secret=FAKE_API_KEY + "c"),
        _row(position=1, account_ref=_ORG, secret=FAKE_API_KEY + "a"),
        _row(position=2, account_ref=_OTHER_ORG, secret=FAKE_API_KEY + "b", state="exhausted", state_reason="credit"),
        _row(position=4, account_ref=None, secret=FAKE_API_KEY + "d", state="disabled", state_reason="admin"),
    ]
    items = [to_pool_credential(row, _checks(row, 1)) for row in rows]

    candidates = pool_candidates(items, "opus", _ALLOWED)

    assert [item.position for item in candidates] == [1, 3]


def test_item_without_a_passing_check_on_that_axis_is_not_a_candidate() -> None:
    credential = _row()

    assert _candidate_axes(credential, _checks(credential, 1, ("sonnet", "haiku"))) == ["sonnet", "haiku"]
    assert _candidate_axes(credential, []) == []


def test_item_whose_latest_check_on_the_axis_failed_is_not_a_candidate() -> None:
    """옛 회차의 통과가 남아 있어도 그 축의 최신 회차가 실패면 그 축의 후보가 아니다 — 다른 축은 그대로다."""
    credential = _row()
    checks = _checks(credential, 1) + _checks(credential, 2, ("opus",), error_kind="credit")

    assert _candidate_axes(credential, checks) == ["sonnet", "haiku_writer", "haiku"]


def test_item_checked_with_a_previous_secret_is_not_a_candidate() -> None:
    """키를 바꾸면 옛 키로 한 통과는 지금 키의 확인이 아니다."""
    credential = _row()
    old = _checks(credential, 1, fingerprint="0badc0de")

    assert _candidate_axes(credential, old) == []
    assert _candidate_axes(credential, old + _checks(credential, 2, ("haiku",))) == ["haiku"]


@pytest.mark.parametrize(
    "case",
    [
        pytest.param("unverified", id="organization-unverified"),
        pytest.param("outside", id="organization-outside-the-allowlist"),
        pytest.param("mismatch-latest", id="organization-error-in-the-latest-run-of-this-key"),
        pytest.param("mismatch-old-key", id="organization-error-only-under-a-previous-key"),
    ],
)
def test_item_with_an_unverified_disallowed_or_mismatched_organization_is_not_a_candidate(case: str) -> None:
    """조직이 확인되지 않았거나 지금 허용 목록 밖이면 어느 축의 후보도 아니다. 지금 키의 가장 최근 회차에 조직이 어긋난 축이
    하나라도 있으면 다른 축이 통과했어도 항목 전체가 빠진다(켜진 뒤의 확인에서 나온 보안 신호). 대조군: 조직 오류가 옛 키의
    회차에만 있으면 지금 키의 통과로 후보다."""
    credential = _row(account_ref=None if case == "unverified" else _ORG)
    checks = _checks(credential, 1)
    allowed = _ALLOWED
    if case == "outside":
        allowed = frozenset({("anthropic", _OUTSIDE_ORG)})
    if case == "mismatch-latest":
        checks = [
            *_checks(credential, 1),
            *_checks(credential, 2, ("opus", "sonnet", "haiku_writer")),
            *_checks(credential, 2, ("haiku",), error_kind="organization-mismatch"),
        ]
    if case == "mismatch-old-key":
        checks = _checks(credential, 1, fingerprint="0badc0de", error_kind="organization-mismatch") + _checks(
            credential, 2
        )

    expected = list(CLAUDE_AXES) if case == "mismatch-old-key" else []
    assert _candidate_axes(credential, checks, allowed) == expected


def test_passed_axes_is_empty_when_the_latest_run_of_this_key_carries_an_account_not_allowed() -> None:
    credential = _row()
    checks = _checks(credential, 1) + _checks(credential, 2, ("sonnet",), error_kind="account-not-allowed")

    assert passed_axes(credential, checks) == frozenset()


@pytest.mark.parametrize(
    ("later", "expected"),
    [
        pytest.param("unavailable", list(CLAUDE_AXES), id="transient-error-keeps-the-earlier-pass"),
        pytest.param("model-not-found", [], id="missing-model-overrides-the-earlier-pass"),
        pytest.param("credit", [], id="credit-overrides-the-earlier-pass"),
        pytest.param("permission", [], id="permission-overrides-the-earlier-pass"),
    ],
)
def test_only_a_conclusive_failure_overrides_an_earlier_pass(later: str, expected: list[str]) -> None:
    """켜진 항목을 확인하다 Anthropic 이 잠깐 429·과부하·시간 초과를 내면 그 회차는 축마다 일시 오류로 남는다. 일시 오류는
    그 축에 대해 아무것도 결론 내지 않았으므로 이전 통과가 그대로 후보를 만든다 — 그렇지 않으면 확인 한 번에 항목이 후보에서
    빠지고, 다음 항목이 없으면 모든 Claude 호출이 실패한다. 크레딧·모델 없음·권한 같은 확정 실패는 이전 통과를 덮는다."""
    credential = _row()
    checks = _checks(credential, 1) + _checks(credential, 2, error_kind=later)

    assert _candidate_axes(credential, checks) == expected


def test_transient_errors_are_skipped_per_axis_down_to_that_axis_last_conclusion() -> None:
    """건너뛰기는 축마다다: 한 회차 안에서도 일시 오류 축은 그 전 결론으로 내려가고, 확정 결과가 난 축은 그 결과를 쓴다.
    일시 오류가 여러 번 이어져도 마지막 결론까지 내려간다."""
    credential = _row()
    checks = [
        *_checks(credential, 1),
        *_checks(credential, 2, ("opus", "haiku"), error_kind="unavailable"),
        *_checks(credential, 2, ("sonnet",), error_kind="credit"),
        *_checks(credential, 2, ("haiku_writer",)),
        *_checks(credential, 3, ("opus",), error_kind="unavailable"),
    ]

    assert _candidate_axes(credential, checks) == ["opus", "haiku_writer", "haiku"]


def test_item_whose_checks_never_reached_a_conclusion_is_not_a_candidate() -> None:
    """일시 오류 아래에 결론이 없으면(확인이 일시 오류뿐) 그 축은 받지 않는다. 일시 오류 아래의 결론이 실패여도 받지 않는다."""
    credential = _row()

    assert _candidate_axes(credential, _checks(credential, 1, error_kind="unavailable")) == []
    failed_then_transient = _checks(credential, 1, error_kind="credit") + _checks(credential, 2, error_kind="unavailable")
    assert _candidate_axes(credential, failed_then_transient) == []


def test_transient_check_under_a_new_key_does_not_fall_back_to_the_previous_key() -> None:
    """키를 바꾼 뒤 첫 확인이 일시 오류면 그 아래의 옛 키 통과로 내려가지 않는다 — 옛 키의 통과는 지금 키의 확인이 아니다.
    대조군: 지금 키로 통과한 뒤의 일시 오류는 그 통과로 내려간다."""
    credential = _row()
    old = _checks(credential, 1, fingerprint="0badc0de")
    transient = _checks(credential, 2, error_kind="unavailable")

    assert _candidate_axes(credential, old + transient) == []
    passed_then_transient = _checks(credential, 2) + _checks(credential, 3, error_kind="unavailable")
    assert _candidate_axes(credential, old + passed_then_transient) == list(CLAUDE_AXES)


@pytest.mark.parametrize(
    ("latest", "expected"),
    [
        pytest.param("transient", [], id="transient-only-run-keeps-the-organization-error"),
        pytest.param("other-axis-failure", [], id="failure-on-another-axis-keeps-the-organization-error"),
        pytest.param("same-axis-unrelated-failure", [], id="unrelated-failure-on-that-axis-keeps-the-organization-error"),
        pytest.param("same-axis-passes", list(CLAUDE_AXES), id="pass-on-that-axis-clears-the-organization-error"),
    ],
)
def test_organization_error_stays_until_that_axis_passes_again(latest: str, expected: list[str]) -> None:
    """지금 키의 확인에서 응답 조직이 어긋난 축은, 그 축이 다시 통과(응답 조직이 맞았다)하기 전까지 항목 전체를 뺀다. 그 뒤의
    일시 오류는 조직에 대해 아무 말도 하지 않았고, 모델 없음·크레딧 같은 조직과 무관한 확정 실패도 응답 조직을 확인하지 않은
    결과라 그 신호를 지우지 않는다 — 지우면 후보 판정이 어긋난 회차의 다른 축 통과로 내려가 그 키로 요청을 보내게 된다."""
    credential = _row()
    checks = [
        *_checks(credential, 1),
        *_checks(credential, 2, ("opus", "sonnet", "haiku_writer")),
        *_checks(credential, 2, ("haiku",), error_kind="organization-mismatch"),
    ]
    if latest == "transient":
        checks += _checks(credential, 3, error_kind="unavailable")
    elif latest == "other-axis-failure":
        checks += _checks(credential, 3, ("opus",), error_kind="credit")
        checks += _checks(credential, 3, ("sonnet", "haiku_writer", "haiku"), error_kind="unavailable")
    elif latest == "same-axis-unrelated-failure":
        checks += _checks(credential, 3, ("opus", "sonnet", "haiku_writer"), error_kind="unavailable")
        checks += _checks(credential, 3, ("haiku",), error_kind="model-not-found")
    else:
        checks += _checks(credential, 3, ("opus", "sonnet", "haiku_writer"), error_kind="unavailable")
        checks += _checks(credential, 3, ("haiku",))

    assert _candidate_axes(credential, checks) == expected


def test_organization_errors_on_several_axes_are_not_cleared_by_unrelated_failures_or_transient_errors() -> None:
    """회차 2 에서 sonnet 만 429 이고 나머지 축이 모두 조직 불일치, 회차 3 에서 그 축들이 404·크레딧이고 sonnet 은 또 429 면 항목
    전체가 빠진 채다 — 조직 불일치 축이 하나도 다시 통과하지 않았고, sonnet 의 회차 1 통과로 내려가면 조직이 어긋난 키로 요청을
    보내게 된다. 대조군: 어긋났던 축이 모두 다시 통과하면 풀린다."""
    credential = _row()
    mismatched: tuple[ClaudeModelAxis, ...] = ("opus", "haiku_writer", "haiku")
    checks = [
        *_checks(credential, 1),
        *_checks(credential, 2, ("sonnet",), error_kind="unavailable"),
        *_checks(credential, 2, mismatched, error_kind="organization-mismatch"),
        *_checks(credential, 3, ("opus",), error_kind="model-not-found"),
        *_checks(credential, 3, ("haiku_writer", "haiku"), error_kind="credit"),
        *_checks(credential, 3, ("sonnet",), error_kind="unavailable"),
    ]

    assert _candidate_axes(credential, checks) == []
    assert _candidate_axes(credential, [*checks, *_checks(credential, 4, mismatched)]) == list(CLAUDE_AXES)


def test_a_pass_without_an_organization_header_does_not_clear_an_organization_error() -> None:
    """회차 2 에서 Haiku 응답 조직이 어긋난 뒤 회차 3 에서 Haiku 가 헤더 없는 200 으로 통과해도 항목은 빠진 채다 — 헤더가 없으면
    응답 조직을 대조하지 않았다. 회차 4 에서 저장된 조직의 헤더가 실린 통과가 오면 풀린다."""
    credential = _row()
    checks = [
        *_checks(credential, 1),
        *_checks(credential, 2, ("opus", "sonnet", "haiku_writer")),
        *_checks(credential, 2, ("haiku",), error_kind="organization-mismatch"),
        *_checks(credential, 3, header=None),
    ]

    assert _candidate_axes(credential, checks) == []
    assert _candidate_axes(credential, [*checks, *_checks(credential, 4, ("haiku",))]) == list(CLAUDE_AXES)


def test_axis_check_still_counts_after_the_model_id_setting_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    """축 단위 확인이라 실제 id 설정을 바꿔도 그 축의 통과가 남는다(id 일치는 목록 사용 켜기에만 건다)."""
    monkeypatch.setattr(settings, "anthropic_opus_model_id", "claude-opus-9-9")
    credential = _row()

    assert _candidate_axes(credential, _checks(credential, 1, sent_model_id="claude-opus-5-5")) == list(CLAUDE_AXES)


def test_enabling_does_not_void_the_check_that_allowed_it() -> None:
    """켜기가 판을 올리므로 켜기를 허락한 확인은 판이 하나 아래다 — 그래도 그 축의 후보다."""
    credential = _row(state_version=4)

    assert _candidate_axes(credential, _checks(credential, 1, state_version=3)) == list(CLAUDE_AXES)


def test_bedrock_items_are_not_candidates() -> None:
    """공급자로 거른다 — 조직 칸이 허용 목록의 Anthropic 조직과 같은 값이어도 Bedrock 항목은 이 판의 후보가 아니다."""
    credential = _row(provider="bedrock", account_ref=_ORG, region="us-east-1")

    assert _candidate_axes(credential, _checks(credential, 1)) == []


# ── 스냅숏 캐시 ────────────────────────────────────────────────────────────────────
class _CountingFactory:
    """풀이 여는 짧은 세션을 테스트 커넥션 위 SAVEPOINT 로 열고, 연 횟수를 센다. `after_read` 는 다음 세션이 닫힌 뒤 한 번 돈다."""

    def __init__(self, db_session: AsyncSession) -> None:
        self._inner = async_sessionmaker(
            bind=db_session.bind, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        self.opened = 0
        self.after_read: Callable[[], Awaitable[None]] | None = None

    def __call__(self) -> Any:
        self.opened += 1
        return self._session()

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        async with self._inner() as session:
            yield session
        hook, self.after_read = self.after_read, None
        if hook is not None:
            await hook()


async def _ready_pool(db_session: AsyncSession) -> LlmCredential:
    await _set_llm_credential_pool(db_session, True)
    credential = await _add_llm_credential(db_session, "첫째 계정")
    await _add_llm_credential_check(db_session, credential)
    return credential


async def test_snapshot_cache_holds_no_secret_or_its_last_four(db_session: AsyncSession) -> None:
    """Redis 에 남는 스냅숏에는 키 원문도 끝 4자리도 없다 — Redis 의 디스크 기록에 원문이 남지 않게. 칸 집합을 정확히 본다(비밀이
    아닌 새 칸이라도 문자열 탐색으로는 잡히지 않는다)."""
    credential = await _ready_pool(db_session)

    await CredentialPool(session_factory=_CountingFactory(db_session), redis=redis_client).plan("opus")

    raw = await redis_client.get(SNAPSHOT_KEY)
    assert raw is not None and FAKE_API_KEY not in raw
    (item,) = json.loads(raw)["credentials"]
    assert set(item) == {
        "id",
        "provider",
        "label",
        "position",
        "state",
        "state_version",
        "secret_fingerprint",
        "key_id",
        "ciphertext",
        "account_ref",
        "passed_axes",
        "credit_micro_usd",
        "credit_since",
        "alert_pct",
    }
    assert base64.b64decode(item["ciphertext"]) == credential.secret_ciphertext
    assert not [value for name, value in item.items() if name != "ciphertext" and FAKE_API_KEY[-4:] in str(value)]


async def test_snapshot_is_served_from_cache_until_the_generation_moves(db_session: AsyncSession) -> None:
    await _ready_pool(db_session)
    factory = _CountingFactory(db_session)

    first = await load_pool_snapshot(factory, redis_client)
    second = await load_pool_snapshot(factory, redis_client)
    assert factory.opened == 1
    assert second == first

    await invalidate_pool_snapshot()
    third = await load_pool_snapshot(factory, redis_client)

    assert factory.opened == 2
    assert first.generation is not None and third.generation == first.generation + 1


async def test_snapshot_built_before_an_invalidation_is_not_served_after_it(db_session: AsyncSession) -> None:
    """미스가 DB 를 읽은 뒤 그 값을 캐시에 쓰기 전에 다른 쪽의 변경·무효화가 지나가도, 그 낡은 값은 다음 읽기에서 버려진다 —
    세대를 DB 를 읽기 전에 읽어 스냅숏에 적기 때문이다."""
    credential = await _ready_pool(db_session)
    factory = _CountingFactory(db_session)

    async def change_and_invalidate() -> None:
        await db_session.execute(
            sa.update(LlmCredential)
            .where(LlmCredential.id == credential.id)
            .values(state="disabled", state_reason="admin", state_version=LlmCredential.state_version + 1)
            .execution_options(synchronize_session=False)
        )
        await invalidate_pool_snapshot()

    factory.after_read = change_and_invalidate
    stale = await load_pool_snapshot(factory, redis_client)
    fresh = await load_pool_snapshot(factory, redis_client)

    assert [item.state for item in stale.credentials] == ["active"]
    assert [item.state for item in fresh.credentials] == ["disabled"]
    assert factory.opened == 2


class _BrokenRedis:
    """조회가 실패하거나(`hang=False`) 답하지 않는다(`hang=True`). 쓰기는 센다."""

    def __init__(self, *, hang: bool) -> None:
        self.hang = hang
        self.writes = 0

    async def mget(self, *keys: str) -> list[str | None]:
        if self.hang:
            await asyncio.sleep(5)
        raise RedisConnectionError("redis is down")

    async def set(self, *args: Any, **kwargs: Any) -> None:
        self.writes += 1


@pytest.mark.parametrize("hang", [pytest.param(False, id="error"), pytest.param(True, id="timeout")])
async def test_redis_failure_or_timeout_reads_the_database_directly(
    db_session: AsyncSession, hang: bool, caplog: pytest.LogCaptureFixture
) -> None:
    """Redis 가 실패하거나 상한 안에 답하지 않으면 목록 규칙대로 DB 를 바로 읽는다 — env 키 경로로 떨어지지 않는다. 세대 없이
    읽은 값은 캐시에 쓰지 않는다."""
    credential = await _ready_pool(db_session)
    broken = _BrokenRedis(hang=hang)
    pool = CredentialPool(session_factory=_CountingFactory(db_session), redis=cast(Redis, broken))

    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="api.llm.credential_pool"):
        plan = await pool.plan("opus")

    assert time.monotonic() - started < 1.0
    assert plan is not None and [item.id for item in plan.candidates] == [credential.id]
    assert broken.writes == 0
    assert any("DB 를 바로 읽는다" in record.getMessage() for record in caplog.records)


async def test_pool_switched_off_in_admin_or_without_rows_yields_no_plan(db_session: AsyncSession) -> None:
    """목록 사용이 꺼져 있거나 목록에 행이 없으면 계획이 없다(부르는 쪽은 env 키 경로로 간다)."""
    pool = CredentialPool(session_factory=_CountingFactory(db_session), redis=redis_client)
    await _set_llm_credential_pool(db_session, True)
    assert await pool.plan("opus") is None

    credential = await _add_llm_credential(db_session, "첫째 계정")
    await _add_llm_credential_check(db_session, credential)
    await _set_llm_credential_pool(db_session, False)
    await invalidate_pool_snapshot()

    assert await pool.plan("opus") is None


async def test_pool_with_only_bedrock_rows_plans_no_candidate_instead_of_none(db_session: AsyncSession) -> None:
    """행이 하나라도 있으면(공급자·상태 무관) 목록 경로다 — Bedrock 행만 있으면 후보 0 인 계획이지 "계획 없음"이 아니다."""
    await _set_llm_credential_pool(db_session, True)
    bedrock = await _add_llm_credential(
        db_session, "Bedrock 계정", account_ref=_AWS, provider="bedrock", region="us-east-1"
    )
    await _add_llm_credential_check(db_session, bedrock)

    plan = await CredentialPool(session_factory=_CountingFactory(db_session), redis=redis_client).plan("opus")

    assert plan is not None and plan.candidates == []


async def test_unreadable_store_is_an_llm_client_error_with_a_cause() -> None:
    """Redis 와 DB 둘 다 읽지 못하면 원인을 단 보통의 호출 실패다(채팅·소설은 환불 경로를 탄다)."""

    def broken_factory() -> Any:
        raise ConnectionRefusedError("database is down")

    pool = CredentialPool(session_factory=broken_factory, redis=cast(Redis, _BrokenRedis(hang=False)))

    with pytest.raises(LLMClientError) as caught:
        await pool.plan("opus")

    assert type(caught.value) is LLMClientError
    assert isinstance(caught.value.__cause__, ConnectionRefusedError)
    assert caught.value.provider == "anthropic"


def test_default_pool_reads_the_shared_session_factory_and_redis() -> None:
    """기본 풀은 api 와 같은 세션 팩토리·Redis 를 쓴다 — 소설화 워커도 같은 모듈 전역이라 같은 스냅숏·세대를 본다."""
    pool = CredentialPool()

    assert pool.session_factory is db_session_module.async_session_factory
    assert pool.redis is core_redis.redis_client


# ── 복호화·SDK 클라이언트 캐시 키 ─────────────────────────────────────────────────────────
async def test_secret_of_returns_the_stored_key(db_session: AsyncSession) -> None:
    await _ready_pool(db_session)
    pool = CredentialPool(session_factory=_CountingFactory(db_session), redis=redis_client)

    plan = await pool.plan("opus")

    assert plan is not None
    assert pool.secret_of(plan.candidates[0]) == FAKE_API_KEY


async def test_unreadable_secret_is_skipped_without_raising_and_warned_once(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """키링에 그 행의 키가 없으면 그 항목의 키는 None 이다 — 예외는 밖으로 나가지 않고, 같은 항목·키는 한 번만 경고한다."""
    await _ready_pool(db_session)
    pool = CredentialPool(session_factory=_CountingFactory(db_session), redis=redis_client)
    plan = await pool.plan("opus")
    assert plan is not None
    monkeypatch.setattr(
        settings, "llm_credential_encryption_keys", "k9:" + base64.urlsafe_b64encode(b"\x09" * 32).decode()
    )

    with caplog.at_level(logging.WARNING, logger="api.llm.credential_pool"):
        first = pool.secret_of(plan.candidates[0])
        second = pool.secret_of(plan.candidates[0])

    assert (first, second) == (None, None)
    warnings = [record for record in caplog.records if record.name == "api.llm.credential_pool"]
    assert len(warnings) == 1
    assert FAKE_API_KEY not in warnings[0].getMessage()


async def test_replacing_the_secret_changes_the_client_key_and_drops_the_old_one(db_session: AsyncSession) -> None:
    """프로세스 안 SDK 클라이언트는 (항목 id, 지문)으로 묶는다 — 키를 바꾸면 새 클라이언트가 필요하고, 옛 키의 클라이언트는 다음
    계획의 살아 있는 키 집합에서 빠져 버려진다."""
    credential = await _ready_pool(db_session)
    pool = CredentialPool(session_factory=_CountingFactory(db_session), redis=redis_client)
    before = await pool.plan("opus")
    assert before is not None

    replace_secret(FieldKeyring.parse(FAKE_CREDENTIAL_KEYRING), credential, FAKE_OTHER_API_KEY)
    await db_session.flush()
    await _add_llm_credential_check(db_session, credential)
    await invalidate_pool_snapshot()
    after = await pool.plan("opus")
    assert after is not None

    old_key, new_key = before.candidates[0].client_key, after.candidates[0].client_key
    assert old_key != new_key
    assert before.live_keys == {old_key}
    assert after.live_keys == {new_key}
    assert pool.secret_of(after.candidates[0]) == FAKE_OTHER_API_KEY


# ── 소진 표시 ─────────────────────────────────────────────────────────────────────────
@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    return _capture_credential_alerts(monkeypatch)


@pytest.fixture
async def _settled_tasks() -> AsyncIterator[None]:
    """표시가 띄운 알림 태스크를 다음 테스트로 넘기지 않는다(이벤트 루프를 모든 테스트가 함께 쓴다)."""
    yield
    await _cancel_credential_tasks()


async def _planned(pool: CredentialPool) -> PoolCredential:
    plan = await pool.plan("opus")
    assert plan is not None
    (credential,) = plan.candidates
    return credential


async def _state_of(db_session: AsyncSession, credential: LlmCredential) -> tuple[str, str | None, int, str]:
    row = (
        await db_session.execute(
            sa.select(
                LlmCredential.state,
                LlmCredential.state_reason,
                LlmCredential.state_version,
                LlmCredential.secret_fingerprint,
            ).where(LlmCredential.id == credential.id)
        )
    ).one()
    return row.state, row.state_reason, row.state_version, row.secret_fingerprint


async def _generation_now() -> int:
    return int(await redis_client.get(GENERATION_KEY) or 0)


@pytest.mark.usefixtures("_settled_tasks")
async def test_two_rejections_from_the_same_snapshot_mark_once_and_alert_once(
    db_session: AsyncSession, alerts: list[str]
) -> None:
    """같은 스냅숏으로 거절이 두 번 와도 상태는 한 번만 바뀐다 — 둘째는 0행이라 세대도 알림도 한 번이다."""
    credential = await _ready_pool(db_session)
    pool = CredentialPool(session_factory=_CountingFactory(db_session), redis=redis_client)
    item = await _planned(pool)
    before = await _generation_now()

    await pool.mark_exhausted(item, "credit")
    await pool.mark_exhausted(item, "credit")
    await _settle_credential_tasks()

    assert await _state_of(db_session, credential) == (
        "exhausted",
        "credit",
        credential.state_version + 1,
        credential.secret_fingerprint,
    )
    assert await _generation_now() == before + 1
    assert len(alerts) == 1


@pytest.mark.usefixtures("_settled_tasks")
async def test_late_rejection_through_a_replaced_key_does_not_exhaust_the_new_key(
    db_session: AsyncSession, alerts: list[str]
) -> None:
    """키를 바꾼 뒤 옛 키로 보낸 요청의 거절은 새 키를 소진시키지 않는다(키 교체는 상태 판을 올리지 않아 지문만이 가른다)."""
    credential = await _ready_pool(db_session)
    pool = CredentialPool(session_factory=_CountingFactory(db_session), redis=redis_client)
    old = await _planned(pool)
    replace_secret(FieldKeyring.parse(FAKE_CREDENTIAL_KEYRING), credential, FAKE_OTHER_API_KEY)
    await db_session.flush()
    before = await _generation_now()

    await pool.mark_exhausted(old, "auth")
    await _settle_credential_tasks()

    assert await _state_of(db_session, credential) == (
        "active",
        None,
        old.state_version,
        credential.secret_fingerprint,
    )
    assert await _generation_now() == before
    assert alerts == []


@pytest.mark.usefixtures("_settled_tasks")
async def test_late_rejection_from_before_a_reenable_does_not_exhaust_the_new_state(
    db_session: AsyncSession, alerts: list[str]
) -> None:
    """끄고 다시 켠 뒤(판 +2) 그 전 스냅숏으로 보낸 요청의 거절은 다시 켠 상태를 소진시키지 않는다."""
    credential = await _ready_pool(db_session)
    pool = CredentialPool(session_factory=_CountingFactory(db_session), redis=redis_client)
    old = await _planned(pool)
    await db_session.execute(
        sa.update(LlmCredential)
        .where(LlmCredential.id == credential.id)
        .values(state_version=LlmCredential.state_version + 2)
        .execution_options(synchronize_session=False)
    )

    await pool.mark_exhausted(old, "credit")
    await _settle_credential_tasks()

    assert await _state_of(db_session, credential) == (
        "active",
        None,
        old.state_version + 2,
        old.secret_fingerprint,
    )
    assert alerts == []


@pytest.mark.parametrize(
    ("kind", "reason", "action"),
    [
        pytest.param("credit", "크레딧 부족", "충전한 뒤 확인 호출 → 켜기", id="credit"),
        pytest.param("auth", "키 무효 또는 조직 비활성", "키를 교체하거나 지운다", id="auth"),
        pytest.param(
            "limit",
            "사용 한도 도달",
            "한도가 풀린 뒤(월 상한은 다음 달 1일 00:00 UTC) 확인 호출 → 켜기",
            id="limit",
        ),
    ],
)
@pytest.mark.parametrize("env_key", [pytest.param(False, id="other-key"), pytest.param(True, id="env-rollback-key")])
@pytest.mark.usefixtures("_settled_tasks")
async def test_exhaustion_alert_names_label_fingerprint_reason_and_env_key_overlap_only(
    db_session: AsyncSession,
    alerts: list[str],
    monkeypatch: pytest.MonkeyPatch,
    kind: RejectionKind,
    reason: str,
    action: str,
    env_key: bool,
) -> None:
    """소진 알림은 공급자·라벨·지문·사유와 대응만 싣는다 — 키·끝 4자리·조직 id 는 없다. 그 키가 env 롤백 키와 같으면 목록 사용을
    꺼도 같은 거절을 받는다고 덧붙인다."""
    monkeypatch.setattr(settings, "anthropic_direct_api_key", FAKE_API_KEY if env_key else FAKE_OTHER_API_KEY)
    credential = await _ready_pool(db_session)
    pool = CredentialPool(session_factory=_CountingFactory(db_session), redis=redis_client)

    await pool.mark_exhausted(await _planned(pool), kind)
    await _settle_credential_tasks()

    expected = (
        f"[Claude 자격] 소진 — anthropic · 첫째 계정 · 지문 {credential.secret_fingerprint} · {reason} · 이 항목을 "
        f"건너뛴다\n{action}"
    )
    if env_key:
        expected += "\nenv 롤백 키와 같은 키다 — 목록 사용을 끄면 env 경로도 같은 거절을 받는다"
    assert alerts == [expected]
    for secret in (FAKE_API_KEY, FAKE_API_KEY[-4:], _ORG):
        assert secret not in alerts[0]


@pytest.mark.usefixtures("_settled_tasks")
async def test_other_process_skips_the_exhausted_item_on_its_next_call(
    db_session: AsyncSession, alerts: list[str]
) -> None:
    """한 프로세스가 표시하면 같은 Redis·DB 를 보는 다른 프로세스도 다음 호출에서 그 항목을 건너뛴다 — 표시가 세대를 올려 그쪽이
    캐시한 스냅숏을 버리게 한다."""
    await _ready_pool(db_session)
    marking = CredentialPool(session_factory=_CountingFactory(db_session), redis=redis_client)
    other = CredentialPool(session_factory=_CountingFactory(db_session), redis=redis_client)
    await _planned(other)

    await marking.mark_exhausted(await _planned(marking), "credit")
    plan = await other.plan("opus")

    assert plan is not None and plan.candidates == []
