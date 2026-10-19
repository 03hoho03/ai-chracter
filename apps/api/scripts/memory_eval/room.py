"""평가 방 준비. 방은 측정 드라이버(`chat_play.py --content-id`)가 만들고(튜토리얼 작품의 첫 시작설정), 방 모델은 opus 로 바꾸며
(`PUT /chat-rooms/{id}/model` — 측정 서버는 상위 모델 스위치가 켜진 채 뜬다), 클로버는 앱의 지급 함수로 격리 작업 DB 에
넣는다. 얼리기 전에 넉넉히 넣어 두면 템플릿에서 복원한 프로브가 모두 같은 잔액으로 시작한다."""

import uuid
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clover


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
