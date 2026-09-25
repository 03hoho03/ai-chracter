"""채팅 실패 9지점 중 **6곳만** 클로버를 되돌린다.

되돌리는 6곳은 프롬프트 렌더 실패와 LLM 호출 실패다 — 둘 다 결과물이 0인데 원인이 우리 쪽이다.
되돌리지 않는 3곳은 LLM 정책 위반이고, 사용자 입력이 원인이면서
LLM 을 실제로 태웠다. **이 비대칭이 의도라는 것을 테스트가 말해야 한다** — 안 그러면
다음 사람이 "3곳을 빠뜨렸다"고 읽고 마저 채운다.

셋업 관례는 `test_clover_gate.py`를 따른다 — 상한을 진짜로 소진시키지 않고
`monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)`으로 클로버를 태운다.
⚠️ 재생성은 **방을 먼저 만들어야** 하므로 상한 패치를 셋업 뒤로 미룬다 — 셋업 전송까지
클로버로 내면 원장 단언이 셋업 잡음까지 세게 된다.

⚠️ 잔액은 `db_session.refresh(user)`로 다시 읽는다. 차감·환불이 **별도 세션·별도 트랜잭션**에서
일어나 테스트 세션의 인스턴스는 낡아 있다.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat import router as chat_router
from api.chat.prompt_builder import PromptRenderError
from api.core import clover, rate_limit_gate
from api.db.models import User
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.clover import CloverLedger
from api.main import app
from api.llm.client import LLMClientError, LLMPolicyViolationError
from factories import (
    _clear_llm_override,
    _FakeLLMClient,
    _get_genre,
    _login_as,
    _make_published_character,
    _make_user_with_clover_lot,
    _override_llm_client,
    _parse_sse_events,
)

_CHAT_COST = clover.CHAT_TURN_COST
_START_BALANCE = 100


async def _ledger_pairs(db_session: AsyncSession, user_id: uuid.UUID) -> list[tuple[str, int]]:
    """원장을 `(kind, amount)` 목록으로 읽는다.

    🔴 **순서로 비교하지 않는다** — `created_at`의 server_default는 트랜잭션 시작 시각이고
    `id`는 uuid4라, 같은 요청이 남긴 행들 사이에 삽입 순서가 보장되지 않는다. 호출부가
    `sorted()`로 비교한다.
    """
    rows = (
        await db_session.scalars(select(CloverLedger).where(CloverLedger.user_id == user_id))
    ).all()
    return [(row.kind, row.amount) for row in rows]


async def _setup_chat_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, user: User
) -> uuid.UUID:
    genre = await _get_genre(db_session)
    content = await _make_published_character(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    await db_session.commit()
    await _login_as(db_client, user.id)
    resp = await db_client.post(
        "/chat-rooms", json={"contentId": str(content.id), "contentType": "character"}
    )
    assert resp.status_code == 201
    return uuid.UUID(resp.json()["id"])


async def _user_message_id(db_session: AsyncSession, room_id: uuid.UUID) -> uuid.UUID:
    """편집 대상(그 방의 사용자 메시지) id. 셋업 전송이 남긴 한 건을 쓴다."""
    rows = (
        await db_session.scalars(
            select(ChatMessage).where(
                ChatMessage.chat_room_id == room_id, ChatMessage.role == ChatMessageRole.USER
            )
        )
    ).all()
    assert len(rows) == 1
    return rows[0].id


def _failing_llm(failure: str) -> _FakeLLMClient:
    """`llm` 케이스만 LLM 을 실패시킨다. `render` 케이스는 LLM 호출 전에 끊기므로 정상 클라이언트."""
    if failure == "llm":
        return _FakeLLMClient(error=LLMClientError("network down"))
    if failure == "policy":
        return _FakeLLMClient(error=LLMPolicyViolationError("blocked"))
    return _FakeLLMClient(tokens=["안", "녕"])


def _patch_render_failure(monkeypatch: pytest.MonkeyPatch, surface: str) -> None:
    """프롬프트 렌더 실패를 만든다. 미리보기만 별도 빌더(`_build_preview_prompt`)를 쓴다."""
    if surface == "preview":

        def _raise_preview(*args: Any, **kwargs: Any) -> Any:
            raise PromptRenderError("렌더 실패")

        monkeypatch.setattr(chat_router, "_build_preview_prompt", _raise_preview)
        return

    async def _raise(*args: Any, **kwargs: Any) -> Any:
        raise PromptRenderError("렌더 실패")

    monkeypatch.setattr(chat_router, "_build_prompt", _raise)


async def _run_failing_turn(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    *,
    surface: str,
    failure: str,
) -> tuple[User, httpx.Response]:
    """`surface`(전송/재생성/미리보기)에서 `failure` 종류의 실패를 일으키고 응답을 돌려준다.

    상한 패치는 **셋업이 끝난 뒤** 건다 — 방 생성과 첫 전송은 무료분으로 통과해야 원장에
    셋업 잡음이 안 남는다.
    """
    # 차감에는 **오늘치 동의**가 선행한다(게이트가 미확인이면
    # `CLOVER_CONFIRM_REQUIRED`로 끊는다). 차감이 일어나는 것을 보는 테스트라 그 선행 조건을
    # 셋업에 명시한다. `_make_user` 기본값은 `None`(한 번도 확인 안 함)으로 그대로 둔다 —
    # 기본을 "오늘 확인됨"으로 바꾸면 확인 게이트 자체를 검증하는 테스트가 무력해진다.
    # 이 유저들은 실제로 chat_spend를 태우므로 매칭 로트가
    # 없으면 `CloverLotShortfallError`가 난다.
    user = await _make_user_with_clover_lot(
        db_session,
        clover_balance=_START_BALANCE,
        clover_spend_confirmed_on=clover.kst_today(datetime.now(UTC)),
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    room_id: uuid.UUID | None = None
    session_id: str | None = None
    message_id: uuid.UUID | None = None

    if surface == "preview":
        payload: dict[str, object] = {
            "name": "아리아",
            "oneLiner": "한 줄 소개",
            "thumbnailAssetId": None,
            "intro": "안녕하세요, 아리아예요",
            "exampleDialogues": [],
            "characterPrompt": "너는 아리아다.",
            "playguide": None,
            "situationalImages": [],
            "description": "상세 설명",
            "genreId": None,
            "target": None,
            "hashtags": [],
            "visibility": "private",
        }
        resp = await db_client.post("/preview-sessions", json=payload)
        assert resp.status_code == 201
        session_id = resp.json()["previewSessionId"]
    else:
        room_id = await _setup_chat_room(db_client, db_session, user)
        if surface in ("regenerate", "edit"):
            # 재생성은 "마지막 메시지가 AI 응답"인 상태를, 편집은 "고칠 사용자 메시지"를
            # 요구한다 — 성공하는 전송을 한 번 먼저 태운다. 이 전송은 상한 패치 전이라
            # 무료분으로 통과한다.
            _override_llm_client(_FakeLLMClient(tokens=["첫", "응답"]))
            try:
                sent = await db_client.post(
                    f"/chat-rooms/{room_id}/messages", json={"content": "안녕"}
                )
            finally:
                _clear_llm_override()
            assert sent.status_code == 200
        if surface == "edit":
            message_id = await _user_message_id(db_session, room_id)

    # 여기서부터 클로버로 낸다.
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)
    if failure == "render":
        _patch_render_failure(monkeypatch, surface)

    _override_llm_client(_failing_llm(failure))
    try:
        if surface == "preview":
            resp = await db_client.post(
                f"/preview-sessions/{session_id}/messages", json={"content": "안녕"}
            )
        elif surface == "regenerate":
            resp = await db_client.post(f"/chat-rooms/{room_id}/regenerate")
        elif surface == "edit":
            resp = await db_client.patch(
                f"/chat-rooms/{room_id}/messages/{message_id}", json={"content": "고친 내용"}
            )
        else:
            resp = await db_client.post(
                f"/chat-rooms/{room_id}/messages", json={"content": "안녕"}
            )
    finally:
        _clear_llm_override()

    await db_session.refresh(user)
    return user, resp


# 환불되는 6지점. 제너레이터 3개 × 실패 2종이고, 전송·편집이 같은
# `_stream_new_turn`을 공유하므로 전송으로 대표한다(편집은 같은 6지점을 다시 태운다).
@pytest.mark.parametrize("surface", ["send", "edit", "regenerate", "preview"])
@pytest.mark.parametrize("failure", ["render", "llm"])
async def test_our_side_failure_refunds_clover(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
    failure: str,
) -> None:
    """6지점 전부에서 차감이 되돌아가고 원장에 `chat_refund` 한 행이 남는다."""
    user, resp = await _run_failing_turn(
        db_client, db_session, monkeypatch, surface=surface, failure=failure
    )

    assert resp.status_code == 200
    assert [event["type"] for event in _parse_sse_events(resp.text)] == ["error"]

    assert user.clover_balance == _START_BALANCE
    assert sorted(await _ledger_pairs(db_session, user.id)) == sorted(
        [("chat_spend", -_CHAT_COST), ("chat_refund", _CHAT_COST)]
    )


@pytest.mark.parametrize("surface", ["send", "edit", "regenerate", "preview"])
async def test_policy_violation_does_not_refund_clover(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
) -> None:
    """정책 위반 3지점은 **소모로 둔다**.

    사용자 입력이 원인이고 LLM 을 실제로 태웠다. 이미지 가드 차단이 환불되는 것과
    결론이 갈리는 자리라, 이 테스트가 그 비대칭을 고정한다.
    """
    user, resp = await _run_failing_turn(
        db_client, db_session, monkeypatch, surface=surface, failure="policy"
    )

    assert resp.status_code == 200
    assert [event["type"] for event in _parse_sse_events(resp.text)] == ["policyWarning"]

    assert user.clover_balance == _START_BALANCE - _CHAT_COST
    assert await _ledger_pairs(db_session, user.id) == [("chat_spend", -_CHAT_COST)]


async def test_refund_failure_does_not_escape_the_generator(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """환불이 실패해도 예외가 제너레이터 밖으로 새지 않는다.

    🔴 새면 이미 시작된 SSE 스트림을 뚫고 나가 태스크가 취소되고, 망가진 asyncpg 커넥션이
    풀로 반환돼 **무관한 요청이 500**이 된다(`core/rate_limit_gate.py` 모듈 docstring).
    그래서 사용자가 보는 것은 평소와 같은 error 이벤트여야 하고, 남는 흔적은 Bugsink 뿐이다
    (자동 재시도를 만들지 않으므로 그게 유일한 발견 수단).
    """
    captured: list[str] = []
    monkeypatch.setattr(
        clover,
        "capture_dependency_failure",
        lambda exc, *, dependency: captured.append(dependency),
    )

    async def _boom(*args: Any, **kwargs: Any) -> int:
        raise RuntimeError("환불 트랜잭션 실패")

    monkeypatch.setattr(clover, "grant", _boom)

    user, resp = await _run_failing_turn(
        db_client, db_session, monkeypatch, surface="send", failure="llm"
    )

    # 스트림은 평소대로 끝난다 — 500 이 아니다.
    assert resp.status_code == 200
    assert [event["type"] for event in _parse_sse_events(resp.text)] == ["error"]
    # 환불이 실패했으므로 차감은 남는다. 보정은 어드민 지급이다.
    assert user.clover_balance == _START_BALANCE - _CHAT_COST
    assert await _ledger_pairs(db_session, user.id) == [("chat_spend", -_CHAT_COST)]
    assert captured == ["clover"]


# ── 본문 창: 차감 이후 · 첫 환불 지점 이전의 라우트 본문 실패 ────────────────────────────
#
# 게이트는 `Depends` 단계에서 클로버를 **별도 트랜잭션으로 커밋**한다.
# 제너레이터가 첫 환불 지점에 닿기 전까지 라우트 본문에는 환불 없이 예외로 끝날 수 있는 창이
# 있었다 — "우리 쪽 실패만 환불"을 일관되게 적용하려면 이 창도
# 되돌려야 한다.
#
# ⚠️ 이 창은 첫 `yield` **이전**이라 스트림이 아직 안 열렸다. 그래서 제너레이터 안의 6지점과
# 달리 예외를 삼키지 않고 **다시 올린다** — 여기서는 500 이 정상 경로다.
#
# 주입 지점이 라우트마다 다른 이유: 게이트(`charge`)는 이제 조회·검증 의존성 **전부보다 뒤**에
# 선언돼 있고 `Depends` 는 시그니처 순서대로 resolve 된다(`apps/api/CLAUDE.md` §API 라우터).
# 그래서 의존성이 쓰는 모듈 전역을 패치하면 **차감 전에** 터져 아래 `test_dependency_failure_
# does_not_spend_clover` 쪽(원장 0행)이 되어 버리고, 본문 창은 만들어지지 않는다. 그래서
# 라우트별로 **본문에만 있는** 것을 골랐다.


def _boom(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError("라우트 본문 실패")


async def _opening_message(db_session: AsyncSession, room_id: uuid.UUID) -> ChatMessage:
    rows = (
        await db_session.scalars(
            select(ChatMessage)
            .where(ChatMessage.chat_room_id == room_id)
            .order_by(ChatMessage.created_at.asc())
        )
    ).all()
    return rows[0]


async def _run_body_failure(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    *,
    surface: str,
) -> tuple[User, BaseException | None]:
    """본문을 터뜨리고 `(유저, 올라온 예외)`를 돌려준다.

    응답이 아니라 예외를 돌려주는 이유: 이 창은 첫 `yield` 전이라 예외를 **다시 올리는 것이
    정상**이고, `ASGITransport`는 기본값(`raise_app_exceptions=True`)이라 그 예외가 테스트까지
    전파된다. 즉 **고친 뒤에도 예외는 그대로 올라온다** — 달라지는 건 돈뿐이다.
    """
    # 차감에는 **오늘치 동의**가 선행한다(게이트가 미확인이면
    # `CLOVER_CONFIRM_REQUIRED`로 끊는다). 차감이 일어나는 것을 보는 테스트라 그 선행 조건을
    # 셋업에 명시한다. `_make_user` 기본값은 `None`(한 번도 확인 안 함)으로 그대로 둔다 —
    # 기본을 "오늘 확인됨"으로 바꾸면 확인 게이트 자체를 검증하는 테스트가 무력해진다.
    # 이 유저들은 실제로 chat_spend를 태우므로 매칭 로트가
    # 없으면 `CloverLotShortfallError`가 난다.
    user = await _make_user_with_clover_lot(
        db_session,
        clover_balance=_START_BALANCE,
        clover_spend_confirmed_on=clover.kst_today(datetime.now(UTC)),
    )
    await db_session.commit()
    await _login_as(db_client, user.id)
    room_id = await _setup_chat_room(db_client, db_session, user)

    message_id: uuid.UUID | None = None
    if surface == "edit":
        _override_llm_client(_FakeLLMClient(tokens=["첫", "응답"]))
        try:
            sent = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
        finally:
            _clear_llm_override()
        assert sent.status_code == 200
        message_id = await _user_message_id(db_session, room_id)

    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)
    _override_llm_client(_FakeLLMClient(tokens=["안", "녕"]))
    raised: BaseException | None = None
    try:
        if surface == "send":
            # 본문 첫 줄의 `select(ChatMessage)`가 깨진다. send 의 의존성 넷은 `ChatMessage`를
            # 쓰지 않으므로 이 패치는 본문에만 닿는다.
            monkeypatch.setattr(chat_router, "ChatMessage", _boom)
            try:
                await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
            except BaseException as exc:  # 무엇이 올라오든 기록만 한다
                raised = exc
        elif surface == "edit":
            # 편집 본문의 `delete(ChatMessage)`가 깨진다(후행 메시지가 있어 반드시 지난다).
            # `_editable_user_message_dependency`는 `db.get`을 쓰므로 영향받지 않는다.
            monkeypatch.setattr(chat_router, "delete", _boom)
            try:
                await db_client.patch(
                    f"/chat-rooms/{room_id}/messages/{message_id}", json={"content": "고친 내용"}
                )
            except BaseException as exc:
                raised = exc
        else:
            # 재생성 본문의 `history[-1]`이 IndexError 를 낸다. "마지막 앞에 사용자 메시지가
            # 있어야 한다"는 의존성 가드를 오버라이드로 뚫어 재현한다 — 그 가드가 언젠가
            # 느슨해져도 환불은 되어야 한다. (LLM·의존성 교체는 `app.dependency_overrides`가
            # 이 저장소 관례다 — `apps/api/CLAUDE.md` §테스트 정책)
            opening = await _opening_message(db_session, room_id)
            app.dependency_overrides[chat_router._regeneratable_last_message_dependency] = (
                lambda: opening
            )
            try:
                await db_client.post(f"/chat-rooms/{room_id}/regenerate")
            except BaseException as exc:
                raised = exc
            finally:
                app.dependency_overrides.pop(
                    chat_router._regeneratable_last_message_dependency, None
                )
    finally:
        _clear_llm_override()

    await db_session.refresh(user)
    return user, raised


@pytest.mark.parametrize("surface", ["send", "edit", "regenerate"])
async def test_route_body_failure_refunds_clover(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
) -> None:
    """차감은 커밋됐는데 본문이 첫 `yield` 전에 터지면 되돌린다.

    미리보기는 대상이 아니다 — 본문에 DB 접근이 0건이라 이 창 자체가 없다.
    """
    user, raised = await _run_body_failure(db_client, db_session, monkeypatch, surface=surface)

    # 요청은 그대로 실패한다 — 환불이 원래 예외를 삼키면 안 된다.
    assert raised is not None

    assert user.clover_balance == _START_BALANCE
    assert sorted(await _ledger_pairs(db_session, user.id)) == sorted(
        [("chat_spend", -_CHAT_COST), ("chat_refund", _CHAT_COST)]
    )


# ── 의존성 창: 조회·검증이 실패하면 **애초에 차감하지 않는다** ────────────────────────
#
# 본문 창(위)이 "차감한 뒤 본문이 터지면 되돌린다"라면, 이쪽은 **차감 자체가 일어나면 안 되는**
# 자리다. 게이트가 `room`·`state` 같은 조회 의존성보다 **뒤에** 선언돼 있어야 성립한다 —
# `Depends`는 시그니처 순서대로 순차 resolve되고 앞의 것이 raise하면 뒤는 호출조차 안 되기
# 때문이다(`apps/api/CLAUDE.md` §API 라우터).
#
# 🔴 본문 창과 단언이 다르다. 본문 창은 원장에 `chat_spend` + `chat_refund` 두 행이 남고, 이쪽은
# **0행**이다. 환불로 되돌린 것과 애초에 안 깎은 것은 사용자에게는 같아 보여도 원장에서는
# 갈린다 — 유상화 뒤 "왜 줄었나"를 설명할 때 이 구분이 근거가 된다.
#
# 404 를 고른 이유: 정상 운영 중에도 난다(지워진 방, 남의 방, 만료된 미리보기 세션).
# 본문 창(차감 성공 직후 DB 실패)보다 훨씬 도달하기 쉽다.


@pytest.mark.parametrize("surface", ["send", "edit", "regenerate", "preview"])
async def test_dependency_failure_does_not_spend_clover(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
) -> None:
    """존재하지 않는 방·세션이면 404 로 끝나고 클로버는 손대지 않는다.

    상한을 0 으로 낮춰 **클로버를 낼 수밖에 없는 상태**로 만든 뒤 요청한다 — 안 그러면
    무료분으로 통과해 단언이 항진명제가 된다.
    """
    # 차감에는 **오늘치 동의**가 선행한다(게이트가 미확인이면
    # `CLOVER_CONFIRM_REQUIRED`로 끊는다). 차감이 일어나는 것을 보는 테스트라 그 선행 조건을
    # 셋업에 명시한다. `_make_user` 기본값은 `None`(한 번도 확인 안 함)으로 그대로 둔다 —
    # 기본을 "오늘 확인됨"으로 바꾸면 확인 게이트 자체를 검증하는 테스트가 무력해진다.
    # 이 유저들은 실제로 chat_spend를 태우므로 매칭 로트가
    # 없으면 `CloverLotShortfallError`가 난다.
    user = await _make_user_with_clover_lot(
        db_session,
        clover_balance=_START_BALANCE,
        clover_spend_confirmed_on=clover.kst_today(datetime.now(UTC)),
    )
    await db_session.commit()
    await _login_as(db_client, user.id)

    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)
    missing = uuid.uuid4()

    if surface == "send":
        resp = await db_client.post(f"/chat-rooms/{missing}/messages", json={"content": "안녕"})
    elif surface == "edit":
        resp = await db_client.patch(
            f"/chat-rooms/{missing}/messages/{uuid.uuid4()}", json={"content": "고친 내용"}
        )
    elif surface == "regenerate":
        resp = await db_client.post(f"/chat-rooms/{missing}/regenerate")
    else:
        resp = await db_client.post(
            f"/preview-sessions/{missing}/messages", json={"content": "안녕"}
        )

    assert resp.status_code == 404

    await db_session.refresh(user)
    assert user.clover_balance == _START_BALANCE
    assert await _ledger_pairs(db_session, user.id) == []
