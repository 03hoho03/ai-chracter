# shellcheck shell=bash
# api blue/green 운영 스크립트(`swap-api.sh`·`bootstrap-bluegreen.sh`·`active-color.sh`)가 같이 쓰는
# 기본값과 함수. 혼자 실행하지 않고 각 스크립트가 `source` 한다.
#
# 세 스크립트가 같은 상태 파일·같은 `.env` 줄·같은 색 판정을 봐야 하므로 사본을 두지 않고 여기 한 곳에
# 둔다 — 한쪽만 고쳐져 판정이 갈리면 두 스크립트가 서로 다른 색을 active 로 보게 된다.
#
# 경로·이름은 전부 env 로 덮어쓸 수 있고 기본값이 운영 값이다. 운영 경로를 박아 두면 같은 스크립트를
# 로컬에서 리허설할 방법이 없다. compose 파일을 절대 경로로 두는 이유: 수동 호출이 `/opt/ddona/app`
# 밖에서 돼도 같은 파일을 보게 하려는 것이다(compose 파일에 `name: ddona` 가 있어 프로젝트 이름은
# 작업 디렉터리와 무관하고, 상대 볼륨 경로는 compose 파일 위치 기준이다).
#
# GNU userland(운영 VM 은 Ubuntu)를 전제한다 — `sed -i`, `date -d`, `flock`. 맥에서 직접 돌리지 않는다.

DDONA_COMPOSE_ARGS="${DDONA_COMPOSE_ARGS:--f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env}"
DDONA_ENV="${DDONA_ENV:-/opt/ddona/.env}"
DDONA_PROJECT="${DDONA_PROJECT:-ddona}"
DDONA_STATE_FILE="${DDONA_STATE_FILE:-/var/lib/ddona/active_color}"
DDONA_LOCK_FILE="${DDONA_LOCK_FILE:-/var/lib/ddona/deploy.lock}"
# 앞선 교체가 끝나기를 기다리는 상한(초). 교체 1회 최악(pull + 마이그레이션 + 기동 대기 + 드레인 유예
# 65초)보다 넉넉하게 잡았다.
DDONA_LOCK_WAIT="${DDONA_LOCK_WAIT:-600}"
# `up --wait` 가 새 컨테이너의 healthy 를 기다리는 상한(초).
DDONA_WAIT_TIMEOUT="${DDONA_WAIT_TIMEOUT:-120}"
API_IMAGE_REPO="${API_IMAGE_REPO:-asia-northeast3-docker.pkg.dev/ddona-ai-character-chat/ddona/api}"

# `$(…)` 안에서도 `set -e` 가 살아 있게 한다 — 기본값으로는 명령 치환 안의 실패가 무시되어, 예컨대
# compose 가 프로젝트를 못 불러온 것을 "떠 있는 색 없음"으로 읽게 된다.
shopt -s inherit_errexit

read -r -a COMPOSE_ARGS <<<"$DDONA_COMPOSE_ARGS"

# 모든 compose 호출은 이 함수를 거친다. `< /dev/null` 이 핵심이다 — 배포는 이 스크립트를 SSH heredoc
# (`bash -s`)의 stdin 으로 넘기는데, `compose exec`·`compose run` 은 `-T` 를 줘도 stdin 을 컨테이너에
# 붙여 스크립트의 남은 줄을 삼킨다. 그러면 bash 는 읽을 게 없어 중간에서 조용히 "성공" 종료한다
# (배포 워크플로의 alembic·caddy reload 줄에서 실제로 일어났던 일이다).
compose() {
  docker compose "${COMPOSE_ARGS[@]}" "$@" </dev/null
}

# 로그는 전부 stderr 로 보낸다. 값을 돌려주는 함수(`$(…)`로 받는)를 안에서 로그가 오염시키지 않게 하려는
# 것이다 — 그렇게 오염된 값이 색 판정과 상태 파일에 그대로 들어간 적이 있다.
log() {
  printf '[%s %s] %s\n' "${LOG_NAME:-bluegreen}" "$(date '+%F %T')" "$*" >&2
}

die() {
  log "에러: $*"
  exit 1
}

# 동시 실행을 막는다. 수동 재스왑과 자동배포가 겹치면 두 스크립트가 같은 active/idle 을 판정해 두
# 색을 동시에 내릴 수 있다 — 워크플로의 concurrency 는 워크플로끼리만 막는다. 즉시 실패가 아니라
# 기다리는 이유는 어느 쪽이든 "앞 교체가 끝난 뒤 이어서 하면 되는" 작업이기 때문이다. 잠금은 fd 9 에
# 걸려 프로세스가 끝나면(죽어도) 풀린다.
take_lock() {
  command -v flock >/dev/null || die "flock 이 없다(util-linux) — 잠금 없이는 진행하지 않는다"
  case "$DDONA_LOCK_WAIT" in '' | *[!0-9]*) die "DDONA_LOCK_WAIT 는 초 단위 정수여야 한다: '$DDONA_LOCK_WAIT'" ;; esac
  mkdir -p "$(dirname "$DDONA_LOCK_FILE")"
  exec 9>>"$DDONA_LOCK_FILE"
  log "잠금 대기: $DDONA_LOCK_FILE (최대 ${DDONA_LOCK_WAIT}s)"
  flock -w "$DDONA_LOCK_WAIT" 9 || die "${DDONA_LOCK_WAIT}s 안에 잠금을 못 얻었다 — 다른 교체가 진행 중이다. 아무것도 바꾸지 않았다"
  log "잠금 획득"
}

# --- 이미지 참조 ---

# 태그는 `sed` 치환문과 `.env` 값에 그대로 들어가므로 docker 태그 문법으로 좁힌다.
valid_tag() {
  [[ "$1" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]
}

# 전체 참조(저장소:태그)에 허용하는 글자. `|`·`&`·`\`·공백이 없어야 아래 `sed` 치환이 글자 그대로
# 동작하고, `.env` 형식 검사(따옴표·`$`·공백 금지)도 통과한다.
valid_ref() {
  [[ "$1" =~ ^[A-Za-z0-9._/:@-]+$ ]]
}

image_key() {
  case "$1" in
    blue) echo API_IMAGE_BLUE ;;
    green) echo API_IMAGE_GREEN ;;
    *) die "알 수 없는 색: '$1'" ;;
  esac
}

other_color() {
  case "$1" in
    blue) echo green ;;
    green) echo blue ;;
    *) die "알 수 없는 색: '$1'" ;;
  esac
}

# --- `.env` 줄 ---
# 값은 로그에 찍지 않는다(이미지 참조만 다루지만, 실수로 다른 키를 넘겨도 새지 않게).

env_count() {
  grep -c "^$1=" "$DDONA_ENV" || true
}

# 정확히 1줄일 때만 값을 낸다. 0줄·2줄 이상은 에러 — 중복 키는 다음 배포의 형식 검사를 멈춘다.
env_get() {
  local n
  n="$(env_count "$1")"
  [ "$n" = 1 ] || die "$DDONA_ENV 에 $1 줄이 정확히 1줄이어야 하는데 ${n}줄이다"
  grep "^$1=" "$DDONA_ENV" | cut -d= -f2-
}

# 있는 줄을 바꾼다. `sed -i "s|^KEY=.*|…|"` 는 줄이 없으면 아무것도 안 하고 성공하므로 먼저 1줄인지
# 보고, 바꾼 뒤 실제 값이 바뀌었는지 다시 읽어 확인한다.
env_set() {
  local key="$1" value="$2" n
  valid_ref "$value" || die "$key 에 넣을 값에 허용하지 않는 글자가 있다"
  n="$(env_count "$key")"
  [ "$n" = 1 ] || die "$DDONA_ENV 에 $key 줄이 정확히 1줄이어야 하는데 ${n}줄이다 — 바꾸지 않았다"
  sed -i "s|^$key=.*|$key=$value|" "$DDONA_ENV"
  [ "$(env_get "$key")" = "$value" ] || die "$key 치환이 반영되지 않았다"
}

# 없는 키를 맨 끝에 더한다. 파일이 개행으로 끝나지 않으면 마지막 줄에 붙지 않게 개행부터 넣는다.
env_add() {
  local key="$1" value="$2"
  valid_ref "$value" || die "$key 에 넣을 값에 허용하지 않는 글자가 있다"
  [ "$(env_count "$key")" = 0 ] || die "$key 줄이 이미 있다 — 더하지 않았다"
  if [ -s "$DDONA_ENV" ] && [ -n "$(tail -c1 "$DDONA_ENV")" ]; then
    printf '\n' >>"$DDONA_ENV"
  fi
  printf '%s=%s\n' "$key" "$value" >>"$DDONA_ENV"
}

# --- 컨테이너·색 ---

# compose 가 지금 불러오는 프로젝트 이름. 라벨 필터(`DDONA_PROJECT`)가 다른 프로젝트를 보고 있으면
# "옛 api 없음" 같은 판정이 조용히 틀리므로, compose 가 로드되는 시점에 둘이 같은지 맞춰 본다.
check_project_name() {
  local name
  name="$(compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
  [ "$name" = "$DDONA_PROJECT" ] ||
    die "compose 프로젝트($name)와 DDONA_PROJECT($DDONA_PROJECT)가 다르다 — 라벨로 찾는 컨테이너 판정이 틀어진다"
}

# compose 파일에서 빠진 서비스(옛 단일 `api`)도 찾아야 해서 compose 가 아니라 라벨로 찾는다.
# 이 함수는 `.env` 에 색 키가 없어 compose 가 프로젝트를 못 불러올 때도 동작한다. 정지 컨테이너 포함.
service_containers() {
  docker ps -aq \
    --filter "label=com.docker.compose.project=$DDONA_PROJECT" \
    --filter "label=com.docker.compose.service=$1" </dev/null
}

# 실행 중인 색을 한 줄에 하나씩.
running_colors() {
  local c ids
  for c in blue green; do
    ids="$(compose ps -q "api_$c")"
    if [ -n "$ids" ]; then
      echo "$c"
    fi
  done
}

# 컨테이너 기동 시각을 나노초 정수로. 문자열 비교는 안 된다 — Go 의 RFC3339Nano 는 소수부 끝의 0 을
# 잘라 길이가 달라진다.
started_at_ns_of() {
  local t
  t="$(docker inspect --format '{{.State.StartedAt}}' "$1" </dev/null)"
  date -u -d "$t" +%s%N
}

started_at_ns() {
  started_at_ns_of "$(compose ps -q "api_$1")"
}

# 상태 파일의 색. 없거나 `blue`/`green` 이 아니면 빈 문자열.
read_state() {
  local v=""
  if [ -f "$DDONA_STATE_FILE" ]; then
    v="$(tr -d '[:space:]' <"$DDONA_STATE_FILE")"
  fi
  case "$v" in
    blue | green) echo "$v" ;;
    *) echo "" ;;
  esac
}

write_state() {
  mkdir -p "$(dirname "$DDONA_STATE_FILE")"
  printf '%s\n' "$1" >"$DDONA_STATE_FILE.tmp"
  mv -f "$DDONA_STATE_FILE.tmp" "$DDONA_STATE_FILE"
}

# 교체용 active/idle 판정. 인자: 실행 중인 색 목록(줄바꿈 구분), 상태 파일 값. 출력: "active idle".
# - 한 색만 떠 있으면 그 색이 active 다(상태 파일과 달라도 실제가 이긴다).
# - 둘 다 떠 있으면(중단된 교체의 잔재) 상태 파일이 가리키는 색이 떠 있으면 그 색이 active.
# - 상태 파일을 못 믿으면 먼저 뜬 쪽이 active 다 — 교체는 늘 "떠 있는 색을 두고 빈 색에 새것을
#   올리는" 방향이라, 어디서 끊겼든 나중에 뜬 컨테이너가 이번에 넣으려던 새 배포다.
pick_active() {
  local running="$1" recorded="$2" n blue_ns green_ns
  n="$(grep -c . <<<"$running" || true)"
  case "$n" in
    0) die "떠 있는 색이 없다" ;;
    1)
      if [ -n "$recorded" ] && [ "$recorded" != "$running" ]; then
        log "상태 파일($recorded)과 실제 실행 색($running)이 다르다 — 실제를 따른다"
      fi
      echo "$running $(other_color "$running")"
      ;;
    2)
      if [ -n "$recorded" ]; then
        log "두 색이 모두 떠 있다 — 상태 파일($recorded)을 active 로 본다"
        echo "$recorded $(other_color "$recorded")"
        return
      fi
      blue_ns="$(started_at_ns blue)"
      green_ns="$(started_at_ns green)"
      log "두 색이 모두 떠 있고 상태 파일을 못 믿는다 — 먼저 뜬 쪽을 active 로 본다(blue=$blue_ns green=$green_ns)"
      if [ "$blue_ns" -le "$green_ns" ]; then
        echo "blue green"
      else
        echo "green blue"
      fi
      ;;
    *) die "실행 중인 색 목록이 이상하다: $running" ;;
  esac
}

# 운영 명령용 active 판정(`active-color.sh`). 교체용보다 보수적이다: 상태 파일의 색이 실제로 떠
# 있으면 그 색, 아니면 떠 있는 색이 정확히 하나일 때만 그 색. 0개·2개(교체 중이거나 중단 잔재)는
# 사람이 볼 상황이라 에러다 — 조용히 아무 색이나 내면 그 명령이 엉뚱한 컨테이너에 간다.
pick_active_for_ops() {
  local running="$1" recorded="$2" n
  if [ -n "$recorded" ] && grep -Fqx "$recorded" <<<"$running"; then
    echo "$recorded"
    return
  fi
  n="$(grep -c . <<<"$running" || true)"
  case "$n" in
    1) echo "$running" ;;
    0) die "떠 있는 api 색이 없다(VM 재구축 직후라면 DEPLOY.md 의 '빈 상태에서 첫 기동' 절차)" ;;
    *) die "두 색이 모두 떠 있고 상태 파일(${recorded:-없음})이 그중 하나를 가리키지 않는다 — 교체 중이거나 중단된 교체의 잔재다" ;;
  esac
}

# Caddy 능동 헬스체커 로그에서 `host`(예: api_blue:8000) 줄 중 정규식에 맞는 것이 `since`(epoch 초)
# 이후에 있는지. 헬스체커 로그는 접근 로그 파일이 아니라 기본 로거(stderr, JSON)로 가서
# `compose logs caddy` 에 나온다. `grep -q` 를 쓰지 않는다 — 먼저 끝나면 앞단이 SIGPIPE 로 죽고
# pipefail 이 그걸 "못 찾음"으로 만든다. `--since` 에는 epoch 초만 넘긴다(타임존 없는 시각 문자열은
# 클라이언트 로컬 타임존으로 해석된다).
caddy_log_has() {
  local host="$1" regex="$2" since="$3"
  compose logs --no-log-prefix --since "$since" caddy 2>&1 |
    grep -F "\"host\":\"$host\"" | grep -E "$regex" >/dev/null
}

# 헬스체커가 그 업스트림을 healthy 로 바꿀 때만 찍는 문구.
caddy_saw_up() {
  caddy_log_has "$1" '"msg":"host is up"' "$2"
}

# unhealthy 로 바꿀 때 찍는 문구는 없어서, 실패 한 번(`health_fails 1`)에 찍히는 실패 로그를 그 신호로 쓴다.
caddy_saw_fail() {
  caddy_log_has "$1" '"msg":"(status code out of tolerances|HTTP request failed)"' "$2"
}
