"""소설 구조화 호출 네 단계(문단 수정·여러 문단 수정·묶음 재검사·묶음 경계)가 모델 배정 표의 소설 칸을 읽는 것.

이 네 호출은 작업 모델과 무관해 칸이 (소설 레인, `any`, 단계) 하나다. 행이 쓰이면 그 행의 체인 세트로 문안을 렌더하고 행의 부를
모델을 호출 문맥(`LLMCallContext.call_model`)에 싣는다. 행이 없거나, 있어도 지금 env 로 쓸 수 없어 해석이 건너뛰면 지금까지와
같다 — 소설 Gemini 체인 세트를 한 번 읽고 부를 모델을 싣지 않는다. 늘어나는 것은 호출마다 배정 표 읽기 한 번뿐이다. 생성 세
단계(화·전체 구성안·장면 구성안)는 행이 있어도 체인·부를 모델이 작업 모델 그대로라 표를 읽지 않으며 여기서 다루지 않는다.

모델은 가짜이고 받은 호출 문맥을 그대로 적는다. 소설 레인 세트 읽기와 배정 표 읽기는 입력 조립 모듈(`novelize/inputs.py`)의
이름을 감싸 센다 — 네 호출 자리가 모두 그 모듈의 함수로 읽는다. Claude 행은 운영 env 에서는 경로가 맞지 않아 해석이 건너뛰므로,
쓰이는 경우는 그 호출 위치를 Anthropic 직결로 배정한 설정 패치로만 만든다."""

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat.prompt_builder import PromptLane, PromptRenderError, load_active_prompt_set
from api.chat.prompt_routing import PromptRoutes
from api.chat.prompt_routing_cache import invalidate_prompt_routes, load_prompt_routes
from api.core import clover
from api.core.config import settings
from api.db.models import ChatRoom, Novel, NovelChapter, NovelChapterRevision, NovelJob
from api.db.models.prompt import PromptRoute, PromptSection, PromptSet
from api.llm.call_policy import LLMCallSite
from api.llm.chat_models import PromptSetModelId
from api.llm.client import LLMCallContext, LLMClient, T
from api.novelize import billing, inputs, runner
from api.novelize import router as novelize_router
from api.novelize.block_edits import BlockEdit, request_targets
from api.novelize.text import split_paragraphs
from factories import (
    _add_chapter,
    _batch_output,
    _clear_llm_override,
    _edited_recheck_bundle,
    _make_user_with_clover_lot,
    _novel_setup,
    _open_room,
    _override_llm_client,
    _room_messages,
)

pytestmark = pytest.mark.usefixtures("novel_prices_for_flow_tests")

_PARAGRAPHS = ["첫 문단이다.", "둘째 문단이다.", "셋째 문단이다.", "넷째 문단이다."]
_BODY = "비가 내리는 저녁이었다. 서진은 가방을 내려놓고 창가에 섰다.\n\n" + "도윤이 잔을 밀어 주었다. " * 20
_EDIT_COST = 20
# 스키마 이름 → 가짜 모델의 응답. 모두 합성 문장이다.
_ANSWERS: dict[str, dict[str, Any]] = {
    "NovelizeReviseResult": {"paragraphs": ["고친 둘째 문단이다."]},
    "NovelizeBlockEditResult": {"patches": [{"paragraph": 2, "paragraphs": ["고친 둘째 문단이다."]}], "bundles": []},
    "NovelizeRecheckResult": {"separable": False, "reason": "남은 수정안이 고치기 전 이름을 쓴다."},
    "NovelizeBoundaryResult": {"end_turn": 1, "reason": "장면이 매듭지어진다."},
}


class _StructuredLLM(LLMClient):
    """소설 구조화 호출 페이크. 스키마마다 정해 둔 응답을 돌려주고 (스키마 이름, 호출 문맥)을 적는다. 화 생성 스트림(연쇄 시험의
    자식)은 한 화짜리 출력을 흘린다."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, LLMCallContext]] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        yield _batch_output(_BODY)

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        raise AssertionError("소설화는 지시문 없는 구조화 호출을 쓰지 않는다")

    async def generate_structured_with_instruction(
        self, prompt: str, response_schema: type[T], *, system_instruction: str, usage: LLMCallContext
    ) -> T:
        self.calls.append((response_schema.__name__, usage))
        return response_schema.model_validate(_ANSWERS[response_schema.__name__])

    def usages(self, schema: str) -> list[LLMCallContext]:
        return [usage for name, usage in self.calls if name == schema]


@dataclass
class _Reads:
    """입력 조립 모듈이 읽은 배정 표 횟수와, 소설 레인 세트를 읽은 체인 순서."""

    routes: int = 0
    novel_sets: list[str] = field(default_factory=list)

    def clear(self) -> None:
        self.routes = 0
        self.novel_sets = []


@pytest.fixture(autouse=True)
def _slow_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "novelize_heartbeat_interval_seconds", 3600)
    monkeypatch.setattr(settings, "novelize_heartbeat_expiry_seconds", 60)


@pytest.fixture(autouse=True)
def llm() -> Iterator[_StructuredLLM]:
    fake = _StructuredLLM()
    _override_llm_client(fake)
    yield fake
    _clear_llm_override()


@pytest.fixture
def reads(monkeypatch: pytest.MonkeyPatch) -> _Reads:
    seen = _Reads()

    async def routes(db: AsyncSession) -> PromptRoutes:
        seen.routes += 1
        return await load_prompt_routes(db)

    async def prompt_set(
        db: AsyncSession, *, lane: PromptLane, model: PromptSetModelId = "gemini"
    ) -> tuple[PromptSet, list[PromptSection]]:
        if lane == "novel":
            seen.novel_sets.append(model)
        return await load_active_prompt_set(db, lane=lane, model=model)

    monkeypatch.setattr(f"{inputs.__name__}.load_prompt_routes", routes)
    monkeypatch.setattr(f"{inputs.__name__}.load_active_prompt_set", prompt_set)
    return seen


def _direct(monkeypatch: pytest.MonkeyPatch, *call_sites: LLMCallSite) -> None:
    """그 호출 위치들을 Anthropic 직결로 배정한다. 모델 id 는 구조화 깊이 검사에 걸리지 않는 고정 값이다."""
    monkeypatch.setattr(settings, "llm_call_site_backends", dict.fromkeys(call_sites, "anthropic"))
    monkeypatch.setattr(settings, "anthropic_haiku_model_id", "fixture-anthropic-haiku")
    monkeypatch.setattr(settings, "anthropic_sonnet_model_id", "fixture-anthropic-sonnet")
    monkeypatch.setattr(settings, "anthropic_opus_model_id", "fixture-anthropic-opus")
    monkeypatch.setattr(settings, "anthropic_structured_effort", "low")


async def _put_rows(db: AsyncSession, *rows: tuple[str, str, str, str]) -> None:
    """(단계, 읽을 체인, 부를 모델, 경로) 행을 소설 구조화 칸에 넣는다. 준비 단계(방 열기)가 빈 표를 이미 캐시했을 수 있어,
    어드민 저장처럼 커밋 뒤 캐시를 지운다."""
    for stage, chain_model, call_model, backend in rows:
        db.add(
            PromptRoute(
                lane="novel",
                room_model="any",
                stage=stage,
                chain_model=chain_model,
                call_model=call_model,
                backend=backend,
            )
        )
    await db.commit()
    await invalidate_prompt_routes()


async def _drop_channel(db: AsyncSession, model: PromptSetModelId, channel: str) -> None:
    """그 소설 체인 활성 세트에서 한 채널의 섹션을 지운다(테스트 트랜잭션 안이라 롤백된다)."""
    prompt_set, _ = await load_active_prompt_set(db, lane="novel", model=model)
    await db.execute(
        sa.delete(PromptSection).where(PromptSection.prompt_set_id == prompt_set.id, PromptSection.channel == channel)
    )
    await db.commit()


def _factory(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")


def _base_usage(call_site: LLMCallSite, user_id: uuid.UUID, room_id: uuid.UUID | None) -> LLMCallContext:
    """배정 표를 읽기 전 코드가 만들던 호출 문맥 — 부를 모델을 싣지 않는다."""
    return LLMCallContext(call_site=call_site, user_id=user_id, room_id=room_id)


# ── 작업 실행(문단 수정·여러 문단 수정) ─────────────────────────────────────────
async def _chapter(db_client: httpx.AsyncClient, db_session: AsyncSession) -> tuple[Novel, NovelChapter]:
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
    chapter = await _add_chapter(
        db_session, novel.id, room, messages[0], room.turns[1][1], body="\n\n".join(_PARAGRAPHS)
    )
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


async def _job(db: AsyncSession, job_id: uuid.UUID) -> NovelJob:
    job = await db.scalar(sa.select(NovelJob).where(NovelJob.id == job_id).execution_options(populate_existing=True))
    assert job is not None
    return job


async def _paragraph_edit(db: AsyncSession, novel: Novel, chapter: NovelChapter) -> NovelJob:
    base = await _current(db, chapter.id)
    job = NovelJob(
        novel_id=novel.id,
        user_id=novel.user_id,
        kind="ai_edit",
        chapter_id=chapter.id,
        base_revision_id=base.id,
        paragraph_start=1,
        paragraph_end=1,
        instruction="더 쓸쓸하게",
    )
    return await billing.create_charged_job(db, job=job, expected_cost=_EDIT_COST, now=datetime.now(UTC))


async def _block_edit(db: AsyncSession, novel: Novel, chapter: NovelChapter) -> NovelJob:
    base = await _current(db, chapter.id)
    targets = request_targets([base.block_ids[1]], base.block_ids, split_paragraphs(base.body))
    job = NovelJob(
        novel_id=novel.id,
        user_id=novel.user_id,
        kind="ai_edit",
        chapter_id=chapter.id,
        base_revision_id=base.id,
        instruction="더 쓸쓸하게",
        block_edit=BlockEdit(targets=targets, scene_id=None).to_json(),
    )
    return await billing.create_charged_job(db, job=job, expected_cost=_EDIT_COST, now=datetime.now(UTC))


async def _run(db_session: AsyncSession, llm: _StructuredLLM, job: NovelJob) -> NovelJob:
    await runner.run_job(_factory(db_session), llm, job.id)
    return await _job(db_session, job.id)


async def test_an_empty_table_leaves_both_revise_jobs_as_they_were(
    db_client: httpx.AsyncClient, db_session: AsyncSession, llm: _StructuredLLM, reads: _Reads
) -> None:
    """빈 표의 문단 수정·여러 문단 수정은 배정 표를 읽기 전과 같다 — 소설 Gemini 체인 세트 한 번(라벨도 같은 세트라 더 읽지
    않는다), 부를 모델을 싣지 않은 호출 문맥, 정액 차감. 늘어난 것은 작업마다 배정 표 읽기 한 번이다. 깨지는 시나리오: 빈 표에서도
    부를 모델(`gemini`)을 실어 호출 문맥의 비교·해시가 달라지거나, 체인을 다시 읽어 세트 조회가 늘어난다."""
    novel, chapter = await _chapter(db_client, db_session)
    base = _base_usage("novelize_revise", novel.user_id, novel.chat_room_id)

    reads.clear()
    edited = await _run(db_session, llm, await _paragraph_edit(db_session, novel, chapter))
    assert (reads.routes, reads.novel_sets) == (1, ["gemini"])

    reads.clear()
    blocked = await _run(db_session, llm, await _block_edit(db_session, novel, chapter))
    assert (reads.routes, reads.novel_sets) == (1, ["gemini"])

    assert llm.calls == [("NovelizeReviseResult", base), ("NovelizeBlockEditResult", base)]
    assert all(usage.call_model is None for _, usage in llm.calls)
    assert [(job.status, job.charged_amount) for job in (edited, blocked)] == [
        ("succeeded", _EDIT_COST),
        ("succeeded", _EDIT_COST),
    ]


@pytest.mark.parametrize(
    "stages",
    [
        pytest.param(("novel_revise",), id="revise-row-only"),
        pytest.param(("novel_revise_blocks",), id="blocks-row-only"),
        pytest.param(("novel_revise", "novel_revise_blocks"), id="both-rows"),
    ],
)
async def test_each_revise_job_reads_its_own_stage_row_though_both_share_a_call_site(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _StructuredLLM,
    reads: _Reads,
    stages: tuple[str, ...],
) -> None:
    """문단 수정은 `novel_revise` 칸, 여러 문단 수정은 `novel_revise_blocks` 칸을 읽는다 — 같은 호출 위치(`novelize_revise`)를
    쓰지만 단계는 갈래로 고른다. 행이 있는 칸은 그 체인 세트로 렌더하고(라벨은 Gemini 체인 세트에서 한 번 더 읽는다) 부를 모델을
    싣고, 행이 없는 칸은 빈 표와 같다. 차감은 부를 모델과 무관하게 정액이다. 깨지는 시나리오: 한쪽 행이 다른 쪽 갈래에 새어 여러
    문단 수정이 문단 수정의 체인·모델로 불리거나, 부를 모델을 싣지 않아 행이 Haiku 를 골라도 기본 모델로 간다."""
    _direct(monkeypatch, "novelize_revise")
    rows = {
        "novel_revise": ("novel_revise", "opus", "sonnet", "anthropic"),
        "novel_revise_blocks": ("novel_revise_blocks", "sonnet", "haiku", "anthropic"),
    }
    await _put_rows(db_session, *(rows[stage] for stage in stages))
    novel, chapter = await _chapter(db_client, db_session)

    reads.clear()
    edited = await _run(db_session, llm, await _paragraph_edit(db_session, novel, chapter))
    edit_sets = reads.novel_sets
    reads.clear()
    blocked = await _run(db_session, llm, await _block_edit(db_session, novel, chapter))
    block_sets = reads.novel_sets

    (edit_usage,) = llm.usages("NovelizeReviseResult")
    (block_usage,) = llm.usages("NovelizeBlockEditResult")
    if "novel_revise" in stages:
        assert (edit_usage.call_model, edit_sets) == ("sonnet", ["opus", "gemini"])
    else:
        assert (edit_usage.call_model, edit_sets) == (None, ["gemini"])
    if "novel_revise_blocks" in stages:
        assert (block_usage.call_model, block_sets) == ("haiku", ["sonnet", "gemini"])
    else:
        assert (block_usage.call_model, block_sets) == (None, ["gemini"])
    assert (edit_usage.call_site, block_usage.call_site) == ("novelize_revise", "novelize_revise")
    assert (edit_usage.model, block_usage.model) == ("gemini", "gemini")
    assert [(job.status, job.charged_amount, job.refunded_amount) for job in (edited, blocked)] == [
        ("succeeded", _EDIT_COST, None),
        ("succeeded", _EDIT_COST, None),
    ]


async def test_a_claude_row_without_a_direct_assignment_is_skipped_and_the_job_runs_as_before(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _StructuredLLM,
    reads: _Reads,
) -> None:
    """운영 env 그대로(소설 구조화 호출 위치에 배정 없음)면 Claude 모델은 기본 구현 Bedrock 으로 가 행의 직결 경로와 맞지 않는다.
    해석이 그 행을 건너뛰므로 작업은 빈 표와 같은 체인·호출 문맥으로 돈다. 깨지는 시나리오: 건너뛴 행의 체인이나 부를 모델을
    그대로 실어, 저장 검사가 막았어야 할 경로로 호출이 간다."""
    _direct(monkeypatch)
    await _put_rows(
        db_session,
        ("novel_revise", "opus", "sonnet", "anthropic"),
        ("novel_revise_blocks", "opus", "haiku", "anthropic"),
    )
    novel, chapter = await _chapter(db_client, db_session)

    reads.clear()
    await _run(db_session, llm, await _paragraph_edit(db_session, novel, chapter))
    await _run(db_session, llm, await _block_edit(db_session, novel, chapter))

    base = _base_usage("novelize_revise", novel.user_id, novel.chat_room_id)
    assert llm.calls == [("NovelizeReviseResult", base), ("NovelizeBlockEditResult", base)]
    assert (reads.routes, reads.novel_sets) == (2, ["gemini", "gemini"])


async def test_a_gemini_row_carries_its_call_model_and_reads_the_gemini_chain(
    db_client: httpx.AsyncClient, db_session: AsyncSession, llm: _StructuredLLM, reads: _Reads
) -> None:
    """Gemini 행도 쓰인 행이라 부를 모델(`gemini`)을 싣는다 — 체인·실제 모델은 빈 표와 같다(배정 없이 쓸 수 있는 유일한 쌍)."""
    await _put_rows(db_session, ("novel_revise", "gemini", "gemini", "gemini"))
    novel, chapter = await _chapter(db_client, db_session)

    reads.clear()
    await _run(db_session, llm, await _paragraph_edit(db_session, novel, chapter))

    ((_, usage),) = llm.calls
    assert usage == LLMCallContext(
        call_site="novelize_revise", user_id=novel.user_id, room_id=novel.chat_room_id, call_model="gemini"
    )
    assert reads.novel_sets == ["gemini"]


async def test_the_prompt_dump_names_the_row_model_and_the_row_chain_set(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _StructuredLLM,
    tmp_path: Path,
) -> None:
    """측정 덤프의 실제로 보낸 모델 id(`callModel`)와 소설 세트 id(`novelSetId`)는 행대로다 — 덤프는 호출 문맥과 렌더한 프롬프트를
    그대로 읽으므로 칸을 더하지 않아도 따라온다. 깨지는 시나리오: 덤프가 행을 모르는 채 Gemini 모델 id 와 Gemini 세트를 적어 리플레이가
    다른 호출을 다시 보낸다."""
    _direct(monkeypatch, "novelize_revise")
    dump = tmp_path / "novel-dump.jsonl"
    monkeypatch.setattr(settings, "novel_prompt_dump_path", str(dump))
    await _put_rows(db_session, ("novel_revise", "opus", "haiku", "anthropic"))
    novel, chapter = await _chapter(db_client, db_session)
    opus_set, _ = await load_active_prompt_set(db_session, lane="novel", model="opus")

    await _run(db_session, llm, await _paragraph_edit(db_session, novel, chapter))

    (line,) = dump.read_text(encoding="utf-8").splitlines()
    record = json.loads(line)
    assert (record["callSite"], record["callModel"], record["novelSetId"]) == (
        "novelize_revise",
        "fixture-anthropic-haiku",
        str(opus_set.id),
    )


async def test_a_row_chain_without_the_channel_fails_the_edit_with_a_refund_before_any_call(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _StructuredLLM,
) -> None:
    """행의 체인 세트에 그 채널이 없으면 렌더가 실패하고, 작업은 지금 렌더 실패와 같은 꼴로 끝난다 — 모델을 부르지 않고 내부 오류로
    실패해 낸 몫을 돌려준다. 저장 검사가 채널 있는 체인만 받으므로 운영에서는 드물다."""
    _direct(monkeypatch, "novelize_revise")
    await _put_rows(db_session, ("novel_revise", "opus", "sonnet", "anthropic"))
    await _drop_channel(db_session, "opus", "novelize_revise")
    novel, chapter = await _chapter(db_client, db_session)

    stored = await _run(db_session, llm, await _paragraph_edit(db_session, novel, chapter))

    assert llm.calls == []
    assert (stored.status, stored.failure_code, stored.charged_amount, stored.refunded_amount) == (
        "failed",
        "internal",
        _EDIT_COST,
        _EDIT_COST,
    )


# ── 묶음 재검사(동기 요청) ───────────────────────────────────────────────────────
async def test_an_empty_table_leaves_the_recheck_call_as_it_was(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _StructuredLLM,
    reads: _Reads,
) -> None:
    """빈 표의 재검사는 소설 Gemini 체인 세트 한 번, 부를 모델 없는 호출 문맥이다. 늘어난 것은 배정 표 읽기 한 번이다."""
    _job_id, url, novel = await _edited_recheck_bundle(db_client, db_session, monkeypatch)

    reads.clear()
    resp = await db_client.post(url)

    assert resp.status_code == 200, resp.text
    assert llm.calls == [
        ("NovelizeRecheckResult", _base_usage("novelize_revise_recheck", novel.user_id, novel.chat_room_id))
    ]
    assert (reads.routes, reads.novel_sets) == (1, ["gemini"])


@pytest.mark.parametrize(
    ("direct", "expected"),
    [
        pytest.param(True, ("sonnet", ["opus", "gemini"]), id="direct-assignment-applies-the-row"),
        pytest.param(False, (None, ["gemini"]), id="no-assignment-skips-the-row"),
    ],
)
async def test_the_recheck_reads_its_row_when_the_route_matches_and_skips_it_otherwise(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _StructuredLLM,
    reads: _Reads,
    direct: bool,
    expected: tuple[str | None, list[str]],
) -> None:
    """재검사 칸(`novel_recheck`)의 행은 재검사 호출 위치가 직결로 배정돼 있을 때만 쓰인다 — 그러면 그 체인으로 렌더하고 부를
    모델을 싣는다. 배정이 없으면 건너뛰어 빈 표와 같다. 다른 단계(문단 수정)의 행은 재검사에 닿지 않는다."""
    assigned: tuple[LLMCallSite, ...] = ("novelize_revise_recheck",) if direct else ()
    _direct(monkeypatch, *assigned)
    await _put_rows(
        db_session,
        ("novel_recheck", "opus", "sonnet", "anthropic"),
        ("novel_revise", "sonnet", "haiku", "anthropic"),
    )
    _job_id, url, _novel = await _edited_recheck_bundle(db_client, db_session, monkeypatch)

    reads.clear()
    resp = await db_client.post(url)

    assert resp.status_code == 200, resp.text
    ((_, usage),) = llm.calls
    assert (usage.call_site, usage.call_model, reads.novel_sets) == ("novelize_revise_recheck", *expected)


async def test_a_row_chain_without_the_recheck_channel_fails_as_a_render_error_before_the_call(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _StructuredLLM,
) -> None:
    """행의 체인 세트에 재검사 채널이 없으면 지금 렌더 실패와 같은 꼴이다 — 모델을 부르기 전에 렌더 오류가 요청 밖으로 나간다
    (500, 묶음에는 아무것도 쓰지 않았다)."""
    _direct(monkeypatch, "novelize_revise_recheck")
    await _put_rows(db_session, ("novel_recheck", "opus", "sonnet", "anthropic"))
    await _drop_channel(db_session, "opus", "novelize_revise_recheck")
    _job_id, url, _novel = await _edited_recheck_bundle(db_client, db_session, monkeypatch)

    with pytest.raises(PromptRenderError):
        await db_client.post(url)

    assert llm.calls == []


# ── 묶음 경계(제안 요청·연쇄 생성) ─────────────────────────────────────────────────
async def test_an_empty_table_leaves_the_boundary_proposal_as_it_was(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _StructuredLLM,
    reads: _Reads,
) -> None:
    """빈 표의 경계 제안은 소설 Gemini 체인 세트 한 번, 부를 모델 없는 호출 문맥이다. 늘어난 것은 배정 표 읽기 한 번이다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)

    reads.clear()
    resp = await db_client.post(f"/novels/{novel_id}/chapter-proposal")

    assert resp.status_code == 200, resp.text
    assert resp.json()["suggestion"] is not None
    assert llm.calls == [("NovelizeBoundaryResult", _base_usage("novelize_boundary", room.user_id, room.room_id))]
    assert (reads.routes, reads.novel_sets) == (1, ["gemini"])


@pytest.mark.parametrize(
    ("direct", "expected"),
    [
        pytest.param(True, ("haiku", ["opus", "gemini"]), id="direct-assignment-applies-the-row"),
        pytest.param(False, (None, ["gemini"]), id="no-assignment-skips-the-row"),
    ],
)
async def test_the_boundary_proposal_reads_its_row_when_the_route_matches_and_skips_it_otherwise(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _StructuredLLM,
    reads: _Reads,
    direct: bool,
    expected: tuple[str | None, list[str]],
) -> None:
    """경계 칸(`novel_boundary`)의 행은 경계 호출 위치가 직결로 배정돼 있을 때만 쓰인다. 쓰이면 그 체인으로 렌더하고(원문 줄
    라벨은 Gemini 체인 세트에서 읽는다) 부를 모델을 싣는다. 무과금이라 원장은 그대로다."""
    assigned: tuple[LLMCallSite, ...] = ("novelize_boundary",) if direct else ()
    _direct(monkeypatch, *assigned)
    await _put_rows(db_session, ("novel_boundary", "opus", "haiku", "anthropic"))
    _room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)

    reads.clear()
    resp = await db_client.post(f"/novels/{novel_id}/chapter-proposal")

    assert resp.status_code == 200, resp.text
    ((_, usage),) = llm.calls
    assert (usage.call_site, usage.call_model, reads.novel_sets) == ("novelize_boundary", *expected)


async def test_a_row_chain_without_the_boundary_channel_answers_without_a_suggestion(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _StructuredLLM,
) -> None:
    """행의 체인 세트에 경계 채널이 없으면 지금 렌더 실패와 같은 꼴이다 — 모델을 부르지 않고 200 에 제안 없음이다(경계는 사람이
    고른다)."""
    _direct(monkeypatch, "novelize_boundary")
    await _put_rows(db_session, ("novel_boundary", "opus", "haiku", "anthropic"))
    await _drop_channel(db_session, "opus", "novelize_boundary")
    _room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)

    resp = await db_client.post(f"/novels/{novel_id}/chapter-proposal")

    assert resp.status_code == 200, resp.text
    assert resp.json()["suggestion"] is None
    assert llm.calls == []


async def test_the_chain_boundary_reads_the_boundary_row(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _StructuredLLM,
    reads: _Reads,
) -> None:
    """연쇄 생성이 묶음마다 자동으로 고르는 경계도 같은 칸을 읽는다 — 경계 모달의 제안과 같은 판정이어야 해서다. 자식 화 생성은
    작업 모델로 부르고 배정 표를 읽지 않는다."""
    _direct(monkeypatch, "novelize_boundary")
    await _put_rows(db_session, ("novel_boundary", "sonnet", "haiku", "anthropic"))
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    await clover.grant(db_session, user_id=room.user_id, amount=2000, kind="admin_grant")
    await db_session.commit()
    started: list[uuid.UUID] = []

    async def record(_factory: Any, _llm: Any, job_id: uuid.UUID) -> None:
        started.append(job_id)

    monkeypatch.setattr(novelize_router, "enqueue_chain_job", record)
    estimate = await db_client.get(f"/novels/{novel_id}/chain-estimate")
    assert estimate.status_code == 200, estimate.text
    (option,) = [o for o in estimate.json()["options"] if o["model"] == "gemini"]
    created = await db_client.post(
        f"/novels/{novel_id}/chain",
        json={"model": "gemini", "expectedCost": option["cost"] // option["batchCount"], "maxBatches": 1},
    )
    assert created.status_code == 202, created.text

    reads.clear()
    await runner.run_chain(_factory(db_session), llm, started[0])

    (usage,) = llm.usages("NovelizeBoundaryResult")
    assert (usage.call_site, usage.call_model) == ("novelize_boundary", "haiku")
    assert reads.routes == 1
    assert reads.novel_sets[:2] == ["sonnet", "gemini"]
