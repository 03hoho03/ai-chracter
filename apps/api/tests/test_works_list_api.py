"""작가의 통합 작품 목록(`GET /me/works`) — 캐릭터·스토리(발행작·초안)와 소설을 마지막 편집 순 한 목록으로.

목록이 기존 세 목록(작가 발행작·초안·내 소설)과 같은 작품 집합을 내는지, 페이지 경계에서 같은 시각의 작품이 빠지거나
겹치지 않는지, 소설화 허용이 없는 계정에 소설이 섞이지 않는지를 본다. 시각은 한 테스트 안에서 DB `now()` 가 고정이라
순서가 필요한 곳은 칸을 직접 써 둔다."""

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.content.router import CREATOR_CONTENT_PAGE_SIZE
from api.db.models.character import CharacterVersionDetail
from api.db.models.content import Content, ContentType, ContentVersion, ContentVisibility, ModerationStatus
from api.db.models.novel import Novel, NovelPublication
from api.db.models.story import StoryPromptTemplate, StoryVersionDetail
from factories import _allow_novelize, _login_as, _make_asset, _make_public_novel, _make_user

_BASE = datetime(2026, 1, 1, tzinfo=UTC)

NovelState = Literal["none", "readable", "pending", "rejected", "withdrawn", "hidden"]


async def _creator(db_client: httpx.AsyncClient, db_session: AsyncSession) -> uuid.UUID:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    return user.id


def _detail(kind: ContentType, version_id: uuid.UUID, name: str, thumbnail_id: uuid.UUID | None) -> object:
    if kind == ContentType.CHARACTER:
        return CharacterVersionDetail(
            content_version_id=version_id,
            name=name,
            one_liner="",
            thumbnail_asset_id=thumbnail_id,
            intro="",
            example_dialogues=[],
            character_prompt="",
        )
    return StoryVersionDetail(
        content_version_id=version_id,
        name=name,
        one_liner="",
        thumbnail_asset_id=thumbnail_id,
        prompt_template=StoryPromptTemplate.BASIC,
    )


async def _content(
    db_session: AsyncSession,
    owner_id: uuid.UUID,
    kind: ContentType,
    *,
    published: bool,
    visibility: ContentVisibility = ContentVisibility.PUBLIC,
    moderation: ModerationStatus = ModerationStatus.NORMAL,
    changes: bool = False,
    draft_name: str = "초안 제목",
    published_name: str = "발행 제목",
    content_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """작품 하나(flush). 발행작이면 발행 버전과 그 뒤에 딸린 초안 버전을 함께 둔다 — 발행이 다음 편집용 초안을 복제해
    두는 상태를 흉내낸다."""
    content = Content(
        id=content_id or uuid.uuid4(),
        creator_user_id=owner_id,
        type=kind,
        hashtags=[],
        visibility=visibility,
        moderation_status=moderation,
        has_unpublished_changes=changes,
    )
    db_session.add(content)
    await db_session.flush()
    if published:
        thumbnail = await _make_asset(db_session, owner_user_id=owner_id)
        version = ContentVersion(
            content_id=content.id, version_number=1, published_at=datetime.now(UTC), detail_description=""
        )
        db_session.add(version)
        await db_session.flush()
        db_session.add(_detail(kind, version.id, published_name, thumbnail.id))
        await db_session.flush()
        content.current_published_version_id = version.id
    draft = ContentVersion(content_id=content.id, detail_description="")
    db_session.add(draft)
    await db_session.flush()
    db_session.add(_detail(kind, draft.id, draft_name, None))
    await db_session.flush()
    return content.id


async def _novel(
    db_session: AsyncSession,
    owner_id: uuid.UUID,
    state: NovelState = "none",
    *,
    title: str | None = None,
    content_title: str = "원작",
    novel_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """내 소설 하나(flush). `readable` 은 독자가 지금 읽을 수 있는 공개 소설이고, 나머지 공개 상태는 그 공개 상태 행을
    고쳐 만든다."""
    if state == "none" or state == "hidden":
        novel = Novel(
            id=novel_id or uuid.uuid4(),
            user_id=owner_id,
            content_id=uuid.uuid4(),
            content_type="character",
            content_title=content_title,
            character_name="인물",
            title=title,
            hidden_at=datetime.now(UTC) if state == "hidden" else None,
        )
        db_session.add(novel)
        await db_session.flush()
        return novel.id
    public = await _make_public_novel(db_session, owner_id, batches=(1,))
    await db_session.execute(
        sa.update(Novel).where(Novel.id == public.novel_id).values(title=title, content_title=content_title)
    )
    values: dict[str, Any] = {}
    if state == "pending":
        values = {"visibility": "withdrawn", "review_status": "pending"}
    elif state == "rejected":
        values = {"visibility": "withdrawn", "review_status": "rejected", "review_reason": "합성 반려 사유"}
    elif state == "withdrawn":
        values = {"visibility": "withdrawn"}
    if values:
        await db_session.execute(
            sa.update(NovelPublication).where(NovelPublication.novel_id == public.novel_id).values(**values)
        )
    await db_session.flush()
    return public.novel_id


async def _all_pages(db_client: httpx.AsyncClient, **params: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(50):
        query = {**params, **({"cursor": cursor} if cursor is not None else {})}
        resp = await db_client.get("/me/works", params=query)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        items.extend(body["items"])
        cursor = body["nextCursor"]
        if cursor is None:
            return items
    raise AssertionError("다음 페이지가 끝나지 않는다")


def _ids(items: list[dict[str, Any]]) -> list[uuid.UUID]:
    return [uuid.UUID(item["id"]) for item in items]


# ── 순서 ─────────────────────────────────────────────────────────────────────────────────────


async def test_one_autosave_brings_a_draft_to_the_top(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """초안 목록(`/me/drafts`)은 만든 순서로 고정이지만, 통합 목록은 마지막 편집 순이라 자동저장 한 번이 순서를 바꾼다."""
    await _creator(db_client, db_session)
    first = uuid.UUID((await db_client.post("/contents", json={"type": "character"})).json()["contentId"])
    second = uuid.UUID((await db_client.post("/contents", json={"type": "character"})).json()["contentId"])
    await db_session.execute(sa.update(Content).where(Content.id == first).values(edited_at=_BASE))
    await db_session.execute(sa.update(Content).where(Content.id == second).values(edited_at=_BASE + timedelta(days=1)))
    await db_session.commit()

    assert _ids(await _all_pages(db_client)) == [second, first]

    resp = await db_client.patch(
        f"/contents/{first}/draft",
        json={
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
        },
    )
    assert resp.status_code == 200

    assert _ids(await _all_pages(db_client)) == [first, second]


async def test_works_and_novels_interleave_by_last_edit(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = await _creator(db_client, db_session)
    await _allow_novelize(db_session, monkeypatch, user_id)
    old_story = await _content(db_session, user_id, ContentType.STORY, published=True)
    novel = await _novel(db_session, user_id)
    new_character = await _content(db_session, user_id, ContentType.CHARACTER, published=False)
    await db_session.execute(sa.update(Content).where(Content.id == old_story).values(edited_at=_BASE))
    await db_session.execute(sa.update(Novel).where(Novel.id == novel).values(updated_at=_BASE + timedelta(hours=1)))
    await db_session.execute(
        sa.update(Content).where(Content.id == new_character).values(edited_at=_BASE + timedelta(hours=2))
    )
    await db_session.commit()

    items = await _all_pages(db_client)

    assert [(item["kind"], uuid.UUID(item["id"])) for item in items] == [
        ("character", new_character),
        ("novel", novel),
        ("story", old_story),
    ]


async def test_page_boundary_keeps_works_that_share_the_same_time_and_id(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """같은 시각의 작품은 유형과 id 로 줄을 세운다. 소설과 작품은 다른 표라 id 가 같을 수 있어, 커서가 유형을 빼고
    (시각, id) 만 들면 첫 페이지 끝의 작품과 id 가 같은 다음 소설이 다음 페이지에서 빠진다."""
    user_id = await _creator(db_client, db_session)
    await _allow_novelize(db_session, monkeypatch, user_id)
    shared_id = uuid.UUID("80000000-0000-0000-0000-000000000000")
    # 첫 페이지를 채우는 스토리(id 가 공유 id 보다 커서 앞에 선다) + 첫 페이지 끝의 스토리(공유 id) + 다음 페이지 첫
    # 소설(같은 id) + 캐릭터 하나.
    expected: list[tuple[str, uuid.UUID]] = []
    for index in reversed(range(CREATOR_CONTENT_PAGE_SIZE - 1)):
        story_id = uuid.UUID(f"f{index:07x}-0000-0000-0000-000000000000")
        await _content(db_session, user_id, ContentType.STORY, published=False, content_id=story_id)
        expected.append(("story", story_id))
    await _content(db_session, user_id, ContentType.STORY, published=False, content_id=shared_id)
    expected.append(("story", shared_id))
    await _novel(db_session, user_id, novel_id=shared_id)
    expected.append(("novel", shared_id))
    character_id = await _content(db_session, user_id, ContentType.CHARACTER, published=False)
    expected.append(("character", character_id))
    await db_session.execute(sa.update(Content).where(Content.creator_user_id == user_id).values(edited_at=_BASE))
    await db_session.execute(sa.update(Novel).where(Novel.user_id == user_id).values(updated_at=_BASE))
    await db_session.commit()

    first_page = (await db_client.get("/me/works")).json()
    items = await _all_pages(db_client)

    assert [(item["kind"], uuid.UUID(item["id"])) for item in first_page["items"]][-1] == ("story", shared_id)
    assert first_page["nextCursor"] is not None
    assert [(item["kind"], uuid.UUID(item["id"])) for item in items] == expected


async def test_broken_cursor_is_422(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await _creator(db_client, db_session)

    resp = await db_client.get("/me/works", params={"cursor": "not-a-cursor"})

    assert resp.status_code == 422
    assert resp.json()["detail"] == {"code": "INVALID_CURSOR"}


async def test_cursor_with_an_unknown_kind_is_422(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """모양은 맞아도 유형이 목록에 없는 값이면 깨진 커서다 — 그대로 비교하면 그 문자열의 사전 순 자리에서 잘려 엉뚱한
    페이지가 나온다."""
    await _creator(db_client, db_session)
    cursor = base64.urlsafe_b64encode(json.dumps([_BASE.isoformat(), "image", str(uuid.uuid4())]).encode()).decode()

    resp = await db_client.get("/me/works", params={"cursor": cursor})

    assert resp.status_code == 422
    assert resp.json()["detail"] == {"code": "INVALID_CURSOR"}


# ── 같은 작품 집합 ────────────────────────────────────────────────────────────────────────────


async def test_all_pages_cover_exactly_the_published_drafts_and_novels_lists(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """전체 목록 = 작가 발행작(캐릭터·스토리) + 초안 + 내 소설. 운영 삭제한 작품과 숨긴 소설은 어느 쪽에도 없다."""
    user_id = await _creator(db_client, db_session)
    await _allow_novelize(db_session, monkeypatch, user_id)
    await _content(db_session, user_id, ContentType.CHARACTER, published=False)
    await _content(db_session, user_id, ContentType.STORY, published=False)
    await _content(db_session, user_id, ContentType.CHARACTER, published=True)
    await _content(db_session, user_id, ContentType.CHARACTER, published=True, visibility=ContentVisibility.PRIVATE)
    await _content(db_session, user_id, ContentType.CHARACTER, published=True, moderation=ModerationStatus.RESTRICTED)
    await _content(db_session, user_id, ContentType.STORY, published=True, changes=True)
    deleted = await _content(
        db_session, user_id, ContentType.STORY, published=True, moderation=ModerationStatus.DELETED
    )
    await _novel(db_session, user_id)
    await _novel(db_session, user_id, "readable")
    hidden = await _novel(db_session, user_id, "hidden")
    await db_session.commit()

    expected: set[uuid.UUID] = set()
    for path, params in [
        (f"/users/{user_id}/contents", {"type": "character"}),
        (f"/users/{user_id}/contents", {"type": "story"}),
        ("/me/drafts", {}),
        ("/novels", {}),
    ]:
        resp = await db_client.get(path, params=params)
        assert resp.status_code == 200
        assert resp.json()["nextCursor"] is None
        expected |= {uuid.UUID(item["id"]) for item in resp.json()["items"]}

    ids = _ids(await _all_pages(db_client))

    assert len(ids) == len(set(ids))
    assert set(ids) == expected
    assert len(ids) == 8
    assert deleted not in ids
    assert hidden not in ids


@pytest.mark.parametrize("allowed", [True, False], ids=["novelize-allowed", "not-allowed"])
async def test_novels_appear_only_for_accounts_allowed_to_novelize(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, allowed: bool
) -> None:
    """소설화 허용이 없는 계정(허용을 회수당해 소설 행만 남은 계정 포함)에는 소설 영역이 없다 — 소설만 고른 목록도 403 이
    아니라 빈 목록이다."""
    user_id = await _creator(db_client, db_session)
    if allowed:
        await _allow_novelize(db_session, monkeypatch, user_id)
    work = await _content(db_session, user_id, ContentType.CHARACTER, published=False)
    novel = await _novel(db_session, user_id, "readable")
    await db_session.commit()

    everything = await _all_pages(db_client)
    novels_only = await db_client.get("/me/works", params={"type": "novel"})

    assert novels_only.status_code == 200
    if allowed:
        assert set(_ids(everything)) == {work, novel}
        assert _ids(novels_only.json()["items"]) == [novel]
    else:
        assert _ids(everything) == [work]
        assert novels_only.json()["items"] == []


# ── 필터 ─────────────────────────────────────────────────────────────────────────────────────


async def _portfolio(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> dict[str, uuid.UUID]:
    user_id = await _creator(db_client, db_session)
    await _allow_novelize(db_session, monkeypatch, user_id)
    character, story = ContentType.CHARACTER, ContentType.STORY
    works = {
        # 자동저장은 발행한 적 없는 초안에도 수정본 표시를 세운다 — 수정본 있음 필터가 발행 여부를 함께 봐야 빠진다.
        "c_draft": await _content(db_session, user_id, character, published=False, changes=True),
        "s_draft": await _content(db_session, user_id, story, published=False),
        "c_public": await _content(db_session, user_id, character, published=True),
        "s_public_changed": await _content(db_session, user_id, story, published=True, changes=True),
        "c_private_changed": await _content(
            db_session, user_id, character, published=True, visibility=ContentVisibility.PRIVATE, changes=True
        ),
        "c_link": await _content(db_session, user_id, character, published=True, visibility=ContentVisibility.LINK),
        "c_restricted": await _content(
            db_session, user_id, character, published=True, moderation=ModerationStatus.RESTRICTED
        ),
        "c_deleted": await _content(
            db_session, user_id, character, published=True, moderation=ModerationStatus.DELETED, changes=True
        ),
        "n_none": await _novel(db_session, user_id),
        "n_readable": await _novel(db_session, user_id, "readable"),
        "n_pending": await _novel(db_session, user_id, "pending"),
        "n_rejected": await _novel(db_session, user_id, "rejected"),
        "n_withdrawn": await _novel(db_session, user_id, "withdrawn"),
        "n_hidden": await _novel(db_session, user_id, "hidden"),
    }
    await db_session.commit()
    return works


_LISTED = {
    "c_draft",
    "s_draft",
    "c_public",
    "s_public_changed",
    "c_private_changed",
    "c_link",
    "c_restricted",
    "n_none",
    "n_readable",
    "n_pending",
    "n_rejected",
    "n_withdrawn",
}


@pytest.mark.parametrize(
    ("type_", "status", "expected"),
    [
        ("all", "all", _LISTED),
        ("all", "draft", {"c_draft", "s_draft", "n_none", "n_rejected"}),
        ("all", "public", {"c_public", "s_public_changed", "n_readable"}),
        ("all", "changed", {"s_public_changed", "c_private_changed"}),
        ("all", "review", {"n_pending"}),
        ("character", "all", {"c_draft", "c_public", "c_private_changed", "c_link", "c_restricted"}),
        ("story", "all", {"s_draft", "s_public_changed"}),
        ("novel", "all", {"n_none", "n_readable", "n_pending", "n_rejected", "n_withdrawn"}),
        ("character", "public", {"c_public"}),
        ("novel", "public", {"n_readable"}),
        ("character", "review", set()),
        ("novel", "changed", set()),
    ],
)
async def test_type_and_status_filters(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    type_: str,
    status: str,
    expected: set[str],
) -> None:
    """공개 중 = 발행됨 ∧ 공개 ∧ 이용제한 아님(소설은 독자가 지금 읽을 수 있음), 수정본 있음 = 발행됨 ∧ 수정본(공개 범위
    무관), 초안 = 발행된 적 없음(소설은 첫 공개 반려 포함), 심사 중 = 소설 첫 공개 승인 대기."""
    works = await _portfolio(db_client, db_session, monkeypatch)
    names = {work_id: name for name, work_id in works.items()}

    items = await _all_pages(db_client, type=type_, status=status)

    assert {names[work_id] for work_id in _ids(items)} == expected
    assert len(items) == len(expected)


async def test_novel_rows_report_their_publication_state(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """소설 행의 "공개 중" 표시는 `publication.readable` 하나다 — 공개 필터와 같은 판정이다."""
    works = await _portfolio(db_client, db_session, monkeypatch)

    by_id = {uuid.UUID(item["id"]): item for item in await _all_pages(db_client, type="novel")}

    assert by_id[works["n_none"]]["publication"] is None
    assert by_id[works["n_readable"]]["publication"] == {
        "visibility": "public",
        "reviewStatus": None,
        "moderationStatus": "normal",
        "readable": True,
    }
    assert by_id[works["n_pending"]]["publication"]["reviewStatus"] == "pending"
    assert by_id[works["n_pending"]]["publication"]["readable"] is False
    assert by_id[works["n_withdrawn"]]["publication"] == {
        "visibility": "withdrawn",
        "reviewStatus": None,
        "moderationStatus": "normal",
        "readable": False,
    }
    assert by_id[works["n_readable"]]["chapterCount"] == 1


async def test_work_rows_carry_publish_state_and_draft_title(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """작품 행의 제목은 작가가 고치고 있는 초안 버전의 것이다 — 수정본이 있는 발행작은 발행본 제목과 다를 수 있다."""
    user_id = await _creator(db_client, db_session)
    published = await _content(
        db_session,
        user_id,
        ContentType.STORY,
        published=True,
        visibility=ContentVisibility.PRIVATE,
        changes=True,
        draft_name="고친 제목",
        published_name="발행한 제목",
    )
    draft = await _content(db_session, user_id, ContentType.CHARACTER, published=False, draft_name="첫 초안")
    await db_session.commit()

    by_id = {uuid.UUID(item["id"]): item for item in await _all_pages(db_client)}

    assert by_id[published]["kind"] == "story"
    assert by_id[published]["title"] == "고친 제목"
    assert by_id[published]["hasPublished"] is True
    assert by_id[published]["hasUnpublishedChanges"] is True
    assert by_id[published]["visibility"] == "private"
    assert by_id[draft]["kind"] == "character"
    assert by_id[draft]["title"] == "첫 초안"
    assert by_id[draft]["hasPublished"] is False


async def test_title_search_matches_draft_titles_and_novel_titles(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """작품은 초안 버전 제목, 소설은 소설 제목(없으면 원작 제목)으로 찾는다."""
    user_id = await _creator(db_client, db_session)
    await _allow_novelize(db_session, monkeypatch, user_id)
    renamed = await _content(
        db_session, user_id, ContentType.CHARACTER, published=True, draft_name="새 등대", published_name="옛 등대"
    )
    await _content(db_session, user_id, ContentType.STORY, published=False, draft_name="안개 항구")
    titled_novel = await _novel(db_session, user_id, title="등대의 밤", content_title="다른 원작")
    untitled_novel = await _novel(db_session, user_id, content_title="등대 원작")
    await _novel(db_session, user_id, title="항구 이야기", content_title="등대 원작 사본")
    await db_session.commit()

    assert set(_ids(await _all_pages(db_client, q="등대"))) == {renamed, titled_novel, untitled_novel}
    assert _ids(await _all_pages(db_client, q="옛 등대")) == []
