#!/usr/bin/env bash
# `ops/cron.d/ddona-chat-cost-ratio` 가 매일(KST 00:50) 이 스크립트를 부른다.
#
# 채팅 모델별 일일 원가 비율 리포트(`python -m api.clover.chat_cost_ratio`)를 지금 서빙 중인 api 컨테이너 안에서 돌린다. 단가표·
# 환율·호출 원가 계산이 앱 코드(`api/llm/pricing.py`) 한 곳에만 있어 컨테이너 안에서 돈다. 리포트는 읽기 전용 트랜잭션에서
# SELECT 만 하고, 무엇도 자동으로 바꾸지 않는다. 인자는 그대로 넘긴다(`--date`·`--dry-run`·`--ignore-previous`).
#
# `/opt/ddona/.env` 를 통째로 source 하지 않는다(`expire-clover.sh` 와 같은 이유 — JSON 값이 쉘 문법과 부딪친다).
# 알림 주소 `DISCORD_WEBHOOK_URL` 만 뽑는다. DB 접속은 컨테이너가 자기 env 로 한다.
#
# 알림: 실패(색을 못 고름·리포트 실패)와, 마지막 줄이 경보인 날만 보낸다. 실패 알림은 고정 문구다 — 예외 문장에는 SQL 인자가
# 섞일 수 있어 로그 파일에만 남긴다. 실패한 날은 다음 날 "연속"으로 보일 수 있으므로, 실패 알림을 보면 `--date` 로 그날을
# 다시 돌린다.
set -uo pipefail

# 심볼릭 링크(`/opt/ddona/chat-cost-ratio.sh`)로 불리므로 링크가 가리키는 저장소 `ops/` 를 찾는다.
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/bluegreen.sh source-path=SCRIPTDIR
source "$SCRIPT_DIR/lib/bluegreen.sh"
LOG_NAME=chat-cost-ratio

DISCORD_WEBHOOK_URL=$(grep '^DISCORD_WEBHOOK_URL=' "$DDONA_ENV" | cut -d= -f2-)
export DISCORD_WEBHOOK_URL

alert() {
  PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.chat_cost_ratio_notify "$1" || true
}

# 교체 중이라 색을 하나로 못 고르면 그날은 실패로 끝난다 — 엉뚱한 컨테이너에서 돌리지 않는다.
if ! color="$(bash "$SCRIPT_DIR/active-color.sh")"; then
  log "서빙 중인 api 색을 고르지 못했다"
  alert "📉 채팅 원가 비율 리포트 실패: 서빙 중인 api 색을 고르지 못했다(교체 중?) — 그날을 --date 로 다시 돌린다"
  exit 1
fi

output="$(compose exec -T "api_$color" python -m api.clover.chat_cost_ratio "$@")"
code=$?
printf '%s\n' "$output"
if [ "$code" -ne 0 ]; then
  log "리포트 실패(종료 코드 $code)"
  alert "📉 채팅 원가 비율 리포트 실패(종료 코드 $code) — /var/log/ddona-chat-cost-ratio.log 확인, 그날을 --date 로 다시 돌린다"
  exit "$code"
fi

last="$(printf '%s\n' "$output" | tail -n 1)"
case "$last" in
  "채팅 원가 경보:"*) alert "📉 $last" ;;
esac
