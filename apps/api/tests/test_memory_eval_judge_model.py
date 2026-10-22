"""판정자 모델 고르기 — 기본은 Haiku 5.5 그대로이고, Sonnet 5.5 를 고르면 요청 모델·사고 끄는 방식·대조군 파일 이름·원장
단가·고정 견적이 그 모델 것으로 바뀐다."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from memory_eval import judge as judge_mod
from memory_eval.judge import JUDGE_MODEL, HaikuJudge, JudgeVerdict, judge_prompt
from memory_eval.ledger import Ledger, cost_usd, price_for
from memory_eval.plants import load_plants
from memory_eval_fakes import write_fake_wording

SONNET = "claude-sonnet-5-5"
OPUS = "claude-opus-5-5"


def _fake_message(thinking_tokens: int | None = None) -> SimpleNamespace:
    details = None if thinking_tokens is None else SimpleNamespace(thinking_tokens=thinking_tokens)
    usage = SimpleNamespace(
        input_tokens=1_000,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
        output_tokens=100,
        output_tokens_details=details,
    )
    text = SimpleNamespace(type="text", text=JudgeVerdict(verdict="declined", reason="r").model_dump_json())
    return SimpleNamespace(stop_reason="end_turn", content=[text], usage=usage)


def _send(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, thinking_tokens: int | None = None, **kwargs: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    """가짜 Anthropic 클라이언트로 판정 한 번을 보내고 (보낸 요청, 원장 줄)을 돌려준다."""
    import anthropic

    sent: dict[str, Any] = {}

    class FakeMessages:
        async def create(self, **request: Any) -> SimpleNamespace:
            sent.update(request)
            return _fake_message(thinking_tokens)

    class FakeClient:
        def __init__(self, **_: Any) -> None:
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeClient)
    ledger = Ledger(tmp_path / "ledger.jsonl")
    result = asyncio.run(HaikuJudge("key", ledger, stage="judge", **kwargs).verdict("p"))
    assert result.verdict == "declined"
    return sent, ledger.rows()[0]


def test_the_default_judge_still_sends_haiku_with_thinking_disabled_and_low_effort(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sent, row = _send(monkeypatch, tmp_path)
    assert JUDGE_MODEL == "claude-haiku-5-5"
    assert sent["model"] == "claude-haiku-5-5"
    assert sent["thinking"] == {"type": "disabled"}
    assert sent["output_config"]["effort"] == "low"
    assert sent["max_tokens"] == 1_000
    assert row["model"] == "claude-haiku-5-5"


def test_a_sonnet_judge_turns_thinking_off_the_way_sonnet_accepts_with_the_same_effort_and_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    haiku_sent, _ = _send(monkeypatch, tmp_path / "h")
    sent, row = _send(monkeypatch, tmp_path / "s", model=SONNET)
    assert sent["model"] == SONNET
    # Sonnet 5.5 는 `disabled` 를 400 으로 거부하고, 사고를 끄는 값은 `between_tools` 다(깊이 high 이하에서만 받는다).
    assert sent["thinking"] == {"type": "between_tools"}
    assert sent["output_config"] == haiku_sent["output_config"]
    assert sent["messages"] == haiku_sent["messages"]
    assert sent["max_tokens"] == haiku_sent["max_tokens"]
    assert row["model"] == SONNET
    assert row["costUsd"] == pytest.approx((1_000 * 2.00 + 100 * 10.00) / 1_000_000)


def test_an_opus_judge_leaves_thinking_out_with_the_same_effort_and_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    haiku_sent, _ = _send(monkeypatch, tmp_path / "h")
    sent, row = _send(monkeypatch, tmp_path / "o", model=OPUS)
    assert sent["model"] == OPUS
    # Opus 5.5 는 `disabled` 를 어느 깊이에서든 400 으로 거부하고 `between_tools` 는 Sonnet 5.5 만 받는다 — 사고를 끌 길이
    # 없어 `thinking` 을 싣지 않고(모델이 알아서 사고한다) 깊이 low 로만 줄인다.
    assert "thinking" not in sent
    assert sent["output_config"] == haiku_sent["output_config"]
    assert sent["messages"] == haiku_sent["messages"]
    assert sent["max_tokens"] == haiku_sent["max_tokens"]
    assert row["model"] == OPUS
    assert row["costUsd"] == pytest.approx((1_000 * 4.00 + 100 * 20.00) / 1_000_000)


def test_an_opus_judge_row_keeps_its_thinking_tokens_apart_and_prices_them_as_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 사고를 끌 수 없는 판정자는 사고 토큰이 출력 토큰 안에 섞여 온다 — 원장 줄이 둘을 갈라 적어야 사고가 원가를 얼마나 먹는지 보인다.
    sent, row = _send(monkeypatch, tmp_path, model=OPUS, thinking_tokens=60)
    assert sent["output_config"]["effort"] == "low"
    assert (row["outputTokens"], row["thoughtsTokens"]) == (40, 60)
    assert row["costUsd"] == pytest.approx((1_000 * 4.00 + 100 * 20.00) / 1_000_000)


def test_the_opus_call_estimate_covers_a_call_that_spends_the_whole_output_cap_on_thinking() -> None:
    # 판정 한 번의 고정 견적이 사고 토큰을 따로 세지 않아도 되는 것은 사고가 출력 상한 안에 들기 때문이다 — 상한을 다 쓴 한
    # 번(입력은 앞 측정 원장의 Opus 판정 입력 최대 약 3.8천 토큰보다 조금 크게)보다 견적이 작으면 드라이런이 사고 원가를 낮게 본다.
    worst = cost_usd(
        OPUS,
        input_tokens=3_900,
        cached_tokens=0,
        cache_write_tokens=0,
        output_tokens=0,
        thoughts_tokens=judge_mod.JUDGE_MAX_TOKENS,
    )
    assert judge_mod.JUDGE_MODELS[OPUS][1] >= worst


def test_an_unknown_judge_model_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        HaikuJudge("key", Ledger(tmp_path / "ledger.jsonl"), stage="judge", model="claude-fable-5-1")


def test_controls_file_name_keeps_the_haiku_name_and_gives_sonnet_its_own() -> None:
    assert judge_mod.controls_filename(JUDGE_MODEL) == "controls.json"
    assert judge_mod.controls_filename(SONNET) == "controls-sonnet.json"
    assert judge_mod.controls_filename(OPUS) == "controls-opus.json"
    assert judge_mod.controls_filename(OPUS, tag="gate") == "controls-opus-gate.json"


def test_ledger_prices_sonnet_judge_calls_at_the_app_rates() -> None:
    price = price_for(SONNET)
    assert (price.input_usd_per_million, price.cached_input_usd_per_million, price.output_usd_per_million) == (
        2.00,
        0.10,
        10.00,
    )
    assert price.cache_write_usd_per_million == 2.50
    tokens = {"cached_tokens": 0, "cache_write_tokens": 0, "thoughts_tokens": 0}
    haiku = cost_usd(JUDGE_MODEL, input_tokens=1_000_000, output_tokens=1_000_000, **tokens)
    sonnet = cost_usd(SONNET, input_tokens=1_000_000, output_tokens=1_000_000, **tokens)
    assert haiku == pytest.approx(0.60)
    assert sonnet == pytest.approx(12.00)


def test_ledger_prices_opus_judge_calls_at_the_app_rates() -> None:
    price = price_for(OPUS)
    assert (price.input_usd_per_million, price.cached_input_usd_per_million, price.output_usd_per_million) == (
        4.00,
        0.20,
        20.00,
    )


def test_fixed_call_estimate_is_per_model_and_haiku_keeps_its_value() -> None:
    assert judge_mod.judge_estimate_usd(10) == pytest.approx(10 * 3 * 0.001)
    assert judge_mod.judge_estimate_usd(10, JUDGE_MODEL) == pytest.approx(10 * 3 * 0.001)
    assert judge_mod.judge_estimate_usd(10, SONNET) == pytest.approx(10 * 3 * 0.02)
    assert judge_mod.judge_estimate_usd(10, OPUS) == pytest.approx(10 * 3 * 0.04)


# ---------------------------------------------------------------- 명령


def _plants_file(tmp_path: Path) -> Path:
    plant = {
        "id": "spk01",
        "category": "화자",
        "subtype": "self",
        "speaker": {"who": "user", "assertedBy": "user"},
        "keywords": ["가상취미"],
        "expectedAnswer": "지어낸 정답 문장이다.",
        "question": "가상취미 얘기를 내가 했던가?",
        "split": "dev",
        "probeCheckpoints": {"opus": [100], "offline": [100]},
    }
    path = tmp_path / "plants.json"
    path.write_text(json.dumps({"seed": 1, "plants": [plant], "abstains": []}, ensure_ascii=False), encoding="utf-8")
    return path


def _run_controls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *extra: str) -> list[str]:
    """가짜 판정자로 대조군 명령을 끝까지 돌리고, 판정자가 받은 모델을 돌려준다."""
    from memory_eval_cli import main

    data = tmp_path / "data"
    wording = judge_mod.load_wording(write_fake_wording(data))
    plant_set = load_plants(_plants_file(tmp_path))
    expected_by_prompt = {
        judge_prompt(r["kind"], judge_mod.control_entry(r, plant_set), judge_mod.control_replies(r), wording): r[
            "expected"
        ]
        for r in judge_mod.controls(plant_set, wording)
    }
    models: list[str] = []

    class FakeJudge:
        def __init__(self, *_: Any, model: str = JUDGE_MODEL, **__: Any) -> None:
            models.append(model)

        async def verdict(self, prompt: str) -> JudgeVerdict:
            return JudgeVerdict(verdict=expected_by_prompt.get(prompt, "correct"), reason="r")

    monkeypatch.setattr(judge_mod, "HaikuJudge", FakeJudge)
    argv = ["--run", str(tmp_path), "--data-dir", str(data), "--cap-usd", "1", "--halt-usd", "1", "--bundle", "t"]
    argv += ["judge", "--plants", str(_plants_file(tmp_path)), "--controls", "--allow-paid"]
    # 경계 견본은 측정 데이터라 여기서는 심기 표 대조군만 돌린다.
    assert main([*argv, "--control-sources", "plants", *extra]) == 0
    return models


def test_the_controls_command_writes_the_haiku_file_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run_controls(tmp_path, monkeypatch) == [JUDGE_MODEL]
    assert sorted(p.name for p in (tmp_path / "judge").iterdir()) == ["controls.json"]


def test_a_sonnet_controls_run_leaves_the_haiku_file_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    haiku_file = tmp_path / "judge" / "controls.json"
    haiku_file.parent.mkdir(parents=True)
    haiku_file.write_text('{"rows": []}', encoding="utf-8")
    assert _run_controls(tmp_path, monkeypatch, "--judge-model", SONNET) == [SONNET]
    assert haiku_file.read_text(encoding="utf-8") == '{"rows": []}'
    assert json.loads((tmp_path / "judge" / "controls-sonnet.json").read_text(encoding="utf-8"))["rows"]


def test_the_dry_run_estimates_with_the_chosen_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    data = tmp_path / "data"
    write_fake_wording(data)
    base = ["--run", str(tmp_path), "--data-dir", str(data), "judge", "--plants", str(_plants_file(tmp_path))]
    base += ["--controls", "--dry-run", "--control-sources", "plants"]
    assert main(base) == 0
    haiku = json.loads(capsys.readouterr().out)
    assert main([*base, "--judge-model", SONNET]) == 0
    sonnet = json.loads(capsys.readouterr().out)
    assert sonnet["calls"] == haiku["calls"] > 0
    assert (haiku["model"], sonnet["model"]) == (JUDGE_MODEL, SONNET)
    assert sonnet["estimateUsd"] == pytest.approx(haiku["estimateUsd"] * 20)
