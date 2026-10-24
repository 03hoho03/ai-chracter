"""측정 하네스의 판정·요약·추출 세트 고르기가 측정 DB 의 모델 배정 표를 앱 방 턴과 같은 규칙으로 푼다 — 표가 비면 표를 넘기지 않은
앱 호출과 같은 세트, 행이 있으면 그 칸의 체인과 부를 모델, 칸은 방 주인의 실효 방 모델로 고른다. 하네스가 프로세스 안에서 부르는
앱의 접기·추출에도 그 칸의 부를 모델이 실린다. 문안은 전부 지어낸 것이다."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat import memory_episodes, memory_fold
from api.chat.prompt_builder import load_active_prompt_set
from api.chat.prompt_routing import ALLOWED_ROUTE_PAIRS, PromptRoutes, RouteRow, row_call_sites, row_route_problem
from api.chat.prompt_stages import LANE_STAGES, STAGES
from api.chat.turn_prompt import JudgmentPromptSets, judgment_prompt_sets
from api.core.config import settings
from api.db.models import ChatRoom
from api.db.models.prompt import PromptRoute, PromptSet
from factories import _open_room
from memory_eval import arm_env, insert, runtime, two_series
from memory_eval.fact_catchup import OperationalFacts
from memory_eval.fake_llm import FakeMemoryLLM

SLOTS = ("stat", "scene", "ending", "image", "summary", "episode", "fact", "impression")
# 측정 DB 에 새로 게시하는 체인 — 판정·요약 모델 설정(아래에서 전부 gemini 로 고정)과 다른 체인이라 행이 쓰였는지가 세트로 갈린다.
ROW_CHAIN = "haiku"


@pytest.fixture(autouse=True)
def _env_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    """env 규칙을 고정한다 — 판정·요약 모델은 전부 gemini, 호출 위치 배정은 비운다(Gemini 로 부르는 행이 경로 대조에 걸리지 않게)."""
    for name in (
        "stat_judgment_model", "ending_judgment_model", "image_judgment_model", "memory_summary_model",
        "memory_episode_model", "memory_fact_model", "memory_impression_model",
    ):  # fmt: skip
        monkeypatch.setattr(settings, name, "gemini")
    monkeypatch.setattr(settings, "llm_call_site_backends", {})


async def _story_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, *, stored: str = "gemini"
) -> runtime.RoomContext:
    room = await _open_room(db_client, db_session, turns=1, lane="story")
    await db_session.execute(update(ChatRoom).where(ChatRoom.id == room.room_id).values(chat_model=stored))
    await db_session.commit()
    return await runtime.load_room(db_session, room.room_id)


async def _row_chain(db: AsyncSession) -> uuid.UUID:
    """스토리 레인에 활성 haiku 세트를 하나 게시한다(시드에 있든 없든 이 세트가 활성이 되게 게시 시각을 뒤로)."""
    prompt_set = PromptSet(
        version=f"t-{uuid.uuid4().hex[:8]}", status="published", lane="story", model=ROW_CHAIN, user_label="사용자",
        story_assistant_label="진행자", story_example_label="서술자", character_assistant_label="캐릭터",
        published_at=datetime.now(UTC) + timedelta(days=2),
    )  # fmt: skip
    db.add(prompt_set)
    await db.flush()
    return prompt_set.id


def _route(room_model: str, stage: str) -> PromptRoute:
    return PromptRoute(
        lane="story", room_model=room_model, stage=stage, chain_model=ROW_CHAIN, call_model="gemini", backend="gemini"
    )


def _set_ids(sets: JudgmentPromptSets) -> dict[str, uuid.UUID]:
    return {slot: sets.prompt_set(slot)[0].id for slot in SLOTS}  # type: ignore[arg-type]


async def test_an_empty_table_gives_the_same_sets_as_the_app_call_without_a_table(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _story_room(db_client, db_session)
    await _row_chain(db_session)
    gemini = await load_active_prompt_set(db_session, lane="story", model="gemini")

    async def load(model: Any) -> Any:
        return await load_active_prompt_set(db_session, lane="story", model=model)

    sets = await runtime.judgment_sets(db_session, ctx)
    without = await judgment_prompt_sets(lane="story", gemini_set=gemini, load=load)
    assert _set_ids(sets) == _set_ids(without)
    assert all(sets.call_model(slot) is None for slot in SLOTS)  # type: ignore[arg-type]


async def test_a_row_in_the_measurement_table_picks_its_chain_and_call_model(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _story_room(db_client, db_session)
    chain_id = await _row_chain(db_session)
    db_session.add(_route("gemini", "memory_summary"))
    await db_session.flush()

    sets = await runtime.judgment_sets(db_session, ctx)
    assert sets.summary[0].id == chain_id
    assert sets.call_model("summary") == "gemini"
    assert sets.stat[0].model == "gemini" and sets.call_model("stat") is None


@pytest.mark.parametrize("harness_premium", [True, False])
async def test_an_opus_room_reads_the_opus_cell_whatever_the_harness_process_switch_says(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    harness_premium: bool,
) -> None:
    """측정 서버는 상위 모델 스위치를 켜고 뜨므로 Opus 로 저장된 방의 턴 판정은 Opus 칸을 읽는다. 하네스 프로세스는 로컬 env 로 떠서
    그 스위치가 꺼져 있을 수 있는데, 그 값으로 칸을 고르면 같은 측정 안에서 하네스의 접기·추출만 Gemini 칸으로 갈린다."""
    monkeypatch.setattr(settings, "chat_premium_models_enabled", harness_premium)
    ctx = await _story_room(db_client, db_session, stored="opus")
    chain_id = await _row_chain(db_session)
    db_session.add(_route("opus", "memory_summary"))
    await db_session.flush()

    sets = await runtime.judgment_sets(db_session, ctx)
    assert sets.summary[0].id == chain_id
    assert sets.call_model("summary") == "gemini"
    assert settings.chat_premium_models_enabled is harness_premium


async def test_a_gemini_room_reads_the_gemini_cell_not_the_opus_cell(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _story_room(db_client, db_session, stored="gemini")
    await _row_chain(db_session)
    db_session.add(_route("opus", "memory_summary"))
    await db_session.flush()

    sets = await runtime.judgment_sets(db_session, ctx)
    assert sets.summary[0].model == "gemini" and sets.call_model("summary") is None


async def test_a_rows_path_is_checked_against_the_measurement_server_assignment_not_the_harness_process(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anthropic 직결로 부르는 행은 측정 서버의 호출 위치 배정으로는 경로가 맞는다. 하네스 프로세스에 그 배정이 없어(여기서는 비움)
    그 값으로 대조하면 같은 행을 경로 불일치로 건너뛰어, 서버의 턴과 하네스의 접기가 다른 체인을 읽는다."""
    monkeypatch.setattr(settings, "anthropic_structured_effort", "low")
    ctx = await _story_room(db_client, db_session)
    chain_id = await _row_chain(db_session)
    db_session.add(
        PromptRoute(
            lane="story", room_model="gemini", stage="memory_summary", chain_model=ROW_CHAIN, call_model="haiku",
            backend="anthropic",
        )
    )  # fmt: skip
    await db_session.flush()

    sets = await runtime.judgment_sets(db_session, ctx)
    assert sets.summary[0].id == chain_id
    assert sets.call_model("summary") == "haiku"
    assert settings.llm_call_site_backends == {}


async def test_episode_extraction_in_the_harness_carries_the_rows_call_model(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = await _story_room(db_client, db_session)
    chain_id = await _row_chain(db_session)
    seen: list[dict[str, Any]] = []

    async def extract_pending_episode(*_: Any, **kwargs: Any) -> None:
        seen.append(kwargs)

    monkeypatch.setattr(memory_episodes, "extract_pending_episode", extract_pending_episode)
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    await insert._extract_once(factory, FakeMemoryLLM(), ctx.room.id, ctx.room.user_id)
    db_session.add(_route("gemini", "memory_episode"))
    await db_session.commit()
    await insert._extract_once(factory, FakeMemoryLLM(), ctx.room.id, ctx.room.user_id)

    assert [kwargs["call_model"] for kwargs in seen] == [None, "gemini"]
    assert seen[1]["prompt_set"].id == chain_id


async def test_operational_fact_extraction_in_the_harness_carries_the_rows_call_model(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _story_room(db_client, db_session)
    await _row_chain(db_session)
    db_session.add(_route("gemini", "memory_fact"))
    await db_session.commit()
    seen: list[dict[str, Any]] = []

    class Module:
        @staticmethod
        async def extract_pending_facts(*_: Any, **kwargs: Any) -> None:
            seen.append(kwargs)

    facts = OperationalFacts(module=Module, llm=FakeMemoryLLM())  # type: ignore[arg-type]
    await facts.run_once(
        async_sessionmaker(bind=db_session.bind, expire_on_commit=False), ctx.room.id, ctx.room.user_id
    )
    assert seen[0]["call_model"] == "gemini"


async def test_fold_both_hands_the_call_model_to_the_app_fold(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = await _story_room(db_client, db_session)
    sets = await runtime.judgment_sets(db_session, ctx)
    seen: list[Any] = []

    async def fold_memory(*_: Any, **kwargs: Any) -> None:
        seen.append(kwargs["call_model"])

    monkeypatch.setattr(memory_fold, "fold_memory", fold_memory)
    await two_series.fold_both(
        async_sessionmaker(bind=db_session.bind, expire_on_commit=False), FakeMemoryLLM(), room_id=ctx.room.id,
        user_id=ctx.room.user_id, prompt_set=sets.summary[0], sections=sets.summary[1], is_story_chat=True,
        names=ctx.names, series=None, writing_model="opus", call_model="haiku",
    )  # fmt: skip
    assert seen == ["haiku"]


def test_every_pair_a_route_row_may_hold_keeps_its_path_under_the_measurement_server_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """운영에서 저장 검사를 지난 행을 측정 DB 로 옮겼을 때, 측정 서버 env 의 호출 위치 배정 때문에 해석이 그 행을 경로 불일치로
    건너뛰면 측정은 운영과 다른 칸으로 돈다. 단계마다 허용된 (부를 모델, 경로) 쌍 전부가 측정 env 배정에서 행의 경로로 간다."""
    assignments = dict(arm_env.COMMON_ENV)["LLM_CALL_SITE_BACKENDS"]
    monkeypatch.setattr(settings, "llm_call_site_backends", dict(pair.split(":") for pair in assignments.split(",")))
    checked = 0
    for lane, stages in LANE_STAGES.items():
        for room_model in ("gemini", "opus"):
            for stage in stages:
                kind = STAGES[stage].kind
                for call_model, backend in ALLOWED_ROUTE_PAIRS[kind]:
                    if kind == "generation" and call_model != room_model:
                        continue
                    row = RouteRow(
                        lane=lane, room_model=room_model, stage=stage,
                        chain_model=None if kind == "generation" else call_model, call_model=call_model,
                        backend=backend,
                    )  # fmt: skip
                    problem = row_route_problem(row, row_call_sites(PromptRoutes.empty(), row), lambda _: "")
                    assert problem is None or problem[0] != "backend-mismatch", (row, problem)
                    checked += 1
    assert checked > 0
