"""Upstash Redis 의 전 키를 TTL 까지 담아 파일 하나로 뜬다.

    cd apps/api && PYTHONPATH=scripts uv run --env-file ~/.config/ddona/prod.env \\
        python -m ops.snapshot_redis --out ~/backups/redis-snapshot.jsonl

**이관용이 아니라 보험용이다.** 이번 이전에서 Redis 데이터는 **옮기지 않기로 확정됐다** —
컷오버와 함께 세션·미리보기 세션이 버려지고 사용자는 재로그인한다(`tasks/preview-progress.md` 결정 9).
그래도 스냅샷을 뜨는 건, 그 판단이 뒤집혔을 때 **되돌릴 수 있는 유일한 경로**인데 비용이 거의
없기 때문이다. 되살리는 쪽(`RESTORE`)은 일부러 만들지 않는다 — 쓰지 않기로 한 경로에 코드를
미리 짜 두면 검증되지 않은 채 남는다. 필요해지면 이 파일 포맷을 보고 그때 짜면 된다.

⚠️ **`DUMP` 의 직렬화 포맷은 Redis 버전에 묶인다 — 이건 실측이다.** Upstash(`redis_version` 8.4.0)가
만든 페이로드를 `redis:7-alpine` 에 넣으면 `DUMP payload version or checksum are wrong` 으로
거부되고 `redis:8-alpine`(8.10.1)에서는 통과한다(2026-09-02 확인). 그래서 스냅샷을 뜰 때 원본의
`redis_version` 을 파일 첫 줄 메타에 박아 둔다 — 되살릴 때 대상 버전을 여기에 맞춰야 한다.

출력은 JSON Lines 다 — 첫 줄이 메타, 이후 한 줄에 키 하나(`{"key", "pttl", "dump"}`).
`dump` 는 바이너리라 base64 로 담는다.
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

import redis


def snapshot(client: redis.Redis, out: Path) -> tuple[int, int]:
    """전 키를 순회해 파일로 쓴다. (총 키 수, TTL 없는 키 수)를 돌려준다.

    `SCAN` 을 쓰는 건 `KEYS *` 가 운영 중인 Redis 를 멈춰 세우기 때문이다. 스냅샷은 살아 있는
    프로덕션에 대고 도는 작업이라 블로킹 명령을 쓰지 않는다.
    """
    info = client.info("server")
    version = str(info["redis_version"])

    total = persistent = 0
    with out.open("w") as handle:
        handle.write(json.dumps({"redis_version": version, "format": "dump-base64"}) + "\n")
        for key in client.scan_iter(count=200):
            payload = client.dump(key)
            if payload is None:
                continue  # SCAN 과 DUMP 사이에 만료됐다. 사라진 게 정상이라 세지 않는다.
            pttl = int(client.pttl(key))
            if pttl < 0:
                persistent += 1
            handle.write(
                json.dumps(
                    {
                        "key": base64.b64encode(key).decode(),
                        "pttl": pttl,
                        "dump": base64.b64encode(payload).decode(),
                    }
                )
                + "\n"
            )
            total += 1
    print(f"원본 redis_version: {version}")
    return total, persistent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL"))
    args = parser.parse_args()

    if not args.redis_url:
        print("REDIS_URL 이 없다", file=sys.stderr)
        return 1

    client = redis.from_url(args.redis_url)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    dbsize = int(client.dbsize())
    total, persistent = snapshot(client, args.out)

    print(f"✅ {total}개 키 → {args.out} ({args.out.stat().st_size / 1024:.1f} KB)")
    print(f"   SCAN {total}개 / DBSIZE {dbsize} / TTL 없는 키 {persistent}개")
    if total != dbsize:
        # 참고 수치일 뿐 실패가 아니다. Upstash 의 DBSIZE·INFO 는 실제 키 상태와 어긋난다 —
        # 2026-09-02 실측에서 `INFO keyspace` 가 `keys=23, expires=0` 을 보고했는데 열거된 7개는
        # 전부 TTL 이 있었다. 즉 `expires=0` 이 거짓이므로 DBSIZE 도 대조군으로 쓸 수 없다.
        # 실제로 읽어서 옮길 수 있는 키는 SCAN 이 돌려주는 쪽이다.
        print(f"   ℹ DBSIZE 와 {abs(dbsize - total)}개 차이 — Upstash 의 DBSIZE 는 신뢰할 대조군이 아니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
