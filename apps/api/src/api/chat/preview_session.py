import uuid

from api.chat.schemas import PreviewSessionState
from api.core.config import settings
from api.core.redis import redis_client


def _preview_session_key(session_id: str) -> str:
    return f"preview-session:{session_id}"


async def create_preview_session(state: PreviewSessionState) -> str:
    """Store `state` under a new random session id and return that id. TTL is set on
    creation only for this story (US-088) — refreshing it on later activity is
    US-089's concern (`POST /preview-sessions/{id}/messages`)."""
    session_id = uuid.uuid4().hex
    await redis_client.set(
        _preview_session_key(session_id),
        state.model_dump_json(by_alias=True),
        ex=settings.preview_session_ttl_seconds,
    )
    return session_id


async def get_preview_session(session_id: str) -> PreviewSessionState | None:
    raw = await redis_client.get(_preview_session_key(session_id))
    if raw is None:
        return None
    return PreviewSessionState.model_validate_json(raw)


async def update_preview_session(session_id: str, state: PreviewSessionState) -> None:
    """Overwrite `state` under the same session id and refresh its TTL — the
    "마지막 활동 기준 24시간 TTL" behavior from techspec-builder-common.md §3 (US-089:
    called after every preview turn, unlike `create_preview_session`'s one-time TTL)."""
    await redis_client.set(
        _preview_session_key(session_id),
        state.model_dump_json(by_alias=True),
        ex=settings.preview_session_ttl_seconds,
    )
