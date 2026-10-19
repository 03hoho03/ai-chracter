"""묶음 1 대본(25턴 묶음 열둘) 기계 검사 — 묶음을 하나 쓸 때마다 그 묶음까지 누적으로 돌린다.

사용:
    python3 -I check_chunks.py <plants.json> <작품 글 JSON> <묶음 폴더> --upto N --markup asterisk|quotes [--status]

`<묶음 폴더>/chunk-01.jsonl` … `chunk-NN.jsonl`(줄마다 `{turn, user, assistant}`)을 1~N 까지 읽어 턴 1~25N 을 본다.
하네스 `check-script` 는 1차 형식 심기 표 전용이라 2차 형식(이번 심기 표)은 이 검사기가 본다. 규칙:

- 턴 번호 연속, 사용자 줄 20~120자(공백 포함), 진행자 줄 공백 뺀 150~350자.
- `--status`(조감독처럼 작품이 상태창을 요구할 때): 진행자 줄 끝 코드 블록이 장소·시간·함께·지금 네 줄.
- 심는 턴의 지정된 줄에 그 사건의 핵심어가 있다.
- 핵심어 자리가 진실 상태와 맞다: 확정 사실(진행자 서술·사용자 지문)의 핵심어는 지문에, 주장(누가 한 말)의 핵심어는
  대사에. 정정은 옛 값=대사·새 값=서술, 사용자 거짓말은 거짓=사용자 대사·진실 단서=사용자 지문. 지문과 대사를 가르는
  표기는 작품마다 다르다 — `asterisk` 는 *…* 안이 지문이고 밖이 대사(조감독), `quotes` 는 따옴표 안이 대사이고 밖이
  지문(나머지 두 작품의 진행자 줄). 사용자 줄은 어느 작품이든 *…* 안이 사용자 지문, 밖이 사용자 대사다.
- 핵심어가 심는 턴 밖에 나오지 않는다(체크포인트 원문 창 [CP−29, CP] 안이면 따로 센다).
- 기권 항목의 금지 낱말이 어디에도 없다.
- 체크포인트 턴(100·300)의 진행자 줄에 어떤 핵심어·단서 명사도 없다.
- 비밀을 심은 뒤 모르는 인물이 이름으로 나오는 턴에 그 비밀의 핵심어·누출 묶음 낱말이 있으면 사람 확인 대상으로 적는다.
- 사람 확인 대상으로 적힌 것 중 확인을 마친 것은 `<묶음 폴더>/review.json`(`[{rule, entry, reason}]`)에 적으면 빠진다.
- 정답 묶음·거짓 전제 묶음의 낱말 하나라도 그 항목을 묻는 체크포인트의 원문 창 [CP−29, CP] 안(심은 턴 밖)에 나오면
  위반이다 — 원문 창은 기억 없이 보이므로 회상이 아니라 읽기로 맞힌다. 상태창 안에서 나온 것은 따로 센다. 한 음절
  낱말은 빼고, 숫자 표기(한글 ↔ 아라비아)·띄어쓰기·조사·두 낱말 사이 한 글자 끼움은 같은 낱말로 본다.
- 정정 항목의 정정 턴에 옛 값(reject 묶음·옛 핵심어) 낱말이 함께 나오면 위반이다.
- 경고(종료 코드에 넣지 않음, 사람 확인 뒤 `review.json` 으로 뺀다): 심은 뒤~마지막으로 묻는 체크포인트 사이 원문 창
  밖에 묶음 낱말(누출·옛 값 포함, 묶음이 없으면 핵심어의 낱말)이 다시 나옴, 정답 묶음이 한 음절이거나 대본 열 턴
  넘게 두루 나오는 흔한 낱말뿐임.
- 마지막 묶음까지 오면: 300턴, 연속 30턴 글자 합 < 24,000(첫 접기가 글자 상한이 아니라 턴 수로 일어난다는 가정).

표준출력에는 규칙 이름과 항목 id·턴만 찍는다(위반 다음에 경고). 위반이 있으면 종료 코드 1."""

import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

USER_LEN = (20, 120)
NARRATOR_LEN = (150, 350)
CHUNK = 25
CHECKPOINTS = (100, 300)
RAW_WINDOW = 29
FOLD_CHARS = 24000
STATUS_KEYS = ["장소", "시간", "함께", "지금"]


def norm(text: str) -> str:
    return "".join(unicodedata.normalize("NFC", text).casefold().split())


def contains(hay: str, needle: str) -> bool:
    n = norm(needle)
    return bool(n) and n in norm(hay)


SINO_DIGITS = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
SINO_UNITS = {"십": 10, "백": 100, "천": 1000}
NATIVE = {
    "한": 1,
    "두": 2,
    "세": 3,
    "네": 4,
    "다섯": 5,
    "여섯": 6,
    "일곱": 7,
    "여덟": 8,
    "아홉": 9,
    "열": 10,
    "열한": 11,
    "열두": 12,
}
SINO_COUNTERS = ("월", "일", "분", "원", "층", "호", "년", "회", "주")
NATIVE_COUNTERS = ("시", "번", "명", "개", "살", "장", "권", "잔", "병")
COUNTERS = SINO_COUNTERS + NATIVE_COUNTERS
MONTH_NAMES = {6: "유월", 10: "시월"}
COMMON_TURNS = 10


def _sino(s: str) -> int | None:
    if not s or any(c not in SINO_DIGITS and c not in SINO_UNITS and c != "만" for c in s):
        return None
    head, has_man, rest = s.partition("만")
    if has_man:
        top = _sino(head) if head else 1
        low = _sino(rest) if rest else 0
        return None if top is None or low is None else top * 10000 + low
    total, cur = 0, 0
    for c in s:
        if c in SINO_DIGITS:
            if cur:
                return None
            cur = SINO_DIGITS[c]
        else:
            total += (cur or 1) * SINO_UNITS[c]
            cur = 0
    return total + cur


def _to_sino(n: int) -> str:
    if n >= 10000:
        return (_to_sino(n // 10000) if n // 10000 > 1 else "") + "만" + (_to_sino(n % 10000) if n % 10000 else "")
    digits = {v: k for k, v in SINO_DIGITS.items()}
    out = ""
    for unit, name in ((1000, "천"), (100, "백"), (10, "십")):
        q, n = divmod(n, unit)
        if q:
            out += ("" if q == 1 else digits[q]) + name
    return out + (digits[n] if n else "")


def _pure_number(token: str) -> int | None:
    return NATIVE.get(token) if token in NATIVE else _sino(token)


def _number_forms(token: str, loose: bool = False) -> set[str]:
    """숫자+단위 토큰의 다른 표기 — 한글 숫자 ↔ 아라비아 숫자, 시월·유월. 단위 없는 숫자나 숫자 아닌 토큰은 빈 집합.

    한글 숫자 쪽은 단위에 맞는 읽기(날짜·돈은 일이삼, 시각·개수는 하나둘셋)만 만들고, 숫자 부분이 한 음절인 한글
    표기("이 장"·"사 일")는 낱말 속 우연 일치("당신이 장비"·"회사 일")가 많아 원래 그렇게 적혔거나 다른 숫자
    토큰과 붙어 나올 때(`loose`, "구월 사 일")만 쓴다."""
    month = {name: n for n, name in MONTH_NAMES.items()}
    if token in month:
        n, unit = month[token], "월"
    elif m := re.fullmatch(r"(\d+)(만?)(\D+)", token):
        n, unit = int(m.group(1)) * (10000 if m.group(2) else 1), m.group(3)
        if unit not in COUNTERS:
            return set()
    else:
        for cut in range(len(token) - 1, 0, -1):
            head, unit = token[:cut], token[cut:]
            if unit in COUNTERS and (got := _pure_number(head)) is not None:
                n = got
                break
        else:
            return set()
    forms = {token, f"{n}{unit}"}
    if n % 10000 == 0:
        forms.add(f"{n // 10000}만{unit}")
    spoken = [_to_sino(n)] if unit in SINO_COUNTERS else [k for k, v in NATIVE.items() if v == n]
    forms |= {k + unit for k in spoken if loose or len(k) > 1}
    if unit == "월" and n in MONTH_NAMES:
        forms.add(MONTH_NAMES[n])
    return forms


def _tokens(word: str) -> list[str]:
    """띄어 쓴 숫자와 단위("이십칠 일")는 한 토큰으로 붙인다."""
    out: list[str] = []
    for tok in unicodedata.normalize("NFC", word).casefold().split():
        if out and tok in COUNTERS and _pure_number(out[-1]) is not None:
            out[-1] += tok
        else:
            out.append(tok)
    return out


_PATTERNS: dict[str, re.Pattern[str]] = {}


def _pattern(word: str) -> re.Pattern[str]:
    """낱말 표기 변형을 받는 정규식 — 띄어쓰기 무시, 숫자 표기 변형, 여러 토큰 사이 한 글자 끼움(조사·접미)."""
    if word not in _PATTERNS:
        parts: list[str] = []
        numeric: list[bool] = []
        toks = _tokens(word)
        loose = sum(1 for tok in toks if _number_forms(tok)) > 1
        for tok in toks:
            forms = _number_forms(tok, loose)
            numeric.append(bool(forms))
            alts = sorted(forms or {tok}, key=len, reverse=True)
            parts.append("(?:" + "|".join(re.escape(a) for a in alts) + ")")
        body = ""
        for i, part in enumerate(parts):
            if i:
                body += "" if numeric[i] or numeric[i - 1] else ".?"
            body += part
        lead = r"(?<!\d)" if numeric and numeric[0] else ""
        _PATTERNS[word] = re.compile(lead + body)
    return _PATTERNS[word]


def flat(text: str) -> str:
    return re.sub(r"(?<=\d),(?=\d)", "", norm(text))


def found(hay_flat: str, word: str) -> bool:
    return bool(norm(word)) and bool(_pattern(word).search(hay_flat))


def status_of(text: str) -> dict[str, str]:
    m = re.search(r"```(?:text)?\n?(.*?)```", text, flags=re.S)
    out: dict[str, str] = {}
    if m:
        for line in m.group(1).strip().splitlines():
            key, sep, value = line.partition("|")
            if sep:
                out[key.strip()] = value.strip()
    return out


def short(name: str) -> str:
    return name[-2:] if len(name) == 3 else name


def _strip_status(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.S)


def segments(text: str, mode: str) -> list[tuple[str, str]]:
    """(지문 narr | 대사 dial, 글) 조각. 상태창 코드 블록은 뺀다."""
    body = _strip_status(text)
    if mode == "asterisk":
        return [("narr" if i % 2 else "dial", part) for i, part in enumerate(body.split("*"))]
    out: list[tuple[str, str]] = []
    for i, part in enumerate(re.split(r"[\u201c\u201d\"]", body)):
        out.append(("dial" if i % 2 else "narr", part.replace("*", "")))
    return out


def where(text: str, word: str, mode: str) -> set[str]:
    return {kind for kind, part in segments(text, mode) if contains(part, word)}


def placements(e: dict[str, Any]) -> list[tuple[dict[str, Any], list[str], str]]:
    """(사건, 핵심어들, 있어야 할 자리). 사용자 줄 사건은 늘 asterisk 표기로 본다."""
    cat, ps = e["category"], e["plants"]
    if cat in ("relation", "secret"):
        return [(p, p["keywords"], "narr") for p in ps]
    if cat == "correction" and len(ps) == 2:
        new = [k for k in ps[1]["keywords"] if k not in ps[0]["keywords"]]
        return [(ps[0], ps[0]["keywords"], "dial"), (ps[1], new, "narr")]
    if cat == "speaker" or (cat == "false_premise" and e["subtype"] == "character_claim"):
        return [(ps[0], ps[0]["keywords"], "dial")]
    if cat in ("detail", "rephrase"):
        fact = e.get("expected_fact") or {}
        want = "narr" if fact.get("truth_status") == "confirmed" else "dial"
        return [(ps[0], ps[0]["keywords"], want)]
    return []


def load_rows(folder: Path, upto: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for n in range(1, upto + 1):
        path = folder / f"chunk-{n:02d}.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


BUNDLE_KEYS = ("bundles", "reject_bundles", "accept_bundles", "leak_bundles")


def bundle_words(e: dict[str, Any], keys: tuple[str, ...] = BUNDLE_KEYS) -> list[str]:
    key = e.get("answer_key") or {}
    return sorted({w for k in keys for b in key.get(k) or [] for w in b})


def _scan(rows: list[dict[str, Any]]) -> tuple[dict[int, str], dict[int, str]]:
    """턴마다 (상태창 뺀 본문, 상태창) — 둘 다 표기 변형 비교용으로 펴 둔다."""
    body, box = {}, {}
    for r in rows:
        t = int(r["turn"])
        body[t] = flat(r["user"] + "\n" + _strip_status(r["assistant"]))
        box[t] = flat("\n".join(status_of(r["assistant"]).values()))
    return body, box


def is_common(word: str, body: dict[int, str]) -> bool:
    """한 음절이거나 대본 여러 턴에 두루 나오는 낱말 — 기억 없이 우연히 맞을 수 있는 일반어."""
    return len(norm(word)) <= 1 or sum(1 for text in body.values() if found(text, word)) >= COMMON_TURNS


def answer_window_hits(e: dict[str, Any], body: dict[int, str], box: dict[int, str]) -> dict[str, dict[int, list[int]]]:
    """체크포인트 원문 창 [CP−29, CP] 안, 심은 턴 밖에서 이 항목이 묻는 값(정답 묶음·거짓 전제 묶음)의 낱말이 나온 턴.

    원문 창은 기억 없이 그대로 보이므로 여기 나온 정답 낱말은 회상이 아니라 읽기로 맞힌다 — 흔한 낱말이어도 같다.
    한 음절 낱말만 뺀다(어느 글에나 들어 있다). 누출·옛 값 묶음은 정답을 주지 않으므로 여기서 세지 않는다."""
    planted = {int(p["turn"]) for p in e["plants"]}
    words = [x for x in bundle_words(e, ("bundles", "accept_bundles")) if len(norm(x)) > 1]
    out: dict[str, dict[int, list[int]]] = {"body": {}, "status": {}}
    for cp in e.get("ask_checkpoints") or []:
        span = [t for t in range(int(cp) - RAW_WINDOW, int(cp) + 1) if t in body and t not in planted]
        for kind, texts in (("body", body), ("status", box)):
            hits = [t for t in span if any(found(texts[t], x) for x in words)]
            if hits:
                out[kind][int(cp)] = hits
    return out


def check_warnings(raw: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """측정을 무효로 만들지는 않지만 사람이 볼 것 — 종료 코드에 넣지 않고, 확인을 마친 것은 `review.json` 으로 뺀다."""
    w: dict[str, list[str]] = defaultdict(list)
    body, box = _scan(rows)
    for e in raw.get("plants", []):
        iid = str(e["id"])
        planted = {int(p["turn"]) for p in e["plants"]}
        cps = [int(c) for c in e.get("ask_checkpoints") or []]
        if not cps:
            continue
        # 묶음이 없는 항목(판정자 채점)은 핵심어 구를 낱말로 쪼개 본다 — 묶음이 있으면 그 낱말이 채점 기준이다.
        words = bundle_words(e) or sorted({x for k in e.get("keywords") or [] for x in k.split()})
        words = [x for x in words if not is_common(x, body)]
        flagged = {t for got in answer_window_hits(e, body, box).values() for ts in got.values() for t in ts}
        again = [
            t
            for t in sorted(body)
            if min(planted) < t <= max(cps)
            and t not in planted
            and t not in flagged
            and any(found(body[t] + "\n" + box[t], x) for x in words)
        ]
        if again:
            w["심기 뒤 묶음 낱말 재등장(사람 확인)"].append(f"{iid} 턴{again}")
        for b in (e.get("answer_key") or {}).get("bundles") or []:
            if b and all(is_common(x, body) for x in b):
                w["정답 묶음이 흔한 낱말뿐(사람 확인)"].append(iid)
                break
    return dict(w)


def check(
    raw: dict[str, Any], work_text: str, rows: list[dict[str, Any]], upto: int, status: bool, markup: str
) -> dict[str, list[str]]:
    v: dict[str, list[str]] = defaultdict(list)
    last_turn = upto * CHUNK
    turns = [int(r["turn"]) for r in rows]
    if turns != list(range(1, last_turn + 1)):
        v["턴 연속성"].append(f"{len(turns)}줄, 기대 1~{last_turn}")
    by_turn = {int(r["turn"]): r for r in rows}
    for t, r in by_turn.items():
        if not USER_LEN[0] <= len(r["user"]) <= USER_LEN[1]:
            v["사용자 줄 길이"].append(f"턴{t} {len(r['user'])}")
        n = sum(1 for c in r["assistant"] if not c.isspace())
        if not NARRATOR_LEN[0] <= n <= NARRATOR_LEN[1]:
            v["진행자 줄 길이"].append(f"턴{t} {n}")
        if status and list(status_of(r["assistant"])) != STATUS_KEYS:
            v["상태창 형식"].append(f"턴{t}")
    whole = {t: r["user"] + "\n" + r["assistant"] for t, r in by_turn.items()}
    items = list(raw.get("plants", []))
    for e in items:
        iid = str(e["id"])
        planted = {int(p["turn"]) for p in e["plants"]}
        for p in e["plants"]:
            t = int(p["turn"])
            if t in by_turn:
                for word in p["keywords"]:
                    if not contains(by_turn[t][p["line"]], word):
                        v["심는 줄에 핵심어 없음"].append(f"{iid} 턴{t}")
        for p, words, want in placements(e):
            t = int(p["turn"])
            if t not in by_turn:
                continue
            mode = "asterisk" if p["line"] == "user" else markup
            for word in words:
                got = where(by_turn[t][p["line"]], word, mode)
                if want not in got or (want == "dial" and "narr" in got):
                    v["핵심어 자리(확정=지문·주장=대사)"].append(f"{iid} 턴{t} 기대 {want} 실제 {sorted(got)}")
        if e["category"] == "false_premise" and e["subtype"] == "user_lie":
            t = int(e["plants"][0]["turn"])
            if t in by_turn and "narr" not in where(by_turn[t]["user"], str(e.get("truthCue", "")), "asterisk"):
                v["사용자 거짓말 진실 단서가 사용자 지문에 없음"].append(f"{iid} 턴{t}")
        for word in e.get("keywords") or []:
            seen = [t for t in sorted(whole) if contains(whole[t], word)]
            extra = [t for t in seen if t not in planted]
            if extra:
                v["핵심어 재등장"].append(f"{iid} 턴{extra}")
            for cp in e.get("ask_checkpoints") or []:
                inside = [t for t in extra if cp - RAW_WINDOW <= t <= cp]
                if inside:
                    v["체크포인트 원문 창 안 재등장"].append(f"{iid} CP{cp} 턴{inside}")
            if contains(work_text, word):
                v["작품 글에 핵심어"].append(iid)
        if e["category"] == "secret" and e.get("unawareCharacter"):
            first = min(planted)
            name = short(str(e["unawareCharacter"]))
            terms = list(e.get("keywords") or []) + [w for b in e["answer_key"].get("leak_bundles") or [] for w in b]
            for t in sorted(whole):
                if t > first and contains(whole[t], name):
                    hits = [w for w in terms if contains(whole[t], w)]
                    if hits:
                        v["비밀 뒤 모르는 인물 턴에 단서(사람 확인)"].append(f"{iid} 턴{t}")
    for e in raw.get("abstains", []):
        for word in e.get("banned") or []:
            seen = [t for t in sorted(whole) if contains(whole[t], word)]
            if seen:
                v["기권 금지 낱말"].append(f"{e['id']} 턴{seen}")
    body, box = _scan(rows)
    for e in items:
        iid = str(e["id"])
        window = answer_window_hits(e, body, box)
        for cp, hits in window["body"].items():
            v["체크포인트 원문 창 안 정답 낱말"].append(f"{iid} CP{cp} 턴{hits}")
        for cp, hits in window["status"].items():
            v["체크포인트 원문 창 안 상태창에 정답 낱말"].append(f"{iid} CP{cp} 턴{hits}")
        ps = e["plants"]
        if e["category"] == "correction" and len(ps) == 2:
            t = int(ps[1]["turn"])
            old = bundle_words(e, ("reject_bundles",)) + [k for k in ps[0]["keywords"] if k not in ps[1]["keywords"]]
            if t in body and any(found(body[t] + "\n" + box[t], x) for x in old if len(norm(x)) > 1):
                v["정정 턴에 옛 값 낱말"].append(f"{iid} 턴{t}")
    watched = sorted({w for e in items for w in list(e.get("keywords") or []) + list(e.get("cueNouns") or [])})
    for cp in CHECKPOINTS:
        if cp in by_turn:
            hits = [w for w in watched if contains(by_turn[cp]["assistant"], w)]
            if hits:
                v["체크포인트 진행자 줄에 핵심어·단서"].append(f"CP{cp} {len(hits)}개")
    if last_turn >= 300 and len(by_turn) >= 300:
        lens = [len(by_turn[t]["user"]) + len(by_turn[t]["assistant"]) for t in range(1, 301)]
        top = max(sum(lens[i : i + 30]) for i in range(len(lens) - 29))
        if top >= FOLD_CHARS:
            v["연속 30턴 글자 합"].append(str(top))
    return dict(v)


def main() -> int:
    plants_path, work_path, folder = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    upto = int(sys.argv[sys.argv.index("--upto") + 1])
    raw = json.loads(plants_path.read_text(encoding="utf-8"))
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

    walk(json.loads(work_path.read_text(encoding="utf-8")))
    markup = sys.argv[sys.argv.index("--markup") + 1]
    if markup not in ("asterisk", "quotes"):
        raise SystemExit("--markup 은 asterisk 또는 quotes")
    rows = load_rows(folder, upto)
    report = check(raw, "\n".join(parts), rows, upto, "--status" in sys.argv, markup)
    review = folder / "review.json"
    allowed = (
        {(r["rule"], r["entry"]) for r in json.loads(review.read_text(encoding="utf-8"))} if review.exists() else set()
    )

    def show(by_rule: dict[str, list[str]]) -> dict[str, list[str]]:
        left = {k: kept for k, hits in by_rule.items() if (kept := [h for h in hits if (k, h) not in allowed])}
        for rule, hits in left.items():
            print(f"{rule}: {len(hits)}")
            for hit in hits[:40]:
                print("   ", hit)
        return left

    report = show(report)
    print("위반", sum(len(h) for h in report.values()))
    warned = show(check_warnings(raw, rows))
    print("경고", sum(len(h) for h in warned.values()))
    return 1 if report else 0


if __name__ == "__main__":
    sys.exit(main())
