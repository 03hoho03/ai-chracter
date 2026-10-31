"""본문·경로 검증에 걸린 채팅 턴 요청은 클로버를 깎지 않는다.

FastAPI 는 한 의존성을 풀 때 그 의존성의 하위 의존성을 먼저 부르고 자기 본문 인자는 그 뒤에 검증하며, 앞 의존성의 검증
오류가 뒤 의존성 호출을 막지도 않는다. 그래서 차감 게이트가 받는 본문 모델이 라우트의 본문 모델보다 느슨하면, 라우트 본문
검증에 걸릴 요청(NUL 문자·빈 문자열·본문 없음)도 게이트를 지나 차감이 커밋된 뒤 422 가 난다. 환불 가드는 라우트 본문
안이라 돌지 않으므로 422 와 함께 클로버만 사라진다.

이 파일은 턴 네 경로(전송·편집·재생성·빌더 미리보기) 각각에서 검증에 걸린 요청이 422 이고 잔액·원장·사용처 행이 그대로임을
본다. 하루 무료분 없이 클로버로 내는 Gemini 턴과 상위 모델 방 턴을 둘 다 본다.
"""

import uuid

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import User
from api.db.models.chat import ChatRoom
from api.db.models.clover import CloverLedger, CloverSpendUsage
from factories import (
    _clear_llm_override,
    _enable_chat_premium,
    _FakeLLMClient,
    _override_llm_client,
    _prepare_paid_turn,
)

_BALANCE = 1000
_NO_BODY = object()


async def _money(db: AsyncSession, user: User) -> tuple[int, int, int]:
    """(잔액, 그 회원의 원장 행 수, 사용처 행 수). 차감은 별도 트랜잭션이라 잔액은 다시 읽는다."""
    await db.refresh(user)
    ledger = await db.scalar(select(func.count()).select_from(CloverLedger).where(CloverLedger.user_id == user.id))
    usages = await db.scalar(select(func.count()).select_from(CloverSpendUsage))
    assert ledger is not None and usages is not None
    return user.clover_balance, ledger, usages


async def _call(client: httpx.AsyncClient, method: str, path: str, body: object) -> httpx.Response:
    # 키 없는 LLM 클라이언트는 게이트보다 앞에서 실패해 차감 여부를 가린다 — 가짜로 갈아 끼운다.
    _override_llm_client(_FakeLLMClient(tokens=["응", "답"]))
    try:
        if body is _NO_BODY:
            return await client.request(method, path)
        return await client.request(method, path, json=body)
    finally:
        _clear_llm_override()


@pytest.mark.parametrize(
    ("surface", "body"),
    [
        pytest.param("send", {"content": "안\x00녕"}, id="send-nul"),
        pytest.param("send", {"content": ""}, id="send-empty"),
        pytest.param("send", {}, id="send-no-content"),
        pytest.param("send", _NO_BODY, id="send-no-body"),
        pytest.param("send", {"content": "안녕", "shortcutId": "not-a-uuid"}, id="send-bad-shortcut"),
        pytest.param("edit", {"content": "고친\x00내용"}, id="edit-nul"),
        pytest.param("edit", {"content": ""}, id="edit-empty"),
        pytest.param("edit", _NO_BODY, id="edit-no-body"),
        pytest.param("regenerate", {"priceVersion": "not-a-number"}, id="regenerate-bad-version"),
        pytest.param("preview", {"content": "안\x00녕"}, id="preview-nul"),
        pytest.param("preview", {"content": ""}, id="preview-empty"),
        pytest.param("preview", _NO_BODY, id="preview-no-body"),
    ],
)
async def test_invalid_turn_request_is_422_and_spends_nothing(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    surface: str,
    body: object,
) -> None:
    """깨지는 시나리오: 게이트가 라우트보다 느슨한 본문 모델로 검증해 이 요청을 통과시키고 차감을 커밋한 뒤 라우트가 422 를
    내 환불 없이 클로버가 깎인다."""
    user, method, path, _ = await _prepare_paid_turn(db_client, db_session, surface=surface, balance=_BALANCE)
    before = await _money(db_session, user)

    resp = await _call(db_client, method, path, body)

    assert resp.status_code == 422
    assert await _money(db_session, user) == before


async def test_edit_with_a_malformed_message_id_is_422_and_spends_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """편집 대상 메시지 id 는 경로 칸이다. 깨지는 시나리오: 게이트가 그 칸을 검증하는 의존성을 거치지 않아, id 꼴이 아닌 경로도
    차감한 뒤 422 가 난다."""
    user, method, path, body = await _prepare_paid_turn(db_client, db_session, surface="edit", balance=_BALANCE)
    malformed = path.rsplit("/", 1)[0] + "/not-a-uuid"
    before = await _money(db_session, user)

    resp = await _call(db_client, method, malformed, body)

    assert resp.status_code == 422
    assert await _money(db_session, user) == before


async def test_premium_room_send_with_a_nul_content_is_422_and_spends_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """상위 모델 방 턴도 클로버로 내므로 같은 결함이 열려 있었다 — 기본 모델과 다른 차감 경로라 따로 본다."""
    user, method, path, _ = await _prepare_paid_turn(db_client, db_session, surface="send", balance=_BALANCE)
    _enable_chat_premium(monkeypatch)
    room_id = uuid.UUID(path.split("/")[2])
    await db_session.execute(update(ChatRoom).where(ChatRoom.id == room_id).values(chat_model="opus"))
    await db_session.commit()
    before = await _money(db_session, user)

    resp = await _call(db_client, method, path, {"content": "안\x00녕"})

    assert resp.status_code == 422
    assert await _money(db_session, user) == before


@pytest.mark.parametrize("surface", ["send", "edit", "preview"])
async def test_valid_turn_request_spends_once(
    db_client: httpx.AsyncClient, db_session: AsyncSession, surface: str
) -> None:
    """대조군: 같은 셋업에서 올바른 본문은 실제로 깎인다. 위 테스트들은 "잔액·원장·사용처가 그대로"만 보므로, 셋업이 유료
    상태를 만들지 못하게 바뀌면(셋업 사용자가 차감 면제 계정이 되는 등) 결함이 되살아나도 그대로 통과한다. 이 테스트가 그때
    빨개져 그런 헛통과를 막는다."""
    user, method, path, body = await _prepare_paid_turn(db_client, db_session, surface=surface, balance=_BALANCE)
    balance, ledger, usages = await _money(db_session, user)

    resp = await _call(db_client, method, path, body)

    assert resp.status_code == 200
    after_balance, after_ledger, after_usages = await _money(db_session, user)
    assert after_balance < balance
    assert (after_ledger, after_usages) == (ledger + 1, usages + 1)
