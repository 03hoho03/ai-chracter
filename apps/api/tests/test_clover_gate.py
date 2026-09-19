"""clover-techspec.md CT-5·CT-7·CT-8, S3: 무료 한도를 소진한 뒤 클로버가 게이트를 뚫는지 —
그리고 **뚫으면 안 되는 자리에서는 안 뚫는지**를 검증한다.

셋업 관례는 `test_user_rate_limit_gate.py`를 그대로 따른다 — 상한을 진짜로 소진시키지 않고
`monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)`으로 만든다(채팅 경로는 한 번만
통과해도 LLM을 태운다).

🔴 **경로 파라미터는 실존해야 한다.** 예전에는 게이트가 `_owned_room_dependency` 앞의
`Depends`라 더미 방 id로도 게이트에 닿았고 "통과 = 404"였다. S4(clover-techspec.md CT-7)가
게이트를 조회·검증 의존성 **뒤**로 옮기면서 그 지름길이 막혔다 — 없는 방은 게이트에 닿기도
전에 404다. 그래서 이 파일은 `_setup_room`으로 진짜 방을 만들어 쓰고, **이 파일에서 통과는
이제 200이다**(LLM은 `_send`가 스텁한다).

⚠️ 잔액 단언은 `db_session.refresh(user)`로 다시 읽는다. 차감이 **별도 세션·별도 트랜잭션**
(clover-techspec.md CT-4)에서 일어나므로 테스트 세션이 들고 있는 인스턴스는 낡아 있다.
`conftest.py`의 `get_session_factory` 오버라이드가 그 세션을 테스트 커넥션에 묶어 두기 때문에
읽을 수는 있다(같은 트랜잭션에 합류한다).
"""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clover, rate_limit_gate
from api.core.rate_limit import seconds_until_kst_midnight
from api.db.models import User
from api.db.models.clover import CloverLedger
from factories import (
    _clear_llm_override,
    _FakeLLMClient,
    _get_genre,
    _login_as,
    _make_published_character,
    _make_user,
    _override_llm_client,
)

_SEND_BODY = {"content": "안녕"}


async def _consented_user(
    db_client: httpx.AsyncClient, db_session: AsyncSession, **overrides: object
) -> User:
    user = _make_user(**overrides)
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    return user


def _confirmed_today() -> dict[str, object]:
    """clover-goal-prompt.md CL-19 / clover-techspec.md CT-17 — 클로버 차감에는 **오늘치 동의**가
    선행한다. 게이트가 미확인이면 차감하지 않고 `CLOVER_CONFIRM_REQUIRED`로 끊으므로, "차감이
    일어난다"를 보는 테스트는 그 선행 조건을 셋업에 명시해야 한다.

    `_make_user`의 기본값은 `None`(한 번도 확인한 적 없음)으로 **그대로 둔다** — 새로 만든
    사용자의 참값이고, 기본을 "오늘 확인됨"으로 바꾸면 확인 게이트를 검증하는 테스트가
    셋업만으로 통과해 버린다.
    """
    return {"clover_spend_confirmed_on": clover.kst_today(datetime.now(UTC))}


async def _setup_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, user: User
) -> uuid.UUID:
    """그 사용자가 소유한 캐릭터 채팅방을 실제로 만든다.

    `POST /chat-rooms`는 RL-1의 채팅 4경로가 아니라 게이트가 안 붙는다 — 셋업이 상한이나
    클로버를 소모하지 않는다(그래서 상한 패치를 셋업 뒤에 걸 필요도 없다).
    """
    genre = await _get_genre(db_session)
    content = await _make_published_character(
        db_session, creator_user_id=user.id, genre_id=genre.id
    )
    await db_session.commit()
    resp = await db_client.post(
        "/chat-rooms", json={"contentId": str(content.id), "contentType": "character"}
    )
    assert resp.status_code == 201
    return uuid.UUID(resp.json()["id"])


async def _ledger_for(db_session: AsyncSession, user_id: uuid.UUID) -> list[CloverLedger]:
    # `id`는 uuid4라 이 정렬은 "결정적"일 뿐 "삽입 순서"가 아니다 — 여러 행을 볼 때는 순서가
    # 아니라 내용으로 비교한다(`test_core_clover.py`의 같은 주의).
    return list(
        (
            await db_session.scalars(
                select(CloverLedger)
                .where(CloverLedger.user_id == user_id)
                .order_by(CloverLedger.created_at, CloverLedger.id)
            )
        ).all()
    )


async def _send(db_client: httpx.AsyncClient, room_id: uuid.UUID) -> httpx.Response:
    """LLM을 스텁해 두고 전송 1회. 게이트를 통과하면 턴이 끝까지 돌아 200이다.

    🔴 `room_id`는 **필수**다(기본값 `uuid.uuid4()`를 두지 않는다). S4가 게이트를 조회·검증
    의존성 뒤로 옮긴 뒤로 더미 방은 게이트에 닿기도 전에 404라, 기본값이 있으면 "차감 없음"을
    단언하는 테스트가 **게이트를 한 번도 실행하지 않은 채 초록**이 된다 — 항진명제다.
    실수로 되살아나지 않게 타입으로 막는다.
    """
    _override_llm_client(_FakeLLMClient())
    try:
        return await db_client.post(f"/chat-rooms/{room_id}/messages", json=_SEND_BODY)
    finally:
        _clear_llm_override()


# ---- T-5. 일일 소진 + 잔액 충분 → 클로버로 통과하고 CHAT_TURN_COST만큼 깎인다 ----


async def test_daily_exhausted_with_balance_spends_clover_and_passes(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """clover-goal-prompt.md CL-1: 클로버가 뚫는 것은 **일일 상한 초과분**이다."""
    user = await _consented_user(db_client, db_session, clover_balance=100, **_confirmed_today())
    room_id = await _setup_room(db_client, db_session, user)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)

    resp = await _send(db_client, room_id)

    # 429가 아니다 = 게이트를 통과했다. 게이트가 조회 뒤로 내려간 뒤로는(CT-7) 방이 실존하므로
    # 턴이 끝까지 돌아 200이다 — 예전의 404는 "소유권 검사에서 막혔다"는 뜻이었다.
    assert resp.status_code == 200

    await db_session.refresh(user)
    assert user.clover_balance == 100 - clover.CHAT_TURN_COST

    rows = await _ledger_for(db_session, user.id)
    assert len(rows) == 1
    assert rows[0].kind == "chat_spend"
    assert rows[0].amount == -clover.CHAT_TURN_COST
    assert rows[0].balance_after == 100 - clover.CHAT_TURN_COST


async def test_daily_exhausted_without_balance_is_the_control(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """위 테스트의 짝. 셋업이 글자까지 같고 `clover_balance`만 0이다 — 이 짝이 없으면 위의
    200은 "클로버가 뚫었다"가 아니라 "이 셋업에서는 원래 아무도 안 걸린다"일 수 있다."""
    user = await _consented_user(db_client, db_session, clover_balance=0, **_confirmed_today())
    room_id = await _setup_room(db_client, db_session, user)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)

    resp = await _send(db_client, room_id)

    assert resp.status_code == 429


# ---- T-6. 잔액 0 → 429 CLOVER_REQUIRED / window=clover / 자정까지 초 ----


async def test_insufficient_clover_returns_clover_required_body(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """clover-techspec.md CT-8 채팅 행. `retryAfterSeconds`가 자정까지 초인 이유는 그때 무료
    30턴이 돌아오기 때문이다 — 값이 거짓이 아니다."""
    user = await _consented_user(
        db_client, db_session, clover_balance=clover.CHAT_TURN_COST - 1, **_confirmed_today()
    )
    room_id = await _setup_room(db_client, db_session, user)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)

    resp = await _send(db_client, room_id)

    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert detail["code"] == "CLOVER_REQUIRED"
    assert detail["window"] == "clover"
    retry_after = detail["retryAfterSeconds"]
    assert isinstance(retry_after, int)
    # 자정까지 남은 초. 상수를 그대로 인용하면 항진명제가 되므로 범위로만 본다 — `day` 창과
    # 같은 상한이고 분당 창(60)보다는 클 수 있다.
    assert 1 <= retry_after <= 86400
    assert retry_after == pytest.approx(seconds_until_kst_midnight(datetime.now(UTC)), abs=5)


async def test_insufficient_clover_does_not_write_a_ledger_row(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """부족해서 거절된 요청은 잔액도 원장도 건드리지 않는다 — 조건부 UPDATE가 행을 못 잡으면
    원장 INSERT까지 가지 않는다(`core/clover.py`의 `_apply`)."""
    user = await _consented_user(
        db_client, db_session, clover_balance=clover.CHAT_TURN_COST - 1, **_confirmed_today()
    )
    room_id = await _setup_room(db_client, db_session, user)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)

    assert (await _send(db_client, room_id)).status_code == 429

    await db_session.refresh(user)
    assert user.clover_balance == clover.CHAT_TURN_COST - 1
    assert await _ledger_for(db_session, user.id) == []


# ---- T-7. 분당 버스트는 클로버로도 안 뚫린다 (CL-1) ----


async def test_burst_limit_is_not_bypassed_by_clover(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """🔴 clover-goal-prompt.md CL-1: 분당 버스트는 **쿼터가 아니라 폭주 방어**라 돈으로 끌 수
    없다. 잔액이 넉넉해도 `window=minute` 429가 나가야 하고 **잔액이 깎이면 안 된다** —
    삽입 지점이 버스트 `raise`(`:187`)보다 앞이면 여기서 깎인다."""
    user = await _consented_user(db_client, db_session, clover_balance=1000)
    room_id = await _setup_room(db_client, db_session, user)
    monkeypatch.setattr(rate_limit_gate, "CHAT_BURST_LIMIT", 0)

    resp = await _send(db_client, room_id)

    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert detail["code"] == "USER_LIMIT"
    assert detail["window"] == "minute"

    await db_session.refresh(user)
    assert user.clover_balance == 1000
    assert await _ledger_for(db_session, user.id) == []


# ---- T-8. 예외 계정은 클로버 분기를 비껴간다 (CL-2) ----


async def test_exempt_user_passes_without_spending_clover(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """🔴 clover-goal-prompt.md CL-2: 면제 판정(`:192-193`)이 클로버 검사보다 **앞**이라
    예외 계정은 일일 상한도 클로버도 건드리지 않고 통과한다. 삽입 지점이 면제 `return`보다
    앞이면 예외 계정의 잔액이 깎인다.

    🔴 **방이 실존해야 한다.** 더미 방이면 게이트가 실행되지 않아(S4가 게이트를 조회 뒤로
    옮겼다 — 모듈 docstring) "차감 없음"이 항진명제가 된다.
    """
    user = await _consented_user(
        db_client, db_session, rate_limit_exempt=True, clover_balance=100
    )
    room_id = await _setup_room(db_client, db_session, user)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)

    resp = await _send(db_client, room_id)

    assert resp.status_code == 200  # 통과

    await db_session.refresh(user)
    assert user.clover_balance == 100
    assert await _ledger_for(db_session, user.id) == []


async def test_exempt_user_with_zero_balance_still_passes(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """면제가 클로버 **앞**이라는 것의 더 강한 증거 — 잔액이 0인데도 통과한다. 순서가 뒤집혀
    있으면 여기서 `CLOVER_REQUIRED` 429가 난다.

    🔴 **방이 실존해야 한다.** 더미 방이면 게이트가 실행되지 않아 이 통과가 면제 때문인지
    404 때문인지 구분되지 않는다(S4가 게이트를 조회 뒤로 옮겼다 — 모듈 docstring).
    """
    user = await _consented_user(
        db_client, db_session, rate_limit_exempt=True, clover_balance=0
    )
    room_id = await _setup_room(db_client, db_session, user)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)

    assert (await _send(db_client, room_id)).status_code == 200


# ---- Redis 장애에서는 클로버 분기에 도달하지 않는다 (CL-2 / CT-5) ----


async def test_redis_failure_fails_open_without_touching_clover(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """🔴 clover-techspec.md CT-5: 클로버 검사가 `try` 블록 **안**이라 `check_rate_limit`이
    `RedisError`를 던지면 `except`로 빠져 **클로버 분기에 도달하지 않는다**. 바깥에 두면
    Redis 장애 동안 전원이 차감된다.

    🔴 **방이 실존해야 한다.** 더미 방이면 게이트가 실행되지 않아 "차감 없음"이 항진명제가
    된다(S4가 게이트를 조회 뒤로 옮겼다 — 모듈 docstring). 방을 먼저 만들고 그 뒤에 Redis를
    고장내는 순서인 이유도 같다 — 셋업이 게이트를 안 타야 한다.
    """
    from redis.exceptions import ConnectionError as RedisConnectionError

    user = await _consented_user(db_client, db_session, clover_balance=100)
    room_id = await _setup_room(db_client, db_session, user)

    async def _raise_redis_error(*args: object, **kwargs: object) -> int:
        raise RedisConnectionError("redis down")

    monkeypatch.setattr(rate_limit_gate, "check_rate_limit", _raise_redis_error)
    monkeypatch.setattr(rate_limit_gate, "_last_redis_failure_reported_at", None)

    resp = await _send(db_client, room_id)

    assert resp.status_code == 200  # fail-open 통과

    await db_session.refresh(user)
    assert user.clover_balance == 100
    assert await _ledger_for(db_session, user.id) == []


# ---- 무료 한도 안에서는 클로버가 깎이지 않는다 (`source="free"`) ----


async def test_within_daily_limit_does_not_spend_clover(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """🔴 이 파일의 다른 "잔액 양수" 테스트는 **전부** `CHAT_DAILY_LIMIT`을 0으로 패치하거나
    `check_rate_limit`을 스텁한다. 그래서 **"일일 한도 안 + 잔액 양수"** 조합이 한 번도
    실행되지 않았다 — `source="free"` 경로에 테스트가 0건이었다.

    그 구멍이 위험한 이유: 클로버 분기가 실수로 `if day_retry_after > 0:` **밖으로** 나가면
    잔액 0인 유저는 대량 실패로 잡히지만 **잔액이 있는 유저는 조용히 매 턴 깎이고 스위트는
    초록이다.** 이 테스트만이 그 경우에 빨개진다.

    셋업의 핵심은 **상한을 패치하지 않는 것**이다(`CHAT_BURST_LIMIT` 10 · `CHAT_DAILY_LIMIT`
    30 에 요청 1건이라 둘 다 여유가 있다). clover-goal-prompt.md CL-1 이 정한 *"무료 한도
    **초과분**만 클로버"*가 지켜지면 잔액도 원장도 그대로여야 한다.

    🔴 **방이 실존해야 한다.** 더미 방이면 게이트가 실행되지 않아(S4가 게이트를 조회 뒤로
    옮겼다 — 모듈 docstring) "차감 없음"이 항진명제가 되고, 위에 적은 구멍을 **이 테스트가
    더 이상 덮지 못한다.**
    """
    user = await _consented_user(db_client, db_session, clover_balance=100)
    room_id = await _setup_room(db_client, db_session, user)

    resp = await _send(db_client, room_id)

    # 429가 아니다 = 게이트를 통과했다. 클로버를 안 쓰고 무료분으로 지났다는 뜻이다.
    assert resp.status_code == 200

    await db_session.refresh(user)
    assert user.clover_balance == 100
    assert await _ledger_for(db_session, user.id) == []


# ---- CT-17. 오늘치 동의가 없으면 차감하지 않고 CLOVER_CONFIRM_REQUIRED로 끊는다 (CL-19) ----


async def test_unconfirmed_spend_is_blocked_before_charging(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """clover-goal-prompt.md CL-19 — "소진 시 하루 1회 확인 **후** 자동 차감"의 *후*가 이 테스트다.

    🔴 **FE는 이 판정을 할 수 없다.** `GET /me/clover`는 잔액·확인여부·출석가능만 주고 "이번
    전송이 무료분을 넘는가"는 모른다 — 미확인인 모든 첫 전송에 모달을 띄우면 무료분을 안 쓴
    사용자까지 매일 붙잡는다. 그래서 **BE가 단일 판정자**가 되고, 그 판정이 곧 이 429다.

    셋업이 `test_daily_exhausted_with_balance_spends_clover_and_passes`와 **글자까지 같고
    `_confirmed_today()`만 없다** — 그 짝이 없으면 이 429가 "동의가 없어서"인지 "원래 이
    셋업에서는 아무도 못 지나서"인지 갈리지 않는다.
    """
    user = await _consented_user(db_client, db_session, clover_balance=100)
    room_id = await _setup_room(db_client, db_session, user)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)

    resp = await _send(db_client, room_id)

    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert detail["code"] == "CLOVER_CONFIRM_REQUIRED"
    # `window`는 "어느 기능이냐"라 부족(`CLOVER_REQUIRED`)과 같은 값을 쓴다 — 둘을 가르는 축은
    # `code`다(이 모듈의 `_IMAGE_WINDOW` 주석이 세운 규칙 그대로).
    assert detail["window"] == "clover"

    # 🔴 차감이 **일어나지 않았다**. 동의 전에 깎으면 CL-19가 무의미해진다.
    await db_session.refresh(user)
    assert user.clover_balance == 100
    assert await _ledger_for(db_session, user.id) == []


async def test_confirmation_from_yesterday_does_not_count_for_today(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CL-19의 "KST 자정마다 리셋". 어제 동의는 오늘치가 아니다.

    이 테스트가 없으면 판정을 `is not None`("한 번이라도 확인했으면 끝")으로 짜도 초록이다 —
    그러면 **하루 1회가 평생 1회가 된다**(무단 차감).
    """
    yesterday = clover.kst_today(datetime.now(UTC)) - timedelta(days=1)
    user = await _consented_user(
        db_client, db_session, clover_balance=100, clover_spend_confirmed_on=yesterday
    )
    room_id = await _setup_room(db_client, db_session, user)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)

    resp = await _send(db_client, room_id)

    assert resp.status_code == 429
    assert resp.json()["detail"]["code"] == "CLOVER_CONFIRM_REQUIRED"
    await db_session.refresh(user)
    assert user.clover_balance == 100


async def test_confirmation_gate_is_after_the_free_quota(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """🔴 미확인이어도 **무료 한도 안에서는 아무 일도 없어야 한다.**

    확인 검사를 클로버 분기 **밖**으로 옮기면 무료분이 남은 사용자까지 429를 받는다 — 그게
    S9-b가 보고한 *"무료분을 안 쓴 사용자까지 매일 붙잡는다"*의 서버쪽 판본이다. 상한을
    패치하지 않는 것이 이 테스트의 핵심이다.
    """
    user = await _consented_user(db_client, db_session, clover_balance=100)
    room_id = await _setup_room(db_client, db_session, user)

    resp = await _send(db_client, room_id)

    assert resp.status_code == 200
    await db_session.refresh(user)
    assert user.clover_balance == 100
    assert await _ledger_for(db_session, user.id) == []


async def test_unconfirmed_without_balance_gets_shortage_not_confirmation(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """🔴 잔액이 모자라면 **묻지 않고** 곧장 `CLOVER_REQUIRED`다 — 동의를 물어 놓고 직후
    "부족해요"를 내는 두 단계 헛걸음을 막는 조건(`rate_limit_gate.py`의 `clover_balance >= cost`).

    `test_unconfirmed_spend_is_blocked_before_charging`의 **짝**이다. 그쪽은 "잔액 있음 +
    미확인 → 확인 429", 이쪽은 "잔액 없음 + 미확인 → 부족 429". 두 테스트가 `clover_balance`
    하나만 다르므로 **`code`를 가르는 것이 잔액이라는 것**이 그 대조로 증명된다.

    🔴 이 테스트가 없으면 잔액 조건에 회귀 가드가 0이다 — 그 줄을 `return True`로 바꿔도
    스위트가 전부 초록이었다(잔액이 단가 미만인 다른 셋업은 전부 `_confirmed_today()`이거나
    `rate_limit_exempt=True`라 확인 게이트에 도달조차 안 한다). 그 커버리지는 원래 우연이었고,
    확인 게이트를 넣은 커밋이 같은 셋업에 `_confirmed_today()`를 주입하며 걷어 갔다.
    """
    user = await _consented_user(db_client, db_session, clover_balance=0)
    room_id = await _setup_room(db_client, db_session, user)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)

    resp = await _send(db_client, room_id)

    assert resp.status_code == 429
    assert resp.json()["detail"]["code"] == "CLOVER_REQUIRED"

    await db_session.refresh(user)
    assert user.clover_balance == 0
    assert await _ledger_for(db_session, user.id) == []


async def test_exempt_user_is_not_asked_to_confirm(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CL-2 — 예외 계정은 차감 대상이 아니므로 동의를 물을 일도 없다.

    게이트 순서가 **버스트 → 면제 → 일일 → 확인 → 차감**이라 면제가 먼저 `return`한다.
    확인 검사를 면제보다 앞에 두면 이 테스트가 429로 빨개진다.
    """
    user = await _consented_user(
        db_client, db_session, clover_balance=0, rate_limit_exempt=True
    )
    room_id = await _setup_room(db_client, db_session, user)
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)

    resp = await _send(db_client, room_id)

    assert resp.status_code == 200
    await db_session.refresh(user)
    assert user.clover_balance == 0
    assert await _ledger_for(db_session, user.id) == []
