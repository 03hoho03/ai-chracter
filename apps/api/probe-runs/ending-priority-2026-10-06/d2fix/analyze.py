"""d2fix 리플레이 결과 → 판정표. 사전 등록의 기대 감소·통과선을 그대로 적용한다."""
import json, glob, os, sys
D = os.path.dirname(os.path.abspath(__file__))
EXP = {"s2": 0, "s3": 2, "t008": 2, "t022": 3, "t038": 3, "t074": 3, "t088": 3, "t095": 3, "t105": 1, "t060": 0, "t061": 0, "t021": 0}
GROUP = {"s2": "a", "s3": "a", "t060": "c", "t061": "c", "t021": "c"}
ARMS = ["current", "candA", "candB"]
res, errors, cost, calls = {}, 0, 0.0, 0
for label in EXP:
    for arm in ARMS:
        recs = [json.loads(l) for l in open(f"{D}/replay/{label}-{arm}.jsonl", encoding="utf-8") if l.strip()]
        out = []
        for r in recs:
            if r.get("kind") != "call":
                continue
            calls += 1
            cost += r.get("costUsd") or 0
            if r["error"]:
                errors += 1; out.append(None); continue
            cd = next(s for s in r["statResult"] if s["name"] == "상영회까지")
            out.append({"dec": cd["start"] - cd["applied"], "req": cd["requested"], "aff": [(s["name"][:2], s["start"], s["requested"], s["applied"]) for s in r["statResult"] if s["name"] != "상영회까지"]})
        res[(label, arm)] = out
def fmt(o): return "·".join("E" if x is None else f"{x['dec']:g}" for x in o)
def hit(label, arm): return sum(1 for x in res[(label, arm)] if x is not None and x["dec"] == EXP[label])
print(f"calls {calls} errors {errors} cost ${cost:.6f}")
print("| 턴 | 기대 | 현행 | A | B |\n|---|---|---|---|---|")
for label in EXP:
    print(f"| {label} | {EXP[label]} | " + " | ".join(f"{fmt(res[(label,a)])} ({hit(label,a)}/3)" for a in ARMS) + " |")
summary = {}
for arm in ARMS:
    s2z = hit("s2", arm); s3 = hit("s3", arm)
    b = sum(hit(l, arm) for l in EXP if GROUP.get(l) is None)
    c = sum(hit(l, arm) for l in EXP if GROUP.get(l) == "c")
    b_no105 = b - hit("t105", arm)
    summary[arm] = dict(s2zero=s2z, s3two=s3, b=b, c=c, bc=b + c, bc_no105=b_no105 + c)
print(json.dumps(summary, ensure_ascii=False))
cur = summary["current"]["bc"]
for arm in ["candA", "candB"]:
    s = summary[arm]
    print(arm, "P1", s["s2zero"] >= 2, "P2", s["s3two"] >= 2, "P3", s["bc"] >= cur - 2, f"({s['bc']} vs {cur}-2)")
print("현행 s2 결함 재현:", summary["current"]["s2zero"] < 2)
# 판정이 요청한 「상영회까지」 새 값(서버 적용 전, None = 요청 없음)
for (label, arm), o in sorted(res.items()):
    reqs = [x["req"] for x in o if x]
    print(label, arm, "requested", reqs)
