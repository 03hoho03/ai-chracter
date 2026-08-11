"""한 턴씩 손으로 치며 노는 도구 (일회성). chat_probe가 고정 대본을 배치로 돌린다면
이건 사람이 응답을 읽고 다음 말을 정하는 용도다.

    python say.py --new romance-3rdloop            # 방 만들고 오프닝 출력
    python say.py --room <id> --say "안녕하세요"    # 한 턴
    python say.py --room <id> --state              # 스탯/턴수/엔딩 상태만

쿼터(분당 15요청, 1턴=LLM 2회+엔딩판정)를 넘기지 않도록 직전 호출 시각을 파일에 남겨
간격을 강제한다 — 프로세스가 매번 새로 뜨므로 메모리에 둘 수 없다.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from typing import Any

import httpx

sys.path.insert(0, "/Users/janghojeong/Projects/work/ai-chracter/apps/api/scripts")
from seed_content.upsert import story_content_id  # noqa: E402

BASE = "http://localhost:8000"
EMAIL, PASSWORD = "test@example.com", "password1234"
STAMP = Path(__file__).parent / ".last_turn"
MIN_GAP = 9.0


def _pace() -> None:
    if STAMP.exists():
        elapsed = time.time() - float(STAMP.read_text())
        if elapsed < MIN_GAP:
            time.sleep(MIN_GAP - elapsed)
    STAMP.write_text(str(time.time()))


def _client() -> httpx.Client:
    """로그인까지 마친 클라이언트. 첫 요청이 `__enter__` 전에 나가면 httpx가 재진입으로
    막으므로, 호출부는 `with` 없이 그대로 받아 쓴다."""
    client = httpx.Client(base_url=BASE, timeout=300)
    client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).raise_for_status()
    return client


def _stats_line(room: dict[str, Any]) -> str:
    defs = {s["id"]: s for s in (room.get("contentSnapshot") or {}).get("stats", [])}
    parts = []
    for stat_id, value in (room.get("stats") or {}).items():
        d = defs.get(stat_id)
        parts.append(f"{d['name'] if d else stat_id[:6]}={value}{(d or {}).get('unit') or ''}")
    ending = " ★엔딩도달" if room.get("endingReached") else ""
    return f"[턴 {room.get('turnCount')}] " + "  ".join(parts) + ending


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--new")
    ap.add_argument("--setup", type=int, default=0, help="시작설정 인덱스")
    ap.add_argument("--room")
    ap.add_argument("--say")
    ap.add_argument("--state", action="store_true")
    args = ap.parse_args()

    client = _client()
    if args.new:
        cid = str(story_content_id(args.new))
        detail = client.get(f"/contents/{cid}").json()
        setup = detail["startingSetups"][args.setup]
        created = client.post(
            "/chat-rooms",
            json={"contentId": cid, "contentType": "story", "startingSetupId": setup["id"]},
        )
        created.raise_for_status()
        room = created.json()
        print(f"room={room['id']}  「{detail['name']}」 / 시작설정: {setup['name']}")
        for message in room.get("messages") or []:
            print(f"\n{message['content']}")
        print("\n" + _stats_line(room))
        return

    if args.state:
        print(_stats_line(client.get(f"/chat-rooms/{args.room}").json()))
        return

    _pace()
    reply, events = "", []
    with client.stream(
        "POST", f"/chat-rooms/{args.room}/messages", json={"content": args.say}
    ) as response:
        if response.status_code != 200:
            response.read()
            print(f"HTTP {response.status_code}: {response.text[:300]}")
            return
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

    print(reply)
    room = client.get(f"/chat-rooms/{args.room}").json()
    defs = {s["id"]: s["name"] for s in (room.get("contentSnapshot") or {}).get("stats", [])}
    for kind, a, b in events:
        if kind == "stat":
            print(f"\n  · {defs.get(a, a)} → {b}")
        elif kind == "ENDING":
            names = {e["id"]: e["name"] for e in (room["contentSnapshot"] or {}).get("endings", [])}
            print(f"\n  ★★ 엔딩 도달: 「{names.get(a, a)}」\n  에필로그: {b}")
        else:
            print(f"\n  !! {kind}: {a}")
    print("\n" + _stats_line(room))


if __name__ == "__main__":
    main()
