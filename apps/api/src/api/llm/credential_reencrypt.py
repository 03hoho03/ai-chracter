"""Claude 자격 암호화 키를 바꾼 뒤 옛 키로 만든 행을 지금 키로 다시 암호화한다 — `python -m api.llm.credential_reencrypt`.

키를 바꾸는 순서는 크리에이터 지급 정보 키와 같다: 새 키를 `LLM_CREDENTIAL_ENCRYPTION_KEYS` 맨 앞에 붙이고 옛 키를 뒤에
남겨 재기동 → 이 모듈 실행 → 백업 보관 기간이 지난 뒤 옛 키 삭제(옛 백업의 암호문은 옛 키로만 읽힌다). 서빙 중인 API
컨테이너 안에서 돈다(설정과 키를 같은 곳에서 읽는다). 이 실행기가 없으면 키링 회전은 모든 항목의 키를 콘솔에서 다시 발급해
붙여넣는 일이 된다.

값은 그대로이고 암호문과 키 id 만 바뀐다(지문·끝 4자리도 그대로). 행마다 따로 커밋해 도중에 멈춰도 다시 돌리면 남은 행만
한다. 복호화할 수 없는 행(그 키를 이미 잃음)은 건너뛰고 수만 센다 — 그 항목은 어드민에서 키를 다시 붙여넣어야 한다.

지급 정보 실행기(`creator_payout/reencrypt.py`)와 달리 실패해도 traceback 을 찍지 않고 오류 클래스 이름(행 쓰기 실패면
클래스 이름과 SQLSTATE)만 찍는다 — SQLAlchemy 문장 오류는 파라미터(암호문 바이트)를, 드라이버 오류의 DETAIL 은 위반한 행
전체를 싣는다. 그래서 행 쓰기도 어드민 라우터와 같은 `credential_write` 로 감싼다.
"""

import asyncio
import sys
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core.field_crypto import FieldDecryptError
from api.db.models.llm_credential import LlmCredential
from api.db.session import async_session_factory, engine
from api.llm.credentials import CredentialStoreError, credential_keyring, credential_write, reencrypt_secret


@dataclass(frozen=True)
class ReencryptResult:
    reencrypted: int
    unreadable: int


async def reencrypt_credentials(session_factory: async_sessionmaker[AsyncSession]) -> ReencryptResult:
    keyring = credential_keyring()
    async with session_factory() as db:
        credential_ids = (
            await db.scalars(select(LlmCredential.id).where(LlmCredential.key_id != keyring.current_key_id))
        ).all()
    reencrypted = unreadable = 0
    for credential_id in credential_ids:
        async with session_factory() as db, credential_write(db):
            credential = await db.scalar(
                select(LlmCredential).where(LlmCredential.id == credential_id).with_for_update()
            )
            if credential is None or credential.key_id == keyring.current_key_id:
                continue
            try:
                reencrypt_secret(keyring, credential)
            except FieldDecryptError:
                unreadable += 1
                continue
            await db.commit()
        reencrypted += 1
    return ReencryptResult(reencrypted=reencrypted, unreadable=unreadable)


async def run(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """다시 암호화하고 결과 한 줄을 찍는다. 종료 코드(건너뛴 행이 있거나 실패하면 1)를 돌려준다."""
    try:
        result = await reencrypt_credentials(session_factory)
    except CredentialStoreError as exc:
        print(f"Claude 자격 재암호화 실패: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # 예외 문장도 찍지 않는다 — 어떤 오류가 어떤 값을 싣는지 이 자리에서 가릴 수 없다.
        print(f"Claude 자격 재암호화 실패: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"Claude 자격 재암호화: {result.reencrypted}행, 복호화할 수 없어 건너뜀 {result.unreadable}행")
    return 1 if result.unreadable else 0


async def _main() -> int:
    try:
        return await run(async_session_factory)
    finally:
        await engine.dispose()


def main() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    sys.exit(main())
