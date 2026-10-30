"""기본 모델(Gemini) 턴이 클로버로 게이트를 뚫는지 —
그리고 **뚫으면 안 되는 자리에서는 안 뚫는지**를 검증한다.

기본 모델 턴에도 하루 무료분이 없어 면제 계정 밖의 첫 턴부터 클로버로 낸다. 그래서 상한을 패치하지 않고 잔액만으로 갈래를
고른다(채팅 경로는 한 번만 통과해도 LLM을 태운다).

🔴 **경로 파라미터는 실존해야 한다.** 예전에는 게이트가 `_owned_room_dependency` 앞의
`Depends`라 더미 방 id로도 게이트에 닿았고 "통과 = 404"였다. 게이트가
조회·검증 의존성 **뒤**로 옮겨지면서 그 지름길이 막혔다 — 없는 방은 게이트에 닿기도
전에 404다. 그래서 이 파일은 `_setup_room`으로 진짜 방을 만들어 쓰고, **이 파일에서 통과는
이제 200이다**(LLM은 `_send`가 스텁한다).

⚠️ 잔액 단언은 `db_session.refresh(user)`로 다시 읽는다. 차감이 **별도 세션·별도 트랜잭션**에서
일어나므로 테스트 세션이 들고 있는 인스턴스는 낡아 있다.
`conftest.py`의 `get_session_factory` 오버라이드가 그 세션을 테스트 커넥션에 묶어 두기 때문에
읽을 수는 있다(같은 트랜잭션에 합류한다).
"""

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clover, rate_limit_gate
from api.core.rate_limit import seconds_until_kst_midnight
from api.db.models import User
from api.db.models.chat import ChatTurn
from api.db.models.clover import CloverLedger
from factories import (
    _clear_llm_override,
    _FakeLLMClient,
    _get_genre,
    _login_as,
    _make_published_character,
    _make_user_with_clover_lot,
    _override_llm_client,
)

_SEND_BODY = {"content": "안녕"}


async def _consented_user(
    db_client: httpx.AsyncClient, db_session: AsyncSession, **overrides: object
) -> User:
    """`clover_balance`가 있으면 매칭 로트도 함께 만든다.
    게이트가 실제로 차감하는 테스트(`test_gemini_turn_with_balance_spends_clover_and_passes`)
    가 로트 0행 상태에서 `CloverLotShortfallError`를 맞지 않도록."""
    balance = overrides.pop("clover_balance", 0)
    assert isinstance(balance, int)
    user = await _make_user_with_clover_lot(db_session, clover_balance=balance, **overrides)
    await db_session.commit()
    await _login_as(db_client, user.id)
    return user


def _confirmed_today() -> dict[str, object]:
    """오늘치 클로버 사용 확인을 마친 상태. 채팅 게이트는 확인을 묻지 않는다 — 이 셋업을 쓰는 테스트는 확인 여부와 무관하게
    차감 경로만 본다(확인 없이도 깎이는지는 확인하지 않은 사용자를 쓰는 테스트가 본다).

    `_make_user`의 기본값은 `None`(한 번도 확인한 적 없음)으로 **그대로 둔다** — 새로 만든
    사용자의 참값이고, 기본을 "오늘 확인됨"으로 바꾸면 확인 게이트를 검증하는 테스트가
    셋업만으로 통과해 버린다.
    """
    return {"clover_spend_confirmed_on": clover.kst_today(datetime.now(UTC))}


async def _setup_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, user: User
) -> uuid.UUID:
    """그 사용자가 소유한 캐릭터 채팅방을 실제로 만든다.

    `POST /chat-rooms`는 채팅 4경로(전송·편집·재생성·미리보기)가 아니라 게이트가 안 붙는다 — 셋업이 상한이나
    클로버를 소모하지 않는다.
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

    🔴 `room_id`는 **필수**다(기본값 `uuid.uuid4()`를 두지 않는다). 게이트가 조회·검증
    의존성 뒤에 있어 더미 방은 게이트에 닿기도 전에 404라, 기본값이 있으면 "차감 없음"을
    단언하는 테스트가 **게이트를 한 번도 실행하지 않은 채 초록**이 된다 — 항진명제다.
    실수로 되살아나지 않게 타입으로 막는다.
    """
    _override_llm_client(_FakeLLMClient())
    try:
        return await db_client.post(f"/chat-rooms/{room_id}/messages", json=_SEND_BODY)
    finally:
        _clear_llm_override()


# ---- 잔액 충분 → 클로버로 통과하고 턴 가격만큼 깎인다 ----


async def test_gemini_turn_with_balance_spends_clover_and_passes(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """하루 무료분이 없어 첫 턴부터 클로버가 낸다."""
    user = await _consented_user(db_client, db_session, clover_balance=100, **_confirmed_today())
    room_id = await _setup_room(db_client, db_session, user)

    resp = await _send(db_client, room_id)

    # 429가 아니다 = 게이트를 통과했다. 게이트가 조회 뒤로 내려간 뒤로는 방이 실존하므로
    # 턴이 끝까지 돌아 200이다 — 예전의 404는 "소유권 검사에서 막혔다"는 뜻이었다.
    assert resp.status_code == 200

    await db_session.refresh(user)
    assert user.clover_balance == 100 - clover.CLOVER_MODEL_PRICES["gemini"].chat_turn

    rows = await _ledger_for(db_session, user.id)
    assert len(rows) == 1
    assert rows[0].kind == "chat_spend"
    assert rows[0].amount == -clover.CLOVER_MODEL_PRICES["gemini"].chat_turn
    assert rows[0].balance_after == 100 - clover.CLOVER_MODEL_PRICES["gemini"].chat_turn


async def test_gemini_turn_without_balance_is_the_control(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """위 테스트의 짝. 셋업이 글자까지 같고 `clover_balance`만 0이다 — 이 짝이 없으면 위의
    200은 "클로버가 뚫었다"가 아니라 "이 셋업에서는 원래 아무도 안 걸린다"일 수 있다."""
    user = await _consented_user(db_client, db_session, clover_balance=0, **_confirmed_today())
    room_id = await _setup_room(db_client, db_session, user)

    resp = await _send(db_client, room_id)

    assert resp.status_code == 429


# ---- 잔액 0 → 429 CLOVER_REQUIRED / window=clover / 자정까지 초 ----


async def test_insufficient_clover_returns_clover_required_body(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """`retryAfterSeconds`는 자정까지 초다. 자정에 돌아오는 무료분은 없다 — 화면이 이 값으로 재시도 시각을 약속하지 않고,
    429 의 계약 모양(`code`·`window`·`retryAfterSeconds`)을 지키려고 싣는다."""
    user = await _consented_user(
        db_client, db_session, clover_balance=clover.CLOVER_MODEL_PRICES["gemini"].chat_turn - 1, **_confirmed_today()
    )
    room_id = await _setup_room(db_client, db_session, user)

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
) -> None:
    """부족해서 거절된 요청은 잔액도 원장도 건드리지 않는다 — 조건부 UPDATE가 행을 못 잡으면
    원장 INSERT까지 가지 않는다(`core/clover.py`의 `_apply`)."""
    user = await _consented_user(
        db_client, db_session, clover_balance=clover.CLOVER_MODEL_PRICES["gemini"].chat_turn - 1, **_confirmed_today()
    )
    room_id = await _setup_room(db_client, db_session, user)

    assert (await _send(db_client, room_id)).status_code == 429

    await db_session.refresh(user)
    assert user.clover_balance == clover.CLOVER_MODEL_PRICES["gemini"].chat_turn - 1
    assert await _ledger_for(db_session, user.id) == []


# ---- 분당 버스트는 클로버로도 안 뚫린다 ----


async def test_burst_limit_is_not_bypassed_by_clover(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """🔴 분당 버스트는 **쿼터가 아니라 폭주 방어**라 돈으로 끌 수
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


# ---- 예외 계정은 클로버 분기를 비껴간다 ----


async def test_exempt_user_passes_without_spending_clover(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """🔴 면제 판정이 클로버 검사보다 **앞**이라
    예외 계정은 클로버를 건드리지 않고 통과한다. 삽입 지점이 면제 `return`보다
    앞이면 예외 계정의 잔액이 깎인다.

    🔴 **방이 실존해야 한다.** 더미 방이면 게이트가 실행되지 않아(게이트가 조회 뒤에
    있다 — 모듈 docstring) "차감 없음"이 항진명제가 된다.
    """
    user = await _consented_user(
        db_client, db_session, rate_limit_exempt=True, clover_balance=100
    )
    room_id = await _setup_room(db_client, db_session, user)

    resp = await _send(db_client, room_id)

    assert resp.status_code == 200  # 통과

    await db_session.refresh(user)
    assert user.clover_balance == 100
    assert await _ledger_for(db_session, user.id) == []


async def test_exempt_user_with_zero_balance_still_passes(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """면제가 클로버 **앞**이라는 것의 더 강한 증거 — 잔액이 0인데도 통과한다. 순서가 뒤집혀
    있으면 여기서 `CLOVER_REQUIRED` 429가 난다.

    🔴 **방이 실존해야 한다.** 더미 방이면 게이트가 실행되지 않아 이 통과가 면제 때문인지
    404 때문인지 구분되지 않는다(게이트가 조회 뒤에 있다 — 모듈 docstring).
    """
    user = await _consented_user(
        db_client, db_session, rate_limit_exempt=True, clover_balance=0
    )
    room_id = await _setup_room(db_client, db_session, user)

    assert (await _send(db_client, room_id)).status_code == 200


# ---- Redis 장애에도 Gemini 턴은 클로버로 낸다 ----


async def test_redis_failure_still_spends_clover(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """🔴 버스트 검사가 Redis 장애로 깨져도 무료로 통과시키지 않는다 — 하루 무료분이 없는 사람에게 장애가 무료 턴을 주게 된다.
    차감은 Redis 를 쓰지 않아 장애 중에도 그대로 할 수 있다. 오늘 확인하지 않은 사용자라 확인을 묻지 않는다는 것도 함께 본다.

    🔴 **방이 실존해야 한다.** 더미 방이면 게이트가 실행되지 않는다(게이트가 조회 뒤에 있다 — 모듈 docstring). 방을 먼저
    만들고 그 뒤에 Redis를 고장내는 순서인 이유도 같다 — 셋업이 게이트를 안 타야 한다.
    """
    from redis.exceptions import ConnectionError as RedisConnectionError

    user = await _consented_user(db_client, db_session, clover_balance=100)
    room_id = await _setup_room(db_client, db_session, user)

    async def _raise_redis_error(*args: object, **kwargs: object) -> int:
        raise RedisConnectionError("redis down")

    monkeypatch.setattr(rate_limit_gate, "check_rate_limit", _raise_redis_error)
    monkeypatch.setattr(rate_limit_gate, "_last_redis_failure_reported_at", None)

    resp = await _send(db_client, room_id)

    assert resp.status_code == 200

    price = clover.CLOVER_MODEL_PRICES["gemini"].chat_turn
    await db_session.refresh(user)
    assert user.clover_balance == 100 - price
    assert [(row.kind, row.amount) for row in await _ledger_for(db_session, user.id)] == [("chat_spend", -price)]


# ---- 채팅은 하루 1회 확인을 묻지 않는다 ----


async def test_unconfirmed_without_balance_gets_shortage_not_confirmation(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """오늘 확인하지 않은 사용자의 잔액 부족은 확인 429 가 아니라 곧장 `CLOVER_REQUIRED` 다 — 채팅은 하루 1회 확인을 묻지
    않는다(하루 무료분이 없어 "무료분을 다 쓴 순간"이 없고, 확인은 그 순간에 묻던 것이다). 잔액이 있는 같은 셋업의 짝은 아래
    턴 기록 테스트다 — 확인 없이 깎인다.
    """
    user = await _consented_user(db_client, db_session, clover_balance=0)
    room_id = await _setup_room(db_client, db_session, user)

    resp = await _send(db_client, room_id)

    assert resp.status_code == 429
    assert resp.json()["detail"]["code"] == "CLOVER_REQUIRED"

    await db_session.refresh(user)
    assert user.clover_balance == 0
    assert await _ledger_for(db_session, user.id) == []


# ---- 첫 턴부터 클로버 턴으로 기록된다 ----


@pytest.mark.parametrize(
    ("exempt", "expected"),
    [
        pytest.param(False, ("clover", clover.CLOVER_MODEL_PRICES["gemini"].chat_turn), id="member"),
        pytest.param(True, ("skipped", 0), id="exempt"),
    ],
)
async def test_first_turn_is_recorded_by_how_it_was_paid(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    exempt: bool,
    expected: tuple[str, int],
) -> None:
    """하루 무료분이 없어 실제 방 전송의 첫 턴부터 클로버로 내고 턴 기록에도 그렇게 남는다(오늘 확인을 묻지 않는다). 같은
    셋업의 면제 계정은 깎지 않은 턴으로 남는다 — 회원 쪽 기록이 셋업만으로 나오지 않는다는 대조군이다."""
    user = await _consented_user(db_client, db_session, clover_balance=100, rate_limit_exempt=exempt)
    room_id = await _setup_room(db_client, db_session, user)

    resp = await _send(db_client, room_id)

    assert resp.status_code == 200
    turns = (await db_session.scalars(select(ChatTurn).where(ChatTurn.chat_room_id == room_id))).all()
    assert [(t.charge_source, t.clover_amount) for t in turns] == [expected]
