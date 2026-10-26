"""`scripts/purge_contents.py` — 운영자가 작품을 DB 와 저장소에서 완전히 지우는 스크립트.

작품 행은 다른 회원의 대화방·소설·좋아요·신고처럼 작가 밖의 행이 가리키고, 그림은 다른 작품이 함께 쓸 수 있다. 그래서
테스트는 늘 "지울 것"과 "남길 것"을 짝으로 두고, 지운 뒤 남길 쪽이 그대로인지까지 본다. 돈·공개·사용자 데이터가 얽힌 행이
있으면 아무것도 쓰지 않고 거부해야 하므로 거부 사유마다 그 작품이 그대로 남는지도 본다.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import api.db.session
import purge_contents as script
from api.core.s3 import build_variant_keys
from api.db.models import (
    AdminActionLog,
    CharacterImageExposure,
    CharacterVersionDetail,
    ChatMessage,
    ChatMessageReport,
    ChatMessageRole,
    ChatRoom,
    CloverLedger,
    CloverSpendUsage,
    Content,
    ContentChatParticipant,
    ContentType,
    ContentVersion,
    ContentVisibility,
    CreatorPayoutConfirmation,
    CreatorPayoutConfirmationLine,
    DiscardedResponse,
    Favorite,
    HomeCuration,
    HomeNovelCuration,
    Inquiry,
    InquiryCategory,
    InquiryStatus,
    Like,
    ModerationAction,
    ModerationActionType,
    ModerationStatus,
    Notification,
    Novel,
    NovelChapterIllustration,
    NovelPublication,
    NovelPurchase,
    Report,
    ReportReasonCategory,
    ReportStatus,
    SituationalImage,
    StartingSetup,
    StatDef,
    StoryEndingUnlock,
    StoryMediaExposure,
    StoryPromptTemplate,
    StoryVersionDetail,
)
from api.db.models.auth import User
from api.db.models.media import Asset, AssetKind, AssetStatus, ImageGenerationRequest
from comment_factories import _make_comment
from factories import (
    _add_media_book_cell,
    _create_admin,
    _make_draft_content,
    _make_novel_tree,
    _make_payment,
    _make_user,
)


@dataclass
class Story:
    content: Content
    # 발행본이 있으면 발행본이 앞, 초안이 마지막이다.
    version_ids: list[uuid.UUID]
    setup_ids: list[uuid.UUID]
    setup_entity_id: uuid.UUID
    thumbnail_id: uuid.UUID | None


async def _user(db: AsyncSession) -> User:
    user = _make_user()
    db.add(user)
    await db.flush()
    return user


async def _image(
    db: AsyncSession, owner_id: uuid.UUID, *, kind: AssetKind = AssetKind.ORIGINAL, request_id: uuid.UUID | None = None
) -> Asset:
    asset = Asset(
        owner_user_id=owner_id,
        storage_key=f"assets/test/{uuid.uuid4()}.png",
        kind=kind,
        status=AssetStatus.READY,
        request_id=request_id,
    )
    db.add(asset)
    await db.flush()
    return asset


async def _add_version(
    db: AsyncSession, content: Content, *, published: bool, setup_entity_id: uuid.UUID, thumbnail_id: uuid.UUID | None
) -> tuple[uuid.UUID, uuid.UUID]:
    """버전 하나에 상세·시작설정·스탯을 붙인다. 초안은 발행본과 같은 시작설정 entity_id 를 쓴다(발행 복제가 지키는 관계)."""
    version = ContentVersion(
        content_id=content.id,
        version_number=1 if published else None,
        published_at=datetime.now(UTC) if published else None,
        detail_description="합성 소개",
    )
    db.add(version)
    await db.flush()
    db.add(
        StoryVersionDetail(
            content_version_id=version.id,
            name="합성 스토리",
            one_liner="한 줄 소개",
            thumbnail_asset_id=thumbnail_id,
            prompt_template=StoryPromptTemplate.BASIC,
            setting_text="합성 세계관",
        )
    )
    setup = StartingSetup(
        entity_id=setup_entity_id, content_version_id=version.id, name="첫 장면", prologue="합성 프롤로그", order=0
    )
    db.add(setup)
    await db.flush()
    db.add(
        StatDef(
            entity_id=uuid.uuid4(),
            starting_setup_id=setup.id,
            name="호감도",
            icon="heart",
            color="#ff0000",
            min_value=0,
            max_value=100,
            initial_value=10,
            description="합성 스탯",
            order=0,
        )
    )
    await db.flush()
    return version.id, setup.id


async def _story(
    db: AsyncSession,
    creator_id: uuid.UUID,
    *,
    published: bool = True,
    thumbnail_id: uuid.UUID | None = None,
    setup_entity_id: uuid.UUID | None = None,
) -> Story:
    """발행작이면 발행본 v1 과 초안 하나, 아니면 초안 하나만 있는 스토리."""
    content = Content(
        creator_user_id=creator_id,
        type=ContentType.STORY,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db.add(content)
    await db.flush()
    entity_id = setup_entity_id or uuid.uuid4()
    version_ids: list[uuid.UUID] = []
    setup_ids: list[uuid.UUID] = []
    if published:
        version_id, setup_id = await _add_version(
            db, content, published=True, setup_entity_id=entity_id, thumbnail_id=thumbnail_id
        )
        version_ids.append(version_id)
        setup_ids.append(setup_id)
        content.current_published_version_id = version_id
    version_id, setup_id = await _add_version(
        db, content, published=False, setup_entity_id=entity_id, thumbnail_id=thumbnail_id
    )
    version_ids.append(version_id)
    setup_ids.append(setup_id)
    await db.flush()
    return Story(content, version_ids, setup_ids, entity_id, thumbnail_id)


async def _room(db: AsyncSession, story: Story, user_id: uuid.UUID, *, messages: int = 1) -> ChatRoom:
    room = ChatRoom(
        user_id=user_id,
        content_id=story.content.id,
        content_version_id=story.version_ids[0],
        starting_setup_entity_id=story.setup_entity_id,
    )
    db.add(room)
    await db.flush()
    db.add_all(
        ChatMessage(chat_room_id=room.id, role=ChatMessageRole.USER, content=f"합성 메시지 {index}")
        for index in range(messages)
    )
    await db.flush()
    return room


async def _populate_reader_rows(db: AsyncSession, story: Story, reader_id: uuid.UUID) -> None:
    """다른 회원이 이 작품에 남기는 행을 하나씩 — 좋아요·즐겨찾기·대화 참여·이미지 노출 둘·신고·엔딩 수집."""
    db.add_all(
        [
            Like(user_id=reader_id, content_id=story.content.id),
            Favorite(user_id=reader_id, content_id=story.content.id),
            ContentChatParticipant(content_id=story.content.id, user_id=reader_id),
            CharacterImageExposure(user_id=reader_id, content_id=story.content.id, image_entity_id=uuid.uuid4()),
            StoryMediaExposure(user_id=reader_id, content_id=story.content.id, cell_entity_id=uuid.uuid4()),
            Report(
                reporter_user_id=reader_id,
                content_id=story.content.id,
                reason_category=ReportReasonCategory.SPAM,
                status=ReportStatus.PENDING,
            ),
            StoryEndingUnlock(
                user_id=reader_id, starting_setup_entity_id=story.setup_entity_id, ending_entity_id=uuid.uuid4()
            ),
        ]
    )
    await db.flush()


async def _count(db: AsyncSession, model: Any, *conditions: Any) -> int:
    return int(await db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0)


async def _target_row_counts(db: AsyncSession, story: Story) -> dict[str, int]:
    """지울 작품에 매달린 행 수. 지운 뒤에는 전부 0 이어야 한다."""
    content_id = story.content.id
    return {
        "contents": await _count(db, Content, Content.id == content_id),
        "content_versions": await _count(db, ContentVersion, ContentVersion.content_id == content_id),
        "story_version_details": await _count(
            db, StoryVersionDetail, StoryVersionDetail.content_version_id.in_(story.version_ids)
        ),
        "starting_setups": await _count(db, StartingSetup, StartingSetup.content_version_id.in_(story.version_ids)),
        "stat_defs": await _count(db, StatDef, StatDef.starting_setup_id.in_(story.setup_ids)),
        "chat_rooms": await _count(db, ChatRoom, ChatRoom.content_id == content_id),
        "likes": await _count(db, Like, Like.content_id == content_id),
        "favorites": await _count(db, Favorite, Favorite.content_id == content_id),
        "content_chat_participants": await _count(
            db, ContentChatParticipant, ContentChatParticipant.content_id == content_id
        ),
        "character_image_exposures": await _count(
            db, CharacterImageExposure, CharacterImageExposure.content_id == content_id
        ),
        "story_media_exposures": await _count(db, StoryMediaExposure, StoryMediaExposure.content_id == content_id),
        "reports": await _count(db, Report, Report.content_id == content_id),
        "story_ending_unlocks": await _count(
            db, StoryEndingUnlock, StoryEndingUnlock.starting_setup_entity_id == story.setup_entity_id
        ),
    }


async def _apply(db: AsyncSession, stories: list[Story], keys_out: Path) -> script.PurgePlan:
    return await script.apply_purge(
        db, [story.content.id for story in stories], expect_contents=len(stories), keys_out=keys_out
    )


async def _assert_refused(db: AsyncSession, story: Story, tmp_path: Path) -> None:
    """계획에 거부 사유가 있고, 적용은 쓰기 없이 거부되며 키 파일도 만들지 않는다."""
    planned = await script.build_plan(db, [story.content.id])
    assert planned.refusals
    keys_out = tmp_path / "keys.json"
    with pytest.raises(script.PurgeRefused) as refused:
        await _apply(db, [story], keys_out)
    assert refused.value.plan.refusals
    assert await _count(db, Content, Content.id == story.content.id) == 1
    assert await _count(db, ContentVersion, ContentVersion.content_id == story.content.id) == len(story.version_ids)
    assert not keys_out.exists()


async def _spend_ledger(db: AsyncSession, user_id: uuid.UUID) -> CloverLedger:
    ledger = CloverLedger(user_id=user_id, amount=-10, balance_after=0, kind="chat_spend")
    db.add(ledger)
    await db.flush()
    return ledger


async def _payout_line(db: AsyncSession, creator_id: uuid.UUID, payer_id: uuid.UUID, content_id: uuid.UUID) -> None:
    """정산 확정 하나와 그 확정의 작품 내역 한 줄."""
    window_end = datetime.now(UTC)
    confirmation = CreatorPayoutConfirmation(
        user_id=creator_id,
        kind="retro",
        window_start=window_end - timedelta(days=1),
        window_end=window_end,
        gross_units=10,
        refunded_units=0,
        rate_bps=500,
        exact_krw=Decimal(1),
        amount_krw=1,
    )
    db.add(confirmation)
    payment = await _make_payment(db, user_id=payer_id)
    await db.flush()
    db.add(
        CreatorPayoutConfirmationLine(
            confirmation_id=confirmation.id,
            content_id=content_id,
            payment_id=payment.id,
            net_units=10,
            cancel_adjust_krw=Decimal(0),
            exact_krw=Decimal(1),
        )
    )


async def _character(
    db: AsyncSession, creator_id: uuid.UUID, image: Asset, blurred: Asset
) -> tuple[Content, list[uuid.UUID]]:
    """발행본 v1 과 초안이 있는 캐릭터. 두 버전 모두 같은 상황 이미지(원본 + 블러)를 쓴다(발행 복제가 지키는 관계)."""
    content = Content(
        creator_user_id=creator_id,
        type=ContentType.CHARACTER,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db.add(content)
    await db.flush()
    entity_id = uuid.uuid4()
    version_ids: list[uuid.UUID] = []
    for published in (True, False):
        version = ContentVersion(
            content_id=content.id,
            version_number=1 if published else None,
            published_at=datetime.now(UTC) if published else None,
            detail_description="합성 소개",
        )
        db.add(version)
        await db.flush()
        db.add_all(
            [
                CharacterVersionDetail(
                    content_version_id=version.id,
                    name="합성 캐릭터",
                    one_liner="한 줄 소개",
                    intro="합성 인트로",
                    example_dialogues=[],
                    character_prompt="합성 프롬프트",
                ),
                SituationalImage(
                    entity_id=entity_id,
                    content_version_id=version.id,
                    image_asset_id=image.id,
                    blurred_asset_id=blurred.id,
                    trigger_condition="합성 조건",
                    order=0,
                ),
            ]
        )
        await db.flush()
        version_ids.append(version.id)
    content.current_published_version_id = version_ids[0]
    await db.flush()
    return content, version_ids


async def _character_row_counts(db: AsyncSession, content: Content, version_ids: list[uuid.UUID]) -> dict[str, int]:
    return {
        "contents": await _count(db, Content, Content.id == content.id),
        "content_versions": await _count(db, ContentVersion, ContentVersion.content_id == content.id),
        "character_version_details": await _count(
            db, CharacterVersionDetail, CharacterVersionDetail.content_version_id.in_(version_ids)
        ),
        "situational_images": await _count(db, SituationalImage, SituationalImage.content_version_id.in_(version_ids)),
    }


def _use_test_session_for_main(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    """명령 실행이 여는 세션을 이 테스트의 커넥션에 묶는다 — 테스트가 넣고 커밋하지 않은 행을 그 세션도 보게 한다."""
    monkeypatch.setattr(
        api.db.session, "async_session_factory", async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    )


def _generation_request(owner_id: uuid.UUID) -> ImageGenerationRequest:
    return ImageGenerationRequest(
        owner_user_id=owner_id,
        prompt="합성 프롬프트",
        style="anime",
        aspect_ratio="1:1",
        model="test-model",
        requested_count=2,
        status="succeeded",
    )


async def test_apply_removes_the_target_story_and_leaves_a_sibling_story_untouched(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """같은 작가의 두 작품 중 하나만 지운다. 깨지는 시나리오: 작가 id 나 회원 id 로 지울 행을 골라 남길 작품의 버전·방·그림·
    좋아요까지 지우거나, 지울 작품의 회원 행(좋아요·신고·엔딩 수집 등)을 남겨 FK 위반이 나거나 고아 행이 쌓인다."""
    creator = await _user(db_session)
    reader = await _user(db_session)
    keep_thumbnail = await _image(db_session, creator.id)
    keep = await _story(db_session, creator.id, thumbnail_id=keep_thumbnail.id)
    keep.content.like_count = 3
    keep.content.chat_count = 2
    keep.content.view_count = 7
    keep_room = await _room(db_session, keep, reader.id)
    # 같은 독자가 두 작품에 같은 종류의 행을 남긴다 — 회원 id 로 지울 행을 고르면 남길 쪽 수가 줄어든다.
    await _populate_reader_rows(db_session, keep, reader.id)
    target = await _story(db_session, creator.id, thumbnail_id=(await _image(db_session, creator.id)).id)
    await _room(db_session, target, reader.id, messages=2)
    await _populate_reader_rows(db_session, target, reader.id)
    keep_before = await _target_row_counts(db_session, keep)
    assert all(keep_before.values()), keep_before

    await _apply(db_session, [target], tmp_path / "keys.json")

    assert await _target_row_counts(db_session, target) == dict.fromkeys(keep_before, 0)
    assert await _target_row_counts(db_session, keep) == keep_before
    assert (
        await db_session.execute(
            select(Content.like_count, Content.chat_count, Content.view_count).where(Content.id == keep.content.id)
        )
    ).one() == (3, 2, 7)
    assert await _count(db_session, ChatRoom, ChatRoom.id == keep_room.id) == 1
    assert await _count(db_session, ChatMessage, ChatMessage.chat_room_id == keep_room.id) == 1
    assert await _count(db_session, Asset, Asset.id == keep_thumbnail.id) == 1


async def test_shared_asset_is_kept_and_unshared_assets_are_deleted_with_every_variant_key(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """남길 작품도 쓰는 그림은 행도 키도 남기고, 지울 작품만 쓰던 그림(원본·블러)은 행을 지우고 원본과 변형 다섯 키를 모두
    지울 목록에 싣는다. 깨지는 시나리오: 공유 그림을 지워 남길 작품의 대표 이미지가 깨지거나, 변형 키를 빠뜨려 저장소에
    사본이 남는다."""
    creator = await _user(db_session)
    shared = await _image(db_session, creator.id)
    own = await _image(db_session, creator.id)
    blurred = await _image(db_session, creator.id, kind=AssetKind.BLURRED)
    await _story(db_session, creator.id, thumbnail_id=shared.id)
    target = await _story(db_session, creator.id, thumbnail_id=shared.id)
    await _add_media_book_cell(db_session, target.version_ids[-1], own.id, blurred.id)
    shared_keys = {shared.storage_key, *build_variant_keys(shared.storage_key)}

    # 계획을 따로 본다 — 계획이 공유 그림을 지울 목록에 넣으면 적용은 FK 위반으로 먼저 멈춰 아래 단언까지 오지 않는다.
    preview = await script.build_plan(db_session, [target.content.id])
    assert shared.id not in preview.asset_ids
    assert shared_keys.isdisjoint(preview.storage_keys)

    planned = await _apply(db_session, [target], tmp_path / "keys.json")

    assert await _count(db_session, Asset, Asset.id == shared.id) == 1
    assert await _count(db_session, Asset, Asset.id.in_([own.id, blurred.id])) == 0
    assert sorted(planned.asset_ids) == sorted([own.id, blurred.id])
    expected = {key for asset in (own, blurred) for key in (asset.storage_key, *build_variant_keys(asset.storage_key))}
    assert len(expected) == 12
    assert set(planned.storage_keys) == expected
    assert planned.storage_keys == sorted(set(planned.storage_keys))
    assert shared.storage_key not in planned.storage_keys


async def test_character_with_situational_images_is_deleted_and_a_sibling_character_is_kept(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """발행본과 초안이 같은 상황 이미지(원본 + 블러)를 쓰는 캐릭터를 지우면 상황 이미지·캐릭터 상세·버전·작품·그림 행이 모두
    지워지고 두 그림의 원본과 변형 키가 지울 목록에 실린다. 같은 작가의 남길 캐릭터는 그대로다. 깨지는 시나리오: 스토리 쪽
    자식만 지워 상황 이미지가 남은 버전 DELETE 가 FK 위반이 나거나, 두 버전이 같은 그림을 쓰는 것을 공유로 오판해 그림을
    남기거나, 작가 id 로 골라 남길 캐릭터까지 지운다."""
    creator = await _user(db_session)
    image = await _image(db_session, creator.id)
    blurred = await _image(db_session, creator.id, kind=AssetKind.BLURRED)
    target, target_versions = await _character(db_session, creator.id, image, blurred)
    keep_image = await _image(db_session, creator.id)
    keep_blurred = await _image(db_session, creator.id, kind=AssetKind.BLURRED)
    keep, keep_versions = await _character(db_session, creator.id, keep_image, keep_blurred)
    keep_before = await _character_row_counts(db_session, keep, keep_versions)

    planned = await script.apply_purge(db_session, [target.id], expect_contents=1, keys_out=tmp_path / "keys.json")

    assert await _character_row_counts(db_session, target, target_versions) == dict.fromkeys(keep_before, 0)
    assert await _count(db_session, Asset, Asset.id.in_([image.id, blurred.id])) == 0
    expected = {
        key for asset in (image, blurred) for key in (asset.storage_key, *build_variant_keys(asset.storage_key))
    }
    assert len(expected) == 12
    assert set(planned.storage_keys) == expected
    assert await _character_row_counts(db_session, keep, keep_versions) == keep_before
    assert await _count(db_session, Asset, Asset.id.in_([keep_image.id, keep_blurred.id])) == 2


async def test_other_members_room_and_novels_from_the_story_are_deleted(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """다른 회원의 방과 그 메시지, 그 방에서 만든 소설과 이 작품을 원작으로 한 소설(공개 안 함)은 함께 지운다. 깨지는 시나리오:
    작가 본인의 방만 지워 남의 방이 사라진 버전을 가리키며 FK 위반이 나거나, 원작이 없어진 소설이 남는다."""
    creator = await _user(db_session)
    reader = await _user(db_session)
    target = await _story(db_session, creator.id)
    room = await _room(db_session, target, reader.id, messages=2)
    room_novel = await _make_novel_tree(db_session, reader.id, chat_room_id=room.id)
    content_novel = await _make_novel_tree(db_session, reader.id)
    content_novel.novel.content_id = target.content.id
    await db_session.flush()

    await _apply(db_session, [target], tmp_path / "keys.json")

    assert await _count(db_session, ChatRoom, ChatRoom.id == room.id) == 0
    assert await _count(db_session, ChatMessage, ChatMessage.chat_room_id == room.id) == 0
    assert await _count(db_session, Novel, Novel.id.in_([room_novel.novel.id, content_novel.novel.id])) == 0


async def test_novel_with_a_publication_refuses_the_purge(db_session: AsyncSession, tmp_path: Path) -> None:
    """그 방에서 나온 소설이 노벨에 공개돼 있으면 독자·구매가 얽혀 있을 수 있어 아무것도 지우지 않는다(바로 위 테스트의
    짝 — 공개 상태만 다르다)."""
    creator = await _user(db_session)
    reader = await _user(db_session)
    target = await _story(db_session, creator.id)
    room = await _room(db_session, target, reader.id)
    novel = await _make_novel_tree(db_session, reader.id, chat_room_id=room.id)
    db_session.add(NovelPublication(novel_id=novel.novel.id, visibility="public"))
    await db_session.flush()

    await _assert_refused(db_session, target, tmp_path)

    assert await _count(db_session, Novel, Novel.id == novel.novel.id) == 1


@pytest.mark.parametrize(
    "axis",
    [pytest.param("content", id="content"), pytest.param("room", id="room"), pytest.param("novel", id="novel")],
)
async def test_spend_usage_on_any_axis_refuses_the_purge(
    db_session: AsyncSession, tmp_path: Path, axis: str
) -> None:
    """클로버 사용처는 정산 근거라 작품·방·소설 중 어느 칸으로든 대상을 가리키면 거부한다. 세 칸을 따로 본다 — 작품 칸만
    보면 미리보기(작품 없음)나 다른 작품으로 기록된 소설 차감이 빠진다."""
    creator = await _user(db_session)
    reader = await _user(db_session)
    other = await _make_draft_content(db_session, creator_user_id=creator.id)
    target = await _story(db_session, creator.id)
    room = await _room(db_session, target, reader.id)
    ledger = await _spend_ledger(db_session, reader.id)
    usage: dict[str, object] = {"spend_ledger_id": ledger.id, "spender_user_id": reader.id, "is_self_play": False}
    if axis == "content":
        # 방 칸은 이미 지워진 다른 방이다 — 작품 칸만 대상을 가리킨다.
        usage |= {
            "usage_kind": "chat",
            "content_id": target.content.id,
            "content_owner_user_id": creator.id,
            "chat_room_id": uuid.uuid4(),
        }
    elif axis == "room":
        # 작품 칸이 비는 사용처는 미리보기뿐이다(CHECK) — 방 칸만 대상을 가리킨다.
        usage |= {"usage_kind": "preview", "content_id": None, "content_owner_user_id": None, "chat_room_id": room.id}
    else:
        novel = await _make_novel_tree(db_session, reader.id, chat_room_id=room.id)
        # 소설 차감은 작품 칸이 차야 한다(CHECK) — 남길 작품으로 두어 소설 칸만 대상을 가리키게 한다.
        usage |= {
            "usage_kind": "novel",
            "content_id": other.id,
            "content_owner_user_id": creator.id,
            "novel_id": novel.novel.id,
        }
    db_session.add(CloverSpendUsage(**usage))
    await db_session.flush()

    await _assert_refused(db_session, target, tmp_path)


@pytest.mark.parametrize(
    "blocker",
    [
        pytest.param("home_curation", id="home-curation"),
        pytest.param("comment", id="comment"),
        pytest.param("illustration", id="illustration"),
        pytest.param("shared_setup", id="shared-setup"),
        pytest.param("payout_line", id="payout-line"),
        pytest.param("profile_image", id="profile-image"),
        pytest.param("inquiry_attachment", id="inquiry-attachment"),
        pytest.param("novel_purchase", id="novel-purchase"),
        pytest.param("home_novel_curation", id="home-novel-curation"),
    ],
)
async def test_blocking_reference_refuses_the_purge(
    db_session: AsyncSession, tmp_path: Path, blocker: str
) -> None:
    """홈 지정·댓글·다른 소설의 삽화가 쓰는 그림·다른 작품과 겹치는 시작설정 entity id·정산 확정 내역·회원 프로필이나 문의
    첨부로 쓰이는 그림은 지우면 남의 화면이나 기록이 깨지므로 거부한다. 정산 내역은 지급·세무의 장부라 작품이 사라지면 근거를
    잃는다. 그 작품에서 나온 소설의 회차 구매는 공개 기록 없이 남아 있어도 금전 기록이라, 홈 노벨 지정은 홈 화면이 그 소설을
    가리키므로 거부한다. 대조군(이것들이 없을 때 지워진다)은 맨 위 테스트다."""
    creator = await _user(db_session)
    reader = await _user(db_session)
    target = await _story(db_session, creator.id, thumbnail_id=(await _image(db_session, creator.id)).id)
    if blocker == "home_curation":
        db_session.add(HomeCuration(content_type=ContentType.STORY, content_id=target.content.id))
    elif blocker == "comment":
        await _make_comment(db_session, target.content, reader.id)
    elif blocker == "illustration":
        unrelated = await _make_novel_tree(db_session, reader.id)
        assert target.thumbnail_id is not None
        db_session.add(
            NovelChapterIllustration(
                revision_id=unrelated.first_revision.id, sort_order=0, asset_id=target.thumbnail_id, source="upload"
            )
        )
    elif blocker == "shared_setup":
        await _story(db_session, creator.id, setup_entity_id=target.setup_entity_id)
    elif blocker == "payout_line":
        await _payout_line(db_session, creator.id, reader.id, target.content.id)
    elif blocker == "profile_image":
        reader.profile_image_asset_id = target.thumbnail_id
    elif blocker == "novel_purchase":
        # 공개 기록 없이 구매만 남긴다 — 공개 기록이 있으면 그쪽 검사가 먼저 거부해 구매 검사를 시험하지 못한다.
        room = await _room(db_session, target, reader.id)
        novel = await _make_novel_tree(db_session, reader.id, chat_room_id=room.id)
        db_session.add(
            NovelPurchase(
                buyer_user_id=reader.id,
                publisher_user_id=reader.id,
                novel_id=novel.novel.id,
                chapter_id=novel.chapter.id,
                chapter_ordinal=1,
                edition=1,
                spend_ledger_id=(await _spend_ledger(db_session, reader.id)).id,
                price=10,
            )
        )
    elif blocker == "home_novel_curation":
        room = await _room(db_session, target, reader.id)
        novel = await _make_novel_tree(db_session, reader.id, chat_room_id=room.id)
        db_session.add(HomeNovelCuration(position=1, novel_id=novel.novel.id))
    else:
        db_session.add(
            Inquiry(
                user_id=reader.id,
                category=InquiryCategory.BUG,
                title="합성 문의",
                body="합성 문의 본문",
                attachment_asset_id=target.thumbnail_id,
                status=InquiryStatus.PENDING,
            )
        )
    await db_session.flush()

    await _assert_refused(db_session, target, tmp_path)


async def test_draft_only_story_and_published_story_are_both_deleted(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """발행된 적 없는 초안과 발행본 + 초안이 있는 작품이 한 목록에 섞여도 둘 다 지운다. 깨지는 시나리오: 발행본 포인터가
    NULL 인 작품에서 버전을 못 찾거나, 발행본 포인터를 비우지 않고 버전을 지워 FK 위반이 난다."""
    creator = await _user(db_session)
    draft = await _story(db_session, creator.id, published=False)
    published = await _story(db_session, creator.id)
    assert draft.content.current_published_version_id is None and len(draft.version_ids) == 1
    assert published.content.current_published_version_id is not None and len(published.version_ids) == 2

    await _apply(db_session, [draft, published], tmp_path / "keys.json")

    ids = [draft.content.id, published.content.id]
    assert await _count(db_session, Content, Content.id.in_(ids)) == 0
    assert await _count(db_session, ContentVersion, ContentVersion.content_id.in_(ids)) == 0


async def test_generation_request_is_deleted_only_when_no_image_of_it_remains(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """생성 그림을 지우면 그림이 하나도 안 남은 요청 행(프롬프트 원문)도 지우고, 같은 요청의 다른 그림이 갤러리에 남아 있으면
    요청 행을 남긴다. 깨지는 시나리오: 요청 행을 남겨 지운 그림의 프롬프트가 남거나, 남은 그림이 가리키는 요청 행을 지워
    FK 위반이 난다."""
    creator = await _user(db_session)
    lone_request = _generation_request(creator.id)
    shared_request = _generation_request(creator.id)
    db_session.add_all([lone_request, shared_request])
    await db_session.flush()
    lone = await _image(db_session, creator.id, kind=AssetKind.GENERATED, request_id=lone_request.id)
    used = await _image(db_session, creator.id, kind=AssetKind.GENERATED, request_id=shared_request.id)
    gallery = await _image(db_session, creator.id, kind=AssetKind.GENERATED, request_id=shared_request.id)
    target = await _story(db_session, creator.id, thumbnail_id=lone.id)
    await _add_media_book_cell(db_session, target.version_ids[-1], used.id)

    await _apply(db_session, [target], tmp_path / "keys.json")

    assert await _count(db_session, Asset, Asset.id.in_([lone.id, used.id])) == 0
    assert await _count(db_session, Asset, Asset.id == gallery.id) == 1
    assert await _count(db_session, ImageGenerationRequest, ImageGenerationRequest.id == lone_request.id) == 0
    assert await _count(db_session, ImageGenerationRequest, ImageGenerationRequest.id == shared_request.id) == 1


async def test_plan_counts_rows_without_writing_anything(db_session: AsyncSession, tmp_path: Path) -> None:
    """계획은 지울 행 수를 세기만 한다. 깨지는 시나리오: 계획 단계에서 정리 쓰기가 일부 나가 운영자가 확인하기도 전에 행이
    바뀌거나, 계획의 수가 실제 대상과 달라 운영자가 틀린 숫자를 보고 적용한다."""
    creator = await _user(db_session)
    reader = await _user(db_session)
    admin = await _create_admin(db_session)
    target = await _story(db_session, creator.id, thumbnail_id=(await _image(db_session, creator.id)).id)
    await _room(db_session, target, reader.id, messages=2)
    await _populate_reader_rows(db_session, target, reader.id)
    db_session.add(
        ModerationAction(content_id=target.content.id, admin_id=admin["id"], action=ModerationActionType.RESTRICT)
    )
    await db_session.flush()
    before = await _target_row_counts(db_session, target)
    assets_before = await _count(db_session, Asset)
    messages_before = await _count(db_session, ChatMessage)
    actions_before = await _count(db_session, ModerationAction, ModerationAction.content_id == target.content.id)

    planned = await script.build_plan(db_session, [target.content.id])

    assert await _target_row_counts(db_session, target) == before
    assert await _count(db_session, Asset) == assets_before
    assert await _count(db_session, ChatMessage) == messages_before
    assert await _count(db_session, ModerationAction, ModerationAction.content_id == target.content.id) == actions_before
    assert planned.refusals == []
    assert planned.missing_ids == []
    assert planned.content_ids == [target.content.id]
    assert planned.counts.get("contents") == 1
    assert planned.counts.get("content_versions") == 2
    assert planned.counts.get("chat_rooms") == 1
    assert planned.counts.get("likes") == 1
    assert planned.counts.get("moderation_actions.content_id:set_null") == 1
    assert target.thumbnail_id is not None and planned.asset_ids == [target.thumbnail_id]


async def test_apply_refuses_when_the_expected_content_count_differs(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """적용은 운영자가 적은 대상 수가 입력과 다르면 거부한다 — ids 파일을 잘못 넘겨 엉뚱한 목록을 지우는 것을 막는 확인이다."""
    creator = await _user(db_session)
    target = await _story(db_session, creator.id)
    keys_out = tmp_path / "keys.json"

    with pytest.raises(script.PurgeRefused):
        await script.apply_purge(db_session, [target.content.id], expect_contents=2, keys_out=keys_out)

    assert await _count(db_session, Content, Content.id == target.content.id) == 1
    assert not keys_out.exists()


async def test_main_apply_without_expect_contents_exits_nonzero(db_session: AsyncSession, tmp_path: Path) -> None:
    """적용 명령에 대상 수 확인이 빠지면 쓰기 전에 실패한다. 깨지는 시나리오: 그 인자를 선택으로 두어 확인 없이 지운다."""
    creator = await _user(db_session)
    target = await _story(db_session, creator.id)
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text(f"# 합성 대상\n\n{target.content.id}\n", encoding="utf-8")
    keys_out = tmp_path / "keys.json"

    try:
        code: object = script.main(["apply", "--ids-file", str(ids_file), "--keys-out", str(keys_out)])
    except SystemExit as exit_:
        code = exit_.code

    assert code not in (0, None)
    assert await _count(db_session, Content, Content.id == target.content.id) == 1
    assert not keys_out.exists()


async def test_missing_id_is_reported_and_refuses_the_purge(db_session: AsyncSession, tmp_path: Path) -> None:
    """DB 에 없는 id 가 섞이면 계획이 그 id 를 보여 주고 적용은 거부한다 — 다른 환경의 목록이나 오타일 수 있다."""
    creator = await _user(db_session)
    target = await _story(db_session, creator.id)
    missing = uuid.uuid4()
    keys_out = tmp_path / "keys.json"

    planned = await script.build_plan(db_session, [target.content.id, missing])

    assert planned.missing_ids == [missing]
    with pytest.raises(script.PurgeRefused) as refused:
        await script.apply_purge(db_session, [target.content.id, missing], expect_contents=2, keys_out=keys_out)
    assert refused.value.plan.missing_ids == [missing]
    assert await _count(db_session, Content, Content.id == target.content.id) == 1
    assert not keys_out.exists()


async def test_apply_writes_the_storage_keys_it_returns(db_session: AsyncSession, tmp_path: Path) -> None:
    """적용이 남기는 키 파일은 돌려준 계획의 키 목록과 같다. 저장소는 이 파일로만 지우므로, 둘이 다르면 지운 행의 그림이
    저장소에 남거나 남길 그림이 지워진다."""
    creator = await _user(db_session)
    target = await _story(db_session, creator.id, thumbnail_id=(await _image(db_session, creator.id)).id)
    keys_out = tmp_path / "keys.json"

    planned = await _apply(db_session, [target], keys_out)

    assert keys_out.exists()
    assert planned.storage_keys
    assert json.loads(keys_out.read_text(encoding="utf-8")) == planned.storage_keys


async def test_commit_failure_keeps_the_keys_file_as_unconfirmed(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """커밋이 예외로 끝나면 키 파일을 지우지 않고 `.unconfirmed` 를 붙여 남긴다. 서버는 커밋했는데 응답만 잃은 경우 그 파일이
    지운 그림 키의 유일한 기록이라서다 — 커밋이 정말 실패했다면 저장소 정리 명령이 아직 살아 있는 그림 키를 보고 거부한다.
    깨지는 시나리오: 파일을 지워 커밋된 삭제의 그림이 저장소에 영영 남거나, 원래 이름 그대로 남겨 확인된 키 목록처럼 보인다."""
    creator = await _user(db_session)
    target = await _story(db_session, creator.id, thumbnail_id=(await _image(db_session, creator.id)).id)
    expected_keys = (await script.build_plan(db_session, [target.content.id])).storage_keys
    keys_out = tmp_path / "keys.json"

    async def failing_commit() -> None:
        raise ConnectionResetError("합성 커밋 응답 유실")

    monkeypatch.setattr(db_session, "commit", failing_commit)

    with pytest.raises(ConnectionResetError):
        await _apply(db_session, [target], keys_out)

    unconfirmed = tmp_path / "keys.json.unconfirmed"
    assert not keys_out.exists()
    assert unconfirmed.exists()
    assert expected_keys
    assert json.loads(unconfirmed.read_text(encoding="utf-8")) == expected_keys


async def test_delete_objects_refuses_when_a_key_still_belongs_to_an_asset(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """키 파일에 아직 그림 행이 가리키는 키가 하나라도 있으면 저장소를 하나도 지우지 않고 2 로 끝난다 — 지울 키 수만 보는
    실행에서도 같다. 깨지는 시나리오: 커밋이 실패했거나 시드 업서트가 같은 결정적 키로 작품을 되살린 뒤 늦게 정리를 돌려
    살아 있는 그림을 지운다."""
    creator = await _user(db_session)
    live = await _image(db_session, creator.id)
    keys_file = tmp_path / "keys.json"
    keys_file.write_text(json.dumps([f"assets/test/{uuid.uuid4()}.png", live.storage_key]), encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(script, "delete_object", calls.append)
    _use_test_session_for_main(monkeypatch, db_session)

    applied = await script._run(script.parse_args(["delete-objects", "--keys-file", str(keys_file), "--apply"]))
    counted = await script._run(script.parse_args(["delete-objects", "--keys-file", str(keys_file)]))

    assert (applied, counted) == (2, 2)
    assert calls == []
    assert await script.find_live_keys(db_session, json.loads(keys_file.read_text(encoding="utf-8"))) == [
        live.storage_key
    ]


async def test_delete_objects_deletes_every_key_when_no_asset_row_remains(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """재대조의 대조군 — 그림 행이 하나도 키를 가리키지 않으면 키를 전부 지우고 0 으로 끝난다."""
    keys = sorted(f"assets/test/{uuid.uuid4()}.png" for _ in range(2))
    keys_file = tmp_path / "keys.json"
    keys_file.write_text(json.dumps(keys), encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(script, "delete_object", calls.append)
    _use_test_session_for_main(monkeypatch, db_session)

    code = await script._run(script.parse_args(["delete-objects", "--keys-file", str(keys_file), "--apply"]))

    assert code == 0
    assert calls == keys


def test_delete_objects_without_apply_only_counts() -> None:
    calls: list[str] = []

    result = script.delete_objects(["a.png", "b.png"], apply=False, delete_fn=calls.append)

    assert result == {"planned": 2}
    assert calls == []


def test_delete_objects_keeps_going_after_a_failed_key() -> None:
    """한 키를 지우다 실패해도 나머지 키는 지운다 — 멈추면 실패한 키 뒤의 그림이 전부 남는다."""
    calls: list[str] = []

    def delete_fn(key: str) -> None:
        calls.append(key)
        if key == "b.png":
            raise RuntimeError("합성 저장소 오류")

    result = script.delete_objects(["a.png", "b.png", "c.png"], apply=True, delete_fn=delete_fn)

    assert calls == ["a.png", "b.png", "c.png"]
    assert result == {"deleted": 2, "failed": 1}


async def test_moderation_action_and_notification_keep_their_rows_with_content_cleared(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """운영 조치와 그 통지는 기록이라 남고 작품 칸만 빈다. 깨지는 시나리오: 기록까지 지워 조치 이력이 사라지거나, 칸을 비우지
    않아 작품 DELETE 가 FK 위반이 난다."""
    creator = await _user(db_session)
    admin = await _create_admin(db_session)
    target = await _story(db_session, creator.id)
    action = ModerationAction(content_id=target.content.id, admin_id=admin["id"], action=ModerationActionType.RESTRICT)
    db_session.add(action)
    await db_session.flush()
    notification = Notification(user_id=creator.id, content_id=target.content.id, action_id=action.id)
    db_session.add(notification)
    await db_session.flush()

    await _apply(db_session, [target], tmp_path / "keys.json")

    assert await _count(db_session, Content, Content.id == target.content.id) == 0
    assert await db_session.scalar(select(ModerationAction.content_id).where(ModerationAction.id == action.id)) is None
    assert await _count(db_session, ModerationAction, ModerationAction.id == action.id) == 1
    assert await db_session.scalar(select(Notification.content_id).where(Notification.id == notification.id)) is None
    assert await _count(db_session, Notification, Notification.id == notification.id) == 1


async def test_room_records_keep_their_rows_with_room_cleared(db_session: AsyncSession, tmp_path: Path) -> None:
    """방을 가리키는 운영자 조치 기록·버린 응답 기록·응답 신고는 기록이라 남고 방 칸만 빈다. 깨지는 시나리오: 기록까지 지워
    조치 이력·신고 증거가 사라지거나, 방 DELETE 가 이 행들 때문에 FK 위반이 난다."""
    creator = await _user(db_session)
    reader = await _user(db_session)
    admin = await _create_admin(db_session)
    target = await _story(db_session, creator.id)
    room = await _room(db_session, target, reader.id)
    message_id = await db_session.scalar(select(ChatMessage.id).where(ChatMessage.chat_room_id == room.id))
    log = AdminActionLog(admin_id=admin["id"], action_type="chat-view", target_chat_room_id=room.id)
    discarded = DiscardedResponse(user_id=reader.id, chat_room_id=room.id, kind="regenerate", discarded_count=1)
    report = ChatMessageReport(
        reporter_user_id=reader.id,
        chat_room_id=room.id,
        chat_message_id=message_id,
        reason="inappropriate",
        status=ReportStatus.PENDING,
    )
    db_session.add_all([log, discarded, report])
    await db_session.flush()

    await _apply(db_session, [target], tmp_path / "keys.json")

    assert await _count(db_session, ChatRoom, ChatRoom.id == room.id) == 0
    assert await db_session.scalar(select(AdminActionLog.target_chat_room_id).where(AdminActionLog.id == log.id)) is None
    assert await _count(db_session, AdminActionLog, AdminActionLog.id == log.id) == 1
    assert (
        await db_session.scalar(select(DiscardedResponse.chat_room_id).where(DiscardedResponse.id == discarded.id))
        is None
    )
    assert await _count(db_session, DiscardedResponse, DiscardedResponse.id == discarded.id) == 1
    assert (
        await db_session.execute(
            select(ChatMessageReport.chat_room_id, ChatMessageReport.chat_message_id).where(
                ChatMessageReport.id == report.id
            )
        )
    ).one() == (None, None)
