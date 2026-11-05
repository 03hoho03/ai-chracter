"""키링 회전 뒤 다시 암호화 실행기(`python -m api.llm.credential_reencrypt`).

실행기는 행마다 자기 세션을 연다. 여기서는 그 세션들을 테스트 커넥션 위의 SAVEPOINT 로 열어, 실행기의 커밋은 SAVEPOINT 만
확정하고 실패한 행은 그 행만 되돌아가게 한다 — 셋업과 단언은 같은 커넥션의 `db_session` 으로 본다."""

import base64
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core.config import settings
from api.core.field_crypto import FieldKeyring
from api.db.models.llm_credential import LlmCredential
from api.llm import credential_reencrypt
from api.llm.credentials import decrypt_secret, new_credential, reencrypt_secret, secret_fingerprint
from factories import FAKE_API_KEY, FAKE_CREDENTIAL_KEYRING, FAKE_ROTATED_KEYRING

_FIRST_KEY = FAKE_CREDENTIAL_KEYRING
# 회전 중 키링의 새 키(k2)만.
_ROTATED_KEY = FAKE_ROTATED_KEYRING.split(",", 1)[0]
_LOST_KEY = "k9:" + base64.urlsafe_b64encode(b"\x09" * 32).decode()


def _factory(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_session.bind, join_transaction_mode="create_savepoint", expire_on_commit=False)


async def _stored(db_session: AsyncSession, keys: str, label: str) -> LlmCredential:
    position = await db_session.scalar(sa.select(sa.func.coalesce(sa.func.max(LlmCredential.position), 0) + 1))
    assert position is not None
    credential = new_credential(
        FieldKeyring.parse(keys),
        provider="anthropic",
        label=label,
        secret=FAKE_API_KEY + label,
        account_ref=None,
        position=position,
        credit_micro_usd=None,
        alert_pct=20,
    )
    db_session.add(credential)
    await db_session.flush()
    return credential


async def _reload(db_session: AsyncSession, credential_id: uuid.UUID) -> LlmCredential:
    credential = await db_session.scalar(
        sa.select(LlmCredential).where(LlmCredential.id == credential_id).execution_options(populate_existing=True)
    )
    assert credential is not None
    return credential


@pytest.fixture(autouse=True)
def _rotated_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """새 키(k2)를 맨 앞에 붙이고 옛 키(k1)를 뒤에 남긴 회전 중 키링."""
    monkeypatch.setattr(settings, "llm_credential_encryption_keys", FAKE_ROTATED_KEYRING)


async def test_rows_under_an_old_key_are_reencrypted_with_the_current_key(
    db_session: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    """옛 키의 행은 지금 키로 다시 암호화되고 값·지문·끝 4자리는 그대로다. 이미 지금 키인 행은 건드리지 않는다. 다시
    암호화한 뒤에는 옛 키를 빼도 읽힌다."""
    old = await _stored(db_session, _FIRST_KEY, "old")
    current = await _stored(db_session, _ROTATED_KEY, "current")
    current_blob = current.secret_ciphertext

    code = await credential_reencrypt.run(_factory(db_session))

    assert code == 0
    assert capsys.readouterr().out.strip() == "Claude 자격 재암호화: 1행, 복호화할 수 없어 건너뜀 0행"
    reencrypted = await _reload(db_session, old.id)
    assert reencrypted.key_id == "k2"
    assert decrypt_secret(FieldKeyring.parse(_ROTATED_KEY), reencrypted) == FAKE_API_KEY + "old"
    assert (reencrypted.secret_fingerprint, reencrypted.secret_last4) == (
        secret_fingerprint(FAKE_API_KEY + "old"),
        "qold",
    )
    assert (await _reload(db_session, current.id)).secret_ciphertext == current_blob


async def test_unreadable_rows_are_counted_and_left_alone(
    db_session: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    """키링에 없는 키(이미 잃은 키)의 행은 건너뛰고 수만 센다 — 그 항목은 키를 다시 붙여넣어야 한다. 종료 코드는 1 이다."""
    lost = await _stored(db_session, _LOST_KEY, "lost")
    before = lost.secret_ciphertext

    code = await credential_reencrypt.run(_factory(db_session))

    assert code == 1
    assert capsys.readouterr().out.strip() == "Claude 자격 재암호화: 0행, 복호화할 수 없어 건너뜀 1행"
    unchanged = await _reload(db_session, lost.id)
    assert (unchanged.key_id, unchanged.secret_ciphertext) == ("k9", before)


async def test_reencrypt_failure_prints_only_the_exception_name(
    db_session: AsyncSession, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """행 쓰기가 DB 에서 실패하면(여기서는 CHECK 위반) 오류 클래스 이름과 SQLSTATE 만 찍는다. 드라이버 오류 문장은 위반한
    행 전체를 싣고(bytea 는 hex 로, 값마다 앞부분까지) SQLAlchemy 문장은 파라미터(암호문 바이트)를 싣는다 — 그대로 찍으면
    운영자 터미널과 그 로그에 암호문이 남는다."""
    credential = await _stored(db_session, _FIRST_KEY, "fail")
    written: list[bytes] = []
    real = reencrypt_secret

    def breaking(keyring: FieldKeyring, row: LlmCredential) -> None:
        real(keyring, row)
        written.append(row.secret_ciphertext)
        row.secret_last4 = "abc"

    monkeypatch.setattr("api.llm.credential_reencrypt.reencrypt_secret", breaking)

    code = await credential_reencrypt.run(_factory(db_session))

    assert code == 1
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "IntegrityError sqlstate=23514" in output
    for blob in (*written, credential.secret_ciphertext):
        assert blob[:31].hex() not in output
        assert blob[:31].hex().upper() not in output
    assert FAKE_API_KEY not in output
    assert (await _reload(db_session, credential.id)).key_id == "k1"
