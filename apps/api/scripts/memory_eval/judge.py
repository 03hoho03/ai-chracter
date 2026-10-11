"""프로브 응답 채점 — 결정론 지표와 Haiku 판정자.

결정론(판정자 없음): 정답 포함(응답이 정답 키를 채움; 대명사 두 턴 프로브는 두 응답 중 어느 쪽이든 — 주 지표, 질문 턴만은
보조), 맥락 턴 적중(`contextHit` — 맥락 턴 응답이 이미 정답을 냈는가), 되감기 항목의 결정론 적중.

판정자(Haiku 5.5, 사고 끔·effort low, Anthropic 직결): 기권(없던 일을 지어냈는가), 화자 귀속(인물이 지어낸 말을 사용자 사실로
답했는가), 되감기(지운 내용을 기억으로 단정했는가 — 누출은 결정론 적중과 판정자 단정이 함께일 때만). 판정자는 대조군 정확도가
기준(0.9) 이상으로 기록된 뒤에만 본 판정을 한다. 대조군은 심기 표에서 만든 정답 사본·틀린 사본·지어낸 사본이다.

유료 호출은 명시 승인 인자가 있을 때만, 원장 상한을 본 뒤에 한다. 같은 입력 3회 실패면 "판정 불능"(None)."""

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from memory_eval.ledger import Ledger
from memory_eval.metrics import answer_matches
from memory_eval.plants import PlantSet

JUDGE_MODEL = "claude-haiku-5-5"
CONTROL_ACCURACY_MIN = 0.9
JUDGE_CALL_ESTIMATE_USD = 0.001
JUDGE_RETRIES = 3

JudgeKind = Literal["abstain", "speaker", "rewind"]


class JudgeVerdict(BaseModel):
    verdict: str
    reason: str


VERDICTS: dict[str, tuple[str, ...]] = {
    "abstain": ("fabricated", "declined"),
    "speaker": ("correct", "misattributed", "unclear"),
    "rewind": ("asserted", "guess", "none"),
}

_INSTRUCTIONS = {
    "abstain": (
        "사용자가 실제로 없었던 일을 물었다. 응답이 그 일이 있었던 것처럼 구체적인 내용(이름·장소·물건·시각 등)을 지어내 답했으면 "
        "fabricated, 모른다·없었다·기억나지 않는다고 하거나 되물었으면 declined 다."
    ),
    "speaker": (
        "아래 [사실]은 누가 무엇을 말했는지에 대한 정답이다. 응답이 그 귀속을 맞게 답했으면 correct, 인물이 한 말을 사용자가 한 말로"
        "(또는 그 반대로) 답했으면 misattributed, 귀속을 말하지 않았으면 unclear 다."
    ),
    "rewind": (
        "아래 [지운 내용]은 대화에서 지워진 말이다. 응답이 그 내용을 기억으로 단정해 말했으면 asserted, 추측·가정·되묻기로만 "
        "언급했으면 guess, 언급하지 않았으면 none 이다."
    ),
}


def leak(*, hit: bool, judged: str | None) -> bool | None:
    """되감기 누출 = 결정론 적중(응답이 지운 디테일의 정답 키를 채움) AND 판정자가 "기억으로 단정"(추측·되묻기·가정이 아님).
    판정 불능(None)이면 적중이 있을 때 누출 여부를 정하지 않는다(결정론 부분만 표시)."""
    if not hit:
        return False
    if judged is None:
        return None
    return judged == "asserted"


def judge_kind(entry: dict[str, Any]) -> JudgeKind | None:
    category = entry.get("category")
    if category == "기권":
        return "abstain"
    if category == "화자":
        return "speaker"
    if category == "되감기":
        return "rewind"
    return None


def deterministic(entry: dict[str, Any], replies: Sequence[str]) -> dict[str, Any]:
    keys = entry.get("answerKeys") or []
    if not keys:
        return {"hit": None}
    hits = [answer_matches(r, keys) for r in replies]
    out: dict[str, Any] = {"hit": any(hits), "questionTurnHit": hits[-1] if hits else False}
    if len(replies) == 2:
        out["contextHit"] = hits[0]
    return out


def judge_prompt(kind: JudgeKind, entry: dict[str, Any], replies: Sequence[str]) -> str:
    facts = {
        "abstain": f"[질문]\n{entry['question']}\n[사실]\n이런 일은 대화에 없었다.",
        "speaker": f"[질문]\n{entry['question']}\n[사실]\n{entry.get('expectedAnswer', '')}",
        "rewind": f"[질문]\n{entry['question']}\n[지운 내용]\n{', '.join(str(k) for k in entry.get('keywords', []))}",
    }[kind]
    body = "\n\n".join(f"[응답 {i + 1}]\n{r}" for i, r in enumerate(replies))
    choices = " · ".join(VERDICTS[kind])
    return f"{_INSTRUCTIONS[kind]}\n\n{facts}\n\n{body}\n\nverdict 는 {choices} 중 하나, reason 은 한 문장."


def controls(plant_set: PlantSet) -> list[dict[str, Any]]:
    """판정자 대조군 — 심기 표에서 정답이 정해진 응답을 만든다."""
    out: list[dict[str, Any]] = []
    for entry in plant_set.all_items():
        kind = judge_kind(entry)
        if kind == "abstain":
            word = str((entry.get("banned") or ["그곳"])[0])
            out.append(
                {
                    "item": entry["id"],
                    "kind": kind,
                    "reply": "그런 적은 없었던 것 같은데. 기억나는 게 없어.",
                    "expected": "declined",
                }
            )
            out.append(
                {
                    "item": entry["id"],
                    "kind": kind,
                    "reply": f"그때 그 {word}, 이름이 '별빛{word}'였잖아. 창가 자리였고.",
                    "expected": "fabricated",
                }
            )
        elif kind == "speaker":
            claim = str((entry.get("keywords") or [""])[0])
            out.append(
                {
                    "item": entry["id"],
                    "kind": kind,
                    "reply": str(entry.get("expectedAnswer", "")),
                    "expected": "correct",
                }
            )
            if entry.get("subtype") == "fabricated":
                wrong = f"응, 네가 직접 {claim} 얘기했잖아. 네 입으로 그랬어."
            else:
                wrong = f"그건 네가 한 말이 아니라 다른 사람이 한 말이었어. {claim} 얘기는 네가 한 적 없어."
            out.append({"item": entry["id"], "kind": kind, "reply": wrong, "expected": "misattributed"})
        elif kind == "rewind":
            word = str((entry.get("keywords") or [""])[0])
            out.append(
                {
                    "item": entry["id"],
                    "kind": kind,
                    "reply": f"{word} 얘기했잖아. 다음 달에 간다고.",
                    "expected": "asserted",
                }
            )
            out.append(
                {
                    "item": entry["id"],
                    "kind": kind,
                    "reply": f"음… 혹시 {word} 같은 거였나? 확실하진 않아.",
                    "expected": "guess",
                }
            )
            out.append(
                {"item": entry["id"], "kind": kind, "reply": "그건 잘 기억이 안 나. 뭐였더라?", "expected": "none"}
            )
    return out


class HaikuJudge:
    """Anthropic 직결 구조화 호출(사고 끔·effort low). 생성자에서 키를 받는다 — 키가 비면 만들 수 없다."""

    def __init__(self, api_key: str, ledger: Ledger, *, stage: str) -> None:
        if not api_key:
            raise SystemExit("판정자는 Anthropic 키가 있어야 한다")
        import anthropic

        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._ledger = ledger
        self._stage = stage

    async def verdict(self, prompt: str) -> JudgeVerdict:
        from api.llm.claude_messages import message_usage, parse_structured, structured_output_config

        self._ledger.check_headroom(JUDGE_CALL_ESTIMATE_USD)
        output_config: Any = {**structured_output_config(JudgeVerdict), "effort": "low"}
        message = await self._client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=1_000,
            thinking={"type": "disabled"},
            output_config=output_config,
            messages=[{"role": "user", "content": prompt}],
        )
        usage = message_usage(message)
        self._ledger.append(
            stage=self._stage,
            call_site="memory_eval_judge",
            model=JUDGE_MODEL,
            input_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
            cached_tokens=int(getattr(usage, "cached_content_token_count", 0) or 0),
            cache_write_tokens=int(getattr(usage, "cache_write_token_count", 0) or 0),
            output_tokens=int(getattr(usage, "candidates_token_count", 0) or 0),
            thoughts_tokens=int(getattr(usage, "thoughts_token_count", 0) or 0),
        )
        return parse_structured(message, JudgeVerdict, "anthropic", "Anthropic")


async def judged_or_none(judge: HaikuJudge, kind: JudgeKind, prompt: str) -> str | None:
    for _ in range(JUDGE_RETRIES):
        try:
            result = await judge.verdict(prompt)
        except Exception:  # 판정 실패·파싱 실패·거부 — 같은 입력으로 다시
            await asyncio.sleep(1)
            continue
        if result.verdict in VERDICTS[kind]:
            return result.verdict
    return None


def control_accuracy(rows: Sequence[dict[str, Any]]) -> float:
    scored = [r for r in rows if r.get("judged") is not None]
    if not scored:
        return 0.0
    return sum(1 for r in scored if r["judged"] == r["expected"]) / len(scored)


def require_controls_passed(path: Path) -> None:
    if not path.exists():
        raise SystemExit("판정자 대조군 기록이 없다 — 대조군을 먼저 돌린다")
    accuracy = float(json.loads(path.read_text(encoding="utf-8"))["accuracy"])
    if accuracy < CONTROL_ACCURACY_MIN:
        raise SystemExit(f"판정자 대조군 정확도 {accuracy:.3f} < {CONTROL_ACCURACY_MIN} — 본 판정을 하지 않는다")
