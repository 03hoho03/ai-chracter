"""소설 구간 선택 라우트 — 조회·초안 저장·승인. 구성 흐름 스위치가 꺼져 있으면 모두 404 다.

방은 `_novel_setup` 이 만든다. 메시지는 오프닝 하나 + `turns` 쌍이라, 키 순 목록 `ms` 에서 `ms[0]` 이 오프닝(모델 응답),
`ms[2k-1]`·`ms[2k]` 가 k번째 사용자 말·응답이다."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models import ChatMessage, ChatMessageRole, NovelSourceSection, NovelSourceSelection
from api.novelize import selection_router
from api.novelize.source import read_source, section_ranges, segment_hash
from factories import (
    _add_chapter,
    _login_as,
    _novel_setup,
    _open_room,
    _room_messages,
)

_EXCLUDED = "빼기로-한-구간-표지"


@pytest.fixture
def outline_flow_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "novelize_outline_flow_enabled", True)
    yield


def _base(novel_id: uuid.UUID) -> str:
    return f"/novels/{novel_id}/source-selection"


def _section(mode: str, start: ChatMessage, end: ChatMessage) -> dict[str, str]:
    return {"mode": mode, "startMessageId": str(start.id), "endMessageId": str(end.id)}


def _shown(sections: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    return [(s["mode"], s["startMessageId"], s["endMessageId"]) for s in sections]


def _ids(mode: str, start: ChatMessage, end: ChatMessage) -> tuple[str, str, str]:
    return (mode, str(start.id), str(end.id))


async def _save(
    db_client: httpx.AsyncClient,
    novel_id: uuid.UUID,
    sections: list[dict[str, str]],
    *,
    base: int | None = None,
    extend: bool = False,
) -> httpx.Response:
    return await db_client.put(
        f"{_base(novel_id)}/draft",
        json={"baseRevision": base, "extendToRoomEnd": extend, "sections": sections},
    )


async def _approve(db_client: httpx.AsyncClient, novel_id: uuid.UUID, revision: int) -> httpx.Response:
    return await db_client.post(f"{_base(novel_id)}/approve", json={"revision": revision})


async def _selections(db: AsyncSession, novel_id: uuid.UUID) -> list[NovelSourceSelection]:
    rows = await db.scalars(
        sa.select(NovelSourceSelection)
        .where(NovelSourceSelection.novel_id == novel_id)
        .order_by(NovelSourceSelection.revision)
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


async def _sections_of(db: AsyncSession, selection_id: uuid.UUID) -> list[NovelSourceSection]:
    rows = await db.scalars(
        sa.select(NovelSourceSection)
        .where(NovelSourceSection.selection_id == selection_id)
        .order_by(NovelSourceSection.start_message_created_at, NovelSourceSection.start_message_id)
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


async def _rewrite(db: AsyncSession, message: ChatMessage, marker: str) -> None:
    await db.execute(
        sa.update(ChatMessage).where(ChatMessage.id == message.id).values(content=f"{message.content} {marker}")
    )
    await db.commit()


def _code(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.json()["detail"]["code"]


# ── 조회 — 기본 선택 ────────────────────────────────────────────────────────
@pytest.mark.usefixtures("outline_flow_on")
async def test_a_novel_without_chapters_proposes_the_whole_room_as_one_include_section(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """선택이 없고 화도 없는 소설은 방 전체(오프닝부터 마지막 메시지까지)를 include 한 구간으로 제안한다. 제안은 저장하지 않는다.
    깨지는 시나리오: 기본값이 비어 사용자가 처음부터 모두 골라야 하거나, 조회만으로 선택 행이 생긴다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=4)
    ms = await _room_messages(db_session, room.room_id)

    response = await db_client.get(_base(novel_id))

    assert response.status_code == 200, response.text
    assert response.headers.get("cache-control") == "no-store"
    body = response.json()
    assert (body["approved"], body["draft"], body["lockedRanges"], body["hasNewMessages"]) == (None, None, [], False)
    assert body["roomEndMessageId"] == str(ms[-1].id)
    assert body["proposal"]["revision"] is None
    assert body["proposal"]["roomEndMessageId"] == str(ms[-1].id)
    assert _shown(body["proposal"]["sections"]) == [_ids("include", ms[0], ms[-1])]
    assert await _selections(db_session, novel_id) == []


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_novel_with_chapters_proposes_from_after_the_last_chapter_to_the_room_end(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """화가 있는 소설의 첫 선택 제안은 마지막 화 끝 키 바로 뒤 메시지부터 방 끝까지 include 이고, 화가 쓴 구간은 잠긴 구간으로
    나온다. 끝 메시지와 같은 시각이지만 id 가 큰 메시지는 끝 "뒤"라 제안에 든다. 깨지는 시나리오: 제안이 이미 쓴 구간을 다시
    include 하거나, 같은 시각 메시지를 시각만 비교해 빠뜨린다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=4)
    ms = await _room_messages(db_session, room.room_id)
    await _add_chapter(db_session, novel_id, room, ms[0], ms[4])
    tie = ChatMessage(
        id=uuid.UUID(int=ms[4].id.int + 1),
        chat_room_id=room.room_id,
        role=ChatMessageRole.USER,
        content="같은 시각 뒤",
        created_at=ms[4].created_at,
    )
    db_session.add(tie)
    await db_session.commit()

    body = (await db_client.get(_base(novel_id))).json()

    assert _shown(body["proposal"]["sections"]) == [("include", str(tie.id), str(ms[-1].id))]
    assert body["lockedRanges"] == [{"startMessageId": str(ms[0].id), "endMessageId": str(ms[4].id)}]


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_novel_whose_chapters_reach_the_room_end_proposes_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """마지막 화가 방 끝까지 썼으면 제안할 구간이 없다(빈 제안). 깨지는 시나리오: 마지막 화 끝을 다시 제안한다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=2)
    ms = await _room_messages(db_session, room.room_id)
    await _add_chapter(db_session, novel_id, room, ms[0], ms[-1])

    body = (await db_client.get(_base(novel_id))).json()

    assert body["proposal"]["sections"] == []


# ── 저장·승인 ───────────────────────────────────────────────────────────────
@pytest.mark.usefixtures("outline_flow_on")
async def test_saving_and_approving_a_selection_stores_each_section_with_its_shape_and_hash(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """초안 저장은 리비전 1의 미승인 선택과 구간 행(mode·양 끝 키·AI 응답 수·해시)을 남기고, 고정 끝은 저장 때 방의 마지막
    메시지다. 승인하면 같은 리비전에 승인 시각이 찍히고 조회의 `approved` 로 나온다. 고르지 않은 사이(3턴)는 행이 없다. 깨지는
    시나리오: 해시가 구간 원문과 달라 다음 생성이 늘 원문 변경으로 막히거나, 승인이 새 행을 만들어 초안이 남는다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=5)
    ms = await _room_messages(db_session, room.room_id)
    sections = [_section("include", ms[0], ms[4]), _section("context", ms[7], ms[8]), _section("include", ms[9], ms[10])]

    saved = await _save(db_client, novel_id, sections)

    assert saved.status_code == 200, saved.text
    assert saved.json()["draft"]["revision"] == 1
    assert saved.json()["approved"] is None
    assert _shown(saved.json()["draft"]["sections"]) == [
        _ids("include", ms[0], ms[4]),
        _ids("context", ms[7], ms[8]),
        _ids("include", ms[9], ms[10]),
    ]
    (selection,) = await _selections(db_session, novel_id)
    assert (selection.revision, selection.approved_at) == (1, None)
    assert (selection.room_end_message_created_at, selection.room_end_message_id) == (ms[-1].created_at, ms[-1].id)
    rows = await _sections_of(db_session, selection.id)
    expected = [("include", 0, 4), ("context", 7, 8), ("include", 9, 10)]
    assert [(r.mode, r.start_message_id, r.end_message_id) for r in rows] == [
        (mode, ms[a].id, ms[b].id) for mode, a, b in expected
    ]
    assert [r.source_hash for r in rows] == [segment_hash(ms[a : b + 1]) for _, a, b in expected]
    assert [r.assistant_message_count for r in rows] == [3, 1, 1]

    approved = await _approve(db_client, novel_id, 1)

    assert approved.status_code == 200, approved.text
    assert approved.json()["draft"] is None
    assert approved.json()["approved"]["revision"] == 1
    assert approved.json()["approved"]["approvedAt"] is not None
    (selection,) = await _selections(db_session, novel_id)
    assert selection.approved_at is not None
    assert [r.id for r in await _sections_of(db_session, selection.id)] == [r.id for r in rows]


@pytest.mark.usefixtures("outline_flow_on")
async def test_an_approved_selection_never_changes_and_edits_become_a_new_revision(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """승인된 선택은 고쳐지지 않는다 — 그 위의 저장은 다음 리비전의 초안이고, 초안을 다시 저장하면 앞 초안은 사라진다(승인본은
    남는다). 낡은 기준 리비전으로 저장하거나 최신이 아닌 리비전을 승인하면 409 `NOVEL_SOURCE_SELECTION_CONFLICT` 이고 아무것도
    바뀌지 않는다. 같은 승인을 두 번 보내면 두 번째도 같은 결과다. 깨지는 시나리오: 다른 탭의 낡은 화면이 남의 저장을 덮거나,
    승인본의 구간이 나중 편집으로 바뀌어 그것을 근거로 만든 구성안의 출처가 사라진다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=4)
    ms = await _room_messages(db_session, room.room_id)
    assert (await _save(db_client, novel_id, [_section("include", ms[0], ms[-1])])).status_code == 200
    assert (await _approve(db_client, novel_id, 1)).status_code == 200
    again = await _approve(db_client, novel_id, 1)
    approved_rows = [(r.mode, r.start_message_id, r.end_message_id) for r in await _sections_of(
        db_session, (await _selections(db_session, novel_id))[0].id
    )]

    second = await _save(db_client, novel_id, [_section("include", ms[0], ms[4])], base=1)
    third = await _save(db_client, novel_id, [_section("include", ms[0], ms[6])], base=2)
    stale_save = await _save(db_client, novel_id, [_section("include", ms[0], ms[2])], base=2)
    missing_base = await _save(db_client, novel_id, [_section("include", ms[0], ms[2])])
    stale_approve = await _approve(db_client, novel_id, 2)

    assert again.status_code == 200
    assert again.json()["approved"]["revision"] == 1
    assert (second.status_code, second.json()["draft"]["revision"]) == (200, 2)
    assert (third.status_code, third.json()["draft"]["revision"]) == (200, 3)
    assert third.json()["approved"]["revision"] == 1
    assert _code(stale_save) == (409, "NOVEL_SOURCE_SELECTION_CONFLICT")
    assert _code(missing_base) == (409, "NOVEL_SOURCE_SELECTION_CONFLICT")
    assert _code(stale_approve) == (409, "NOVEL_SOURCE_SELECTION_CONFLICT")
    selections = await _selections(db_session, novel_id)
    assert [(s.revision, s.approved_at is not None) for s in selections] == [(1, True), (3, False)]
    assert [(r.mode, r.start_message_id, r.end_message_id) for r in await _sections_of(
        db_session, selections[0].id
    )] == approved_rows
    assert [r.end_message_id for r in await _sections_of(db_session, selections[1].id)] == [ms[6].id]


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_save_that_loses_the_revision_race_is_a_conflict_and_writes_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """두 탭이 같은 기준으로 동시에 저장하면 둘 다 같은 다음 리비전을 넣으려 하고, 늦은 쪽은 리비전 유니크에 걸려 409 다. 여기서는
    늦은 쪽이 최신 리비전을 읽은 뒤 다른 저장이 끼어든 상태를 만든다. 깨지는 시나리오: 유니크 위반이 500 으로 나가거나 늦은 저장이
    앞 저장을 덮는다. 끼어든 행이 이 시험 연결에서는 늦은 쪽의 되감기에 함께 지워질 수 있어(운영에서는 다른 트랜잭션이라 남는다)
    선택 행 수는 보지 않고 구간 행이 하나도 남지 않았는지만 본다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=2)
    ms = await _room_messages(db_session, room.room_id)
    real_latest = selection_router._latest_selection

    async def read_then_lose_the_race(db: AsyncSession, nid: uuid.UUID) -> NovelSourceSelection | None:
        seen = await real_latest(db, nid)
        db.add(
            NovelSourceSelection(
                novel_id=nid,
                revision=1,
                room_end_message_id=ms[-1].id,
                room_end_message_created_at=ms[-1].created_at,
                approved_at=datetime.now(UTC),
            )
        )
        await db.commit()
        return seen

    monkeypatch.setattr(selection_router, "_latest_selection", read_then_lose_the_race)

    response = await _save(db_client, novel_id, [_section("include", ms[0], ms[-1])])

    assert _code(response) == (409, "NOVEL_SOURCE_SELECTION_CONFLICT")
    assert [await _sections_of(db_session, s.id) for s in await _selections(db_session, novel_id)] in ([], [[]])


# ── 새 메시지 자동 편입 금지 ────────────────────────────────────────────────
@pytest.mark.usefixtures("outline_flow_on")
async def test_messages_after_the_fixed_end_join_only_through_an_explicit_extend(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """승인 뒤 이어진 대화는 선택에 저절로 붙지 않는다 — 조회는 "새 메시지 있음"만 알리고, 승인본의 include 를 관문으로 읽어도 새
    메시지가 없다. 고정 끝을 그대로 둔 저장은 새 메시지를 가리키면 422 `NOVEL_SOURCE_SECTION_OUT_OF_RANGE` 이고, "방 끝까지 늘리기"를
    밝힌 저장만 고정 끝을 지금 방 끝으로 옮겨 새 구간을 받는다. 깨지는 시나리오: "방 전체" 선택이 승인 뒤 대화를 조용히 삼켜 사용자가
    고른 적 없는 원문이 모델에 간다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=3)
    ms = await _room_messages(db_session, room.room_id)
    assert (await _save(db_client, novel_id, [_section("include", ms[0], ms[-1])])).status_code == 200
    assert (await _approve(db_client, novel_id, 1)).status_code == 200
    later = [
        ChatMessage(
            id=uuid.uuid4(),
            chat_room_id=room.room_id,
            role=role,
            content=f"승인 뒤 {i}",
            created_at=ms[-1].created_at + timedelta(seconds=i + 1),
        )
        for i, role in enumerate((ChatMessageRole.USER, ChatMessageRole.ASSISTANT))
    ]
    db_session.add_all(later)
    await db_session.commit()

    state = (await db_client.get(_base(novel_id))).json()
    (approved,) = await _selections(db_session, novel_id)
    read = await read_source(
        db_session, room.room_id, section_ranges(await _sections_of(db_session, approved.id), mode="include")
    )
    kept_end = await _save(
        db_client, novel_id, [_section("include", ms[0], ms[-1]), _section("include", later[0], later[1])], base=1
    )
    extended = await _save(
        db_client,
        novel_id,
        [_section("include", ms[0], ms[-1]), _section("include", later[0], later[1])],
        base=1,
        extend=True,
    )

    assert state["hasNewMessages"] is True
    assert state["approved"]["roomEndMessageId"] == str(ms[-1].id)
    assert state["roomEndMessageId"] == str(later[1].id)
    assert _shown(state["approved"]["sections"]) == [_ids("include", ms[0], ms[-1])]
    assert [m.id for m in read] == [m.id for m in ms]
    assert _code(kept_end) == (422, "NOVEL_SOURCE_SECTION_OUT_OF_RANGE")
    assert extended.status_code == 200, extended.text
    assert extended.json()["draft"]["roomEndMessageId"] == str(later[1].id)
    assert extended.json()["hasNewMessages"] is False


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_draft_saved_on_a_draft_keeps_the_first_fixed_end(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """초안 위의 저장도 고정 끝을 물려받는다 — 초안을 고치는 사이 들어온 메시지가 고정 끝 안으로 들어오지 않는다. 깨지는 시나리오:
    두 번째 저장이 고정 끝을 그때의 방 끝으로 옮겨, 사용자가 본 적 없는 메시지가 "고르지 않은 사이"로 숨는다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=2)
    ms = await _room_messages(db_session, room.room_id)
    assert (await _save(db_client, novel_id, [_section("include", ms[0], ms[-1])])).status_code == 200
    db_session.add(
        ChatMessage(
            id=uuid.uuid4(),
            chat_room_id=room.room_id,
            role=ChatMessageRole.USER,
            content="초안 뒤",
            created_at=ms[-1].created_at + timedelta(seconds=1),
        )
    )
    await db_session.commit()

    second = await _save(db_client, novel_id, [_section("include", ms[0], ms[2])], base=1)

    assert second.status_code == 200, second.text
    assert second.json()["draft"]["roomEndMessageId"] == str(ms[-1].id)
    assert second.json()["hasNewMessages"] is True


# ── 겹침·정렬·소유 ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("overlap", (422, "NOVEL_SOURCE_SECTION_INVALID")),
        ("touching", (422, "NOVEL_SOURCE_SECTION_INVALID")),
        ("unordered", (422, "NOVEL_SOURCE_SECTION_INVALID")),
        ("reversed", (422, "NOVEL_SOURCE_SECTION_INVALID")),
        ("other_room", (422, "NOVEL_SOURCE_MESSAGE_NOT_FOUND")),
        ("unknown", (422, "NOVEL_SOURCE_MESSAGE_NOT_FOUND")),
        ("no_include", (422, "NOVEL_SOURCE_SELECTION_EMPTY")),
        ("include_without_reply", (422, "NOVEL_SOURCE_SELECTION_EMPTY")),
        ("nothing", (422, "NOVEL_SOURCE_SELECTION_EMPTY")),
    ],
)
@pytest.mark.usefixtures("outline_flow_on")
async def test_a_malformed_selection_is_rejected_before_anything_is_stored(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected: tuple[int, str],
) -> None:
    """겹치거나(끝과 다음 시작이 같은 메시지인 것 포함) 키 순이 아닌 구간 목록, 시작이 끝보다 뒤인 구간, 이 방의 메시지가 아닌
    키, include 가 없거나 include 에 모델 응답이 하나도 없는 선택은 저장 전에 422 다. 깨지는 시나리오: 겹친 구간이 관문에서 같은
    메시지를 두 번 싣거나, 남의 방 메시지 id 로 그 방 원문의 해시·응답 수를 엿보거나, 쓸 원문이 없는 선택이 승인된다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=4)
    ms = await _room_messages(db_session, room.room_id)
    other = await _open_room(db_client, db_session, turns=1)
    other_ms = await _room_messages(db_session, other.room_id)
    await _login_as(db_client, room.user_id)
    sections = {
        "overlap": [_section("include", ms[0], ms[4]), _section("context", ms[3], ms[6])],
        "touching": [_section("include", ms[0], ms[4]), _section("include", ms[4], ms[6])],
        "unordered": [_section("include", ms[5], ms[6]), _section("include", ms[0], ms[2])],
        "reversed": [_section("include", ms[4], ms[0])],
        "other_room": [_section("include", ms[0], other_ms[-1])],
        "unknown": [{"mode": "include", "startMessageId": str(uuid.uuid4()), "endMessageId": str(ms[2].id)}],
        "no_include": [_section("context", ms[0], ms[4])],
        "include_without_reply": [_section("include", ms[1], ms[1]), _section("context", ms[2], ms[4])],
        "nothing": [],
    }[case]

    response = await _save(db_client, novel_id, sections)

    assert _code(response) == expected
    assert await _selections(db_session, novel_id) == []


@pytest.mark.usefixtures("outline_flow_on")
async def test_an_unknown_mode_is_a_validation_error(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """mode 는 include·context 둘뿐이다 — exclude 는 고르지 않은 나머지라 보낼 수 없다. 깨지는 시나리오: exclude 행이 저장돼
    관문이 그것을 읽을 구간으로 받는다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=2)
    ms = await _room_messages(db_session, room.room_id)

    response = await _save(db_client, novel_id, [_section("exclude", ms[0], ms[-1])])

    assert response.status_code == 422
    assert response.headers.get("cache-control") == "no-store"
    assert await _selections(db_session, novel_id) == []


# ── 이미 쓴 구간 ────────────────────────────────────────────────────────────
@pytest.mark.usefixtures("outline_flow_on")
async def test_a_written_range_cannot_be_included_again_until_its_chapter_is_deleted(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """화가 쓴 구간과 겹치는 include(일부만 걸치거나 그 구간을 감싸는 것 포함)는 422 `NOVEL_SOURCE_SECTION_LOCKED` 다. 그 구간은
    잠긴 구간으로 따로 나오므로 고르지 않은 나머지(exclude)로 셈하지 않는다. 화를 지우면 잠금이 풀려 다시 include 할 수 있다.
    깨지는 시나리오: 이미 소설이 된 대화를 다음 화가 또 쓰거나, 지운 화의 구간이 영영 잠긴다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=4)
    ms = await _room_messages(db_session, room.room_id)
    chapter = await _add_chapter(db_session, novel_id, room, ms[3], ms[6])

    partial = await _save(db_client, novel_id, [_section("include", ms[5], ms[8])])
    wrapping = await _save(db_client, novel_id, [_section("include", ms[0], ms[-1])])
    around = await _save(
        db_client, novel_id, [_section("include", ms[0], ms[2]), _section("include", ms[7], ms[-1])]
    )
    state = (await db_client.get(_base(novel_id))).json()
    deleted = await db_client.delete(f"/novels/{novel_id}/batches/{chapter.batch_id}")
    after_delete = await _save(db_client, novel_id, [_section("include", ms[0], ms[-1])], base=1)

    assert _code(partial) == (422, "NOVEL_SOURCE_SECTION_LOCKED")
    assert _code(wrapping) == (422, "NOVEL_SOURCE_SECTION_LOCKED")
    assert around.status_code == 200, around.text
    assert state["lockedRanges"] == [{"startMessageId": str(ms[3].id), "endMessageId": str(ms[6].id)}]
    assert deleted.status_code == 204, deleted.text
    assert after_delete.status_code == 200, after_delete.text


@pytest.mark.usefixtures("outline_flow_on")
async def test_a_written_range_may_be_sent_as_context(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """이미 쓴 구간을 맥락(context)으로 보내는 것은 막지 않는다 — 잠금은 다시 쓰기(include)를 막는 것이다. 깨지는 시나리오: 앞 화와
    이어지는 장면을 쓰려는 사용자가 앞 화의 원문을 참고로도 보낼 수 없다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=4)
    ms = await _room_messages(db_session, room.room_id)
    await _add_chapter(db_session, novel_id, room, ms[0], ms[4])

    response = await _save(db_client, novel_id, [_section("context", ms[3], ms[4]), _section("include", ms[5], ms[-1])])

    assert response.status_code == 200, response.text


@pytest.mark.usefixtures("outline_flow_on")
async def test_approving_a_draft_that_a_new_chapter_overlaps_is_refused(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """초안을 저장한 뒤 그 include 구간으로 화가 생겼으면(옛 흐름이 아직 살아 있는 동안) 승인은 422 `NOVEL_SOURCE_SECTION_LOCKED`
    이고 초안은 미승인으로 남는다. 깨지는 시나리오: 저장 때만 잠금을 보고 승인이 이미 쓴 구간을 근거로 굳힌다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=4)
    ms = await _room_messages(db_session, room.room_id)
    assert (await _save(db_client, novel_id, [_section("include", ms[0], ms[-1])])).status_code == 200
    await _add_chapter(db_session, novel_id, room, ms[0], ms[4])

    response = await _approve(db_client, novel_id, 1)

    assert _code(response) == (422, "NOVEL_SOURCE_SECTION_LOCKED")
    (draft,) = await _selections(db_session, novel_id)
    assert draft.approved_at is None


# ── 해시 — include·context 만 ───────────────────────────────────────────────
@pytest.mark.usefixtures("outline_flow_on")
async def test_editing_an_excluded_gap_changes_no_hash_and_editing_a_chosen_section_does(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """고르지 않은 사이(exclude)의 원문을 고쳐도 구간 해시는 그대로라 승인이 되고 조회의 "원문 바뀜"도 없다. 승인 뒤 context 구간
    원문을 고치면 그 구간만 "원문 바뀜"이다. 초안 저장 뒤 include 원문이 바뀌면 승인은 409 `NOVEL_SOURCE_CHANGED` 다. 깨지는
    시나리오: 빼기로 한 대화를 고친 것만으로 다음 생성이 원문 변경으로 막히거나(해시가 exclude 를 읽음), 고른 구간의 원문이 바뀐
    선택이 그대로 승인된다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=5)
    ms = await _room_messages(db_session, room.room_id)
    sections = [_section("include", ms[0], ms[4]), _section("context", ms[7], ms[8]), _section("include", ms[9], ms[10])]
    assert (await _save(db_client, novel_id, sections)).status_code == 200
    await _rewrite(db_session, ms[5], _EXCLUDED)

    approved = await _approve(db_client, novel_id, 1)
    await _rewrite(db_session, ms[8], "고친 맥락")
    after_context_edit = (await db_client.get(_base(novel_id))).json()
    assert (await _save(db_client, novel_id, sections, base=1)).status_code == 200
    await _rewrite(db_session, ms[2], "고친 본문")
    refused = await _approve(db_client, novel_id, 2)

    assert approved.status_code == 200, approved.text
    assert [s["sourceChanged"] for s in approved.json()["approved"]["sections"]] == [False, False, False]
    assert [s["sourceChanged"] for s in after_context_edit["approved"]["sections"]] == [False, True, False]
    assert _code(refused) == (409, "NOVEL_SOURCE_CHANGED")
    assert (await _selections(db_session, novel_id))[-1].approved_at is None


# ── 관문 — include 와 context 를 나눠 읽는다 ────────────────────────────────
@pytest.mark.usefixtures("outline_flow_on")
async def test_the_gateway_reads_an_approved_selection_by_mode_and_never_its_gaps(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """승인된 선택을 관문으로 읽을 때 include 와 context 는 mode 로 나눠 받는다 — 빌더가 맥락을 본문 근거와 다른 블록에 싣게.
    어느 쪽에도 고르지 않은 사이의 표지가 없다. 깨지는 시나리오: 맥락으로만 보낸 대화가 소설 본문 근거로 섞이거나, 빼기로 한 대화가
    실린다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=5)
    ms = await _room_messages(db_session, room.room_id)
    await _rewrite(db_session, ms[5], _EXCLUDED)
    sections = [_section("include", ms[0], ms[4]), _section("context", ms[7], ms[8]), _section("include", ms[9], ms[10])]
    assert (await _save(db_client, novel_id, sections)).status_code == 200
    assert (await _approve(db_client, novel_id, 1)).status_code == 200
    (selection,) = await _selections(db_session, novel_id)
    rows = await _sections_of(db_session, selection.id)

    include = await read_source(db_session, room.room_id, section_ranges(rows, mode="include"))
    context = await read_source(db_session, room.room_id, section_ranges(rows, mode="context"))

    assert [m.id for m in include] == [m.id for m in ms[0:5] + ms[9:11]]
    assert [m.id for m in context] == [m.id for m in ms[7:9]]
    assert not any(_EXCLUDED in m.content for m in include + context)


# ── 소유·방 ─────────────────────────────────────────────────────────────────
@pytest.mark.usefixtures("outline_flow_on")
async def test_someone_elses_novel_and_a_novel_without_its_room_are_refused(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """남의 소설은 403 `NOVEL_FORBIDDEN`, 방이 지워진 소설은 409 `NOVEL_ROOM_GONE` 이다. 깨지는 시나리오: 남의 방 원문 구간을
    고르거나, 방 없는 소설에서 500 이 난다."""
    _, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=2)
    _, roomless_id = await _novel_setup(db_client, db_session, monkeypatch, turns=1)
    await db_session.execute(sa.text("UPDATE novels SET chat_room_id = NULL WHERE id = :id"), {"id": roomless_id})
    await db_session.commit()

    roomless = [
        await db_client.get(_base(roomless_id)),
        await _save(db_client, roomless_id, [{"mode": "include", "startMessageId": str(uuid.uuid4()), "endMessageId": str(uuid.uuid4())}]),
    ]
    foreign = await db_client.get(_base(novel_id))

    assert [_code(r) for r in roomless] == [(409, "NOVEL_ROOM_GONE")] * 2
    assert _code(foreign) == (403, "NOVEL_FORBIDDEN")


# ── 스위치 ──────────────────────────────────────────────────────────────────
async def test_every_selection_route_is_an_uncached_404_while_the_switch_is_off(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """구성 흐름 스위치가 꺼져 있으면 선택 라우트 셋 모두 404 `NOVEL_OUTLINE_FLOW_DISABLED` 이고 `Cache-Control: no-store` 라 켠 뒤
    브라우저가 404 를 붙잡지 않는다. 아무 행도 생기지 않고 소설 상세는 그대로 열린다. 깨지는 시나리오: 꺼진 채 배포한 동안 선택이
    저장되거나, 켠 뒤에도 캐시된 404 가 남는다."""
    monkeypatch.setattr(settings, "novelize_outline_flow_enabled", False)
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=2)
    ms = await _room_messages(db_session, room.room_id)

    responses = [
        await db_client.get(_base(novel_id)),
        await _save(db_client, novel_id, [_section("include", ms[0], ms[-1])]),
        await _approve(db_client, novel_id, 1),
    ]
    detail = await db_client.get(f"/novels/{novel_id}")

    assert [(_code(r), r.headers.get("cache-control")) for r in responses] == [
        ((404, "NOVEL_OUTLINE_FLOW_DISABLED"), "no-store")
    ] * 3
    assert await _selections(db_session, novel_id) == []
    assert detail.status_code == 200
