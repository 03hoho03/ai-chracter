#!/usr/bin/env bash
# `ops/cron.d/ddona-daily-digest` 가 매일(KST 09:00) 이 스크립트를 부른다.
#
# 일일 운영 요약(`python -m api.ops_digest`)을 지금 서빙 중인 api 컨테이너 안에서 돌린다. 모델·단가표·사용량 집계 읽기가 앱
# 코드에 있어 컨테이너 안에서 돈다. 요약은 읽기 전용 트랜잭션에서 SELECT 만 하고, 무엇도 자동으로 바꾸지 않는다. 인자는 그대로
# 넘긴다(`--date`·`--dry-run`).
#
# `/opt/ddona/.env` 를 통째로 source 하지 않는다(`expire-clover.sh` 와 같은 이유 — JSON 값이 쉘 문법과 부딪친다).
# 알림 주소 `DISCORD_WEBHOOK_URL` 만 뽑는다. DB·Redis 접속은 컨테이너가 자기 env 로 한다.
#
# 알림: 다른 리포트 래퍼는 마지막 한 줄만 보내지만 요약은 여러 줄·여러 통이라, 성공하면 출력 전체를 알림 모듈의 표준입력으로
# 넘기고 그 모듈이 머리 줄마다 한 통씩 보낸다(한 통이 Discord 상한을 넘지 않게 나누는 것은 요약 쪽이 한다). `--dry-run` 출력에는
# 머리 줄이 없어 아무것도 가지 않는다. 실패(색을 못 고름·요약 실패)는 고정 문구다 — 예외 문장에는 SQL 인자가 섞일 수 있어 로그
# 파일에만 남긴다. 실패한 날은 `--date` 로 그날을 다시 돌린다.
set -uo pipefail

# 심볼릭 링크(`/opt/ddona/daily-digest.sh`)로 불리므로 링크가 가리키는 저장소 `ops/` 를 찾는다.
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/bluegreen.sh source-path=SCRIPTDIR
source "$SCRIPT_DIR/lib/bluegreen.sh"
LOG_NAME=daily-digest

DISCORD_WEBHOOK_URL=$(grep '^DISCORD_WEBHOOK_URL=' "$DDONA_ENV" | cut -d= -f2-)
export DISCORD_WEBHOOK_URL

alert() {
  PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.daily_digest_notify "$1" || true
}

# 교체 중이라 색을 하나로 못 고르면 그날은 실패로 끝난다 — 엉뚱한 컨테이너에서 돌리지 않는다.
if ! color="$(bash "$SCRIPT_DIR/active-color.sh")"; then
  log "서빙 중인 api 색을 고르지 못했다"
  alert "📊 일일 운영 요약 실패: 서빙 중인 api 색을 고르지 못했다(교체 중?) — 그날을 --date 로 다시 돌린다"
  exit 1
fi

output="$(compose exec -T "api_$color" python -m api.ops_digest "$@")"
code=$?
printf '%s\n' "$output"
if [ "$code" -ne 0 ]; then
  log "요약 실패(종료 코드 $code)"
  alert "📊 일일 운영 요약 실패(종료 코드 $code) — /var/log/ddona-daily-digest.log 확인, 그날을 --date 로 다시 돌린다"
  exit "$code"
fi

printf '%s\n' "$output" | PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.daily_digest_notify || true
