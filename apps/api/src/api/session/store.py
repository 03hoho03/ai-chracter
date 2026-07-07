import json
import uuid
from typing import Any

from api.core.config import settings
from api.core.redis import redis_client


def _session_key(session_id: str) -> str:
    return f"session:{session_id}"


async def create_session(data: dict[str, Any]) -> str:
    """Store `data` under a new random session id and return that id."""
    session_id = uuid.uuid4().hex
    await redis_client.set(_session_key(session_id), json.dumps(data), ex=settings.session_ttl_seconds)
    return session_id


async def get_session(session_id: str) -> dict[str, Any] | None:
    raw = await redis_client.get(_session_key(session_id))
    if raw is None:
        return None
    data: dict[str, Any] = json.loads(raw)
    return data


async def delete_session(session_id: str) -> None:
    await redis_client.delete(_session_key(session_id))
