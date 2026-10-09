"""노벨 공개 테이블의 CHECK 제약과 마지막 묶음 삭제. CHECK 는 `alembic check` 가 비교하지 않아 이 행위 테스트가 유일한
검증이다."""

from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    NovelBatch,
    NovelChapter,
    NovelChapterPublication,
    NovelChapterRevision,
    NovelPublication,
    NovelScreening,
)
from api.novelize.deletion import delete_batch
from factories import NovelTree, _make_novel_tree, _make_user


async def _tree(db_session: AsyncSession) -> NovelTree:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    return await _make_novel_tree(db_session, user.id)


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        pytest.param({"visibility": "hidden"}, "ck_novel_publications_visibility", id="visibility"),
        pytest.param({"moderation_status": "deleted"}, "ck_novel_publications_moderation_status", id="moderation"),
    ],
)
async def test_publication_state_axes_reject_unknown_values(
    db_session: AsyncSession, overrides: dict[str, str], constraint: str
) -> None:
    tree = await _tree(db_session)
    row = NovelPublication(novel_id=tree.novel.id, **{"visibility": "public", **overrides})
    db_session.add(row)
    with pytest.raises(IntegrityError, match=constraint):
        await db_session.flush()


async def test_publication_accepts_both_axes_values(db_session: AsyncSession) -> None:
    """짝 — 위 거부가 값 목록이 아니라 모든 값을 막아서 나는 것이 아님을 본다."""
    tree = await _tree(db_session)
    other = await _make_novel_tree(db_session, tree.novel.user_id)
    db_session.add_all(
        [
            NovelPublication(novel_id=tree.novel.id, visibility="public", moderation_status="restricted"),
            NovelPublication(novel_id=other.novel.id, visibility="withdrawn", moderation_status="normal"),
        ]
    )
    await db_session.flush()


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        pytest.param({"ordinal": 0}, "ck_novel_chapter_publications_ordinal_positive", id="ordinal"),
        pytest.param({"edition": 0}, "ck_novel_chapter_publications_edition_positive", id="edition"),
    ],
)
async def test_chapter_publication_rejects_non_positive_numbers(
    db_session: AsyncSession, overrides: dict[str, int], constraint: str
) -> None:
    tree = await _tree(db_session)
    values: dict[str, Any] = {"ordinal": 1, "edition": 1, **overrides}
    row = NovelChapterPublication(
        chapter_id=tree.chapter.id, novel_id=tree.novel.id, revision_id=tree.first_revision.id, **values
    )
    db_session.add(row)
    with pytest.raises(IntegrityError, match=constraint):
        await db_session.flush()


def _screening(tree: NovelTree, **overrides: Any) -> NovelScreening:
    values: dict[str, Any] = {
        "novel_id": tree.novel.id,
        "user_id": tree.novel.user_id,
        "outcome": "rejected",
        "flagged_parts": ["chapter_body"],
        "model": "gemini-test",
        **overrides,
    }
    return NovelScreening(**values)


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        pytest.param({"outcome": "error"}, "ck_novel_screenings_outcome", id="outcome"),
        pytest.param({"flagged_parts": ["chapter_body", "cover"]}, "ck_novel_screenings_flagged_parts", id="part"),
        pytest.param(
            {"outcome": "passed", "flagged_parts": ["synopsis"]}, "ck_novel_screenings_passed_flags_none", id="passed"
        ),
    ],
)
async def test_screening_rejects_inconsistent_rows(
    db_session: AsyncSession, overrides: dict[str, Any], constraint: str
) -> None:
    tree = await _tree(db_session)
    db_session.add(_screening(tree, **overrides))
    with pytest.raises(IntegrityError, match=constraint):
        await db_session.flush()


async def test_screening_accepts_rejection_with_every_part_and_a_clean_pass(db_session: AsyncSession) -> None:
    tree = await _tree(db_session)
    db_session.add_all(
        [
            _screening(
                tree, flagged_parts=["novel_title", "synopsis", "chapter_title", "author_note", "chapter_body"]
            ),
            _screening(tree, outcome="passed", flagged_parts=[]),
        ]
    )
    await db_session.flush()


async def test_delete_batch_removes_only_that_batchs_publications_and_keeps_the_novel_publication(
    db_session: AsyncSession,
) -> None:
    """마지막 묶음을 지우면 그 화들의 공개본·심사 기록만 사라지고, 앞 묶음 화의 공개본과 소설 공개 상태는 남는다 — 남은
    공개 화가 여전히 1화부터 이어지고, 소설 제목·소개 사본과 운영자 조치가 소설에 붙어 있어야 해서다."""
    tree = await _tree(db_session)
    segment = {
        column: getattr(tree.chapter, column)
        for column in (
            "start_message_id",
            "start_message_created_at",
            "end_message_id",
            "end_message_created_at",
            "assistant_message_count",
            "source_hash",
        )
    }
    last_batch = NovelBatch(novel_id=tree.novel.id, ordinal=2, target_episode_count=1, **segment)
    db_session.add(last_batch)
    await db_session.flush()
    last_chapter = NovelChapter(novel_id=tree.novel.id, ordinal=2, batch_id=last_batch.id, episode_index=0, **segment)
    db_session.add(last_chapter)
    await db_session.flush()
    last_revision = NovelChapterRevision(chapter_id=last_chapter.id, revision_no=1, body="둘째 화", source="generate")
    db_session.add(last_revision)
    await db_session.flush()
    db_session.add_all(
        [
            NovelPublication(novel_id=tree.novel.id, visibility="public"),
            NovelChapterPublication(
                chapter_id=tree.chapter.id, novel_id=tree.novel.id, ordinal=1, revision_id=tree.first_revision.id
            ),
            NovelChapterPublication(
                chapter_id=last_chapter.id, novel_id=tree.novel.id, ordinal=2, revision_id=last_revision.id
            ),
            _screening(tree, chapter_id=tree.chapter.id, outcome="passed", flagged_parts=[]),
            _screening(tree, chapter_id=last_chapter.id),
        ]
    )
    await db_session.flush()

    await delete_batch(db_session, novel_id=tree.novel.id, batch_id=last_batch.id)

    published = await db_session.scalars(
        sa.select(NovelChapterPublication.chapter_id).where(NovelChapterPublication.novel_id == tree.novel.id)
    )
    assert list(published) == [tree.chapter.id]
    screened = await db_session.scalars(
        sa.select(NovelScreening.chapter_id).where(NovelScreening.novel_id == tree.novel.id)
    )
    assert list(screened) == [tree.chapter.id]
    assert await db_session.get(NovelPublication, tree.novel.id, populate_existing=True) is not None
