"""가입하면서 받은 대화 프로필 이름(`personaName`) — 이메일 가입·구글 온보딩·카카오 온보딩 세 경로.

이름이 있으면 사용자를 만드는 같은 트랜잭션에서 프로필 하나를 만들고 기본으로 둔다. 비었거나 없으면 만들지 않는다(닉네임으로
채우지 않는다 — 닉네임은 프롬프트에 싣지 않는 계정 정보다). 기존 행을 재사용하는 분기는 둘로 갈린다.

- 방치된 미인증 행을 덮어쓰는 분기(이메일 재가입, 카카오의 미인증 이메일 행 대체): 그 행은 남이 같은 이메일로 해 둔 가입일
  수 있으므로 남아 있던 프로필을 지우고 이번에 받은 이름으로 새로 만든다.
- 이미 가입된 사용자로 이어지는 소셜 분기(같은 구글·카카오 계정): 쓰던 프로필이 있으면 건드리지 않고, 없을 때만 만든다.
"""

import uuid
from collections.abc import Awaitable, Callable

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.google_oauth import PendingGoogleSignup, store_pending_google_signup
from api.auth.kakao_oauth import KakaoPendingSignup, store_pending_kakao_signup
from api.db.models import User, UserPersona
from factories import _make_user

_FORM = {
    "nickname": "닉네임",
    "birthDate": "2000-01-01",
    "termsAgreed": True,
    "privacyAgreed": True,
    "transferAgreed": True,
}

Submit = Callable[[httpx.AsyncClient, dict[str, object]], Awaitable[tuple[httpx.Response, str]]]


def _new_email() -> str:
    return f"persona-{uuid.uuid4()}@example.com"


async def _email_signup(
    client: httpx.AsyncClient, extra: dict[str, object], email: str | None = None
) -> tuple[httpx.Response, str]:
    email = email or _new_email()
    resp = await client.post("/auth/signup", json={**_FORM, "email": email, "password": "password123", **extra})
    return resp, email


async def _google_onboarding(
    client: httpx.AsyncClient, extra: dict[str, object], sub: str | None = None, email: str | None = None
) -> tuple[httpx.Response, str]:
    email = email or _new_email()
    token = await store_pending_google_signup(PendingGoogleSignup(sub=sub or f"google-{uuid.uuid4()}", email=email))
    client.cookies.set("oauth_pending_google", token)
    return await client.post("/auth/onboarding/google", json={**_FORM, **extra}), email


async def _kakao_onboarding(
    client: httpx.AsyncClient, extra: dict[str, object], kakao_id: str | None = None, email: str | None = None
) -> tuple[httpx.Response, str]:
    email = email or _new_email()
    token = await store_pending_kakao_signup(
        KakaoPendingSignup(kakao_id=kakao_id or str(uuid.uuid4().int)[:12], email=email)
    )
    client.cookies.set("oauth_pending_kakao", token)
    return await client.post("/auth/onboarding/kakao", json={**_FORM, **extra}), email


_PATHS = [
    pytest.param(_email_signup, 201, id="email"),
    pytest.param(_google_onboarding, 200, id="google"),
    pytest.param(_kakao_onboarding, 200, id="kakao"),
]


async def _personas_of(db_session: AsyncSession, email: str) -> tuple[list[tuple[uuid.UUID, str]], uuid.UUID | None]:
    """(프로필 (id, 이름) 목록, 기본 프로필 id). 컬럼 select 라 앱 세션이 커밋한 값을 identity map 캐시 없이 읽는다."""
    user_id = await db_session.scalar(select(User.id).where(User.email == email))
    assert user_id is not None
    rows = (
        await db_session.execute(
            select(UserPersona.id, UserPersona.name).where(UserPersona.user_id == user_id).order_by(UserPersona.id)
        )
    ).all()
    default_id = await db_session.scalar(select(User.default_persona_id).where(User.id == user_id))
    return [(row.id, row.name) for row in rows], default_id


# ---- 신규 가입 ----


@pytest.mark.parametrize(("submit", "ok_status"), _PATHS)
async def test_signup_with_persona_name_creates_it_as_default(
    submit: Submit, ok_status: int, db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    resp, email = await submit(db_client, {"personaName": "  하늘  "})

    assert resp.status_code == ok_status
    personas, default_id = await _personas_of(db_session, email)
    assert [name for _, name in personas] == ["하늘"]
    assert default_id == personas[0][0]


@pytest.mark.parametrize(("submit", "ok_status"), _PATHS)
@pytest.mark.parametrize(
    "extra",
    [
        pytest.param({}, id="omitted"),
        pytest.param({"personaName": None}, id="null"),
        pytest.param({"personaName": ""}, id="empty"),
        pytest.param({"personaName": "   "}, id="blank"),
    ],
)
async def test_signup_without_persona_name_creates_none(
    submit: Submit, ok_status: int, extra: dict[str, object], db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """이름을 비워 두면 프로필이 없다 — 닉네임으로 채우지 않는다. 첫 대화 전에 화면이 이름을 받는다."""
    resp, email = await submit(db_client, extra)

    assert resp.status_code == ok_status
    assert await _personas_of(db_session, email) == ([], None)


@pytest.mark.parametrize(("submit", "ok_status"), _PATHS)
@pytest.mark.parametrize(
    "name",
    [pytest.param("a:b", id="colon"), pytest.param("*별*", id="markdown"), pytest.param("가" * 21, id="21-chars")],
)
async def test_signup_with_invalid_persona_name_returns_422_without_a_user(
    submit: Submit, ok_status: int, name: str, db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """프로필 화면과 같은 이름 규칙이다. 가입 자체가 거절돼 사용자도 생기지 않는다."""
    resp, email = await submit(db_client, {"personaName": name})

    assert resp.status_code == 422
    assert await db_session.scalar(select(func.count()).select_from(User).where(User.email == email)) == 0


# ---- 방치된 미인증 행 덮어쓰기: 남아 있던 프로필을 바꾼다 ----


async def _abandoned_signup(db_client: httpx.AsyncClient, persona_name: str | None) -> str:
    """미인증 이메일 가입을 하나 남겨 둔다(앞선 가입자가 정한 프로필 이름이 있을 수 있다)."""
    resp, email = await _email_signup(db_client, {"personaName": persona_name} if persona_name else {})
    assert resp.status_code == 201
    return email


async def _overwrite_by_email(db_client: httpx.AsyncClient, email: str, extra: dict[str, object]) -> httpx.Response:
    resp, _ = await _email_signup(db_client, extra, email=email)
    return resp


async def _overwrite_by_kakao(db_client: httpx.AsyncClient, email: str, extra: dict[str, object]) -> httpx.Response:
    resp, _ = await _kakao_onboarding(db_client, extra, email=email)
    return resp


_OVERWRITES = [
    pytest.param(_overwrite_by_email, 201, id="email-resignup"),
    pytest.param(_overwrite_by_kakao, 200, id="kakao-replacement"),
]


@pytest.mark.parametrize(("overwrite", "ok_status"), _OVERWRITES)
async def test_overwriting_abandoned_signup_replaces_its_persona_with_the_new_name(
    overwrite: Callable[[httpx.AsyncClient, str, dict[str, object]], Awaitable[httpx.Response]],
    ok_status: int,
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """앞선 가입자가 정한 이름이 새 가입자의 기본으로 남으면 안 된다 — 지우고 새로 만든다."""
    email = await _abandoned_signup(db_client, "앞사람")
    [(previous_id, _)], _ = await _personas_of(db_session, email)

    resp = await overwrite(db_client, email, {"personaName": "새사람"})

    assert resp.status_code == ok_status
    personas, default_id = await _personas_of(db_session, email)
    assert [name for _, name in personas] == ["새사람"]
    assert personas[0][0] != previous_id
    assert default_id == personas[0][0]


@pytest.mark.parametrize(("overwrite", "ok_status"), _OVERWRITES)
async def test_overwriting_abandoned_signup_without_a_name_leaves_no_persona(
    overwrite: Callable[[httpx.AsyncClient, str, dict[str, object]], Awaitable[httpx.Response]],
    ok_status: int,
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """새 가입자가 이름을 비워 두면 앞사람 프로필도 남지 않는다 — 0개가 맞다."""
    email = await _abandoned_signup(db_client, "앞사람")

    resp = await overwrite(db_client, email, {})

    assert resp.status_code == ok_status
    assert await _personas_of(db_session, email) == ([], None)


@pytest.mark.parametrize(("overwrite", "ok_status"), _OVERWRITES)
async def test_overwriting_abandoned_signup_without_persona_creates_the_new_one(
    overwrite: Callable[[httpx.AsyncClient, str, dict[str, object]], Awaitable[httpx.Response]],
    ok_status: int,
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    email = await _abandoned_signup(db_client, None)

    resp = await overwrite(db_client, email, {"personaName": "새사람"})

    assert resp.status_code == ok_status
    personas, default_id = await _personas_of(db_session, email)
    assert [name for _, name in personas] == ["새사람"]
    assert default_id == personas[0][0]


# ---- 이미 가입된 사용자로 이어지는 소셜 온보딩: 있으면 그대로, 없을 때만 만든다 ----


async def _existing_social_user(db_session: AsyncSession, provider: str, *, with_persona: bool) -> tuple[User, str]:
    identifier = f"{provider}-{uuid.uuid4()}"
    user = _make_user(**({"google_sub": identifier} if provider == "google" else {"kakao_id": identifier}))
    db_session.add(user)
    await db_session.flush()
    if with_persona:
        persona = UserPersona(user_id=user.id, name="쓰던 것")
        db_session.add(persona)
        await db_session.flush()
        user.default_persona_id = persona.id
    await db_session.commit()
    return user, identifier


async def _resubmit(client: httpx.AsyncClient, provider: str, identifier: str, email: str) -> httpx.Response:
    extra: dict[str, object] = {"personaName": "새 이름"}
    if provider == "google":
        resp, _ = await _google_onboarding(client, extra, sub=identifier, email=email)
    else:
        resp, _ = await _kakao_onboarding(client, extra, kakao_id=identifier, email=email)
    return resp


@pytest.mark.parametrize("provider", ["google", "kakao"])
async def test_onboarding_existing_social_user_keeps_their_persona(
    provider: str, db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """두 탭에서 같은 가입을 냈거나 이미 쓰던 계정이면, 쓰던 프로필과 기본을 그대로 둔다."""
    user, identifier = await _existing_social_user(db_session, provider, with_persona=True)
    before = await _personas_of(db_session, user.email)

    resp = await _resubmit(db_client, provider, identifier, user.email)

    assert resp.status_code == 200
    assert await _personas_of(db_session, user.email) == before


@pytest.mark.parametrize("provider", ["google", "kakao"])
async def test_onboarding_existing_social_user_without_persona_creates_it(
    provider: str, db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user, identifier = await _existing_social_user(db_session, provider, with_persona=False)

    resp = await _resubmit(db_client, provider, identifier, user.email)

    assert resp.status_code == 200
    personas, default_id = await _personas_of(db_session, user.email)
    assert [name for _, name in personas] == ["새 이름"]
    assert default_id == personas[0][0]
