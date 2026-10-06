#!/usr/bin/env bash
# 단일 `api` 서비스 형상에서 blue/green 형상으로 한 번 옮긴다. 이행이 끝나면 다시 쓸 일이 없다.
#
#   sudo bash ops/bootstrap-bluegreen.sh <태그>
#
# 평상시 교체(`swap-api.sh`)와 따로 둔 이유: 딱 한 번만 쓰이고 그 뒤 영원히 안 쓰일 분기를 매 배포가
# 타는 스크립트에 얹지 않으려는 것이다. root 로 돈다(상태·잠금 파일이 root 소유 `/var/lib/ddona/`).
#
# 이 이행은 짧은 끊김 한 번을 감수한다 — Caddy 를 새 설정(두 색 업스트림)으로 재생성하는 몇 초 동안
# 80/443 에 듣는 프로세스가 없다. 그 앞까지는 옛 `api` 가 계속 서빙하고, blue 는 옆에 나란히 뜬다.
# 끊김 길이는 이 스크립트가 아니라 밖에서 폴링으로 잰다(재생성 중엔 접근 로그 자체가 비어 있다).
#
# **재실행 가능하다.** 중간에 실패하면 같은 명령(또는 같은 태그의 배포 재실행)으로 다시 부르면 된 단계는
# 건너뛰고 이어서 끝낸다. 옛 `api` 컨테이너가 남아 있는 한 배포는 이 스크립트로 오고, `swap-api.sh` 는
# 그 형상을 거부하므로 수동 교체가 이 상태를 덮지도 않는다. 옛 `API_IMAGE=` 줄은 지우지 않는다.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/bluegreen.sh source-path=SCRIPTDIR
source "$SCRIPT_DIR/lib/bluegreen.sh"
LOG_NAME=bootstrap-bluegreen

TAG="${1:-}"
log "시작: tag=${TAG:-(없음)}"
[ -n "$TAG" ] || die "태그를 준다: sudo bash ops/bootstrap-bluegreen.sh <태그>"
valid_tag "$TAG" || die "태그 형식이 아니다: '$TAG'"
REF="$API_IMAGE_REPO:$TAG"
valid_ref "$REF" || die "이미지 참조에 허용하지 않는 글자가 있다: '$REF'"

# 0) 잠금 — 평상시 교체와 같은 파일이라 이행 중에 교체가 끼어들지 않는다.
take_lock

# 1) 전제는 compose 가 아니라 라벨로 본다 — 이 시점엔 `.env` 에 색 키가 없을 수 있고, 그러면 compose 는
#    `ps` 까지 거부한다. 옛 `api` 가 있어야 하고(없으면 이행은 이미 끝났다) green 은 없어야 한다(있으면
#    사람이 형상을 봐야 한다). blue 는 있어도 된다 — 앞선 실행의 잔재다.
if [ -z "$(service_containers api)" ]; then
  die "옛 단일 api 컨테이너가 없다 — 이행은 이미 끝났다. 평상시 교체는 'sudo bash ops/swap-api.sh <태그>'"
fi
if [ -n "$(service_containers api_green)" ]; then
  die "api_green 컨테이너가 있다(정지 포함) — 이 스크립트가 예상하는 형상이 아니다. 직접 확인한다"
fi

# 2) `.env` 시드는 어떤 compose 호출보다 먼저다(아래 판정용 `config` 는 두 키가 이미 다 있을 때만 부른다).
#    먼저 Caddy 재생성(6단계)이 이미 끝났는지 본다. 끝났다면 blue 는 이미 유일한 서빙 색이라 다시 만들면
#    끊긴다 — 그때는 4·6단계를 건너뛰고 있는 줄도 바꾸지 않는다(새 태그는 이어지는 교체가 무중단으로
#    올린다). 판정: compose 가 지금 계산하는 caddy 정의의 해시와 실제 caddy 컨테이너에 붙은 해시가 같은가.
#    이행이 caddy 정의(api 의존 제거·로그 상한)를 바꾸므로 재생성 전엔 둘이 다르다.
BLUE_N="$(env_count API_IMAGE_BLUE)"
GREEN_N="$(env_count API_IMAGE_GREEN)"
for n in "$BLUE_N" "$GREEN_N"; do
  [ "$n" -le 1 ] || die "$DDONA_ENV 에 API_IMAGE_BLUE/GREEN 중복 줄이 있다 — 중복 키는 배포 형식 검사를 멈춘다. 직접 정리한다"
done
CADDY_DONE=false
if [ "$BLUE_N" = 1 ] && [ "$GREEN_N" = 1 ]; then
  compose config -q || die "compose 가 프로젝트를 불러오지 못했다(위 메시지)"
  check_project_name
  caddy_id="$(compose ps -aq caddy)"
  if [ -n "$caddy_id" ]; then
    want="$(compose config --hash caddy | awk '{print $2}')"
    have="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.config-hash"}}' "$caddy_id" </dev/null)"
    if [ -n "$want" ] && [ "$want" = "$have" ]; then
      CADDY_DONE=true
    fi
  fi
fi
log "caddy_done=$CADDY_DONE"

docker pull "$REF" </dev/null >/dev/null || die "docker pull 실패 — 아무것도 바꾸지 않았다"
log "pull 완료: $REF"

# 두 색 줄을 같은 참조로. 비워 둔 줄은 형식 검사가 거부하고, 서비스명 없는 `up -d` 가 쉬는 색을 띄워도
# 같은 코드가 뜨게 하려는 것이다.
for key in API_IMAGE_BLUE API_IMAGE_GREEN; do
  if [ "$(env_count "$key")" = 0 ]; then
    env_add "$key" "$REF"
    log "2) $key 추가"
  elif [ "$CADDY_DONE" = true ]; then
    log "2) $key 는 이미 있다 — Caddy 재생성까지 끝난 재실행이라 바꾸지 않는다"
  else
    env_set "$key" "$REF"
    log "2) $key 갱신"
  fi
done
python3 "$SCRIPT_DIR/check_env.py" --format "$DDONA_ENV" </dev/null ||
  die "$DDONA_ENV 형식 검사 실패(위 줄 번호) — 직접 고친 뒤 다시 부른다"
compose config -q || die "시드 뒤에도 compose 가 프로젝트를 불러오지 못했다(위 메시지)"
check_project_name

# 3) 마이그레이션 — 옛 api 가 아직 서빙하는 동안, blue 기동 전에. 이미 적용됐으면 아무것도 안 한다.
log "3) 마이그레이션(api_blue 의 이미지)"
compose run --rm -T api_blue alembic upgrade head </dev/null

# 4) blue 를 옛 api 옆에 띄운다. `--remove-orphans` 를 쓰지 않는다 — 옛 api 는 compose 파일에서 빠져
#    고아가 됐는데, 여기서 지우면 Caddy 가 아직 옛 설정(`api:8000` 만)이라 서비스가 내려간다. 실패해도
#    blue 는 아직 업스트림 밖이라 서비스는 옛 api 로 계속된다. 재실행에서 다시 만들어도 무해하다.
if [ "$CADDY_DONE" = true ]; then
  log "4) 건너뜀 — blue 가 이미 유일한 서빙 색이다"
else
  log "4) api_blue 기동(최대 ${DDONA_WAIT_TIMEOUT}s)"
  compose up -d --force-recreate --wait --wait-timeout "$DDONA_WAIT_TIMEOUT" api_blue ||
    die "api_blue 가 healthy 가 안 됐다 — 서비스는 옛 api 로 계속된다. 원인을 본 뒤 정상 태그로 다시 부른다"
fi

# 5) 상태 파일. green 이 없으므로 언제나 blue 가 맞다.
write_state blue
log "5) 상태 파일 = blue"

# 6) Caddy 재생성 — 새 Caddyfile(두 색 업스트림)·api 의존 제거·로그 상한이 여기서 반영된다. 이행이
#    감수하기로 한 끊김이 이 몇 초다. caddy 이미지는 떠다니는 태그라 재생성 때 버전이 바뀔 수 있어 찍어 둔다.
if [ "$CADDY_DONE" = true ]; then
  log "6) 건너뜀 — caddy 는 이미 새 정의로 떠 있다"
else
  log "6) caddy 재생성(짧은 끊김)"
  compose up -d --force-recreate --wait caddy ||
    die "caddy 재생성 실패 — 80/443 이 비어 있을 수 있다. 바로 compose ps caddy·compose logs caddy 를 본다"
  log "6) caddy 버전: $(compose exec -T caddy caddy version </dev/null)"
fi

# 7) blue 와 Caddy 가 정상인지 짧게 확인한다. Caddy 는 갓 뜬 업스트림을 healthy 로 시작해 healthy 로 남으면
#    아무 로그도 남기지 않으므로, "최근 몇 초 동안 blue 에 대한 헬스체크 실패 로그가 없다"로 본다(체크 간격
#    1초). 끊김 구간 측정은 이 스크립트 밖에서 한다.
log "7) api_blue /health 와 Caddy 의 blue 헬스체크 확인(최대 30s)"
deadline=$(($(date +%s) + 30))
while :; do
  now="$(date +%s)"
  caddy_id="$(compose ps -q caddy)"
  if [ -n "$caddy_id" ] &&
    compose exec -T api_blue python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" </dev/null &&
    [ $(($(started_at_ns_of "$caddy_id") / 1000000000)) -le $((now - 3)) ] &&
    ! caddy_saw_fail "api_blue:8000" $((now - 3)); then
    break
  fi
  [ "$now" -lt "$deadline" ] || die "30s 안에 blue·Caddy 정상 확인을 못 했다 — 서비스 상태를 직접 본다(재실행하면 이 단계부터 다시 확인한다)"
  sleep 1
done
log "7) 확인 완료"

# 8) 이제서야 옛 api 컨테이너를 지운다. 서비스명을 줘도 `--remove-orphans` 는 compose 파일에 없는 컨테이너를
#    지우고, 인자에 없는 api_green 은 띄우지 않는다. `--no-recreate` 는 재실행에서도 blue·caddy 를 어떤
#    경우에도 다시 만들지 않는다는 보장을 명령에 둔다. 마지막 줄이 찍혀야 stdin 이 삼켜지지 않고 끝까지 돈 것이다.
log "8) 옛 api 컨테이너 정리"
compose up -d --no-recreate --remove-orphans api_blue caddy
log "8) 부트스트랩 정리 완료: active=blue 이미지 $(env_get API_IMAGE_BLUE)"
