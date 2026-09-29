"""`scripts/backfill_chat_notation.py` — 운영에 이미 들어간 시드 작품의 문안을 칸 단위
compare-and-set 으로 바꾸는 일회성 스크립트.

옛 상태는 이렇게 재현한다: 현재 시드 JSON 을 실제 시드 경로로 넣고(그래야 스냅샷의 행 id 가
시드가 만드는 id 와 같다는 것까지 검사된다), 스냅샷이 적은 대상 칸만 옛 값으로 되돌린다.
"""

import json
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import backfill_chat_notation as backfill
import seed_dev
from api.db.base import Base
from api.db.models.auth import User
from api.db.models.character import CharacterVersionDetail
from api.db.models.chat import ChatMessage
from api.db.models.content import (
    Content,
    ContentType,
    ContentVersion,
    ContentVisibility,
    ModerationStatus,
)
from api.db.models.story import Ending, KeywordNote, StartingSetup, StatDef, StoryVersionDetail
from seed_content import images
from seed_content.ids import SEED_AUTHOR_USER_ID
from seed_content.upsert import story_draft_version_id, story_version_id

ADMIN_EDIT = "어드민이 고친 값"


@pytest.fixture(autouse=True)
def _no_image_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """이미지 디렉터리는 gitignore 라 CI 에는 없다 — 목업 폴백 경로로 고정한다."""
    monkeypatch.setattr(images, "IMAGES_DIR", tmp_path / "images")


@pytest.fixture
def targets() -> list[backfill.Target]:
    return backfill.load_targets()


async def _seed_current(db_session: AsyncSession) -> None:
    """현재 시드(새 표기)를 실제 시드 경로로 넣고, `seed_dev.py` 의 미아도 같은 id 로 만든다."""
    now = datetime.now(UTC)
    db_session.add(
        User(
            id=SEED_AUTHOR_USER_ID,
            email=seed_dev.SEED_AUTHOR_EMAIL,
            nickname="시드 작가",
            birth_date=date(1995, 1, 1),
            terms_agreed_at=now,
            privacy_agreed_at=now,
        )
    )
    await db_session.flush()
    await seed_dev.seed_content_files(db_session)

    db_session.add(
        Content(
            id=seed_dev.CONTENT_ID,
            type=ContentType.CHARACTER,
            creator_user_id=SEED_AUTHOR_USER_ID,
            genre_id=seed_dev.GENRE_ROMANCE,
            hashtags=[],
            visibility=ContentVisibility.PUBLIC,
            moderation_status=ModerationStatus.NORMAL,
        )
    )
    await db_session.flush()
    db_session.add(
        ContentVersion(
            id=seed_dev.VERSION_ID,
            content_id=seed_dev.CONTENT_ID,
            version_number=1,
            published_at=now,
            detail_description="로컬 개발용 샘플 캐릭터입니다.",
        )
    )
    await db_session.flush()
    db_session.add(
        CharacterVersionDetail(
            content_version_id=seed_dev.VERSION_ID,
            name="미아",
            one_liner="불 꺼진 방",
            intro="*조용히 곁에 앉으며* 아직 안 잤구나. 오늘 하루는 어땠어? 천천히 말해줘, 다 들어줄게.",
            example_dialogues=[],
            character_prompt="너는 미아다.",
        )
    )
    await db_session.flush()


async def _row(db_session: AsyncSession, target: backfill.Target) -> Any:
    if target.table == backfill.STORY_TABLE:
        return await db_session.get(StoryVersionDetail, target.version_id)
    if target.table == backfill.CHARACTER_TABLE:
        return await db_session.get(CharacterVersionDetail, target.version_id)
    return (
        await db_session.scalars(
            select(StartingSetup).where(
                StartingSetup.content_version_id == target.version_id,
                StartingSetup.entity_id == target.entity_id,
            )
        )
    ).one()


async def _set(db_session: AsyncSession, target: backfill.Target, value: Any) -> None:
    setattr(await _row(db_session, target), target.field, value)
    await db_session.flush()


async def _values(db_session: AsyncSession, targets: list[backfill.Target]) -> list[Any]:
    """DB 에서 다시 읽은 대상 칸 값들(세션에 남은 객체 상태가 아니라)."""
    db_session.expire_all()
    return [getattr(await _row(db_session, target), target.field) for target in targets]


async def _seed_old(db_session: AsyncSession, targets: list[backfill.Target]) -> None:
    """변경 직전 시드 상태 — 대상 칸마다 스냅샷의 첫 옛 값(마이그레이션 파싱 결과 등)."""
    await _seed_current(db_session)
    for target in targets:
        await _set(db_session, target, target.old[0])


async def _untouched(db_session: AsyncSession) -> list[Any]:
    """스크립트가 건드리면 안 되는 모든 것 — 대상 테이블의 다른 칸, 발행·공개·심사 상태, 자식 행 수."""
    db_session.expire_all()
    owned = {
        backfill.STORY_TABLE: backfill.ALLOWED_FIELDS[backfill.STORY_TABLE],
        backfill.SETUP_TABLE: backfill.ALLOWED_FIELDS[backfill.SETUP_TABLE],
        backfill.CHARACTER_TABLE: backfill.ALLOWED_FIELDS[backfill.CHARACTER_TABLE],
    }
    state: list[Any] = []
    models: list[type[Base]] = [
        StoryVersionDetail,
        StartingSetup,
        CharacterVersionDetail,
        ContentVersion,
        Content,
    ]
    for model in models:
        columns = [
            column.key
            for column in model.__table__.columns
            if column.key not in owned.get(model.__tablename__, frozenset())
        ]
        rows = (await db_session.scalars(select(model))).all()
        state.append(sorted(repr([getattr(row, column) for column in columns]) for row in rows))
    for model in (StatDef, Ending, KeywordNote, ChatMessage):
        state.append(await db_session.scalar(select(func.count()).select_from(model)))
    return state


def _statuses(planned: list[backfill.Planned]) -> set[str]:
    return {item.status for item in planned}


async def test_every_snapshot_row_is_where_the_seed_puts_it(
    db_session: AsyncSession, s3_bucket: None, targets: list[backfill.Target]
) -> None:
    """현재 시드를 그대로 넣은 DB 에서는 모든 칸이 "이미 적용"이다 — 스냅샷의 행 id 가 시드가
    만드는 id 와 같고(행 없음 0), 스냅샷의 새 값이 현재 시드 JSON 이 넣는 값과 같다."""
    await _seed_current(db_session)

    planned = await backfill.plan(db_session, targets)

    assert _statuses(planned) == {backfill.DONE}
    assert {t.table for t in targets} == set(backfill.ALLOWED_FIELDS)
    assert {t.version_id for t in targets} >= {
        story_version_id("daily-lastorder"),
        story_draft_version_id("daily-lastorder"),
        seed_dev.VERSION_ID,
    }


async def test_dry_run_reports_every_field_as_pending_and_changes_nothing(
    db_session: AsyncSession, s3_bucket: None, targets: list[backfill.Target]
) -> None:
    await _seed_old(db_session, targets)
    before = await _values(db_session, targets)
    untouched = await _untouched(db_session)

    planned = await backfill.plan(db_session, targets)

    assert _statuses(planned) == {backfill.APPLY}
    assert await _values(db_session, targets) == before
    assert await _untouched(db_session) == untouched


async def test_apply_writes_new_values_only_into_target_fields(
    db_session: AsyncSession, s3_bucket: None, targets: list[backfill.Target], tmp_path: Path
) -> None:
    await _seed_old(db_session, targets)
    untouched = await _untouched(db_session)

    await backfill.apply(db_session, targets, tmp_path / "backup.json")

    assert await _values(db_session, targets) == [target.new for target in targets]
    assert await _untouched(db_session) == untouched


async def test_apply_leaves_an_admin_edited_field_alone_and_reports_it(
    db_session: AsyncSession, s3_bucket: None, targets: list[backfill.Target], tmp_path: Path
) -> None:
    await _seed_old(db_session, targets)
    edited = next(t for t in targets if t.field == "setting_text" and "published" in t.label)
    await _set(db_session, edited, ADMIN_EDIT)

    planned = await backfill.apply(db_session, targets, tmp_path / "backup.json")

    [report] = [item for item in planned if item.status == backfill.MISMATCH]
    assert report.target == edited and report.current == ADMIN_EDIT
    values = await _values(db_session, targets)
    for target, value in zip(targets, values, strict=True):
        assert value == (ADMIN_EDIT if target == edited else target.new)


async def test_apply_accepts_an_empty_development_examples_as_old(
    db_session: AsyncSession, s3_bucket: None, targets: list[backfill.Target], tmp_path: Path
) -> None:
    """마이그레이션 뒤 옛 시드 JSON 으로 시드를 다시 돌렸다면 전개 예시가 빈 목록이다."""
    await _seed_old(db_session, targets)
    examples = [t for t in targets if t.field == "development_examples"]
    assert len(examples) == 60
    for target in examples:
        await _set(db_session, target, [])

    planned = await backfill.apply(db_session, targets, tmp_path / "backup.json")

    assert _statuses(planned) == {backfill.APPLY}
    assert await _values(db_session, examples) == [target.new for target in examples]


async def test_apply_accepts_the_first_pair_list_of_the_seed_json_as_old(
    db_session: AsyncSession, s3_bucket: None, targets: list[backfill.Target], tmp_path: Path
) -> None:
    """comedy-demonintern 만 마이그레이션 파싱 결과와 시드 JSON 의 첫 쌍 목록이 다르다."""
    await _seed_old(db_session, targets)
    [first, *_] = [
        t for t in targets if t.field == "development_examples" and t.label.startswith("story:comedy-demonintern:")
    ]
    assert len(first.old) == 3 and first.old[1] != first.old[0]
    await _set(db_session, first, first.old[1])

    planned = await backfill.apply(db_session, targets, tmp_path / "backup.json")

    assert _statuses(planned) == {backfill.APPLY}
    assert await _values(db_session, [first]) == [first.new]


async def test_rerunning_apply_changes_nothing(
    db_session: AsyncSession, s3_bucket: None, targets: list[backfill.Target], tmp_path: Path
) -> None:
    await _seed_old(db_session, targets)
    await backfill.apply(db_session, targets, tmp_path / "first.json")
    after_first = await _values(db_session, targets)
    untouched = await _untouched(db_session)

    planned = await backfill.apply(db_session, targets, tmp_path / "second.json")

    assert _statuses(planned) == {backfill.DONE}
    assert await _values(db_session, targets) == after_first
    assert await _untouched(db_session) == untouched


async def test_apply_backs_up_current_values_and_never_overwrites_a_backup(
    db_session: AsyncSession, s3_bucket: None, targets: list[backfill.Target], tmp_path: Path
) -> None:
    await _seed_old(db_session, targets)
    backup_path = tmp_path / "backup.json"
    backup_path.write_text("앞선 적용의 백업", encoding="utf-8")

    with pytest.raises(FileExistsError):
        await backfill.apply(db_session, targets, backup_path)

    assert await _values(db_session, targets) == [target.old[0] for target in targets]
    backup_path.unlink()
    await backfill.apply(db_session, targets, backup_path)
    entries = json.loads(backup_path.read_text(encoding="utf-8"))["entries"]
    assert [entry["before"] for entry in entries] == [target.old[0] for target in targets]
    assert [entry["after"] for entry in entries] == [target.new for target in targets]


async def test_rollback_restores_old_values_except_fields_changed_since(
    db_session: AsyncSession, s3_bucket: None, targets: list[backfill.Target], tmp_path: Path
) -> None:
    await _seed_old(db_session, targets)
    untouched = await _untouched(db_session)
    backup_path = tmp_path / "backup.json"
    await backfill.apply(db_session, targets, backup_path)
    edited_after = next(t for t in targets if t.field == "opening_message")
    await _set(db_session, edited_after, ADMIN_EDIT)

    dry = await backfill.plan_rollback(db_session, backup_path)
    assert await _values(db_session, [edited_after]) == [ADMIN_EDIT]
    planned = await backfill.rollback(db_session, backup_path)

    assert [item.status for item in planned] == [item.status for item in dry]
    [report] = [item for item in planned if item.status == backfill.MISMATCH]
    assert report.entry["label"] == edited_after.label and report.current == ADMIN_EDIT
    values = await _values(db_session, targets)
    for target, value in zip(targets, values, strict=True):
        assert value == (ADMIN_EDIT if target == edited_after else target.old[0])
    assert await _untouched(db_session) == untouched

    again = await backfill.rollback(db_session, backup_path)
    assert {item.status for item in again} == {backfill.ALREADY_REVERTED, backfill.MISMATCH}


async def test_rollback_ignores_fields_the_apply_did_not_change(
    db_session: AsyncSession, s3_bucket: None, targets: list[backfill.Target], tmp_path: Path
) -> None:
    """이미 새 값이던 칸은 적용이 바꾼 게 아니다 — 되돌리기가 그 칸을 옛 값으로 만들면 안 된다."""
    await _seed_current(db_session)
    backup_path = tmp_path / "backup.json"
    await backfill.apply(db_session, targets, backup_path)

    assert await backfill.rollback(db_session, backup_path) == []
    assert await _values(db_session, targets) == [target.new for target in targets]


def _forge_other_environment(entries: list[dict[str, Any]]) -> None:
    entries[0]["version_id"] = str(uuid.uuid4())


def _forge_before(entries: list[dict[str, Any]]) -> None:
    entries[-1]["before"] = "스냅샷의 옛 값이 아닌 값"


def _forge_after(entries: list[dict[str, Any]]) -> None:
    entries[len(entries) // 2]["after"] = "스냅샷의 새 값이 아닌 값"


@pytest.mark.parametrize(
    "forge",
    [
        pytest.param(_forge_other_environment, id="snapshot-has-no-such-row"),
        pytest.param(_forge_before, id="before-is-not-an-old-value"),
        pytest.param(_forge_after, id="after-is-not-the-new-value"),
    ],
)
async def test_rollback_refuses_a_backup_that_does_not_match_the_snapshot_before_writing(
    db_session: AsyncSession,
    s3_bucket: None,
    targets: list[backfill.Target],
    tmp_path: Path,
    forge: Any,
) -> None:
    """다른 환경에서 뜬 백업이나 손댄 백업으로 되돌리면 스냅샷 밖의 값이 운영 칸에 들어간다 —
    어긋난 항목이 하나라도 있으면 한 칸도 쓰기 전에 멈춰야 한다(앞 항목만 되돌린 채 멈추면 안 된다)."""
    await _seed_old(db_session, targets)
    backup_path = tmp_path / "backup.json"
    await backfill.apply(db_session, targets, backup_path)
    backup = json.loads(backup_path.read_text(encoding="utf-8"))
    forge(backup["entries"])
    backup_path.write_text(json.dumps(backup, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(backfill.BackupMismatchError):
        await backfill.plan_rollback(db_session, backup_path)
    with pytest.raises(backfill.BackupMismatchError):
        await backfill.rollback(db_session, backup_path)

    assert await _values(db_session, targets) == [target.new for target in targets]


def test_snapshot_only_names_fields_the_chat_reads(targets: list[backfill.Target]) -> None:
    for target in targets:
        assert target.field in backfill.ALLOWED_FIELDS[target.table]
        assert target.new not in target.old
    assert len({(t.table, t.version_id, t.entity_id, t.field) for t in targets}) == len(targets)


def test_load_targets_refuses_a_field_outside_the_allowed_set(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.json"
    path.write_text(
        json.dumps(
            {
                "stories": [
                    {
                        "slug": "x",
                        "version_ids": [str(uuid.uuid4())],
                        "fields": {"prologue": {"old": ["a"], "new": "b"}},
                        "starting_setups": [],
                    }
                ],
                "characters": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="prologue"):
        backfill.load_targets(path)
