#!/usr/bin/env bash
# `ops/cron.d/ddona-hidden-novel-purge` 가 매일(KST 02:35) 이 스크립트를 부른다.
#
# 숨긴 소설 파기(`python -m api.novelize.hidden_purge`)를 지금 서빙 중인 api 컨테이너 안에서 돌린다. 소설 삭제·탈퇴와 같은
# 삭제 코드(`api/novelize/deletion.py`)를 써야 해서 psql 로 직접 붙지 않는다 — 소설 아래 테이블 목록이 앱 한 곳에만 있다.
# 지울 것이 없는 날에는 아무것도 바꾸지 않고 끝난다. 실패한 날은 다음 날 저절로 다시 돈다(실패는 Bugsink 에도 남는다).
#
# `/opt/ddona/.env` 를 읽지 않는다 — DB 접속은 컨테이너가 자기 env 로 한다.
set -uo pipefail

# 심볼릭 링크(`/opt/ddona/purge-hidden-novels.sh`)로 불리므로 링크가 가리키는 저장소 `ops/` 를 찾는다.
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=lib/bluegreen.sh source-path=SCRIPTDIR
source "$SCRIPT_DIR/lib/bluegreen.sh"
LOG_NAME=hidden-novel-purge

# 교체 중이라 색을 하나로 못 고르면 그날은 실패로 끝난다 — 엉뚱한 컨테이너에서 돌리지 않는다.
if ! color="$(bash "$SCRIPT_DIR/active-color.sh")"; then
  log "서빙 중인 api 색을 고르지 못했다"
  exit 1
fi

compose exec -T "api_$color" python -m api.novelize.hidden_purge
code=$?
if [ "$code" -ne 0 ]; then
  log "숨긴 소설 파기 실패(종료 코드 $code)"
fi
exit "$code"
