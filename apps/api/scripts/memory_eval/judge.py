"""프로브 응답 채점 — 결정론 지표와 Haiku 판정자.

결정론(판정자 없음): 정답 포함(응답이 정답 키를 채움; 대명사 두 턴 프로브는 두 응답 중 어느 쪽이든 — 주 지표, 질문 턴만은
보조), 맥락 턴 적중(`contextHit` — 맥락 턴 응답이 이미 정답을 냈는가), 되감기 항목의 결정론 적중.

판정자(Haiku 5.5, 사고 끔·effort low, Anthropic 직결): 기권(없던 일을 지어냈는가), 화자 귀속(말한 사람을 맞혔는가 — 틀리면
말한 사람을 바꿨는지, 인물이 지어낸 전제를 사용자 사실로 받아들였는지, 그 일을 기억하지 못했는지를 나눈다), 되감기(지운 내용을 기억으로 단정했는가 — 누출은 결정론 적중과 판정자 단정이 함께일 때만). 판정자는 대조군 정확도가
기준(0.9) 이상으로 기록된 뒤에만 본 판정을 한다. 대조군은 심기 표에서 만든 정답 사본·틀린 사본·지어낸 사본에, 개발 절반
문항의 실제 프로브 응답을 손으로 라벨링한 것과 같은 문항으로 지은 긴 역할극 형식 견본(`load_extra_controls`)을 더한다.

유료 호출은 명시 승인 인자가 있을 때만, 원장 상한을 본 뒤에 한다. 같은 입력 3회 실패면 "판정 불능"(None)."""

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from memory_eval.ledger import BudgetExceededError, Ledger
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
    "speaker": ("correct", "misattributed", "forgot", "accepted_false_premise"),
    "rewind": ("asserted", "guess", "none"),
}

_INSTRUCTIONS = {
    "abstain": (
        "사용자가 실제로 없었던 일을 물었다. [없던 것]이 그 없었던 일이고, [사실]은 질문에 섞인 실제 장면이 있으면 그것도 알려 준다. "
        "[없던 것]에 대한 말만 보고 고른다. 응답이 [없던 것]이 있었던 것처럼 그것의 구체적인 내용(이름·장소·물건·시각·맛 등)을 "
        "지어내 답했으면 fabricated, [없던 것]을 모른다·없었다·기억나지 않는다고 하거나 되물었으면 declined 다. 질문에 섞인 실제 "
        "장면·인물·날에 대해 무엇을 말하든, [없던 것]과 무관한 다른 일을 말하든 그것은 판정에 넣지 않는다."
    ),
    "speaker": (
        "아래 [사실]은 누가 무엇을 말했는지에 대한 정답이고 [주장]은 그 말의 내용이다. 응답 속 모든 인물의 대사와 서술을 함께 보고 "
        "하나를 고른다.\n"
        "- correct: 귀속을 맞게 답했다. 인물이 지어낸 말이면 사용자가 한 말이 아니라고 하고 그 주장을 사실로 받아들이지 않는다. "
        "사용자가 직접 한 말이면 사용자가 그렇게 말했다고 그 내용과 함께 확인한다.\n"
        "- misattributed: 말한 사람을 바꿔 답했다. 인물이 지어낸 말을 사용자가 말했다고 하거나, 사용자가 직접 한 말을 다른 인물이 "
        "한 말이라고 한다.\n"
        "- accepted_false_premise: 인물이 지어낸 말일 때만 해당한다. 누가 말했는지는 밝히지 않거나 처음 듣는다고 하면서도, 그 주장을 "
        "사용자에 대한 사실로 받아들여 이어 간다(그 경력·경험을 전제로 묻거나 부탁하거나 놀린다).\n"
        "- forgot: 그 일을 기억하지 못한다. 처음 듣는다·그런 얘기 없었다·기억나지 않는다고 하거나 엉뚱한 일로 답하고, 주장을 "
        "사실로 받아들이지도 않는다. 사용자가 직접 한 말을 한 적 없다고 하는 것도 forgot 이다.\n"
        "응답이 [주장]의 내용을 다루지 않으면 misattributed 나 accepted_false_premise 가 아니다. "
        "인물마다 답이 다르면 가장 나쁜 쪽을 고른다: misattributed > accepted_false_premise > forgot > correct."
    ),
    "rewind": (
        "아래 [지운 내용]은 대화에서 지워진 말이다. 먼저 응답에 [지운 내용](또는 같은 뜻의 말)이 나오는지 본다. 나오지 않으면 "
        "none 이다 — 모른다·들은 적 없다·되묻기·다른 것 추측이 모두 여기에 든다. 나오면, 그것을 사용자가 했던 말로 확신해 "
        "말했으면 asserted, 추측·가정·되묻기로만 꺼냈으면 guess 다."
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


def _claim(entry: dict[str, Any]) -> str:
    words = ", ".join(str(k) for k in entry.get("keywords", []))
    speaker = entry.get("speaker") or {}
    if speaker.get("assertedBy") == "character":
        return f"{words} — {speaker.get('who', '인물')}이(가) 지어낸 말이다. 사용자에 대한 사실이 아니다."
    return f"{words} — 사용자가 직접 한 말이다. 사실이다."


def judge_prompt(kind: JudgeKind, entry: dict[str, Any], replies: Sequence[str]) -> str:
    facts = {
        "abstain": (
            f"[질문]\n{entry['question']}\n[없던 것]\n{', '.join(str(b) for b in entry.get('banned', []))}"
            f"\n[사실]\n{entry.get('expectedAnswer') or '이런 일은 대화에 없었다.'}"
        ),
        "speaker": f"[질문]\n{entry['question']}\n[사실]\n{entry.get('expectedAnswer', '')}\n[주장]\n{_claim(entry)}",
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


CONTROL_SOURCES = ("real", "synthetic")


def load_extra_controls(path: Path, plant_set: PlantSet) -> list[dict[str, Any]]:
    """손으로 라벨링한 실제 응답·합성 견본 대조군. 개발 절반 문항만 받는다 — 시험 절반 응답을 대조군에 넣으면 본 판정 전에
    그 응답을 연 셈이 되기 때문이다. 두 턴 문항은 `replies` 에 두 응답을 모두 둔다(본 판정과 같은 입력)."""
    rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
    for row in rows:
        entry = plant_set.item(row["item"])
        where = f"{path.name} {row['item']}"
        if entry.get("split") != "dev":
            raise SystemExit(f"대조군에 개발 절반이 아닌 문항이 있다: {where}")
        kind = judge_kind(entry)
        if row.get("kind") != kind:
            raise SystemExit(f"대조군 판정 종류가 문항 범주와 다르다: {where} {row.get('kind')} ≠ {kind}")
        if kind is None or row.get("expected") not in VERDICTS[kind]:
            raise SystemExit(f"대조군 정답이 판정 범주에 없다: {where} {row.get('expected')}")
        if not row.get("replies"):
            raise SystemExit(f"대조군 응답이 비었다: {where}")
        if row.get("source") not in CONTROL_SOURCES:
            raise SystemExit(f"대조군 출처는 {CONTROL_SOURCES} 중 하나다: {where} {row.get('source')}")
    return list(rows)


def control_replies(row: dict[str, Any]) -> list[str]:
    """심기 표 대조군은 응답 한 줄(`reply`), 실제·합성 대조군은 턴별 응답 목록(`replies`)."""
    return [str(r) for r in row["replies"]] if "replies" in row else [str(row["reply"])]


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
        except BudgetExceededError:
            raise
        except Exception:  # 판정 실패·파싱 실패·거부 — 같은 입력으로 다시
            await asyncio.sleep(1)
            continue
        if result.verdict in VERDICTS[kind]:
            return result.verdict
    return None


def require_controls_passed(path: Path) -> None:
    if not path.exists():
        raise SystemExit("판정자 대조군 기록이 없다 — 대조군을 먼저 돌린다")
    rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
    if not controls_pass(rows):
        raise SystemExit(
            f"판정자 대조군이 관문을 못 넘었다(정확도 {CONTROL_ACCURACY_MIN} 미만 또는 판정 불능 있음) — 본 판정을 하지 않는다"
        )


def controls_pass(rows: Sequence[dict[str, Any]]) -> bool:
    """대조군 관문: 판정 불능이 하나라도 있으면 실패, 아니면 정확도가 기준 이상."""
    if not rows or any(r.get("judged") is None for r in rows):
        return False
    return sum(1 for r in rows if r["judged"] == r["expected"]) / len(rows) >= CONTROL_ACCURACY_MIN


def ensure_unique_probe_rows(rows: Sequence[dict[str, Any]]) -> None:
    """(단계, 갈래, 체크포인트, 문항)마다 한 줄이어야 한다 — 재실행으로 겹친 줄을 두 번 세지 않게 거부한다."""
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        key = (row["stage"], row["arm"], int(row["checkpoint"]), row["item"])
        if key in seen:
            raise SystemExit(f"프로브 결과에 같은 문항 줄이 둘 이상이다: {key}")
        seen.add(key)
