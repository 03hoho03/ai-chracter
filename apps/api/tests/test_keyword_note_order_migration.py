"""키워드북 노트에 순서·옵션 컬럼을 더하는 마이그레이션 `5cf390a62b62` 의 검증.

마이그레이션 자체는 다시 돌리지 않는다. 세션 스코프 스키마(`_migrated_schema`)가 이미 `upgrade head` 를 했으므로
backfill 문장(`BACKFILL_ORDER_SQL`)을 테스트마다 롤백되는 `db_session` 커넥션에서 그대로 실행한다."""

import importlib.util
import uuid
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Genre,
    KeywordNote,
    ModerationStatus,
)
from factories import _make_user

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("5cf390a62b62")


async def _two_story_versions(db_session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = (await db_session.execute(sa.select(Genre).limit(1))).scalar_one()
    content = Content(
        type=ContentType.STORY,
        creator_user_id=user.id,
        genre_id=genre.id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()
    first = ContentVersion(content_id=content.id, detail_description="초안")
    second = ContentVersion(content_id=content.id, detail_description="발행본")
    db_session.add_all([first, second])
    await db_session.flush()
    return first.id, second.id


async def _get_order(db_session: AsyncSession, version_id: uuid.UUID) -> list[uuid.UUID]:
    """빌더 GET 이 노트를 읽는 것과 같은 조회 — ORDER BY 가 없다."""
    rows = await db_session.execute(
        sa.text("SELECT entity_id FROM keyword_notes WHERE content_version_id = :v"), {"v": version_id}
    )
    return [row[0] for row in rows]


async def _order_column(db_session: AsyncSession, version_id: uuid.UUID) -> list[tuple[int, uuid.UUID]]:
    rows = await db_session.execute(
        sa.text('SELECT "order", entity_id FROM keyword_notes WHERE content_version_id = :v ORDER BY "order"'),
        {"v": version_id},
    )
    return [(row[0], row[1]) for row in rows]


async def test_backfill_numbers_each_version_in_the_order_the_builder_get_returns(db_session: AsyncSession) -> None:
    """id(uuid) 순서로 매기면 작가가 보던 순서가 뒤섞인다 — 물리 id 를 삽입 순서와 반대로 골라 넣어, 힙 순서가
    아닌 기준으로 매기는 backfill 이 이 테스트에서 깨지게 한다. 두 버전을 번갈아 넣어 버전마다 0 부터 매기는지도 본다."""
    # 다른 테스트가 남긴 죽은 튜플이 빈자리를 만들면 새 행이 삽입 순서와 다른 힙 자리에 들어갈 수 있다. 트랜잭션 안의
    # TRUNCATE 는 빈 새 파일로 시작하고 테스트 끝 롤백으로 되돌아간다.
    await db_session.execute(sa.text("TRUNCATE keyword_notes"))
    first, second = await _two_story_versions(db_session)

    inserted: dict[uuid.UUID, list[uuid.UUID]] = {first: [], second: []}
    for i in range(12):
        version = first if i % 2 == 0 else second
        entity_id = uuid.uuid4()
        # 뒤에 넣을수록 작은 id — id 순서가 삽입 순서와 정확히 반대가 된다.
        physical_id = uuid.UUID(int=(100 - i) << 64)
        db_session.add(
            KeywordNote(
                id=physical_id,
                entity_id=entity_id,
                content_version_id=version,
                info_text=f"노트 {i}",
                trigger_keywords=[f"키워드{i}"],
            )
        )
        await db_session.flush()
        inserted[version].append(entity_id)

    for version in (first, second):
        assert len(inserted[version]) == 6
        # 전제: 지금 GET 은 삽입 순서를 돌려준다(빈 힙에 차례로 들어갔다).
        assert await _get_order(db_session, version) == inserted[version]

    await db_session.execute(sa.text(_M.BACKFILL_ORDER_SQL))

    for version in (first, second):
        assert await _order_column(db_session, version) == list(enumerate(inserted[version]))


async def test_insert_without_new_columns_gets_defaults(db_session: AsyncSession) -> None:
    """API 를 이 컬럼을 모르는 이전 이미지로 되돌리면 그 코드는 새 다섯 컬럼 없이 INSERT 한다. 그때 NOT NULL 위반
    500 이 아니라 기본값으로 들어가야 한다. `alembic check` 는 `server_default` 를 비교하지 않아 이 테스트가 유일한 신호다."""
    first, _ = await _two_story_versions(db_session)
    note_id = uuid.uuid4()
    await db_session.execute(
        sa.text(
            "INSERT INTO keyword_notes (id, entity_id, content_version_id, info_text, trigger_keywords) "
            "VALUES (:id, :entity_id, :version, '정보', ARRAY['키워드'])"
        ),
        {"id": note_id, "entity_id": uuid.uuid4(), "version": first},
    )
    row = (
        await db_session.execute(
            sa.text(
                'SELECT name, "order", exclude_keywords, sticky_turns, always_on FROM keyword_notes WHERE id = :id'
            ),
            {"id": note_id},
        )
    ).one()
    assert tuple(row) == ("", 0, [], 0, False)
