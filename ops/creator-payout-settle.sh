#!/usr/bin/env bash
# `ops/cron.d/ddona-creator-payout-settle` 가 매일(KST 01:35) 이 스크립트를 부른다.
#
# 크리에이터 정산 월 확정(`python -m api.creator_payout.monthly`)을 지금 서빙 중인 api 컨테이너 안에서 돌린다. 승인 때의
# 소급과 같은 계산 코드를 쓰려고 컨테이너 안에서 돌린다 — 계산식과 비율 설정이 앱 한 곳에만 있다. 할 일이 없는 날(매월
# 3일 전, 이미 확정한 달)에는 아무것도 바꾸지 않고 끝난다. 실패한 날은 다음 날 저절로 다시 돈다.
#
# `/opt/ddona/.env` 를 통째로 source 하지 않는다(`expire-clover.sh` 와 같은 이유 — JSON 값이 쉘 문법과 부딪친다).
# 알림 주소 `DISCORD_WEBHOOK_URL` 만 뽑는다. DB 접속은 컨테이너가 자기 env 로 한다.
#
# 알림: 실패(색을 못 고름·배치 실패)와, 확정한 달이 있는 날의 요약만 보낸다. 실패 알림은 고정 문구다 — 예외 문장에는
# SQL 인자(회원 id)가 섞일 수 있어 로그 파일에만 남긴다.
set -uo pipefail

# 심볼릭 링크(`/opt/ddona/creator-payout-settle.sh`)로 불리므로 링크가 가리키는 저장소 `ops/` 를 찾는다.
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/bluegreen.sh source-path=SCRIPTDIR
source "$SCRIPT_DIR/lib/bluegreen.sh"
LOG_NAME=creator-payout-settle

DISCORD_WEBHOOK_URL=$(grep '^DISCORD_WEBHOOK_URL=' "$DDONA_ENV" | cut -d= -f2-)
export DISCORD_WEBHOOK_URL

alert() {
  PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.creator_payout_notify "$1" || true
}

# 교체 중이라 색을 하나로 못 고르면 그날은 실패로 끝난다 — 엉뚱한 컨테이너에서 돌리지 않는다.
if ! color="$(bash "$SCRIPT_DIR/active-color.sh")"; then
  log "서빙 중인 api 색을 고르지 못했다"
  alert "💰 크리에이터 정산 월 확정 실패: 서빙 중인 api 색을 고르지 못했다(교체 중?) — 내일 다시 돈다"
  exit 1
fi

output="$(compose exec -T "api_$color" python -m api.creator_payout.monthly)"
code=$?
printf '%s\n' "$output"
if [ "$code" -ne 0 ]; then
  log "월 확정 실패(종료 코드 $code)"
  alert "💰 크리에이터 정산 월 확정 실패(종료 코드 $code) — /var/log/ddona-creator-payout-settle.log 확인, 내일 다시 돈다"
  exit "$code"
fi

last="$(printf '%s\n' "$output" | tail -n 1)"
case "$last" in
  "크리에이터 정산 확정:"*) alert "💰 $last" ;;
esac
