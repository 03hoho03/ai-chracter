"""스탯 판정 리플레이의 오프라인 입력을 만든다 — 원천마다 다른 기록(측정 방 trace, 스토리 가이드 런의 턴 기록, 옛 런의
trace)에서 "그 턴 판정 직전 스탯 값"을 읽고, 원천 DB 에서 스탯 정의·턴 텍스트·이름을 읽어 입력 JSON 하나로 묶는다.
조립은 하지 않는다 — 입력 JSON 을 `judgment_replay.py --input-json` 이 서버 빌더로 조립한다.

두 단계로 나뉜다. DB 는 첫 단계에서만 읽는다.

    # 1. 원천 DB 하나를 읽기 전용으로 읽어 스냅숏 JSON 으로 남긴다(원천마다 한 번, DB 를 하나씩 띄운 동안).
    python extract_stat_inputs.py snapshot --source filmclub --container <컨테이너> --room <id>... --out <run>/inputs/db/filmclub.json
    # 2. 스냅숏과 원천 기록으로 후보 전체 → 시드 추출 → 입력 JSON(DB 접속 없음).
    python extract_stat_inputs.py build --run <run> --filmclub-trace … --filmclub-driver … --storyguide-dir … \\
        --longrun-dir … --tuning-dir …

DB 읽기는 컨테이너 안 psql 로 하고, 세션을 `default_transaction_read_only=on` 으로 연 뒤 `BEGIN READ ONLY … ROLLBACK`
안에서 SELECT 만 한다 — 옛 볼륨을 띄워 읽는 동안 데이터 행이 바뀌지 않게 접속 설정으로 막는다.

원천 기록의 형식이 기대와 다르면(키가 없거나, 이름 키가 스탯 정의와 안 맞거나, 텍스트가 드라이버 기록과 다르면) 추정하지
않고 멈춘다 — 다른 턴의 값이나 다른 문장이 섞이면 재구성 프롬프트가 실제 판정과 달라진다.
"""

import argparse
import json
import random
import subprocess
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SEED = 20261006
GROUP_SIZES = {"E1": 6, "E2": 6, "N1": 2, "N2": 8}
LIKING = ("도희 호감도", "유나 호감도", "세빈 호감도")
GAP = 15.0
CLUSTER = 5.0
FILMCLUB_ROOM = "6787bb78-c54d-4c65-966c-024e1dff0c74"
FILMCLUB_SPARE_ROOM = "c3a19d00-e53e-4cfa-a377-ff100d3660e9"
USED_TURNS = (13, 25)  # 앞선 형식 비교에 이미 쓴 턴 — 닻으로만 쓴다
N2_WORKS = ("wuxia", "comedy", "healing", "horror", "mystery")
# 스키마에 없으면 서버 기본값으로 읽는다(`StatDef` 주석: 없는 옵션은 양방향·제한 없음).
OPTIONAL_STAT_COLUMNS = {"change_direction": "both", "max_change_per_turn": None, "per_turn_delta": None}


class SourceFormatError(Exception):
    """원천 기록이 기대한 형식이 아니다 — 멈춘다."""


# ── DB 스냅숏 ────────────────────────────────────────────────────────────────


def readonly_query(container: str, sql: str) -> str:
    """컨테이너 안 psql 로 읽기 전용 세션을 열어 SQL 한 문장의 결과(한 칸)를 돌려준다. 세션 기본값과 트랜잭션 양쪽에서
    읽기 전용을 걸고, 트랜잭션 안에서 읽기 전용이 실제로 켜졌는지 함께 확인한다."""
    script = f"BEGIN READ ONLY;\nSHOW transaction_read_only;\n{sql};\nROLLBACK;\n"
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "-e",
            "PGOPTIONS=-c default_transaction_read_only=on",
            container,
            "psql",
            "-U",
            "postgres",
            "-d",
            "ai_character_chat",
            "-X",
            "-q",
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input=script,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql 실패(rc={result.returncode}): {result.stderr.strip()[:500]}")
    lines = result.stdout.split("\n", 1)
    if lines[0] != "on":
        raise RuntimeError(f"읽기 전용 트랜잭션이 아니다: {lines[0]!r}")
    return lines[1].rstrip("\n") if len(lines) > 1 else ""


def _columns(container: str, table: str) -> set[str]:
    out = readonly_query(
        container,
        "SELECT coalesce(json_agg(column_name), '[]'::json) FROM information_schema.columns "
        f"WHERE table_schema = 'public' AND table_name = '{table}'",
    )
    return set(json.loads(out))


def snapshot_room(
    container: str, room_id: str, stat_columns: set[str], has_default_name: bool, has_persona: bool
) -> dict[str, Any]:
    """방 한 개: 고정 버전·시작설정·작품 이름·프로필 이름·작품 기본 이름, 스탯 정의(서버와 같은 질의 순서), 메시지 전부."""
    room_id = str(uuid.UUID(room_id))  # 형식 검사 — SQL 에 그대로 넣는 값이다
    default_name = "svd.default_user_name" if has_default_name else "NULL"
    # 옛 스키마(프로필 기능 전)에는 프로필 테이블·방의 프로필 컬럼이 없다 — 그때는 프로필 없음으로 읽는다.
    persona_cols = (
        "'personaId', r.persona_id, 'personaName', p.name,"
        if has_persona
        else "'personaId', NULL, 'personaName', NULL,"
    )
    persona_join = "LEFT JOIN user_personas p ON p.id = r.persona_id " if has_persona else ""
    room = json.loads(
        readonly_query(
            container,
            "SELECT json_build_object("
            "'roomId', r.id, 'contentId', r.content_id, 'contentVersionId', r.content_version_id,"
            "'startingSetupEntityId', r.starting_setup_entity_id, 'turnCount', r.turn_count,"
            f"{persona_cols} 'storyName', svd.name,"
            f"'defaultUserName', {default_name}, 'setupId', s.id, 'setupName', s.name) "
            "FROM chat_rooms r "
            f"{persona_join}"
            "LEFT JOIN story_version_details svd ON svd.content_version_id = r.content_version_id "
            "LEFT JOIN starting_setups s ON s.content_version_id = r.content_version_id "
            "AND s.entity_id = r.starting_setup_entity_id "
            f"WHERE r.id = '{room_id}'",
        )
        or "null"
    )
    if room is None:
        raise SourceFormatError(f"{container}: 방이 없다 {room_id}")
    if room["setupId"] is None:
        raise SourceFormatError(f"{container}: 방 {room_id} 의 시작설정을 고정 버전에서 찾지 못했다")
    wanted = [
        "entity_id", "name", "description", "min_value", "max_value", "initial_value", "per_turn_delta",
        "change_direction", "max_change_per_turn", "order",
    ]  # fmt: skip
    present = [c for c in wanted if c in stat_columns]
    # 서버 `_load_room_stats` 와 같은 모양의 질의(ORDER BY 없음) — 그 결과 순서가 서버 스탯 줄 순서다.
    select_list = ", ".join(f'"{c}"' for c in present) + ", ctid::text AS ctid"
    stat_rows = json.loads(
        readonly_query(
            container,
            "SELECT coalesce(json_agg(row_to_json(t)), '[]'::json) FROM ("
            f"SELECT {select_list} FROM stat_defs WHERE starting_setup_id = '{room['setupId']}') t",
        )
    )
    messages = json.loads(
        readonly_query(
            container,
            "SELECT coalesce(json_agg(json_build_object('id', id, 'role', role, 'content', content, "
            "'createdAt', created_at) ORDER BY created_at, id), '[]'::json) "
            f"FROM chat_messages WHERE chat_room_id = '{room_id}'",
        )
    )
    return {
        "room": room,
        "statDefs": stat_rows,
        "absentStatColumns": sorted(set(wanted) - stat_columns),
        "messages": messages,
    }


def snapshot(source: str, container: str, room_ids: list[str]) -> dict[str, Any]:
    stat_columns = _columns(container, "stat_defs")
    has_default_name = "default_user_name" in _columns(container, "story_version_details")
    has_persona = "persona_id" in _columns(container, "chat_rooms") and bool(_columns(container, "user_personas"))
    alembic = readonly_query(container, "SELECT coalesce(json_agg(version_num), '[]'::json) FROM alembic_version")
    return {
        "source": source,
        "container": container,
        "alembic": json.loads(alembic),
        "hasDefaultUserNameColumn": has_default_name,
        "hasPersona": has_persona,
        "rooms": {rid: snapshot_room(container, rid, stat_columns, has_default_name, has_persona) for rid in room_ids},
    }


# ── 원천 기록 ────────────────────────────────────────────────────────────────


@dataclass
class TurnRecord:
    """한 원천의 한 판정 턴. `start_by_id` 는 스냅숏의 스탯 정의로 entity_id 키를 맞춘 뒤 채운다."""

    source: str
    room_id: str
    turn: int
    start_path: str
    start_line: int
    start_raw: dict[str, float]
    start_key: str  # "id" | "name"
    round: str | None = None
    driver_user_text: str | None = None
    driver_reply: str | None = None
    driver_path: str | None = None
    driver_line: int | None = None
    start_by_id: dict[str, float] = field(default_factory=dict)


def _jsonl(path: Path) -> list[tuple[int, dict[str, Any]]]:
    return [
        (n, json.loads(line)) for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if line.strip()
    ]


def read_stat_outcome_starts(path: Path, source: str) -> list[TurnRecord]:
    """측정 방 trace(`stats[].start`) 또는 옛 런 trace(`before`)의 `stat_outcome` — 방·턴마다 정확히 하나여야 한다."""
    records: list[TurnRecord] = []
    seen: set[tuple[str, int]] = set()
    for n, r in _jsonl(path):
        if r.get("kind") != "stat_outcome":
            continue
        key = (str(r["roomId"]), int(r["turn"]))
        if key in seen:
            raise SourceFormatError(f"{path}:{n}: 방 {key[0]} 턴 {key[1]} 의 stat_outcome 이 둘 이상")
        seen.add(key)
        if source == "filmclub":
            if "stats" not in r or any("start" not in s for s in r["stats"]):
                raise SourceFormatError(f"{path}:{n}: stats[].start 가 없다")
            raw = {str(s["statId"]): float(s["start"]) for s in r["stats"]}
        else:
            if not isinstance(r.get("before"), dict):
                raise SourceFormatError(f"{path}:{n}: before 가 없다")
            raw = {str(k): float(v) for k, v in r["before"].items()}
        records.append(TurnRecord(source, key[0], key[1], str(path), n, raw, "id"))
    return records


def read_storyguide_turns(root: Path) -> list[TurnRecord]:
    """스토리 가이드 런 `r*/<드라이버>/turns.jsonl` — 이번 턴 시작값은 직전 줄(opening 또는 직전 턴)의 `roomAfter.stats`
    (스탯 이름 키). 응답 실패·턴 수가 1 늘지 않은 줄·엔딩 뒤 턴은 판정이 없었거나 짝이 맞지 않아 뺀다."""
    records: list[TurnRecord] = []
    for path in sorted(root.glob("r*/*/turns.jsonl")):
        lines = _jsonl(path)
        if not lines or lines[0][1].get("kind") != "meta":
            raise SourceFormatError(f"{path}: 첫 줄이 meta 가 아니다")
        room_id = str(lines[0][1]["roomId"])
        prev: tuple[int, dict[str, Any]] | None = None
        for n, r in lines[1:]:
            kind = r.get("kind")
            if kind not in ("opening", "turn"):
                continue
            after = r.get("roomAfter")
            if kind == "turn" and prev is not None and r.get("http") == 200 and isinstance(after, dict):
                prev_after = prev[1]["roomAfter"]
                if after["turnCount"] == prev_after["turnCount"] + 1 and not prev_after.get("endingReached"):
                    records.append(
                        TurnRecord(
                            "storyguide",
                            room_id,
                            int(after["turnCount"]),
                            str(path),
                            prev[0],
                            {str(k): float(v) for k, v in prev_after["stats"].items()},
                            "name",
                            round=path.parent.parent.name,
                            driver_user_text=r["userText"],
                            driver_reply=r.get("reply"),
                            driver_path=str(path),
                            driver_line=n,
                        )
                    )
            if isinstance(after, dict) and "stats" in after:
                prev = (n, r)
    return records


def attach_driver(records: list[TurnRecord], driver_paths: list[Path]) -> None:
    """드라이버 jsonl(`turn` 줄, http 200)의 사용자 문장을 같은 방·턴 기록에 붙인다 — 텍스트 대조용."""
    by_key: dict[tuple[str, int], tuple[str, int, str, str | None]] = {}
    for path in driver_paths:
        lines = _jsonl(path)
        room_id = next((str(r["roomId"]) for _, r in lines if r.get("kind") == "meta"), None)
        for n, r in lines:
            if r.get("kind") != "turn" or r.get("http") != 200:
                continue
            rid = str(r.get("roomId") or room_id)
            after = r.get("roomAfter")
            if isinstance(after, dict) and "turnCount" in after:
                turn = int(after["turnCount"])
            elif "turnBefore" in r:
                turn = int(r["turnBefore"]) + 1
            else:
                continue
            by_key[(rid, turn)] = (str(path), n, r["userText"], r.get("reply"))
    for rec in records:
        hit = by_key.get((rec.room_id, rec.turn))
        if hit is not None:
            rec.driver_path, rec.driver_line, rec.driver_user_text, rec.driver_reply = hit


# ── 스냅숏과 맞추기 ─────────────────────────────────────────────────────────


def turn_pairs(messages: list[dict[str, Any]]) -> list[int]:
    """서버 리플레이와 같은 규칙: 바로 뒤가 응답인 사용자 메시지만 턴(N 번째 쌍 = 턴 N)."""
    return [
        i for i in range(len(messages) - 1) if messages[i]["role"] == "USER" and messages[i + 1]["role"] == "ASSISTANT"
    ]


def stat_defs_of(room_snap: dict[str, Any]) -> list[dict[str, Any]]:
    """스냅숏 스탯 행을 입력 파일 형식으로 — 없는 옵션 컬럼은 서버 기본값, 서버 질의 순서는 `serverIndex`."""
    defs = []
    for index, row in enumerate(room_snap["statDefs"]):
        item = {key: row.get(key, default) for key, default in OPTIONAL_STAT_COLUMNS.items()}
        item.update(
            {
                "entity_id": str(row["entity_id"]),
                "name": row["name"],
                "description": row["description"],
                "min_value": int(row["min_value"]),
                "max_value": int(row["max_value"]),
                "initial_value": int(row["initial_value"]),
                "order": row.get("order"),
                "serverIndex": index,
                "ctid": row.get("ctid"),
            }
        )
        defs.append(item)
    return defs


def resolve_start(rec: TurnRecord, defs: list[dict[str, Any]]) -> None:
    """시작값을 entity_id 키로 맞춘다. 키 집합이 스탯 정의와 정확히 같아야 한다(빠지거나 남으면 멈춘다)."""
    if rec.start_key == "id":
        ids = {d["entity_id"] for d in defs}
        if set(rec.start_raw) != ids:
            raise SourceFormatError(f"{rec.start_path}:{rec.start_line}: 시작값 statId 가 스탯 정의와 다르다")
        rec.start_by_id = dict(rec.start_raw)
        return
    by_name = {d["name"]: d["entity_id"] for d in defs}
    if len(by_name) != len(defs) or set(rec.start_raw) != set(by_name):
        raise SourceFormatError(f"{rec.start_path}:{rec.start_line}: 시작값 이름 키가 스탯 정의 이름과 다르다")
    rec.start_by_id = {by_name[name]: value for name, value in rec.start_raw.items()}


def liking_ids(defs: list[dict[str, Any]]) -> dict[str, str] | None:
    """호감 3종 이름 → entity_id. 셋 다 없으면 None, 일부만 있거나 범위·종류가 다르면 멈춘다."""
    found = {d["name"]: d for d in defs if d["name"] in LIKING}
    if not found:
        return None
    if len(found) != 3:
        raise SourceFormatError(f"호감 스탯이 {sorted(found)} 뿐이다")
    ranges = {(d["min_value"], d["max_value"]) for d in found.values()}
    if len(ranges) != 1 or any(d["per_turn_delta"] is not None for d in found.values()):
        raise SourceFormatError("호감 3종의 범위가 다르거나 카운터가 섞였다")
    return {name: found[name]["entity_id"] for name in LIKING}


def s_star(start: dict[str, float], ids: dict[str, str]) -> list[dict[str, str]]:
    """선두(나머지 둘 각각보다 GAP 이상 큼)·후미(각각보다 GAP 이상 작음) 스탯."""
    out = []
    for name, sid in ids.items():
        others = [start[o] for n, o in ids.items() if n != name]
        if all(start[sid] - v >= GAP for v in others):
            out.append({"name": name, "side": "lead"})
        elif all(v - start[sid] >= GAP for v in others):
            out.append({"name": name, "side": "trail"})
    return out


def person(stat_name: str) -> str:
    return stat_name.split(" ", 1)[0]


# ── 후보·추출 ────────────────────────────────────────────────────────────────


def _sort_key(c: dict[str, Any]) -> tuple[str, str, int]:
    return (c["source"], c["roomId"], c["turn"])


def _draw(rng: random.Random, items: list[Any], k: int) -> list[Any]:
    return rng.sample(items, min(k, len(items)))


def draw_e1(rng: random.Random, cands: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    strata: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in sorted(cands, key=_sort_key):
        strata[c["stratum"]].append(c)
    need = GROUP_SIZES["E1"]
    chosen: list[dict[str, Any]] = []
    log: list[dict[str, Any]] = []
    while need > 0:
        live = sorted(name for name, items in strata.items() if items)
        if not live:
            break
        alloc = {name: need // len(live) for name in live}
        for name in rng.sample(live, need % len(live)):
            alloc[name] += 1
        for name in live:
            take = _draw(rng, strata[name], alloc[name])
            log.append({"stratum": name, "allocated": alloc[name], "available": len(strata[name]), "taken": len(take)})
            chosen.extend(take)
            strata[name] = [c for c in strata[name] if c not in take]
        need = GROUP_SIZES["E1"] - len(chosen)
    return chosen, {"rounds": log, "short": GROUP_SIZES["E1"] - len(chosen)}


def draw_e2(rng: random.Random, cands: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    log: dict[str, Any] = {}
    for stratum in sorted(person(name) for name in LIKING):  # 층 이름 오름차순
        items = sorted((c for c in cands if c["stratum"] == stratum), key=_sort_key)
        rounds = sorted({c["round"] for c in items})
        if len(rounds) >= 2:
            picked_rounds = sorted(rng.sample(rounds, 2))
            take = [rng.sample([c for c in items if c["round"] == r], 1)[0] for r in picked_rounds]
        else:
            picked_rounds = rounds
            take = _draw(rng, items, 2)
        log[stratum] = {
            "available": len(items),
            "byRound": {r: sum(c["round"] == r for c in items) for r in rounds},
            "pickedRounds": picked_rounds,
            "taken": len(take),
            "short": 2 - len(take),
        }
        chosen.extend(take)
    return chosen, log


def draw_n2(rng: random.Random, cands: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    works = sorted({c["work"] for c in cands})
    picked = sorted(_draw(rng, works, 4))
    chosen: list[dict[str, Any]] = []
    log: dict[str, Any] = {"works": {w: sum(c["work"] == w for c in cands) for w in works}, "pickedWorks": picked}
    for work in picked:
        items = sorted((c for c in cands if c["work"] == work), key=_sort_key)
        chosen.extend(_draw(rng, items, 2))
    log["short"] = GROUP_SIZES["N2"] - len(chosen)
    return chosen, log


# ── 입력 파일 ────────────────────────────────────────────────────────────────


def build_input(
    rec: TurnRecord, snap: dict[str, Any], snap_path: str, group: str, extra: dict[str, Any]
) -> dict[str, Any]:
    room_snap = snap["rooms"][rec.room_id]
    room = room_snap["room"]
    defs = stat_defs_of(room_snap)
    messages = room_snap["messages"]
    pairs = turn_pairs(messages)
    if not 1 <= rec.turn <= len(pairs):
        raise SourceFormatError(f"{rec.room_id} 턴 {rec.turn} 이 DB 에 없다(완결 턴 {len(pairs)}개)")
    user, assistant = messages[pairs[rec.turn - 1]], messages[pairs[rec.turn - 1] + 1]
    if rec.driver_user_text is not None and rec.driver_user_text != user["content"]:
        raise SourceFormatError(f"{rec.room_id} 턴 {rec.turn}: DB 사용자 메시지가 드라이버 기록과 다르다")
    persona_name = room["personaName"]
    default_user_name = room["defaultUserName"] or ""
    if rec.source != "filmclub":
        persona_name = None  # 다른 원천은 프로필 없음 + 작품 기본 이름(있으면)으로 고정한다
    input_id = f"{group}-{rec.source}-{rec.room_id[:8]}-t{rec.turn:03d}"
    return {
        "inputId": input_id,
        "group": group,
        "source": rec.source,
        "round": rec.round,
        "roomId": rec.room_id,
        "turn": rec.turn,
        "work": {
            "contentId": room["contentId"],
            "contentVersionId": room["contentVersionId"],
            "storyName": room["storyName"],
            "setupId": room["setupId"],
            "setupName": room["setupName"],
            **({"slug": extra["slug"]} if extra.get("slug") else {}),
        },
        "statDefs": defs,
        "absentStatColumns": room_snap["absentStatColumns"],
        "statStart": {d["entity_id"]: rec.start_by_id[d["entity_id"]] for d in defs},
        "sStar": extra.get("sStar", []),
        "userMessage": user["content"],
        "assistantMessage": assistant["content"],
        "names": {
            "personaName": persona_name,
            "defaultUserName": default_user_name,
            "userNameLine": persona_name or default_user_name,
            "rule": "측정 방 실제 값(프로필·작품 기본 이름)"
            if rec.source == "filmclub"
            else "프로필 없음 + 작품 기본 이름(없으면 빈 값 → 이름 한 줄 섹션 빠짐)",
            "roomPersonaName": room["personaName"],
        },
        "provenance": {
            "start": {"path": rec.start_path, "line": rec.start_line, "key": rec.start_key, "raw": rec.start_raw},
            "db": {
                "snapshot": snap_path,
                "container": snap["container"],
                "alembic": snap["alembic"],
                "userMessageId": user["id"],
                "assistantMessageId": assistant["id"],
            },
            "driver": {
                "path": rec.driver_path,
                "line": rec.driver_line,
                "userTextMatchesDb": None if rec.driver_user_text is None else rec.driver_user_text == user["content"],
                "replyMatchesDb": None if rec.driver_reply is None else rec.driver_reply == assistant["content"],
            },
        },
    }


def build(args: argparse.Namespace) -> int:
    run = Path(args.run)
    db_dir = run / "inputs" / "db"
    snaps = {
        s: json.loads((db_dir / f"{s}.json").read_text(encoding="utf-8"))
        for s in ("filmclub", "storyguide", "longrun", "tuning")
    }
    snap_paths = {s: str(db_dir / f"{s}.json") for s in snaps}

    film = read_stat_outcome_starts(Path(args.filmclub_trace), "filmclub")
    attach_driver(film, [Path(args.filmclub_driver)])
    guide = read_storyguide_turns(Path(args.storyguide_dir))
    longrun = read_stat_outcome_starts(Path(args.longrun_dir) / "trace.jsonl", "longrun")
    attach_driver(longrun, sorted(Path(args.longrun_dir).glob("*-s0.jsonl")))
    tuning = read_stat_outcome_starts(Path(args.tuning_dir) / "trace.jsonl", "tuning")
    attach_driver(tuning, sorted(Path(args.tuning_dir).glob("R*/*-s0.jsonl")))

    slug_by_content: dict[str, str] = {}
    for path in [*Path(args.longrun_dir).glob("*.jsonl"), *Path(args.tuning_dir).glob("R*/*.jsonl")]:
        for _, r in _jsonl(path):
            if r.get("kind") == "meta" and r.get("slug"):
                slug_by_content[str(r["contentId"])] = str(r["slug"])

    candidates: list[dict[str, Any]] = []
    records: dict[tuple[str, str, int], TurnRecord] = {}
    for rec in [*film, *guide, *longrun, *tuning]:
        if rec.room_id not in snaps[rec.source]["rooms"]:
            raise SourceFormatError(f"{rec.source} 스냅숏에 방 {rec.room_id} 가 없다")
        room_snap = snaps[rec.source]["rooms"][rec.room_id]
        defs = stat_defs_of(room_snap)
        resolve_start(rec, defs)
        records[(rec.source, rec.room_id, rec.turn)] = rec
        base = {
            "source": rec.source,
            "roomId": rec.room_id,
            "turn": rec.turn,
            "round": rec.round,
            "startLine": rec.start_line,
            "start": rec.start_by_id,
        }
        ids = liking_ids(defs)
        if rec.source == "filmclub":
            assert ids is not None
            if rec.turn in USED_TURNS:
                continue
            liking = {n: rec.start_by_id[i] for n, i in ids.items()}
            stars = s_star(rec.start_by_id, ids)
            if stars:
                lead = [s for s in stars if s["side"] == "lead"]
                candidates.append(
                    base
                    | {"group": "E1", "sStar": stars, "stratum": person((lead or stars)[0]["name"]), "liking": liking}
                )
            if max(liking.values()) - min(liking.values()) <= CLUSTER:
                candidates.append(base | {"group": "N1", "liking": liking})
        elif rec.source == "storyguide":
            assert ids is not None
            stars = s_star(rec.start_by_id, ids)
            if stars:
                lead = [s for s in stars if s["side"] == "lead"]
                liking = {n: rec.start_by_id[i] for n, i in ids.items()}
                candidates.append(
                    base
                    | {"group": "E2", "sStar": stars, "stratum": person((lead or stars)[0]["name"]), "liking": liking}
                )
        else:
            judged = [d for d in defs if d["per_turn_delta"] is None]
            content_id = str(room_snap["room"]["contentId"])
            slug = slug_by_content.get(content_id)
            work = next((w for w in N2_WORKS if slug and slug.startswith(w)), None)
            if work is None:
                raise SourceFormatError(f"{rec.source} 방 {rec.room_id}: 작품 slug 를 찾지 못했다({slug})")
            if len(judged) >= 2:
                candidates.append(base | {"group": "N2", "work": work, "slug": slug, "judgedStats": len(judged)})

    e1_rooms = {FILMCLUB_ROOM}
    e1 = [c for c in candidates if c["group"] == "E1" and c["roomId"] in e1_rooms]
    if len(e1) < GROUP_SIZES["E1"]:
        e1 += [c for c in candidates if c["group"] == "E1" and c["roomId"] == FILMCLUB_SPARE_ROOM]
    n1 = [c for c in candidates if c["group"] == "N1" and c["roomId"] == FILMCLUB_ROOM]
    e2 = [c for c in candidates if c["group"] == "E2"]
    n2 = [c for c in candidates if c["group"] == "N2"]

    candidates.sort(key=lambda c: (c["group"], *_sort_key(c)))
    (run / "inputs" / "candidates.jsonl").write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in candidates), encoding="utf-8"
    )

    rng = random.Random(SEED)
    picks: dict[str, list[dict[str, Any]]] = {}
    logs: dict[str, Any] = {}
    picks["E1"], logs["E1"] = draw_e1(rng, e1)
    picks["E2"], logs["E2"] = draw_e2(rng, e2)
    picks["N1"] = _draw(rng, sorted(n1, key=_sort_key), GROUP_SIZES["N1"])
    logs["N1"] = {"available": len(n1), "short": GROUP_SIZES["N1"] - len(picks["N1"])}
    picks["N2"], logs["N2"] = draw_n2(rng, n2)

    out_dir = run / "inputs"
    written = []
    for group in ("E1", "E2", "N1", "N2"):
        for c in sorted(picks[group], key=_sort_key):
            rec = records[(c["source"], c["roomId"], c["turn"])]
            data = build_input(rec, snaps[rec.source], snap_paths[rec.source], group, c)
            path = out_dir / f"{data['inputId']}.json"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            written.append(str(path))
    for turn in USED_TURNS:
        rec = records[("filmclub", FILMCLUB_ROOM, turn)]
        data = build_input(rec, snaps["filmclub"], snap_paths["filmclub"], "anchor", {})
        data["inputId"] = f"anchor-filmclub-{FILMCLUB_ROOM[:8]}-t{turn:03d}"
        (out_dir / f"{data['inputId']}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    summary = {
        "seed": SEED,
        "candidateCounts": {"E1": len(e1), "E2": len(e2), "N1": len(n1), "N2": len(n2)},
        "draws": {
            g: [f"{c['source']}/{c['roomId'][:8]}/t{c['turn']:03d}" for c in sorted(p, key=_sort_key)]
            for g, p in picks.items()
        },
        "logs": logs,
        "written": written,
    }
    (out_dir / "selection-result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: summary[k] for k in ("candidateCounts", "draws", "logs")}, ensure_ascii=False, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--source", required=True, choices=["filmclub", "storyguide", "longrun", "tuning"])
    s.add_argument("--container", required=True)
    s.add_argument("--room", action="append", required=True)
    s.add_argument("--out", required=True)
    b = sub.add_parser("build")
    b.add_argument("--run", required=True)
    b.add_argument("--filmclub-trace", required=True)
    b.add_argument("--filmclub-driver", required=True)
    b.add_argument("--storyguide-dir", required=True)
    b.add_argument("--longrun-dir", required=True)
    b.add_argument("--tuning-dir", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "snapshot":
        data = snapshot(args.source, args.container, args.room)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{args.source}: 방 {len(data['rooms'])}개, alembic {data['alembic']}, 없는 스탯 컬럼 "
              f"{sorted({c for r in data['rooms'].values() for c in r['absentStatColumns']})}")  # fmt: skip
        return 0
    return build(args)


if __name__ == "__main__":
    sys.exit(main())
