"""Claude 자격 목록의 순수 함수 — 비밀 암호화(연관 데이터·키링 회전·교체·재암호화), 지문, 거절 분류.

암호화 테스트는 DB 를 타지 않는다 — 행 id 를 코드가 정하므로 모델 객체만으로 연관 데이터의 묶임을 볼 수 있다."""

import base64
import hashlib
import uuid

import anthropic
import httpx2
import pytest

from api.core.config import settings
from api.core.field_crypto import FieldDecryptError, FieldKeyring
from api.db.models.llm_credential import LlmCredential
from api.llm.credentials import (
    classify_anthropic_rejection,
    credential_keyring,
    decrypt_secret,
    new_credential,
    reencrypt_secret,
    replace_secret,
    secret_fingerprint,
    secret_last4,
)

_FIRST_KEY = "k1:" + base64.urlsafe_b64encode(b"\x01" * 32).decode()
_ROTATED_KEY = "k2:" + base64.urlsafe_b64encode(b"\x02" * 32).decode()
FAKE_CREDENTIAL_KEYRING = _FIRST_KEY
FAKE_ROTATED_KEYRING = f"{_ROTATED_KEY},{_FIRST_KEY}"
# 가짜 키다. 끝 네 글자는 다른 가짜 값(라벨·지문·id)에 우연히 나오지 않는 글자로 골랐다.
FAKE_API_KEY = "sk-ant-test-" + "0123456789abcdefghij0123456789abcdeCANARYzq"
OTHER_API_KEY = "sk-ant-test-" + "zyxwvutsrq9876543210zyxwvutsrqOTHERkeyWx"


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
    other = _credential(keyring, OTHER_API_KEY)

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

    replace_secret(rotated, credential, OTHER_API_KEY)

    assert credential.key_id == "k2"
    assert decrypt_secret(FieldKeyring.parse(_ROTATED_KEY), credential) == OTHER_API_KEY
    assert (credential.secret_fingerprint, credential.secret_last4) == (
        secret_fingerprint(OTHER_API_KEY),
        OTHER_API_KEY[-4:],
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
