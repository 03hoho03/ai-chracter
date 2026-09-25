"""`GET /me/clover/ledger`.

이 파일이 검증하는 성질(범주 필터·권한 포함):

1. 커서 페이징 경계 — `limit+1` 판정과 동률 `created_at`에서 2차 키(`id`) 정렬. 빨개지는
   조건: 2차 키가 없으면 같은 트랜잭션에 든 여러 행(테스트 트랜잭션 안에서는 `created_at`
   server_default가 전부 같은 값이다, `apps/api/CLAUDE.md` "테스트 인프라")이 페이지 경계에서
   중복되거나 빠진다.
2. `kind` → 범주 맵이 `CloverKind` 전 값을 덮는다(누락 0건).
3. 범주 필터: `category=use|earn|expire` 각각이 맞는 행만 돌려준다.
4. 권한: 남의 원장이 보이지 않는다.

셋업은 API(`grant`/`spend`)를 거치지 않고 원장 행을 직접 만든다 — 이 파일이 검증하는 것은
`GET /me/clover/ledger`의 필터·정렬·페이징이지 잔액 판정 로직이 아니라서다.
"""

import uuid
from typing import get_args

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from api.clover.router import CLOVER_KIND_CATEGORY, CLOVER_LEDGER_PAGE_SIZE
from api.core.clover import CloverKind
from api.db.models.auth import User
from api.db.models.clover import CloverLedger
from factories import _login_as, _make_user


async def _logged_in(db_client: httpx.AsyncClient, db_session: AsyncSession) -> User:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    return user


def _ledger_row(*, user_id: uuid.UUID, kind: str, amount: int = 10, balance_after: int = 10) -> CloverLedger:
    # idempotency_key는 비운다 — Postgres는 NULL을 중복으로 치지 않으므로 여러 행을 자유롭게
    # 만들 수 있다(`db/models/clover.py` docstring).
    return CloverLedger(user_id=user_id, amount=amount, balance_after=balance_after, kind=kind)


# ── kind → 범주 맵 ────────────────────────────────────────────────────────────
def test_kind_category_map_covers_every_clover_kind() -> None:
    """빨개지는 조건: 새 `CloverKind`를 추가하고 `CLOVER_KIND_CATEGORY`에 안 넣으면 실패한다."""
    assert set(CLOVER_KIND_CATEGORY.keys()) == set(get_args(CloverKind))


# ── 커서 페이징 경계 ──────────────────────────────────────────────────────
async def test_ledger_pagination_splits_ties_by_id_without_gaps_or_duplicates(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _logged_in(db_client, db_session)
    total = CLOVER_LEDGER_PAGE_SIZE + 5
    for i in range(total):
        db_session.add(_ledger_row(user_id=user.id, kind="attendance_grant", amount=i, balance_after=i))
    # 한 트랜잭션 안에서 커밋하므로 전부 같은 `created_at`(server_default)을 받는다 — 2차 키
    # (`id`)만이 이 페이지 경계를 결정한다.
    await db_session.commit()

    first = await db_client.get("/me/clover/ledger", params={"category": "earn"})
    assert first.status_code == 200
    first_body = first.json()
    assert len(first_body["items"]) == CLOVER_LEDGER_PAGE_SIZE
    assert first_body["nextCursor"] is not None

    second = await db_client.get(
        "/me/clover/ledger", params={"category": "earn", "cursor": first_body["nextCursor"]}
    )
    second_body = second.json()
    assert len(second_body["items"]) == total - CLOVER_LEDGER_PAGE_SIZE
    assert second_body["nextCursor"] is None

    first_ids = {item["id"] for item in first_body["items"]}
    second_ids = {item["id"] for item in second_body["items"]}
    # 2차 키가 없으면 여기서 중복(합이 total보다 큼) 또는 누락(합이 total보다 작음)이 난다.
    assert first_ids.isdisjoint(second_ids)
    assert len(first_ids) + len(second_ids) == total


# ── 범주 필터 ──────────────────────────────────────────────────────────────────
async def test_ledger_category_filter_returns_only_matching_kinds(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _logged_in(db_client, db_session)
    db_session.add_all(
        [
            _ledger_row(user_id=user.id, kind="chat_spend", amount=-10, balance_after=0),
            _ledger_row(user_id=user.id, kind="attendance_grant", amount=100, balance_after=100),
            _ledger_row(user_id=user.id, kind="expire_burn", amount=-5, balance_after=95),
        ]
    )
    await db_session.commit()

    use_resp = await db_client.get("/me/clover/ledger", params={"category": "use"})
    earn_resp = await db_client.get("/me/clover/ledger", params={"category": "earn"})
    expire_resp = await db_client.get("/me/clover/ledger", params={"category": "expire"})

    assert [item["kind"] for item in use_resp.json()["items"]] == ["chat_spend"]
    assert [item["kind"] for item in earn_resp.json()["items"]] == ["attendance_grant"]
    assert [item["kind"] for item in expire_resp.json()["items"]] == ["expire_burn"]
    # 응답에 실린 category도 맞다 — FE가 이 값을 그대로 쓰고 같은 맵을 다시 두지 않는다.
    assert use_resp.json()["items"][0]["category"] == "use"
    assert earn_resp.json()["items"][0]["category"] == "earn"
    assert expire_resp.json()["items"][0]["category"] == "expire"


# ── 권한 ──────────────────────────────────────────────────────────────────────
async def test_ledger_only_shows_the_caller_own_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    db_session.add(_ledger_row(user_id=owner.id, kind="attendance_grant", amount=100, balance_after=100))
    await db_session.commit()
    await _login_as(db_client, other.id)

    resp = await db_client.get("/me/clover/ledger", params={"category": "earn"})

    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_ledger_requires_a_session(db_client: httpx.AsyncClient) -> None:
    assert (await db_client.get("/me/clover/ledger", params={"category": "earn"})).status_code == 401
