"""Claude 자격 목록 — 운영자가 어드민에서 붙여넣은 API 키를 순서대로 담는 자격(`llm_credentials`), 그 키로 모델 축마다
받아들여지는지 본 확인 기록(`llm_credential_checks`), 목록 사용 칸과 목록 판 번호를 담는 한 행 표(`llm_credential_settings`).

키 원문은 남지 않는다 — `LLM_CREDENTIAL_ENCRYPTION_KEYS` 의 키로 AES-256-GCM 암호화한 바이트(`secret_ciphertext`)와 화면
표시용 끝 4자리·지문만 남는다. 연관 데이터가 행 id 와 칸 이름이라(`llm/credentials.py`) 자격 행의 id 는 INSERT 전에 코드가
정한다.

상태·공급자·축·실패 종류는 Text + Literal 이다. 칼럼 값 Literal 을 여기 두는 이유는 감사 로그 종류(`db/models/moderation.py`
의 `AdminActionType`)와 같다 — 쓰는 쪽(`llm/credentials.py`·어드민 스키마)이 이 모듈을 import 하므로 거꾸로 두면 순환한다.
🔴 `alembic check` 는 CHECK 를 비교하지 않는다 — 이 파일의 CHECK 는 `pytest.raises(IntegrityError)` 행위 테스트가 유일한
검증이다.
"""

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
    Uuid,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base

# Bedrock 은 스키마만 지금 받는다(API 는 아직 거부한다) — 나중에 Bedrock 행이 생긴 뒤 이미지를 그 값을 모르는 판으로
# 되돌려도 조회 응답이 이 값을 이미 알아 응답 검증에서 500 이 되지 않고, Bedrock 을 여는 변경에 마이그레이션이 필요 없다.
CredentialProvider = Literal["anthropic", "bedrock"]
CredentialState = Literal["active", "exhausted", "disabled"]
# 소진(`exhausted`)의 이유는 크레딧·키 무효·사용 한도, 끔(`disabled`)의 이유는 운영자뿐이다.
CredentialStateReason = Literal["credit", "auth", "limit", "admin"]
# 확인 호출이 기록하는 모델 축. `llm/backends.py` 의 Anthropic 구현이 실제 id 설정을 두는 축과 같아야 한다(테스트가 본다).
# CHECK 를 두지 않는다 — 모델 라인업이 늘 때마다 CHECK 를 넓히는 마이그레이션이 생기지 않게.
ClaudeModelAxis = Literal["haiku_writer", "sonnet", "opus", "haiku"]
# 확인 기록의 실패 종류. 거절 분류(크레딧·키 무효·한도)와 그 밖의 호출 실패, 응답 조직 대조 실패다. CHECK 는 위와 같은
# 이유로 두지 않는다.
CheckErrorKind = Literal[
    "credit",
    "auth",
    "limit",
    "permission",
    "model-not-found",
    "rejected",
    "unavailable",
    "organization-mismatch",
    "account-not-allowed",
    "account-already-listed",
]


class LlmCredential(Base):
    """목록의 항목 하나 — 한 계정(조직)의 키 하나. 런타임은 `position` 순서로 쓸 수 있는 첫 항목을 고른다.

    `state_version` 은 상태가 바뀌는 UPDATE 마다 1 오른다. 켜기는 "확인을 시작할 때의 판 = 지금 판"인 확인만 세므로,
    끄기·소진 뒤에는 다시 확인해야 켤 수 있다(시각이 아니라 판으로 가른다 — 한 트랜잭션 안의 `now()` 는 같고, 호출 도중의
    상태 변화를 시각으로는 가를 수 없다). `account_ref` 가 NULL 이면 조직 미확인이라 켤 수 없다. 충전액은 마이크로달러
    정수다.
    """

    __tablename__ = "llm_credentials"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    provider: Mapped[CredentialProvider] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[CredentialState] = mapped_column(Text, nullable=False)
    state_reason: Mapped[CredentialStateReason | None] = mapped_column(Text, nullable=True)
    state_version: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    # 표시·감사용 기록이다. 어떤 판정에도 쓰지 않는다.
    state_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 허용 목록과 대조해 확인된 조직 id(소문자)·AWS 계정 id. NULL 은 조직 미확인이다.
    account_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_id: Mapped[str] = mapped_column(Text, nullable=False)
    secret_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    secret_last4: Mapped[str] = mapped_column(Text, nullable=False)
    # 비밀 원문 sha256 의 앞 8자. 확인 기록이 이 값으로 그때의 키에 묶인다.
    secret_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    # Bedrock 전용 평문.
    region: Mapped[str | None] = mapped_column(Text, nullable=True)
    credit_micro_usd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    credit_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    alert_pct: Mapped[int] = mapped_column(SmallInteger, server_default="20", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("provider IN ('anthropic', 'bedrock')", name="ck_llm_credentials_provider"),
        CheckConstraint("label <> ''", name="ck_llm_credentials_label"),
        CheckConstraint("position > 0", name="ck_llm_credentials_position"),
        CheckConstraint("state IN ('active', 'exhausted', 'disabled')", name="ck_llm_credentials_state"),
        CheckConstraint(
            "(state = 'active' AND state_reason IS NULL)"
            " OR (state = 'exhausted' AND state_reason IN ('credit', 'auth', 'limit'))"
            " OR (state = 'disabled' AND state_reason = 'admin')",
            name="ck_llm_credentials_state_reason",
        ),
        CheckConstraint("account_ref IS NULL OR account_ref <> ''", name="ck_llm_credentials_account_ref"),
        CheckConstraint("key_id <> ''", name="ck_llm_credentials_key_id"),
        CheckConstraint("char_length(secret_last4) = 4", name="ck_llm_credentials_secret_last4"),
        CheckConstraint("secret_fingerprint ~ '^[0-9a-f]{8}$'", name="ck_llm_credentials_secret_fingerprint"),
        CheckConstraint("(provider = 'bedrock') = (region IS NOT NULL)", name="ck_llm_credentials_region"),
        CheckConstraint("credit_micro_usd IS NULL OR credit_micro_usd > 0", name="ck_llm_credentials_credit"),
        CheckConstraint("(credit_micro_usd IS NULL) = (credit_since IS NULL)", name="ck_llm_credentials_credit_since"),
        CheckConstraint("alert_pct BETWEEN 1 AND 99", name="ck_llm_credentials_alert_pct"),
        # 즉시 검사 유일 인덱스. 순서 저장은 모두를 같은 양수만큼 민 뒤 최종값을 매겨(두 단계) 문장 도중에도 겹치지 않는다.
        Index("ix_llm_credentials_position", "position", unique=True),
        # 한 조직은 목록에 한 번. 미확인(NULL) 행끼리는 막지 않는다(PostgreSQL 기본 NULLS DISTINCT).
        Index("ix_llm_credentials_provider_account_ref", "provider", "account_ref", unique=True),
    )


class LlmCredentialCheck(Base):
    """확인 호출 한 번이 모델 축마다 남긴 결과 한 행. 한 번의 확인이 쓴 행들은 같은 회차(`run`)다.

    "축마다 최신"은 `run` 으로 고른다 — `checked_at` 은 기록용이라 판정에 쓰지 않는다(시계 순서가 커밋 순서를 보장하지
    않는다). `state_version`·`secret_fingerprint` 는 확인을 **시작할 때** 읽은 항목의 값이라, 호출 도중 상태나 키가 바뀌면
    그 회차는 켜기에 세지 않는다. 응답 조직 헤더는 비밀이 아니지만 저장소가 공개라 DB 에만 둔다.
    """

    __tablename__ = "llm_credential_checks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # 확인 기록은 항목의 부속 기록이다 — 항목을 지우면 함께 지운다.
    credential_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("llm_credentials.id", ondelete="CASCADE", name="fk_llm_credential_checks_credential_id"),
        nullable=False,
    )
    run: Mapped[int] = mapped_column(Integer, nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    model_axis: Mapped[ClaudeModelAxis] = mapped_column(Text, nullable=False)
    sent_model_id: Mapped[str] = mapped_column(Text, nullable=False)
    secret_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_kind: Mapped[CheckErrorKind | None] = mapped_column(Text, nullable=True)
    organization_header: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 문장 실행 시각(`chat_messages.created_at` 과 같다). 기록용이다.
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("run > 0", name="ck_llm_credential_checks_run"),
        CheckConstraint("sent_model_id <> ''", name="ck_llm_credential_checks_sent_model_id"),
        CheckConstraint("secret_fingerprint ~ '^[0-9a-f]{8}$'", name="ck_llm_credential_checks_secret_fingerprint"),
        CheckConstraint("passed = (error_kind IS NULL)", name="ck_llm_credential_checks_outcome"),
        # 한 회차에 축당 한 행. 항목의 최신 회차·축마다 최신 회차 조회도 이 인덱스를 탄다.
        Index("ix_llm_credential_checks_run_axis", "credential_id", "run", "model_axis", unique=True),
    )


class LlmCredentialSettings(Base):
    """목록 사용 칸과 목록 판 번호 — 마이그레이션이 심은 한 행(id 1)뿐이다.

    판 번호는 목록의 구성·순서가 바뀌는 추가·삭제·순서 저장에서만 오르고, 순서 저장은 화면이 본 판과 같을 때만 된다(한
    문장 조건부 UPDATE). 셋 다 이 행을 먼저 갱신하므로 이 행의 잠금이 그 변경들을 줄 세운다.
    """

    __tablename__ = "llm_credential_settings"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False, server_default="1")
    pool_enabled: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    list_revision: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_llm_credential_settings_singleton"),
        CheckConstraint("list_revision >= 0", name="ck_llm_credential_settings_list_revision"),
    )
