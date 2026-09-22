#!/bin/sh
# clover-page-goal-prompt.md CE-9: `ops/cron.d/ddona-clover-expire`가 매일(KST 00:05) 이 스크립트를 부른다.
#
# `/opt/ddona/.env`를 통째로 source하지 않는다 — `purge-image-requests.sh`·`resource-check.sh`와
# 같은 이유(JSON 값이 쉘 문법과 부딪친다). 필요한 키만 뽑아 export한다.
#
# `expire_clover.py`가 `run_sh`로 컨테이너 안 `psql`을 띄워 운영 DB에 직접 붙으므로
# `DATABASE_URL`이 필요하고, 운영 Postgres는 포트를 게시하지 않으므로(DEPLOY.md §3-4)
# `PG_DOCKER_NETWORK`도 없으면 접속 자체가 안 된다.
DATABASE_URL=$(grep '^DATABASE_URL=' /opt/ddona/.env | cut -d= -f2-)
DISCORD_WEBHOOK_URL=$(grep '^DISCORD_WEBHOOK_URL=' /opt/ddona/.env | cut -d= -f2-)
export DATABASE_URL DISCORD_WEBHOOK_URL
export PG_DOCKER_NETWORK=ddona_default

cd /opt/ddona/app/apps/api || exit 1
exec env PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.expire_clover
