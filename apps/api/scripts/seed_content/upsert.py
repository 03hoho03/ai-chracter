"""시드 JSON 하나를 발행 상태의 콘텐츠로(미발행 표시면 초안으로) DB 에 밀어 넣는다.

빌더 API 의 자동저장 로직(`api.content.router._update_story_draft` /
`_update_character_draft`)을 그대로 재사용하고, 그 앞뒤로 시드에만 필요한 것 — 결정적
UUID, 발행 검증, 발행 포인터 — 만 붙인다. 자식 행 조정(entity_id
업서트 + 사라진 항목 삭제) 로직을 두 벌 유지하지 않으려는 것이고, 그래서 draft 스키마가
바뀌면 시드도 자동으로 따라간다.

프로덕션 발행과 의도적으로 다른 점 두 가지:

- **버전은 콘텐츠당 하나(`version_number=1`)이고 UUID 가 slug 파생으로 영구 고정**이다.
  재발행이 새 버전 행을 만들면 `chat_rooms.content_version_id` 로 그 버전에 핀이 걸린 기존
  대화방이 고아가 되므로, 내용 수정은 같은 버전 행의 in-place 갱신으로 처리한다.
- **LLM 안전 필터(`build_story_publish_filter_prompt`)를 호출하지 않는다** — 시드 콘텐츠는
  사람이 검수한 것이고, 시드를 돌릴 때마다 LLM 을 콘텐츠 수만큼 부를 이유가 없다.
  `validate_story_publish()`(필드 검증)는 그대로 통과해야 한다.

세션은 커밋하지 않는다 — 여러 콘텐츠를 한 트랜잭션에 묶을지는 호출부가 정한다.
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.assets.image_processing import generate_blurred_image
from api.content.publish import (
    draft_dangling_situation_note_paths,
    draft_dangling_stat_rule_paths,
    validate_character_publish,
    validate_story_publish,
)
from api.content.router import _update_character_draft, _update_story_draft
from api.content.schemas import (
    CharacterDraftPayload,
    MediaBookPayload,
    StoryDraftPayload,
)
from api.db.models.character import CharacterVersionDetail, SituationalImage
from api.db.models.chat import ChatRoom
from api.db.models.content import (
    Content,
    ContentType,
    ContentVersion,
    ContentVisibility,
    ModerationStatus,
)
from api.db.models.media import AssetKind
from api.db.models.story import (
    Ending,
    KeywordNote,
    MediaBookCell,
    MediaBookPerson,
    MediaBookScene,
    SituationNote,
    StartingSetup,
    StatDef,
    StatRule,
    StoryVersionDetail,
)

from .ids import SEED_AUTHOR_USER_ID, seed_uuid
from .images import ensure_asset, read_image, situational_image_slug
from .loader import SeedImage


class SeedPublishError(Exception):
    """발행 검증을 통과하지 못했다 — 메시지에 빈 필드 목록과 slug 가 들어간다."""


def story_content_id(slug: str) -> uuid.UUID:
    return seed_uuid("story", slug)


def story_version_id(slug: str) -> uuid.UUID:
    return seed_uuid("story", slug, "version")


def story_draft_version_id(slug: str) -> uuid.UUID:
    return seed_uuid("story", slug, "draft")


def character_content_id(slug: str) -> uuid.UUID:
    return seed_uuid("character", slug)


def character_version_id(slug: str) -> uuid.UUID:
    return seed_uuid("character", slug, "version")


def character_draft_version_id(slug: str) -> uuid.UUID:
    return seed_uuid("character", slug, "draft")


async def upsert_story(
    session: AsyncSession,
    slug: str,
    payload: StoryDraftPayload,
    *,
    published: bool = True,
    media_book_images: Mapping[uuid.UUID, SeedImage] | None = None,
) -> uuid.UUID:
    """스토리 하나를 발행 상태로 업서트하고 콘텐츠 id 를 돌려준다.

    `published` 가 거짓이면(JSON 의 `seedPublished: false`) 초안 버전만 만들고 발행 검증·발행을 건너뛰어
    `current_published_version_id` 가 비어 있다 — 운영에서 아직 발행하지 않은 작품은 쓰다 만 초안일 수 있다.
    공개 범위는 어느 쪽이든 payload 의 `visibility` 를 따른다.

    `payload.thumbnail_asset_id` 는 이미 채워져 있어야 한다(발행 검증 필수 항목) — 시드
    이미지 자산을 만드는 건 `images.ensure_asset` 의 몫이고, 호출부가 그 결과를 payload 에
    넣어 넘긴다.

    미디어 북 칸 그림은 이 함수가 만든다 — JSON 의 `imageAssetId` 는 운영 자산이라 로컬에 없다. 칸마다
    `media_book_images` 의 그림(칸 entity id 키)으로 원본·블러 자산을 만들어 그 id 로 바꿔 넣는다.

    발행 검증에 실패하면 DB 를 **전혀 건드리지 않고** `SeedPublishError` 를 던진다.
    """
    if published:
        bad_fields = _validate_payload(payload)
        if bad_fields:
            raise SeedPublishError(
                f"{slug}: 발행 검증 실패 — 비었거나 참조가 깨진 필드: {', '.join(bad_fields)}"
            )

    content_id = story_content_id(slug)
    content = await _ensure_content(session, content_id, ContentType.STORY, payload.hashtags)

    if published:
        await _warn_if_rooms_lose_their_setups(session, slug, content_id, payload)

    # 자동저장은 미디어 북 키가 없으면 칸을 건드리지 않는다. 같은 slug 를 미디어 북 없는 JSON 으로 다시 시드하면(묶음
    # 없는 작업트리가 같은 로컬 DB 에 튜토리얼을 넣을 때) 앞선 인물·장면·칸이 새 본문에 붙어 남으므로 빈 미디어 북으로 비운다.
    media_book = payload.media_book or MediaBookPayload(people=[], scenes=[], cells=[])
    cell_blurs: dict[uuid.UUID, uuid.UUID] = {}
    cells = []
    for cell in media_book.cells:
        image = (media_book_images or {}).get(cell.id)
        original_asset_id, blurred_asset_id = await _ensure_original_and_blur(session, f"{slug}-cell-{cell.id}", image)
        cell_blurs[cell.id] = blurred_asset_id
        cells.append(cell.model_copy(update={"image_asset_id": original_asset_id}))
    payload = payload.model_copy(update={"media_book": media_book.model_copy(update={"cells": cells})})
    # `_update_media_book` 이 칸 그림을 작가 소유·READY 자산인지 DB 에서 확인한다.
    await session.flush()

    # 발행 버전을 마지막에 채운다 — 루프가 끝난 `version` 을 `_publish` 가 발행한다.
    version_ids = (story_draft_version_id(slug), story_version_id(slug)) if published else (story_draft_version_id(slug),)
    for version_id in version_ids:
        version = await _ensure_version(session, content_id, version_id, payload.description)
        if await session.get(StoryVersionDetail, version_id) is None:
            # `_update_story_draft` 는 이 행이 이미 있다고 보고 `db.get` 으로 집어 든다
            # (빌더에서는 `POST /contents` 가 만들어 둔다). 나머지 필드는 그 함수가 채운다.
            session.add(
                StoryVersionDetail(
                    content_version_id=version_id,
                    name=payload.name,
                    one_liner=payload.one_liner,
                    prompt_template=payload.prompt_template,
                )
            )
            await session.flush()
        await _update_story_draft(session, content, version, payload)
        if cell_blurs:
            await session.flush()
            # 자동저장은 새 칸의 블러본을 비워 두고 앱은 발행 때 건다 — 시드는 발행 경로를 타지 않아 여기서 건다.
            for cell_row in await session.scalars(
                select(MediaBookCell).where(MediaBookCell.content_version_id == version_id)
            ):
                cell_row.blurred_asset_id = cell_blurs[cell_row.entity_id]

    await _finish(session, content, version, published=published)
    return content_id


async def upsert_character(
    session: AsyncSession,
    slug: str,
    payload: CharacterDraftPayload,
    *,
    published: bool = True,
    situational_images: Mapping[uuid.UUID, SeedImage] | None = None,
) -> uuid.UUID:
    """캐릭터 하나를 발행 상태로 업서트하고 콘텐츠 id 를 돌려준다.

    `published`·공개 범위는 `upsert_story` 와 같다. `situational_images` 는 상황별 이미지 entity id 키의 그림이고,
    없는 항목은 `images/{캐릭터slug}-scene{n}.png` 파일이나 목업을 쓴다.

    스토리와 달리 **상황별 이미지 자산까지 이 함수가 만든다** — `situationalImages` 항목에는
    자산을 담을 필드가 아예 없어서(`CharacterSituationalImageDraftInput` 은 빌더 자동저장이
    소유하는 `id`/`triggerCondition` 뿐, 실제 이미지는 `POST /assets/{id}/
    register-situational-image` 가 채운다) 호출부가 payload 로 넘길 방법이 없다. 대표
    썸네일(`payload.thumbnail_asset_id`)만 스토리와 동일하게 호출부가 채워서 넘긴다.

    이미지 하나마다 원본(`kind=ORIGINAL`)과 블러(`kind=BLURRED`) 자산 두 행이 생긴다 —
    이미지 보관함이 아직 노출되지 않은 이미지를 블러본으로 보여주기 때문이다.

    발행 검증에 실패하면 DB 를 **전혀 건드리지 않고** `SeedPublishError` 를 던진다.
    """
    missing = [] if not published else validate_character_publish(
        Content(genre_id=payload.genre_id, target=payload.target),
        ContentVersion(detail_description=payload.description),
        CharacterVersionDetail(
            name=payload.name,
            one_liner=payload.one_liner,
            thumbnail_asset_id=payload.thumbnail_asset_id,
            intro=payload.intro,
            character_prompt=payload.character_prompt,
        ),
        # 시드는 항목마다 이미지 자산을 만들어 붙이므로 이미지 없는 상황별 이미지 행이 생기지 않는다.
        [],
    )
    if missing:
        raise SeedPublishError(f"{slug}: 발행 검증 실패 — 비어 있는 필드: {', '.join(missing)}")

    content_id = character_content_id(slug)
    content = await _ensure_content(session, content_id, ContentType.CHARACTER, payload.hashtags)

    # 자산은 버전과 무관하게 slug 파생이라 한 번만 만들면 두 버전이 같은 것을 가리킨다.
    image_assets: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]] = []
    for order, item in enumerate(payload.situational_images):
        original_asset_id, blurred_asset_id = await _ensure_original_and_blur(
            session, situational_image_slug(slug, order), (situational_images or {}).get(item.id)
        )
        image_assets.append((item.id, original_asset_id, blurred_asset_id))
    await session.flush()  # `situational_images.image_asset_id` 가 참조한다

    # 발행 버전을 마지막에 채운다 — 이유는 `upsert_story` 와 같다.
    version_ids = (
        (character_draft_version_id(slug), character_version_id(slug)) if published else (character_draft_version_id(slug),)
    )
    for version_id in version_ids:
        version = await _ensure_version(session, content_id, version_id, payload.description)
        if await session.get(CharacterVersionDetail, version_id) is None:
            # `_update_character_draft` 는 이 행이 이미 있다고 보고 `db.get` 으로 집어 든다
            # (빌더에서는 `POST /contents` 가 만들어 둔다). 나머지 필드는 그 함수가 채운다.
            session.add(
                CharacterVersionDetail(
                    content_version_id=version_id,
                    name=payload.name,
                    one_liner=payload.one_liner,
                    intro=payload.intro,
                    example_dialogues=[],
                    character_prompt=payload.character_prompt,
                )
            )
            await session.flush()

        await _update_character_draft(session, content, version, payload)
        await session.flush()

        # 자동저장 로직은 이미지 자산 필드를 의도적으로 건드리지 않으므로 여기서 채운다.
        rows = {
            row.entity_id: row
            for row in (
                await session.scalars(
                    select(SituationalImage).where(SituationalImage.content_version_id == version_id)
                )
            ).all()
        }
        for entity_id, original_asset_id, blurred_asset_id in image_assets:
            rows[entity_id].image_asset_id = original_asset_id
            rows[entity_id].blurred_asset_id = blurred_asset_id

    await _finish(session, content, version, published=published)
    return content_id


async def _warn_if_rooms_lose_their_setups(
    session: AsyncSession, slug: str, content_id: uuid.UUID, payload: StoryDraftPayload
) -> None:
    """발행본의 시작설정 entity id 가 이번 payload 와 다르고 그 작품에 대화방이 있으면 경고 한 줄을 남긴다.

    튜토리얼과 비공개 묶음을 바꿔 넣으면 같은 콘텐츠 id 의 시작설정·엔딩·스탯 id 가 통째로 바뀐다. 대화방은 이 id 들을
    FK 없이 들고 있어 DB 가 막지 않고, 방이 사라진 항목을 가리킨 채 남는다. 시드는 사용자의 대화방을 지우지 않으므로
    알리기만 한다 — 대화방 이름이나 본문은 적지 않는다.
    """
    existing = set(
        await session.scalars(
            select(StartingSetup.entity_id).where(StartingSetup.content_version_id == story_version_id(slug))
        )
    )
    if not existing or existing == {setup.id for setup in payload.starting_setups}:
        return
    room_count = await session.scalar(
        select(func.count()).select_from(ChatRoom).where(ChatRoom.content_id == content_id)
    )
    if room_count:
        print(
            f"  ! {slug}: 시작설정이 바뀌어 이 작품의 로컬 대화방 {room_count}개가 없는 시작설정·엔딩·스탯을 가리킨다"
            " — 그 대화방을 지운다(DEV.md 의 비공개 시드 묶음 안내)."
        )


async def _ensure_original_and_blur(
    session: AsyncSession, image_slug: str, image: SeedImage | None
) -> tuple[uuid.UUID, uuid.UUID]:
    """그림 한 장의 (원본, 블러) 자산 id — 블러는 원본에서 그때그때 만든다. 상황별 이미지와 미디어 북 칸이 쓴다.
    둘 다 이미지 보관함이 아직 노출되지 않은 그림을 블러본으로 보여 준다.

    `image` 가 없으면 `images/{image_slug}.png` 나 목업을 쓴다. 원본 바이트를 한 번만 읽어 둘 다에 쓴다: 이미지
    파일이 없을 때 목업 폴백 경고가 장당 한 번만 나오고, 블러본이 항상 실제로 올라간 원본의 흐린 버전임이 보장된다.
    블러 id 도 slug 파생 고정값이라 재시드가 자산을 늘리지 않고, moto 를 재기동해도 같은 키로 다시 올라간다. Pillow 호출이
    CPU 를 잡지만 여기는 요청 핸들러가 아니라 시드 스크립트라 스레드풀로 뺄 이유가 없다.
    """
    original = image.data if image is not None else read_image(image_slug)
    crop = image.crop if image is not None else None
    return (
        await ensure_asset(session, image_slug, AssetKind.ORIGINAL, data=original, crop=crop),
        await ensure_asset(
            session, image_slug, AssetKind.BLURRED, data=generate_blurred_image(original)
        ),
    )


async def _ensure_content(
    session: AsyncSession,
    content_id: uuid.UUID,
    content_type: ContentType,
    hashtags: list[str],
) -> Content:
    """`relationship()` 을 선언하지 않는 코드베이스라(순수 FK 컬럼만) 참조 순서를 직접
    지킨다: contents -> flush -> content_versions -> flush -> {타입}_version_details."""
    content = await session.get(Content, content_id)
    if content is None:
        # 순환 FK 인 `current_published_version_id` 는 생성자에 넘기지 않는다 — 가리킬 버전
        # 행이 아직 없다. `_publish` 가 버전을 flush 한 뒤 속성 대입으로 건다.
        content = Content(
            id=content_id,
            type=content_type,
            creator_user_id=SEED_AUTHOR_USER_ID,
            hashtags=hashtags,
            visibility=ContentVisibility.PUBLIC,
            moderation_status=ModerationStatus.NORMAL,
            # 새 작품의 기본값(허용 안 함)이 아니라 이 값을 명시해, 기본값이 바뀌어도 시드 작품의 소설화가 그대로 열려 있게 한다.
            novel_permission="private",
        )
        session.add(content)
        await session.flush()

    return content


async def _ensure_version(
    session: AsyncSession, content_id: uuid.UUID, version_id: uuid.UUID, description: str
) -> ContentVersion:
    """콘텐츠 하나당 버전 행은 둘이다 — 발행본(`*_version_id`)과, 그 옆에 늘 비워 두는
    초안(`*_draft_version_id`).

    초안이 필요한 이유: 빌더는 `published_at IS NULL` 인 버전을 찾아 편집하고(`GET
    /contents/{id}/draft`), 프로덕션 발행 로직은 발행 직후 다음 편집용 초안을 하나 남긴다.
    시드가 발행본만 만들면 작가 계정으로 로그인해도 시드 콘텐츠가 빌더에서 404 로 안 열린다.
    두 버전 다 같은 payload 로 채우므로 초안은 "발행본과 동일한 편집 출발점"이 된다.
    """
    version = await session.get(ContentVersion, version_id)
    if version is None:
        version = ContentVersion(
            id=version_id, content_id=content_id, detail_description=description
        )
        session.add(version)
        await session.flush()

    return version


async def _finish(session: AsyncSession, content: Content, version: ContentVersion, *, published: bool) -> None:
    if published:
        await _publish(session, content, version)
        return
    # 앞선 시드가 발행했던 작품이면 그 발행본 행은 남긴다 — 그 버전에 핀이 걸린 대화방이 고아가 되지 않게.
    content.current_published_version_id = None
    await session.flush()


async def _publish(session: AsyncSession, content: Content, version: ContentVersion) -> None:
    version.version_number = 1
    # 최초 시드 시각을 유지한다 — 재시드가 발행 시각을 매번 앞당길 이유가 없다.
    version.published_at = version.published_at or datetime.now(UTC)
    # 공개 범위는 자동저장이 넣은 payload 값 그대로다 — 운영에서 내보낸 비공개 작품이 로컬 홈에 뜨면 안 된다.
    # 이용제한 상태는 dev 에서 걸어둔 값이 아니라 이 값이 진실 공급원이다.
    content.moderation_status = ModerationStatus.NORMAL
    # 정지 표식은 제한 상태에서만 설 수 있다 — 정상으로 되돌리면서 같이 내린다.
    content.restricted_by_suspension = False
    content.current_published_version_id = version.id
    await session.flush()


def _validate_payload(payload: StoryDraftPayload) -> list[str]:
    """DB 를 건드리기 전에 `validate_story_publish()` + 엔딩 규칙·상황 노트 조건의 스탯 참조 검사를 돌린다.

    검증 함수가 요구하는 건 ORM 행의 값뿐이라 세션 없이 생성자로만 채운 인메모리 인스턴스로
    충분하다(빌더 미리보기가 `chat/router.py` 의 `_preview_*` 헬퍼로 하는 것과 같은 패턴). 시작설정의 물리적 id 자리에는 entity_id
    를 그대로 쓴다 — 여기서는 엔딩 목록을 되찾는 dict 키로만 쓰인다.

    규칙 참조 검사는 어긋난 경로를 하나하나 돌려준다. 시드 JSON 의 entity_id 는 loader 가 파일 안의 위치로 파생하므로
    손으로 쓴 스탯 참조가 어긋나기 쉽다.
    """
    endings_by_setup_id: dict[uuid.UUID, Sequence[Ending]] = {
        setup_item.id: [
            Ending(turn_count_gate=ending_item.turn_count_gate) for ending_item in setup_item.endings
        ]
        for setup_item in payload.starting_setups
    }
    dangling_stat_rule_paths = draft_dangling_stat_rule_paths(payload.starting_setups)
    dangling_situation_note_paths = draft_dangling_situation_note_paths(payload.starting_setups)
    media_book = payload.media_book
    return dangling_stat_rule_paths + dangling_situation_note_paths + validate_story_publish(
        Content(genre_id=payload.genre_id, target=payload.target),
        ContentVersion(detail_description=payload.description),
        StoryVersionDetail(
            name=payload.name,
            one_liner=payload.one_liner,
            thumbnail_asset_id=payload.thumbnail_asset_id,
            prompt_template=payload.prompt_template,
            setting_text=payload.setting_text,
            custom_prompt=payload.custom_prompt,
        ),
        [
            StartingSetup(id=setup_item.id, name=setup_item.name, prologue=setup_item.prologue)
            for setup_item in payload.starting_setups
        ],
        endings_by_setup_id,
        media_book_people=[MediaBookPerson(entity_id=item.id) for item in media_book.people] if media_book else [],
        media_book_scenes=[MediaBookScene(entity_id=item.id) for item in media_book.scenes] if media_book else [],
        media_book_cells=[
            MediaBookCell(person_entity_id=cell.person_id, scene_entity_id=cell.scene_id) for cell in media_book.cells
        ]
        if media_book
        else [],
        keyword_notes=[
            KeywordNote(
                info_text=note_item.info_text,
                trigger_keywords=note_item.trigger_keywords,
                always_on=note_item.always_on,
            )
            for note_item in payload.keyword_notes
        ],
        dangling_stat_rule_paths=dangling_stat_rule_paths,
        stat_defs=[
            StatDef(
                id=stat_item.id,
                min_value=stat_item.min_value,
                max_value=stat_item.max_value,
                initial_value=stat_item.initial_value,
                per_turn_delta=stat_item.per_turn_delta,
            )
            for setup_item in payload.starting_setups
            for stat_item in setup_item.stat_defs
        ],
        # 스탯의 물리 id 자리에는 시작설정처럼 entity_id 를 쓴다 — 규칙이 어느 스탯에 달렸는지 잇는 데만 쓰인다.
        stat_rules=[
            StatRule(stat_def_id=stat_item.id, delta=rule_item.delta)
            for setup_item in payload.starting_setups
            for stat_item in setup_item.stat_defs
            for rule_item in stat_item.rules
        ],
        # 조건은 DB 경로와 같은 JSON 꼴로 넣어야 검증 함수가 두 경로에서 같은 값을 본다.
        situation_notes=[
            SituationNote(
                info_text=note_item.info_text,
                condition_rules=[rule_item.model_dump(mode="json") for rule_item in note_item.condition_rules],
            )
            for setup_item in payload.starting_setups
            for note_item in setup_item.situation_notes
        ],
        dangling_situation_note_paths=dangling_situation_note_paths,
    )
