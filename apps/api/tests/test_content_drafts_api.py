import uuid
from datetime import datetime, timedelta, timezone, UTC

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    Asset,
    CharacterVersionDetail,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    ModerationStatus,
    StoryPromptTemplate,
    StoryVersionDetail,
)
from factories import _get_genre, _login_as, _make_asset, _make_user


async def _make_content(
    db_session: AsyncSession,
    *,
    creator_user_id: uuid.UUID,
    genre_id: uuid.UUID,
    content_type: ContentType = ContentType.CHARACTER,
) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=content_type,
        genre_id=genre_id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()
    return content


async def _add_version(
    db_session: AsyncSession,
    content: Content,
    *,
    published: bool,
    created_at: datetime | None = None,
) -> ContentVersion:
    version = ContentVersion(
        content_id=content.id,
        version_number=1 if published else None,
        published_at=datetime.now(UTC) if published else None,
        detail_description="설명",
    )
    db_session.add(version)
    await db_session.flush()
    if published:
        # `_write_character_publish`/`_write_story_publish` also point the content at the
        # version they just published — the flag the drafts-list filter reads.
        content.current_published_version_id = version.id
        await db_session.flush()
    if created_at is not None:
        await db_session.execute(
            sa.update(ContentVersion)
            .where(ContentVersion.id == version.id)
            .values(created_at=created_at)
        )
        await db_session.refresh(version)
    return version


async def _add_character_detail(
    db_session: AsyncSession, version: ContentVersion, thumbnail: Asset, *, name: str
) -> CharacterVersionDetail:
    detail = CharacterVersionDetail(
        content_version_id=version.id,
        name=name,
        one_liner="한줄소개",
        thumbnail_asset_id=thumbnail.id,
        intro="인트로",
        example_dialogues=[],
        character_prompt="프롬프트",
    )
    db_session.add(detail)
    await db_session.flush()
    return detail


async def _add_story_detail(
    db_session: AsyncSession, version: ContentVersion, thumbnail: Asset, *, name: str
) -> StoryVersionDetail:
    detail = StoryVersionDetail(
        content_version_id=version.id,
        name=name,
        one_liner="한줄소개",
        thumbnail_asset_id=thumbnail.id,
        prompt_template=StoryPromptTemplate.BASIC,
    )
    db_session.add(detail)
    await db_session.flush()
    return detail


async def test_list_drafts_requires_login(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get("/me/drafts")
    assert resp.status_code == 401


async def test_list_drafts_returns_never_published_character_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    thumbnail = await _make_asset(db_session, user.id)

    content = await _make_content(
        db_session, creator_user_id=user.id, genre_id=genre.id, content_type=ContentType.CHARACTER
    )
    version = await _add_version(db_session, content, published=False)
    await _add_character_detail(db_session, version, thumbnail, name="캐릭터 초안")
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get("/me/drafts")
    assert resp.status_code == 200

    [draft] = resp.json()["items"]
    assert draft["id"] == str(content.id)
    assert draft["type"] == "character"
    assert draft["name"] == "캐릭터 초안"
    assert draft["thumbnailAssetId"] == str(thumbnail.id)
    assert draft["thumbnailUrl"]
    assert draft["updatedAt"]


async def test_list_drafts_returns_story_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    thumbnail = await _make_asset(db_session, user.id)

    content = await _make_content(
        db_session, creator_user_id=user.id, genre_id=genre.id, content_type=ContentType.STORY
    )
    version = await _add_version(db_session, content, published=False)
    await _add_story_detail(db_session, version, thumbnail, name="스토리 초안")
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get("/me/drafts")
    assert resp.status_code == 200

    [draft] = resp.json()["items"]
    assert draft["type"] == "story"
    assert draft["name"] == "스토리 초안"


async def test_list_drafts_excludes_content_with_no_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    thumbnail = await _make_asset(db_session, user.id)

    content = await _make_content(db_session, creator_user_id=user.id, genre_id=genre.id)
    version = await _add_version(db_session, content, published=True)
    await _add_character_detail(db_session, version, thumbnail, name="발행됨")
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get("/me/drafts")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_list_drafts_excludes_published_content_with_auto_cloned_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """발행하면 다음 편집용 초안이 자동 복제되므로 발행작에도 미발행 버전이 항상 딸려
    있다 — 그래도 초안 목록에는 나오지 않아야 한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    thumbnail = await _make_asset(db_session, user.id)

    content = await _make_content(db_session, creator_user_id=user.id, genre_id=genre.id)
    published_version = await _add_version(db_session, content, published=True)
    await _add_character_detail(db_session, published_version, thumbnail, name="발행 버전")
    draft_version = await _add_version(db_session, content, published=False)
    await _add_character_detail(db_session, draft_version, thumbnail, name="재발행용 초안")
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get("/me/drafts")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_list_drafts_drops_content_once_it_is_published(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """같은 콘텐츠를 발행 전/후 두 상태에서 본다 — 발행 전에는 초안으로 잡히고,
    발행하는 순간 목록에서 빠진다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    thumbnail = await _make_asset(db_session, user.id)

    content = await _make_content(db_session, creator_user_id=user.id, genre_id=genre.id)
    first_version = await _add_version(db_session, content, published=False)
    await _add_character_detail(db_session, first_version, thumbnail, name="작성 중")
    await db_session.commit()

    await _login_as(db_client, user.id)
    before = await db_client.get("/me/drafts")
    assert before.status_code == 200
    assert [draft["name"] for draft in before.json()["items"]] == ["작성 중"]

    # 발행: 이 버전이 발행본이 되고, 다음 편집용 초안이 자동 복제된다.
    first_version.version_number = 1
    first_version.published_at = datetime.now(UTC)
    content.current_published_version_id = first_version.id
    cloned_draft = await _add_version(db_session, content, published=False)
    await _add_character_detail(db_session, cloned_draft, thumbnail, name="작성 중")
    await db_session.commit()

    after = await db_client.get("/me/drafts")
    assert after.status_code == 200
    assert after.json()["items"] == []


async def test_list_drafts_only_returns_own_drafts(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner = _make_user()
    other = _make_user()
    db_session.add_all([owner, other])
    await db_session.flush()
    genre = await _get_genre(db_session)
    thumbnail = await _make_asset(db_session, other.id)

    content = await _make_content(db_session, creator_user_id=other.id, genre_id=genre.id)
    version = await _add_version(db_session, content, published=False)
    await _add_character_detail(db_session, version, thumbnail, name="다른 사람 초안")
    await db_session.commit()

    await _login_as(db_client, owner.id)
    resp = await db_client.get("/me/drafts")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_list_drafts_uses_latest_draft_row_when_multiple_exist(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    thumbnail = await _make_asset(db_session, user.id)

    content = await _make_content(db_session, creator_user_id=user.id, genre_id=genre.id)
    now = datetime.now(UTC)
    older_version = await _add_version(
        db_session, content, published=False, created_at=now - timedelta(hours=1)
    )
    await _add_character_detail(db_session, older_version, thumbnail, name="오래된 초안")
    newer_version = await _add_version(db_session, content, published=False, created_at=now)
    await _add_character_detail(db_session, newer_version, thumbnail, name="최신 초안")
    await db_session.commit()

    await _login_as(db_client, user.id)
    resp = await db_client.get("/me/drafts")
    assert resp.status_code == 200

    [draft] = resp.json()["items"]
    assert draft["name"] == "최신 초안"


async def test_list_drafts_paginates_at_page_size_without_duplicates(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`/me/drafts`도 `/users/{id}/contents`와 같은 페이지 크기(24)·같은 봉투를 쓴다.

    `Content.updated_at`은 server default라 이 테스트의 25건이 **전부 같은 시각**을 갖는다(하나의
    바깥 트랜잭션 안에서 `now()`가 고정되기 때문 — apps/api/CLAUDE.md). 그래서 순서는 tiebreaker인
    `id DESC`가 정하고, 그 사실이 곧 "동시각 25건에서도 페이지가 겹치거나 새지 않는다"의 검증이 된다.
    """
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    thumbnail = await _make_asset(db_session, user.id)

    total = 25
    for index in range(total):
        content = await _make_content(db_session, creator_user_id=user.id, genre_id=genre.id)
        version = await _add_version(db_session, content, published=False)
        await _add_character_detail(db_session, version, thumbnail, name=f"초안-{index:02d}")
    await db_session.commit()

    await _login_as(db_client, user.id)

    pages: list[list[dict[str, object]]] = []
    cursors: list[str | None] = []
    cursor: str | None = None
    for _ in range(10):
        params = {"cursor": cursor} if cursor is not None else {}
        resp = await db_client.get("/me/drafts", params=params)
        assert resp.status_code == 200
        body = resp.json()
        pages.append(body["items"])
        cursor = body["nextCursor"]
        cursors.append(cursor)
        if cursor is None:
            break
    else:
        raise AssertionError("커서가 10페이지 안에 끝나지 않았다")

    assert [len(page) for page in pages] == [24, 1]
    assert cursors[0] is not None
    assert cursors[-1] is None

    collected = [draft["id"] for page in pages for draft in page]
    assert len(collected) == total
    assert len(set(collected)) == total

    all_ids = set(
        (
            await db_session.scalars(
                sa.select(Content.id).where(
                    Content.creator_user_id == user.id,
                    Content.current_published_version_id.is_(None),
                )
            )
        ).all()
    )
    assert {uuid.UUID(str(content_id)) for content_id in collected} == all_ids


async def test_list_drafts_cursor_excludes_published_content_across_pages(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """커서에는 정렬 키만 들어 있으므로 "발행작 제외" 조건이 페이지마다 다시 걸려야 한다.
    발행작을 초안들 사이에 끼워 두고 페이지 경계를 넘겨도 새지 않는지 본다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    thumbnail = await _make_asset(db_session, user.id)

    draft_total = 25
    for index in range(draft_total):
        content = await _make_content(db_session, creator_user_id=user.id, genre_id=genre.id)
        version = await _add_version(db_session, content, published=False)
        await _add_character_detail(db_session, version, thumbnail, name=f"초안-{index:02d}")
    for index in range(3):
        published = await _make_content(db_session, creator_user_id=user.id, genre_id=genre.id)
        published_version = await _add_version(db_session, published, published=True)
        await _add_character_detail(db_session, published_version, thumbnail, name=f"발행-{index}")
        cloned_draft = await _add_version(db_session, published, published=False)
        await _add_character_detail(db_session, cloned_draft, thumbnail, name=f"발행-{index}")
    await db_session.commit()

    await _login_as(db_client, user.id)

    names: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        params = {"cursor": cursor} if cursor is not None else {}
        resp = await db_client.get("/me/drafts", params=params)
        assert resp.status_code == 200
        body = resp.json()
        names.extend(draft["name"] for draft in body["items"])
        cursor = body["nextCursor"]
        if cursor is None:
            break
    else:
        raise AssertionError("커서가 10페이지 안에 끝나지 않았다")

    assert sorted(names) == sorted(f"초안-{index:02d}" for index in range(draft_total))


async def test_list_drafts_q_searches_character_and_story_titles_ignoring_case(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """초안 목록은 `type` 인자가 없어 캐릭터·스토리 두 상세 테이블을 모두 봐야 한다. 이미 발행한
    작품의 자동 복제 초안은 제목이 같아도 여전히 빠진다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    thumbnail = await _make_asset(db_session, user.id)

    character = await _make_content(
        db_session, creator_user_id=user.id, genre_id=genre.id, content_type=ContentType.CHARACTER
    )
    await _add_character_detail(
        db_session, await _add_version(db_session, character, published=False), thumbnail, name="Star 캐릭터"
    )
    story = await _make_content(
        db_session, creator_user_id=user.id, genre_id=genre.id, content_type=ContentType.STORY
    )
    await _add_story_detail(
        db_session, await _add_version(db_session, story, published=False), thumbnail, name="starry 스토리"
    )
    other = await _make_content(db_session, creator_user_id=user.id, genre_id=genre.id)
    await _add_character_detail(
        db_session, await _add_version(db_session, other, published=False), thumbnail, name="무관한 초안"
    )
    published = await _make_content(db_session, creator_user_id=user.id, genre_id=genre.id)
    await _add_character_detail(
        db_session, await _add_version(db_session, published, published=True), thumbnail, name="STAR 발행작"
    )
    await _add_character_detail(
        db_session, await _add_version(db_session, published, published=False), thumbnail, name="STAR 발행작"
    )
    await db_session.commit()

    await _login_as(db_client, user.id)
    for q in ("STAR", "  sTaR "):
        resp = await db_client.get("/me/drafts", params={"q": q})
        assert resp.status_code == 200
        assert {draft["id"] for draft in resp.json()["items"]} == {str(character.id), str(story.id)}


async def test_list_drafts_q_matches_only_the_latest_draft_title_it_shows(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """목록에 보이는 제목은 가장 최근 초안의 것이다. 검색도 그 제목을 봐야 한다 — 옛 초안 제목으로
    걸려 나오면 화면에는 검색어가 없는 제목이 뜬다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    thumbnail = await _make_asset(db_session, user.id)

    content = await _make_content(db_session, creator_user_id=user.id, genre_id=genre.id)
    now = datetime.now(UTC)
    older = await _add_version(db_session, content, published=False, created_at=now - timedelta(hours=1))
    await _add_character_detail(db_session, older, thumbnail, name="옛 이름")
    newer = await _add_version(db_session, content, published=False, created_at=now)
    await _add_character_detail(db_session, newer, thumbnail, name="새 이름")
    await db_session.commit()

    await _login_as(db_client, user.id)
    old_hit = await db_client.get("/me/drafts", params={"q": "옛"})
    assert old_hit.json()["items"] == []
    new_hit = await db_client.get("/me/drafts", params={"q": "새"})
    assert [draft["name"] for draft in new_hit.json()["items"]] == ["새 이름"]


async def test_list_drafts_q_treats_like_wildcards_and_backslash_as_plain_text(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    thumbnail = await _make_asset(db_session, user.id)
    for name, content_type in [
        ("100% 진심", ContentType.CHARACTER),
        ("a_b", ContentType.STORY),
        ("역\\슬래시", ContentType.CHARACTER),
        ("평범한 제목", ContentType.STORY),
    ]:
        content = await _make_content(
            db_session, creator_user_id=user.id, genre_id=genre.id, content_type=content_type
        )
        version = await _add_version(db_session, content, published=False)
        if content_type == ContentType.CHARACTER:
            await _add_character_detail(db_session, version, thumbnail, name=name)
        else:
            await _add_story_detail(db_session, version, thumbnail, name=name)
    await db_session.commit()

    await _login_as(db_client, user.id)
    for q, expected in [("%", "100% 진심"), ("_", "a_b"), ("\\", "역\\슬래시")]:
        resp = await db_client.get("/me/drafts", params={"q": q})
        assert resp.status_code == 200, q
        assert [draft["name"] for draft in resp.json()["items"]] == [expected], q


async def test_list_drafts_blank_q_returns_same_bytes_as_no_q(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    thumbnail = await _make_asset(db_session, user.id)
    for name in ["첫째", "둘째"]:
        content = await _make_content(db_session, creator_user_id=user.id, genre_id=genre.id)
        await _add_character_detail(
            db_session, await _add_version(db_session, content, published=False), thumbnail, name=name
        )
    await db_session.commit()

    await _login_as(db_client, user.id)
    baseline = await db_client.get("/me/drafts")
    assert len(baseline.json()["items"]) == 2
    for q in ("", "   "):
        resp = await db_client.get("/me/drafts", params={"q": q})
        assert resp.status_code == 200
        assert resp.content == baseline.content


async def test_list_drafts_q_keeps_filter_across_cursor_pages(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """커서에는 정렬 키만 들어 있으므로 `q` 도 페이지마다 다시 걸려야 한다. 걸리지 않는 초안을
    섞어 두고 두 번째 페이지까지 읽어도 걸리는 초안만 빠짐없이 한 번씩 나오는지 본다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    thumbnail = await _make_asset(db_session, user.id)

    match_total = 25
    for index in range(match_total + 5):
        name = f"검색어-{index:02d}" if index < match_total else f"다른 제목-{index:02d}"
        content = await _make_content(db_session, creator_user_id=user.id, genre_id=genre.id)
        await _add_character_detail(
            db_session, await _add_version(db_session, content, published=False), thumbnail, name=name
        )
    await db_session.commit()

    await _login_as(db_client, user.id)
    pages: list[list[str]] = []
    cursor: str | None = None
    for _ in range(10):
        params = {"q": "검색어"} | ({"cursor": cursor} if cursor is not None else {})
        resp = await db_client.get("/me/drafts", params=params)
        assert resp.status_code == 200
        body = resp.json()
        pages.append([draft["name"] for draft in body["items"]])
        cursor = body["nextCursor"]
        if cursor is None:
            break
    else:
        raise AssertionError("커서가 10페이지 안에 끝나지 않았다")

    assert [len(page) for page in pages] == [24, 1]
    collected = [name for page in pages for name in page]
    assert sorted(collected) == [f"검색어-{index:02d}" for index in range(match_total)]
