#!/usr/bin/env bash
# 지금 서빙 중인 api 색(`blue`/`green`)을 한 줄로 찍는다. 운영 명령이 컨테이너를 고를 때 쓴다:
#
#   sudo docker compose … exec -T api_$(sudo bash ops/active-color.sh) python …
#
# 읽기 전용이라 잠그지 않는다. 그래도 sudo 로 부른다 — compose 가 프로젝트를 불러올 때 root 0600 인
# `/opt/ddona/.env`(`--env-file`·`env_file`)를 읽어서, 일반 사용자로는 색을 찾기 전에 실패한다.
#
# 두 색이 다 떠 있으면 드레인 플래그가 선 색(교체가 내리던 옛 색)은 후보에서 뺀다. 그다음 상태 파일의 색이
# 실제로 떠 있으면 그 색, 상태 파일이 없거나 그 색이 안 떠 있으면 남은 색이 정확히 하나일 때만 그 색이다.
# 하나도 없거나 둘 다 남으면(교체 중이거나 중단된 교체의 잔재) 이유를 stderr 에 남기고 0 이 아닌 코드로
# 끝난다 — 조용히 아무 색이나 내면 그 명령이 엉뚱한 컨테이너로 간다.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/bluegreen.sh source-path=SCRIPTDIR
source "$SCRIPT_DIR/lib/bluegreen.sh"
LOG_NAME=active-color

RUNNING="$(running_colors)"
DRAINING=""
if [ "$(grep -c . <<<"$RUNNING" || true)" = 2 ]; then
  DRAINING="$(draining_colors "$RUNNING")"
fi
pick_active_for_ops "$RUNNING" "$(read_state)" "$DRAINING"
