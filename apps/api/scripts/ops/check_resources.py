"""VM 메모리·디스크를 직접 읽어 임계를 넘거나 다시 내려올 때 Discord로 알린다.

    # VM 크론 (5분마다, ops/cron.d/ddona-resource-check 가 ops/resource-check.sh 를 부른다)
    cd /opt/ddona/app/apps/api && PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.check_resources \
        --state-file /var/lib/ddona/resource-check.state

알림은 **상태가 바뀔 때만** 간다(정상→경고, 경고→정상 "복구"). 5분마다 같은 경고를 보내면 채널이
같은 줄로 덮여 정작 새 경고가 묻히기 때문이다. 경고가 이어지면 첫 알림이 묻혔을 때를 대비해
24시간마다 한 번 다시 보낸다. 항목별 마지막 상태는 `--state-file` 에 남긴다 — 배포마다
`git reset --hard` 되는 체크아웃 밖이어야 하므로 경로를 인자로 받는다.

GCP의 balloon 메트릭(`instance/memory/balloon/ram_used`) 대신 `free`/`df`를 직접 읽는 이유는
우리 VM에서 실측 1.78GB로 `free -m`의 890MB와 2배 차이가 났고, 그
메트릭은 e2 계열 전용이라 인스턴스 타입을 바꾸면 조용히 사라지기 때문이다.

같은 실행이 healthchecks.io로도 ping한다 — VM 자체의 생사를 VM 밖에서 보기 위해서다
(`ops/backup_db.py`의 healthchecks.io check-in과 같은 이유).

⚠️ **이 파일은 `backup_db.py`와 같은 이유로 SQLAlchemy/asyncpg/`api.*`를 import 하면 안 된다**
— 프로덕션 크론은 시스템 `/usr/bin/python3`(boto3만 있고 SQLAlchemy는 없음)로 돈다.
`tests/test_ops_production_cron_importable.py`가 이 제약을 `ast`로 고정한다.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from typing import TypedDict

from ops.notify import notify, ping

DEFAULT_MEMORY_THRESHOLD_PERCENT = 90.0
DEFAULT_DISK_THRESHOLD_PERCENT = 85.0
RENOTIFY_AFTER_SECONDS = 24 * 60 * 60

# 상태 파일의 항목 키와 복구 알림에 쓰는 이름. 순서가 로그·알림 순서다.
_RESOURCE_LABELS = {"memory": "메모리", "disk": "디스크(/)"}
_MESSAGE_PREFIX = "🖥️ ddona-api VM: "


class ItemState(TypedDict):
    alerting: bool
    last_notified_at: float | None


def _read(cmd: list[str]) -> str:
    """`cmd`를 돌려 stdout을 돌려준다. 실패하면 stderr를 담아 터뜨린다."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} 실패:\n{result.stderr.strip()}")
    return result.stdout


def parse_memory_used_percent(free_output: str) -> float:
    """`free -m`의 `Mem:` 줄에서 `(total - available) / total`을 퍼센트로 돌려준다.

    `used` 컬럼이 아니라 `available`을 쓴다 — `used`는 회수 가능한 buff/cache를 실사용량에
    포함시켜, 캐시가 쌓이기만 해도 거의 항상 높게 나온다.
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


def _healthy() -> ItemState:
    return {"alerting": False, "last_notified_at": None}


def load_state(path: str | os.PathLike[str]) -> dict[str, ItemState]:
    """항목별 마지막 상태를 읽는다. 못 읽는 항목은 "정상, 알린 적 없음" 으로 본다.

    경고 중이었다면 다음 실행이 한 번 더 보낸다 — 알림을 놓치는 것보다 한 번 중복되는 편이 낫다.
    파일 없음·JSON 오류·모양이 다른 항목을 모두 같은 규칙으로 다룬다.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}

    state: dict[str, ItemState] = {}
    for key in _RESOURCE_LABELS:
        item = raw.get(key)
        state[key] = _healthy()
        if not isinstance(item, dict):
            continue
        alerting = item.get("alerting")
        last = item.get("last_notified_at")
        # bool 은 int 의 하위형이라 시각 자리에 true 가 들어와도 숫자로 통과하지 않게 따로 막는다.
        last_is_valid = last is None or (isinstance(last, (int, float)) and not isinstance(last, bool))
        if isinstance(alerting, bool) and last_is_valid:
            state[key] = {"alerting": alerting, "last_notified_at": None if last is None else float(last)}
    return state


def save_state(path: str | os.PathLike[str], state: dict[str, ItemState]) -> None:
    """같은 디렉터리의 임시 파일에 쓰고 바꿔 끼운다 — 쓰다 죽어도 반쯤 쓴 파일이 남지 않는다.
    크론 실행은 5분 간격이라 겹치지 않으므로 임시 이름은 고정으로 충분하다."""
    tmp_path = f"{os.fspath(path)}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle)
    os.replace(tmp_path, path)


def decide(
    previous: dict[str, ItemState],
    current: dict[str, str | None],
    now: float,
    renotify_after: float = RENOTIFY_AFTER_SECONDS,
) -> tuple[dict[str, str], dict[str, ItemState]]:
    """이번 측정(`current`: 항목별 경고 메시지 또는 `None`)과 지난 상태로 보낼 알림(항목 → 문구)과
    다음 상태를 정한다.

    경고 값이 더 나빠져도 상태(경고 중)는 그대로라 다시 보내지 않는다 — 그 사이에는 24시간 재알림만 간다.
    """
    to_send: dict[str, str] = {}
    next_state: dict[str, ItemState] = {}
    for key, label in _RESOURCE_LABELS.items():
        before = previous.get(key, _healthy())
        message = current.get(key)
        if message is None:
            if before["alerting"]:
                to_send[key] = f"{_MESSAGE_PREFIX}✅ {label} 복구 — 임계값 아래로 내려왔다"
            next_state[key] = _healthy()
        elif not before["alerting"]:
            to_send[key] = f"{_MESSAGE_PREFIX}{message}"
            next_state[key] = {"alerting": True, "last_notified_at": now}
        elif before["last_notified_at"] is None or now - before["last_notified_at"] >= renotify_after:
            to_send[key] = f"{_MESSAGE_PREFIX}{message} (24시간 넘게 지속 중)"
            next_state[key] = {"alerting": True, "last_notified_at": now}
        else:
            next_state[key] = before
    return to_send, next_state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # 기본값을 두지 않는다 — 기본값이 있으면 테스트(비 root)가 운영 경로에 쓰려 들고, 래퍼에서 인자가
    # 빠졌을 때 조용히 다른 곳에 상태를 쌓는다.
    parser.add_argument("--state-file", required=True, help="항목별 마지막 알림 상태를 남길 JSON 파일")
    args = parser.parse_args()

    memory_threshold = float(
        os.environ.get("MEMORY_ALERT_THRESHOLD_PERCENT", DEFAULT_MEMORY_THRESHOLD_PERCENT)
    )
    disk_threshold = float(
        os.environ.get("DISK_ALERT_THRESHOLD_PERCENT", DEFAULT_DISK_THRESHOLD_PERCENT)
    )

    free_output = _read(["free", "-m"])
    df_output = _read(["df", "/"])

    current = {
        "memory": check_memory(free_output, threshold_percent=memory_threshold),
        "disk": check_disk(df_output, threshold_percent=disk_threshold),
    }
    previous = load_state(args.state_file)
    to_send, next_state = decide(previous, current, now=time.time())

    failed: set[str] = set()
    for key, notice in to_send.items():
        if not notify(notice):
            failed.add(key)
            # 보내지 못한 알림을 "보냈다" 로 남기면 다음 24시간 동안 아무도 모른다 — 이 항목은 지난 상태로
            # 두어 다음 실행이 다시 보내게 한다.
            next_state[key] = previous[key]

    # 운영에서 억제가 도는지는 이 로그 줄로 확인한다 — 보낸 실행과 생략한 실행을 구별해 찍는다.
    def _outcome(key: str) -> str:
        if key not in to_send:
            return "지속 — 알림 생략"
        return "알림 실패" if key in failed else "알림"

    for key, message in current.items():
        if message is not None:
            print(f"⚠️ {message} ({_outcome(key)})")
        elif key in to_send:
            print(f"{to_send[key].removeprefix(_MESSAGE_PREFIX)} ({_outcome(key)})")
    if all(message is None for message in current.values()):
        print("✅ 리소스 정상")

    try:
        save_state(args.state_file, next_state)
    except OSError as error:
        # 죽게 두면 아래 ping 이 빠져 VM 이 멈춘 것처럼 보인다. 상태를 못 남긴 대가는 다음 실행이 같은
        # 경고를 다시 보내는 것(상태 파일이 없던 때의 동작)이라 계속 가는 편이 안전하다.
        print(f"상태 파일을 쓰지 못했다({args.state_file}): {error}", file=sys.stderr)

    # dead man's switch — 크론이 죽으면 healthchecks.io가 grace time 초과로 잡는다.
    # 임계 초과 여부와 무관하게 매번 ping한다(살아서 돌았다는 사실 자체가 신호이기 때문에
    # 경고·알림 분기 밖에 둔다).
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
