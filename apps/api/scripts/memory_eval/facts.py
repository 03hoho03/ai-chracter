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

from memory_eval.metrics import answer_matches, normalize_match_text, wilson_interval

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
            disproved_rows = [
                (o, r)
                for o, r in members
                if r.get("truth_status") == "disproved" and normalize_part(r.get("value")) == value
            ]
            if disproved_rows:
                order, winner = disproved_rows[-1]
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


# ---------------------------------------------------------------- 오프라인 지표

# 정답 묶음이 지금 값을 묻는 범주(정답 = 기대 사실의 값). 나머지 범주의 묶음은 질문의 답(귀속·거절·비밀 지킴)이라 값 비교에 쓰지 않는다.
_VALUE_BUNDLE_CATEGORIES = ("relation", "correction", "detail")


def expected_key(expected: Mapping[str, Any]) -> str:
    return row_key(expected)


def _names(value: Any) -> frozenset[str]:
    return frozenset(normalize_part(str(n)) for n in (value or []) if normalize_part(str(n)))


def value_matches(row_value: str | None, entry: Mapping[str, Any]) -> bool:
    """값은 느슨히 본다: 정답 일치와 같은 정규화(NFC·casefold·공백 제거·숫자 표기) 뒤 기대 값과 행 값 가운데 한쪽이 다른
    쪽에 들어 있거나, 정답 묶음이 지금 값을 묻는 범주(관계·정정·디테일)에서 행 값이 그 묶음을 채우면 맞다."""
    expected = (entry.get("expected_fact") or {}).get("value")
    got = normalize_match_text(str(row_value or ""))
    want = normalize_match_text(str(expected or ""))
    if got and want and (want in got or got in want):
        return True
    bundles = (entry.get("answer_key") or {}).get("bundles") or []
    return (
        entry.get("category") in _VALUE_BUNDLE_CATEGORIES and bool(bundles) and answer_matches(str(row_value), bundles)
    )


def row_matches(row: Mapping[str, Any], entry: Mapping[str, Any], *, check_key: bool = True) -> bool:
    """행이 항목의 기대 사실을 담는가: 키(정규화 뒤 같음) · 진실 상태(같음) · 아는 사람(정규화한 이름 집합이 같음,
    기대가 공개면 행도 비어야 함) · 값(`value_matches`)."""
    expected = entry.get("expected_fact") or {}
    if check_key and row_key(row) != expected_key(expected):
        return False
    if row.get("truth_status") != expected.get("truth_status"):
        return False
    if _names(row.get("known_by")) != _names(expected.get("known_by")):
        return False
    return value_matches(row.get("value"), entry)


def _rate(k: int, n: int) -> dict[str, Any]:
    return {"k": k, "n": n, "rate": k / n if n else None, "wilson": wilson_interval(k, n)}


def fact_metrics(
    items: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
    *,
    checkpoint: int | None = None,
    max_chars: int = RENDER_MAX_CHARS,
) -> dict[str, Any]:
    """사실 계층 오프라인 지표. 체크포인트를 주면 그때 읽을 수 있던 행(`available_from_turn` ≤ 체크포인트 + 1)과 그때 심기가
    모두 접힌 항목만 센다.

    항목 단위(기대 사실이 있는 항목, 범주별·전체):
    - `preserved`(사실 보존율): 덧붙은 행 가운데 `row_matches` 인 행이 하나라도 있다.
    - `preservedInRead`: 그 키의 키별 최신 행(읽기가 실제로 내놓는 행)이 `row_matches` 다.
    - `droppedByCap`(분모 = `preservedInRead` 인 항목): 그 최신 행이 렌더 상한에서 잘렸다.
    - 진단: `keyFound`(그 키의 행이 있다), `matchedIgnoringKey`(키만 빼고 맞는 행이 있다 — 키 이름이 갈려 놓친 것).

    행 단위:
    - `duplicateKeyRate`: 같은 스냅샷(같은 추출 호출)에서 같은 키가 두 번 이상 나온 행 / 전체 행.
    - `restatedRate`: 앞 스냅샷에 같은 키·같은 값·같은 진실 상태 행이 이미 있는데 다시 쓴 행 / 전체 행(바뀐 것 없는 재진술).
    - `capDropRate`: 키별 최신 행 가운데 렌더 상한에서 잘린 행 / 키별 최신 행."""
    visible = [
        r
        for r in rows
        if checkpoint is None or r.get("available_from_turn") is None or int(r["available_from_turn"]) <= checkpoint + 1
    ]
    targets = [
        e
        for e in items
        if e.get("expected_fact")
        and (checkpoint is None or checkpoint in (e.get("probeCheckpoints") or {}).get("offline", []))
    ]
    kept, dropped, _ = render(visible, max_chars=max_chars)
    latest = {row_key(r): r for r in kept + dropped}
    dropped_keys = {row_key(r) for r in dropped}
    per_item = []
    for entry in targets:
        key = expected_key(entry["expected_fact"])
        resolved = latest.get(key)
        in_read = resolved is not None and row_matches(resolved, entry)
        per_item.append(
            {
                "item": entry["id"],
                "category": entry.get("category"),
                "split": entry.get("split"),
                "key": key,
                "preserved": any(row_matches(r, entry) for r in visible),
                "preservedInRead": in_read,
                "droppedByCap": in_read and key in dropped_keys,
                "keyFound": resolved is not None,
                "matchedIgnoringKey": any(row_matches(r, entry, check_key=False) for r in visible),
            }
        )

    def summary(members: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        read = [m for m in members if m["preservedInRead"]]
        return {
            "preserved": _rate(sum(1 for m in members if m["preserved"]), len(members)),
            "preservedInRead": _rate(len(read), len(members)),
            "droppedByCap": _rate(sum(1 for m in read if m["droppedByCap"]), len(read)),
            "keyFound": _rate(sum(1 for m in members if m["keyFound"]), len(members)),
            "matchedIgnoringKey": _rate(sum(1 for m in members if m["matchedIgnoringKey"]), len(members)),
        }

    by_category: dict[str, list[Mapping[str, Any]]] = {}
    for m in per_item:
        by_category.setdefault(str(m["category"]), []).append(m)
    seen_in_snapshot: dict[tuple[str, str], int] = {}
    for r in visible:
        pair = (str(r.get("snapshot_id")), row_key(r))
        seen_in_snapshot[pair] = seen_in_snapshot.get(pair, 0) + 1
    duplicates = sum(1 for r in visible if seen_in_snapshot[(str(r.get("snapshot_id")), row_key(r))] > 1)
    restated = 0
    earlier: dict[tuple[str, str, str], set[str]] = {}
    for r in visible:
        sig = (row_key(r), normalize_part(r.get("value")), str(r.get("truth_status")))
        snapshots = earlier.setdefault(sig, set())
        if snapshots - {str(r.get("snapshot_id"))}:
            restated += 1
        snapshots.add(str(r.get("snapshot_id")))
    n_rows = len(visible)
    n_latest = len(kept) + len(dropped)
    return {
        "checkpoint": checkpoint,
        "maxChars": max_chars,
        "rows": n_rows,
        "latestRows": n_latest,
        "duplicateKeyRate": _rate(duplicates, n_rows),
        "restatedRate": _rate(restated, n_rows),
        "capDropRate": _rate(len(dropped), n_latest),
        "overall": summary(per_item),
        "byCategory": {name: summary(members) for name, members in sorted(by_category.items())},
        "items": per_item,
    }
