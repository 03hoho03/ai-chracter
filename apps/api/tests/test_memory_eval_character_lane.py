"""캐릭터 레인 방도 하네스가 싣는다 — 방에서 레인을 읽고, 그 레인의 생성·판정·요약 세트로 가짜 클라이언트 접기와 궤적 조립이
돈다(스토리 세트로 캐릭터 방을 조립하면 다른 작품의 문안이 실린다)."""

from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat import memory_fold
from api.db.models import ChatRoom, ChatRoomMemorySnapshot
from api.db.models.character import CharacterVersionDetail
from factories import _open_room
from memory_eval import runtime
from memory_eval.fake_llm import FakeMemoryLLM
from memory_eval.trajectory import assemble_point
from seed_content.loader import load_character

SEED = Path(__file__).resolve().parents[1] / "scripts/seed_content/data/tutorial/characters/tutorial-filmclub-yuna.json"


async def test_character_seed_room_folds_with_the_fake_client_and_assembles_a_trajectory_point(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _open_room(db_client, db_session, turns=memory_fold.FOLD_AT_TURNS, lane="character")
    payload = load_character(SEED)
    chat_room = await db_session.get(ChatRoom, room.room_id)
    assert chat_room is not None
    detail = await db_session.scalar(
        sa.select(CharacterVersionDetail).where(
            CharacterVersionDetail.content_version_id == chat_room.content_version_id
        )
    )
    assert detail is not None
    detail.name = payload.name
    detail.intro = payload.intro
    detail.character_prompt = payload.character_prompt
    await db_session.commit()

    ctx = await runtime.load_room(db_session, room.room_id)
    assert ctx.lane == "character" and ctx.setup is None
    with pytest.raises(SystemExit, match="레인"):
        await runtime.load_room(db_session, room.room_id, lane="story")
    sets = await runtime.judgment_sets(db_session, lane=ctx.lane)
    assert sets.summary[0].lane == "character"
    generation_set, _ = await runtime.generation_set(db_session, "gemini", lane=ctx.lane)
    assert generation_set.lane == "character"

    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    llm = FakeMemoryLLM()
    await memory_fold.fold_memory(
        factory,
        llm,
        room_id=room.room_id,
        user_id=room.user_id,
        prompt_set=sets.summary[0],
        sections=sets.summary[1],
        is_story_chat=False,
        names=ctx.names,
        writing_model="opus",
    )
    snapshots = (
        await db_session.scalars(
            sa.select(ChatRoomMemorySnapshot).where(ChatRoomMemorySnapshot.chat_room_id == room.room_id)
        )
    ).all()
    assert len(snapshots) == 1 and "가짜 요약" in snapshots[0].summary_text
    assert llm.calls == ["chat_memory_summary"]

    point, prompt = await assemble_point(
        db_session, room.room_id, next_turn=memory_fold.FOLD_AT_TURNS + 1, user_content="오늘 상영작 뭐야?",
        arm="baseline", model="gemini", embeddings=None,
    )  # fmt: skip
    assert point["arm"] == "baseline" and point["chars"] == len(prompt) > 0
    assert point["historyMessages"] == 1 + 2 * memory_fold.FOLD_AT_TURNS  # 오프닝 + 심은 턴
    assert payload.name in prompt
