"""사실 계층의 순수 계산 — 키 정규화, 키별 최신 읽기, 렌더 순서와 글자 상한. LLM·DB 없음.

행 칸: `kind`(relation·fact), `subject`, `object`(관계만), `attribute`(사실만), `fact_key`, `value`, `truth_status`(confirmed·claimed·
disproved), `asserted_by`(user·character·narration), `speaker`, `known_by`(배열, 없으면 공개·불명), `importance` 1~5, 원문 범위.
행은 접힌 창마다 덧붙기만 한다(append-only) — 행 목록의 순서가 곧 쓴 순서다.

- 키 = 종류 + 주어 + (관계는 대상, 사실은 속성). 칸마다 키워드 정규화(NFC·casefold) 뒤 공백을 한 칸으로 줄이고 앞뒤를 지운다.
- 키별 최신: 같은 키의 마지막 행이 이긴다. 단 반증된 값은 뒤의 주장으로 되살아나지 않는다 — 같은 키에 같은 값의 반증 행이
  앞에 있으면 마지막 행이 반증이 아니어도 그 반증 행이 이긴다. 값이 다른 옛 주장의 반증 행은 새 값을 가리지 않는다(정정).
- 렌더 순서: 관계 → 아는 사람이 정해진 사실 → 반증 → 그 밖의 사실. 묶음 안은 중요도가 높은 쪽, 같으면 최근 쪽이 먼저다.
- 렌더 상한: 줄을 순서대로 이어 붙이다 다음 줄이 상한(줄바꿈 포함 글자 수)을 넘으면 거기서 멈추고 나머지는 모두 탈락이다.
  줄 모양은 이 하네스의 시제품이다 — 운영 렌더가 생기면 그 함수의 줄로 같은 상한을 다시 잰다."""

from collections.abc import Mapping, Sequence
from typing import Any

from api.chat.keyword_notes import normalize_keyword_text

KINDS = ("relation", "fact")
TRUTH_STATUSES = ("confirmed", "claimed", "disproved")
RENDER_MAX_CHARS = 700
# 추출 입력에 주는 기존 키 목록의 줄 수 상한.
EXISTING_KEYS_MAX = 40


def normalize_part(text: str | None) -> str:
    return " ".join(normalize_keyword_text(text or "").split())


def fact_key(kind: str, subject: str | None, target: str | None) -> str:
    return "|".join(normalize_part(part) for part in (kind, subject, target))


def target_of(row: Mapping[str, Any]) -> str | None:
    return row.get("object") if row.get("kind") == "relation" else row.get("attribute")


def row_key(row: Mapping[str, Any]) -> str:
    return fact_key(str(row.get("kind", "")), row.get("subject"), target_of(row))


def latest_by_key(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """키마다 이긴 행 하나씩, 이긴 행이 쓰인 순서대로. 돌려주는 행에는 쓴 순번(`_order`)을 붙인다."""
    groups: dict[str, list[tuple[int, Mapping[str, Any]]]] = {}
    for order, row in enumerate(rows):
        groups.setdefault(row_key(row), []).append((order, row))
    winners: list[tuple[int, Mapping[str, Any]]] = []
    for members in groups.values():
        order, winner = members[-1]
        if winner.get("truth_status") != "disproved":
            value = normalize_part(winner.get("value"))
            refuted = [
                (o, r)
                for o, r in members
                if r.get("truth_status") == "disproved" and normalize_part(r.get("value")) == value
            ]
            if refuted:
                order, winner = refuted[-1]
        winners.append((order, winner))
    return [{**row, "_order": order} for order, row in sorted(winners, key=lambda pair: pair[0])]


def _group(row: Mapping[str, Any]) -> int:
    if row.get("kind") == "relation":
        return 0
    if row.get("known_by"):
        return 1
    if row.get("truth_status") == "disproved":
        return 2
    return 3


def render_order(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """키별 최신 행(`_order` 가 붙은 것)을 렌더 순서로."""
    return sorted(rows, key=lambda r: (_group(r), -int(r.get("importance") or 0), -int(r.get("_order") or 0)))


def render_line(row: Mapping[str, Any]) -> str:
    if row.get("kind") == "relation":
        head = f"- {row.get('subject')} → {row.get('object')}: {row.get('value')}"
    else:
        head = f"- {row.get('subject')} · {row.get('attribute')}: {row.get('value')}"
    status = row.get("truth_status")
    if status == "claimed":
        head += f" (주장 — {row['speaker']})" if row.get("speaker") else " (주장)"
    elif status == "disproved":
        head += " (사실 아님)"
    if row.get("known_by"):
        head += f" (아는 사람: {', '.join(str(n) for n in row['known_by'])})"
    return head


def render(
    rows: Sequence[Mapping[str, Any]], *, max_chars: int = RENDER_MAX_CHARS
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]], str]:
    """덧붙은 행 전부를 받아 키별 최신으로 줄이고 렌더한다. (실린 행, 상한에 잘린 행, 렌더 글)."""
    ordered = render_order(latest_by_key(rows))
    kept: list[Mapping[str, Any]] = []
    lines: list[str] = []
    used = 0
    for k, row in enumerate(ordered):
        line = render_line(row)
        cost = len(line) + (1 if lines else 0)
        if used + cost > max_chars:
            return kept, list(ordered[k:]), "\n".join(lines)
        kept.append(row)
        lines.append(line)
        used += cost
    return kept, [], "\n".join(lines)


def existing_key_lines(rows: Sequence[Mapping[str, Any]], *, limit: int = EXISTING_KEYS_MAX) -> list[str]:
    """추출 입력의 기존 키 목록: 앞 창들의 행을 키별 최신으로 줄여 최근 `limit` 개를 `키 = 값 (진실 상태)` 줄로."""
    latest = latest_by_key(rows)[-limit:] if limit > 0 else []
    return [f"{row_key(r)} = {r.get('value')} ({r.get('truth_status')})" for r in latest]
