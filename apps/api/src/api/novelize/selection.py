"""구간 선택을 읽는 공용 조회 — 선택 라우트와 구성안(요청·실행)이 같이 쓴다. 라우트 모듈에 두지 않는 것은 작업 실행
(`runner.py`)이 라우트 모듈을 import 하면 순환이 되기 때문이다(라우트가 실행을 띄운다). 원문은 읽지 않는다 — 메시지 키만 다룬다."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_window import MessageKey
from api.db.models.novel import (
    NovelChapter,
    NovelEpisodeOutline,
    NovelSourceSection,
    NovelSourceSectionMode,
    NovelSourceSelection,
)

# 이미 화가 된 구간과 겹치면 안 되는 mode. 맥락(context)은 막지 않는다 — 잠금은 이미 쓴 대화를 다시 쓰는 것을 막는 것이고, 앞
# 화와 이어지는 장면을 쓸 때 앞 화의 원문을 참고로 보내는 것은 그 약속을 깨지 않는다. 성공한 원고에 맥락으로 실렸던 구간까지
# 잠글지는 아직 정하지 않았다 — 정하면 이 집합과 `locked_ranges` 만 바뀐다.
LOCK_BLOCKS_MODES: frozenset[NovelSourceSectionMode] = frozenset({"include"})


def overlaps(a: tuple[MessageKey, MessageKey], b: tuple[MessageKey, MessageKey]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def section_key(section: NovelSourceSection) -> tuple[MessageKey, MessageKey]:
    return (
        (section.start_message_created_at, section.start_message_id),
        (section.end_message_created_at, section.end_message_id),
    )


async def latest_approved_selection(db: AsyncSession, novel_id: uuid.UUID) -> NovelSourceSelection | None:
    selection: NovelSourceSelection | None = await db.scalar(
        select(NovelSourceSelection)
        .where(NovelSourceSelection.novel_id == novel_id, NovelSourceSelection.approved_at.is_not(None))
        .order_by(NovelSourceSelection.revision.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return selection


async def selection_sections(db: AsyncSession, selection_id: uuid.UUID) -> list[NovelSourceSection]:
    rows = await db.scalars(
        select(NovelSourceSection)
        .where(NovelSourceSection.selection_id == selection_id)
        .order_by(NovelSourceSection.start_message_created_at, NovelSourceSection.start_message_id)
    )
    return list(rows.all())


def stored_basis_key(basis: dict[str, str]) -> tuple[MessageKey, MessageKey]:
    """장면 구성안에 저장한 장면 근거 하나(메시지 id 와 `created_at` 의 ISO 글자)의 양 끝 키."""
    return (
        (datetime.fromisoformat(basis["start_message_created_at"]), uuid.UUID(basis["start_message_id"])),
        (datetime.fromisoformat(basis["end_message_created_at"]), uuid.UUID(basis["end_message_id"])),
    )


async def locked_ranges(db: AsyncSession, novel_id: uuid.UUID) -> list[tuple[MessageKey, MessageKey]]:
    """이미 화가 된 구간 — 지금 있는 화마다 그 화가 쓴 대화, 키 순, 중복 없이. 화를 지우면 그 구간은 풀린다.

    옛 흐름의 화는 연속 구간 하나를 쓰므로 첫·끝 키 사이 전체가 정확히 그 화가 쓴 대화다. 한 묶음의 화들은 묶음 구간을 함께
    가리켜 같은 구간이 여러 번 나오므로 하나로 줄인다. 구성 흐름 화는 여러 include 구간에 걸칠 수 있어(사이는 맥락이거나 고르지 않은
    대화) 첫·끝 사이 통째가 아니라 그 화가 쓴 장면 구성안의 장면 근거 구간들이다. 그 장면 구성안이 지워졌으면(판매된 소설의 작가 전용
    데이터 정리 뒤) 첫·끝 사이로 읽는다."""
    rows = (
        await db.execute(
            select(
                NovelChapter.start_message_created_at,
                NovelChapter.start_message_id,
                NovelChapter.end_message_created_at,
                NovelChapter.end_message_id,
                NovelChapter.episode_outline_id,
            )
            .where(NovelChapter.novel_id == novel_id)
            .distinct()
        )
    ).all()
    outline_ids = {row[4] for row in rows if row[4] is not None}
    scenes = (
        dict(
            (
                await db.execute(
                    select(NovelEpisodeOutline.id, NovelEpisodeOutline.scenes).where(
                        NovelEpisodeOutline.id.in_(outline_ids)
                    )
                )
            )
            .tuples()
            .all()
        )
        if outline_ids
        else {}
    )
    ranges: set[tuple[MessageKey, MessageKey]] = set()
    for row in rows:
        if row[4] in scenes:
            ranges.update(stored_basis_key(basis) for scene in scenes[row[4]] for basis in scene["basis"])
        else:
            ranges.add(((row[0], row[1]), (row[2], row[3])))
    return sorted(ranges)


def hits_locked(
    sections: list[tuple[NovelSourceSectionMode, MessageKey, MessageKey]], locked: list[tuple[MessageKey, MessageKey]]
) -> bool:
    """잠금이 막는 mode 의 구간 중 이미 화가 된 구간과 겹치는 것이 있는가."""
    return any(
        mode in LOCK_BLOCKS_MODES and any(overlaps((start, end), lock) for lock in locked)
        for mode, start, end in sections
    )
