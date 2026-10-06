#!/usr/bin/env bash
# api 를 blue/green 으로 무중단 교체한다. 배포 워크플로·수동 롤백·env 반영 재기동이 모두 이것 하나를 부른다.
#
#   sudo bash ops/swap-api.sh [태그]          # 태그 생략 = 지금 active 의 이미지로 다시 교체(env 반영용)
#   sudo SKIP_OVERLAP=true bash ops/swap-api.sh <태그>   # 겹침 없이 active 를 그 자리에서 교체
#
# root 로 돈다 — 상태 파일·잠금 파일이 root 소유 `/var/lib/ddona/` 에 있다.
#
# 평상시 흐름: 쉬는 색(idle)에 새 이미지를 띄우고 Caddy 가 그 색을 healthy 로 넣은 것을 확인한 뒤, 서빙
# 중인 색(active)에 드레인 플래그를 세워 그 색의 `/health` 를 503 으로 만든다. Caddy 능동 헬스체크가
# 그 색을 **멈추기 전에** 업스트림에서 빼므로 새 연결은 새 색으로만 가고, 옛 색은 하던 요청(SSE 턴
# 포함)을 `stop_grace_period` 안에서 마친 뒤 내려간다. 그래서 교체 소요 시간은 옛 색에 남은 요청 길이에
# 비례한다 — 느린 게 아니라 드레인이 일하는 것이다.
#
# Caddy 가 그 색을 healthy/unhealthy 로 보는지는 admin API 로 알 수 없다 — `/reverse_proxy/upstreams`
# 의 `fails` 는 수동(passive) 헬스체크 카운터라 능동 헬스체크 결과를 반영하지 않는다. 그래서 Caddy
# 헬스체커 로그를 교체 시작 시각 이후로 읽는다(`lib/bluegreen.sh` 의 `caddy_log_has`).
#
# 실패하면: 새 색이 끝내 healthy 가 안 되면(가장 흔한 실패) 그 색만 정리하고 `.env` 의 그 색 줄을 실행 전
# 값으로 되돌린 뒤 종료코드 1 — 옛 색은 손대지 않아 서비스는 그대로다. 드레인을 시작한 뒤에는 새 색이
# 이미 서빙 중이라 되돌리지 않는다. 중간에 끊겨 두 색이 다 떠 있으면 같은 명령을 다시 부르면 이어서
# 끝난다(색 판정이 그 형상을 알아본다).
#
# SKIP_OVERLAP=true 는 위험한 마이그레이션 배포의 탈출구다 — 옛 코드와 새 스키마가 겹치는 구간을 아예
# 없애려고 쉬는 색을 띄우지 않고 active 를 그 자리에서 재생성한다. 그 대가로 단일 컨테이너 시절의
# 완전교체처럼 짧은 끊김이 생긴다.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/bluegreen.sh source-path=SCRIPTDIR
source "$SCRIPT_DIR/lib/bluegreen.sh"
LOG_NAME=swap-api

# 새 색이 compose 상 healthy 가 된 뒤 Caddy 가 그 색을 넣기까지(보통 1~2초) 기다리는 상한.
HEALTHY_TIMEOUT=60
# 드레인 플래그를 세운 뒤 Caddy 가 그 색을 빼기까지(보통 1~2초) 기다리는 상한.
UNHEALTHY_TIMEOUT=30

TAG_ARG="${1:-}"
# 받은 값을 무엇보다 먼저 찍는다 — 워크플로가 값을 못 넘겼는지(특히 SKIP_OVERLAP 이 원격 셸까지
# 갔는지) 배포 로그만 보고 알 수 있어야 한다.
log "시작: tag=${TAG_ARG:-(생략)} skip_overlap=${SKIP_OVERLAP:-}"

case "${SKIP_OVERLAP:-}" in
  true) SKIP=1 ;;
  false | '') SKIP=0 ;;
  *) die "SKIP_OVERLAP 은 true·false·빈 값만 받는다: '${SKIP_OVERLAP}'" ;;
esac
if [ -n "$TAG_ARG" ] && ! valid_tag "$TAG_ARG"; then
  die "태그 형식이 아니다: '$TAG_ARG'"
fi

take_lock
START="$(date +%s)"

# 1) compose 가 프로젝트를 불러오는지부터 본다. 색 이미지 변수 하나라도 비거나 없으면 compose 는 `ps`
#    까지 전부 거부하는데, 이걸 삼키면 아래에서 "떠 있는 색 없음"으로 오진한다. 종료코드 값은 compose
#    버전마다 달라 0 이 아닌지만 본다.
compose config -q || die "compose 가 프로젝트를 불러오지 못했다(위 메시지) — 아무것도 바꾸지 않았다"
check_project_name

# 2) 전제. 옛 단일 `api` 컨테이너가 남아 있으면 blue/green 이행이 덜 끝난 것이다 — Caddy 가 아직 옛 설정이면
#    새 색이 영영 healthy 로 안 들어와 매번 실패하고, 이 스크립트가 그 형상을 덮어 옛 api 를 고아로 남긴다.
if [ -n "$(service_containers api)" ]; then
  die "옛 단일 api 컨테이너가 남아 있다 — blue/green 이행이 덜 끝났다. 'sudo bash ops/bootstrap-bluegreen.sh <태그>' 를 다시 부른다"
fi
RUNNING="$(running_colors)"
if [ -z "$RUNNING" ]; then
  die "떠 있는 api 색이 없다 — 이 스크립트는 첫 기동을 다루지 않는다(VM 재구축 직후라면 DEPLOY.md 의 '빈 상태에서 첫 기동' 절차)"
fi

# 3) active/idle 판정.
PAIR="$(pick_active "$RUNNING" "$(read_state)")"
read -r ACTIVE IDLE <<<"$PAIR"
ACTIVE_KEY="$(image_key "$ACTIVE")"
IDLE_KEY="$(image_key "$IDLE")"
log "active=$ACTIVE idle=$IDLE"

# 두 색 줄이 모두 정확히 1줄인지 아무것도 바꾸기 전에 본다 — 교체 끝에 쉬는 색 줄까지 고치므로, 거기서
# 처음 알게 되면 이미 서빙 색이 바뀐 뒤다.
CURRENT_REF="$(env_get "$ACTIVE_KEY")"
env_get "$IDLE_KEY" >/dev/null

# 4) 올릴 이미지. 태그를 생략하면 지금 active 가 쓰는 참조 그대로 — 같은 이미지를 새 env 로 다시 띄우는
#    용도다(env 는 컨테이너를 만들 때만 읽힌다).
if [ -n "$TAG_ARG" ]; then
  REF="$API_IMAGE_REPO:$TAG_ARG"
else
  REF="$CURRENT_REF"
fi
valid_ref "$REF" || die "이미지 참조에 허용하지 않는 글자가 있다: '$REF'"
log "이미지: $REF"

# 5) pull 을 `.env` 수정보다 먼저 한다. 반대 순서면 pull 이 실패했을 때 `.env` 가 받을 수 없는 태그를
#    가리킨 채 남는다. 로컬에 있어도 받는다 — 로컬 이미지 정리가 옛 태그를 지웠을 수 있다.
docker pull "$REF" </dev/null >/dev/null || die "docker pull 실패 — 아무것도 바꾸지 않았다"
log "pull 완료"

# 실패 시 되돌리기. ROLLBACK 이 무엇을 되돌릴지 정한다(빈 값 = 되돌리지 않음).
#   idle   : idle 컨테이너 정지·삭제 + idle 줄을 실행 전 값으로(평상시 경로, Caddy 확인 전까지)
#   active : active 줄만 실행 전 값으로(SKIP_OVERLAP 경로, 재생성 전까지)
ROLLBACK=""
PREV_REF=""
on_exit() {
  local rc=$?
  if [ "$rc" = 0 ] || [ -z "$ROLLBACK" ]; then
    return
  fi
  set +e
  case "$ROLLBACK" in
    idle)
      log "실패 정리: api_$IDLE 정지·삭제, $IDLE_KEY 를 실행 전 값으로 되돌린다(api_$ACTIVE 는 그대로 서빙)"
      compose stop "api_$IDLE"
      compose rm -f "api_$IDLE"
      (env_set "$IDLE_KEY" "$PREV_REF") || log "⚠️ $IDLE_KEY 되돌리기 실패 — 직접 확인한다"
      ;;
    active)
      log "실패 정리: $ACTIVE_KEY 를 실행 전 값으로 되돌린다(api_$ACTIVE 는 재생성 전이라 그대로 서빙)"
      (env_set "$ACTIVE_KEY" "$PREV_REF") || log "⚠️ $ACTIVE_KEY 되돌리기 실패 — 직접 확인한다"
      ;;
  esac
  exit 1
}
trap on_exit EXIT
# 신호로 끝날 때도 위 정리를 타게 한다(SIGKILL 은 어쩔 수 없다 — 그때는 재실행이 이어서 끝낸다).
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if [ "$SKIP" = 1 ]; then
  # 겹침 없는 교체. 두 색이 다 떠 있으면(중단 잔재) 쉬는 색부터 내린다 — 남겨 두면 옛 코드의 잔재가
  # 새 스키마로 트래픽을 받는다. 겹침을 끄려는 바로 그 상황이다.
  if [ "$(grep -c . <<<"$RUNNING")" = 2 ]; then
    log "skip_overlap: 남아 있던 api_$IDLE 를 먼저 정지·삭제"
    compose stop "api_$IDLE"
    compose rm -f "api_$IDLE"
  fi

  PREV_REF="$CURRENT_REF"
  env_set "$ACTIVE_KEY" "$REF"
  ROLLBACK=active
  log "skip_overlap: $ACTIVE_KEY 갱신, 마이그레이션(api_$ACTIVE 의 새 이미지)"
  # 기동보다 먼저다 — 앱이 기동할 때 새 스키마를 읽는 코드가 있어 순서가 바뀌면 새 컨테이너가 죽는다.
  compose run --rm -T "api_$ACTIVE" alembic upgrade head </dev/null

  # 여기부터는 되돌리지 않는다 — 재생성이 시작되면 active 가 이미 바뀌는 중이라, 복구는 이전 태그로 이
  # 스크립트를 다시 부르는 것이다.
  ROLLBACK=""
  log "skip_overlap: api_$ACTIVE 를 그 자리에서 재생성(드레인 없음 — 짧은 끊김)"
  compose up -d --force-recreate --wait --wait-timeout "$DDONA_WAIT_TIMEOUT" "api_$ACTIVE" ||
    die "api_$ACTIVE 가 healthy 가 안 됐다 — 서비스가 내려갔을 수 있다. 이전 태그로 이 스크립트를 다시 부른다"

  # 쉬는 색 변수도 같은 참조로 — 서비스명 없는 `up -d` 가 실수로 그 색을 띄워도 같은 코드가 뜨게.
  # 컨테이너는 만들지 않는다.
  env_set "$IDLE_KEY" "$REF"
  write_state "$ACTIVE"
  log "완료(skip_overlap): active=$ACTIVE 상태 파일 기록, 이미지 $REF, 소요 $(($(date +%s) - START))s"
  exit 0
fi

# 6) idle 줄 교체 — 바로 되돌리기를 건다. 여기서 Caddy 확인(9)까지 어디서 실패하든 idle 을 정리하고 줄을
#    되돌려, 실패 뒤 형상이 "실행 전과 같음" 하나로 판정되게 한다.
PREV_REF="$(env_get "$IDLE_KEY")"
env_set "$IDLE_KEY" "$REF"
ROLLBACK=idle
log "6) $IDLE_KEY 갱신"

# 7) 마이그레이션은 idle 의 새 이미지로, 옛 색이 서빙하는 동안, idle 기동 전에.
log "7) 마이그레이션(api_$IDLE 의 새 이미지)"
compose run --rm -T "api_$IDLE" alembic upgrade head </dev/null

# 8) idle 기동. `--force-recreate` 는 매번 새 컨테이너를 만들게 한다 — 앞선 교체가 드레인 플래그를 세운
#    채 멈춘 컨테이너가 재사용되면 `/health` 가 영원히 503 이다. 이 시각 이후의 Caddy 로그만 본다.
T0="$(date +%s)"
log "8) api_$IDLE 기동(최대 ${DDONA_WAIT_TIMEOUT}s)"
compose up -d --force-recreate --wait --wait-timeout "$DDONA_WAIT_TIMEOUT" "api_$IDLE" ||
  die "api_$IDLE 가 healthy 가 안 됐다"

# 9) Caddy 가 idle 을 업스트림에 넣었는지.
log "9) Caddy 가 api_$IDLE 를 healthy 로 보기를 대기(최대 ${HEALTHY_TIMEOUT}s)"
deadline=$(($(date +%s) + HEALTHY_TIMEOUT))
until caddy_saw_up "api_$IDLE:8000" "$T0"; do
  [ "$(date +%s)" -lt "$deadline" ] || die "${HEALTHY_TIMEOUT}s 안에 Caddy 가 api_$IDLE 를 healthy 로 보지 않았다"
  sleep 1
done
# 여기부터는 새 색이 서빙 중이라 되돌리지 않는다. 중간에 끊기면 재실행이 이어서 끝낸다.
ROLLBACK=""
log "9) api_$IDLE 합류 확인"

# 10) active 드레인.
T_FLAG="$(date +%s)"
log "10) api_$ACTIVE 에 드레인 플래그"
compose exec -T "api_$ACTIVE" touch /tmp/draining </dev/null ||
  die "api_$ACTIVE 에 드레인 플래그를 못 세웠다 — 두 색이 다 떠 있다. 원인을 본 뒤 같은 명령을 다시 부른다"
deadline=$(($(date +%s) + UNHEALTHY_TIMEOUT))
drained=0
while [ "$(date +%s)" -lt "$deadline" ]; do
  if caddy_saw_fail "api_$ACTIVE:8000" "$T_FLAG"; then
    drained=1
    break
  fi
  sleep 1
done
if [ "$drained" = 1 ]; then
  # 1초 여유는 이 교체 방식을 실측(비-2xx 0건)할 때 쓴 값 그대로다 — 줄이거나 뺀 형태는 재 보지 않았다.
  sleep 1
  log "10) Caddy 가 api_$ACTIVE 를 뺐다"
else
  log "⚠️ ${UNHEALTHY_TIMEOUT}s 안에 Caddy 가 api_$ACTIVE 를 빼는 로그를 못 봤다 — 그래도 정지로 간다(정지 유예 동안 하던 요청은 마친다)"
fi

# 11) active 정지 — 유예(`stop_grace_period`)를 그대로 존중해 하던 요청을 마칠 때까지 기다린다.
log "11) api_$ACTIVE 정지·삭제"
compose stop "api_$ACTIVE"
compose rm -f "api_$ACTIVE"

# 12) 쉬는 색이 된 옛 active 의 변수도 새 참조로 — 서비스명 없는 `up -d` 가 실수로 그 색을 띄우면 옛
#     코드가 업스트림에 합류하기 때문이다.
env_set "$ACTIVE_KEY" "$REF"
log "12) $ACTIVE_KEY 도 같은 이미지로 맞춤"

# 13) 상태 파일. 이 줄이 배포 로그에 찍혀야 stdin 이 중간에 삼켜지지 않고 끝까지 돈 것이다.
write_state "$IDLE"
log "13) 완료: active=$IDLE 상태 파일 기록, 이미지 $REF, 소요 $(($(date +%s) - START))s"
