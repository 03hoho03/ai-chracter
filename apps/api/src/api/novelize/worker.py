"""소설화 워커 — api 와 따로 뜬 프로세스가 대기 중인 소설화 작업을 집어 돌린다.

    # 운영: api 와 같은 이미지·env 로 뜬 워커 컨테이너의 명령
    python -m api.novelize.worker

api 프로세스 안에서 돌던 작업은 api 교체(blue/green) 때 프로세스째 끝나 결과를 버리고 만료 환불로 넘어간다. 워커를 켜면
(`novelize_worker_enabled`) api 는 작업 행만 남기고, 이 프로세스가 그 행을 집는다. 워커는 SIGTERM 을 받으면 새 작업을 집지
않고 돌던 작업을 끝까지 마친 뒤 끝나므로, 교체가 정지 유예를 넉넉히 주면 돌던 작업이 죽지 않는다.

**고르기**: 대기 중이고 연쇄 자식이 아니며 이 코드가 처리할 줄 아는 종류(`WORKER_JOB_KINDS`)인 행을 오래된 순으로 빈 칸
수만큼 고른 뒤 api 와 같은 `run_job` 으로 돌린다. 받기는 `run_job` 안의 조건부 전이(대기 → 실행)라, 교체 구간에 워커 둘이
같은 행을 골라도 한쪽만 돈다. 연쇄 자식은 부모가 직접 돌리고, 연쇄 부모는 api 안에서 돈다 — 둘 다 집지 않는다.

**종류는 아는 목록으로만 고른다**("연쇄 부모가 아닌 것"이 아니라). 교체 동안 새 api 가 만든 작업을 옛 워커가 집는데, 옛
워커가 모르는 새 종류를 집으면, 아래 갈래 판정이 들어간 워커부터는 실행 경로가 그 종류를 판정하지 못해 내부 오류로 환불한다.
아는 목록이면 모르는 종류는 새 워커가 뜰 때까지 대기로 남아 새 워커에게 넘어간다. 갈래 판정(`job_variants.variant_of`)이
종류 전부를 덮는지 타입 검사가 보고 실행이 갈래 표로만 가므로, 종류를 더하고 실행 갈래를 빠뜨린 변경은 타입 검사에서 막힌다
— 그래서 목록은 갈래 표의 워커 칸에서 끌어낸다.
이 목록이 "작업 종류 전체 − 연쇄 부모"와 같은지는 테스트가 리터럴로 고정한다. 장 생성은 워커가 도는 갈래(혼자 도는 생성)와 안
도는 갈래(연쇄 자식)로 갈려 종류 목록만으로는 거를 수 없어, 고르기 조회가 연쇄 부모 칸 조건을 따로 건다.

이 목록이 못 막는 것은 **이미 있는 종류에 실행 갈래를 가르는 칸을 더하는 변경**이다 — 옛 워커가 그 칸을 모른 채 옛 갈래로
저장한다. 그 칸을 채우는 라우트는 워커 쪽 처리가 배포된 다음에 켜거나, 스위치를 끄는 교체로 워커를 비운 뒤 켠다.

**만료 정리**: 폴링 루프가 heartbeat 만료 + 10초 뒤 처음, 그 뒤 60초마다 모든 소설의 만료 작업을 실패·환불한다. api 의 기동
뒤 정리는 기동마다 한 번이라, 옛 프로세스가 그 뒤에 죽인 작업(유예를 넘겨 잘린 옛 워커의 작업, api 교체로 죽은 연쇄)은
사용자가 그 소설로 돌아올 때까지 남는다. 주기 정리가 그것을 사용자 행동과 무관하게 거둔다. 정리 경로는 모두 같은 환불
함수라 겹쳐도 한 번만 환불한다. 정지 신호 뒤에는 돌리지 않는다(새 워커가 돈다).

**살아 있음 파일**: 고르기 조회가 성공한 바퀴마다(정지 뒤 비우는 동안은 기다릴 때마다) `ALIVE_FILE` 을 만진다. 컨테이너
헬스체크가 이 파일의 수정 시각을 본다 — DB 가 계속 안 되면 만지지 않아 unhealthy 가 된다."""

import asyncio
import logging
import signal
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import sentry_sdk
from sqlalchemy import select

from api.core.config import settings
from api.core.sentry import build_sentry_options, capture_dependency_failure
from api.db.models.novel import NovelJob, NovelJobKind
from api.clover.unit import assert_clover_unit_matches
from api.db.session import async_session_factory, engine
from api.llm.client import LLMClient
from api.llm.dependencies import get_llm_client
from api.novelize.job_variants import kinds_where
from api.novelize.runner import _STARTUP_EXPIRY_MARGIN_SECONDS, SessionFactory, expire_all_stale_jobs, run_job

logger = logging.getLogger(__name__)

# 이 코드가 처리할 줄 아는 작업 종류 — 갈래 표에서 워커가 도는 갈래의 종류. 옛 워커가 이 목록에 없는 종류를 집으면 갈래 판정이
# 들어간 워커부터는 실행 경로가 판정하지 못해 내부 오류로 환불하므로, 목록이 그 행을 대기로 남겨 새 워커에게 넘긴다. 고르기가
# 부를 때 이 이름을 읽는다.
WORKER_JOB_KINDS: tuple[NovelJobKind, ...] = kinds_where(worker_runs=True)

# 컨테이너는 비루트 사용자로 돌아 /tmp 에만 쓸 수 있다. 헬스체크가 같은 경로를 본다.
ALIVE_FILE = Path("/tmp/novelize-worker.alive")

# 주기 만료 정리 간격(초). 정리 기준(heartbeat 만료)은 api 의 지연 정리와 같아 자주 돌려도 살아 있는 작업을 죽이지 않는다.
SWEEP_INTERVAL_SECONDS = 60


async def claim_candidates(session_factory: SessionFactory, limit: int) -> list[uuid.UUID]:
    """집을 수 있는 대기 작업 id 를 오래된 순으로 `limit` 개까지. 대기 행의 heartbeat 는 만든 시각 그대로라 먼저 들어온
    행이 먼저 만료에 닿는다. 잠그지 않는다 — 받기는 `run_job` 의 조건부 전이가 한다."""
    async with session_factory() as db:
        rows = await db.scalars(
            select(NovelJob.id)
            .where(
                NovelJob.status == "queued",
                NovelJob.parent_job_id.is_(None),
                NovelJob.kind.in_(WORKER_JOB_KINDS),
            )
            .order_by(NovelJob.created_at, NovelJob.id)
            .limit(limit)
        )
        return list(rows.all())


async def run_worker(
    session_factory: SessionFactory,
    llm_client: LLMClient,
    stop: asyncio.Event,
    *,
    alive_file: Path = ALIVE_FILE,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """`stop` 이 설 때까지 대기 작업을 집어 돌리고, 선 뒤에는 돌던 작업이 모두 끝나기를 기다렸다가 돌아온다(취소하지
    않는다). 이 코루틴 자체가 취소되면(정지 유예를 넘긴 강제 종료와 같은 결과) 돌던 작업도 취소한다 — 실행 중으로 남은
    행은 heartbeat 가 멈춰 만료 정리가 환불한다."""
    cap = settings.novelize_worker_max_concurrent_jobs
    poll_interval = settings.novelize_worker_poll_interval_seconds
    active: set[asyncio.Task[None]] = set()
    next_sweep = clock() + settings.novelize_heartbeat_expiry_seconds + _STARTUP_EXPIRY_MARGIN_SECONDS
    try:
        while not stop.is_set():
            if clock() >= next_sweep:
                await _sweep(session_factory)
                next_sweep = clock() + SWEEP_INTERVAL_SECONDS
            active = {task for task in active if not task.done()}
            if await _poll(session_factory, llm_client, active, cap - len(active)):
                _mark_alive(alive_file)
            try:
                await asyncio.wait_for(stop.wait(), timeout=poll_interval)
            except TimeoutError:
                pass
        while active:
            _, active = await asyncio.wait(active, timeout=poll_interval)
            _mark_alive(alive_file)
    except asyncio.CancelledError:
        for task in active:
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)
        raise


def _mark_alive(alive_file: Path) -> None:
    # 빈 파일의 수정 시각만 바꾸는 시스템 호출 하나라 이벤트 루프를 막을 만큼 걸리지 않는다.
    alive_file.touch()


async def _poll(
    session_factory: SessionFactory, llm_client: LLMClient, active: set[asyncio.Task[None]], free: int
) -> bool:
    """빈 칸만큼 집어 띄운다. 조회가 성공했으면 참이다(빈 칸이 없어 조회하지 않은 바퀴도 루프가 살아 있으므로 참). 조회
    실패(DB 가 잠깐 안 됨)는 남기고 거짓을 돌려 다음 바퀴로 간다."""
    if free <= 0:
        return True
    try:
        job_ids = await claim_candidates(session_factory, free)
    except Exception as exc:
        logger.warning("소설화 워커가 대기 작업을 찾지 못했다(다음 바퀴에 다시 본다): %s", type(exc).__name__)
        capture_dependency_failure(exc, dependency="novelize")
        return False
    for job_id in job_ids:
        active.add(asyncio.create_task(run_job(session_factory, llm_client, job_id)))
    return True


async def _sweep(session_factory: SessionFactory) -> None:
    try:
        expired = await expire_all_stale_jobs(session_factory)
    except Exception as exc:
        logger.warning("소설화 워커의 만료 정리에 실패했다(다음 주기에 다시 한다): %s", type(exc).__name__)
        capture_dependency_failure(exc, dependency="novelize")
        return
    if expired:
        logger.warning("소설화 워커의 만료 정리로 작업 %d 건을 환불했다", expired)


async def serve(session_factory: SessionFactory, llm_client: LLMClient, *, alive_file: Path = ALIVE_FILE) -> None:
    """SIGTERM·SIGINT 를 정지 신호로 받아 `run_worker` 를 돌린다. 컨테이너에서 이 프로세스는 PID 1 이라 처리기가 없는
    신호는 무시된다 — 처리기가 없으면 `docker stop` 은 유예를 다 기다린 뒤 SIGKILL 로 끝낸다."""
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    try:
        await run_worker(session_factory, llm_client, stop, alive_file=alive_file)
    finally:
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(signum)


def _init_sentry() -> None:
    # 서버(`main.py`)와 같은 옵션. DSN 이 없으면(dev) 부르지 않아 실패 기록이 no-op 이다.
    if settings.sentry_dsn:
        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.sentry_environment, **build_sentry_options())


async def _main() -> None:
    # 서버 lifespan 과 같은 클로버 단위 대조 — 교체 스크립트 밖에서 워커를 손으로 띄워도 단위가 다른 DB 에서는 일을 받지 않는다.
    await assert_clover_unit_matches(async_session_factory)
    # 모델 클라이언트를 일을 받기 전에 만든다 — 키가 없으면 여기서 실패해 기동부터 안 된다.
    llm_client = get_llm_client()
    logger.info(
        "소설화 워커 시작 — 동시 상한 %d, 폴링 %s초",
        settings.novelize_worker_max_concurrent_jobs,
        settings.novelize_worker_poll_interval_seconds,
    )
    try:
        await serve(async_session_factory, llm_client)
    finally:
        await engine.dispose()
    logger.info("소설화 워커 종료 — 돌던 작업을 모두 마쳤다")


def main() -> int:
    # uvicorn 이 없어 로그 처리기를 붙이는 쪽이 없다 — 붙여야 실행 경로의 경고가 컨테이너 로그로 나간다.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    _init_sentry()
    asyncio.run(_main())
    return 0


if __name__ == "__main__":
    sys.exit(main())
