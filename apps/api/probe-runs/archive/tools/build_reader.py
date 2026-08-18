"""probe-runs 대화록을 읽기용 단일 HTML 로 굳힌다 (일회성 도구).

주장을 본문에서 직접 확인할 수 있게, 절단 지점·자기복제 구간·키릴 문자·되받기 키워드를
문자 오프셋으로 계산해 하이라이트 범위로 넘긴다 — 리포트의 수치를 사람이 되짚을 수 있어야
한다는 것이 이 파일의 목적이다.
"""

import json
import re
from pathlib import Path

ARCHIVE = Path(__file__).resolve().parent.parent
RUNS = ARCHIVE / "transcripts"
OUT = ARCHIVE / "reports" / "2026-08-14_transcripts.html"

# chat_probe.TURNS / analyze_chat_probe.TURN_KEYWORDS 와 반드시 같아야 한다.
TURNS = [
    "일단 상황부터 좀 알려줘요",
    "그건 별로 좋은 생각이 아닌 것 같은데요",
    "왜 그렇게 생각하세요?",
    "그냥 제 느낌을 말한 거예요",
    "좀 무섭네요 솔직히",
    "그럼 이제 어떻게 하면 되죠?",
]
TURN_KEYWORDS = [
    ["상황"],
    ["좋은 생각", "생각이 아니", "별로"],
    ["왜", "생각"],
    ["느낌", "그냥"],
    ["무섭", "무서", "솔직"],
]

TERMINAL = set('.!?…"”\'’')
CYRILLIC = re.compile(r"[Ѐ-ӿ]+")
BROKEN = re.compile(r"[가-힣][A-Za-z]|[A-Za-z][가-힣]")

# 파일 → (라운드, 표시이름, 조건설명). 08-10 은 다른 실험(18개 스토리)이라 제외한다.
FILES = [
    ("2026-08-11_gemini-3.5-flash-lite.json", "1R", "gemini-3.5-flash-lite", "상한 2048 · 사고 없음 · 현 운영 기본값"),
    ("2026-08-11_gemini-3.1-flash-lite.json", "1R", "gemini-3.1-flash-lite", "상한 2048 · 사고 없음"),
    ("2026-08-11_gemini-3-flash-preview.json", "1R", "gemini-3-flash-preview", "상한 2048 · 사고형"),
    ("2026-08-11_gemini-3.5-flash.json", "1R", "gemini-3.5-flash", "상한 2048 · 사고형 — 절단 최다"),
    ("2026-08-11_gemini-3.6-flash.json", "1R", "gemini-3.6-flash", "상한 2048 · 사고형"),
    ("2026-08-11_gemini-2.5-flash.json", "1R", "gemini-2.5-flash", "상한 2048 · 사고형 — 자기 복제 발생"),
    ("2026-08-11_gemini-2.5-flash-lite.json", "1R", "gemini-2.5-flash-lite", "404 — 이 키로 호출 불가"),
    ("2026-08-14_3.5-flash_max8192_think-on.json", "2R", "gemini-3.5-flash · 사고 켬", "상한 8192 · 사고 모델 기본값"),
    ("2026-08-14_3.5-flash_max8192_think-off.json", "2R", "gemini-3.5-flash · 사고 끔", "상한 8192 · thinking_budget=0"),
    ("2026-08-14_3.6-flash_max8192_think-on.json", "2R", "gemini-3.6-flash · 사고 켬", "상한 8192 · 사고 모델 기본값"),
    ("2026-08-14_3.6-flash_max8192_think-off_failed-400-invalid-argument.json", "2R", "gemini-3.6-flash · 사고 끔", "400 INVALID_ARGUMENT — 이 모델은 사고를 못 끈다"),
    ("2026-08-12_3.5-flash_max8192_think-on_partial-rpd429.json", "중단", "gemini-3.5-flash (중단분)", "상한 8192 · RPD 소진으로 중도 중단"),
]


def is_truncated(text: str) -> bool:
    """꼬리 공백과 닫는 이탤릭을 벗긴 뒤 종결 부호로 끝나지 않으면 절단."""
    tail = text.rstrip().rstrip("*").rstrip()
    return bool(tail) and tail[-1] not in TERMINAL


def marks(text: str, turn_index: int, prev: str | None) -> list[dict]:
    """본문에 얹을 하이라이트 범위. 겹치면 앞의 것이 이긴다."""
    found: list[dict] = []

    if prev:
        head = prev.strip()[:50]
        if head and text.strip().startswith(head):
            # 직전 응답 전문 복사 — 공통 접두가 어디까지인지 실제로 재서 보여준다.
            a, b = text.strip(), prev.strip()
            n = 0
            while n < min(len(a), len(b)) and a[n] == b[n]:
                n += 1
            start = text.index(a[:1]) if a else 0
            found.append({"s": start, "e": start + n, "k": "copy", "t": f"직전 응답과 글자 단위로 동일한 구간 {n}자"})

    for m in CYRILLIC.finditer(text):
        found.append({"s": m.start(), "e": m.end(), "k": "bad", "t": f"키릴 문자 '{m.group()}'"})

    for m in BROKEN.finditer(text):
        found.append({"s": m.start(), "e": m.end(), "k": "warn", "t": "한글·라틴 혼합 (한국어 깨짐 후보)"})

    if turn_index < len(TURN_KEYWORDS):
        for kw in TURN_KEYWORDS[turn_index]:
            i = text.find(kw)
            if i >= 0:
                where = "앞 250자 안" if i < 250 else f"{i}번째 글자 — 앞 250자 밖"
                found.append({"s": i, "e": i + len(kw), "k": "parrot", "t": f"되받기 표지 '{kw}' · {where}"})

    found.sort(key=lambda x: (x["s"], -(x["e"] - x["s"])))
    out: list[dict] = []
    end = -1
    for f in found:
        if f["s"] >= end:
            out.append(f)
            end = f["e"]
    return out


def build() -> dict:
    runs = []
    for fname, rnd, name, cond in FILES:
        path = RUNS / fname
        if not path.exists():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        results = raw.get("results", raw) if isinstance(raw, dict) else raw
        rooms = []
        for r in results:
            if not isinstance(r, dict):
                continue
            if "error" in r:
                rooms.append({"label": r.get("label", r.get("slug", "?")), "error": r["error"], "turns": []})
                continue
            trans = r.get("transcript", [])
            opening = trans[0]["text"] if trans else ""
            turns = []
            prev = None
            idx = 0
            for item in trans[1:]:
                if item["role"] != "진행자":
                    continue
                text = item["text"]
                turns.append({
                    "n": idx + 1,
                    "user": TURNS[idx] if idx < len(TURNS) else "",
                    "text": text,
                    "len": len(text),
                    "sec": item.get("seconds"),
                    "events": item.get("events") or [],
                    "cut": is_truncated(text) if text else False,
                    "marks": marks(text, idx, prev) if text else [],
                })
                if text:
                    prev = text
                idx += 1
            scored = [t for t in turns if t["text"]]
            rooms.append({
                "label": r.get("label", r.get("slug", "?")),
                "setup": r.get("startingSetupId", ""),
                "opening": opening,
                "turns": turns,
                "empty": sum(1 for t in turns if not t["text"]),
                "cuts": sum(1 for t in scored if t["cut"]),
                "median": sorted(t["len"] for t in scored)[len(scored) // 2] if scored else 0,
            })
        runs.append({
            "id": fname.replace(".json", ""),
            "round": rnd,
            "name": name,
            "cond": cond,
            "collectedAt": raw.get("collectedAt", "") if isinstance(raw, dict) else "",
            "rooms": rooms,
        })
    return {"runs": runs}


if __name__ == "__main__":
    data = build()
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    template = Path(__file__).with_name("reader_template.html").read_text(encoding="utf-8")
    OUT.write_text(template.replace("/*__DATA__*/null", payload), encoding="utf-8")
    n_turns = sum(len(r["turns"]) for run in data["runs"] for r in run["rooms"])
    chars = sum(t["len"] for run in data["runs"] for r in run["rooms"] for t in r["turns"])
    print(f"{OUT}  런 {len(data['runs'])}개 · 턴 {n_turns}개 · {chars:,}자 · {OUT.stat().st_size:,} bytes")
