"""스토리 여러 개와 채팅해 대화록을 남기는 진단용 드라이버 (일회성, 시드와 무관).

앵무새 패턴 점검용. 대화록은 JSON 으로 떨어뜨리고 판단은 사람/에이전트가 한다 —
이 스크립트는 판단하지 않는다.

    cd apps/api && uv run --env-file .env python scripts/chat_probe.py \
        --slugs mystery-elevator,sf-backup --turns 5 --out /tmp/probe.json

**쿼터가 이 스크립트의 진짜 제약이다.** 무료 티어는 모델당 분당 15요청(RPD 가 아니라
RPM)이고 스토리 챗 1턴 = LLM 2회(생성 + 스탯 판단)라, 전체 합쳐 **분당 7.5턴이 천장**이다
(엔딩 판정은 `turnCountGate` 를 넘긴 턴에만 붙으므로 5턴 프로브에는 보통 안 붙는다 —
돌리기 전에 대상 스토리의 게이트를 확인할 것). 그래서 기본값이 `--concurrency 1` +
`--interval 10` 이다: 동시 실행은 예산을 늘려주지 않으면서 벽시계만 줄이려다 429 로
턴을 통째로 날린다(실측: 5개 동시 × 2세션에서 130턴 중 102턴이 빈 응답으로 유실).
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import TypedDict

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


class _Pacer:
    """턴 시작 간격의 하한을 강제해 분당 요청 상한 아래에 머문다.

    1턴 = LLM 2회라 간격 10초면 분당 12회로 상한(15)에 여유를 둔다. 요청이 실제로 몇 초
    걸리든 상관없이 "시작 시각" 기준으로 간격을 재므로, 응답이 빨라져도 버스트가 안 난다.
    """

    def __init__(self, interval: float) -> None:
        self._interval = interval
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if now < self._next:
                await asyncio.sleep(self._next - now)
            self._next = max(now, self._next) + self._interval


async def _login(client: httpx.AsyncClient) -> None:
    r = await client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    r.raise_for_status()


class _Turn(TypedDict):
    reply: str
    events: list[str]
    seconds: float


# 대화가 정상인데 붙는 부수 이벤트(stat/ending)와, 그 턴이 실패했다는 신호를 구분한다.
_FAILURE_PREFIXES = ("error", "policyWarning", "HTTP")


async def _send(client: httpx.AsyncClient, room_id: str, text: str) -> _Turn:
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


async def _run_story(
    client: httpx.AsyncClient, slug: str, turns: int, pacer: _Pacer
) -> dict[str, object]:
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
    empty, failed = 0, 0
    for text in TURNS[:turns]:
        await pacer.wait()
        transcript.append({"role": "사용자", "text": text})
        got = await _send(client, room["id"], text)
        if not got["reply"]:
            empty += 1
        failed += sum(1 for event in got["events"] if event.startswith(_FAILURE_PREFIXES))
        transcript.append(
            {"role": "진행자", "text": got["reply"], "events": got["events"], "seconds": got["seconds"]}
        )
    # 빈 응답은 거의 항상 쿼터 소진(429)이다 — 대화록을 읽기 전에 여기서 먼저 드러나야 한다.
    print(f"  · {slug:26} 빈응답 {empty}/{turns}, 에러이벤트 {failed}", flush=True)
    return {
        "slug": slug,
        "name": detail.json().get("name"),
        "roomId": room["id"],
        "emptyReplies": empty,
        "transcript": transcript,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slugs", required=True, help="쉼표로 구분한 스토리 slug 목록")
    ap.add_argument("--turns", type=int, default=5)
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--concurrency", type=int, default=1, help="동시에 진행할 스토리 수 (쿼터가 공유되므로 1 권장)"
    )
    ap.add_argument(
        "--interval", type=float, default=10.0, help="턴 시작 간격의 하한(초). 1턴=LLM 2회 기준"
    )
    args = ap.parse_args()

    slugs = [s.strip() for s in args.slugs.split(",") if s.strip()]
    sem = asyncio.Semaphore(args.concurrency)
    pacer = _Pacer(args.interval)
    started = time.monotonic()
    print(
        f"스토리 {len(slugs)}개 × {args.turns}턴 = 요청 {len(slugs) * args.turns * 2}회, "
        f"간격 {args.interval}초 → 예상 {len(slugs) * args.turns * args.interval / 60:.0f}분",
        flush=True,
    )

    async with httpx.AsyncClient(base_url=BASE, timeout=300) as client:
        await _login(client)

        async def one(slug: str) -> dict[str, object]:
            async with sem:
                try:
                    return await _run_story(client, slug, args.turns, pacer)
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
