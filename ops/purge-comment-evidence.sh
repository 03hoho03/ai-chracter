#!/bin/sh
# JSON을 포함하는 운영 env 전체를 source하지 않고 DB 연결 값만 읽는다.
DATABASE_URL=$(grep '^DATABASE_URL=' /opt/ddona/.env | cut -d= -f2-)
export DATABASE_URL
export PG_DOCKER_NETWORK=ddona_default
cd /opt/ddona/app/apps/api || exit 1
exec env PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.purge_comment_evidence
