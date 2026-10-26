"""작품의 마지막 편집 시각(`contents.edited_at`) — 작가가 자기 작품을 바꾼 순간에만 앞으로 가고, 읽기·독자 행동에는
움직이지 않으며, `/me/drafts` 의 순서·커서(`updated_at` 기준)는 편집과 무관하게 그대로다.

시각은 한 테스트 안에서 DB `now()` 가 고정이라 라이브 호출 전후를 비교할 수 없다 — 편집 전에 칸을 먼 과거 값으로
직접 써 두고, 편집 뒤에 그 값보다 늦어졌는지(또는 그대로인지) 본다. 칸은 컬럼 단위 select 로 DB 에서 읽는다(세션
캐시를 보지 않게).

상황이미지 등록과 발행이 미는지는 각 경로의 셋업 헬퍼가 있는 `test_assets_situational_image_api.py`·
`test_content_publish_api.py` 에서 본다."""

import uuid
from datetime import UTC, datetime

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.content import router as content_router
from api.db.models.character import CharacterVersionDetail
from api.db.models.content import Content, ContentVersion
from factories import _get_genre, _login_as, _make_published_character, _make_user

_LONG_AGO = datetime(2020, 1, 1, tzinfo=UTC)


async def _edited_at(db_session: AsyncSession, content_id: uuid.UUID) -> datetime:
    value: datetime | None = await db_session.scalar(sa.select(Content.edited_at).where(Content.id == content_id))
    assert value is not None
    return value


async def _set_long_ago(db_session: AsyncSession, content_id: uuid.UUID) -> None:
    await db_session.execute(sa.update(Content).where(Content.id == content_id).values(edited_at=_LONG_AGO))
    await db_session.commit()


async def _logged_in_creator(db_client: httpx.AsyncClient, db_session: AsyncSession) -> uuid.UUID:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    return user.id


async def _new_draft(db_client: httpx.AsyncClient, content_type: str) -> uuid.UUID:
    resp = await db_client.post("/contents", json={"type": content_type})
    assert resp.status_code == 201
    return uuid.UUID(resp.json()["contentId"])


async def _published_character_with_draft(db_session: AsyncSession, creator_user_id: uuid.UUID) -> Content:
    """발행본 하나와 그 뒤에 딸린 빈 초안 버전을 가진 캐릭터. 발행이 다음 편집용 초안을 복제해 두는 상태를 흉내낸다."""
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=creator_user_id, genre_id=genre.id)
    draft = ContentVersion(content_id=content.id, detail_description="")
    db_session.add(draft)
    await db_session.flush()
    db_session.add(
        CharacterVersionDetail(
            content_version_id=draft.id, name="", one_liner="", intro="", example_dialogues=[], character_prompt=""
        )
    )
    await db_session.commit()
    return content


def _character_payload() -> dict[str, object]:
    return {
        "name": "등대지기",
        "oneLiner": "바닷가 등대를 지키는 사람",
        "thumbnailAssetId": None,
        "intro": "오늘도 불을 켰다",
        "exampleDialogues": [],
        "characterPrompt": "너는 등대지기다.",
        "playguide": None,
        "situationalImages": [],
        "description": "합성 설명",
        "genreId": None,
        "target": None,
        "hashtags": [],
        "visibility": "private",
    }


def _story_payload() -> dict[str, object]:
    return {
        "name": "안개 낀 항구",
        "oneLiner": "배가 들어오지 않는 밤",
        "thumbnailAssetId": None,
        "promptTemplate": "basic",
        "settingText": "합성 세계관",
        "developmentExample": None,
        "customPrompt": None,
        "startingSetups": [],
        "keywordNotes": [],
        "shortcuts": [],
        "description": "합성 설명",
        "genreId": None,
        "target": None,
        "hashtags": [],
        "visibility": "private",
    }


# ── 미는 곳 ───────────────────────────────────────────────────────────────────────────────────


async def test_a_new_draft_starts_with_its_creation_time_as_last_edit(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """작품을 만든 순간이 첫 편집이다 — 칸 기본값이 생성 시각과 같은 값을 채운다."""
    await _logged_in_creator(db_client, db_session)
    content_id = await _new_draft(db_client, "character")

    created_at = await db_session.scalar(sa.select(Content.created_at).where(Content.id == content_id))
    assert await _edited_at(db_session, content_id) == created_at


@pytest.mark.parametrize(
    ("content_type", "payload"),
    [
        pytest.param("character", _character_payload(), id="character"),
        pytest.param("story", _story_payload(), id="story"),
    ],
)
async def test_autosaving_a_draft_moves_last_edit_forward(
    db_client: httpx.AsyncClient, db_session: AsyncSession, content_type: str, payload: dict[str, object]
) -> None:
    await _logged_in_creator(db_client, db_session)
    content_id = await _new_draft(db_client, content_type)
    await _set_long_ago(db_session, content_id)

    resp = await db_client.patch(f"/contents/{content_id}/draft", json=payload)

    assert resp.status_code == 200
    assert await _edited_at(db_session, content_id) > _LONG_AGO


async def test_resetting_a_draft_to_the_published_version_moves_last_edit_forward(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """편집 취소도 작가가 작품을 바꾼 순간이다 — 목록에서 방금 손댄 작품으로 올라와야 한다."""
    creator_id = await _logged_in_creator(db_client, db_session)
    content = await _published_character_with_draft(db_session, creator_id)
    await _set_long_ago(db_session, content.id)

    resp = await db_client.post(f"/contents/{content.id}/draft/reset")

    assert resp.status_code == 204
    assert await _edited_at(db_session, content.id) > _LONG_AGO


async def test_changing_visibility_moves_last_edit_forward(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator_id = await _logged_in_creator(db_client, db_session)
    content = await _published_character_with_draft(db_session, creator_id)
    await _set_long_ago(db_session, content.id)

    resp = await db_client.patch(f"/contents/{content.id}/visibility", json={"visibility": "private"})

    assert resp.status_code == 204
    assert await _edited_at(db_session, content.id) > _LONG_AGO


async def test_changing_novel_permission_moves_last_edit_forward(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    creator_id = await _logged_in_creator(db_client, db_session)
    content = await _published_character_with_draft(db_session, creator_id)
    await _set_long_ago(db_session, content.id)

    resp = await db_client.put(f"/contents/{content.id}/novel-permission", json={"novelPermission": "public"})

    assert resp.status_code == 204
    assert await _edited_at(db_session, content.id) > _LONG_AGO


# ── 밀지 않는 곳 ──────────────────────────────────────────────────────────────────────────────


async def test_reading_the_draft_and_the_draft_list_leaves_last_edit_alone(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _logged_in_creator(db_client, db_session)
    content_id = await _new_draft(db_client, "character")
    await _set_long_ago(db_session, content_id)

    assert (await db_client.get(f"/contents/{content_id}/draft")).status_code == 200
    assert (await db_client.get("/me/drafts")).status_code == 200

    assert await _edited_at(db_session, content_id) == _LONG_AGO


async def test_a_reader_opening_the_detail_leaves_last_edit_alone(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """상세 조회는 조회수를 올리는 쓰기를 하지만 독자 행동이라 작가의 편집 순서를 흔들지 않는다."""
    creator = _make_user()
    reader = _make_user()
    db_session.add_all([creator, reader])
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=creator.id, genre_id=genre.id)
    await _set_long_ago(db_session, content.id)
    await _login_as(db_client, reader.id)

    assert (await db_client.get(f"/contents/{content.id}")).status_code == 200
    assert (await db_client.get(f"/users/{creator.id}/contents", params={"type": "character"})).status_code == 200

    assert await _edited_at(db_session, content.id) == _LONG_AGO


# ── `/me/drafts` 커서는 편집과 무관하다 ─────────────────────────────────────────────────────────


async def test_editing_a_draft_does_not_reorder_or_reshape_my_drafts_pages(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """초안 목록은 생성 순(`updated_at`)으로 고정이다. 넘기는 도중 다음 쪽의 초안을 고쳐도 그 초안이 앞 쪽으로 튀어
    남은 쪽에서 빠지지 않고, 두 쪽의 응답이 편집 전과 같다. 한 쪽에 하나씩 보이게 쪽 크기를 1 로 줄인다."""
    monkeypatch.setattr(content_router, "CREATOR_CONTENT_PAGE_SIZE", 1)
    await _logged_in_creator(db_client, db_session)
    older = await _new_draft(db_client, "character")
    newer = await _new_draft(db_client, "story")
    await db_session.execute(
        sa.update(Content).where(Content.id == older).values(updated_at=datetime(2026, 1, 1, tzinfo=UTC))
    )
    await db_session.execute(
        sa.update(Content).where(Content.id == newer).values(updated_at=datetime(2026, 1, 2, tzinfo=UTC))
    )
    await db_session.commit()

    first_before = (await db_client.get("/me/drafts")).json()
    cursor = first_before["nextCursor"]
    second_before = (await db_client.get("/me/drafts", params={"cursor": cursor})).json()
    assert [item["id"] for item in first_before["items"] + second_before["items"]] == [str(newer), str(older)]

    resp = await db_client.patch(f"/contents/{older}/visibility", json={"visibility": "public"})
    assert resp.status_code == 204

    assert (await db_client.get("/me/drafts")).json() == first_before
    assert (await db_client.get("/me/drafts", params={"cursor": cursor})).json() == second_before
