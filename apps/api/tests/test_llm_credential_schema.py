"""Claude 자격 목록 표 셋의 CHECK 제약과 유일·FK 인덱스.

`alembic check` 는 CHECK 제약을 비교하지 않는다 — 이 표들의 CHECK 는 여기 행위 테스트가 유일한 검증이다. 지우지 말 것.
경우마다 경계 안쪽 값이 들어가는 것과 바깥 값이 **그 제약 이름으로** 거부되는 것을 함께 본다 — 거부만 보면 모든 값을 막는
제약도 통과하고, 수락만 보면 제약이 없어도 통과하고, 이름을 보지 않으면 다른 제약이 우연히 같은 값을 막아도 통과한다.
유일·FK 는 `alembic check` 가 비교하는 범주지만, 미확인 행 여럿을 허용하는 것과 삭제가 확인 기록을 함께 지우는 것은 동작의
뜻이라 고정해 둔다."""

import uuid
from typing import Any, Literal

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import LlmCredential, LlmCredentialCheck, LlmCredentialSettings

_Target = Literal["credential", "check", "settings"]


def _violated_constraint(error: IntegrityError) -> str | None:
    """asyncpg 가 알려 준, 행을 거부한 제약 이름."""
    name = getattr(error.orig.__cause__, "constraint_name", None) if error.orig is not None else None
    return name if isinstance(name, str) else None


async def _insert_credential(db_session: AsyncSession, **overrides: Any) -> uuid.UUID:
    """유효한 자격 한 행(위치는 지금 끝 다음)을 넣고 id 를 돌려준다. 덮어쓴 칸만 바뀐다."""
    next_position = await db_session.scalar(sa.select(sa.func.coalesce(sa.func.max(LlmCredential.position), 0) + 1))
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "provider": "anthropic",
        "label": "운영 계정",
        "position": next_position,
        "state": "disabled",
        "state_reason": "admin",
        "account_ref": None,
        "key_id": "k1",
        "secret_ciphertext": b"\x00" * 40,
        "secret_last4": "abcd",
        "secret_fingerprint": "0123abcd",
        "region": None,
        "credit_micro_usd": None,
        "credit_since": None,
    }
    values.update(overrides)
    async with db_session.begin_nested():
        await db_session.execute(sa.insert(LlmCredential).values(**values))
    credential_id: uuid.UUID = values["id"]
    return credential_id


async def _insert_check(db_session: AsyncSession, credential_id: uuid.UUID, **overrides: Any) -> None:
    """그 자격의 확인 기록 한 행(회차는 지금 끝 다음). 덮어쓴 칸만 바뀐다."""
    next_run = await db_session.scalar(
        sa.select(sa.func.coalesce(sa.func.max(LlmCredentialCheck.run), 0) + 1).where(
            LlmCredentialCheck.credential_id == credential_id
        )
    )
    values: dict[str, Any] = {
        "credential_id": credential_id,
        "run": next_run,
        "state_version": 0,
        "model_axis": "opus",
        "sent_model_id": "claude-opus-5-5",
        "secret_fingerprint": "0123abcd",
        "passed": True,
        "error_kind": None,
        "organization_header": None,
    }
    values.update(overrides)
    async with db_session.begin_nested():
        await db_session.execute(sa.insert(LlmCredentialCheck).values(**values))


async def _write(db_session: AsyncSession, target: _Target, overrides: dict[str, Any]) -> None:
    if target == "credential":
        await _insert_credential(db_session, **overrides)
    elif target == "check":
        await _insert_check(db_session, await _insert_credential(db_session), **overrides)
    else:
        async with db_session.begin_nested():
            await db_session.execute(
                sa.insert(LlmCredentialSettings).values(**{"id": 1, "list_revision": 0, **overrides})
            )


def _case(target: _Target, accepted: dict[str, Any], rejected: list[dict[str, Any]], constraint: str) -> Any:
    return pytest.param(target, accepted, rejected, constraint, id=constraint)


_FINGERPRINT = "0123abcd"

_CHECK_CASES = [
    _case(
        "credential",
        {"provider": "bedrock", "region": "us-east-1"},
        [{"provider": "gemini"}],
        "ck_llm_credentials_provider",
    ),
    _case("credential", {"label": "a"}, [{"label": ""}], "ck_llm_credentials_label"),
    _case("credential", {"position": 1}, [{"position": 0}], "ck_llm_credentials_position"),
    _case(
        "credential",
        {"state": "exhausted", "state_reason": "credit"},
        [{"state": "paused", "state_reason": None}],
        "ck_llm_credentials_state",
    ),
    _case(
        "credential",
        {"state": "exhausted", "state_reason": "limit"},
        [{"state": "active", "state_reason": "admin"}, {"state": "exhausted", "state_reason": "admin"}],
        "ck_llm_credentials_state_reason",
    ),
    _case("credential", {"account_ref": None}, [{"account_ref": ""}], "ck_llm_credentials_account_ref"),
    _case("credential", {"key_id": "k1"}, [{"key_id": ""}], "ck_llm_credentials_key_id"),
    _case("credential", {"secret_last4": "abcd"}, [{"secret_last4": "abc"}], "ck_llm_credentials_secret_last4"),
    _case(
        "credential",
        {"secret_fingerprint": _FINGERPRINT},
        [{"secret_fingerprint": _FINGERPRINT.upper()}],
        "ck_llm_credentials_secret_fingerprint",
    ),
    _case(
        "credential",
        {"provider": "anthropic", "region": None},
        [{"provider": "anthropic", "region": "us-east-1"}],
        "ck_llm_credentials_region",
    ),
    _case(
        "credential",
        {"credit_micro_usd": 1, "credit_since": sa.func.now()},
        [{"credit_micro_usd": 0, "credit_since": sa.func.now()}],
        "ck_llm_credentials_credit",
    ),
    _case(
        "credential",
        {"credit_micro_usd": None, "credit_since": None},
        [{"credit_micro_usd": 50_000_000, "credit_since": None}],
        "ck_llm_credentials_credit_since",
    ),
    _case("credential", {"alert_pct": 99}, [{"alert_pct": 100}], "ck_llm_credentials_alert_pct"),
    _case("check", {"run": 1}, [{"run": 0}], "ck_llm_credential_checks_run"),
    _case("check", {"sent_model_id": "m"}, [{"sent_model_id": ""}], "ck_llm_credential_checks_sent_model_id"),
    _case(
        "check",
        {"secret_fingerprint": _FINGERPRINT},
        [{"secret_fingerprint": _FINGERPRINT[:7]}],
        "ck_llm_credential_checks_secret_fingerprint",
    ),
    _case(
        "check",
        {"passed": False, "error_kind": "credit"},
        [{"passed": True, "error_kind": "credit"}],
        "ck_llm_credential_checks_outcome",
    ),
    _case("settings", {"id": 1}, [{"id": 2}], "ck_llm_credential_settings_singleton"),
    _case("settings", {"list_revision": 0}, [{"list_revision": -1}], "ck_llm_credential_settings_list_revision"),
]


@pytest.mark.parametrize(("target", "accepted", "rejected", "constraint"), _CHECK_CASES)
async def test_each_check_constraint_accepts_its_boundary_and_rejects_the_next(
    db_session: AsyncSession,
    target: _Target,
    accepted: dict[str, Any],
    rejected: list[dict[str, Any]],
    constraint: str,
) -> None:
    if target == "settings":
        # 한 행 표는 심은 행이 이미 id 1 을 쥐고 있다 — 이 테스트의 트랜잭션 안에서만 비우고 다시 넣어 본다.
        await db_session.execute(sa.delete(LlmCredentialSettings))

    await _write(db_session, target, accepted)
    for overrides in rejected:
        if target == "settings":
            await db_session.execute(sa.delete(LlmCredentialSettings))
        with pytest.raises(IntegrityError) as caught:
            await _write(db_session, target, overrides)
        assert _violated_constraint(caught.value) == constraint


async def test_position_is_unique(db_session: AsyncSession) -> None:
    """순서 저장의 두 단계 재배열이 이 유일 인덱스에 기대 겹침 없음을 지킨다 — 같은 자리 둘은 들어가지 않는다."""
    await _insert_credential(db_session, position=1)
    await _insert_credential(db_session, position=2)

    with pytest.raises(IntegrityError) as caught:
        await _insert_credential(db_session, position=1)
    assert _violated_constraint(caught.value) == "ix_llm_credentials_position"


async def test_one_account_per_provider_but_unverified_rows_may_repeat(db_session: AsyncSession) -> None:
    """한 조직은 목록에 한 번만 — 같은 조직 키 둘이 각자의 충전액으로 세어지면 잔액 추정이 두 배가 된다. 조직 미확인(NULL)
    행은 여럿이어도 된다(헤더 없이 저장한 항목끼리 막히면 두 번째 키를 넣을 수 없다)."""
    await _insert_credential(db_session, account_ref=None)
    await _insert_credential(db_session, account_ref=None)
    await _insert_credential(db_session, account_ref="org-a")
    await _insert_credential(db_session, provider="bedrock", region="us-east-1", account_ref="org-a")

    with pytest.raises(IntegrityError) as caught:
        await _insert_credential(db_session, account_ref="org-a")
    assert _violated_constraint(caught.value) == "ix_llm_credentials_provider_account_ref"


async def test_one_row_per_axis_in_a_check_run(db_session: AsyncSession) -> None:
    """한 회차는 축마다 한 행 — 같은 회차를 잡은 두 확인 중 뒤의 것이 여기서 막힌다. 다른 축·다른 회차는 막지 않는다."""
    credential_id = await _insert_credential(db_session)
    await _insert_check(db_session, credential_id, run=1, model_axis="opus")
    await _insert_check(db_session, credential_id, run=1, model_axis="sonnet")
    await _insert_check(db_session, credential_id, run=2, model_axis="opus")

    with pytest.raises(IntegrityError) as caught:
        await _insert_check(db_session, credential_id, run=1, model_axis="opus")
    assert _violated_constraint(caught.value) == "ix_llm_credential_checks_run_axis"


async def test_deleting_a_credential_deletes_its_checks(db_session: AsyncSession) -> None:
    """삭제는 하드 삭제다 — 확인 기록은 항목의 부속 기록이라 함께 사라지고 다른 항목의 기록은 남는다."""
    deleted = await _insert_credential(db_session)
    kept = await _insert_credential(db_session)
    await _insert_check(db_session, deleted)
    await _insert_check(db_session, deleted, model_axis="sonnet")
    await _insert_check(db_session, kept)

    await db_session.execute(sa.delete(LlmCredential).where(LlmCredential.id == deleted))

    remaining = (await db_session.scalars(sa.select(LlmCredentialCheck.credential_id))).all()
    assert remaining == [kept]


async def test_settings_row_is_seeded_once(db_session: AsyncSession) -> None:
    """목록 사용 칸과 목록 판 번호는 마이그레이션이 심은 한 행에 있다 — 꺼짐·판 0 으로 시작한다."""
    rows = (
        await db_session.execute(
            sa.select(LlmCredentialSettings.id, LlmCredentialSettings.pool_enabled, LlmCredentialSettings.list_revision)
        )
    ).all()

    assert [tuple(row) for row in rows] == [(1, False, 0)]
