"""Viewer identity and 24h dedup for content view counting (tasks/prd-view-count.md).

Guest cookies follow the same policy family as session cookies (see
api/session/cookies.py) but are not sessions, so this module keeps its own
cookie helpers instead of reusing that one — the same split as admin/cookies.py
and chat/preview_session.py.
"""

import uuid

from fastapi import Request, Response
from redis.exceptions import RedisError

from api.core.config import settings
from api.core.redis import redis_client


def resolve_viewer_key(request: Request, response: Response, user_id: uuid.UUID | None) -> str:
    """Return a stable viewer key: `user:{id}` when logged in, else `guest:{uuid}`.

    The `user:`/`guest:` prefixes keep the two namespaces structurally disjoint.
    Guests without a (parseable) cookie get a fresh UUID baked into `response`
    and that new value is used for this request immediately — browsers that
    refuse cookies are accepted as a new viewer on every request.
    """
    if user_id is not None:
        return f"user:{user_id}"

    guest_id: uuid.UUID | None = None
    raw = request.cookies.get(settings.guest_viewer_cookie_name)
    if raw is not None:
        try:
            guest_id = uuid.UUID(raw)
        except ValueError:
            guest_id = None

    if guest_id is None:
        guest_id = uuid.uuid4()
        response.set_cookie(
            key=settings.guest_viewer_cookie_name,
            value=str(guest_id),
            max_age=settings.guest_viewer_cookie_max_age_seconds,
            httponly=True,
            secure=settings.session_cookie_secure,
            samesite=settings.session_cookie_samesite,
        )

    return f"guest:{guest_id}"


async def try_mark_viewed(content_id: uuid.UUID, viewer_key: str) -> bool:
    """Atomically mark (content, viewer) as viewed; True only on the first view in the TTL window.

    SET NX doubles as the dedup check. Redis failures are swallowed into False
    so a dead Redis never leaks an exception into the request path (FR-5).
    """
    try:
        was_set = await redis_client.set(
            f"view:{content_id}:{viewer_key}",
            "1",
            nx=True,
            ex=settings.content_view_dedup_ttl_seconds,
        )
    except RedisError:
        return False
    return bool(was_set)
