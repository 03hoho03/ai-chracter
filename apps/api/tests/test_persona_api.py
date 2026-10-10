"""대화 프로필 CRUD·기본 지정·방 선택 API.

🔴 쓰기 경로의 소유권 검사가 이 기능의 유일한 방어선이다. 읽기 경로(`build_room_prompt`,
`_preview_persona_dependency`)는 프로필 소유자를 다시 보지 않는다. 그래서
남의 프로필을 기본·방에 거는 모든 경로가 403인지를 여기서 하나씩 확인한다.

방 생성 두 경로(새 방 = 기본, 시작설정 변경 = 원래 방의 선택 승계)는 `test_chat_room_api.py`, 탈퇴는
`test_auth_me_api.py`, 재동의 게이트 분류는 `test_consent_gate_endpoints.py`에 있다.
"""

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from api.db.models import ChatRoom, User, UserPersona
from api.main import app
from api.persona import router as persona_router
from api.session.store import revoke_user_sessions
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
        pytest.param({"name": "*별*"}, id="name-markdown-star"),
        pytest.param({"name": "`별`"}, id="name-backtick"),
        pytest.param({"name": "- 별"}, id="name-starts-with-list-marker"),
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


async def test_create_persona_explains_markdown_name_in_korean(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """이름은 작가 글 속 `{{user}}` 자리에 들어가므로 채팅 렌더러가 표기로 읽는 문자를 막는다. 화면이 그대로 띄울 문구다."""
    await _logged_in_user(db_client, db_session)
    await db_session.commit()

    resp = await db_client.post("/me/personas", json=_create_body(name="*별*"))

    assert resp.status_code == 422
    assert "별표(*)" in resp.json()["detail"][0]["msg"]


async def test_persona_saved_before_markdown_rule_stays_readable_and_must_be_renamed_to_edit(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """금지는 새 저장부터다 — 규칙 전에 저장된 이름도 목록에 그대로 나온다. 다만 수정은 전체 교체라 설명만 고쳐도
    이름이 다시 검사된다. 그런 프로필은 이름을 바꿔야 저장된다."""
    user = await _logged_in_user(db_client, db_session)
    persona = await _make_persona(db_session, user.id, name="*별*")
    await db_session.commit()

    listed = await db_client.get("/me/personas")
    same_name = await db_client.put(
        f"/me/personas/{persona.id}", json={"name": "*별*", "gender": None, "description": "새 설명"}
    )
    renamed = await db_client.put(f"/me/personas/{persona.id}", json={"name": "별", "gender": None, "description": ""})

    assert listed.status_code == 200
    assert [item["name"] for item in listed.json()["items"]] == ["*별*"]
    assert same_name.status_code == 422
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "별"


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


@pytest.mark.parametrize("set_as_default", [True, False])
async def test_create_first_persona_becomes_default_regardless_of_set_as_default(
    set_as_default: bool, db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """프로필이 하나라도 있으면 기본이 있어야 하므로, 첫 프로필은 체크박스와 무관하게 기본이 된다."""
    user = await _logged_in_user(db_client, db_session)
    await db_session.commit()

    resp = await db_client.post("/me/personas", json=_create_body(setAsDefault=set_as_default))

    assert resp.status_code == 201
    assert await _default_persona_id(db_session, user.id) == uuid.UUID(resp.json()["id"])


@pytest.mark.parametrize(
    ("has_default", "set_as_default", "expect_new_is_default"),
    [
        pytest.param(False, True, True, id="no-default-checked"),
        pytest.param(False, False, False, id="no-default-unchecked"),
        pytest.param(True, True, True, id="has-default-checked-replaces"),
        pytest.param(True, False, False, id="has-default-unchecked-keeps"),
    ],
)
async def test_create_persona_with_existing_profiles_follows_set_as_default(
    has_default: bool,
    set_as_default: bool,
    expect_new_is_default: bool,
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """프로필이 이미 있으면 받은 `setAsDefault`만 따른다. 기본이 비어 있는 예전 계정도 여기서 기본을 채우지 않는다 —
    그 승격은 새 방을 만들 때 한다."""
    user = await _logged_in_user(db_client, db_session)
    existing = await _make_persona(db_session, user.id, name="원래 것")
    if has_default:
        user.default_persona_id = existing.id
    await db_session.commit()

    resp = await db_client.post("/me/personas", json=_create_body(setAsDefault=set_as_default))

    assert resp.status_code == 201
    new_id = uuid.UUID(resp.json()["id"])
    expected = new_id if expect_new_is_default else (existing.id if has_default else None)
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


async def test_delete_default_persona_promotes_the_oldest_remaining_and_nulls_referencing_rooms(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """기본을 지우면 남은 것 중 가장 먼저 만든 것이 기본이 된다. 지운 프로필을 쓰던 방은 승격된 것으로 바꾸지 않고
    "선택 없음"이 되며, 다른 프로필을 가리키는 방은 그대로다.

    지울 프로필을 전체에서 가장 오래된 것으로 둬야 "남은 것 중"이 갈린다. 남은 둘은 나중 것을 먼저 넣어 삽입 순서가
    생성 시각 순서와 어긋나게 한다."""
    user = await _logged_in_user(db_client, db_session)
    now = datetime.now(UTC)
    target = await _make_persona(db_session, user.id, name="지울 것", created_at=now - timedelta(minutes=3))
    newer = await _make_persona(db_session, user.id, name="나중", created_at=now - timedelta(minutes=1))
    older = await _make_persona(db_session, user.id, name="먼저", created_at=now - timedelta(minutes=2))
    user.default_persona_id = target.id
    referencing_room = await _make_room(db_session, user, persona_id=target.id)
    other_room = await _make_room(db_session, user, persona_id=newer.id)
    await db_session.commit()

    resp = await db_client.delete(f"/me/personas/{target.id}")

    assert resp.status_code == 204
    assert await db_session.scalar(select(UserPersona.id).where(UserPersona.id == target.id)) is None
    assert await _room_persona_id(db_session, referencing_room.id) is None
    assert await _room_persona_id(db_session, other_room.id) == newer.id
    assert await _default_persona_id(db_session, user.id) == older.id


async def test_delete_default_persona_breaks_created_at_tie_by_id(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """생성 시각이 같으면 id가 작은 쪽이 기본이 된다 — 목록(`GET /me/personas`)과 같은 순서다."""
    user = await _logged_in_user(db_client, db_session)
    same_time = datetime.now(UTC) - timedelta(minutes=1)
    target = await _make_persona(db_session, user.id, name="지울 것", created_at=same_time - timedelta(minutes=1))
    tied = [await _make_persona(db_session, user.id, name=f"동률{index}", created_at=same_time) for index in range(2)]
    user.default_persona_id = target.id
    await db_session.commit()

    resp = await db_client.delete(f"/me/personas/{target.id}")

    assert resp.status_code == 204
    assert await _default_persona_id(db_session, user.id) == min(persona.id for persona in tied)


async def test_delete_non_default_persona_keeps_default(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """기본이 아닌 걸 지우면 기본은 그대로다 — 지울 것을 더 오래된 것으로 둬야 "무조건 가장 오래된 것으로 승격"과 갈린다."""
    user = await _logged_in_user(db_client, db_session)
    now = datetime.now(UTC)
    target = await _make_persona(db_session, user.id, name="지울 것", created_at=now - timedelta(minutes=3))
    await _make_persona(db_session, user.id, name="먼저", created_at=now - timedelta(minutes=2))
    default = await _make_persona(db_session, user.id, name="기본", created_at=now - timedelta(minutes=1))
    user.default_persona_id = default.id
    await db_session.commit()

    resp = await db_client.delete(f"/me/personas/{target.id}")

    assert resp.status_code == 204
    assert await _default_persona_id(db_session, user.id) == default.id


async def test_delete_last_persona_returns_409_and_keeps_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """프로필이 하나라도 있으면 하나는 남아야 한다. 화면이 409 문구를 그대로 보여 준다."""
    user = await _logged_in_user(db_client, db_session)
    only = await _make_persona(db_session, user.id)
    user.default_persona_id = only.id
    room = await _make_room(db_session, user, persona_id=only.id)
    await db_session.commit()

    resp = await db_client.delete(f"/me/personas/{only.id}")

    assert resp.status_code == 409
    assert resp.json()["detail"] == "마지막 대화 프로필은 지울 수 없어요. 다른 프로필을 먼저 만들어 주세요."
    assert await db_session.scalar(select(UserPersona.id).where(UserPersona.id == only.id)) == only.id
    assert await _default_persona_id(db_session, user.id) == only.id
    assert await _room_persona_id(db_session, room.id) == only.id


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


async def test_set_default_persona_sets_it(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = await _logged_in_user(db_client, db_session)
    current = await _make_persona(db_session, user.id, name="지금 기본")
    persona = await _make_persona(db_session, user.id)
    user.default_persona_id = current.id
    await db_session.commit()

    resp = await db_client.put("/me/default-persona", json={"personaId": str(persona.id)})

    assert resp.status_code == 204
    assert await _default_persona_id(db_session, user.id) == persona.id


@pytest.mark.parametrize("has_default", [True, False])
async def test_clear_default_persona_with_profiles_returns_409(
    has_default: bool, db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """프로필이 있으면 기본을 비울 수 없다 — 다른 프로필을 기본으로 지정하는 것만 된다. 기본이 비어 있는 예전 계정도
    같은 응답이다(비우기를 "아무것도 안 바뀜"으로 통과시키지 않는다)."""
    user = await _logged_in_user(db_client, db_session)
    persona = await _make_persona(db_session, user.id)
    if has_default:
        user.default_persona_id = persona.id
    await db_session.commit()

    resp = await db_client.put("/me/default-persona", json={"personaId": None})

    assert resp.status_code == 409
    assert resp.json()["detail"] == "기본 대화 프로필은 비울 수 없어요. 다른 프로필을 기본으로 지정해 주세요."
    assert await _default_persona_id(db_session, user.id) == (persona.id if has_default else None)


async def test_clear_default_persona_without_profiles_is_allowed(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """프로필이 없으면 비울 기본도 없다 — 거절할 이유가 없어 그대로 204다."""
    user = await _logged_in_user(db_client, db_session)
    await db_session.commit()

    resp = await db_client.put("/me/default-persona", json={"personaId": None})

    assert resp.status_code == 204
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
    assert set_resp.json() == {"personaId": str(persona.id), "personaName": "하늘"}
    assert await _room_persona_id(db_session, room.id) == persona.id

    clear_resp = await db_client.put(f"/chat-rooms/{room.id}/persona", json={"personaId": None})
    assert clear_resp.status_code == 200
    assert clear_resp.json() == {"personaId": None, "personaName": None}
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


# ---- 동시 삭제 ----


async def test_concurrent_deletes_of_the_last_two_personas_leave_one(
    db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """프로필 둘을 두 요청이 동시에 지워도 하나는 남는다. 개수를 센 직후 상대 요청을 잠깐 기다리게 해, 유저 행 잠금이
    없으면 둘 다 "2개"를 보고 둘 다 지우는 엇갈림을 실제로 만든다. 잠금이 있으면 뒤 요청은 잠금에서 기다리다 앞 요청의
    커밋 뒤에 1개를 세고 409가 된다.

    롤백 공유 커넥션(`db_client`)은 두 요청이 한 트랜잭션을 써 잠금이 드러나지 않으므로 실제로 커밋하는 별도
    커넥션에서 돌린다."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    user = _make_user()
    async with factory() as db:
        db.add(user)
        await db.flush()
        first = UserPersona(user_id=user.id, name="첫째")
        second = UserPersona(user_id=user.id, name="둘째")
        db.add_all([first, second])
        await db.flush()
        user.default_persona_id = first.id
        await db.commit()

    real_count = persona_router.count_personas
    counted = 0
    both_counted = asyncio.Event()

    async def count_then_wait_for_the_other(db: AsyncSession, user_id: uuid.UUID) -> int:
        nonlocal counted
        count = await real_count(db, user_id)
        counted += 1
        if counted >= 2:
            both_counted.set()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(both_counted.wait(), 0.5)
        return count

    monkeypatch.setattr(persona_router, "count_personas", count_then_wait_for_the_other)
    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with (
            httpx.AsyncClient(transport=transport, base_url="http://testserver") as one,
            httpx.AsyncClient(transport=transport, base_url="http://testserver") as other,
        ):
            await _login_as(one, user.id)
            await _login_as(other, user.id)
            responses = await asyncio.gather(
                one.delete(f"/me/personas/{first.id}"), other.delete(f"/me/personas/{second.id}")
            )

        assert sorted(response.status_code for response in responses) == [204, 409]
        async with factory() as db:
            remaining = (await db.scalars(select(UserPersona.id).where(UserPersona.user_id == user.id))).all()
            assert len(remaining) == 1
            assert await db.scalar(select(User.default_persona_id).where(User.id == user.id)) == remaining[0]
    finally:
        async with factory() as db:
            await db.execute(update(User).where(User.id == user.id).values(default_persona_id=None))
            await db.execute(delete(UserPersona).where(UserPersona.user_id == user.id))
            await db.execute(delete(User).where(User.id == user.id))
            await db.commit()
        await revoke_user_sessions(user.id)
