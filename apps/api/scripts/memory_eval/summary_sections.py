"""요약 본문의 칸별 글자 수와 비율. 운영 요약 지시문은 요약을 `[지금]`·`[관계]`·`[지난 일]` 세 칸으로, 이 순서로 쓰게 한다 —
사실 계층을 들일 때 `[관계]` 칸이 요약에서 얼마를 차지하는지(사실 섹션과 겹치는 몫)를 잰다.

칸 = 줄 맨 앞의 `[이름]` 머리글부터 다음 머리글 앞까지. 글자 수는 머리글을 뺀 본문의 앞뒤 공백을 지운 길이(가운데 공백·줄바꿈
포함)이고, 비율의 분모는 모든 칸 글자 수의 합이다. 첫 머리글 앞의 글은 `(머리글 없음)` 칸으로 센다. 지시문에 없는 이름의
머리글도 칸으로 세고 따로 표시한다(요약이 칸 이름을 바꿔 쓴 것을 놓치지 않게)."""

import json
import re
from pathlib import Path
from typing import Any

SECTION_NAMES = ("지금", "관계", "지난 일")
NO_HEADER = "(머리글 없음)"
_HEADER = re.compile(r"^\[([^\]\n]{1,20})\]", re.MULTILINE)


def section_chars(summary: str) -> dict[str, int]:
    """칸 이름 → 글자 수(같은 이름이 두 번 나오면 더한다). 순서는 처음 나온 순서."""
    out: dict[str, int] = {}
    matches = list(_HEADER.finditer(summary))
    head = summary[: matches[0].start()] if matches else summary
    if head.strip():
        out[NO_HEADER] = len(head.strip())
    for k, match in enumerate(matches):
        end = matches[k + 1].start() if k + 1 < len(matches) else len(summary)
        body = summary[match.end() : end].strip()
        out[match.group(1)] = out.get(match.group(1), 0) + len(body)
    return out


def section_report(summary: str) -> dict[str, Any]:
    chars = section_chars(summary)
    total = sum(chars.values())
    return {
        "total": total,
        "sections": {name: {"chars": n, "ratio": n / total if total else None} for name, n in chars.items()},
        "relationRatio": chars.get("관계", 0) / total if total else None,
        "unknownHeaders": [name for name in chars if name not in SECTION_NAMES and name != NO_HEADER],
    }


def summaries_from_file(path: Path) -> list[tuple[str, str]]:
    """(이름, 요약 본문) 목록. 드라이버 기억 기록(`memory-snapshots.jsonl`)은 첫 기억 조회의 요약 — 복원 직후 첫 턴 전이라
    체크포인트의 요약이다. 그 밖의 파일은 파일 전체를 요약 본문 하나로 읽는다."""
    text = path.read_text(encoding="utf-8")
    if path.suffix != ".jsonl":
        return [(str(path), text)]
    for line in text.splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("kind") == "memorySnapshot" and row.get("summary"):
                return [(str(path), str(row["summary"]))]
    return []
