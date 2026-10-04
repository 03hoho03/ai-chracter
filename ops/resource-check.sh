#!/bin/sh
# `ops/cron.d/ddona-resource-check`가 5분마다 이 스크립트를 부른다.
#
# `/opt/ddona/.env`를 통째로 source하지 않는다 — `CORS_ALLOW_ORIGINS` 같은 JSON 값이 쉘 문법과
# 부딪친다(`backup.sh`가 같은 이유로 이미 이렇게 한다, DEPLOY.md 참고). 필요한 키 둘만 뽑아
# export한다. 둘 다 값이 없어도 안전하다 — `ops/notify.py`의 `notify()`/`ping()` 호출부가
# 빈 문자열을 "설정 안 함"으로 다뤄 조용히 건너뛴다.
DISCORD_WEBHOOK_URL=$(grep '^DISCORD_WEBHOOK_URL=' /opt/ddona/.env | cut -d= -f2-)
HEALTHCHECKS_RESOURCE_PING_URL=$(grep '^HEALTHCHECKS_RESOURCE_PING_URL=' /opt/ddona/.env | cut -d= -f2-)
export DISCORD_WEBHOOK_URL HEALTHCHECKS_RESOURCE_PING_URL

# 알림 상태(항목별 경고 여부·마지막 알림 시각)는 배포마다 `git reset --hard` 되는 체크아웃 밖에 둔다.
# 디렉터리를 못 만들어도 멈추지 않는다 — 파이썬 쪽이 상태를 못 쓰면 stderr 에 남기고 계속해
# healthchecks.io ping 까지 간다(그 대가는 같은 경고가 실행마다 다시 가는 것뿐이다).
STATE_DIR=/var/lib/ddona
mkdir -p "$STATE_DIR"

cd /opt/ddona/app/apps/api || exit 1
exec env PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.check_resources \
  --state-file "$STATE_DIR/resource-check.state"
