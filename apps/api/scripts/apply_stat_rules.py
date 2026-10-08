"""이미 DB 에 들어가 있는 시드 작품의 스탯 행에 시드 JSON 의 「조건 → 증감」 규칙과 카운터 전환을 넣는다(일회성).

시드 JSON 에 규칙을 더해도 운영에서는 `seed_dev.py` 를 돌릴 수 없다(테스트 계정을 만들고, 어드민 조치와 빌더 편집을
시드 값으로 되돌린다). 게다가 대화방은 만들어진 시점의 버전에 고정되므로 현재 발행본뿐 아니라 초안과 옛 발행본의
스탯 행에도 규칙이 있어야 그 방들이 새 판정으로 넘어간다. 그래서 모든 버전의 스탯 행을 하나씩 보고 비어 있는 것만
채운다. LLM 은 부르지 않는다.

운영 스탯 행을 시드 스탯에 잇는 방법은 둘이다.

- 시드 경로 id: 시드 로더가 파일 안의 위치로 만드는 스탯 entity_id(`seed_content/loader.py`)와 행의 `entity_id` 가
  같으면 그 시드 스탯이다. 위치가 밀려 다른 스탯을 가리키는 일을 막으려고 이름까지 같아야 한다. 규칙의 entity_id 도
  로더가 `rules[]` 에 주는 경로 id 를 쓴다 — 버전이 달라도 같은 규칙은 같은 id 다(발행 복제가 지키는 관계와 같다).
- 이름 대응 파일(`--name-map`): 시드 경로 id 가 아닌 운영 스탯(빌더에서 따로 만든 작품 등)을 사람이 확인해 시드
  스탯에 이은 목록이다. 항목은 `{"prod_entity_id", "seed_file", "seed_setup_index", "seed_stat_name", "match"}` 이고
  (`seed_file` 은 `seed_content/data/` 기준 경로, 그 밖의 키는 무시한다) 최상위는 `{"entries": [...]}` 다. 이때
  규칙 entity_id 는 `uuid5(prod_entity_id, f"rule:{순번}")` 로 정한다 — 재실행해도, 버전이 달라도 같다.

행마다 하는 일:

- 행이 이미 카운터(`per_turn_delta` 있음)면 건너뛴다. 카운터에 규칙을 달면 발행 검증 위반 상태가 되고, 운영에는 옛
  버전에서만 카운터였던 스탯도 있다.
- 행에 이미 규칙이 있으면 건너뛴다(재실행 안전).
- 시드가 카운터이면 `per_turn_delta` 를 넣는다. 단 그 행에 방향 제한(`change_direction` 이 `both` 가 아님)이나 턴당
  최대 폭(`max_change_per_turn`)이 있으면 건너뛰고 보고한다 — 카운터와 두 제한 옵션은 함께 쓸 수 없다.
- 시드가 규칙이면 규칙 행을 넣는다. 규칙 폭이 그 행의 범위 폭(최대 − 최소)을 넘으면 건너뛰고 보고한다 — 옛 버전의
  범위가 시드와 다르면 생길 수 있고, 발행 검증이 막는 상태다.

대상 스탯이 속한 작품 중 하나라도 소유자가 `--seed-author-id`(기본: 시드 작가)가 아니면 아무것도 쓰지 않고 거부한다
— 사용자 작품은 이 스크립트가 손댈 대상이 아니다. 적용 뒤에도 규칙 없는 판정 스탯이 남아 새 판정으로 넘어가지 못하는
시작설정(대상 작품의 모든 버전)은 따로 보고한다. 초안과 발행본에 같은 규칙을 넣으므로 `has_unpublished_changes` 는
건드리지 않는다.

    # 계획만(기본, 쓰기 없음)
    cd apps/api && uv run --env-file .env python scripts/apply_stat_rules.py --name-map map.json --out plan.json

    # 적용 — 한 트랜잭션. `--out` 에 넣은 규칙 id 와 카운터로 바꾼 스탯 id 를 남긴다(되돌릴 때 쓴다)
    cd apps/api && uv run --env-file .env python scripts/apply_stat_rules.py --name-map map.json \\
        --execute --out applied.json

되돌리기는 `--out` 의 목록으로 한다 — `DELETE FROM stat_rules WHERE id IN (inserted_rule_ids)` 와
`UPDATE stat_defs SET per_turn_delta = NULL WHERE id IN (counter_stat_def_ids)`. 운영에서 돌리는 방법은 다른 컨테이너 안
스크립트와 같다(`DEPLOY.md` 의 "BE → GCE VM" 절, 서빙 중인 색의 api 컨테이너에서 `python scripts/apply_stat_rules.py …`).
"""

import argparse
import asyncio
import json
import sys
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.content import Content, ContentVersion
from api.db.models.story import StartingSetup, StatDef, StatRule
from seed_content.ids import SEED_AUTHOR_USER_ID
from seed_content.loader import DATA_DIR, STORY_DIRS, load_story

# 행 하나의 판정. 요약과 `--out` 에 그대로 찍힌다.
INSERT_RULES = "규칙 추가"
SET_COUNTER = "카운터 전환"
SKIP_COUNTER = "건너뜀: 이미 카운터"
SKIP_HAS_RULES = "건너뜀: 규칙 있음"
SKIP_CHANGE_LIMIT = "건너뜀: 제한 옵션 있는 카운터 전환"
SKIP_RULE_DELTA = "건너뜀: 규칙 폭이 범위 폭 초과"
SKIP_NAME_MISMATCH = "건너뜀: 이름 불일치"
ACTIONS = (
    INSERT_RULES,
    SET_COUNTER,
    SKIP_COUNTER,
    SKIP_HAS_RULES,
    SKIP_CHANGE_LIMIT,
    SKIP_RULE_DELTA,
    SKIP_NAME_MISMATCH,
)


class ForeignOwnerError(Exception):
    """대상 스탯 중 시드 작가가 아닌 사용자의 작품에 속한 것이 있다 — 아무것도 쓰지 않는다."""


class NameMapError(ValueError):
    """이름 대응 파일의 항목이 시드와 맞지 않는다."""


@dataclass(frozen=True)
class SeedRule:
    condition: str
    delta: int


@dataclass(frozen=True)
class SeedStat:
    file: str
    setup_index: int
    name: str
    per_turn_delta: int | None
    rules: tuple[SeedRule, ...]
    # 시드 경로 id 로 이을 때 쓰는 규칙 entity_id(로더가 `rules[]` 에 준 값). 이름 대응은 따로 만든다.
    rule_entity_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class Link:
    """운영 스탯 entity_id 하나를 시드 스탯에 이은 것."""

    seed: SeedStat
    via: str  # "seed_id" | "name_map"
    rule_entity_ids: tuple[uuid.UUID, ...]


@dataclass
class Decision:
    action: str
    stat_def_id: uuid.UUID
    stat_entity_id: uuid.UUID
    stat_name: str
    content_id: uuid.UUID
    content_version_id: uuid.UUID
    version_number: int | None
    is_draft: bool
    setup_entity_id: uuid.UUID
    setup_name: str
    via: str
    seed_file: str
    seed_setup_index: int
    seed_stat_name: str
    per_turn_delta: int | None = None
    rules: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class BlockedSetup:
    """적용 뒤에도 규칙 없는 판정 스탯이 남는 시작설정 — 새 판정으로 넘어가지 못한다."""

    content_id: uuid.UUID
    content_version_id: uuid.UUID
    version_number: int | None
    is_draft: bool
    setup_entity_id: uuid.UUID
    setup_name: str
    stats_without_rules: list[str]


@dataclass
class Plan:
    decisions: list[Decision]
    blocked_setups: list[BlockedSetup]


def load_seed_stats(directories: tuple[Path, ...] = STORY_DIRS) -> dict[uuid.UUID, SeedStat]:
    """시드 스토리 전부의 스탯을 로더가 만드는 스탯 entity_id 로 찾게 한다."""
    stats: dict[uuid.UUID, SeedStat] = {}
    for directory in directories:
        for path in sorted(directory.glob("*.json")):
            payload = load_story(path)
            relative = path.relative_to(DATA_DIR).as_posix()
            for setup_index, setup in enumerate(payload.starting_setups):
                for stat in setup.stat_defs:
                    stats[stat.id] = SeedStat(
                        file=relative,
                        setup_index=setup_index,
                        name=stat.name,
                        per_turn_delta=stat.per_turn_delta,
                        rules=tuple(SeedRule(condition=rule.condition, delta=rule.delta) for rule in stat.rules),
                        rule_entity_ids=tuple(rule.id for rule in stat.rules),
                    )
    return stats


def build_links(seed_stats: dict[uuid.UUID, SeedStat], name_map: list[dict[str, Any]]) -> dict[uuid.UUID, Link]:
    """시드 경로 id 전부와 이름 대응 항목을 운영 스탯 entity_id → 시드 스탯으로 합친다."""
    links = {
        entity_id: Link(seed=seed, via="seed_id", rule_entity_ids=seed.rule_entity_ids)
        for entity_id, seed in seed_stats.items()
    }
    by_ref = {(seed.file, seed.setup_index, seed.name): seed for seed in seed_stats.values()}
    for entry in name_map:
        prod_entity_id = uuid.UUID(entry["prod_entity_id"])
        ref = (entry["seed_file"], int(entry["seed_setup_index"]), entry["seed_stat_name"])
        seed = by_ref.get(ref)
        if seed is None:
            raise NameMapError(f"{prod_entity_id}: 시드에 없는 스탯 {ref}")
        if prod_entity_id in links:
            # 시드 경로 id 와 겹치는 항목은 둘 중 어느 대응을 따를지 정할 수 없다.
            raise NameMapError(f"{prod_entity_id}: 이미 시드 경로 id 이거나 대응 파일에 두 번 나온다")
        links[prod_entity_id] = Link(
            seed=seed,
            via="name_map",
            rule_entity_ids=tuple(uuid.uuid5(prod_entity_id, f"rule:{order}") for order in range(len(seed.rules))),
        )
    return links


def load_name_map(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries: list[dict[str, Any]] = raw["entries"]
    return entries


async def _rule_counts(session: AsyncSession, stat_def_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not stat_def_ids:
        return {}
    rows = await session.execute(
        select(StatRule.stat_def_id, func.count(StatRule.id))
        .where(StatRule.stat_def_id.in_(stat_def_ids))
        .group_by(StatRule.stat_def_id)
    )
    return {stat_def_id: count for stat_def_id, count in rows.tuples()}


def _decide(stat: StatDef, rule_count: int, link: Link) -> tuple[str, int | None, list[dict[str, Any]]]:
    seed = link.seed
    if stat.per_turn_delta is not None:
        return SKIP_COUNTER, None, []
    if rule_count > 0:
        return SKIP_HAS_RULES, None, []
    if link.via == "seed_id" and stat.name != seed.name:
        return SKIP_NAME_MISMATCH, None, []
    if seed.per_turn_delta is not None:
        if stat.change_direction != "both" or stat.max_change_per_turn is not None:
            return SKIP_CHANGE_LIMIT, seed.per_turn_delta, []
        return SET_COUNTER, seed.per_turn_delta, []
    rules = [
        {"entity_id": entity_id, "order": order, "condition": rule.condition, "delta": rule.delta}
        for order, (entity_id, rule) in enumerate(zip(link.rule_entity_ids, seed.rules, strict=True))
    ]
    if any(abs(rule.delta) > stat.max_value - stat.min_value for rule in seed.rules):
        return SKIP_RULE_DELTA, None, rules
    return INSERT_RULES, None, rules


async def plan(
    session: AsyncSession, links: dict[uuid.UUID, Link], *, seed_author_id: uuid.UUID, lock: bool = False
) -> Plan:
    """행마다 판정만 한다 — DB 를 바꾸지 않는다. 남의 작품이 섞여 있으면 `ForeignOwnerError`."""
    statement = (
        select(StatDef, StartingSetup, ContentVersion, Content.creator_user_id)
        .join(StartingSetup, StartingSetup.id == StatDef.starting_setup_id)
        .join(ContentVersion, ContentVersion.id == StartingSetup.content_version_id)
        .join(Content, Content.id == ContentVersion.content_id)
        .where(StatDef.entity_id.in_(list(links)))
        .order_by(Content.id, ContentVersion.version_number.nulls_last(), StartingSetup.order, StatDef.order)
    )
    if lock:
        statement = statement.with_for_update(of=StatDef)
    rows = (await session.execute(statement)).tuples().all()

    foreign = sorted({str(version.content_id) for _, _, version, owner in rows if owner != seed_author_id})
    if foreign:
        raise ForeignOwnerError(f"시드 작가가 아닌 사용자의 작품이 대상에 있다: {', '.join(foreign)}")

    counts = await _rule_counts(session, [stat.id for stat, _, _, _ in rows])
    decisions: list[Decision] = []
    for stat, setup, version, _ in rows:
        link = links[stat.entity_id]
        action, per_turn_delta, rules = _decide(stat, counts.get(stat.id, 0), link)
        decisions.append(
            Decision(
                action=action,
                stat_def_id=stat.id,
                stat_entity_id=stat.entity_id,
                stat_name=stat.name,
                content_id=version.content_id,
                content_version_id=version.id,
                version_number=version.version_number,
                is_draft=version.published_at is None,
                setup_entity_id=setup.entity_id,
                setup_name=setup.name,
                via=link.via,
                seed_file=link.seed.file,
                seed_setup_index=link.seed.setup_index,
                seed_stat_name=link.seed.name,
                per_turn_delta=per_turn_delta,
                rules=rules,
            )
        )
    content_ids = sorted({decision.content_id for decision in decisions})
    return Plan(decisions=decisions, blocked_setups=await _blocked_setups(session, content_ids, decisions))


async def _blocked_setups(
    session: AsyncSession, content_ids: list[uuid.UUID], decisions: list[Decision]
) -> list[BlockedSetup]:
    """대상 작품의 모든 버전·시작설정에서, 적용 뒤 규칙 없는 판정 스탯이 남는 곳을 찾는다.

    채팅이 새 판정을 고르는 조건(판정 스탯이 하나 이상이고 그 전부에 규칙이 있다 — `prepare_stat_judgment`)을 적용 뒤
    상태에 그대로 건다. 판정 스탯이 하나도 없는 시작설정은 새 판정과 상관이 없어 보고하지 않는다.
    """
    if not content_ids:
        return []
    rows = (
        await session.execute(
            select(StatDef, StartingSetup, ContentVersion)
            .join(StartingSetup, StartingSetup.id == StatDef.starting_setup_id)
            .join(ContentVersion, ContentVersion.id == StartingSetup.content_version_id)
            .where(ContentVersion.content_id.in_(content_ids))
            .order_by(
                ContentVersion.content_id, ContentVersion.version_number.nulls_last(), StartingSetup.order, StatDef.order
            )
        )
    ).tuples().all()
    counts = await _rule_counts(session, [stat.id for stat, _, _ in rows])
    action_by_stat = {decision.stat_def_id: decision.action for decision in decisions}

    missing_by_setup: dict[uuid.UUID, list[str]] = {}
    judged_setups: dict[uuid.UUID, tuple[StartingSetup, ContentVersion]] = {}
    for stat, setup, version in rows:
        action = action_by_stat.get(stat.id)
        if stat.per_turn_delta is not None or action == SET_COUNTER:
            continue
        judged_setups[setup.id] = (setup, version)
        if counts.get(stat.id, 0) == 0 and action != INSERT_RULES:
            missing_by_setup.setdefault(setup.id, []).append(stat.name)
    return [
        BlockedSetup(
            content_id=version.content_id,
            content_version_id=version.id,
            version_number=version.version_number,
            is_draft=version.published_at is None,
            setup_entity_id=setup.entity_id,
            setup_name=setup.name,
            stats_without_rules=missing_by_setup[setup_id],
        )
        for setup_id, (setup, version) in judged_setups.items()
        if setup_id in missing_by_setup
    ]


async def execute(session: AsyncSession, planned: Plan) -> None:
    """판정이 "규칙 추가"·"카운터 전환"인 행만 쓴다. 규칙 행의 물리 id 는 `assign_rule_ids` 가 미리 정한 값을 쓰고, 없으면
    여기서 정한다. 커밋은 호출부가 한다."""
    for decision in planned.decisions:
        if decision.action == SET_COUNTER:
            await session.execute(
                update(StatDef)
                .where(StatDef.id == decision.stat_def_id, StatDef.per_turn_delta.is_(None))
                .values(per_turn_delta=decision.per_turn_delta)
            )
        elif decision.action == INSERT_RULES:
            session.add_all(
                StatRule(
                    id=rule.setdefault("id", uuid.uuid4()),
                    entity_id=rule["entity_id"],
                    stat_def_id=decision.stat_def_id,
                    condition=rule["condition"],
                    delta=rule["delta"],
                    order=rule["order"],
                )
                for rule in decision.rules
            )
    await session.flush()


def assign_rule_ids(planned: Plan) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """넣을 규칙 행의 물리 id 를 정하고 (넣을 규칙 id, 카운터로 바꿀 스탯 id) 를 돌려준다 — 쓰기 전에 되돌리기 목록을
    파일로 남기려는 것이다."""
    inserted: list[uuid.UUID] = []
    for decision in planned.decisions:
        if decision.action != INSERT_RULES:
            continue
        for rule in decision.rules:
            rule["id"] = uuid.uuid4()
            inserted.append(rule["id"])
    countered = [decision.stat_def_id for decision in planned.decisions if decision.action == SET_COUNTER]
    return inserted, countered


def summarize(planned: Plan) -> dict[str, Any]:
    by_action = Counter(decision.action for decision in planned.decisions)
    by_content: dict[str, Counter[str]] = {}
    for decision in planned.decisions:
        key = f"{decision.content_id} ({decision.seed_file})"
        by_content.setdefault(key, Counter())[decision.action] += 1
    return {
        "by_action": {action: by_action[action] for action in ACTIONS},
        "rules_to_insert": sum(len(d.rules) for d in planned.decisions if d.action == INSERT_RULES),
        "by_content": {key: dict(counter) for key, counter in by_content.items()},
        "blocked_setups": len(planned.blocked_setups),
    }


def format_report(planned: Plan) -> str:
    summary = summarize(planned)
    lines = ["행동별:"]
    lines += [f"  {action}: {count}" for action, count in summary["by_action"].items()]
    lines.append(f"  넣을 규칙 행: {summary['rules_to_insert']}")
    lines.append("작품별:")
    for key, counter in summary["by_content"].items():
        lines.append(f"  {key}: " + ", ".join(f"{action} {count}" for action, count in counter.items()))
    lines.append("상세(쓰기·제한 건너뜀만):")
    for d in planned.decisions:
        if d.action in (SKIP_COUNTER, SKIP_HAS_RULES):
            continue
        version = "초안" if d.is_draft else f"v{d.version_number}"
        extra = f" 규칙 {len(d.rules)}개" if d.rules else ""
        extra += f" perTurnDelta {d.per_turn_delta}" if d.per_turn_delta is not None else ""
        lines.append(f"  {d.action} | {d.seed_file} {version} {d.setup_name} / {d.stat_name} ({d.via}){extra}")
    lines.append(f"새 판정으로 못 넘어가는 시작설정: {len(planned.blocked_setups)}")
    for blocked in planned.blocked_setups:
        version = "초안" if blocked.is_draft else f"v{blocked.version_number}"
        lines.append(
            f"  {blocked.content_id} {version} {blocked.setup_name}: 규칙 없는 판정 스탯 "
            + ", ".join(blocked.stats_without_rules)
        )
    return "\n".join(lines)


def _report_json(
    planned: Plan, mode: str, inserted: list[uuid.UUID] | None, countered: list[uuid.UUID] | None
) -> str:
    body: dict[str, Any] = {
        "mode": mode,
        "summary": summarize(planned),
        "decisions": [asdict(decision) for decision in planned.decisions],
        "blocked_setups": [asdict(blocked) for blocked in planned.blocked_setups],
    }
    if inserted is not None:
        body["inserted_rule_ids"] = inserted
        body["counter_stat_def_ids"] = countered
    return json.dumps(body, ensure_ascii=False, indent=1, default=str)


async def run(
    session: AsyncSession,
    *,
    links: dict[uuid.UUID, Link],
    seed_author_id: uuid.UUID,
    execute_writes: bool,
    out: Path | None,
) -> Plan:
    """계획을 세우고 `--out` 에 떨군다. `execute_writes` 면 쓰기까지 한다(커밋은 호출부).

    `--out` 은 쓰기 전에 쓴다 — 파일을 못 쓰면 아무것도 바꾸지 않고 예외가 난다. 쓰기가 실패해 롤백되면 파일의 목록은
    없는 행을 가리킬 뿐이라 그대로 지워도 해가 없다. 이미 있는 파일은 덮지 않는다(앞선 적용의 되돌리기 목록을 재실행이
    지우면 되돌릴 길이 없어진다).
    """
    planned = await plan(session, links, seed_author_id=seed_author_id, lock=execute_writes)
    if not execute_writes:
        if out is not None:
            with out.open("x", encoding="utf-8") as file:
                file.write(_report_json(planned, "dry-run", None, None))
        return planned
    assert out is not None
    inserted, countered = assign_rule_ids(planned)
    with out.open("x", encoding="utf-8") as file:
        file.write(_report_json(planned, "execute", inserted, countered))
    await execute(session, planned)
    return planned


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else None)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="계획만 출력한다(기본)")
    mode.add_argument("--execute", action="store_true", help="한 트랜잭션으로 쓴다")
    parser.add_argument("--name-map", type=Path, help="시드 경로 id 가 아닌 운영 스탯을 시드 스탯에 잇는 파일")
    parser.add_argument("--seed-author-id", type=uuid.UUID, default=SEED_AUTHOR_USER_ID)
    parser.add_argument("--out", type=Path, help="계획(또는 적용 결과·되돌리기 목록)을 떨굴 새 파일 경로")
    args = parser.parse_args(argv)
    if args.execute and args.out is None:
        parser.error("--execute 에는 --out 경로가 필요하다(되돌릴 때 지울 규칙 id 목록)")

    links = build_links(load_seed_stats(), load_name_map(args.name_map) if args.name_map else [])

    from api.db.session import async_session_factory

    async with async_session_factory() as session:
        try:
            planned = await run(
                session, links=links, seed_author_id=args.seed_author_id, execute_writes=args.execute, out=args.out
            )
        except ForeignOwnerError as exc:
            print(f"거부: {exc}", file=sys.stderr)
            return 2
        print(format_report(planned))
        if not args.execute:
            print("(계획만 출력했다 — 적용하려면 --execute --out <경로>)")
            return 0
        await session.commit()
        print(f"적용했다. 되돌리기 목록: {args.out}")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
