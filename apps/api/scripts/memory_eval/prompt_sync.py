"""운영 문안 맞추기 — 운영 활성 세트를 내보낸 파일로 측정 DB 의 (레인, 모델)별 활성 세트를 통째로 바꾸고, 다시 읽어 견준다.

문안은 DB 에 있어 측정 이미지가 운영과 같아도 어드민 게시 하나로 다른 문안이 된다. 그래서 측정 DB 의 활성 세트를 운영 활성
세트와 바이트로 같게 만든 뒤에 잰다. 레인은 생성·판정·요약이 읽는 story·character 둘만 맞춘다.

내보낸 파일은 운영 DB 를 읽기 전용 트랜잭션으로 읽은 psql 출력이다 — 트랜잭션 줄 사이에 JSON 배열 한 줄이 있고, 원소마다
섹션 칸(`channel`·`scope`·`slot`·`variant`·`order`·`conditional`·`md5`·`chars`·`body`)과 그 섹션이 든 세트 칸(`lane`·`model`·
`set_version`·`set_id`, 화자 라벨 넷)이 있다. `export_format` 은 꼴 표지다(`md5` 는 운영 Postgres 가 본문으로 계산한 값). 섹션
키는 테이블 유니크 키와 같은 (채널, 범위, 슬롯, 변형)이다.

화자 라벨(`LABEL_FIELDS`)은 세트 칸이지만 생성 프롬프트의 대화 줄·예시 라벨로 실리고 사용자 라벨은 장면 인물 판정에서 사용자
표기로 빠지므로, 본문처럼 운영 값으로 맞추고 견준다. 화자 라벨이 없는 옛 꼴 파일은 거부한다 — 받으면 라벨이 조용히 측정 DB
값으로 남는다.

모델 배정 표(`prompt_routes`)도 같은 배열에 실린다. 측정 서버의 판정·요약·추출이 그 표로 체인과 부를 모델을 고르므로, 문안이
같아도 표가 다르면 다른 세트로 잰다. 원소마다 `kind` 칸이 `section`(위 섹션 원소) 또는 `route`(표 한 행 — `lane`·`room_model`·
`stage`·`chain_model`·`call_model`·`backend`)다. 섹션 원소는 그때 운영 배정 저장 이력의 최신 번호(`route_revision`, 저장한 적이
없으면 null)를 함께 싣는다 — 표가 비어 행 원소가 하나도 없어도 어느 저장 뒤의 표인지 남는다. 덮어쓰기는 측정 DB 의 표를 내보낸
행과 똑같이 바꾸고(운영 표가 비었으면 측정 표도 비운다), 저장 이력 표는 건드리지 않는다(이력 행은 어드민 계정을 가리켜야 한다).
표 행의 값은 이 코드가 아는 값인지 보지 않고 그대로 옮긴다 — 운영 서버가 모르는 행을 건너뛰듯 측정 서버도 같은 행을 건너뛴다.

운영 문안은 공개 저장소에 들어가면 안 되므로 차이는 건수와 섹션 키로만 낸다. 본문은 출력·예외 문구 어디에도 싣지 않는다."""

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.prompt import PromptRoute, PromptSection, PromptSectionSemver, PromptSet, PromptSetSemver

SYNC_LANES = ("story", "character")
# 꼴 표지 — 모델 배정 표 행과 원소 종류(`kind`)·배정 저장 번호 칸을 더한 판. 칸이 바뀌면 올린다. 앞 판(화자 라벨까지) 파일은
# 새 칸이 없어 칸 검사에서 거부된다 — 받으면 측정 DB 의 배정 표가 운영과 같은지 모른 채 잰다.
EXPORT_FORMAT = 3
# 프롬프트에 실리는 세트 칸(`PromptSet` 의 화자 라벨). 세트 버전 문자열과 함께 세트 라벨로 맞추고 견준다.
LABEL_FIELDS = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")
EXPORT_FIELDS = frozenset(
    {"export_format", "kind", "route_revision", "lane", "model", "set_version", "set_id", *LABEL_FIELDS, "channel",
     "scope", "slot", "variant", "order", "conditional", "md5", "chars", "body"}
)  # fmt: skip
# 배정 표 한 행의 원소 칸. 견주는 값 칸은 `ROUTE_VALUE_FIELDS` 다.
ROUTE_VALUE_FIELDS = ("chain_model", "call_model", "backend")
ROUTE_FIELDS = frozenset({"export_format", "kind", "lane", "room_model", "stage", *ROUTE_VALUE_FIELDS})
# 차이 종류 — 세트 단위(내보낸 쪽에만·DB 쪽에만 있는 체인, 라벨)와 섹션 단위(빠진·남는 섹션, 본문·조건·순서), 배정 표 단위(내보낸
# 쪽에만·DB 쪽에만 있는 칸, 같은 칸의 값). 뒤 셋은 앞 판 보고에 없던 종류라 끝에 붙인다.
DIFF_KINDS = (
    "missingSets", "extraSets", "label", "missingSections", "extraSections", "body", "conditional", "order",
    "missingRoutes", "extraRoutes", "route",
)  # fmt: skip

Chain = tuple[str, str]
SectionKey = tuple[str, str, str, str]
# 배정 표의 칸 — (레인, 방 모델, 단계). 테이블 유니크 키와 같다.
RouteKey = tuple[str, str, str]


@dataclass(frozen=True)
class ExportedSection:
    body: str
    md5: str
    conditional: bool
    order: int


@dataclass(frozen=True)
class ExportedSet:
    label: str
    speaker_labels: Mapping[str, str]
    sections: Mapping[SectionKey, ExportedSection]


@dataclass(frozen=True)
class ExportedRoute:
    chain_model: str | None
    call_model: str
    backend: str


@dataclass(frozen=True)
class Export:
    """내보낸 파일 하나 — story·character 체인별 세트, 배정 표 전체(칸 → 값), 배정 저장 이력의 최신 번호(없으면 None)."""

    sets: Mapping[Chain, ExportedSet]
    routes: Mapping[RouteKey, ExportedRoute]
    route_revision: int | None


def chain_key(chain: Chain) -> str:
    return "/".join(chain)


def section_key(chain: Chain, key: SectionKey) -> str:
    return "/".join((*chain, *key))


def route_key(key: RouteKey) -> str:
    return "/".join(key)


def _route_chain(key: RouteKey, route: ExportedRoute) -> Chain:
    """그 행이 읽는 체인 — 생성 행은 체인 칸이 비어 방 모델의 체인을 읽는다."""
    lane, room_model, _ = key
    return (lane, route.chain_model if route.chain_model is not None else room_model)


def load_export(path: Path) -> Export:
    """내보낸 파일을 (레인, 모델)별 세트와 배정 표로 읽는다. story·character 밖 레인의 섹션은 버린다. 칸이 모자라거나(옛 꼴 — 없는
    칸 이름만 낸다) 꼴 표지가 다르거나, 원소 종류를 모르거나, 본문과 기록된 해시가 다르거나(파일이 깨졌다), 한 체인에 세트 라벨이
    둘이거나, 같은 섹션 키·같은 배정 칸이 두 번 나오거나, 섹션 원소의 배정 저장 번호가 서로 다르거나, 배정 행이 읽는 체인이 내보낸
    세트에 없으면(파일이 잘렸다 — 측정 DB 에 남은 옛 세트를 그 칸이 읽게 된다) 거부한다."""
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("[")]
    if len(lines) != 1:
        raise SystemExit(f"내보낸 파일에 JSON 배열 줄이 하나여야 한다(지금 {len(lines)}줄): {path}")
    rows = json.loads(lines[0])
    if not isinstance(rows, list):
        raise SystemExit(f"내보낸 파일의 JSON 줄이 배열이 아니다: {path}")
    labels: dict[Chain, set[tuple[str, ...]]] = {}
    sections: dict[Chain, dict[SectionKey, ExportedSection]] = {}
    routes: dict[RouteKey, ExportedRoute] = {}
    revisions: set[int | None] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SystemExit(f"내보낸 파일 {index}번째 원소가 객체가 아니다: {type(row).__name__}")
        fields = ROUTE_FIELDS if row.get("kind") == "route" else EXPORT_FIELDS
        missing = sorted(fields - set(row))
        if missing:
            raise SystemExit(
                f"내보낸 파일 {index}번째 원소에 칸이 없다(옛 꼴이면 운영에서 새 꼴로 다시 내보낸다): {missing}"
            )
        unknown = sorted(set(row) - fields)
        if unknown:
            raise SystemExit(f"내보낸 파일 {index}번째 원소에 모르는 칸이 있다: {unknown}")
        if row["export_format"] != EXPORT_FORMAT:
            raise SystemExit(f"내보낸 파일의 꼴 표지가 {row['export_format']!r} 다 — {EXPORT_FORMAT} 만 받는다")
        if row["kind"] == "route":
            key = (str(row["lane"]), str(row["room_model"]), str(row["stage"]))
            if key in routes:
                raise SystemExit(f"내보낸 파일에 같은 배정 칸이 두 번 있다: {route_key(key)}")
            chain_model = row["chain_model"]
            routes[key] = ExportedRoute(
                chain_model=None if chain_model is None else str(chain_model),
                call_model=str(row["call_model"]),
                backend=str(row["backend"]),
            )
            continue
        if row["kind"] != "section":
            raise SystemExit(f"내보낸 파일 {index}번째 원소의 kind 가 {row['kind']!r} 다 — section·route 만 받는다")
        revision = row["route_revision"]
        revisions.add(None if revision is None else int(revision))
        chain = (str(row["lane"]), str(row["model"]))
        if chain[0] not in SYNC_LANES:
            continue
        section = (str(row["channel"]), str(row["scope"]), str(row["slot"]), str(row["variant"]))
        body = str(row["body"])
        if hashlib.md5(body.encode("utf-8")).hexdigest() != row["md5"]:
            raise SystemExit(f"내보낸 본문이 기록된 해시와 다르다(파일이 깨졌다): {section_key(chain, section)}")
        chain_sections = sections.setdefault(chain, {})
        if section in chain_sections:
            raise SystemExit(f"내보낸 파일에 같은 섹션이 두 번 있다: {section_key(chain, section)}")
        chain_sections[section] = ExportedSection(
            body=body, md5=str(row["md5"]), conditional=bool(row["conditional"]), order=int(row["order"])
        )
        labels.setdefault(chain, set()).add((str(row["set_version"]), *(str(row[f]) for f in LABEL_FIELDS)))
    if not sections:
        raise SystemExit(f"내보낸 파일에 {'·'.join(SYNC_LANES)} 레인 섹션이 없다: {path}")
    for chain, found in labels.items():
        if len(found) != 1:
            raise SystemExit(f"한 체인에 세트 라벨이 {len(found)}개다: {chain_key(chain)}")
    if len(revisions) != 1:
        raise SystemExit(f"섹션 원소의 route_revision 이 서로 다르다: {sorted(revisions, key=str)}")
    orphans = [route_key(key) for key, route in sorted(routes.items()) if _route_chain(key, route) not in sections]
    if orphans:
        raise SystemExit(f"배정 행이 읽는 체인이 내보낸 세트에 없다(파일이 잘렸다): {orphans}")
    out: dict[Chain, ExportedSet] = {}
    for chain in sorted(sections):
        version, *speakers = next(iter(labels[chain]))
        out[chain] = ExportedSet(
            label=version, speaker_labels=dict(zip(LABEL_FIELDS, speakers, strict=True)), sections=sections[chain]
        )
    return Export(sets=out, routes=routes, route_revision=next(iter(revisions)))


async def active_sets(db: AsyncSession) -> dict[Chain, PromptSet]:
    """측정 DB 의 story·character (레인, 모델)별 활성 세트 — published 중 `published_at` 이 가장 최신인 것(같으면 id 큰 것,
    운영 읽기와 같은 순서)."""
    rows = (
        await db.scalars(
            select(PromptSet)
            .where(PromptSet.status == "published", PromptSet.lane.in_(SYNC_LANES))
            .order_by(PromptSet.lane, PromptSet.model, PromptSet.published_at.desc(), PromptSet.id.desc())
            # 다시 읽을 때 세션에 남은 옛 값(덮어쓰기 전 라벨 등)이 아니라 DB 값을 본다.
            .execution_options(populate_existing=True)
        )
    ).all()
    active: dict[Chain, PromptSet] = {}
    for row in rows:
        active.setdefault((row.lane, row.model), row)
    return active


async def overwrite(db: AsyncSession, exported: Export) -> dict[str, Any]:
    """내보낸 체인마다 측정 DB 의 활성 세트를 통째로 바꾼다 — 그 세트의 섹션을 지우고 내보낸 섹션을 넣고 세트 라벨(버전·화자
    라벨)을 내보낸 값으로. 세트 행은 그대로 두므로 활성 판정(게시 시각)은 바뀌지 않는다. 그리고 배정 표를 내보낸 행으로 통째로
    바꾼다(내보낸 행이 없으면 비운다).

    판 표: 같은 체인에서 같은 (섹션, 번호)는 늘 같은 내용이어야 하는데, 제자리에서 내용을 바꾼 세트에 판 행이 남으면 그 번호가 다른
    내용을 가리킨다. 그래서 덮는 세트의 체인 판 행·섹션 판 행을 함께 지워 "번호 없는 옛 게시본"으로 만든다 — 측정 DB 에서 다음
    게시는 그 앞의 번호 있는 판과 견준다. 다른 판 행이 덮는 세트를 기준판으로 가리키면 거부한다. 기준판 FK 는 세트 행을 지우는 것만
    막고 판 행 지우기는 막지 않아 그대로 지울 수는 있지만, 그러면 그 다른 판이 "내용이 바뀌고 번호도 없는 세트"를 기준으로 매긴
    번호로 남는다. 활성 세트(가장 늦은 게시)를 기준으로 삼은 판은 그 뒤에 게시된 세트일 수밖에 없어 정상 흐름에서는 생기지 않는
    상태이고, 그 기준판 칸을 비우거나 그 판 행을 지우면 다른 세트의 판 기록을 맞추기가 조용히 고쳐 쓰게 된다. 사람이 측정 DB 를 보고
    정리하게 멈춘다.

    측정 DB 에 그 체인의 활성 세트가 없거나, 새 버전 문자열을 같은 체인의 다른 게시 세트가 이미 쓰고 있거나(게시 버전 유니크
    인덱스에 걸린다), 위 기준판 참조가 있으면 아무것도 쓰기 전에 거부한다. 커밋은 부른 쪽이 한다.

    결과는 체인 키마다 세트 id·지운 섹션·넣은 섹션·지운 판 행 수(체인 판과 섹션 판을 합친 수)이고, `routes` 키에 배정 표의 지운
    행·넣은 행 수다(체인 키는 늘 `/` 를 품어 겹치지 않는다)."""
    active = await active_sets(db)
    missing = [chain_key(chain) for chain in exported.sets if chain not in active]
    if missing:
        raise SystemExit(f"측정 DB 에 활성 세트가 없는 체인: {missing}")
    clashes = []
    for chain, exported_set in exported.sets.items():
        other = await db.scalar(
            select(PromptSet.id).where(
                PromptSet.status == "published",
                PromptSet.lane == chain[0],
                PromptSet.model == chain[1],
                PromptSet.version == exported_set.label,
                PromptSet.id != active[chain].id,
            )
        )
        if other is not None:
            clashes.append(f"{chain_key(chain)}={exported_set.label}")
    if clashes:
        raise SystemExit(
            f"덮어쓸 버전 문자열을 같은 체인의 다른 게시 세트가 이미 쓴다(아무것도 바꾸지 않았다): {clashes}"
        )
    based = []
    for chain in exported.sets:
        uses = await db.scalar(select(func.count()).where(PromptSetSemver.base_set_id == active[chain].id))
        if uses:
            based.append(chain_key(chain))
    if based:
        raise SystemExit(
            "덮어쓸 활성 세트를 다른 판 행이 기준판으로 가리킨다 — 판 기록을 고쳐 쓰지 않으려고 멈춘다(아무것도 바꾸지 "
            f"않았다). 측정 DB 의 판 표를 먼저 정리한다: {based}"
        )
    report: dict[str, Any] = {}
    for chain, exported_set in exported.sets.items():
        target = active[chain]
        removed = await db.execute(delete(PromptSection).where(PromptSection.prompt_set_id == target.id))
        set_semvers = await db.execute(delete(PromptSetSemver).where(PromptSetSemver.prompt_set_id == target.id))
        section_semvers = await db.execute(
            delete(PromptSectionSemver).where(PromptSectionSemver.prompt_set_id == target.id)
        )
        await db.flush()
        for (channel, scope, slot, variant), section in exported_set.sections.items():
            db.add(
                PromptSection(
                    id=uuid.uuid4(), prompt_set_id=target.id, channel=channel, scope=scope, slot=slot,
                    variant=variant, body=section.body, conditional=section.conditional, order=section.order,
                )
            )  # fmt: skip
        target.version = exported_set.label
        for field, value in exported_set.speaker_labels.items():
            setattr(target, field, value)
        await db.flush()
        report[chain_key(chain)] = {
            "setId": str(target.id),
            "removed": _rowcount(removed),
            "inserted": len(exported_set.sections),
            "semverRowsRemoved": _rowcount(set_semvers) + _rowcount(section_semvers),
        }
    routes_removed = await db.execute(delete(PromptRoute))
    await db.flush()
    for (lane, room_model, stage), route in sorted(exported.routes.items()):
        db.add(
            PromptRoute(
                lane=lane, room_model=room_model, stage=stage, chain_model=route.chain_model,
                call_model=route.call_model, backend=route.backend,
            )
        )  # fmt: skip
    await db.flush()
    report["routes"] = {"removed": _rowcount(routes_removed), "inserted": len(exported.routes)}
    return report


def _rowcount(result: Any) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


async def _stored_routes(db: AsyncSession) -> dict[RouteKey, ExportedRoute]:
    rows = (await db.scalars(select(PromptRoute).execution_options(populate_existing=True))).all()
    return {
        (row.lane, row.room_model, row.stage): ExportedRoute(
            chain_model=row.chain_model, call_model=row.call_model, backend=row.backend
        )
        for row in rows
    }


async def compare(db: AsyncSession, exported: Export) -> dict[str, Any]:
    """측정 DB 를 다시 읽어 내보낸 세트·배정 표와 견준다. 본문은 DB 가 계산한 해시(`md5(body)`)를 내보낸 파일의 운영 해시와
    견주므로 저장 경로에서 바이트가 바뀌었어도 잡힌다. 배정 표는 칸마다 값(읽을 체인·부를 모델·경로)을 견주고, 다른 칸은
    `레인/방 모델/단계/칸 이름` 으로 낸다. 결과는 종류별 건수와 키뿐이다 — 견준 수(`chains`·`sections`·`routes`)와 운영 배정 저장
    번호(`routeRevision`)를 함께 싣는다."""
    keys: dict[str, list[str]] = {kind: [] for kind in DIFF_KINDS}
    active = await active_sets(db)
    keys["missingSets"] = [chain_key(chain) for chain in exported.sets if chain not in active]
    keys["extraSets"] = [chain_key(chain) for chain in sorted(active) if chain not in exported.sets]
    for chain, exported_set in exported.sets.items():
        target = active.get(chain)
        if target is None:
            continue
        if target.version != exported_set.label:
            keys["label"].append(f"{chain_key(chain)}/version")
        for field, value in exported_set.speaker_labels.items():
            if getattr(target, field) != value:
                keys["label"].append(f"{chain_key(chain)}/{field}")
        rows = (
            await db.execute(
                select(
                    PromptSection.channel, PromptSection.scope, PromptSection.slot, PromptSection.variant,
                    func.md5(PromptSection.body), PromptSection.conditional, PromptSection.order,
                ).where(PromptSection.prompt_set_id == target.id)
            )
        ).all()  # fmt: skip
        stored = {(r[0], r[1], r[2], r[3]): (str(r[4]), bool(r[5]), int(r[6])) for r in rows}
        for key in sorted(exported_set.sections.keys() | stored.keys()):
            name = section_key(chain, key)
            want = exported_set.sections.get(key)
            have = stored.get(key)
            if have is None:
                keys["missingSections"].append(name)
            elif want is None:
                keys["extraSections"].append(name)
            else:
                for kind, a, b in (
                    ("body", want.md5, have[0]),
                    ("conditional", want.conditional, have[1]),
                    ("order", want.order, have[2]),
                ):
                    if a != b:
                        keys[kind].append(name)
    stored_routes = await _stored_routes(db)
    for cell in sorted(exported.routes.keys() | stored_routes.keys()):
        want_route = exported.routes.get(cell)
        have_route = stored_routes.get(cell)
        if have_route is None:
            keys["missingRoutes"].append(route_key(cell))
        elif want_route is None:
            keys["extraRoutes"].append(route_key(cell))
        else:
            for field in ROUTE_VALUE_FIELDS:
                if getattr(want_route, field) != getattr(have_route, field):
                    keys["route"].append(f"{route_key(cell)}/{field}")
    counts = {kind: len(found) for kind, found in keys.items()}
    return {
        "chains": len(exported.sets),
        "sections": sum(len(s.sections) for s in exported.sets.values()),
        "routes": len(exported.routes),
        "routeRevision": exported.route_revision,
        "differences": sum(counts.values()),
        "counts": counts,
        "keys": {kind: found for kind, found in keys.items() if found},
    }


def exit_code(report: Mapping[str, Any]) -> int:
    return 0 if report["differences"] == 0 else 1


async def clear_prompt_set_cache(redis_url: str) -> list[str]:
    """측정 서버 Redis 의 활성 프롬프트 세트 캐시 키를 지운다 — 체크포인트 복원이 지우는 것과 같은 키다. 서버가 캐시한 옛 세트를
    계속 읽지 않게 덮어쓴 뒤에 부른다. 다른 키는 건드리지 않는다(`FLUSHDB` 를 쓰지 않는다)."""
    from redis.asyncio import Redis

    from api.chat.prompt_set_cache import ACTIVE_PROMPT_SET_KEY_PREFIX

    client = Redis.from_url(redis_url, decode_responses=True)
    try:
        deleted = []
        async for key in client.scan_iter(match=f"{ACTIVE_PROMPT_SET_KEY_PREFIX}*"):
            if await client.delete(key):
                deleted.append(key)
        return deleted
    finally:
        await client.aclose()


async def clear_prompt_routes_cache(redis_url: str) -> int:
    """측정 서버 Redis 의 배정 표 캐시 키(하나)를 지우고 지운 수(0 또는 1)를 낸다. 서버가 캐시한 옛 표로 판정 세트를 고르지 않게
    덮어쓴 뒤에 부른다."""
    from redis.asyncio import Redis

    from api.chat.prompt_routing_cache import PROMPT_ROUTES_CACHE_KEY

    client = Redis.from_url(redis_url, decode_responses=True)
    try:
        return int(await client.delete(PROMPT_ROUTES_CACHE_KEY))
    finally:
        await client.aclose()


# 세션을 여는 함수 — 인자는 DB 이름(템플릿 대조) 또는 없음(작업 DB). 명령은 엔진을 만들어 넘기고, 테스트는 롤백되는 세션을 넘긴다.
OpenDb = Callable[..., AbstractAsyncContextManager[AsyncSession]]
# 템플릿 대조가 거부할 때 템플릿마다 보여 줄 키 수.
SHOWN_KEYS = 10


async def run_sync(open_db: OpenDb, exported: Export, *, check_only: bool, redis_url: str | None) -> dict[str, Any]:
    """`sync-prompts` 의 본문 — 덮어쓰기(한 트랜잭션, 끝나고 커밋)와 캐시 키 정리(활성 세트 키와 배정 표 키), 그리고 새 세션으로
    다시 읽은 대조."""
    out: dict[str, Any] = {}
    if not check_only:
        if not redis_url:
            raise SystemExit(
                "덮어쓰기는 --redis-url(측정 서버가 쓰는 Redis)을 줘야 한다 — 서버가 캐시한 옛 세트를 지운다"
            )
        async with open_db() as db:
            out["overwritten"] = await overwrite(db, exported)
            await db.commit()
        out["redisDeleted"] = len(await clear_prompt_set_cache(redis_url))
        out["routesCacheDeleted"] = await clear_prompt_routes_cache(redis_url)
    async with open_db() as db:
        out["compare"] = await compare(db, exported)
    return out


async def require_templates_synced(templates: Sequence[str], exported: Export, open_db: OpenDb) -> None:
    """프로브가 복원할 체크포인트 템플릿마다 내보낸 운영 세트·배정 표와 대조한다(읽기만). 프로브 시도마다 작업 DB 가 템플릿 복제본으로
    바뀌므로, 템플릿이 맞추기보다 먼저 얼려졌으면 작업 DB 대조가 0 이어도 그 템플릿의 이전 문안이 실린다. 차이가 있는 템플릿이
    하나라도 있으면 템플릿 이름·건수·처음 몇 키만 대고 거부한다."""
    problems = []
    for name in templates:
        async with open_db(name) as db:
            report = await compare(db, exported)
        if report["differences"]:
            keys = [key for found in report["keys"].values() for key in found]
            problems.append(f"{name}: 차이 {report['differences']}건(처음 {keys[:SHOWN_KEYS]})")
    if problems:
        raise SystemExit(
            "운영 문안과 다른 체크포인트 템플릿 — 맞추기(sync-prompts) 뒤 투입·얼리기를 다시 한다: "
            + "; ".join(problems)
        )
