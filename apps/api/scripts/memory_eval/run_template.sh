#!/usr/bin/env bash
# 측정 하네스 실행 틀 — 이 파일을 실행 폴더로 복사해 <...> 자리만 채워 쓴다. 데이터·키는 여기 적지 않는다.
#
# - 전역 인자(--run · --data-dir · --status-dir · --cap-usd · --halt-usd · --bundle)는 하위 명령 **앞에** 둔다.
#   뒤에 두면 argparse 가 그 하위 명령의 인자로 읽으려다 거부한다.
# - 측정 데이터(대본·심기 표·명세)는 공개 저장소 밖 폴더에 두고 --data-dir 로 준다. 기본 경로는 없다.
# - 작업 DB 는 명령 앞의 DATABASE_URL 로 준다(이름이 lm_eval_ 로 시작해야 한다). .env 의 값보다 명령의 값이 이긴다.
# - 끝났는지는 --status-dir 의 완료 표지(done.<종료 코드>)로 본다. status.json 은 진행 중 상태(명령·pid·시작 시각)다.
set -euo pipefail

API_DIR="<저장소>/apps/api"
RUN_DIR="<원자료 폴더>"
DATA_DIR="<측정 데이터 폴더 — 저장소 밖>"
STATUS_DIR="$RUN_DIR/status/<단계 이름>"
WORK_DB_URL="postgresql+asyncpg://<사용자>:<비밀번호>@localhost:5432/lm_eval_<작업 DB>"

cd "$API_DIR"
DATABASE_URL="$WORK_DB_URL" uv run --env-file .env python scripts/memory_eval_cli.py \
  --run "$RUN_DIR" \
  --data-dir "$DATA_DIR" \
  --status-dir "$STATUS_DIR" \
  --cap-usd "<묶음 상한>" --halt-usd "<멈춤 선>" --bundle "<승인 묶음>" \
  <하위 명령> <하위 명령 인자...>

# 다른 셸에서 끝을 기다릴 때(출력 마지막 줄을 견주지 않는다):
#   until ls "$STATUS_DIR"/done.* >/dev/null 2>&1; do sleep 30; done; ls "$STATUS_DIR"/done.*

# 투입(insert)은 요약 접기·추출을 이 프로세스 안에서 부르므로, 이 프로세스의 설정이 투입 env 표와 한 줄이라도 다르거나
# PROMPT_DUMP_PATH 가 없으면 시작 전에 거부한다. 표를 파일로 뽑아 명령 앞에 env 로 붙인다(값에 공백이 없어 그대로 펼친다).
# 임베딩을 채우는 투입(--fill-embeddings)이면 --embed-model·--embed-dims 를 투입 인자와 같은 값으로 준다.
#   uv run --env-file .env python scripts/memory_eval_cli.py --run "$RUN_DIR" arm-env --insert \
#     --embed-model "<모델>" --embed-dims "<차원>" --prompt-dump "$RUN_DIR/dumps/insert-<단계 이름>.jsonl" \
#     > "$RUN_DIR/insert-env.txt"
#   env $(grep -v '^#' "$RUN_DIR/insert-env.txt") DATABASE_URL="$WORK_DB_URL" \
#     uv run --env-file .env python scripts/memory_eval_cli.py --run "$RUN_DIR" ... insert <투입 인자...>

# 중단된 프로브가 남긴 작업자 서버 내리기(이 트리·작업자 포트만, pid·포트만 출력). --port 는 프로브의 --port 와 같게:
#   uv run --env-file .env python scripts/memory_eval_cli.py --run "$RUN_DIR" probe-cleanup --port <기준 포트>
