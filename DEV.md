# 로컬 개발 환경

늦은 밤 홈에서 Google 로그인 → 샘플 캐릭터 '미아'와 채팅까지, 로컬에서 굴리기 위한 최소 셋업.

## 사전 준비

- **Docker Desktop** 실행 중
- **Google OAuth 클라이언트**(Client ID/Secret) — Cloud Console에서 발급하고, **승인된 리디렉션 URI**에 아래를 정확히 등록:
  ```
  http://localhost:8000/auth/google/callback
  ```
- **Gemini API Key**

## 1) 한 번에 부트스트랩

```sh
./dev-up.sh
```

이게 하는 일: `docker-compose.dev.yml`(Postgres·Redis·moto S3 + 버킷/CORS 자동 생성) 기동 → 없으면 `.env` 생성 → `uv sync` → `alembic upgrade head` → 샘플 캐릭터 시드.

> 처음이라면 `apps/api/.env`를 열어 `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GEMINI_API_KEY`를 채운 뒤 `./dev-up.sh`를 한 번 더 실행하세요. (나머지 값 — DB/Redis/S3/AWS 더미 자격증명 — 은 로컬 기본값으로 이미 채워져 있습니다.)

## 2) 서버 기동 (각각 별도 터미널)

```sh
# API — 반드시 --env-file 로 실행해야 boto3가 AWS 더미 자격증명을 읽어 썸네일 URL을 서명한다
cd apps/api && uv run --env-file .env uvicorn api.main:app --reload --port 8000

# web
pnpm install && pnpm --filter @ai-character-chat/web dev   # http://localhost:5173

# (선택) admin — 채팅엔 불필요
pnpm --filter @ai-character-chat/admin dev                  # http://localhost:5174
```

## 3) 채팅

`http://localhost:5173` → Google 로그인 → 홈의 **'미아'** 카드 → 대화 시작.

- 이메일 회원가입은 실제 메일 발송이 없어(인증코드가 API stdout / Redis에 찍힘) 불편하니 **Google 로그인**을 권장.
- 시드된 크리에이터 계정(`seed-creator@example.com`)은 콘텐츠 소유자일 뿐 로그인용이 아닙니다.

## 구성 요소

| 서비스 | 포트 | 비고 |
|---|---|---|
| Postgres | 5432 | 볼륨(`pgdata`)으로 데이터 유지 |
| Redis | 6379 | 세션·이메일코드·미리보기세션(휘발성) |
| moto (S3 호환) | 5001 | **인메모리** — 컨테이너 재생성 시 업로드 객체 소실 (macOS 5000=AirPlay 회피) |
| API | 8000 | `uv run --env-file .env uvicorn ...` |
| web | 5173 | 기본 다크 |

## 트러블슈팅

- **썸네일이 깨져 보임(이미지 404)**: moto는 인메모리라 `docker compose down`/재생성 시 업로드된 이미지가 사라집니다. `uv run --env-file .env python apps/api/... ` 대신 루트에서 `./dev-up.sh`를 다시 돌리면(또는 `cd apps/api && uv run --env-file .env python scripts/seed_dev.py`) 재업로드됩니다. 채팅 자체는 이미지와 무관하게 동작합니다.
- **모든 화면 500 + `NoCredentialsError`**: API를 `--env-file .env` 없이 띄운 경우입니다. boto3가 자격증명을 못 찾은 것이니 위 명령대로 `--env-file .env`로 실행하세요.
- **Google 로그인 후 redirect_uri_mismatch**: Cloud Console 승인된 리디렉션 URI가 `http://localhost:8000/auth/google/callback`와 정확히 일치해야 합니다.
- **채팅 응답이 안 옴 / LLM 에러**: `.env`의 `GEMINI_API_KEY` 확인.
- **`pnpm typecheck`가 zod 등 이상한 에러**: 먼저 `pnpm install`(stale node_modules).
- **DB를 완전히 초기화하고 싶을 때**: `docker compose -f docker-compose.dev.yml down -v` 후 `./dev-up.sh`.
