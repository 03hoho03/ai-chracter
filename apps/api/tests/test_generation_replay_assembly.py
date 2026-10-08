"""생성 리플레이가 측정한 방의 지난 턴을 그때 상태로 다시 조립하는지, 변형 축마다 그 축만 바뀌는지, 받은 세션을
그대로 두는지, 호출 기록과 상한을 지키는지 — 가짜 LLM 클라이언트로만 본다(실제 호출 0).

방은 6턴이고, 턴마다 그 턴의 DB 상태(기억 노트·스탯·요약 스냅숏)로 서버 조립 함수를 불러 서버의 덤프 함수로 덤프를
남긴 뒤, DB 를 "지금" 값(다른 노트·스탯·더 늦은 요약·바뀐 프로필 설명·측정 뒤 게시한 세트)으로 옮긴다. 리플레이가 DB 의
지금 값을 하나라도 읽으면 그 턴의 덤프와 어긋난다. 드라이버 로그의 방 고정값·스탯 줄은 드라이버의 기록 함수로 만든다.
"""

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import chat_play
import generation_replay
from api.chat import router
from api.chat.prompt_builder import load_active_prompt_set
from api.chat.router import _build_prompt, _resolve_starting_setup
from api.content.schemas import EndingRuleDraftItem
from api.core.config import settings
from api.db.models import ChatRoom, ChatRoomStat, StartingSetup, StatDef, StoryVersionDetail
from api.db.models.chat import ChatMessage, ChatRoomMemorySnapshot
from api.db.models.content import ContentVersion
from api.db.models.persona import UserPersona
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.story import EndingRuleOperator, Shortcut, SituationNote
from api.llm import bedrock as bedrock_module
from api.llm import gemini as gemini_module
from api.llm.bedrock import BedrockLLMClient
from api.llm.gemini import GeminiLLMClient
from api.llm.pricing import estimate_cost_usd
from api.llm.routing import RoutingLLMClient
from factories import Room, _add_situation_note, _make_default_persona, _make_user, _open_room, _story_with_setup
from replay.assemble import ArmSpec, assemble_turn
from replay.budget import ledger_paths, sum_ledger
from replay.logs import ReplayRefusedError, load_driver_logs, sha256
from replay.prompt_sets import load_sections
from replay.swap import SwapSlot

TURNS = 6
GATE = 80
GATED_NOTE = "신뢰가 문턱을 넘은 뒤에만 실리는 상황"
SHORTCUT_TURN = 3
SHORTCUT_PROMPT = "지금 장면을 마무리하고 다음 날 아침으로 넘겨라"
# 턴 N 에 보낸 노트·요약, 턴 N 을 마친 뒤의 신뢰. 신뢰는 턴 3 판정에서 문턱을 넘는다.
NOTE_AT = {1: "노트 A", 2: "노트 A", 3: "노트 A", 4: "노트 B", 5: "노트 B", 6: "노트 B"}
SUMMARY_AT = {1: "", 2: "", 3: "요약 1", 4: "요약 1", 5: "요약 2", 6: "요약 2"}
# 요약 본문 → 그 요약이 덮는 마지막 턴.
SUMMARY_CURSOR_TURN = {"요약 1": 2, "요약 2": 4}
TRUST_AFTER = {0: 73.0, 1: 73.0, 2: 73.0, 3: 85.0, 4: 85.0, 5: 85.0, 6: 85.0}
PERSONA_THEN = "그때 프로필 설명"


@dataclass
class Scenario:
    room: Room
    trust_id: uuid.UUID
    shortcut_id: uuid.UUID
    measured_set_id: uuid.UUID
    later_set_id: uuid.UUID
    log: Path
    snapshot_log: Path
    dump: Path


def _clone(row: Any, **changes: Any) -> Any:
    values = {attr.key: getattr(row, attr.key) for attr in sa.inspect(type(row)).column_attrs if attr.key != "id"}
    return type(row)(**(values | changes))


async def _clone_set(
    db_session: AsyncSession, source: PromptSet, *, status: str, published_at: datetime | None, model: str, mark: str
) -> PromptSet:
    """`source` 의 섹션을 그대로 옮기고 지시문 채널 본문 끝에만 `mark` 를 붙인 세트."""
    copy: PromptSet = _clone(
        source,
        status=status,
        published_at=published_at,
        model=model,
        version=None if status == "draft" else f"t-{uuid.uuid4()}",
    )
    db_session.add(copy)
    await db_session.flush()
    for section in await load_sections(db_session, source.id):
        body = section.body + mark if section.channel == "system" else section.body
        db_session.add(_clone(section, prompt_set_id=copy.id, body=body))
    await db_session.flush()
    return copy


def _jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


async def _messages(db_session: AsyncSession, room_id: uuid.UUID) -> list[ChatMessage]:
    return list(
        (
            await db_session.scalars(
                select(ChatMessage)
                .where(ChatMessage.chat_room_id == room_id)
                .order_by(ChatMessage.created_at, ChatMessage.id)
            )
        ).all()
    )


def _snapshot_row(room: Room, text: str) -> ChatRoomMemorySnapshot:
    cursor = room.turns[SUMMARY_CURSOR_TURN[text]][1]
    return ChatRoomMemorySnapshot(
        chat_room_id=room.room_id,
        cursor_created_at=cursor.created_at,
        cursor_message_id=cursor.id,
        summary_text=text,
        source="auto",
    )


async def _scenario(
    db_client: httpx.AsyncClient, db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Scenario:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    persona = await _make_default_persona(db_session, user.id, "하늘")
    persona.description = PERSONA_THEN
    room = await _open_room(db_client, db_session, turns=TURNS, lane="story", user=user)
    # 시드 세트의 게시 시각은 이 테스트 세션의 마이그레이션 시각이라 하루 전으로 심은 메시지보다 늦다. 측정 전에 게시된
    # 세트로 만든다(순서는 그대로).
    await db_session.execute(
        sa.update(PromptSet)
        .where(PromptSet.status == "published")
        .values(published_at=PromptSet.published_at - timedelta(days=3))
    )
    chat_room = await db_session.get(ChatRoom, room.room_id)
    assert chat_room is not None
    setup = await _resolve_starting_setup(db_session, chat_room)
    assert setup is not None
    trust_id = await db_session.scalar(select(StatDef.entity_id).where(StatDef.starting_setup_id == setup.id))
    assert trust_id is not None
    rule = EndingRuleDraftItem(
        id=uuid.uuid4(), stat_id=trust_id, operator=EndingRuleOperator("gte"), threshold=GATE, next_op=None
    )
    _add_situation_note(db_session, setup, GATED_NOTE, [rule])
    shortcut = Shortcut(
        entity_id=uuid.uuid4(),
        content_version_id=chat_room.content_version_id,
        name="다음 날로",
        description="장면 넘기기",
        prompt=SHORTCUT_PROMPT,
    )
    db_session.add(shortcut)
    await db_session.commit()

    log, snapshot_log, dump = tmp_path / "chat.jsonl", tmp_path / "memory.jsonl", tmp_path / "dump.jsonl"
    api_room = (await db_client.get(f"/chat-rooms/{room.room_id}")).json()
    db_room = await chat_play.read_db_room(db_session, room.room_id)
    assert db_room is not None
    static = chat_play.room_static(api_room, db_room)
    _jsonl(snapshot_log, static)

    def after(turn_count: int, source: str) -> dict[str, Any]:
        return chat_play.room_after(
            {"turnCount": turn_count, "stats": {str(trust_id): TRUST_AFTER[turn_count]}}, static, source
        )

    room_id = str(room.room_id)
    _jsonl(log, {"kind": "opening", "roomId": room_id, "messages": [], "roomAfter": after(0, "create")})
    measured_set, measured_sections = await load_active_prompt_set(db_session, lane="story")
    monkeypatch.setattr(settings, "prompt_dump_path", str(dump))
    stat_row = await db_session.scalar(select(ChatRoomStat).where(ChatRoomStat.chat_room_id == room.room_id))
    assert stat_row is not None
    previous: tuple[str, str] | None = None
    for turn in range(1, TURNS + 1):
        # 이 턴을 보낼 때의 DB 상태 — 서버는 이것을 읽어 조립했다.
        chat_room.memory_note = NOTE_AT[turn]
        stat_row.current_value = Decimal(str(TRUST_AFTER[turn - 1]))
        if SUMMARY_AT[turn] and SUMMARY_AT[turn] != SUMMARY_AT[turn - 1]:
            db_session.add(_snapshot_row(room, SUMMARY_AT[turn]))
        await db_session.commit()
        messages = await _messages(db_session, room.room_id)
        user_message = room.turns[turn][0]
        index = next(i for i, m in enumerate(messages) if m.id == user_message.id)
        prompt, system_instruction, _, _, _ = await _build_prompt(
            db_session,
            chat_room,
            setup,
            messages[:index],
            user_message.content,
            shortcut if turn == SHORTCUT_TURN else None,
            measured_set,
            measured_sections,
        )
        router._dump_prompt(
            room_id=room.room_id, model="gemini", turn=turn, prompt=prompt, system_instruction=system_instruction
        )
        memory = (NOTE_AT[turn], SUMMARY_AT[turn])
        if memory != previous:
            _jsonl(
                snapshot_log,
                {
                    "kind": "memorySnapshot",
                    "roomId": room_id,
                    "turnBefore": turn - 1,
                    "turn": turn,
                    "note": memory[0],
                    "summary": memory[1],
                },
            )
            previous = memory
        _jsonl(
            log,
            {
                "kind": "turn",
                "roomId": room_id,
                "clientTurn": turn,
                "turnBefore": turn - 1,
                "userText": None if turn == SHORTCUT_TURN else user_message.content,
                "shortcut": shortcut.name if turn == SHORTCUT_TURN else None,
                "shortcutId": str(shortcut.entity_id) if turn == SHORTCUT_TURN else None,
                "memory": {"noteSha": sha256(memory[0]), "summarySha": sha256(memory[1])},
                "http": 200,
                "done": True,
                "reply": room.turns[turn][1].content,
                "partialReply": None,
                "assistantMessageId": str(room.turns[turn][1].id),
                "roomAfter": after(turn, "sse"),
            },
        )
    monkeypatch.setattr(settings, "prompt_dump_path", None)

    # 지금 값 — 측정 뒤 바뀐 것들.
    chat_room.memory_note = "지금 노트"
    stat_row.current_value = Decimal(60)
    last = room.turns[TURNS][1]
    db_session.add(
        ChatRoomMemorySnapshot(
            chat_room_id=room.room_id,
            cursor_created_at=last.created_at,
            cursor_message_id=last.id,
            summary_text="지금 요약",
            source="auto",
        )
    )
    persona_row = await db_session.get(UserPersona, persona.id)
    assert persona_row is not None
    persona_row.description = "지금 프로필 설명"
    later = await _clone_set(
        db_session, measured_set, status="published", published_at=datetime.now(UTC), model="gemini", mark="[측정 뒤]"
    )
    await db_session.commit()
    return Scenario(
        room=room,
        trust_id=trust_id,
        shortcut_id=shortcut.entity_id,
        measured_set_id=measured_set.id,
        later_set_id=later.id,
        log=log,
        snapshot_log=snapshot_log,
        dump=dump,
    )


async def _assemble(
    db_session: AsyncSession, s: Scenario, turn: int, arm: ArmSpec | None = None, *, log: Path | None = None
) -> Any:
    logs = load_driver_logs(log or s.log, s.snapshot_log, s.room.room_id)
    return await assemble_turn(db_session, room_id=s.room.room_id, turn=turn, logs=logs, dump=s.dump, arm=arm)


@pytest.fixture
async def scenario(
    db_client: httpx.AsyncClient, db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Scenario:
    return await _scenario(db_client, db_session, tmp_path, monkeypatch)


# ---- 현행 갈래 --------------------------------------------------------------------------------


async def test_every_turn_is_reassembled_byte_identical_to_its_dump_from_the_logs(
    db_session: AsyncSession, scenario: Scenario
) -> None:
    for turn in range(1, TURNS + 1):
        assembly = await _assemble(db_session, scenario, turn)
        assert assembly.window_identical and assembly.passed, (turn, assembly.checks)
        assert assembly.stats_before == {"[STAT]신뢰": TRUST_AFTER[turn - 1]}
        assert assembly.state["persona"] == "roomStatic"
        cursor = assembly.state["summaryCursor"]
        if SUMMARY_AT[turn]:
            # 요약 커서는 본문 해시로 찾은 스냅숏의 것이다 — 지금 가장 늦은 스냅숏이 아니다.
            assert cursor["rule"] == "sha256"
            assert cursor["messageId"] == str(scenario.room.turns[SUMMARY_CURSOR_TURN[SUMMARY_AT[turn]]][1].id)
        else:
            assert cursor is None
        assert assembly.inputs[0].chosen_set["setId"] == str(scenario.measured_set_id)
    window = (await _assemble(db_session, scenario, 4)).inputs[0]
    # 스탯은 턴 3 판정 뒤 문턱을 넘었다 — 턴 4 에 실리고 턴 3 에는 실리지 않는다(지금 값 60 은 문턱 아래).
    assert GATED_NOTE in window.prompt
    assert GATED_NOTE not in (await _assemble(db_session, scenario, 3)).inputs[0].prompt
    assert SHORTCUT_PROMPT in (await _assemble(db_session, scenario, SHORTCUT_TURN)).inputs[0].prompt


async def test_assembly_leaves_the_given_session_and_its_outer_transaction_alone(
    db_session: AsyncSession, scenario: Scenario
) -> None:
    held = await db_session.get(ChatRoom, scenario.room.room_id)
    assert held is not None
    await _assemble(
        db_session,
        scenario,
        5,
        ArmSpec(variant="swap", arm="W", swap=(SwapSlot("설정", "세계관 설정", "바뀐 세계관"),)),
    )
    # 저장점만 되돌렸다 — 부른 쪽이 들고 있는 방 객체는 세션에 붙은 채이고, 바깥 트랜잭션은 쓸 수 있다.
    assert held in db_session and db_session.in_transaction()
    assert not db_session.dirty and not db_session.new
    held.memory_note = "바깥 트랜잭션에 쓰기"
    await db_session.flush()
    db_session.expire_all()
    detail = (await db_session.scalars(select(StoryVersionDetail))).all()
    assert detail and all(row.setting_text != "바뀐 세계관" for row in detail)
    note = await db_session.scalar(select(ChatRoom.memory_note).where(ChatRoom.id == scenario.room.room_id))
    assert note == "바깥 트랜잭션에 쓰기"
    stat = await db_session.scalar(
        select(ChatRoomStat.current_value).where(ChatRoomStat.chat_room_id == scenario.room.room_id)
    )
    assert stat == 60


async def test_window_set_is_the_latest_published_before_the_turn_not_the_one_active_now(
    db_session: AsyncSession, scenario: Scenario
) -> None:
    active, _ = await load_active_prompt_set(db_session, lane="story")
    assert active.id == scenario.later_set_id
    assembly = await _assemble(db_session, scenario, 2)
    chosen = assembly.inputs[0].chosen_set
    assert (chosen["setId"], chosen["setRule"]) == (str(scenario.measured_set_id), "publishedBeforeTurn")
    assert "[측정 뒤]" not in assembly.inputs[0].system_instruction


async def test_section_reading_matches_the_active_set_loader(db_session: AsyncSession) -> None:
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story")
    assert [s.id for s in await load_sections(db_session, prompt_set.id)] == [s.id for s in sections]


# ---- 거부 -------------------------------------------------------------------------------------


async def test_changed_fixed_values_refuse_the_turn(db_session: AsyncSession, scenario: Scenario) -> None:
    await db_session.execute(
        sa.update(ChatRoom).where(ChatRoom.id == scenario.room.room_id).values(chat_model="sonnet")
    )
    await db_session.commit()
    with pytest.raises(ReplayRefusedError, match="chatModel"):
        await _assemble(db_session, scenario, 2)


async def test_an_old_log_without_fixed_values_uses_the_current_profile_and_says_so(
    db_session: AsyncSession, scenario: Scenario, tmp_path: Path
) -> None:
    old = tmp_path / "old-memory.jsonl"
    for line in scenario.snapshot_log.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record["kind"] == "roomStatic":
            record = {k: record[k] for k in ("kind", "roomId", "at", "stats", "endings", "shortcuts")}
        _jsonl(old, record)
    logs = load_driver_logs(scenario.log, old, scenario.room.room_id)
    assembly = await assemble_turn(db_session, room_id=scenario.room.room_id, turn=2, logs=logs, dump=scenario.dump)
    assert assembly.fixed["recorded"] == "고정값 기록 없음" and assembly.state["persona"] == "db-current"
    # 측정 뒤 바뀐 프로필 설명으로 조립되어 덤프와 다르다 — 고정값 기록이 있으면 기록값으로 조립된다(위 테스트).
    assert not assembly.window_identical
    assert "지금 프로필 설명" in assembly.inputs[0].prompt


async def test_summary_without_a_matching_snapshot_or_with_two_cursors_is_refused(
    db_session: AsyncSession, scenario: Scenario
) -> None:
    second = _snapshot_row(scenario.room, "요약 1")
    second.cursor_message_id = scenario.room.turns[1][1].id
    second.cursor_created_at = scenario.room.turns[1][1].created_at
    db_session.add(second)
    await db_session.commit()
    with pytest.raises(ReplayRefusedError, match="커서가 2개"):
        await _assemble(db_session, scenario, 3)
    await db_session.execute(sa.delete(ChatRoomMemorySnapshot).where(ChatRoomMemorySnapshot.summary_text == "요약 1"))
    await db_session.commit()
    with pytest.raises(ReplayRefusedError, match="해시가 같은 DB 스냅숏이 없다"):
        await _assemble(db_session, scenario, 4)
    # 요약이 없던 턴은 그대로 된다.
    assert (await _assemble(db_session, scenario, 2)).window_identical


async def test_a_stat_missing_from_the_stats_line_refuses_the_turn(
    db_session: AsyncSession, scenario: Scenario, tmp_path: Path
) -> None:
    edited = tmp_path / "edited.jsonl"
    for line in scenario.log.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("clientTurn") == 3:
            record["roomAfter"]["stats"] = {}
        _jsonl(edited, record)
    with pytest.raises(ReplayRefusedError, match="값이 없는 스탯"):
        await _assemble(db_session, scenario, 4, log=edited)
    assert (await _assemble(db_session, scenario, 3, log=edited)).window_identical


async def test_a_turn_without_a_dump_is_refused(db_session: AsyncSession, scenario: Scenario) -> None:
    with pytest.raises(ReplayRefusedError, match="덤프에 턴 7"):
        await _assemble(db_session, scenario, 7)


# ---- 변형 축 ----------------------------------------------------------------------------------


async def test_model_axis_uses_that_models_set_active_now_even_if_published_after_the_turn(
    db_session: AsyncSession, scenario: Scenario
) -> None:
    measured, _ = await load_active_prompt_set(db_session, lane="story", model="sonnet")
    newer = await _clone_set(
        db_session, measured, status="published", published_at=datetime.now(UTC), model="sonnet", mark="[새 소네트]"
    )
    await db_session.commit()
    window, arm = (
        await _assemble(db_session, scenario, 4, ArmSpec(variant="model", arm="sonnet", model="sonnet"))
    ).inputs
    assert (window.chat_model, arm.chat_model) == ("gemini", "sonnet")
    assert arm.chosen_set["setId"] == str(newer.id) and arm.chosen_set["setRule"] == "activeNow"
    assert "[새 소네트]" in arm.system_instruction and "[새 소네트]" not in window.system_instruction
    # 상태는 현행과 같다 — 같은 노트·요약·상황 노트가 실린다.
    for text in ("노트 B", "요약 1", GATED_NOTE):
        assert text in window.prompt and text in arm.prompt


async def test_set_axis_takes_a_draft_or_a_set_by_id_with_that_sets_model(
    db_session: AsyncSession, scenario: Scenario
) -> None:
    measured = await db_session.get(PromptSet, scenario.measured_set_id)
    assert measured is not None
    await db_session.execute(
        sa.delete(PromptSection).where(
            PromptSection.prompt_set_id.in_(
                select(PromptSet.id).where(
                    PromptSet.status == "draft", PromptSet.lane == "story", PromptSet.model == "gemini"
                )
            )
        )
    )
    await db_session.execute(
        sa.delete(PromptSet).where(PromptSet.status == "draft", PromptSet.lane == "story", PromptSet.model == "gemini")
    )
    await _clone_set(db_session, measured, status="draft", published_at=None, model="gemini", mark="[초안]")
    await db_session.commit()
    window, draft = (
        await _assemble(db_session, scenario, 5, ArmSpec(variant="set", arm="draft", set_draft=True))
    ).inputs
    assert (draft.variant, draft.chat_model, draft.chosen_set["setRule"]) == ("set", "gemini", "draft")
    assert "[초안]" in draft.system_instruction and "[초안]" not in window.system_instruction
    assert draft.prompt == window.prompt
    _, by_id = (
        await _assemble(db_session, scenario, 5, ArmSpec(variant="set", arm="later", set_id=scenario.later_set_id))
    ).inputs
    assert by_id.chosen_set["setId"] == str(scenario.later_set_id) and "[측정 뒤]" in by_id.system_instruction
    with pytest.raises(ReplayRefusedError, match="모델 gemini 의 세트"):
        await _assemble(
            db_session, scenario, 5, ArmSpec(variant="set", arm="x", set_id=scenario.later_set_id, model="opus")
        )


async def _clone_version(db_session: AsyncSession, scenario: Scenario, setting_text: str) -> uuid.UUID:
    """방 작품의 새 버전 — 상세·시작 설정·스탯·상황 노트·단축어를 entity_id 그대로 옮기고 세계관 글만 바꾼다."""
    room = await db_session.get(ChatRoom, scenario.room.room_id)
    assert room is not None
    version = ContentVersion(
        content_id=room.content_id, version_number=2, published_at=datetime.now(UTC), detail_description="v2"
    )
    db_session.add(version)
    await db_session.flush()
    detail = await db_session.get(StoryVersionDetail, room.content_version_id)
    db_session.add(_clone(detail, content_version_id=version.id, setting_text=setting_text))
    setup = await db_session.scalar(
        select(StartingSetup).where(StartingSetup.content_version_id == room.content_version_id)
    )
    assert setup is not None
    new_setup = _clone(setup, content_version_id=version.id)
    db_session.add(new_setup)
    await db_session.flush()
    for model in (StatDef, SituationNote):
        for row in (await db_session.scalars(select(model).where(model.starting_setup_id == setup.id))).all():
            db_session.add(_clone(row, starting_setup_id=new_setup.id))
    for row in (
        await db_session.scalars(select(Shortcut).where(Shortcut.content_version_id == room.content_version_id))
    ).all():
        db_session.add(_clone(row, content_version_id=version.id))
    await db_session.commit()
    return version.id


async def test_version_axis_assembles_the_same_turn_from_another_version_of_the_work(
    db_session: AsyncSession, scenario: Scenario
) -> None:
    version_id = await _clone_version(db_session, scenario, "새 버전의 세계관")
    window, other = (
        await _assemble(
            db_session, scenario, SHORTCUT_TURN + 1, ArmSpec(variant="version", arm="v2", version_id=version_id)
        )
    ).inputs
    assert "세계관 설정" in window.prompt and "새 버전의 세계관" not in window.prompt
    assert "새 버전의 세계관" in other.prompt and "세계관 설정" not in other.prompt
    assert other.content_version_id == version_id and other.arm_record()["contentVersionId"] == str(version_id)
    assert GATED_NOTE in other.prompt  # 새 버전의 상황 노트도 그 턴 스탯으로 본다
    # 단축어 턴은 새 버전에서 entity_id 로 단축어를 다시 찾는다.
    _, shortcut_turn = (
        await _assemble(
            db_session, scenario, SHORTCUT_TURN, ArmSpec(variant="version", arm="v2", version_id=version_id)
        )
    ).inputs
    assert SHORTCUT_PROMPT in shortcut_turn.prompt
    _, other_work, _ = await _story_with_setup(db_session, opening_message=None)
    foreign = other_work.current_published_version_id
    assert foreign is not None
    with pytest.raises(ReplayRefusedError, match="이 방 작품의 버전이 아니다"):
        await _assemble(db_session, scenario, 2, ArmSpec(variant="version", arm="x", version_id=foreign))


async def test_swap_axis_changes_only_the_table_text_and_writes_nothing(
    db_session: AsyncSession, scenario: Scenario
) -> None:
    opening = (await _messages(db_session, scenario.room.room_id))[0]
    arm = ArmSpec(
        variant="swap",
        arm="W",
        swap=(
            SwapSlot("설정", "세계관 설정", "바뀐 세계관"),
            SwapSlot("노트", GATED_NOTE, "문턱 뒤 바뀐 상황"),
            SwapSlot("오프닝", opening.content, "바뀐 오프닝 인사", target="historyOpening"),
        ),
    )
    assembly = await _assemble(db_session, scenario, 4, arm)
    window, swapped = assembly.inputs
    assert assembly.passed and assembly.checks["swap"]["passed"], assembly.checks["swap"]
    assert assembly.checks["swap"]["loadedSlots"] == ["노트", "설정", "오프닝"]
    assert (swapped.variant, swapped.swap_label, swapped.arm_record()["swapLabel"]) == ("swap", "W", "W")
    assert "바뀐 세계관" in swapped.prompt and "바뀐 오프닝 인사" in swapped.prompt
    assert not db_session.dirty and not db_session.new
    await db_session.refresh(opening)
    assert opening.content != "바뀐 오프닝 인사"
    # 이어서 조립한 현행 갈래에 바꾼 글이 남지 않는다.
    assert (await _assemble(db_session, scenario, 4)).inputs[0].prompt == window.prompt
    # 턴 3 은 상황 노트가 실리지 않는다 — 실리지 않은 칸은 바꾸지 않은 것이 맞다.
    turn3 = await _assemble(db_session, scenario, 3, arm)
    assert turn3.passed and turn3.checks["swap"]["loadedSlots"] == ["설정", "오프닝"]
    with pytest.raises(ReplayRefusedError, match="찾지 못한 칸"):
        await _assemble(
            db_session, scenario, 4, ArmSpec(variant="swap", arm="x", swap=(SwapSlot("없음", "작품에 없는 글", "y"),))
        )


# ---- CLI: 시험 실행 · 호출 · 상한 -------------------------------------------------------------


def _args(s: Scenario, tmp_path: Path, *extra: str, turns: tuple[int, ...] = (4,)) -> list[str]:
    argv = ["--room", str(s.room.room_id), "--dump", str(s.dump), "--log", str(s.log)]
    argv += ["--snapshot-log", str(s.snapshot_log), "--out", str(tmp_path / "out" / "gen")]
    for turn in turns:
        argv += ["--turn", str(turn)]
    return [*argv, *extra]


def _records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class _Fake:
    """두 공급자 SDK 경계(Gemini `aio.models.generate_content_stream`, Bedrock `messages.create`)만 가짜로 둔 라우팅
    클라이언트. 실제로 보낸 요청 인자를 모은다."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.gemini_sent: list[dict[str, Any]] = []
        self.bedrock_sent: list[dict[str, Any]] = []
        self.built = 0
        self.recorded: list[tuple[str, str]] = []
        # 주면 Bedrock 호출이 사용량 기록 없이 이 예외로 끝난다(정책 거절·연결 오류처럼).
        self.bedrock_error: Exception | None = None

        async def record_usage(call_site: str, model: str, usage_metadata: object | None) -> None:
            self.recorded.append((call_site, model))

        # 사용량 기록의 원래 자리(Redis)는 쓰지 않는다 — 리플레이는 이 이름을 감싸 보낸 값을 잡는다.
        monkeypatch.setattr(gemini_module, "record_usage", record_usage)
        monkeypatch.setattr(bedrock_module, "record_usage", record_usage)
        self.gemini = GeminiLLMClient(api_key="test-key")
        monkeypatch.setattr(
            self.gemini,
            "_client",
            SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content_stream=self._gemini_stream))),
        )
        self.bedrock = BedrockLLMClient()
        monkeypatch.setattr(
            self.bedrock, "_client", SimpleNamespace(messages=SimpleNamespace(create=self._bedrock_create))
        )

    async def _gemini_stream(self, **kwargs: Any) -> AsyncIterator[SimpleNamespace]:
        self.gemini_sent.append(kwargs)

        async def chunks() -> AsyncIterator[SimpleNamespace]:
            yield SimpleNamespace(text="제미나이 ", candidates=[], usage_metadata=None, prompt_feedback=None)
            yield SimpleNamespace(
                text="응답",
                candidates=[SimpleNamespace(finish_reason="STOP")],
                usage_metadata=SimpleNamespace(
                    prompt_token_count=100,
                    cached_content_token_count=10,
                    candidates_token_count=7,
                    thoughts_token_count=3,
                    total_token_count=110,
                ),
                prompt_feedback=None,
            )

        return chunks()

    async def _bedrock_create(self, **kwargs: Any) -> AsyncIterator[SimpleNamespace]:
        self.bedrock_sent.append(kwargs)
        if self.bedrock_error is not None:
            raise self.bedrock_error

        async def stream() -> AsyncIterator[SimpleNamespace]:
            usage = SimpleNamespace(
                input_tokens=50, cache_read_input_tokens=20, cache_creation_input_tokens=30, output_tokens=0
            )
            yield SimpleNamespace(type="message_start", message=SimpleNamespace(usage=usage))
            yield SimpleNamespace(
                type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="클로드 응답")
            )
            yield SimpleNamespace(
                type="message_delta",
                delta=SimpleNamespace(stop_reason="end_turn"),
                usage=SimpleNamespace(
                    output_tokens=9, input_tokens=None, cache_read_input_tokens=None, cache_creation_input_tokens=None
                ),
            )

        return stream()

    def client(self) -> RoutingLLMClient:
        self.built += 1
        return RoutingLLMClient(self.gemini, bedrock_factory=lambda: self.bedrock)


async def _run(db_session: AsyncSession, argv: list[str], fake: _Fake) -> int:
    args, arm = generation_replay.parse_args(argv)
    return await generation_replay.run(args, arm, db_session, client_factory=fake.client)


async def test_execute_records_calls_through_gemini_and_bedrock_with_the_replay_label(
    db_session: AsyncSession, scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _Fake(monkeypatch)
    argv = _args(scenario, tmp_path, "--model", "sonnet", "--arm", "sonnet", "--limit-calls", "10", "--execute")
    assert await _run(db_session, argv, fake) == 0
    window_file, arm_file = tmp_path / "out" / "gen.window.jsonl", tmp_path / "out" / "gen.sonnet.jsonl"
    window_calls = [r for r in _records(window_file) if r["kind"] == "call"]
    arm_calls = [r for r in _records(arm_file) if r["kind"] == "call"]
    assert [(c["variant"], c["arm"], c["rep"]) for c in window_calls] == [
        ("window", "window", 0),
        ("window", "window", 1),
    ]
    assert [(c["variant"], c["arm"], c["rep"]) for c in arm_calls] == [("model", "sonnet", 0), ("model", "sonnet", 1)]
    plan = next(r for r in _records(arm_file) if r["kind"] == "plan")
    window_input, arm_input = plan["inputs"]

    gemini_call = window_calls[0]
    assert {
        k: gemini_call[k] for k in ("turn", "callSite", "chatModel", "sentModel", "reply", "error", "swapLabel")
    } == {
        "turn": 4,
        "callSite": "replay_generate",
        "chatModel": "gemini",
        "sentModel": settings.gemini_model_name,
        "reply": "제미나이 응답",
        "error": None,
        "swapLabel": None,
    }
    assert gemini_call["tokens"] == {
        "prompt": 100,
        "cached": 10,
        "cacheWrite": None,
        "candidates": 7,
        "thoughts": 3,
        "total": 110,
    }
    assert gemini_call["costUsd"] == estimate_cost_usd(
        settings.gemini_model_name, input_tokens=100, cached_tokens=10, output_tokens=7, thoughts_tokens=3
    )
    assert gemini_call["promptSha256"] == window_input["promptSha256"]

    claude_call = arm_calls[0]
    assert {k: claude_call[k] for k in ("callSite", "chatModel", "sentModel", "reply", "error")} == {
        "callSite": "replay_generate",
        "chatModel": "sonnet",
        "sentModel": settings.bedrock_sonnet_model_id,
        "reply": "클로드 응답",
        "error": None,
    }
    assert claude_call["tokens"] == {
        "prompt": 100,
        "cached": 20,
        "cacheWrite": 30,
        "candidates": 9,
        "thoughts": 0,
        "total": 109,
    }
    assert claude_call["costUsd"] == estimate_cost_usd(
        settings.bedrock_sonnet_model_id,
        input_tokens=100,
        cached_tokens=20,
        output_tokens=9,
        thoughts_tokens=0,
        cache_write_tokens=30,
    )
    assert claude_call["promptSha256"] == arm_input["promptSha256"]
    assert all(c["latencyMs"] >= 0 and c["historyMessages"] > 0 for c in window_calls + arm_calls)
    assert claude_call["cumulativeChargedUsd"] > gemini_call["cumulativeChargedUsd"] > 0

    # 실제로 보낸 요청 — 생성 모델·정지 시퀀스(갈래 세트의 사용자 라벨)·지시문, 사용량 기록의 call_site.
    sent = fake.gemini_sent[0]
    assert sent["model"] == settings.gemini_model_name
    assert fake.bedrock_sent[0]["model"] == settings.bedrock_sonnet_model_id
    content = fake.bedrock_sent[0]["messages"][0]["content"]
    assert isinstance(content, list) and "cache_control" in content[1]  # 실제 생성과 같은 캐시 블록 모양
    assert (
        fake.recorded
        == [("replay_generate", settings.gemini_model_name), ("replay_generate", settings.bedrock_sonnet_model_id)] * 2
    )
    assert fake.built == 1


async def test_stop_sequence_comes_from_each_arms_set_label(
    db_session: AsyncSession, scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    measured = await db_session.get(PromptSet, scenario.measured_set_id)
    assert measured is not None
    await db_session.execute(
        sa.update(PromptSet).where(PromptSet.id == scenario.later_set_id).values(user_label="다른라벨")
    )
    await db_session.commit()
    fake = _Fake(monkeypatch)
    argv = _args(
        scenario,
        tmp_path,
        "--set",
        str(scenario.later_set_id),
        "--arm",
        "later",
        "--reps",
        "1",
        "--limit-calls",
        "2",
        "--execute",
    )
    assert await _run(db_session, argv, fake) == 0
    assert [s["config"].stop_sequences for s in fake.gemini_sent] == [[f"\n{measured.user_label}:"], ["\n다른라벨:"]]


async def test_dump_mismatch_refuses_every_arm_and_makes_no_calls(
    db_session: AsyncSession, scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = _records(scenario.dump)
    records[3]["prompt"] += " "  # 턴 4
    scenario.dump.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    fake = _Fake(monkeypatch)
    argv = _args(
        scenario, tmp_path, "--model", "sonnet", "--arm", "sonnet", "--limit-calls", "10", "--execute", turns=(3, 4)
    )
    assert await _run(db_session, argv, fake) == 2
    assert (fake.built, fake.gemini_sent, fake.bedrock_sent) == (0, [], [])
    # 변형 축 없이 현행만 부를 때도 같고, 지시문만 달라도 거부한다.
    records[2]["systemInstruction"] += " "  # 턴 3
    scenario.dump.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    window_only = _args(scenario, tmp_path / "only", "--limit-calls", "10", "--execute", turns=(3,))
    assert await _run(db_session, window_only, fake) == 2
    assert (fake.built, fake.gemini_sent) == (0, [])
    (only,) = _records(tmp_path / "only" / "out" / "gen.window.jsonl")
    assert only["checks"]["windowPromptIdentical"] and not only["checks"]["windowSystemInstructionIdentical"]
    plans = {r["turn"]: r for r in _records(tmp_path / "out" / "gen.window.jsonl")}
    assert plans[3]["passed"] and not plans[4]["passed"]
    assert plans[4]["checks"]["windowPromptIdentical"] is False and plans[4]["checks"]["firstDifferenceAt"] is not None
    # 현행이 덤프와 다르면 변형 갈래는 만들지도 않는다.
    assert [i["variant"] for i in plans[4]["inputs"]] == ["window"]
    assert not any(r["kind"] == "call" for r in _records(tmp_path / "out" / "gen.sonnet.jsonl"))


async def test_dry_run_builds_no_client_and_refused_turns_are_written(
    db_session: AsyncSession, scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _Fake(monkeypatch)
    assert await _run(db_session, _args(scenario, tmp_path, "--limit-calls", "10", turns=(1, 6)), fake) == 0
    assert fake.built == 0
    assert await _run(db_session, _args(scenario, tmp_path, "--limit-calls", "10", "--execute", turns=(7,)), fake) == 2
    assert fake.built == 0
    refused = _records(tmp_path / "out" / "gen.window.jsonl")[-1]
    assert refused["turn"] == 7 and "덤프에 턴 7" in refused["refused"]


async def test_call_limit_and_cost_limit_stop_the_calls(
    db_session: AsyncSession, scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _Fake(monkeypatch)
    argv = _args(scenario, tmp_path, "--model", "sonnet", "--arm", "s", "--limit-calls", "3", "--execute")
    assert await _run(db_session, argv, fake) == 0
    window = _records(tmp_path / "out" / "gen.window.jsonl")
    arm = _records(tmp_path / "out" / "gen.s.jsonl")
    calls = [r for r in window + arm if r["kind"] == "call"]
    assert sorted((c["rep"], c["arm"]) for c in calls) == [(0, "s"), (0, "window"), (1, "window")]
    assert window[-1]["kind"] == arm[-1]["kind"] == "budgetExhausted"
    assert window[-1]["used"] == 3

    first_cost = next(c for c in calls if c["arm"] == "window")["costUsd"]
    fake = _Fake(monkeypatch)
    out = tmp_path / "usd"
    argv = _args(scenario, out, "--limit-calls", "10", "--limit-usd", str(first_cost / 2), "--execute")
    assert await _run(db_session, argv, fake) == 0
    records = _records(out / "out" / "gen.window.jsonl")
    assert [r["kind"] for r in records] == ["plan", "call", "budgetExhausted"]


async def test_a_ledger_already_over_the_cost_limit_ends_without_calls(
    db_session: AsyncSession, scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "ledger" / "old.jsonl"
    ledger.parent.mkdir()
    ledger.write_text(json.dumps({"kind": "call", "costUsd": 0.5}) + "\n", encoding="utf-8")
    fake = _Fake(monkeypatch)
    argv = _args(
        scenario,
        tmp_path,
        "--limit-calls",
        "10",
        "--limit-usd",
        "0.5",
        "--ledger",
        str(tmp_path / "ledger" / "**" / "*.jsonl"),
        "--execute",
    )
    assert await _run(db_session, argv, fake) == 3
    assert fake.built == 0


def test_a_database_outside_this_machine_is_refused_before_anything_else(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://app:pw@postgres:5432/app")
    with pytest.raises(SystemExit, match="운영 DB"):
        generation_replay.main(["--room", str(uuid.uuid4())])


async def test_a_claude_call_without_usage_is_charged_at_its_models_ceiling_and_stops_the_cost_limit(
    db_session: AsyncSession, scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _Fake(monkeypatch)
    fake.bedrock_error = RuntimeError("정책 거절")
    argv = _args(
        scenario,
        tmp_path,
        "--model",
        "opus",
        "--arm",
        "opus",
        "--skip-window-calls",
        "--reps",
        "3",
        "--limit-calls",
        "10",
        "--limit-usd",
        "0.05",
        "--execute",
    )
    assert await _run(db_session, argv, fake) == 0
    records = _records(tmp_path / "out" / "gen.opus.jsonl")
    plan = records[0]
    (call,) = [r for r in records if r["kind"] == "call"]
    assert call["costUsd"] is None and call["error"].startswith("RuntimeError")
    # 원가를 모르는 호출은 그 모델 단가로 입력 추정 + 출력 상한을 센 값이다 — 옛 고정값(0.01)보다 훨씬 크다.
    expected = estimate_cost_usd(
        settings.bedrock_opus_model_id,
        input_tokens=plan["inputs"][1]["estimatedInputTokens"],
        cached_tokens=0,
        output_tokens=settings.bedrock_chat_max_tokens,
        thoughts_tokens=0,
    )
    assert expected is not None and expected > 0.05
    assert call["costCeilingUsd"] == pytest.approx(expected)
    assert call["cumulativeChargedUsd"] == pytest.approx(expected)
    assert records[-1]["kind"] == "budgetExhausted"
    # 장부도 같은 값으로 센다 — 다음 묶음의 상한에 들어간다.
    ledger = sum_ledger(ledger_paths(str(tmp_path / "out" / "*.jsonl")))
    assert ledger.charged_usd == pytest.approx(expected)


async def test_running_the_same_turns_and_arm_again_into_the_same_output_is_refused(
    db_session: AsyncSession, scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _Fake(monkeypatch)
    argv = _args(scenario, tmp_path, "--reps", "1", "--limit-calls", "10", "--execute")
    assert await _run(db_session, argv, fake) == 0
    before = (tmp_path / "out" / "gen.window.jsonl").read_text(encoding="utf-8")
    # 같은 (턴, 반복, 갈래)가 이미 있다 — 다시 붙이면 쌍 판정이 한 칸에 응답 둘을 본다.
    assert await _run(db_session, argv, fake) == 2
    assert (tmp_path / "out" / "gen.window.jsonl").read_text(encoding="utf-8") == before
    assert len(fake.gemini_sent) == 1
    # 변형 갈래를 더할 때는 현행을 다시 부르지 않으면 된다.
    more = _args(
        scenario,
        tmp_path,
        "--model",
        "sonnet",
        "--arm",
        "s",
        "--skip-window-calls",
        "--reps",
        "1",
        "--limit-calls",
        "10",
        "--execute",
    )
    assert await _run(db_session, more, fake) == 0
    assert (tmp_path / "out" / "gen.window.jsonl").read_text(encoding="utf-8").startswith(before)
    assert len(fake.bedrock_sent) == 1


async def test_plan_records_the_dumped_and_current_actual_window_model(
    db_session: AsyncSession, scenario: Scenario
) -> None:
    same = (await _assemble(db_session, scenario, 2)).checks
    assert (same["dumpModel"], same["windowSentModel"], same["windowModelDiffers"]) == (
        settings.gemini_model_name,
        settings.gemini_model_name,
        False,
    )
    records = _records(scenario.dump)
    records[1]["model"] = "gemini-그때-모델"  # 턴 2
    scenario.dump.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    assembly = await _assemble(db_session, scenario, 2)
    assert assembly.checks["dumpModel"] == "gemini-그때-모델" and assembly.checks["windowModelDiffers"] is True
    # 두 갈래가 같은 모델로 생성하므로 쌍은 공정하다 — 표시만 하고 거부하지 않는다.
    assert assembly.passed


async def test_a_missing_active_set_refuses_the_turn_without_calls(
    db_session: AsyncSession, scenario: Scenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await db_session.execute(
        sa.update(PromptSet).where(PromptSet.lane == "story", PromptSet.model == "opus").values(lane="legacy")
    )
    await db_session.commit()
    fake = _Fake(monkeypatch)
    argv = _args(scenario, tmp_path, "--model", "opus", "--arm", "opus", "--limit-calls", "10", "--execute")
    assert await _run(db_session, argv, fake) == 2
    assert fake.built == 0
    (refused,) = _records(tmp_path / "out" / "gen.opus.jsonl")
    assert refused["turn"] == 4 and "opus" in refused["refused"]
