"""`scripts/apply_stat_rules.py` — 이미 DB 에 들어간 시드 작품의 스탯 행에 시드 JSON 의 규칙·카운터 전환을 넣는 일회성
스크립트.

운영의 옛 상태는 이렇게 재현한다: 현재 시드 JSON 을 실제 시드 경로(`upsert_story`)로 넣고(그래야 행의 entity_id 가
로더가 만드는 id 와 같다는 것까지 검사된다), 규칙 행을 지우고, 이번에 카운터로 바뀐 스탯을 판정 스탯으로 되돌린다.
"""

import json
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

import apply_stat_rules as script
from api.db.models.auth import User
from api.db.models.content import Content, ContentVersion
from api.db.models.media import Asset, AssetKind, AssetStatus
from api.db.models.story import StartingSetup, StatDef, StatRule
from seed_content.ids import SEED_AUTHOR_USER_ID
from seed_content.loader import STORIES_DIR, load_story
from seed_content.upsert import story_content_id, upsert_story

# 시작설정 둘에 판정 스탯·원래 카운터·이번에 카운터로 바뀐 스탯이 다 있는 시드.
SLUG = "sf-longnight"
SEED_FILE = f"stories/{SLUG}.json"
# 이번에 카운터로 바뀐 스탯(시작설정 순번, 이름) → 시드의 턴당 변화. 운영 행은 아직 판정 스탯이다.
NEW_COUNTERS = {(0, "남은 일수"): -10, (1, "산소·전력"): -1}


def _user(user_id: uuid.UUID, email: str) -> User:
    now = datetime.now(UTC)
    return User(
        id=user_id,
        email=email,
        nickname="작가",
        birth_date=date(1995, 1, 1),
        terms_agreed_at=now,
        privacy_agreed_at=now,
    )


@pytest.fixture(scope="module")
def links() -> dict[uuid.UUID, script.Link]:
    return script.build_links(script.load_seed_stats(), [])


async def _seed_as_production(db_session: AsyncSession) -> None:
    """시드를 넣은 뒤 규칙을 지우고 새 카운터를 판정 스탯으로 되돌린다 — 규칙이 들어가기 전의 운영 모양이다."""
    db_session.add(_user(SEED_AUTHOR_USER_ID, "seed-creator@example.com"))
    await db_session.flush()
    asset = Asset(
        owner_user_id=SEED_AUTHOR_USER_ID,
        storage_key=f"assets/seed/{uuid.uuid4()}.png",
        kind=AssetKind.THUMBNAIL,
        status=AssetStatus.READY,
    )
    db_session.add(asset)
    await db_session.flush()
    payload = load_story(STORIES_DIR / f"{SLUG}.json").model_copy(update={"thumbnail_asset_id": asset.id})
    await upsert_story(db_session, SLUG, payload)

    rows = await _stat_rows(db_session)
    await db_session.execute(delete(StatRule).where(StatRule.stat_def_id.in_([stat.id for stat, _ in rows])))
    for stat, setup in rows:
        if (setup.order, stat.name) in NEW_COUNTERS:
            stat.per_turn_delta = None
    await db_session.flush()


async def _stat_rows(db_session: AsyncSession) -> list[tuple[StatDef, StartingSetup]]:
    """시드 작품의 모든 버전(발행본·초안)의 스탯 행."""
    rows = await db_session.execute(
        select(StatDef, StartingSetup)
        .join(StartingSetup, StartingSetup.id == StatDef.starting_setup_id)
        .join(ContentVersion, ContentVersion.id == StartingSetup.content_version_id)
        .where(ContentVersion.content_id == story_content_id(SLUG))
        .order_by(StartingSetup.content_version_id, StartingSetup.order, StatDef.order)
    )
    return list(rows.tuples().all())


async def _rules(db_session: AsyncSession) -> list[StatRule]:
    stat_ids = [stat.id for stat, _ in await _stat_rows(db_session)]
    return list(await db_session.scalars(select(StatRule).where(StatRule.stat_def_id.in_(stat_ids))))


async def _row(db_session: AsyncSession, setup_order: int, name: str, *, draft: bool) -> StatDef:
    for stat, setup in await _stat_rows(db_session):
        version = await db_session.get(ContentVersion, setup.content_version_id)
        assert version is not None
        if setup.order == setup_order and stat.name == name and (version.published_at is None) == draft:
            return stat
    raise AssertionError(f"{setup_order}/{name} 행이 없다")


async def _run(
    db_session: AsyncSession,
    links: dict[uuid.UUID, script.Link],
    *,
    execute_writes: bool = False,
    out: Path | None = None,
) -> script.Plan:
    return await script.run(
        db_session, links=links, seed_author_id=SEED_AUTHOR_USER_ID, execute_writes=execute_writes, out=out
    )


def _seed_rule_total() -> int:
    return sum(len(seed.rules) for seed in script.load_seed_stats().values() if seed.file == SEED_FILE)


async def test_dry_run_writes_nothing_and_execute_fills_every_version_once(
    db_session: AsyncSession, links: dict[uuid.UUID, script.Link], tmp_path: Path
) -> None:
    await _seed_as_production(db_session)
    seed_stats = script.load_seed_stats()

    dry = await _run(db_session, links, out=tmp_path / "plan.json")

    assert await _rules(db_session) == []
    for (setup_order, name), _ in NEW_COUNTERS.items():
        for draft in (True, False):
            assert (await _row(db_session, setup_order, name, draft=draft)).per_turn_delta is None
    planned = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    assert planned["mode"] == "dry-run"
    # 판정 스탯 셋 × 버전 둘, 새 카운터 둘 × 버전 둘, 원래 카운터 하나 × 버전 둘.
    assert planned["summary"]["by_action"][script.INSERT_RULES] == 6
    assert planned["summary"]["by_action"][script.SET_COUNTER] == 4
    assert planned["summary"]["by_action"][script.SKIP_COUNTER] == 2
    assert planned["summary"]["rules_to_insert"] == 2 * _seed_rule_total()
    assert dry.blocked_setups == []

    await _run(db_session, links, execute_writes=True, out=tmp_path / "applied.json")

    rules = await _rules(db_session)
    assert len(rules) == 2 * _seed_rule_total()
    rows = await _stat_rows(db_session)
    for stat, setup in rows:
        seed = seed_stats[stat.entity_id]
        own = sorted((rule for rule in rules if rule.stat_def_id == stat.id), key=lambda rule: rule.order)
        # 버전이 달라도 같은 규칙은 로더가 준 같은 entity_id 를 갖는다.
        assert [rule.entity_id for rule in own] == list(seed.rule_entity_ids)
        assert [(rule.condition, rule.delta) for rule in own] == [(r.condition, r.delta) for r in seed.rules]
        assert stat.per_turn_delta == seed.per_turn_delta, f"{setup.order}/{stat.name}"
    applied = json.loads((tmp_path / "applied.json").read_text(encoding="utf-8"))
    assert sorted(applied["inserted_rule_ids"]) == sorted(str(rule.id) for rule in rules)
    assert sorted(applied["counter_stat_def_ids"]) == sorted(
        str(stat.id) for stat, setup in rows if (setup.order, stat.name) in NEW_COUNTERS
    )

    again = await _run(db_session, links, execute_writes=True, out=tmp_path / "again.json")

    assert {decision.action for decision in again.decisions} == {script.SKIP_COUNTER, script.SKIP_HAS_RULES}
    assert len(await _rules(db_session)) == 2 * _seed_rule_total()


async def test_counter_row_is_left_without_rules(
    db_session: AsyncSession, links: dict[uuid.UUID, script.Link]
) -> None:
    """옛 버전에서만 카운터였던 스탯 — 규칙을 달면 카운터에 규칙이 걸린 발행 위반 상태가 된다."""
    await _seed_as_production(db_session)
    counter = await _row(db_session, 0, "AI 자아 성장도", draft=False)
    counter.per_turn_delta = 1
    await db_session.flush()

    planned = await script.plan(db_session, links, seed_author_id=SEED_AUTHOR_USER_ID)
    await script.execute(db_session, planned)

    decision = next(d for d in planned.decisions if d.stat_def_id == counter.id)
    assert decision.action == script.SKIP_COUNTER
    assert [rule for rule in await _rules(db_session) if rule.stat_def_id == counter.id] == []
    assert counter.per_turn_delta == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("max_change_per_turn", 5, id="max-change"),
        pytest.param("change_direction", "increase", id="direction"),
    ],
)
async def test_counter_conversion_skips_a_row_with_a_change_limit(
    db_session: AsyncSession, links: dict[uuid.UUID, script.Link], field: str, value: Any
) -> None:
    """카운터와 두 제한 옵션은 함께 쓸 수 없다 — 건너뛰고, 그 시작설정이 새 판정으로 못 넘어감을 알린다."""
    await _seed_as_production(db_session)
    limited = await _row(db_session, 0, "남은 일수", draft=False)
    setattr(limited, field, value)
    await db_session.flush()

    planned = await script.plan(db_session, links, seed_author_id=SEED_AUTHOR_USER_ID)
    await script.execute(db_session, planned)

    decision = next(d for d in planned.decisions if d.stat_def_id == limited.id)
    assert decision.action == script.SKIP_CHANGE_LIMIT
    assert limited.per_turn_delta is None
    assert [(blocked.is_draft, blocked.stats_without_rules) for blocked in planned.blocked_setups] == [
        (False, ["남은 일수"])
    ]
    # 같은 스탯의 초안 행은 제한이 없어 그대로 카운터가 된다.
    assert (await _row(db_session, 0, "남은 일수", draft=True)).per_turn_delta == -10


async def test_rows_that_drifted_from_the_seed_are_skipped(
    db_session: AsyncSession, links: dict[uuid.UUID, script.Link]
) -> None:
    """이름이 바뀐 행(위치가 밀려 다른 스탯일 수 있다)과 범위가 좁아 규칙 폭이 넘치는 행은 건드리지 않는다."""
    await _seed_as_production(db_session)
    renamed = await _row(db_session, 1, "AI 자아 성장도", draft=False)
    renamed.name = "다른 스탯"
    narrowed = await _row(db_session, 0, "산소·전력", draft=False)
    narrowed.max_value = 3  # 시드 규칙 폭 -4 가 범위 폭 3 을 넘는다
    await db_session.flush()

    planned = await script.plan(db_session, links, seed_author_id=SEED_AUTHOR_USER_ID)
    await script.execute(db_session, planned)

    actions = {d.stat_def_id: d.action for d in planned.decisions}
    assert actions[renamed.id] == script.SKIP_NAME_MISMATCH
    assert actions[narrowed.id] == script.SKIP_RULE_DELTA
    filled = {rule.stat_def_id for rule in await _rules(db_session)}
    assert renamed.id not in filled and narrowed.id not in filled


async def test_unlinked_stat_is_reported_and_name_map_links_it(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """시드 경로 id 가 아닌 스탯은 대응 파일 없이는 비어 남아 그 시작설정이 막히고, 대응 파일로 이으면 채워진다."""
    await _seed_as_production(db_session)
    seed_stats = script.load_seed_stats()
    prod_entity_id = uuid.uuid4()
    for draft in (True, False):
        (await _row(db_session, 1, "AI 자아 성장도", draft=draft)).entity_id = prod_entity_id
    await db_session.flush()

    unlinked = await script.plan(db_session, script.build_links(seed_stats, []), seed_author_id=SEED_AUTHOR_USER_ID)

    assert sorted((b.is_draft, b.setup_name, b.stats_without_rules) for b in unlinked.blocked_setups) == [
        (False, "이미 300일을 함께 보낸 뒤", ["AI 자아 성장도"]),
        (True, "이미 300일을 함께 보낸 뒤", ["AI 자아 성장도"]),
    ]

    name_map = tmp_path / "map.json"
    name_map.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "prod_entity_id": str(prod_entity_id),
                        "seed_file": SEED_FILE,
                        "seed_setup_index": 1,
                        "seed_stat_name": "AI 자아 성장도",
                        "match": "name",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    links = script.build_links(seed_stats, script.load_name_map(name_map))
    planned = await script.plan(db_session, links, seed_author_id=SEED_AUTHOR_USER_ID)
    await script.execute(db_session, planned)

    assert planned.blocked_setups == []
    expected = [uuid.uuid5(prod_entity_id, "rule:0"), uuid.uuid5(prod_entity_id, "rule:1")]
    for draft in (True, False):
        stat = await _row(db_session, 1, "AI 자아 성장도", draft=draft)
        own = sorted((r for r in await _rules(db_session) if r.stat_def_id == stat.id), key=lambda r: r.order)
        assert [rule.entity_id for rule in own] == expected


async def test_refuses_to_touch_another_users_story(
    db_session: AsyncSession, links: dict[uuid.UUID, script.Link], tmp_path: Path
) -> None:
    await _seed_as_production(db_session)
    other = uuid.uuid4()
    db_session.add(_user(other, "someone@example.com"))
    await db_session.flush()
    content = await db_session.get(Content, story_content_id(SLUG))
    assert content is not None
    content.creator_user_id = other
    await db_session.flush()

    with pytest.raises(script.ForeignOwnerError):
        await _run(db_session, links, execute_writes=True, out=tmp_path / "applied.json")

    assert await _rules(db_session) == []
    assert not (tmp_path / "applied.json").exists()
