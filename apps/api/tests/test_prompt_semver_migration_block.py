"""문안 마이그레이션이 복사해 쓰는 판 매기기 블록과 어드민 게시 규칙(`api.admin.prompt_semver`)이 같은 판을 매기는지.

마이그레이션은 앱 코드를 import 하지 않아 같은 규칙이 두 곳에 있다. 이 동치는 **가장 최근에 복사한 블록 하나**만 견준다
(`_LATEST_BLOCK`). 블록은 그 리비전 시점의 규칙으로 얼어 있어야 하므로(옛 리비전을 빈 DB 에서 다시 돌린 결과가 바뀌면 안
된다), 앱 규칙이 바뀐 뒤 옛 블록과의 동치를 요구하면 얼린 블록을 고치거나 테스트를 지우는 길밖에 없다. 새 문안 마이그레이션이
블록을 복사하면 `_LATEST_BLOCK` 을 그 리비전으로 옮기고, 옛 리비전의 테스트는 자기 시드가 매긴 판 행을 고정값으로 단언한다.

입력은 리비전 시드가 아니라 아래 공용 표본이다 — 시드는 보통 "채널 하나 새로 들어옴"이나 "하나 바뀜·기본 patch" 갈래만 지나
블록 사본의 비교 칸 누락·단계 리셋 누락·단계 검사 누락을 놓친다. 표본은 바뀜·새·빠짐·빠졌다 다시 들어옴·라벨만 바뀜·내용
그대로·major/minor/patch 섞임·단계 오류·시작판·기준판에 판 행 없는 섹션을 지난다. 고친 본문은 모두 합성 문장이다."""

import importlib.util
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.prompt_semver import SemverLevel, SemverLevelError, assign_semver

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"
# 판 매기기 블록을 가장 최근에 복사한 리비전. 새 문안 마이그레이션이 블록을 복사하면 이 값을 그 리비전으로 옮긴다.
_LATEST_BLOCK = "d0051f733bb7"
_CHAIN = ("story", "semver-block-test")

Row = tuple[str, str, str, str, bool, int]  # (scope, slot, variant, body, conditional, order)


@dataclass(frozen=True)
class _Step:
    channels: dict[str, list[Row]]
    labels: tuple[str, str, str, str] = ("사용자", "진행자", "서술자", "캐릭터")
    levels: dict[str, SemverLevel] = field(default_factory=dict)
    # 판을 매긴 뒤 이 세트에서 지울 섹션 판 행 — 측정 도구가 게시 세트의 섹션을 제자리에서 덮어 판 행 없는 내용이 생긴 상태.
    unnumbered: tuple[str, ...] = ()


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_block_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_A = [("both", "intro", "", "합성 가 하나.", False, 1), ("both", "rule", "", "합성 가 둘.", True, 2)]
_B = [("story", "turn", "", "합성 나 하나.", False, 1)]
_C = [("both", "note", "", "합성 다 하나.", False, 1)]
_RENAMED = ("합성", "진행자", "서술자", "캐릭터")


def _edit(rows: list[Row], index: int = 0, **change: object) -> list[Row]:
    fields = ("scope", "slot", "variant", "body", "conditional", "order")
    edited = list(rows)
    values = dict(zip(fields, edited[index], strict=True))
    values.update(change)
    edited[index] = tuple(values[name] for name in fields)  # type: ignore[assignment]
    return edited


_A_BODY = _edit(_A, body="합성 가 하나 고침.")
_A_ORDER = _edit(_A_BODY, order=5)
_A_CONDITIONAL = _edit(_A_ORDER, 1, conditional=False)

_SAMPLES: dict[str, list[_Step]] = {
    # 한 단계에 한 칸만 바꾼다 — 앞 단계 위에 고쳐 쌓아야 순서만·조건만 바뀐 갈래가 실제로 생긴다.
    "field-by-field": [
        _Step({"a": _A, "b": _B}),
        _Step({"a": _A_BODY, "b": _B}),
        _Step({"a": _A_ORDER, "b": _B}, levels={"a": "minor"}),
        _Step({"a": _A_CONDITIONAL, "b": _B}, levels={"a": "major"}),
        _Step({"a": _A_CONDITIONAL, "b": _B}, labels=_RENAMED),
        _Step({"a": _A_CONDITIONAL, "b": _B}, labels=_RENAMED),
    ],
    "removed-and-returning": [
        _Step({"a": _A, "b": _B}),
        _Step({"a": _A, "b": _edit(_B, variant="alt")}, levels={"b": "minor"}),
        _Step({"a": _A}, levels={"b": "minor"}),
        _Step({"a": _A, "b": _edit(_B, body="합성 나 돌아옴.")}),
        _Step({"a": _A, "b": _edit(_B, body="합성 나 돌아옴 고침."), "c": _C}, levels={"b": "major"}),
    ],
    "mixed-levels": [
        _Step({"a": _A, "b": _B, "c": _C}),
        _Step(
            {
                "a": _edit(_A, scope="story"),
                "b": _edit(_B, slot="turn2"),
                "c": [*_C, ("both", "note", "v", "합성", False, 1)],
            },
            levels={"a": "minor", "b": "major"},
        ),
        _Step({"a": _edit(_A, scope="story"), "b": _B, "c": _C}, levels={"c": "minor"}),
    ],
    "level-for-unchanged": [
        _Step({"a": _A, "b": _B}),
        _Step({"a": _edit(_A, body="합성 가 고침."), "b": _B}, levels={"b": "patch"}),
    ],
    "start-ignores-present-levels": [
        _Step({"a": _A, "b": _B}, levels={"a": "major"}),
        _Step({"a": _A, "b": _B}),
    ],
    "start-rejects-unknown-levels": [
        _Step({"a": _A}, levels={"nowhere": "patch"}),
    ],
    "unnumbered-base-section": [
        _Step({"a": _A, "b": _B}),
        _Step({"a": _A, "b": _edit(_B, body="합성 나 고침.")}, levels={"b": "minor"}, unnumbered=("b",)),
        _Step({"a": _A, "b": _edit(_B, body="합성 나 고침.")}),
    ],
}


async def _insert_step(db: AsyncSession, step: _Step, index: int) -> uuid.UUID:
    set_id = uuid.uuid4()
    user, story_assistant, story_example, character_assistant = step.labels
    await db.execute(
        sa.text(
            "INSERT INTO prompt_sets (id, version, status, lane, model, user_label, story_assistant_label,"
            " story_example_label, character_assistant_label, note, published_at)"
            " VALUES (:id, :version, 'published', :lane, :model, :user, :sa, :se, :ca, '', :published_at)"
        ),
        {
            "id": set_id,
            "version": str(80000 + index),
            "lane": _CHAIN[0],
            "model": _CHAIN[1],
            "user": user,
            "sa": story_assistant,
            "se": story_example,
            "ca": character_assistant,
            "published_at": datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index),
        },
    )
    for channel, rows in step.channels.items():
        for scope, slot, variant, body, conditional, order in rows:
            await db.execute(
                sa.text(
                    "INSERT INTO prompt_sections"
                    ' (id, prompt_set_id, channel, scope, slot, variant, body, conditional, "order") VALUES'
                    " (:id, :set_id, :channel, :scope, :slot, :variant, :body, :conditional, :order)"
                ),
                {
                    "id": uuid.uuid4(),
                    "set_id": set_id,
                    "channel": channel,
                    "scope": scope,
                    "slot": slot,
                    "variant": variant,
                    "body": body,
                    "conditional": conditional,
                    "order": order,
                },
            )
    return set_id


async def _run_sample(db: AsyncSession, steps: list[_Step], *, migration: ModuleType | None) -> list[object]:
    """표본을 한 구현으로 돌려 그 체인에 매긴 판을 세트 순번으로 펼쳐 돌려준다(행 id·세트 id 는 실행마다 달라 순번으로 바꾼다).
    단계 오류가 나면 그 순번에서 멈추고 오류 표시를 남긴다. 쓴 것은 모두 되감는다."""
    outcome: list[object] = []
    savepoint = await db.begin_nested()
    try:
        order: dict[uuid.UUID, int] = {}
        for index, step in enumerate(steps):
            set_id = await _insert_step(db, step, index)
            order[set_id] = index
            try:
                async with db.begin_nested():
                    if migration is None:
                        await assign_semver(db, set_id=set_id, levels=step.levels)
                    else:
                        connection = await db.connection()

                        def _assign(sync: Connection, set_id: uuid.UUID = set_id, step: _Step = step) -> None:
                            migration._assign_semver(sync, set_id=set_id, levels=step.levels)

                        await connection.run_sync(_assign)
                    if step.unnumbered:
                        await db.execute(
                            sa.text(
                                "DELETE FROM prompt_section_semvers WHERE prompt_set_id = :id AND channel = ANY(:channels)"
                            ),
                            {"id": set_id, "channels": list(step.unnumbered)},
                        )
            except (SemverLevelError, RuntimeError):
                outcome.append(("level-error", index))
                break
        chains = await db.execute(
            sa.text(
                "SELECT prompt_set_id, major, minor, patch, level, base_set_id FROM prompt_set_semvers"
                " WHERE lane = :lane AND model = :model"
            ),
            {"lane": _CHAIN[0], "model": _CHAIN[1]},
        )
        for set_id, major, minor, patch, level, base_set_id in chains:
            outcome.append(("chain", order[set_id], (major, minor, patch), level, order.get(base_set_id)))
        sections = await db.execute(
            sa.text(
                "SELECT prompt_set_id, channel, major, minor, patch, level FROM prompt_section_semvers"
                " WHERE prompt_set_id = ANY(:ids)"
            ),
            {"ids": list(order)},
        )
        for set_id, channel, major, minor, patch, level in sections:
            outcome.append(("section", order[set_id], channel, (major, minor, patch), level))
    finally:
        await savepoint.rollback()
    return sorted(outcome, key=repr)


async def _assert_migration_semver_matches_app(db: AsyncSession, module: ModuleType) -> None:
    for name, steps in _SAMPLES.items():
        app = await _run_sample(db, steps, migration=None)
        block = await _run_sample(db, steps, migration=module)
        assert block == app, name


async def test_the_latest_copied_block_numbers_like_the_admin_publish(db_session: AsyncSession) -> None:
    """가장 최근에 복사한 판 매기기 블록이 공용 표본마다 어드민 게시 규칙과 같은 판 행을 매긴다. 깨지는 시나리오: 블록 사본이
    순서·조건 비교를 빠뜨리거나 major 상승 때 뒷자리를 되돌리지 않아, 마이그레이션이 넣은 세트의 판이 같은 내용을 어드민이
    게시했을 때와 달라진다."""
    await _assert_migration_semver_matches_app(db_session, _load(_LATEST_BLOCK))


async def test_the_samples_reach_every_branch_of_the_rule(db_session: AsyncSession) -> None:
    """표본이 규칙의 갈래를 실제로 지난다 — 앱 규칙으로 돌린 결과에 리셋·다시 들어온 섹션·단계 오류·시작판이 보인다. 깨지는
    시나리오: 표본이 한 갈래만 지나 두 구현이 그 갈래에서만 같아도 동치 테스트가 초록이 된다."""
    field_by_field = await _run_sample(db_session, _SAMPLES["field-by-field"], migration=None)
    assert ("chain", 3, (2, 0, 0), "major", 2) in field_by_field
    assert ("chain", 5, (2, 0, 2), "patch", 4) in field_by_field
    assert ("section", 4, "speaker_labels", (1, 0, 1), "patch") in field_by_field

    returning = await _run_sample(db_session, _SAMPLES["removed-and-returning"], migration=None)
    assert ("chain", 2, (1, 2, 0), "minor", 1) in returning
    assert ("section", 3, "b", (1, 1, 1), "patch") in returning
    assert ("section", 4, "c", (1, 0, 0), "patch") in returning

    unnumbered = await _run_sample(db_session, _SAMPLES["unnumbered-base-section"], migration=None)
    assert ("chain", 2, (1, 1, 1), "patch", 1) in unnumbered
    assert ("section", 2, "b", (1, 0, 1), "patch") in unnumbered

    assert ("level-error", 1) in await _run_sample(db_session, _SAMPLES["level-for-unchanged"], migration=None)
    started = await _run_sample(db_session, _SAMPLES["start-ignores-present-levels"], migration=None)
    assert ("chain", 0, (1, 0, 0), None, None) in started
    assert ("level-error", 0) in await _run_sample(db_session, _SAMPLES["start-rejects-unknown-levels"], migration=None)
