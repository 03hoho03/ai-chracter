"""고정 대본(`transcript.jsonl`, 줄마다 `{turn, user, assistant}`) 읽기와 기계 검사.

검사 규칙(사전 등록한 배제 규칙):
- 턴 번호가 1부터 빠짐없이 차례로, 정해진 수만큼.
- 사용자 줄 길이(공백 포함), 진행자 줄 길이(공백 뺀 글자) — 범위는 실행 인자로 받는다(보정값이 바뀔 수 있다).
- 심는 턴의 지정된 줄(사용자·진행자)에 핵심어가 있다.
- 핵심어가 심는 턴·명시한 재언급 턴 밖에 나오지 않는다. 체크포인트 T 의 원문 윈도 후보 구간 [T−29, T] 에 심는 턴 말고
  다시 나오면 원문 창이 실어 회상이 아니게 되므로 따로 센다(명시한 재언급이어도 센다).
- 핵심어가 작품 글·질문·맥락 턴 문장에 없다(질문은 `exclusionWaiver` 가 있는 항목만 예외).
- 기권 항목의 금지 낱말이 대본 어디에도 없다.
- 체크포인트 턴의 진행자 줄에 어떤 핵심어·단서 명사도 없다(프로브 직전 줄이 답을 흘리지 않게).

비교는 정답 일치와 같은 정규화(NFC · casefold · 공백 제거)다."""

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memory_eval.metrics import normalize_match_text
from memory_eval.plants import PlantSet, checkpoints, plant_turns

# 원문 윈도가 실을 수 있는 최대 턴 수(접기 직전 29턴).
RAW_WINDOW_TURNS = 29


@dataclass(frozen=True)
class ScriptTurn:
    turn: int
    user: str
    assistant: str


@dataclass(frozen=True)
class LengthRule:
    user: tuple[int, int]
    narrator: tuple[int, int]


def load_transcript(path: Path) -> list[ScriptTurn]:
    turns = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            turns.append(ScriptTurn(turn=int(row["turn"]), user=str(row["user"]), assistant=str(row["assistant"])))
    return turns


def narrator_length(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


def _violation(rule: str, item: str | None, turn: int | None, detail: str) -> dict[str, Any]:
    return {"rule": rule, "item": item, "turn": turn, "detail": detail}


def _turns_with(word: str, by_turn: dict[int, str]) -> list[int]:
    needle = normalize_match_text(word)
    return sorted(t for t, text in by_turn.items() if needle and needle in text)


def check_script(
    turns: Sequence[ScriptTurn], plant_set: PlantSet, *, work_text: str, rule: LengthRule, expected_turns: int
) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    numbers = [t.turn for t in turns]
    if numbers != list(range(1, expected_turns + 1)):
        missing = sorted(set(range(1, expected_turns + 1)) - set(numbers))
        violations.append(
            _violation("턴 번호", None, None, f"기대 1~{expected_turns}, 빠짐 {missing[:10]}, 실제 {len(numbers)}줄")
        )

    user_lengths = [len(t.user) for t in turns]
    narrator_lengths = [narrator_length(t.assistant) for t in turns]
    for t in turns:
        if not rule.user[0] <= len(t.user) <= rule.user[1]:
            violations.append(_violation("사용자 줄 길이", None, t.turn, f"{len(t.user)}자"))
        n = narrator_length(t.assistant)
        if not rule.narrator[0] <= n <= rule.narrator[1]:
            violations.append(_violation("진행자 줄 길이", None, t.turn, f"공백 뺀 {n}자"))

    by_line = {
        "user": {t.turn: normalize_match_text(t.user) for t in turns},
        "assistant": {t.turn: normalize_match_text(t.assistant) for t in turns},
    }
    whole = {t.turn: by_line["user"][t.turn] + "\n" + by_line["assistant"][t.turn] for t in turns}
    work = normalize_match_text(work_text)
    cps = checkpoints(plant_set)

    keyword_table: list[dict[str, Any]] = []
    for plant in plant_set.plants:
        pid = str(plant["id"])
        planted = plant_turns(plant)
        line = str(plant.get("speaker", {}).get("line", "assistant"))
        re_mention = {int(t) for t in plant.get("reMentionTurns", [])}
        probe_cps = sorted(
            {int(c) for c in plant["probeCheckpoints"].get("opus", []) + plant["probeCheckpoints"].get("offline", [])}
        )
        for keyword in plant.get("keywords", []):
            needle = normalize_match_text(str(keyword))
            seen = _turns_with(str(keyword), whole)
            keyword_table.append({"item": pid, "keyword": keyword, "plantTurns": planted, "turns": seen})
            for planted_turn in planted:
                if needle not in by_line[line].get(planted_turn, ""):
                    violations.append(_violation("심는 줄에 핵심어 없음", pid, planted_turn, f"{keyword} ({line})"))
            extra = [t for t in seen if t not in planted and t not in re_mention]
            if extra:
                violations.append(_violation("핵심어 재등장", pid, extra[0], f"{keyword} 턴 {extra}"))
            for cp in probe_cps:
                inside = [t for t in seen if cp - RAW_WINDOW_TURNS <= t <= cp and t not in planted]
                if inside:
                    violations.append(
                        _violation("원문 윈도 후보 구간에 핵심어", pid, inside[0], f"{keyword} CP{cp} 턴 {inside}")
                    )
            if needle and needle in work:
                violations.append(_violation("작품 글에 핵심어", pid, None, str(keyword)))
            if (
                needle
                and needle in normalize_match_text(str(plant.get("question", "")))
                and not plant.get("exclusionWaiver")
            ):
                violations.append(_violation("질문에 핵심어", pid, None, str(keyword)))
            context = plant.get("contextTurn") or {}
            if needle and needle in normalize_match_text(str(context.get("userLine", ""))):
                violations.append(_violation("맥락 문장에 핵심어", pid, None, str(keyword)))

    for abstain in plant_set.abstains:
        for word in abstain.get("banned", []):
            seen = _turns_with(str(word), whole)
            if seen:
                violations.append(_violation("기권 금지 낱말", str(abstain["id"]), seen[0], f"{word} 턴 {seen}"))

    watched = sorted(
        {str(w) for p in plant_set.plants for w in list(p.get("keywords", [])) + list(p.get("cueNouns", []))}
    )
    for cp in cps:
        text = by_line["assistant"].get(cp, "")
        hits = [w for w in watched if normalize_match_text(w) and normalize_match_text(w) in text]
        if hits:
            violations.append(_violation("체크포인트 진행자 줄에 핵심어·단서", None, cp, ", ".join(hits)))

    cue_table = [
        {"item": str(p["id"]), "cue": cue, "turns": _turns_with(str(cue), whole)}
        for p in plant_set.plants
        for cue in p.get("cueNouns", [])
    ]
    forms = Counter((str(p.get("category")), str(p.get("questionForm"))) for p in plant_set.plants)
    return {
        "violations": violations,
        "keywordTable": keyword_table,
        "cueTable": cue_table,
        "lengths": {"user": _distribution(user_lengths), "narrator": _distribution(narrator_lengths)},
        "forms": [{"category": c, "form": f, "count": n} for (c, f), n in sorted(forms.items())],
    }


def _distribution(values: Sequence[int]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "min": None, "median": None, "max": None}
    ordered = sorted(values)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    return {"n": len(ordered), "min": ordered[0], "median": median, "max": ordered[-1]}


def work_text_from_seed(seed_path: Path) -> str:
    """작품 글 = 시드 작품 JSON 의 문자열 전부(설정·오프닝·프롤로그·키워드북·상황 노트 등)."""
    parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            parts.append(node)

    walk(json.loads(seed_path.read_text(encoding="utf-8")))
    return "\n".join(parts)
