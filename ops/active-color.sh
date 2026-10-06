#!/usr/bin/env bash
# 지금 서빙 중인 api 색(`blue`/`green`)을 한 줄로 찍는다. 운영 명령이 컨테이너를 고를 때 쓴다:
#
#   docker compose … exec -T api_$(bash ops/active-color.sh) python …
#
# 읽기 전용이라 잠그지 않고 sudo 도 필요 없다(상태 파일은 누구나 읽을 수 있다).
#
# 상태 파일의 색이 실제로 떠 있으면 그 색, 상태 파일이 없거나 그 색이 안 떠 있으면 떠 있는 색이 정확히
# 하나일 때만 그 색이다. 하나도 없거나 둘 다 떠 있으면(교체 중이거나 중단된 교체의 잔재) 이유를 stderr 에
# 남기고 0 이 아닌 코드로 끝난다 — 조용히 아무 색이나 내면 그 명령이 엉뚱한 컨테이너로 간다.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/bluegreen.sh source-path=SCRIPTDIR
source "$SCRIPT_DIR/lib/bluegreen.sh"
LOG_NAME=active-color

RUNNING="$(running_colors)"
pick_active_for_ops "$RUNNING" "$(read_state)"
