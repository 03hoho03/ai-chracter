"""투입(insert)은 요약 접기·장면·사실 추출을 하네스 프로세스 안에서 부르므로, 그 프로세스의 설정이 측정 서버 env 표와 다르면
투입한 요약·추출이 프로브 서버와 다른 모델·스위치로 만들어진다. 투입 시작 때 표와 한 줄이라도 다르면 키 이름만 대고 거부하고,
프롬프트 덤프 경로가 없으면 투입이 보낸 프롬프트가 남지 않으므로 거부한다."""

import json
import logging
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat import memory_fold
from api.core.config import Settings, settings
from factories import _open_room
from memory_eval import runtime
from memory_eval.arm_env import COMMON_ENV, insert_env_pairs
from memory_eval.fake_llm import FakeMemoryLLM
from memory_eval.insert import require_insert_settings

# 지어낸 임베딩 설정 — 앱 기본값과 다르게 둬야 표에서 왔는지 기본값인지 갈린다.
MODEL, DIMS = "voyage-지어낸-모델", 384


def _matching(**changed: object) -> Settings:
    """표의 줄을 env 처럼 글로 넘겨 만든 설정(실행 환경·`.env` 는 읽지 않는다). 표의 모델 배정이 요구하는 자격은 지어낸 값으로
    채운다."""
    values: dict[str, object] = {k.lower(): v for k, v in insert_env_pairs(embed_model=MODEL, embed_dims=DIMS)}
    values |= {"voyage_api_key": "지어낸-키", "anthropic_direct_api_key": "지어낸-키", **changed}
    return Settings.model_validate(values)


def test_settings_matching_the_table_with_a_dump_path_pass(tmp_path: Path) -> None:
    require_insert_settings(_matching(prompt_dump_path=str(tmp_path / "d.jsonl")), embed_model=MODEL, embed_dims=DIMS)


@pytest.mark.parametrize(
    ("changed", "key"),
    [
        pytest.param({"anthropic_haiku_model_id": "claude-haiku-지어낸-판"}, "ANTHROPIC_HAIKU_MODEL_ID", id="model-id"),
        pytest.param({"memory_facts_extract": False}, "MEMORY_FACTS_EXTRACT", id="switch"),
        pytest.param({"memory_embed_write": False}, "MEMORY_EMBED_WRITE", id="embed-write"),
        pytest.param({"memory_embed_model": "voyage-다른-지어낸-모델"}, "MEMORY_EMBED_MODEL", id="embed-model"),
        pytest.param(
            {"llm_call_site_backends": dict(COMMON_ENV)["LLM_CALL_SITE_BACKENDS"] + ",chat_scene_judgment:anthropic"},
            "LLM_CALL_SITE_BACKENDS",
            id="assignment",
        ),
    ],
)
def test_one_setting_differing_from_the_table_is_refused_by_key_name_only(
    tmp_path: Path, changed: dict[str, object], key: str
) -> None:
    current = _matching(prompt_dump_path=str(tmp_path / "d.jsonl"), **changed)
    with pytest.raises(SystemExit) as stop:
        require_insert_settings(current, embed_model=MODEL, embed_dims=DIMS)
    message = str(stop.value.code)
    assert key in message
    assert "지어낸" not in message  # 값은 내보내지 않는다


def test_a_missing_dump_path_is_refused() -> None:
    with pytest.raises(SystemExit, match="PROMPT_DUMP_PATH"):
        require_insert_settings(_matching(), embed_model=MODEL, embed_dims=DIMS)


async def test_matching_settings_let_a_fake_client_fold_leave_a_dump_line(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dump = tmp_path / "insert-dump.jsonl"
    matching = _matching(prompt_dump_path=str(dump))
    for key, _ in insert_env_pairs(embed_model=MODEL, embed_dims=DIMS):
        monkeypatch.setattr(settings, key.lower(), getattr(matching, key.lower()))
    monkeypatch.setattr(settings, "prompt_dump_path", str(dump))
    require_insert_settings(settings, embed_model=MODEL, embed_dims=DIMS)

    room = await _open_room(db_client, db_session, turns=memory_fold.FOLD_AT_TURNS, lane="character")
    ctx = await runtime.load_room(db_session, room.room_id)
    sets = await runtime.judgment_sets(db_session, ctx)
    await memory_fold.fold_memory(
        async_sessionmaker(bind=db_session.bind, expire_on_commit=False),
        FakeMemoryLLM(),
        room_id=room.room_id,
        user_id=room.user_id,
        prompt_set=sets.summary[0],
        sections=sets.summary[1],
        is_story_chat=False,
        names=ctx.names,
        writing_model="opus",
    )
    lines = [json.loads(line) for line in dump.read_text(encoding="utf-8").splitlines()]
    assert [(r["kind"], r["callSite"], r["model"]) for r in lines] == [
        ("background", "chat_memory_summary", matching.anthropic_haiku_model_id)
    ]


def _cli_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **changed: object) -> list[str]:
    """CLI 프로세스의 설정을 표(임베딩을 채우지 않는 투입)와 같게 맞추고 `changed` 만 다르게 둔 뒤 투입 인자를 돌려준다."""
    from memory_eval import cli_infra

    dump = tmp_path / "insert-dump.jsonl"
    matching = Settings.model_validate(
        {k.lower(): v for k, v in insert_env_pairs(embed_model=None, embed_dims=None)}
        | {"voyage_api_key": "지어낸-키", "anthropic_direct_api_key": "지어낸-키"}
    )
    for key, _ in insert_env_pairs(embed_model=None, embed_dims=None):
        monkeypatch.setattr(settings, key.lower(), getattr(matching, key.lower()))
    monkeypatch.setattr(settings, "prompt_dump_path", str(dump))
    for name, value in changed.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(cli_infra, "_db_url", lambda *, writes: "postgresql+asyncpg://지어낸/lm_eval_x")
    plants = tmp_path / "plants.json"
    plants.write_text(json.dumps({"plants": [], "abstains": []}), encoding="utf-8")
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(json.dumps({"turn": 1, "user": "안녕", "assistant": "응"}) + "\n", encoding="utf-8")
    return ["--run", str(tmp_path / "run"), "insert", "--plants", str(plants), "--transcript", str(transcript),
            "--room", "00000000-0000-0000-0000-000000000001", "--until", "1", "--fake-llm"]  # fmt: skip


def test_insert_cli_refuses_a_process_setting_that_differs_from_the_table_by_key_name_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval import insert
    from memory_eval_cli import main

    argv = _cli_world(tmp_path, monkeypatch, anthropic_haiku_model_id="claude-haiku-지어낸-판")
    started: list[object] = []

    async def must_not_run(**kwargs: object) -> dict[str, object]:
        started.append(kwargs)
        return {}

    monkeypatch.setattr(insert, "run_insert", must_not_run)
    assert main(argv) == 2
    err = capsys.readouterr().err
    assert "ANTHROPIC_HAIKU_MODEL_ID" in err and "지어낸" not in err
    assert started == []


def test_insert_cli_with_settings_matching_the_table_goes_on_and_its_dump_gets_the_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """표와 같으면 투입으로 넘어간다. 투입 자리에는 접기가 덤프를 남기는 함수를 그대로 부르는 대역을 둔다(실제 투입은 측정용 작업
    DB 가 있어야 돈다) — 이 프로세스의 덤프 경로로 줄이 남는다."""
    from api.chat.prompt_dump import dump_background_prompt
    from memory_eval import insert
    from memory_eval_cli import main

    argv = _cli_world(tmp_path, monkeypatch)
    seen: list[dict[str, object]] = []

    async def stand_in(**kwargs: object) -> dict[str, object]:
        seen.append(kwargs)
        room_id = kwargs["room_id"]
        assert isinstance(room_id, uuid.UUID)
        dump_background_prompt(
            room_id=room_id, call_site="chat_memory_summary", schema="지어낸", prompt="지어낸 프롬프트",
            log=logging.getLogger(__name__), turn=1,
        )  # fmt: skip
        return {"ok": True}

    monkeypatch.setattr(insert, "run_insert", stand_in)
    assert main(argv) == 0
    assert len(seen) == 1 and isinstance(seen[0]["llm"], FakeMemoryLLM)
    lines = [json.loads(line) for line in (tmp_path / "insert-dump.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(r["kind"], r["callSite"]) for r in lines] == [("background", "chat_memory_summary")]


def test_arm_env_insert_output_applied_as_env_passes_the_insert_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """실행 틀이 붙이는 `arm-env --insert` 출력이 곧 투입 대조가 받는 표다 — 출력을 env 로 읽은 설정이 대조를 지난다."""
    from memory_eval_cli import main

    dump = str(tmp_path / "d.jsonl")
    argv = ["--run", str(tmp_path), "arm-env", "--insert", "--embed-model", MODEL, "--embed-dims", str(DIMS)]
    assert main([*argv, "--prompt-dump", dump]) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line and not line.startswith("#")]
    for line in lines:
        key, _, value = line.partition("=")
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("VOYAGE_API_KEY", "지어낸-키")
    monkeypatch.setenv("ANTHROPIC_DIRECT_API_KEY", "지어낸-키")
    from_env = Settings(_env_file=None)  # type: ignore[call-arg]
    require_insert_settings(from_env, embed_model=MODEL, embed_dims=DIMS)
    assert from_env.prompt_dump_path == dump
