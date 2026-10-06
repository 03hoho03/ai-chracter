"""생성 리플레이의 "작품 글 바꿔 끼우기" 갈래가 쓰는 치환 표와 두 겹 단언.

치환 표(JSON)는 바꾼 칸마다 v6-fix 문안과 보완판 문안, 그 칸이 생성 프롬프트에 실리는 조건을 적는다:

    {"slots": [
        {"key": "무대-날넘김", "v6fix": "<v6-fix 원문 조각>", "supplement": "<보완판 조각>", "when": "always"},
        {"key": "상영회 당일 노트", "v6fix": "...", "supplement": "...", "when": "situationNote:상영회 당일"},
        {"key": "장소 노트", "v6fix": "...", "supplement": "...", "when": "keywordNote:장소"}
    ]}

`when` 은 `always`, 또는 측정 분석표(`turns.json`)의 그 턴 `situationNotes`·`keywordNotes` 에 든 이름이다. 조각은 칸
전체일 필요는 없고, 그 칸 안에서 바뀐 부분을 덮는 문자열이면 된다 — 같은 조각이 생성 프롬프트의 다른 자리(히스토리 등)에
나오면 단언이 실패하므로(거짓 통과가 아니라 거짓 실패 쪽) 충분히 긴 조각을 쓴다.

단언 두 겹:
1. 역치환 — 보완판 프롬프트에서 보완판 조각을 v6-fix 조각으로 되돌리면 같은 턴의 v6-fix 프롬프트와 바이트까지 같다. 바꿔
   끼운 것이 표의 칸뿐이고 히스토리·요약·노트·그 밖의 조립은 그대로라는 뜻이다.
2. 양성 — 그 턴에 실려야 할 칸(`when`)마다 보완판 조각이 보완판 프롬프트에 한 번 이상 있다. 역치환만으로는 칸을 덜
   바꿔 끼운 경우(보완판 버전에 v6-fix 문안이 남은 경우)가 통과한다. 더해서 실림 조건과 실제 실림이 엇갈리면(실려야 할 칸의
   v6-fix 조각이 v6-fix 프롬프트에 없거나, 안 실려야 할 칸이 실림) 실패로 본다 — 표의 조건이나 조각이 틀린 것이다.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SwapSlot:
    key: str
    v6fix: str
    supplement: str
    when: str

    def expected(self, situation_notes: Iterable[str], keyword_notes: Iterable[str]) -> bool:
        if self.when == "always":
            return True
        kind, _, name = self.when.partition(":")
        if kind == "situationNote":
            return name in set(situation_notes)
        if kind == "keywordNote":
            return name in set(keyword_notes)
        raise ValueError(f"칸 {self.key} 의 실림 조건을 모른다: {self.when}")


def load_swap_table(path: Path) -> list[SwapSlot]:
    data = json.loads(path.read_text(encoding="utf-8"))
    slots = [
        SwapSlot(key=s["key"], v6fix=s["v6fix"], supplement=s["supplement"], when=s["when"]) for s in data["slots"]
    ]
    keys = [s.key for s in slots]
    if len(set(keys)) != len(keys):
        raise ValueError("치환 표에 같은 칸 키가 둘 이상 있다")
    for slot in slots:
        if not slot.v6fix or not slot.supplement or slot.v6fix == slot.supplement:
            raise ValueError(f"칸 {slot.key}: 두 문안이 비었거나 같다")
        slot.expected([], [])  # 조건 형식만 먼저 검사한다
    return slots


def check_swap(
    *,
    base_prompt: str,
    base_system: str,
    swapped_prompt: str,
    swapped_system: str,
    slots: list[SwapSlot],
    situation_notes: Iterable[str],
    keyword_notes: Iterable[str],
) -> dict[str, Any]:
    situation_notes, keyword_notes = list(situation_notes), list(keyword_notes)
    restored = swapped_prompt
    counts: dict[str, int] = {}
    # 긴 조각부터 되돌린다 — 짧은 조각이 긴 조각 안에 들어 있을 때 긴 쪽이 먼저 깨지지 않게.
    for slot in sorted(slots, key=lambda s: len(s.supplement), reverse=True):
        counts[slot.key] = restored.count(slot.supplement)
        restored = restored.replace(slot.supplement, slot.v6fix)
    expected = {s.key for s in slots if s.expected(situation_notes, keyword_notes)}
    missing = sorted(k for k in expected if counts[k] == 0)
    unexpected = sorted(k for k, n in counts.items() if n > 0 and k not in expected)
    base_loaded = {s.key for s in slots if s.v6fix in base_prompt}
    condition_mismatch = sorted(expected ^ base_loaded)
    result: dict[str, Any] = {
        "reverseIdentical": restored == base_prompt,
        "systemInstructionIdentical": swapped_system == base_system,
        "expectedSlots": sorted(expected),
        "swapCounts": counts,
        "missingSlots": missing,
        "unexpectedSlots": unexpected,
        "conditionMismatch": condition_mismatch,
    }
    if not result["reverseIdentical"]:
        result["firstDifferenceAt"] = next(
            (i for i, (x, y) in enumerate(zip(restored, base_prompt, strict=False)) if x != y),
            min(len(restored), len(base_prompt)),
        )
    result["passed"] = (
        result["reverseIdentical"]
        and result["systemInstructionIdentical"]
        and not missing
        and not unexpected
        and not condition_mismatch
    )
    return result


def replace_in_value(value: Any, slots: list[SwapSlot], hits: dict[str, int]) -> Any:
    """문자열·목록·사전 안의 v6-fix 조각을 보완판 조각으로 바꾼 새 값(원본은 그대로). 칸마다 바꾼 횟수를 `hits` 에
    더한다 — 메모리 안 바꿔 끼우기(격리 DB 에 보완판 버전이 없을 때)가 쓴다."""
    if isinstance(value, str):
        for slot in slots:
            n = value.count(slot.v6fix)
            if n:
                hits[slot.key] = hits.get(slot.key, 0) + n
                value = value.replace(slot.v6fix, slot.supplement)
        return value
    if isinstance(value, list):
        return [replace_in_value(v, slots, hits) for v in value]
    if isinstance(value, dict):
        return {k: replace_in_value(v, slots, hits) for k, v in value.items()}
    return value
