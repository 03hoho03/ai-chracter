#!/bin/sh
# `ops/cron.d/ddona-bugsink-vacuum`가 매일 이 스크립트를 부른다.
#
# `/opt/ddona/.env`를 통째로 source하지 않는다 — `resource-check.sh`·`backup.sh`와 같은 이유(JSON
# 값이 쉘 문법과 부딪친다). `DISCORD_WEBHOOK_URL` 하나만 뽑아 export한다 — 값이 없어도 안전하다
# (`ops/notify.py`의 `notify()`가 빈 문자열을 "설정 안 함"으로 다뤄 조용히 건너뛴다).
DISCORD_WEBHOOK_URL=$(grep '^DISCORD_WEBHOOK_URL=' /opt/ddona/.env | cut -d= -f2-)
export DISCORD_WEBHOOK_URL

cd /opt/ddona/app/apps/api || exit 1
exec env PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.vacuum_bugsink
