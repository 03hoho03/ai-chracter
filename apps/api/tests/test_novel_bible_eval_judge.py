"""정본 기억 측정 하네스의 κ 용 판정 — 사람이 라벨한 주장을 판정 모델에도 같은 범주로 매기게 하고, 사람과 모델의 일치(Cohen's
κ)를 이진·3범주로 세어 합격선(0.6)에 대 본다.

모델은 가짜 판정기다. 주장과 판정은 합성이다 — 실제 라벨 원문은 저장소에 두지 않는다."""

import json
import re
from pathlib import Path
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.llm.client import LLMCallContext
from api.novel_bible.adapters.table import ADAPTERS, AdapterId
from api.novel_bible.core.contracts import AdapterCallError, AdapterCapabilities, PromptSource
from api.novel_bible.core.types import RenderedPrompt
from api.novel_bible.ids import OperationKey
from api.novelize.call_records import sent_model
from memory_eval.ledger import EXIT_BUDGET, Ledger
from novel_bible_eval import judge, labels
from novel_bible_eval.__main__ import _parser, _run
from novel_bible_eval.__main__ import judge as judge_command
from novel_bible_eval.report import label_report
from novel_bible_eval.run import Meter

T = TypeVar("T", bound=BaseModel)
ALPHA, BETA = "adapter-alpha", "adapter-beta"
LITE = "gemini-3.5-flash-lite"
_LINE = re.compile(r"^주장: (.*)$", re.MULTILINE)


def _claim(number: int, *, slot: str = "facts", quotes: int = 1) -> labels.Claim:
    return labels.Claim(
        id=f"claim-{number}", chapter=1 + number % 2, slot=slot, core={ALPHA: True, BETA: False},
        line=f"합성 주장 {number}", quotes=[f"합성 인용 {number}-{index}" for index in range(quotes)], adapters={ALPHA: [0], BETA: []},
    )


def _label(verdict: str, *marks: str | None) -> labels.Label:
    return labels.Label.model_validate({"verdict": verdict, "quotes": list(marks)})


class _FakeJudge:
    """주장 한 줄로 답을 고른다. `answers` 의 값이 목록이면 부를 때마다 앞에서 하나씩 쓴다(예외면 올린다)."""

    id = "fake-judge"
    capabilities = AdapterCapabilities(structured=True, with_instruction=True, max_input_chars=100_000)

    def __init__(
        self, answers: dict[str, Any], *, thoughts: int = 0, output_tokens: int = 200, model: str = LITE
    ) -> None:
        self._answers = answers
        self.model = model
        self._thoughts = thoughts
        self._output_tokens = output_tokens
        self.prompts: list[RenderedPrompt] = []

    async def prompt_source(self, session: AsyncSession) -> PromptSource:
        raise AssertionError("판정 문안은 하네스 코드에 있다 — 문안 세트를 읽지 않는다")

    async def structured(
        self, prompt: RenderedPrompt, schema: type[T], *, records: list[dict[str, Any]], stage: OperationKey
    ) -> T:
        self.prompts.append(prompt)
        records.append({
            "callSite": "novel_bible_judge", "model": self.model, "promptTokens": 0,
            "outputTokens": self._output_tokens, "thoughtsTokens": self._thoughts, "stage": stage,
        })
        found = _LINE.search(prompt.prompt)
        assert found is not None
        answer = self._answers[found.group(1)]
        if isinstance(answer, list):
            answer = answer.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return schema.model_validate(answer)


def _answer(verdict: str, *marks: str) -> dict[str, Any]:
    return {"verdict": verdict, "quotes": list(marks), "reason": "합성 판정 이유"}


def _metered(fake: _FakeJudge, meter: Meter) -> Any:
    return meter.wrap(lambda _operation: fake)("conflicts.judge")


async def test_the_judge_rates_every_claim_blind_to_the_adapters_through_the_ledger(tmp_path: Path) -> None:
    claims = [_claim(1), _claim(2, slot="knowledge"), _claim(3, quotes=2)]
    fake = _FakeJudge({
        "합성 주장 1": _answer("correct", "supported"),
        "합성 주장 2": _answer("direction", "supported"),
        "합성 주장 3": _answer("wrong", "unsupported", "supported"),
    })
    ledger = Ledger(tmp_path / "ledger.jsonl", cap_usd=10, halt_usd=5, bundle="ci")
    meter = Meter(ledger=ledger, estimate_usd=0.01)
    _, key = labels.write_sheet(claims, tmp_path, halted={ALPHA: None, BETA: None})

    assert await judge_command(_metered(fake, meter), key, tmp_path, model="gemini", model_id=LITE) == 0

    run = judge.read_run(tmp_path / "judge-gemini.json")
    assert (run.model, run.model_id, run.halted, run.failures) == ("gemini", LITE, None, {})
    assert {claim_id: (label.verdict, label.quotes) for claim_id, label in run.answers.items()} == {
        "claim-1": ("correct", ["supported"]),
        "claim-2": ("direction", ["supported"]),
        "claim-3": ("wrong", ["unsupported", "supported"]),
    }
    # 판정 호출도 원장에 든다 — 주장마다 하나.
    assert [row["stage"] for row in ledger.rows()] == ["conflicts.judge"] * 3
    # 판정기는 시트가 보이는 것(슬롯·주장 한 줄·인용)만 받는다. 어느 어댑터의 주장인지는 모른다.
    third = fake.prompts[2]
    assert "합성 인용 3-0" in third.prompt and "합성 인용 3-1" in third.prompt
    assert all(ALPHA not in prompt.prompt and BETA not in prompt.prompt for prompt in fake.prompts)
    assert third.system_instruction == judge.INSTRUCTION


async def test_a_judge_halted_by_the_ledger_keeps_its_answers_and_a_rerun_asks_only_the_rest(tmp_path: Path) -> None:
    claims = [_claim(1), _claim(2), _claim(3)]
    answers = {claim.line: _answer("correct", "supported") for claim in claims}
    _, key = labels.write_sheet(claims, tmp_path, halted={ALPHA: None})
    # 호출 하나가 단가표로 $1 — 출력 40만 토큰 × $2.50/100만. 둘째 호출 뒤 셋째 호출은 견적을 더하면 멈춤 선 $2.5 를 넘는다.
    first = _FakeJudge(answers, output_tokens=400_000)
    meter = Meter(ledger=Ledger(tmp_path / "ledger.jsonl", cap_usd=3, halt_usd=2.5, bundle="first"), estimate_usd=1)
    assert await judge_command(_metered(first, meter), key, tmp_path, model="gemini", model_id=LITE) == EXIT_BUDGET
    halted = judge.read_run(tmp_path / "judge-gemini.json")
    assert sorted(halted.answers) == ["claim-1", "claim-2"]
    assert halted.halted is not None and "멈춤 선" in halted.halted

    second = _FakeJudge(answers, output_tokens=400_000)
    meter = Meter(ledger=Ledger(tmp_path / "ledger.jsonl", cap_usd=3, halt_usd=2.5, bundle="second"), estimate_usd=1)
    assert await judge_command(_metered(second, meter), key, tmp_path, model="gemini", model_id=LITE) == 0
    finished = judge.read_run(tmp_path / "judge-gemini.json")
    assert (sorted(finished.answers), finished.halted) == (["claim-1", "claim-2", "claim-3"], None)
    assert len(second.prompts) == 1


async def test_a_judge_call_that_spent_thinking_tokens_stops_the_judge(tmp_path: Path) -> None:
    # 판정은 사고를 끈 조건에서 잰다. 앱의 구조화 호출은 Gemini 에 사고 설정을 싣지 않아 모델 기본값을 따르므로, 사고 토큰이 나온
    # 호출이 있으면 그 모델로는 이어 부르지 않는다.
    claims = [_claim(1), _claim(2)]
    fake = _FakeJudge({claim.line: _answer("correct", "supported") for claim in claims}, thoughts=12)
    _, key = labels.write_sheet(claims, tmp_path, halted={ALPHA: None})
    meter = Meter()
    with pytest.raises(judge.ThinkingOnError):
        await judge_command(_metered(fake, meter), key, tmp_path, model="gemini", model_id=LITE)
    assert len(fake.prompts) == 1
    run = judge.read_run(tmp_path / "judge-gemini.json")
    assert run.halted is not None and "사고" in run.halted
    assert run.answers == {}


async def test_a_failed_or_misshapen_answer_is_retried_and_after_three_tries_left_unjudged(tmp_path: Path) -> None:
    claims = [_claim(1), _claim(2, quotes=2)]
    fake = _FakeJudge({
        "합성 주장 1": [AdapterCallError("schema_invalid", retryable=True), _answer("correct", "supported")],
        # 인용이 둘인 주장에 받침 표시를 하나만 낸다 — 사람 라벨과 같은 범주가 아니므로 세 번 다 틀리면 판정하지 못한 주장이다.
        "합성 주장 2": [_answer("correct", "supported")] * 3,
    })
    _, key = labels.write_sheet(claims, tmp_path, halted={ALPHA: None})
    meter = Meter()
    assert await judge_command(_metered(fake, meter), key, tmp_path, model="gemini", model_id=LITE) == 0
    run = judge.read_run(tmp_path / "judge-gemini.json")
    assert sorted(run.answers) == ["claim-1"]
    assert run.failures == {"claim-2": "quote_count"}
    assert len(fake.prompts) == 5
    assert ("conflicts.judge", "schema_invalid") in meter.attempts


# 사람 라벨과 판정을 손으로 접은 값. 이진은 맞음 + 인용 전부 받침 / 나머지, 3범주는 맞음(+받침)·틀림(방향 포함)·근거 없음.
#   주장  사람                    판정                    이진(사람/판정)  3범주(사람/판정)
#   1    맞음 [받침]               맞음 [받침]               C / C          맞음 / 맞음
#   2    맞음 [받침]               맞음 [안 받침]            C / O          맞음 / 근거 없음
#   3    맞음 [안 받침]            맞음 [안 받침]            O / O          근거 없음 / 근거 없음
#   4    틀림 [받침]               틀림 [안 받침]            O / O          틀림 / 틀림
#   5    방향 틀림 [받침]          틀림 [받침]               O / O          틀림 / 틀림
#   6    판단 불가 [-]             맞음 [받침]               O / C          근거 없음 / 맞음
#   7    맞음 [받침, 받침]         맞음 [받침, 받침]         C / C          맞음 / 맞음
#   8    틀림 [안 받침]            판단 불가 [안 받침]       O / O          틀림 / 근거 없음
#   9    맞음 [받침, 안 받침]      맞음 [받침, 받침]         O / C          근거 없음 / 맞음
# 이진: 일치 6/9, 우연 (3·4 + 6·5)/81 = 14/27 → κ = (2/3 − 14/27)/(1 − 14/27) = 4/13.
# 3범주: 일치 5/9, 우연 (3·4 + 3·3 + 3·2)/81 = 1/3 → κ = (5/9 − 1/3)/(2/3) = 1/3.
_Rows = list[tuple[str, tuple[str | None, ...]]]
_HUMAN: _Rows = [
    ("correct", ("supported",)), ("correct", ("supported",)), ("correct", ("unsupported",)),
    ("wrong", ("supported",)), ("direction", ("supported",)), ("unknown", (None,)),
    ("correct", ("supported", "supported")), ("wrong", ("unsupported",)), ("correct", ("supported", "unsupported")),
]
_JUDGE: _Rows = [
    ("correct", ("supported",)), ("correct", ("unsupported",)), ("correct", ("unsupported",)),
    ("wrong", ("unsupported",)), ("wrong", ("supported",)), ("correct", ("supported",)),
    ("correct", ("supported", "supported")), ("unknown", ("unsupported",)), ("correct", ("supported", "supported")),
]


def _labeled(rows: _Rows) -> list[labels.LabeledClaim]:
    return [
        labels.LabeledClaim(
            _claim(number, slot="knowledge" if verdict == "direction" else "facts", quotes=len(marks)),
            _label(verdict, *marks),
        )
        for number, (verdict, marks) in enumerate(rows, start=1)
    ]


def _answers(rows: _Rows) -> dict[str, labels.Label]:
    return {f"claim-{number}": _label(verdict, *marks) for number, (verdict, marks) in enumerate(rows, start=1)}


def test_kappa_folds_human_and_judge_labels_the_same_way_into_two_and_three_categories() -> None:
    summary = judge.kappa(_labeled(_HUMAN), _answers(_JUDGE))
    assert (summary.n, summary.unjudged) == (9, 0)
    assert summary.binary == pytest.approx(4 / 13)
    assert summary.three == pytest.approx(1 / 3)
    assert summary.binary is not None and summary.binary_bootstrap is not None
    low, high = summary.binary_bootstrap
    assert low <= summary.binary <= high
    assert low < high  # 주장을 다시 뽑으면 κ 가 흔들린다


def _kappa_report(
    human: _Rows, answers: dict[str, labels.Label], *, halted: str | None = None
) -> dict[str, Any]:
    labeled = _labeled(human)
    run = judge.JudgeRun(
        model="gemini", model_id=LITE, key_digest=judge.key_digest([row.claim for row in labeled]), halted=halted,
        answers=answers,
    )
    report = label_report(labeled, {ALPHA: None}, judged={"gemini": run})
    kappa: dict[str, Any] = report["kappa"]["gemini"]
    return kappa


def test_the_label_report_judges_kappa_against_its_floor() -> None:
    below = _kappa_report(_HUMAN, _answers(_JUDGE))
    assert (below["value"], below["pass"]) == (pytest.approx(4 / 13), False)
    assert below["three_category"]["value"] == pytest.approx(1 / 3)
    assert len(below["bootstrap"]) == 2
    agreed = _kappa_report(_HUMAN, _answers(_HUMAN))
    assert (agreed["value"], agreed["pass"]) == (1.0, True)


def test_kappa_from_a_judge_that_halted_or_left_claims_unjudged_is_undetermined() -> None:
    halted = _kappa_report(_HUMAN, _answers(_HUMAN), halted="합성 멈춤")
    assert (halted["pass"], halted["undetermined"]) == (None, "멈춘 판정")
    partial = _answers(_HUMAN)
    partial.pop("claim-9")
    unjudged = _kappa_report(_HUMAN, partial)
    assert (unjudged["value"], unjudged["n"], unjudged["unjudged"]) == (1.0, 8, 1)
    assert (unjudged["pass"], unjudged["undetermined"]) == (None, "판정 못 한 주장 1건")


async def test_score_reads_the_judge_files_into_the_kappa_section(tmp_path: Path) -> None:
    labeled = _labeled(_HUMAN)
    _, key = labels.write_sheet([row.claim for row in labeled], tmp_path, halted={ALPHA: None})
    result = tmp_path / "labels-result.json"
    result.write_text(json.dumps({"labels": {row.claim.id: row.label.model_dump() for row in labeled}}), encoding="utf-8")
    digest = judge.key_digest([row.claim for row in labeled])
    judge.write_run(
        judge.JudgeRun(model="gemini", model_id=LITE, key_digest=digest, answers=_answers(_JUDGE)),
        tmp_path / "judge-gemini.json",
    )
    await _run(_parser().parse_args([
        "score", "--key", str(key), "--labels", str(result), "--out", str(tmp_path),
        "--judged", str(tmp_path / "judge-gemini.json"),
    ]))
    report = json.loads((tmp_path / "label-report.json").read_text(encoding="utf-8"))
    assert report["kappa"]["gemini"]["value"] == pytest.approx(4 / 13)
    assert report["kappa"]["gemini"]["pass"] is False
    # 어느 모델의 κ 인지 보고서에서 보인다 — 판정 이름(gemini)이 아니라 실제로 부른 모델 id.
    assert report["kappa"]["gemini"]["model_id"] == LITE


async def test_score_refuses_two_judge_files_under_the_same_judge_name(tmp_path: Path) -> None:
    # 두 Gemini id 의 κ 를 견주려고 두 폴더의 판정 파일을 함께 주면, 보고서의 κ 칸은 판정 이름마다 하나라 한 파일이 조용히 빠진다.
    labeled = _labeled(_HUMAN)
    _, key = labels.write_sheet([row.claim for row in labeled], tmp_path, halted={ALPHA: None})
    result = tmp_path / "labels-result.json"
    result.write_text(json.dumps({"labels": {row.claim.id: row.label.model_dump() for row in labeled}}), encoding="utf-8")
    digest = judge.key_digest([row.claim for row in labeled])
    judged = []
    for folder, model_id in (("first", LITE), ("second", "gemini-3.1-flash-lite")):
        (tmp_path / folder).mkdir()
        judged.append(str(tmp_path / folder / "judge-gemini.json"))
        judge.write_run(
            judge.JudgeRun(model="gemini", model_id=model_id, key_digest=digest, answers=_answers(_JUDGE)),
            Path(judged[-1]),
        )
    with pytest.raises(SystemExit, match="판정 이름"):
        await _run(_parser().parse_args([
            "score", "--key", str(key), "--labels", str(result), "--out", str(tmp_path), "--judged", *judged,
        ]))
    assert not (tmp_path / "label-report.json").exists()


class _NoCallAdapter:
    """판정 명령이 거절해야 할 때 실제 어댑터 대신 놓는다 — 거절이 빠져도 유료 호출이 나가지 않게."""

    def __init__(self, adapter_id: str) -> None:
        self.id = adapter_id

    async def structured(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("거절했어야 할 판정 호출이 나갔다")


@pytest.fixture
def _judge_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """판정 어댑터는 그 판정 경로가 읽는 모델 설정을 덮는다 — 테스트가 끝나면 되돌린다."""
    for name in ("gemini_model_name", "anthropic_haiku_model_id", "bedrock_haiku_model_id"):
        monkeypatch.setattr(settings, name, getattr(settings, name))
    monkeypatch.setattr(judge, "ModelAdapter", _NoCallAdapter)


def _sent(adapter_id: AdapterId) -> str:
    usage = LLMCallContext(
        call_site="novel_bible_judge", user_id=None, room_id=None, call_model=ADAPTERS[adapter_id].call_model
    )
    return sent_model(usage)[1]


@pytest.mark.usefixtures("_judge_settings")
@pytest.mark.parametrize(
    ("model", "model_id", "setting", "configured"),
    [
        ("gemini", LITE, "gemini_model_name", "gemini-3.1-flash-lite"),
        ("haiku", "claude-haiku-5-5", "anthropic_haiku_model_id", "claude-haiku-4-5"),
    ],
)
def test_the_judge_model_id_overrides_the_model_the_app_judge_path_sends(
    monkeypatch: pytest.MonkeyPatch, model: str, model_id: str, setting: str, configured: str
) -> None:
    # 프로세스 env 의 모델 설정이 다른 id 여도 판정은 인자로 준 id 를 부른다.
    monkeypatch.setattr(settings, setting, configured)
    assert _sent(judge.JUDGE_MODELS[model]) == configured
    adapter = judge.judge_adapter(model, model_id)
    assert adapter.id == judge.JUDGE_MODELS[model]
    assert _sent(judge.JUDGE_MODELS[model]) == model_id


@pytest.mark.usefixtures("_judge_settings")
@pytest.mark.parametrize(
    ("model", "model_id"),
    [
        # 앱의 Gemini 판정 경로는 사고 설정을 싣지 않는다 — 기본으로 사고하는 모델은 사고를 끈 조건이 아니다.
        pytest.param("gemini", "gemini-2.5-flash", id="gemini-thinking-by-default"),
        # Claude 구조화 호출이 사고를 끄는 것은 Haiku 5 계열뿐이다.
        pytest.param("haiku", "claude-sonnet-5-5", id="claude-without-thinking-off"),
    ],
)
def test_a_judge_model_that_cannot_judge_with_thinking_off_is_refused_before_any_call(model: str, model_id: str) -> None:
    before = _sent(judge.JUDGE_MODELS[model])
    with pytest.raises(SystemExit, match="사고"):
        judge.judge_adapter(model, model_id)
    assert _sent(judge.JUDGE_MODELS[model]) == before


@pytest.mark.usefixtures("_judge_settings")
def test_a_judge_path_assigned_to_bedrock_takes_only_bedrock_ids_that_bedrock_calls_with_thinking_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # env 배정이 판정 호출을 Bedrock 으로 보내면 허용 여부도 Bedrock 구현의 규칙으로 가린다. 직결 꼴 id 는 Bedrock 이 모르는
    # 모델이라 주장마다 실패하고, 사고를 끌 수 없는 5.x 글쓰기 모델은 Bedrock 구조화 호출이 사고를 싣지 않는다.
    monkeypatch.setattr(settings, "llm_call_site_backends", {"novel_bible_judge": "bedrock"})
    before = _sent("haiku")
    for model_id in ("claude-haiku-5-5", "global.anthropic.claude-sonnet-5-5"):
        with pytest.raises(SystemExit, match="사고"):
            judge.judge_adapter("haiku", model_id)
        assert _sent("haiku") == before
    bedrock_haiku = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    judge.judge_adapter("haiku", bedrock_haiku)
    assert settings.bedrock_haiku_model_id == bedrock_haiku
    assert _sent("haiku") == bedrock_haiku


@pytest.mark.usefixtures("_judge_settings")
def test_a_judge_model_id_missing_from_the_price_table_is_refused_before_any_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 원장은 단가표로 원가를 센다 — 단가를 모르는 id 는 첫 호출 하나가 나간 뒤에야 원장 멈춤으로 선다. 사고 끔 조건(Haiku 5
    # 계열 직결 id)은 맞는 id 로 단가표만 가른다.
    monkeypatch.setattr(settings, "llm_call_site_backends", {})
    before = _sent("haiku")
    with pytest.raises(SystemExit, match="단가"):
        judge.judge_adapter("haiku", "claude-haiku-5-5-20261101")
    assert _sent("haiku") == before


@pytest.mark.usefixtures("_judge_settings")
async def test_the_judge_command_refuses_a_thinking_model_before_touching_the_ledger(tmp_path: Path) -> None:
    _, key = labels.write_sheet([_claim(1)], tmp_path, halted={ALPHA: None})
    ledger = tmp_path / "ledger.jsonl"
    with pytest.raises(SystemExit, match="사고"):
        await _run(_parser().parse_args([
            "judge", "--model", "gemini", "--judge-model", "gemini-2.5-flash", "--key", str(key),
            "--run-dir", str(tmp_path), "--ledger", str(ledger), "--bundle", "ci", "--cap-usd", "1",
            "--halt-usd", "0.5", "--estimate-usd", "0.01",
        ]))
    assert not ledger.exists()
    assert not (tmp_path / "judge-gemini.json").exists()


async def test_a_judge_file_from_another_model_id_is_not_resumed(tmp_path: Path) -> None:
    # 멈춘 판정을 다른 모델로 이어 돌리면 한 파일에 두 모델의 판정이 섞여, κ 가 어느 모델의 것인지 알 수 없다.
    claims = [_claim(1), _claim(2)]
    answers = {claim.line: _answer("correct", "supported") for claim in claims}
    _, key = labels.write_sheet(claims, tmp_path, halted={ALPHA: None})
    first = _FakeJudge({"합성 주장 1": answers["합성 주장 1"], "합성 주장 2": [AdapterCallError("blocked", retryable=False)]})
    assert await judge_command(_metered(first, Meter()), key, tmp_path, model="gemini", model_id=LITE) == 0
    before = (tmp_path / "judge-gemini.json").read_text(encoding="utf-8")

    other = _FakeJudge(answers, model="gemini-3.1-flash-lite")
    with pytest.raises(SystemExit, match=LITE):
        await judge_command(_metered(other, Meter()), key, tmp_path, model="gemini", model_id="gemini-3.1-flash-lite")
    assert other.prompts == []
    assert (tmp_path / "judge-gemini.json").read_text(encoding="utf-8") == before


async def test_a_judge_call_answered_by_another_model_than_asked_stops_the_judge(tmp_path: Path) -> None:
    # 요청한 id 와 다른 모델이 답했다면(경로가 바뀌었다) 그 답은 이 판정 파일의 모델 판정이 아니다.
    claims = [_claim(1), _claim(2)]
    fake = _FakeJudge({claim.line: _answer("correct", "supported") for claim in claims}, model="gemini-2.5-flash")
    _, key = labels.write_sheet(claims, tmp_path, halted={ALPHA: None})
    with pytest.raises(judge.WrongModelError):
        await judge_command(_metered(fake, Meter()), key, tmp_path, model="gemini", model_id=LITE)
    assert len(fake.prompts) == 1
    run = judge.read_run(tmp_path / "judge-gemini.json")
    assert run.answers == {}
    assert run.halted is not None and "gemini-2.5-flash" in run.halted


async def test_a_judge_file_made_for_another_key_is_neither_resumed_nor_scored(tmp_path: Path) -> None:
    # 판정 뒤 한 어댑터를 다시 추출해 열쇠를 다시 쓰면 주장 id 는 같아도 인용이 달라질 수 있다 — 옛 판정이 새 인용에 붙으면
    # 이진 접기가 조용히 틀린다.
    claims = [_claim(1), _claim(2)]
    answers = {claim.line: _answer("correct", "supported") for claim in claims}
    _, key = labels.write_sheet(claims, tmp_path, halted={ALPHA: None})
    first = _FakeJudge({"합성 주장 1": answers["합성 주장 1"], "합성 주장 2": [AdapterCallError("blocked", retryable=False)]})
    assert await judge_command(_metered(first, Meter()), key, tmp_path, model="gemini", model_id=LITE) == 0

    changed = [claims[0].model_copy(update={"quotes": ["합성 인용 1-다른 것"]}), claims[1]]
    _, key = labels.write_sheet(changed, tmp_path, halted={ALPHA: None})
    second = _FakeJudge(answers)
    with pytest.raises(SystemExit, match="열쇠"):
        await judge_command(_metered(second, Meter()), key, tmp_path, model="gemini", model_id=LITE)
    assert second.prompts == []

    result = tmp_path / "labels-result.json"
    marks = {claim.id: {"verdict": "correct", "quotes": ["supported"]} for claim in changed}
    result.write_text(json.dumps({"labels": marks}), encoding="utf-8")
    with pytest.raises(SystemExit, match="열쇠"):
        await _run(_parser().parse_args([
            "score", "--key", str(key), "--labels", str(result), "--out", str(tmp_path),
            "--judged", str(tmp_path / "judge-gemini.json"),
        ]))
    assert not (tmp_path / "label-report.json").exists()
