"""격리 DB 에서 복제 v5 와 v6-fix 의 행을 필드 단위로 비교하고, 기준 story 세트와 새 세트를 섹션 단위로 비교한다.

버전 행끼리는 `entity_id` 로 짝짓는다(복제가 물리 id 를 새로 만들기 때문). 물리 id 와 버전 FK 는 비교에서 빼고,
부모를 가리키는 물리 FK(시작설정·엔딩·규칙 그룹)는 부모의 entity_id 로 바꿔 비교한다 — 행이 엉뚱한 부모로
옮겨 가도 잡히게 하려는 것. 나온 차이는 확정 문안에서 계산한 기대 차이와 대조해, 기대 밖 차이·빠진 기대가
하나라도 있으면 종료 코드 1.

사용: python diff_v6_fix.py <v6-fix id> <새 story 세트 id>  (출력은 사람이 읽는 diff + 판정)
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import v6_fix_texts as T

CONTAINER = "ai-character-chat-wt-filmclub-longturn-postgres-1"
PSQL = ["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", "ai_character_chat", "-X", "-At"]

SETUPS = "SELECT id FROM starting_setups WHERE content_version_id = '{v}'"
ENDINGS = f"SELECT id FROM endings WHERE starting_setup_id IN ({SETUPS})"
GROUPS = f"SELECT id FROM ending_rule_groups WHERE ending_id IN ({ENDINGS})"
FILTERS = {
    "content_versions": "id = '{v}'",
    "story_version_details": "content_version_id = '{v}'",
    "starting_setups": "content_version_id = '{v}'",
    "stat_defs": f"starting_setup_id IN ({SETUPS})",
    "endings": f"starting_setup_id IN ({SETUPS})",
    "ending_rule_groups": f"ending_id IN ({ENDINGS})",
    "ending_rules": f"ending_id IN ({ENDINGS}) OR rule_group_id IN ({GROUPS})",
    "situation_notes": f"starting_setup_id IN ({SETUPS})",
    "keyword_notes": "content_version_id = '{v}'",
    "shortcuts": "content_version_id = '{v}'",
    "media_book_people": "content_version_id = '{v}'",
    "media_book_scenes": "content_version_id = '{v}'",
    "media_book_cells": "content_version_id = '{v}'",
}
# 부모 물리 FK → 부모 테이블(비교 때 부모 entity_id 로 바꾼다)
PARENT_FK = {"starting_setup_id": "starting_setups", "ending_id": "endings", "rule_group_id": "ending_rule_groups"}
DROP = {"id", "content_version_id"}


def query(sql: str) -> Any:
    out = subprocess.run(PSQL, input=sql, capture_output=True, text=True, check=True).stdout.strip()
    return json.loads(out) if out else []


def load_version(v: str) -> dict[str, list[dict[str, Any]]]:
    return {
        t: query(f"SELECT coalesce(json_agg(to_jsonb(x)), '[]') FROM {t} x WHERE {f.format(v=v)};")
        for t, f in FILTERS.items()
    }


def keyed(rows: dict[str, list[dict[str, Any]]]) -> dict[tuple[str, str], dict[str, Any]]:
    entity_of = {t: {r["id"]: r["entity_id"] for r in rows[t]} for t in PARENT_FK.values()}
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for table, table_rows in rows.items():
        for r in table_rows:
            key = r.get("entity_id") or "-"
            norm = {}
            for col, val in r.items():
                if col in DROP:
                    continue
                if col in PARENT_FK:
                    norm[col + "→entity"] = entity_of[PARENT_FK[col]].get(val) if val else None
                else:
                    norm[col] = val
            if table == "content_versions":
                key = "-"
            if (table, key) in result:
                raise SystemExit(f"{table} entity_id {key} 가 두 번 나온다")
            result[(table, key)] = norm
    return result


def expected_changes(v5: dict[tuple[str, str], dict[str, Any]]) -> dict[tuple[str, str, str], Any]:
    """(테이블, entity_id, 열) → v6-fix 에서 기대하는 값. v5 값에서 확정 문안으로 계산한다."""
    exp: dict[tuple[str, str, str], Any] = {}
    svd = v5[("story_version_details", "-")]
    exp[("story_version_details", "-", "setting_text")] = T.replace_once(
        svd["setting_text"], T.SETTING_OLD, T.SETTING_NEW, "설정"
    )
    assert v5[("stat_defs", T.COUNTDOWN_STAT)]["description"] == T.COUNTDOWN_DESC_OLD
    exp[("stat_defs", T.COUNTDOWN_STAT, "description")] = T.COUNTDOWN_DESC_NEW
    for note_id, changes in T.STAGE_RULE_CHANGES.items():
        rules = json.loads(json.dumps(v5[("situation_notes", note_id)]["condition_rules"]))
        for rule_id, old_op, old_th, new_op, new_th in changes:
            (rule,) = [r for r in rules if r["id"] == rule_id]
            assert (rule["operator"], rule["threshold"]) == (old_op, old_th)
            rule["operator"], rule["threshold"] = new_op, new_th
        exp[("situation_notes", note_id, "condition_rules")] = rules
    assert v5[("situation_notes", T.NOTE_EARLY)]["info_text"] == T.EARLY_INFO_OLD
    exp[("situation_notes", T.NOTE_EARLY, "info_text")] = T.EARLY_INFO_NEW
    assert v5[("situation_notes", T.NOTE_DAY)]["info_text"] == T.DAY_INFO_OLD
    exp[("situation_notes", T.NOTE_DAY, "info_text")] = T.DAY_INFO_NEW
    for rule_entity in T.ROUTE_ENDINGS.values():
        exp[("ending_rules", rule_entity, "order")] = 1
    exp[("ending_rules", T.ALL_CREW_KEEP_RULE, "next_op")] = None
    for note_id, (old_s, new_s) in T.KEYWORD_CHANGES.items():
        exp[("keyword_notes", note_id, "info_text")] = T.replace_once(
            v5[("keyword_notes", note_id)]["info_text"], old_s, new_s, "키워드 노트"
        )
    exp[("content_versions", "-", "version_number")] = 6
    return exp


def show(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v


def main() -> None:
    v6_id, new_set_id = sys.argv[1], sys.argv[2]
    v5 = keyed(load_version(T.REPLICA_V5_ID))
    v6 = keyed(load_version(v6_id))
    exp = expected_changes(v5)
    # 새 버전 행이라 당연히 다른 열(값 대조 대신 존재만 본다)
    inherent = {("content_versions", "-", "published_at"), ("content_versions", "-", "created_at")}
    bad: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    lines: list[str] = []

    print("## 버전 diff (복제 v5 → v6-fix)\n")
    print(f"행 수: v5 {len(v5)} / v6-fix {len(v6)}\n")
    for key in sorted(set(v5) | set(v6)):
        table, ent = key
        if key not in v6:
            lines.append(f"- 삭제 {table} {ent}: {show(v5[key])}")
            if not (table == "ending_rules" and ent in T.ALL_CREW_DROP_RULES):
                bad.append(f"기대 밖 삭제 {table} {ent}")
            continue
        if key not in v5:
            row = v6[key]
            lines.append(f"- 추가 {table} {ent}: {show(row)}")
            route_rule_entities = {v5[("ending_rules", e)]["ending_id→entity"] for e in T.ROUTE_ENDINGS.values()}
            ok = (
                table == "ending_rules"
                and row["ending_id→entity"] in route_rule_entities
                and row["rule_group_id→entity"] is None
                and row["stat_def_entity_id"] == T.COUNTDOWN_STAT
                and row["operator"] == "LTE"
                and json.dumps(row["threshold"]) == "0.0"  # 기존 행과 같은 numeric 표기
                and row["next_op"] == "AND"
                and row["order"] == 0
            )
            if not ok:
                bad.append(f"기대 밖 추가 {table} {ent}")
            continue
        a, b = v5[key], v6[key]
        for col in sorted(set(a) | set(b)):
            if a.get(col) == b.get(col):
                continue
            ck = (table, ent, col)
            seen.add(ck)
            if ck in inherent:
                lines.append(f"- {table} {ent} .{col}: (새 버전 행) {show(a.get(col))} → {show(b.get(col))}")
                continue
            lines.append(f"- {table} {ent} .{col}:\n  - 전: {show(a.get(col))}\n  - 후: {show(b.get(col))}")
            if ck not in exp:
                bad.append(f"기대 밖 변경 {ck}")
            elif exp[ck] != b.get(col):
                bad.append(f"값이 확정본과 다름 {ck}")
    added = sum(1 for k in v6 if k not in v5)
    removed = sum(1 for k in v5 if k not in v6)
    for ck in exp:
        if ck not in seen:
            bad.append(f"기대한 변경이 없음 {ck}")
    if added != 3:
        bad.append(f"추가 행이 {added}개(기대 3)")
    if removed != 3:
        bad.append(f"삭제 행이 {removed}개(기대 3)")
    print("\n".join(lines))
    print(
        f"\n변경 칸 {len(seen) - len(inherent & seen)} (새 버전 행 열 {len(inherent & seen)} 별도) / 추가 {added} / 삭제 {removed}"
    )

    print("\n## 세트 diff (기준 story 세트 → 새 세트)\n")
    sec_sql = (
        "SELECT coalesce(json_agg(json_build_object('k', concat_ws('|', channel, scope, slot, variant), "
        "'body', body, 'order', \"order\", 'conditional', conditional)), '[]') FROM prompt_sections "
        "WHERE prompt_set_id = '{s}';"
    )
    base = {r["k"]: r for r in query(sec_sql.format(s=T.BASE_STORY_SET_ID))}
    new = {r["k"]: r for r in query(sec_sql.format(s=new_set_id))}
    hdr_sql = (
        "SELECT to_jsonb(p) - 'id' - 'version' - 'note' - 'published_at' - 'created_at' FROM prompt_sets p "
        "WHERE id = '{s}';"
    )
    hb, hn = query(hdr_sql.format(s=T.BASE_STORY_SET_ID)), query(hdr_sql.format(s=new_set_id))
    print(f"섹션 수: 기준 {len(base)} / 새 {len(new)}; 헤더(id·version·note·시각 제외) 같음: {hb == hn}")
    if hb != hn:
        bad.append("세트 헤더 다름")
    diff_keys = sorted(k for k in set(base) | set(new) if base.get(k) != new.get(k))
    for k in diff_keys:
        print(f"- 다른 섹션 {k}")
        for f in ("order", "conditional"):
            if base.get(k, {}).get(f) != new.get(k, {}).get(f):
                print(f"  - {f}: {base.get(k, {}).get(f)} → {new.get(k, {}).get(f)}")
        if base.get(k, {}).get("body") != new.get(k, {}).get("body"):
            print("  - body 전:\n```\n" + base[k]["body"] + "\n```\n  - body 후:\n```\n" + new[k]["body"] + "\n```")
    if diff_keys != ["memory_summary|both|instruction|"]:
        bad.append(f"세트 diff 섹션이 기대(요약 지시문 한 행)와 다름: {diff_keys}")
    elif new[diff_keys[0]]["body"] != T.replace_once(
        base[diff_keys[0]]["body"], T.SUMMARY_RULES_OLD, T.SUMMARY_RULES_NEW, "요약 지시문"
    ) or (base[diff_keys[0]]["order"], base[diff_keys[0]]["conditional"]) != (
        new[diff_keys[0]]["order"],
        new[diff_keys[0]]["conditional"],
    ):
        bad.append("요약 지시문 diff 가 원문→확정본과 다름")

    print("\n## 판정\n")
    print("통과" if not bad else "실패:\n" + "\n".join(f"- {b}" for b in bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
