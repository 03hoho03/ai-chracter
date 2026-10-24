#!/usr/bin/env bash
# api 를 blue/green 으로 무중단 교체한다. 배포 워크플로·수동 롤백·env 반영 재기동이 모두 이것 하나를 부른다.
#
#   sudo bash ops/swap-api.sh [태그]          # 태그 생략 = 지금 active 의 이미지로 다시 교체(env 반영용)
#   sudo SKIP_OVERLAP=true bash ops/swap-api.sh <태그>   # 겹침 없이 active 를 그 자리에서 교체
#   sudo DDONA_ROLLBACK=1 bash ops/swap-api.sh <이전 태그>  # 롤백 — DB 가 그 이미지보다 앞서 있어도 이어 간다
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
# 끝난다. 재실행은 떠 있는 색을 드레인 없이 멈추지 않는다 — 한쪽에 드레인 플래그가 있으면 그쪽이 내리던
# 옛 색이라 마저 내리고, 플래그가 없으면 이번에 다시 만들 쪽을 먼저 드레인해 내린 뒤 다시 만든다.
#
# 마이그레이션은 DB 가 올릴 이미지보다 앞서 있을 때 롤백 표시(`DDONA_ROLLBACK=1`)가 있으면 건너뛰고,
# 없으면 멈춘다 — 아래 `migrate`.
#
# SKIP_OVERLAP=true 는 위험한 마이그레이션 배포의 탈출구다 — 옛 코드와 새 스키마가 겹치는 구간을 아예
# 없애려고 쉬는 색을 띄우지 않고 active 를 그 자리에서 재생성한다. 그 대가로 끊김이 생긴다. 길이는 옛
# 컨테이너에 남은 가장 긴 요청이 끝날 때까지(정지 유예 상한 65초) + 새 컨테이너 기동(약 15초)이고, 그동안
# 들어온 요청은 Caddy 에서 기다리다(최대 30초) 실패할 수 있다.
#
# 소설화 워커(`worker_blue`·`worker_green`)는 api 교체가 끝난 뒤(12-1) 다룬다. 스위치와 이미지의 워커 모듈 유무는 막
# 합류한 새 api 색 안에서 판정한다(`.env` 를 읽지 않는다). 켜져 있으면 빈 슬롯에 새 워커를 띄우고 healthy 가 된 뒤에만
# 옛 워커를 분리 정지한다 — 옛 워커는 돌던 작업을 정지 유예(420초) 안에서 마치고 내려간다. 꺼져 있으면 새 워커를 띄우지
# 않고 떠 있던 워커를 모두 분리 정지한다. 새 워커가 안 뜨면 api 교체는 그대로 두고 옛 워커를 살려 둔 채 알리고
# `DDONA_WORKER_STEP_FAILED` 줄을 남긴다(종료코드는 0 — 배포 워크플로가 그 줄로 run 을 실패로 표시한다). 아직 비우는 중인
# 옛 워커가 있으면 api 를 겹치기 전(5-2)에 그것이 내려가기를 최대 420초 기다린다. 겹침 없는 교체(SKIP_OVERLAP)는
# 워커를 보지 않는다.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/bluegreen.sh source-path=SCRIPTDIR
source "$SCRIPT_DIR/lib/bluegreen.sh"
LOG_NAME=swap-api

# 새 색이 compose 상 healthy 가 된 뒤 Caddy 가 그 색을 넣기까지(보통 1~2초) 기다리는 상한.
HEALTHY_TIMEOUT=60
# 드레인 플래그를 세운 뒤 Caddy 가 그 색을 빼기까지(보통 1~2초) 기다리는 상한.
UNHEALTHY_TIMEOUT=30
# 새 워커가 healthy 가 되기를 기다리는 상한(초). 정상 기동은 import 몇 초 + 첫 폴링이라 10~20초다.
WORKER_WAIT_TIMEOUT=60
# 비우는 중인 옛 워커가 내려가기를 기다리는 상한(초) — 워커의 정지 유예(compose `stop_grace_period`)와 같은 값이다.
# 작업 하나의 상한(`NOVELIZE_JOB_TIMEOUT_SECONDS`)을 올리면 둘을 함께 올린다.
WORKER_DRAIN_WAIT=420
# 교체가 판정한 워커 기대 상태(`on`/`off`). VM 리소스 감시 크론이 이 파일로 워커를 감시할지 정한다(`.env` 를 읽지 않게).
DDONA_WORKER_STATE_FILE="${DDONA_WORKER_STATE_FILE:-/var/lib/ddona/novelize_worker}"

# 한 색을 끊김 없이 내린다: 드레인 플래그 → Caddy 가 그 색을 뺀 것을 확인 → 정지(정지 유예
# `stop_grace_period` 를 그대로 존중해 하던 요청과 SSE 턴을 마칠 때까지 기다린다) → 삭제. 평상시 교체의 옛
# 색과 재실행이 만나는 중단 잔재가 모두 이것 하나로 내려간다. 플래그가 이미 서 있어도(드레인 중에 끊긴
# 잔재) 다시 세우면 된다 — 플래그가 서 있는 동안 헬스체크가 매번 실패 로그를 남겨 아래 확인이 곧 통과한다.
# 인자: 색, 로그 줄 머리표.
drain_and_remove() {
  local c="$1" step="$2" t_flag deadline drained=0
  t_flag="$(date +%s)"
  log "$step) api_$c 에 드레인 플래그"
  compose exec -T "api_$c" touch /tmp/draining </dev/null ||
    die "api_$c 에 드레인 플래그를 못 세웠다 — 그 색은 아직 떠 있다. 원인을 본 뒤 같은 명령을 다시 부른다"
  deadline=$(($(date +%s) + UNHEALTHY_TIMEOUT))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if caddy_saw_fail "api_$c:8000" "$t_flag"; then
      drained=1
      break
    fi
    sleep 1
  done
  if [ "$drained" = 1 ]; then
    # 1초 여유는 이 교체 방식을 실측(비-2xx 0건)할 때 쓴 값 그대로다 — 줄이거나 뺀 형태는 재 보지 않았다.
    sleep 1
    log "$step) Caddy 가 api_$c 를 뺐다"
  else
    log "⚠️ ${UNHEALTHY_TIMEOUT}s 안에 Caddy 가 api_$c 를 빼는 로그를 못 봤다 — 그래도 정지로 간다(정지 유예 동안 하던 요청은 마친다)"
  fi
  log "$step) api_$c 정지·삭제"
  compose stop "api_$c"
  compose rm -f "api_$c"
}

# 올릴 이미지 안에서 돌리는 판정: 그 이미지의 리비전 파일 목록과 DB 의 `alembic_version` 을 대조해 마지막에
# `DDONA_DB_REVISION known|ahead <리비전들>` 한 줄을 낸다(`alembic_version` 이 없거나 비면 known). `alembic
# current` 의 실패로 가리지 않는 이유: DB 에 못 닿은 실패와 문구 말고는 구분되지 않는다. 여기서는 DB 에 못
# 닿으면 예외로 0 이 아닌 코드가 나 판정 실패가 된다. DB 주소는 마이그레이션과 같은 설정값(`settings.database_url`)이다.
DB_REVISION_CHECK="$(
  cat <<'PY'
import asyncio

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from api.core.config import settings

known = {s.revision for s in ScriptDirectory.from_config(Config("alembic.ini")).walk_revisions()}


async def db_revisions():
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            if (await conn.execute(text("SELECT to_regclass('alembic_version')"))).scalar() is None:
                return []
            return list((await conn.execute(text("SELECT version_num FROM alembic_version"))).scalars())
    finally:
        await engine.dispose()


revs = asyncio.run(db_revisions())
print("DDONA_DB_REVISION", "ahead" if any(r not in known for r in revs) else "known", " ".join(revs) or "-")
PY
)"

# 마이그레이션. DB 의 현재 리비전을 올릴 이미지가 모르면 DB 가 이 이미지보다 앞서 있거나 이미지와 갈라져
# 있는데, 판정은 둘을 구분하지 못한다. 마이그레이션이 낀 배포를 옛 태그로 되돌리는 롤백이면 앞선 쪽이라
# 건너뛰는 게 맞다 — 그 이미지로 `alembic upgrade head` 를 돌리면 `Can't locate revision` 으로 멈춰 롤백
# 자체가 안 되고, 앞선 DB 에서 upgrade 가 할 일은 원래 없다. 롤백이 아닌 배포에서는 이 상황이 정상적으로
# 생기지 않는다. downgrade 없이 revert 를 main 에 올리면 DB 가 앞선 채 남고, 그 뒤 새 마이그레이션이 든
# 배포는 갈라진 쪽이라 건너뛰면 새 코드가 자기 마이그레이션 없는 스키마에서 뜬다(`/health` 는 DB 를 보지
# 않아 교체는 성공으로 끝난다). 그래서 건너뜀은 부른 쪽이 롤백이라고 밝혔을 때(`DDONA_ROLLBACK`)만 하고,
# 아니면 멈춘다 — 실패 정리가 쉬는 색을 되돌리고 옛 색은 계속 서빙한다. 스키마를 되돌리는 downgrade 는
# 이 스크립트가 하지 않는다(순서를 사람이 정한다). DB 가 이미지보다 뒤거나 같으면 표시와 상관없이
# upgrade 한다. 판정 자체가 실패하면 건너뛰지 않고 멈춘다 — 확인 못 한 채 건너뛰면 새 코드가 옛 스키마
# 위에서 뜰 수 있다. 인자: 올릴 이미지가 걸린 색.
migrate() {
  local c="$1" out verdict
  out="$(compose run --rm -T "api_$c" python -c "$DB_REVISION_CHECK" </dev/null)" ||
    die "DB 리비전 판정이 실패했다(위 메시지) — 마이그레이션을 건너뛸지 정하지 못해 멈춘다"
  verdict="$(sed -n 's/^DDONA_DB_REVISION //p' <<<"$out" | tail -n 1)"
  case "$verdict" in
    known\ *)
      log "DB 리비전(${verdict#known })을 이 이미지가 안다 — alembic upgrade head"
      compose run --rm -T "api_$c" alembic upgrade head </dev/null
      ;;
    ahead\ *)
      if [ "$IS_ROLLBACK" = 1 ]; then
        log "DB 리비전(${verdict#ahead })을 이 이미지가 모른다 — 롤백 표시가 있어 DB 가 이 이미지보다 앞선 것으로 보고 마이그레이션 건너뜀"
      else
        die "DB 리비전(${verdict#ahead })을 이 이미지가 모른다 — DB 가 이 이미지보다 앞서 있거나 갈라져 있다. 롤백이 아닌 배포에서 마이그레이션을 건너뛰면 새 코드가 맞지 않는 스키마에서 뜰 수 있어 멈춘다(옛 색은 그대로 서빙). 옛 태그로 되돌리는 롤백이면 DDONA_ROLLBACK=1 을 붙여 다시 부른다(Actions 수동 실행은 image_tag 를 채우면 붙는다)"
      fi
      ;;
    *) die "DB 리비전 판정 출력을 읽지 못했다 — 마이그레이션을 건너뛸지 정하지 못해 멈춘다" ;;
  esac
}

# --- 소설화 워커 ---
# 아래 함수들은 api 교체를 멈추지 않는다 — 실패는 로그·알림·실패 표식으로 남기고 돌아온다. 워커 단계(12-1)는 새 api 가
# 이미 서빙 중인 구간이라 여기서 `die` 하면 13) 의 상태 파일이 안 쓰이고 배포가 실패로 보여, 성공한 api 교체를 사람이
# 되돌리게 만든다.

# 워커 한 색의 상태: none(컨테이너 없음) / stopped(있지만 떠 있지 않음) / draining(떠 있고 정지 표식이 있음) /
# alive(떠 있고 표식 없음) / unknown(확인 실패 — 재시작을 되풀이하는 중이면 exec 가 거부된다).
worker_status() {
  local c="$1" all up out
  all="$(compose ps -aq "worker_$c")" || {
    echo unknown
    return 0
  }
  if [ -z "$all" ]; then
    echo none
    return 0
  fi
  up="$(compose ps -q "worker_$c")" || {
    echo unknown
    return 0
  }
  if [ -z "$up" ]; then
    echo stopped
    return 0
  fi
  out="$(compose exec -T "worker_$c" sh -c 'if [ -e /tmp/draining ]; then echo yes; else echo no; fi')" || {
    echo unknown
    return 0
  }
  case "$out" in
    yes) echo draining ;;
    no) echo alive ;;
    *) echo unknown ;;
  esac
}

# 워커 한 색을 분리 정지한다: 정지 표식을 세운 뒤 `docker compose stop` 을 systemd 유닛으로 띄우고 곧바로 돌아온다. 정지는
# 정지 유예(420초) 동안 돌던 작업을 마치느라 오래 걸리는데, 이 스크립트가 기다리면 잠금을 그만큼 쥐고 배포 SSH 가 끊기면
# 함께 죽는다. `systemd-run` 유닛은 PID 1 이 띄워 이 스크립트의 열린 fd(교체 잠금 fd 9)를 물려받지 않고 SSH·스크립트가
# 끝나도 산다 — 백그라운드 `&`·`nohup`·`setsid` 만으로는 잠금 fd 를 물려받아 정지가 끝날 때까지 다음 교체가 잠금을 못
# 얻는다. 같은 이름의 유닛이 이미 돌고 있으면(앞선 교체가 보낸 정지) 다시 보내지 않는다. 정지가 끝난 컨테이너는 멈춘 채
# 남고 다음 교체의 5-2) 가 치운다.
detach_stop_worker() {
  local c="$1" unit="ddona-novelize-worker-stop-$1"
  compose exec -T "worker_$c" touch /tmp/draining ||
    log "⚠️ worker_$c 에 정지 표식을 못 세웠다 — 정지는 그대로 보낸다"
  if systemctl is-active --quiet "$unit"; then
    log "worker_$c 는 이미 정지 중이다(유닛 $unit)"
    return 0
  fi
  systemd-run --unit="$unit" --collect --quiet \
    docker compose "${COMPOSE_ARGS[@]}" stop "worker_$c" </dev/null ||
    log "⚠️ worker_$c 의 분리 정지를 띄우지 못했다(위 메시지) — 그 워커는 떠 있다. 다음 교체가 다시 시도한다"
}

# 알림은 지금 서빙 중인 api 색(`WORKER_API`, `worker_step` 이 정한다) 안에서 보낸다 — 그 컨테이너 env 에 웹훅 주소가 있어
# 이 스크립트가 `.env` 를 읽지 않아도 된다.
WORKER_API=""
worker_notify() {
  compose exec -T "api_$WORKER_API" env PYTHONPATH=/app/scripts python -c \
    'import sys; from ops.notify import notify; sys.exit(0 if notify(sys.argv[1]) else 1)' "$1" ||
    log "⚠️ 워커 단계 알림을 보내지 못했다"
}

# 워커 단계 실패: 로그·알림, 그리고 표준 출력의 실패 표식 한 줄. 배포 워크플로는 이 줄을 보고 run 을 실패로 표시한다 —
# 스크립트는 api 교체가 끝났으므로 0 으로 끝난다(0 이 아니면 원격 배포 스크립트가 그 자리에서 멈춰 caddy 반영·실행 이미지
# 확인·이미지 정리가 건너뛰어진다). 인자: 무엇이 실패했는지, 옛 워커 상황 문장.
worker_fail() {
  local what="$1" after="$2"
  log "⚠️ 12-1) $what — $after"
  worker_notify "🧵 ddona-api 배포: $what — api 교체는 끝냈다. $after"
  echo "DDONA_WORKER_STEP_FAILED $what"
}

# 실패 알림의 둘째 문장. 살아 있는 워커가 있으면 그것이 계속 작업을 받고, 없으면 새 작업이 만료 환불된다.
worker_after_text() {
  local c
  for c in blue green; do
    if [ "$(worker_status "$c")" = alive ]; then
      echo "옛 워커(worker_$c)가 계속 작업을 받는다. 원인을 고친 뒤 같은 교체를 다시 부른다"
      return 0
    fi
  done
  echo "소설화 워커가 하나도 없다 — 새 소설화 작업은 60초 뒤 환불된다. 원인을 고친 뒤 같은 교체를 다시 부르거나, 스위치를 끄는 교체로 되돌린다"
}

write_worker_state() {
  { mkdir -p "$(dirname "$DDONA_WORKER_STATE_FILE")" &&
    printf '%s\n' "$1" >"$DDONA_WORKER_STATE_FILE.tmp" &&
    mv -f "$DDONA_WORKER_STATE_FILE.tmp" "$DDONA_WORKER_STATE_FILE"; } ||
    log "⚠️ 워커 기대 상태 파일($DDONA_WORKER_STATE_FILE)을 쓰지 못했다 — 리소스 감시가 지난 값으로 판정한다"
}

# 5-2) 슬롯 비우기. 멈춘 워커는 곧바로 지우고(정상 교체 뒤에는 정지가 끝난 옛 워커가 늘 하나 남는다 — 그것을 기다리면
# 매 교체가 420초를 채운 뒤 워커를 못 갈게 된다), 떠 있으면서 정지 중인 워커만 내려갈 때까지 기다린다. api 를 겹치기
# 전에 기다려야 "api 두 색 + 워커 둘" 이 동시에 뜨지 않는다. 스위치와 무관하게 기다린다 — 스위치를 끄는 교체 바로 뒤의
# 태그 롤백도 워커가 다 내려가기를 이 단계가 기다린다. 상한을 넘기면 api 교체는 계속하고 워커 단계만 건너뛴다
# (`WORKER_SKIP_REASON`, 12-1 이 알린다).
WORKER_SKIP_REASON=""
wait_worker_slots() {
  local deadline c st waiting next_log
  deadline=$(($(date +%s) + WORKER_DRAIN_WAIT))
  next_log=0
  while :; do
    waiting=""
    for c in blue green; do
      st="$(worker_status "$c")"
      case "$st" in
        stopped)
          log "5-2) 멈춘 worker_$c 삭제"
          compose rm -f "worker_$c" || log "⚠️ 멈춘 worker_$c 를 지우지 못했다"
          ;;
        unknown)
          log "⚠️ 5-2) worker_$c 상태를 확인하지 못했다(재시작을 되풀이하는 중일 수 있다) — 30초 유예로 정지·삭제"
          compose stop -t 30 "worker_$c" || true
          compose rm -f "worker_$c" || log "⚠️ worker_$c 를 지우지 못했다"
          ;;
        draining)
          # 표식은 섰는데 정지가 안 걸린 잔재(표식 직후 교체가 끊김)면 여기서 다시 건다.
          detach_stop_worker "$c"
          waiting="$waiting worker_$c"
          ;;
      esac
    done
    if [ -z "$waiting" ]; then
      return 0
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
      WORKER_SKIP_REASON="정지 중인 옛 워커(${waiting# })가 ${WORKER_DRAIN_WAIT}s 안에 안 내려가 새 워커를 띄우지 않았다"
      log "⚠️ 5-2) $WORKER_SKIP_REASON — api 교체는 계속한다"
      return 0
    fi
    if [ "$(date +%s)" -ge "$next_log" ]; then
      log "5-2) 정지 중인 워커(${waiting# })가 내려가기를 대기(최대 ${WORKER_DRAIN_WAIT}s)"
      next_log=$(($(date +%s) + 30))
    fi
    sleep 5
  done
}

# 12-1) 판정: 지금 서빙 중인 api 색(인자 — 평상시는 막 합류한 새 색) 안에서 스위치와 워커 모듈 유무를 한 줄로 찍는다. 그
# 컨테이너는 이번 이미지와 지금 `.env` 로 만들어졌고 워커도 같은 이미지·env 로 뜨므로 판정 대상이 같다. 앱과 같은 설정 파서라 참/거짓 해석이 갈리지 않고,
# 출력은 토큰 셋뿐이다(`.env` grep 은 파서가 다르고, `compose config`·`docker inspect` 는 비밀까지 꺼낸다). 워커 도입
# 이전 이미지는 그 설정 칸도 모듈도 없어 `off absent` 다 — 옛 이미지로 워커를 띄워 모듈을 못 찾고 재시작을 되풀이하는
# 일을 이 판정이 막는다.
WORKER_CHECK='import importlib.util as u; from api.core.config import settings as s; print("DDONA_WORKER", "on" if getattr(s, "novelize_worker_enabled", False) else "off", "present" if u.find_spec("api.novelize.worker") else "absent")'

worker_step() {
  local serving="$1" out verdict c st n t="" o started_c started_o
  WORKER_API="$serving"
  out="$(compose exec -T "api_$serving" python -c "$WORKER_CHECK")" || {
    worker_fail "소설화 워커 판정이 실패했다(위 메시지) — 워커는 건드리지 않았다" "$(worker_after_text)"
    return 0
  }
  verdict="$(sed -n 's/^DDONA_WORKER //p' <<<"$out" | tail -n 1)"
  case "$verdict" in
    "on present") write_worker_state on ;;
    "on absent" | "off present" | "off absent") write_worker_state off ;;
    *)
      worker_fail "소설화 워커 판정 출력을 읽지 못했다 — 워커는 건드리지 않았다" "$(worker_after_text)"
      return 0
      ;;
  esac

  if [ "$verdict" != "on present" ]; then
    n=0
    for c in blue green; do
      case "$(worker_status "$c")" in
        alive | draining)
          detach_stop_worker "$c"
          n=$((n + 1))
          ;;
      esac
    done
    log "12-1) 소설화 워커 꺼짐(판정: $verdict — 스위치가 꺼졌거나 이 이미지에 워커가 없다) — 떠 있던 워커 ${n}개 분리 정지"
    return 0
  fi

  if [ -n "$WORKER_SKIP_REASON" ]; then
    worker_fail "$WORKER_SKIP_REASON" "$(worker_after_text)"
    return 0
  fi

  # 대상 슬롯: 서빙 중인 api 색 슬롯이 비었으면 그것, 아니면 다른 색 슬롯. 두 색 이미지 줄이 같은 참조가 된 뒤에만 부르므로
  # 어느 슬롯이든 이번 이미지로 뜬다. 둘 다 차 있으면(새 워커를 띄운 뒤 옛 워커를 정지하기 전에 끊긴 잔재) 먼저 뜬 쪽을 정지하고 이번
  # 기동은 건너뛴다 — 다음 교체가 빈 슬롯으로 잇는다.
  for c in "$serving" "$(other_color "$serving")"; do
    case "$(worker_status "$c")" in
      alive | draining) ;;
      *)
        t="$c"
        break
        ;;
    esac
  done
  if [ -z "$t" ]; then
    started_c="$(started_at_ns_of "$(compose ps -q worker_blue)")" || started_c=0
    started_o="$(started_at_ns_of "$(compose ps -q worker_green)")" || started_o=0
    if [ "$started_c" -le "$started_o" ]; then o=blue; else o=green; fi
    log "12-1) 두 워커가 다 떠 있다(중단된 교체의 잔재) — 먼저 뜬 worker_$o 를 분리 정지하고 이번 기동은 건너뛴다"
    detach_stop_worker "$o"
    return 0
  fi

  log "12-1) worker_$t 기동(이미지 $REF, 최대 ${WORKER_WAIT_TIMEOUT}s)"
  if compose up -d --no-deps --force-recreate --wait --wait-timeout "$WORKER_WAIT_TIMEOUT" "worker_$t"; then
    o="$(other_color "$t")"
    st="$(worker_status "$o")"
    case "$st" in
      alive | draining)
        detach_stop_worker "$o"
        log "12-1) worker_$t 기동(이미지 $REF), worker_$o 분리 정지"
        ;;
      *) log "12-1) worker_$t 기동(이미지 $REF), 옛 워커 없음" ;;
    esac
    return 0
  fi
  # 막 뜬 워커는 받은 일이 없거나 적다 — 30초에 잘린 작업은 만료 정리가 환불한다. 옛 워커는 그대로 둔다.
  log "12-1) worker_$t 가 ${WORKER_WAIT_TIMEOUT}s 안에 healthy 가 안 됐다 — 정지·삭제하고 옛 워커는 그대로 둔다"
  compose stop -t 30 "worker_$t" || true
  compose rm -f "worker_$t" || log "⚠️ worker_$t 를 지우지 못했다 — 직접 확인한다"
  worker_fail "새 소설화 워커(worker_$t, $REF)가 healthy 가 안 됐다" "$(worker_after_text)"
}

TAG_ARG="${1:-}"
# 받은 값을 무엇보다 먼저 찍는다 — 워크플로가 값을 못 넘겼는지(특히 SKIP_OVERLAP 이 원격 셸까지
# 갔는지) 배포 로그만 보고 알 수 있어야 한다.
log "시작: tag=${TAG_ARG:-(생략)} skip_overlap=${SKIP_OVERLAP:-} rollback=${DDONA_ROLLBACK:-}"

case "${SKIP_OVERLAP:-}" in
  true) SKIP=1 ;;
  false | '') SKIP=0 ;;
  *) die "SKIP_OVERLAP 은 true·false·빈 값만 받는다: '${SKIP_OVERLAP}'" ;;
esac
# 롤백 표시. DB 가 올릴 이미지보다 앞서 있을 때 마이그레이션을 건너뛸지만 정한다(`migrate`).
case "${DDONA_ROLLBACK:-}" in
  1 | true) IS_ROLLBACK=1 ;;
  0 | false | '') IS_ROLLBACK=0 ;;
  *) die "DDONA_ROLLBACK 은 1·true·0·false·빈 값만 받는다: '${DDONA_ROLLBACK}'" ;;
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

# 3) active/idle 판정. 두 색이 다 떠 있으면(중단된 교체의 잔재) 드레인 플래그부터 본다 — 그 형상에서 어느
#    쪽이 서빙 중인지는 플래그만 답한다(`lib/bluegreen.sh` 의 `pick_active`).
DRAINING=""
if [ "$(grep -c . <<<"$RUNNING")" = 2 ]; then
  DRAINING="$(draining_colors "$RUNNING")"
fi
PAIR="$(pick_active "$RUNNING" "$(read_state)" "$DRAINING")"
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

# 4-1) 드레인 시작 뒤 끊긴 교체의 잔재(쉬는 색에 드레인 플래그)면 그 색을 마저 내린다. 이미 Caddy 밖이고
#      하던 요청은 정지 유예 안에서 마친다. 끝나면 한 색 형상이라 아래가 평소처럼 이어진다. 원래 요청이 끊긴
#      교체가 올리던 바로 그 이미지면(같은 태그로 재실행) 그 교체에 남은 일은 이것과 워커 단계뿐이라 둘을 하고 끝낸다.
#      태그를 생략한 재실행(env 반영)은 끊긴 교체가 지금 env 로 떴는지 알 수 없어 한 번 더 교체한다.
if grep -Fqx "$IDLE" <<<"$DRAINING"; then
  log "4-1) 중단된 교체의 잔재: api_$IDLE 에 드레인 플래그가 있다 — 마저 내리고 이어 간다"
  drain_and_remove "$IDLE" "4-1"
  env_set "$IDLE_KEY" "$CURRENT_REF"
  write_state "$ACTIVE"
  RUNNING="$ACTIVE"
  log "4-1) 잔재 정리 완료: active=$ACTIVE 상태 파일 기록"
  if [ -n "$TAG_ARG" ] && [ "$REF" = "$CURRENT_REF" ]; then
    # 끊긴 곳은 옛 색 드레인(10~11)이라 그 교체의 워커 단계(12-1)는 아직 돌지 않았다. 두 색 줄이 이제 같은 참조이고 api 는
    # 한 색이므로 여기서 슬롯을 비우고 워커 단계를 돌려 워커도 이 이미지로 맞춘다 — 안 하면 같은 태그 재실행이 초록으로
    # 끝나도 워커는 옛 이미지 그대로(처음 켜는 교체였다면 워커 없음)로 남는다.
    wait_worker_slots
    worker_step "$ACTIVE"
    log "완료: api_$ACTIVE 가 이미 $REF 다 — 끊긴 교체를 마저 끝냈다. 소요 $(($(date +%s) - START))s"
    exit 0
  fi
fi

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
# 워크플로가 부른 실행은 SSH 가 끊긴 뒤 다음 로그 줄에서 SIGPIPE 로 이 정리 없이 끝날 수도 있다. 그때 남는
# 형상(쉬는 색 줄이 새 값이거나 두 색이 다 떠 있음)도 같은 명령을 다시 부르면 이어서 끝난다.
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if [ "$SKIP" = 1 ]; then
  # 겹침 없는 교체. 두 색이 다 떠 있으면(중단 잔재) 쉬는 색부터 내린다 — 남겨 두면 옛 코드의 잔재가
  # 새 스키마로 트래픽을 받는다. 겹침을 끄려는 바로 그 상황이다. 그 색이 서빙 중일 수 있어 드레인한 뒤 내린다.
  if [ "$(grep -c . <<<"$RUNNING")" = 2 ]; then
    log "skip_overlap: 남아 있던 api_$IDLE 를 먼저 드레인·정지·삭제"
    drain_and_remove "$IDLE" "skip_overlap"
  fi

  PREV_REF="$CURRENT_REF"
  env_set "$ACTIVE_KEY" "$REF"
  ROLLBACK=active
  log "skip_overlap: $ACTIVE_KEY 갱신, 마이그레이션(api_$ACTIVE 의 새 이미지)"
  # 기동보다 먼저다 — 앱이 기동할 때 새 스키마를 읽는 코드가 있어 순서가 바뀌면 새 컨테이너가 죽는다.
  migrate "$ACTIVE"

  # 여기부터는 되돌리지 않는다 — 재생성이 시작되면 active 가 이미 바뀌는 중이라, 복구는 이전 태그로 이
  # 스크립트를 다시 부르는 것이다.
  ROLLBACK=""
  log "skip_overlap: api_$ACTIVE 를 그 자리에서 재생성(드레인 없음 — 하던 요청이 끝나고 새 컨테이너가 뜰 때까지 끊긴다)"
  compose up -d --force-recreate --wait --wait-timeout "$DDONA_WAIT_TIMEOUT" "api_$ACTIVE" ||
    die "api_$ACTIVE 가 healthy 가 안 됐다 — 서비스가 내려갔을 수 있다. 이전 태그로 이 스크립트를 다시 부른다"

  # 쉬는 색 변수도 같은 참조로 — 서비스명 없는 `up -d` 가 실수로 그 색을 띄워도 같은 코드가 뜨게.
  # 컨테이너는 만들지 않는다.
  env_set "$IDLE_KEY" "$REF"
  write_state "$ACTIVE"
  log "완료(skip_overlap): active=$ACTIVE 상태 파일 기록, 이미지 $REF, 소요 $(($(date +%s) - START))s"
  exit 0
fi

# 5-1) 쉬는 색이 떠 있으면(새 색 합류 직후 끊긴 교체의 잔재 — 플래그 없는 두 색) 그 색은 Caddy 업스트림에
#      들어가 서빙 중일 수 있다. 8단계의 재생성은 그 색을 그냥 멈추므로 하던 요청이 끊긴다. 그래서 아무것도
#      바꾸기 전에 드레인해 내린다 — 그동안은 active 혼자 서빙한다.
if [ "$(grep -c . <<<"$RUNNING")" = 2 ]; then
  log "5-1) 떠 있는 api_$IDLE(중단된 교체의 잔재)를 다시 만들기 전에 드레인"
  drain_and_remove "$IDLE" "5-1"
fi

# 5-2) 소설화 워커 슬롯 비우기(위 `wait_worker_slots`). 아무것도 바꾸기 전, api 를 겹치기 전에 한다.
wait_worker_slots

# 6) idle 줄 교체 — 바로 되돌리기를 건다. 여기서 Caddy 확인(9)까지 어디서 실패하든 idle 을 정리하고 줄을
#    되돌려, 실패 뒤 형상이 "실행 전과 같음" 하나로 판정되게 한다.
PREV_REF="$(env_get "$IDLE_KEY")"
env_set "$IDLE_KEY" "$REF"
ROLLBACK=idle
log "6) $IDLE_KEY 갱신"

# 7) 마이그레이션은 idle 의 새 이미지로, 옛 색이 서빙하는 동안, idle 기동 전에.
log "7) 마이그레이션(api_$IDLE 의 새 이미지)"
migrate "$IDLE"

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

# 10~11) active 드레인 → 정지·삭제. 여기서 끊기면(두 색이 다 떠 있고 옛 색에 플래그) 재실행의 4-1 이 잇는다.
drain_and_remove "$ACTIVE" "10~11"

# 12) 쉬는 색이 된 옛 active 의 변수도 새 참조로 — 서비스명 없는 `up -d` 가 실수로 그 색을 띄우면 옛
#     코드가 업스트림에 합류하기 때문이다.
env_set "$ACTIVE_KEY" "$REF"
log "12) $ACTIVE_KEY 도 같은 이미지로 맞춤"

# 12-1) 소설화 워커(위 `worker_step`). 두 색 이미지 줄이 같은 참조가 된 뒤라 빈 슬롯 어디에 띄워도 이번 이미지다. 새 api 가
#       이미 서빙 중이라 여기서 무엇이 실패해도 api 교체를 되돌리지 않는다.
worker_step "$IDLE"

# 13) 상태 파일. 이 줄이 배포 로그에 찍혀야 stdin 이 중간에 삼켜지지 않고 끝까지 돈 것이다.
write_state "$IDLE"
log "13) 완료: active=$IDLE 상태 파일 기록, 이미지 $REF, 소요 $(($(date +%s) - START))s"
