"""consent-gate-goal-prompt.md CG-3·CG-4·CG-9, S2: `require_legal_consent`가 "막는다" 25개에
붙어 있고 "연다" 16개에는 안 붙어 있는지 3층으로 검증한다(consent-gate-progress.md I-2).
개수는 persona-goal-prompt.md §3-3이 출처다(대화 프로필 차단 4·개방 1 추가 — CG-4 표의 21+15는 역사 기록).

(a) 라우트 테이블 내성검사 — `app.routes`를 순회해 25개/16개의 실제 데코레이터를 대조한다.
    이 저장소가 신형 FastAPI(0.139) 내부 구조를 쓴다 — `app.routes`는 평범한 `APIRoute` 목록이
    아니라 `_IncludedRouter`(`app.include_router()`의 결과)로 감싸여 있어, 공개 API인
    `fastapi.routing.iter_route_contexts()`로 펼쳐야 각 라우트의 `.dependant`에 닿는다
    (`fastapi/openapi/utils.py`의 `get_openapi`가 스키마를 만들 때 쓰는 것과 같은 경로).
(b) 25개에 최소 요청 → 403 + `LEGAL_RECONSENT_REQUIRED`. `require_legal_consent`가
    데코레이터든(21개) 시그니처든(SSE 4개) `dependant.dependencies`의 나머지보다 먼저
    해석되므로(fastapi.dependencies.utils.solve_dependencies가 그 리스트를 순서대로 돌며 첫
    HTTPException에서 곧장 전파한다) 경로 파라미터는 실존할 필요가 없다 — 라우터 본문의
    소유권 조회(404) 이전에 게이트가 먼저 막는다.
(c) 16개 예외가 재동의가 실제로 필요한 상태에서도 여전히 200/204 — `require_legal_consent`를
    `get_current_user_id`에 잘못 넣는 변이(CG-7이 금지한 것)를 이 층만이 잡는다.

`factories._make_user`는 기본적으로 어떤 게시본보다 큰 `terms_version`/`privacy_version`을
채워 "이미 동의한 사용자"를 만든다 — 그래서 (b)·(c) 모두 자신이 테스트하려는 재동의-필요
상태를 `terms_version=None`(또는 `privacy_version=None`)으로 직접 명시해야 한다(그래야
"요청이 막히긴 하는데 이유가 다른" 오탐을 피한다).
"""

import uuid

import httpx
import pytest
from fastapi import routing as fastapi_routing
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.security import hash_password
from api.db.models import AssetKind, ChatMessage, ChatMessageRole, ChatRoom, Notification, User, UserPersona
from api.legal.dependencies import require_legal_consent
from api.main import app
from factories import _get_genre, _login_as, _make_asset, _make_published, _make_published_story, _make_user

# ---- (a)/(b) 공통: "막는다" 25개. path는 실제 라우트 경로(=(a)의 조회 키이자 (b)의 URL 템플릿) ----

_BLOCKED_REQUESTS: list[tuple[str, str, dict[str, object] | None]] = [
    ("POST", "/chat-rooms", {"contentId": str(uuid.uuid4()), "contentType": "character"}),
    ("PATCH", "/chat-rooms/{room_id}", {"name": "새 이름"}),
    ("POST", "/chat-rooms/{room_id}/acknowledge-version-upgrade", None),
    ("POST", "/chat-rooms/{room_id}/change-starting-setup", {"startingSetupId": str(uuid.uuid4())}),
    ("POST", "/chat-rooms/{room_id}/messages", {"content": "안녕"}),
    ("PATCH", "/chat-rooms/{room_id}/messages/{message_id}", {"content": "안녕"}),
    ("POST", "/chat-rooms/{room_id}/pin-latest-version", None),
    ("POST", "/chat-rooms/{room_id}/regenerate", None),
    ("POST", "/chat-rooms/{room_id}/reset", None),
    ("POST", "/preview-sessions", {}),
    ("POST", "/preview-sessions/{id}/messages", {"content": "안녕"}),
    (
        "POST",
        "/images/generate",
        {"prompt": "고양이", "model": "v1", "style": "base", "aspectRatio": "1:1"},
    ),
    ("POST", "/contents", {"type": "character"}),
    ("PATCH", "/contents/{id}/draft", {}),
    ("DELETE", "/contents/{id}/draft", None),
    ("POST", "/contents/{id}/draft/reset", None),
    ("PATCH", "/contents/{id}/visibility", {"visibility": "public"}),
    ("POST", "/contents/{id}/publish", None),
    ("POST", "/assets/presigned-upload", {"contentType": "image/png", "purpose": "profile-image"}),
    ("POST", "/assets/{asset_id}/complete", None),
    (
        "POST",
        "/assets/{asset_id}/register-situational-image",
        {
            "entityId": str(uuid.uuid4()),
            "contentVersionId": str(uuid.uuid4()),
            "triggerCondition": "조건",
            "order": 1,
        },
    ),
    # persona-goal-prompt.md §3-3 — 대화 프로필 쓰기 4개(삭제는 아래 "연다")
    ("POST", "/me/personas", {"name": "하늘", "gender": None, "description": "", "setAsDefault": False}),
    ("PUT", "/me/personas/{persona_id}", {"name": "하늘", "gender": None, "description": ""}),
    ("PUT", "/me/default-persona", {"personaId": None}),
    ("PUT", "/chat-rooms/{room_id}/persona", {"personaId": None}),
]

# ---- (a)/(c) 공통: "연다" 16개 ----

_OPEN_PATHS: list[tuple[str, str]] = [
    ("POST", "/legal/consent"),
    ("DELETE", "/me"),
    ("PATCH", "/me/password"),
    ("POST", "/contents/{id}/report"),
    ("POST", "/appeals"),
    ("POST", "/inquiries"),
    ("PATCH", "/notifications/{notification_id}/read"),
    ("PATCH", "/me/profile"),
    ("POST", "/contents/{id}/favorite"),
    ("DELETE", "/contents/{id}/favorite"),
    ("POST", "/contents/{id}/like"),
    ("DELETE", "/contents/{id}/like"),
    ("DELETE", "/me/generated-images/{asset_id}"),
    ("DELETE", "/chat-rooms/{room_id}"),
    ("DELETE", "/chat-rooms/{room_id}/messages/{message_id}"),
    ("DELETE", "/me/personas/{persona_id}"),  # persona-goal-prompt.md §3-3 — CG-4 "자기 데이터 삭제"
]


# ---- (a) 라우트 테이블 내성검사 ----


def _routes_by_method_and_path() -> dict[tuple[str, str], APIRoute]:
    routes: dict[tuple[str, str], APIRoute] = {}
    for context in fastapi_routing.iter_route_contexts(app.routes):
        route = context.original_route
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods or ():
            routes[(method, route.path)] = route
    return routes


def test_blocked_endpoints_all_carry_the_consent_gate() -> None:
    routes = _routes_by_method_and_path()
    for method, path, _body in _BLOCKED_REQUESTS:
        route = routes.get((method, path))
        assert route is not None, f"route not found: {method} {path}"
        dependency_calls = [dep.call for dep in route.dependant.dependencies]
        assert require_legal_consent in dependency_calls, f"{method} {path} is missing require_legal_consent"


def test_open_endpoints_never_carry_the_consent_gate() -> None:
    routes = _routes_by_method_and_path()
    for method, path in _OPEN_PATHS:
        route = routes.get((method, path))
        assert route is not None, f"route not found: {method} {path}"
        dependency_calls = [dep.call for dep in route.dependant.dependencies]
        assert require_legal_consent not in dependency_calls, f"{method} {path} must not require consent"


# ---- (b) 25개 최소 요청 → 403 ----

_DUMMY_IDS = {
    "room_id": str(uuid.uuid4()),
    "message_id": str(uuid.uuid4()),
    "id": str(uuid.uuid4()),
    "asset_id": str(uuid.uuid4()),
    "persona_id": str(uuid.uuid4()),
}


@pytest.mark.parametrize(
    ("method", "path_template", "body"),
    _BLOCKED_REQUESTS,
    ids=[f"{method} {path}" for method, path, _body in _BLOCKED_REQUESTS],
)
async def test_blocked_endpoint_returns_403_without_consent(
    method: str,
    path_template: str,
    body: dict[str, object] | None,
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = _make_user(terms_version=None)
    db_session.add(user)
    await db_session.flush()
    await _make_published(db_session, kind="terms", version="2099-01-01", requires_reconsent=True)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.request(method, path_template.format(**_DUMMY_IDS), json=body)

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "LEGAL_RECONSENT_REQUIRED"


# ---- (c) 16개 예외 — 재동의가 실제로 필요한 상태에서도 200/204 ----


async def _unconsented_user(db_client: httpx.AsyncClient, db_session: AsyncSession) -> User:
    """`_make_user`는 기본적으로 이미 동의한 사용자를 만들므로, "재동의가 실제로 필요한
    상태"를 이 테스트가 `terms_version=None`/`privacy_version=None`으로 직접 다시 만든다 —
    그래야 (c)가 증명하려는 것(예외는 그 상태에서도 안 막힌다)이 성립한다."""
    user = _make_user(terms_version=None, privacy_version=None)
    db_session.add(user)
    await db_session.flush()
    await _make_published(db_session, kind="terms", version="2099-01-01", requires_reconsent=True)
    await _make_published(db_session, kind="privacy", version="2099-02-01", requires_reconsent=True)
    await db_session.commit()
    await _login_as(db_client, user.id)
    return user


async def _owned_chat_room(db_session: AsyncSession, user: User) -> ChatRoom:
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    room = ChatRoom(user_id=user.id, content_id=content.id, content_version_id=content.current_published_version_id)
    db_session.add(room)
    await db_session.flush()
    return room


async def test_legal_consent_still_open_without_consent(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _unconsented_user(db_client, db_session)

    resp = await db_client.post("/legal/consent", json={"kind": "terms", "version": "2099-01-01"})

    assert resp.status_code == 204


async def test_withdraw_still_open_without_consent(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await _unconsented_user(db_client, db_session)

    resp = await db_client.delete("/me")

    assert resp.status_code == 204


async def test_change_password_still_open_without_consent(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user(password_hash=hash_password("oldpassword123"), terms_version=None)
    db_session.add(user)
    await db_session.flush()
    await _make_published(db_session, kind="terms", version="2099-01-01", requires_reconsent=True)
    await db_session.commit()
    await _login_as(db_client, user.id)

    resp = await db_client.patch(
        "/me/password", json={"currentPassword": "oldpassword123", "newPassword": "newpassword456"}
    )

    assert resp.status_code == 204


async def test_report_still_open_without_consent(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = await _unconsented_user(db_client, db_session)
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    resp = await db_client.post(f"/contents/{content.id}/report", json={"reasonCategory": "spam"})

    assert resp.status_code == 204


async def test_appeal_still_open_without_consent(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await _unconsented_user(db_client, db_session)

    resp = await db_client.post(
        "/appeals",
        json={"targetKind": "publish-rejection", "targetId": str(uuid.uuid4()), "reasonText": "이의 있습니다"},
    )

    assert resp.status_code == 201


async def test_inquiry_still_open_without_consent(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await _unconsented_user(db_client, db_session)

    resp = await db_client.post("/inquiries", json={"category": "bug", "title": "제목", "body": "내용"})

    assert resp.status_code == 201


async def test_notification_read_still_open_without_consent(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _unconsented_user(db_client, db_session)
    notification = Notification(user_id=user.id)
    db_session.add(notification)
    await db_session.flush()
    await db_session.commit()

    resp = await db_client.patch(f"/notifications/{notification.id}/read")

    assert resp.status_code == 200


async def test_profile_update_still_open_without_consent(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _unconsented_user(db_client, db_session)

    resp = await db_client.patch("/me/profile", json={"nickname": "새닉네임"})

    assert resp.status_code == 200


@pytest.mark.parametrize(
    ("method", "path_template"),
    [
        ("POST", "/contents/{id}/favorite"),
        ("DELETE", "/contents/{id}/favorite"),
        ("POST", "/contents/{id}/like"),
        ("DELETE", "/contents/{id}/like"),
    ],
    ids=["favorite", "unfavorite", "like", "unlike"],
)
async def test_favorite_and_like_endpoints_still_open_without_consent(
    method: str, path_template: str, db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _unconsented_user(db_client, db_session)
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    await db_session.commit()

    resp = await db_client.request(method, path_template.format(id=content.id))

    assert resp.status_code == 204


async def test_delete_generated_image_still_open_without_consent(
    db_client: httpx.AsyncClient, db_session: AsyncSession, s3_bucket: None
) -> None:
    user = await _unconsented_user(db_client, db_session)
    asset = await _make_asset(db_session, owner_user_id=user.id, kind=AssetKind.GENERATED)
    await db_session.commit()

    resp = await db_client.delete(f"/me/generated-images/{asset.id}")

    assert resp.status_code == 204


async def test_delete_chat_room_still_open_without_consent(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _unconsented_user(db_client, db_session)
    room = await _owned_chat_room(db_session, user)
    await db_session.commit()

    resp = await db_client.delete(f"/chat-rooms/{room.id}")

    assert resp.status_code == 204


async def test_delete_chat_message_still_open_without_consent(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _unconsented_user(db_client, db_session)
    room = await _owned_chat_room(db_session, user)
    message = ChatMessage(chat_room_id=room.id, role=ChatMessageRole.USER, content="안녕")
    db_session.add(message)
    await db_session.flush()
    await db_session.commit()

    resp = await db_client.delete(f"/chat-rooms/{room.id}/messages/{message.id}")

    assert resp.status_code == 204


async def test_delete_persona_still_open_without_consent(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _unconsented_user(db_client, db_session)
    persona = UserPersona(user_id=user.id, name="하늘")
    db_session.add(persona)
    await db_session.flush()
    await db_session.commit()

    resp = await db_client.delete(f"/me/personas/{persona.id}")

    assert resp.status_code == 204
