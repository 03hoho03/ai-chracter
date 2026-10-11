"""평가 방 준비 — 방 만들기는 측정 드라이버(`chat_play.py --content-id`)로(작품 = 조감독, 시작설정 0), 방 모델을 opus 로
(`PUT /chat-rooms/{id}/model`, 서버는 상위 모델 스위치를 켜고 띄운다), 클로버 지급(격리 작업 DB 에 앱의 지급 함수로 —
체크포인트를 얼리기 전에 넉넉히 채워 두면 프로브마다 템플릿 복원으로 같은 잔액에서 시작한다)."""

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
