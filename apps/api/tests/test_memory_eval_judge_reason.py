"""판정 이유 재현성 도구 — 스탯 판정 줄을 운영 판정기 조건 그대로 두 판(응답 스키마에 이유 칸이 없는 판·있는 판)으로 반복
재판정해 판마다 자기 반복 일치율과 판 사이 일치율, 발동 분포를 낸다. 판정기는 전부 가짜 클라이언트다(유료 호출 0). 덤프는
합성이다 — 실제 판정 문안·대화를 싣지 않는다.

지키는 것: 두 판의 차이는 응답 스키마의 이유 칸 하나뿐이고 프롬프트는 같은 바이트다, 같은 입력은 같은 비교표를 낸다, 표본 고르기는
씨앗마다 같고 방에 고르게 퍼진다, 견적과 상한은 호출 전에 멈춘다."""

import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import anthropic
import pytest

from api.chat.prompt_builder import StatRuleJudgmentResult
from memory_eval import judge_agreement as ja
from memory_eval import judge_reason as jr
from memory_eval.ledger import Ledger

STAT_PROMPT = (
    "규칙 판정 지시\n\n"
    "윤결 신뢰 / 범위 [0, 100] / 윤결이 사용자를 믿는 정도\n"
    "- a1: 사용자가 바게트를 다 구웠다\n"
    "- a2: 사용자가 가게 문을 늦게 열었다\n\n"
    "나: 윤결아 바게트 남았어?\n진행자: 윤결이 빈손을 펴 보였다."
)
HAIKU = "claude-haiku-5-5"


def _dump(path: Path, records: Sequence[Mapping[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    return path


def _stat(turn: int, *, room: str = "room-1", tag: str = "") -> dict[str, Any]:
    return {
        "roomId": room,
        "turn": turn,
        "kind": "judgment",
        "callSite": "chat_stat_judgment",
        "model": HAIKU,
        "schema": "StatRuleJudgmentResult",
        "prompt": f"{STAT_PROMPT}\n턴 표시 {room}{tag}:{turn}",
    }


def _ending(turn: int) -> dict[str, Any]:
    return {
        "roomId": "room-1",
        "turn": turn,
        "kind": "judgment",
        "callSite": "chat_ending_judgment",
        "model": HAIKU,
        "schema": "EndingJudgmentResult",
        "prompt": "엔딩 판정 지시",
    }


def _turn_of(prompt: str) -> int:
    return int(prompt.rsplit(":", 1)[1])


def _variant_answer(plain: Mapping[int, list[list[str]]], reason: Mapping[int, list[list[str]]]) -> ja.FakeAnswer:
    """판(응답 스키마 이름으로 가른다)과 턴마다 반복 순서대로 낼 발동 규칙 목록. 없는 턴은 늘 빈 결과. 이유 판은 이유 글도 낸다."""
    seen: Counter[tuple[str, int]] = Counter()

    def answer(prompt: str, schema: str, call_site: str) -> dict[str, Any]:
        turn = _turn_of(prompt)
        is_reason = schema == jr.ReasonedStatRuleJudgmentResult.__name__
        table = reason if is_reason else plain
        index = seen[(schema, turn)]
        seen[(schema, turn)] += 1
        sequence = table.get(turn)
        fired = sequence[index % len(sequence)] if sequence else []
        out: dict[str, Any] = {"fired_rule_ids": fired}
        if is_reason:
            out["reason"] = "근거" * (turn + 1)
        return out

    return answer


def _models(answer: ja.FakeAnswer) -> list[ja.JudgeModel]:
    client = ja.FakeJudgeLLM(HAIKU, answer)
    return jr.variant_models(client, HAIKU)


async def _run(tmp_path: Path, lines: list[ja.JudgmentLine], answer: ja.FakeAnswer, reps: int) -> list[dict[str, Any]]:
    calls = tmp_path / "out" / "calls.jsonl"
    await ja.run_calls(
        lines,
        _models(answer),
        reps,
        ledger=Ledger(tmp_path / "out" / "ledger.jsonl"),
        calls_path=calls,
        stage="test",
        rates={},
        output_tokens=400,
    )
    return ja.read_calls(calls)


def _baseline_lines(tmp_path: Path, count: int) -> list[ja.JudgmentLine]:
    return jr.load_stat_lines([_dump(tmp_path / "dump-story.jsonl", [_stat(t) for t in range(1, count + 1)])])


# ---------------------------------------------------------------- 두 판의 스키마


def test_the_reason_variant_sends_the_stat_schema_plus_one_required_reason_field_and_nothing_else() -> None:
    # 깨지는 시나리오: 이유 판 스키마의 제목·설명이 운영 스키마와 달라져 두 판의 차이가 이유 칸 하나가 아니게 된다.
    plain = anthropic.transform_schema(StatRuleJudgmentResult)
    reasoned = anthropic.transform_schema(jr.ReasonedStatRuleJudgmentResult)
    expected = json.loads(json.dumps(plain))
    expected["properties"]["reason"] = {"type": "string", "title": "Reason"}
    expected["required"] = ["fired_rule_ids", "reason"]
    assert reasoned == expected


async def test_both_variants_send_the_same_prompt_bytes_and_only_the_schema_differs(tmp_path: Path) -> None:
    lines = _baseline_lines(tmp_path, 1)
    sent: list[tuple[str, str]] = []

    def answer(prompt: str, schema: str, call_site: str) -> dict[str, Any]:
        sent.append((prompt, schema))
        return {"fired_rule_ids": [], "reason": ""} if schema != "StatRuleJudgmentResult" else {"fired_rule_ids": []}

    await _run(tmp_path, lines, answer, reps=1)
    assert [schema for _, schema in sent] == ["StatRuleJudgmentResult", jr.ReasonedStatRuleJudgmentResult.__name__]
    assert {prompt for prompt, _ in sent} == {lines[0].prompt}


# ---------------------------------------------------------------- 줄 읽기·표본


def test_dev_dumps_sharing_a_file_name_get_distinct_stable_ids_and_only_stat_lines_are_kept(tmp_path: Path) -> None:
    # 깨지는 시나리오: 덤프 파일 이름이 모두 같아(probe 마다 prompt-dump.jsonl) 줄 id 가 겹쳐 결과가 서로를 덮는다.
    first = _dump(tmp_path / "probes" / "p1" / "attempt1" / "prompt-dump.jsonl", [_ending(1), _stat(1)])
    second = _dump(tmp_path / "probes" / "p2" / "attempt1" / "prompt-dump.jsonl", [_stat(2), _stat(1)])
    lines = jr.load_stat_lines([first, second], prefix="dev")
    assert [line.line_id for line in lines] == [
        "dev/p1/attempt1/prompt-dump.jsonl:2",
        "dev/p2/attempt1/prompt-dump.jsonl:1",
    ]
    # 같은 (방, 턴, 프롬프트) 줄은 파일이 달라도 하나다.
    assert lines[0].duplicates == 1
    assert jr.load_stat_lines([second, first], prefix="dev")[0].line_id == "dev/p2/attempt1/prompt-dump.jsonl:1"


def test_baseline_ids_keep_the_existing_harness_form_so_old_control_specs_still_name_their_lines(
    tmp_path: Path,
) -> None:
    lines = _baseline_lines(tmp_path, 2)
    assert [line.line_id for line in lines] == ["dump-story.jsonl:1", "dump-story.jsonl:2"]
    controls = ja.control_lines(lines, [{"id": "c1", "base": {"lineId": "dump-story.jsonl:2"}, "replace": [["a1", "x1"]]}])
    assert controls[0].base_id == "dump-story.jsonl:2"


def test_balanced_sample_spreads_across_rooms_and_is_the_same_for_the_same_seed(tmp_path: Path) -> None:
    records = (
        [_stat(t, room="room-a") for t in range(1, 11)]
        + [_stat(t, room="room-b") for t in range(1, 11)]
        + [_stat(t, room="room-c") for t in range(1, 3)]
    )
    lines = jr.load_stat_lines([_dump(tmp_path / "d" / "prompt-dump.jsonl", records)], prefix="dev")
    picked = jr.balanced_sample(lines, 9, seed=7)
    # 고르게 — 줄이 모자란 방(room-c 2줄)을 다 쓰고 남는 몫을 나머지가 나눈다.
    assert Counter(line.room_id for line in picked) == {"room-a": 4, "room-b": 3, "room-c": 2}
    assert [line.line_id for line in jr.balanced_sample(list(reversed(lines)), 9, seed=7)] == [
        line.line_id for line in picked
    ]
    others = {line.line_id for line in jr.balanced_sample(lines, 9, seed=8)}
    assert others != {line.line_id for line in picked}
    assert [line.line_id for line in picked] == sorted(line.line_id for line in picked)
    with pytest.raises(SystemExit, match="23"):
        jr.balanced_sample(lines, 23, seed=7)


# ---------------------------------------------------------------- 집계


async def test_variants_are_called_interleaved_per_line_and_the_reason_text_is_kept_beside_the_result(
    tmp_path: Path,
) -> None:
    lines = _baseline_lines(tmp_path, 2)
    calls = await _run(tmp_path, lines, _variant_answer({1: [["a1"]]}, {1: [["a1", "zz"]]}), reps=2)
    assert [(row["lineId"], row["model"]) for row in calls] == [
        ("dump-story.jsonl:1", jr.PLAIN),
        ("dump-story.jsonl:1", jr.PLAIN),
        ("dump-story.jsonl:1", jr.REASON),
        ("dump-story.jsonl:1", jr.REASON),
        ("dump-story.jsonl:2", jr.PLAIN),
        ("dump-story.jsonl:2", jr.PLAIN),
        ("dump-story.jsonl:2", jr.REASON),
        ("dump-story.jsonl:2", jr.REASON),
    ]
    # 일치를 따지는 결과는 두 판 모두 같은 정규화(프롬프트에 없던 id 는 지움)이고, 이유 글은 따로 남는다.
    assert calls[0]["result"] == calls[2]["result"] == ["a1"]
    assert "extra" not in calls[0]
    assert calls[2]["extra"] == {"reason": "근거근거"}


async def test_self_agreement_cross_agreement_and_fire_distribution_are_reported_per_variant(tmp_path: Path) -> None:
    lines = _baseline_lines(tmp_path, 2)
    # 줄 1: 이유 없는 판은 늘 a1, 이유 판은 a1 과 빈 결과를 번갈아. 줄 2: 두 판 모두 늘 빈 결과.
    answer = _variant_answer({1: [["a1"]]}, {1: [["a1"], []]})
    calls = await _run(tmp_path, lines, answer, reps=4)
    group = jr.summarize(lines, {line.line_id: "baseline" for line in lines}, calls)["groups"]["baseline"]
    plain, reason, between = group["variants"][jr.PLAIN], group["variants"][jr.REASON], group["between"]
    assert group["lines"] == 2 and group["firedLines"] == 1
    assert plain["selfAgreement"] == 1.0
    # 이유 판 줄 1: 6쌍 중 같은 쌍 2 → 1/3, 줄 2: 1 → 평균 2/3.
    assert reason["selfAgreement"] == pytest.approx((1 / 3 + 1) / 2)
    assert reason["firedSelfAgreement"] == pytest.approx(1 / 3)
    assert plain["fireRate"] == pytest.approx(4 / 8) and reason["fireRate"] == pytest.approx(2 / 8)
    assert plain["meanFiredIds"] == pytest.approx(4 / 8)
    assert reason["meanReasonChars"] == pytest.approx((4 * 4 + 4 * 6) / 8)
    assert reason["emptyReasons"] == 0
    # 판 사이: 줄 1 은 4×4 쌍 중 같은 쌍 8 → 0.5, 줄 2 는 1.
    assert between["crossAgreement"] == pytest.approx(0.75)
    assert between["lines"] == 2
    # 줄마다 (두 자기 반복 평균 − 판 사이): 줄 1 = (1 + 1/3)/2 − 0.5 = 1/6, 줄 2 = 0.
    assert between["selfMinusCross"] == pytest.approx(1 / 12)
    assert between["selfMinusCrossSe"] == pytest.approx(math.sqrt(((1 / 6 - 1 / 12) ** 2 * 2) / 1) / math.sqrt(2))
    # 줄 1 의 최빈 결과는 이유 판에서 동률(a1 2·빈 2)이라 먼저 나온 a1 — 두 판의 최빈이 두 줄 모두 같다.
    assert between["modalAgreement"] == 1.0


async def test_a_variant_that_changes_what_fires_shows_up_as_cross_below_both_self_agreements(tmp_path: Path) -> None:
    # 깨지는 시나리오: 판 사이 일치율을 같은 판 안의 쌍으로 계산해 이유 칸이 판정을 바꿔도 차이가 0 으로 나온다.
    lines = _baseline_lines(tmp_path, 3)
    calls = await _run(tmp_path, lines, _variant_answer({1: [["a1"]], 2: [["a2"]]}, {1: [["a2"]], 2: [["a1"]]}), 3)
    between = jr.summarize(lines, {line.line_id: "baseline" for line in lines}, calls)["groups"]["baseline"]["between"]
    assert between["crossAgreement"] == pytest.approx(1 / 3)
    assert between["selfMinusCross"] == pytest.approx(2 / 3)
    assert between["modalAgreement"] == pytest.approx(1 / 3)


async def test_groups_are_reported_apart_and_together(tmp_path: Path) -> None:
    baseline = _baseline_lines(tmp_path, 2)
    dev = jr.load_stat_lines(
        [_dump(tmp_path / "s3" / "p" / "prompt-dump.jsonl", [_stat(3, room="room-d")])], prefix="dev"
    )
    lines = baseline + dev
    groups = {line.line_id: "baseline" for line in baseline} | {line.line_id: "dev" for line in dev}
    calls = await _run(tmp_path, lines, _variant_answer({3: [["a1"]]}, {3: [["a1"]]}), reps=2)
    out = jr.summarize(lines, groups, calls)["groups"]
    assert {name: out[name]["lines"] for name in out} == {"all": 3, "baseline": 2, "dev": 1}
    assert out["dev"]["firedLines"] == 1 and out["baseline"]["firedLines"] == 0


async def test_structured_failures_are_counted_per_variant(tmp_path: Path) -> None:
    from api.llm.client import LLMClientError

    lines = _baseline_lines(tmp_path, 1)

    def answer(prompt: str, schema: str, call_site: str) -> dict[str, Any] | Exception:
        if schema == jr.ReasonedStatRuleJudgmentResult.__name__:
            return LLMClientError("스키마로 읽히지 않음")
        return {"fired_rule_ids": []}

    calls = await _run(tmp_path, lines, answer, reps=2)
    variants = jr.summarize(lines, {lines[0].line_id: "baseline"}, calls)["groups"]["baseline"]["variants"]
    assert variants[jr.REASON]["structuredFailures"] == 2
    assert variants[jr.PLAIN]["structuredFailures"] == 0


async def test_the_same_inputs_give_the_same_comparison_table(tmp_path: Path) -> None:
    # 깨지는 시나리오: 집계가 결과 파일 순서나 실행마다 다른 값(시각·난수)에 기대 같은 결과가 다른 표가 된다.
    lines = _baseline_lines(tmp_path, 3)
    answer_a = _variant_answer({1: [["a1"], []], 2: [["a2"]]}, {1: [["a1"]], 3: [["a1"], ["a2"]]})
    answer_b = _variant_answer({1: [["a1"], []], 2: [["a2"]]}, {1: [["a1"]], 3: [["a1"], ["a2"]]})
    groups = {line.line_id: "baseline" for line in lines}
    first = jr.summarize(lines, groups, await _run(tmp_path / "a", lines, answer_a, reps=4))
    second_calls = await _run(tmp_path / "b", lines, answer_b, reps=4)
    second = jr.summarize(lines, groups, list(reversed(second_calls)))
    assert first == second
    assert jr.render_tables({"summary": first}) == jr.render_tables({"summary": second})


# ---------------------------------------------------------------- 견적·CLI


def _cli_dumps(tmp_path: Path) -> tuple[Path, list[Path]]:
    baseline = _dump(tmp_path / "base" / "dump-story.jsonl", [_stat(1, tag="b"), _stat(2, tag="b"), _ending(2)])
    dev = [
        _dump(tmp_path / "s3" / f"p{i}" / "prompt-dump.jsonl", [_stat(i, room=f"room-{i % 2}", tag="d")])
        for i in range(1, 5)
    ]
    return baseline, dev


def test_dry_run_estimates_both_variants_from_prompt_size_without_calling(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from memory_eval_cli import main

    monkeypatch.setattr(ja, "real_models", _no_real_models)
    baseline, dev = _cli_dumps(tmp_path)
    run = tmp_path / "run"
    argv = ["--run", str(run), "judge-reason", "--baseline-dumps", str(baseline), "--dev-dumps", *map(str, dev)]
    argv += ["--dev-sample", "2", "--seed", "3", "--reps", "5", "--tokens-per-char", "1.5"]
    argv += ["--output-tokens", "30", "--reason-output-tokens", "300", "--dry-run"]
    assert main(argv) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["lines"] == {"baseline": 2, "dev": 2}
    assert report["calls"] == 4 * 5 * 2
    chars = len(_stat(1, tag="b")["prompt"])
    assert all(len(_stat(i, room=f"room-{i % 2}", tag="d")["prompt"]) == chars for i in range(1, 5))
    per_input = math.ceil(chars * 1.5) * 0.10
    plain = 4 * 5 * (per_input + 30 * 0.50) / 1_000_000
    reason = 4 * 5 * (per_input + 300 * 0.50) / 1_000_000
    assert report["perVariant"][jr.PLAIN]["usd"] == pytest.approx(plain)
    assert report["perVariant"][jr.REASON]["usd"] == pytest.approx(reason)
    assert report["totalUsd"] == pytest.approx(plain + reason)
    assert report["ledgerSpentUsd"] == 0
    assert not run.exists()


def _no_real_models(*_args: Any, **_kwargs: Any) -> list[ja.JudgeModel]:
    raise AssertionError("이 실행은 실제 판정기를 만들면 안 된다")


def test_sampling_needs_an_explicit_seed_and_a_dev_dump_needs_a_sample_size(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    baseline, dev = _cli_dumps(tmp_path)
    base = ["--run", str(tmp_path / "run"), "judge-reason", "--baseline-dumps", str(baseline), "--dry-run"]
    assert main([*base, "--dev-dumps", *map(str, dev)]) == 2
    assert "--dev-sample" in capsys.readouterr().err
    assert main([*base, "--dev-dumps", *map(str, dev), "--dev-sample", "2"]) == 2
    assert "--seed" in capsys.readouterr().err
    assert main([*base, "--baseline-sample", "1"]) == 2
    assert "--seed" in capsys.readouterr().err


def test_paid_run_without_ledger_limits_is_refused_before_any_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from memory_eval_cli import main

    monkeypatch.setattr(ja, "real_models", _no_real_models)
    baseline, _ = _cli_dumps(tmp_path)
    argv = ["--run", str(tmp_path / "run"), "--bundle", "b", "judge-reason", "--baseline-dumps", str(baseline)]
    assert main([*argv, "--allow-paid"]) == 2
    err = capsys.readouterr().err
    assert "--cap-usd" in err and "--halt-usd" in err


def test_paid_run_whose_whole_estimate_crosses_the_cap_is_refused_before_building_a_judge(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # 깨지는 시나리오: 상한을 호출마다만 보아 상한에 닿을 때까지 돈을 쓰고 반쯤 된 표본만 남긴다.
    from memory_eval_cli import main

    monkeypatch.setattr(ja, "real_models", _no_real_models)
    baseline, _ = _cli_dumps(tmp_path)
    run = tmp_path / "run"
    argv = ["--run", str(run), "--cap-usd", "0.0001", "--halt-usd", "0.0001", "--bundle", "b"]
    argv += ["judge-reason", "--baseline-dumps", str(baseline), "--allow-paid"]
    assert main(argv) == 20
    assert "0.0001" in capsys.readouterr().out
    assert not (run / "s5").exists()


def test_fake_run_writes_its_own_files_and_a_comparison_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from memory_eval_cli import main

    monkeypatch.setattr(ja, "real_models", _no_real_models)
    baseline, dev = _cli_dumps(tmp_path)
    run = tmp_path / "run"
    argv = ["--run", str(run), "judge-reason", "--baseline-dumps", str(baseline), "--dev-dumps", *map(str, dev)]
    argv += ["--dev-sample", "4", "--seed", "1", "--reps", "2", "--fake-llm"]
    assert main(argv) == 0
    out = run / "s5" / "judge-reason"
    assert sorted(path.name for path in out.iterdir()) == [
        "fake-calls.jsonl",
        "fake-ledger.jsonl",
        "fake-ledger.jsonl.lock",
        "fake-lines.json",
        "fake-summary.json",
        "fake-tables.md",  # cite-ok: 도구가 쓰는 결과 파일 이름
    ]
    assert not (run / "ledger.jsonl").exists()
    summary = json.loads((out / "fake-summary.json").read_text(encoding="utf-8"))
    assert summary["meta"]["sampleSeed"] == 1
    assert summary["meta"]["lines"] == {"baseline": 2, "dev": 4}
    assert summary["summary"]["groups"]["all"]["between"]["crossAgreement"] == 1.0
    tables = (out / "fake-tables.md").read_text(encoding="utf-8")  # cite-ok: 도구가 쓰는 결과 파일 이름
    assert "| all |" in tables and "| baseline |" in tables and "| dev |" in tables
    capsys.readouterr()
