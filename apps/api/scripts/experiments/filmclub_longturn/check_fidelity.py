"""복제 충실도의 항목별 대조. 운영 쪽은 읽기 전용 내보내기(JSON)와 운영 지문(Postgres md5)을,
격리 쪽은 격리 DB 를 지금 직접 조회한 값을 쓴다. 항목마다 (1) 운영 = 격리 (2) 기대값 성립을 본다.

사용: python check_fidelity.py <내보내기 JSON 디렉터리>
  디렉터리에 prod-fingerprint.tsv 가 함께 있어야 한다.
"""

import json
import subprocess
import sys
from pathlib import Path

CONTAINER = "ai-character-chat-wt-filmclub-longturn-postgres-1"
PSQL = ["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-d", "ai_character_chat", "-X", "-At"]
VERSION = "73cf197c-a8a4-4629-af9b-34029cba4127"
SETUPS = f"(SELECT id FROM starting_setups WHERE content_version_id = '{VERSION}')"
SET_IDS = {
    "story": "4f446070-dc83-416a-b53d-3f43546ac15c",
    "character": "4da67d2d-bb07-44d8-b307-0e790bab03e3",
    "publish_filter": "d22ab240-0abb-46bf-b12c-0d638563f0b1",
}

failures: list[str] = []


def iso(sql: str) -> list:
    """격리 DB 에서 json_agg 한 결과 하나를 읽는다. 시각 열이 섞이지 않도록 TimeZone 을 고정한다."""
    out = subprocess.run(
        PSQL, input=f"SET TimeZone = 'UTC';\n{sql}", capture_output=True, text=True, check=True
    ).stdout
    return json.loads(out.split("\n", 1)[1]) or []


def check(item: str, ok: bool, detail: str) -> None:
    print(f"{item}\t{'통과' if ok else '실패'}\t{detail}")
    if not ok:
        failures.append(item)


def project(rows: list[dict], cols: list[str], key: str = "order") -> list[list]:
    return [[r[c] for c in cols] for r in sorted(rows, key=lambda r: (r[key], r["id"]))]


def main() -> None:
    src = Path(sys.argv[1])
    prod = {p.stem: json.loads(p.read_text()) for p in src.glob("*.json")}
    fp: dict[tuple[str, str, str], str] = {}
    for line in (src / "prod-fingerprint.tsv").read_text().splitlines():
        p = line.split("\t")
        if p[0] == "fp":
            fp[(p[1], p[2], p[3])] = p[4]

    # 스탯 정의 4행
    cols = ["name", "min_value", "max_value", "initial_value", "per_turn_delta", "change_direction",
            "max_change_per_turn", "description"]
    i_rows = iso(f"SELECT json_agg(t) FROM stat_defs t WHERE starting_setup_id IN {SETUPS};")
    p, i = project(prod["stat_defs"], cols), project(i_rows, cols)
    shape = [r[1:7] for r in i]
    affinity = [0, 100, 20, None, "both", None]
    countdown = [0, 42, 42, None, "decrease", 7]
    exp_ok = len(i) == 4 and sorted(map(str, shape)) == sorted(map(str, [affinity] * 3 + [countdown]))
    check("스탯", p == i and exp_ok, f"운영=격리 {p == i}; 기대 모양 {exp_ok}; {[(r[0], *r[1:7]) for r in i]}")

    # 상황 노트 7행
    cols = ["name", "order", "info_text", "condition_rules"]
    i_rows = iso(f"SELECT json_agg(t) FROM situation_notes t WHERE starting_setup_id IN {SETUPS};")
    p, i = project(prod["situation_notes"], cols), project(i_rows, cols)
    conds = [" ".join(f"{c['operator']} {c['threshold']:g} {c['next_op'] or ''}".strip() for c in r[3]) for r in i]
    expected = ["gte 29", "gte 8 and lte 28", "gte 1 and lte 7", "lte 0", "gte 45", "gte 45", "gte 45"]
    check("상황 노트", p == i and conds == expected, f"운영=격리 {p == i}; {len(i)}행; 조건 {conds}")

    # 미디어 북
    counts = {}
    for t in ("media_book_people", "media_book_scenes", "media_book_cells"):
        i_rows = iso(f"SELECT json_agg(t) FROM {t} t WHERE content_version_id = '{VERSION}';")
        same = sorted(json.dumps(r, sort_keys=True) for r in prod[t]) == sorted(json.dumps(r, sort_keys=True) for r in i_rows)
        counts[t] = (len(i_rows), same)
        if t == "media_book_cells":
            excluded = sum(1 for r in i_rows if r["exclude_from_chat"])
    ok = [c[0] for c in counts.values()] == [3, 16, 48] and all(c[1] for c in counts.values()) and excluded == 0
    check("미디어 북", ok, f"{ {k: v[0] for k, v in counts.items()} } 운영=격리 {all(c[1] for c in counts.values())}; exclude_from_chat=t {excluded}")

    # 엔딩 5 + 규칙 11
    cols = ["order", "name", "turn_count_gate"]
    i_end = iso(f"SELECT json_agg(t) FROM endings t WHERE starting_setup_id IN {SETUPS};")
    i_rules = iso(f"SELECT json_agg(t) FROM ending_rules t WHERE ending_id IN (SELECT id FROM endings WHERE starting_setup_id IN {SETUPS});")
    pe, ie = project(prod["endings"], cols), project(i_end, cols)
    rule_cols = ["ending_id", "order", "stat_def_entity_id", "operator", "threshold", "next_op"]
    pr = sorted(map(str, project(prod["ending_rules"], rule_cols)))
    ir = sorted(map(str, project(i_rules, rule_cols)))
    gates = [r[2] for r in ie]
    ops = sorted({r["operator"] for r in i_rules})
    nexts = sorted({str(r["next_op"]) for r in i_rules})
    ok = pe == ie and pr == ir and gates == [10, 10, 10, 25, 25] and len(i_rules) == 11
    check("엔딩", ok, f"운영=격리 엔딩 {pe == ie}·규칙 {pr == ir}; gate {gates}; 규칙 {len(i_rules)}행 op {ops} next_op {nexts}; {[r[1] for r in ie]}")

    # 텍스트 필드 md5 — 운영 쪽은 운영 Postgres 가 읽기 전용으로 계산한 md5(지문)
    text_cols = {
        "story_version_details": ["setting_text", "development_example", "development_examples", "user_goal", "rules",
                                  "prompt_template", "custom_prompt"],
        "starting_setups": ["prologue", "opening_message", "playguide", "suggested_replies"],
        "keyword_notes": ["info_text", "name", "trigger_keywords"],
        "shortcuts": ["name", "description", "prompt"],
        "endings": ["judgment_prompt", "epilogue", "hint"],
        "content_versions": ["detail_description"],
    }
    n = bad = 0
    for t, cs in text_cols.items():
        key = "content_version_id" if t == "story_version_details" else "id"
        where = (f"content_version_id = '{VERSION}'" if t in ("story_version_details", "keyword_notes", "shortcuts")
                 else f"id = '{VERSION}'" if t == "content_versions" else
                 f"id IN {SETUPS}" if t == "starting_setups" else f"starting_setup_id IN {SETUPS}")
        sel = ", ".join(f"'{c}', coalesce(md5(to_jsonb(t)->>'{c}'), '<null>')" for c in cs)
        rows = iso(f"SELECT json_agg(json_build_object('k', {key}::text, {sel})) FROM {t} t WHERE {where};")
        for r in rows:
            for c in cs:
                n += 1
                if fp.get((t, r["k"], c)) != r[c]:
                    bad += 1
                    print(f"  md5 불일치 {t} {r['k']} {c}")
    check("텍스트 md5", bad == 0 and n > 0, f"{n}칸 대조, 불일치 {bad}")

    # 프롬프트 섹션 — (channel, scope, slot, variant) 키로 md5(body)·order·conditional
    for lane, sid in SET_IDS.items():
        i_rows = iso(
            "SELECT json_agg(json_build_object('id', id::text, 'key', concat_ws('|', channel, scope, slot, variant), "
            f"'md5', md5(body), 'order', \"order\", 'conditional', conditional)) FROM prompt_sections WHERE prompt_set_id = '{sid}';"
        )
        p_rows = [r for r in prod["prompt_sections"] if r["prompt_set_id"] == sid]
        pm = {"|".join([r["channel"], r["scope"], r["slot"], r["variant"]]):
              (fp[("prompt_sections", r["id"], "body")], r["order"], r["conditional"]) for r in p_rows}
        im = {r["key"]: (r["md5"], r["order"], r["conditional"]) for r in i_rows}
        diff = sorted(k for k in pm.keys() | im.keys() if pm.get(k) != im.get(k))
        check(f"프롬프트 섹션 {lane}", not diff and len(pm) == len(im) == len(p_rows),
              f"섹션 운영 {len(p_rows)} / 격리 {len(im)}; 키 {len(pm)}; 불일치 {diff}")

    print(f"실패 {len(failures)}: {failures}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
