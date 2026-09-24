"""한 턴씩 손으로 치며 노는 도구 (일회성). chat_probe가 고정 대본을 배치로 돌린다면
이건 사람이 응답을 읽고 다음 말을 정하는 용도다.

    python chat_play.py --base <url> --log <run>/x.jsonl --new romance-3rdloop       # 방 만들고 오프닝·칩·playguide 출력
    python chat_play.py --base <url> --log <run>/x.jsonl --trace <run>/trace.jsonl \
        --room <id> --say "안녕하세요"                                               # 한 턴
    python chat_play.py --base <url> --room <id> --state                             # 스탯/턴수/엔딩 상태만

`--base` 는 필수다 — 기본값이던 8000 은 메인 dev 서버(공유 DB)라 빠뜨리면 거기에 방이 생긴다
(chat-longrun-goal-prompt.md LB-18).

쿼터(분당 15요청, 1턴=LLM 2회+엔딩판정)를 넘기지 않도록 직전 호출 시각을 `--log` 옆 파일에 남겨
간격을 강제한다 — 프로세스가 매번 새로 뜨므로 메모리에 둘 수 없다.

종료 코드(chat-longrun-goal-prompt.md LB-4·LB-29): 0 정상 · 2 HTTP 401/403(로그인 포함) ·
3 엔딩 도달 · 4 앱 429(같은 명령을 다시 실행하면 retryAfterSeconds 만큼 기다린다) ·
5 Gemini 한도(`--trace` 에 이 방의 LLMRateLimitError). 인자 오류도 argparse 가 2 로 끝낸다.

로그·출력에는 채팅 화면에 보이는 것만 남긴다. 스탯 description, 엔딩 judgmentPrompt·statRules,
도달 전 epilogue 는 `contentSnapshot` 에 들어 있지만 어디에도 옮기지 않는다 — 대화 에이전트가
자기 JSONL 을 읽을 수 있다(chat-longrun-goal-prompt.md LB-13·LB-23).
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from seed_content.upsert import story_content_id

EMAIL, PASSWORD = "test@example.com", "password1234"
MIN_GAP = 10.0
RATE_LIMIT_NOTICE = "측정 중단: 외부 한도 — 오케스트레이터에게 보고"


class _AuthError(Exception):
    """401/403 — 종료 코드 2 로 끝낸다."""


def _pace(stamp: Path, retry_at: Path) -> None:
    """직전 턴 + MIN_GAP 과 앱 429 가 알려 준 재시도 가능 시각 중 늦은 쪽까지 기다린다."""
    wake = 0.0
    if stamp.exists():
        wake = float(stamp.read_text()) + MIN_GAP
    if retry_at.exists():
        wake = max(wake, float(retry_at.read_text()))
    if wake > time.time():
        time.sleep(wake - time.time())
    stamp.write_text(str(time.time()))


def _client(base: str) -> httpx.Client:
    """로그인까지 마친 클라이언트. 첫 요청이 `__enter__` 전에 나가면 httpx가 재진입으로
    막으므로, 호출부는 `with` 없이 그대로 받아 쓴다."""
    client = httpx.Client(base_url=base, timeout=300)
    login = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    if login.status_code in (401, 403):
        raise _AuthError(f"HTTP {login.status_code}: {login.text[:300]}")
    login.raise_for_status()
    return client


def _append(log: Path, record: dict[str, Any]) -> None:
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()


def _stat_names(room: dict[str, Any]) -> dict[str, str]:
    return {s["id"]: s["name"] for s in (room.get("contentSnapshot") or {}).get("stats", [])}


def _room_after(room: dict[str, Any]) -> dict[str, Any]:
    names = _stat_names(room)
    return {
        "turnCount": room.get("turnCount"),
        "stats": {names.get(k, k): v for k, v in (room.get("stats") or {}).items()},
        "endingReached": room.get("endingReached"),
    }


def _stats_line(room: dict[str, Any]) -> str:
    defs = {s["id"]: s for s in (room.get("contentSnapshot") or {}).get("stats", [])}
    parts = []
    for stat_id, value in (room.get("stats") or {}).items():
        d = defs.get(stat_id)
        parts.append(f"{d['name'] if d else stat_id[:6]}={value}{(d or {}).get('unit') or ''}")
    ending = " ★엔딩도달" if room.get("endingReached") else ""
    return f"[턴 {room.get('turnCount')}] " + "  ".join(parts) + ending


def _gemini_rate_limited(trace: Path, offset: int, room_id: str) -> bool:
    """요청 전 오프셋 이후 이 방 레코드에 Gemini 429 가 있었나. 내용은 호출부에 돌려주지 않는다."""
    if not trace.exists():
        return False
    with trace.open("rb") as f:
        f.seek(offset)
        chunk = f.read().decode("utf-8", errors="replace")
    for line in chunk.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(record, dict)
            and record.get("roomId") == room_id
            and record.get("kind") in ("generation", "judgment_failed")
            and record.get("errorType") == "LLMRateLimitError"
        ):
            return True
    return False


def _client_turn(log: Path) -> int:
    """이 로그에서 서버가 받아 준(http=200) 턴 수 + 1. 429·401 재시도는 같은 번호를 쓴다."""
    if not log.exists():
        return 1
    done = 0
    for line in log.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("kind") == "turn" and record.get("http") == 200:
            done += 1
    return done + 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--new")
    ap.add_argument("--setup", type=int, default=0, help="시작설정 인덱스")
    ap.add_argument("--room")
    ap.add_argument("--say")
    ap.add_argument("--state", action="store_true")
    ap.add_argument("--base", required=True, help="API 서버 base URL (필수, LB-18)")
    ap.add_argument("--log", help="턴 로그 JSONL (--new·--say 필수). 간격 스탬프도 이 옆에 둔다")
    ap.add_argument("--trace", help="서버 trace.jsonl (--say 필수). Gemini 429 감지용")
    ap.add_argument("--intent", choices=["목표", "반응", "탐색"], help="로그에만 남긴다")
    args = ap.parse_args()
    if (args.new or args.say is not None) and not args.log:
        ap.error("--new·--say 에는 --log 가 필요하다")
    if args.say is not None and not args.trace:
        ap.error("--say 에는 --trace 가 필요하다")

    try:
        client = _client(args.base)
    except _AuthError as exc:
        print(exc)
        return 2
    log = Path(args.log) if args.log else None
    if args.new:
        assert log is not None
        cid = str(story_content_id(args.new))
        detail = client.get(f"/contents/{cid}").json()
        setup = detail["startingSetups"][args.setup]
        created = client.post(
            "/chat-rooms",
            json={"contentId": cid, "contentType": "story", "startingSetupId": setup["id"]},
        )
        if created.status_code in (401, 403):
            print(f"HTTP {created.status_code}: {created.text[:300]}")
            return 2
        created.raise_for_status()
        room_id = created.json()["id"]
        room = client.get(f"/chat-rooms/{room_id}").json()
        chips = (room.get("contentSnapshot") or {}).get("suggestedReplies") or []
        guide = client.get(f"/chat-rooms/{room_id}/play-guide").json().get("playGuide")
        messages = [m["content"] for m in room.get("messages") or []]
        print(f"room={room_id}  「{detail['name']}」 / 시작설정: {setup['name']}")
        for message in messages:
            print(f"\n{message}")
        print("\n추천 답변:")
        for chip in chips:
            print(f"  - {chip}")
        print(f"\n플레이 가이드:\n{guide or '(없음)'}")
        print("\n" + _stats_line(room))
        _append(log, {
            "kind": "meta", "roomId": room_id, "slug": args.new, "contentId": cid,
            "storyName": detail["name"], "setupIndex": args.setup, "setupName": setup["name"],
            "base": args.base, "createdAt": datetime.now().isoformat(timespec="seconds"),
        })
        _append(log, {
            "kind": "opening", "roomId": room_id, "messages": messages,
            "suggestedReplies": chips, "playGuide": guide, "roomAfter": _room_after(room),
        })
        return 0

    if args.state:
        print(_stats_line(client.get(f"/chat-rooms/{args.room}").json()))
        return 0

    assert log is not None
    trace = Path(args.trace)
    retry_at = log.parent / ".retry_at"
    _pace(log.parent / ".last_turn", retry_at)
    offset = trace.stat().st_size if trace.exists() else 0
    record: dict[str, Any] = {
        "kind": "turn", "clientTurn": _client_turn(log),
        "sentAt": datetime.now().isoformat(timespec="seconds"),
        "userText": args.say, "intent": args.intent,
    }
    started = time.monotonic()
    reply, failure, events = "", None, []
    retry_after = None
    with client.stream(
        "POST", f"/chat-rooms/{args.room}/messages", json={"content": args.say}
    ) as response:
        status = response.status_code
        if status != 200:
            response.read()
            failure = f"HTTP {status}: {response.text[:300]}"
            if status == 429:
                try:
                    retry_after = response.json()["detail"]["retryAfterSeconds"]
                except (ValueError, KeyError, TypeError):
                    retry_after = None
        else:
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                kind = event.get("type")
                if kind == "token":
                    reply += event.get("delta", "")
                elif kind == "statChange":
                    events.append(("stat", event.get("statId"), event.get("newValue")))
                elif kind == "endingReached":
                    events.append(("ENDING", event.get("endingId"), event.get("epilogue")))
                elif kind in ("error", "policyWarning"):
                    events.append((kind, event.get("message"), None))
                    failure = failure or f"{kind}: {event.get('message')}"
    record["seconds"] = round(time.monotonic() - started, 1)
    record["http"] = status
    rate_limited = _gemini_rate_limited(trace, offset, args.room)

    if status != 200:
        record.update(reply="", statChanges=[], ending=None, failure=failure, roomAfter=None)
        if rate_limited:
            record["geminiRateLimited"] = True
        _append(log, record)
        print(failure)
        if status == 429:
            if isinstance(retry_after, (int, float)):
                retry_at.write_text(str(time.time() + retry_after))
            print(f"retryAfterSeconds={retry_after}")
            return 4
        if status in (401, 403):
            return 2
        if rate_limited:
            print(RATE_LIMIT_NOTICE)
            return 5
        return 0

    print(reply)
    room = client.get(f"/chat-rooms/{args.room}").json()
    defs = _stat_names(room)
    ending = None
    stat_changes = []
    for kind, a, b in events:
        if kind == "stat":
            stat_changes.append({"name": defs.get(a, a), "value": b})
            print(f"\n  · {defs.get(a, a)} → {b}")
        elif kind == "ENDING":
            names = {e["id"]: e["name"] for e in (room["contentSnapshot"] or {}).get("endings", [])}
            ending = {"id": a, "name": names.get(a, a), "epilogue": b}
            print(f"\n  ★★ 엔딩 도달: 「{names.get(a, a)}」\n  에필로그: {b}")
        else:
            print(f"\n  !! {kind}: {a}")
    print("\n" + _stats_line(room))
    record.update(
        reply=reply, statChanges=stat_changes, ending=ending, failure=failure,
        roomAfter=_room_after(room),
    )
    if rate_limited:
        record["geminiRateLimited"] = True
    _append(log, record)
    if rate_limited:
        print(RATE_LIMIT_NOTICE)
        return 5
    if ending is not None:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
