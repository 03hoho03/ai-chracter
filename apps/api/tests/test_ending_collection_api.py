import uuid
from datetime import timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    Content,
    Ending,
    StartingSetup,
    StoryEndingUnlock,
)
from factories import _get_genre, _login_as, _make_published_story, _make_user


async def _add_starting_setup(db_session: AsyncSession, content: Content, **overrides: object) -> StartingSetup:
    assert content.current_published_version_id is not None
    defaults: dict[str, object] = {
        "entity_id": uuid.uuid4(),
        "content_version_id": content.current_published_version_id,
        "name": "첫 만남",
        "prologue": "옛날 옛적, 낯선 마을에 도착했다.",
        "order": 1,
    }
    defaults.update(overrides)
    setup = StartingSetup(**defaults)
    db_session.add(setup)
    await db_session.flush()
    return setup


async def _add_ending(db_session: AsyncSession, setup: StartingSetup, **overrides: object) -> Ending:
    defaults: dict[str, object] = {
        "entity_id": uuid.uuid4(),
        "starting_setup_id": setup.id,
        "name": "엔딩",
        "turn_count_gate": 1,
        "judgment_prompt": "주인공이 마을을 완전히 떠났는가?",
        "epilogue": "이야기는 여기서 끝난다.",
        "hint": "마을을 떠나 보세요.",
        "order": 1,
    }
    defaults.update(overrides)
    ending = Ending(**defaults)
    db_session.add(ending)
    await db_session.flush()
    return ending


async def test_ending_collection_marks_reached_ending_with_epilogue_and_hides_hint(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    reached = await _add_ending(db_session, setup, order=1)
    unreached = await _add_ending(db_session, setup, order=2, name="다른 엔딩", hint="힌트만 노출")
    db_session.add(
        StoryEndingUnlock(
            user_id=user.id, starting_setup_entity_id=setup.entity_id, ending_entity_id=reached.entity_id
        )
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get(f"/stories/starting-setups/{setup.id}/ending-collection")

    assert resp.status_code == 200
    body = resp.json()
    assert [item["id"] for item in body] == [str(reached.entity_id), str(unreached.entity_id)]

    reached_item, unreached_item = body
    assert reached_item["reached"] is True
    assert reached_item["epilogue"] == "이야기는 여기서 끝난다."
    assert reached_item["hint"] is None

    assert unreached_item["reached"] is False
    assert unreached_item["epilogue"] is None
    assert unreached_item["hint"] == "힌트만 노출"


async def test_ending_collection_reuses_unlock_across_new_chat_rooms_for_same_starting_setup(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """엔딩 도달 기록은 특정 대화방이 아니라 (user, starting_setup_entity_id, ending_entity_id)
    단위로 누적되므로, 같은 시작설정으로 새 대화방을 만들어도 유지되어야 한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    ending = await _add_ending(db_session, setup)
    db_session.add(
        StoryEndingUnlock(
            user_id=user.id, starting_setup_entity_id=setup.entity_id, ending_entity_id=ending.entity_id
        )
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.post(
        "/chat-rooms", json={"contentId": str(content.id), "contentType": "story", "startingSetupId": str(setup.id)}
    )
    assert resp.status_code == 201

    resp = await db_client.get(f"/stories/starting-setups/{setup.id}/ending-collection")
    assert resp.status_code == 200
    assert resp.json()[0]["reached"] is True


async def test_ending_collection_requires_login(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    await db_session.commit()

    resp = await db_client.get(f"/stories/starting-setups/{setup.id}/ending-collection")
    assert resp.status_code == 401


async def test_ending_collection_unknown_starting_setup_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get(f"/stories/starting-setups/{uuid.uuid4()}/ending-collection")
    assert resp.status_code == 404


async def test_ending_collection_returns_empty_list_when_no_endings_registered(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    setup = await _add_starting_setup(db_session, content)
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get(f"/stories/starting-setups/{setup.id}/ending-collection")
    assert resp.status_code == 200
    assert resp.json() == []
