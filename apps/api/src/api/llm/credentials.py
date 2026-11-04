"""Claude 자격 목록의 저장 규칙 — 키링·허용 목록 접근, 비밀 암호화와 지문, Anthropic 거절 분류, 표 쓰기의 DB 오류 변환.

- 비밀은 `core/field_crypto.py` 의 키링으로 암호화한다. 연관 데이터는 표 접두 + 행 id + 칸 이름(`secret`)이라, 다른 항목
  행이나 다른 칸으로 옮긴 암호문은 조용한 오답 대신 복호화 실패가 된다. 그래서 행 id 는 암호화 전에 정한다.
- 지문은 비밀 원문 sha256 의 앞 8자다. 키링과 무관해 회전해도 값이 같고(확인 기록이 지문으로 그때의 키에 묶인다), 운영자가
  콘솔의 키로 `printf %s "$KEY" | shasum -a 256 | cut -c1-8` 해 어느 항목인지 맞춰 볼 수 있다. 입력이 엔트로피가 큰 API 키라
  길이와 무관하게 역산할 수 없고, 비교 대상이 항목 몇 개뿐이라 8자의 충돌 확률은 무시할 수 있다. 끝 4자리는 화면 힌트로만
  쓴다(원문의 일부라 감사 로그·알림에 싣지 않는다).
- 설정은 호출 때마다 `settings` 에서 다시 읽는다 — 테스트가 `monkeypatch.setattr(settings, …)` 로 값을 정한다.
"""

import hashlib
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Literal

import anthropic
from fastapi import HTTPException, status
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.field_crypto import FieldDecryptError, FieldKeyring
from api.db.models.llm_credential import CredentialProvider, CredentialStateReason, LlmCredential
from api.llm.credential_accounts import AccountProvider, parse_allowed_accounts

# 운영자가 끈 상태의 이유. 새 항목도 이 상태로 시작한다(확인 호출이 통과한 뒤에 켠다) — 끄기와 같은 값을 쓴다.
ADMIN_DISABLED_REASON: CredentialStateReason = "admin"


# ── 설정 ─────────────────────────────────────────────────────────────────────
def credential_keyring() -> FieldKeyring:
    """자격 암호화 키 목록. 형식은 기동 때 설정 검증이 이미 확인했다. 키가 비어 있으면 `FieldDecryptError` — 저장소가 꺼진
    것이고, 그때 저장한 비밀은 읽을 수 없는 것과 같다."""
    if not settings.llm_credential_encryption_keys:
        raise FieldDecryptError
    return FieldKeyring.parse(settings.llm_credential_encryption_keys)


def allowed_accounts() -> frozenset[tuple[AccountProvider, str]]:
    """목록에 넣을 수 있는 계정. 형식은 기동 때 설정 검증이 이미 확인했다."""
    return parse_allowed_accounts(settings.llm_credential_allowed_accounts)


def store_configured() -> bool:
    """자격을 저장·확인할 수 있는가: 암호화 키와 허용 계정이 둘 다 있다."""
    return bool(settings.llm_credential_encryption_keys) and bool(allowed_accounts())


# ── 암호화 ───────────────────────────────────────────────────────────────────
def _aad(credential_id: uuid.UUID, column: Literal["secret"]) -> bytes:
    return b"llm_credential:" + credential_id.bytes + b":" + column.encode()


def secret_fingerprint(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()[:8]


def secret_last4(secret: str) -> str:
    return secret[-4:]


def new_credential(
    keyring: FieldKeyring,
    *,
    provider: CredentialProvider,
    label: str,
    secret: str,
    account_ref: str | None,
    position: int,
    credit_micro_usd: int | None,
    alert_pct: int,
) -> LlmCredential:
    """암호화한 새 항목. 꺼진 채(운영자가 끔) 시작한다. 충전액이 있으면 그 기준 시각은 지금이다."""
    credential_id = uuid.uuid4()
    key_id, blob = keyring.encrypt(secret, aad=_aad(credential_id, "secret"))
    return LlmCredential(
        id=credential_id,
        provider=provider,
        label=label,
        position=position,
        state="disabled",
        state_reason=ADMIN_DISABLED_REASON,
        state_version=0,
        account_ref=account_ref,
        key_id=key_id,
        secret_ciphertext=blob,
        secret_last4=secret_last4(secret),
        secret_fingerprint=secret_fingerprint(secret),
        credit_micro_usd=credit_micro_usd,
        credit_since=None if credit_micro_usd is None else datetime.now(UTC),
        alert_pct=alert_pct,
    )


def decrypt_secret(keyring: FieldKeyring, credential: LlmCredential) -> str:
    """저장한 비밀을 되읽는다. 실패하면 `FieldDecryptError`."""
    return keyring.decrypt(credential.key_id, credential.secret_ciphertext, aad=_aad(credential.id, "secret"))


def replace_secret(keyring: FieldKeyring, credential: LlmCredential, secret: str) -> None:
    """비밀을 새 값으로 바꾼다 — 지금 맨 앞 키로 암호화하고 지문·끝 4자리를 새 값으로 갱신한다. 상태·판 번호는 그대로다:
    확인 기록이 옛 지문에 묶여 있어 교체만으로 그 기록이 지금 키의 확인이 아니게 된다."""
    credential.key_id, credential.secret_ciphertext = keyring.encrypt(secret, aad=_aad(credential.id, "secret"))
    credential.secret_last4 = secret_last4(secret)
    credential.secret_fingerprint = secret_fingerprint(secret)


def reencrypt_secret(keyring: FieldKeyring, credential: LlmCredential) -> None:
    """키링 회전 뒤 같은 값을 지금 키로 다시 쓴다. 값이 같으니 지문·끝 4자리는 그대로다. 복호화에 실패하면
    `FieldDecryptError` 이고 행은 그대로다."""
    secret = decrypt_secret(keyring, credential)
    credential.key_id, credential.secret_ciphertext = keyring.encrypt(secret, aad=_aad(credential.id, "secret"))


# ── 거절 분류 ─────────────────────────────────────────────────────────────────
RejectionKind = Literal["credit", "auth", "limit"]


def _error_object(exc: anthropic.APIStatusError) -> dict[str, object]:
    body = exc.body
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return error
    return {}


def classify_anthropic_rejection(exc: BaseException) -> RejectionKind | None:
    """그 오류가 그 자격을 소진으로 볼 거절인가. None 이면 소진이 아니다(그 요청만의 실패).

    위에서부터 처음 맞는 규칙을 쓴다. 메시지 대조는 대소문자를 무시한 부분 일치이고, 메시지는 응답 본문의 `error.message`
    가 문자열이면 그것, 아니면 SDK 예외 문장이다. 결제 오류 종류는 HTTP 상태와 무관하게 크레딧 소진이다(스트림 도중이라
    상태가 200 이어도). 이 함수는 뜻만 판정한다 — 스트림 도중의 거절을 재시도·전환할지는 부르는 쪽이 정한다.
    """
    if not isinstance(exc, anthropic.APIStatusError):
        return None
    if exc.type == "billing_error":
        return "credit"
    if exc.status_code == 402:
        return "credit"
    if exc.status_code == 401:
        return "auth"
    error = _error_object(exc)
    message = error.get("message")
    text = (message if isinstance(message, str) else exc.message).lower()
    if exc.status_code == 400:
        if "credit balance is too low" in text:
            return "credit"
        if "this organization has been disabled" in text:
            return "auth"
        # 조직·워크스페이스 사용 한도 두 문구를 함께 덮는다.
        if "you have reached your specified" in text and "api usage limits" in text:
            return "limit"
    if exc.status_code == 429:
        details = error.get("details")
        if isinstance(details, dict) and details.get("error_code") == "enforced_spend_limit_reached":
            return "limit"
    return None


# ── 표 쓰기의 DB 오류 ──────────────────────────────────────────────────────────
_UNIQUE_VIOLATION = "23505"


class CredentialStoreError(Exception):
    """자격 표 쓰기가 DB 에서 실패했다. 문장에 오류 클래스 이름과 SQLSTATE 만 싣는다 — 드라이버 오류의 DETAIL 이 위반한
    행 전체(암호문 포함)를 싣기 때문이다."""


@asynccontextmanager
async def credential_write(db: AsyncSession) -> AsyncIterator[None]:
    """자격 표에 쓰는 구간을 감싼다 — 첫 변경부터 `commit()` 까지를 통째로 이 안에 둔다(자동 flush 가 다음 SELECT 에서
    터지는 경우까지 덮는다). 세션은 부르는 쪽이 닫는다(닫을 때 되돌려진다).

    비밀이 나가는 길이 둘이라 이 표들에 쓰는 **모든** 문장이 대상이다: SQLAlchemy 문장 오류가 싣는 파라미터(그 문장의
    암호문)와, CHECK·NOT NULL 위반 때 드라이버 오류의 DETAIL 이 싣는 위반한 행 전체(상태만 바꾸는 UPDATE 라도 그 행의
    암호문 앞부분이 hex 로 실린다). 원인 사슬을 끊어(`from None`) 오류 추적과 traceback 출력이 그 문장을 싣지 않게 한다.
    유일 위반은 동시 저장의 정상 경쟁이라 사유 없는 409 이고, 그 밖(CHECK·NOT NULL·FK 위반은 버그, 연결 오류)은 클래스
    이름·SQLSTATE 만 실은 `CredentialStoreError` 로 500 이 되어 오류 추적에 남는다. 안에서 내는 `HTTPException` 은 DB 오류가
    아니라 그대로 지나간다.
    """
    try:
        yield
    except DBAPIError as exc:
        sqlstate = getattr(exc.orig, "sqlstate", None)
        if isinstance(exc, IntegrityError) and sqlstate == _UNIQUE_VIOLATION:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "rule": "conflict",
                    "message": "다른 변경이 먼저 반영됐습니다. 새로 고친 뒤 다시 시도해 주세요.",
                },
            ) from None
        raise CredentialStoreError(f"{type(exc).__name__} sqlstate={sqlstate}") from None
