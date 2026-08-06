"""시드 JSON 하나를 발행 상태의 콘텐츠로 DB 에 밀어 넣는다.

빌더 API 의 자동저장 로직(`api.content.router._update_story_draft` /
`_update_character_draft`)을 그대로 재사용하고, 그 앞뒤로 시드에만 필요한 것 — 결정적
UUID, 발행 검증, 발행 포인터 — 만 붙인다(PRD §8 의 선택지 (a)). 자식 행 조정(entity_id
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
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.assets.image_processing import generate_blurred_image
from api.content.publish import validate_character_publish, validate_story_publish
from api.content.router import _update_character_draft, _update_story_draft
from api.content.schemas import (
    CharacterDraftPayload,
    EndingRuleGroupDraftItem,
    StoryDraftPayload,
)
from api.db.models.character import CharacterVersionDetail, SituationalImage
from api.db.models.content import (
    Content,
    ContentType,
    ContentVersion,
    ContentVisibility,
    ModerationStatus,
)
from api.db.models.media import AssetKind
from api.db.models.story import Ending, StartingSetup, StoryVersionDetail

from .ids import SEED_AUTHOR_USER_ID, seed_uuid
from .images import ensure_asset, read_image, situational_image_slug


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


async def upsert_story(session: AsyncSession, slug: str, payload: StoryDraftPayload) -> uuid.UUID:
    """스토리 하나를 발행 상태로 업서트하고 콘텐츠 id 를 돌려준다.

    `payload.thumbnail_asset_id` 는 이미 채워져 있어야 한다(발행 검증 필수 항목) — 시드
    이미지 자산을 만드는 건 `images.ensure_asset` 의 몫이고, 호출부가 그 결과를 payload 에
    넣어 넘긴다.

    발행 검증에 실패하면 DB 를 **전혀 건드리지 않고** `SeedPublishError` 를 던진다.
    """
    bad_fields = _validate_payload(payload)
    if bad_fields:
        raise SeedPublishError(
            f"{slug}: 발행 검증 실패 — 비었거나 참조가 깨진 필드: {', '.join(bad_fields)}"
        )

    content_id = story_content_id(slug)
    content = await _ensure_content(session, content_id, ContentType.STORY, payload.hashtags)

    # 초안을 발행 버전보다 **먼저** 채운다 — `_update_story_draft` 가 `content.visibility` 를
    # payload 값으로 되돌리므로, 마지막에 도는 `_publish` 가 PUBLIC 으로 확정해야 한다.
    for version_id in (story_draft_version_id(slug), story_version_id(slug)):
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

    await _publish(session, content, version)
    return content_id


async def upsert_character(
    session: AsyncSession, slug: str, payload: CharacterDraftPayload
) -> uuid.UUID:
    """캐릭터 하나를 발행 상태로 업서트하고 콘텐츠 id 를 돌려준다.

    스토리와 달리 **상황별 이미지 자산까지 이 함수가 만든다** — `situationalImages` 항목에는
    자산을 담을 필드가 아예 없어서(`CharacterSituationalImageDraftInput` 은 빌더 자동저장이
    소유하는 `id`/`triggerCondition` 뿐, 실제 이미지는 `POST /assets/{id}/
    register-situational-image` 가 채운다) 호출부가 payload 로 넘길 방법이 없다. 대표
    썸네일(`payload.thumbnail_asset_id`)만 스토리와 동일하게 호출부가 채워서 넘긴다.

    이미지 하나마다 원본(`kind=ORIGINAL`)과 블러(`kind=BLURRED`) 자산 두 행이 생긴다 —
    이미지 보관함이 아직 노출되지 않은 이미지를 블러본으로 보여주기 때문이다(US-074).

    발행 검증에 실패하면 DB 를 **전혀 건드리지 않고** `SeedPublishError` 를 던진다.
    """
    missing = validate_character_publish(
        Content(genre_id=payload.genre_id, target=payload.target),
        ContentVersion(detail_description=payload.description),
        CharacterVersionDetail(
            name=payload.name,
            one_liner=payload.one_liner,
            thumbnail_asset_id=payload.thumbnail_asset_id,
            intro=payload.intro,
            character_prompt=payload.character_prompt,
        ),
    )
    if missing:
        raise SeedPublishError(f"{slug}: 발행 검증 실패 — 비어 있는 필드: {', '.join(missing)}")

    content_id = character_content_id(slug)
    content = await _ensure_content(session, content_id, ContentType.CHARACTER, payload.hashtags)

    # 자산은 버전과 무관하게 slug 파생이라 한 번만 만들면 두 버전이 같은 것을 가리킨다.
    image_assets: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]] = []
    for order, item in enumerate(payload.situational_images):
        original_asset_id, blurred_asset_id = await _ensure_situational_assets(session, slug, order)
        image_assets.append((item.id, original_asset_id, blurred_asset_id))
    await session.flush()  # `situational_images.image_asset_id` 가 참조한다

    # 초안을 발행 버전보다 **먼저** 채운다 — 이유는 `upsert_story` 와 같다.
    for version_id in (character_draft_version_id(slug), character_version_id(slug)):
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

        # 자동저장 로직은 이미지 자산 필드를 의도적으로 건드리지 않으므로(US-082) 여기서 채운다.
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

    await _publish(session, content, version)
    return content_id


async def _ensure_situational_assets(
    session: AsyncSession, slug: str, order: int
) -> tuple[uuid.UUID, uuid.UUID]:
    """상황별 이미지 한 장의 (원본, 블러) 자산 id — 블러는 원본에서 그때그때 만든다.

    원본 바이트를 한 번만 읽어 둘 다에 쓴다: 이미지 파일이 없을 때 목업 폴백 경고가 장당 한
    번만 나오고, 블러본이 항상 실제로 올라간 원본의 흐린 버전임이 보장된다. Pillow 호출이
    CPU 를 잡지만 여기는 요청 핸들러가 아니라 시드 스크립트라 스레드풀로 뺄 이유가 없다.
    """
    image_slug = situational_image_slug(slug, order)
    original = read_image(image_slug)
    return (
        await ensure_asset(session, image_slug, AssetKind.ORIGINAL, data=original),
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


async def _publish(session: AsyncSession, content: Content, version: ContentVersion) -> None:
    version.version_number = 1
    # 최초 시드 시각을 유지한다 — 재시드가 발행 시각을 매번 앞당길 이유가 없다.
    version.published_at = version.published_at or datetime.now(UTC)
    # 시드 콘텐츠는 정의상 홈 목록에 떠야 한다 — payload 의 visibility 나 dev 에서 걸어둔
    # 이용제한 상태가 아니라 이 값이 진실 공급원이다.
    content.visibility = ContentVisibility.PUBLIC
    content.moderation_status = ModerationStatus.NORMAL
    content.current_published_version_id = version.id
    await session.flush()


def _validate_payload(payload: StoryDraftPayload) -> list[str]:
    """DB 를 건드리기 전에 `validate_story_publish()` + 엔딩 규칙 참조 검사를 돌린다.

    검증 함수가 요구하는 건 ORM 행의 값뿐이라 세션 없이 생성자로만 채운 인메모리 인스턴스로
    충분하다(US-089 의 미리보기 어댑팅과 같은 패턴). 시작설정의 물리적 id 자리에는 entity_id
    를 그대로 쓴다 — 여기서는 엔딩 목록을 되찾는 dict 키로만 쓰인다.
    """
    endings_by_setup_id: dict[uuid.UUID, Sequence[Ending]] = {
        setup_item.id: [
            Ending(turn_count_gate=ending_item.turn_count_gate) for ending_item in setup_item.endings
        ]
        for setup_item in payload.starting_setups
    }
    return _dangling_stat_refs(payload) + validate_story_publish(
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
    )


def _dangling_stat_refs(payload: StoryDraftPayload) -> list[str]:
    """엔딩 규칙이 같은 시작설정에 없는 스탯을 가리키면 그 필드 경로를 돌려준다.

    `statId` 는 스탯의 entity_id 참조인데(§1 원칙 4) 시드 JSON 의 entity_id 는 loader 가
    파일 안의 위치로 파생하므로, 손으로 쓴 참조는 어긋나기 쉽다. 어긋난 규칙은 발행도
    채팅도 에러 없이 통과한 뒤 엔딩이 조용히 영영 안 열리는 형태로만 드러나므로,
    시드 시점에 발행 검증과 같은 통로로 막는다.
    """
    dangling: list[str] = []
    for setup_index, setup_item in enumerate(payload.starting_setups):
        known_stat_ids = {stat_item.id for stat_item in setup_item.stat_defs}
        for ending_index, ending_item in enumerate(setup_item.endings):
            for rule_index, rule_item in enumerate(ending_item.stat_rules):
                path = f"startingSetups[{setup_index}].endings[{ending_index}].statRules[{rule_index}]"
                if isinstance(rule_item, EndingRuleGroupDraftItem):
                    for nested_index, nested_item in enumerate(rule_item.rules):
                        if nested_item.stat_id not in known_stat_ids:
                            dangling.append(f"{path}.rules[{nested_index}].statId")
                elif rule_item.stat_id not in known_stat_ids:
                    dangling.append(f"{path}.statId")
    return dangling
