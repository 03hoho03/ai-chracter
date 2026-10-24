"""운영 문안 맞추기 — 운영 활성 세트를 내보낸 파일로 측정 DB 의 (레인, 모델)별 활성 세트를 통째로 바꾸고, 다시 읽어 섹션마다 본문
해시·조건·순서와 세트 라벨(버전과 프롬프트에 실리는 화자 라벨 칸)을 견준다. 차이는 건수와 섹션 키로만 내고 본문은 어디에도 내지 않는다. 문안은 전부 지어낸 것이다."""

import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.redis import redis_client
from api.db.models.prompt import PromptSection, PromptSet
from memory_eval import prompt_sync as ps

LANES = ("story", "character")
# 지어낸 문안 — 출력에 이 글자가 하나라도 나오면 본문이 샌 것이다.
BODY_MARK = "보라색고래가부르는노래"


def _body(lane: str, model: str, slot: str) -> str:
    return f"{BODY_MARK} {lane} {model} {slot} 지어낸 문안이다."


def _labels(lane: str, model: str) -> dict[str, str]:
    """지어낸 화자 라벨 — 측정 DB 시드 값과 겹치지 않게 체인마다 다르게."""
    return {field: f"지어낸{field}-{lane}-{model}" for field in ps.LABEL_FIELDS}


def _row(lane: str, model: str, label: str, slot: str, *, order: int, conditional: bool = False) -> dict[str, Any]:
    body = _body(lane, model, slot)
    return {
        "export_format": ps.EXPORT_FORMAT, "kind": "section", "route_revision": None, "lane": lane, "model": model,
        "set_version": label, "set_id": str(uuid.uuid4()), **_labels(lane, model),
        "channel": "system", "scope": "both", "slot": slot, "variant": "", "order": order,
        "conditional": conditional, "md5": hashlib.md5(body.encode()).hexdigest(), "chars": len(body), "body": body,
    }  # fmt: skip


def _write_export(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text("BEGIN\n" + json.dumps(rows, ensure_ascii=False) + "\nROLLBACK\n", encoding="utf-8")
    return path


async def _chains(db: AsyncSession) -> list[tuple[str, str]]:
    rows = await db.execute(
        sa.select(PromptSet.lane, PromptSet.model)
        .where(PromptSet.status == "published", PromptSet.lane.in_(LANES))
        .distinct()
    )
    return sorted((lane, model) for lane, model in rows.all())


async def _export_file(db: AsyncSession, tmp_path: Path, *, extra: list[dict[str, Any]] | None = None) -> Path:
    """측정 DB 의 story·character 활성 체인 전부에 지어낸 섹션 셋씩 — 운영 읽기 명령이 남기는 꼴(앞뒤 트랜잭션 줄 사이 JSON 한 줄)
    이다. 다른 레인 줄도 섞어 둔다(맞추기는 두 레인만 본다)."""
    chains = await _chains(db)
    if not chains:
        for lane in LANES:
            db.add(_published_set(lane, "gemini"))
        await db.flush()
        chains = await _chains(db)
    rows = [
        _row(lane, model, f"lab-{lane}-{model}", slot, order=order, conditional=(slot == "c"))
        for lane, model in chains
        for order, slot in enumerate(("a", "b", "c"))
    ]
    rows += [_row("novel", "gemini", "lab-novel", "a", order=0)]
    rows += extra or []
    path = tmp_path / "active-sections.json"
    path.write_text("BEGIN\n" + json.dumps(rows, ensure_ascii=False) + "\nROLLBACK\n", encoding="utf-8")
    return path


def _published_set(lane: str, model: str) -> PromptSet:
    return PromptSet(
        version=f"t-{uuid.uuid4().hex[:8]}", status="published", lane=lane, model=model, user_label="사용자",
        story_assistant_label="진행자", story_example_label="서술자", character_assistant_label="캐릭터",
        published_at=datetime.now(UTC) + timedelta(days=1),
    )  # fmt: skip


async def _active_id(db: AsyncSession, lane: str, model: str) -> uuid.UUID:
    set_id = await db.scalar(
        sa.select(PromptSet.id)
        .where(PromptSet.status == "published", PromptSet.lane == lane, PromptSet.model == model)
        .order_by(PromptSet.published_at.desc(), PromptSet.id.desc())
        .limit(1)
    )
    assert set_id is not None
    return set_id


async def _synced(db_session: AsyncSession, tmp_path: Path) -> Any:
    exported = ps.load_export(await _export_file(db_session, tmp_path))
    await ps.overwrite(db_session, exported)
    return exported


async def test_overwrite_then_compare_finds_no_difference_and_exits_zero(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    exported = await _synced(db_session, tmp_path)
    report = await ps.compare(db_session, exported)
    assert report["differences"] == 0
    assert ps.exit_code(report) == 0
    lane, model = sorted(exported.sets)[0]
    active = await db_session.get(PromptSet, await _active_id(db_session, lane, model))
    assert active is not None and active.version == f"lab-{lane}-{model}"
    assert {field: getattr(active, field) for field in ps.LABEL_FIELDS} == _labels(lane, model)
    slots = await db_session.scalars(
        sa.select(PromptSection.slot).where(PromptSection.prompt_set_id == active.id).order_by(PromptSection.order)
    )
    assert list(slots) == ["a", "b", "c"]


async def test_check_only_counts_one_body_difference_by_its_key_and_exits_non_zero(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    exported = await _synced(db_session, tmp_path)
    lane, model = sorted(exported.sets)[0]
    set_id = await _active_id(db_session, lane, model)
    await db_session.execute(
        sa.update(PromptSection)
        .where(PromptSection.prompt_set_id == set_id, PromptSection.slot == "b")
        .values(body="어드민이 고친 지어낸 문안")
    )
    report = await ps.compare(db_session, exported)
    assert report["differences"] == 1
    assert report["counts"]["body"] == 1
    assert report["keys"]["body"] == [f"{lane}/{model}/system/both/b/"]
    assert ps.exit_code(report) != 0


@pytest.mark.parametrize("field", ["conditional", "order"])
async def test_only_the_condition_or_only_the_order_changed_still_exits_non_zero(
    db_session: AsyncSession, tmp_path: Path, field: str
) -> None:
    exported = await _synced(db_session, tmp_path)
    lane, model = sorted(exported.sets)[0]
    set_id = await _active_id(db_session, lane, model)
    values = {"conditional": True} if field == "conditional" else {"order": 7}
    await db_session.execute(
        sa.update(PromptSection)
        .where(PromptSection.prompt_set_id == set_id, PromptSection.slot == "a")
        .values(**values)
    )
    report = await ps.compare(db_session, exported)
    assert report["counts"][field] == 1
    assert report["differences"] == 1
    assert ps.exit_code(report) != 0


async def test_only_the_set_label_changed_still_exits_non_zero(db_session: AsyncSession, tmp_path: Path) -> None:
    exported = await _synced(db_session, tmp_path)
    lane, model = sorted(exported.sets)[0]
    await db_session.execute(
        sa.update(PromptSet).where(PromptSet.id == await _active_id(db_session, lane, model)).values(version="다른-판")
    )
    report = await ps.compare(db_session, exported)
    assert report["counts"]["label"] == 1
    assert report["keys"]["label"] == [f"{lane}/{model}/version"]
    assert ps.exit_code(report) != 0


@pytest.mark.parametrize(
    "field", ["user_label", "story_assistant_label", "story_example_label", "character_assistant_label"]
)
async def test_only_one_speaker_label_changed_still_exits_non_zero(
    db_session: AsyncSession, tmp_path: Path, field: str
) -> None:
    exported = await _synced(db_session, tmp_path)
    lane, model = sorted(exported.sets)[0]
    await db_session.execute(
        sa.update(PromptSet)
        .where(PromptSet.id == await _active_id(db_session, lane, model))
        .values({field: "다른 라벨"})
    )
    report = await ps.compare(db_session, exported)
    assert report["keys"]["label"] == [f"{lane}/{model}/{field}"]
    assert report["differences"] == 1
    assert ps.exit_code(report) != 0


def test_old_export_without_the_speaker_labels_is_refused_by_field_name(tmp_path: Path) -> None:
    row = _row("story", "gemini", "lab", "a", order=0)
    for field in ("export_format", *ps.LABEL_FIELDS):
        del row[field]
    with pytest.raises(SystemExit) as stop:
        ps.load_export(_write_export(tmp_path / "old.json", [row]))
    message = str(stop.value.code)
    assert all(field in message for field in ("export_format", *ps.LABEL_FIELDS))
    assert "지어낸" not in message


async def _chain_state(db: AsyncSession) -> dict[tuple[str, str], Any]:
    """체인마다 활성 세트의 라벨 칸과 섹션(키·해시·조건·순서) — 덮어쓰기 전후를 견줄 지문."""
    state: dict[tuple[str, str], Any] = {}
    for lane, model in await _chains(db):
        active = await db.get(PromptSet, await _active_id(db, lane, model), populate_existing=True)
        assert active is not None
        rows = await db.execute(
            sa.select(
                PromptSection.channel, PromptSection.scope, PromptSection.slot, PromptSection.variant,
                sa.func.md5(PromptSection.body), PromptSection.conditional, PromptSection.order,
            ).where(PromptSection.prompt_set_id == active.id)
        )  # fmt: skip
        state[(lane, model)] = (
            active.version,
            tuple(getattr(active, field) for field in ps.LABEL_FIELDS),
            sorted(tuple(r) for r in rows.all()),
        )
    return state


async def test_a_label_clash_on_the_last_chain_is_refused_before_any_chain_is_written(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    exported = ps.load_export(await _export_file(db_session, tmp_path))
    lane, model = sorted(exported.sets)[-1]
    older = _published_set(lane, model)
    older.version = f"lab-{lane}-{model}"
    older.published_at = datetime(2000, 1, 1, tzinfo=UTC)
    db_session.add(older)
    await db_session.flush()
    before = await _chain_state(db_session)
    with pytest.raises(SystemExit) as stop:
        await ps.overwrite(db_session, exported)
    assert f"{lane}/{model}=lab-{lane}-{model}" in str(stop.value.code)
    assert await _chain_state(db_session) == before


def _open(db: AsyncSession) -> Any:
    @asynccontextmanager
    async def open_db(*_: str) -> AsyncIterator[AsyncSession]:
        yield db

    return open_db


async def test_the_overwrite_run_clears_the_active_set_cache_and_leaves_other_keys(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    exported = ps.load_export(await _export_file(db_session, tmp_path))
    cached = ["prompt_set:active:story:gemini", "prompt_set:active:character:opus"]
    other = "chat_room:turn_lock:prompt-sync-run"
    for key in [*cached, other]:
        await redis_client.set(key, "x")
    try:
        checked = await ps.run_sync(_open(db_session), exported, check_only=True, redis_url=settings.redis_url)
        assert checked["compare"]["differences"] > 0 and "overwritten" not in checked
        assert await redis_client.exists(*cached) == len(cached)

        result = await ps.run_sync(_open(db_session), exported, check_only=False, redis_url=settings.redis_url)
        assert result["compare"]["differences"] == 0
        assert result["redisDeleted"] >= len(cached)
        assert await redis_client.exists(*cached) == 0
        assert await redis_client.exists(other) == 1
    finally:
        await redis_client.delete(other)


async def test_templates_frozen_before_the_sync_are_refused_and_synced_templates_pass(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    exported = ps.load_export(await _export_file(db_session, tmp_path))
    templates = ["lm_eval_s9_cp100_frozen", "lm_eval_s9_cp300_frozen"]
    with pytest.raises(SystemExit) as stop:
        await ps.require_templates_synced(templates, exported, _open(db_session))
    message = str(stop.value.code)
    assert all(name in message for name in templates)
    assert BODY_MARK not in message and "지어낸" not in message

    await ps.overwrite(db_session, exported)
    await ps.require_templates_synced(templates, exported, _open(db_session))


def test_sync_refuses_while_a_measurement_server_of_this_tree_is_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval import server
    from memory_eval_cli import main

    monkeypatch.setattr(server, "running_api_servers", lambda: [(4242, str(server.API_DIR), 8123)])
    export = _write_export(tmp_path / "export.json", [_row("story", "gemini", "s", "a", order=0)])
    code = main(
        ["--run", str(tmp_path / "run"), "sync-prompts", "--export", str(export), "--redis-url", "redis://x/15"]
    )
    assert code == 2
    assert "4242" in capsys.readouterr().err


def test_the_run_template_orders_sync_insert_freeze_and_pins_the_export_on_probe() -> None:
    template = (Path(ps.__file__).parent / "run_template.sh").read_text(encoding="utf-8")
    assert template.index("sync-prompts") < template.index(" insert ") < template.index(" freeze ")
    assert '--prompt-export "$PROMPT_EXPORT"' in template


async def test_sections_only_in_the_export_or_only_in_the_database_are_differences(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    exported = await _synced(db_session, tmp_path)
    lane, model = sorted(exported.sets)[0]
    set_id = await _active_id(db_session, lane, model)
    await db_session.execute(
        sa.delete(PromptSection).where(PromptSection.prompt_set_id == set_id, PromptSection.slot == "a")
    )
    db_session.add(
        PromptSection(
            prompt_set_id=set_id, channel="system", scope="both", slot="z", variant="", body="남는 지어낸 문안",
            conditional=False, order=9,
        )
    )  # fmt: skip
    await db_session.flush()
    report = await ps.compare(db_session, exported)
    assert report["keys"]["missingSections"] == [f"{lane}/{model}/system/both/a/"]
    assert report["keys"]["extraSections"] == [f"{lane}/{model}/system/both/z/"]
    assert report["differences"] == 2
    assert ps.exit_code(report) != 0


async def test_report_carries_counts_and_keys_but_no_body_text(db_session: AsyncSession, tmp_path: Path) -> None:
    exported = await _synced(db_session, tmp_path)
    lane, model = sorted(exported.sets)[0]
    set_id = await _active_id(db_session, lane, model)
    await db_session.execute(
        sa.update(PromptSection)
        .where(PromptSection.prompt_set_id == set_id, PromptSection.slot == "b")
        .values(body=f"{BODY_MARK} 고친 글")
    )
    report = await ps.compare(db_session, exported)
    text = json.dumps(report, ensure_ascii=False)
    assert report["differences"] == 1
    assert BODY_MARK not in text and "지어낸" not in text and "고친 글" not in text


def test_export_with_a_body_that_does_not_match_its_recorded_hash_is_refused(tmp_path: Path) -> None:
    row = _row("story", "gemini", "lab", "a", order=0)
    row["body"] += " 덧붙임"
    with pytest.raises(SystemExit) as stop:
        ps.load_export(_write_export(tmp_path / "export.json", [row]))
    assert "story/gemini/system/both/a/" in str(stop.value.code)
    assert "덧붙임" not in str(stop.value.code)


def test_export_needs_exactly_one_json_line(tmp_path: Path) -> None:
    path = tmp_path / "export.json"
    path.write_text("BEGIN\nROLLBACK\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        ps.load_export(path)


def test_export_keeps_only_the_story_and_character_lanes(tmp_path: Path) -> None:
    rows = [_row("story", "gemini", "s", "a", order=0), _row("novel", "gemini", "n", "a", order=0)]
    path = tmp_path / "export.json"
    path.write_text("BEGIN\n" + json.dumps(rows, ensure_ascii=False) + "\nROLLBACK\n", encoding="utf-8")
    assert sorted(ps.load_export(path).sets) == [("story", "gemini")]


async def test_clearing_the_cache_deletes_only_active_prompt_set_keys() -> None:
    await redis_client.set("prompt_set:active:story:gemini", "x")
    await redis_client.set("chat_room:turn_lock:prompt-sync-test", "x")
    try:
        deleted = await ps.clear_prompt_set_cache(settings.redis_url)
        assert "prompt_set:active:story:gemini" in deleted
        assert await redis_client.exists("chat_room:turn_lock:prompt-sync-test") == 1
    finally:
        await redis_client.delete("chat_room:turn_lock:prompt-sync-test")


def test_the_command_refuses_a_database_outside_the_measurement_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://u:p@localhost:5432/ai_character_chat")
    export = tmp_path / "export.json"
    export.write_text(
        "BEGIN\n" + json.dumps([_row("story", "gemini", "s", "a", order=0)], ensure_ascii=False) + "\nROLLBACK\n",
        encoding="utf-8",
    )
    for extra in ([], ["--check-only"]):
        code = main(
            ["--run", str(tmp_path / "run"), "sync-prompts", "--export", str(export),
             "--redis-url", "redis://localhost:6379/15", *extra]
        )  # fmt: skip
        assert code == 2
        assert "lm_eval_" in capsys.readouterr().err


def _probe_plants(tmp_path: Path) -> tuple[Path, Path]:
    """드라이런 프로브가 계획을 세울 수 있는 2차 형식 심기 표와 분할 — 지어낸 문항, 시험 절반 주 지표 하한을 넘는 수."""
    from memory_eval import holdout

    plants = [
        {
            "id": f"{category}-{i:02d}", "category": category, "primary": True, "subtype": "x", "plant_turns": [20 + i],
            "plants": [{"turn": 20 + i, "line": "assistant", "who": "민지", "assertedBy": "narration",
                        "keywords": [f"단서{i}"]}],
            "keywords": [f"단서{i}"], "ask_checkpoints": [100, 300], "score_checkpoint": 300, "questionForm": "direct",
            "question": f"지어낸 질문 {i}", "answer_key": {"mode": "match", "bundles": [[f"단서{i}"]], "correct": "지어낸 답"},
            "expected_fact": None,
        }
        for category in ("relation", "secret", "false_premise", "correction")
        for i in range(13)
    ]  # fmt: skip
    path = tmp_path / "plants.json"
    path.write_text(
        json.dumps({"version": "v2", "checkpoints": [100, 300], "plants": plants, "abstains": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    assert holdout.write_split(path, tmp_path / "split")["ok"]
    return path, tmp_path / "split"


async def _export_rows_of(url: str) -> list[dict[str, Any]]:
    """그 DB 의 story·character 활성 세트를 지금 꼴의 섹션 원소로 — 운영 읽기 명령이 내는 것과 같은 칸. 테스트 DB 의 시드 문안을 읽어
    임시 파일로만 쓴다."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with AsyncSession(engine) as db:
            rows: list[dict[str, Any]] = []
            for (lane, model), active in sorted((await ps.active_sets(db)).items()):
                sections = await db.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == active.id))
                for section in sections:
                    rows.append(
                        {
                            "export_format": ps.EXPORT_FORMAT, "kind": "section", "route_revision": None,
                            "lane": lane, "model": model, "set_version": active.version, "set_id": str(active.id),
                            **{field: getattr(active, field) for field in ps.LABEL_FIELDS},
                            "channel": section.channel, "scope": section.scope, "slot": section.slot,
                            "variant": section.variant, "order": section.order, "conditional": section.conditional,
                            "md5": hashlib.md5(section.body.encode()).hexdigest(), "chars": len(section.body),
                            "body": section.body,
                        }
                    )  # fmt: skip
            return rows
    finally:
        await engine.dispose()


def test_probe_refuses_an_unsynced_template_before_any_probe_work_and_passes_a_synced_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """프로브는 계획한 체크포인트 템플릿마다 내보내기와 대조한다. 템플릿 이름이 테스트 DB 를 가리키게 바꿔 끼우고, 그 DB 와 같은
    내보내기면 대조를 지나 드라이런 계획까지 가고, 섹션 하나가 다른 내보내기면 계획을 내기 전에 템플릿 이름·건수만 대고 거부한다."""
    import asyncio

    from sqlalchemy.engine import make_url

    from memory_eval import checkpoint
    from memory_eval_cli import main

    test_db = make_url(settings.database_url).database
    assert test_db
    asked: list[str] = []

    def template_db_name(cp: int, label: str) -> str:
        asked.append(f"{label}:{cp}")
        return test_db

    monkeypatch.setattr(checkpoint, "template_db_name", template_db_name)
    rows = asyncio.run(_export_rows_of(settings.database_url))
    assert rows
    synced = _write_export(tmp_path / "synced.json", rows)
    changed = [dict(row) for row in rows]
    changed[0]["body"] = f"{BODY_MARK} 다른 문안"
    changed[0]["md5"] = hashlib.md5(changed[0]["body"].encode()).hexdigest()
    unsynced = _write_export(tmp_path / "unsynced.json", changed)
    plants, split_dir = _probe_plants(tmp_path)
    argv = ["--run", str(tmp_path), "probe", "--plants", str(plants), "--split-dir", str(split_dir),
            "--stage", "s9", "--arm", "A", "--dry-run", "--checkpoints", "100,300"]  # fmt: skip

    assert main([*argv, "--prompt-export", str(unsynced)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"{test_db}: 차이 1건" in captured.err
    assert BODY_MARK not in captured.err and "다른 문안" not in captured.err
    assert asked == ["s9:100", "s9:300"]

    assert main([*argv, "--prompt-export", str(synced)]) == 0
    assert json.loads(capsys.readouterr().out)["plan"]


# --- 모델 배정 표 — 운영 표를 그대로 옮기고, 비었으면 측정 표도 비운다 -------------------------------------------------


def _route(
    lane: str,
    room_model: str,
    stage: str,
    *,
    chain_model: str | None = "gemini",
    call_model: str = "gemini",
    backend: str = "gemini",
) -> dict[str, Any]:
    """내보낸 배정 표 한 행 — 운영 읽기 명령이 섹션 원소와 같은 배열에 싣는 꼴."""
    return {
        "export_format": ps.EXPORT_FORMAT, "kind": "route", "lane": lane, "room_model": room_model, "stage": stage,
        "chain_model": chain_model, "call_model": call_model, "backend": backend,
    }  # fmt: skip


def _route_row(lane: str, room_model: str, stage: str, *, chain_model: str = "gemini", backend: str = "gemini") -> Any:
    from api.db.models.prompt import PromptRoute

    return PromptRoute(
        lane=lane, room_model=room_model, stage=stage, chain_model=chain_model, call_model="gemini", backend=backend
    )


async def _table(db: AsyncSession) -> list[tuple[Any, ...]]:
    from api.db.models.prompt import PromptRoute

    rows = await db.execute(
        sa.select(
            PromptRoute.lane, PromptRoute.room_model, PromptRoute.stage, PromptRoute.chain_model,
            PromptRoute.call_model, PromptRoute.backend,
        )
    )  # fmt: skip
    return sorted(tuple(r) for r in rows.all())


ROUTES = [_route("story", "opus", "stat_judgment"), _route("story", "opus", "ending_judgment")]


async def test_exported_routes_replace_the_measurement_table_and_compare_clean(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    db_session.add(_route_row("story", "gemini", "memory_summary"))
    await db_session.flush()
    rows = [dict(r) for r in ROUTES]
    exported = ps.load_export(await _export_file(db_session, tmp_path, extra=rows))
    result = await ps.overwrite(db_session, exported)
    assert result["routes"] == {"removed": 1, "inserted": 2}
    assert await _table(db_session) == [
        ("story", "opus", "ending_judgment", "gemini", "gemini", "gemini"),
        ("story", "opus", "stat_judgment", "gemini", "gemini", "gemini"),
    ]
    report = await ps.compare(db_session, exported)
    assert report["differences"] == 0
    assert report["routes"] == 2


async def test_an_export_with_an_empty_route_table_empties_the_measurement_table(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    db_session.add(_route_row("story", "opus", "stat_judgment"))
    await db_session.flush()
    exported = ps.load_export(await _export_file(db_session, tmp_path))
    before = await ps.compare(db_session, exported)
    assert before["keys"]["extraRoutes"] == ["story/opus/stat_judgment"]

    await ps.overwrite(db_session, exported)
    assert await _table(db_session) == []
    assert (await ps.compare(db_session, exported))["differences"] == 0


async def test_route_differences_are_counted_by_their_own_kinds(db_session: AsyncSession, tmp_path: Path) -> None:
    from api.db.models.prompt import PromptRoute

    exported = ps.load_export(await _export_file(db_session, tmp_path, extra=[dict(r) for r in ROUTES]))
    await ps.overwrite(db_session, exported)
    await db_session.execute(sa.delete(PromptRoute).where(PromptRoute.stage == "stat_judgment"))
    await db_session.execute(
        sa.update(PromptRoute).where(PromptRoute.stage == "ending_judgment").values(backend="anthropic")
    )
    db_session.add(_route_row("character", "opus", "memory_fact"))
    await db_session.flush()

    report = await ps.compare(db_session, exported)
    assert report["keys"]["missingRoutes"] == ["story/opus/stat_judgment"]
    assert report["keys"]["extraRoutes"] == ["character/opus/memory_fact"]
    assert report["keys"]["route"] == ["story/opus/ending_judgment/backend"]
    assert report["counts"]["missingRoutes"] == report["counts"]["extraRoutes"] == report["counts"]["route"] == 1
    assert report["differences"] == 3
    assert ps.exit_code(report) != 0


async def test_the_route_revision_rides_on_the_section_rows_and_reaches_the_report(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    path = await _export_file(db_session, tmp_path)
    rows = json.loads(path.read_text(encoding="utf-8").splitlines()[1])
    for row in rows:
        row["route_revision"] = 7
    exported = ps.load_export(_write_export(tmp_path / "rev.json", rows))
    assert exported.route_revision == 7
    await ps.overwrite(db_session, exported)
    assert (await ps.compare(db_session, exported))["routeRevision"] == 7


def test_a_format_two_export_is_refused_by_the_fields_it_lacks(tmp_path: Path) -> None:
    row = _row("story", "gemini", "lab", "a", order=0)
    del row["kind"], row["route_revision"]
    row["export_format"] = 2
    with pytest.raises(SystemExit) as stop:
        ps.load_export(_write_export(tmp_path / "v2.json", [row]))
    message = str(stop.value.code)
    assert "kind" in message and "route_revision" in message
    assert BODY_MARK not in message and "지어낸" not in message


@pytest.mark.parametrize(
    ("case", "needle"),
    [
        ("chain-missing", "story/opus/stat_judgment"),
        ("duplicate", "story/opus/stat_judgment"),
        ("revisions-disagree", "route_revision"),
        ("unknown-kind", "kind"),
    ],
)
def test_inconsistent_route_rows_are_refused_before_anything_is_written(tmp_path: Path, case: str, needle: str) -> None:
    rows = [_row("story", "gemini", "s", "a", order=0), _row("story", "gemini", "s", "b", order=1)]
    if case == "chain-missing":
        rows.append(_route("story", "opus", "stat_judgment", chain_model="sonnet"))
    elif case == "duplicate":
        rows += [_route("story", "opus", "stat_judgment"), _route("story", "opus", "stat_judgment")]
    elif case == "revisions-disagree":
        rows[1]["route_revision"] = 3
    else:
        rows[1]["kind"] = "revision"
    with pytest.raises(SystemExit) as stop:
        ps.load_export(_write_export(tmp_path / "bad.json", rows))
    assert needle in str(stop.value.code)
    assert BODY_MARK not in str(stop.value.code)


async def test_the_overwrite_run_clears_the_route_table_cache(db_session: AsyncSession, tmp_path: Path) -> None:
    from api.chat.prompt_routing_cache import PROMPT_ROUTES_CACHE_KEY

    exported = ps.load_export(await _export_file(db_session, tmp_path))
    await redis_client.set(PROMPT_ROUTES_CACHE_KEY, "x")
    result = await ps.run_sync(_open(db_session), exported, check_only=False, redis_url=settings.redis_url)
    assert result["routesCacheDeleted"] == 1
    assert await redis_client.exists(PROMPT_ROUTES_CACHE_KEY) == 0


# --- 제자리 덮기와 판 표 — 같은 (체인, 섹션, 번호)는 같은 내용이어야 한다 ---------------------------------------------


async def _semver_rows(db: AsyncSession, set_id: uuid.UUID) -> tuple[int, int]:
    from api.db.models.prompt import PromptSectionSemver, PromptSetSemver

    sets = await db.scalar(sa.select(sa.func.count()).where(PromptSetSemver.prompt_set_id == set_id))
    sections = await db.scalar(sa.select(sa.func.count()).where(PromptSectionSemver.prompt_set_id == set_id))
    return int(sets or 0), int(sections or 0)


def _numbered(set_id: uuid.UUID, lane: str, model: str, major: int, *, base: uuid.UUID | None = None) -> list[Any]:
    """번호를 매긴 게시본의 판 행 둘(체인 판·섹션 판). 섹션 판은 시드가 이미 매긴 채널과 겹치지 않게 지어낸 채널 이름이다."""
    from api.db.models.prompt import PromptSectionSemver, PromptSetSemver

    return [
        PromptSetSemver(
            prompt_set_id=set_id, lane=lane, model=model, major=major, minor=0, patch=0,
            level=None if base is None else "major", base_set_id=base,
        ),
        PromptSectionSemver(prompt_set_id=set_id, channel="지어낸채널", major=major, minor=0, patch=0, level=None),
    ]  # fmt: skip


async def _older_numbered_set(db: AsyncSession, lane: str, model: str, major: int, *, base: uuid.UUID | None) -> Any:
    older = _published_set(lane, model)
    older.published_at = datetime(2000, 1, 1, tzinfo=UTC)
    db.add(older)
    await db.flush()
    db.add_all(_numbered(older.id, lane, model, major, base=base))
    await db.flush()
    return older


async def test_overwrite_strips_the_version_rows_of_the_set_it_rewrites_in_place(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    exported = ps.load_export(await _export_file(db_session, tmp_path))
    lane, model = sorted(exported.sets)[0]
    target = await _active_id(db_session, lane, model)
    older = await _older_numbered_set(db_session, lane, model, 901, base=None)
    # 시드가 이미 매겼을 수 있는 체인 판은 그대로 두고, 섹션 판 하나는 늘 더한다 — 덮는 세트에 판 행이 있는 상태를 보장한다.
    if (await _semver_rows(db_session, target))[0] == 0:
        db_session.add_all(_numbered(target, lane, model, 902, base=older.id))
    else:
        db_session.add(_numbered(target, lane, model, 902)[1])
    await db_session.flush()
    numbered = sum(await _semver_rows(db_session, target))
    assert numbered >= 2

    result = await ps.overwrite(db_session, exported)
    assert result[f"{lane}/{model}"]["semverRowsRemoved"] == numbered
    assert await _semver_rows(db_session, target) == (0, 0)
    assert await _semver_rows(db_session, older.id) == (1, 1)


async def test_overwrite_refuses_when_another_version_row_takes_the_set_as_its_base(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    exported = ps.load_export(await _export_file(db_session, tmp_path))
    lane, model = sorted(exported.sets)[-1]
    target = await _active_id(db_session, lane, model)
    db_session.add(_numbered(target, lane, model, 903)[1])
    await _older_numbered_set(db_session, lane, model, 904, base=target)
    before = await _chain_state(db_session)
    numbered = await _semver_rows(db_session, target)

    with pytest.raises(SystemExit) as stop:
        await ps.overwrite(db_session, exported)
    assert f"{lane}/{model}" in str(stop.value.code)
    assert await _chain_state(db_session) == before
    assert await _semver_rows(db_session, target) == numbered
    assert BODY_MARK not in str(stop.value.code)
