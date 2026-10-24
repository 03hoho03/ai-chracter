"""여러 문단 수정 작업의 실행 — 입력 조립(장면 문맥·대상 번호), 모델 응답 정리(대상 밖 패치 버림·묶음), 저장 때 패치 단위 낡음,
실패·환불. 모델은 가짜다.

작업은 `create_charged_job` 으로 만들고(차감 포함) `run_job` 을 직접 기다려 돌린다(`test_novelize_runner.py` 와 같은 방식)."""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core.config import settings
from api.db.models import ChatRoom, Novel, NovelChapter, NovelChapterRevision, NovelJob
from api.db.models.clover import CloverLedger
from api.db.models.novel import NovelEpisodeOutline, NovelJobFailureCode, NovelOutline, NovelSceneBlock
from api.llm.client import LLMCallContext, LLMClient, LLMTruncatedError, T
from api.novelize import billing, runner
from api.novelize.block_edits import BlockEdit, block_hash, request_targets
from api.novelize.blocks import build_revision
from api.novelize.text import split_paragraphs
from factories import _add_chapter, _make_user_with_clover_lot, _open_room, _room_messages, revision_row

pytestmark = pytest.mark.usefixtures("novel_prices_for_flow_tests")

_PARAGRAPHS = ["비가 내렸다.", "서진은 창가에 섰다.", "도윤이 잔을 밀었다.", "둘은 말이 없었다."]


class _BlockLLM(LLMClient):
    """여러 문단 수정 페이크. 구조화 호출에 `result`(응답 dict)를 돌려주거나 `error` 를 낸다. `during` 은 모델을 부르는 순간
    실행할 일이다."""

    def __init__(
        self,
        result: dict[str, Any] | None = None,
        *,
        error: Exception | None = None,
        during: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.result = result if result is not None else {"patches": [], "bundles": []}
        self.error = error
        self.during = during
        self.calls: list[tuple[str, str, LLMCallContext, type]] = []

    async def generate(
        self, prompt: str, system_instruction: str | None = None, stop_sequences: list[str] | None = None, *, usage: LLMCallContext
    ) -> AsyncIterator[str]:
        raise AssertionError("여러 문단 수정은 스트리밍 호출을 쓰지 않는다")
        yield ""  # pragma: no cover

    async def generate_structured(self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext) -> Any:
        raise AssertionError("소설화는 지시문 없는 구조화 호출을 쓰지 않는다")

    async def generate_structured_with_instruction(
        self, prompt: str, response_schema: type[T], *, system_instruction: str, usage: LLMCallContext
    ) -> T:
        self.calls.append((prompt, system_instruction, usage, response_schema))
        if self.during is not None:
            await self.during()
        if self.error is not None:
            raise self.error
        return response_schema.model_validate(self.result)


@pytest.fixture(autouse=True)
def _slow_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novelize_heartbeat_interval_seconds", 3600)


def _factory(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")


async def _chapter(
    db_client: httpx.AsyncClient, db_session: AsyncSession, paragraphs: list[str] = _PARAGRAPHS
) -> tuple[Novel, NovelChapter]:
    owner = await _make_user_with_clover_lot(db_session, clover_balance=100)
    room = await _open_room(db_client, db_session, turns=2, lane="character", user=owner)
    chat_room = await db_session.get_one(ChatRoom, room.room_id)
    novel = Novel(
        user_id=owner.id,
        chat_room_id=room.room_id,
        content_id=chat_room.content_id,
        content_type="character",
        content_title="원작",
        character_name="캐릭터",
        protagonist_name="서진",
        setting_notes="도윤은 서진의 소꿉친구다.",
    )
    db_session.add(novel)
    await db_session.commit()
    messages = await _room_messages(db_session, room.room_id)
    chapter = await _add_chapter(db_session, novel.id, room, messages[0], room.turns[1][1], body="\n\n".join(paragraphs))
    return novel, chapter


async def _current(db: AsyncSession, chapter_id: uuid.UUID) -> NovelChapterRevision:
    revision = await db.scalar(
        sa.select(NovelChapterRevision)
        .where(NovelChapterRevision.chapter_id == chapter_id)
        .order_by(NovelChapterRevision.revision_no.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    assert revision is not None
    return revision


async def _block_job(
    db: AsyncSession, novel: Novel, chapter: NovelChapter, positions: list[int], *, scene_id: str | None = None
) -> NovelJob:
    base = await _current(db, chapter.id)
    targets = request_targets([base.block_ids[i] for i in positions], base.block_ids, split_paragraphs(base.body))
    job = NovelJob(
        novel_id=novel.id,
        user_id=novel.user_id,
        kind="ai_edit",
        chapter_id=chapter.id,
        base_revision_id=base.id,
        instruction="더 쓸쓸하게",
        block_edit=BlockEdit(targets=targets, scene_id=scene_id).to_json(),
    )
    return await billing.create_charged_job(db, job=job, expected_cost=20, now=datetime.now(UTC))


async def _job(db: AsyncSession, job_id: uuid.UUID) -> NovelJob:
    job = await db.scalar(sa.select(NovelJob).where(NovelJob.id == job_id).execution_options(populate_existing=True))
    assert job is not None
    return job


async def _ledger(db: AsyncSession, user_id: uuid.UUID) -> list[tuple[str, int]]:
    rows = await db.execute(
        sa.select(CloverLedger.kind, CloverLedger.amount)
        .where(CloverLedger.user_id == user_id)
        .order_by(CloverLedger.amount, CloverLedger.kind)
    )
    return [(kind, amount) for kind, amount in rows.all()]


def _patches(job: NovelJob) -> list[tuple[str, str, list[str] | None]]:
    assert job.block_edit is not None
    return [(p["blockId"], p["state"], p["paragraphs"]) for p in job.block_edit["patches"]]


# ── 성공 ─────────────────────────────────────────────────────────────────────
async def test_a_block_edit_keeps_patches_for_the_targets_only_and_writes_no_revision(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """대상(2·4번 문단)만 패치로 남는다 — 모델이 대상이 아닌 3번 문단을 고쳐 보내도 버린다. 결과 본문·범위 칸은 비어 있고 새
    개정은 없으며 차감은 한 번이다. 프롬프트는 새 채널 문안으로 화 전체 문단을 번호와 함께, 고칠 문단 번호를 함께 싣고, 호출
    위치는 문단 수정과 같다(Gemini 고정·타임아웃 공유)."""
    novel, chapter = await _chapter(db_client, db_session)
    job = await _block_job(db_session, novel, chapter, [1, 3])
    base = await _current(db_session, chapter.id)
    llm = _BlockLLM(
        {
            "patches": [
                {"paragraph": 2, "paragraphs": ["[2] 서진은 젖은 창가에 섰다.", "빗소리가 들렸다."]},
                {"paragraph": 3, "paragraphs": ["대상이 아닌 문단을 고쳤다."]},
                {"paragraph": 4, "paragraphs": ["둘은 끝내 말이 없었다."]},
            ],
            "bundles": [{"paragraphs": [2, 4], "reason": "창가의 침묵이 이어진다"}],
        }
    )

    await runner.run_job(_factory(db_session), llm, job.id)

    stored = await _job(db_session, job.id)
    assert (stored.status, stored.result_text, stored.paragraph_start, stored.paragraph_end) == ("succeeded", None, None, None)
    assert stored.instruction == "더 쓸쓸하게"
    assert _patches(stored) == [
        (str(base.block_ids[1]), "pending", ["서진은 젖은 창가에 섰다.", "빗소리가 들렸다."]),
        (str(base.block_ids[3]), "pending", ["둘은 끝내 말이 없었다."]),
    ]
    assert stored.block_edit is not None
    assert [p["baseHash"] for p in stored.block_edit["patches"]] == [block_hash(_PARAGRAPHS[1]), block_hash(_PARAGRAPHS[3])]
    (bundle,) = stored.block_edit["bundles"]
    assert bundle["patchIds"] == [p["id"] for p in stored.block_edit["patches"]]
    assert bundle["reason"] == "창가의 침묵이 이어진다"
    assert (await _current(db_session, chapter.id)).revision_no == 1
    assert await _ledger(db_session, novel.user_id) == [("novelize_spend", -20)]
    prompt, system_instruction, usage, _schema = llm.calls[0]
    assert usage.call_site == "novelize_revise"
    assert "[고칠 문단]" in prompt and "2번, 4번" in prompt and "더 쓸쓸하게" in prompt
    assert all(f"[{n}] {text}" in prompt for n, text in enumerate(_PARAGRAPHS, start=1))
    assert "[고치는 규칙]" in system_instruction


async def test_a_target_the_model_leaves_alone_is_saved_without_its_base_hash(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """대상 셋 중 모델이 둘만 고쳐 보내면 저장된 칸에서 수정안이 없는 대상의 기준 해시만 지워진다 — 그 해시를 다시 읽을 판정이
    없고, 짧은 문단은 해시로 글을 되찾을 수 있다. 대기 패치의 대상·패치 해시는 적용 판정에 쓰므로 남는다."""
    novel, chapter = await _chapter(db_client, db_session)
    job = await _block_job(db_session, novel, chapter, [0, 1, 3])
    llm = _BlockLLM(
        {"patches": [{"paragraph": 1, "paragraphs": ["고친 첫째."]}, {"paragraph": 4, "paragraphs": ["고친 넷째."]}], "bundles": []}
    )

    await runner.run_job(_factory(db_session), llm, job.id)

    stored = await _job(db_session, job.id)
    assert stored.status == "succeeded" and stored.block_edit is not None
    kept = [block_hash(_PARAGRAPHS[0]), block_hash(_PARAGRAPHS[3])]
    assert [t["baseHash"] for t in stored.block_edit["targets"]] == [kept[0], "", kept[1]]
    assert [p["baseHash"] for p in stored.block_edit["patches"]] == kept


async def test_a_chapter_with_scenes_sends_only_the_target_scene_as_context(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """장면 있는 화는 대상 장면의 문단만 문맥으로 보낸다(번호는 화 전체 번호 그대로). 다른 장면 문단은 모델에 가지 않는다."""
    novel, chapter = await _chapter(db_client, db_session)
    base = await _current(db_session, chapter.id)
    outline = NovelOutline(novel_id=novel.id, revision=1, source="generate", selection_id=uuid.uuid4(), episodes=[])
    db_session.add(outline)
    await db_session.flush()
    episode = NovelEpisodeOutline(
        novel_id=novel.id, outline_id=outline.id, episode_key=uuid.uuid4(), revision=1, source="generate", scenes=[]
    )
    db_session.add(episode)
    await db_session.flush()
    db_session.add_all(
        NovelSceneBlock(block_id=block_id, chapter_id=chapter.id, episode_outline_id=episode.id, scene_id=scene)
        for block_id, scene in zip(base.block_ids, ["s1", "s1", "s2", "s2"], strict=True)
    )
    await db_session.commit()
    job = await _block_job(db_session, novel, chapter, [2], scene_id="s2")
    llm = _BlockLLM({"patches": [{"paragraph": 3, "paragraphs": ["도윤이 잔을 천천히 밀었다."]}], "bundles": []})

    await runner.run_job(_factory(db_session), llm, job.id)

    prompt = llm.calls[0][0]
    assert "[3] 도윤이 잔을 밀었다." in prompt and "[4] 둘은 말이 없었다." in prompt
    assert _PARAGRAPHS[0] not in prompt and _PARAGRAPHS[1] not in prompt
    assert (await _job(db_session, job.id)).status == "succeeded"


# ── 저장 때 낡음 ─────────────────────────────────────────────────────────────
async def test_a_target_the_user_edits_during_the_call_is_saved_stale_and_the_rest_stay_pending(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """모델을 부르는 동안 사용자가 대상 블록 하나를 직접 고치면 그 패치만 낡음(문단 비움)으로 저장되고 나머지는 대기다. 적용할
    패치가 남았으니 성공·차감 그대로다. 깨지는 시나리오: 한 블록이 바뀌었다고 쓸 수 있는 다른 패치까지 버리고 환불하거나, 바뀐
    블록의 패치가 대기로 남아 사용자 글을 덮어쓴다."""
    novel, chapter = await _chapter(db_client, db_session)
    job = await _block_job(db_session, novel, chapter, [0, 2])
    base = await _current(db_session, chapter.id)

    async def edit_meanwhile() -> None:
        body = "\n\n".join([_PARAGRAPHS[0], _PARAGRAPHS[1], "사용자가 고친 셋째.", _PARAGRAPHS[3]])
        db_session.add(
            build_revision(chapter_id=chapter.id, revision_no=2, body=body, source="manual_edit", block_ids=list(base.block_ids))
        )
        await db_session.commit()

    llm = _BlockLLM(
        {"patches": [{"paragraph": 1, "paragraphs": ["고친 첫째."]}, {"paragraph": 3, "paragraphs": ["고친 셋째."]}], "bundles": []},
        during=edit_meanwhile,
    )

    await runner.run_job(_factory(db_session), llm, job.id)

    stored = await _job(db_session, job.id)
    assert (stored.status, stored.refunded_at, stored.instruction) == ("succeeded", None, "더 쓸쓸하게")
    assert _patches(stored) == [(str(base.block_ids[0]), "pending", ["고친 첫째."]), (str(base.block_ids[2]), "stale", None)]
    assert await _ledger(db_session, novel.user_id) == [("novelize_spend", -20)]


async def test_an_edit_outside_the_targets_during_the_call_keeps_every_patch_pending(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """대상이 아닌 블록만 바뀌면 패치는 모두 대기다 — 화 전체 해시가 아니라 블록 단위로 본다(옛 수정은 이 경우 환불한다)."""
    novel, chapter = await _chapter(db_client, db_session)
    job = await _block_job(db_session, novel, chapter, [0])
    base = await _current(db_session, chapter.id)

    async def edit_meanwhile() -> None:
        body = "\n\n".join([_PARAGRAPHS[0], "사용자가 고친 둘째.", *_PARAGRAPHS[2:]])
        db_session.add(
            build_revision(chapter_id=chapter.id, revision_no=2, body=body, source="manual_edit", block_ids=list(base.block_ids))
        )
        await db_session.commit()

    llm = _BlockLLM({"patches": [{"paragraph": 1, "paragraphs": ["고친 첫째."]}], "bundles": []}, during=edit_meanwhile)

    await runner.run_job(_factory(db_session), llm, job.id)

    stored = await _job(db_session, job.id)
    assert stored.status == "succeeded"
    assert _patches(stored) == [(str(base.block_ids[0]), "pending", ["고친 첫째."])]


async def test_when_every_target_changes_during_the_call_the_job_is_refunded_as_source_changed(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """모든 패치가 낡으면 쓸 수 있는 결과가 없다 — 성공으로 저장하지 않고 `source_changed` 로 전액 환불하며 패치·지시문을 남기지
    않는다. 지운 블록도 낡음이다."""
    novel, chapter = await _chapter(db_client, db_session)
    job = await _block_job(db_session, novel, chapter, [0, 2])

    async def edit_meanwhile() -> None:
        db_session.add(revision_row(chapter_id=chapter.id, revision_no=2, body="완전히 다른 글.", source="manual_edit"))
        await db_session.commit()

    llm = _BlockLLM(
        {"patches": [{"paragraph": 1, "paragraphs": ["고친 첫째."]}, {"paragraph": 3, "paragraphs": ["고친 셋째."]}], "bundles": []},
        during=edit_meanwhile,
    )

    await runner.run_job(_factory(db_session), llm, job.id)

    stored = await _job(db_session, job.id)
    assert (stored.status, stored.failure_code, stored.instruction, stored.result_text) == (
        "failed",
        "source_changed",
        None,
        None,
    )
    assert stored.block_edit is not None and stored.block_edit["patches"] == []
    assert await _ledger(db_session, novel.user_id) == [("novelize_spend", -20), ("novelize_refund", 20)]


# ── 쓸 수 없는 응답 ─────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("result", "error", "code"),
    [
        pytest.param({"patches": [], "bundles": []}, None, "empty", id="no-patches"),
        pytest.param({"patches": [{"paragraph": 9, "paragraphs": ["대상 밖"]}], "bundles": []}, None, "empty", id="only-outside"),
        pytest.param({"patches": [{"paragraph": 1, "paragraphs": ["  "]}], "bundles": []}, None, "empty", id="blank"),
        pytest.param(
            {"patches": [{"paragraph": 1, "paragraphs": ["죄송하지만 그 요청은 도와드릴 수 없습니다."]}], "bundles": []},
            None,
            "refused",
            id="refusal",
        ),
        pytest.param(None, LLMTruncatedError("잘림"), "truncated", id="truncated"),
    ],
)
async def test_an_unusable_block_edit_is_refunded(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    result: dict[str, Any] | None,
    error: Exception | None,
    code: NovelJobFailureCode,
) -> None:
    novel, chapter = await _chapter(db_client, db_session)
    job = await _block_job(db_session, novel, chapter, [0])

    await runner.run_job(_factory(db_session), _BlockLLM(result, error=error), job.id)

    stored = await _job(db_session, job.id)
    assert (stored.status, stored.failure_code, stored.instruction) == ("failed", code, None)
    assert stored.block_edit is not None and stored.block_edit["patches"] == []
    assert await _ledger(db_session, novel.user_id) == [("novelize_spend", -20), ("novelize_refund", 20)]


async def test_the_old_range_edit_still_runs_through_the_old_channel(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """패치 칸이 없는 옛 AI 수정은 옛 입력·옛 응답 꼴 그대로 돌아 장 전체 결과 본문을 남긴다(새 분기를 타지 않는다)."""
    novel, chapter = await _chapter(db_client, db_session)
    base = await _current(db_session, chapter.id)
    job = await billing.create_charged_job(
        db_session,
        job=NovelJob(
            novel_id=novel.id,
            user_id=novel.user_id,
            kind="ai_edit",
            chapter_id=chapter.id,
            base_revision_id=base.id,
            paragraph_start=1,
            paragraph_end=1,
            instruction="더 쓸쓸하게",
        ),
        expected_cost=20,
        now=datetime.now(UTC),
    )

    class _RangeLLM(_BlockLLM):
        async def generate_structured_with_instruction(
            self, prompt: str, response_schema: type[T], *, system_instruction: str, usage: LLMCallContext
        ) -> T:
            self.calls.append((prompt, system_instruction, usage, response_schema))
            return response_schema.model_validate({"paragraphs": ["고친 둘째."]})

    llm = _RangeLLM()
    await runner.run_job(_factory(db_session), llm, job.id)

    stored = await _job(db_session, job.id)
    assert stored.result_text == "\n\n".join([_PARAGRAPHS[0], "고친 둘째.", *_PARAGRAPHS[2:]])
    assert stored.block_edit is None
    assert "2번 문단부터 2번 문단까지" in llm.calls[0][0]
