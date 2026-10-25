"""소설 화 삽화 — 배치 쓰기(붙이기·옮기기·바꾸기·떼기)와 그 개정, 다른 개정 경로의 배치 승계, 그림 권한, 원작 그림 후보,
쓰이는 그림 보호, 업로드 삽화 파일의 수명, 삽화 스위치.

배치 변경은 본문이 같은 새 개정(출처 `illustration`)을 쌓는다. 되돌리기·스냅숏 복원은 원본 개정의 배치를 그대로 복사하고, 그
밖의 새 개정은 앞 개정에서 앵커 문단이 살아 있는 배치를 잇고 사라진 것은 "위치 확인 필요"로 남긴다(자동으로 옮기지 않는다)."""

import ast
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models import (
    Asset,
    AssetKind,
    AssetStatus,
    CharacterImageExposure,
    CloverLedger,
    Content,
    ContentType,
    ImageGenerationRequest,
    Novel,
    NovelChapter,
    NovelChapterIllustration,
    NovelChapterRevision,
    SituationalImage,
    StoryMediaExposure,
)
from api.novelize import blocks
from api.novelize import illustrations as illustrations_module
from api.novelize.illustrations import add_revision
from factories import (
    Room,
    _NeverCalledLLMClient,
    _add_chapter,
    _add_named_media_cell,
    _clear_llm_override,
    _finished_ai_edit,
    _login_as,
    _make_user,
    _novel_setup,
    _override_llm_client,
    _room_messages,
)

pytestmark = pytest.mark.usefixtures("novel_prices_for_flow_tests")

_BODY = "첫 문단이다.\n\n둘째 문단이다.\n\n셋째 문단이다."
_SRC = Path(__file__).resolve().parents[1] / "src" / "api"


@pytest.fixture(autouse=True)
def _no_model() -> Iterator[None]:
    _override_llm_client(_NeverCalledLLMClient())
    yield
    _clear_llm_override()


@pytest.fixture
def illustrations_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novel_illustrations_enabled", True)


@pytest.fixture
def deleted_keys(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """저장소 삭제를 기록만 한다(업로드 삽화 파일을 지우는 경로가 무엇을 지우려 했는지 본다)."""
    seen: list[str] = []
    monkeypatch.setattr(illustrations_module, "delete_object", seen.append)
    return seen


async def _chapter(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, *, lane: str = "character"
) -> tuple[Room, uuid.UUID, NovelChapter]:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, lane=lane)
    messages = await _room_messages(db_session, room.room_id)
    chapter = await _add_chapter(db_session, novel_id, room, messages[0], room.turns[1][1], body=_BODY)
    return room, novel_id, chapter


async def _revisions(db: AsyncSession, chapter_id: uuid.UUID) -> list[NovelChapterRevision]:
    rows = await db.scalars(
        sa.select(NovelChapterRevision)
        .where(NovelChapterRevision.chapter_id == chapter_id)
        .order_by(NovelChapterRevision.revision_no)
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


async def _current(db: AsyncSession, chapter_id: uuid.UUID) -> NovelChapterRevision:
    return (await _revisions(db, chapter_id))[-1]


async def _placements(db: AsyncSession, revision_id: uuid.UUID) -> list[tuple[Any, ...]]:
    """개정의 배치를 (앵커, 앞뒤, 순서, 자산, 출처)로 — 위치 있는 것 먼저(앵커·앞뒤·순서), 위치 확인 필요는 뒤(순서)."""
    rows = await db.execute(
        sa.select(
            NovelChapterIllustration.anchor_block_id,
            NovelChapterIllustration.placement,
            NovelChapterIllustration.sort_order,
            NovelChapterIllustration.asset_id,
            NovelChapterIllustration.source,
        )
        .where(NovelChapterIllustration.revision_id == revision_id)
        .order_by(
            NovelChapterIllustration.anchor_block_id.is_(None),
            NovelChapterIllustration.anchor_block_id,
            NovelChapterIllustration.placement,
            NovelChapterIllustration.sort_order,
        )
    )
    return [tuple(row) for row in rows.all()]


async def _asset(
    db: AsyncSession,
    owner_id: uuid.UUID,
    *,
    kind: AssetKind = AssetKind.GENERATED,
    status: AssetStatus = AssetStatus.READY,
    prefix: str = "assets/generated/",
) -> Asset:
    asset = Asset(
        owner_user_id=owner_id,
        storage_key=f"{prefix}{uuid.uuid4()}.webp",
        kind=kind,
        status=status,
        width=300,
        height=400,
    )
    db.add(asset)
    await db.commit()
    return asset


async def _upload(db: AsyncSession, owner_id: uuid.UUID) -> Asset:
    return await _asset(db, owner_id, kind=AssetKind.ORIGINAL, prefix="assets/novel-illustration/")


async def _attach(
    db_client: httpx.AsyncClient,
    novel_id: uuid.UUID,
    chapter_id: uuid.UUID,
    base: NovelChapterRevision,
    anchor: uuid.UUID,
    asset_id: uuid.UUID,
    *,
    source: str = "generated",
    placement: str = "after",
    order: int | None = None,
) -> httpx.Response:
    body: dict[str, Any] = {
        "baseRevisionId": str(base.id),
        "anchorBlockId": str(anchor),
        "placement": placement,
        "assetId": str(asset_id),
        "source": source,
    }
    if order is not None:
        body["order"] = order
    return await db_client.post(f"/novels/{novel_id}/chapters/{chapter_id}/illustrations", json=body)


async def _ok(resp: httpx.Response) -> dict[str, Any]:
    assert resp.status_code == 201, resp.text
    revision: dict[str, Any] = resp.json()["revision"]
    return revision


# ── 스위치 ──────────────────────────────────────────────────────────────────
async def test_with_the_switch_off_the_placement_routes_are_404_and_responses_carry_no_pictures(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """스위치가 꺼져 있으면 배치 API·원작 후보가 모두 캐시하지 않는 404 이고, 개정에 배치가 남아 있어도 화 응답에 그림이 없다.
    깨지는 시나리오: 약관 게시 전에 작가가 그림을 붙이거나, 스위치를 끈 뒤에도 켰을 때 붙인 그림이 화면에 나간다."""
    room, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    current = await _current(db_session, chapter.id)
    asset = await _asset(db_session, room.user_id)
    db_session.add(
        NovelChapterIllustration(
            revision_id=current.id,
            anchor_block_id=current.block_ids[0],
            placement="after",
            sort_order=0,
            asset_id=asset.id,
            source="generated",
        )
    )
    await db_session.commit()
    some_id = uuid.uuid4()
    base = f"/novels/{novel_id}/chapters/{chapter.id}/illustrations"

    responses = [
        await _attach(db_client, novel_id, chapter.id, current, current.block_ids[0], asset.id),
        await db_client.post(f"{base}/{some_id}/move", json={"baseRevisionId": str(current.id)}),
        await db_client.post(f"{base}/{some_id}/replace", json={"baseRevisionId": str(current.id)}),
        await db_client.post(f"{base}/{some_id}/detach", json={"baseRevisionId": str(current.id)}),
        await db_client.get(f"/novels/{novel_id}/illustration-candidates"),
    ]
    chapter_view = (await db_client.get(f"/novels/{novel_id}/chapters/{chapter.id}")).json()["revision"]

    assert [(r.status_code, r.headers.get("cache-control")) for r in responses] == [(404, "no-store")] * 5
    assert (chapter_view["illustrations"], chapter_view["unplacedIllustrations"]) == ([], [])
    assert len(await _revisions(db_session, chapter.id)) == 1


# ── 붙이기 ──────────────────────────────────────────────────────────────────
@pytest.mark.usefixtures("illustrations_on")
async def test_attaching_a_picture_stacks_a_same_text_revision_that_carries_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """붙이기는 본문·블록 id 가 그대로인 새 개정(출처 illustration)을 쌓고 그 개정에만 배치가 있다. 응답은 그림 주소·크기·출처를
    문단 블록 id 와 함께 싣는다. 클로버는 쓰지 않는다. 깨지는 시나리오: 배치가 옛 개정을 고쳐 판 이력·공개본이 그림까지 바뀌거나,
    본문 해시가 달라져 미리보기·공개 판정이 "바뀜"으로 본다."""
    room, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    first = await _current(db_session, chapter.id)
    asset = await _asset(db_session, room.user_id)
    ledger_before = await db_session.scalar(sa.select(sa.func.count()).select_from(CloverLedger))

    revision = await _ok(await _attach(db_client, novel_id, chapter.id, first, first.block_ids[1], asset.id))

    second = await _current(db_session, chapter.id)
    assert (second.revision_no, second.source, second.body, second.block_ids, second.content_hash) == (
        2,
        "illustration",
        first.body,
        first.block_ids,
        first.content_hash,
    )
    assert await _placements(db_session, first.id) == []
    assert await _placements(db_session, second.id) == [(first.block_ids[1], "after", 0, asset.id, "generated")]
    (shown,) = revision["illustrations"]
    assert (shown["anchorBlockId"], shown["placement"], shown["order"], shown["assetId"], shown["source"]) == (
        str(first.block_ids[1]),
        "after",
        0,
        str(asset.id),
        "generated",
    )
    assert (shown["width"], shown["height"]) == (300, 400)
    assert "_display.webp" in shown["url"]
    assert revision["unplacedIllustrations"] == []
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(CloverLedger)) == ledger_before


@pytest.mark.usefixtures("illustrations_on")
async def test_a_placement_change_on_an_older_revision_is_409_and_stacks_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """기준 개정이 지금 개정이 아니면(다른 탭이 먼저 고침) 409 `NOVEL_REVISION_CONFLICT` 이고 개정이 늘지 않는다. 깨지는
    시나리오: 옛 화면 기준으로 붙인 그림이 그사이 쌓인 개정의 배치를 덮어 다른 탭의 그림이 사라진다."""
    room, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    first = await _current(db_session, chapter.id)
    asset = await _asset(db_session, room.user_id)
    await _ok(await _attach(db_client, novel_id, chapter.id, first, first.block_ids[0], asset.id))

    stale = await _attach(db_client, novel_id, chapter.id, first, first.block_ids[2], asset.id)

    assert stale.status_code == 409 and stale.json()["detail"] == {"code": "NOVEL_REVISION_CONFLICT"}
    assert len(await _revisions(db_session, chapter.id)) == 2


@pytest.mark.usefixtures("illustrations_on")
async def test_attaching_to_a_paragraph_the_current_revision_does_not_have_is_422(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    first = await _current(db_session, chapter.id)
    asset = await _asset(db_session, room.user_id)

    resp = await _attach(db_client, novel_id, chapter.id, first, uuid.uuid4(), asset.id)

    assert resp.status_code == 422 and resp.json()["detail"] == {"code": "NOVEL_ILLUSTRATION_ANCHOR_INVALID"}
    assert len(await _revisions(db_session, chapter.id)) == 1


@pytest.mark.usefixtures("illustrations_on")
@pytest.mark.parametrize(
    "case",
    [
        pytest.param("others_generated", id="others_generated"),
        pytest.param("pending_generated", id="pending_generated"),
        pytest.param("others_upload", id="others_upload"),
        pytest.param("own_non_illustration_upload", id="own_non_illustration_upload"),
        pytest.param("generated_called_upload", id="generated_called_upload"),
        pytest.param("upload_called_generated", id="upload_called_generated"),
        pytest.param("missing", id="missing"),
    ],
)
async def test_a_picture_the_author_may_not_use_is_refused(
    case: str, db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """남의 생성 이미지·남의 업로드·아직 준비 안 된 자산·삽화 용도가 아닌 내 업로드, 그리고 출처를 바꿔 부른 내 그림은 모두 422
    `NOVEL_ILLUSTRATION_ASSET_INVALID` 이고 개정이 늘지 않는다. 깨지는 시나리오: 남의 자산 id 를 알아낸 작가가 남의 그림을 자기
    소설에 싣거나, 업로드 출처로 부른 생성 이미지가 업로드 파일 수명 규칙에 걸려 지워진다."""
    room, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    first = await _current(db_session, chapter.id)
    other = _make_user()
    db_session.add(other)
    await db_session.commit()
    source = "generated"
    if case == "others_generated":
        asset_id = (await _asset(db_session, other.id)).id
    elif case == "pending_generated":
        asset_id = (await _asset(db_session, room.user_id, status=AssetStatus.PENDING)).id
    elif case == "others_upload":
        asset_id, source = (await _upload(db_session, other.id)).id, "upload"
    elif case == "own_non_illustration_upload":
        asset_id = (await _asset(db_session, room.user_id, kind=AssetKind.ORIGINAL, prefix="assets/situational-image/")).id
        source = "upload"
    elif case == "generated_called_upload":
        asset_id, source = (await _asset(db_session, room.user_id)).id, "upload"
    elif case == "upload_called_generated":
        asset_id = (await _upload(db_session, room.user_id)).id
    else:
        asset_id = uuid.uuid4()

    resp = await _attach(db_client, novel_id, chapter.id, first, first.block_ids[0], asset_id, source=source)

    assert resp.status_code == 422 and resp.json()["detail"] == {"code": "NOVEL_ILLUSTRATION_ASSET_INVALID"}
    assert len(await _revisions(db_session, chapter.id)) == 1


@pytest.mark.usefixtures("illustrations_on")
async def test_an_own_upload_for_illustrations_is_attached_as_an_upload(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    first = await _current(db_session, chapter.id)
    upload = await _upload(db_session, room.user_id)

    revision = await _ok(
        await _attach(db_client, novel_id, chapter.id, first, first.block_ids[0], upload.id, source="upload", placement="before")
    )

    assert [(i["assetId"], i["source"], i["placement"]) for i in revision["illustrations"]] == [
        (str(upload.id), "upload", "before")
    ]


# ── 원작 그림 ───────────────────────────────────────────────────────────────
async def _hand_original_to_someone_else(db: AsyncSession, novel_id: uuid.UUID) -> Content:
    novel = await db.get_one(Novel, novel_id)
    creator = _make_user()
    db.add(creator)
    await db.flush()
    await db.execute(sa.update(Content).where(Content.id == novel.content_id).values(creator_user_id=creator.id))
    await db.commit()
    return await db.get_one(Content, novel.content_id, populate_existing=True)


async def _situational_image(db: AsyncSession, content: Content) -> tuple[SituationalImage, Asset, Asset]:
    assert content.current_published_version_id is not None
    image = await _asset(db, content.creator_user_id, kind=AssetKind.ORIGINAL, prefix="assets/situational-image/")
    blurred = await _asset(db, content.creator_user_id, kind=AssetKind.BLURRED, prefix="assets/blurred/")
    row = SituationalImage(
        entity_id=uuid.uuid4(),
        content_version_id=content.current_published_version_id,
        image_asset_id=image.id,
        blurred_asset_id=blurred.id,
        trigger_condition="골목에서 마주칠 때",
        order=0,
    )
    db.add(row)
    await db.commit()
    return row, image, blurred


async def _thumbnail(db: AsyncSession, content: Content) -> uuid.UUID:
    from api.db.models import CharacterVersionDetail, StoryVersionDetail

    model = CharacterVersionDetail if content.type == ContentType.CHARACTER else StoryVersionDetail
    thumbnail = await db.scalar(
        sa.select(model.thumbnail_asset_id).where(model.content_version_id == content.current_published_version_id)
    )
    assert thumbnail is not None
    return thumbnail


@pytest.mark.usefixtures("illustrations_on")
async def test_an_author_uses_only_the_original_pictures_they_have_seen(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """남의 원작이면 대표 이미지와 작가가 그 작품에서 본(노출 기록이 있는) 상황 이미지만 후보이고 붙일 수 있다. 못 본 그림·블러본·
    다른 작품의 그림은 후보에 없고 붙이면 422 다. 깨지는 시나리오: 아직 해금하지 않은 그림(스포일러)이 작가의 소설로 새거나,
    블러본 대신 원본을 알아낸다."""
    room, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    content = await _hand_original_to_someone_else(db_session, novel_id)
    seen, seen_asset, seen_blurred = await _situational_image(db_session, content)
    _unseen, unseen_asset, _ = await _situational_image(db_session, content)
    db_session.add(CharacterImageExposure(user_id=room.user_id, content_id=content.id, image_entity_id=seen.entity_id))
    await db_session.commit()
    thumbnail = await _thumbnail(db_session, content)
    _other_room, other_novel = await _novel_setup(db_client, db_session, monkeypatch)
    other_content = await _hand_original_to_someone_else(db_session, other_novel)
    _x, foreign_asset, _y = await _situational_image(db_session, other_content)
    db_session.add(CharacterImageExposure(user_id=room.user_id, content_id=other_content.id, image_entity_id=_x.entity_id))
    await db_session.commit()
    await _login_as(db_client, room.user_id)

    candidates = await db_client.get(f"/novels/{novel_id}/illustration-candidates")
    first = await _current(db_session, chapter.id)
    refused = [
        await _attach(db_client, novel_id, chapter.id, first, first.block_ids[0], asset_id, source="original")
        for asset_id in (unseen_asset.id, seen_blurred.id, foreign_asset.id)
    ]
    accepted = await _attach(db_client, novel_id, chapter.id, first, first.block_ids[0], seen_asset.id, source="original")

    assert candidates.status_code == 200, candidates.text
    assert {(item["assetId"], item["kind"]) for item in candidates.json()["items"]} == {
        (str(thumbnail), "thumbnail"),
        (str(seen_asset.id), "situationalImage"),
    }
    assert [r.status_code for r in refused] == [422, 422, 422]
    assert [i["source"] for i in (await _ok(accepted))["illustrations"]] == ["original"]


@pytest.mark.usefixtures("illustrations_on")
async def test_the_creator_of_the_original_may_use_all_of_its_current_pictures(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """작가가 원작자 본인이면 지금 발행본의 그림 전부가 후보다(본 적 없어도). 깨지는 시나리오: 자기 작품 그림을 자기 소설에
    쓰려는 원작자가 노출 기록이 없어 막힌다."""
    room, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    novel = await db_session.get_one(Novel, novel_id)
    content = await db_session.get_one(Content, novel.content_id)
    assert content.creator_user_id == room.user_id
    _row, unseen_asset, _ = await _situational_image(db_session, content)
    first = await _current(db_session, chapter.id)

    candidates = await db_client.get(f"/novels/{novel_id}/illustration-candidates")
    attached = await _attach(db_client, novel_id, chapter.id, first, first.block_ids[0], unseen_asset.id, source="original")

    assert str(unseen_asset.id) in {item["assetId"] for item in candidates.json()["items"]}
    assert [i["assetId"] for i in (await _ok(attached))["illustrations"]] == [str(unseen_asset.id)]


@pytest.mark.usefixtures("illustrations_on")
async def test_story_media_book_cells_are_candidates_only_once_seen(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, novel_id, _chapter_row = await _chapter(db_client, db_session, monkeypatch, lane="story")
    content = await _hand_original_to_someone_else(db_session, novel_id)
    assert content.current_published_version_id is not None
    seen, seen_asset = await _add_named_media_cell(
        db_session, content.current_published_version_id, content.creator_user_id, "민아", "교실"
    )
    _unseen, unseen_asset = await _add_named_media_cell(
        db_session, content.current_published_version_id, content.creator_user_id, "민아", "옥상"
    )
    db_session.add(StoryMediaExposure(user_id=room.user_id, content_id=content.id, cell_entity_id=seen.entity_id))
    await db_session.commit()

    items = (await db_client.get(f"/novels/{novel_id}/illustration-candidates")).json()["items"]

    listed = {(item["assetId"], item["kind"]) for item in items}
    assert (str(seen_asset.id), "mediaBook") in listed
    assert str(unseen_asset.id) not in {asset_id for asset_id, _kind in listed}


# ── 옮기기·바꾸기·떼기 ──────────────────────────────────────────────────────
@pytest.mark.usefixtures("illustrations_on")
async def test_moving_reorders_within_a_slot_and_carries_a_picture_to_another_paragraph(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """같은 자리에 둘째로 붙인 그림을 맨 앞으로 옮기고, 다른 문단 앞으로 옮긴다. 순서는 자리마다 0부터 빈틈없이 다시 매긴다.
    깨지는 시나리오: 옮긴 뒤 남은 그림의 순서 값에 빈틈이 생겨 화면은 같은데 공개 판정이 "바뀜"으로 보거나, 옮긴 그림이 옛
    자리에도 남는다."""
    room, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    first = await _current(db_session, chapter.id)
    a = await _asset(db_session, room.user_id)
    b = await _asset(db_session, room.user_id)
    anchor = first.block_ids[0]
    await _ok(await _attach(db_client, novel_id, chapter.id, first, anchor, a.id))
    revision = await _ok(await _attach(db_client, novel_id, chapter.id, await _current(db_session, chapter.id), anchor, b.id))
    b_id = next(i["id"] for i in revision["illustrations"] if i["assetId"] == str(b.id))
    base = f"/novels/{novel_id}/chapters/{chapter.id}/illustrations"

    reordered = await _ok(
        await db_client.post(
            f"{base}/{b_id}/move",
            json={
                "baseRevisionId": revision["id"],
                "anchorBlockId": str(anchor),
                "placement": "after",
                "order": 0,
            },
        )
    )
    a_id = next(i["id"] for i in reordered["illustrations"] if i["assetId"] == str(a.id))
    moved = await _ok(
        await db_client.post(
            f"{base}/{a_id}/move",
            json={"baseRevisionId": reordered["id"], "anchorBlockId": str(first.block_ids[2]), "placement": "before"},
        )
    )

    assert await _placements(db_session, uuid.UUID(reordered["id"])) == sorted(
        [(anchor, "after", 0, b.id, "generated"), (anchor, "after", 1, a.id, "generated")], key=lambda r: r[2]
    )
    assert sorted(await _placements(db_session, uuid.UUID(moved["id"])), key=str) == sorted(
        [(anchor, "after", 0, b.id, "generated"), (first.block_ids[2], "before", 0, a.id, "generated")], key=str
    )
    assert [(i["anchorBlockId"], i["assetId"]) for i in moved["illustrations"]] == [
        (str(anchor), str(b.id)),
        (str(first.block_ids[2]), str(a.id)),
    ]


@pytest.mark.usefixtures("illustrations_on")
async def test_replacing_keeps_the_spot_and_detaching_keeps_the_file_free_of_charge(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, deleted_keys: list[str]
) -> None:
    """바꾸기는 자리를 두고 그림만 바꾸고, 떼기는 그 자리를 비운다. 둘 다 클로버를 쓰지 않고 그림 파일·자산 행을 지우지 않는다
    (앞 개정이 여전히 쓴다). 깨지는 시나리오: 떼기가 업로드 파일을 지워 되돌리기로 돌아간 개정의 그림이 깨진다."""
    room, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    first = await _current(db_session, chapter.id)
    upload = await _upload(db_session, room.user_id)
    other = await _asset(db_session, room.user_id)
    attached = await _ok(
        await _attach(db_client, novel_id, chapter.id, first, first.block_ids[1], upload.id, source="upload")
    )
    ledger_before = await db_session.scalar(sa.select(sa.func.count()).select_from(CloverLedger))
    base = f"/novels/{novel_id}/chapters/{chapter.id}/illustrations"
    (spot,) = attached["illustrations"]

    replaced = await _ok(
        await db_client.post(
            f"{base}/{spot['id']}/replace",
            json={"baseRevisionId": attached["id"], "assetId": str(other.id), "source": "generated"},
        )
    )
    (new_spot,) = replaced["illustrations"]
    detached = await _ok(
        await db_client.post(f"{base}/{new_spot['id']}/detach", json={"baseRevisionId": replaced["id"]})
    )

    assert await _placements(db_session, uuid.UUID(replaced["id"])) == [
        (first.block_ids[1], "after", 0, other.id, "generated")
    ]
    assert (detached["illustrations"], detached["unplacedIllustrations"]) == ([], [])
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(CloverLedger)) == ledger_before
    assert await db_session.get(Asset, upload.id) is not None
    assert deleted_keys == []


@pytest.mark.usefixtures("illustrations_on")
async def test_a_placement_of_an_older_revision_is_not_found(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """옮기기·바꾸기·떼기는 기준 개정(=지금 개정)의 배치만 고른다 — 옛 개정의 배치 id 는 404. 깨지는 시나리오: 옛 판의 행을
    고른 요청이 지금 판에 없는 그림을 되살린다."""
    room, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    first = await _current(db_session, chapter.id)
    asset = await _asset(db_session, room.user_id)
    attached = await _ok(await _attach(db_client, novel_id, chapter.id, first, first.block_ids[0], asset.id))
    (spot,) = attached["illustrations"]
    detached = await _ok(
        await db_client.post(
            f"/novels/{novel_id}/chapters/{chapter.id}/illustrations/{spot['id']}/detach",
            json={"baseRevisionId": attached["id"]},
        )
    )

    resp = await db_client.post(
        f"/novels/{novel_id}/chapters/{chapter.id}/illustrations/{spot['id']}/detach",
        json={"baseRevisionId": detached["id"]},
    )

    assert resp.status_code == 404 and resp.json()["detail"] == {"code": "NOVEL_ILLUSTRATION_NOT_FOUND"}


# ── 승계 ────────────────────────────────────────────────────────────────────
@pytest.mark.usefixtures("illustrations_on")
async def test_a_direct_edit_keeps_pictures_on_surviving_paragraphs_and_marks_the_rest_for_a_position_check(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """직접 수정으로 앵커 문단을 지우면 그 그림은 위치 확인 필요로 가고(다른 문단으로 옮기지 않는다), 살아 있는 문단의 그림은
    자리·순서가 그대로다. 위치 확인 필요 그림은 다음 개정에도 이어진다. 깨지는 시나리오: 사라진 문단의 그림이 조용히 사라지거나
    엉뚱한 문단에 붙는다."""
    room, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    first = await _current(db_session, chapter.id)
    kept = await _asset(db_session, room.user_id)
    lost = await _asset(db_session, room.user_id)
    await _ok(await _attach(db_client, novel_id, chapter.id, first, first.block_ids[0], kept.id))
    revision = await _ok(
        await _attach(db_client, novel_id, chapter.id, await _current(db_session, chapter.id), first.block_ids[1], lost.id)
    )

    edited = await db_client.post(
        f"/novels/{novel_id}/chapters/{chapter.id}/revisions",
        json={"baseRevisionId": revision["id"], "body": "첫 문단이다.\n\n셋째 문단이다."},
    )
    after_edit = await _current(db_session, chapter.id)
    again = await db_client.post(
        f"/novels/{novel_id}/chapters/{chapter.id}/revisions",
        json={"baseRevisionId": str(after_edit.id), "body": "첫 문단이다.\n\n셋째 문단이다.\n\n넷째."},
    )
    latest = await _current(db_session, chapter.id)

    assert edited.status_code == 201, edited.text
    body = edited.json()["revision"]
    assert [(i["anchorBlockId"], i["assetId"]) for i in body["illustrations"]] == [(str(first.block_ids[0]), str(kept.id))]
    assert [(i["anchorBlockId"], i["placement"], i["assetId"]) for i in body["unplacedIllustrations"]] == [
        (None, None, str(lost.id))
    ]
    assert again.status_code == 201, again.text
    assert await _placements(db_session, latest.id) == [
        (first.block_ids[0], "after", 0, kept.id, "generated"),
        (None, None, 0, lost.id, "generated"),
    ]


@pytest.mark.usefixtures("illustrations_on")
async def test_an_unplaced_picture_is_put_back_by_moving_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    first = await _current(db_session, chapter.id)
    asset = await _asset(db_session, room.user_id)
    await _ok(await _attach(db_client, novel_id, chapter.id, first, first.block_ids[1], asset.id))
    edited = await db_client.post(
        f"/novels/{novel_id}/chapters/{chapter.id}/revisions",
        json={"baseRevisionId": str((await _current(db_session, chapter.id)).id), "body": "첫 문단이다.\n\n셋째 문단이다."},
    )
    (unplaced,) = edited.json()["revision"]["unplacedIllustrations"]

    moved = await _ok(
        await db_client.post(
            f"/novels/{novel_id}/chapters/{chapter.id}/illustrations/{unplaced['id']}/move",
            json={
                "baseRevisionId": edited.json()["revision"]["id"],
                "anchorBlockId": str(first.block_ids[2]),
                "placement": "after",
            },
        )
    )

    assert [(i["anchorBlockId"], i["assetId"]) for i in moved["illustrations"]] == [(str(first.block_ids[2]), str(asset.id))]
    assert moved["unplacedIllustrations"] == []


async def test_new_paragraph_ids_send_every_picture_to_the_position_check(db_session: AsyncSession) -> None:
    """다시 만들기처럼 문단 id 를 모두 새로 받은 개정은 모든 그림을 위치 확인 필요로 넘긴다(순서는 앞 개정의 읽는 순서).
    깨지는 시나리오: 새 id 와 우연히 맞춘 자리로 그림이 옮겨 가거나, 그림이 다음 개정에서 사라진다."""
    from factories import NovelTree, _make_novel_tree

    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    tree: NovelTree = await _make_novel_tree(db_session, user.id)
    first = tree.reverting_revision
    a = await _asset(db_session, user.id)
    b = await _asset(db_session, user.id)
    db_session.add_all(
        [
            NovelChapterIllustration(
                revision_id=first.id, anchor_block_id=first.block_ids[0], placement="after", sort_order=0, asset_id=a.id, source="generated"
            ),
            NovelChapterIllustration(
                revision_id=first.id, anchor_block_id=first.block_ids[0], placement="before", sort_order=0, asset_id=b.id, source="generated"
            ),
        ]
    )
    await db_session.flush()

    fresh = blocks.build_revision(
        chapter_id=tree.chapter.id, revision_no=3, body=first.body, source="regenerate", block_ids=blocks.fresh_ids(first.body)
    )
    added = await add_revision(db_session, fresh, previous=first)

    assert await _placements(db_session, added.id) == [
        (None, None, 0, b.id, "generated"),
        (None, None, 1, a.id, "generated"),
    ]


@pytest.mark.usefixtures("illustrations_on")
async def test_restoring_an_older_revision_brings_its_pictures_back(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """그림을 붙인 판(r2) → 뗀 판(r3) → r2 로 되돌리면 r4 의 배치가 r2 와 같다. 스냅숏 복원도 같다. 깨지는 시나리오: 되돌리기가
    지금 판(그림 없음)에서 배치를 이어 옛 판의 그림이 돌아오지 않는다."""
    room, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    first = await _current(db_session, chapter.id)
    asset = await _asset(db_session, room.user_id)
    with_picture = await _ok(await _attach(db_client, novel_id, chapter.id, first, first.block_ids[2], asset.id))
    snapshot = await db_client.post(f"/novels/{novel_id}/snapshots", json={"name": "그림 붙인 때"})
    assert snapshot.status_code == 201, snapshot.text
    (spot,) = with_picture["illustrations"]
    detached = await _ok(
        await db_client.post(
            f"/novels/{novel_id}/chapters/{chapter.id}/illustrations/{spot['id']}/detach",
            json={"baseRevisionId": with_picture["id"]},
        )
    )

    restored = await db_client.post(
        f"/novels/{novel_id}/chapters/{chapter.id}/revisions/{with_picture['id']}/restore",
        json={"baseRevisionId": detached["id"]},
    )
    after_restore = await _current(db_session, chapter.id)
    gone = await _ok(
        await db_client.post(
            f"/novels/{novel_id}/chapters/{chapter.id}/illustrations/{restored.json()['revision']['illustrations'][0]['id']}/detach",
            json={"baseRevisionId": str(after_restore.id)},
        )
    )
    from_snapshot = await db_client.post(f"/novels/{novel_id}/snapshots/{snapshot.json()['id']}/restore")
    after_snapshot = await _current(db_session, chapter.id)

    expected = [(first.block_ids[2], "after", 0, asset.id, "generated")]
    assert restored.status_code == 201, restored.text
    assert await _placements(db_session, after_restore.id) == expected
    assert gone["illustrations"] == []
    assert from_snapshot.status_code == 200, from_snapshot.text
    assert after_snapshot.revision_no == after_restore.revision_no + 2
    assert await _placements(db_session, after_snapshot.id) == expected


@pytest.mark.usefixtures("illustrations_on")
async def test_attaching_a_picture_keeps_an_ai_edit_preview_whose_result_then_carries_the_picture(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """끝난 AI 수정 미리보기가 있는 화에 그림을 붙여도 미리보기는 목록에 남고 적용되며, 적용 결과 개정이 그림을 잇는다(앵커가
    수정 범위 밖). 깨지는 시나리오: 그림을 붙였다고 돈을 낸 미리보기가 사라지거나, 적용이 그림을 떨어뜨린다."""
    room, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    first = await _current(db_session, chapter.id)
    job = await _finished_ai_edit(db_session, novel_id, chapter, first)
    asset = await _asset(db_session, room.user_id)
    await _ok(await _attach(db_client, novel_id, chapter.id, first, first.block_ids[2], asset.id))

    pending = (await db_client.get(f"/novels/{novel_id}")).json()["pendingAiEdits"]
    applied = await db_client.post(f"/novels/{novel_id}/jobs/{job.id}/apply")

    assert [edit["id"] for edit in pending] == [str(job.id)]
    assert applied.status_code == 201, applied.text
    body = applied.json()["revision"]
    assert body["paragraphs"][1] == "쓸쓸한 둘째 문단."
    assert [(i["anchorBlockId"], i["assetId"]) for i in body["illustrations"]] == [(str(first.block_ids[2]), str(asset.id))]


# ── 쓰이는 그림 보호 ────────────────────────────────────────────────────────
@pytest.mark.usefixtures("illustrations_on")
async def test_a_generated_image_used_by_any_revision_cannot_be_deleted_until_the_novel_is_gone(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """지금 개정이 아니라 옛 개정만 쓰는 그림도 지울 수 없다(409, 소설 사용처는 따로 `novelUsages` 칸). 갤러리 목록도 같은
    사용처를 싣는다. 소설을 지운 뒤에는 지울 수 있다. 깨지는 시나리오: 떼고 나서 지운 그림 때문에 되돌리기·산 판의 그림이 깨지거나,
    그림 행 DELETE 가 FK 거부로 500 이 된다."""
    room, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    first = await _current(db_session, chapter.id)
    asset = await _asset(db_session, room.user_id)
    attached = await _ok(await _attach(db_client, novel_id, chapter.id, first, first.block_ids[0], asset.id))
    await _ok(
        await db_client.post(
            f"/novels/{novel_id}/chapters/{chapter.id}/illustrations/{attached['illustrations'][0]['id']}/detach",
            json={"baseRevisionId": attached["id"]},
        )
    )
    monkeypatch.setattr("api.assets.router.delete_object", lambda _key: None)

    novel = await db_session.get_one(Novel, novel_id)
    title = novel.title or novel.content_title
    refused = await db_client.delete(f"/me/generated-images/{asset.id}")
    listed = (await db_client.get("/me/generated-images")).json()
    assert (await db_client.delete(f"/novels/{novel_id}")).status_code == 204
    deleted = await db_client.delete(f"/me/generated-images/{asset.id}")

    assert refused.status_code == 409
    assert refused.json()["detail"]["usages"] == []
    assert refused.json()["detail"]["novelUsages"] == [
        {"novelId": str(novel_id), "novelTitle": title, "field": "illustration"}
    ]
    assert [item["novelUsages"] for item in listed if item["assetId"] == str(asset.id)] == [
        refused.json()["detail"]["novelUsages"]
    ]
    assert deleted.status_code == 204, deleted.text


@pytest.mark.usefixtures("illustrations_on")
async def test_the_creator_of_a_picture_used_in_someone_elses_novel_is_not_told_which_novel(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """원작자의 생성 이미지를 남의 작가가 원작 그림으로 붙이면 원작자는 그 이미지를 지울 수 없지만(409), 어느 소설인지(id·제목)는
    받지 않는다. 깨지는 시나리오: 원작자가 갤러리·삭제 응답으로 남의 비공개 소설 제목과 id 를 알아낸다."""
    from api.db.models import CharacterVersionDetail

    room, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    content = await _hand_original_to_someone_else(db_session, novel_id)
    picture = await _asset(db_session, content.creator_user_id)
    await db_session.execute(
        sa.update(CharacterVersionDetail)
        .where(CharacterVersionDetail.content_version_id == content.current_published_version_id)
        .values(thumbnail_asset_id=picture.id)
    )
    await db_session.commit()
    first = await _current(db_session, chapter.id)
    await _ok(await _attach(db_client, novel_id, chapter.id, first, first.block_ids[0], picture.id, source="original"))
    await _login_as(db_client, content.creator_user_id)

    refused = await db_client.delete(f"/me/generated-images/{picture.id}")
    listed = (await db_client.get("/me/generated-images")).json()

    hidden = [{"novelId": None, "novelTitle": None, "field": "illustration"}]
    assert refused.status_code == 409
    assert refused.json()["detail"]["novelUsages"] == hidden
    assert [item["novelUsages"] for item in listed if item["assetId"] == str(picture.id)] == [hidden]
    assert room.user_id != content.creator_user_id


@pytest.mark.usefixtures("illustrations_on")
async def test_purging_a_withdrawn_authors_hidden_novel_deletes_the_generated_pictures_it_kept(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, deleted_keys: list[str]
) -> None:
    """탈퇴 때 숨겨 남긴 팔린 소설의 판이 쓰던 탈퇴자의 생성 이미지는, 그 소설이 파기되면 함께 지워진다(살아 있는 회원의 생성
    이미지는 남는다). 깨지는 시나리오: 지울 사람이 없는 탈퇴자의 그림이 저장소에 영영 남는다."""
    from api.db.models import User
    from api.novelize.hidden_purge import purge_hidden_novels

    room, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    first = await _current(db_session, chapter.id)
    picture = await _asset(db_session, room.user_id)
    await _ok(await _attach(db_client, novel_id, chapter.id, first, first.block_ids[0], picture.id))
    await db_session.execute(sa.update(Novel).where(Novel.id == novel_id).values(hidden_at=sa.func.now(), chat_room_id=None))
    await db_session.execute(sa.update(User).where(User.id == room.user_id).values(deleted_at=sa.func.now()))
    await db_session.commit()

    assert await purge_hidden_novels(db_session) == 1

    assert await db_session.get(Asset, picture.id, populate_existing=True) is None
    assert picture.storage_key in deleted_keys


async def _request(db: AsyncSession, owner_id: uuid.UUID, *pictures: Asset, status: str = "succeeded") -> uuid.UUID:
    """`pictures` 를 만든 이미지 생성 요청 행 하나(커밋)."""
    request = ImageGenerationRequest(
        owner_user_id=owner_id,
        prompt="요청 프롬프트",
        style="anime",
        aspect_ratio="3:4",
        model="test-model",
        requested_count=max(len(pictures), 1),
        status=status,
    )
    db.add(request)
    await db.flush()
    for picture in pictures:
        await db.execute(sa.update(Asset).where(Asset.id == picture.id).values(request_id=request.id))
    await db.commit()
    return request.id


@pytest.mark.usefixtures("illustrations_on")
async def test_purging_a_withdrawn_authors_hidden_novel_deletes_the_requests_left_without_a_picture(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, deleted_keys: list[str]
) -> None:
    """숨겨 남긴 소설이 파기되어 탈퇴자의 생성 이미지가 지워지면, 그림이 하나도 남지 않은 그 이미지의 생성 요청 행(프롬프트 원문)도
    함께 지운다. 같은 요청의 다른 그림이 남아 있으면 요청 행도 남고, 처음부터 그림이 없던 요청(차단·실패)은 보관 기간 정리의 몫이라
    건드리지 않는다. 깨지는 시나리오: 이미지와 함께 파기한다는 프롬프트 원문이 그림이 사라진 뒤에도 기한 없이 남거나, 남은 그림이
    가리키는 요청 행을 지워 외래 키 오류로 파기 전체가 실패한다."""
    from api.db.models import User
    from api.novelize.hidden_purge import purge_hidden_novels

    room, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    alone, paired, sibling = [await _asset(db_session, room.user_id) for _ in range(3)]
    alone_request = await _request(db_session, room.user_id, alone)
    paired_request = await _request(db_session, room.user_id, paired, sibling)
    blocked_request = await _request(db_session, room.user_id, status="blocked")
    first = await _current(db_session, chapter.id)
    await _ok(await _attach(db_client, novel_id, chapter.id, first, first.block_ids[0], alone.id))
    second = await _current(db_session, chapter.id)
    await _ok(await _attach(db_client, novel_id, chapter.id, second, second.block_ids[0], paired.id))
    await db_session.execute(sa.update(Novel).where(Novel.id == novel_id).values(hidden_at=sa.func.now(), chat_room_id=None))
    await db_session.execute(sa.update(User).where(User.id == room.user_id).values(deleted_at=sa.func.now()))
    await db_session.commit()

    assert await purge_hidden_novels(db_session) == 1

    left = set(
        (
            await db_session.scalars(
                sa.select(ImageGenerationRequest.id).where(ImageGenerationRequest.owner_user_id == room.user_id)
            )
        ).all()
    )
    assert left == {paired_request, blocked_request}
    assert await db_session.get(Asset, sibling.id, populate_existing=True) is not None
    assert {alone.storage_key, paired.storage_key} <= set(deleted_keys)


@pytest.mark.parametrize("switch_on", [pytest.param(True, id="on"), pytest.param(False, id="off")])
async def test_a_novel_cover_protects_its_image_only_while_illustrations_are_on(
    switch_on: bool, db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """표지로 쓴 내 이미지 삭제는 스위치가 켜졌을 때만 409 다. 꺼져 있으면 지금처럼 지워지고 표지가 빈다. 깨지는 시나리오:
    약관 게시 전(스위치 꺼짐)에 표지 이미지 삭제 동작이 바뀐다."""
    monkeypatch.setattr(settings, "novel_illustrations_enabled", switch_on)
    room, novel_id, _chapter_row = await _chapter(db_client, db_session, monkeypatch)
    asset = await _asset(db_session, room.user_id)
    assert (await db_client.patch(f"/novels/{novel_id}", json={"coverAssetId": str(asset.id)})).status_code == 200
    monkeypatch.setattr("api.assets.router.delete_object", lambda _key: None)

    resp = await db_client.delete(f"/me/generated-images/{asset.id}")

    if switch_on:
        assert resp.status_code == 409
        assert [u["field"] for u in resp.json()["detail"]["novelUsages"]] == ["cover"]
    else:
        assert resp.status_code == 204
        assert (await db_session.get_one(Novel, novel_id, populate_existing=True)).cover_asset_id is None


# ── 업로드 삽화 파일의 수명 ─────────────────────────────────────────────────
@pytest.mark.usefixtures("illustrations_on")
async def test_deleting_a_novel_deletes_upload_files_no_other_revision_uses(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, deleted_keys: list[str]
) -> None:
    """두 소설에 붙인 업로드는 한 소설을 지워도 남고, 둘 다 지우면 자산 행과 저장소 파일(원본·변형)이 함께 지워진다. 생성
    이미지는 소설 삭제로 지우지 않는다. 깨지는 시나리오: 지운 소설의 업로드 사진이 영영 남거나, 다른 소설이 쓰는 파일을 지운다."""
    room, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    first = await _current(db_session, chapter.id)
    upload = await _upload(db_session, room.user_id)
    generated = await _asset(db_session, room.user_id)
    await _ok(await _attach(db_client, novel_id, chapter.id, first, first.block_ids[0], upload.id, source="upload"))
    await _ok(
        await _attach(
            db_client, novel_id, chapter.id, await _current(db_session, chapter.id), first.block_ids[1], generated.id
        )
    )
    other_room, other_novel = await _novel_setup(db_client, db_session, monkeypatch)
    await db_session.execute(sa.update(Novel).where(Novel.id == other_novel).values(user_id=room.user_id))
    await db_session.commit()
    other_messages = await _room_messages(db_session, other_room.room_id)
    other_chapter = await _add_chapter(db_session, other_novel, other_room, other_messages[0], other_room.turns[1][1])
    await _login_as(db_client, room.user_id)
    other_first = await _current(db_session, other_chapter.id)
    await _ok(
        await _attach(db_client, other_novel, other_chapter.id, other_first, other_first.block_ids[0], upload.id, source="upload")
    )

    assert (await db_client.delete(f"/novels/{novel_id}")).status_code == 204
    kept = await db_session.get(Asset, upload.id, populate_existing=True)
    keys_after_first = list(deleted_keys)
    assert (await db_client.delete(f"/novels/{other_novel}")).status_code == 204

    assert kept is not None and keys_after_first == []
    assert await db_session.get(Asset, upload.id, populate_existing=True) is None
    assert upload.storage_key in deleted_keys and any(key.endswith("_display.webp") for key in deleted_keys)
    assert await db_session.get(Asset, generated.id, populate_existing=True) is not None


@pytest.mark.usefixtures("illustrations_on")
async def test_deleting_the_last_batch_deletes_its_unused_upload_files(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, deleted_keys: list[str]
) -> None:
    room, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    first = await _current(db_session, chapter.id)
    upload = await _upload(db_session, room.user_id)
    await _ok(await _attach(db_client, novel_id, chapter.id, first, first.block_ids[0], upload.id, source="upload"))

    resp = await db_client.delete(f"/novels/{novel_id}/batches/{chapter.batch_id}")

    assert resp.status_code == 204, resp.text
    assert await db_session.get(Asset, upload.id, populate_existing=True) is None
    assert upload.storage_key in deleted_keys


@pytest.mark.usefixtures("illustrations_on")
async def test_a_withdrawal_deletes_the_authors_illustration_uploads(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """탈퇴는 지운 소설이 쓰던 업로드와 아직 어디에도 붙이지 않은 업로드를 모두 지운다(저장소 파일까지). 깨지는 시나리오:
    탈퇴한 사람의 사진이 저장소에 남는다."""
    from api.auth import withdrawal

    removed: list[str] = []
    monkeypatch.setattr(withdrawal, "delete_object", removed.append)
    room, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    first = await _current(db_session, chapter.id)
    used = await _upload(db_session, room.user_id)
    loose = await _upload(db_session, room.user_id)
    await _ok(await _attach(db_client, novel_id, chapter.id, first, first.block_ids[0], used.id, source="upload"))

    assert (await db_client.delete("/me")).status_code == 204

    assert await db_session.get(Asset, used.id, populate_existing=True) is None
    assert await db_session.get(Asset, loose.id, populate_existing=True) is None
    assert {used.storage_key, loose.storage_key} <= set(removed)


@pytest.mark.usefixtures("illustrations_on")
async def test_the_hidden_novel_purge_deletes_upload_files_once_the_novel_is_gone(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, deleted_keys: list[str]
) -> None:
    from api.novelize.hidden_purge import purge_hidden_novels

    room, novel_id, chapter = await _chapter(db_client, db_session, monkeypatch)
    first = await _current(db_session, chapter.id)
    upload = await _upload(db_session, room.user_id)
    await _ok(await _attach(db_client, novel_id, chapter.id, first, first.block_ids[0], upload.id, source="upload"))
    await db_session.execute(sa.update(Novel).where(Novel.id == novel_id).values(hidden_at=sa.func.now(), chat_room_id=None))
    await db_session.commit()

    assert await purge_hidden_novels(db_session) == 1

    assert await db_session.get(Asset, upload.id, populate_existing=True) is None
    assert upload.storage_key in deleted_keys


# ── 구조 ────────────────────────────────────────────────────────────────────
def _callee(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _unrouted_revision_builds(source: str) -> list[int]:
    """`build_revision(...)` 호출 중 개정을 넣는 함수(`add_revision`·`_stack_revision`)의 인자로 바로 넘기지 않는 자리."""
    tree = ast.parse(source)
    routed: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _callee(node) in {"add_revision", "_stack_revision"}:
            for arg in [*node.args, *(kw.value for kw in node.keywords)]:
                routed.add(id(arg))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _callee(node) == "build_revision" and id(node) not in routed
    ]


def test_the_routing_guard_sees_a_build_that_is_not_handed_to_the_inserting_function() -> None:
    sample = """
add_revision(db, build_revision(body=b), previous=p)
await _stack_revision(db, n, c, build_revision(body=b))
db.add(build_revision(body=b))
rows = [build_revision(body=b) for b in bodies]
"""
    assert _unrouted_revision_builds(sample) == [4, 5]


def test_every_new_revision_goes_through_the_function_that_carries_its_pictures() -> None:
    """깨지는 시나리오: 새 개정 경로가 개정을 세션에 바로 넣어 그 개정만 그림을 잃는다(배치 승계를 건너뛴다)."""
    offenders = {
        str(path.relative_to(_SRC)): lines
        for path in sorted(_SRC.rglob("*.py"))
        if path != _SRC / "novelize" / "blocks.py"
        and (lines := _unrouted_revision_builds(path.read_text(encoding="utf-8")))
    }
    stack = ast.parse((_SRC / "novelize" / "router.py").read_text(encoding="utf-8"))
    (stack_def,) = [n for n in ast.walk(stack) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_stack_revision"]

    assert offenders == {}
    assert any(isinstance(n, ast.Call) and _callee(n) == "add_revision" for n in ast.walk(stack_def))


def test_placement_rows_are_never_updated() -> None:
    """배치 행은 쓰고 지울 뿐 고치지 않는다 — 공개본이 얼린 개정의 그림이 나중에 바뀌지 않는다는 전제다. 깨지는 시나리오: 배치를
    제자리에서 고치는 코드가 생겨 심사한 그림과 독자가 보는 그림이 달라진다."""
    found: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "update novel_chapter_illustrations" in " ".join(node.value.lower().split()):
                    found.append(f"{path.name}:{node.lineno}")
            if isinstance(node, ast.Call) and _callee(node) == "update":
                if any(isinstance(a, ast.Name) and a.id == "NovelChapterIllustration" for a in node.args):
                    found.append(f"{path.name}:{node.lineno}")

    assert found == []
