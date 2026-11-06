"""Claude 자격 목록의 순수 함수 — 비밀 암호화(연관 데이터·키링 회전·교체·재암호화), 지문, 거절 분류.

암호화 테스트는 DB 를 타지 않는다 — 행 id 를 코드가 정하므로 모델 객체만으로 연관 데이터의 묶임을 볼 수 있다."""

import hashlib
import uuid
from datetime import UTC, datetime
from typing import get_args

import anthropic
import httpx2
import pytest

from api.core.config import settings
from api.core.field_crypto import FieldDecryptError, FieldKeyring
from api.db.models.llm_credential import CheckErrorKind, ClaudeModelAxis, LlmCredential, LlmCredentialCheck
from api.llm.backends import BACKENDS
from api.llm.credential_accounts import AccountProvider
from api.llm.credentials import (
    CLAUDE_AXES,
    CheckGroup,
    check_groups,
    classify_anthropic_rejection,
    credential_keyring,
    current_model_ids,
    decrypt_secret,
    enable_blocker,
    latest_checks_per_axis,
    new_credential,
    probe_failure_kind,
    reencrypt_secret,
    replace_secret,
    same_as_env_key,
    secret_fingerprint,
    secret_last4,
    uncovered_axes,
)
from factories import FAKE_API_KEY, FAKE_CREDENTIAL_KEYRING, FAKE_OTHER_API_KEY, FAKE_ROTATED_KEYRING

# 회전 중 키링의 새 키(k2)만 — 옛 키 없이도 다시 암호화한 값이 읽히는지 본다.
_ROTATED_KEY = FAKE_ROTATED_KEYRING.split(",", 1)[0]


def _credential(keyring: FieldKeyring, secret: str = FAKE_API_KEY) -> LlmCredential:
    return new_credential(
        keyring,
        provider="anthropic",
        label="운영 계정",
        secret=secret,
        account_ref="org-test-0001",
        position=1,
        credit_micro_usd=None,
        alert_pct=20,
    )


# ── 암호화 ───────────────────────────────────────────────────────────────────
def test_secret_round_trips_through_the_keyring() -> None:
    """저장한 키를 그대로 되읽는다. 암호문에 원문이 없고, 새 항목은 꺼진 채(운영자가 끔) 시작한다."""
    keyring = FieldKeyring.parse(FAKE_CREDENTIAL_KEYRING)

    credential = _credential(keyring)

    assert decrypt_secret(keyring, credential) == FAKE_API_KEY
    assert FAKE_API_KEY.encode() not in credential.secret_ciphertext
    assert (credential.key_id, credential.secret_last4) == ("k1", FAKE_API_KEY[-4:])
    assert (credential.state, credential.state_reason) == ("disabled", "admin")


def test_ciphertext_moved_to_another_row_fails_to_decrypt() -> None:
    """연관 데이터에 행 id 가 들어간다 — 한 항목의 암호문을 다른 항목 행에 옮겨 붙이면 그 항목의 키로 읽히지 않고 실패한다."""
    keyring = FieldKeyring.parse(FAKE_CREDENTIAL_KEYRING)
    mine = _credential(keyring)
    other = _credential(keyring, FAKE_OTHER_API_KEY)

    other.key_id, other.secret_ciphertext = mine.key_id, mine.secret_ciphertext

    assert other.id != mine.id
    with pytest.raises(FieldDecryptError):
        decrypt_secret(keyring, other)


def test_ciphertext_under_another_column_name_fails_to_decrypt() -> None:
    """연관 데이터는 표 접두 + 행 id + 칸 이름이다. 같은 행의 다른 칸 이름으로 만든 암호문은 읽히지 않고, 칸 이름이
    `secret` 인 것만 읽힌다 — 이 형식이 바뀌면 이미 저장한 행을 모두 읽지 못하게 되므로 형식 자체를 고정한다."""
    keyring = FieldKeyring.parse(FAKE_CREDENTIAL_KEYRING)
    credential = _credential(keyring)
    prefix = b"llm_credential:" + credential.id.bytes + b":"

    _, other_column = keyring.encrypt(FAKE_API_KEY, aad=prefix + b"region")
    credential.secret_ciphertext = other_column
    with pytest.raises(FieldDecryptError):
        decrypt_secret(keyring, credential)

    _, same_column = keyring.encrypt(FAKE_API_KEY, aad=prefix + b"secret")
    credential.secret_ciphertext = same_column
    assert decrypt_secret(keyring, credential) == FAKE_API_KEY


def test_rotated_keyring_still_reads_old_rows() -> None:
    """새 키를 맨 앞에 붙이면 옛 키의 행도 읽히고, 새로 만드는 행은 새 키로 암호화된다."""
    old = _credential(FieldKeyring.parse(FAKE_CREDENTIAL_KEYRING))
    rotated = FieldKeyring.parse(FAKE_ROTATED_KEYRING)

    assert decrypt_secret(rotated, old) == FAKE_API_KEY
    assert _credential(rotated).key_id == "k2"


def test_replace_secret_uses_the_current_key_and_updates_fingerprint_and_last4() -> None:
    """키 교체는 지금 맨 앞 키로 다시 암호화하고 지문·끝 4자리를 새 키 것으로 바꾼다. 상태와 판 번호는 그대로다 —
    확인 기록이 옛 지문에 묶여 있어 교체만으로 미확인이 된다."""
    credential = _credential(FieldKeyring.parse(FAKE_CREDENTIAL_KEYRING))
    credential.state, credential.state_reason, credential.state_version = "active", None, 3
    rotated = FieldKeyring.parse(FAKE_ROTATED_KEYRING)

    replace_secret(rotated, credential, FAKE_OTHER_API_KEY)

    assert credential.key_id == "k2"
    assert decrypt_secret(FieldKeyring.parse(_ROTATED_KEY), credential) == FAKE_OTHER_API_KEY
    assert (credential.secret_fingerprint, credential.secret_last4) == (
        secret_fingerprint(FAKE_OTHER_API_KEY),
        FAKE_OTHER_API_KEY[-4:],
    )
    assert credential.secret_fingerprint != secret_fingerprint(FAKE_API_KEY)
    assert (credential.state, credential.state_reason, credential.state_version) == ("active", None, 3)


def test_reencrypt_keeps_fingerprint_and_last4() -> None:
    """키링 회전 뒤 다시 암호화는 값을 그대로 두고 암호문과 키 id 만 바꾼다 — 지문·끝 4자리도 그대로다."""
    credential = _credential(FieldKeyring.parse(FAKE_CREDENTIAL_KEYRING))
    before = (credential.secret_ciphertext, credential.secret_fingerprint, credential.secret_last4)

    reencrypt_secret(FieldKeyring.parse(FAKE_ROTATED_KEYRING), credential)

    assert credential.key_id == "k2"
    assert credential.secret_ciphertext != before[0]
    assert decrypt_secret(FieldKeyring.parse(_ROTATED_KEY), credential) == FAKE_API_KEY
    assert (credential.secret_fingerprint, credential.secret_last4) == before[1:]


def test_empty_keyring_raises_decrypt_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """키 목록이 비면 저장소가 꺼진 것이다 — 키링을 꺼내는 순간 읽을 수 없다는 예외가 나고, 있으면 설정을 그때 읽는다."""
    monkeypatch.setattr(settings, "llm_credential_encryption_keys", "")
    with pytest.raises(FieldDecryptError):
        credential_keyring()

    monkeypatch.setattr(settings, "llm_credential_encryption_keys", FAKE_ROTATED_KEYRING)
    assert credential_keyring().current_key_id == "k2"


# ── 지문 ─────────────────────────────────────────────────────────────────────
def test_fingerprint_is_the_first_eight_hex_of_sha256() -> None:
    """운영자가 콘솔의 키로 `printf %s "$KEY" | shasum -a 256 | cut -c1-8` 해 같은 값을 얻어야 어느 항목인지 맞춰 볼 수
    있다. 표준 시험 벡터(`abc`)로 고정한다."""
    assert secret_fingerprint("abc") == "ba7816bf"
    assert secret_fingerprint(FAKE_API_KEY) == hashlib.sha256(FAKE_API_KEY.encode()).hexdigest()[:8]
    assert secret_last4(FAKE_API_KEY) == "RYzq"


# ── 거절 분류 ─────────────────────────────────────────────────────────────────
_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _rejection(
    status: int, error_type: str | None, message: str = "m", details: dict[str, object] | None = None
) -> anthropic.APIStatusError:
    """SDK 가 오류 응답에서 만드는 모양 그대로. 종류가 없으면 본문이 없는 응답이다."""
    body: dict[str, object] | None = None
    if error_type is not None:
        error: dict[str, object] = {"type": error_type, "message": message}
        if details is not None:
            error["details"] = details
        body = {"type": "error", "error": error}
    return anthropic.APIStatusError(
        f"Error code: {status}", response=httpx2.Response(status, request=_REQUEST), body=body
    )


_LOW_CREDIT = (
    "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or "
    "purchase credits."
)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        pytest.param(_rejection(402, None), "credit", id="402-without-a-type"),
        pytest.param(_rejection(402, "billing_error"), "credit", id="402-billing-error"),
        pytest.param(_rejection(400, "billing_error"), "credit", id="400-billing-error"),
        # 스트림 도중의 오류는 응답 상태가 이미 200 이라 종류로만 드러난다.
        pytest.param(_rejection(200, "billing_error"), "credit", id="mid-stream-billing-error"),
        # 종류가 상태보다 먼저다 — 401 이어도 결제 오류면 크레딧 소진이다.
        pytest.param(_rejection(401, "billing_error"), "credit", id="401-billing-error"),
        pytest.param(_rejection(400, "invalid_request_error", _LOW_CREDIT), "credit", id="400-low-credit"),
        pytest.param(
            _rejection(400, "invalid_request_error", "YOUR Credit Balance Is Too LOW to access the API."),
            "credit",
            id="400-low-credit-mixed-case",
        ),
        pytest.param(_rejection(401, "authentication_error", "invalid x-api-key"), "auth", id="401"),
        pytest.param(
            _rejection(400, "invalid_request_error", "This organization has been disabled."),
            "auth",
            id="400-organization-disabled",
        ),
        pytest.param(
            _rejection(
                400,
                "invalid_request_error",
                "You have reached your specified API usage limits. You will regain access on 2026-12-01 at 00:00 UTC.",
            ),
            "limit",
            id="400-organization-usage-limit",
        ),
        pytest.param(
            _rejection(
                400,
                "invalid_request_error",
                "You have reached your specified workspace API usage limits. You will regain access on 2026-12-01.",
            ),
            "limit",
            id="400-workspace-usage-limit",
        ),
        pytest.param(
            _rejection(429, "rate_limit_error", "spend cap", {"error_code": "enforced_spend_limit_reached"}),
            "limit",
            id="429-spend-cap",
        ),
        pytest.param(_rejection(429, "rate_limit_error", "Number of request tokens has exceeded"), None, id="429"),
        pytest.param(_rejection(403, "permission_error"), None, id="403"),
        pytest.param(_rejection(400, "invalid_request_error", "max_tokens: must be positive"), None, id="400-other"),
        pytest.param(_rejection(404, "not_found_error"), None, id="404"),
        pytest.param(_rejection(413, "request_too_large"), None, id="413"),
        pytest.param(_rejection(529, "overloaded_error"), None, id="529"),
        pytest.param(_rejection(500, "api_error"), None, id="500"),
        pytest.param(_rejection(200, "overloaded_error"), None, id="mid-stream-overloaded"),
        pytest.param(anthropic.APIConnectionError(request=_REQUEST), None, id="connection"),
        pytest.param(anthropic.APITimeoutError(request=_REQUEST), None, id="sdk-timeout"),
        pytest.param(httpx2.ReadTimeout("read timed out"), None, id="httpx2-read-timeout"),
        pytest.param(TimeoutError(), None, id="bare-timeout"),
    ],
)
def test_anthropic_rejections_are_classified(exc: BaseException, expected: str | None) -> None:
    """그 자격을 소진으로 볼 거절(크레딧·키 무효·사용 한도)만 종류를 돌려주고, 그 요청만의 실패는 None 이다 — None 을
    소진으로 오판하면 멀쩡한 계정이 목록에서 빠지고, 소진을 None 으로 놓치면 소진된 계정에 계속 보낸다."""
    assert classify_anthropic_rejection(exc) == expected


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        pytest.param(_rejection(402, None), "credit", id="402-is-the-classifier-credit"),
        pytest.param(_rejection(401, "authentication_error"), "auth", id="401-is-the-classifier-auth"),
        pytest.param(
            _rejection(429, "rate_limit_error", "spend cap", {"error_code": "enforced_spend_limit_reached"}),
            "limit",
            id="spend-cap-is-the-classifier-limit",
        ),
        pytest.param(_rejection(403, "permission_error"), "permission", id="403"),
        pytest.param(_rejection(404, "not_found_error"), "model-not-found", id="404"),
        pytest.param(_rejection(400, "invalid_request_error", "max_tokens: must be positive"), "rejected", id="400"),
        pytest.param(_rejection(413, "request_too_large"), "rejected", id="413"),
        pytest.param(_rejection(429, "rate_limit_error"), "unavailable", id="429"),
        pytest.param(_rejection(529, "overloaded_error"), "unavailable", id="529"),
        pytest.param(_rejection(500, "api_error"), "unavailable", id="500"),
        pytest.param(anthropic.APITimeoutError(request=_REQUEST), "unavailable", id="sdk-timeout"),
        pytest.param(anthropic.APIConnectionError(request=_REQUEST), "unavailable", id="connection"),
        pytest.param(httpx2.ReadTimeout("read timed out"), "unavailable", id="httpx2-read-timeout"),
        pytest.param(TimeoutError(), "unavailable", id="bare-timeout"),
    ],
)
def test_probe_failure_kinds_cover_everything_the_classifier_leaves(exc: BaseException, expected: str) -> None:
    """저장·확인 호출의 실패 종류. 소진으로 볼 거절은 분류 함수의 값 그대로이고, 나머지는 권한·모델 없음·그 밖 거절과
    "다시 시도할 일"(과부하·서버 오류·시간 초과·연결)로 가른다 — 마지막 것만 저장을 503 으로 돌려 다시 누르게 한다."""
    assert probe_failure_kind(exc) == expected


# ── 모델 축 ───────────────────────────────────────────────────────────────────
def test_check_axes_match_the_anthropic_backend_models() -> None:
    """확인 호출이 도는 축, 확인 기록 칸의 값, Anthropic 구현이 실제 id 설정을 두는 축이 같은 집합이다 — 모델 라인업에 축이
    늘었는데 확인이 그 축을 돌지 않으면 그 축은 영영 덮이지 않아 목록 사용을 켤 수 없다."""
    assert len(CLAUDE_AXES) == len(set(CLAUDE_AXES))
    assert set(CLAUDE_AXES) == set(get_args(ClaudeModelAxis)) == set(BACKENDS["anthropic"].model_id_settings)


_DEFAULT_IDS: dict[ClaudeModelAxis, str] = {
    "opus": "claude-opus-5-5",
    "sonnet": "claude-sonnet-5-5",
    "haiku_writer": "claude-haiku-5-5",
    "haiku": "claude-haiku-5-5",
}


def test_ids_shared_by_axes_are_grouped_and_take_the_generation_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """같은 실제 id 는 한 번만 부르고 그 결과를 그 id 를 쓰는 축마다 남긴다. 생성 축과 판정 축이 같은 id 를 쓰면 사용자가 값을
    내는 쪽(생성 꼴)으로 확인하고, 판정 전용 id 는 판정 꼴로 보내 판정 요청 규칙의 거부를 놓치지 않는다."""
    for axis, model_id in _DEFAULT_IDS.items():
        monkeypatch.setattr(settings, BACKENDS["anthropic"].model_id_settings[axis], model_id)

    assert current_model_ids() == _DEFAULT_IDS
    assert check_groups(current_model_ids()) == [
        CheckGroup(model_id="claude-opus-5-5", axes=("opus",), shape="generation"),
        CheckGroup(model_id="claude-sonnet-5-5", axes=("sonnet",), shape="generation"),
        CheckGroup(model_id="claude-haiku-5-5", axes=("haiku_writer", "haiku"), shape="generation"),
    ]
    assert check_groups({**_DEFAULT_IDS, "haiku": "claude-haiku-4-5"})[-2:] == [
        CheckGroup(model_id="claude-haiku-5-5", axes=("haiku_writer",), shape="generation"),
        CheckGroup(model_id="claude-haiku-4-5", axes=("haiku",), shape="judgment"),
    ]


# ── 확인 기록으로 켜기·덮임 판정 ──────────────────────────────────────────────────────
_ORG = "org-test-0001"
_ALLOWED: frozenset[tuple[AccountProvider, str]] = frozenset({("anthropic", _ORG)})


def _active(keyring: FieldKeyring, secret: str = FAKE_API_KEY) -> LlmCredential:
    credential = _credential(keyring, secret)
    credential.state, credential.state_reason = "active", None
    return credential


def _check(
    credential: LlmCredential,
    run: int,
    axis: ClaudeModelAxis = "opus",
    *,
    error_kind: CheckErrorKind | None = None,
    state_version: int | None = None,
    fingerprint: str | None = None,
    model_id: str | None = None,
    checked_at: datetime | None = None,
) -> LlmCredentialCheck:
    return LlmCredentialCheck(
        id=uuid.uuid4(),
        credential_id=credential.id,
        run=run,
        state_version=credential.state_version if state_version is None else state_version,
        model_axis=axis,
        sent_model_id=_DEFAULT_IDS[axis] if model_id is None else model_id,
        secret_fingerprint=credential.secret_fingerprint if fingerprint is None else fingerprint,
        passed=error_kind is None,
        error_kind=error_kind,
        organization_header=None,
        checked_at=checked_at or datetime(2026, 11, 4, tzinfo=UTC),
    )


def test_latest_check_per_axis_is_the_highest_run() -> None:
    """축마다 최신은 회차로 고른다 — 기록 시각은 한 트랜잭션 안에서 같고 시계 순서가 커밋 순서를 보장하지 않는다. 뒤 회차의
    기록 시각을 일부러 앞 회차보다 이르게 두어, 시각으로 고르면 통과·회차로 고르면 실패가 나오게 했다."""
    credential = _credential(FieldKeyring.parse(FAKE_CREDENTIAL_KEYRING))
    first = _check(credential, 1, checked_at=datetime(2026, 11, 4, 12, tzinfo=UTC))
    second = _check(credential, 2, error_kind="credit", checked_at=datetime(2026, 11, 4, 11, tzinfo=UTC))
    sonnet = _check(credential, 1, "sonnet")

    latest = latest_checks_per_axis([second, sonnet, first])

    assert latest == {"opus": second, "sonnet": sonnet}


_Row = tuple[int, CheckErrorKind | None]


@pytest.mark.parametrize(
    ("account_ref", "rows", "expected"),
    [
        pytest.param(None, [(1, None)], "organization-unverified", id="unverified-organization"),
        pytest.param("org-test-0009", [(1, None)], "account-not-allowed", id="organization-outside-the-allowlist"),
        pytest.param(_ORG, [], "check-required", id="no-check"),
        pytest.param(_ORG, ["stale-version"], "check-required", id="check-started-before-a-state-change"),
        pytest.param(_ORG, ["old-secret"], "check-required", id="check-of-the-previous-secret"),
        pytest.param(_ORG, [(1, "credit"), (1, "unavailable")], "check-required", id="nothing-passed"),
        pytest.param(_ORG, [(1, None), (2, "credit")], "check-required", id="latest-run-did-not-pass"),
        pytest.param(
            _ORG,
            [(1, None), (1, None), (2, "unavailable"), (2, "unavailable")],
            "check-required",
            id="latest-run-had-only-transient-errors",
        ),
        pytest.param(
            _ORG, [(1, None), (1, "organization-mismatch")], "organization-mismatch", id="one-axis-org-mismatch"
        ),
        pytest.param(_ORG, [(1, None), (1, "account-not-allowed")], "organization-mismatch", id="one-axis-not-allowed"),
        pytest.param(
            _ORG,
            [(1, "organization-mismatch"), (1, None), (2, None), (2, None)],
            None,
            id="earlier-mismatch-is-cleared-when-that-axis-passes-again",
        ),
        pytest.param(
            _ORG,
            [(1, "organization-mismatch"), (1, None), (2, "unavailable"), (2, None)],
            "organization-mismatch",
            id="mismatch-is-not-cleared-by-a-transient-error-on-that-axis",
        ),
        pytest.param(
            _ORG,
            [(1, "organization-mismatch"), (1, None), (2, "model-not-found"), (2, None)],
            "organization-mismatch",
            id="mismatch-is-not-cleared-by-an-unrelated-failure-on-that-axis",
        ),
        pytest.param(_ORG, [(1, None), (1, "credit")], None, id="one-passing-axis-is-enough"),
    ],
)
def test_enable_blocker_order(account_ref: str | None, rows: list[_Row | str], expected: str | None) -> None:
    """켜기 조건은 위에서부터 처음 걸린 것을 이유로 낸다: 조직 미확인 → 허용 목록 밖 → 지금 키·지금 판의 최신 회차에 통과가
    없음 → 조직 신호(어느 축이든 그 축의 마지막 조직 판정 — 통과나 조직 오류 — 이 조직 오류). 조직 신호는 런타임 후보 판정과
    같은 규칙이라, 런타임이 조직 때문에 쓰지 않는 항목은 켜지지도 않는다 — 어긋난 축이 다시 통과해야 풀리고, 그 축의 일시 오류나
    조직과 무관한 실패로는 풀리지 않는다. 판은 시각 대신 쓰는 기준이다 — 확인을 시작한 뒤 상태가 바뀌었으면(끄기·소진) 그 회차는 세지
    않는다. 축이 모자란 것은 켜기가 아니라 목록 사용 켜기가 막는다. 일시 오류뿐인 최신 회차도 통과가 없는 회차다 — 런타임
    후보 판정과 달리 그 전 회차의 통과로 내려가지 않는다."""
    credential = _credential(FieldKeyring.parse(FAKE_CREDENTIAL_KEYRING))
    credential.account_ref = account_ref
    credential.state_version = 3
    axes: list[ClaudeModelAxis] = ["opus", "sonnet"]
    checks: list[LlmCredentialCheck] = []
    for index, row in enumerate(rows):
        if row == "stale-version":
            checks.append(_check(credential, 1, state_version=2))
        elif row == "old-secret":
            checks.append(_check(credential, 1, fingerprint=secret_fingerprint(FAKE_OTHER_API_KEY)))
        else:
            assert isinstance(row, tuple)
            checks.append(_check(credential, row[0], axes[index % 2], error_kind=row[1]))

    assert enable_blocker(credential, checks, _ALLOWED) == expected


def test_same_as_env_key_is_computed_from_the_current_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """env 롤백 키와 같은 키인지는 저장하지 않고 그때의 env 키로 계산한다 — env 키를 바꾸면 같은 행의 답이 바뀐다."""
    credential = _credential(FieldKeyring.parse(FAKE_CREDENTIAL_KEYRING))

    monkeypatch.setattr(settings, "anthropic_direct_api_key", "")
    assert same_as_env_key(credential) is False
    monkeypatch.setattr(settings, "anthropic_direct_api_key", f" {FAKE_API_KEY}\n")
    assert same_as_env_key(credential) is True
    monkeypatch.setattr(settings, "anthropic_direct_api_key", FAKE_OTHER_API_KEY)
    assert same_as_env_key(credential) is False


def _covered(keyring: FieldKeyring) -> tuple[LlmCredential, dict[ClaudeModelAxis, LlmCredentialCheck]]:
    credential = _active(keyring)
    return credential, {axis: _check(credential, 1, axis) for axis in CLAUDE_AXES}


@pytest.mark.parametrize(
    ("breaking", "expected"),
    [
        pytest.param("nothing", [], id="covered"),
        pytest.param("disabled", list(CLAUDE_AXES), id="not-active"),
        pytest.param("unverified", list(CLAUDE_AXES), id="organization-unverified"),
        pytest.param("not-allowed", list(CLAUDE_AXES), id="organization-outside-the-allowlist"),
        pytest.param("opus-failed", ["opus"], id="latest-check-failed"),
        pytest.param("sonnet-old-secret", ["sonnet"], id="check-of-the-previous-secret"),
        pytest.param("haiku-old-model-id", ["haiku"], id="check-sent-another-model-id"),
        pytest.param("haiku-writer-missing", ["haiku_writer"], id="axis-never-checked"),
        pytest.param("opus-failed-but-another-covers", [], id="another-credential-covers-the-axis"),
        pytest.param("opus-transient", ["opus"], id="latest-check-was-a-transient-error"),
        pytest.param("organization-signal", list(CLAUDE_AXES), id="runtime-drops-the-item-for-an-organization-error"),
    ],
)
def test_uncovered_axes_require_active_verified_current_secret_and_current_model_id(
    breaking: str, expected: list[str]
) -> None:
    """목록 사용을 켜려면 축마다 덮는 항목이 하나 이상 있어야 한다: 켜져 있고, 조직이 확인돼 지금 허용 목록 안이고, 그 축의
    최신 확인이 통과했고, 그 확인이 지금 키와 지금 설정의 모델 id 로 한 것이고, 런타임도 그 축을 받는다. 최신 확인이 일시 오류면
    런타임은 이전 통과로 그 축을 받아도 덮지 않는다(새로 쓰기 시작하는 결정이라 확정 통과가 필요하다). 거꾸로 다른 축의 최신
    확인이 통과여도 런타임이 조직 신호로 그 항목을 쓰지 않으면(회차 2 에서 haiku 조직 불일치, 회차 3 에서 haiku 만 429) 어느
    축도 덮지 않는다."""
    keyring = FieldKeyring.parse(FAKE_CREDENTIAL_KEYRING)
    credential, checks = _covered(keyring)
    credential.account_ref = _ORG
    credentials = [credential]
    history: dict[uuid.UUID, list[LlmCredentialCheck]] = {credential.id: []}
    if breaking == "disabled":
        credential.state, credential.state_reason = "disabled", "admin"
    elif breaking == "unverified":
        credential.account_ref = None
    elif breaking == "not-allowed":
        credential.account_ref = "org-test-0009"
    elif breaking in ("opus-failed", "opus-failed-but-another-covers"):
        checks["opus"] = _check(credential, 2, "opus", error_kind="credit")
    elif breaking == "sonnet-old-secret":
        checks["sonnet"] = _check(credential, 1, "sonnet", fingerprint=secret_fingerprint(FAKE_OTHER_API_KEY))
    elif breaking == "haiku-old-model-id":
        checks["haiku"] = _check(credential, 1, "haiku", model_id="claude-haiku-4-5")
    elif breaking == "haiku-writer-missing":
        del checks["haiku_writer"]
    elif breaking == "opus-transient":
        history[credential.id].append(checks["opus"])
        checks["opus"] = _check(credential, 2, "opus", error_kind="unavailable")
    elif breaking == "organization-signal":
        history[credential.id] += [*checks.values(), _check(credential, 2, "haiku", error_kind="organization-mismatch")]
        others: tuple[ClaudeModelAxis, ...] = ("opus", "sonnet", "haiku_writer")
        history[credential.id] += [_check(credential, 2, axis) for axis in others]
        checks = {axis: _check(credential, 3, axis) for axis in CLAUDE_AXES}
        checks["haiku"] = _check(credential, 3, "haiku", error_kind="unavailable")
    if breaking == "opus-failed-but-another-covers":
        other = _active(keyring, FAKE_OTHER_API_KEY)
        other.account_ref = "org-test-0002"
        credentials.append(other)
        history[other.id] = [_check(other, 1, "opus")]
    all_checks = {credential.id: [*history[credential.id], *checks.values()]}
    all_checks.update({key: rows for key, rows in history.items() if key != credential.id})

    allowed: frozenset[tuple[AccountProvider, str]] = _ALLOWED | {("anthropic", "org-test-0002")}
    assert uncovered_axes(credentials, all_checks, _DEFAULT_IDS, allowed) == expected
