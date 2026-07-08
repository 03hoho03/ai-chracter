from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.assets.router import me_router as assets_me_router, router as assets_router
from api.auth.router import me_router, router as auth_router
from api.chat.router import characters_router, preview_router, router as chat_router, stories_router
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
app.include_router(assets_me_router)
app.include_router(auth_router)
app.include_router(me_router)
app.include_router(content_router)
app.include_router(moderation_router)
app.include_router(chat_router)
app.include_router(stories_router)
app.include_router(characters_router)
app.include_router(preview_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
