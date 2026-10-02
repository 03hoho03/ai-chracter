"""`scripts/judgment_replay` 의 입력 — 운영 문안 스냅숏으로 렌더한 판정 프롬프트가 서버 빌더 + DB 행이 만드는 글과
바이트까지 같은지, 설계 장면의 정답이 판정 문구·조건에서 도출되는 모양인지."""

import json
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.ending_rules import is_ending_check_due
from api.chat.prompt_builder import (
    PromptLane,
    build_ending_judgment_prompt,
    build_stat_judgment_prompt,
    load_active_prompt_set,
)
from api.db.models.auth import User
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.media import Asset, AssetKind, AssetStatus
from api.db.models.story import Ending, StartingSetup, StatDef
from judgment_replay import scenes
from judgment_replay.prompts import dump_prompt_snapshot, load_prompt_snapshot
from seed_content.ids import SEED_AUTHOR_USER_ID
from seed_content.loader import TUTORIAL_STORIES_DIR, load_story
from seed_content.upsert import story_version_id, upsert_story

STORY_SLUG = "tutorial-filmclub"


async def _snapshot_from_db(db_session: AsyncSession) -> dict[str, Any]:
    lanes: tuple[PromptLane, ...] = ("story", "character", "publish_filter")
    loaded = [await load_active_prompt_set(db_session, lane=lane) for lane in lanes]
    return dump_prompt_snapshot(loaded)


def _inputs(snapshot: dict[str, Any], tmp_path: Path) -> dict[str, scenes.ReplayInput]:
    return {item.input_id: item for item in scenes.build_inputs(load_prompt_snapshot(snapshot), images_dir=tmp_path)}


# ---- 렌더 동등성: 서버 빌더 + DB 행과 바이트까지 같다 ----------------------------------------------------------


async def test_stat_and_ending_prompts_match_server_render_from_seeded_rows(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """시드 업서트가 만든 스탯·엔딩 행과 DB 활성 세트를 서버 빌더에 넣은 글이 리플레이 입력과 같아야 한다. 스냅숏
    왕복(섹션 순서·conditional·라벨)이나 시드 → ORM 변환(정수 범위·소수 현재값·카운터 꼬리·entity_id)이 하나라도
    어긋나면 깨진다."""
    db_session.add(
        User(
            id=SEED_AUTHOR_USER_ID,
            email="seed-creator@example.com",
            nickname="시드 작가",
            birth_date=date(1995, 1, 1),
            terms_agreed_at=datetime.now(UTC),
            privacy_agreed_at=datetime.now(UTC),
        )
    )
    asset = Asset(
        owner_user_id=SEED_AUTHOR_USER_ID,
        storage_key=f"assets/seed/{uuid.uuid4()}.png",
        kind=AssetKind.THUMBNAIL,
        status=AssetStatus.READY,
    )
    db_session.add(asset)
    await db_session.flush()
    payload = load_story(TUTORIAL_STORIES_DIR / f"{STORY_SLUG}.json").model_copy(
        update={"thumbnail_asset_id": asset.id}
    )
    await upsert_story(db_session, STORY_SLUG, payload)

    story_set, story_sections = await load_active_prompt_set(db_session, lane="story")
    setup = await db_session.scalar(
        select(StartingSetup).where(StartingSetup.content_version_id == story_version_id(STORY_SLUG))
    )
    assert setup is not None
    stat_defs = list((await db_session.scalars(select(StatDef).where(StatDef.starting_setup_id == setup.id))).all())
    by_name = {stat_def.name: stat_def for stat_def in stat_defs}

    inputs = _inputs(await _snapshot_from_db(db_session), tmp_path)
    raw = json.loads(scenes.DATA_PATH.read_text(encoding="utf-8"))

    stat_case = next(case for case in raw["stat_cases"] if case["id"] == "stat-15")
    log, index = stat_case["turn"]
    turn = raw["logs"][log][index]
    current = {str(by_name[name].entity_id): float(value) for name, value in stat_case["current"].items()}
    expected_stat_prompt = build_stat_judgment_prompt(
        prompt_set=story_set,
        sections=story_sections,
        stat_defs=stat_defs,
        current_stats=current,
        user_message=turn["user"],
        assistant_message=scenes.assistant_text(turn),
    )
    assert inputs["stat-15"].prompt == expected_stat_prompt

    ending_case = next(case for case in raw["ending_cases"] if case["id"] == "end-05")
    ending = await db_session.scalar(
        select(Ending).where(Ending.starting_setup_id == setup.id, Ending.name == ending_case["ending"])
    )
    assert ending is not None
    turns = [raw["logs"][name][i] for name, start, end in ending_case["turns"] for i in range(start, end)]
    history = [ChatMessage(role=ChatMessageRole.ASSISTANT, content=setup.opening_message)]
    for past in turns[:-1]:
        history.append(ChatMessage(role=ChatMessageRole.USER, content=past["user"]))
        history.append(ChatMessage(role=ChatMessageRole.ASSISTANT, content=scenes.assistant_text(past)))
    expected_ending_prompt = build_ending_judgment_prompt(
        prompt_set=story_set,
        sections=story_sections,
        judgment_prompt=ending.judgment_prompt,
        history=history,
        user_message=turns[-1]["user"],
        assistant_message=scenes.assistant_text(turns[-1]),
        memory_summary="",
    )
    assert inputs["end-05"].prompt == expected_ending_prompt


async def test_prompt_snapshot_round_trip_keeps_every_rendered_channel(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """운영 스냅숏과 같은 모양으로 덤프한 DB 세트로 모든 판정 종류가 렌더되고, 레인별 세트 id 가 기록된다."""
    snapshot = await _snapshot_from_db(db_session)
    loaded = load_prompt_snapshot(snapshot)
    inputs = scenes.build_inputs(loaded, images_dir=tmp_path)
    assert {item.kind for item in inputs} == {"stat", "image", "ending", "publish"}
    assert all(item.prompt for item in inputs)
    assert loaded.set_ids == {s["lane"]: s["id"] for s in snapshot["sets"]}


# ---- 장면 데이터의 정답이 조건에서 도출되는 모양인지 -----------------------------------------------------------


def _scene_raw() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(scenes.DATA_PATH.read_text(encoding="utf-8"))
    return data


def _case_turns(raw: dict[str, Any], spec: list[list[Any]]) -> list[dict[str, Any]]:
    return [raw["logs"][name][i] for name, start, end in spec for i in range(start, end)]


def test_stat_cases_expecting_no_change_never_name_that_character() -> None:
    """스탯 설명은 '장면에 나오지 않고 언급되지도 않았으면 그대로'다. 0 을 기대한 인물의 이름·호칭이 그 턴 글
    (상태창 포함)에 있으면 정답이 0~1 로 흐려진다."""
    raw = _scene_raw()
    aliases: dict[str, list[str]] = raw["stat_aliases"]
    assert len(raw["stat_cases"]) == 20
    for case in raw["stat_cases"]:
        log, index = case["turn"]
        turn = raw["logs"][log][index]
        text = turn["user"] + scenes.assistant_text(turn)
        for stat, direction in case["expected"].items():
            assert direction in {"+", "-", "0"}
            if direction == "0":
                assert not [a for a in aliases[stat] if a in text], (case["id"], stat)


def test_ending_cases_sit_on_turns_where_the_server_would_judge() -> None:
    raw = _scene_raw()
    payload = load_story(TUTORIAL_STORIES_DIR / f"{STORY_SLUG}.json")
    gates = {ending.name: ending.turn_count_gate for ending in payload.starting_setups[0].endings}
    cases = raw["ending_cases"]
    assert len(cases) == 10
    assert sum(case["expected"] for case in cases) == 5
    for case in cases:
        turn_count = len(_case_turns(raw, case["turns"]))
        assert 10 <= turn_count <= 30, case["id"]
        assert is_ending_check_due(turn_count, gates[case["ending"]]), case["id"]


def test_image_cases_mix_short_and_long_rooms_and_name_real_candidates() -> None:
    raw = _scene_raw()
    lengths = [len(_case_turns(raw, case["turns"])) for case in raw["image_cases"]]
    assert len(lengths) == 12
    assert sum(n <= 5 for n in lengths) == 6
    assert sum(20 <= n <= 30 for n in lengths) == 6
    cell_keys = {cell["key"] for cell in raw["story_media_cells"]}
    for case in raw["image_cases"]:
        expected = case["expected"]
        if expected is None:
            continue
        if case["target"] == "story":
            assert expected in cell_keys
        else:
            assert expected in {f"상황 이미지 {n}" for n in range(1, 6)}
