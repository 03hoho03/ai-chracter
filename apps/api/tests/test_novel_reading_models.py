"""노벨 독자 쪽 테이블(독자 읽은 자리·좋아요·홈 노벨 자리)과 공개 상태 수 칸의 CHECK·복합 PK. 둘 다 `alembic check` 가
비교하지 않아 이 행위 테스트가 유일한 검증이다."""

from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import HomeNovelCuration, NovelLike, NovelPublication, NovelReaderPosition
from factories import NovelTree, _make_novel_tree, _make_user


async def _tree(db_session: AsyncSession) -> NovelTree:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    return await _make_novel_tree(db_session, user.id)


def _position(tree: NovelTree, **overrides: Any) -> NovelReaderPosition:
    values: dict[str, Any] = {"paragraph_index": 0, "paragraph_count": 3, "edition": 1, **overrides}
    return NovelReaderPosition(user_id=tree.novel.user_id, chapter_id=tree.chapter.id, novel_id=tree.novel.id, **values)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"paragraph_index": -1}, id="negative-index"),
        pytest.param({"paragraph_index": 3}, id="index-past-count"),
        pytest.param({"edition": 0}, id="edition"),
    ],
)
async def test_reader_position_rejects_out_of_range_numbers(db_session: AsyncSession, overrides: dict[str, int]) -> None:
    tree = await _tree(db_session)
    db_session.add(_position(tree, **overrides))
    with pytest.raises(IntegrityError, match="ck_novel_reader_positions_range"):
        await db_session.flush()


async def test_reader_position_is_one_row_per_reader_and_chapter(db_session: AsyncSession) -> None:
    """같은 사람·같은 화는 한 행이다(저장은 덮어쓰기). 마지막 칸의 범위 끝(문단 수 - 1)은 받는다."""
    tree = await _tree(db_session)
    db_session.add(_position(tree, paragraph_index=2))
    await db_session.flush()
    db_session.add(_position(tree))
    with pytest.raises(IntegrityError, match="novel_reader_positions_pkey"):
        await db_session.flush()


async def test_like_is_one_row_per_member_and_novel(db_session: AsyncSession) -> None:
    tree = await _tree(db_session)
    db_session.add(NovelLike(user_id=tree.novel.user_id, novel_id=tree.novel.id))
    await db_session.flush()
    db_session.add(NovelLike(user_id=tree.novel.user_id, novel_id=tree.novel.id))
    with pytest.raises(IntegrityError, match="novel_likes_pkey"):
        await db_session.flush()


@pytest.mark.parametrize("position", [pytest.param(0, id="zero"), pytest.param(11, id="past-last-slot")])
async def test_home_novel_slot_must_be_one_of_the_slots(db_session: AsyncSession, position: int) -> None:
    tree = await _tree(db_session)
    db_session.add(HomeNovelCuration(position=position, novel_id=tree.novel.id))
    with pytest.raises(IntegrityError, match="ck_home_novel_curations_position_range"):
        await db_session.flush()


async def test_home_novel_slots_accept_first_and_last(db_session: AsyncSession) -> None:
    """짝 — 위 거부가 모든 자리를 막아서 나는 것이 아님을 본다."""
    first = await _tree(db_session)
    last = await _make_novel_tree(db_session, first.novel.user_id)
    db_session.add_all(
        [HomeNovelCuration(position=1, novel_id=first.novel.id), HomeNovelCuration(position=10, novel_id=last.novel.id)]
    )
    await db_session.flush()


@pytest.mark.parametrize("column", ["like_count", "view_count"])
async def test_publication_counts_cannot_go_negative(db_session: AsyncSession, column: str) -> None:
    tree = await _tree(db_session)
    db_session.add(NovelPublication(novel_id=tree.novel.id, visibility="public", **{column: -1}))
    with pytest.raises(IntegrityError, match="ck_novel_publications_counts_nonnegative"):
        await db_session.flush()
