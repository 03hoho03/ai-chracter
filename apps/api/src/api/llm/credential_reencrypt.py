"""Claude 자격 암호화 키를 바꾼 뒤 옛 키로 만든 행을 지금 키로 다시 암호화한다 — `python -m api.llm.credential_reencrypt`.

키를 바꾸는 순서는 크리에이터 지급 정보 키와 같다: 새 키를 `LLM_CREDENTIAL_ENCRYPTION_KEYS` 맨 앞에 붙이고 옛 키를 뒤에
남겨 재기동 → 이 모듈 실행 → 백업 보관 기간이 지난 뒤 옛 키 삭제(옛 백업의 암호문은 옛 키로만 읽힌다). 서빙 중인 API
컨테이너 안에서 돈다(설정과 키를 같은 곳에서 읽는다). 이 실행기가 없으면 키링 회전은 모든 항목의 키를 콘솔에서 다시 발급해
붙여넣는 일이 된다.

값은 그대로이고 암호문과 키 id 만 바뀐다(지문·끝 4자리도 그대로). 행마다 따로 커밋해 도중에 멈춰도 다시 돌리면 남은 행만
한다. 한 행이라도 다시 썼으면 끝에 런타임의 목록 캐시 세대를 한 번 올린다. 그 무효화가 실패하면 따로 한 줄을 찍고 종료 코드
2 로 끝난다 — 캐시된 스냅숏이 있으면 다시 쓰기 전의 암호문(옛 키 id)을 든 채 캐시 수명(5분)까지 남는데, 그 사이 옛 키를 빼고
교체하면 새 프로세스가 그 항목들을 복호화하지 못해 건너뛴다(모든 항목이 옛 키였으면 보낼 항목이 없다). 그래서 그 5분 안에는 옛
키를 지우지 않는다(지우는 시점 자체는 회전 순서 그대로 백업 보관 기간 뒤다). 복호화할 수 없는 행(그 키를 이미 잃음)은 건너뛰고 수만 센다 — 그 항목은 어드민에서 키를 다시 붙여넣어야 한다.
행 쓰기가 DB 에서 실패한 행도 그 행만 실패로 세고 다음 행으로 간다 — 첫 실패에서 멈추면 뒤 행이 모두 옛 키에 남는데, 요약 줄만으로는
옛 키를 지워도 되는지 가릴 수 없게 된다.

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
from api.llm.credential_pool import invalidate_pool_snapshot
from api.llm.credentials import CredentialStoreError, credential_keyring, credential_write, reencrypt_secret


@dataclass(frozen=True)
class ReencryptResult:
    reencrypted: int
    failed: int
    unreadable: int


async def reencrypt_credentials(session_factory: async_sessionmaker[AsyncSession]) -> ReencryptResult:
    """옛 키의 행을 하나씩 다시 암호화한다. 쓰기에 실패한 행은 그 오류(클래스 이름·SQLSTATE) 한 줄을 찍고 센다."""
    keyring = credential_keyring()
    async with session_factory() as db:
        credential_ids = (
            await db.scalars(select(LlmCredential.id).where(LlmCredential.key_id != keyring.current_key_id))
        ).all()
    reencrypted = failed = unreadable = 0
    for credential_id in credential_ids:
        try:
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
        except CredentialStoreError as exc:
            print(f"Claude 자격 재암호화 실패: {exc}", file=sys.stderr)
            failed += 1
            continue
        reencrypted += 1
    return ReencryptResult(reencrypted=reencrypted, failed=failed, unreadable=unreadable)


async def run(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """다시 암호화하고 결과 한 줄을 찍는다. 종료 코드를 돌려준다 — 쓰기에 실패했거나 건너뛴 행이 있으면 1(옛 키를 지우지 않는다),
    그렇지 않은데 캐시 무효화가 실패했으면 2(5분 안에는 옛 키를 지우지 않는다), 둘 다 아니면 0. 무효화 실패 줄은 1 일 때도 찍힌다
    — 그때는 1 의 "지우지 않는다"가 앞선다."""
    try:
        result = await reencrypt_credentials(session_factory)
    except Exception as exc:
        # 예외 문장도 찍지 않는다 — 어떤 오류가 어떤 값을 싣는지 이 자리에서 가릴 수 없다.
        print(f"Claude 자격 재암호화 실패: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(
        f"Claude 자격 재암호화: {result.reencrypted}행, 쓰기 실패 {result.failed}행, "
        f"복호화할 수 없어 건너뜀 {result.unreadable}행"
    )
    invalidation_failed = False
    if result.reencrypted:
        try:
            await invalidate_pool_snapshot()
        except Exception as exc:
            # 옛 키가 키링에 있는 동안은 캐시에 남은 옛 암호문도 읽힌다. 옛 키를 지우는 순간부터 읽히지 않으므로, 캐시가 수명으로
            # 맞춰지기 전에는 지우지 말라고 따로 알린다(지우라는 지시가 아니라 금지다). 오류 문장은 Redis 주소를 실을 수 있어 클래스
            # 이름만 찍는다.
            print(
                f"Claude 자격 목록 캐시 무효화 실패({type(exc).__name__}) — 5분 안에는 옛 키를 지우지 않는다", file=sys.stderr
            )
            invalidation_failed = True
    if result.failed or result.unreadable:
        return 1
    return 2 if invalidation_failed else 0


async def _main() -> int:
    try:
        return await run(async_session_factory)
    finally:
        await engine.dispose()


def main() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    sys.exit(main())
