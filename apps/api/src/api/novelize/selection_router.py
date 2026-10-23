"""소설 구간 선택 라우트 — 소설로 옮길 대화 구간을 고르는 조회·초안 저장·승인. 구성 흐름 스위치가 꺼져 있으면 모두 404 다.

선택은 리비전으로 쌓는다. 승인한 리비전은 고치지 않는다 — 구성안이 그 리비전을 근거로 삼으므로, 바꾸려면 그 위에 새 초안을 저장해
다시 승인한다. 초안은 가장 최근 리비전 하나만 남는다(새 초안을 저장하면 앞 초안은 지운다). 동시 저장은 기준 리비전 비교와
`(novel_id, revision)` 유니크가 막는다.

검증은 모두 여기서 한다 — DB 는 구간 겹침을 막지 않는다. 구간은 이 방의 메시지 양 끝으로 가리키고(아니면 422), 키 순으로 서로
겹치지 않으며, 고정 끝 안에 있어야 한다. 이미 화가 된 구간은 include 로 다시 고를 수 없다. 원문은 관문(`source.py`)으로만 읽는다.

무과금이고 모델을 부르지 않는다. 모든 응답에 `Cache-Control: no-store` 를 붙인다 — 스위치가 꺼진 동안의 404 를 브라우저가 붙잡아
두지 않게(`no_store.py`)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.memory_window import MessageKey
from api.core.config import settings
from api.db.models.novel import (
    Novel,
    NovelChapter,
    NovelSourceSection,
    NovelSourceSectionMode,
    NovelSourceSelection,
)
from api.db.session import get_db_session
from api.legal.dependencies import require_legal_consent
from api.novel_public.no_store import NoStoreRoute
from api.novelize.access import require_novelize_access
from api.novelize.router import _novel_error, _owned_novel_dependency
from api.novelize.schemas import (
    NovelSourceRange,
    NovelSourceSectionView,
    NovelSourceSelectionApproveRequest,
    NovelSourceSelectionSaveRequest,
    NovelSourceSelectionState,
    NovelSourceSelectionView,
)
from api.novelize.source import (
    RangeShape,
    SourceRange,
    first_message_key_after,
    last_message_key,
    range_shape,
    room_message_keys,
)

# 이미 화가 된 구간과 겹치면 안 되는 mode. 맥락(context)은 막지 않는다 — 잠금은 이미 쓴 대화를 다시 쓰는 것을 막는 것이고, 앞
# 화와 이어지는 장면을 쓸 때 앞 화의 원문을 참고로 보내는 것은 그 약속을 깨지 않는다. 성공한 원고에 맥락으로 실렸던 구간까지
# 잠글지는 아직 정하지 않았다 — 정하면 이 집합과 `_locked_ranges` 만 바뀐다.
_LOCK_BLOCKS_MODES: frozenset[NovelSourceSectionMode] = frozenset({"include"})


async def _require_outline_flow_enabled() -> None:
    if not settings.novelize_outline_flow_enabled:
        raise _novel_error(status.HTTP_404_NOT_FOUND, "NOVEL_OUTLINE_FLOW_DISABLED")


selection_router = APIRouter(
    prefix="/novels",
    tags=["novels"],
    route_class=NoStoreRoute,
    dependencies=[Depends(require_novelize_access), Depends(_require_outline_flow_enabled)],
)


@dataclass(frozen=True)
class _Section:
    """키로 풀어 검증을 마친 구간 하나와 지금 원문의 모양."""

    mode: NovelSourceSectionMode
    start: MessageKey
    end: MessageKey
    shape: RangeShape


def _room_id(novel: Novel) -> uuid.UUID:
    if novel.chat_room_id is None:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_ROOM_GONE")
    return novel.chat_room_id


def _overlaps(a: tuple[MessageKey, MessageKey], b: tuple[MessageKey, MessageKey]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


async def _latest_selection(db: AsyncSession, novel_id: uuid.UUID) -> NovelSourceSelection | None:
    selection: NovelSourceSelection | None = await db.scalar(
        select(NovelSourceSelection)
        .where(NovelSourceSelection.novel_id == novel_id)
        .order_by(NovelSourceSelection.revision.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return selection


async def _latest_approved(db: AsyncSession, novel_id: uuid.UUID) -> NovelSourceSelection | None:
    selection: NovelSourceSelection | None = await db.scalar(
        select(NovelSourceSelection)
        .where(NovelSourceSelection.novel_id == novel_id, NovelSourceSelection.approved_at.is_not(None))
        .order_by(NovelSourceSelection.revision.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return selection


async def _sections_of(db: AsyncSession, selection_id: uuid.UUID) -> list[NovelSourceSection]:
    rows = await db.scalars(
        select(NovelSourceSection)
        .where(NovelSourceSection.selection_id == selection_id)
        .order_by(NovelSourceSection.start_message_created_at, NovelSourceSection.start_message_id)
    )
    return list(rows.all())


async def _locked_ranges(db: AsyncSession, novel_id: uuid.UUID) -> list[tuple[MessageKey, MessageKey]]:
    """이미 화가 된 구간 — 지금 있는 화마다 그 화의 첫·끝 키 사이 전체, 키 순, 중복 없이. 화를 지우면 그 구간은 풀린다.

    옛 흐름의 화는 연속 구간 하나를 쓰므로 첫·끝 키 사이 전체가 정확히 그 화가 쓴 대화다. 한 묶음의 화들은 묶음 구간을 함께
    가리켜 같은 구간이 여러 번 나오므로 하나로 줄인다."""
    rows = await db.execute(
        select(
            NovelChapter.start_message_created_at,
            NovelChapter.start_message_id,
            NovelChapter.end_message_created_at,
            NovelChapter.end_message_id,
        )
        .where(NovelChapter.novel_id == novel_id)
        .distinct()
    )
    return sorted(((row[0], row[1]), (row[2], row[3])) for row in rows.all())


def _section_key(section: NovelSourceSection) -> tuple[MessageKey, MessageKey]:
    return (
        (section.start_message_created_at, section.start_message_id),
        (section.end_message_created_at, section.end_message_id),
    )


def _require_unlocked(
    sections: list[tuple[NovelSourceSectionMode, MessageKey, MessageKey]], locked: list[tuple[MessageKey, MessageKey]]
) -> None:
    for mode, start, end in sections:
        if mode in _LOCK_BLOCKS_MODES and any(_overlaps((start, end), lock) for lock in locked):
            raise _novel_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_SOURCE_SECTION_LOCKED")


async def _checked_sections(
    db: AsyncSession,
    novel: Novel,
    room_id: uuid.UUID,
    payload: NovelSourceSelectionSaveRequest,
    room_end: MessageKey,
) -> list[_Section]:
    """요청 구간을 키로 풀고 검증한 뒤 지금 원문의 모양을 붙인다. 검증 순서: 이 방의 메시지인가(422 `NOVEL_SOURCE_MESSAGE_NOT_FOUND`)
    → 구간마다 시작 ≤ 끝이고 앞 구간 끝 < 다음 구간 시작인가(422 `NOVEL_SOURCE_SECTION_INVALID`) → 고정 끝 안인가(422
    `NOVEL_SOURCE_SECTION_OUT_OF_RANGE`) → 이미 쓴 구간을 include 하지 않는가(422 `NOVEL_SOURCE_SECTION_LOCKED`) → include 에 모델
    응답이 하나라도 있는가(422 `NOVEL_SOURCE_SELECTION_EMPTY`)."""
    wanted = {s.start_message_id for s in payload.sections} | {s.end_message_id for s in payload.sections}
    keys = await room_message_keys(db, room_id, wanted)
    if len(keys) != len(wanted):
        raise _novel_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_SOURCE_MESSAGE_NOT_FOUND")
    resolved = [(s.mode, keys[s.start_message_id], keys[s.end_message_id]) for s in payload.sections]
    previous_end: MessageKey | None = None
    for _, start, end in resolved:
        if start > end or (previous_end is not None and start <= previous_end):
            raise _novel_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_SOURCE_SECTION_INVALID")
        previous_end = end
    if previous_end is not None and previous_end > room_end:
        raise _novel_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_SOURCE_SECTION_OUT_OF_RANGE")
    _require_unlocked(resolved, await _locked_ranges(db, novel.id))
    sections = [
        _Section(mode, start, end, await range_shape(db, room_id, SourceRange(start, end)))
        for mode, start, end in resolved
    ]
    if not any(s.mode == "include" and s.shape.assistant_message_count > 0 for s in sections):
        raise _novel_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_SOURCE_SELECTION_EMPTY")
    return sections


async def _view(db: AsyncSession, room_id: uuid.UUID, selection: NovelSourceSelection) -> NovelSourceSelectionView:
    sections = []
    for row in await _sections_of(db, selection.id):
        start, end = _section_key(row)
        shape = await range_shape(db, room_id, SourceRange(start, end))
        sections.append(
            NovelSourceSectionView(
                start_message_id=row.start_message_id,
                end_message_id=row.end_message_id,
                mode=row.mode,
                assistant_message_count=row.assistant_message_count,
                source_changed=shape.source_hash != row.source_hash,
            )
        )
    return NovelSourceSelectionView(
        revision=selection.revision,
        approved_at=selection.approved_at,
        room_end_message_id=selection.room_end_message_id,
        sections=sections,
    )


async def _proposal(
    db: AsyncSession, room_id: uuid.UUID, locked: list[tuple[MessageKey, MessageKey]], room_end: MessageKey | None
) -> NovelSourceSelectionView:
    """선택이 없을 때의 기본 제안 — 이미 쓴 구간 중 가장 늦은 끝 바로 뒤(화가 없으면 방의 첫 메시지)부터 방 끝까지 include 한 구간.
    그 앞의 쓰지 않은 대화는 고르지 않은 나머지(exclude)다. 제안할 대화가 없으면 구간이 비어 있다."""
    written_end = max((end for _, end in locked), default=None)
    start = await first_message_key_after(db, room_id, written_end)
    sections = []
    if start is not None and room_end is not None:
        shape = await range_shape(db, room_id, SourceRange(start, room_end))
        sections.append(
            NovelSourceSectionView(
                start_message_id=start[1],
                end_message_id=room_end[1],
                mode="include",
                assistant_message_count=shape.assistant_message_count,
                source_changed=False,
            )
        )
    return NovelSourceSelectionView(
        revision=None,
        approved_at=None,
        room_end_message_id=None if room_end is None else room_end[1],
        sections=sections,
    )


async def _state(db: AsyncSession, novel: Novel, room_id: uuid.UUID) -> NovelSourceSelectionState:
    latest = await _latest_selection(db, novel.id)
    approved = await _latest_approved(db, novel.id)
    locked = await _locked_ranges(db, novel.id)
    room_end = await last_message_key(db, room_id)
    draft = latest if latest is not None and latest.approved_at is None else None
    has_new = latest is not None and (
        await first_message_key_after(
            db, room_id, (latest.room_end_message_created_at, latest.room_end_message_id)
        )
        is not None
    )
    return NovelSourceSelectionState(
        approved=None if approved is None else await _view(db, room_id, approved),
        draft=None if draft is None else await _view(db, room_id, draft),
        proposal=await _proposal(db, room_id, locked, room_end) if latest is None else None,
        locked_ranges=[
            NovelSourceRange(start_message_id=start[1], end_message_id=end[1]) for start, end in locked
        ],
        room_end_message_id=None if room_end is None else room_end[1],
        has_new_messages=has_new,
    )


@selection_router.get("/{novel_id}/source-selection")
async def get_source_selection(
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelSourceSelectionState:
    """구간 선택 화면의 상태 — 승인본·초안·기본 제안·이미 쓴 구간·지금 방 끝. 방이 지워진 소설은 409 `NOVEL_ROOM_GONE`."""
    return await _state(db, novel, _room_id(novel))


@selection_router.put("/{novel_id}/source-selection/draft", dependencies=[Depends(require_legal_consent)])
async def save_source_selection_draft(
    payload: NovelSourceSelectionSaveRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelSourceSelectionState:
    """선택을 새 리비전의 초안으로 저장한다(앞 초안은 지우고 승인본은 그대로 둔다). 기준 리비전이 지금 최신이 아니면(다른 탭이
    먼저 저장함) 409 `NOVEL_SOURCE_SELECTION_CONFLICT`. 구간 검증 실패는 `_checked_sections` 의 422 들이고, 그때는 아무것도 바뀌지
    않는다."""
    room_id = _room_id(novel)
    latest = await _latest_selection(db, novel.id)
    if (None if latest is None else latest.revision) != payload.base_revision:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_SOURCE_SELECTION_CONFLICT")
    if latest is None or payload.extend_to_room_end:
        found = await room_message_keys(db, room_id, {payload.room_end_message_id})
        if payload.room_end_message_id not in found:
            raise _novel_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "NOVEL_SOURCE_MESSAGE_NOT_FOUND")
        room_end = found[payload.room_end_message_id]
    elif payload.room_end_message_id != latest.room_end_message_id:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_SOURCE_SELECTION_CONFLICT")
    else:
        room_end = (latest.room_end_message_created_at, latest.room_end_message_id)
    sections = await _checked_sections(db, novel, room_id, payload, room_end)
    await db.execute(
        delete(NovelSourceSelection).where(
            NovelSourceSelection.novel_id == novel.id, NovelSourceSelection.approved_at.is_(None)
        )
    )
    selection = NovelSourceSelection(
        novel_id=novel.id,
        revision=(0 if latest is None else latest.revision) + 1,
        room_end_message_id=room_end[1],
        room_end_message_created_at=room_end[0],
    )
    db.add(selection)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_SOURCE_SELECTION_CONFLICT") from None
    db.add_all(
        NovelSourceSection(
            selection_id=selection.id,
            mode=section.mode,
            start_message_id=section.start[1],
            start_message_created_at=section.start[0],
            end_message_id=section.end[1],
            end_message_created_at=section.end[0],
            assistant_message_count=section.shape.assistant_message_count,
            source_hash=section.shape.source_hash,
        )
        for section in sections
    )
    await db.commit()
    return await _state(db, novel, room_id)


@selection_router.post("/{novel_id}/source-selection/approve", dependencies=[Depends(require_legal_consent)])
async def approve_source_selection(
    payload: NovelSourceSelectionApproveRequest,
    novel: Novel = Depends(_owned_novel_dependency),
    db: AsyncSession = Depends(get_db_session),
) -> NovelSourceSelectionState:
    """가장 최근 리비전의 초안을 승인한다. 이미 승인된 최신 리비전이면 그대로 돌려준다(두 번 누름). 최신이 아니면 409
    `NOVEL_SOURCE_SELECTION_CONFLICT`. 저장 뒤 그 include 구간으로 화가 생겼으면 422 `NOVEL_SOURCE_SECTION_LOCKED`, 고른 구간의 원문이
    저장 뒤 바뀌었으면 409 `NOVEL_SOURCE_SELECTION_SOURCE_CHANGED`(다시 저장해 지금 원문으로 고른다 — 화 다시 만들기의
    원문 변경 코드와 할 일이 달라 코드를 나눈다) — 둘 다 초안은 그대로 남는다."""
    room_id = _room_id(novel)
    latest = await _latest_selection(db, novel.id)
    if latest is None or latest.revision != payload.revision:
        raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_SOURCE_SELECTION_CONFLICT")
    if latest.approved_at is None:
        rows = await _sections_of(db, latest.id)
        _require_unlocked([(row.mode, *_section_key(row)) for row in rows], await _locked_ranges(db, novel.id))
        for row in rows:
            if (await range_shape(db, room_id, SourceRange(*_section_key(row)))).source_hash != row.source_hash:
                raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_SOURCE_SELECTION_SOURCE_CHANGED")
        # 승인 칸이 빈 행만 바꾼다 — 그사이 다른 저장이 이 초안을 지웠으면 바뀐 행이 없다.
        approved = await db.scalar(
            update(NovelSourceSelection)
            .where(NovelSourceSelection.id == latest.id, NovelSourceSelection.approved_at.is_(None))
            .values(approved_at=datetime.now(UTC))
            .returning(NovelSourceSelection.id)
        )
        if approved is None:
            raise _novel_error(status.HTTP_409_CONFLICT, "NOVEL_SOURCE_SELECTION_CONFLICT")
        await db.commit()
    return await _state(db, novel, room_id)
