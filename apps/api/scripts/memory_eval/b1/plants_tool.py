"""묶음 1 측정 대본 셋의 심기 표 채우기·검사(대본을 쓰기 전 단계).

사용:
    python3 -I plants_tool.py fill  <plants.json> <거짓 전제 판정 정의 JSON>
    python3 -I plants_tool.py check <plants.json> <작품 글 JSON>

`fill` 은 작성자가 적은 칸에서 파생 칸을 계산해 같은 파일에 다시 쓴다(여러 번 돌려도 결과가 같다):
`primary`·`layer`·`stratum`·`plant_turns`·`keywords`(사건 핵심어의 합집합)·`storyBatch`·`ask_checkpoints`·
`score_checkpoint`·`reMentionTurns`, 거짓 전제 항목의 `verdicts`·`judge_note`·`correct`·`fail_if`.
거짓 전제 판정 정의는 측정 판정자와 같은 문장이어야 하므로 작성자가 쓰지 않고, 데이터 폴더의 정의 파일 문장을 넣는다.

`check` 는 대본 없이 확인할 수 있는 규칙만 본다(대본 본문 검사는 대본 검사기 몫). 위반이 하나라도 있으면 종료 코드 1.
표준출력에는 규칙 이름과 항목 id·턴만 찍는다 — 질문·정답 내용은 찍지 않는다."""

import json
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

TOTAL_TURNS = 300
CHECKPOINTS = (100, 300)
FOLD_AT = 30  # 첫 접기 턴 — 이 턴까지 심은 비밀은 첫 요약에 처음 실린다
WINDOW = 10  # 접기 한 번이 접는 턴 수
MAX_EVENTS_PER_WINDOW = 6  # 접힌 창 하나가 장면 기억 상한을 넘지 않게 두는 여유
MIN_GAP = 31  # 심은 턴이 묻는 체크포인트의 원문 창(최대 29턴) 밖에 있으려면 체크포인트보다 31턴 앞이어야 한다
RELATION_GAP = 50  # 관계는 마지막 변화 뒤 50턴 넘게 지나서 묻는다
CHUNK_TURNS = 25
PRIMARY = frozenset({"relation", "secret", "false_premise", "correction"})
CATEGORIES = PRIMARY | {"detail", "rephrase", "speaker", "abstain"}
SUBTYPES = {
    "relation": {"+", "-"},
    "secret": {"confided", "witnessed", "group"},
    "false_premise": {"character_claim", "user_lie"},
    "correction": {"claim_then_narration"},
    "detail": {"object", "place", "time", "promise"},
    "rephrase": {"object", "place", "time", "promise"},
    "speaker": {"fabricated", "user_said"},
    "abstain": {"pure", "near_miss"},
}
QUESTION_FORMS = {"direct", "paraphrase", "anaphora"}
LINES = {"assistant", "user"}
ASSERTED = {"narration", "character", "user"}

# 거짓 전제 판정 정의(라벨마다 한 문장과 판정 주의)는 측정 판정자가 보는 문장과 같아야 하고 정답 키에 그대로 복사되므로
# 측정 데이터 폴더의 파일(`fill` 의 둘째 인자)에서 읽는다. 사용자 거짓말 항목의 정의는 `{truth}` 자리에 그 항목의 진실을 넣는다.
DEFINITION_KEYS = ("claimVerdicts", "claimNote", "lieVerdicts", "lieNote")


def load_definitions(path: Path) -> dict[str, Any]:
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in DEFINITION_KEYS if not raw.get(k)]
    if missing:
        raise SystemExit(f"{path.name}: 판정 정의 칸이 비었다 {missing}")
    for key in ("claimVerdicts", "lieVerdicts"):
        if sorted(raw[key]) != ["accepted", "rejected", "unaddressed"]:
            raise SystemExit(f"{path.name}: {key} 는 rejected·accepted·unaddressed 세 라벨이다")
    return raw


def norm(text: str) -> str:
    return "".join(unicodedata.normalize("NFC", text).casefold().split())


def contains(hay: str, needle: str) -> bool:
    n = norm(needle)
    return bool(n) and n in norm(hay)


def entries(raw: dict[str, Any]) -> list[dict[str, Any]]:
    return list(raw.get("plants", [])) + list(raw.get("abstains", []))


def event_turns(entry: dict[str, Any]) -> list[int]:
    return sorted(int(p["turn"]) for p in entry.get("plants") or [])


def stratum_of(entry: dict[str, Any]) -> str:
    """분할 층. 비밀만 첫 접기 전 층과 그 뒤 층으로 나눈다 — 첫 요약에 처음 실리는 비밀이 한쪽 절반에 몰리지 않게."""
    if entry["category"] == "secret":
        return f"secret:{entry['layer']}"
    return str(entry["category"])


def fill(raw: dict[str, Any], definitions: dict[str, Any]) -> dict[str, Any]:
    for entry in entries(raw):
        category = entry["category"]
        turns = event_turns(entry)
        entry["primary"] = category in PRIMARY
        if category == "secret":
            entry["layer"] = "early" if turns and turns[-1] <= FOLD_AT else "main"
        entry["stratum"] = stratum_of(entry)
        if category != "abstain":
            entry["plant_turns"] = turns
            keywords: list[str] = []
            for event in entry["plants"]:
                for word in event["keywords"]:
                    if word not in keywords:
                        keywords.append(word)
            entry["keywords"] = keywords
            entry["storyBatch"] = sorted({(t - 1) // CHUNK_TURNS + 1 for t in turns})
            entry.setdefault("reMentionTurns", [])
        last = turns[-1] if turns else 0
        gap = RELATION_GAP if category == "relation" else MIN_GAP
        if category == "abstain":
            ask = [CHECKPOINTS[-1]]
        else:
            ask = [cp for cp in CHECKPOINTS if last <= cp - gap and (entry["primary"] or cp == CHECKPOINTS[-1])]
        entry["ask_checkpoints"] = ask
        entry["score_checkpoint"] = ask[-1] if ask else None
        entry.setdefault("questionForm", "direct")
        if category == "false_premise":
            key = entry["answer_key"]
            key["mode"] = "judge"
            key["judge_kind"] = "false_premise"
            if entry["subtype"] == "user_lie":
                key["verdicts"] = {k: v.format(truth=key["truth"]) for k, v in definitions["lieVerdicts"].items()}
                key["judge_note"] = definitions["lieNote"]
            else:
                key["verdicts"] = dict(definitions["claimVerdicts"])
                key["judge_note"] = definitions["claimNote"]
            key["correct"] = "verdicts.rejected"
            key["fail_if"] = ["verdicts.accepted"]
    return raw


def check(raw: dict[str, Any], work_text: str) -> dict[str, list[str]]:
    v: dict[str, list[str]] = defaultdict(list)
    items = entries(raw)
    cast = [str(n) for n in raw.get("cast", {}).get("named", [])]
    quota = raw.get("quota", {})
    ids = [str(e["id"]) for e in items]
    for dup, n in Counter(ids).items():
        if n > 1:
            v["id 중복"].append(dup)
    prefix = str(raw.get("idPrefix", ""))
    for i in ids:
        if not i.startswith(prefix):
            v["id 접두어"].append(i)

    counts = Counter(stratum_of(e) for e in items if e["category"] != "secret" or "layer" in e)
    for stratum, n in counts.items():
        if n % 2:
            v["층 크기 홀수"].append(f"{stratum} {n}")
    for stratum, want in quota.items():
        if counts.get(stratum, 0) != want:
            v["층 배정 수"].append(f"{stratum} {counts.get(stratum, 0)}≠{want}")
    for stratum in counts:
        if stratum not in quota:
            v["배정에 없는 층"].append(stratum)

    events_by_turn: dict[int, list[str]] = defaultdict(list)
    keyword_owner: dict[str, str] = {}
    for e in items:
        iid, cat = str(e["id"]), e["category"]
        if cat not in CATEGORIES:
            v["모르는 범주"].append(iid)
            continue
        if e.get("subtype") not in SUBTYPES[cat]:
            v["모르는 하위 유형"].append(f"{iid} {e.get('subtype')}")
        form = e.get("questionForm", "direct")
        if form not in QUESTION_FORMS:
            v["모르는 질문 형식"].append(iid)
        if cat == "rephrase" and form == "direct":
            v["바꿔 말하기 항목이 직접 질문"].append(iid)
        if cat != "rephrase" and form != "direct":
            v["직접 질문이어야 할 항목"].append(iid)
        if form == "anaphora":
            ctx = (e.get("contextTurn") or {}).get("userLine", "")
            if not 20 <= len(ctx) <= 120:
                v["맥락 턴 길이"].append(f"{iid} {len(ctx)}")
        if cat == "rephrase":
            # 바꿔 말하기는 심은 줄의 명사와 낱말이 겹치지 않아야 명사 일치 회상과 갈린다.
            nouns = e.get("planNouns") or []
            if not nouns:
                v["바꿔 말하기 심은 줄 명사 목록 없음"].append(iid)
            asked = str(e.get("question", "")) + str((e.get("contextTurn") or {}).get("userLine", ""))
            for noun in nouns:
                if contains(asked, noun):
                    v["바꿔 말하기 질문에 심은 줄 명사"].append(iid)
        if not 20 <= len(str(e.get("question", ""))) <= 120:
            v["질문 길이"].append(f"{iid} {len(str(e.get('question', '')))}")
        if not e.get("people") and cat != "abstain":
            v["관련 인물 없음"].append(iid)
        if cat == "abstain":
            for word in e.get("banned") or []:
                if contains(work_text, word):
                    v["기권 금지 낱말이 작품 글에"].append(f"{iid}")
            continue
        turns = event_turns(e)
        if not turns:
            v["심는 사건 없음"].append(iid)
            continue
        if len(set(turns)) != len(turns):
            v["한 항목이 같은 턴에 두 번"].append(iid)
        for p in e["plants"]:
            t = int(p["turn"])
            events_by_turn[t].append(iid)
            if p.get("line") not in LINES or p.get("assertedBy") not in ASSERTED:
                v["사건 칸 값"].append(f"{iid} 턴{t}")
            if not p.get("keywords") or not p.get("plan"):
                v["사건 핵심어·지시 없음"].append(f"{iid} 턴{t}")
            if t in CHECKPOINTS:
                v["체크포인트 턴에 심기"].append(f"{iid} 턴{t}")
        last = turns[-1]
        if not e.get("ask_checkpoints"):
            v["묻는 체크포인트 없음(심기가 너무 늦음)"].append(f"{iid} 마지막 턴{last}")
        for cp in e.get("ask_checkpoints") or []:
            gap = RELATION_GAP if cat == "relation" else MIN_GAP
            if last > cp - gap:
                v["프로브가 심기보다 충분히 뒤가 아님"].append(f"{iid} CP{cp} 턴{last}")
        if cat == "relation":
            if len(turns) < 3:
                v["관계 변화 2회 미만"].append(iid)
            pair = (e["expected_fact"]["subject"], e["expected_fact"].get("object"))
            if len(e["expected_fact"].get("history") or []) != len(turns) - 1:
                v["관계 옛 태도 수≠사건 수-1"].append(iid)
            e["_pair"] = pair
        if cat == "correction" and len(turns) != 2:
            v["정정 사건 2개 아님"].append(iid)
        if cat == "secret":
            owner, unaware = e.get("secretOwner"), e.get("unawareCharacter")
            setup = str(e.get("setup_turn_text", ""))
            known = e["expected_fact"].get("known_by") or []
            if not 20 <= len(setup) <= 120:
                v["장면 설정 길이"].append(f"{iid} {len(setup)}")
            if owner not in known or "사용자" not in known:
                v["비밀 known_by 에 주인·사용자 없음"].append(iid)
            if e["subtype"] == "group" and len([k for k in known if k != "사용자"]) < 2:
                v["집단 비밀인데 아는 인물 하나"].append(iid)
            if unaware is None:
                # 이름 없이 등장하는 모르는 인물: 주인 이름이 장면에 나와 행이 걸러지지 않는 상황을 만든다.
                if not e.get("unawareRole"):
                    v["이름 없는 모르는 인물 설명 없음"].append(iid)
                if not contains(setup, short(owner)):
                    v["이름 없는 장면 설정에 주인 이름 없음"].append(iid)
                named = [n for n in cast if n != owner and contains(setup, short(n))]
                if named:
                    v["이름 없는 장면 설정에 다른 인물 이름"].append(f"{iid} {named}")
            else:
                if unaware in known:
                    v["모르는 인물이 known_by 에"].append(iid)
                if not contains(setup, short(unaware)):
                    v["장면 설정에 모르는 인물 이름 없음"].append(iid)
                if contains(setup, short(owner)):
                    v["장면 설정에 비밀 주인 이름"].append(iid)
                if unaware not in cast:
                    v["모르는 인물이 등장인물 목록 밖"].append(f"{iid} {unaware}")
            if not (e.get("answer_key") or {}).get("leak_bundles"):
                v["누출 묶음 없음"].append(iid)
        if cat == "false_premise" and e["subtype"] == "user_lie" and not e.get("truthCue"):
            v["사용자 거짓말 진실 단서 없음"].append(iid)
        for word in e.get("keywords") or []:
            if norm(word) in norm(work_text):
                v["작품 글에 핵심어"].append(f"{iid}")
            for other, owner_id in keyword_owner.items():
                if owner_id != iid and (norm(word) in norm(other) or norm(other) in norm(word)):
                    v["핵심어 부분 겹침"].append(f"{iid}·{owner_id}")
            for person in cast:
                if norm(word) in norm(person):
                    v["핵심어가 인물 이름 안에"].append(iid)
            if contains(str(e.get("question", "")), word) and not e.get("exclusionWaiver"):
                v["질문에 핵심어"].append(iid)
            if contains(str(e.get("setup_turn_text", "")), word):
                v["장면 설정에 핵심어"].append(iid)
            if contains(str((e.get("contextTurn") or {}).get("userLine", "")), word):
                v["맥락 턴에 핵심어"].append(iid)
        for word in e.get("keywords") or []:
            keyword_owner.setdefault(word, iid)

    for t, owners in sorted(events_by_turn.items()):
        if len(owners) > 1:
            v["한 턴에 심기 둘 이상"].append(f"턴{t} {owners}")
    per_window = Counter((t - 1) // WINDOW for t in events_by_turn for _ in events_by_turn[t])
    for w, n in sorted(per_window.items()):
        if n > MAX_EVENTS_PER_WINDOW:
            v["접기 창당 심기 초과"].append(f"턴{w * WINDOW + 1}~{w * WINDOW + WINDOW} {n}")

    # 같은 쌍의 관계 항목은 하나만(최신 태도가 하나여야 정답이 하나다).
    pairs = Counter(e.pop("_pair") for e in items if "_pair" in e)
    for pair, n in pairs.items():
        if n > 1:
            v["같은 쌍 관계 항목 둘 이상"].append(str(pair))
    banned = [(str(e["id"]), w) for e in items if e["category"] == "abstain" for w in e.get("banned") or []]
    for e in items:
        blob = json.dumps(e.get("plants") or [], ensure_ascii=False) + str(e.get("question", ""))
        for aid, w in banned:
            # 기권 질문은 없던 일을 묻느라 자기 금지 낱말을 담는다 — 다른 항목에서만 본다.
            if aid != str(e["id"]) and contains(blob, w):
                v["기권 금지 낱말이 다른 항목 지시·질문에"].append(f"{aid}←{e['id']}")
    return dict(v)


def short(name: str | None) -> str:
    """세 글자 실명은 뒤 두 글자(부르는 이름)로 찾는다 — 대사는 주로 이름만 부른다."""
    if not name:
        return ""
    return name[-2:] if len(name) == 3 else name


def work_text(path: Path) -> str:
    parts: list[str] = []

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            for value in x.values():
                walk(value)
        elif isinstance(x, list):
            for value in x:
                walk(value)
        elif isinstance(x, str):
            parts.append(x)

    walk(json.loads(path.read_text(encoding="utf-8")))
    return "\n".join(parts)


def summary(raw: dict[str, Any]) -> dict[str, Any]:
    items = entries(raw)
    events = [t for e in items for t in event_turns(e)]
    return {
        "strata": dict(sorted(Counter(stratum_of(e) for e in items).items())),
        "subtypes": dict(sorted(Counter(f"{e['category']}/{e.get('subtype')}" for e in items).items())),
        "questionForms": dict(sorted(Counter(e.get("questionForm", "direct") for e in items).items())),
        "namelessUnaware": sum(1 for e in items if e["category"] == "secret" and e.get("unawareCharacter") is None),
        "plantEvents": len(events),
        "lastPlantTurn": max(events) if events else None,
        "askedAt100": sum(1 for e in items if 100 in (e.get("ask_checkpoints") or [])),
        "twoTurnProbesAt300": sum(1 for e in items if e.get("setup_turn_text") or e.get("questionForm") == "anaphora"),
    }


def main() -> int:
    command, path = sys.argv[1], Path(sys.argv[2])
    raw = json.loads(path.read_text(encoding="utf-8"))
    if command == "fill":
        fill(raw, load_definitions(Path(sys.argv[3])))
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps(summary(raw), ensure_ascii=False))
        return 0
    if command == "check":
        report = check(raw, work_text(Path(sys.argv[3])))
        for rule, hits in report.items():
            print(f"{rule}: {len(hits)}")
            for hit in hits[:30]:
                print("   ", hit)
        print(json.dumps(summary(raw), ensure_ascii=False))
        print("위반", sum(len(h) for h in report.values()))
        return 1 if report else 0
    raise SystemExit(f"모르는 명령: {command}")


if __name__ == "__main__":
    sys.exit(main())
