"""체크포인트별 스탯 고정 — 체크포인트를 얼리기 직전에 방 스탯을 파일 값(`{"50": {"<스탯 이름>": 값, …}, …}`)으로 맞춘다.

대본 넣기는 판정 호출이 없어 스탯이 시작값에 머문다. 체크포인트 상태를 실제 플레이에 가깝게 고정해 두 갈래·기준선이 같은
스탯에서 프로브를 시작하게 한다. 값은 앱이 스탯을 저장하는 방식 그대로(방 스탯 행) 작업 DB 에만 쓰고 LLM 은 부르지 않는다.

거부 조건(모두 모아 한 번에 보고한 뒤 거부): 시작설정에 없는 스탯 이름 · 숫자가 아닌 값 · 범위(최소~최대, 양 끝 포함) 밖 ·
고정 뒤 스탯(파일에 없는 스탯은 방의 지금 값)으로 규칙이 있는 엔딩에 닿음. 엔딩 규칙은 작품 데이터(엔딩 규칙 표)에서 읽어
앱의 규칙 평가 함수로 본다. 규칙이 없는 엔딩은 판정 모델만으로 열리므로 스탯으로 막을 수 없다 — 거부하지 않고 알린다."""

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.ending_rules import evaluate_rule_list
from api.chat.schemas import EndingRuleListItem


@dataclass(frozen=True)
class PinnedStatDef:
    entity_id: str
    name: str
    min_value: float
    max_value: float


def load_pinned_doc(path: Path) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return doc


def pinned_for_checkpoint(doc: Mapping[str, Any], checkpoint: int) -> dict[str, Any]:
    entry = doc.get(str(checkpoint))
    if not isinstance(entry, dict):
        raise SystemExit(f"스탯 고정 파일에 체크포인트 {checkpoint} 항목이 없다")
    return entry


def validate_pinned(
    values: Mapping[str, Any],
    defs: Sequence[PinnedStatDef],
    endings: Sequence[tuple[str, list[EndingRuleListItem]]],
    current: Mapping[str, float],
) -> tuple[dict[str, float], list[str], list[str]]:
    """(스탯 entity_id → 고정 값, 거부 사유 목록, 알림 목록). 거부 사유가 하나라도 있으면 쓰지 않는다."""
    by_name = {d.name: d for d in defs}
    resolved: dict[str, float] = {}
    errors: list[str] = []
    for name, raw in values.items():
        stat = by_name.get(name)
        if stat is None:
            errors.append(f"없는 스탯: {name!r}")
            continue
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            errors.append(f"숫자 아님: {name}={raw!r}")
            continue
        value = float(raw)
        if not stat.min_value <= value <= stat.max_value:
            errors.append(f"범위 밖: {name}={value} (허용 {stat.min_value}~{stat.max_value})")
            continue
        resolved[stat.entity_id] = value
    notes: list[str] = []
    after = {**current, **resolved}
    for ending_name, rules in endings:
        if not rules:
            notes.append(f"규칙 없는 엔딩 {ending_name!r} — 판정 모델만으로 열려 스탯으로 막을 수 없다")
            continue
        if evaluate_rule_list(rules, after):
            errors.append(f"엔딩 문턱: 고정 뒤 스탯이 엔딩 {ending_name!r} 의 규칙을 채운다")
    return resolved, errors, notes


def pinned_diff(fingerprint_stats: Mapping[str, str], pinned: Mapping[str, float]) -> list[str]:
    """복원 뒤 지문의 스탯이 고정 값과 같은가(숫자로 비교 — 저장 값은 `30` 이나 `30.0` 으로 읽힌다)."""
    diffs = []
    for stat_id, value in pinned.items():
        now = fingerprint_stats.get(stat_id)
        if now is None:
            diffs.append(f"{stat_id}: 고정 {value} → 지금 없음")
        elif float(now) != value:
            diffs.append(f"{stat_id}: 고정 {value} → 지금 {now}")
    return diffs


async def apply_pinned_stats(
    db: AsyncSession, room_id: uuid.UUID, setup_id: uuid.UUID, values: Mapping[str, Any]
) -> dict[str, Any]:
    """검사를 모두 통과하면 방 스탯 행에 쓰고 커밋한다(앱의 스탯 쓰기 함수 — 행이 없으면 만들어 쓴다)."""
    from api.chat.room_stats import load_room_stats
    from api.chat.turn_store import _write_room_stat

    stat_defs, stat_rows, current = await load_room_stats(db, room_id, setup_id)
    defs = [PinnedStatDef(str(d.entity_id), d.name, float(d.min_value), float(d.max_value)) for d in stat_defs]
    resolved, errors, notes = validate_pinned(values, defs, await _ending_rules(db, setup_id), current)
    if errors:
        raise SystemExit("스탯 고정 거부: " + "; ".join(errors))
    for stat_id, value in resolved.items():
        _write_room_stat(db, room_id, stat_rows, stat_id, value)
    await db.commit()
    return {"pinned": resolved, "notes": notes}


def validate_sequence(
    doc: Mapping[str, Any],
    checkpoints: Sequence[int],
    defs: Sequence[PinnedStatDef],
    endings: Sequence[tuple[str, list[EndingRuleListItem]]],
    current: Mapping[str, float],
) -> list[str]:
    """넣기 시작 전에 얼릴 체크포인트 전부를 차례로 검사한다. 넣기는 판정 호출이 없어 스탯이 고정할 때만 바뀌므로, 앞
    체크포인트의 고정 값을 이어받아 다음 체크포인트를 보면 실제 얼릴 때와 같은 결과다. 첫 턴을 넣기 전에 거부해야 유료 넣기를
    체크포인트 직전까지 돌린 뒤 멈추는 일이 없다."""
    errors: list[str] = []
    state = dict(current)
    for checkpoint in sorted(checkpoints):
        entry = doc.get(str(checkpoint))
        if not isinstance(entry, dict):
            errors.append(f"CP{checkpoint} 항목 없음")
            continue
        resolved, found, _ = validate_pinned(entry, defs, endings, state)
        errors += [f"CP{checkpoint} {e}" for e in found]
        state.update(resolved)
    return errors


async def preflight_pinned(
    db: AsyncSession, room_id: uuid.UUID, setup_id: uuid.UUID, doc: Mapping[str, Any], checkpoints: Sequence[int]
) -> None:
    from api.chat.room_stats import load_room_stats

    stat_defs, _, current = await load_room_stats(db, room_id, setup_id)
    defs = [PinnedStatDef(str(d.entity_id), d.name, float(d.min_value), float(d.max_value)) for d in stat_defs]
    errors = validate_sequence(doc, checkpoints, defs, await _ending_rules(db, setup_id), current)
    if errors:
        raise SystemExit("스탯 고정 파일 거부(넣기 전): " + "; ".join(errors))


async def _ending_rules(db: AsyncSession, setup_id: uuid.UUID) -> list[tuple[str, list[EndingRuleListItem]]]:
    from api.chat.turn_judgments import _ending_rule_items
    from api.db.models.story import Ending

    endings = (
        await db.scalars(select(Ending).where(Ending.starting_setup_id == setup_id).order_by(Ending.order))
    ).all()
    return [(e.name, await _ending_rule_items(db, e)) for e in endings]
