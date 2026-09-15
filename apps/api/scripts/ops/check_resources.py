"""VM 메모리·디스크를 직접 읽어 임계 초과 시 Discord로 알린다(monitoring-techspec.md MT-13).

    # VM 크론 (5분마다, ops/cron.d/ddona-resource-check 로 설치)
    cd /opt/ddona/app/apps/api && PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.check_resources

GCP의 balloon 메트릭(`instance/memory/balloon/ram_used`) 대신 `free`/`df`를 직접 읽는 이유는
techspec MT-13 참고 — 우리 VM에서 실측 1.78GB로 `free -m`의 890MB와 2배 차이가 났고, 그
메트릭은 e2 계열 전용이라 인스턴스 타입을 바꾸면 조용히 사라진다.

같은 실행이 healthchecks.io로도 ping한다 — VM 자체의 생사를 VM 밖에서 보기 위해서다
(`ops/backup_db.py`의 MT-11과 같은 이유).

⚠️ **이 파일은 `backup_db.py`와 같은 이유로 SQLAlchemy/asyncpg/`api.*`를 import 하면 안 된다**
— 프로덕션 크론은 시스템 `/usr/bin/python3`(boto3만 있고 SQLAlchemy는 없음)로 돈다.
`tests/test_ops_production_cron_importable.py`가 이 제약을 `ast`로 고정한다.
"""

import argparse
import os
import subprocess
import sys

from ops.notify import notify, ping

DEFAULT_MEMORY_THRESHOLD_PERCENT = 90.0
DEFAULT_DISK_THRESHOLD_PERCENT = 85.0


def _read(cmd: list[str]) -> str:
    """`cmd`를 돌려 stdout을 돌려준다. 실패하면 stderr를 담아 터뜨린다."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} 실패:\n{result.stderr.strip()}")
    return result.stdout


def parse_memory_used_percent(free_output: str) -> float:
    """`free -m`의 `Mem:` 줄에서 `(total - available) / total`을 퍼센트로 돌려준다.

    `used` 컬럼이 아니라 `available`을 쓴다 — `used`는 회수 가능한 buff/cache를 실사용량에
    포함시켜, 캐시가 쌓이기만 해도 거의 항상 높게 나온다(MT-13).
    """
    for line in free_output.splitlines():
        if line.startswith("Mem:"):
            # 컬럼 순서: total used free shared buff/cache available
            total, _used, _free, _shared, _buff_cache, available = (int(x) for x in line.split()[1:7])
            return (total - available) / total * 100
    raise ValueError("`free -m` 출력에 'Mem:' 줄이 없다")


def parse_disk_used_percent(df_output: str, *, mount: str = "/") -> float:
    """`df` 출력에서 `mount`의 `Use%` 컬럼을 읽는다."""
    for line in df_output.splitlines()[1:]:  # 헤더 제외
        fields = line.split()
        if fields and fields[-1] == mount:
            return float(fields[-2].rstrip("%"))
    raise ValueError(f"`df` 출력에 마운트 {mount!r} 줄이 없다")


def check_memory(free_output: str, *, threshold_percent: float) -> str | None:
    """임계 초과면 알림 메시지를, 아니면 `None`을 돌려준다."""
    used_percent = parse_memory_used_percent(free_output)
    if used_percent >= threshold_percent:
        return f"메모리 사용률 {used_percent:.1f}% (임계값 {threshold_percent:.0f}%)"
    return None


def check_disk(df_output: str, *, threshold_percent: float, mount: str = "/") -> str | None:
    used_percent = parse_disk_used_percent(df_output, mount=mount)
    if used_percent >= threshold_percent:
        return f"디스크({mount}) 사용률 {used_percent:.1f}% (임계값 {threshold_percent:.0f}%)"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    memory_threshold = float(
        os.environ.get("MEMORY_ALERT_THRESHOLD_PERCENT", DEFAULT_MEMORY_THRESHOLD_PERCENT)
    )
    disk_threshold = float(
        os.environ.get("DISK_ALERT_THRESHOLD_PERCENT", DEFAULT_DISK_THRESHOLD_PERCENT)
    )

    free_output = _read(["free", "-m"])
    df_output = _read(["df", "/"])

    alerts = [
        message
        for message in (
            check_memory(free_output, threshold_percent=memory_threshold),
            check_disk(df_output, threshold_percent=disk_threshold),
        )
        if message is not None
    ]

    for message in alerts:
        print(f"⚠️ {message}")
        notify(f"🖥️ ddona-api VM: {message}")

    if not alerts:
        print("✅ 리소스 정상")

    # MT-13: dead man's switch — 크론이 죽으면 healthchecks.io가 grace time 초과로 잡는다.
    # 임계 초과 여부와 무관하게 매번 ping한다(살아서 돌았다는 사실 자체가 신호이기 때문에
    # `alerts` 분기 밖에 둔다).
    ping_url = os.environ.get("HEALTHCHECKS_RESOURCE_PING_URL")
    if ping_url:
        ping(ping_url)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError) as error:
        print(f"실패: {error}", file=sys.stderr)
        sys.exit(1)
