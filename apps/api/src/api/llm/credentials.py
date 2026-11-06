"""Claude 자격 목록의 저장 규칙 — 키링·허용 목록 접근, 비밀 암호화와 지문, 키 형식 검사, Anthropic 거절 분류, 확인 호출의
모델 축과 그 기록으로 하는 판정(켜기 조건·목록 사용 덮임·런타임에 받을 수 있는 축·env 롤백 키와 같은 키), 표 쓰기의 DB 오류 변환.

- 비밀은 `core/field_crypto.py` 의 키링으로 암호화한다. 연관 데이터는 표 접두 + 행 id + 칸 이름(`secret`)이라, 다른 항목
  행이나 다른 칸으로 옮긴 암호문은 조용한 오답 대신 복호화 실패가 된다. 그래서 행 id 는 암호화 전에 정한다.
- 지문은 비밀 원문 sha256 의 앞 8자다. 키링과 무관해 회전해도 값이 같고(확인 기록이 지문으로 그때의 키에 묶인다), 운영자가
  콘솔의 키로 `printf %s "$KEY" | shasum -a 256 | cut -c1-8` 해 어느 항목인지 맞춰 볼 수 있다. 입력이 엔트로피가 큰 API 키라
  길이와 무관하게 역산할 수 없고, 비교 대상이 항목 몇 개뿐이라 8자의 충돌 확률은 무시할 수 있다. 끝 4자리는 화면 힌트로만
  쓴다(원문의 일부라 감사 로그·알림에 싣지 않는다).
- 설정은 호출 때마다 `settings` 에서 다시 읽는다 — 테스트가 `monkeypatch.setattr(settings, …)` 로 값을 정한다.
"""

import hashlib
import re
import uuid
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import anthropic
from fastapi import HTTPException, status
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.field_crypto import FieldDecryptError, FieldKeyring
from api.db.models.llm_credential import (
    CheckErrorKind,
    ClaudeModelAxis,
    CredentialProvider,
    CredentialStateReason,
    LlmCredential,
    LlmCredentialCheck,
)
from api.llm.chat_models import backend_model_id
from api.llm.credential_accounts import AccountProvider, parse_allowed_accounts

# 운영자가 끈 상태의 이유. 새 항목도 이 상태로 시작한다(확인 호출이 통과한 뒤에 켠다) — 끄기와 같은 값을 쓴다.
ADMIN_DISABLED_REASON: CredentialStateReason = "admin"
# 런타임이 Redis 에 두는 모든 키(목록 스냅숏·세대, 추정 사용액, 알림 중복 억제 표지)의 접두. 하나로 두어 운영 문서의 "지우지
# 마라"와 테스트의 격리가 한 줄이 된다. 확인 호출의 분당 제한 키는 제한 기구의 접두(`rate_limit:`)를 따른다.
CREDENTIAL_KEY_PREFIX = "llm_credential:"


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
    return decrypt_stored_secret(
        keyring, credential_id=credential.id, key_id=credential.key_id, ciphertext=credential.secret_ciphertext
    )


def decrypt_stored_secret(keyring: FieldKeyring, *, credential_id: uuid.UUID, key_id: str, ciphertext: bytes) -> str:
    """행 객체 없이 그 칸 값들로 비밀을 되읽는다(런타임은 행이 아니라 캐시한 스냅숏 항목을 든다). 규칙은 `decrypt_secret` 과 같다
    — 연관 데이터가 그 항목 id 라 다른 항목의 암호문이면 실패한다. 실패하면 `FieldDecryptError`."""
    return keyring.decrypt(key_id, ciphertext, aad=_aad(credential_id, "secret"))


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



ProbeFailureKind = Literal["credit", "auth", "limit", "permission", "model-not-found", "rejected", "unavailable"]


def probe_failure_kind(exc: BaseException) -> ProbeFailureKind:
    """저장(토큰 세기)·확인 호출이 실패한 종류. 소진으로 볼 거절은 위 분류 그대로이고, 나머지는 권한(403)·모델 없음(404)·그
    밖 거절(429 를 뺀 4xx)과 다시 시도할 일(429·과부하·서버 오류·시간 초과·연결)로 가른다."""
    rejection = classify_anthropic_rejection(exc)
    if rejection is not None:
        return rejection
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code == 403:
            return "permission"
        if exc.status_code == 404:
            return "model-not-found"
        if 400 <= exc.status_code < 500 and exc.status_code != 429:
            return "rejected"
    return "unavailable"


# ── 키 형식 ───────────────────────────────────────────────────────────────────
# 공백 없는 인쇄 가능 ASCII. 줄바꿈·제어 문자가 섞인 값이 SDK 헤더로 가면 하위 계층(h11)이 그 값을 오류 문장에 싣는다. 접두
# (`sk-ant-`)는 형식 근거가 없어 보지 않는다 — 틀린 키는 어차피 조직 조회에서 401 로 거부된다.
_API_KEY_SHAPE = re.compile(r"[\x21-\x7e]{20,256}")


class SecretFormatError(ValueError):
    """붙여넣은 값이 키 형식이 아니다. 문장에 값·길이를 싣지 않는다."""


def validate_api_key_format(raw: str) -> str:
    """앞뒤 공백을 지운 키. 암호화·지문이 이 값에서 나오므로 먼저 지워야 같은 키의 지문이 env 키·콘솔에서 계산한 값과 맞는다."""
    key = raw.strip()
    if not _API_KEY_SHAPE.fullmatch(key):
        raise SecretFormatError("키 형식이 아닙니다")
    return key


# ── 모델 축 ───────────────────────────────────────────────────────────────────
# 확인 호출이 도는 순서. Anthropic 구현이 실제 id 설정을 두는 축과 같은 집합이어야 한다(테스트가 본다).
CLAUDE_AXES: tuple[ClaudeModelAxis, ...] = ("opus", "sonnet", "haiku_writer", "haiku")
# 판정·요약 전용 축. 이 축만 쓰는 id 는 판정 요청 꼴로 확인한다.
_JUDGMENT_AXES: frozenset[ClaudeModelAxis] = frozenset({"haiku"})

CheckShape = Literal["generation", "judgment"]


@dataclass(frozen=True)
class CheckGroup:
    """실제 id 하나로 하는 확인 호출 한 번과 그 결과를 남길 축들. 생성 축이 하나라도 있으면 생성 요청 꼴로 보낸다 — 사용자가
    값을 내는 쪽의 요청 형태를 확인하고, 판정 전용 id 만 판정 요청 꼴(그 규칙의 거부를 놓치지 않게)로 보낸다."""

    model_id: str
    axes: tuple[ClaudeModelAxis, ...]
    shape: CheckShape


def current_model_ids() -> dict[ClaudeModelAxis, str]:
    """축마다 지금 설정의 실제 id."""
    return {axis: backend_model_id("anthropic", axis) for axis in CLAUDE_AXES}


def check_groups(model_ids: Mapping[ClaudeModelAxis, str]) -> list[CheckGroup]:
    """같은 실제 id 를 쓰는 축을 묶는다(호출은 id 수만큼). 순서는 축 순서에서 그 id 가 처음 나온 자리다."""
    axes_by_id: dict[str, list[ClaudeModelAxis]] = {}
    for axis in CLAUDE_AXES:
        axes_by_id.setdefault(model_ids[axis], []).append(axis)
    return [
        CheckGroup(model_id, tuple(axes), "judgment" if set(axes) <= _JUDGMENT_AXES else "generation")
        for model_id, axes in axes_by_id.items()
    ]


# ── 확인 기록으로 하는 판정 ─────────────────────────────────────────────────────────
EnableBlocker = Literal["organization-unverified", "account-not-allowed", "check-required", "organization-mismatch"]

# 응답 조직이 어긋났다는 기록. 한 축이라도 있으면 다른 축이 통과했어도 켜지 않는다(보안 신호).
_ORGANIZATION_ERRORS: frozenset[CheckErrorKind] = frozenset({"organization-mismatch", "account-not-allowed"})
# 확인 호출의 일시 오류(429·과부하·서버 오류·시간 초과·연결 — `probe_failure_kind` 가 다시 시도할 일로 가른 것). 그 축이 지금
# 키로 되는지 아무것도 결론 내지 않은 기록이라, 런타임 후보 판정은 이 기록을 건너뛰고 그 축의 이전 결론을 쓴다.
TRANSIENT_CHECK_ERROR: CheckErrorKind = "unavailable"
_ACCOUNT_PROVIDER: dict[CredentialProvider, AccountProvider] = {"anthropic": "anthropic", "bedrock": "aws"}


def account_in_allowlist(
    provider: CredentialProvider, account_ref: str, allowed: frozenset[tuple[AccountProvider, str]]
) -> bool:
    """그 공급자의 조직(계정) id 가 허용 목록 안인가."""
    return (_ACCOUNT_PROVIDER[provider], account_ref) in allowed


def _verified_and_allowed(credential: LlmCredential, allowed: frozenset[tuple[AccountProvider, str]]) -> bool:
    return credential.account_ref is not None and account_in_allowlist(credential.provider, credential.account_ref, allowed)


def latest_checks_per_axis(checks: Iterable[LlmCredentialCheck]) -> dict[ClaudeModelAxis, LlmCredentialCheck]:
    """축마다 회차가 가장 큰 기록. 기록 시각은 보지 않는다 — 한 트랜잭션 안에서는 같고, 시계 순서가 커밋 순서를 보장하지
    않는다."""
    latest: dict[ClaudeModelAxis, LlmCredentialCheck] = {}
    for check in checks:
        current = latest.get(check.model_axis)
        if current is None or check.run > current.run:
            latest[check.model_axis] = check
    return latest


def enable_blocker(
    credential: LlmCredential,
    checks: Sequence[LlmCredentialCheck],
    allowed: frozenset[tuple[AccountProvider, str]],
) -> EnableBlocker | None:
    """그 항목(`checks` 는 그 항목의 기록)을 켤 수 없는 이유 중 처음 걸린 것, 켤 수 있으면 None.

    기준 회차는 지금 키 지문의 기록 중 회차가 가장 큰 것이다. 그 회차가 시작할 때의 판이 지금 판과 같고 통과한 축이 하나
    이상이어야 한다 — 상태가 바뀔 때마다 판이 오르므로, 끄기·소진 전에 시작한 확인은 지문이 같아도 세지 않는다(충전하지
    않은 계정을 켰다가 바로 다시 떨어지는 왕복을 막는다). 모든 축의 통과는 요구하지 않는다 — 축이 모자라면 목록 사용 켜기가
    막는다.

    일시 오류 기록도 회차에 그대로 센다 — 일시 오류뿐인 최신 회차는 통과가 없어 켜지 않는다. 런타임 후보 판정(`passed_axes`)은
    일시 오류를 건너뛰고 이전 결론을 쓰지만 켜기는 그러지 않는다: 켜기는 그 항목을 새로 쓰기 시작하는 결정이라 지금 상태에서 난
    확정 통과가 증거로 있어야 하고, 런타임의 건너뛰기는 이미 쓰던 항목을 확인 한 번의 일시 오류로 빼지 않기 위한 것이다.

    조직 불일치는 런타임과 같은 조직 신호(`organization_signal`)로 본다 — 런타임이 조직 때문에 쓰지 않는 항목을 켜 두지 않는다.
    기준 회차의 조직 오류는 그 축의 마지막 조직 판정이므로 이 신호에 이미 든다."""
    if credential.account_ref is None:
        return "organization-unverified"
    if not _verified_and_allowed(credential, allowed):
        return "account-not-allowed"
    current = [check for check in checks if check.secret_fingerprint == credential.secret_fingerprint]
    if not current:
        return "check-required"
    run = max(check.run for check in current)
    basis = [check for check in current if check.run == run]
    if any(check.state_version != credential.state_version for check in basis):
        return "check-required"
    if not any(check.passed for check in basis):
        return "check-required"
    if organization_signal(credential, checks):
        return "organization-mismatch"
    return None


def uncovered_axes(
    credentials: Sequence[LlmCredential],
    checks: Mapping[uuid.UUID, Sequence[LlmCredentialCheck]],
    model_ids: Mapping[ClaudeModelAxis, str],
    allowed: frozenset[tuple[AccountProvider, str]],
) -> list[ClaudeModelAxis]:
    """덮는 항목이 없는 축(축 순서). `checks` 는 항목 id → 그 항목의 확인 기록 전부다. 덮는 항목은 켜져 있고, 조직이 확인돼 지금
    허용 목록 안이고, 그 축의 최신 확인이 통과했고 그 확인이 지금 키 지문과 지금 설정의 id 로 한 것이고, 런타임도 그 축을
    받는다(`passed_axes`) — 두 조건의 교집합이다. id 일치는 목록 사용 켜기에만 거는 조건이다 — 모델 id 설정을 바꾼 뒤 항목마다
    새 id 로 다시 확인하게 강제한다. 최신 확인이 일시 오류면 그 축을 덮지 않는다 — 목록 사용 켜기도 켜기(`enable_blocker`)처럼
    새로 쓰기 시작하는 결정이라 확정 통과를 요구한다. 런타임 축과 교집합을 두는 것은 최신 확인이 통과여도 런타임이 조직 신호로
    그 항목을 쓰지 않으면 그 축은 실제로 덮이지 않기 때문이다."""
    covered: set[ClaudeModelAxis] = set()
    for credential in credentials:
        if credential.state != "active" or not _verified_and_allowed(credential, allowed):
            continue
        rows = checks.get(credential.id, ())
        runtime = passed_axes(credential, rows)
        for axis, check in latest_checks_per_axis(rows).items():
            if (
                axis in runtime
                and check.passed
                and check.secret_fingerprint == credential.secret_fingerprint
                and check.sent_model_id == model_ids.get(axis)
            ):
                covered.add(axis)
    return [axis for axis in CLAUDE_AXES if axis not in covered]


def conclusive_checks_per_axis(
    fingerprint: str, checks: Iterable[LlmCredentialCheck]
) -> dict[ClaudeModelAxis, LlmCredentialCheck]:
    """축마다 그 키 지문으로 한 기록 가운데 일시 오류(`TRANSIENT_CHECK_ERROR`)를 뺀 회차가 가장 큰 것 — 런타임이 그 축에 쓰는
    결론이다. 지문을 먼저 거르므로 키를 바꾼 뒤 그 아래의 옛 키 기록으로 내려가지 않고, 예전에 쓰던 키로 되돌리면 그 키로 한
    예전 결론을 다시 쓴다(확인 기록은 지문으로 그때의 키에 묶인다). 그런 기록이 없는 축은 빠진다."""
    return latest_checks_per_axis(
        check for check in checks if check.secret_fingerprint == fingerprint and check.error_kind != TRANSIENT_CHECK_ERROR
    )


def organization_signal(credential: LlmCredential, checks: Iterable[LlmCredentialCheck]) -> bool:
    """지금 키로 한 확인에 풀리지 않은 조직 불일치가 있는가. 축마다 그 축의 마지막 조직 판정 — 지금 키 지문으로 한 기록 가운데
    응답 조직을 대조한 것, 곧 조직 헤더가 실린 통과(헤더가 저장된 조직과 같았다)나 조직 오류(불일치·허용 밖) 중 회차가 가장 큰
    것 — 을 보고, 어느 축이든 그것이 조직 오류면 참이다. 그래서 신호는 어긋난 그 축이 응답 조직이 맞는 통과를 다시 받아야만
    풀린다: 헤더 없는 통과(200 이지만 조직 헤더가 없다)와 일시 오류는 조직에 대해 아무 말도 하지 않았고, 모델 없음·권한·크레딧
    같은 조직과 무관한 확정 실패는 응답 조직을 대조하지 않은 결과라 풀지 않는다. 다른 축의 통과도 풀지 않는다. 지금 키의 가장
    최근 회차에 조직 오류가 있으면 그 축의 마지막 판정이 그 오류라 참이다(이전 규칙이 그대로 든다)."""
    verdicts = latest_checks_per_axis(
        check
        for check in checks
        if check.secret_fingerprint == credential.secret_fingerprint
        and ((check.passed and check.organization_header is not None) or check.error_kind in _ORGANIZATION_ERRORS)
    )
    return any(check.error_kind in _ORGANIZATION_ERRORS for check in verdicts.values())


def passed_axes(credential: LlmCredential, checks: Sequence[LlmCredentialCheck]) -> frozenset[ClaudeModelAxis]:
    """런타임에 그 항목이 받을 수 있는 축(`checks` 는 그 항목의 확인 기록 전부): 축마다 지금 키로 한 결론 난 최신 기록
    (`conclusive_checks_per_axis` — 일시 오류 기록을 건너뛴다)이 통과한 축이다. 켜진 항목을 확인하다 Anthropic 이 잠깐
    429·과부하·시간 초과를 내도 그 축의 이전 통과가 남아 항목이 후보에서 빠지지 않는다 — 런타임이 소진이 아닌 429·529·5xx·
    시간 초과에서 다음 항목으로 넘기지 않는 것과 같은 뜻이고, 그렇지 않으면 확인 한 번에 항목이 빠져 다음 항목이 없을 때 모든
    호출이 실패한다. 크레딧·키·조직·모델 접근 같은 확정 실패는 이전 통과를 덮는다. 켜기·목록 사용 켜기는 이렇게 건너뛰지 않는다
    (`enable_blocker` 의 이유).

    풀리지 않은 조직 불일치(`organization_signal`)가 있으면 빈 집합이다 — 켜기를 막는 것과 같은 보안 신호이고, 켜진 뒤의 확인에서
    나와도 그 키로 요청을 보내지 않게 한다. 어긋난 축이 응답 조직이 맞는 통과를 다시 받아야 풀리므로, 그 축의 일시 오류나 조직과 무관한 실패 뒤에 위의
    건너뛰기가 어긋난 회차의 다른 축 통과로 내려가 그 키로 요청을 보내는 일이 없다.

    상태·허용 목록은 부르는 쪽이 본다. 모델 id 와 확인 때의 상태 판은 보지 않는다 — 축 단위 확인이라 id 설정을 바꿔도 남고,
    켜기가 판을 올리므로 판을 보면 켠 순간 모든 확인이 무효가 된다."""
    if organization_signal(credential, checks):
        return frozenset()
    concluded = conclusive_checks_per_axis(credential.secret_fingerprint, checks)
    return frozenset(axis for axis, check in concluded.items() if check.passed)


def same_as_env_key(credential: LlmCredential) -> bool:
    """그 항목의 키가 지금 env 롤백 키(`ANTHROPIC_DIRECT_API_KEY`)와 같은가. 저장하지 않고 볼 때마다 계산한다 — env 키를
    바꾸면 답이 바뀌어야 한다. env 키의 지문은 이 비교에만 쓰고 어디에도 남기지 않는다."""
    return is_env_key(credential.provider, credential.secret_fingerprint)


def is_env_key(provider: str, fingerprint: str) -> bool:
    """`same_as_env_key` 의 규칙을 행 없이 그 두 칸으로 본다(런타임은 행이 아니라 캐시한 스냅숏 항목을 든다)."""
    env_key = settings.anthropic_direct_api_key.strip()
    return provider == "anthropic" and bool(env_key) and secret_fingerprint(env_key) == fingerprint

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

