"""소설 작업 행을 종류(·하위 칸)로 걸러 읽는 서버 조회 자리마다, 지금 그 조회가 고르는 작업 갈래 집합을 리터럴로 고정한다.

작업 행의 종류 칸(`kind`)만으로는 실행 경로가 갈리지 않는다 — 장 생성은 연쇄 부모 아래의 자식과 혼자 도는 생성으로, 다시 만들기는
옛 흐름 묶음과 구성 흐름 화로, AI 수정은 연속 범위 수정과 여러 문단 수정으로 다시 나뉜다. 그래서 갈래 열 개를 각각 칸 조합이 다른
작업 행 하나로 만들어 넣고(`_variant_row`), 실제 조회 함수를 불러 어느 갈래의 행이 걸렸는지 본다. 기대 집합은 코드에서 끌어내지
않고 손으로 적은 리터럴이다 — 조회 조건을 다른 표현으로 옮기는 변경이 고르는 행을 몰래 바꾸면(가령 종류 하나에 묶인 두 갈래 중
하나를 놓치면) 여기서 깨진다.

갈래마다 다른 칸만 채우고, 나머지 조건(상태·지시문·결과 본문·기준 개정 등)은 그 조회의 다른 조건을 모두 통과하도록 모든 행에
같게 채운다 — 걸러지는 이유가 종류·하위 칸뿐이게. 작업 표의 CHECK 가 허락하지 않는 조합(패치 칸을 가진 AI 수정 밖의 행, 패치
칸과 결과 본문을 함께 가진 행)은 만들지 않는다."""

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core.config import settings
from api.db.models import ChatMessage, ChatRoom, Novel, NovelChapter, NovelChapterRevision, NovelJob, User
from api.db.models.novel import NovelBatch, NovelJobStatus
from api.novelize import billing, worker
from api.novelize import router as novelize_router
from api.novelize.block_edits import BlockEdit, BlockEditPatch, block_hash
from api.novelize.blocks import build_revision
from api.novelize.deletion import erase_stale_ai_edit_previews
from api.novelize.schemas import NovelChapterSummary
from api.novelize.writing_lock import first_saved_chapter_at
from factories import _make_user, _make_user_with_clover_lot, _open_room, revision_row

pytestmark = pytest.mark.usefixtures("novel_prices_for_flow_tests")

# 갈래 열 개. 이름은 실행 경로를 가리킨다 — 혼자 도는 장 생성, 연쇄 자식, 연쇄 부모, 옛 흐름 다시 만들기, 구성 흐름 화 다시 만들기,
# 연속 범위 문단 수정, 여러 문단 수정, 전체 구성안, 장면 구성안, 구성 흐름 원고.
VARIANTS = (
    "legacy_generate",
    "chain_child",
    "chain_parent",
    "legacy_regenerate",
    "outline_regenerate",
    "paragraph_edit",
    "block_edit",
    "outline",
    "episode_outline",
    "manuscript",
)


def _variant_row(
    variant: str,
    *,
    novel_id: uuid.UUID,
    user_id: uuid.UUID,
    status: NovelJobStatus,
    start: ChatMessage | None = None,
    episode_outline_id: uuid.UUID | None = None,
    **extra: Any,
) -> NovelJob:
    """갈래 하나의 작업 행. 갈래를 가르는 칸(종류·연쇄 부모·장면 구성안 리비전·패치 칸·구성안 대상)은 여기서 정하고, 조회의 다른
    조건을 맞추는 칸은 `extra` 로 받는다. 칸 조합은 실제 라우트가 만드는 행을 따른다. 시작·끝 메시지는 실제로 그 칸을 갖는
    갈래(장 생성·연쇄 자식·옛 흐름 다시 만들기·구성 흐름 원고)에만 싣는다 — 원고 라우트는 장면 구성안이 쓰는 첫·끝 메시지를 싣고,
    구성 흐름 화의 다시 만들기는 원문 구간이 아니라 장면 구성안으로 쓰므로 시작 메시지도 구성안 화 키도 비어 있다."""
    outline_id = episode_outline_id or uuid.uuid4()
    key = uuid.uuid4()
    columns: dict[str, Any] = {"novel_id": novel_id, "user_id": user_id, "status": status, "charged_amount": 0}
    segment: dict[str, Any] = {}
    if start is not None:
        segment = {
            "start_message_id": start.id,
            "start_message_created_at": start.created_at,
            "end_message_id": start.id,
            "end_message_created_at": start.created_at,
        }
    if variant == "legacy_generate":
        columns.update(kind="chapter_generate", **segment)
    elif variant == "chain_child":
        columns.update(kind="chapter_generate", parent_job_id=uuid.uuid4(), **segment)
    elif variant == "chain_parent":
        columns.update(kind="chain_generate", planned_batches=1, batch_k_max=1, unit_price=40)
    elif variant == "legacy_regenerate":
        columns.update(kind="chapter_regenerate", **segment)
    elif variant == "outline_regenerate":
        columns.update(kind="chapter_regenerate", episode_outline_id=outline_id)
    elif variant == "paragraph_edit":
        columns.update(kind="ai_edit")
    elif variant == "block_edit":
        columns.update(kind="ai_edit", block_edit=BlockEdit(targets=[], scene_id=None).to_json())
    elif variant == "outline":
        columns.update(kind="outline_generate")
    elif variant == "episode_outline":
        columns.update(kind="episode_outline_generate", outline_id=uuid.uuid4(), outline_episode_key=key)
    elif variant == "manuscript":
        columns.update(kind="outline_chapter_generate", episode_outline_id=outline_id, outline_episode_key=key, **segment)
    else:
        raise AssertionError(f"모르는 갈래: {variant}")
    columns.update(extra)
    if variant == "block_edit":
        # 패치 칸이 있는 행은 CHECK 상 결과 본문·범위를 가질 수 없다.
        for name in ("result_text", "paragraph_start", "paragraph_end"):
            columns.pop(name, None)
    if status in ("queued", "running"):
        columns.setdefault("heartbeat_at", sa.func.now())
    if status == "succeeded":
        columns.setdefault("finished_at", sa.func.now())
    return NovelJob(**columns)


def _factory(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")


async def _bare_novel(db: AsyncSession, user_id: uuid.UUID) -> Novel:
    """방 없는 소설 한 권(과금하지 않는 조회용). 진행 중 작업은 소설마다 하나뿐이라 대기 행을 넣을 소설을 갈래마다 따로 둔다."""
    novel = Novel(
        user_id=user_id,
        chat_room_id=None,
        content_id=uuid.uuid4(),
        content_type="character",
        content_title="원작",
        character_name="인물",
    )
    db.add(novel)
    await db.flush()
    return novel


async def _owner(db: AsyncSession) -> User:
    user = _make_user()
    db.add(user)
    await db.flush()
    return user


async def _chapter_with_two_revisions(
    db: AsyncSession, novel_id: uuid.UUID
) -> tuple[NovelChapter, NovelChapterRevision, NovelChapterRevision]:
    """화 하나와 개정 둘. 둘째 개정은 블록 id 는 같고 둘째 문단의 글만 다르다 — 첫 개정을 기준으로 한 결과는 낡았다."""
    now = datetime.now(UTC)
    segment: dict[str, Any] = {
        "start_message_id": uuid.uuid4(),
        "start_message_created_at": now,
        "end_message_id": uuid.uuid4(),
        "end_message_created_at": now,
        "assistant_message_count": 1,
        "source_hash": "0" * 64,
    }
    batch = NovelBatch(novel_id=novel_id, ordinal=1, target_episode_count=1, **segment)
    db.add(batch)
    await db.flush()
    chapter = NovelChapter(novel_id=novel_id, ordinal=1, batch_id=batch.id, episode_index=0, **segment)
    db.add(chapter)
    await db.flush()
    first = revision_row(chapter_id=chapter.id, revision_no=1, body="첫 문단이다.\n\n둘째 문단이다.", source="generate")
    db.add(first)
    await db.flush()
    second = build_revision(
        chapter_id=chapter.id,
        revision_no=2,
        body="첫 문단이다.\n\n사용자가 고친 둘째 문단이다.",
        source="manual_edit",
        block_ids=list(first.block_ids),
    )
    db.add(second)
    await db.flush()
    return chapter, first, second


def _picked(rows: dict[str, NovelJob], ids: set[uuid.UUID]) -> set[str]:
    return {variant for variant, row in rows.items() if row.id in ids}


# ── 실행 · 워커 ──────────────────────────────────────────────────────────────
async def test_the_worker_claims_every_queued_variant_but_the_chain_parent_and_its_children(
    db_session: AsyncSession,
) -> None:
    """워커가 집는 대기 행은 연쇄 부모(부모는 자기 경로가 돌린다)와 연쇄 자식(부모가 직접 돌린다)을 뺀 여덟 갈래다. 연쇄 자식은
    혼자 도는 장 생성과 종류가 같아, 종류 목록이 아니라 연쇄 부모 칸이 비었는지로 걸러진다. 깨지는 시나리오: 종류 목록을 갈래에서
    끌어내며 부모 칸 조건을 지워 워커가 부모가 돌리고 있는 자식을 한 번 더 돌리거나, 종류 하나에 묶인 갈래 하나를 놓친다."""
    owner = await _owner(db_session)
    rows: dict[str, NovelJob] = {}
    for variant in VARIANTS:
        novel = await _bare_novel(db_session, owner.id)
        rows[variant] = _variant_row(variant, novel_id=novel.id, user_id=owner.id, status="queued")
        db_session.add(rows[variant])
    await db_session.commit()

    claimed = await worker.claim_candidates(_factory(db_session), 1000)

    assert _picked(rows, set(claimed)) == {
        "legacy_generate",
        "legacy_regenerate",
        "outline_regenerate",
        "paragraph_edit",
        "block_edit",
        "outline",
        "episode_outline",
        "manuscript",
    }


# ── 라우트 · 조회 ────────────────────────────────────────────────────────────
async def test_the_last_chapter_model_reads_only_jobs_that_wrote_chapters(db_session: AsyncSession) -> None:
    """지금 쓸 모델을 읽는 "최근 화 모델"은 화를 쓴 성공 작업만 본다 — 장 생성(연쇄 자식 포함)·두 다시 만들기·구성 흐름 원고. 연쇄
    부모·AI 수정·구성안 두 종은 화를 쓰지 않아 세지 않는다. 갈래마다 따로 소설을 두고 그 행 하나에 상위 모델을 적어, 그 모델이
    읽히는지로 본다. 깨지는 시나리오: 연쇄 부모의 모델이 읽혀 화를 쓴 적 없는 모델이 다음 화의 기본값이 된다."""
    owner = await _owner(db_session)
    rows: dict[str, NovelJob] = {}
    novels: dict[str, uuid.UUID] = {}
    for variant in VARIANTS:
        novel = await _bare_novel(db_session, owner.id)
        novels[variant] = novel.id
        rows[variant] = _variant_row(variant, novel_id=novel.id, user_id=owner.id, status="succeeded", model="opus")
        db_session.add(rows[variant])
    await db_session.commit()

    read = {
        variant
        for variant in VARIANTS
        if await novelize_router._last_chapter_model(db_session, novels[variant], allowed=True) == "opus"
    }

    assert read == {"legacy_generate", "chain_child", "legacy_regenerate", "outline_regenerate", "manuscript"}


async def test_the_first_saved_chapter_time_counts_only_jobs_that_create_chapters(db_session: AsyncSession) -> None:
    """집필권 잠금을 뒤늦게 채우는 "첫 화 저장 시각"은 새 화를 만드는 성공 작업만 센다 — 혼자 도는 장 생성·연쇄 자식·구성 흐름
    원고. 다시 만들기는 이미 있는 화를 고치므로 세지 않는다. 깨지는 시나리오: 연쇄 자식이 빠져 연쇄로만 첫 화를 쓴 소설이 잠기지
    않거나, 다시 만들기가 세어 잠금 시각이 앞당겨진다."""
    owner = await _owner(db_session)
    novels: dict[str, uuid.UUID] = {}
    for variant in VARIANTS:
        novel = await _bare_novel(db_session, owner.id)
        novels[variant] = novel.id
        db_session.add(_variant_row(variant, novel_id=novel.id, user_id=owner.id, status="succeeded"))
    await db_session.commit()

    counted = {variant for variant in VARIANTS if await first_saved_chapter_at(db_session, novels[variant]) is not None}

    assert counted == {"legacy_generate", "chain_child", "manuscript"}


# ── 과금: 하루 상한 세기 ─────────────────────────────────────────────────────
async def _room_novel(db_client: httpx.AsyncClient, db_session: AsyncSession, owner: User) -> tuple[Novel, ChatMessage]:
    """과금할 수 있는 소설(방·원작이 실제로 있다)과 그 방의 첫 메시지."""
    room = await _open_room(db_client, db_session, turns=1, lane="character", user=owner)
    chat_room = await db_session.get_one(ChatRoom, room.room_id)
    novel = Novel(
        user_id=owner.id,
        chat_room_id=room.room_id,
        content_id=chat_room.content_id,
        content_type="character",
        content_title="원작",
        character_name="캐릭터",
        protagonist_name="서진",
    )
    db_session.add(novel)
    await db_session.flush()
    first = await db_session.scalar(
        sa.select(ChatMessage)
        .where(ChatMessage.chat_room_id == room.room_id)
        .order_by(ChatMessage.created_at, ChatMessage.id)
        .limit(1)
    )
    assert first is not None
    return novel, first


async def _refused_by_daily_cap(db: AsyncSession, probe: NovelJob, cost: int) -> bool:
    """과금은 세이브포인트로 묶인 별도 세션에서 부른다. 거절 경로의 롤백이 테스트 세션에서 일어나면 테스트 전체를 감싼 바깥
    트랜잭션까지 되감겨, 앞 회차까지 만든 소유자·방·소설이 다음 회차에서 사라진다."""
    async with _factory(db)() as service:
        try:
            await billing.create_charged_job(service, job=probe, expected_cost=cost, now=datetime.now(UTC))
        except HTTPException as exc:
            assert exc.status_code == 429, exc.detail
            return True
    return False


async def test_the_daily_cap_on_one_start_message_counts_generates_children_and_old_regenerates(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """같은 시작 메시지의 하루 상한은 장 생성·다시 만들기 종류 중 그 시작 메시지를 가진 행을 센다 — 혼자 도는 장 생성, 연쇄 자식,
    옛 흐름 다시 만들기. 구성 흐름 화의 다시 만들기는 시작 메시지가 비어 있어, 구성 흐름 원고는 같은 시작 메시지를 가져도 종류가
    달라 걸리지 않는다. 상한을 1 로 두고 갈래 행 하나가 있는 소설에 같은 시작 메시지의 장 생성을 넣어 거절되는지로 본다. 깨지는
    시나리오: 세기를 갈래 단위로 좁혀 연쇄 자식이 빠지고, 연쇄로 쓴 구간을 같은 날 몇 번이고 다시 산다."""
    monkeypatch.setattr(settings, "novelize_chapter_daily_limit", 1)
    owner = await _make_user_with_clover_lot(db_session, clover_balance=1000)
    refused: set[str] = set()
    for variant in VARIANTS:
        novel, first = await _room_novel(db_client, db_session, owner)
        db_session.add(
            _variant_row(
                variant,
                novel_id=novel.id,
                user_id=owner.id,
                status="succeeded",
                start=first,
                episode_outline_id=uuid.uuid4(),
            )
        )
        await db_session.commit()
        probe = NovelJob(
            novel_id=novel.id,
            user_id=owner.id,
            kind="chapter_generate",
            start_message_id=first.id,
            start_message_created_at=first.created_at,
            end_message_id=first.id,
            end_message_created_at=first.created_at,
        )
        if await _refused_by_daily_cap(db_session, probe, 40):
            refused.add(variant)

    assert refused == {"legacy_generate", "chain_child", "legacy_regenerate"}


async def test_the_daily_cap_on_one_scene_outline_counts_manuscripts_and_outline_regenerates(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """같은 장면 구성안 리비전의 하루 상한은 구성 흐름 원고와 다시 만들기 종류 중 그 리비전을 가진 행을 센다 — 원고와 구성 흐름
    화의 다시 만들기. 옛 흐름 다시 만들기는 리비전 칸이 비어 있어 걸리지 않는다. 깨지는 시나리오: 같은 장면 구성안으로 원고와
    다시 만들기를 번갈아 사서 상한을 비켜 간다."""
    monkeypatch.setattr(settings, "novelize_chapter_daily_limit", 1)
    owner = await _make_user_with_clover_lot(db_session, clover_balance=1000)
    refused: set[str] = set()
    for variant in VARIANTS:
        novel, first = await _room_novel(db_client, db_session, owner)
        scene_outline = uuid.uuid4()
        db_session.add(
            _variant_row(
                variant,
                novel_id=novel.id,
                user_id=owner.id,
                status="succeeded",
                start=first,
                episode_outline_id=scene_outline,
            )
        )
        await db_session.commit()
        probe = NovelJob(
            novel_id=novel.id,
            user_id=owner.id,
            kind="outline_chapter_generate",
            model="gemini",
            episode_outline_id=scene_outline,
            outline_episode_key=uuid.uuid4(),
        )
        if await _refused_by_daily_cap(db_session, probe, 40):
            refused.add(variant)

    assert refused == {"outline_regenerate", "manuscript"}


# ── 미결 수정 목록 · 낡은 수정 비우기 ─────────────────────────────────────────
def _edit_columns(chapter: NovelChapter, base: NovelChapterRevision) -> dict[str, Any]:
    """수정 목록·비우기 조회의 종류 밖 조건을 모두 통과하는 칸 — 장·기준 개정·범위·지시문·결과 본문(패치 행은 결과 본문·범위를
    갖지 못해 `_variant_row` 가 뺀다)."""
    return {
        "chapter_id": chapter.id,
        "base_revision_id": base.id,
        "paragraph_start": 1,
        "paragraph_end": 1,
        "instruction": "더 쓸쓸하게",
        "result_text": "첫 문단이다.\n\n쓸쓸한 둘째 문단.",
    }


def _pending_patch(base: NovelChapterRevision) -> dict[str, Any]:
    """기준 개정 둘째 블록을 고친 대기 패치 하나를 가진 패치 칸."""
    patch = BlockEditPatch(
        id="p1",
        block_id=base.block_ids[1],
        base_hash=block_hash("둘째 문단이다."),
        paragraphs=["쓸쓸한 둘째 문단."],
        state="pending",
    )
    return BlockEdit(targets=[], scene_id=None, patches=[patch]).to_json()


async def _edit_rows(
    db: AsyncSession, novel_id: uuid.UUID, user_id: uuid.UUID, chapter: NovelChapter, base: NovelChapterRevision
) -> dict[str, NovelJob]:
    rows: dict[str, NovelJob] = {}
    for variant in VARIANTS:
        row = _variant_row(variant, novel_id=novel_id, user_id=user_id, status="succeeded", **_edit_columns(chapter, base))
        if variant == "block_edit":
            row.block_edit = _pending_patch(base)
        rows[variant] = row
        db.add(row)
    await db.commit()
    return rows


async def test_the_pending_edit_lists_pick_only_their_own_kind_of_edit(db_session: AsyncSession) -> None:
    """상세의 미결 목록 둘은 AI 수정 종류만 본다 — 연속 범위 미리보기 목록은 결과 본문이 있는 행이라 문단 수정만, 대기 패치 목록은
    패치 칸이 있는 행이라 여러 문단 수정만 걸린다. 다른 종류의 행이 같은 칸을 가져도 싣지 않는다. 깨지는 시나리오: 종류 조건을
    갈래 사실로 옮기며 문단 수정 목록에 다른 종류의 결과 본문이 섞여 적용 버튼이 엉뚱한 작업을 가리킨다."""
    owner = await _owner(db_session)
    novel = await _bare_novel(db_session, owner.id)
    chapter, _, current = await _chapter_with_two_revisions(db_session, novel.id)
    rows = await _edit_rows(db_session, novel.id, owner.id, chapter, current)
    summary = NovelChapterSummary.model_construct(id=chapter.id, current_revision_id=current.id)

    previews = await novelize_router._pending_ai_edits(db_session, novel.id, [summary])
    patches = await novelize_router._pending_block_edits(db_session, novel.id, [summary])

    assert _picked(rows, {edit.id for edit in previews}) == {"paragraph_edit"}
    assert _picked(rows, {edit.id for edit in patches}) == {"block_edit"}


async def test_erasing_stale_edits_clears_only_ai_edit_previews_and_patches(db_session: AsyncSession) -> None:
    """화의 글이 바뀐 뒤 낡은 수정 비우기는 AI 수정 종류만 고친다 — 결과 본문을 비우는 쪽은 문단 수정만, 패치를 낡음으로 바꾸는
    쪽은 여러 문단 수정만. 다른 종류의 행은 같은 낡은 기준 개정·지시문·결과 본문을 가져도 그대로다. 깨지는 시나리오: 비우기 조건을
    옮기며 다른 종류 행의 지시문이 지워지거나(처리방침의 즉시 삭제 대상이 아닌 기록 손실), 낡은 미리보기가 남는다."""
    owner = await _owner(db_session)
    novel = await _bare_novel(db_session, owner.id)
    chapter, first, _ = await _chapter_with_two_revisions(db_session, novel.id)
    rows = await _edit_rows(db_session, novel.id, owner.id, chapter, first)

    await erase_stale_ai_edit_previews(db_session, chapter.id)
    await db_session.commit()

    stored = {
        job.id: job
        for job in (
            await db_session.scalars(
                sa.select(NovelJob)
                .where(NovelJob.id.in_([row.id for row in rows.values()]))
                .execution_options(populate_existing=True)
            )
        ).all()
    }
    cleared = {variant for variant, row in rows.items() if stored[row.id].result_text is None and variant != "block_edit"}
    staled = {
        variant
        for variant, row in rows.items()
        if (edit := stored[row.id].block_edit) is not None and [p["state"] for p in edit["patches"]] == ["stale"]
    }
    assert cleared == {"paragraph_edit"}
    assert staled == {"block_edit"}
