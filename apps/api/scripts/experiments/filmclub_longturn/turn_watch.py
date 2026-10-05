"""측정 방 10턴 감시기. LLM 호출 없음, DB·Redis 는 읽기만(컨테이너 안 psql·redis-cli).

방 `turn_count` 가 10의 배수를 넘을 때마다 한 번:
  1. `longturn_metrics.py turns` 를 다시 돌려 `<run>/analysis/live/` 를 갱신한다.
  2. 원가 한 줄을 `<run>/cost.jsonl` 에 붙인다. 대화 원가는 서버 로그의 `gemini_usage` 줄 중 측정 방 id 를 가진 줄만
     센다 — 스모크 방·합성 방의 호출은 측정이 아니라서 빼야 하고, 서버 로그는 재기동에도 이어 쓰여 Redis 처럼
     재시작으로 사라지지 않는다. 리플레이 원가는 리플레이 도구가 따로 돌아 서버 로그에 없으므로 Redis 사용량 해시의
     리플레이 call_site 로 센다.
  3. 깨짐 기계 항목(B1·B2·B3·B4·B6a·B6b·B6c·B8·B9·B9.affinity·B11·B12), 조기 점검 E1·E5, 원가 정지를 판정해 `<run>/checks/tNNN.json` 을 쓰고,
     걸린 것은 `<run>/watch/alerts.jsonl` 에 남긴다. 멈춰야 하면 `<run>/STOP` 만 만든다 — 드라이버가 다음 턴을 보내기
     전에 그 파일을 보고 종료 코드 10 으로 선다. 감시기는 시뮬레이터를 직접 건드리지 않는다.

임계값은 사전 등록 문서의 깨짐 기준 표와 원가 규칙을 그대로 옮겼다. 사람 턴·프로브 턴·유실 턴은 채점에서 빠지고(연속
판정은 채점 턴 순서로), 직전 점검에서 이미 본 턴은 다시 걸지 않는다(`since`). 재개한 뒤 같은 항목을 보고만 하려면
`--report-only B3` 처럼 준다. 「상영회까지」 비정상 이동(B9)은 재개 뒤에도 매번 멈춘다 — 보고만 목록에 넣어도 풀리지
않는다. 호감 급변(B9.affinity)은 언제나 보고만 하고, 방 전체의 건수·턴 목록을 상태 파일에 누적해 둔다.

    cd apps/api
    uv run --env-file .env python scripts/experiments/filmclub_longturn/turn_watch.py run \\
        --run <run> --room <방 id> [--interval 10] [--report-only B3]
    # 한 번만(지금 turn_count 기준, 상태 파일은 그대로 갱신):
    … turn_watch.py once --run <run> --room <방 id>

중지: `touch <run>/watch/STOP-WATCH`(다음 확인 때 스스로 끝냄) 또는 `kill $(cat <run>/watch/watch.pid)`.
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from pathlib import Path
from typing import Any

# 스크립트로 실행할 때도 `scripts/` 를 패키지 기준으로 둔다(pytest·mypy 와 같은 모듈 경로).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from api.llm.pricing import estimate_cost_usd
from experiments.filmclub_longturn import longturn_metrics as metrics
from experiments.filmclub_longturn import longturn_text as text_rules

KST = timezone(timedelta(hours=9))
COUNTDOWN = "상영회까지"
STOP_ITEMS = ("B1", "B2", "B3", "B4", "B6a", "B6c", "B8", "B9", "B11", "B12", "E1", "E5")
# 장거리 n-gram 반복은 판별력이 확인되지 않은 지표라 정지 없이 보고만 한다. E1·E5 교차 확인은 정의상 본 판정을
# 대신하지 않는 보조 신호라 어긋나도 보고만 한다.
# 호감 급변은 스탯 판정이 다른 인물의 현재값을 기준으로 잘못 읽는 같은 패턴으로 두 번 확인됐다. 원인이 판명된 결함이라
# 매번 멈춰 원 출력을 볼 이유가 없어져, 방을 멈추지 않고 빈도·턴만 쌓아 중간 보고서에서 집계한다.
REPORT_ONLY_ALWAYS = ("B6b", "B9.affinity", "E1.crosscheck", "E5.crosscheck")
# 재개 뒤에도 매번 멈추는 항목. 「상영회까지」는 엔딩 시점을 정하는 값이라 비정상 이동이 그대로 방 결말을 바꾼다 —
# 보고만으로 내리지 않는다.
STOP_ALWAYS = ("B9",)
# 단계 노트 = 「상영회까지」 하나만 조건으로 가리키는 상황 노트 넷. 생성 프롬프트에는 언제나 이 중 정확히 하나가 실린다.
STAGE_NOTES = ("준비 초반", "촬영 기간", "상영회 직전", "상영회 당일")
JUDGMENT_FAILURES = {
    "chat_stat_judgment": "stat_judgment",
    "chat_media_book_image": "media_book_judgment",
    "chat_ending_judgment": "judgment",
}
REPLAY_SITES = ("replay_stat_judgment", "replay_ending_judgment", "replay_media_book_image")
CONVERSATION_STOP_USD = 10.0
TOTAL_STOP_USD = 25.0
CONVERSATION_REPORT_USD = 8.0
PG = "ai-character-chat-wt-filmclub-longturn-postgres-1"
REDIS = "ai-character-chat-wt-filmclub-longturn-redis-1"
USAGE_SINCE_DAY = "2026-10-05"

Turn = dict[str, Any]


def _scored(turns: list[Turn]) -> list[Turn]:
    return [t for t in turns if t.get("scored")]


def _simulated(turns: list[Turn]) -> list[Turn]:
    return [t for t in turns if t.get("source") != "human"]


# ---------------------------------------------------------------- 깨짐 기계 항목


def b1_generation(turns: list[Turn], since: int) -> list[str]:
    """유실 1턴 또는 생성 타임아웃 1회."""
    out: list[str] = []
    for t in _simulated(turns):
        if t["turn"] <= since:
            continue
        if t.get("lost"):
            out.append(f"턴 {t['turn']} 유실(시도 {t.get('attempt')})")
        for call in t.get("calls", []):
            if (
                call.get("callSite") == "chat_generate"
                and not call.get("ok", True)
                and "Timeout" in str(call.get("errorType") or "")
            ):
                out.append(f"턴 {t['turn']} 생성 타임아웃 {call.get('errorType')}")
        for failure in t.get("logFailures", []):
            if failure.get("failure") == "generation" and failure.get("timeout"):
                out.append(f"턴 {t['turn']} 서버 로그 생성 실패(타임아웃)")
    return out


def b2_judgment(turns: list[Turn], since: int) -> list[str]:
    """같은 판정 call_site 의 실패 턴이 연속 10턴 창 안에 둘."""
    out: list[str] = []
    for site, kind in JUDGMENT_FAILURES.items():
        failed = sorted(
            {
                t["turn"]
                for t in _simulated(turns)
                if any(f.get("failure") == kind for f in t.get("logFailures", []))
                or any(c.get("callSite") == site and not c.get("ok", True) for c in t.get("calls", []))
            }
        )
        out += [f"{site} 실패 턴 {a}·{b}" for a, b in pairwise(failed) if b - a <= 9 and b > since]
    return out


def b3_status(turns: list[Turn], since: int) -> list[str]:
    """상태창 없음·4항목 형식 불일치가 채점 턴 2연속."""

    def bad(t: Turn) -> bool:
        return not t.get("statusPresent") or not t.get("statusFmtOk")

    return [
        f"턴 {a['turn']}·{b['turn']} 상태창 형식 불일치"
        for a, b in pairwise(_scored(turns))
        if bad(a) and bad(b) and b["turn"] > since
    ]


def b4_mimic(turns: list[Turn], since: int) -> list[str]:
    """상태창·본문 스탯 흉내 수치 1턴."""
    return [
        f"턴 {t['turn']} 수치 노출 {t.get('bodyMimic') or '상태창'}"
        for t in _scored(turns)
        if t["turn"] > since and (t.get("statusMimic") or t.get("bodyMimic"))
    ]


def b6a_duplicate(turns: list[Turn], since: int) -> list[str]:
    """채점 턴 3연속으로 8어절 복제가 있고 셋에 공통 출처가 있다."""
    scored = _scored(turns)
    out: list[str] = []
    for a, b, c in zip(scored, scored[1:], scored[2:], strict=False):
        if c["turn"] <= since or not (a.get("dup") and b.get("dup") and c.get("dup")):
            continue
        common = set.intersection(*({d["src"] for d in t["dup"]} for t in (a, b, c)))
        if common:
            out.append(f"턴 {a['turn']}·{b['turn']}·{c['turn']} 같은 출처 복제 {sorted(common)}")
    return out


def _overlaps(turns: list[Turn], replies: dict[int, str]) -> list[tuple[int, float]]:
    """채점 턴마다 직전 20 채점 턴과의 어절 4-gram 겹침. 20개가 안 차면 계산하지 않는다."""
    grams: list[tuple[int, set[tuple[str, ...]]]] = []
    for t in _scored(turns):
        body = text_rules.strip_status(replies.get(t["attempt"], ""))
        seq = text_rules.words(body)
        grams.append((t["turn"], {tuple(seq[i : i + 4]) for i in range(len(seq) - 3)}))
    out: list[tuple[int, float]] = []
    for i, (turn, g) in enumerate(grams):
        if i < 20 or not g:
            continue
        seen = set().union(*(h for _, h in grams[i - 20 : i]))
        out.append((turn, len(g & seen) / len(g)))
    return out


def b6b_long_repeat(turns: list[Turn], replies: dict[int, str]) -> list[str]:
    """보고만: 직전 10 채점 턴의 겹침 중앙값이 턴 21~50 기준의 2배 이상이고 0.30 이상."""
    overlaps = _overlaps(turns, replies)
    base_values = [v for turn, v in overlaps if 21 <= turn <= 50]
    recent = [v for _, v in overlaps[-10:]]
    if not base_values or not recent or max(turn for turn, _ in overlaps) <= 50:
        return []
    base, block = statistics.median(base_values), statistics.median(recent)
    if block >= 2 * base and block >= 0.30:
        return [f"겹침 중앙값 {block:.2f}(기준 {base:.2f})"]
    return []


def b6c_time_stuck(turns: list[Turn], since: int) -> list[str]:
    """상태창 `시간` 같은 값 채점 턴 20연속, 또는 감소 턴에서 시간 불변이 감소 턴 2회 연속."""
    scored = _scored(turns)
    out: list[str] = []
    run = 0
    previous_time: str | None = None
    for cur in scored:
        time_now = cur.get("statusTime")
        run = 0 if time_now is None else (run + 1 if time_now == previous_time else 1)
        previous_time = time_now
        if run == 20 and cur["turn"] > since:
            out.append(f"턴 {cur['turn']} 까지 시간 「{cur.get('statusTime')}」 20연속")
    unchanged: list[tuple[int, bool]] = [
        (cur["turn"], cur.get("statusTime") is not None and cur.get("statusTime") == prev.get("statusTime"))
        for prev, cur in pairwise(scored)
        if (cur.get("countdownDelta") or 0) < 0
    ]
    out += [
        f"감소 턴 {a}·{b} 시간 불변"
        for (a, still_a), (b, still_b) in pairwise(unchanged)
        if still_a and still_b and b > since
    ]
    return out


def b8_cost(turns: list[Turn], cost_lines: list[dict[str, Any]], since: int) -> list[str]:
    """① 10턴 원가 d 가 턴 40·50 줄 평균의 2배 이상(턴 60 줄부터) ② 칸 판정 입력이 턴 40~60 최대의 1.5배 초과(턴 61부터)
    ③ 엔딩 판정 입력이 이 방 첫 엔딩 판정 입력의 1.5배 초과."""
    out: list[str] = []
    by_turn = {line["turn"]: line for line in cost_lines}
    if 40 in by_turn and 50 in by_turn:
        base = (by_turn[40]["dUsd"] + by_turn[50]["dUsd"]) / 2
        out += [
            f"턴 {line['turn']} 줄 d ${line['dUsd']:.4f} ≥ 2 × 기준 ${base:.4f}"
            for line in cost_lines
            if line["turn"] >= 60 and line["turn"] > since and line["dUsd"] >= 2 * base
        ]

    def tokens(t: Turn, site: str) -> list[int]:
        return [u["promptTokens"] for u in t.get("usage", []) if u.get("callSite") == site]

    plateau = [n for t in turns if 40 <= t["turn"] <= 60 for n in tokens(t, "chat_media_book_image")]
    if plateau and max(t["turn"] for t in turns) > 60:
        r_img = max(plateau)
        out += [
            f"턴 {t['turn']} 칸 판정 입력 {n} > 1.5 × {r_img}"
            for t in turns
            if t["turn"] >= 61 and t["turn"] > since
            for n in tokens(t, "chat_media_book_image")
            if n > 1.5 * r_img
        ]
    endings = [(t["turn"], n) for t in turns for n in tokens(t, "chat_ending_judgment")]
    if endings:
        first = endings[0][1]
        out += [
            f"턴 {turn} 엔딩 판정 입력 {n} > 1.5 × {first}"
            for turn, n in endings[1:]
            if turn > since and n > 1.5 * first
        ]
    return out


def _over_seven(t: Turn, trace_stats: dict[int, list[dict[str, Any]]]) -> bool:
    traced = trace_stats.get(t["turn"])
    if traced is not None:
        for stat in traced:
            if stat.get("name") == COUNTDOWN and stat.get("requested") is not None:
                return float(stat["start"]) - float(stat["requested"]) > 7
        return False
    first_days = next((p["days"] for p in t.get("dayPhrases", []) if isinstance(p.get("days"), int)), None)
    return t.get("countdownDelta") == -7 and first_days is not None and first_days > 7


def b9_stats(
    turns: list[Turn], trace_stats: dict[int, list[dict[str, Any]]], since: int, ooc_turns: set[int] | None = None
) -> list[str]:
    """「상영회까지」 증가 1회 · 감소 > 7 요청 2턴 연속 · 「상영회까지」 정수 아닌 값 1회.

    OOC 턴(사용자가 극 밖 발화로 게이지를 서사 날짜에 맞춰 달라고 한 턴)은 채점에서 빠진 턴이지만 증가·정수 아닌
    값은 똑같이 본다. 7 넘는 감소 요청은 그 턴이 의도한 결과라 연속 판정에서 7 이내 요청으로 친다.
    """
    ooc = ooc_turns or set()
    scored = [t for t in turns if t.get("scored") or (t["turn"] in ooc and not t.get("lost"))]
    out: list[str] = []
    for t in scored:
        if t["turn"] <= since:
            continue
        if (t.get("countdownDelta") or 0) > 0:
            out.append(f"턴 {t['turn']} 「상영회까지」 증가 {t['countdownDelta']}")
        after = t.get("countdownAfter")
        if after is not None and float(after) % 1:
            out.append(f"턴 {t['turn']} 「상영회까지」 정수 아님 {after}")
    out += [
        f"턴 {a['turn']}·{b['turn']} 감소 > 7 요청 연속"
        for a, b in pairwise(scored)
        if b["turn"] > since
        and a["turn"] not in ooc
        and b["turn"] not in ooc
        and _over_seven(a, trace_stats)
        and _over_seven(b, trace_stats)
    ]
    return out


def ooc_turns(meta_path: Path) -> set[int]:
    """런 meta 의 오케스트레이터 상태에 적힌 OOC 턴 번호."""
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return {int(x["turn"]) for x in meta.get("orchestratorState", {}).get("ooc", [])}


def _affinity_jumps(t: Turn) -> list[str]:
    return [
        f"턴 {t['turn']} {name} Δ {delta}"
        for name, delta in (t.get("affectionDelta") or {}).items()
        if delta is not None and abs(delta) > 8
    ]


def b9_affinity(turns: list[Turn], since: int) -> list[str]:
    """보고만: 호감 |Δ| > 8 1회."""
    return [line for t in _scored(turns) if t["turn"] > since for line in _affinity_jumps(t)]


def affinity_misread_tally(turns: list[Turn]) -> dict[str, Any]:
    """방 전체(직전 점검과 무관)의 호감 |Δ| > 8 채점 턴 수와 턴 목록. 정지 없이 집계만 이어 가기 위한 상태 값."""
    hit = [t["turn"] for t in _scored(turns) if _affinity_jumps(t)]
    return {"b9AffinityMisreads": len(hit), "b9AffinityMisreadTurns": hit}


def b11_memory(turns: list[Turn], raw_turns: int | None, backoff_failures: int, state: dict[str, Any]) -> list[str]:
    """원문 턴 수 ≥ 40 · 접기 백오프 실패 ≥ 3 · 요약 1,500자 첫 도달(첫 회만 — 이후는 보고만)."""
    out: list[str] = []
    if raw_turns is not None and raw_turns >= 40:
        out.append(f"원문 턴 수 {raw_turns} ≥ 40")
    if backoff_failures >= 3:
        out.append(f"요약 접기 백오프 실패 {backoff_failures}")
    long = [t["turn"] for t in turns if ((t.get("memory") or {}).get("summaryLen") or 0) >= 1500]
    if long and not state.get("summaryTruncationSeen"):
        state["summaryTruncationSeen"] = long[0]
        out.append(f"턴 {long[0]} 요약 길이 ≥ 1500(첫 절단)")
    return out


def b12_size_latency(turns: list[Turn], since: int) -> list[str]:
    """응답 길이가 기준 중앙값의 2배 이상 채점 턴 3연속 · 턴 소요 60초 초과 1회. 기준은 직전 50턴 구간의 채점 턴
    중앙값, 첫 구간은 그 턴 앞 채점 턴(10개 이상)의 중앙값."""
    scored = _scored(turns)

    def baseline(index: int) -> float | None:
        turn = scored[index]["turn"]
        bin_start = (turn - 1) // 50 * 50 + 1
        if bin_start > 1:
            prior = [t["replyLen"] for t in scored if bin_start - 50 <= t["turn"] < bin_start]
        else:
            prior = [t["replyLen"] for t in scored[:index]]
            if len(prior) < 10:
                return None
        return statistics.median(prior) if prior else None

    big = []
    for i, t in enumerate(scored):
        base = baseline(i)
        big.append(base is not None and t["replyLen"] >= 2 * base)
    out = [
        f"턴 {scored[i - 2]['turn']}·{scored[i - 1]['turn']}·{scored[i]['turn']} 응답 길이 2배 이상"
        for i in range(2, len(scored))
        if big[i] and big[i - 1] and big[i - 2] and scored[i]["turn"] > since
    ]
    out += [
        f"턴 {t['turn']} 소요 {t['seconds']}초"
        for t in _simulated(turns)
        if t["turn"] > since and not t.get("lost") and (t.get("seconds") or 0) > 60
    ]
    return out


# ---------------------------------------------------------------- 조기 점검 E1·E5


def _ending_window_turns(turns: list[Turn], since: int) -> list[Turn]:
    """판정 반영 뒤에도 「상영회까지」가 남은 턴. 스탯 판정이 실패한 턴은 엔딩 판정을 건너뛰므로 대상이 아니다."""
    return [
        t
        for t in turns
        if t["turn"] > since
        and t.get("countdownAfter") is not None
        and float(t["countdownAfter"]) > 0
        and not any(f.get("failure") == "stat_judgment" for f in t.get("logFailures", []))
    ]


def e1_ending_judgment(turns: list[Turn], since: int) -> list[str]:
    """「상영회까지」 > 0 인 턴의 엔딩 판정 시도(서버 로그 사용량 줄 + 판정 실패 줄)가 하나라도 있으면 건다."""
    out: list[str] = []
    for t in _ending_window_turns(turns, since):
        used = sum(1 for u in t.get("usage", []) if u.get("callSite") == "chat_ending_judgment")
        failed = sum(1 for f in t.get("logFailures", []) if f.get("failure") == "judgment")
        if used + failed:
            out.append(f"턴 {t['turn']} 「상영회까지」 {t['countdownAfter']} 에서 엔딩 판정 시도 {used + failed}")
    return out


def e1_crosscheck(turns: list[Turn], since: int) -> list[str]:
    """보고만: 같은 대상 턴의 trace `llm_call` 중 엔딩 판정 호출 수."""
    out: list[str] = []
    for t in _ending_window_turns(turns, since):
        traced = sum(1 for c in t.get("calls", []) if c.get("callSite") == "chat_ending_judgment")
        if traced:
            out.append(f"턴 {t['turn']} trace 엔딩 판정 호출 {traced}")
    return out


def stage_note_texts(frame_path: Path) -> dict[str, str]:
    """frame.json 에서 단계 노트 넷의 본문. 하나라도 없으면 점검이 공회전하므로 예외로 멈춘다."""
    notes = json.loads(frame_path.read_text(encoding="utf-8"))["situationNotes"]
    by_name = {n["name"]: n["infoText"] for n in notes}
    missing = [name for name in STAGE_NOTES if name not in by_name]
    if missing:
        raise ValueError(f"frame.json 에 단계 노트가 없다: {missing}")
    return {name: by_name[name] for name in STAGE_NOTES}


def e5_stage_notes(records: list[dict[str, Any]], stage_texts: dict[str, str], room: str, since: int) -> list[str]:
    """이 방의 덤프 레코드마다 단계 노트 본문이 프롬프트에 글자 그대로 들어 있는 개수가 1이 아니면 건다."""
    out: list[str] = []
    for r in records:
        if r.get("roomId") != room or int(r.get("turn") or 0) <= since:
            continue
        present = [name for name, text in stage_texts.items() if text in str(r.get("prompt") or "")]
        if len(present) != 1:
            out.append(f"턴 {r['turn']} 덤프의 단계 노트 {len(present)}개 {present}")
    return out


def e5_crosscheck(turns: list[Turn], since: int) -> list[str]:
    """보고만: 판정 전 스탯으로 다시 계산한 단계 노트가 정확히 하나가 아닌 턴."""
    return [
        f"턴 {t['turn']} 재계산 단계 {t.get('stage')}"
        for t in turns
        if t["turn"] > since and not t.get("lost") and len(t.get("stage") or []) != 1
    ]


# ---------------------------------------------------------------- 원가


def _call_cost(model: str, fields: dict[str, Any]) -> float | None:
    def num(key: str) -> int:
        value = fields.get(key)
        return 0 if value is None or value == "None" else int(value)

    output, thoughts = num("candidates"), num("thoughts")
    # 이미지가 실린 호출은 입력 토큰이 비어 오고 total 만 온다 — 입력을 total 에서 복원한다.
    if fields.get("prompt") in (None, "None") or num("missing"):
        input_tokens = max(num("total") - output - thoughts, 0)
    else:
        input_tokens = num("prompt")
    return estimate_cost_usd(
        model, input_tokens=input_tokens, cached_tokens=num("cached"), output_tokens=output, thoughts_tokens=thoughts
    )


def room_conversation_cost(lines: list[str], room_id: str) -> dict[str, Any]:
    """서버 로그에서 이 방의 `gemini_usage` 줄만 합친 대화 원가(리플레이 call_site 제외)."""
    by_site: dict[str, float] = {}
    unpriced = 0
    for record in metrics.parse_server_log(lines, room_id):
        if record["kind"] != "usage" or record.get("call_site", "").startswith("replay_"):
            continue
        cost = _call_cost(
            record.get("model", ""),
            {
                "prompt": record.get("prompt_tokens"),
                "cached": record.get("cached_content_tokens"),
                "candidates": record.get("candidates_tokens"),
                "thoughts": record.get("thoughts_tokens"),
                "total": record.get("total_tokens"),
            },
        )
        if cost is None:
            unpriced += 1
            continue
        by_site[record["call_site"]] = by_site.get(record["call_site"], 0.0) + cost
    return {"total": sum(by_site.values()), "byCallSite": by_site, "unpriced": unpriced}


def redis_cost(hashes: dict[str, dict[str, str]], since_day: str = USAGE_SINCE_DAY) -> dict[str, Any]:
    """`llm_usage:<날짜>` 해시(since_day 이후)를 리플레이 call_site 와 그 밖(모든 방)으로 나눠 환산한다."""
    grouped: dict[tuple[str, str], dict[str, int]] = {}
    for key, fields in hashes.items():
        if key.split(":", 1)[1] < since_day:
            continue
        for field, value in fields.items():
            site, model, metric = field.split("|")
            bucket = grouped.setdefault((site, model), {})
            bucket[metric] = bucket.get(metric, 0) + int(value)
    replay = conv = 0.0
    unpriced = 0
    for (site, model), m in grouped.items():
        cost = _call_cost(
            model,
            {k: m.get(k, 0) for k in ("cached", "candidates", "thoughts", "total", "missing")}
            | {"prompt": m.get("prompt", 0)},
        )
        if cost is None:
            unpriced += m.get("calls", 1)
            continue
        if site in REPLAY_SITES:
            replay += cost
        else:
            conv += cost
    return {"replay": replay, "convAllRooms": conv, "unpriced": unpriced}


def judge_cost(line: dict[str, Any], previous: dict[str, Any] | None, state: dict[str, Any]) -> list[dict[str, Any]]:
    """원가 줄 하나의 정지·보고. 누적 감소(집계 소실) · 단가 없는 모델 · 대화 + d ≥ $10 · 총액 + d ≥ $25 는 정지,
    대화 ≥ $8 첫 도달과 Redis 교차 확인 어긋남은 보고만."""
    alerts: list[dict[str, Any]] = []
    conv, replay, d = line["cConvUsd"], line["cReplayUsd"], line["dUsd"]

    def add(item: str, stop: bool, reason: str) -> None:
        alerts.append({"item": item, "stop": stop, "evidence": [reason]})

    if previous is not None and (conv < previous["cConvUsd"] - 1e-9 or replay < previous["cReplayUsd"] - 1e-9):
        add(
            "cost.decrease",
            True,
            f"누적 감소: 대화 {previous['cConvUsd']:.6f}→{conv:.6f}, 리플레이 {previous['cReplayUsd']:.6f}→{replay:.6f}",
        )
    if line.get("unpricedCalls"):
        add("cost.unpriced", True, f"단가표에 없는 모델 호출 {line['unpricedCalls']}")
    if conv + d >= CONVERSATION_STOP_USD:
        add("cost.conversation10", True, f"대화 ${conv:.4f} + d ${d:.4f} ≥ $10")
    if conv + replay + d >= TOTAL_STOP_USD:
        add("cost.total25", True, f"총액 ${conv + replay:.4f} + d ${d:.4f} ≥ $25")
    if conv >= CONVERSATION_REPORT_USD and not state.get("conversation8Reported"):
        state["conversation8Reported"] = line["turn"]
        add("cost.conversation8", False, f"대화 ${conv:.4f} ≥ $8 첫 도달")
    if line.get("redisConvAllRoomsUsd") is not None and line["redisConvAllRoomsUsd"] < conv - 1e-6:
        add("cost.crosscheck", False, f"Redis 전체 대화 ${line['redisConvAllRoomsUsd']:.6f} < 측정 방 ${conv:.6f}")
    return alerts


# ---------------------------------------------------------------- 기록


def item_alerts(items: dict[str, dict[str, Any]], report_only: set[str]) -> list[dict[str, Any]]:
    return [
        {
            "item": name,
            "stop": name in STOP_ITEMS and (name in STOP_ALWAYS or name not in report_only),
            "evidence": item["evidence"],
        }
        for name, item in items.items()
        if item["hit"]
    ]


def write_outcome(run: Path, turn: int, items: dict[str, dict[str, Any]], alerts: list[dict[str, Any]]) -> bool:
    stop = any(a["stop"] for a in alerts)
    (run / "checks").mkdir(parents=True, exist_ok=True)
    (run / "watch").mkdir(parents=True, exist_ok=True)
    check = {"turn": turn, "items": items, "stop": stop, "alerts": alerts}
    (run / "checks" / f"t{turn:03d}.json").write_text(
        json.dumps(check, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    now = datetime.now(KST).isoformat(timespec="seconds")
    with (run / "watch" / "alerts.jsonl").open("a", encoding="utf-8") as f:
        for alert in alerts:
            f.write(json.dumps({"at": now, "turn": turn, **alert}, ensure_ascii=False) + "\n")
    if stop:
        (run / "STOP").touch()
    return stop


# ---------------------------------------------------------------- 실서버 읽기


def _psql(sql: str) -> str:
    return subprocess.run(
        ["docker", "exec", PG, "psql", "-U", "postgres", "-d", "ai_character_chat", "-At", "-c", sql],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


def _redis(*args: str) -> str:
    return subprocess.run(
        ["docker", "exec", REDIS, "redis-cli", "-n", "0", *args], check=True, capture_output=True, text=True, timeout=30
    ).stdout


def room_turn_count(room: str) -> int:
    return int(_psql(f"SELECT turn_count FROM chat_rooms WHERE id = '{room}'"))


def raw_turn_count(room: str) -> int:
    """요약 커서 뒤 원문 응답 수(오프닝 제외)."""
    return int(
        _psql(
            f"""WITH cur AS (SELECT cursor_created_at, cursor_message_id FROM chat_room_memory_snapshots
                 WHERE chat_room_id = '{room}' ORDER BY cursor_created_at DESC, cursor_message_id DESC LIMIT 1),
               op AS (SELECT id FROM chat_messages WHERE chat_room_id = '{room}' ORDER BY created_at, id LIMIT 1)
            SELECT count(*) FROM chat_messages m
            WHERE m.chat_room_id = '{room}' AND m.role = 'ASSISTANT' AND m.id <> (SELECT id FROM op)
              AND (NOT EXISTS (SELECT 1 FROM cur)
                   OR (m.created_at, m.id) > (SELECT cursor_created_at, cursor_message_id FROM cur))"""
        )
    )


def backoff_failures(room: str) -> int:
    value = _redis("HGET", f"memory_fold_backoff:{room}", "failures").strip()
    return int(value) if value else 0


def usage_hashes() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for key in _redis("--scan", "--pattern", "llm_usage:*").split():
        flat = _redis("HGETALL", key).splitlines()
        out[key] = dict(zip(flat[::2], flat[1::2], strict=False))
    return out


def trace_stat_outcomes(path: Path, room: str) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("kind") == "stat_outcome" and record.get("roomId") == room and record.get("turn") is not None:
            out[int(record["turn"])] = record.get("stats", [])
    return out


def replies_by_attempt(log: Path) -> dict[int, str]:
    """`longturn_metrics.build_turns` 와 같은 순서(http 200 턴 줄)로 시도 번호 → 응답 원문."""
    out: dict[int, str] = {}
    attempt = 0
    for row in metrics.read_jsonl(log):
        if row.get("kind") != "turn" or row.get("http", 200) != 200:
            continue
        attempt += 1
        out[attempt] = str(row.get("reply") or "")
    return out


def _read_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def check(run: Path, room: str, turn: int, observed: int, state: dict[str, Any], report_only: set[str]) -> bool:
    log = run / "filmclub-v6fix.jsonl"
    live = run / "analysis" / "live"
    metrics.main(
        [
            "turns",
            "--log",
            str(log),
            "--frame",
            str(run / "analysis" / "frame.json"),
            "--server-log",
            str(run / "server.log"),
            "--trace",
            str(run / "trace.jsonl"),
            "--snapshots",
            str(run / "memory-snapshots.jsonl"),
            "--room",
            room,
            "--out",
            str(live),
        ]
    )
    turns = json.loads((live / "turns.json").read_text(encoding="utf-8"))
    since = int(state.get("lastTurnSeen", 0))

    conv = room_conversation_cost((run / "server.log").read_text(encoding="utf-8").splitlines(), room)
    redis = redis_cost(usage_hashes())
    cost_path = run / "cost.jsonl"
    cost_lines = _read_lines(cost_path)
    previous = cost_lines[-1] if cost_lines else None
    line = {
        "turn": turn,
        "turnCountObserved": observed,
        "at": datetime.now(KST).isoformat(timespec="seconds"),
        "cConvUsd": round(conv["total"], 6),
        "cReplayUsd": round(redis["replay"], 6),
        "cUsd": round(conv["total"] + redis["replay"], 6),
        "dUsd": round(conv["total"] - (previous["cConvUsd"] if previous else 0.0), 6),
        "byCallSite": {site: round(v, 6) for site, v in sorted(conv["byCallSite"].items())},
        "unpricedCalls": conv["unpriced"] + redis["unpriced"],
        "redisConvAllRoomsUsd": round(redis["convAllRooms"], 6),
    }
    with cost_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    cost_lines.append(line)

    trace = trace_stat_outcomes(run / "trace.jsonl", room)
    replies = replies_by_attempt(log)
    found = {
        "B1": b1_generation(turns, since),
        "B2": b2_judgment(turns, since),
        "B3": b3_status(turns, since),
        "B4": b4_mimic(turns, since),
        "B6a": b6a_duplicate(turns, since),
        "B6b": b6b_long_repeat(turns, replies),
        "B6c": b6c_time_stuck(turns, since),
        "B8": b8_cost(turns, cost_lines, since),
        "B9": b9_stats(turns, trace, since, ooc_turns(run / "meta.json")),
        "B9.affinity": b9_affinity(turns, since),
        "B11": b11_memory(turns, raw_turn_count(room), backoff_failures(room), state),
        "B12": b12_size_latency(turns, since),
        "E1": e1_ending_judgment(turns, since),
        "E1.crosscheck": e1_crosscheck(turns, since),
        "E5": e5_stage_notes(
            _read_lines(run / "prompt-dump.jsonl"), stage_note_texts(run / "analysis" / "frame.json"), room, since
        ),
        "E5.crosscheck": e5_crosscheck(turns, since),
    }
    items = {name: {"hit": bool(ev), "evidence": ev} for name, ev in found.items()}
    for name in REPORT_ONLY_ALWAYS:
        items[name]["reportOnly"] = True
    alerts = item_alerts(items, report_only | set(REPORT_ONLY_ALWAYS)) + judge_cost(line, previous, state)
    stop = write_outcome(run, turn, items, alerts)
    state.update(affinity_misread_tally(turns))
    state["lastTurnSeen"] = max((t["turn"] for t in turns), default=since)
    state["lastBucket"] = turn
    return stop


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _guarded_check(
    run: Path, room: str, bucket: int, observed: int, state: dict[str, Any], report_only: set[str]
) -> None:
    try:
        check(run, room, bucket, observed, state, report_only)
    except Exception as exc:  # 감시가 멈추면 원가 정지도 꺼진다 — 그 자체를 정지 사유로 남긴다
        write_outcome(
            run, bucket, {}, [{"item": "watch.error", "stop": True, "evidence": [f"{type(exc).__name__}: {exc}"[:500]]}]
        )
        state["lastBucket"] = bucket


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["run", "once"])
    ap.add_argument("--run", required=True, help="런 디렉터리")
    ap.add_argument("--room", required=True)
    ap.add_argument("--interval", type=float, default=10.0, help="turn_count 확인 간격(초)")
    ap.add_argument("--report-only", default="", help="재개 뒤 보고만 할 항목(쉼표)")
    args = ap.parse_args(argv)
    run = Path(args.run)
    watch = run / "watch"
    watch.mkdir(parents=True, exist_ok=True)
    state_path = watch / "state.json"
    state: dict[str, Any] = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    report_only = {x for x in args.report_only.split(",") if x}

    if args.mode == "once":
        observed = room_turn_count(args.room)
        _guarded_check(run, args.room, observed // 10 * 10, observed, state, report_only)
        _save_state(state_path, state)
        return

    (watch / "watch.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
    db_errors = 0
    while not (watch / "STOP-WATCH").exists():
        try:
            observed = room_turn_count(args.room)
            db_errors = 0
        except Exception as exc:
            db_errors += 1
            if db_errors == 3:  # 30초 넘게 방을 못 읽으면 판정이 멈춘 것이다
                write_outcome(
                    run,
                    int(state.get("lastBucket", 0)),
                    {},
                    [{"item": "watch.error", "stop": True, "evidence": [f"turn_count 조회 실패 3회: {exc}"[:500]]}],
                )
            time.sleep(args.interval)
            continue
        bucket = observed // 10 * 10
        if bucket > int(state.get("lastBucket", 0)):
            _guarded_check(run, args.room, bucket, observed, state, report_only)
            _save_state(state_path, state)
        time.sleep(args.interval)
    (watch / "watch.pid").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
