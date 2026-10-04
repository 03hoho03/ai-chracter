#!/usr/bin/env bash
# 로컬 개발 환경 부트스트랩: 인프라 기동 → DB 마이그레이션 → 샘플 데이터 시드.
# 서버(API/web)는 마지막에 안내하는 명령으로 각각 띄운다.
#
#   ./dev-up.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# 있는 env 파일(apps/api/.env, apps/web/.env.local, apps/admin/.env.local)의 형식을 먼저 본다. 파서마다 다르게
# 읽는 표기(따옴표·$·공백·값 없는 KEY= 등)는 아무 에러 없이 다른 값으로 뜨므로, 손대기 전에 멈춘다.
# 위반은 줄 번호와 규칙 이름만 찍힌다(값은 찍지 않는다).
echo "▶ 0/4 env 파일 형식 검사..."
python3 ops/check_env.py --dev || {
  echo "✖ 위 줄을 고친 뒤 다시 실행하세요 (규칙: DEV.md 의 \"env 파일 형식\" 절)" >&2
  exit 1
}

echo "▶ 1/4 인프라(Postgres·Redis·moto S3) 기동..."
docker compose -f docker-compose.dev.yml up -d --wait

cd apps/api

if [ ! -f .env ]; then
  echo "▶ .env 없음 → .env.example 복사 (GOOGLE_*/GEMINI_API_KEY 주석을 풀고 채워야 로그인·채팅 가능)"
  cp .env.example .env
fi

# 기존 .env 에 로컬 S3/AWS 기본값이 없으면 누락된 키만 덧붙인다(기존 값은 절대 건드리지 않음).
# 덧붙이는 줄도 위 형식 규칙을 지킨다 — 따옴표·공백 없는 값, 파일 끝 개행.
NEED_ENV=""
grep -q "^S3_ENDPOINT_URL=" .env       || NEED_ENV="${NEED_ENV}S3_ENDPOINT_URL=http://localhost:5001\n"
grep -q "^AWS_ACCESS_KEY_ID=" .env     || NEED_ENV="${NEED_ENV}AWS_ACCESS_KEY_ID=testing\n"
grep -q "^AWS_SECRET_ACCESS_KEY=" .env || NEED_ENV="${NEED_ENV}AWS_SECRET_ACCESS_KEY=testing\n"
grep -q "^AWS_REGION=" .env            || NEED_ENV="${NEED_ENV}AWS_REGION=ap-northeast-2\n"
if [ -n "$NEED_ENV" ]; then
  echo "▶ .env 에 누락된 로컬 S3/AWS 기본값 추가"
  printf "\n# --- dev-up.sh 자동 추가 (로컬 moto/AWS) ---\n%b" "$NEED_ENV" >> .env
fi

echo "▶ 2/4 파이썬 의존성 동기화..."
uv sync --quiet

echo "▶ 3/4 DB 마이그레이션..."
uv run alembic upgrade head

echo "▶ 4/4 샘플 캐릭터 시드..."
uv run --env-file .env python scripts/seed_dev.py

cat <<'EOF'

✅ 준비 완료. 이제 서버 두 개를 각각 띄우세요:

  # API — 반드시 --env-file 로 실행(썸네일 서명에 AWS 자격증명 필요)
  cd apps/api && uv run --env-file .env uvicorn api.main:app --reload --port 8000

  # web
  pnpm install && pnpm --filter @ai-character-chat/web dev

그다음 http://localhost:5173 → Google 로그인 → 홈의 '미아' 캐릭터로 채팅.

⚠ 사전 확인:
  - apps/api/.env 의 GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GEMINI_API_KEY 주석을 풀고 채웠는지
  - Google Cloud Console '승인된 리디렉션 URI' 에 http://localhost:8000/auth/google/callback 등록했는지
EOF
