"""측정 방 한 개의 턴 로그를 기계 지표로 집계한다. LLM 호출 없음. DB 는 `export-frame` 만 읽는다.

    cd apps/api
    # 1) 방이 고정된 버전의 작품 글을 한 번 내보낸다(읽기만).
    uv run --env-file .env python scripts/experiments/filmclub_longturn/longturn_metrics.py \\
        export-frame --version <버전 id> --out <run>/analysis/frame.json
    # 2) 턴별 표 + 50턴 구간 요약(중간 보고서 입력).
    uv run python scripts/experiments/filmclub_longturn/longturn_metrics.py \\
        turns --log <run>/<방>.jsonl --frame <run>/analysis/frame.json --server-log <run>/server.log \\
        [--trace <run>/trace.jsonl] --out <run>/analysis
    # 3) 스토리 가이드 런의 집계 결과와 같은 값이 나오는지(정의 회귀).
    uv run python scripts/experiments/filmclub_longturn/longturn_metrics.py \\
        regress --story-guide <story-guide 런 폴더> --examples r1=<예시.json> r2=<…> r3=<…>
    # 4) 회상 프로브 후보 배제 규칙·선택, 출처 귀속, 교대 인계용 직전 턴 보기.
    … probe-check --log <방.jsonl> --frame <frame.json> --candidates <후보.json> --probe-turn <T> --start-category 물건
    … probe-attribution --keys <run>/probes --dump <run>/prompt-dump.jsonl --snapshots <run>/memory-snapshots.jsonl \\
        --frame <frame.json> --room <방 id>
    … visible-tail --log <방.jsonl> --frame <frame.json> --snapshots <memory-snapshots.jsonl> --n 30

**턴 번호는 방의 `turnCount` 다**(드라이버의 클라이언트 순번이 아니다 — 사람 턴·유실 턴이 끼면 어긋난다).
생성 유실 턴은 `turnCount` 가 늘지 않으므로 시도한 번호(직전 + 1)에 놓고 채점에서 뺀다. 사람 턴(`source:
human`)·프로브 턴(`tag: 프로브`)은 표에 남기되 `scored` 를 거짓으로 둔다 — 기계 지표 분모에서 뺀다.

작품 쪽 사실(상황 노트 조건, 키워드 노트, 전개 예시, 칸 이름)은 하드코딩하지 않고 `export-frame` 이 DB 에서
내보낸 파일에서 읽는다. 상황 노트·키워드 노트 발동은 실채팅이 쓰는 함수를 그대로 불러 다시 계산한다 — 손으로
흉내 내면 조건 되읽기·정렬·금지 키워드 규칙이 어긋난다.

`gemini_usage` 줄은 같은 방 id 를 가진 줄만, 그 시각 이하로 가장 늦게 보낸 턴에 붙인다(요약 접기는 응답 뒤
백그라운드라 다음 턴을 보내기 전까지의 줄이 그 턴 몫이다). 원가는 앱 단가표(`estimate_cost_usd`)로 낸다.
"""

import argparse
import asyncio
import difflib
import hashlib
import json
import re
import statistics
import sys
import uuid
from collections import Counter
from collections.abc import Iterable
from itertools import pairwise
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# 스크립트로 실행할 때도 `scripts/` 를 패키지 기준으로 둔다(pytest·mypy 와 같은 모듈 경로).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from api.chat.ending_rules import referenced_stat_ids
from api.chat.keyword_notes import match_keyword_notes
from api.chat.prompt_builder import PromptNames
from api.chat.router import _preview_ending_rule_list_item, _situation_note_texts
from api.content.author_macros import expand_author_macros, resolve_user_name
from api.content.schemas import RULE_LIST_ADAPTER
from api.content.media_tags import media_tag_refs
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.story import KeywordNote
from api.llm.pricing import estimate_cost_usd
from experiments.filmclub_longturn import longturn_text as text_rules

COUNTDOWN = "상영회까지"
AFFECTIONS = ("도희 호감도", "유나 호감도", "세빈 호감도")
BIN = 50
LCS_MIN = 15
# 키워드 노트 유지 범위를 넘는 만큼만 거슬러 보면 되지만, 요약이 덮지 않는 원문 윈도(20턴 이상)보다 짧게 잡아
# 모델이 보지 못한 옛 글로 노트가 열리지 않게 한다.
KEYWORD_HISTORY_MESSAGES = 40
_KV = re.compile(r"(\w+)=(\S+)")
_ISO_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?[+-]\d{4})\s")
_FAILURE_KINDS = (
    ("요약 접기 실패", "summary_fold"),
    ("미디어 북 칸 판정 실패", "media_book_judgment"),
    ("스탯 판정 실패", "stat_judgment"),
    ("메시지 생성 실패", "generation"),
    ("판정 실패", "judgment"),
)


# ---------------------------------------------------------------- 작품 글 내보내기


async def export_frame(db: Any, version_id: uuid.UUID) -> dict[str, Any]:
    """방이 고정된 버전의 작품 글 중 집계가 읽는 것만. 시작설정은 하나라고 본다(측정 작품이 그렇다)."""
    from sqlalchemy import or_, select

    from api.db.models.story import (
        MediaBookCell,
        MediaBookPerson,
        MediaBookScene,
        SituationNote,
        StartingSetup,
        StatDef,
        StoryVersionDetail,
    )

    detail = await db.get(StoryVersionDetail, version_id)
    (setup,) = (await db.scalars(select(StartingSetup).where(StartingSetup.content_version_id == version_id))).all()
    stats = (
        await db.scalars(select(StatDef).where(StatDef.starting_setup_id == setup.id).order_by(StatDef.order))
    ).all()
    situation = (
        await db.scalars(
            select(SituationNote)
            .where(SituationNote.starting_setup_id == setup.id)
            .order_by(SituationNote.order, SituationNote.entity_id)
        )
    ).all()
    keyword = (
        await db.scalars(
            select(KeywordNote)
            .where(
                KeywordNote.content_version_id == version_id,
                or_(KeywordNote.starting_setup_id.is_(None), KeywordNote.starting_setup_id == setup.id),
            )
            .order_by(KeywordNote.order, KeywordNote.entity_id)
        )
    ).all()
    people = {
        p.entity_id: p.name
        for p in (await db.scalars(select(MediaBookPerson).where(MediaBookPerson.content_version_id == version_id)))
    }
    scenes = {
        s.entity_id: s.name
        for s in (await db.scalars(select(MediaBookScene).where(MediaBookScene.content_version_id == version_id)))
    }
    cells = (await db.scalars(select(MediaBookCell).where(MediaBookCell.content_version_id == version_id))).all()
    return {
        "versionId": str(version_id),
        "name": detail.name,
        "defaultUserName": detail.default_user_name,
        "settingText": detail.setting_text or "",
        "examples": [str(pair.get("assistantLine") or "") for pair in detail.development_examples],
        "setup": {
            "id": str(setup.id),
            "name": setup.name,
            "prologue": setup.prologue,
            "openingMessage": setup.opening_message or "",
        },
        "stats": [
            {"id": str(s.entity_id), "name": s.name, "min": s.min_value, "max": s.max_value, "initial": s.initial_value}
            for s in stats
        ],
        "situationNotes": [
            {"id": str(n.entity_id), "name": n.name, "infoText": n.info_text, "conditionRules": n.condition_rules}
            for n in situation
        ],
        "keywordNotes": [
            {
                "id": str(n.entity_id),
                "name": n.name,
                "infoText": n.info_text,
                "triggerKeywords": list(n.trigger_keywords),
                "excludeKeywords": list(n.exclude_keywords),
                "stickyTurns": n.sticky_turns,
                "alwaysOn": n.always_on,
                "order": n.order,
            }
            for n in keyword
        ],
        "cells": {
            str(c.entity_id): f"{people.get(c.person_entity_id, '?')}/{scenes.get(c.scene_entity_id, '?')}"
            for c in cells
        },
    }


# ---------------------------------------------------------------- 재계산(앱 함수)


class Frame:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.stat_id_by_name = {s["name"]: s["id"] for s in data["stats"]}
        self.names = PromptNames(persona_name=None, default_user_name=data["defaultUserName"], char_name=None)
        # 실채팅과 같은 (조건, 본문) 쌍. 본문으로 이름을 되찾는다.
        self.situation = [
            (RULE_LIST_ADAPTER.validate_python(note["conditionRules"]), note["infoText"])
            for note in data["situationNotes"]
        ]
        self.situation_name = {note["infoText"]: note["name"] for note in data["situationNotes"]}
        # 단계 노트 = 조건이 「상영회까지」 하나만 가리키는 노트(호감 노트와 가른다).
        countdown_id = self.stat_id_by_name.get(COUNTDOWN)
        self.stage_names = {
            self.situation_name[info]
            for rules, info in self.situation
            if rules
            and {str(i) for i in referenced_stat_ids([_preview_ending_rule_list_item(r) for r in rules])}
            == {countdown_id}
        }
        self.keyword_notes = [
            KeywordNote(
                entity_id=uuid.UUID(note["id"]),
                name=note["name"],
                info_text=note["infoText"],
                trigger_keywords=note["triggerKeywords"],
                exclude_keywords=note["excludeKeywords"],
                sticky_turns=note["stickyTurns"],
                always_on=note["alwaysOn"],
                order=note["order"],
            )
            for note in data["keywordNotes"]
        ]
        self.keyword_info = {note["id"]: note["infoText"] for note in data["keywordNotes"]}
        self.keyword_name = {note["id"]: note["name"] or note["id"] for note in data["keywordNotes"]}

    def stat_values(self, stats_by_name: dict[str, float]) -> dict[str, float]:
        return {
            self.stat_id_by_name[name]: float(v) for name, v in stats_by_name.items() if name in self.stat_id_by_name
        }

    def active_situation_notes(self, stats_by_name: dict[str, float]) -> list[str]:
        """그 스탯 값에서 실채팅이 싣는 노트의 이름(목록 순)."""
        texts = _situation_note_texts(self.situation, self.stat_values(stats_by_name))
        return [self.situation_name[text] for text in texts]

    def fired_keyword_notes(self, history: list[tuple[str, str]], user_text: str) -> list[str]:
        messages = [
            ChatMessage(
                role=ChatMessageRole.ASSISTANT if role == "assistant" else ChatMessageRole.USER, content=content
            )
            for role, content in history[-KEYWORD_HISTORY_MESSAGES:]
        ]
        notes = match_keyword_notes(self.keyword_notes, messages, user_text, names=self.names)
        return [str(note.entity_id) for note in notes]

    def render(self, content: str) -> str:
        """화면 표시와 같은 꼴: `{{user}}` 를 이름으로, id 형 그림 태그를 `[그림: 인물/장면]` 으로."""
        out = expand_author_macros(
            content, user_name=resolve_user_name(None, self.data["defaultUserName"]), char_name=None
        )
        for ref in media_tag_refs(out):
            label = self.data["cells"].get(str(ref), "?")
            out = re.sub(r"\{\{img::\s*" + re.escape(str(ref)) + r"\s*\}\}", f"[그림: {label}]", out, flags=re.I)
        return re.sub(r"\{\{img::([^{}]*)\}\}", r"[그림: \1]", out)


def longest_common(a: str, b: str) -> int:
    match = difflib.SequenceMatcher(None, a, b, autojunk=False).find_longest_match(0, len(a), 0, len(b))
    return match.size


# ---------------------------------------------------------------- 로그 읽기


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_sent_at(raw: str, tz: timezone) -> datetime:
    at = datetime.fromisoformat(raw)
    return at if at.tzinfo else at.replace(tzinfo=tz)


def parse_server_log(lines: Iterable[str], room_id: str) -> list[dict[str, Any]]:
    """이 방의 `gemini_usage`·실패 줄. 시각 접두(ISO, 오프셋 포함)가 없는 줄은 버린다."""
    out: list[dict[str, Any]] = []
    for line in lines:
        if room_id not in line:
            continue
        head = _ISO_PREFIX.match(line)
        if not head:
            continue
        at = datetime.strptime(
            head.group(1), "%Y-%m-%dT%H:%M:%S.%f%z" if "." in head.group(1) else "%Y-%m-%dT%H:%M:%S%z"
        )
        if "gemini_usage" in line:
            fields = dict(_KV.findall(line[head.end() :]))
            out.append({"kind": "usage", "at": at, **fields})
        elif "실패" in line:
            kind = next((name for phrase, name in _FAILURE_KINDS if phrase in line), "other")
            timeout = bool(re.search(r"timeout|timed out|시간 초과", line, re.I))
            out.append({"kind": "failure", "at": at, "failure": kind, "timeout": timeout})
    return out


def _int(value: str | None) -> int:
    return 0 if value is None or value == "None" else int(value)


def usage_cost(record: dict[str, Any]) -> float | None:
    return estimate_cost_usd(
        record.get("model", ""),
        input_tokens=_int(record.get("prompt_tokens")),
        cached_tokens=_int(record.get("cached_content_tokens")),
        output_tokens=_int(record.get("candidates_tokens")),
        thoughts_tokens=_int(record.get("thoughts_tokens")),
    )


def attach_log(turns: list[dict[str, Any]], records: list[dict[str, Any]], tz: timezone) -> list[dict[str, Any]]:
    """로그 줄을 그 시각 이하로 가장 늦게 보낸 턴에 붙인다. 첫 턴 전 줄은 돌려준다."""
    ordered = sorted(turns, key=lambda t: parse_sent_at(t["sentAt"], tz))
    starts = [parse_sent_at(t["sentAt"], tz) for t in ordered]
    before: list[dict[str, Any]] = []
    for record in records:
        index = None
        for i, start in enumerate(starts):
            if start <= record["at"]:
                index = i
        if index is None:
            before.append(record)
        else:
            ordered[index].setdefault("log", []).append(record)
    return before


def trace_calls(path: Path | None, room_id: str) -> tuple[dict[int, list[dict[str, Any]]], list[dict[str, Any]]]:
    """trace 의 호출별 지연·성패. 레코드에 `roomId`·`callSite`(또는 `call_site`)·`elapsedMs` 가 있는 줄만 쓴다.
    두 번째 값은 턴 번호가 없는(null) 호출 — 턴이 끝난 뒤 백그라운드로 도는 기억 요약이 그렇다. 턴에 붙이지 않고 따로 센다."""
    by_turn: dict[int, list[dict[str, Any]]] = {}
    background: list[dict[str, Any]] = []
    if path is None or not path.exists():
        return by_turn, background
    for record in read_jsonl(path):
        site = record.get("callSite") or record.get("call_site")
        if record.get("roomId") != room_id or site is None or "elapsedMs" not in record:
            continue
        call = {
            "callSite": site,
            "elapsedMs": record["elapsedMs"],
            "ok": record.get("ok", True),
            "errorType": record.get("errorType"),
            "ts": record.get("ts"),
        }
        if record.get("turn") is None:
            background.append(call)
        else:
            by_turn.setdefault(int(record["turn"]), []).append(call)
    return by_turn, background


def background_summary(calls: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """턴 번호 없는 호출의 call_site 별 지연 p50·p90·수와 실패 종류별 수."""
    by_site: dict[str, list[dict[str, Any]]] = {}
    for call in calls:
        by_site.setdefault(call["callSite"], []).append(call)
    return {
        site: {
            "p50": _pct([float(c["elapsedMs"]) for c in group], 0.5),
            "p90": _pct([float(c["elapsedMs"]) for c in group], 0.9),
            "n": len(group),
            "errors": dict(Counter(c["errorType"] or "?" for c in group if not c["ok"])),
        }
        for site, group in by_site.items()
    }


# ---------------------------------------------------------------- 턴 표


def build_turns(rows: list[dict[str, Any]], frame: Frame) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(오프닝, 턴 목록). 앱 429·409 등 http≠200 줄은 같은 발화의 재시도라 턴이 아니다."""
    opening = next(row for row in rows if row["kind"] == "opening")
    stats = dict(opening["roomAfter"]["stats"])
    turn_count = int(opening["roomAfter"]["turnCount"])
    ending_before = bool(opening["roomAfter"].get("endingReached"))
    opening_text = "\n\n".join(opening["messages"])
    previous_reply = opening_text
    history: list[tuple[str, str]] = [("assistant", opening_text)]
    previous_weekday = text_rules.weekday(text_rules.status_metrics(opening_text))
    pending_note: dict[str, Any] | None = None
    turns: list[dict[str, Any]] = []
    for row in rows:
        if row["kind"] == "noteUpdate":
            pending_note = row
            continue
        if row["kind"] != "turn" or row.get("http", 200) != 200:
            continue
        human = row.get("source") == "human"
        tag = row.get("tag")
        reply = str(row.get("reply") or "")
        lost = bool(row.get("failure")) or not reply
        after = row.get("roomAfter") or {}
        turn = turn_count + 1 if lost else int(after.get("turnCount", turn_count + 1))
        stats_before = dict(stats)
        # 생성 프롬프트는 이번 턴 판정 전 스탯으로 노트를 고른다.
        active = frame.active_situation_notes(stats_before)
        status = text_rules.status_metrics(reply)
        record: dict[str, Any] = {
            "turn": turn,
            "sentAt": row.get("sentAt"),
            "seconds": row.get("seconds"),
            "ttftMs": row.get("ttftMs"),
            "source": "human" if human else "simulator",
            "tag": tag or ("보통" if not human else None),
            "shortcut": row.get("shortcut"),
            "userLen": len(str(row.get("userText") or "")),
            "lost": lost,
            "probe": tag == "프로브",
            "scored": not (lost or human or tag == "프로브"),
            "stage": ["엔딩 뒤"] if ending_before else [n for n in active if n in frame.stage_names],
            "situationNotes": [] if ending_before else active,
            "noteUpdate": {"length": pending_note.get("length"), "sha256": pending_note.get("sha256")}
            if pending_note
            else None,
            "memory": row.get("memory"),
        }
        pending_note = None
        user_text = str(row.get("userText") or "")
        fired = frame.fired_keyword_notes(history, user_text)
        record["keywordNotes"] = [frame.keyword_name[i] for i in fired]
        if lost:
            history.append(("user", user_text))
            turns.append(record)
            continue
        new_stats = {**stats, **{k: float(v) for k, v in (after.get("stats") or {}).items()}}
        delta = {name: new_stats.get(name, 0.0) - stats_before.get(name, 0.0) for name in new_stats}
        wd = text_rules.weekday(status)
        body = text_rules.strip_status(reply)
        record.update(
            statusPresent=status.present,
            statusPosEnd=status.pos_end,
            statusFmtOk=status.fmt_ok,
            statusLines=status.lines,
            statusTime=text_rules.status_field(status, "시간"),
            statusMimic=bool(status.mimic_status),
            statusStatWord=status.statword,
            statusOtherDigit=status.digit and not status.mimic_status,
            bodyMimic=[line for line, _ in text_rules.mimic_body(reply)],
            otherBlocks=status.other_blocks,
            dup=text_rules.duplicate_spans(
                reply,
                user_text,
                {"prev": previous_reply, "opening": opening_text}
                | {f"ex{i + 1}": ex for i, ex in enumerate(frame.data["examples"])},
            ),
            labels=text_rules.labels(reply),
            replyLen=len(body.strip()),
            dayPhrases=text_rules.day_phrases(reply),
            weekday=wd,
            weekdayStep=text_rules.weekday_step(previous_weekday, wd),
            countdownBefore=stats_before.get(COUNTDOWN),
            countdownAfter=new_stats.get(COUNTDOWN),
            countdownDelta=delta.get(COUNTDOWN),
            affection={name: new_stats.get(name) for name in AFFECTIONS},
            affectionDelta={name: delta.get(name) for name in AFFECTIONS},
            imageId=row.get("imageId"),
            image=frame.data["cells"].get(str(row.get("imageId"))) if row.get("imageId") else None,
            ending=row.get("ending"),
            keywordEcho=[
                frame.keyword_name[note_id]
                for note_id in fired
                if longest_common(body, frame.names.expand(frame.keyword_info[note_id])) >= LCS_MIN
            ],
        )
        if wd is not None:
            previous_weekday = wd
        stats = new_stats
        turn_count = turn
        ending_before = ending_before or bool(after.get("endingReached"))
        previous_reply = reply
        history.extend([("user", user_text), ("assistant", reply)])
        turns.append(record)
    return opening, turns


def summarize_log(turns: list[dict[str, Any]]) -> None:
    """턴에 붙은 로그 줄을 사용량(원가 포함)과 실패 줄로 나눈다."""
    for record in turns:
        entries = record.pop("log", [])
        record["usage"] = [
            {
                "callSite": e.get("call_site"),
                "model": e.get("model"),
                "promptTokens": _int(e.get("prompt_tokens")),
                "cachedTokens": _int(e.get("cached_content_tokens")),
                "costUsd": usage_cost(e),
            }
            for e in entries
            if e["kind"] == "usage"
        ]
        record["logFailures"] = [
            {"failure": e["failure"], "timeout": e["timeout"]} for e in entries if e["kind"] == "failure"
        ]


# ---------------------------------------------------------------- 50턴 구간 요약


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def bin_summary(turns: list[dict[str, Any]], size: int = BIN) -> list[dict[str, Any]]:
    """중간 보고서가 읽는 구간 요약. 관측 없는 구간은 내지 않는다(0 이 아니라 관측 없음)."""
    out: list[dict[str, Any]] = []
    last = max((t["turn"] for t in turns), default=0)
    for start in range(1, last + 1, size):
        end = start + size - 1
        inside = [t for t in turns if start <= t["turn"] <= end]
        if not inside:
            continue
        done = [t for t in inside if not t["lost"]]
        scored = [t for t in inside if t["scored"]]
        cost: Counter[str] = Counter()
        tokens: dict[str, list[int]] = {}
        unpriced = 0
        for t in inside:
            for u in t.get("usage", []):
                if u["costUsd"] is None:
                    unpriced += 1
                else:
                    cost[u["callSite"]] += u["costUsd"]
                tokens.setdefault(u["callSite"], []).append(u["promptTokens"])
        seconds = [float(t["seconds"]) for t in done if t.get("seconds") is not None]
        images = [t["image"] for t in done if t.get("image")]
        same_image_runs = sum(1 for a, b in pairwise(done) if a.get("image") and a.get("image") == b.get("image"))
        out.append(
            {
                "bin": f"{start}-{end}",
                "turns": [t["turn"] for t in inside],
                "lost": [t["turn"] for t in inside if t["lost"]],
                "human": [t["turn"] for t in inside if t["source"] == "human"],
                "probe": [t["turn"] for t in inside if t["probe"]],
                "advanceTags": [t["turn"] for t in inside if t["tag"] == "넘김"],
                "shortcuts": dict(Counter(t["shortcut"] for t in inside if t.get("shortcut"))),
                "countdown": {
                    "first": done[0].get("countdownBefore") if done else None,
                    "last": done[-1].get("countdownAfter") if done else None,
                    "decreasedTurns": [t["turn"] for t in done if (t.get("countdownDelta") or 0) < 0],
                    "increasedTurns": [t["turn"] for t in done if (t.get("countdownDelta") or 0) > 0],
                    "nonInteger": [
                        t["turn"] for t in done if t.get("countdownAfter") is not None and t["countdownAfter"] % 1
                    ],
                },
                "affection": {name: _affection(done, name) for name in AFFECTIONS},
                "statusTime": [(t["turn"], t.get("statusTime")) for t in done],
                "weekdays": [(t["turn"], t.get("weekday")) for t in done],
                "dayPhraseTurns": [(t["turn"], [p["text"] for p in t["dayPhrases"]]) for t in done if t["dayPhrases"]],
                "stages": dict(Counter(n for t in inside for n in t["stage"])),
                "situationNotes": dict(Counter(n for t in inside for n in t["situationNotes"])),
                "keywordNotes": dict(Counter(n for t in inside for n in t["keywordNotes"])),
                "keywordEchoTurns": [t["turn"] for t in done if t.get("keywordEcho")],
                "images": {"count": len(images), "byCell": dict(Counter(images)), "sameAsPrevious": same_image_runs},
                "status": {
                    "scored": len(scored),
                    "missing": [t["turn"] for t in scored if not t.get("statusPresent")],
                    "notAtEnd": [t["turn"] for t in scored if t.get("statusPresent") and not t["statusPosEnd"]],
                    "formatBroken": [t["turn"] for t in scored if t.get("statusPresent") and not t["statusFmtOk"]],
                    "statMimic": [t["turn"] for t in scored if t.get("statusMimic") or t.get("bodyMimic")],
                    "statWord": [t["turn"] for t in scored if t.get("statusStatWord")],
                    "otherDigit": [t["turn"] for t in scored if t.get("statusOtherDigit")],
                },
                "duplicateTurns": [t["turn"] for t in scored if t.get("dup")],
                "labelTurns": [t["turn"] for t in scored if t.get("labels")],
                "replyLenMedian": statistics.median([t["replyLen"] for t in scored]) if scored else None,
                "noteUpdates": [t["turn"] for t in inside if t.get("noteUpdate")],
                "summaryChangedTurns": _summary_changes(inside),
                "logFailures": [
                    (t["turn"], f["failure"], f["timeout"]) for t in inside for f in t.get("logFailures", [])
                ],
                "costUsd": {site: round(v, 6) for site, v in cost.items()},
                "costUsdTotal": round(sum(cost.values()), 6),
                "unpricedCalls": unpriced,
                "promptTokensMax": {site: max(v) for site, v in tokens.items()},
                "secondsP50": _pct(seconds, 0.5),
                "secondsP90": _pct(seconds, 0.9),
                "secondsMax": max(seconds, default=None),
                "over60s": [t["turn"] for t in done if (t.get("seconds") or 0) > 60],
                "callLatencyMs": _latency(inside),
            }
        )
    return out


def _affection(done: list[dict[str, Any]], name: str) -> dict[str, float | None]:
    values = [(t["affection"].get(name), t["affectionDelta"].get(name)) for t in done]
    seen = [(v, d) for v, d in values if v is not None]
    if not seen:
        return {"first": None, "last": None, "maxAbsDelta": None}
    return {
        "first": seen[0][0] - (seen[0][1] or 0),
        "last": seen[-1][0],
        "maxAbsDelta": max(abs(d or 0) for _, d in seen),
    }


def _summary_changes(turns: list[dict[str, Any]]) -> list[int]:
    changed: list[int] = []
    previous = None
    for t in turns:
        memory = t.get("memory") or {}
        sha = memory.get("summarySha")
        if previous is not None and sha != previous:
            changed.append(t["turn"])
        previous = sha
    return changed


def _latency(turns: list[dict[str, Any]]) -> dict[str, dict[str, float | None]]:
    by_site: dict[str, list[float]] = {}
    for t in turns:
        for call in t.get("calls", []):
            by_site.setdefault(call["callSite"], []).append(float(call["elapsedMs"]))
    return {site: {"p50": _pct(v, 0.5), "p90": _pct(v, 0.9), "n": len(v)} for site, v in by_site.items()}


def run_turns(args: argparse.Namespace) -> None:
    tz = timezone(timedelta(hours=args.tz_hours))
    rows = read_jsonl(Path(args.log))
    frame = Frame(json.loads(Path(args.frame).read_text(encoding="utf-8")))
    meta = next((row for row in rows if row["kind"] == "meta"), {})
    room_id = str(args.room or meta["roomId"])
    _, turns = build_turns(rows, frame)
    records = (
        parse_server_log(Path(args.server_log).read_text(encoding="utf-8").splitlines(), room_id)
        if args.server_log
        else []
    )
    before = attach_log([t for t in turns if t.get("sentAt")], records, tz)
    summarize_log(turns)
    calls, background = trace_calls(Path(args.trace) if args.trace else None, room_id)
    for t in turns:
        t["calls"] = calls.get(t["turn"], [])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "turns.json").write_text(json.dumps(turns, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / "phases.json").write_text(
        json.dumps({str(t["turn"]): "/".join(t["stage"]) or "단계 노트 없음" for t in turns}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    summary: dict[str, Any] = {
        "roomId": room_id,
        "logLinesBeforeFirstTurn": len(before),
        "bins": bin_summary(turns, args.bin_size),
        "costUsdTotal": round(sum(u["costUsd"] or 0 for t in turns for u in t["usage"]), 6),
        "callsWithoutTurn": background_summary(background),
    }
    (out / "bins-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"turns": len(turns), "bins": len(summary["bins"]), "costUsdTotal": summary["costUsdTotal"]},
            ensure_ascii=False,
        )
    )


# ---------------------------------------------------------------- 정의 회귀(스토리 가이드 런)

REGRESS_KEYS = (
    "status",
    "pos_end",
    "fmt_ok",
    "status_lines",
    "digit",
    "digit_lines",
    "mimic_status",
    "statword",
    "together",
    "label",
    "other_blocks",
    "mimic_body",
    "dup",
)


def regress_turn(reply: str, user_text: str, previous: str, opening: str, examples: list[str]) -> dict[str, Any]:
    status = text_rules.status_metrics(reply)
    got: dict[str, Any] = {
        "status": status.present,
        "label": text_rules.labels(reply),
        "other_blocks": status.other_blocks,
        "mimic_body": [[line, [list(r) for r in runs]] for line, runs in text_rules.mimic_body(reply)],
        "together": text_rules.together(status),
        "dup": sorted(
            e["src"]
            for e in text_rules.duplicate_spans(
                reply,
                user_text,
                {"prev": previous, "opening": opening} | {f"ex{i + 1}": x for i, x in enumerate(examples)},
            )
        ),
    }
    if status.present:
        got.update(
            pos_end=status.pos_end,
            fmt_ok=status.fmt_ok,
            status_lines=status.lines,
            digit=status.digit,
            digit_lines=status.digit_lines,
            mimic_status=[[line, [list(r) for r in runs]] for line, runs in status.mimic_status],
            statword=status.statword,
        )
    return got


def regress_round(round_dir: Path, examples: list[str]) -> dict[str, Any]:
    """회차 폴더의 방마다 `mech.json` 의 턴 값과 같은지. 일치·불일치 수와 양성 턴 수를 지표별로."""
    mech = json.loads((round_dir / "analysis" / "mech.json").read_text(encoding="utf-8"))
    tally: dict[str, Counter[str]] = {key: Counter() for key in REGRESS_KEYS}
    mismatches: list[dict[str, Any]] = []
    for room, data in mech.items():
        rows = read_jsonl(round_dir / room / "turns.jsonl")
        opening = "\n\n".join(next(r for r in rows if r["kind"] == "opening")["messages"])
        previous = opening
        by_turn: dict[int, tuple[dict[str, Any], str]] = {}
        for row in rows:
            if row["kind"] != "turn" or row["http"] != 200 or row.get("failure") or not row.get("reply"):
                continue
            by_turn[int(row["roomAfter"]["turnCount"])] = (row, previous)
            previous = row["reply"]
        for want in data["turns"]:
            row, prev = by_turn[want["t"]]
            got = regress_turn(row["reply"], row["userText"], prev, opening, examples)
            expected = dict(want)
            expected["dup"] = sorted(e["src"] for e in want["dup"])
            for key in REGRESS_KEYS:
                if key not in expected:
                    continue
                same = got.get(key) == expected[key]
                tally[key]["match" if same else "mismatch"] += 1
                if _positive(key, expected[key]):
                    tally[key]["positive"] += 1
                if not same:
                    mismatches.append(
                        {"room": room, "t": want["t"], "key": key, "got": got.get(key), "want": expected[key]}
                    )
    return {"tally": {k: dict(v) for k, v in tally.items()}, "mismatches": mismatches}


def _positive(key: str, value: Any) -> bool:
    """정답지가 결함(또는 관심 사건)으로 표시한 값인가 — 판별력 확인의 한쪽."""
    if key in ("status", "pos_end", "fmt_ok"):
        return value is False
    if key == "together":
        return False
    return bool(value)


def run_regress(args: argparse.Namespace) -> None:
    root = Path(args.story_guide)
    report: dict[str, Any] = {}
    for spec in args.examples:
        name, path = spec.split("=", 1)
        examples = json.loads(Path(path).read_text(encoding="utf-8"))
        report[name] = regress_round(root / name, examples)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if any(r["mismatches"] for r in report.values()):
        sys.exit(1)


# ---------------------------------------------------------------- 회상 프로브 출처 귀속


def latest_snapshot(snapshots: list[dict[str, Any]], turn: int) -> dict[str, Any] | None:
    """그 턴을 보내기 직전에 남은 스냅숏 = 턴 번호가 그 턴 이하인 마지막 줄(바뀐 턴에만 남으므로)."""
    chosen = None
    for row in snapshots:
        at = row.get("turn")
        if at is not None and int(at) <= turn:
            chosen = row
    return chosen


def attribute(
    key: dict[str, Any], prompt: str | None, snapshot: dict[str, Any] | None, static_texts: list[str]
) -> dict[str, Any]:
    """대상 사실의 핵심어가 생성 프롬프트의 어느 자리에 실렸나. 노트·요약은 스냅숏 전문에서, 원문 윈도는 덤프 프롬프트에서
    노트·요약 문자열을 뺀 나머지에서 찾는다. 그 문자열을 덤프에서 그대로 찾지 못하면 귀속 불가."""
    keywords = [str(k) for k in key["keywords"]]
    result: dict[str, Any] = {"probeTurn": key["probeTurn"], "keywords": keywords}
    if prompt is None or snapshot is None:
        result["unattributable"] = "덤프 없음" if prompt is None else "스냅숏 없음"
        return result
    note = str(snapshot.get("note") or "")
    summary = str(snapshot.get("summary") or "")
    rest = prompt
    for label, piece in (("노트", note), ("요약", summary)):
        if piece.strip():
            if piece not in rest:
                result["unattributable"] = f"덤프에서 {label} 원문을 찾지 못함"
                return result
            rest = rest.replace(piece, "", 1)

    def hit(text: str) -> bool:
        return any(k in text for k in keywords)

    places = [name for name, text in (("노트", note), ("요약", summary), ("원문 윈도", rest)) if hit(text)]
    result["places"] = places or ["어디에도 없음"]
    # 작품 글(설정·노트·오프닝)에도 핵심어가 있으면 원문 윈도 자리에 작품 글이 섞였다는 표시 — 귀속 판독 때 본다.
    result["staticTextHit"] = any(hit(t) for t in static_texts)
    return result


PROBE_CATEGORIES = ("물건", "장소·일정", "약속", "털어놓은 비밀")
PROBE_WINDOW = (90, 40)  # 프로브 턴의 90턴 앞부터 40턴 앞까지
RAW_WINDOW = 29  # 원문 윈도가 실을 수 있는 최대 턴 수 — 그 안에 핵심어가 다시 나오면 회상이 아니다


def static_texts(frame: dict[str, Any]) -> list[str]:
    """작품 글 — 여기 있는 핵심어는 대화의 기억이 아니라 작품 지식이다."""
    return [frame["settingText"], frame["setup"]["openingMessage"], frame["setup"]["prologue"]] + [
        n["infoText"] for n in frame["keywordNotes"] + frame["situationNotes"]
    ]


def check_probe_candidates(
    candidates: list[dict[str, Any]],
    turn_texts: dict[int, str],
    statics: list[str],
    probe_turn: int,
    start_category: str,
) -> dict[str, Any]:
    """선정 에이전트가 낸 후보에 사전 고정 배제 규칙을 기계로 걸고, 범주 순환 순서 → 가장 이른 원천 턴으로 하나를 고른다.

    배제: 원천 턴이 프로브 턴의 90턴 앞~40턴 앞 밖 · 핵심어가 1~2개가 아님 · 핵심어가 원천 턴 글에 없음 · 핵심어가 직전 29턴 글에 다시 나옴
    (원문 윈도에 실려 회상이 아니게 된다) · 핵심어가 작품 글에 있음(대화의 기억이 아니다)."""
    low, high = probe_turn - PROBE_WINDOW[0], probe_turn - PROBE_WINDOW[1]
    recent = [turn_texts[t] for t in range(probe_turn - RAW_WINDOW, probe_turn) if t in turn_texts]
    checked = []
    for cand in candidates:
        keywords = [str(k) for k in cand.get("keywords", [])]
        source = int(cand["sourceTurn"])
        reasons = []
        if not low <= source <= high:
            reasons.append("구간 밖")
        if not 1 <= len(keywords) <= 2:
            reasons.append("핵심어 수")
        if not all(k in turn_texts.get(source, "") for k in keywords):
            reasons.append("원천 턴에 핵심어 없음")
        if any(k in text for k in keywords for text in recent):
            reasons.append("직전 29턴에 다시 나옴")
        if any(k in text for k in keywords for text in statics):
            reasons.append("작품 글에 있음")
        checked.append({**cand, "excluded": reasons})
    start = PROBE_CATEGORIES.index(start_category)
    order = PROBE_CATEGORIES[start:] + PROBE_CATEGORIES[:start]
    chosen = None
    for category in order:
        ok = [c for c in checked if c["category"] == category and not c["excluded"]]
        if ok:
            chosen = min(ok, key=lambda c: int(c["sourceTurn"]))
            break
    return {
        "probeTurn": probe_turn,
        "window": [low, high],
        "categoryOrder": list(order),
        "candidates": checked,
        "chosen": chosen,
    }


def turn_texts_from_log(rows: list[dict[str, Any]]) -> dict[int, str]:
    """턴 번호 → 그 턴의 사용자 발화 + 응답. 유실 턴·프로브 턴은 넣지 않는다(프로브는 옛 사실을 다시 꺼낸 턴이다)."""
    out: dict[int, str] = {}
    for row in rows:
        if row["kind"] != "turn" or row.get("http", 200) != 200 or row.get("failure") or not row.get("reply"):
            continue
        if row.get("tag") == "프로브":
            continue
        out[int(row["roomAfter"]["turnCount"])] = f"{row.get('userText') or ''}\n{row['reply']}"
    return out


def run_probe_check(args: argparse.Namespace) -> None:
    frame = json.loads(Path(args.frame).read_text(encoding="utf-8"))
    candidates = json.loads(Path(args.candidates).read_text(encoding="utf-8"))
    texts = turn_texts_from_log(read_jsonl(Path(args.log)))
    report = check_probe_candidates(candidates, texts, static_texts(frame), args.probe_turn, args.start_category)
    print(json.dumps(report, ensure_ascii=False, indent=1))


def run_attribution(args: argparse.Namespace) -> None:
    frame = json.loads(Path(args.frame).read_text(encoding="utf-8"))
    static = static_texts(frame)
    dumps = {int(r["turn"]): r["prompt"] for r in read_jsonl(Path(args.dump)) if r.get("roomId") == args.room}
    snapshots = read_jsonl(Path(args.snapshots))
    out = []
    for path in sorted(Path(args.keys).glob("key-t*.json")):
        key = json.loads(path.read_text(encoding="utf-8"))
        turn = int(key["probeTurn"])
        out.append(attribute(key, dumps.get(turn), latest_snapshot(snapshots, turn), static))
    print(json.dumps(out, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- 교대 인계: 직전 턴 보기


def visible_tail(rows: list[dict[str, Any]], frame: Frame, n: int) -> list[str]:
    """화면에 보였던 것만 — 사용자 발화, 응답(이름·그림 라벨 치환), 게이지. 태그·노트 갱신·기억 해시는 넣지 않는다."""
    lines: list[str] = []
    turns = [r for r in rows if r["kind"] == "turn" and r.get("http", 200) == 200]
    for row in turns[-n:]:
        after = row.get("roomAfter") or {}
        reply = row.get("display") or frame.render(str(row.get("reply") or ""))
        gauges = "  ".join(f"{k}={v:g}" for k, v in (after.get("stats") or {}).items())
        lines.append(f"[턴 {after.get('turnCount', '?')}] 나: {row.get('userText')}")
        lines.append(reply if not row.get("failure") else "(응답 없음 — 오류)")
        if gauges:
            lines.append(f"  게이지: {gauges}")
        lines.append("")
    return lines


def current_note(snapshots: list[dict[str, Any]], room_id: str) -> str:
    """그 방의 마지막 기억 스냅숏의 노트. 스냅숏 파일에는 정지·도달·방 정적 정보 줄이 섞여 있고, 정기 교대는 일시
    정지 바로 뒤라 마지막 줄이 노트 없는 정지 줄이다 — 종류와 방으로 거르지 않으면 노트가 빈 값으로 나온다."""
    note = ""
    for row in snapshots:
        if row.get("kind") == "memorySnapshot" and row.get("roomId") == room_id:
            note = str(row.get("note") or "")
    return note


def run_visible_tail(args: argparse.Namespace) -> None:
    frame = Frame(json.loads(Path(args.frame).read_text(encoding="utf-8")))
    rows = read_jsonl(Path(args.log))
    lines = visible_tail(rows, frame, args.n)
    if args.snapshots:
        room_id = str(args.room or next(row for row in rows if row["kind"] == "meta")["roomId"])
        note = current_note(read_jsonl(Path(args.snapshots)), room_id)
        lines += [
            "## 방의 현재 기억 노트(원문)",
            note or "(비어 있음)",
            f"(sha256 {hashlib.sha256(note.encode()).hexdigest()[:12]})",
        ]
    print("\n".join(lines))


# ---------------------------------------------------------------- 진입점


def run_export(args: argparse.Namespace) -> None:
    from api.db.session import async_session_factory

    async def go() -> dict[str, Any]:
        async with async_session_factory() as db:
            data = await export_frame(db, uuid.UUID(args.version))
            await db.rollback()
            return data

    data = asyncio.run(go())
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(
        f"frame: stats {len(data['stats'])} · situation {len(data['situationNotes'])} · keyword {len(data['keywordNotes'])} · cells {len(data['cells'])}"
    )


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("export-frame")
    p.add_argument("--version", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(fn=run_export)
    p = sub.add_parser("turns")
    p.add_argument("--log", required=True)
    p.add_argument("--frame", required=True)
    p.add_argument("--server-log")
    p.add_argument("--trace")
    p.add_argument("--room")
    p.add_argument("--out", required=True)
    p.add_argument("--bin-size", type=int, default=BIN)
    p.add_argument("--tz-hours", type=int, default=9, help="드라이버 sentAt 이 오프셋 없이 찍힌 시간대")
    p.set_defaults(fn=run_turns)
    p = sub.add_parser("regress")
    p.add_argument("--story-guide", required=True)
    p.add_argument("--examples", nargs="+", required=True, help="회차=전개 예시 assistantLine 목록 JSON")
    p.set_defaults(fn=run_regress)
    p = sub.add_parser("probe-attribution")
    p.add_argument("--keys", required=True)
    p.add_argument("--dump", required=True)
    p.add_argument("--snapshots", required=True)
    p.add_argument("--frame", required=True)
    p.add_argument("--room", required=True)
    p.set_defaults(fn=run_attribution)
    p = sub.add_parser("probe-check")
    p.add_argument("--log", required=True)
    p.add_argument("--frame", required=True)
    p.add_argument("--candidates", required=True)
    p.add_argument("--probe-turn", type=int, required=True)
    p.add_argument("--start-category", choices=PROBE_CATEGORIES, required=True)
    p.set_defaults(fn=run_probe_check)
    p = sub.add_parser("visible-tail")
    p.add_argument("--log", required=True)
    p.add_argument("--frame", required=True)
    p.add_argument("--snapshots")
    p.add_argument("--room", help="방 id(없으면 --log 의 meta 줄)")
    p.add_argument("--n", type=int, default=30)
    p.set_defaults(fn=run_visible_tail)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
