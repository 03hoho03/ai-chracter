"""스토리 여러 개와 동시에 채팅해 대화록을 남기는 진단용 드라이버 (일회성, 시드와 무관).

앵무새 패턴 점검과 동시 세션 부하 테스트를 겸한다. 대화록은 JSON 으로 떨어뜨리고
판단은 사람/에이전트가 한다 — 이 스크립트는 판단하지 않는다.

    cd apps/api && uv run --env-file .env python scripts/chat_probe.py \
        --slugs mystery-elevator,sf-backup --turns 5 --out /tmp/probe.json
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from seed_content.upsert import story_content_id  # noqa: E402

BASE = "http://localhost:8000"
EMAIL, PASSWORD = "test@example.com", "password1234"

# 앵무새 패턴은 "사용자 말을 되받는" 자리에서 드러나므로, 짧은 반응·의견·질문·감정 표현을
# 섞는다. 어느 스토리에나 말이 되도록 세계관 고유명사를 쓰지 않는다.
TURNS = [
    "일단 상황부터 좀 알려줘요",
    "그건 별로 좋은 생각이 아닌 것 같은데요",
    "왜 그렇게 생각하세요?",
    "그냥 제 느낌을 말한 거예요",
    "좀 무섭네요 솔직히",
    "그럼 이제 어떻게 하면 되죠?",
]


async def _login(client: httpx.AsyncClient) -> None:
    r = await client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    r.raise_for_status()


async def _send(client: httpx.AsyncClient, room_id: str, text: str) -> dict[str, object]:
    """한 턴. 토큰을 모으고 부수 이벤트(스탯/엔딩/에러)도 함께 기록한다."""
    reply, events = "", []
    started = time.monotonic()
    async with client.stream("POST", f"/chat-rooms/{room_id}/messages", json={"content": text}) as r:
        if r.status_code != 200:
            await r.aread()
            return {"reply": "", "events": [f"HTTP {r.status_code}: {r.text[:200]}"], "seconds": 0.0}
        async for line in r.aiter_lines():
            if not line.startswith("data: "):
                continue
            ev = json.loads(line[6:])
            kind = ev.get("type")
            if kind == "token":
                reply += ev.get("delta", "")  # 필드명은 delta 다 (content 아님)
            elif kind == "statChange":
                events.append(f"stat {ev.get('statId','')[:8]}={ev.get('newValue')}")
            elif kind == "endingReached":
                events.append(f"ending {ev.get('endingId','')[:8]}")
            elif kind in ("error", "policyWarning"):
                events.append(f"{kind}: {ev.get('message','')[:120]}")
    return {"reply": reply, "events": events, "seconds": round(time.monotonic() - started, 1)}


async def _run_story(client: httpx.AsyncClient, slug: str, turns: int) -> dict[str, object]:
    cid = str(story_content_id(slug))
    detail = await client.get(f"/contents/{cid}")
    if detail.status_code != 200:
        return {"slug": slug, "error": f"GET /contents {detail.status_code}"}
    setups = detail.json().get("startingSetups") or []
    if not setups:
        return {"slug": slug, "error": "시작 상황 없음"}

    created = await client.post(
        "/chat-rooms",
        json={"contentId": cid, "contentType": "story", "startingSetupId": setups[0]["id"]},
    )
    if created.status_code >= 400:
        return {"slug": slug, "error": f"POST /chat-rooms {created.status_code}: {created.text[:200]}"}
    room = created.json()

    transcript = [
        {"role": "진행자", "text": m["content"]} for m in (room.get("messages") or [])
    ]
    for text in TURNS[:turns]:
        transcript.append({"role": "사용자", "text": text})
        got = await _send(client, room["id"], text)
        transcript.append(
            {"role": "진행자", "text": got["reply"], "events": got["events"], "seconds": got["seconds"]}
        )
    return {"slug": slug, "name": detail.json().get("name"), "roomId": room["id"], "transcript": transcript}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slugs", required=True, help="쉼표로 구분한 스토리 slug 목록")
    ap.add_argument("--turns", type=int, default=5)
    ap.add_argument("--out", required=True)
    ap.add_argument("--concurrency", type=int, default=3, help="동시에 진행할 스토리 수")
    args = ap.parse_args()

    slugs = [s.strip() for s in args.slugs.split(",") if s.strip()]
    sem = asyncio.Semaphore(args.concurrency)
    started = time.monotonic()

    async with httpx.AsyncClient(base_url=BASE, timeout=300) as client:
        await _login(client)

        async def one(slug: str) -> dict[str, object]:
            async with sem:
                try:
                    return await _run_story(client, slug, args.turns)
                except Exception as exc:  # noqa: BLE001 - 한 스토리 실패가 나머지를 막지 않게
                    return {"slug": slug, "error": f"{type(exc).__name__}: {exc}"}

        results = await asyncio.gather(*(one(s) for s in slugs))

    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = [r for r in results if "error" not in r]
    print(f"완료 {len(ok)}/{len(slugs)} — {time.monotonic() - started:.0f}초, 출력 {args.out}")
    for r in results:
        if "error" in r:
            print(f"  실패 {r['slug']}: {r['error']}")


if __name__ == "__main__":
    asyncio.run(main())
