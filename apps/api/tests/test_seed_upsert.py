"""`scripts/seed_content/upsert.py` 의 스토리 시드 업서트 (US-004)."""

import json
import uuid
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.auth import User
from api.db.models.chat import ChatRoom
from api.db.models.content import (
    Content,
    ContentTarget,
    ContentVersion,
    ContentVisibility,
    ModerationStatus,
)
from api.db.models.media import Asset, AssetKind, AssetStatus
from api.db.models.story import (
    Ending,
    EndingRule,
    EndingRuleGroup,
    KeywordNote,
    Shortcut,
    StartingSetup,
    StatDef,
    StoryVersionDetail,
)
from seed_content.ids import SEED_AUTHOR_USER_ID, seed_uuid
from seed_content.loader import load_story
from seed_content.upsert import (
    SeedPublishError,
    story_content_id,
    story_version_id,
    upsert_story,
)

SLUG = "romance-3rdloop"
# 마이그레이션(91a008760f4a)이 시드한 장르 '로맨스'.
GENRE_ROMANCE = uuid.UUID("b8a1e6b0-1c1a-4b8a-9b0a-000000000001")


def _stat_entity_id(setup_index: int, stat_index: int) -> uuid.UUID:
    """엔딩 규칙이 참조해야 하는 스탯 entity_id — loader 가 파일 안의 위치로 파생하는 값과 같다."""
    return seed_uuid(f"story:{SLUG}:startingSetups[{setup_index}]:statDefs[{stat_index}]")


def _story_json() -> dict[str, Any]:
    """id 를 하나도 적지 않은 시드 JSON — entity_id 는 loader 가 위치로 파생한다.

    시작설정 2개 / 스탯 2개 / 엔딩 2개(하나는 top-level 규칙 + 그룹 중첩 규칙) / 키워드북 /
    단축어까지 담아 자식 테이블 전부를 밟는다.
    """
    return {
        "name": "세 번째 루프",
        "oneLiner": "같은 밤을 세 번째 반복한다",
        "thumbnailAssetId": None,  # 호출부가 ensure_asset 결과로 채운다
        "promptTemplate": "basic",
        "settingText": "세계관 설명",
        "developmentExample": None,
        "customPrompt": None,
        "startingSetups": [
            {
                "name": "첫 번째 밤",
                "prologue": "프롤로그",
                "openingMessage": "또 이 밤이야.",
                "playguide": None,
                "suggestedReplies": ["무슨 일이야?"],
                "statDefs": [
                    {
                        "name": "신뢰",
                        "icon": "heart",
                        "color": "#888888",
                        "minValue": 0,
                        "maxValue": 100,
                        "initialValue": 50,
                        "unit": None,
                        "description": "신뢰도",
                    },
                    {
                        "name": "의심",
                        "icon": "eye",
                        "color": "#666666",
                        "minValue": 0,
                        "maxValue": 100,
                        "initialValue": 10,
                        "unit": None,
                        "description": "의심도",
                    },
                ],
                "endings": [
                    {
                        "name": "해피엔딩",
                        "turnCountGate": 10,
                        "judgmentPrompt": "신뢰가 높은 상태로 끝났는가",
                        "epilogue": "에필로그",
                        "hint": None,
                        "statRules": [
                            {
                                "kind": "rule",
                                "statId": str(_stat_entity_id(0, 0)),
                                "operator": "gte",
                                "threshold": 80,
                                "nextOp": "and",
                            },
                            {
                                "kind": "group",
                                "rules": [
                                    {
                                        "kind": "rule",
                                        "statId": str(_stat_entity_id(0, 1)),
                                        "operator": "lt",
                                        "threshold": 30,
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "name": "배드엔딩",
                        "turnCountGate": 12,
                        "judgmentPrompt": "의심이 끝까지 남았는가",
                        "epilogue": None,
                        "hint": "의심을 놓지 못하면",
                        "statRules": [],
                    },
                ],
            },
            {
                "name": "두 번째 밤",
                "prologue": "두 번째 프롤로그",
                "openingMessage": None,
                "playguide": None,
                "suggestedReplies": [],
                "statDefs": [
                    {
                        "name": "체력",
                        "icon": "spark",
                        "color": "#999999",
                        "minValue": 0,
                        "maxValue": 100,
                        "initialValue": 70,
                        "unit": None,
                        "description": "체력",
                    }
                ],
                "endings": [
                    {
                        "name": "탈출",
                        "turnCountGate": 10,
                        "judgmentPrompt": "루프를 벗어났는가",
                        "epilogue": None,
                        "hint": None,
                        "statRules": [],
                    }
                ],
            },
        ],
        "keywordNotes": [
            {"infoText": "설정 메모", "triggerKeywords": ["루프", "시계"], "startingSetupId": None}
        ],
        "shortcuts": [{"name": "돌아보기", "description": "설명", "prompt": "프롬프트"}],
        "description": "상세 설명",
        "genreId": str(GENRE_ROMANCE),
        "target": "female",
        "hashtags": ["루프", "로맨스"],
        "visibility": "public",
    }


def _write_story(tmp_path: Path, payload: dict[str, Any]) -> Path:
    directory = tmp_path / "stories"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{SLUG}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


async def _seed_author(db_session: AsyncSession) -> None:
    """`contents.creator_user_id` FK 를 만족시킬 작가 계정 (테스트 종료 시 롤백된다)."""
    db_session.add(
        User(
            id=SEED_AUTHOR_USER_ID,
            email="seed-creator@example.com",
            nickname="시드 작가",
            birth_date=date(1995, 1, 1),
            terms_agreed_at=datetime.now(timezone.utc),
            privacy_agreed_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()


async def _thumbnail_asset(db_session: AsyncSession) -> uuid.UUID:
    asset = Asset(
        owner_user_id=SEED_AUTHOR_USER_ID,
        storage_key=f"assets/seed/{uuid.uuid4()}.png",
        kind=AssetKind.THUMBNAIL,
        status=AssetStatus.READY,
    )
    db_session.add(asset)
    await db_session.flush()
    return asset.id


async def _load_seed_payload(
    db_session: AsyncSession, tmp_path: Path, mutate: Callable[[dict[str, Any]], None] | None = None
) -> Any:
    """JSON 파일 -> loader -> 썸네일 자산 주입까지, 실제 시드 경로 그대로 만든다."""
    raw = _story_json()
    if mutate is not None:
        mutate(raw)
    payload = load_story(_write_story(tmp_path, raw))
    if raw["thumbnailAssetId"] is None:
        payload = payload.model_copy(update={"thumbnail_asset_id": await _thumbnail_asset(db_session)})
    return payload


async def _count(db_session: AsyncSession, model: Any, *where: Any) -> int:
    result = await db_session.scalar(select(func.count()).select_from(model).where(*where))
    assert result is not None
    return result


async def _child_row_counts(db_session: AsyncSession, version_id: uuid.UUID) -> dict[str, int]:
    setup_ids = (
        await db_session.scalars(
            select(StartingSetup.id).where(StartingSetup.content_version_id == version_id)
        )
    ).all()
    ending_ids = (
        await db_session.scalars(select(Ending.id).where(Ending.starting_setup_id.in_(setup_ids)))
    ).all()
    group_ids = (
        await db_session.scalars(
            select(EndingRuleGroup.id).where(EndingRuleGroup.ending_id.in_(ending_ids))
        )
    ).all()
    return {
        "startingSetups": len(setup_ids),
        "statDefs": await _count(db_session, StatDef, StatDef.starting_setup_id.in_(setup_ids)),
        "endings": len(ending_ids),
        "endingRuleGroups": len(group_ids),
        "endingRules": await _count(
            db_session,
            EndingRule,
            EndingRule.ending_id.in_(ending_ids) | EndingRule.rule_group_id.in_(group_ids),
        ),
        "keywordNotes": await _count(
            db_session, KeywordNote, KeywordNote.content_version_id == version_id
        ),
        "shortcuts": await _count(db_session, Shortcut, Shortcut.content_version_id == version_id),
    }


async def test_upsert_story_publishes_with_derived_ids(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    await _seed_author(db_session)
    payload = await _load_seed_payload(db_session, tmp_path)

    content_id = await upsert_story(db_session, SLUG, payload)

    assert content_id == seed_uuid("story", SLUG)
    content = await db_session.get(Content, content_id)
    assert content is not None
    assert content.creator_user_id == SEED_AUTHOR_USER_ID
    assert content.current_published_version_id == seed_uuid("story", SLUG, "version")
    assert content.visibility == ContentVisibility.PUBLIC
    assert content.moderation_status == ModerationStatus.NORMAL
    assert content.genre_id == GENRE_ROMANCE
    assert content.target == ContentTarget.FEMALE
    assert content.hashtags == ["루프", "로맨스"]

    version = await db_session.get(ContentVersion, story_version_id(SLUG))
    assert version is not None
    assert version.version_number == 1
    assert version.published_at is not None
    assert version.detail_description == "상세 설명"


async def test_upsert_story_writes_every_child_table(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    await _seed_author(db_session)
    payload = await _load_seed_payload(db_session, tmp_path)

    await upsert_story(db_session, SLUG, payload)
    version_id = story_version_id(SLUG)

    detail = await db_session.get(StoryVersionDetail, version_id)
    assert detail is not None
    assert detail.name == "세 번째 루프"
    assert detail.setting_text == "세계관 설명"
    assert detail.thumbnail_asset_id == payload.thumbnail_asset_id

    assert await _child_row_counts(db_session, version_id) == {
        "startingSetups": 2,
        "statDefs": 3,
        "endings": 3,
        "endingRuleGroups": 1,
        "endingRules": 2,
        "keywordNotes": 1,
        "shortcuts": 1,
    }

    setups = (
        await db_session.scalars(
            select(StartingSetup)
            .where(StartingSetup.content_version_id == version_id)
            .order_by(StartingSetup.order)
        )
    ).all()
    # entity_id 는 JSON 안의 위치에서 파생된다 (loader 규약).
    assert [setup.entity_id for setup in setups] == [
        seed_uuid(f"story:{SLUG}:startingSetups[0]"),
        seed_uuid(f"story:{SLUG}:startingSetups[1]"),
    ]
    assert setups[0].opening_message == "또 이 밤이야."

    endings = (
        await db_session.scalars(
            select(Ending).where(Ending.starting_setup_id == setups[0].id).order_by(Ending.order)
        )
    ).all()
    assert [ending.name for ending in endings] == ["해피엔딩", "배드엔딩"]
    # top-level 규칙과 그룹은 하나의 order 시퀀스를 공유한다 (§1.5).
    top_rule = (
        await db_session.scalars(select(EndingRule).where(EndingRule.ending_id == endings[0].id))
    ).one()
    group = (
        await db_session.scalars(
            select(EndingRuleGroup).where(EndingRuleGroup.ending_id == endings[0].id)
        )
    ).one()
    assert (top_rule.order, group.order) == (0, 1)
    nested_rule = (
        await db_session.scalars(select(EndingRule).where(EndingRule.rule_group_id == group.id))
    ).one()
    stat_defs = (
        await db_session.scalars(
            select(StatDef).where(StatDef.starting_setup_id == setups[0].id).order_by(StatDef.order)
        )
    ).all()
    # 규칙은 스탯의 물리 id 가 아니라 entity_id 를 참조한다 (§1 원칙 4).
    assert top_rule.stat_def_entity_id == stat_defs[0].entity_id
    assert nested_rule.stat_def_entity_id == stat_defs[1].entity_id

    note = (
        await db_session.scalars(
            select(KeywordNote).where(KeywordNote.content_version_id == version_id)
        )
    ).one()
    assert note.trigger_keywords == ["루프", "시계"]
    assert note.starting_setup_id is None


async def test_upsert_story_twice_does_not_duplicate_rows(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    await _seed_author(db_session)
    payload = await _load_seed_payload(db_session, tmp_path)
    version_id = story_version_id(SLUG)

    await upsert_story(db_session, SLUG, payload)
    first_counts = await _child_row_counts(db_session, version_id)
    first_setup_ids = (
        await db_session.scalars(
            select(StartingSetup.id)
            .where(StartingSetup.content_version_id == version_id)
            .order_by(StartingSetup.order)
        )
    ).all()

    await upsert_story(db_session, SLUG, payload)

    assert await _count(db_session, Content, Content.id == story_content_id(SLUG)) == 1
    # 콘텐츠당 버전은 둘 — 발행본과, 빌더가 열 초안. 재시드해도 늘지 않는다.
    assert await _count(db_session, ContentVersion, ContentVersion.content_id == story_content_id(SLUG)) == 2
    assert (
        await _count(
            db_session,
            ContentVersion,
            ContentVersion.content_id == story_content_id(SLUG),
            ContentVersion.published_at.is_(None),
        )
        == 1
    )
    assert await _child_row_counts(db_session, version_id) == first_counts
    # 자식의 물리 id 까지 그대로여야 재시드가 기존 참조를 끊지 않는다.
    assert (
        await db_session.scalars(
            select(StartingSetup.id)
            .where(StartingSetup.content_version_id == version_id)
            .order_by(StartingSetup.order)
        )
    ).all() == first_setup_ids


async def test_upsert_story_updates_content_in_place(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    await _seed_author(db_session)
    await upsert_story(db_session, SLUG, await _load_seed_payload(db_session, tmp_path))
    version_id = story_version_id(SLUG)
    first_published_at = (await db_session.get(ContentVersion, version_id)).published_at  # type: ignore[union-attr]

    def _edit(raw: dict[str, Any]) -> None:
        raw["name"] = "세 번째 루프 (개정)"
        raw["startingSetups"][0]["endings"][0]["epilogue"] = "고친 에필로그"
        raw["shortcuts"] = []  # 사라진 항목은 정리된다

    await upsert_story(db_session, SLUG, await _load_seed_payload(db_session, tmp_path, _edit))

    detail = await db_session.get(StoryVersionDetail, version_id)
    assert detail is not None
    assert detail.name == "세 번째 루프 (개정)"
    counts = await _child_row_counts(db_session, version_id)
    assert counts["shortcuts"] == 0
    setup = (
        await db_session.scalars(
            select(StartingSetup)
            .where(StartingSetup.content_version_id == version_id)
            .order_by(StartingSetup.order)
        )
    ).first()
    assert setup is not None
    ending = (
        await db_session.scalars(
            select(Ending).where(Ending.starting_setup_id == setup.id).order_by(Ending.order)
        )
    ).first()
    assert ending is not None
    assert ending.epilogue == "고친 에필로그"
    # 발행 시각은 최초 시드 값을 유지한다.
    version = await db_session.get(ContentVersion, version_id)
    assert version is not None
    assert version.published_at == first_published_at


async def test_reseed_keeps_existing_chat_room_version_pin_valid(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """버전 UUID 가 고정이라 재시드가 기존 대화방의 핀을 고아로 만들지 않는다."""
    await _seed_author(db_session)
    payload = await _load_seed_payload(db_session, tmp_path)
    content_id = await upsert_story(db_session, SLUG, payload)
    version_id = story_version_id(SLUG)

    reader = User(
        email=f"reader-{uuid.uuid4()}@example.com",
        nickname="독자",
        birth_date=date(1995, 1, 1),
        terms_agreed_at=datetime.now(timezone.utc),
        privacy_agreed_at=datetime.now(timezone.utc),
    )
    db_session.add(reader)
    await db_session.flush()
    setup = (
        await db_session.scalars(
            select(StartingSetup).where(StartingSetup.content_version_id == version_id)
        )
    ).first()
    assert setup is not None
    room = ChatRoom(
        user_id=reader.id,
        content_id=content_id,
        content_version_id=version_id,
        starting_setup_entity_id=setup.entity_id,
    )
    db_session.add(room)
    await db_session.flush()

    await upsert_story(db_session, SLUG, payload)

    await db_session.refresh(room)
    assert room.content_version_id == version_id
    assert await db_session.get(ContentVersion, room.content_version_id) is not None
    # 방이 고정한 시작설정도 같은 버전 안에서 그대로 조회된다.
    assert (
        await db_session.scalars(
            select(StartingSetup).where(
                StartingSetup.content_version_id == room.content_version_id,
                StartingSetup.entity_id == room.starting_setup_entity_id,
            )
        )
    ).one() is not None


async def test_upsert_story_rejects_incomplete_payload_without_writing(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    await _seed_author(db_session)

    def _break(raw: dict[str, Any]) -> None:
        raw["genreId"] = None
        raw["description"] = ""
        raw["startingSetups"][0]["endings"][0]["turnCountGate"] = 5

    raw = _story_json()
    _break(raw)
    payload = load_story(_write_story(tmp_path, raw))  # thumbnailAssetId 도 None 인 채로 둔다

    with pytest.raises(SeedPublishError) as exc_info:
        await upsert_story(db_session, SLUG, payload)

    message = str(exc_info.value)
    assert SLUG in message
    for field in ("thumbnailAssetId", "description", "genreId", "startingSetups[0].endings[0].turnCountGate"):
        assert field in message
    # 검증 실패 시 아무 행도 쓰이지 않는다.
    assert await db_session.get(Content, story_content_id(SLUG)) is None
    assert await db_session.get(ContentVersion, story_version_id(SLUG)) is None


async def test_upsert_story_rejects_ending_rule_pointing_at_unknown_stat(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """엔딩 규칙이 조용히 영영 안 열리는 대신 시드 시점에 막힌다."""
    await _seed_author(db_session)

    def _dangle(raw: dict[str, Any]) -> None:
        rules = raw["startingSetups"][0]["endings"][0]["statRules"]
        rules[0]["statId"] = str(uuid.uuid4())
        rules[1]["rules"][0]["statId"] = str(_stat_entity_id(1, 0))  # 다른 시작설정의 스탯

    payload = await _load_seed_payload(db_session, tmp_path, _dangle)

    with pytest.raises(SeedPublishError) as exc_info:
        await upsert_story(db_session, SLUG, payload)

    message = str(exc_info.value)
    assert "startingSetups[0].endings[0].statRules[0].statId" in message
    assert "startingSetups[0].endings[0].statRules[1].rules[0].statId" in message
    assert await db_session.get(Content, story_content_id(SLUG)) is None
