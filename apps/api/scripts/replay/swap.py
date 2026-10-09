"""작품 글 치환 표 — 버전을 새로 만들지 않고 작품 글 일부만 바꿔 같은 턴을 다시 조립하는 갈래(`swap`)와 그 단언.

치환 표(JSON)는 바꿀 칸마다 지금 글 조각(`before`)과 바꿀 글 조각(`after`)을 적는다:

    {"slots": [
        {"key": "무대", "before": "<지금 작품 글 조각>", "after": "<바꿀 조각>"},
        {"key": "오프닝", "before": "<방에 복사된 오프닝>", "after": "<바꿀 오프닝>", "target": "historyOpening"}
    ]}

조각은 칸 전체일 필요는 없고 그 칸 안에서 바뀐 부분을 덮는 문자열이면 된다. 같은 조각이 생성 프롬프트의 다른
자리(대화 기록 등)에도 나오면 단언이 실패하므로(거짓 통과가 아니라 거짓 실패 쪽) 충분히 긴 조각을 쓴다. 칸 문안은 작품
글 원문(`{{user}}`·그림 태그가 남은 형태)이고, 프롬프트와 견주는 단언은 조립 함수가 하는 변환(그림 태그를 지우고
`{{user}}` 를 이름으로 바꿈)을 거친 형태로 한다(`prompt_form`). `target` 이 `historyOpening` 인 칸은 작품 행이 아니라
대화 기록 첫 진행자 줄(방을 만들 때 복사된 오프닝)을 바꾼다.

어느 칸이 그 턴 프롬프트에 실려야 하는지는 현행 프롬프트에 그 칸의 지금 글이 몇 번 나오는지로 정한다. 단언 네 겹:
1. 역치환 — 바꾼 프롬프트에서 바꾼 조각을 지금 조각으로 되돌리면 현행 프롬프트와 바이트까지 같고, 지시문도 같다. 바뀐
   것이 표의 칸뿐이고 히스토리·요약·노트·그 밖의 조립은 그대로라는 뜻이다.
2. 양성 — 현행 프롬프트에 실린 칸마다 바꾼 조각이 한 번 이상 있고, 실리지 않은 칸의 바꾼 조각은 없다. 그리고 실린 칸이
   하나는 있다(없으면 두 갈래가 같은 프롬프트라 비교할 것이 없다).
3. 개수 — 칸마다 현행 프롬프트 속 지금 조각 수와 바꾼 프롬프트 속 바꾼 조각 수가 같고, 바꾼 프롬프트에 지금 조각이
   남지 않는다. 같은 조각이 두 자리에 실렸는데 한 자리만 바뀐 경우를 역치환과 양성은 둘 다 통과시킨다.
4. 고유 조각 잔존 — 칸마다 지금 글에서 바꿀 글과 다른 부분을 앞뒤 글자와 함께 떼어 낸 조각(바꿀 글에는 없는 조각)이
   바꾼 프롬프트에 몇 번 나와야 하는지를 셈으로 맞춘다: 현행 프롬프트 속 횟수에서 바뀐 칸들이 가져간 만큼 빼고 바꿀
   글이 들여온 만큼 더한 값. 대화 기록에 같은 말이 원래 있어도 셈에 들어가 거짓 실패가 나지 않고, 칸 밖에 지금 글이
   남으면 셈이 어긋난다.
"""

import difflib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SWAP_TARGETS = ("rows", "historyOpening")
# 고유 조각의 앞뒤로 붙이는 글자 수 — 짧은 차이도 대화 기록의 우연한 같은 말과 덜 겹치게 한다.
UNIQUE_CONTEXT = 6


@dataclass(frozen=True)
class SwapSlot:
    key: str
    before: str
    after: str
    target: str = "rows"


def load_swap_table(path: Path) -> list[SwapSlot]:
    data = json.loads(path.read_text(encoding="utf-8"))
    slots = [
        SwapSlot(key=s["key"], before=s["before"], after=s["after"], target=s.get("target", "rows"))
        for s in data["slots"]
    ]
    if not slots:
        raise ValueError("치환 표에 칸이 없다")
    keys = [s.key for s in slots]
    if len(set(keys)) != len(keys):
        raise ValueError("치환 표에 같은 칸 키가 둘 이상 있다")
    for slot in slots:
        if not slot.before or not slot.after or slot.before == slot.after:
            raise ValueError(f"칸 {slot.key}: 두 문안이 비었거나 같다")
        if slot.target not in SWAP_TARGETS:
            raise ValueError(f"칸 {slot.key} 의 바꿀 자리를 모른다: {slot.target}")
    if sum(slot.target == "historyOpening" for slot in slots) > 1:
        raise ValueError("대화 기록 오프닝을 바꾸는 칸은 하나뿐이어야 한다")
    return slots


def unique_fragments(before: str, after: str) -> list[str]:
    """지금 글에서 바꿀 글과 다른 부분마다, 앞뒤 글자를 붙여 바꿀 글에는 없는 조각으로 만든다(끼워 넣기만 있는 자리도
    앞뒤 글자로 조각이 생긴다). 바꿀 글에 없을 때까지 앞뒤를 넓힌다."""
    fragments: list[str] = []
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    for tag, i1, i2, _j1, _j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        pad = UNIQUE_CONTEXT
        while True:
            fragment = before[max(0, i1 - pad) : i2 + pad]
            if fragment not in after or (i1 - pad <= 0 and i2 + pad >= len(before)):
                break
            pad *= 2
        if fragment in after:
            raise ValueError("지금 글이 바꿀 글 안에 통째로 들어 있어 고유 조각을 만들 수 없다")
        if fragment not in fragments:
            fragments.append(fragment)
    return fragments


def first_difference(a: str, b: str) -> int:
    return next((i for i, (x, y) in enumerate(zip(a, b, strict=False)) if x != y), min(len(a), len(b)))


def check_swap(
    *,
    base_prompt: str,
    base_system: str,
    swapped_prompt: str,
    swapped_system: str,
    slots: list[SwapSlot],
    prompt_form: Callable[[str], str] = lambda text: text,
) -> dict[str, Any]:
    forms = {s.key: (prompt_form(s.before), prompt_form(s.after)) for s in slots}
    restored = swapped_prompt
    counts: dict[str, int] = {}
    # 긴 조각부터 되돌린다 — 짧은 조각이 긴 조각 안에 들어 있을 때 긴 쪽이 먼저 깨지지 않게.
    for slot in sorted(slots, key=lambda s: len(forms[s.key][1]), reverse=True):
        before, after = forms[slot.key]
        counts[slot.key] = restored.count(after)
        restored = restored.replace(after, before)
    base_counts = {key: base_prompt.count(before) for key, (before, _after) in forms.items()}
    loaded = sorted(key for key, n in base_counts.items() if n > 0)
    missing = sorted(key for key in loaded if counts[key] == 0)
    unexpected = sorted(key for key, n in counts.items() if n > 0 and key not in loaded)
    count_mismatch = sorted(key for key in forms if base_counts[key] != counts[key])
    leftover = {
        key: swapped_prompt.count(before) for key, (before, _after) in forms.items() if swapped_prompt.count(before)
    }
    fragment_residue: dict[str, int] = {}
    for key, (before, after) in forms.items():
        for fragment in unique_fragments(before, after):
            due = base_prompt.count(fragment) + sum(
                base_counts[k] * (forms[k][1].count(fragment) - forms[k][0].count(fragment)) for k in forms
            )
            residue = swapped_prompt.count(fragment) - due
            if residue:
                fragment_residue[f"{key}: {fragment}"] = residue
    result: dict[str, Any] = {
        "reverseIdentical": restored == base_prompt,
        "systemInstructionIdentical": swapped_system == base_system,
        "loadedSlots": loaded,
        "swapCounts": counts,
        "missingSlots": missing,
        "unexpectedSlots": unexpected,
        "baseCounts": base_counts,
        "countMismatch": count_mismatch,
        "beforeLeftover": leftover,
        "uniqueFragmentResidue": fragment_residue,
    }
    if not result["reverseIdentical"]:
        result["firstDifferenceAt"] = first_difference(restored, base_prompt)
    result["passed"] = (
        result["reverseIdentical"]
        and result["systemInstructionIdentical"]
        and bool(loaded)
        and not missing
        and not unexpected
        and not count_mismatch
        and not leftover
        and not fragment_residue
    )
    return result


def replace_in_value(value: Any, slots: list[SwapSlot], hits: dict[str, int]) -> Any:
    """문자열·목록·사전 안의 지금 조각을 바꿀 조각으로 바꾼 새 값(원본은 그대로). 칸마다 바꾼 횟수를 `hits` 에 더한다."""
    if isinstance(value, str):
        for slot in slots:
            if slot.target != "rows":
                continue
            n = value.count(slot.before)
            if n:
                hits[slot.key] = hits.get(slot.key, 0) + n
                value = value.replace(slot.before, slot.after)
        return value
    if isinstance(value, list):
        return [replace_in_value(v, slots, hits) for v in value]
    if isinstance(value, dict):
        return {k: replace_in_value(v, slots, hits) for k, v in value.items()}
    return value
