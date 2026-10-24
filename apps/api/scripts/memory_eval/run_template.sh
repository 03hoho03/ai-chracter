#!/usr/bin/env bash
# 측정 하네스 실행 틀 — 이 파일을 실행 폴더로 복사해 <...> 자리만 채워 쓴다. 데이터·키는 여기 적지 않는다.
#
# - 전역 인자(--run · --data-dir · --status-dir · --cap-usd · --halt-usd · --bundle)는 하위 명령 **앞에** 둔다.
#   뒤에 두면 argparse 가 그 하위 명령의 인자로 읽으려다 거부한다.
# - 측정 데이터(대본·심기 표·명세)는 공개 저장소 밖 폴더에 두고 --data-dir 로 준다. 기본 경로는 없다.
# - 작업 DB 는 명령 앞의 DATABASE_URL 로 준다(이름이 lm_eval_ 로 시작해야 한다). .env 의 값보다 명령의 값이 이긴다.
# - 끝났는지는 --status-dir 의 완료 표지(done.<종료 코드>)로 본다. status.json 은 진행 중 상태(명령·pid·시작 시각)다.
# - 측정 커밋(MEASURE_COMMIT)을 env 로 준다. 명령은 시작할 때 HEAD 가 그 커밋이고 추적 파일 변경이 없는지 단언하고
#   결과를 status.json 의 headCheck 칸에 남긴다. 다르거나 고친 파일이 있으면 명령을 돌리지 않고 done.2 로 끝난다.
set -euo pipefail

MEASURE_COMMIT="${MEASURE_COMMIT:?측정 커밋 sha 를 env MEASURE_COMMIT 로 준다}"
# 운영 활성 세트·모델 배정 표 내보내기(꼴 3) — 저장소 밖 원자료 폴더에 0600 으로 둔다.
PROMPT_EXPORT="${PROMPT_EXPORT:?운영 활성 세트 내보내기 파일 경로를 env PROMPT_EXPORT 로 준다}"

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
  --expect-head "$MEASURE_COMMIT" \
  <하위 명령> <하위 명령 인자...>

# 순서: 운영 문안 맞추기(sync-prompts) → 투입( insert ) → 체크포인트 얼리기( freeze ) → 프로브. 프로브 시도마다 작업 DB 가
# 템플릿 복제본으로 바뀌어, 템플릿이 맞추기보다 먼저 얼려졌으면 그 템플릿의 이전 문안이 실린다. 측정 서버를 내린 채 맞춘다.
#   DATABASE_URL="$WORK_DB_URL" uv run --env-file .env python scripts/memory_eval_cli.py --run "$RUN_DIR" \
#     --expect-head "$MEASURE_COMMIT" sync-prompts --export "$PROMPT_EXPORT" --redis-url "<측정 서버 Redis>"
# 프로브는 늘 같은 내보내기를 준다 — 계획한 체크포인트 템플릿마다 시작 전에 대조하고 다르면 거부한다:
#   ... probe --prompt-export "$PROMPT_EXPORT" <프로브 인자...>

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

# 판정자 대조군 — 경계 견본 파일을 여럿 줄 수 있다(id 가 서로·심기 표와 겹치면 거부, 파일별 sha256 은 대조군 결과에 남는다).
# 주지 않으면 --data-dir 의 기본 견본 파일 하나를 읽는다:
#   ... judge --plants <심기 표> --controls --allow-paid --boundary-controls <견본 파일> <견본 파일...>
# 묶음 판정 — 효과마다 분할 시드 파일의 합계 하한을 읽는다. 빠뜨리면 효과 하나만 표본이 모자라도 전체 판정이 멈춘다:
#   ... v4-verdict --seal-sha <봉인 sha> --story <심기 표> <분할 폴더> --character <심기 표> <분할 폴더> \
#     --scores <score 출력...> --judged <judge 출력...> --split-seeds <분할 시드 파일>
# 개발 절반 미리보기 — 같은 판정 함수를 개발 문항에(봉인 없이). A0·A1·B1 밖 갈래가 든 쌍·효과는 개발 범위 밖으로 표시된다:
#   ... v4-preview --story <심기 표> <분할 폴더> --character <심기 표> <분할 폴더> \
#     --scores <score 출력...> --judged <judge 출력...> --split-seeds <분할 시드 파일>
