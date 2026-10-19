"""숨긴 소설의 파기 — 하루 한 번 도는 정리.

    # 운영: 서빙 중인 api 컨테이너 안에서 (ops/purge-hidden-novels.sh 가 매일 부른다)
    python -m api.novelize.hidden_purge

노벨로 팔린 소설을 작가가 지우거나 그 게시자가 탈퇴하면 소설을 지우지 않고 숨긴다(`novels.hidden_at`) — 산 사람이 계속
읽어야 해서다. 그 소장이 모두 끝나면(구매자가 모두 탈퇴했거나 모두 환급받음) 남겨 둘 까닭이 없으므로 이 정리가 진짜로
지운다. 구매자의 탈퇴·환급 경로는 남의 소설을 지우지 않는다 — 그 자리에서 지우면 구매자 탈퇴가 남의 소설 행을 잠그게 되어
잠금 순서를 새로 맞춰야 한다.

소설을 지우는 코드(`delete_novels`)를 소설 삭제·탈퇴와 함께 쓰려고 앱 코드로 두고 api 컨테이너 안에서 돈다(크리에이터 정산
월 확정과 같은 꼴). 숨긴 소설은 정책 스위치가 켜졌을 때만 생기지만 이 정리는 스위치와 무관하게 돈다 — 스위치를 끈 뒤에도
남은 숨긴 소설은 소장이 끝나면 지워져야 한다.

표준출력 마지막 줄이 요약이다. 실패하면 Bugsink 에 남기고 0 이 아닌 코드로 끝난다(다음 날 다시 돈다)."""

import asyncio
import sys
import traceback

import sentry_sdk
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.sentry import build_sentry_options, capture_dependency_failure
from api.db.models.novel import Novel, NovelPurchase
from api.db.session import async_session_factory, engine
from api.novel_public.purchases import lock_novel_parties
from api.novelize.deletion import delete_novels

# 숨긴 소설 중 아직 환급되지 않은 구매(탈퇴하지 않은 구매자)가 남지 않은 것 — 소장이 모두 끝났다.
_PURGEABLE = (
    Novel.hidden_at.is_not(None),
    ~exists().where(
        NovelPurchase.novel_id == Novel.id,
        NovelPurchase.refunded_at.is_(None),
        NovelPurchase.buyer_user_id.is_not(None),
    ),
)


async def purge_hidden_novels(db: AsyncSession) -> int:
    """미환급 구매자가 남지 않은 숨긴 소설을 모두 지우고 지운 소설 수를 돌려준다. 구매 행(소설·화를 FK 없이 가리키는
    사본)은 거래 기록이라 남긴다. 소설마다 게시자 행을 먼저 잠근다 — 소설을 지우는 다른 경로(소설 삭제·탈퇴)와 같은 첫
    잠금이라 함께 돌아도 줄을 선다. 잠근 뒤 같은 조건으로 다시 확인해, 기다리는 사이 게시자 탈퇴가 먼저 지운 소설은
    건너뛴다. 소설마다 커밋한다 — 한 소설의 잠금을 쥔 채 다음 소설을 기다리지 않는다."""
    candidates = (await db.scalars(select(Novel.id).where(*_PURGEABLE).order_by(Novel.id))).all()
    await db.commit()
    purged = 0
    for novel_id in candidates:
        await lock_novel_parties(db, novel_ids=[novel_id])
        still = await db.scalar(select(Novel.id).where(Novel.id == novel_id, *_PURGEABLE))
        if still is not None:
            await delete_novels(db, [novel_id])
            purged += 1
        await db.commit()
    return purged


def _init_sentry() -> None:
    # 서버(`main.py`)와 같은 옵션. DSN 이 없으면(dev) 부르지 않아 실패 기록이 no-op 이다.
    if settings.sentry_dsn:
        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.sentry_environment, **build_sentry_options())


async def _main() -> None:
    try:
        async with async_session_factory() as db:
            purged = await purge_hidden_novels(db)
    finally:
        await engine.dispose()
    print(f"숨긴 소설 파기: {purged}편")


def main() -> int:
    _init_sentry()
    try:
        asyncio.run(_main())
    except Exception as exc:
        capture_dependency_failure(exc, dependency="hidden_novel_purge")
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
