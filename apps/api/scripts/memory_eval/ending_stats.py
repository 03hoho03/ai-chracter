"""엔딩 층 스탯 맞추기 — 작업 DB 의 방 스탯을 지정 값으로 맞춰, 드라이버가 그 상태에서 이어 쳐 엔딩 판정 줄을 만들게 한다.

체크포인트 스탯 고정(`memory_eval.pinned_stats`)은 고정 뒤 스탯이 규칙 있는 엔딩에 닿으면 거부한다 — 그 고정은 프로브를 엔딩 전
상태에서 시작하려는 것이라서다. 엔딩 층은 반대로 문턱 위에 일부러 세워 "엔딩 판정이 열리는 턴"을 표본에 넣으려는 것이라 엔딩
문턱 검사를 하지 않고, 닿는 엔딩 이름을 알리기만 한다. 없는 스탯·숫자 아님·범위 밖은 같은 규칙으로 거부한다.

LLM 은 부르지 않고 앱의 스탯 쓰기 함수로 방 스탯 행만 쓴다. 측정 작업 DB(이름 `lm_eval_` 로 시작)에서만 돈다 — 드라이버가 재는
서버가 그 DB 를 써야 하고, 다른 DB 의 방 스탯을 바꾸면 사람이 쓰는 방의 상태가 바뀐다. 쓰고 나면 드라이버의 누적값이 DB 와
어긋나므로 다음 턴 전에 드라이버 `--rebase` 로 기준을 다시 잡는다."""

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.ending_rules import evaluate_rule_list
from api.chat.schemas import EndingRuleListItem

from memory_eval.pinned_stats import PinnedStatDef, _ending_rules, validate_pinned


def validate_ending_stats(
    values: Mapping[str, Any],
    defs: Sequence[PinnedStatDef],
    endings: Sequence[tuple[str, list[EndingRuleListItem]]],
    current: Mapping[str, float],
) -> tuple[dict[str, float], list[str], list[str]]:
    """(스탯 entity_id → 값, 거부 사유, 맞춘 뒤 규칙이 채워지는 엔딩 이름). 엔딩 문턱은 거부 사유가 아니다."""
    resolved, errors, _ = validate_pinned(values, defs, [], current)
    after = {**current, **resolved}
    reached = [name for name, rules in endings if rules and evaluate_rule_list(rules, after)]
    return resolved, errors, reached


async def apply_ending_stats(db: AsyncSession, room_id: uuid.UUID, values: Mapping[str, Any]) -> dict[str, Any]:
    """검사를 통과하면 방 스탯 행에 쓰고 커밋한다. 시작 설정이 없는 방(캐릭터)은 스탯이 없어 거부한다."""
    from api.chat.room_stats import load_room_stats
    from api.chat.turn_store import _write_room_stat

    from memory_eval.runtime import load_room

    ctx = await load_room(db, room_id, lane="story")
    assert ctx.setup is not None
    stat_defs, stat_rows, current = await load_room_stats(db, room_id, ctx.setup.id)
    defs = [PinnedStatDef(str(d.entity_id), d.name, float(d.min_value), float(d.max_value)) for d in stat_defs]
    resolved, errors, reached = validate_ending_stats(values, defs, await _ending_rules(db, ctx.setup.id), current)
    if errors:
        raise SystemExit("엔딩 층 스탯 거부: " + "; ".join(errors))
    for stat_id, value in resolved.items():
        _write_room_stat(db, room_id, stat_rows, stat_id, value)
    await db.commit()
    names = {str(d.entity_id): d.name for d in stat_defs}
    return {
        "set": {names[stat_id]: value for stat_id, value in resolved.items()},
        "endingsReachedByRules": reached,
        "next": "드라이버 --rebase 로 누적 기준을 다시 잡은 뒤 이어 친다",
    }
