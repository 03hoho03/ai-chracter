"""요약 스냅샷의 `[관계]` 칸이 얼마나 자주 있고 요약에서 얼마를 차지하는지 — 레인·모델별 집계. DB 는 읽기만 한다.

칸 나누기는 `summary_sections` 와 같다(운영 요약 지시문의 `[지금]`·`[관계]`·`[지난 일]`). 스냅샷 하나마다
- 칸 있음: `[관계]` 머리글이 있다.
- 비어 있지 않음: 그 칸 본문(머리글 뺀, 앞뒤 공백 지운 글)이 한 글자 이상이다.
- 몫: 그 칸 글자 수 / 모든 칸 글자 수의 합(`summary_sections.section_report` 의 `relationRatio`). 본문이 없는 요약은 몫에서 뺀다.
몫은 스냅샷 평균·최소·최대와, 글자 수를 모두 더해 나눈 합산 몫을 함께 낸다. 방마다 커서가 가장 뒤인 스냅샷(그 방이 닿은 가장 긴
대화의 요약)은 따로 센다.

레인은 작품 종류(스토리·캐릭터), 모델은 방의 채팅 모델(`NULL` 은 `default`)이다 — 스냅샷에는 요약을 쓴 모델이 적히지 않아 방이
응답에 쓰는 모델로 묶는다.

측정 DB 들은 템플릿 복제라 같은 스냅샷이 여러 DB 에 있다. 출처(이름 붙인 DB 묶음)를 준 순서로 읽어 (방, 커서 메시지, 요약 글)
이 같은 스냅샷은 처음 나온 출처에서 한 번만 센다. 결과에는 개수·비율만 있고 방 id·요약 글은 없다."""

import hashlib
import statistics
from collections.abc import Sequence
from typing import Any

from memory_eval.summary_sections import NO_HEADER, section_report

SNAPSHOTS_SQL = """
SELECT s.chat_room_id::text AS room, lower(c.type::text) AS lane, coalesce(r.chat_model, 'default') AS model,
       s.cursor_created_at, s.cursor_message_id::text AS cursor_id, s.summary_text
  FROM chat_room_memory_snapshots s
  JOIN chat_rooms r ON r.id = s.chat_room_id
  JOIN contents c ON c.id = r.content_id
 ORDER BY s.chat_room_id, s.cursor_created_at, s.cursor_message_id
"""

RELATION = "관계"
ALL_SOURCES = "*"


async def load_snapshots(connection: Any) -> list[dict[str, Any]]:
    """연결(asyncpg) 하나의 DB 에서 요약 스냅샷 전부를 방·커서 순으로."""
    return [
        {
            "room": row["room"],
            "lane": row["lane"],
            "model": row["model"],
            "cursorCreatedAt": row["cursor_created_at"],
            "cursorId": row["cursor_id"],
            "summary": row["summary_text"],
        }
        for row in await connection.fetch(SNAPSHOTS_SQL)
    ]


def _share_stats(reports: list[dict[str, Any]]) -> dict[str, Any]:
    ratios = [r["relationRatio"] for r in reports if r["relationRatio"] is not None]
    total = sum(r["total"] for r in reports)
    relation = sum(r["sections"].get(RELATION, {}).get("chars", 0) for r in reports)
    return {
        "n": len(ratios),
        "mean": statistics.fmean(ratios) if ratios else None,
        "median": statistics.median(ratios) if ratios else None,
        "min": min(ratios) if ratios else None,
        "max": max(ratios) if ratios else None,
        "pooled": relation / total if total else None,
    }


def _presence(reports: list[dict[str, Any]]) -> dict[str, Any]:
    present = sum(1 for r in reports if RELATION in r["sections"])
    non_empty = sum(1 for r in reports if r["sections"].get(RELATION, {}).get("chars", 0) > 0)
    n = len(reports)
    return {
        "present": present,
        "nonEmpty": non_empty,
        "presentRate": present / n if n else None,
        "nonEmptyRate": non_empty / n if n else None,
        "share": _share_stats(reports),
    }


def _group(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    reports = [section_report(s["summary"]) for s in snapshots]
    last_by_room: dict[str, tuple[Any, dict[str, Any]]] = {}
    for snapshot, report in zip(snapshots, reports, strict=True):
        key = (snapshot["cursorCreatedAt"], snapshot["cursorId"])
        held = last_by_room.get(snapshot["room"])
        if held is None or key > held[0]:
            last_by_room[snapshot["room"]] = (key, report)
    last = [report for _key, report in last_by_room.values()]
    return {
        "snapshots": len(snapshots),
        "rooms": len(last_by_room),
        **_presence(reports),
        "unknownHeaderSnapshots": sum(1 for r in reports if r["unknownHeaders"]),
        "noHeaderSnapshots": sum(1 for r in reports if NO_HEADER in r["sections"]),
        "last": {"rooms": len(last), **_presence(last)},
    }


def relation_share(sources: Sequence[tuple[str, list[dict[str, Any]]]]) -> dict[str, Any]:
    """출처(이름, 스냅샷 목록)들을 준 순서로 합쳐 `출처|레인|모델` 묶음과 출처를 합친 `*|레인|모델` 묶음의 집계."""
    seen: set[tuple[str, str, str]] = set()
    duplicates = 0
    grouped: dict[str, list[dict[str, Any]]] = {}
    for label, snapshots in sources:
        for snapshot in snapshots:
            digest = hashlib.sha256(snapshot["summary"].encode("utf-8")).hexdigest()
            key = (snapshot["room"], snapshot["cursorId"], digest)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            for prefix in (label, ALL_SOURCES):
                grouped.setdefault(f"{prefix}|{snapshot['lane']}|{snapshot['model']}", []).append(snapshot)
    return {
        "sources": [label for label, _snapshots in sources],
        "duplicatesSkipped": duplicates,
        "groups": {name: _group(snapshots) for name, snapshots in sorted(grouped.items())},
    }
