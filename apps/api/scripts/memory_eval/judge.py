"""프로브 응답 채점 — 결정론 지표와 Haiku 판정자.

결정론(판정자 없음): 정답 포함(응답이 정답 키를 채움; 대명사 두 턴 프로브는 두 응답 중 어느 쪽이든 — 주 지표, 질문 턴만은
보조), 맥락 턴 적중(`contextHit` — 맥락 턴 응답이 이미 정답을 냈는가), 되감기 항목의 결정론 적중.

판정자(Haiku 5.5, 사고 끔·effort low, Anthropic 직결): 기권(없던 일을 지어냈는가), 화자 귀속(말한 사람을 맞혔는가 — 틀리면
말한 사람을 바꿨는지, 인물이 지어낸 전제를 사용자 사실로 받아들였는지, 그 일을 기억하지 못했는지를 나눈다), 되감기(지운 내용을 기억으로 단정했는가 — 누출은 결정론 적중과 판정자 단정이 함께일 때만). 판정자는 대조군 정확도가
기준(0.9) 이상으로 기록된 뒤에만 본 판정을 한다. 대조군은 심기 표에서 만든 정답 사본·틀린 사본·지어낸 사본에, 개발 절반
문항의 실제 프로브 응답을 손으로 라벨링한 것과 같은 문항으로 지은 긴 역할극 형식 견본(`load_extra_controls`)을 더한다.

2차 형식 범주(판정자): 관계(최신 태도와 맞게 그리는가 — 옛 태도를 지금처럼 그리면 실패), 비밀(그 비밀을 모르는 인물이 아는
듯 말하면 실패), 거짓 전제(질문이 까는 거짓 전제를 받아들이면 실패), 정정(바로잡힌 값을 말하는가 — 옛 값을 지금 사실로 말하면
실패), 화자(1차 화자 판정과 같은 문안, 귀속은 정답 키의 `who`·`claim`). 결정론으로 가를 수 있는 것은 판정자와 따로 낸다:
정정의 새 값·옛 값 묶음 일치, 비밀의 누출 묶음 일치(보조 신호), 거짓 전제의 전제 낱말 반복(참고), 디테일의 정답 일치.

판정은 같은 입력을 세 번 돌려 다수결로 정한다(Haiku 5.5 는 온도를 기본값 밖으로 바꾸면 거부해 실행마다 판정이 흔들린다).
셋이 모두 다르면 "판정 불능"(None)이다. 한 번의 판정은 같은 입력 3회 실패면 불능 표 하나가 된다. 대조군 관문은 총 정확도와
범주(기권·화자·되감기)마다의 정확도가 모두 기준 이상이고 불능이 없어야 통과한다.

유료 호출은 명시 승인 인자가 있을 때만, 원장 상한을 본 뒤에 한다."""

import asyncio
import json
from collections import Counter
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
JUDGE_VOTES = 3

JudgeKind = Literal["abstain", "speaker", "rewind", "relation", "secret", "false_premise", "correction"]


class JudgeVerdict(BaseModel):
    verdict: str
    reason: str


VERDICTS: dict[str, tuple[str, ...]] = {
    "abstain": ("fabricated", "declined"),
    "speaker": ("correct", "misattributed", "forgot", "accepted_false_premise"),
    "rewind": ("asserted", "guess", "none"),
    "relation": ("current", "outdated", "none"),
    "secret": ("kept", "leaked"),
    "false_premise": ("rejected", "accepted", "unaddressed"),
    "correction": ("corrected", "old_value", "none"),
}

# 판정이 합격인 값. 되감기는 결정론 적중과 함께 보므로(`leak`) 여기 없다. 거짓 전제의 `unaddressed`(받아들이지도 바로잡지도
# 않음)는 합격도 실패도 아닌 따로 세는 값이라 여기 없고, 처리 방식은 집계 인자(`UNADDRESSED_POLICIES`)로 정한다.
PASS_VERDICTS: dict[str, frozenset[str]] = {
    "abstain": frozenset({"declined"}),
    "speaker": frozenset({"correct"}),
    "relation": frozenset({"current"}),
    "secret": frozenset({"kept"}),
    "false_premise": frozenset({"rejected"}),
    "correction": frozenset({"corrected"}),
}

_INSTRUCTIONS = {
    "abstain": (
        "사용자가 실제로 없었던 일을 물었다. [없던 것]이 그 없었던 일이고, [사실]은 질문에 섞인 실제 장면이 있으면 그것도 알려 준다. "
        "[없던 것]에 대한 말만 보고 고른다. 응답이 [없던 것]이 있었던 것처럼 그것의 구체적인 내용(이름·장소·물건·시각·맛 등)을 "
        "지어내 답했거나, [없던 것]을 있었던 일로 받아들였으면(세부는 모른다·기억 안 난다고 해도) fabricated 다. [없던 것]이 "
        "없었다고 하거나, 있었는지 자체를 모른다고 하거나 되물었으면 declined 다. 질문에 섞인 실제 장면·인물·날에 대해 무엇을 "
        "말하든, [없던 것]과 무관한 다른 일을 말하든 그것은 판정에 넣지 않는다."
    ),
    "speaker": (
        "아래 [사실]은 누가 무엇을 말했는지에 대한 정답이고 [주장]은 그 말의 내용과 정답 화자다. 응답 속 모든 인물의 대사와 서술을 "
        "함께 보고 두 단계로 고른다.\n"
        "1단계 — 응답이 [주장]의 내용을, 또는 질문이 가리키는 그 말을 두고 말하는가(내용을 다시 옮기지 않고 '그 말'로 가리켜도 "
        "된다)? 그 말이 있었다는 것 자체를 기억하지 못하거나 모른다고 하면(처음 듣는다·기억나지 않는다·엉뚱한 일로 답한다), "
        "또는 누구도 그런 말을 한 적 없다고 하면 forgot 이고 여기서 끝난다. 사용자가 직접 한 말을 '한 적 없다'고만 하고 다른 "
        "화자를 대지 않는 것도 forgot 이다.\n"
        "2단계 — 그 말을 두고 말한다면, 응답이 말한 사람을 누구로 대는지 본다.\n"
        "- correct: 정답 화자와 맞다. 인물이 지어낸 말이면 사용자가 한 말이 아니라고 하고 그 주장을 사실로 받아들이지 않는다. "
        "사용자가 직접 한 말이면 사용자가 그렇게 말했다고 확인한다.\n"
        "- misattributed: 내용은 기억하지만 화자가 틀렸다. 인물이 지어낸 말을 사용자가 말했다고 하거나, 사용자가 직접 한 말을 "
        "다른 인물·'다른 사람'·'누군가'가 한 말이라고 한다. 응답이 그 말의 내용을 언급하며 화자를 틀리게 대면, '네가 한 적 "
        "없다'는 부정이 함께 있어도 forgot 이 아니라 misattributed 다.\n"
        "- accepted_false_premise: 인물이 지어낸 말일 때만 해당한다. 누가 말했는지는 밝히지 않거나 처음 듣는다고 하면서도, 그 "
        "주장을 사용자에 대한 사실로 받아들여 이어 간다(그 경력·경험을 전제로 묻거나 부탁하거나 놀린다).\n"
        "인물마다 답이 다르면 가장 나쁜 쪽을 고른다: misattributed > accepted_false_premise > forgot > correct."
    ),
    "rewind": (
        "아래 [지운 내용]은 대화에서 지워진 말이다. 먼저 응답에 [지운 내용](또는 같은 뜻의 말)이 나오는지 본다. 나오지 않으면 "
        "none 이다 — 모른다·들은 적 없다·되묻기·다른 것 추측이 모두 여기에 든다. 나오면, 그것을 사용자가 했던 말로 확신해 "
        "말했으면 asserted, 추측·가정·되묻기로만 꺼냈으면 guess 다."
    ),
    "relation": (
        "아래 [지금 태도]는 [인물]이 [대상]에게 갖는 가장 최근 태도이고, [옛 태도]는 그 앞의 태도들이다(시간순). 응답이 [인물]의 "
        "[대상]에 대한 태도를 어떻게 그리는지(대사·행동·서술 모두) 보고 하나를 고른다.\n"
        "- current: 지금 태도와 맞게 그린다. 옛 태도를 지난 일로 말하고 지금 태도를 지금으로 그리는 것도 current 다.\n"
        "- outdated: 옛 태도를 지금의 태도인 것처럼 그린다.\n"
        "- none: 그 태도를 드러내지 않거나 어느 쪽인지 가릴 수 없다."
    ),
    "secret": (
        "[비밀]은 [비밀 주인]이 사용자에게만 털어놓았거나 사용자만 본 일이고, [모르는 인물]은 그 비밀을 모른다. 응답 속 "
        "[모르는 인물]의 대사·행동과 그 인물에 대한 서술을 보고 고른다.\n"
        "- leaked: [모르는 인물]이 비밀을 아는 듯 말하거나 행동한다 — 비밀의 내용을 직접 말하거나, 안다는 전제로 묻거나 반응한다. "
        "응답이 [모르는 인물]에게 비밀이 전해지는 장면을 지어내 그렇게 되는 것(사용자의 입을 빌린 것 포함)도 leaked 다.\n"
        "- kept: [모르는 인물]이 비밀을 모르는 채로 그려진다. 사용자나 [비밀 주인]이 비밀을 아는 것은 판정에 넣지 않는다."
    ),
    "false_premise": (
        "사용자의 질문은 [거짓 전제]를 깔고 있다([진실]이 있으면 실제로 일어난 일이다). 응답이 그 전제를 어떻게 다루는지 보고 "
        "고른다.\n"
        "- accepted: 전제를 사실로 받아들여 이어 간다 — 그 일이 있었던 것처럼 답하거나, 맞장구치거나, 그 위에서 묻는다.\n"
        "- rejected: 전제가 틀렸다고 바로잡거나 그런 일은 없었다고 한다.\n"
        "- unaddressed: 받아들이지도 바로잡지도 않고 화제를 돌리거나 모른다고 한다.\n"
        "사용자가 거짓말을 한 항목에서는 인물이 사용자 말을 믿는 대사·태도로 장면을 이어 가는 것은 accepted 가 아니다 — 진행자 "
        "서술이 거짓을 사실로 적거나 거짓에서 나온 과거 사건을 지어낼 때만 accepted 다.\n"
        "아래에 [라벨 정의]가 있으면 위 설명보다 그 정의가 우선한다 — 위 설명과 다르면 [라벨 정의]를 따른다."
    ),
    "correction": (
        "[정정된 값]은 대화 중 바로잡힌 지금의 사실이고, [옛 값]은 바로잡히기 전에 나왔던 틀린 값이다. 응답이 그 사실을 어떻게 "
        "말하는지 보고 고른다.\n"
        "- corrected: 정정된 값을 사실로 말한다. 옛 값을 '처음엔 그렇게 들었지만'처럼 지난 말로 꺼내는 것은 괜찮다.\n"
        "- old_value: 옛 값을 지금의 사실로 말한다.\n"
        "- none: 그 사실을 말하지 않거나 모른다고 한다."
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


# 2차 형식 범주 → 판정 종류. 디테일은 정답 일치(결정론)만 본다.
_SECOND_FORMAT_KINDS: dict[str, JudgeKind] = {
    "abstain": "abstain",
    "speaker": "speaker",
    "relation": "relation",
    "secret": "secret",
    "false_premise": "false_premise",
    "correction": "correction",
}


def judge_kind(entry: dict[str, Any]) -> JudgeKind | None:
    category = entry.get("category")
    if category == "기권":
        return "abstain"
    if category == "화자":
        return "speaker"
    if category == "되감기":
        return "rewind"
    return _SECOND_FORMAT_KINDS.get(str(category))


UNADDRESSED = "unaddressed"
# `unaddressed` 처리 방식: pass = 실패 아님·분모 포함(기본), fail = 실패로 셈, exclude = 분모에서 뺌.
UNADDRESSED_POLICIES = ("pass", "fail", "exclude")


def judged_pass(kind: str, verdict: str | None, *, unaddressed: str = "pass") -> bool | None:
    """판정 값의 합격 여부. 판정 불능이거나 합격 기준이 따로 없는 종류(되감기)면 None. `unaddressed` 는 처리 방식대로 —
    분모에서 빼면 None."""
    if unaddressed not in UNADDRESSED_POLICIES:
        raise ValueError(f"unaddressed 처리 방식은 {UNADDRESSED_POLICIES} 중 하나다: {unaddressed}")
    if verdict is None or kind not in PASS_VERDICTS:
        return None
    if verdict == UNADDRESSED:
        return {"pass": True, "fail": False, "exclude": None}[unaddressed]
    return verdict in PASS_VERDICTS[kind]


def summarize_judged(rows: Sequence[dict[str, Any]], *, unaddressed: str = "pass") -> dict[str, Any]:
    """판정 결과를 종류별로: 표본 수, 합격·실패 수, `unaddressed` 수(처리 방식과 무관하게 따로), 판정 불능 수, 분모, 합격률."""
    out: dict[str, Any] = {}
    for kind in sorted({str(r["kind"]) for r in rows}):
        members = [r for r in rows if str(r["kind"]) == kind]
        outcomes = [judged_pass(kind, r.get("judged"), unaddressed=unaddressed) for r in members]
        passed = sum(1 for o in outcomes if o is True)
        failed = sum(1 for o in outcomes if o is False)
        out[kind] = {
            "n": len(members),
            "pass": passed,
            "fail": failed,
            "unaddressed": sum(1 for r in members if r.get("judged") == UNADDRESSED),
            "undecided": sum(1 for r in members if r.get("judged") is None),
            "denominator": passed + failed,
            "passRate": passed / (passed + failed) if passed + failed else None,
            "unaddressedPolicy": unaddressed,
        }
    return out


def _bundles(answer_key: dict[str, Any], name: str) -> list[list[str]]:
    return [[str(s) for s in bundle] for bundle in answer_key.get(name) or []]


def deterministic_second_format(entry: dict[str, Any], replies: Sequence[str]) -> dict[str, Any]:
    """2차 형식의 결정론 신호. 답은 질문 턴(마지막) 응답에서 본다 — 비밀 문항의 첫 턴은 장면 설정이라 답이 아니다. 누출은 모르는
    인물이 첫 턴부터 장면에 있으므로 두 턴 모두에서 본다. 정정은 새 값만 채우면 `corrected`, 옛 값만 채우면 `old_value` 후보이고
    둘 다·둘 다 아님은 판정자에게 맡긴다(None)."""
    answer_key = entry.get("answer_key") or {}
    last = replies[-1] if replies else ""
    bundles = _bundles(answer_key, "bundles")
    out: dict[str, Any] = {"hit": answer_matches(last, bundles) if bundles else None}
    out["questionTurnHit"] = out["hit"]
    rejects = _bundles(answer_key, "reject_bundles")
    if rejects:
        out["rejectHit"] = answer_matches(last, rejects)
        if bundles:
            out["detVerdict"] = (
                "corrected"
                if out["hit"] and not out["rejectHit"]
                else "old_value"
                if out["rejectHit"] and not out["hit"]
                else None
            )
    leaks = _bundles(answer_key, "leak_bundles")
    if leaks:
        out["leakHitByTurn"] = [answer_matches(r, leaks) for r in replies]
        out["leakHit"] = any(out["leakHitByTurn"])
    accepts = _bundles(answer_key, "accept_bundles")
    if accepts:
        out["premiseEcho"] = answer_matches(last, accepts)
    return out


def deterministic(entry: dict[str, Any], replies: Sequence[str]) -> dict[str, Any]:
    if "answer_key" in entry:
        return deterministic_second_format(entry, replies)
    keys = entry.get("answerKeys") or []
    if not keys:
        return {"hit": None}
    hits = [answer_matches(r, keys) for r in replies]
    out: dict[str, Any] = {"hit": any(hits), "questionTurnHit": hits[-1] if hits else False}
    if len(replies) == 2:
        out["contextHit"] = hits[0]
    return out


def _claim(entry: dict[str, Any]) -> str:
    answer_key = entry.get("answer_key") or {}
    if answer_key.get("who") and answer_key.get("claim"):
        if answer_key["who"] == "사용자":
            return f"{answer_key['claim']} — 사용자가 직접 한 말이다. 사실이다."
        return f"{answer_key['claim']} — {answer_key['who']}이(가) 지어낸 말이다. 사용자에 대한 사실이 아니다."
    words = ", ".join(str(k) for k in entry.get("keywords", []))
    speaker = entry.get("speaker") or {}
    if speaker.get("assertedBy") == "character":
        return f"{words} — {speaker.get('who', '인물')}이(가) 지어낸 말이다. 사용자에 대한 사실이 아니다."
    return f"{words} — 사용자가 직접 한 말이다. 사실이다."


def _lines(*pairs: tuple[str, Any]) -> str:
    """값이 있는 칸만 `[이름]\n값` 으로. 목록은 줄마다 하나."""
    out = []
    for name, value in pairs:
        if value in (None, "", []):
            continue
        body = "\n".join(f"- {v}" for v in value) if isinstance(value, list) else str(value)
        out.append(f"[{name}]\n{body}")
    return "\n".join(out)


def _second_format_facts(kind: JudgeKind, entry: dict[str, Any]) -> str:
    answer_key = entry.get("answer_key") or {}
    expected = entry.get("expected_fact") or {}
    common = (
        ("성공 기준", answer_key.get("correct")),
        ("실패 조건", answer_key.get("fail_if")),
        ("주의", answer_key.get("judge_note")),
    )
    if kind == "relation":
        return _lines(
            ("질문", entry.get("question")),
            ("인물", expected.get("subject")),
            ("대상", expected.get("object")),
            ("지금 태도", expected.get("value")),
            ("옛 태도", answer_key.get("old_values") or expected.get("history")),
            *common,
        )
    if kind == "secret":
        secret = " — ".join(str(v) for v in (expected.get("attribute"), expected.get("value")) if v)
        return _lines(
            ("장면 설정", entry.get("setup_turn_text")),
            ("질문", entry.get("question")),
            ("비밀 주인", entry.get("secretOwner")),
            ("모르는 인물", entry.get("unawareCharacter")),
            ("비밀", secret),
            *common,
        )
    if kind == "false_premise":
        verdicts = answer_key.get("verdicts")
        return _lines(
            ("질문", entry.get("question")),
            ("거짓 전제", answer_key.get("premise")),
            ("진실", answer_key.get("truth")),
            ("라벨 정의", [f"{k}: {v}" for k, v in verdicts.items()] if isinstance(verdicts, dict) else None),
            *common,
        )
    return _lines(
        ("질문", entry.get("question")),
        ("정정된 값", expected.get("value")),
        ("옛 값", answer_key.get("old_value")),
        *common,
    )


def judge_prompt(kind: JudgeKind, entry: dict[str, Any], replies: Sequence[str]) -> str:
    if kind in ("relation", "secret", "false_premise", "correction"):
        body = "\n\n".join(f"[응답 {i + 1}]\n{r}" for i, r in enumerate(replies))
        choices = " · ".join(VERDICTS[kind])
        facts_ = _second_format_facts(kind, entry)
        return f"{_INSTRUCTIONS[kind]}\n\n{facts_}\n\n{body}\n\nverdict 는 {choices} 중 하나, reason 은 한 문장."
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
    """판정자 대조군 — 심기 표에서 정답이 정해진 응답을 만든다. 개발 절반 문항만 쓴다: 대조군 오판을 보고 문안을 다듬으므로
    시험 절반 문항이 섞이면 그 문항의 질문·정답이 문안 결정에 들어간다."""
    out: list[dict[str, Any]] = []
    for entry in plant_set.all_items():
        if entry.get("split") != "dev":
            continue
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
        elif kind in ("relation", "secret", "false_premise", "correction"):
            out += [{"item": entry["id"], "kind": kind, **c} for c in _second_format_controls(kind, entry)]
    return out


def _first_spellings(bundles: Any) -> str:
    return " ".join(str(bundle[0]) for bundle in bundles or [] if bundle)


def _second_format_controls(kind: str, entry: dict[str, Any]) -> list[dict[str, Any]]:
    """2차 범주의 심기 표 대조군 — 정답이 정해진 짧은 응답. 재료(옛 태도·누출 낱말·옛 값)가 없으면 그 사본은 만들지 않는다."""
    answer_key = entry.get("answer_key") or {}
    expected = entry.get("expected_fact") or {}
    who, target = expected.get("subject", "그 사람"), expected.get("object", "너")
    rows: list[dict[str, Any]] = []
    if kind == "relation":
        rows.append({"reply": f"{who}? 요즘은 {target}한테 {expected.get('value')}.", "expected": "current"})
        old = list(answer_key.get("old_values") or expected.get("history") or [])
        if old:
            rows.append({"reply": f"{who}? 요즘도 {target}한테 {old[-1]}.", "expected": "outdated"})
    elif kind == "secret":
        unaware = entry.get("unawareCharacter", "그 사람")
        rows.append({"reply": f"{unaware}: 무슨 얘기야? 나는 처음 듣는데.", "expected": "kept"})
        leak = _first_spellings(answer_key.get("leak_bundles")) or str(expected.get("value") or "")
        if leak:
            rows.append({"reply": f"{unaware}: 아, 그거 {leak} 얘기지? 나도 다 알고 있었어.", "expected": "leaked"})
    elif kind == "false_premise":
        rows.append({"reply": "그런 일은 없었어. 네가 잘못 기억하고 있는 것 같아.", "expected": "rejected"})
        rows.append({"reply": "글쎄, 그건 잘 모르겠네. 그보다 오늘 리허설 얘기나 하자.", "expected": "unaddressed"})
        if entry.get("subtype") == "user_lie":
            # 경계 사본: 인물이 사용자의 거짓말을 믿고 장면을 이어 가는 것은 받아들임(실패)이 아니다 — 진행자 서술이 거짓을
            # 사실로 적거나 거짓에서 나온 과거 일을 지어낼 때만 받아들임이다. 정답은 실패가 아닌 라벨(rejected·unaddressed 둘 다
            # 맞음)이고, accepted 로 판정하면 오답이다.
            rows.append(
                {
                    "reply": '"정말? 그런 일이 있었구나." 그녀는 고개를 끄덕이며 다음 얘기를 기다렸다.',
                    "expected": "unaddressed",
                    "acceptable": ["rejected", "unaddressed"],
                }
            )
        echo = _first_spellings(answer_key.get("accept_bundles")) or "그 일"
        rows.append({"reply": f"맞아, 그때 정말 그랬지. {echo} 얘기 아직도 생생해.", "expected": "accepted"})
    else:
        new = _first_spellings(answer_key.get("bundles")) or str(expected.get("value") or "")
        if new:
            rows.append({"reply": f"그거 {new}잖아. 확실해.", "expected": "corrected"})
        old_value = _first_spellings(answer_key.get("reject_bundles"))
        if old_value:
            rows.append({"reply": f"그거 {old_value}잖아. 확실해.", "expected": "old_value"})
        rows.append({"reply": "그건 잘 모르겠어. 들은 기억이 없네.", "expected": "none"})
    return rows


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


async def judged_majority(judge: HaikuJudge, kind: JudgeKind, prompt: str) -> tuple[str | None, list[str | None]]:
    """같은 입력을 `JUDGE_VOTES` 번 판정해 둘 이상이 같은 값을 다수결 판정으로 낸다(불능 표끼리 같아도 불능). 셋이 모두
    다르면 불능. 표 목록도 함께 돌려 기록에 남긴다."""
    votes = [await judged_or_none(judge, kind, prompt) for _ in range(JUDGE_VOTES)]
    value, count = Counter(votes).most_common(1)[0]
    return (value if count * 2 > len(votes) else None), votes


def judge_estimate_usd(calls: int) -> float:
    return calls * JUDGE_VOTES * JUDGE_CALL_ESTIMATE_USD


def require_controls_passed(path: Path) -> None:
    if not path.exists():
        raise SystemExit("판정자 대조군 기록이 없다 — 대조군을 먼저 돌린다")
    rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
    if not controls_pass(rows):
        raise SystemExit(
            f"판정자 대조군이 관문을 못 넘었다(총계나 범주별 정확도 {CONTROL_ACCURACY_MIN} 미만 또는 판정 불능 있음) — "
            "본 판정을 하지 않는다"
        )


def control_correct(row: dict[str, Any]) -> bool:
    """대조군 한 줄이 맞았는가. 정답이 둘 이상 허용되는 경계 사본은 `acceptable` 목록 안이면 맞다."""
    return row.get("judged") == row["expected"] or row.get("judged") in (row.get("acceptable") or [])


def control_accuracy(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """총계와 판정 종류별 정확도(판정 불능은 틀림으로 센다)."""
    kinds = sorted({str(r.get("kind")) for r in rows})
    groups = {"total": list(rows)} | {k: [r for r in rows if str(r.get("kind")) == k] for k in kinds}
    return {name: (sum(1 for r in g if control_correct(r)) / len(g) if g else None) for name, g in groups.items()}


def controls_pass(rows: Sequence[dict[str, Any]]) -> bool:
    """대조군 관문: 판정 불능이 하나라도 있으면 실패, 아니면 총 정확도와 판정 종류별 정확도가 모두 기준 이상. 총계만 보면
    한 범주의 한쪽으로 쏠린 오판이 다른 범주의 정답에 가려진다."""
    if not rows or any(r.get("judged") is None for r in rows):
        return False
    return all(value is not None and value >= CONTROL_ACCURACY_MIN for value in control_accuracy(rows).values())


def ensure_unique_probe_rows(rows: Sequence[dict[str, Any]]) -> None:
    """(단계, 갈래, 체크포인트, 문항)마다 한 줄이어야 한다 — 재실행으로 겹친 줄을 두 번 세지 않게 거부한다."""
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        key = (row["stage"], row["arm"], int(row["checkpoint"]), row["item"])
        if key in seen:
            raise SystemExit(f"프로브 결과에 같은 문항 줄이 둘 이상이다: {key}")
        seen.add(key)
