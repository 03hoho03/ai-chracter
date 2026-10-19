"""CP300 상영회 카운트다운 집계 — 프로브 턴마다 "상영회까지" 스탯 값과, 그 턴 생성 프롬프트에 상영회 노트 본문이 실렸는지.

두 턴(대명사) 문항에서 맥락 턴이 스탯을 0으로 내리면 질문 턴 프롬프트에 「상영회 당일」 노트가 실려 장면이 상영회 날로 바뀐다 —
회상과 무관한 장면 전환이 질문 턴 답을 흔드는지 보는 보고 항목이다. 응답 내용과 정답은 읽지 않고 스탯 값과 노트 본문의 존재만
읽으므로 두 절반을 함께 센다. 그래도 문항 이름은 개발 절반만 낸다. 노트는 이름이 아니라 본문으로 찾는다 — 프롬프트에는 노트
이름이 실리지 않는다. 갈래별로 따로 센다(기준선 단계는 `baseline` 하나, 최종 짝 비교는 A·B)."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

STAT = "상영회까지"
DAY_NOTE = "상영회 당일"
EVE_NOTE = "상영회 직전"


def note_bodies(seed_json: Path, names: Sequence[str]) -> dict[str, str]:
    """시드 작품의 상황 노트 본문(`infoText`)을 이름으로 찾는다. 시작 설정이 여럿이어도 이름이 같으면 본문이 같아야 한다."""
    seed = json.loads(seed_json.read_text(encoding="utf-8"))
    found: dict[str, str] = {}
    for setup in seed.get("startingSetups", []):
        for note in setup.get("situationNotes", []):
            if note.get("name") in names:
                body = str(note["infoText"])
                if found.setdefault(note["name"], body) != body:
                    raise SystemExit(f"같은 이름의 노트 본문이 시작 설정마다 다르다: {note['name']}")
    missing = [n for n in names if n not in found]
    if missing:
        raise SystemExit(f"시드에 노트가 없다: {missing}")
    return found


def probe_trace(row: Mapping[str, Any], bodies: Mapping[str, str], *, stat: str = STAT) -> dict[str, Any]:
    """프로브 결과 한 줄 → 턴마다 (그 턴 뒤 스탯 값, 엔딩 도달, 그 턴 생성 프롬프트에 실린 노트 이름)."""
    folder = Path(row["attempts"][-1]["folder"])
    chat = [
        json.loads(line) for line in (folder / "chat.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    prompts: dict[int, str] = {}
    for line in (folder / "prompt-dump.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip() and (dump := json.loads(line)).get("kind") == "generation":
            prompts[int(dump["turn"])] = str(dump["prompt"])
    turns = []
    for event in chat:
        if event.get("kind") != "turn":
            continue
        after = event.get("roomAfter") or {}
        value = (after.get("stats") or {}).get(stat)
        prompt = prompts.get(int(event["clientTurn"]), "")
        turns.append(
            {
                "statAfter": None if value is None else float(value),
                "ending": bool(after.get("endingReached")),
                "promptNotes": [name for name, body in bodies.items() if body in prompt],
            }
        )
    return {"arm": row["arm"], "item": row["item"], "split": row["split"], "turns": turns}


def _zero(turn: Mapping[str, Any]) -> bool:
    return turn["statAfter"] is not None and turn["statAfter"] <= 0


def screening_countdown(
    traces: Sequence[Mapping[str, Any]], *, day_note: str = DAY_NOTE, eve_note: str = EVE_NOTE
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for arm in sorted({str(t["arm"]) for t in traces}):
        mine = [t for t in traces if t["arm"] == arm]
        two = [t for t in mine if len(t["turns"]) == 2]
        context_zero = [_zero(t["turns"][0]) for t in two]
        question_day = [day_note in t["turns"][1]["promptNotes"] for t in two]
        values = sorted({turn["statAfter"] for t in mine for turn in t["turns"] if turn["statAfter"] is not None})
        out[arm] = {
            "twoTurn": {
                "n": len(two),
                "contextZero": sum(context_zero),
                "questionDayNote": sum(question_day),
                "questionEveNote": sum(eve_note in t["turns"][1]["promptNotes"] for t in two),
                "contextEveNote": sum(eve_note in t["turns"][0]["promptNotes"] for t in two),
                "matches": context_zero == question_day,
            },
            "all": {
                "n": len(mine),
                "anyTurnZero": sum(any(_zero(turn) for turn in t["turns"]) for t in mine),
                "endings": sum(any(turn["ending"] for turn in t["turns"]) for t in mine),
                "values": values,
            },
            "devTwoTurn": [
                {
                    "item": t["item"],
                    "statAfter": [turn["statAfter"] for turn in t["turns"]],
                    "questionDayNote": day_note in t["turns"][1]["promptNotes"],
                }
                for t in two
                if t["split"] == "dev"
            ],
        }
    return out
