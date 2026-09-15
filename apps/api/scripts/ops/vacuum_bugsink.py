"""Bugsink 가 보관하는 오류 이벤트를 `MAX_EVENT_AGE_DAYS`보다 오래된 것부터 지운다
(monitoring-legal-draft.md §7-6, MT-16).

    # VM 크론 (매일, ops/cron.d/ddona-bugsink-vacuum 로 설치)
    cd /opt/ddona/app/apps/api && PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.vacuum_bugsink

`docker-compose.monitoring.yml`이 `MAX_EVENT_AGE_DAYS: "30"`을 고정해도, 그 값을 실제로 적용하는
건 `bugsink-manage vacuum --old-events` 관리 명령이고, Bugsink 공식 이미지는 이 명령을 도는
스케줄러를 컨테이너 안에 두지 않는다(Dockerfile CMD 확인 — gunicorn+snappea 뿐). 이 모듈이 그
역할을 host cron에서 대신한다.

**명령은 로컬 실측으로 확인했다**(2026-09-15, `bugsink/bugsink:2` == 2.6.0, `bugsink-manage
vacuum --help`): `--old-events`는 `get_settings().MAX_EVENT_AGE_DAYS`(compose env로 고정된 값)를
그대로 읽어 그보다 오래된 이벤트를 지운다 — 별도 `--max-event-age-days` 플래그가 필요 없다
(`bsmain/management/commands/vacuum.py` 소스도 확인: `days = options["max_event_age_days"]; if
days is None: days = get_settings().MAX_EVENT_AGE_DAYS`).

**컨테이너 지목은 이름 하나로 고정한다** — `docker-compose.monitoring.yml`의 `name:
ddona-monitoring` + 서비스 `bugsink`(replica 1개)는 Compose V2 관례상 컨테이너명을
`ddona-monitoring-bugsink-1`로 결정한다. 추측이 아니라 `docker compose config`로 프로젝트·서비스
이름을 확인하고, 로컬에서 실제로 `docker compose up`한 컨테이너의 이름을 실측했다. `docker
compose exec`가 아니라 `docker exec <고정 이름>`을 쓰는 이유는 이 스크립트가
`docker-compose.monitoring.yml`의 경로나 실행 시점 cwd를 몰라도 되게 하기 위해서다
(`resource-check.sh`가 `free`/`df`를 직접 읽는 것과 같은 host-스크립트 단순화).

**컨테이너가 안 떠 있으면 `docker exec` 자체가 nonzero exit + stderr 메시지를 낸다**(로컬 실측:
"Error response from daemon: container ... is not running" / "No such container"). `bugsink`
서비스는 `docker-compose.prod.yml`의 배포 워크플로 밖에서 수동으로 기동·재기동되므로
(`docker-compose.monitoring.yml` 헤더 주석), 앱 배포와 무관하게 내려가 있을 수 있다. 이 모듈은
그 실패를 삼키지 않고 Discord로 알린다(`ops/notify.py`) — 조용히 실패하면 방침 문안이 약속한
"30일 보관 후 파기"가 아무도 모르게 깨진다(이 모듈이 생긴 배경 자체가 그 문제). 별도
healthchecks.io dead man's switch는 만들지 않았다 — 이 작업의 범위는 "vacuum이 실제로 도는가"이지
"bugsink 서비스 자체의 생사"가 아니고(후자는 별도 관심사), Discord 알림 하나로 "실패를 아무도
모른다"는 실제 위험은 이미 닫힌다.

⚠️ **이 파일은 `check_resources.py`와 같은 이유로 SQLAlchemy/asyncpg/`api.*`를 import 하면
안 된다** — 프로덕션 크론은 시스템 `/usr/bin/python3`(boto3만 있고 SQLAlchemy는 없음)로 돈다.
`tests/test_ops_production_cron_importable.py`가 이 제약을 `ast`로 고정한다.
"""

import argparse
import subprocess
import sys

from ops.notify import notify

CONTAINER_NAME = "ddona-monitoring-bugsink-1"


def run_vacuum(container: str = CONTAINER_NAME) -> str:
    """`container` 안에서 `bugsink-manage vacuum --old-events`를 돈다.

    실패하면(컨테이너 미기동·미존재 포함 — `docker exec`가 그 경우도 nonzero exit + stderr로
    알려준다) stderr를 담아 RuntimeError를 던진다.
    """
    result = subprocess.run(
        ["docker", "exec", container, "bugsink-manage", "vacuum", "--old-events"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"docker exec 실패(exit {result.returncode})")
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    output = run_vacuum()
    print(output.strip() or "✅ vacuum 완료")
    return 0


def _on_failure(error: Exception) -> int:
    """실패를 stderr에 남기고 Discord로 알린다 — 조용히 실패하면 "30일 보관 후 파기" 약속이
    아무도 모르게 깨진다(이 모듈의 배경)."""
    print(f"실패: {error}", file=sys.stderr)
    notify(f"🗑️ ddona-monitoring bugsink vacuum 실패: {error}")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as error:
        sys.exit(_on_failure(error))
