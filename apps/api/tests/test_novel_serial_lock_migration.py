"""연재권 잠금·공개 행 심사 마이그레이션(`6fbf1e9a65b8`)의 백필·CHECK·기존 행 검증.

세션 스코프 스키마(`_migrated_schema`)가 이미 `upgrade head` 를 했다. 백필 함수는 테스트마다 롤백되는 `db_session`
커넥션에 직접 부르고, 리비전의 downgrade·upgrade 를 실제로 돌려야 하는 테스트는 `ddl_engine` 의 롤백되는 트랜잭션
안에서 돌린다(세션 스코프 스키마는 그대로 남는다). `alembic check` 는 CHECK 제약을 비교하지 않으므로 이 파일의 테스트가
그 유일한 신호다.

테스트 DB 에는 마이그레이션이 심은 약관 게시본이 있고 그 시행 시각은 스키마를 만든 순간이다. 그래서 이 파일의 공개
시각과 약관 게시본은 모두 2001년에 두어, 심어 둔 게시본이 약관 판 선택에 끼어들지 않게 한다."""

import importlib.util
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from api.db.models import LegalDocument, Novel, NovelPublication
from factories import _make_user

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("6fbf1e9a65b8")

# 첫 약관 게시본이 시행되는 시각. 이보다 이른 공개에는 효력 있던 약관이 없다.
_T_TERMS_1 = datetime(2001, 1, 1, tzinfo=UTC)
# 둘째 약관 게시본이 시행되는 시각. 게시(공지)는 한 달 앞이다.
_T_TERMS_2 = datetime(2001, 6, 1, tzinfo=UTC)

_LockRow = tuple[datetime | None, str | None, str | None, uuid.UUID | None, str | None]
_UNLOCKED: _LockRow = (None, None, None, None, None)


async def _run(connection: AsyncConnection, step: Callable[[], None]) -> None:
    """리비전의 upgrade·downgrade 를 이 커넥션에서 alembic `op` 가 쓰이도록 돌린다."""

    def run(sync_connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(sync_connection)):
            step()

    await connection.run_sync(run)


async def _backfill(db_session: AsyncSession) -> int:
    connection = await db_session.connection()
    locked: int = await connection.run_sync(_M.backfill_serial_locks)
    return locked


async def _user_id(db_session: AsyncSession) -> uuid.UUID:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    return user.id


async def _novel(db_session: AsyncSession, user_id: uuid.UUID, **lock: Any) -> uuid.UUID:
    novel = Novel(user_id=user_id, content_id=uuid.uuid4(), content_type="story", content_title="원작", **lock)
    db_session.add(novel)
    await db_session.flush()
    return novel.id


async def _publication(db_session: AsyncSession, novel_id: uuid.UUID, **values: Any) -> None:
    db_session.add(NovelPublication(novel_id=novel_id, **{"visibility": "public", **values}))
    await db_session.flush()


async def _terms(
    db_session: AsyncSession, *, effective_at: datetime, published_at: datetime, status: str = "published"
) -> str:
    """약관 게시본(또는 철회본) 하나를 넣고 그 버전을 돌려준다. 버전은 심어 둔 판과 겹치지 않게 매번 새로 만든다."""
    version = f"test-{uuid.uuid4().hex[:12]}"
    db_session.add(
        LegalDocument(
            kind="terms",
            version=version,
            body_markdown="약관",
            status=status,
            published_at=published_at,
            effective_at=effective_at,
        )
    )
    await db_session.flush()
    return version


async def _locks(db_session: AsyncSession, novel_ids: list[uuid.UUID]) -> dict[uuid.UUID, _LockRow]:
    rows = await db_session.execute(
        sa.select(
            Novel.id,
            Novel.serial_locked_at,
            Novel.serial_lock_source,
            Novel.serial_lock_permission,
            Novel.serial_lock_content_version_id,
            Novel.serial_lock_terms_version,
        ).where(Novel.id.in_(novel_ids))
    )
    return {
        novel_id: (locked_at, source, permission, version_id, terms_version)
        for novel_id, locked_at, source, permission, version_id, terms_version in rows.tuples()
    }


async def test_backfill_locks_every_novel_that_was_ever_public(db_session: AsyncSession) -> None:
    """공개 중인 소설과 공개했다 거둔 소설을 그 첫 공개 시각으로 잠그고, 출처는 백필·허락과 원작 버전은 알 수
    없음(NULL)·약관 판은 그 시각에 효력 있던 판이다. 공개 행이 없는 소설과 심사 대기·반려 행만 있는 소설은 잠그지 않는다.
    깨지는 시나리오: 공개했다 거둔 소설이 잠기지 않아 원작자가 허락을 거두면 다음 화가 막히거나, 독자에게 보인 적 없는 대기
    소설이 잠겨 허락 검사를 영영 건너뛴다."""
    user_id = await _user_id(db_session)
    terms = await _terms(db_session, effective_at=_T_TERMS_1, published_at=_T_TERMS_1)
    first_published_at = _T_TERMS_1 + timedelta(days=10)
    public = await _novel(db_session, user_id)
    await _publication(db_session, public, first_published_at=first_published_at)
    withdrawn = await _novel(db_session, user_id)
    await _publication(db_session, withdrawn, visibility="withdrawn", first_published_at=first_published_at)
    never_published = await _novel(db_session, user_id)
    pending = await _novel(db_session, user_id)
    await _publication(db_session, pending, visibility="withdrawn", review_status="pending")
    rejected = await _novel(db_session, user_id)
    await _publication(db_session, rejected, visibility="withdrawn", review_status="rejected", review_reason="사유")

    await _backfill(db_session)

    assert await _locks(db_session, [public, withdrawn, never_published, pending, rejected]) == {
        public: (first_published_at, "backfill", None, None, terms),
        withdrawn: (first_published_at, "backfill", None, None, terms),
        never_published: _UNLOCKED,
        pending: _UNLOCKED,
        rejected: _UNLOCKED,
    }


async def test_backfill_run_again_changes_no_lock(db_session: AsyncSession) -> None:
    """두 번째 실행은 아무 소설도 고치지 않고, 첫 공개가 이미 남긴 잠금도 덮지 않는다. 옛 이미지가 다 내려간 뒤와 심사를
    켜기 직전에 같은 문장을 한 번 더 돌리는 절차가 이 성질에 기댄다. 깨지는 시나리오: 재실행이 첫 공개의 허락·약관 사본을
    지우거나 잠긴 시각을 공개 행의 시각으로 되돌린다."""
    user_id = await _user_id(db_session)
    backfilled = await _novel(db_session, user_id)
    await _publication(db_session, backfilled, first_published_at=_T_TERMS_1)
    version_id = uuid.uuid4()
    locked_at_first_publish = await _novel(
        db_session,
        user_id,
        serial_locked_at=_T_TERMS_2,
        serial_lock_source="first_publish",
        serial_lock_permission="public",
        serial_lock_content_version_id=version_id,
        serial_lock_terms_version="first-publish-terms",
    )
    await _publication(db_session, locked_at_first_publish, first_published_at=_T_TERMS_1)
    await _backfill(db_session)
    first = await _locks(db_session, [backfilled, locked_at_first_publish])

    assert await _backfill(db_session) == 0

    assert await _locks(db_session, [backfilled, locked_at_first_publish]) == first
    assert first[locked_at_first_publish] == (
        _T_TERMS_2,
        "first_publish",
        "public",
        version_id,
        "first-publish-terms",
    )


@pytest.mark.parametrize(
    ("first_published_at", "expected"),
    [
        pytest.param(_T_TERMS_1 - timedelta(microseconds=1), None, id="before-any-terms"),
        pytest.param(_T_TERMS_1, "first", id="first-terms-effective-instant"),
        pytest.param(_T_TERMS_2 - timedelta(microseconds=1), "first", id="just-before-second-terms"),
        pytest.param(_T_TERMS_2, "second", id="second-terms-effective-instant"),
    ],
)
async def test_backfill_picks_terms_in_effect_at_first_publication(
    db_session: AsyncSession, first_published_at: datetime, expected: str | None
) -> None:
    """약관 판은 첫 공개 시각에 시행 중이던 게시본이다 — 시행 시각이 첫 공개 시각과 같으면 그 판이고, 게시(공지)만 되고
    아직 시행 전인 판·시행 전에 철회한 판은 고르지 않는다. 시행 시각이 같은 판이 둘이면 나중에 게시한 판이다. 깨지는
    시나리오: 공지만 된 새 약관이나 철회한 판이 잠금 근거로 남아, 작가가 동의한 적 없는 조건으로 연재권이 기록된다."""
    user_id = await _user_id(db_session)
    first = await _terms(db_session, effective_at=_T_TERMS_1, published_at=_T_TERMS_1 - timedelta(days=30))
    # 같은 시행 시각의 더 이른 게시본 — 정렬의 둘째 키(게시 시각)가 이 판을 밀어낸다.
    await _terms(db_session, effective_at=_T_TERMS_1, published_at=_T_TERMS_1 - timedelta(days=60))
    # 둘째 판 앞에 시행되기로 했다가 철회한 판.
    await _terms(
        db_session,
        effective_at=_T_TERMS_1 + timedelta(days=1),
        published_at=_T_TERMS_1,
        status="withdrawn",
    )
    second = await _terms(db_session, effective_at=_T_TERMS_2, published_at=_T_TERMS_2 - timedelta(days=30))
    novel_id = await _novel(db_session, user_id)
    await _publication(db_session, novel_id, first_published_at=first_published_at)

    await _backfill(db_session)

    versions = {"first": first, "second": second, None: None}
    assert (await _locks(db_session, [novel_id]))[novel_id] == (
        first_published_at,
        "backfill",
        None,
        None,
        versions[expected],
    )


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        pytest.param(
            {"serial_lock_permission": "unknown"}, "ck_novels_serial_lock_permission", id="unknown-permission"
        ),
        pytest.param(
            {"serial_lock_permission": "PUBLIC"}, "ck_novels_serial_lock_permission", id="uppercase-permission"
        ),
        pytest.param(
            {"serial_locked_at": _T_TERMS_1, "serial_lock_source": "first_chapter"},
            "ck_novels_serial_lock_source",
            id="writing-lock-source",
        ),
        pytest.param(
            {"serial_locked_at": _T_TERMS_1, "serial_lock_source": "BACKFILL"},
            "ck_novels_serial_lock_source",
            id="uppercase-source",
        ),
        pytest.param({"serial_locked_at": _T_TERMS_1}, "ck_novels_serial_lock_complete", id="time-without-source"),
        pytest.param({"serial_lock_source": "backfill"}, "ck_novels_serial_lock_complete", id="source-without-time"),
    ],
)
async def test_serial_lock_rejects_out_of_range_or_half_written_values(
    db_session: AsyncSession, values: dict[str, Any], constraint: str
) -> None:
    """허락 사본과 출처는 정해진 값만, 잠긴 시각과 출처는 함께 있거나 함께 없다. 깨지는 시나리오: 출처 없는 잠금이 생겨
    알 수 없는 잠금과 첫 공개 잠금을 가를 수 없거나, 집필권 잠금의 출처 값이 연재권 잠금에 섞인다."""
    novel_id = await _novel(db_session, await _user_id(db_session))

    with pytest.raises(IntegrityError, match=constraint):
        await db_session.execute(sa.update(Novel).where(Novel.id == novel_id).values(**values))


async def test_serial_lock_accepts_both_sources_and_unknown_permission(db_session: AsyncSession) -> None:
    """위 CHECK 들이 정상 모양을 막지 않는다 — 사본을 다 채운 첫 공개 잠금, 허락·약관을 알 수 없는 백필 잠금, 원작 행이
    사라져 허락 사본이 빈 첫 공개 잠금. 깨지는 시나리오: 너무 좁은 CHECK 가 첫 공개 전체를 실패시킨다."""
    user_id = await _user_id(db_session)
    locks: list[dict[str, Any]] = [
        {
            "serial_lock_source": "first_publish",
            "serial_lock_permission": "forbidden",
            "serial_lock_content_version_id": uuid.uuid4(),
            "serial_lock_terms_version": "terms",
        },
        {"serial_lock_source": "backfill"},
        {"serial_lock_source": "first_publish"},
    ]
    for lock in locks:
        await _novel(db_session, user_id, serial_locked_at=_T_TERMS_1, **lock)


_REJECTED: dict[str, Any] = {"visibility": "withdrawn", "review_status": "rejected", "review_reason": "사유"}


@pytest.mark.parametrize(
    ("start", "values", "constraint"),
    [
        pytest.param({}, {"review_status": "approve"}, "ck_novel_publications_review_status", id="unknown-status"),
        pytest.param({}, {"review_status": "APPROVED"}, "ck_novel_publications_review_status", id="uppercase-status"),
        pytest.param(
            {"visibility": "withdrawn"},
            {"review_status": "rejected"},
            "ck_novel_publications_review_reason",
            id="rejected-without-reason",
        ),
        pytest.param(
            _REJECTED, {"review_reason": None}, "ck_novel_publications_review_reason", id="rejected-reason-cleared"
        ),
        pytest.param(
            {}, {"review_status": "pending"}, "ck_novel_publications_review_hidden", id="public-row-set-pending"
        ),
        pytest.param(
            _REJECTED,
            {"visibility": "public"},
            "ck_novel_publications_review_hidden",
            id="rejected-row-reopened-alone",
        ),
    ],
)
async def test_publication_review_rejects_bad_status_missing_reason_or_visible_unapproved(
    db_session: AsyncSession, start: dict[str, Any], values: dict[str, Any], constraint: str
) -> None:
    """심사 상태는 정해진 값만, 반려 행에는 사유가 있고, 대기·반려 행은 공개 범위가 `withdrawn` 이다. 마지막 경우의 "공개
    범위만 바꾸는 UPDATE" 는 심사 칸을 모르는 옛 코드의 다시 열기와 같은 모양이다. 깨지는 시나리오: 승인 전 글이 독자에게
    나가거나, 작가가 이유를 모르는 반려가 남는다."""
    novel_id = await _novel(db_session, await _user_id(db_session))
    await _publication(db_session, novel_id, **start)

    with pytest.raises(IntegrityError, match=constraint):
        await db_session.execute(
            sa.update(NovelPublication).where(NovelPublication.novel_id == novel_id).values(**values)
        )


async def test_publication_review_accepts_every_valid_shape(db_session: AsyncSession) -> None:
    """위 CHECK 들이 정상 모양을 막지 않는다 — 심사 없는 공개·거둠, 대기, 사유 있는 반려, 승인된 공개·거둠, 그리고 반려
    행의 공개 범위와 심사 칸을 한 UPDATE 로 함께 바꾸는 재공개. 깨지는 시나리오: 너무 좁은 CHECK 가 승인이나 거두기를
    실패시킨다."""
    user_id = await _user_id(db_session)
    shapes: list[dict[str, Any]] = [
        {"visibility": "public"},
        {"visibility": "withdrawn"},
        {"visibility": "withdrawn", "review_status": "pending"},
        _REJECTED,
        {"visibility": "public", "review_status": "approved", "reviewed_at": _T_TERMS_1},
        {"visibility": "withdrawn", "review_status": "approved", "reviewed_at": _T_TERMS_1},
    ]
    for shape in shapes:
        await _publication(db_session, await _novel(db_session, user_id), **shape)
    reopened = await _novel(db_session, user_id)
    await _publication(db_session, reopened, **_REJECTED)

    await db_session.execute(
        sa.update(NovelPublication)
        .where(NovelPublication.novel_id == reopened)
        .values(visibility="public", review_status=None, review_reason=None)
    )


async def test_upgrade_leaves_existing_rows_unreviewed_and_locks_them(ddl_engine: AsyncEngine) -> None:
    """리비전을 실제로 내린 뒤 옛 스키마에 공개 행을 넣고 다시 올린다. 이미 있던 공개 행의 심사 칸은 모두 NULL(심사 없이
    공개된 행)이라 독자 판정이 그대로이고, upgrade 가 백필까지 마쳐 그 소설이 잠긴다. 깨지는 시나리오: 칸 추가가 기존 행에
    심사 값을 채워 공개 중인 소설이 사라지거나, upgrade 만으로는 잠금이 채워지지 않는다."""
    async with ddl_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await _run(connection, _M.downgrade)
            session = AsyncSession(bind=connection)
            author = _make_user()
            session.add(author)
            await session.flush()
            novel_id = uuid.uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO novels (id, user_id, content_id, content_type, content_title)"
                    " VALUES (:id, :user_id, :content_id, 'story', '원작')"
                ),
                {"id": novel_id, "user_id": author.id, "content_id": uuid.uuid4()},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO novel_publications (novel_id, visibility, first_published_at)"
                    " VALUES (:novel_id, 'public', :at)"
                ),
                {"novel_id": novel_id, "at": _T_TERMS_1},
            )

            await _run(connection, _M.upgrade)
            review = (
                await connection.execute(
                    sa.text(
                        "SELECT review_status, review_reason, reviewed_at FROM novel_publications WHERE novel_id = :id"
                    ),
                    {"id": novel_id},
                )
            ).one()
            lock = (
                await connection.execute(
                    sa.text("SELECT serial_locked_at, serial_lock_source FROM novels WHERE id = :id"),
                    {"id": novel_id},
                )
            ).one()
        finally:
            await transaction.rollback()

    assert tuple(review) == (None, None, None)
    assert tuple(lock) == (_T_TERMS_1, "backfill")
