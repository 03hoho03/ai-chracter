"""두 계열 투입 — 접기마다 요약을 슬롯 꺼짐(A 계열)과 켜짐(B 계열) 두 판으로 함께 만든다. A 판은 앱의 접기 함수가 스위치를 끈
채로 커밋하고, B 판은 같은 접기 구간·같은 순간의 이름 출처로 스위치를 켠 접기와 바이트까지 같은 프롬프트를 만들어 자기 직전
B 판 요약을 이어 받는다. B 판은 `series-template` 이 읽는 `{"snapshotId", "summary"}` 줄로 남는다.

갈래 env 의 줄 이름은 모두 앱 설정 칸과 같아야 한다 — 서버는 모르는 환경변수를 조용히 버려, 이름이 틀린 갈래는 스위치를 끈
채로 돈다."""

import json
import uuid
from pathlib import Path
from typing import Any, TypeVar

import httpx
import pytest
import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat import memory_fold
from api.chat.memory_window import load_current_summary
from api.core.config import Settings, settings
from api.db.models import ChatRoom, ChatRoomMemorySnapshot, MediaBookPerson
from api.db.models.character import CharacterVersionDetail
from api.llm.client import LLMCallContext
from factories import _open_room
from memory_eval import arm_env, runtime, two_series
from memory_eval import embed_offline as eo
from memory_eval.arm_env import BUNDLE1_SWITCHES, bundle1_env_pairs
from memory_eval.fake_llm import FakeMemoryLLM
from memory_eval.series_template import load_summaries

T = TypeVar("T", bound=BaseModel)

SLOT_HEAD = "[비밀 표기]"


class CapturingLLM(FakeMemoryLLM):
    """가짜 요약을 주면서 요약 프롬프트를 모은다."""

    def __init__(self) -> None:
        super().__init__()
        self.prompts: list[str] = []

    async def generate_structured(
        self, prompt: str, response_schema: type[T], images: Any = None, *, usage: LLMCallContext
    ) -> T:
        self.prompts.append(prompt)
        return await super().generate_structured(prompt, response_schema, images, usage=usage)


def test_every_arm_env_name_is_an_app_setting_and_no_provisional_name_is_left() -> None:
    fields = set(Settings.model_fields)
    env = dict(
        bundle1_env_pairs(
            "b1-B2",
            lane="story",
            embed_model="m",
            embed_dims=256,
            recall=eo.HybridParams(df_max=5),
            embed_timeout_ms=250,
        )
    )
    # 기억 사용 범위 줄은 운영 코드에 먼저 들어온 설정이라 이 코드에는 아직 칸이 없다 — 서버는 모르는 환경변수를 버리므로 지금은
    # 무해하고, 서버를 운영 코드로 올린 뒤에는 이 예외가 비어 다른 모든 줄과 같이 설정 칸 검사를 받는다.
    assert [n for n in env if n.lower() not in fields and n != "MEMORY_MODEL_SCOPE"] == []
    for name in (
        "MEMORY_EMBED_RECALL",
        "MEMORY_EMBED_WRITE",
        "MEMORY_EMBED_MODEL",
        "MEMORY_EMBED_DIMS",
        "MEMORY_EMBED_RECALL_TIMEOUT_MS",
        *map(str.upper, eo.CONFIG_NAMES),
    ):
        assert name in env, name
    assert not hasattr(arm_env, "PROVISIONAL_SWITCHES")
    for name in (
        "MEMORY_SUMMARY_SECRET_MARKING",
        "MEMORY_KNOWLEDGE_FILTER",
        "MEMORY_FACTS_INJECT",
        "MEMORY_EPISODES_RECALL",
    ):
        assert name in BUNDLE1_SWITCHES and name.lower() in fields, name
    env = dict(
        bundle1_env_pairs(
            "b1-B1", lane="story", embed_model="m", embed_dims=256, recall=eo.DEFAULT_PARAMS, embed_timeout_ms=250
        )
    )
    assert (env["MEMORY_SUMMARY_SECRET_MARKING"], env["MEMORY_KNOWLEDGE_FILTER"]) == ("true", "true")


async def test_character_room_context_names_the_character_like_the_server_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """서버는 캐릭터 방 접기에 그 턴의 이름(작품 이름 포함)을 넘긴다 — 하네스 접기도 같아야 B 판 인물 목록에 작품 이름이 들어간다."""
    room = await _open_room(db_client, db_session, turns=1, lane="character")
    chat_room = await db_session.get(ChatRoom, room.room_id)
    assert chat_room is not None
    detail = await db_session.scalar(
        sa.select(CharacterVersionDetail).where(
            CharacterVersionDetail.content_version_id == chat_room.content_version_id
        )
    )
    assert detail is not None
    ctx = await runtime.load_room(db_session, room.room_id)
    assert ctx.names.char_name == detail.name
    story = await _open_room(db_client, db_session, turns=1, lane="story")
    assert (await runtime.load_room(db_session, story.room_id)).names.char_name is None


async def _story_room(db_client: httpx.AsyncClient, db_session: AsyncSession, *, turns: int) -> Any:
    room = await _open_room(db_client, db_session, turns=turns, lane="story")
    version_id = await db_session.scalar(sa.select(ChatRoom.content_version_id).where(ChatRoom.id == room.room_id))
    for order, name in enumerate(["한서윤", "Mina"]):
        db_session.add(MediaBookPerson(entity_id=uuid.uuid4(), content_version_id=version_id, name=name, order=order))
    await db_session.commit()
    return room


async def test_b_prompt_is_byte_identical_to_the_fold_with_the_marking_switch_on(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room = await _story_room(db_client, db_session, turns=memory_fold.FOLD_AT_TURNS)
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    ctx = await runtime.load_room(db_session, room.room_id)
    summary_set, sections = (await runtime.judgment_sets(db_session, ctx)).summary
    current = await load_current_summary(db_session, room.room_id)
    unsummarized = await memory_fold._load_unsummarized(db_session, room.room_id, current.cursor if current else None)
    plan = memory_fold.plan_fold(unsummarized)
    assert plan is not None

    mine = await two_series.b_summary_prompt(
        factory, room_id=room.room_id, prompt_set=summary_set, sections=sections, is_story_chat=True,
        names=ctx.names, previous_summary="", turns=plan.turns,
    )  # fmt: skip
    monkeypatch.setattr(settings, "memory_summary_secret_marking", True)
    llm = CapturingLLM()
    await memory_fold.fold_memory(
        factory, llm, room_id=room.room_id, user_id=room.user_id, prompt_set=summary_set, sections=sections,
        is_story_chat=True, names=ctx.names, writing_model="opus",
    )  # fmt: skip
    assert llm.prompts == [mine]
    assert SLOT_HEAD in mine and "한서윤, Mina" in mine


async def _plant_turns(db_session: AsyncSession, room_id: uuid.UUID, start: int, count: int) -> None:
    """방 끝에 `count` 턴을 더한다(사용자·진행자 한 쌍씩, 넣은 순서가 키 순서)."""
    from api.db.models import ChatMessage, ChatMessageRole

    for turn in range(start, start + count):
        db_session.add(ChatMessage(chat_room_id=room_id, role=ChatMessageRole.USER, content=f"사용자 {turn}"))
        await db_session.flush()
        db_session.add(ChatMessage(chat_room_id=room_id, role=ChatMessageRole.ASSISTANT, content=f"진행자 {turn}"))
        await db_session.flush()
    await db_session.commit()


async def test_fold_both_commits_the_a_summary_with_the_switch_off_and_chains_the_b_summaries(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """프로세스 설정이 켜져 있어도 A 판 접기는 슬롯 없이 커밋하고, B 판은 슬롯을 싣고 직전 B 판(A 판이 아니다)을 이어 받는다."""
    monkeypatch.setattr(settings, "memory_summary_secret_marking", True)
    room = await _story_room(db_client, db_session, turns=memory_fold.FOLD_AT_TURNS)
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    ctx = await runtime.load_room(db_session, room.room_id)
    summary_set, sections = (await runtime.judgment_sets(db_session, ctx)).summary
    path = two_series.summaries_path(tmp_path, "b1-measure")
    series = two_series.BSeries(path)
    llm = CapturingLLM()

    async def fold() -> dict[str, Any]:
        return await two_series.fold_both(
            factory, llm, room_id=room.room_id, user_id=room.user_id, prompt_set=summary_set, sections=sections,
            is_story_chat=True, names=ctx.names, series=series, writing_model="opus",
        )  # fmt: skip

    first = await fold()
    assert first == {"folded": True, "bSummary": True}
    assert await fold() == {"folded": False, "bSummary": False}  # 접을 때가 아니면 두 판 모두 부르지 않는다
    await _plant_turns(db_session, room.room_id, memory_fold.FOLD_AT_TURNS + 1, memory_fold.FOLD_TURNS)
    assert (await fold())["bSummary"] is True

    a_prompts, b_prompts = llm.prompts[0::2], llm.prompts[1::2]
    assert len(llm.prompts) == 4
    assert all(SLOT_HEAD not in p for p in a_prompts) and all(SLOT_HEAD in p for p in b_prompts)
    snapshots = (
        await db_session.scalars(
            sa.select(ChatRoomMemorySnapshot)
            .where(ChatRoomMemorySnapshot.chat_room_id == room.room_id)
            .order_by(ChatRoomMemorySnapshot.cursor_created_at)
        )
    ).all()
    rows = load_summaries(path)
    assert list(rows) == [str(s.id) for s in snapshots]
    assert all(rows[str(s.id)] != s.summary_text for s in snapshots)
    assert rows[str(snapshots[0].id)] in b_prompts[1] and snapshots[0].summary_text not in b_prompts[1]
    assert snapshots[0].summary_text in a_prompts[1]
    assert [json.loads(line)["snapshotId"] for line in path.read_text(encoding="utf-8").splitlines()] == list(rows)
    # 다시 열어도(이어 넣기) 같은 줄을 읽는다.
    assert two_series.BSeries(path).previous(snapshots[1].id) == rows[str(snapshots[1].id)]


def test_b_series_refuses_a_current_snapshot_without_a_b_summary(tmp_path: Path) -> None:
    series = two_series.BSeries(two_series.summaries_path(tmp_path, "x"))
    assert series.previous(None) == ""
    with pytest.raises(SystemExit, match="B 판"):
        series.previous(uuid.uuid4())
