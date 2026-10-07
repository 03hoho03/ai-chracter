"""소설 스냅샷 라우트 — 저장·목록·상세·삭제·복원.

복원은 내용만 되돌리고 구조는 남긴다: 스냅샷 뒤에 생긴 화는 그대로이고, 스냅샷의 화는 그때 본문을 새 개정으로 쌓는다.
화나 그때 개정이 지워졌으면 건너뛴다. 복원 직전 상태는 자동 스냅샷으로 남고, 상한은 자동 스냅샷부터 지워 지킨다. 진행 중
작업과 겹치는 경쟁은 `test_novelize_edit_races.py` 에 있다."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models.novel import (
    Novel,
    NovelChapter,
    NovelChapterRevision,
    NovelCharacter,
    NovelJob,
    NovelSnapshot,
)
from api.novelize import router as novelize_router
from factories import (
    _NeverCalledLLMClient,
    _add_batch,
    _clear_llm_override,
    _novel_setup,
    _override_llm_client,
    _room_messages,
)


@pytest.fixture(autouse=True)
def _no_model() -> Iterator[None]:
    _override_llm_client(_NeverCalledLLMClient())
    yield
    _clear_llm_override()


async def _novel_with_two_episodes(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> tuple[uuid.UUID, list[NovelChapter]]:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    chapters = await _add_batch(db_session, novel_id, room, messages[0], room.turns[1][1], episodes=2, body="옛 본문")
    return novel_id, chapters


async def _snapshot(db_client: httpx.AsyncClient, novel_id: uuid.UUID, name: str = "1차") -> httpx.Response:
    return await db_client.post(f"/novels/{novel_id}/snapshots", json={"name": name})


async def _revisions(db: AsyncSession, chapter_id: uuid.UUID) -> list[tuple[int, str, str]]:
    rows = await db.scalars(
        sa.select(NovelChapterRevision)
        .where(NovelChapterRevision.chapter_id == chapter_id)
        .order_by(NovelChapterRevision.revision_no)
        .execution_options(populate_existing=True)
    )
    return [(r.revision_no, r.source, r.body) for r in rows.all()]


async def _stack(db: AsyncSession, chapter_id: uuid.UUID, body: str) -> NovelChapterRevision:
    last = await db.scalar(
        sa.select(sa.func.max(NovelChapterRevision.revision_no)).where(NovelChapterRevision.chapter_id == chapter_id)
    )
    revision = NovelChapterRevision(chapter_id=chapter_id, revision_no=(last or 0) + 1, body=body, source="manual_edit")
    db.add(revision)
    await db.commit()
    return revision


async def test_saving_captures_the_editable_state_and_the_detail_lists_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    novel_id, (first, second) = await _novel_with_two_episodes(db_client, db_session, monkeypatch)
    await db_client.patch(f"/novels/{novel_id}", json={"title": "고친 제목", "synopsis": "소개"})
    await db_client.put(f"/novels/{novel_id}/notes", json={"settingNotes": "노트"})
    await db_client.patch(f"/novels/{novel_id}/chapters/{first.id}", json={"title": "1화 제목", "authorNote": "말"})
    db_session.add(NovelCharacter(novel_id=novel_id, name="도윤", aliases=["윤이"], memo="메모"))
    await db_session.commit()
    current = await _stack(db_session, second.id, "2화 새 본문")

    saved = await _snapshot(db_client, novel_id, "  첫 저장 ")
    listed = await db_client.get(f"/novels/{novel_id}/snapshots")
    detail = await db_client.get(f"/novels/{novel_id}/snapshots/{saved.json()['id']}")

    assert saved.status_code == 201, saved.text
    assert (saved.json()["name"], saved.json()["kind"]) == ("첫 저장", "manual")
    assert listed.json()["limit"] == settings.novelize_snapshot_limit
    assert [item["id"] for item in listed.json()["items"]] == [saved.json()["id"]]
    body = detail.json()
    assert (body["title"], body["titleEdited"], body["synopsis"], body["settingNotes"]) == (
        "고친 제목",
        True,
        "소개",
        "노트",
    )
    assert [(c["name"], c["aliases"], c["memo"]) for c in body["characters"]] == [("도윤", ["윤이"], "메모")]
    assert [(c["chapterId"], c["deleted"], c["title"], c["authorNote"]) for c in body["chapters"]] == [
        (str(first.id), False, "1화 제목", "말"),
        (str(second.id), False, None, ""),
    ]
    assert body["chapters"][1]["revisionId"] == str(current.id)


async def test_restore_brings_back_text_titles_notes_and_cards_as_new_revisions_and_keeps_later_episodes(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """스냅샷 때 AI 가 쓴 제목이었으면 고친 시각도 비워져, 다음 생성이 제목을 다시 쓸 수 있다. 스냅샷 뒤에 만든 묶음은
    지우지 않는다(값을 치른 화가 사라지지 않게). 본문이 이미 그때 개정인 화에는 같은 본문을 또 쌓지 않는다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    first, second = await _add_batch(
        db_session, novel_id, room, messages[0], room.turns[1][1], episodes=2, body="옛 본문"
    )
    await db_session.execute(
        sa.update(Novel)
        .where(Novel.id == novel_id)
        .values(title="AI 제목", synopsis="옛 소개", setting_notes="옛 노트")
    )
    await db_session.execute(sa.update(NovelChapter).where(NovelChapter.id == first.id).values(summary="옛 요약"))
    card = NovelCharacter(novel_id=novel_id, name="도윤", aliases=["윤이"], memo="옛 메모")
    db_session.add(card)
    await db_session.commit()
    snapshot_id = (await _snapshot(db_client, novel_id)).json()["id"]

    await db_client.patch(f"/novels/{novel_id}", json={"title": "사용자 제목", "synopsis": "새 소개"})
    await db_client.put(f"/novels/{novel_id}/notes", json={"settingNotes": "새 노트"})
    await db_client.patch(
        f"/novels/{novel_id}/chapters/{first.id}", json={"title": "새 화 제목", "authorNote": "새 말"}
    )
    await db_session.execute(sa.update(NovelChapter).where(NovelChapter.id == first.id).values(summary="새 요약"))
    await db_session.commit()
    await _stack(db_session, first.id, "새 본문")
    await db_client.patch(
        f"/novels/{novel_id}/characters/{card.id}", json={"name": "윤도윤", "aliases": [], "memo": "새 메모"}
    )
    (later,) = await _add_batch(db_session, novel_id, room, room.turns[2][0], room.turns[2][1])

    resp = await db_client.post(f"/novels/{novel_id}/snapshots/{snapshot_id}/restore")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["skippedChapters"] == []
    novel = body["novel"]
    assert (novel["title"], novel["titleEdited"], novel["synopsis"], novel["settingNotes"]) == (
        "AI 제목",
        False,
        "옛 소개",
        "옛 노트",
    )
    assert [(c["id"], c["title"], c["summary"], c["authorNote"]) for c in novel["chapters"]] == [
        (str(first.id), None, "옛 요약", ""),
        (str(second.id), None, None, ""),
        (str(later.id), None, None, ""),
    ]
    assert await _revisions(db_session, first.id) == [
        (1, "generate", "옛 본문"),
        (2, "manual_edit", "새 본문"),
        (3, "revert", "옛 본문"),
    ]
    assert await _revisions(db_session, second.id) == [(1, "generate", "옛 본문")]
    restored = await db_session.get(NovelCharacter, card.id, populate_existing=True)
    assert restored is not None
    assert (restored.name, restored.aliases, restored.memo) == ("도윤", ["윤이"], "옛 메모")
    stored = await db_session.get(Novel, novel_id, populate_existing=True)
    assert stored is not None and stored.title_edited_at is None
    auto = await db_client.get(f"/novels/{novel_id}/snapshots/{body['autoSnapshotId']}")
    assert (auto.json()["kind"], auto.json()["title"], auto.json()["titleEdited"]) == (
        "auto_before_restore",
        "사용자 제목",
        True,
    )


async def test_restore_keeps_a_user_edited_title_edited(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    novel_id, _chapters = await _novel_with_two_episodes(db_client, db_session, monkeypatch)
    await db_client.patch(f"/novels/{novel_id}", json={"title": "내 제목"})
    edited_at = (await db_session.get_one(Novel, novel_id, populate_existing=True)).title_edited_at
    snapshot_id = (await _snapshot(db_client, novel_id)).json()["id"]
    await db_session.execute(
        sa.update(Novel)
        .where(Novel.id == novel_id)
        .values(title="다른 제목", title_edited_at=datetime.now(UTC) + timedelta(days=1))
    )
    await db_session.commit()

    await db_client.post(f"/novels/{novel_id}/snapshots/{snapshot_id}/restore")

    stored = await db_session.get_one(Novel, novel_id, populate_existing=True)
    assert (stored.title, stored.title_edited_at) == ("내 제목", edited_at)


async def test_restore_skips_episodes_whose_episode_or_revision_is_gone(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """지운 화(스냅샷 항목이 `deleted` 로 줄어든 것)와 개정이 사라진 화는 건너뛰고 알린다. 나머지 화는 되돌린다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    (kept,) = await _add_batch(db_session, novel_id, room, messages[0], room.turns[1][1], body="옛 본문")
    (lost_revision,) = await _add_batch(db_session, novel_id, room, room.turns[2][0], room.turns[2][1], body="옛 본문")
    (deleted,) = await _add_batch(db_session, novel_id, room, room.turns[3][0], room.turns[3][1], body="옛 본문")
    snapshot_id = (await _snapshot(db_client, novel_id)).json()["id"]
    await _stack(db_session, kept.id, "새 본문")
    # 그때 개정이 사라진 화: 스냅샷이 가리키는 개정 id 를 없는 값으로 바꿔 흉내 낸다(개정만 지우는 경로는 없다).
    snapshot = await db_session.get_one(NovelSnapshot, uuid.UUID(snapshot_id))
    payload = dict(snapshot.payload)
    payload["chapters"] = [
        {**entry, "revisionId": str(uuid.uuid4())} if entry["chapterId"] == str(lost_revision.id) else entry
        for entry in payload["chapters"]
    ]
    await db_session.execute(sa.update(NovelSnapshot).where(NovelSnapshot.id == snapshot.id).values(payload=payload))
    await db_session.commit()
    removed = await db_client.delete(f"/novels/{novel_id}/batches/{deleted.batch_id}")
    assert removed.status_code == 204, removed.text

    resp = await db_client.post(f"/novels/{novel_id}/snapshots/{snapshot_id}/restore")

    assert resp.status_code == 200, resp.text
    assert resp.json()["skippedChapters"] == [str(lost_revision.id), str(deleted.id)]
    assert (await _revisions(db_session, kept.id))[-1] == (3, "revert", "옛 본문")
    assert await _revisions(db_session, lost_revision.id) == [(1, "generate", "옛 본문")]


async def test_restore_returns_a_merged_cards_memo_to_the_card_that_absorbed_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """스냅샷 뒤 합쳐져 사라진 카드의 메모는 그 이름을 별칭으로 가진 카드로 돌아간다 — 남는 카드의 그때 메모가 앞, 흡수된
    카드의 그때 메모가 `[이름] 메모` 로 뒤. 합쳐 온 별칭은 남는다(빼면 다음 생성에서 그 이름이 다시 갈라진다)."""
    novel_id, _chapters = await _novel_with_two_episodes(db_client, db_session, monkeypatch)
    doyun = NovelCharacter(novel_id=novel_id, name="도윤", aliases=["도"], memo="그때 도윤 메모")
    yuni = NovelCharacter(novel_id=novel_id, name="윤이", aliases=["윤"], memo="그때 윤이 메모")
    db_session.add_all([doyun, yuni])
    await db_session.commit()
    snapshot_id = (await _snapshot(db_client, novel_id)).json()["id"]
    await db_client.post(f"/novels/{novel_id}/characters/{yuni.id}/merge", json={"intoCharacterId": str(doyun.id)})
    await db_client.patch(f"/novels/{novel_id}/characters/{doyun.id}", json={"memo": "지금 메모"})

    resp = await db_client.post(f"/novels/{novel_id}/snapshots/{snapshot_id}/restore")

    assert resp.status_code == 200, resp.text
    (card,) = (await db_client.get(f"/novels/{novel_id}/characters")).json()["items"]
    assert (card["id"], card["name"], card["aliases"]) == (str(doyun.id), "도윤", ["도", "윤이", "윤"])
    assert card["memo"] == "그때 도윤 메모\n\n[윤이] 그때 윤이 메모"


async def test_restore_leaves_a_cards_name_alone_when_a_later_card_now_holds_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """스냅샷 뒤 이름을 바꾼 카드의 옛 이름을 그 뒤 생긴 카드가 쓰고 있으면, 되돌린 이름이 겹친다. 이름 ∪ 별칭은 겹치면
    안 되므로 그 카드의 이름은 지금 값으로 두고 메모만 되돌린다. 두 카드가 이름을 맞바꾼 경우는 둘 다 되돌린다."""
    novel_id, _chapters = await _novel_with_two_episodes(db_client, db_session, monkeypatch)
    doyun = NovelCharacter(novel_id=novel_id, name="도윤", memo="그때 도윤")
    seojin = NovelCharacter(novel_id=novel_id, name="서진", memo="그때 서진")
    haneul = NovelCharacter(novel_id=novel_id, name="하늘", memo="그때 하늘")
    db_session.add_all([doyun, seojin, haneul])
    await db_session.commit()
    snapshot_id = (await _snapshot(db_client, novel_id)).json()["id"]
    await db_client.patch(f"/novels/{novel_id}/characters/{haneul.id}", json={"name": "하늘이", "memo": "지금 하늘"})
    await db_client.put(f"/novels/{novel_id}/characters", json={"name": "하늘"})
    # 맞바꾸기: 도윤 → 임시 → 서진, 서진 → 도윤
    await db_client.patch(f"/novels/{novel_id}/characters/{doyun.id}", json={"name": "임시"})
    await db_client.patch(f"/novels/{novel_id}/characters/{seojin.id}", json={"name": "도윤"})
    await db_client.patch(f"/novels/{novel_id}/characters/{doyun.id}", json={"name": "서진"})

    resp = await db_client.post(f"/novels/{novel_id}/snapshots/{snapshot_id}/restore")

    assert resp.status_code == 200, resp.text
    cards = {
        c["id"]: (c["name"], c["memo"]) for c in (await db_client.get(f"/novels/{novel_id}/characters")).json()["items"]
    }
    assert cards[str(doyun.id)] == ("도윤", "그때 도윤")
    assert cards[str(seojin.id)] == ("서진", "그때 서진")
    assert cards[str(haneul.id)] == ("하늘이", "그때 하늘")


async def test_restore_is_409_while_a_job_runs_and_404_for_another_novels_snapshot(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    other_id, _ = await _novel_with_two_episodes(db_client, db_session, monkeypatch)
    foreign = (await _snapshot(db_client, other_id)).json()["id"]
    novel_id, _chapters = await _novel_with_two_episodes(db_client, db_session, monkeypatch)
    snapshot_id = (await _snapshot(db_client, novel_id)).json()["id"]
    novel = await db_session.get_one(Novel, novel_id)
    db_session.add(
        NovelJob(
            novel_id=novel_id,
            user_id=novel.user_id,
            kind="ai_edit",
            status="running",
            charged_amount=5,
            heartbeat_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    busy = await db_client.post(f"/novels/{novel_id}/snapshots/{snapshot_id}/restore")
    other = await db_client.post(f"/novels/{novel_id}/snapshots/{foreign}/restore")

    assert (busy.status_code, busy.json()["detail"]) == (409, {"code": "NOVEL_JOB_IN_PROGRESS"})
    assert (other.status_code, other.json()["detail"]) == (404, {"code": "NOVEL_SNAPSHOT_NOT_FOUND"})
    kinds = (await db_session.scalars(sa.select(NovelSnapshot.kind).where(NovelSnapshot.novel_id == novel_id))).all()
    assert kinds == ["manual"]


async def test_restore_clears_ai_edit_previews_made_stale_by_the_new_revision(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    novel_id, (first, _second) = await _novel_with_two_episodes(db_client, db_session, monkeypatch)
    snapshot_id = (await _snapshot(db_client, novel_id)).json()["id"]
    newer = await _stack(db_session, first.id, "새 본문")
    novel = await db_session.get_one(Novel, novel_id)
    preview = NovelJob(
        novel_id=novel_id,
        user_id=novel.user_id,
        kind="ai_edit",
        status="succeeded",
        charged_amount=5,
        chapter_id=first.id,
        base_revision_id=newer.id,
        paragraph_start=0,
        paragraph_end=0,
        instruction="고쳐 줘",
        result_text="고친 본문",
    )
    db_session.add(preview)
    await db_session.commit()

    resp = await db_client.post(f"/novels/{novel_id}/snapshots/{snapshot_id}/restore")

    assert resp.status_code == 200, resp.text
    stored = await db_session.get_one(NovelJob, preview.id, populate_existing=True)
    assert (stored.instruction, stored.result_text) == (None, None)
    assert resp.json()["novel"]["pendingAiEdits"] == []


async def test_a_failing_preview_cleanup_does_not_undo_a_committed_restore(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """미리보기 비우기는 복원을 커밋한 뒤 따로 돈다. 같은 트랜잭션이면 그 실패가 복원까지 되돌리고(500), 화를 쥔 채 작업
    행을 고치게 되어 적용과 교착한다."""
    novel_id, (first, _second) = await _novel_with_two_episodes(db_client, db_session, monkeypatch)
    snapshot_id = (await _snapshot(db_client, novel_id)).json()["id"]
    await _stack(db_session, first.id, "새 본문")

    async def broken_erase(db: AsyncSession, _chapter_id: uuid.UUID) -> None:
        await db.execute(sa.text("SELECT 1 / 0"))

    reported: list[str] = []
    monkeypatch.setattr(novelize_router, "erase_stale_ai_edit_previews", broken_erase)
    monkeypatch.setattr(
        novelize_router, "capture_dependency_failure", lambda _exc, *, dependency: reported.append(dependency)
    )

    resp = await db_client.post(f"/novels/{novel_id}/snapshots/{snapshot_id}/restore")

    assert resp.status_code == 200, resp.text
    assert (await _revisions(db_session, first.id))[-1] == (3, "revert", "옛 본문")
    assert reported == ["db"]


async def test_cap_rotates_out_the_oldest_auto_snapshot_and_refuses_a_save_when_only_named_ones_fill_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """상한 3. 이름 붙인 2 + 자동 1 이 차 있으면 새 이름 저장은 가장 오래된 자동 것을 밀어낸다. 이름 붙인 것만 3 이면
    새 저장은 409 지만 복원은 막히지 않는다 — 복원 직전 자동 스냅샷은 한 장 더(4) 허용되고, 다음 복원 때 그 자동 것이
    먼저 밀려난다."""
    monkeypatch.setattr(settings, "novelize_snapshot_limit", 3)
    novel_id, _chapters = await _novel_with_two_episodes(db_client, db_session, monkeypatch)
    one = (await _snapshot(db_client, novel_id, "하나")).json()["id"]
    await _snapshot(db_client, novel_id, "둘")
    restored = await db_client.post(f"/novels/{novel_id}/snapshots/{one}/restore")
    auto = restored.json()["autoSnapshotId"]

    third = await _snapshot(db_client, novel_id, "셋")
    full = await _snapshot(db_client, novel_id, "넷")
    again = await db_client.post(f"/novels/{novel_id}/snapshots/{one}/restore")
    once_more = await db_client.post(f"/novels/{novel_id}/snapshots/{one}/restore")

    assert third.status_code == 201
    assert (full.status_code, full.json()["detail"]) == (409, {"code": "NOVEL_SNAPSHOT_LIMIT"})
    assert again.status_code == 200 and once_more.status_code == 200
    rows = (
        await db_session.execute(
            sa.select(NovelSnapshot.id, NovelSnapshot.name, NovelSnapshot.kind).where(
                NovelSnapshot.novel_id == novel_id
            )
        )
    ).all()
    assert sorted((name, kind) for _id, name, kind in rows) == [
        ("「하나」 복원 직전", "auto_before_restore"),
        ("둘", "manual"),
        ("셋", "manual"),
        ("하나", "manual"),
    ]
    assert uuid.UUID(auto) not in {row_id for row_id, _name, _kind in rows}
    assert uuid.UUID(once_more.json()["autoSnapshotId"]) in {row_id for row_id, _name, _kind in rows}


async def test_deleting_a_snapshot_and_an_unknown_one(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    novel_id, _chapters = await _novel_with_two_episodes(db_client, db_session, monkeypatch)
    snapshot_id = (await _snapshot(db_client, novel_id)).json()["id"]

    deleted = await db_client.delete(f"/novels/{novel_id}/snapshots/{snapshot_id}")
    again = await db_client.delete(f"/novels/{novel_id}/snapshots/{snapshot_id}")
    detail = await db_client.get(f"/novels/{novel_id}/snapshots/{snapshot_id}")

    assert deleted.status_code == 204
    assert (again.status_code, again.json()["detail"]) == (404, {"code": "NOVEL_SNAPSHOT_NOT_FOUND"})
    assert detail.status_code == 404
    assert (await db_client.get(f"/novels/{novel_id}/snapshots")).json()["items"] == []


async def test_restore_does_not_append_a_merged_memo_again_to_a_card_made_after_the_snapshot(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """남는 카드가 스냅샷 뒤에 생긴 카드면 합치기가 이미 `[이름] 메모` 를 이어 두었다. 복원이 다시 이으면 복원할 때마다 같은
    줄이 쌓이고, 그 메모가 다음 묶음 생성 입력에 실린다."""
    novel_id, _chapters = await _novel_with_two_episodes(db_client, db_session, monkeypatch)
    kim = NovelCharacter(novel_id=novel_id, name="김철수", memo="m1")
    db_session.add(kim)
    await db_session.commit()
    snapshot_id = (await _snapshot(db_client, novel_id)).json()["id"]
    later = NovelCharacter(novel_id=novel_id, name="철수")
    db_session.add(later)
    await db_session.commit()
    await db_client.post(f"/novels/{novel_id}/characters/{kim.id}/merge", json={"intoCharacterId": str(later.id)})

    first = await db_client.post(f"/novels/{novel_id}/snapshots/{snapshot_id}/restore")
    second = await db_client.post(f"/novels/{novel_id}/snapshots/{snapshot_id}/restore")

    assert (first.status_code, second.status_code) == (200, 200)
    (card,) = (await db_client.get(f"/novels/{novel_id}/characters")).json()["items"]
    assert (card["name"], card["memo"]) == ("철수", "[김철수] m1")


async def test_restoring_an_auto_snapshot_at_the_cap_does_not_rotate_it_away(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """상한에서 자리를 낼 때 가장 오래된 자동 스냅샷을 지우는데, 지금 복원하는 것이 바로 그 자동 스냅샷일 수 있다 — 지우면
    사용자가 고른 판이 복원과 함께 사라진다."""
    monkeypatch.setattr(settings, "novelize_snapshot_limit", 2)
    novel_id, _chapters = await _novel_with_two_episodes(db_client, db_session, monkeypatch)
    one = (await _snapshot(db_client, novel_id, "하나")).json()["id"]
    auto = (await db_client.post(f"/novels/{novel_id}/snapshots/{one}/restore")).json()["autoSnapshotId"]

    resp = await db_client.post(f"/novels/{novel_id}/snapshots/{auto}/restore")

    assert resp.status_code == 200, resp.text
    kept = (await db_client.get(f"/novels/{novel_id}/snapshots/{auto}")).status_code
    assert kept == 200
