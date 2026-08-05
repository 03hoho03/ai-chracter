"""시드 JSON 하나를 발행 상태의 콘텐츠로 DB 에 밀어 넣는다.

빌더 API 의 자동저장 로직(`api.content.router._update_story_draft`)을 그대로 재사용하고,
그 앞뒤로 시드에만 필요한 것 — 결정적 UUID, 발행 검증, 발행 포인터 — 만 붙인다(PRD §8 의
선택지 (a)). 자식 행 조정(entity_id 업서트 + 사라진 항목 삭제) 로직을 두 벌 유지하지
않으려는 것이고, 그래서 draft 스키마가 바뀌면 시드도 자동으로 따라간다.

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

from sqlalchemy.ext.asyncio import AsyncSession

from api.content.publish import validate_story_publish
from api.content.router import _update_story_draft
from api.content.schemas import EndingRuleGroupDraftItem, StoryDraftPayload
from api.db.models.content import (
    Content,
    ContentType,
    ContentVersion,
    ContentVisibility,
    ModerationStatus,
)
from api.db.models.story import Ending, StartingSetup, StoryVersionDetail

from .ids import SEED_AUTHOR_USER_ID, seed_uuid


class SeedPublishError(Exception):
    """발행 검증을 통과하지 못했다 — 메시지에 빈 필드 목록과 slug 가 들어간다."""


def story_content_id(slug: str) -> uuid.UUID:
    return seed_uuid("story", slug)


def story_version_id(slug: str) -> uuid.UUID:
    return seed_uuid("story", slug, "version")


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
    version_id = story_version_id(slug)

    # `relationship()` 을 선언하지 않는 코드베이스라(순수 FK 컬럼만) 참조 순서를 직접 지킨다:
    # contents -> flush -> content_versions -> flush -> story_version_details -> flush -> 자식들.
    content = await session.get(Content, content_id)
    if content is None:
        # 순환 FK 인 `current_published_version_id` 는 생성자에 넘기지 않는다 — 가리킬 버전
        # 행이 아직 없다. 아래에서 버전을 flush 한 뒤 속성 대입으로 건다.
        content = Content(
            id=content_id,
            type=ContentType.STORY,
            creator_user_id=SEED_AUTHOR_USER_ID,
            hashtags=payload.hashtags,
            visibility=ContentVisibility.PUBLIC,
            moderation_status=ModerationStatus.NORMAL,
        )
        session.add(content)
        await session.flush()

    version = await session.get(ContentVersion, version_id)
    if version is None:
        version = ContentVersion(
            id=version_id, content_id=content_id, detail_description=payload.description
        )
        session.add(version)
        await session.flush()

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

    version.version_number = 1
    # 최초 시드 시각을 유지한다 — 재시드가 발행 시각을 매번 앞당길 이유가 없다.
    version.published_at = version.published_at or datetime.now(UTC)
    # 시드 콘텐츠는 정의상 홈 목록에 떠야 한다 — payload 의 visibility 나 dev 에서 걸어둔
    # 이용제한 상태가 아니라 이 값이 진실 공급원이다.
    content.visibility = ContentVisibility.PUBLIC
    content.moderation_status = ModerationStatus.NORMAL
    content.current_published_version_id = version_id
    await session.flush()
    return content_id


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
