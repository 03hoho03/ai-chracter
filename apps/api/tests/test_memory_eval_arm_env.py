"""2차 런 두 갈래의 측정 서버 env 표 — 두 갈래는 사실 주입 한 줄만 다르고, 공통 줄은 추출·회상·직결 배정을 다 켜며, 하네스
갈래 설정·궤적 회상 갈래와 어긋나지 않는다."""

from pathlib import Path

import pytest

from memory_eval.arm_env import ANTHROPIC_CALL_SITES, env_pairs, env_text


def test_the_two_arms_differ_only_in_fact_injection() -> None:
    a, b = dict(env_pairs("A2")), dict(env_pairs("B2"))
    assert {k for k in a.keys() | b.keys() if a.get(k) != b.get(k)} == {"MEMORY_FACTS_INJECT"}
    assert (a["MEMORY_FACTS_INJECT"], b["MEMORY_FACTS_INJECT"]) == ("false", "true")


def test_common_lines_turn_on_extraction_recall_and_haiku_models_with_direct_assignment() -> None:
    env = dict(env_pairs("A2"))
    for name in ("MEMORY_EPISODES_EXTRACT", "MEMORY_EPISODES_RECALL", "MEMORY_FACTS_EXTRACT"):
        assert env[name] == "true", name
    for name in ("STAT_JUDGMENT_MODEL", "ENDING_JUDGMENT_MODEL", "IMAGE_JUDGMENT_MODEL", "MEMORY_SUMMARY_MODEL",
                 "MEMORY_EPISODE_MODEL", "MEMORY_FACT_MODEL"):  # fmt: skip
        assert env[name] == "haiku", name
    assigned = dict(item.split(":") for item in env["LLM_CALL_SITE_BACKENDS"].split(","))
    assert set(assigned.values()) == {"anthropic"}
    for site in ("preview_stat_judgment", "preview_ending_judgment", "preview_media_book_image", "chat_memory_fact"):
        assert site in assigned, site
    assert list(assigned) == list(ANTHROPIC_CALL_SITES)


def test_both_arms_pin_the_memory_model_scope_to_opus() -> None:
    """측정 생성 모델이 Opus 라 코드 기본값과 같은 값이지만, 기본값이 바뀐 서버로 돌려도 측정 조건이 같도록 표에 적어 둔다."""
    for arm in ("A2", "B2"):
        assert dict(env_pairs(arm))["MEMORY_MODEL_SCOPE"] == "opus", arm


def test_the_table_carries_no_key_values() -> None:
    env = dict(env_pairs("B2"))
    assert env["BEDROCK_ACCESS_KEY_ID"] == env["BEDROCK_SECRET_ACCESS_KEY"] == ""
    assert env["GEMINI_API_KEY"] == "dummy-not-used"
    assert "ANTHROPIC_DIRECT_API_KEY" not in env


def test_prompt_dump_line_is_added_only_when_given() -> None:
    assert "PROMPT_DUMP_PATH" not in dict(env_pairs("A2"))
    assert dict(env_pairs("A2", prompt_dump="/tmp/d.jsonl"))["PROMPT_DUMP_PATH"] == "/tmp/d.jsonl"
    text = env_text("B2")
    assert text.startswith("# 2차 런 갈래 B2") and "MEMORY_FACTS_INJECT=true\n" in text
    with pytest.raises(SystemExit):
        env_pairs("B")


def test_harness_arm_settings_agree_with_the_env_table_and_both_arms_assemble_with_recall() -> None:
    from memory_eval.runtime import arm_env
    from memory_eval.trajectory import RECALL_ARMS

    for arm in ("A2", "B2"):
        table = dict(env_pairs(arm))
        assert all(table[k] == v for k, v in arm_env(arm).items()), arm
    assert {"A2", "B2"} <= RECALL_ARMS


def test_arm_env_command_prints_the_file_body(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    from memory_eval_cli import main

    assert main(["--run", str(tmp_path), "arm-env", "--arm", "A2"]) == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln and not ln.startswith("#")]
    assert dict(ln.split("=", 1) for ln in lines) == dict(env_pairs("A2"))
