"""클로버 단위 — DB 에 남은 단위 전환 기록(`clover_unit_events`)을 읽는 곳.

둘을 한다. 기동 가드(`assert_clover_unit_matches`): 이 코드의 단위(`core/clover.py` 의 `CLOVER_UNIT_KRW`)와 DB 의 마지막 기록이
다르면 요청을 받기 전에 기동을 멈춘다. 내역의 옛 단위 표시(`is_legacy_unit`): 원장 행이 전환 전의 단위로 적혔는가.

표를 쓰는 쪽(전환 마이그레이션·되돌림 스크립트)은 여기 없다.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core import clover
from api.db.models.clover import CloverUnitEvent

UnitAction = Literal["convert", "revert"]


@dataclass(frozen=True)
class UnitEvent:
    action: UnitAction
    occurred_at: datetime


async def load_unit_events(db: AsyncSession) -> list[UnitEvent]:
    """전환·되돌림 기록 전부를 시각 순으로. 평생 몇 행이라(전환·되돌림·다시 전환) 요청마다 한 번 읽어 파이썬에서 판정한다."""
    rows = await db.execute(
        select(CloverUnitEvent.action, CloverUnitEvent.occurred_at).order_by(CloverUnitEvent.occurred_at)
    )
    return [UnitEvent(action=action, occurred_at=occurred_at) for action, occurred_at in rows.all()]


def is_legacy_unit(*, kind: str, created_at: datetime, events: Sequence[UnitEvent]) -> bool:
    """원장 행이 전환 전의 단위로 적혔는가 — 그 행이 적힌 시각(`created_at`) 이하의 마지막 기록이 전환이 아니면 참이다.

    두 예외: 전환한 적이 한 번도 없으면 모든 행이 하나뿐인 단위로 적혔으므로 거짓이다(전환 전 배포에서 모든 내역에 옛 단위
    표시가 붙지 않게). 전환·되돌림 행 자신은 자기 설명을 가지므로 늘 거짓이다. 경계는 포함이다 — 전환 행이 전환 기록의
    `occurred_at` 을 `created_at` 으로 받으므로 같은 시각의 행은 전환 뒤다. `events` 는 `load_unit_events` 의 시각 순서다.
    """
    if kind in clover.UNIT_CONVERSION_KINDS or not any(event.action == "convert" for event in events):
        return False
    state: UnitAction | None = None
    for event in events:
        if event.occurred_at > created_at:
            break
        state = event.action
    return state != "convert"


async def latest_unit_action(db: AsyncSession) -> UnitAction | None:
    """DB 의 마지막 단위 기록. 표가 없거나(이 표보다 옛 백업으로 복원한 DB) 행이 없으면 `None` 이다."""
    if (await db.scalar(text("SELECT to_regclass('clover_unit_events')"))) is None:
        return None
    action: UnitAction | None = await db.scalar(
        select(CloverUnitEvent.action).order_by(CloverUnitEvent.occurred_at.desc()).limit(1)
    )
    return action


def check_unit_matches(action: UnitAction | None, *, unit_krw: int) -> None:
    """옛 단위(3원) 코드는 마지막 기록이 전환이면, 새 단위(1원) 코드는 마지막 기록이 전환이 아니면 `RuntimeError`."""
    converted = action == "convert"
    if unit_krw == 3 and converted:
        raise RuntimeError(
            "DB 의 클로버 단위는 전환됐는데 이 코드는 전환 전 단위(1클로버 = 3원)다 — 기동을 멈춘다. 단위 전환을 아는 이미지로"
            " 올리거나, 전환을 되돌린 뒤 다시 띄운다."
        )
    if unit_krw != 3 and not converted:
        raise RuntimeError(
            f"이 코드는 1클로버 = {unit_krw}원 단위인데 DB 의 마지막 단위 기록이 전환이 아니다({action}) — 기동을 멈춘다."
        )


async def assert_clover_unit_matches(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """옛 단위 코드가 새 단위 잔액을 읽으면 환불이 세 배가 된다. 그래서 DB 에 남은 마지막 단위 전환 기록과 이 코드의 단위가
    다르면 요청을 받기 전에 기동을 멈춘다. 평상시 교체에서는 새 색만 기동에 실패하고 옛 색이 계속 서빙한다 — 겹침 없는 교체는
    그 자리에서 다시 만들므로 거부가 곧 서비스 중단이다.

    기동 때만 본다. 떠 있는 프로세스는 그 뒤에 기록이 바뀌어도 그대로 돈다(되돌림 스크립트가 커밋한 뒤 곧바로 이미지를 바꾸는
    이유)."""
    async with session_factory() as session:
        action = await latest_unit_action(session)
    check_unit_matches(action, unit_krw=clover.CLOVER_UNIT_KRW)
