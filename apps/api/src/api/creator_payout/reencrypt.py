"""지급 정보 암호화 키를 바꾼 뒤 옛 키로 만든 행을 지금 키로 다시 암호화한다 — `python -m api.creator_payout.reencrypt`.

키를 바꾸는 순서(DEPLOY.md 크리에이터 지급 정보 암호화 키 절): 새 키를 `CREATOR_PAYOUT_ENCRYPTION_KEYS` 맨 앞에 붙이고
옛 키를 뒤에 남겨 재기동 → 이 모듈 실행 → 백업 보관 기간이 지난 뒤 옛 키 삭제. 이 모듈은 서빙 중인 API 컨테이너 안에서
돈다(설정과 키를 같은 곳에서 읽는다).

지급 정보 행은 고치지 않는 것이 규칙인데, 이것이 유일한 예외다 — 값은 그대로이고 암호문과 키 id 만 바뀐다. 행마다 따로
커밋해 도중에 멈춰도 다시 돌리면 남은 행만 한다. 복호화할 수 없는 행(그 키를 이미 잃음)은 건너뛰고 수만 센다. 값은 어디에도
찍지 않는다.
"""

import asyncio
import sys
import traceback
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core.field_crypto import FieldDecryptError
from api.creator_payout.config import payout_keyring
from api.creator_payout.payout_info import reencrypt_profile
from api.db.models.creator_payout import CreatorPayoutProfile
from api.db.session import async_session_factory, engine


@dataclass(frozen=True)
class ReencryptResult:
    reencrypted: int
    unreadable: int


async def reencrypt_profiles(session_factory: async_sessionmaker[AsyncSession]) -> ReencryptResult:
    keyring = payout_keyring()
    async with session_factory() as db:
        profile_ids = (
            await db.scalars(
                select(CreatorPayoutProfile.id).where(CreatorPayoutProfile.key_id != keyring.current_key_id)
            )
        ).all()
    reencrypted = unreadable = 0
    for profile_id in profile_ids:
        async with session_factory() as db:
            profile = await db.scalar(
                select(CreatorPayoutProfile).where(CreatorPayoutProfile.id == profile_id).with_for_update()
            )
            if profile is None or profile.key_id == keyring.current_key_id:
                continue
            try:
                reencrypt_profile(keyring, profile)
            except FieldDecryptError:
                unreadable += 1
                continue
            await db.commit()
            reencrypted += 1
    return ReencryptResult(reencrypted=reencrypted, unreadable=unreadable)


async def _main() -> ReencryptResult:
    try:
        return await reencrypt_profiles(async_session_factory)
    finally:
        await engine.dispose()


def main() -> int:
    try:
        result = asyncio.run(_main())
    except Exception:
        # 운영자가 손으로 돌리는 명령이라 터미널에만 남긴다. 예외 문장에 평문 값은 없다(복호화 실패는 값 없는 예외다).
        traceback.print_exc()
        return 1
    print(f"지급 정보 재암호화: {result.reencrypted}행, 복호화할 수 없어 건너뜀 {result.unreadable}행")
    return 1 if result.unreadable else 0


if __name__ == "__main__":
    sys.exit(main())
