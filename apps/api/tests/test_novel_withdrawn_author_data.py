"""숨겨 남긴 팔린 소설(게시자 탈퇴·작가의 삭제) — 독자가 읽는 것만 남기고 작가 전용 데이터를 지운다.

정책 스위치(`novel_public_policy_v2_enabled`)가 켜져 있으면 탈퇴와 작가의 삭제는 팔린 소설을 지우지 않고 숨겨 남긴다(산 사람이 계속 읽는다).
남기는 것은 공개 상태 행, 화 공개본과 판 행, 그 둘이 가리키는 개정과 화 행뿐이다. 스냅숏·등장인물·작가 읽은 자리·설정 노트·
주인공 이름·작업본 제목과 소개·편집 보드·표지 연결·공개되지 않은 화와 개정, 화의 작업본 제목·요약·작가의 말은 지운다. 이미
숨겨 남은 소설(배포 겹침 동안 옛 이미지가 숨긴 것, 숨긴 직후 늦게 도착한 작가 쓰기)은 하루 한 번 파기 크론이 같은 정리를 한다.

공개 소설은 `_make_public_novel`(6화 + 2화 묶음, 전부 공개, 앞 5화 무료)로 만든다."""

import uuid
from dataclasses import dataclass

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models import Asset, AssetKind, AssetStatus, User
from api.db.models.novel import (
    Novel,
    NovelBatch,
    NovelChapter,
    NovelChapterCharacter,
    NovelChapterEdition,
    NovelChapterIllustration,
    NovelChapterPublication,
    NovelChapterRevision,
    NovelCharacter,
    NovelComment,
    NovelJob,
    NovelPurchase,
    NovelReaderPosition,
    NovelReadingPosition,
    NovelScreening,
    NovelSnapshot,
)
from api.novelize import illustrations
from factories import (
    revision_row,
    PublicNovel,
    _create_admin,
    _login_as,
    _login_as_admin,
    _make_asset,
    _make_public_novel,
    _make_user,
    _make_user_with_clover_lot,
)


@pytest.fixture(autouse=True)
def _switches_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novel_public_enabled", True)
    monkeypatch.setattr(settings, "novel_public_policy_v2_enabled", True)


@dataclass(frozen=True)
class Planted:
    """`_plant_author_data` 가 심은 것. 6화는 판 둘(1판 = 산 판, 2판 = 지금 판)과 그 사이·뒤의 공개되지 않은 개정을 갖는다."""

    novel: PublicNovel
    buyer_id: uuid.UUID
    first_edition_revision_id: uuid.UUID
    current_revision_id: uuid.UUID
    draft_revision_ids: tuple[uuid.UUID, ...]
    unpublished_chapter_id: uuid.UUID
    unpublished_batch_id: uuid.UUID
    kept_screening_id: uuid.UUID


async def _member(db_session: AsyncSession) -> uuid.UUID:
    user = await _make_user_with_clover_lot(db_session, clover_balance=100)
    await db_session.commit()
    return user.id


async def _plant_author_data(db_client: httpx.AsyncClient, db_session: AsyncSession) -> Planted:
    """게시자 한 명의 공개 소설에 산 사람 하나(6화를 1판으로 삼)와 작가 전용 데이터 전부를 심는다(커밋)."""
    publisher = _make_user()
    db_session.add(publisher)
    await db_session.flush()
    novel = await _make_public_novel(db_session, publisher.id)
    await db_session.commit()
    buyer = await _member(db_session)
    await _login_as(db_client, buyer)
    bought = await db_client.post(
        f"/webnovels/{novel.novel_id}/chapters/{novel.chapter_ids[5]}/purchase", json={"expectedPrice": 30}
    )
    assert bought.status_code == 200, bought.text

    sixth = novel.chapter_ids[5]
    first_edition = await db_session.scalar(
        sa.select(NovelChapterPublication.revision_id).where(NovelChapterPublication.chapter_id == sixth)
    )
    assert first_edition is not None
    await db_session.execute(
        sa.update(NovelChapterRevision).where(NovelChapterRevision.id == first_edition).values(body="6화 첫 판")
    )
    # 1판과 2판 사이의 초고, 그 초고를 되돌리기 원본으로 가리키는 2판, 2판 뒤의 초고.
    between = revision_row(chapter_id=sixth, revision_no=2, body="6화 사이 초고", source="manual_edit")
    db_session.add(between)
    await db_session.flush()
    current = revision_row(
        chapter_id=sixth, revision_no=3, body="6화 둘째 판", source="revert", reverted_from_revision_id=between.id
    )
    db_session.add(current)
    await db_session.flush()
    latest = revision_row(chapter_id=sixth, revision_no=4, body="6화 마지막 초고", source="manual_edit")
    db_session.add(latest)
    db_session.add_all(
        [
            NovelChapterEdition(chapter_id=sixth, edition=1, novel_id=novel.novel_id, revision_id=first_edition),
            NovelChapterEdition(chapter_id=sixth, edition=2, novel_id=novel.novel_id, revision_id=current.id),
        ]
    )
    await db_session.execute(
        sa.update(NovelChapterPublication)
        .where(NovelChapterPublication.chapter_id == sixth)
        .values(revision_id=current.id, edition=2)
    )

    # 공개되지 않은 9화(묶음 하나).
    batch = NovelBatch(
        novel_id=novel.novel_id,
        ordinal=3,
        target_episode_count=1,
        start_message_id=uuid.uuid4(),
        start_message_created_at=sa.func.now(),
        end_message_id=uuid.uuid4(),
        end_message_created_at=sa.func.now(),
        assistant_message_count=1,
        source_hash="0" * 64,
    )
    db_session.add(batch)
    await db_session.flush()
    unpublished = NovelChapter(
        novel_id=novel.novel_id,
        ordinal=9,
        batch_id=batch.id,
        episode_index=0,
        start_message_id=uuid.uuid4(),
        start_message_created_at=sa.func.now(),
        end_message_id=uuid.uuid4(),
        end_message_created_at=sa.func.now(),
        assistant_message_count=1,
        source_hash="0" * 64,
        title="9화 작업 제목",
    )
    db_session.add(unpublished)
    await db_session.flush()
    unpublished_revision = revision_row(
        chapter_id=unpublished.id, revision_no=1, body="9화 초고", source="generate"
    )
    db_session.add(unpublished_revision)

    # 작가 전용 — 인물 카드·등장 인물·스냅숏·작가 읽은 자리·작업본 칸.
    card = NovelCharacter(novel_id=novel.novel_id, name="작가가 지은 인물", memo="작가 메모")
    db_session.add(card)
    await db_session.flush()
    kept_screening = NovelScreening(
        novel_id=novel.novel_id,
        chapter_id=sixth,
        chapter_ordinal=6,
        user_id=publisher.id,
        outcome="passed",
        model="gemini-test",
    )
    db_session.add_all(
        [
            NovelChapterCharacter(chapter_id=sixth, character_id=card.id),
            NovelChapterCharacter(chapter_id=unpublished.id, character_id=card.id),
            NovelSnapshot(novel_id=novel.novel_id, name="저장", kind="manual", payload={"v": 1, "chapters": []}),
            NovelReadingPosition(
                chapter_id=sixth,
                novel_id=novel.novel_id,
                paragraph_index=0,
                paragraph_count=1,
                revision_id=latest.id,
            ),
            kept_screening,
            NovelScreening(
                novel_id=novel.novel_id,
                chapter_id=unpublished.id,
                chapter_ordinal=9,
                user_id=publisher.id,
                outcome="rejected",
                flagged_parts=["chapter_body"],
                reason="9화 초고를 옮겨 적은 사유",
                model="gemini-test",
            ),
            # 산 사람의 기록 — 남는다.
            NovelReaderPosition(
                user_id=buyer, chapter_id=sixth, novel_id=novel.novel_id, paragraph_index=0, paragraph_count=1, edition=1
            ),
            NovelComment(novel_id=novel.novel_id, chapter_id=sixth, author_user_id=buyer, body="독자 댓글"),
        ]
    )
    # 끝난 AI 수정 작업(지시문·결과 본문)과 표지 연결 — 표지는 탈퇴 파기가 지우지 않는 업로드 이미지로 걸어, 연결을 끊는 것이
    # 정리임을 본다.
    db_session.add(
        NovelJob(
            novel_id=novel.novel_id,
            user_id=publisher.id,
            kind="ai_edit",
            status="succeeded",
            chapter_id=sixth,
            base_revision_id=latest.id,
            instruction="작가의 수정 지시",
            result_text="수정 결과",
            charged_amount=1,
        )
    )
    cover = await _make_asset(db_session, publisher.id)
    await db_session.execute(
        sa.update(Novel)
        .where(Novel.id == novel.novel_id)
        .values(
            cover_asset_id=cover.id,
            setting_notes="작가 설정 노트",
            protagonist_name="대화 프로필 이름",
            title="작업본 제목",
            title_edited_at=sa.func.now(),
            synopsis="작업본 소개",
            board_layout={"nodes": {"a": [1, 2]}},
        )
    )
    await db_session.execute(
        sa.update(NovelChapter)
        .where(NovelChapter.novel_id == novel.novel_id, NovelChapter.ordinal <= 8)
        .values(title="작업 제목", title_edited_at=sa.func.now(), summary="작업 요약", author_note="작업 작가의 말")
    )
    await db_session.commit()
    return Planted(
        novel=novel,
        buyer_id=buyer,
        first_edition_revision_id=first_edition,
        current_revision_id=current.id,
        draft_revision_ids=(between.id, latest.id),
        unpublished_chapter_id=unpublished.id,
        unpublished_batch_id=batch.id,
        kept_screening_id=kept_screening.id,
    )


async def _count(db_session: AsyncSession, model: type, *where: sa.ColumnElement[bool]) -> int:
    return (await db_session.scalar(sa.select(sa.func.count()).select_from(model).where(*where))) or 0


async def _assert_only_reader_rows_remain(db_session: AsyncSession, planted: Planted) -> None:
    novel_id = planted.novel.novel_id
    chapters = sa.select(NovelChapter.id).where(NovelChapter.novel_id == novel_id)
    assert set(
        (await db_session.scalars(chapters.order_by(NovelChapter.ordinal))).all()
    ) == set(planted.novel.chapter_ids)
    assert set(
        (await db_session.scalars(sa.select(NovelBatch.id).where(NovelBatch.novel_id == novel_id))).all()
    ) == set(planted.novel.batch_ids)
    revisions = {
        revision.id: revision
        for revision in (
            await db_session.scalars(
                sa.select(NovelChapterRevision)
                .where(NovelChapterRevision.chapter_id.in_(chapters))
                .execution_options(populate_existing=True)
            )
        ).all()
    }
    published = set(
        (
            await db_session.scalars(
                sa.select(NovelChapterPublication.revision_id).where(NovelChapterPublication.novel_id == novel_id)
            )
        ).all()
    )
    assert set(revisions) == published | {planted.first_edition_revision_id}
    assert not set(planted.draft_revision_ids) & set(revisions)
    assert revisions[planted.current_revision_id].reverted_from_revision_id is None
    assert revisions[planted.current_revision_id].body == "6화 둘째 판"
    assert await _count(db_session, NovelChapterEdition, NovelChapterEdition.novel_id == novel_id) == 2

    for model in (NovelSnapshot, NovelCharacter, NovelReadingPosition, NovelJob):
        assert await _count(db_session, model, model.novel_id == novel_id) == 0, model.__name__
    assert await _count(db_session, NovelChapterCharacter, NovelChapterCharacter.chapter_id.in_(chapters)) == 0
    assert set(
        (await db_session.scalars(sa.select(NovelScreening.id).where(NovelScreening.novel_id == novel_id))).all()
    ) == {planted.kept_screening_id}

    novel = await db_session.get_one(Novel, novel_id, populate_existing=True)
    assert (
        novel.setting_notes,
        novel.protagonist_name,
        novel.title,
        novel.title_edited_at,
        novel.synopsis,
        novel.board_layout,
        novel.cover_asset_id,
    ) == ("", None, None, None, "", {}, None)
    assert (novel.content_title, novel.character_name, novel.hidden_at is not None) == ("원작", "인물", True)
    leftovers = (
        await db_session.execute(
            sa.select(NovelChapter.title, NovelChapter.title_edited_at, NovelChapter.summary, NovelChapter.author_note)
            .where(NovelChapter.novel_id == novel_id)
            .execution_options(populate_existing=True)
        )
    ).tuples().all()
    assert set(leftovers) == {(None, None, None, "")}

    # 산 사람의 기록은 남는다.
    assert await _count(db_session, NovelReaderPosition, NovelReaderPosition.novel_id == novel_id) == 1
    assert await _count(db_session, NovelComment, NovelComment.novel_id == novel_id) == 1
    assert await _count(db_session, NovelPurchase, NovelPurchase.novel_id == novel_id) == 1


async def _assert_readers_still_read(db_client: httpx.AsyncClient, db_session: AsyncSession, planted: Planted) -> None:
    """작품 정보·목차, 무료 화, 산 화(지금 판과 산 때의 판), 읽은 자리 저장, 소장 목록, 어드민 상세·화 보기가 그대로 열린다."""
    novel = planted.novel
    base = f"/webnovels/{novel.novel_id}"
    sixth = f"{base}/chapters/{novel.chapter_ids[5]}"
    await _login_as(db_client, planted.buyer_id)

    detail = await db_client.get(base)
    assert detail.status_code == 200, detail.text
    assert [chapter["ordinal"] for chapter in detail.json()["chapters"]] == list(range(1, 9))
    assert (detail.json()["title"], detail.json()["salesStopped"]) == ("공개 제목", True)
    free = await db_client.get(f"{base}/chapters/{novel.chapter_ids[0]}")
    assert (free.status_code, free.json()["paragraphs"]) == (200, ["1화 본문"])
    current = await db_client.get(sixth)
    assert current.status_code == 200, current.text
    assert (current.json()["paragraphs"], current.json()["edition"], current.json()["purchasedEdition"]["edition"]) == (
        ["6화 둘째 판"],
        2,
        1,
    )
    bought = await db_client.get(sixth, params={"edition": 1})
    assert (bought.status_code, bought.json()["paragraphs"], bought.json()["edition"]) == (200, ["6화 첫 판"], 1)
    saved = await db_client.put(
        f"{sixth}/reading-position", json={"paragraphIndex": 0, "paragraphCount": 1, "edition": 2, "finished": True}
    )
    assert saved.status_code == 204, saved.text
    owned = await db_client.get("/webnovels/owned")
    assert [item["id"] for item in owned.json()["items"]] == [str(novel.novel_id)]

    admin = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin)
    admin_detail = await db_client.get(f"/admin/novels/{novel.novel_id}")
    assert admin_detail.status_code == 200, admin_detail.text
    assert len(admin_detail.json()["chapters"]) == 8
    admin_chapter = await db_client.get(f"/admin/novels/{novel.novel_id}/chapters/{novel.chapter_ids[5]}")
    assert (admin_chapter.status_code, admin_chapter.json()["paragraphs"]) == (200, ["6화 둘째 판"])


async def test_a_withdrawal_keeps_only_what_readers_read_of_a_sold_novel(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """게시자가 탈퇴하면 숨겨 남기는 팔린 소설에서 작가 전용 데이터가 사라지고, 화 공개본·판 행이 가리키는 개정과 화만 남는다
    — 산 사람의 지난 판도 남는다. 산 사람·운영자의 읽기 경로는 모두 그대로 열린다. 깨지는 시나리오: 탈퇴한 작가의 설정 노트·
    스냅숏·초고가 소장자 때문에 남거나, 정리가 산 사람이 고르는 지난 판의 본문까지 지운다."""
    planted = await _plant_author_data(db_client, db_session)

    await _login_as(db_client, planted.novel.publisher_id)
    assert (await db_client.delete("/me")).status_code == 204

    await _assert_only_reader_rows_remain(db_session, planted)
    await _assert_readers_still_read(db_client, db_session, planted)


async def test_deleting_a_sold_novel_keeps_only_what_readers_read_like_a_withdrawal(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """작가가 팔린 소설을 지우면 숨겨 남기는 소설에서 탈퇴 때와 같은 작가 전용 데이터가 사라지고, 화 공개본·판 행이 가리키는 개정과
    화만 남는다 — 산 사람의 지난 판도 남는다. 지운 초고만 쓰던 업로드 삽화는 파일까지 지운다. 산 사람·운영자의 읽기 경로는 모두
    그대로 열린다. 깨지는 시나리오: 작가가 지워 달라고 한 설정 노트·주인공 이름·스냅숏·초고가 소장자 때문에 남거나, 정리가 산 사람이
    고르는 지난 판의 본문까지 지우거나, 초고와 함께 행이 사라진 삽화 파일이 저장소에 고아로 남는다."""
    planted = await _plant_author_data(db_client, db_session)
    removed: list[str] = []
    monkeypatch.setattr(illustrations, "delete_object", removed.append)
    draft = await db_session.get_one(NovelChapterRevision, planted.draft_revision_ids[1])
    upload = Asset(
        owner_user_id=planted.novel.publisher_id,
        storage_key=f"{illustrations.UPLOAD_KEY_PREFIX}{uuid.uuid4()}.webp",
        kind=AssetKind.ORIGINAL,
        status=AssetStatus.READY,
        width=300,
        height=400,
    )
    db_session.add(upload)
    await db_session.flush()
    db_session.add(
        NovelChapterIllustration(
            revision_id=draft.id,
            anchor_block_id=draft.block_ids[0],
            placement="after",
            sort_order=0,
            asset_id=upload.id,
            source="upload",
        )
    )
    await db_session.commit()

    await _login_as(db_client, planted.novel.publisher_id)
    assert (await db_client.delete(f"/novels/{planted.novel.novel_id}")).status_code == 204

    await _assert_only_reader_rows_remain(db_session, planted)
    assert await db_session.get(Asset, upload.id, populate_existing=True) is None
    assert upload.storage_key in removed
    await _assert_readers_still_read(db_client, db_session, planted)


async def test_the_daily_purge_strips_author_data_left_on_a_hidden_novel(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """숨긴 소설에 작가 전용 데이터가 남아 있으면(배포 겹침 동안 옛 이미지가 정리 없이 숨겼거나, 숨긴 직후 늦게 도착한 작가 쓰기)
    하루 한 번 크론이 같은 정리를 하고 정리한 소설 수를 센다 — 게시자가 탈퇴해 숨긴 소설이든 살아 있는 작가가 지워 숨긴 소설이든
    같다. 두 번째 실행은 바꿀 것이 없어 0 이다. 숨기지 않은 소설은 건드리지 않는다. 깨지는 시나리오: 옛 이미지가 남긴 작가의
    초고가 기한 없이 남거나, 크론이 숨겨 남긴 것이 아닌 소설의 작업 데이터를 지운다."""
    from api.novelize.hidden_purge import strip_hidden_novels

    planted = await _plant_author_data(db_client, db_session)
    # 옛 이미지의 탈퇴 — 작가 행을 탈퇴로 표시하고 소설을 숨기기만 한다.
    await db_session.execute(
        sa.update(User).where(User.id == planted.novel.publisher_id).values(deleted_at=sa.func.now(), nickname=None)
    )
    await db_session.execute(
        sa.update(Novel).where(Novel.id == planted.novel.novel_id).values(hidden_at=sa.func.now(), chat_room_id=None)
    )
    cover = await _make_asset(db_session, planted.novel.publisher_id)
    await db_session.execute(sa.update(Novel).where(Novel.id == planted.novel.novel_id).values(cover_asset_id=cover.id))
    # 표지 연결만 남은 숨긴 소설 — 다른 작업 칸이 모두 비어 있어도 표지 연결은 끊는다.
    cover_only = await _make_public_novel(db_session, planted.novel.publisher_id)
    await db_session.execute(
        sa.update(Novel)
        .where(Novel.id == cover_only.novel_id)
        .values(hidden_at=sa.func.now(), cover_asset_id=cover.id)
    )
    living = _make_user()
    db_session.add(living)
    await db_session.flush()
    kept_by_author = await _make_public_novel(db_session, living.id)
    visible = await _make_public_novel(db_session, living.id)
    # 숨기지 않은 채 남은 탈퇴자의 소설(소설화 테이블을 모르던 옛 코드의 탈퇴가 남긴 꼴) — 숨겨 남긴 소설이 아니라 건드리지 않는다.
    unhidden = await _make_public_novel(db_session, planted.novel.publisher_id)
    untouched = [visible.novel_id, unhidden.novel_id]
    await db_session.execute(
        sa.update(Novel)
        .where(Novel.id.in_([*untouched, kept_by_author.novel_id]))
        .values(setting_notes="남아야 하는 노트")
    )
    await db_session.execute(
        sa.update(Novel).where(Novel.id == kept_by_author.novel_id).values(hidden_at=sa.func.now())
    )
    await db_session.commit()

    first = await strip_hidden_novels(db_session)
    again = await strip_hidden_novels(db_session)

    assert (first, again) == (3, 0)
    assert await db_session.scalar(
        sa.select(Novel.cover_asset_id)
        .where(Novel.id == cover_only.novel_id)
        .execution_options(populate_existing=True)
    ) is None
    await _assert_only_reader_rows_remain(db_session, planted)
    notes = (
        await db_session.scalars(
            sa.select(Novel.setting_notes).where(Novel.id.in_(untouched)).execution_options(populate_existing=True)
        )
    ).all()
    assert notes == ["남아야 하는 노트"] * 2
    assert await db_session.scalar(
        sa.select(Novel.setting_notes)
        .where(Novel.id == kept_by_author.novel_id)
        .execution_options(populate_existing=True)
    ) == ""
    await _assert_readers_still_read(db_client, db_session, planted)


async def test_a_withdrawal_with_the_policy_switch_off_still_deletes_the_whole_novel(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """스위치가 꺼져 있으면 탈퇴는 지금처럼 팔린 소설까지 통째로 지운다 — 정리는 숨겨 남길 때만 돈다. 깨지는 시나리오: 정리를
    넣으며 꺼짐의 탈퇴가 소설 일부(공개본·판)를 남긴다."""
    planted = await _plant_author_data(db_client, db_session)
    monkeypatch.setattr(settings, "novel_public_policy_v2_enabled", False)

    await _login_as(db_client, planted.novel.publisher_id)
    assert (await db_client.delete("/me")).status_code == 204

    assert await _count(db_session, Novel, Novel.id == planted.novel.novel_id) == 0
    assert await _count(db_session, NovelPurchase, NovelPurchase.novel_id == planted.novel.novel_id) == 1
