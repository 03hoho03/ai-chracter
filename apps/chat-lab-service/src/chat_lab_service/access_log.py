"""접근 기록 — 요청 하나에 한 행, 90일 보관."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.types import Scope

from chat_lab_service.models import access_log
from chat_lab_service.schemas import AccessReason

logger = logging.getLogger(__name__)

RETENTION = timedelta(days=90)
PURGE_INTERVAL_SECONDS = 24 * 60 * 60

IdentityKind = Literal["none", "human", "service", "unknown"]


@dataclass
class AccessRecord:
    """요청 하나의 기록. 가장 바깥 미들웨어가 만들고, 안쪽(인증·라우트)이 신원·판·이유를 채운다.

    토큰·머리 값·본문·경로 원문은 칸이 없어 담을 자리가 없다.
    """

    at: datetime
    method: str
    route: str
    run_id: str | None = None
    identity_kind: IdentityKind = "none"
    identity: str | None = None
    sha256: str | None = None
    raw_served: bool = False
    status: int = 500
    reason: AccessReason | None = None
    client_ip: str | None = None


def record_of(scope: Scope) -> AccessRecord:
    record = scope.get("state", {}).get("access")
    if not isinstance(record, AccessRecord):
        raise RuntimeError("접근 기록 자리가 없다 — 가장 바깥 미들웨어를 거치지 않은 요청이다")
    return record


async def write_access_row(engine: AsyncEngine, record: AccessRecord) -> None:
    async with engine.begin() as conn:
        await conn.execute(insert(access_log).values(**asdict(record)))


async def purge_old_access_log(engine: AsyncEngine, now: datetime) -> int:
    """`now` 에서 90일보다 오래된 행을 지우고 지운 수를 돌려준다. 정확히 90일 된 행은 남긴다."""
    async with engine.begin() as conn:
        result = await conn.execute(delete(access_log).where(access_log.c.at < now - RETENTION))
    return result.rowcount


async def purge_logging_failure(engine: AsyncEngine, clock: Callable[[], datetime]) -> None:
    try:
        await purge_old_access_log(engine, clock())
    except Exception as error:
        # 오류 글에는 SQL 과 바인드 값이 실린다. 다음 주기에 다시 돈다.
        logger.error("90일 지난 접근 기록을 지우지 못했다: %s", type(error).__name__)


async def purge_daily(engine: AsyncEngine, clock: Callable[[], datetime]) -> None:
    """떠 있는 동안 하루에 한 번씩 지운다(기동 때의 한 번은 lifespan 이 먼저 돌린다). 요청 때 지우면 조용한 날에는 돌지 않는다."""
    while True:
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)
        await purge_logging_failure(engine, clock)
