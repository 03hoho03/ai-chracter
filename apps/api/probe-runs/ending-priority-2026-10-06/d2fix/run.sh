#!/bin/bash
# 「상영회까지」 설명 고침 스탯 판정 리플레이. 사용: run.sh dry|exec
# apps/api 에서 실행한다. 턴마다 현행 → A → B 를 붙여 부른다.
set -euo pipefail
MODE="$1"
RUN=probe-runs/ending-priority-2026-10-06
D=$RUN/d2fix
ROOM=6787bb78-c54d-4c65-966c-024e1dff0c74
TRACE=/Users/janghojeong/Projects/work/ai-chracter/apps/api/probe-runs/filmclub-longturn-2026-10-05/trace.jsonl
TOOL=scripts/experiments/filmclub_longturn/judgment_replay.py
if [ "$MODE" = exec ]; then OUTDIR=$D/replay; EXTRA=--execute; else OUTDIR=$D/dryrun; EXTRA=--limit-calls=3; fi
mkdir -p "$OUTDIR" "$D/prompts"

one() { # label start-args... -- extra-args...
  local label="$1"; shift
  for arm in current candA candB; do
    local out="$OUTDIR/$label-$arm.jsonl"
    if [ "$MODE" = exec ] && [ -e "$out" ]; then echo "이미 있음: $out — 새 이름을 쓴다"; exit 1; fi
    uv run --env-file .env python $TOOL --room $ROOM --kind stat --stat-format A \
      --stat-start-trace "$TRACE" --stat-override "$D/inputs/override-$arm.json" \
      --reps 3 --limit-calls 3 --limit-usd 0.5 --ledger "$D/replay/**/*.jsonl" \
      --prompt-out "$D/prompts/$label-$arm" --out "$out" "$@" "$EXTRA"
  done
}

S2=(--stat-start-set "도희 호감도=24" --stat-start-set "유나 호감도=20" --stat-start-set "세빈 호감도=20" --stat-start-set "상영회까지=46")
S3=(--stat-start-set "도희 호감도=26" --stat-start-set "유나 호감도=21" --stat-start-set "세빈 호감도=21" --stat-start-set "상영회까지=44")
one s2 --turn 2 --exchange-from $D/inputs/smoke-t2.json "${S2[@]}"
one s3 --turn 2 --exchange-from $D/inputs/smoke-t3.json "${S3[@]}"
one t008 --turn 8 --stat-start-set "상영회까지=46"
one t022 --turn 22 --stat-start-set "상영회까지=44"
one t038 --turn 38 --stat-start-set "상영회까지=41"
one t074 --turn 74 --stat-start-set "상영회까지=38"
one t088 --turn 88 --stat-start-set "상영회까지=35"
one t095 --turn 95 --stat-start-set "상영회까지=32"
one t105 --turn 105 --stat-start-set "상영회까지=8"
one t060 --turn 60 --stat-start-set "상영회까지=38"
one t061 --turn 61 --stat-start-set "상영회까지=38"
one t021 --turn 21 --stat-start-set "상영회까지=44"
