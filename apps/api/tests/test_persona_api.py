"""대화 프로필 CRUD·기본 지정·방 선택 API.

🔴 쓰기 경로의 소유권 검사가 이 기능의 유일한 방어선이다. 읽기 경로(`_build_prompt`,
`_preview_persona_dependency`)는 프로필 소유자를 다시 보지 않는다. 그래서
남의 프로필을 기본·방에 거는 모든 경로가 403인지를 여기서 하나씩 확인한다.

방 생성 두 경로(새 방 = 기본, 시작설정 변경 = 원래 방의 선택 승계)는 `test_chat_room_api.py`, 탈퇴는
`test_auth_me_api.py`, 재동의 게이트 분류는 `test_consent_gate_endpoints.py`에 있다.
"""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import ChatRoom, User, UserPersona
from factories import _get_genre, _login_as, _make_published_character, _make_user


async def _make_persona(
    db_session: AsyncSession, user_id: uuid.UUID, name: str = "하늘", **overrides: object
) -> UserPersona:
    persona = UserPersona(user_id=user_id, name=name, **overrides)
    db_session.add(persona)
    await db_session.flush()
    return persona


async def _logged_in_user(db_client: httpx.AsyncClient, db_session: AsyncSession) -> User:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _login_as(db_client, user.id)
    return user


async def _make_room(db_session: AsyncSession, user: User, persona_id: uuid.UUID | None = None) -> ChatRoom:
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    room = ChatRoom(
        user_id=user.id,
        content_id=content.id,
        content_version_id=content.current_published_version_id,
        persona_id=persona_id,
    )
    db_session.add(room)
    await db_session.flush()
    return room


async def _default_persona_id(db_session: AsyncSession, user_id: uuid.UUID) -> uuid.UUID | None:
    # 컬럼 select — 앱 세션이 커밋한 값을 identity map 캐시 없이 다시 읽는다.
    return await db_session.scalar(select(User.default_persona_id).where(User.id == user_id))


async def _room_persona_id(db_session: AsyncSession, room_id: uuid.UUID) -> uuid.UUID | None:
    return await db_session.scalar(select(ChatRoom.persona_id).where(ChatRoom.id == room_id))


def _create_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {"name": "하늘", "gender": "female", "description": "밤하늘을 좋아한다", "setAsDefault": False}
    body.update(overrides)
    return body


# ---- GET /me/personas ----


async def test_list_personas_returns_own_items_in_creation_order_with_default_and_max_count(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _logged_in_user(db_client, db_session)
    other = _make_user()
    db_session.add(other)
    await db_session.flush()
    now = datetime.now(UTC)
    # created_at을 일부러 이름 순서와 반대로 둬 "생성 순"과 "이름 순·삽입 순"을 가른다.
    later = await _make_persona(db_session, user.id, name="가", created_at=now)
    earlier = await _make_persona(db_session, user.id, name="나", gender="male", created_at=now - timedelta(minutes=1))
    await _make_persona(db_session, other.id, name="남의 것")
    user.default_persona_id = later.id
    await db_session.commit()

    resp = await db_client.get("/me/personas")

    assert resp.status_code == 200
    body = resp.json()
    assert [item["id"] for item in body["items"]] == [str(earlier.id), str(later.id)]
    assert body["items"][0]["name"] == "나"
    assert body["items"][0]["gender"] == "male"
    assert body["defaultPersonaId"] == str(later.id)
    assert body["maxCount"] == 10


async def test_list_personas_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get("/me/personas")
    assert resp.status_code == 401


# ---- POST /me/personas ----


async def test_create_persona_trims_and_stores_fields(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = await _logged_in_user(db_client, db_session)
    await db_session.commit()

    resp = await db_client.post(
        "/me/personas", json=_create_body(name="  하 늘  ", gender=None, description="  설명\n둘째 줄  ")
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "하 늘"
    assert body["gender"] is None
    assert body["description"] == "설명\n둘째 줄"
    stored = await db_session.scalar(
        select(UserPersona.name).where(UserPersona.user_id == user.id, UserPersona.id == uuid.UUID(body["id"]))
    )
    assert stored == "하 늘"


async def test_create_persona_accepts_boundary_lengths_and_empty_description(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _logged_in_user(db_client, db_session)
    await db_session.commit()

    long_resp = await db_client.post("/me/personas", json=_create_body(name="가" * 20, description="나" * 500))
    empty_resp = await db_client.post("/me/personas", json=_create_body(description=""))

    assert long_resp.status_code == 201
    assert empty_resp.status_code == 201
    assert empty_resp.json()["description"] == ""


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"name": "  "}, id="name-blank"),
        pytest.param({"name": "a:b"}, id="name-colon"),
        pytest.param({"name": "a\nb"}, id="name-newline"),
        pytest.param({"name": "a\rb"}, id="name-carriage-return"),
        pytest.param({"name": "가" * 21}, id="name-21-chars"),
        pytest.param({"description": "나" * 501}, id="description-501-chars"),
    ],
)
async def test_create_persona_rejects_invalid_fields_with_422(
    overrides: dict[str, object], db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _logged_in_user(db_client, db_session)
    await db_session.commit()

    resp = await db_client.post("/me/personas", json=_create_body(**overrides))

    assert resp.status_code == 422
    count = await db_session.scalar(select(func.count()).select_from(UserPersona).where(UserPersona.user_id == user.id))
    assert count == 0


async def test_create_eleventh_persona_returns_409(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = await _logged_in_user(db_client, db_session)
    for index in range(10):
        await _make_persona(db_session, user.id, name=f"프로필{index}")
    await db_session.commit()

    resp = await db_client.post("/me/personas", json=_create_body())

    assert resp.status_code == 409
    assert resp.json()["detail"] == "대화 프로필은 최대 10개까지 만들 수 있어요."
    count = await db_session.scalar(select(func.count()).select_from(UserPersona).where(UserPersona.user_id == user.id))
    assert count == 10


async def test_create_tenth_persona_succeeds(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """상한 경계의 다른 쪽 — 9개에서 10번째는 된다(`>=`/`>` 뒤집힘을 가른다)."""
    user = await _logged_in_user(db_client, db_session)
    for index in range(9):
        await _make_persona(db_session, user.id, name=f"프로필{index}")
    await db_session.commit()

    resp = await db_client.post("/me/personas", json=_create_body())

    assert resp.status_code == 201


@pytest.mark.parametrize(
    ("has_default", "set_as_default", "expect_new_is_default"),
    [
        pytest.param(False, True, True, id="no-default-checked"),
        pytest.param(False, False, False, id="no-default-unchecked"),
        pytest.param(True, True, True, id="has-default-checked-replaces"),
        pytest.param(True, False, False, id="has-default-unchecked-keeps"),
    ],
)
async def test_create_persona_follows_set_as_default(
    has_default: bool,
    set_as_default: bool,
    expect_new_is_default: bool,
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """BE는 받은 `setAsDefault`만 따른다(자체 추론 없음)."""
    user = await _logged_in_user(db_client, db_session)
    existing_default = None
    if has_default:
        existing_default = await _make_persona(db_session, user.id, name="원래 기본")
        user.default_persona_id = existing_default.id
    await db_session.commit()

    resp = await db_client.post("/me/personas", json=_create_body(setAsDefault=set_as_default))

    assert resp.status_code == 201
    new_id = uuid.UUID(resp.json()["id"])
    expected = new_id if expect_new_is_default else (existing_default.id if existing_default else None)
    assert await _default_persona_id(db_session, user.id) == expected


async def test_create_persona_without_set_as_default_returns_422(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`setAsDefault`는 기본값 없는 필수 필드다 — 규칙이 두 곳에 생기지 않게."""
    await _logged_in_user(db_client, db_session)
    await db_session.commit()
    body = _create_body()
    del body["setAsDefault"]

    resp = await db_client.post("/me/personas", json=body)

    assert resp.status_code == 422


# ---- PUT /me/personas/{persona_id} ----


async def test_update_persona_replaces_fields(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = await _logged_in_user(db_client, db_session)
    persona = await _make_persona(db_session, user.id, gender="female", description="옛 설명")
    await db_session.commit()

    resp = await db_client.put(
        f"/me/personas/{persona.id}", json={"name": " 바다 ", "gender": None, "description": ""}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert (body["id"], body["name"], body["gender"], body["description"]) == (str(persona.id), "바다", None, "")
    row = (
        await db_session.execute(
            select(UserPersona.name, UserPersona.gender, UserPersona.description).where(UserPersona.id == persona.id)
        )
    ).one()
    assert tuple(row) == ("바다", None, "")


async def test_update_persona_rejects_invalid_name_with_422(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _logged_in_user(db_client, db_session)
    persona = await _make_persona(db_session, user.id)
    await db_session.commit()

    resp = await db_client.put(f"/me/personas/{persona.id}", json={"name": "a:b", "gender": None, "description": ""})

    assert resp.status_code == 422


async def test_update_persona_of_other_user_returns_403_and_unknown_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _logged_in_user(db_client, db_session)
    other = _make_user()
    db_session.add(other)
    await db_session.flush()
    others_persona = await _make_persona(db_session, other.id, name="남의 것")
    await db_session.commit()
    body = {"name": "탈취", "gender": None, "description": ""}

    forbidden = await db_client.put(f"/me/personas/{others_persona.id}", json=body)
    missing = await db_client.put(f"/me/personas/{uuid.uuid4()}", json=body)

    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "Not the persona owner"
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Persona not found"
    assert await db_session.scalar(select(UserPersona.name).where(UserPersona.id == others_persona.id)) == "남의 것"


# ---- DELETE /me/personas/{persona_id} ----


async def test_delete_default_persona_nulls_referencing_rooms_and_default(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """프로필을 지우면 참조하던 방은 "선택 없음", 기본이었으면 기본도 없음.
    다른 프로필을 가리키는 방은 그대로다."""
    user = await _logged_in_user(db_client, db_session)
    target = await _make_persona(db_session, user.id, name="지울 것")
    kept = await _make_persona(db_session, user.id, name="남길 것")
    user.default_persona_id = target.id
    referencing_room = await _make_room(db_session, user, persona_id=target.id)
    other_room = await _make_room(db_session, user, persona_id=kept.id)
    await db_session.commit()

    resp = await db_client.delete(f"/me/personas/{target.id}")

    assert resp.status_code == 204
    assert await db_session.scalar(select(UserPersona.id).where(UserPersona.id == target.id)) is None
    assert await _room_persona_id(db_session, referencing_room.id) is None
    assert await _room_persona_id(db_session, other_room.id) == kept.id
    assert await _default_persona_id(db_session, user.id) is None


async def test_delete_non_default_persona_keeps_default(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _logged_in_user(db_client, db_session)
    default = await _make_persona(db_session, user.id, name="기본")
    target = await _make_persona(db_session, user.id, name="지울 것")
    user.default_persona_id = default.id
    await db_session.commit()

    resp = await db_client.delete(f"/me/personas/{target.id}")

    assert resp.status_code == 204
    assert await _default_persona_id(db_session, user.id) == default.id


async def test_delete_persona_of_other_user_returns_403_and_unknown_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _logged_in_user(db_client, db_session)
    other = _make_user()
    db_session.add(other)
    await db_session.flush()
    others_persona = await _make_persona(db_session, other.id)
    await db_session.commit()

    forbidden = await db_client.delete(f"/me/personas/{others_persona.id}")
    missing = await db_client.delete(f"/me/personas/{uuid.uuid4()}")

    assert forbidden.status_code == 403
    assert missing.status_code == 404
    assert await db_session.scalar(select(UserPersona.id).where(UserPersona.id == others_persona.id)) is not None


# ---- PUT /me/default-persona ----


async def test_set_default_persona_sets_and_clears(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = await _logged_in_user(db_client, db_session)
    persona = await _make_persona(db_session, user.id)
    await db_session.commit()

    set_resp = await db_client.put("/me/default-persona", json={"personaId": str(persona.id)})
    assert set_resp.status_code == 204
    assert await _default_persona_id(db_session, user.id) == persona.id

    clear_resp = await db_client.put("/me/default-persona", json={"personaId": None})
    assert clear_resp.status_code == 204
    assert await _default_persona_id(db_session, user.id) is None


async def test_set_default_persona_of_other_user_returns_403_and_unknown_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _logged_in_user(db_client, db_session)
    other = _make_user()
    db_session.add(other)
    await db_session.flush()
    others_persona = await _make_persona(db_session, other.id)
    await db_session.commit()

    forbidden = await db_client.put("/me/default-persona", json={"personaId": str(others_persona.id)})
    missing = await db_client.put("/me/default-persona", json={"personaId": str(uuid.uuid4())})

    assert forbidden.status_code == 403
    assert missing.status_code == 404
    assert await _default_persona_id(db_session, user.id) is None


async def test_set_default_persona_without_persona_id_field_returns_422(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`personaId`를 빼먹은 요청이 "해제"로 해석되면 안 된다 — null은 명시해야 한다."""
    user = await _logged_in_user(db_client, db_session)
    persona = await _make_persona(db_session, user.id)
    user.default_persona_id = persona.id
    await db_session.commit()

    resp = await db_client.put("/me/default-persona", json={})

    assert resp.status_code == 422
    assert await _default_persona_id(db_session, user.id) == persona.id


# ---- PUT /chat-rooms/{room_id}/persona ----


async def test_set_room_persona_sets_and_clears(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = await _logged_in_user(db_client, db_session)
    persona = await _make_persona(db_session, user.id)
    room = await _make_room(db_session, user)
    await db_session.commit()

    set_resp = await db_client.put(f"/chat-rooms/{room.id}/persona", json={"personaId": str(persona.id)})
    assert set_resp.status_code == 200
    assert set_resp.json() == {"personaId": str(persona.id)}
    assert await _room_persona_id(db_session, room.id) == persona.id

    clear_resp = await db_client.put(f"/chat-rooms/{room.id}/persona", json={"personaId": None})
    assert clear_resp.status_code == 200
    assert clear_resp.json() == {"personaId": None}
    assert await _room_persona_id(db_session, room.id) is None


async def test_set_room_persona_to_other_users_persona_returns_403_and_unknown_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """🔴 방은 내 것이지만 프로필이 남의 것 — 방 소유 확인만으로는 막히지 않는 경로."""
    user = await _logged_in_user(db_client, db_session)
    other = _make_user()
    db_session.add(other)
    await db_session.flush()
    others_persona = await _make_persona(db_session, other.id)
    room = await _make_room(db_session, user)
    await db_session.commit()

    forbidden = await db_client.put(f"/chat-rooms/{room.id}/persona", json={"personaId": str(others_persona.id)})
    missing = await db_client.put(f"/chat-rooms/{room.id}/persona", json={"personaId": str(uuid.uuid4())})

    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "Not the persona owner"
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Persona not found"
    assert await _room_persona_id(db_session, room.id) is None


async def test_set_room_persona_on_other_users_room_returns_403_and_unknown_room_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """방이 남의 것 — 프로필은 내 것이어도 막힌다."""
    user = await _logged_in_user(db_client, db_session)
    other = _make_user()
    db_session.add(other)
    await db_session.flush()
    persona = await _make_persona(db_session, user.id)
    others_room = await _make_room(db_session, other)
    await db_session.commit()

    forbidden = await db_client.put(f"/chat-rooms/{others_room.id}/persona", json={"personaId": str(persona.id)})
    missing = await db_client.put(f"/chat-rooms/{uuid.uuid4()}/persona", json={"personaId": str(persona.id)})

    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "Not the chat room owner"
    assert missing.status_code == 404
    assert await _room_persona_id(db_session, others_room.id) is None


async def test_get_chat_room_exposes_persona_id(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = await _logged_in_user(db_client, db_session)
    persona = await _make_persona(db_session, user.id)
    room = await _make_room(db_session, user, persona_id=persona.id)
    await db_session.commit()

    resp = await db_client.get(f"/chat-rooms/{room.id}")

    assert resp.status_code == 200
    assert resp.json()["personaId"] == str(persona.id)
