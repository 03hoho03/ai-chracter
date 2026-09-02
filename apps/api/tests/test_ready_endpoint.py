"""`/ready` — 외부 업타임 모니터가 보는 엔드포인트.

`/health` 와 나눈 게 이 엔드포인트의 존재 이유다: `/health` 는 프로세스 생존만 보므로
**API 는 살아 있고 Postgres 가 죽은 상태에서 200 을 낸다.** 그 갭을 메우려고 만든 것이니
"자원이 죽으면 503 이 된다"가 깨지면 이 엔드포인트는 아무 일도 하지 않는 셈이 된다.
"""

from typing import Any

import pytest
from httpx import AsyncClient

from api import main


async def test_자원이_모두_살아있으면_200에_ready다(api_client: AsyncClient) -> None:
    response = await api_client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"database": "ok", "redis": "ok"}


async def test_health는_의존자원을_보지_않는다(api_client: AsyncClient) -> None:
    """`/health` 가 얕다는 것 자체가 계약이다 — Caddy 헬스체크와 배포 검증이 여기 의존한다."""
    response = await api_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("broken", "healthy"),
    [("database", "redis"), ("redis", "database")],
)
async def test_한_자원만_죽어도_503이다(
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
