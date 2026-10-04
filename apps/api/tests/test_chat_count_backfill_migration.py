"""대화 상대 기록 표를 만들고 대화수를 채우는 마이그레이션 `ade2c1031e12` 의 백필 검증.

마이그레이션 자체는 다시 돌리지 않는다. 세션 스코프 스키마(`_migrated_schema`)가 이미 `upgrade head` 를 했으므로 백필
문장 둘을 테스트마다 롤백되는 `db_session` 커넥션에서 그대로 실행한다. 방은 생성자로 직접 넣는다 — API 로 만들면
라이브 증가가 먼저 기록을 채워 백필이 할 일이 없어진다."""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import ChatRoom, Content, ContentChatParticipant
from factories import _get_genre, _make_published_character, _make_user

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("ade2c1031e12")


async def test_backfill_counts_distinct_non_author_users_per_content(db_session: AsyncSession) -> None:
    """한 사람이 방을 여러 개 만들었어도 한 번, 작가 본인 방은 0번 센다. 방이 없는 작품은 0 으로 맞춘다.

    빨개지는 조건: 작가 제외 조건을 빼면 첫 작품이 2, 중복 제거(GROUP BY)를 빼면 기록 삽입이 PK 충돌로 실패한다.
    방 없는 작품을 건드리지 않는 형태로 바꾸면 마지막 작품이 미리 넣은 7 로 남는다."""
    author, reader, other = _make_user(), _make_user(), _make_user()
    db_session.add_all([author, reader, other])
    await db_session.flush()
    genre = await _get_genre(db_session)
    played, own_only, untouched = [
        await _make_published_character(db_session, creator_user_id=author.id, genre_id=genre.id) for _ in range(3)
    ]
    untouched.chat_count = 7
    earlier = datetime.now(UTC) - timedelta(days=3)
    for user_id, content, created_at in [
        (reader.id, played, earlier),
        (reader.id, played, earlier + timedelta(days=1)),
        (other.id, played, earlier + timedelta(days=2)),
        (author.id, played, earlier),
        (author.id, own_only, earlier),
    ]:
        db_session.add(
            ChatRoom(
                user_id=user_id,
                content_id=content.id,
                content_version_id=content.current_published_version_id,
                created_at=created_at,
            )
        )
    await db_session.flush()

    await db_session.execute(sa.text(_M.BACKFILL_PARTICIPANTS_SQL))
    await db_session.execute(sa.text(_M.BACKFILL_CHAT_COUNT_SQL))

    count_rows = await db_session.execute(
        sa.select(Content.id, Content.chat_count).where(Content.id.in_([played.id, own_only.id, untouched.id]))
    )
    counts = {content_id: chat_count for content_id, chat_count in count_rows.tuples()}
    assert counts == {played.id: 2, own_only.id: 0, untouched.id: 0}

    rows = (
        await db_session.execute(
            sa.select(ContentChatParticipant.content_id, ContentChatParticipant.user_id, ContentChatParticipant.created_at)
        )
    ).tuples()
    assert {(content_id, user_id): created_at for content_id, user_id, created_at in rows} == {
        (played.id, reader.id): earlier,
        (played.id, other.id): earlier + timedelta(days=2),
    }

