from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.assets.router import router as assets_router
from api.auth.router import me_router, router as auth_router
from api.content.router import router as content_router
from api.core.config import settings
from api.moderation.router import router as moderation_router
from api.session.router import router as session_router

app = FastAPI(title="AI 캐릭터 챗 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(session_router)
app.include_router(assets_router)
app.include_router(auth_router)
app.include_router(me_router)
app.include_router(content_router)
app.include_router(moderation_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
