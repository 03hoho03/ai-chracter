#!/bin/sh
# image-monitoring-goal-prompt.md IM-7a: `ops/cron.d/ddona-image-request-purge`가 매일 이 스크립트를 부른다.
#
# `/opt/ddona/.env`를 통째로 source하지 않는다 — `resource-check.sh`·`bugsink-vacuum.sh`와 같은 이유
# (JSON 값이 쉘 문법과 부딪친다). 필요한 키만 뽑아 export한다.
#
# ⚠️ `bugsink-vacuum.sh`와 다르다 — 그 스크립트는 `docker exec`로 Bugsink 컨테이너 안에 들어갈
# 뿐 Postgres에 직접 접속하지 않지만, 이 모듈(`purge_image_requests.py`)은 `backup_db.py`처럼
# `run_sh`로 컨테이너 안 `psql`을 띄워 운영 DB에 직접 붙는다. 그래서 `DATABASE_URL`이 필요하고,
# 운영 Postgres는 포트를 게시하지 않으므로(`backup.sh`·DEPLOY.md §3-4) `PG_DOCKER_NETWORK`도
# 없으면 접속 자체가 안 된다.
DATABASE_URL=$(grep '^DATABASE_URL=' /opt/ddona/.env | cut -d= -f2-)
DISCORD_WEBHOOK_URL=$(grep '^DISCORD_WEBHOOK_URL=' /opt/ddona/.env | cut -d= -f2-)
export DATABASE_URL DISCORD_WEBHOOK_URL
export PG_DOCKER_NETWORK=ddona_default

cd /opt/ddona/app/apps/api || exit 1
exec env PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.purge_image_requests
