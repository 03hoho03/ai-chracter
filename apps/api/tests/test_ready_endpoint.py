"""`/ready` — 외부 업타임 모니터가 보는 엔드포인트.

`/health` 와 나눈 게 이 엔드포인트의 존재 이유다: `/health` 는 프로세스 생존만 보므로
**API 는 살아 있고 Postgres 가 죽은 상태에서 200 을 낸다.** 그 갭을 메우려고 만든 것이니
"자원이 죽으면 503 이 된다"가 깨지면 이 엔드포인트는 아무 일도 하지 않는 셈이 된다.
"""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from api import main


@pytest.fixture
def drain_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """드레인 플래그 경로를 테스트 전용 임시 경로로 바꾼다 — 호스트의 `/tmp/draining`
    유무에 결과가 흔들리지 않게. 파일은 만들지 않은 채로 돌려준다."""
    path = tmp_path / "draining"
    monkeypatch.setattr(main, "_DRAIN_FLAG_PATH", path)
    return path


async def test_returns_200_ready_when_all_resources_are_alive(api_client: AsyncClient) -> None:
    response = await api_client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"database": "ok", "redis": "ok"}


async def test_head_ready_is_allowed(api_client: AsyncClient) -> None:
    """UptimeRobot 이 HEAD 로 찌르고 405 를 받으면 GET 으로 폴백한다 —
    체크당 왕복이 2 번이 되던 것을, HEAD 를 허용해 1 번으로 줄인다."""
    response = await api_client.head("/ready")

    assert response.status_code == 200


async def test_health_does_not_check_dependent_resources(api_client: AsyncClient, drain_flag: Path) -> None:
    """`/health` 가 얕다는 것 자체가 계약이다 — Caddy 헬스체크와 배포 검증이 여기 의존한다."""
    response = await api_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_returns_503_while_drain_flag_exists(api_client: AsyncClient, drain_flag: Path) -> None:
    """교체 배포가 옛 컨테이너에 플래그를 두면 프록시가 그 컨테이너를 먼저 빼야 한다 —
    HTTP 상태만 보는 헬스체커가 알아채도록 503 이어야 한다."""
    await asyncio.to_thread(drain_flag.touch)

    response = await api_client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "draining"}


async def test_health_returns_200_again_after_drain_flag_removed(api_client: AsyncClient, drain_flag: Path) -> None:
    """플래그는 매 요청마다 다시 본다 — 지우면 재시작 없이 다시 받아들여야 한다."""
    await asyncio.to_thread(drain_flag.touch)
    assert (await api_client.get("/health")).status_code == 503

    await asyncio.to_thread(drain_flag.unlink)
    response = await api_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_ignores_drain_flag(api_client: AsyncClient, drain_flag: Path) -> None:
    """외부 업타임 모니터는 `/ready` 를 본다 — 드레인 중 오경보가 나면 안 된다."""
    await asyncio.to_thread(drain_flag.touch)

    response = await api_client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


@pytest.mark.parametrize(
    ("broken", "healthy"),
    [("database", "redis"), ("redis", "database")],
)
async def test_returns_503_when_only_one_resource_is_dead(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, broken: str, healthy: str
) -> None:
    """모니터가 HTTP 상태만 봐도 알아채야 한다. 어느 쪽이 죽었는지는 본문으로 구분한다."""

    class Dead:
        """죽은 자원. `AsyncEngine.connect`는 읽기 전용 속성이라 메서드만 갈아끼울 수 없어,
        모듈 전역을 통째로 바꾼다(두 자원에 같은 방식이 쓰여 대칭도 유지된다)."""

        def __getattr__(self, _name: str) -> Any:
            def explode(*args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("자원이 죽은 상황")

            return explode

    monkeypatch.setattr(main, "engine" if broken == "database" else "redis_client", Dead())

    response = await api_client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["checks"][broken] == "error"
    assert body["checks"][healthy] == "ok"
