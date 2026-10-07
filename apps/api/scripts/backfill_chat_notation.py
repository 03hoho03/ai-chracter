"""이미 DB 에 들어가 있는 시드 작품의 대화 문안을 별표 지문 표기로 바꾼다(일회성).

시드 JSON 의 서술·행동을 `*…*` 로 감싸는 변경은 시드를 다시 돌려야 DB 에 닿는데, 운영에서는
`seed_dev.py` 를 돌릴 수 없다(테스트 계정을 만들고, 이미지가 없으면 목업이 실제 아트를 덮고,
어드민 조치와 빌더 편집을 시드 값으로 되돌린다). 그래서 채팅이 읽는 문안 칸만 골라 고친다.

- 스토리 버전(`story_version_details`): `setting_text`, `development_examples`
- 시작설정(`starting_setups`): `opening_message`, `suggested_replies`
- 캐릭터 버전(`character_version_details`): `intro`, `example_dialogues`, `character_prompt`

대상 행과 칸, 바꾸기 전 값("옛 값")과 바꾼 뒤 값("새 값")은 옆의
`backfill_chat_notation.snapshot.json` 에 전부 적혀 있다. 운영 컨테이너에는 git 이 없으므로
옛 값을 실행 시점에 저장소 이력에서 꺼내지 않고, 변경 직전 커밋의 시드 JSON 에서 미리 뽑아
두었다. 시드 콘텐츠의 행 id 는 slug 에서 파생한 값이라(`seed_content/ids.py`) 스냅샷에 그대로
적을 수 있다. 전개 예시의 옛 값은 셋 중 하나로 인정한다 — 옛 자유 텍스트를 쌍 목록으로 옮긴
마이그레이션의 파싱 결과, 시드 JSON 에 처음 들어간 쌍 목록, 그리고 빈 목록(시드를 옛 JSON 으로
다시 돌리면 이 칸이 비었다).

칸마다 compare-and-set 이다. 현재 값이 새 값이면 건너뛰고(재실행 안전), 옛 값 중 하나면 새 값으로
바꾸고, 그 밖의 값(어드민·빌더가 고친 값)은 건드리지 않고 "불일치"로 보고만 한다. 그 밖의 칸과
테이블(스탯·엔딩·키워드, 발행 시각, 공개 상태, 심사 상태, 이미 만들어진 방의 첫 메시지)은 읽지도
쓰지도 않는다. `contents.has_unpublished_changes` 도 그대로 둔다 — 발행본과 초안의 같은 칸에
같은 옛 값이 있으면 둘 다 같은 새 값이 되고, 둘이 달랐다면(초안을 고쳐 둔 경우) 그 초안 칸은
불일치로 남으므로 "초안이 발행본과 다른가"의 답이 적용 전후로 바뀌지 않는다.

    # 적용 예정 표만 출력(기본, DB 를 바꾸지 않는다)
    cd apps/api && uv run --env-file .env python scripts/backfill_chat_notation.py

    # 적용 — 바꾸기 전 값을 백업 파일로 먼저 떨군 뒤 한 트랜잭션으로 바꾼다
    cd apps/api && uv run --env-file .env python scripts/backfill_chat_notation.py \\
        --apply --backup /tmp/chat-notation-backup.json

    # 되돌리기 — 현재 값이 새 값인 칸만 백업의 값으로 돌린다(`--apply` 없으면 표만 출력)
    cd apps/api && uv run --env-file .env python scripts/backfill_chat_notation.py \\
        --rollback /tmp/chat-notation-backup.json --apply

운영에서 돌리는 방법은 `DEPLOY.md` 의 다른 컨테이너 안 스크립트와 같다(api 컨테이너에서
`exec -T api_$(sudo bash ops/active-color.sh) python scripts/backfill_chat_notation.py …` — 서빙 중인 색 컨테이너).

콘텐츠 문안을 담아 두는 서버 캐시는 없다(Redis 의 캐시는 프롬프트 세트뿐이고 나머지 키는 세션·
레이트리밋 같은 상태다) — 적용 뒤 무효화할 것이 없고, 채팅은 방에 고정된 버전의 칸을 매 턴 읽으므로
기존 방도 다음 턴부터 바뀐 값을 쓴다. 이미 저장된 방의 첫 메시지는 옛 표기로 남는다.
"""

import argparse
import asyncio
import json
import sys
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.character import CharacterVersionDetail
from api.db.models.story import StartingSetup, StoryVersionDetail

SNAPSHOT_PATH = Path(__file__).with_name("backfill_chat_notation.snapshot.json")

STORY_TABLE = "story_version_details"
SETUP_TABLE = "starting_setups"
CHARACTER_TABLE = "character_version_details"

# 이 스크립트가 쓸 수 있는 칸의 전부다. 스냅샷에 다른 칸이 적혀 있으면 읽는 단계에서 죽는다.
ALLOWED_FIELDS: dict[str, frozenset[str]] = {
    STORY_TABLE: frozenset({"setting_text", "development_examples"}),
    SETUP_TABLE: frozenset({"opening_message", "suggested_replies"}),
    CHARACTER_TABLE: frozenset({"intro", "example_dialogues", "character_prompt"}),
}

# 칸 하나의 판정. 표에 그대로 찍힌다.
APPLY = "적용 예정"
DONE = "이미 적용"
MISMATCH = "불일치"
MISSING = "행 없음"
REVERT = "되돌림 예정"
ALREADY_REVERTED = "이미 되돌림"

Row = StoryVersionDetail | StartingSetup | CharacterVersionDetail


class BackupMismatchError(ValueError):
    """백업 항목이 스냅샷과 어긋난다 — 다른 환경의 백업이거나 손댄 백업이다."""


@dataclass(frozen=True)
class Target:
    """(행, 칸) 하나. `old` 는 옛 값으로 인정하는 후보 전부다."""

    label: str
    table: str
    version_id: uuid.UUID
    entity_id: uuid.UUID | None
    field: str
    old: list[Any]
    new: Any


@dataclass(frozen=True)
class Planned:
    target: Target
    status: str
    current: Any


@dataclass(frozen=True)
class RollbackPlanned:
    entry: dict[str, Any]
    status: str
    current: Any


def load_targets(path: Path = SNAPSHOT_PATH) -> list[Target]:
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    targets: list[Target] = []
    for story in snapshot["stories"]:
        for version_id, version_label in _versions(story["version_ids"]):
            prefix = f"story:{story['slug']}:{version_label}"
            targets += _field_targets(prefix, STORY_TABLE, version_id, None, story["fields"])
            for setup in story["starting_setups"]:
                targets += _field_targets(
                    f"{prefix}:setup{setup['index']}",
                    SETUP_TABLE,
                    version_id,
                    uuid.UUID(setup["entity_id"]),
                    setup["fields"],
                )
    for character in snapshot["characters"]:
        for version_id, version_label in _versions(character["version_ids"]):
            targets += _field_targets(
                f"character:{character['slug']}:{version_label}",
                CHARACTER_TABLE,
                version_id,
                None,
                character["fields"],
            )
    return targets


def _versions(version_ids: list[str]) -> list[tuple[uuid.UUID, str]]:
    """스냅샷의 버전 id 는 [발행본, 초안] 순서다(초안이 없는 콘텐츠는 발행본 하나)."""
    return [(uuid.UUID(value), "published" if index == 0 else "draft") for index, value in enumerate(version_ids)]


def _field_targets(
    label: str,
    table: str,
    version_id: uuid.UUID,
    entity_id: uuid.UUID | None,
    fields: dict[str, dict[str, Any]],
) -> list[Target]:
    targets: list[Target] = []
    for field, values in fields.items():
        if field not in ALLOWED_FIELDS[table]:
            raise ValueError(f"{label}: 이 스크립트가 쓰지 않는 칸 {table}.{field}")
        targets.append(
            Target(
                label=label,
                table=table,
                version_id=version_id,
                entity_id=entity_id,
                field=field,
                old=values["old"],
                new=values["new"],
            )
        )
    return targets


async def _fetch(
    session: AsyncSession,
    table: str,
    version_id: uuid.UUID,
    entity_id: uuid.UUID | None,
    *,
    lock: bool,
) -> Row | None:
    statement: Any
    if table == STORY_TABLE:
        statement = select(StoryVersionDetail).where(StoryVersionDetail.content_version_id == version_id)
    elif table == CHARACTER_TABLE:
        statement = select(CharacterVersionDetail).where(CharacterVersionDetail.content_version_id == version_id)
    else:
        statement = select(StartingSetup).where(
            StartingSetup.content_version_id == version_id,
            StartingSetup.entity_id == entity_id,
        )
    if lock:
        statement = statement.with_for_update()
    row: Row | None = (await session.scalars(statement)).one_or_none()
    return row


def _classify(current: Any, target: Target) -> str:
    if current == target.new:
        return DONE
    if current in target.old:
        return APPLY
    return MISMATCH


async def plan(session: AsyncSession, targets: list[Target], *, lock: bool = False) -> list[Planned]:
    """칸마다 현재 값을 읽어 판정만 한다 — DB 를 바꾸지 않는다."""
    planned: list[Planned] = []
    for target in targets:
        row = await _fetch(session, target.table, target.version_id, target.entity_id, lock=lock)
        if row is None:
            planned.append(Planned(target, MISSING, None))
            continue
        current = getattr(row, target.field)
        planned.append(Planned(target, _classify(current, target), current))
    return planned


async def apply(session: AsyncSession, targets: list[Target], backup_path: Path) -> list[Planned]:
    """판정이 "적용 예정"인 칸만 새 값으로 바꾼다. 커밋은 호출부가 한다.

    바꾸기 전에 대상 칸 전부의 현재 값을 `backup_path` 에 쓴다 — 쓰기에 실패하면 아무것도 바꾸지
    않고 예외가 난다. 같은 경로에 파일이 이미 있으면 덮지 않고 멈춘다(앞선 적용의 백업을 재실행이
    지우면 되돌릴 길이 없어진다).
    """
    planned = await plan(session, targets, lock=True)
    entries = [
        {
            "label": item.target.label,
            "table": item.target.table,
            "version_id": str(item.target.version_id),
            "entity_id": None if item.target.entity_id is None else str(item.target.entity_id),
            "field": item.target.field,
            "status": item.status,
            "before": item.current,
            "after": item.target.new,
        }
        for item in planned
        if item.status != MISSING
    ]
    backup = {"created_at": datetime.now(UTC).isoformat(), "entries": entries}
    with backup_path.open("x", encoding="utf-8") as file:
        json.dump(backup, file, ensure_ascii=False, indent=1)

    for item in planned:
        if item.status != APPLY:
            continue
        row = await _fetch(session, item.target.table, item.target.version_id, item.target.entity_id, lock=True)
        assert row is not None
        setattr(row, item.target.field, item.target.new)
    await session.flush()
    return planned


def _check_backup_against_snapshot(entries: list[dict[str, Any]], targets: list[Target]) -> None:
    """백업 항목이 전부 스냅샷의 대상과 맞는지 본다 — 하나라도 어긋나면 한 칸도 쓰기 전에 멈춘다.

    다른 환경에서 뜬 백업이나 손댄 백업을 그대로 되돌리면 스냅샷이 알지 못하는 값이 운영 칸에
    들어간다. 그래서 칸의 정체(테이블·버전·시작설정·필드)가 스냅샷에 있고, 적용 때 넣었다는 값이
    스냅샷의 새 값이며, 적용이 실제로 바꾼 칸이라면 되돌릴 값이 스냅샷의 옛 값 후보 중 하나인지
    확인한다. 적용이 바꾸지 않은 칸(판정이 적용 예정이 아니었던 칸)은 되돌리지 않으므로 그 전 값은
    묻지 않는다.
    """
    by_key = {
        (t.table, str(t.version_id), None if t.entity_id is None else str(t.entity_id), t.field): t for t in targets
    }
    for entry in entries:
        key = (entry["table"], entry["version_id"], entry["entity_id"], entry["field"])
        target = by_key.get(key)
        if target is None:
            raise BackupMismatchError(f"{entry['label']} {entry['field']}: 스냅샷에 없는 칸이다")
        if entry["after"] != target.new:
            raise BackupMismatchError(f"{entry['label']} {entry['field']}: 적용 값이 스냅샷의 새 값과 다르다")
        if entry["status"] == APPLY and entry["before"] not in target.old:
            raise BackupMismatchError(f"{entry['label']} {entry['field']}: 되돌릴 값이 스냅샷의 옛 값이 아니다")


async def plan_rollback(
    session: AsyncSession,
    backup_path: Path,
    *,
    lock: bool = False,
    targets: list[Target] | None = None,
) -> list[RollbackPlanned]:
    """적용 때 실제로 바꾼 칸만 본다. 현재 값이 그때 넣은 새 값일 때만 되돌릴 수 있다.

    DB 를 읽기 전에 백업 전체를 스냅샷과 대조한다(`_check_backup_against_snapshot`).
    """
    backup = json.loads(await asyncio.to_thread(backup_path.read_text, encoding="utf-8"))
    _check_backup_against_snapshot(backup["entries"], load_targets() if targets is None else targets)
    planned: list[RollbackPlanned] = []
    for entry in backup["entries"]:
        if entry["status"] != APPLY:
            continue
        table = entry["table"]
        field = entry["field"]
        entity_id = None if entry["entity_id"] is None else uuid.UUID(entry["entity_id"])
        row = await _fetch(session, table, uuid.UUID(entry["version_id"]), entity_id, lock=lock)
        if row is None:
            planned.append(RollbackPlanned(entry, MISSING, None))
            continue
        current = getattr(row, field)
        if current == entry["after"]:
            status = REVERT
        elif current == entry["before"]:
            status = ALREADY_REVERTED
        else:
            status = MISMATCH
        planned.append(RollbackPlanned(entry, status, current))
    return planned


async def rollback(session: AsyncSession, backup_path: Path) -> list[RollbackPlanned]:
    """판정이 "되돌림 예정"인 칸만 백업의 값으로 되돌린다. 커밋은 호출부가 한다."""
    planned = await plan_rollback(session, backup_path, lock=True)
    for item in planned:
        if item.status != REVERT:
            continue
        entity_id = None if item.entry["entity_id"] is None else uuid.UUID(item.entry["entity_id"])
        row = await _fetch(session, item.entry["table"], uuid.UUID(item.entry["version_id"]), entity_id, lock=True)
        assert row is not None
        setattr(row, item.entry["field"], item.entry["before"])
    await session.flush()
    return planned


def _preview(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = text.replace("\n", "⏎")
    return text if len(text) <= 60 else text[:60] + "…"


def format_plan(planned: list[Planned]) -> str:
    lines = [f"{'판정':<6} {'필드':<20} 대상"]
    for item in planned:
        line = f"{item.status:<6} {item.target.field:<20} {item.target.label}"
        if item.status == MISMATCH:
            line += f"\n       현재 값: {_preview(item.current)}"
        lines.append(line)
    counts = Counter(item.status for item in planned)
    lines.append("합계 " + ", ".join(f"{status} {counts[status]}" for status in (APPLY, DONE, MISMATCH, MISSING)))
    return "\n".join(lines)


def format_rollback(planned: list[RollbackPlanned]) -> str:
    lines = [f"{'판정':<6} {'필드':<20} 대상"]
    for item in planned:
        line = f"{item.status:<6} {item.entry['field']:<20} {item.entry['label']}"
        if item.status == MISMATCH:
            line += f"\n       현재 값: {_preview(item.current)}"
        lines.append(line)
    counts = Counter(item.status for item in planned)
    lines.append(
        "합계 " + ", ".join(f"{status} {counts[status]}" for status in (REVERT, ALREADY_REVERTED, MISMATCH, MISSING))
    )
    return "\n".join(lines)


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else None)
    parser.add_argument("--apply", action="store_true", help="실제로 쓴다(없으면 표만 출력)")
    parser.add_argument("--backup", type=Path, help="--apply 때 바꾸기 전 값을 떨굴 새 파일 경로")
    parser.add_argument("--rollback", type=Path, help="이 백업 파일의 값으로 되돌린다")
    args = parser.parse_args(argv)
    if args.rollback is None and args.apply and args.backup is None:
        parser.error("--apply 에는 --backup 경로가 필요하다")

    from api.db.session import async_session_factory

    async with async_session_factory() as session:
        if args.rollback is not None:
            if not args.apply:
                print(format_rollback(await plan_rollback(session, args.rollback)))
                print("(표만 출력했다 — 되돌리려면 --apply)")
                return 0
            print(format_rollback(await rollback(session, args.rollback)))
            await session.commit()
            print("되돌렸다.")
            return 0

        targets = load_targets()
        if not args.apply:
            print(format_plan(await plan(session, targets)))
            print("(표만 출력했다 — 적용하려면 --apply --backup <경로>)")
            return 0
        planned = await apply(session, targets, args.backup)
        await session.commit()
        print(format_plan(planned))
        print(f"적용했다. 백업: {args.backup}")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
