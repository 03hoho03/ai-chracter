"""보완판 리플레이(날짜·날 넘김) 분석기 — 생성 리플레이 기록의 응답마다 상태창·날수 문구·날짜를 읽어 갈래별로 센다.

    uv run python scripts/experiments/filmclub_longturn/s3_date_analysis.py \\
        --turns-json <측정>/analysis/final/turns.json --gen '<run>/replay/gen-main-*.jsonl' \\
        [--table] [--out <run>/s3/analysis.json]

`--table` 은 응답 없이 턴별 기준 날짜 표만 낸다(사전 등록용). 갈래는 기록의 `variant` 와 `swapLabel` 로 나눈다(window =
v6-fix, supplement + W/N = 보완판 두 안).

읽는 것(응답마다):
- 장면 머리 날수 문구: 상태창을 뺀 본문의 문단(빈 줄로 나눔) 가운데, 지문 표시(`*`)와 공백을 걷은 문단 앞
  `LEAD_CHARS` 글자 안에 있는 날수 문구 — 응답은 앞 장면을 마무리한 뒤 새 문단에서 「사흘 뒤, 금요일 저녁.」처럼 장면을
  옮긴다. 그 밖 자리(대사 속 등)의 날수 문구는 세지 않고 `otherPhrases` 로 남겨 사람이 읽는다.
- 날 이동: 직전 턴 상태창(고정 히스토리)에서 요일이 바뀌었거나, 요일은 같은데 때가 앞으로 돌아갔거나(오후 → 아침 —
  밤을 넘긴 것. 밤 → 새벽은 같은 밤으로 본다), 장면 머리 날수 문구가 있으면 날이 바뀐 것으로 본다. 상태창에 요일이
  없으면 문구로만 보고 `weekdayMissing`.
- 무문구 이동: 요일·때로 날이 바뀌었는데 장면 머리 날수 문구가 없다.
- 상태창 형식 결함: 상태창 없음, 네 줄·이름·순서가 아님, 마지막 블록이 아님, 날짜(「n월 n일」)를 뺀 아라비아 숫자.
- 날짜: `시간` 줄의 「n월 n일」. 요일 정합은 2025년 달력. 기준 날짜는 두 가지 — 본문 기준(9월 22일 + 히스토리 응답의
  날수 문구 누적)과 요일 사슬 기준(9월 22일 + 히스토리 상태창 요일 이동 누적). 응답의 기대 날짜 = 기준 + 그 응답의 이동
  날수(앞머리 문구의 날수, 없으면 요일 이동 칸 수, 둘 다 없으면 0).
"""

import argparse
import glob
import json
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.filmclub_longturn import longturn_text as lt

START = date(2025, 9, 22)
LEAD_CHARS = 12
# 때의 순서 — 같은 요일에서 앞 순서로 돌아가면 밤을 넘긴 것. 새벽은 밤 뒤로도 같은 요일 표기가 흔해 셈에서 뺀다.
PERIODS = ("아침", "오전", "낮", "점심", "오후", "저녁", "밤")
SAHEUL = "사흘"
# 전개 예시 상태창의 날짜(보완판). 이 날짜가 기대 날짜가 아닌데 나오면 예시를 베낀 것으로 의심한다.
EXAMPLE_DATES = {(9, 30), (10, 16), (10, 18)}
# 날 넘김 턴에서 사용자가 말로 정한 다음 일정까지의 날수(사용자 메시지 판독 — 사전 등록에 근거를 적는다).
INTENDED_DAYS = {8: 2, 22: 1, 38: 1, 74: 1, 88: 3, 95: 1, 105: 1}
DAY_TURNS = (8, 22, 38, 74, 88, 95, 105)
CONTROL_TURNS = (21, 60, 61, 73, 94)
_DATE = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")
WEEKDAY_NAMES = "월화수목금토일"


def _rows(turns_json: Path) -> dict[int, dict[str, Any]]:
    return {row["turn"]: row for row in json.loads(turns_json.read_text(encoding="utf-8"))}


def base_dates(rows: dict[int, dict[str, Any]], turn: int) -> dict[str, Any]:
    """턴 `turn` 의 사용자 메시지 직전까지 히스토리로 본 기준 날짜 두 가지와 직전 상태창 요일."""
    body_days = 0
    chain_days = 0
    previous = "월"  # 오프닝 상태창
    previous_time = "월요일 저녁"
    for t in range(1, turn):
        row = rows[t]
        body_days += sum(p["days"] for p in row.get("dayPhrases") or [] if p.get("days"))
        if row.get("weekday"):
            chain_days += lt.weekday_step(previous, row["weekday"]) or 0
            previous = row["weekday"]
            previous_time = row["statusTime"]
    body = START + timedelta(days=body_days)
    chain = START + timedelta(days=chain_days)
    return {
        "turn": turn,
        "previousWeekday": previous,
        "previousTime": previous_time,
        "bodyBase": body.isoformat(),
        "bodyBaseWeekday": WEEKDAY_NAMES[body.weekday()],
        "chainBase": chain.isoformat(),
        "chainBaseWeekday": WEEKDAY_NAMES[chain.weekday()],
    }


def _lead_and_other(reply: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    body = lt.strip_status(reply).strip()
    lead: list[dict[str, Any]] = []
    for paragraph in re.split(r"\n\s*\n", body):
        head = paragraph.strip().lstrip("*").strip()[:LEAD_CHARS]
        lead += lt.day_phrases(head)
    other = lt.day_phrases(body)
    for phrase in lead:  # 장면 머리 것은 빼고 남은 것만 사람 판독 목록으로
        for i, candidate in enumerate(other):
            if candidate["text"] == phrase["text"]:
                del other[i]
                break
    return lead, other


def period(time_value: str | None) -> int | None:
    """`시간` 값의 때 순서(마지막에 나온 때 낱말). 새벽·없음은 None."""
    found = [(time_value.rfind(word), i) for i, word in enumerate(PERIODS) if time_value and word in time_value]
    return max(found)[1] if found else None


def read_reply(reply: str, turn: int, base: dict[str, Any]) -> dict[str, Any]:
    status = lt.status_metrics(reply)
    time_value = lt.status_field(status, "시간") if status.present else None
    weekday = lt.weekday(status) if status.present else None
    step = lt.weekday_step(base["previousWeekday"], weekday)
    if step == 0:
        before, after = period(base["previousTime"]), period(time_value)
        if before is not None and after is not None and after < before:
            step = 1  # 같은 요일 표기로 때가 앞으로 돌아갔다 — 밤을 넘겼다(7일 넘김은 문구로 잡는다)
    lead, other = _lead_and_other(reply)
    lead_days = next((p["days"] for p in lead if p["days"] is not None), None)
    moved = bool(lead) or bool(step)
    date_match = _DATE.search(time_value or "")
    non_date_digits = [line for line in status.lines if lt._DIGIT.search(_DATE.sub("", line))]
    defects = []
    if not status.present:
        defects.append("상태창 없음")
    else:
        if not status.fmt_ok:
            defects.append("네 줄·이름 아님")
        if not status.pos_end or status.other_blocks:
            defects.append("마지막 블록 아님")
        if non_date_digits:
            defects.append("날짜 밖 숫자")
    record: dict[str, Any] = {
        "turn": turn,
        "time": time_value,
        "weekday": weekday,
        "weekdayStep": step,
        "weekdayMissing": status.present and weekday is None,
        "leadPhrases": [p["text"] for p in lead],
        "leadDays": lead_days,
        "otherPhrases": [p["text"] for p in other],
        "moved": moved,
        "unmarkedMove": bool(step) and not lead,
        "saheul": any(SAHEUL in p["text"] for p in lead),
        "defects": defects,
        "date": None,
    }
    if date_match:
        month, day = int(date_match.group(1)), int(date_match.group(2))
        try:
            written = date(2025, month, day)
        except ValueError:
            written = None
        advance = lead_days if lead_days is not None else (step or 0)
        expected_body = date.fromisoformat(base["bodyBase"]) + timedelta(days=advance)
        expected_chain = date.fromisoformat(base["chainBase"]) + timedelta(days=advance)
        record["date"] = {
            "text": date_match.group(0),
            "valid": written is not None,
            "calendarWeekday": WEEKDAY_NAMES[written.weekday()] if written else None,
            "weekdayMatches": written is not None and weekday == WEEKDAY_NAMES[written.weekday()],
            "advance": advance,
            "expectedBody": expected_body.isoformat(),
            "matchesBody": written == expected_body,
            "expectedChain": expected_chain.isoformat(),
            "matchesChain": written == expected_chain,
            "exampleCopy": (month, day) in EXAMPLE_DATES and written not in (expected_body, expected_chain),
        }
    return record


def arm_of(record: dict[str, Any]) -> str:
    if record["variant"] == "window":
        return "v6fix"
    return f"{record['variant']}-{record.get('swapLabel')}"


def _ratio(n: int, d: int) -> dict[str, Any]:
    return {"n": n, "of": d, "rate": round(n / d, 3) if d else None}


def summarize(reads: list[dict[str, Any]]) -> dict[str, Any]:
    day = [r for r in reads if r["turn"] in DAY_TURNS]
    control = [r for r in reads if r["turn"] in CONTROL_TURNS]
    with_lead = [r for r in day if r["leadPhrases"]]
    known_intent = [r for r in with_lead if r["leadDays"] is not None]
    dated = [r for r in reads if r["date"]]
    with_status = [r for r in reads if "상태창 없음" not in r["defects"]]
    return {
        "replies": len(reads),
        "item1_saheulShare": _ratio(sum(r["saheul"] for r in with_lead), len(with_lead)),
        "item1_overJump": _ratio(
            sum(r["leadDays"] > INTENDED_DAYS[r["turn"]] for r in known_intent), len(known_intent)
        ),
        "item1_intendedDays": _ratio(
            sum(r["leadDays"] == INTENDED_DAYS[r["turn"]] for r in known_intent), len(known_intent)
        ),
        "dayTurns_leadPhrase": _ratio(len(with_lead), len(day)),
        "dayTurns_moved": _ratio(sum(r["moved"] for r in day), len(day)),
        "item2_unmarkedOfMoved": _ratio(sum(r["unmarkedMove"] for r in reads), sum(r["moved"] for r in reads)),
        "item3a_datePresent": _ratio(len(dated), len(with_status)),
        "item3b_weekdayMatches": _ratio(sum(r["date"]["weekdayMatches"] for r in dated), len(dated)),
        "item3c_matchesBody": _ratio(sum(r["date"]["matchesBody"] for r in dated), len(dated)),
        "item3c_matchesChain": _ratio(sum(r["date"]["matchesChain"] for r in dated), len(dated)),
        "exampleDateCopies": sum(r["date"]["exampleCopy"] for r in dated),
        "item4_controlMoved": _ratio(sum(r["moved"] for r in control), len(control)),
        "item5_defects": _ratio(sum(bool(r["defects"]) for r in reads), len(reads)),
        "weekdayMissing": sum(r["weekdayMissing"] for r in reads),
        "otherPhrasesToRead": sum(bool(r["otherPhrases"]) for r in reads),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns-json", required=True)
    ap.add_argument("--gen", action="append", default=[], help="생성 리플레이 기록 glob(여럿 가능)")
    ap.add_argument("--table", action="store_true", help="턴별 기준 날짜 표만 낸다")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    rows = _rows(Path(args.turns_json))
    turns = sorted({*DAY_TURNS, *CONTROL_TURNS})
    bases = {t: base_dates(rows, t) for t in turns}
    if args.table:
        for t in turns:
            print(json.dumps({**bases[t], "intendedDays": INTENDED_DAYS.get(t)}, ensure_ascii=False))
        return 0
    reads_by_arm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pattern in args.gen:
        for path in sorted(glob.glob(pattern, recursive=True)):
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                if record.get("kind") != "call" or record.get("error") or not record.get("reply"):
                    continue
                read = read_reply(record["reply"], record["turn"], bases[record["turn"]])
                read.update({"rep": record["rep"], "source": Path(path).name})
                reads_by_arm[arm_of(record)].append(read)
    result = {
        "summary": {arm: summarize(reads) for arm, reads in sorted(reads_by_arm.items())},
        "reads": reads_by_arm,
    }
    print(json.dumps(result["summary"], ensure_ascii=False, indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
