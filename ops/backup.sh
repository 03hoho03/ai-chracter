#!/usr/bin/env bash
# VM 로컬 Postgres 를 덤프해 R2 에 올린다. VM 의 `/etc/cron.d/ddona-backup`(저장소 밖 로컬 파일)이 매일 18:00 UTC 에 부른다.
#
# `.env` 를 통째로 source 하지 않는다 — `CORS_ALLOW_ORIGINS` 값이 `["https://a","https://b"]` 라
# 쉘 문법과 부딪친다(`resource-check.sh`·`bugsink-vacuum.sh` 도 같은 이유로 같은 방식이다).
# 필요한 키만 뽑아 넘긴다.
#
# ⚠️ 이 목록이 곧 `backup_db.py` 가 볼 수 있는 환경의 전부다. 알림 키를 빠뜨려도 백업 자체는
# 성공하므로 **아무 증상 없이 감시만 죽는다** — 2026-09-16 에 실제로 그 상태였다. VM 로컬에만
# 있던 옛 판(9/2자)에 `HEALTHCHECKS_BACKUP_PING_URL`·`DISCORD_WEBHOOK_URL` 이 없어서 healthchecks.io
# dead-man's switch 와 R2 용량 경고가 둘 다 침묵했다. 그 사고가 이 파일을 저장소로
# 올린 이유다 — 이제 `ops/*` 의 다른 스크립트들처럼 배포로 갱신된다.
set -euo pipefail
for k in DATABASE_URL S3_ENDPOINT_URL AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_REGION S3_BUCKET_NAME \
         HEALTHCHECKS_BACKUP_PING_URL DISCORD_WEBHOOK_URL; do
  export "$k=$(grep -m1 "^${k}=" /opt/ddona/.env | cut -d= -f2-)"
done
# 운영 Postgres 는 포트를 게시하지 않으므로 compose 네트워크에 붙어야 닿는다.
export PG_DOCKER_NETWORK=ddona_default
export PYTHONPATH=/opt/ddona/scripts
exec /usr/bin/python3 -m ops.backup_db --out-dir /opt/ddona/backups
