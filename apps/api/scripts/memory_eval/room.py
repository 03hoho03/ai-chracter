"""평가 방 준비. 방은 측정 드라이버(`chat_play.py --content-id`)가 만들고(튜토리얼 작품의 첫 시작설정), 방 모델은 opus 로 바꾸며
(`PUT /chat-rooms/{id}/model` — 측정 서버는 상위 모델 스위치가 켜진 채 뜬다), 클로버는 앱의 지급 함수로 격리 작업 DB 에
넣는다. 얼리기 전에 넉넉히 넣어 두면 템플릿에서 복원한 프로브가 모두 같은 잔액으로 시작한다.

약관 동의도 여기서 맞춘다. 앱은 쓰기 라우트(방 만들기·턴·모델 바꾸기)를 재동의 게이트로 막고, 게이트는 시행된 최신 판보다 앞선
동의를 거부한다. 템플릿은 얼린 때의 동의 판을 그대로 담고 있으므로 그 뒤 새 판이 게시·시행되면 측정 계정이 403 으로 막힌다.
측정 작업 DB 는 격리 사본이라 서버 코드를 건드리지 않고 그 회원의 동의를 현행판으로 적는다(앱의 동의 기록 함수 그대로)."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clover
from api.db.models.auth import User
from api.legal import consents, documents
from api.legal.dependencies import reconsent_required_units


def set_room_model(base: str, cookie_value: str, room_id: uuid.UUID, model: str) -> dict[str, Any]:
    from api.core.config import settings

    with httpx.Client(base_url=base, timeout=30) as client:
        client.cookies.set(settings.session_cookie_name, cookie_value)
        response = client.put(f"/chat-rooms/{room_id}/model", json={"model": model})
    if response.status_code != 200:
        raise SystemExit(f"방 모델 바꾸기 실패 HTTP {response.status_code}: {response.text[:200]}")
    body: dict[str, Any] = response.json()
    if body.get("effectiveChatModel") != model:
        raise SystemExit(f"방 모델이 {model} 이 아니다: {body}")
    return body


async def grant_clover(db: AsyncSession, user_id: uuid.UUID, amount: int) -> None:
    await clover.grant(
        db, user_id=user_id, amount=amount, kind="admin_grant", idempotency_key=f"memory-eval:{uuid.uuid4()}"
    )
    await db.commit()


async def ensure_current_consent(db: AsyncSession, user_ids: Sequence[uuid.UUID] | None = None) -> dict[str, list[str]]:
    """재동의가 필요한 회원(`user_ids` 를 주면 그 회원만, 아니면 탈퇴하지 않은 전원)의 동의를 현행판으로 적는다. 돌려주는 값은
    회원 id → 적은 동의 단위(이미 최신이면 빠진다). 커밋은 부른 쪽이 한다 — 측정 작업 DB 에서만 부른다."""
    now = documents.utcnow()
    query = select(User).where(User.deleted_at.is_(None))
    if user_ids is not None:
        query = query.where(User.id.in_(list(user_ids)))
    updated: dict[str, list[str]] = {}
    for user in (await db.scalars(query)).all():
        units = await reconsent_required_units(db, user, now=now)
        if not units:
            continue
        consented = await consents.current_consent_documents(db, units, now=now)
        at = datetime.now(UTC)
        consents.apply_consent_versions(user, consented, at=at)
        consents.add_consent_history(db, user.id, consented, at=at)
        updated[str(user.id)] = list(units)
    await db.flush()
    return updated
