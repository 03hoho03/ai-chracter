import json
import secrets
from typing import TypedDict
from uuid import UUID

from api.core.config import settings
from api.core.redis import redis_client


class PasswordResetToken(TypedDict):
    user_id: str


def _key(token: str) -> str:
    return f"password_reset:{token}"


async def store_reset_token(user_id: UUID) -> str:
    token = secrets.token_urlsafe(24)
    payload: PasswordResetToken = {"user_id": str(user_id)}
    await redis_client.set(_key(token), json.dumps(payload), ex=settings.password_reset_token_ttl_seconds)
    return token


async def get_reset_token(token: str) -> PasswordResetToken | None:
    raw = await redis_client.get(_key(token))
    if raw is None:
        return None
    data: PasswordResetToken = json.loads(raw)
    return data


async def delete_reset_token(token: str) -> None:
    await redis_client.delete(_key(token))
