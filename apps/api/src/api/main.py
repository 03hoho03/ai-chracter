import asyncio

from fastapi import FastAPI, Response, status as status_module
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from api.admin.router import me_router as admin_me_router, router as admin_router
from api.assets.router import me_router as assets_me_router, router as assets_router
from api.auth.router import me_router, router as auth_router
from api.chat.router import characters_router, preview_router, router as chat_router, stories_router
from api.content.router import router as content_router
from api.core.config import settings
from api.core.redis import redis_client
from api.db.session import engine
from api.images.router import router as images_router
from api.moderation.router import router as moderation_router
from api.session.router import router as session_router

app = FastAPI(title="AI 캐릭터 챗 API")

# `/ready` 의 자원별 검사 상한. 모니터가 5분 간격이라 넉넉할 이유가 없고, 길면 죽은 자원이
# 실패가 아니라 타임아웃으로 보여 원인이 흐려진다.
_READY_CHECK_TIMEOUT_SECONDS = 3

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(session_router)
app.include_router(admin_router)
app.include_router(admin_me_router)
app.include_router(assets_router)
app.include_router(assets_me_router)
app.include_router(auth_router)
app.include_router(me_router)
app.include_router(content_router)
app.include_router(moderation_router)
app.include_router(chat_router)
app.include_router(stories_router)
app.include_router(characters_router)
app.include_router(preview_router)
app.include_router(images_router)


@app.get("/health")
def health() -> dict[str, str]:
    """프로세스가 살아 있는지만 본다 — 의존 자원을 건드리지 않는다.

    Caddy 헬스체크와 배포 검증(`.github/workflows/deploy-api.yml`)이 이 얕음에 의존한다:
    DB 가 잠깐 흔들린다고 배포가 실패하거나 리버스 프록시가 백엔드를 빼면 안 된다.
    "의존 자원까지 살아 있는가"는 `/ready` 가 답한다.
    """
    return {"status": "ok"}


@app.get("/ready")
async def ready(response: Response) -> dict[str, object]:
    """DB·Redis 까지 실제로 찔러 본다 — **외부 업타임 모니터가 보는 엔드포인트다.**

    `/health` 와 나눈 이유가 이것이다. `/health` 만 감시하면 **API 는 살아 있고 Postgres 가
    죽은 상태에서 200 이 나가 모니터가 조용하다**(그 갭을 GCE 이전 후 실제로 확인했다).
    UptimeRobot 의 keyword 감시로도 못 잡는다 — 응답 본문이 정상이기 때문이다.

    하나라도 실패하면 **503** 이라 HTTP 상태만 보는 모니터도 알아챈다. 어느 쪽이 죽었는지는
    본문에 담아 사람이 로그 없이도 구분하게 한다.

    각 검사에 타임아웃을 건다 — 죽은 자원은 보통 거부가 아니라 **응답 없음**으로 나타나고,
    그러면 모니터가 실패 대신 타임아웃을 보게 되어 원인이 흐려진다.
    """
    checks: dict[str, str] = {}

    try:
        async with asyncio.timeout(_READY_CHECK_TIMEOUT_SECONDS):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001 — 원인을 가리지 않는다. 어떤 실패든 "준비 안 됨"이다.
        checks["database"] = "error"

    try:
        async with asyncio.timeout(_READY_CHECK_TIMEOUT_SECONDS):
            await redis_client.ping()
        checks["redis"] = "ok"
    except Exception:  # noqa: BLE001
        checks["redis"] = "error"

    ready = all(status == "ok" for status in checks.values())
    if not ready:
        response.status_code = status_module.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready else "unavailable", "checks": checks}
