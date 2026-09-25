"""어드민 클로버 지급·회수·원장 조회.

이 파일이 고정하는 성질 셋:

1. **지급/회수와 `admin_action_logs` 행이 한 트랜잭션이다.** 하나만 남는 상태가 없다.
2. 🔴 **멱등키가 더블클릭을 막는다.** `rate_limit_exempt` 토글은 *"같은 값을 다시 적용해도
   막지 않는다"*(`admin/users.py`의 docstring)가 성립했지만 — 대입이 멱등이라서다 — 지급은
   **누적**이라 그 문장을 옮기면 두 번 누른 만큼 돈이 늘어난다.
3. **회수는 잔액을 음수로 만들지 않는다.** `revoke`의 `guard=True`가 그 자리다.
"""

import uuid
from datetime import UTC, datetime

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.clover import CloverLotShortfallError
from api.db.models import AdminActionLog
from api.db.models.auth import User
from api.db.models.clover import CloverLedger
from factories import _create_admin, _login_as_admin, _make_user, _make_user_with_clover_lot


async def _ledger_rows(db: AsyncSession, user_id: uuid.UUID) -> list[CloverLedger]:
    """원장 행 전부. **정렬에 `id` tiebreaker를 붙인다** — `created_at`의 `server_default`는
    Postgres에서 트랜잭션 시작 시각이라 한 트랜잭션에 쌓인 행이 전부 동률이다
    (`tests/test_core_clover.py`의 같은 헬퍼와 같은 이유).
    ⚠️ `id`가 uuid4라 이 정렬은 "결정적"일 뿐 "삽입 순서"가 아니다 — 여러 행을 단언하는
    테스트는 순서가 아니라 **내용**으로 비교한다."""
    return list(
        (
            await db.scalars(
                sa.select(CloverLedger)
                .where(CloverLedger.user_id == user_id)
                .order_by(CloverLedger.created_at, CloverLedger.id)
            )
        ).all()
    )


async def _balance(db: AsyncSession, user_id: uuid.UUID) -> int:
    """ORM 인스턴스가 아니라 **DB 행**을 다시 읽는다 — 라우트가 바꾼 값을 테스트 세션의 낡은
    인스턴스로 보면 통과해야 할 것이 통과하지 않는다."""
    balance = await db.scalar(sa.select(User.clover_balance).where(User.id == user_id))
    assert balance is not None
    return balance


async def _seed_user(db: AsyncSession, **overrides: object) -> uuid.UUID:
    """유저와, `clover_balance`가 있으면 그 값과 매칭되는 로트 1행을 만들고 **id만** 돌려준다.

    🔴 ORM 인스턴스를 들고 다니지 않는 것이 요점이다. 라우트가 409로 끝나며 SAVEPOINT를
    되감으면 테스트 세션의 그 인스턴스가 만료 상태로 남고, 이후 `user_id` 한 번이
    지연 로드를 일으켜 `MissingGreenlet`으로 터진다(실측). id는 파이썬 값이라 그 경로가 없다.

    `revoke()`가 로트 인지로 바뀌어, 로트 0행인 유저를
    회수하면 `CloverLotShortfallError`가 난다(`[revoke]` 파라미터 케이스). 매칭 로트를
    항상 만들어 두면 지급(양수) 케이스는 영향 없이 그대로 통과한다.
    """
    balance = overrides.pop("clover_balance", 0)
    assert isinstance(balance, int)
    user = await _make_user_with_clover_lot(db, clover_balance=balance, **overrides)
    await db.commit()
    user_id = user.id
    assert isinstance(user_id, uuid.UUID)
    return user_id


async def _admin_login(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)


# ---- 지급·회수가 원장과 감사 로그를 한 트랜잭션에 남긴다 --------------------------


@pytest.mark.parametrize(
    ("amount", "expected_kind", "expected_action_type"),
    [
        pytest.param(50, "admin_grant", "user-clover-grant", id="grant"),
        pytest.param(-30, "admin_revoke", "user-clover-revoke", id="revoke"),
    ],
)
async def test_admin_clover_writes_ledger_and_exactly_one_action_log(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    amount: int,
    expected_kind: str,
    expected_action_type: str,
) -> None:
    """지급/회수 양방향을 한 함수로 본다 — 한쪽만 보면 삼항(`grant`/`revoke`)의 반대편이
    통째로 미검증으로 남는다.

    **빨개지는 조건**: 원장과 액션 로그를 갈라 커밋하면 한쪽만 남는 상태가 생기고, 삼항을
    한 값으로 고정하면 반대 케이스의 `action_type`이 어긋난다."""
    user_id = await _seed_user(db_session, clover_balance=100)
    await _admin_login(db_client, db_session)

    resp = await db_client.post(
        f"/admin/users/{user_id}/clover",
        json={"amount": amount, "adminComment": "운영 보상", "idempotencyKey": str(uuid.uuid4())},
    )
    assert resp.status_code == 204

    assert await _balance(db_session, user_id) == 100 + amount

    rows = await _ledger_rows(db_session, user_id)
    assert len(rows) == 1
    assert rows[0].amount == amount
    assert rows[0].kind == expected_kind
    assert rows[0].balance_after == 100 + amount

    logs = (
        await db_session.scalars(
            sa.select(AdminActionLog).where(AdminActionLog.target_user_id == user_id)
        )
    ).all()
    assert len(logs) == 1
    assert logs[0].action_type == expected_action_type
    assert logs[0].reason_text == "운영 보상"


# ---- 멱등키가 더블클릭을 막는다 --------------------------------------------------


async def test_same_idempotency_key_twice_returns_409_and_grants_once(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """🔴 `ux_clover_ledger_idempotency_key`를 만든 **원래 목적**이
    이 경로다. 토글 선례의 *"같은 값 재적용을 막지 않는다"*를 그대로 옮기면 더블클릭이 곧
    중복 지급이 된다 — 지급은 대입이 아니라 누적이기 때문이다.

    **빨개지는 조건**: 멱등키를 원장에 안 싣거나 유니크 위반을 409로 번역하지 않으면 두 번째
    호출이 204를 내고 잔액 200 + 원장 2행이 된다."""
    user_id = await _seed_user(db_session, clover_balance=0)
    await _admin_login(db_client, db_session)

    key = str(uuid.uuid4())
    body = {"amount": 100, "adminComment": "이벤트 보상", "idempotencyKey": key}

    first = await db_client.post(f"/admin/users/{user_id}/clover", json=body)
    assert first.status_code == 204

    second = await db_client.post(f"/admin/users/{user_id}/clover", json=body)
    assert second.status_code == 409

    assert await _balance(db_session, user_id) == 100
    assert len(await _ledger_rows(db_session, user_id)) == 1


async def test_different_idempotency_keys_grant_twice_on_purpose(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """같은 어드민이 같은 유저에게 같은 금액을 **의도적으로 두 번** 줄 수 있어야 한다 — 그래서
    키를 서버가 결정적으로 만들지 않고 클라이언트가 요청마다 보낸다(출석과 다른 점이다).

    **빨개지는 조건**: 키를 `(user, amount)`처럼 서버가 파생하면 두 번째가 409로 막힌다."""
    user_id = await _seed_user(db_session, clover_balance=0)
    await _admin_login(db_client, db_session)

    for _ in range(2):
        resp = await db_client.post(
            f"/admin/users/{user_id}/clover",
            json={"amount": 100, "adminComment": "두 번 준다", "idempotencyKey": str(uuid.uuid4())},
        )
        assert resp.status_code == 204

    assert await _balance(db_session, user_id) == 200
    assert len(await _ledger_rows(db_session, user_id)) == 2


# ---- 회수가 음수로 내려가지 않는다 ------------------------------------------------


async def test_revoke_more_than_balance_returns_422_and_leaves_balance_untouched(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`revoke`의 `guard=True`(`WHERE clover_balance >= -delta`)가 이 자리다. 오지급
    회수가 이미 쓴 만큼을 빚으로 남기지 않는다.

    **빨개지는 조건**: `revoke`를 `guard=False`로 바꾸면 잔액이 -20이 되고 원장 행이 생긴다."""
    user_id = await _seed_user(db_session, clover_balance=30)
    await _admin_login(db_client, db_session)

    resp = await db_client.post(
        f"/admin/users/{user_id}/clover",
        json={"amount": -50, "adminComment": "오지급 회수", "idempotencyKey": str(uuid.uuid4())},
    )
    assert resp.status_code == 422

    assert await _balance(db_session, user_id) == 30
    assert await _ledger_rows(db_session, user_id) == []


async def test_revoke_rolls_back_the_balance_cas_when_lots_are_insufficient(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """로트 없이 잔액만 있는 비정상 상태(Σ 불변식이 이미
    깨진 상태, 예: 백필 누락)에서 회수하면 `CloverLotShortfallError`가 나고, 그 예외가
    `admin/users.py`의 `db.begin_nested()` SAVEPOINT를 되감아 총액 CAS까지 롤백돼야 한다.

    `_seed_user`(매칭 로트를 항상 만드는 헬퍼)를 일부러 쓰지 않는다 — 로트가 0행인 상태를
    직접 만들어야 하기 때문이다(`_make_user`는 DB를 안 건드리는 순수 팩토리라 로트가 안 생긴다).

    🔴 **`user.id`를 요청 뒤에 다시 읽지 않는다** — `db.begin_nested()`가 예외로 되감기면
    (`_seed_user`의 docstring과 같은 이유) 세션의 그 인스턴스가 만료 상태로 남아, 이후
    `user.id` 접근 한 번이 지연 로드를 일으켜 `MissingGreenlet`으로 터진다(실측). 그래서
    요청 **전에** `user_id`를 파이썬 값으로 미리 뽑아 둔다.

    빨개지는 조건: SAVEPOINT 롤백이 안 되면 잔액만 30만큼 줄고 로트는 그대로라 Σ 불변식이
    깨진 채로 커밋된다 — 이 테스트는 잔액이 회수 시도 **전과 같은 값**으로 남는지를 본다.
    """
    user = _make_user(clover_balance=100)
    db_session.add(user)
    await db_session.commit()
    user_id = user.id
    await _admin_login(db_client, db_session)

    with pytest.raises(CloverLotShortfallError):
        await db_client.post(
            f"/admin/users/{user_id}/clover",
            json={
                "amount": -30,
                "adminComment": "로트 없는 유저 회수",
                "idempotencyKey": str(uuid.uuid4()),
            },
        )

    assert await _balance(db_session, user_id) == 100
    assert await _ledger_rows(db_session, user_id) == []


# ---- 오류 번역 ----------------------------------------------


async def test_blank_admin_comment_returns_422_without_touching_balance(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """토글 선례(`admin/users.py`의 `set_user_rate_limit_exempt`)와 같은 규칙이다."""
    user_id = await _seed_user(db_session, clover_balance=10)
    await _admin_login(db_client, db_session)

    resp = await db_client.post(
        f"/admin/users/{user_id}/clover",
        json={"amount": 10, "adminComment": "   ", "idempotencyKey": str(uuid.uuid4())},
    )
    assert resp.status_code == 422

    assert await _balance(db_session, user_id) == 10
    assert await _ledger_rows(db_session, user_id) == []


async def test_zero_amount_returns_422(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """의미 없는 0원 원장 행을 만들지 않는다 — `burn_all`이 잔액 0에서 아무것도 안 하는 것과
    같은 규칙이다."""
    user_id = await _seed_user(db_session, clover_balance=10)
    await _admin_login(db_client, db_session)

    resp = await db_client.post(
        f"/admin/users/{user_id}/clover",
        json={"amount": 0, "adminComment": "0원", "idempotencyKey": str(uuid.uuid4())},
    )
    assert resp.status_code == 422

    assert await _ledger_rows(db_session, user_id) == []


async def test_deleted_user_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id = await _seed_user(db_session, deleted_at=datetime.now(UTC), clover_balance=10)
    await _admin_login(db_client, db_session)

    resp = await db_client.post(
        f"/admin/users/{user_id}/clover",
        json={"amount": 10, "adminComment": "지급", "idempotencyKey": str(uuid.uuid4())},
    )
    assert resp.status_code == 404
    assert await _ledger_rows(db_session, user_id) == []


# ---- 유저 상세의 잔액 + 원장 조회 -------------------------------------------------


async def test_user_detail_exposes_clover_balance(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """유저 둘을 다른 잔액으로 조회한다 — 한쪽만 보면 상수를 내려도 통과하는 항진 테스트가
    된다(`test_user_detail_exposes_rate_limit_exempt`와 같은 이유)."""
    rich = _make_user(clover_balance=250)
    poor = _make_user(clover_balance=0)
    db_session.add_all([rich, poor])
    await db_session.commit()
    await _admin_login(db_client, db_session)

    rich_resp = await db_client.get(f"/admin/users/{rich.id}")
    assert rich_resp.status_code == 200
    assert rich_resp.json()["cloverBalance"] == 250

    poor_resp = await db_client.get(f"/admin/users/{poor.id}")
    assert poor_resp.status_code == 200
    assert poor_resp.json()["cloverBalance"] == 0


async def test_clover_ledger_list_is_newest_first_and_paginates(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """원장 조회는 어드민만이고 오프셋 3종 세트를 돌려준다.

    행을 **서로 다른 `created_at`으로** 심는다 — 같은 트랜잭션의 동률에 기대면 정렬 단언이
    무엇을 논증하는지 흐려진다(2차 키 `id`는 uuid4라 삽입 순서가 아니다).

    **빨개지는 조건**: `desc()`를 빼면 첫 페이지가 가장 오래된 행으로 시작한다."""
    user_id = await _seed_user(db_session, clover_balance=0)

    base = datetime(2026, 9, 19, 0, 0, tzinfo=UTC)
    for index in range(25):
        db_session.add(
            CloverLedger(
                user_id=user_id,
                amount=index + 1,
                balance_after=index + 1,
                kind="admin_grant",
                created_at=base.replace(minute=index),
            )
        )
    await db_session.commit()
    await _admin_login(db_client, db_session)

    first = await db_client.get(f"/admin/users/{user_id}/clover-ledger?page=1")
    assert first.status_code == 200
    payload = first.json()
    assert payload["totalCount"] == 25
    assert payload["totalPages"] == 2
    assert payload["page"] == 1
    assert len(payload["items"]) == 20
    assert payload["items"][0]["amount"] == 25

    second = await db_client.get(f"/admin/users/{user_id}/clover-ledger?page=2")
    assert second.status_code == 200
    assert len(second.json()["items"]) == 5
    assert second.json()["items"][-1]["amount"] == 1


async def test_clover_ledger_of_user_without_rows_is_empty(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`total_pages`가 0이다 — `-(-0 // 20)`은 0이지만 관례가 `if total_count else 0`으로
    명시하므로 그 값을 고정한다."""
    user_id = await _seed_user(db_session, clover_balance=0)
    await _admin_login(db_client, db_session)

    resp = await db_client.get(f"/admin/users/{user_id}/clover-ledger?page=1")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "page": 1, "totalPages": 0, "totalCount": 0}
