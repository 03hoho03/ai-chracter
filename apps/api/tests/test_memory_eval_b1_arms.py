"""묶음 1 측정의 여섯 갈래 env 표 — 갈래마다 다섯 스위치만 다르고, 두 레인 모두 여섯 갈래를 받으며, 템플릿 계열(요약 표기
꺼짐 A · 켜짐 B)이 갈래마다 정해진다. 2차 런의 A2·B2 표는 그대로 남는다. 스위치가 없는 코드에서는 하네스가 먼저 거부한다
(서버는 모르는 환경변수를 조용히 버려서, 그대로 돌리면 스위치 없이 돈다). 임베딩 쓰기·읽기의 모델·차원과 하이브리드 회상
설정도 앱 설정 칸 그대로 env 에 실린다 — 여섯 갈래 모두 이 코드의 설정으로 거부 없이 만들어져야 한다."""

import uuid
from pathlib import Path
from typing import Any

import pytest

from api.core.config import Settings
from memory_eval import arm_env
from memory_eval import embed_offline as eo
from memory_eval.arm_env import (
    BUNDLE1_ARMS,
    BUNDLE1_SWITCHES,
    bundle1_env_pairs,
    series_label,
    template_series,
)

EXPECTED = {
    # 갈래: (회상, 요약 표기, 지식 범위 필터, 사실 주입, 임베딩 읽기)
    "b1-A0": (False, False, False, False, False),
    # A0 + 요약 비밀 표기 — 회상을 보류해도 요약 표기를 켤 수 있는지 보는 갈래. 지식 범위 필터는 운영에서 요약 표기와 한 단계로
    # 켜므로 같이 켠다(사실 주입·회상이 꺼져 있어 필터는 생성 프롬프트를 바꾸지 않는다).
    "b1-A0M": (False, True, True, False, False),
    "b1-A1": (True, False, False, False, False),
    "b1-B1": (True, True, True, False, False),
    "b1-B2": (True, True, True, True, True),
    "b1-B1E": (True, True, True, False, True),
}


MODEL, DIMS = "voyage-4", 512
# 기본값과 다른 하이브리드 설정 — 기본값을 그대로 주면 env 에 실렸는지와 앱 기본값으로 돌았는지가 구분되지 않는다.
RECALL = eo.HybridParams(rrf_k=20, max_plain=2, max_cue=4, max_distance=0.6, vector_limit=8, df_max=12)
# 질의 임베딩 시간 상한도 기본값(1000)과 다르게 — 같으면 env 에 실렸는지 앱 기본값인지 구분되지 않는다.
TIMEOUT_MS = 900


def _pairs(arm: str, *, lane: str = "story", **kw: Any) -> list[tuple[str, str]]:
    return bundle1_env_pairs(
        arm, lane=lane, embed_model=MODEL, embed_dims=DIMS, recall=RECALL, embed_timeout_ms=TIMEOUT_MS, **kw
    )


def _switches(arm: str, lane: str = "story") -> tuple[bool, ...]:
    env = dict(_pairs(arm, lane=lane))
    return tuple(env[name] == "true" for name in BUNDLE1_SWITCHES)


def test_each_of_the_six_arms_sets_exactly_its_switches() -> None:
    assert set(BUNDLE1_ARMS) == set(EXPECTED)
    for arm, switches in EXPECTED.items():
        assert _switches(arm) == switches, arm


def test_every_switch_line_appears_once_so_a_later_line_cannot_silently_override_an_earlier_one() -> None:
    for arm in EXPECTED:
        keys = [k for k, _ in _pairs(arm)]
        assert len(keys) == len(set(keys)), arm


def test_the_arms_differ_from_each_other_only_in_the_five_switches() -> None:
    tables = {arm: dict(_pairs(arm)) for arm in EXPECTED}
    base = tables["b1-A0"]
    for arm, table in tables.items():
        assert {k for k in base.keys() | table.keys() if base.get(k) != table.get(k)} <= set(BUNDLE1_SWITCHES), arm


def test_common_lines_extract_and_write_embeddings_with_the_given_model_and_keep_direct_assignment() -> None:
    env = dict(_pairs("b1-A0", prompt_dump="/tmp/d.jsonl"))
    for name in ("MEMORY_EPISODES_EXTRACT", "MEMORY_FACTS_EXTRACT", "MEMORY_EMBED_WRITE"):
        assert env[name] == "true", name
    assert (env["MEMORY_EMBED_MODEL"], env["MEMORY_EMBED_DIMS"]) == (MODEL, str(DIMS))
    assert {k: v for k, v in env.items() if k.startswith("MEMORY_EMBED_RECALL_")} == {
        "MEMORY_EMBED_RECALL_RRF_K": "20",
        "MEMORY_EMBED_RECALL_MAX_PLAIN": "2",
        "MEMORY_EMBED_RECALL_MAX_CUE": "4",
        "MEMORY_EMBED_RECALL_MAX_DISTANCE": "0.6",
        "MEMORY_EMBED_RECALL_VECTOR_LIMIT": "8",
        "MEMORY_EMBED_RECALL_DF_MAX": "12",
        "MEMORY_EMBED_RECALL_TIMEOUT_MS": str(TIMEOUT_MS),
    }
    assert env["PROMPT_DUMP_PATH"] == "/tmp/d.jsonl"
    assigned = dict(item.split(":") for item in env["LLM_CALL_SITE_BACKENDS"].split(","))
    assert set(assigned.values()) == {"anthropic"}
    assert "preview_stat_judgment" in assigned
    assert "ANTHROPIC_DIRECT_API_KEY" not in env and "VOYAGE_API_KEY" not in env


def test_every_arm_pins_the_memory_model_scope_to_opus_on_both_lanes() -> None:
    """기억 스위치가 꺼진 갈래도 같은 값을 받는다 — 갈래 사이 차이가 다섯 스위치뿐이라는 조건이 이 줄에도 걸린다."""
    for arm in EXPECTED:
        assert dict(_pairs(arm))["MEMORY_MODEL_SCOPE"] == "opus", arm
    for arm in EXPECTED:
        assert dict(_pairs(arm, lane="character"))["MEMORY_MODEL_SCOPE"] == "opus", arm


def test_character_lane_takes_all_six_arms_with_their_switches_and_the_opus_scope() -> None:
    """캐릭터 대본도 스위치 하나짜리 비교(요약 표기 위 임베딩 읽기 등)를 잰다 — 여섯 갈래 모두 스토리 레인과 같은 스위치를 받는다."""
    for arm, switches in EXPECTED.items():
        assert _switches(arm, "character") == switches, arm
        env = dict(_pairs(arm, lane="character"))
        assert env["MEMORY_MODEL_SCOPE"] == "opus", arm
        assert env == dict(_pairs(arm, lane="story")), arm


def test_unknown_lane_or_arm_or_empty_embedding_model_is_refused() -> None:
    with pytest.raises(SystemExit):
        _pairs("b1-A0", lane="")
    with pytest.raises(SystemExit):
        _pairs("B2")
    with pytest.raises(SystemExit):
        bundle1_env_pairs("b1-A0", lane="story", embed_model="", embed_dims=DIMS, recall=RECALL, embed_timeout_ms=250)
    with pytest.raises(SystemExit):
        bundle1_env_pairs("b1-A0", lane="story", embed_model=MODEL, embed_dims=0, recall=RECALL, embed_timeout_ms=250)
    with pytest.raises(SystemExit, match="시간 상한"):
        bundle1_env_pairs("b1-B2", lane="story", embed_model=MODEL, embed_dims=DIMS, recall=RECALL, embed_timeout_ms=0)


def test_template_series_follows_summary_marking_and_b_series_restores_its_own_template_label() -> None:
    assert {arm: template_series(arm) for arm in EXPECTED} == {
        "b1-A0": "A",
        "b1-A0M": "B",
        "b1-A1": "A",
        "b1-B1": "B",
        "b1-B2": "B",
        "b1-B1E": "B",
    }
    for arm, switches in EXPECTED.items():
        assert (template_series(arm) == "B") == switches[1], arm
    assert series_label("b1fc", "b1-A1") == "b1fc"
    assert series_label("b1fc", "b1-B1") != "b1fc"
    assert series_label("b1fc", "b1-B1") == series_label("b1fc", "b1-B2") == series_label("b1fc", "b1-B1E")


def test_second_run_table_is_left_as_it_was() -> None:
    a, b = dict(arm_env.env_pairs("A2")), dict(arm_env.env_pairs("B2"))
    assert {k for k in a.keys() | b.keys() if a.get(k) != b.get(k)} == {"MEMORY_FACTS_INJECT"}


def test_harness_arm_settings_match_the_table_and_this_code_has_every_switch() -> None:
    from memory_eval.runtime import ARMS, arm_env as runtime_arm_env, require_arm_supported
    from memory_eval.trajectory import RECALL_ARMS

    for arm in EXPECTED:
        table = dict(_pairs(arm))
        assert all(table[k] == v for k, v in runtime_arm_env(arm).items()), arm
        assert set(runtime_arm_env(arm)) == set(BUNDLE1_SWITCHES), arm
        assert (arm in RECALL_ARMS) == EXPECTED[arm][0], arm
    assert ARMS["A2"] == {"memory_episodes_recall": True, "memory_facts_inject": False}
    # 이 코드에는 다섯 스위치의 설정 칸이 모두 있다 — 여섯 갈래 모두 서버를 띄우기 전 검사를 지난다.
    for arm in EXPECTED:
        require_arm_supported(arm)


def test_each_arm_env_builds_app_settings_without_refusal_and_lands_in_the_matching_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """서버가 그 env 로 설정을 만들 때 거부(호출 위치 배정 검증·임베딩 키 검사 등)가 없고, 줄마다 같은 이름의 칸에 들어간다.
    키 값은 env 표에 없고 서버가 `.env` 에서 읽으므로 여기서는 자리값을 준다."""
    for arm in EXPECTED:
        env = dict(_pairs(arm))
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setenv("VOYAGE_API_KEY", "test-not-used")
        monkeypatch.setenv("ANTHROPIC_DIRECT_API_KEY", "test-not-used")
        built = Settings(_env_file=None)  # type: ignore[call-arg]
        assert tuple(getattr(built, name.lower()) for name in BUNDLE1_SWITCHES) == EXPECTED[arm], arm
        assert (built.memory_embed_write, built.memory_embed_model, built.memory_embed_dims) == (True, MODEL, DIMS)
        assert {name: getattr(built, name) for name in eo.CONFIG_NAMES} == RECALL.config(), arm
        assert built.memory_embed_recall_timeout_ms == TIMEOUT_MS, arm


def test_a_none_df_max_leaves_the_line_out_since_env_cannot_spell_none(monkeypatch: pytest.MonkeyPatch) -> None:
    env = dict(
        bundle1_env_pairs(
            "b1-B2", lane="story", embed_model=MODEL, embed_dims=DIMS, recall=eo.DEFAULT_PARAMS, embed_timeout_ms=250
        )
    )
    assert "MEMORY_EMBED_RECALL_DF_MAX" not in env
    assert env["MEMORY_EMBED_RECALL_RRF_K"] == "20"
    # 앱 설정은 '없음'을 env 글로 받지 못한다 — 빈 값도 정수 해석에서 거부된다. 그래서 줄을 빼는 수밖에 없다.
    monkeypatch.setenv("MEMORY_EMBED_RECALL_DF_MAX", "")
    with pytest.raises(ValueError, match="memory_embed_recall_df_max"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_an_embedding_line_the_arm_leaves_out_is_refused_when_env_file_or_environment_carries_it() -> None:
    """줄을 뺀 키(df 상한 없음)는 서버가 `.env` 나 실행 환경의 값을 읽는다 — 그 키가 거기 있으면 측정 서버를 띄우지 않는다.
    갈래가 직접 정한 키는 실행 명령의 값이 이기므로 `.env` 에 있어도 괜찮다."""
    overrides = dict(
        bundle1_env_pairs(
            "b1-B2", lane="story", embed_model=MODEL, embed_dims=DIMS, recall=eo.DEFAULT_PARAMS, embed_timeout_ms=250
        )
    )
    env_file = "# 주석\nVOYAGE_API_KEY=x\nMEMORY_EMBED_RECALL_RRF_K=5\n"
    assert arm_env.leaked_embed_keys(overrides, env_file=env_file, environ={}) == []
    leaked = "export MEMORY_EMBED_RECALL_DF_MAX = 7\n"
    assert arm_env.leaked_embed_keys(overrides, env_file=env_file + leaked, environ={}) == [
        "MEMORY_EMBED_RECALL_DF_MAX"
    ]
    assert arm_env.leaked_embed_keys(overrides, env_file="", environ={"MEMORY_EMBED_RECALL_DF_MAX": "7"}) == [
        "MEMORY_EMBED_RECALL_DF_MAX"
    ]
    # df 상한을 정한 갈래는 그 줄을 싣으므로 새지 않는다.
    assert arm_env.leaked_embed_keys(dict(_pairs("b1-B2")), env_file=leaked, environ={}) == []


def test_trajectory_replay_refuses_b_series_arms_until_it_can_pick_the_b_template(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    def replay(arms: str) -> int:
        return main(
            ["--run", str(tmp_path), "trajectory-replay", "--room", str(uuid.uuid4()),
             "--insert-log", str(tmp_path / "no-insert-log.jsonl"), "--arms", arms, "--out-dir", str(tmp_path / "out")]
        )  # fmt: skip

    assert replay("baseline,b1-B1") == 2  # 템플릿 이름(--label) 없이는 B 계열 템플릿을 고를 수 없다
    assert "b1-B1" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()
    # A 계열 갈래는 이 거부에 걸리지 않고 넣기 기록을 읽으러 간다.
    with pytest.raises(FileNotFoundError):
        replay("b1-A1")
