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
3. 개수 — 칸마다 v6-fix 프롬프트 속 v6-fix 조각 등장 수와 보완판 프롬프트 속 보완판 조각 등장 수(치환 수)가 같고, 보완판
   프롬프트에 v6-fix 조각이 하나도 남지 않는다. 같은 조각이 두 자리에 실렸는데 한 자리만 바뀐 경우를 역치환(되돌리면
   같아진다)과 양성(한 번 이상 있다)은 둘 다 통과시킨다.
4. 고유 조각 잔존 — 칸마다 v6-fix 문안에서 보완판과 다른 부분을 앞뒤 글자와 함께 떼어 낸 조각(보완판 문안에는 없는
   조각)이 보완판 프롬프트에 몇 번 나와야 하는지를 셈으로 맞춘다: v6-fix 프롬프트 속 횟수에서 바뀐 칸들이 가져간 만큼
   빼고 보완판 문안이 들여온 만큼 더한 값. 대화 기록에 같은 말(예: 「사흘 뒤」)이 원래 있어도 셈에 들어가므로 거짓 실패가
   나지 않고, 칸 밖에 v6-fix 문안이 남으면 셈이 어긋난다.

칸 문안은 작품 글 원문(`{{user}}`·이미지 태그가 남은 형태)이다. 프롬프트와 견주는 단언은 조립 함수가 하는 변환(이미지
태그를 지우고 `{{user}}` 를 이름으로 바꿈)을 거친 프롬프트 형태로 한다(`prompt_form`). `target` 이 `historyOpening` 인
칸은 작품 행이 아니라 대화 기록 첫 진행자 줄(방을 만들 때 복사된 오프닝)을 바꾼다.
"""

import difflib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SwapSlot:
    key: str
    v6fix: str
    supplement: str
    when: str
    target: str = "rows"

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
        SwapSlot(
            key=s["key"], v6fix=s["v6fix"], supplement=s["supplement"], when=s["when"], target=s.get("target", "rows")
        )
        for s in data["slots"]
    ]
    keys = [s.key for s in slots]
    if len(set(keys)) != len(keys):
        raise ValueError("치환 표에 같은 칸 키가 둘 이상 있다")
    for slot in slots:
        if not slot.v6fix or not slot.supplement or slot.v6fix == slot.supplement:
            raise ValueError(f"칸 {slot.key}: 두 문안이 비었거나 같다")
        slot.expected([], [])  # 조건 형식만 먼저 검사한다
        if slot.target not in SWAP_TARGETS:
            raise ValueError(f"칸 {slot.key} 의 바꿀 자리를 모른다: {slot.target}")
    if sum(slot.target == "historyOpening" for slot in slots) > 1:
        raise ValueError("대화 기록 오프닝을 바꾸는 칸은 하나뿐이어야 한다")
    return slots


SWAP_TARGETS = ("rows", "historyOpening")
# 고유 조각의 앞뒤로 붙이는 글자 수 — 「셋째」 같은 짧은 차이도 대화 기록의 우연한 같은 말과 덜 겹치게 한다.
UNIQUE_CONTEXT = 6


def unique_fragments(v6fix: str, supplement: str) -> list[str]:
    """v6-fix 문안에서 보완판과 다른 부분마다, 앞뒤 글자를 붙여 보완판 문안에는 없는 조각으로 만든다(끼워 넣기만 있는
    자리도 앞뒤 글자로 조각이 생긴다). 보완판에 없을 때까지 앞뒤를 넓힌다."""
    fragments: list[str] = []
    matcher = difflib.SequenceMatcher(a=v6fix, b=supplement, autojunk=False)
    for tag, i1, i2, _j1, _j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        pad = UNIQUE_CONTEXT
        while True:
            fragment = v6fix[max(0, i1 - pad) : i2 + pad]
            if fragment not in supplement or (i1 - pad <= 0 and i2 + pad >= len(v6fix)):
                break
            pad *= 2
        if fragment in supplement:
            raise ValueError("v6-fix 문안이 보완판 문안 안에 통째로 들어 있어 고유 조각을 만들 수 없다")
        if fragment not in fragments:
            fragments.append(fragment)
    return fragments


def check_swap(
    *,
    base_prompt: str,
    base_system: str,
    swapped_prompt: str,
    swapped_system: str,
    slots: list[SwapSlot],
    situation_notes: Iterable[str],
    keyword_notes: Iterable[str],
    prompt_form: Callable[[str], str] = lambda text: text,
) -> dict[str, Any]:
    situation_notes, keyword_notes = list(situation_notes), list(keyword_notes)
    forms = {s.key: (prompt_form(s.v6fix), prompt_form(s.supplement)) for s in slots}
    restored = swapped_prompt
    counts: dict[str, int] = {}
    # 긴 조각부터 되돌린다 — 짧은 조각이 긴 조각 안에 들어 있을 때 긴 쪽이 먼저 깨지지 않게.
    for slot in sorted(slots, key=lambda s: len(forms[s.key][1]), reverse=True):
        v6, sup = forms[slot.key]
        counts[slot.key] = restored.count(sup)
        restored = restored.replace(sup, v6)
    expected = {s.key for s in slots if s.expected(situation_notes, keyword_notes)}
    missing = sorted(k for k in expected if counts[k] == 0)
    unexpected = sorted(k for k, n in counts.items() if n > 0 and k not in expected)
    base_counts = {key: base_prompt.count(v6) for key, (v6, _sup) in forms.items()}
    base_loaded = {key for key, n in base_counts.items() if n > 0}
    condition_mismatch = sorted(expected ^ base_loaded)
    count_mismatch = sorted(key for key in forms if base_counts[key] != counts[key])
    leftover = {key: swapped_prompt.count(v6) for key, (v6, _sup) in forms.items() if swapped_prompt.count(v6)}
    fragment_residue: dict[str, int] = {}
    for key, (v6, sup) in forms.items():
        for fragment in unique_fragments(v6, sup):
            due = base_prompt.count(fragment) + sum(
                base_counts[k] * (forms[k][1].count(fragment) - forms[k][0].count(fragment)) for k in forms
            )
            residue = swapped_prompt.count(fragment) - due
            if residue:
                fragment_residue[f"{key}: {fragment}"] = residue
    result: dict[str, Any] = {
        "reverseIdentical": restored == base_prompt,
        "systemInstructionIdentical": swapped_system == base_system,
        "expectedSlots": sorted(expected),
        "swapCounts": counts,
        "missingSlots": missing,
        "unexpectedSlots": unexpected,
        "conditionMismatch": condition_mismatch,
        "baseCounts": base_counts,
        "countMismatch": count_mismatch,
        "v6fixLeftover": leftover,
        "uniqueFragmentResidue": fragment_residue,
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
        and not count_mismatch
        and not leftover
        and not fragment_residue
    )
    return result


def replace_in_value(value: Any, slots: list[SwapSlot], hits: dict[str, int]) -> Any:
    """문자열·목록·사전 안의 v6-fix 조각을 보완판 조각으로 바꾼 새 값(원본은 그대로). 칸마다 바꾼 횟수를 `hits` 에
    더한다 — 메모리 안 바꿔 끼우기(격리 DB 에 보완판 버전이 없을 때)가 쓴다."""
    if isinstance(value, str):
        for slot in slots:
            if slot.target != "rows":
                continue
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
