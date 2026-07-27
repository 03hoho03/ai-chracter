# 배포 런북 — 무료 티어 (Cloud Run + Neon + Upstash + R2 + Cloudflare Pages)

> 상태: 준비 단계. 스택은 확정(아래), 실제 프로비저닝/시크릿은 사용자 수작업.
> 근거·대안 분석은 옵시디언 노트 "AI 캐릭터 챗 - 추천 무료 배포 스택" 참고.

## 0. 확정 스택

| 컴포넌트 | 서비스 | 도메인(1차) |
|---|---|---|
| BE 컨테이너 (FastAPI) | **Google Cloud Run** | `https://<svc>-<hash>.run.app` |
| PostgreSQL | **Neon** | — |
| Redis (세션·인증코드·OAuth state·미리보기) | **Upstash** | `rediss://...` |
| 오브젝트 스토리지 (자산·생성 이미지) | **Cloudflare R2** | `https://<accountid>.r2.cloudflarestorage.com` |
| FE web / admin (정적 SPA) | **Cloudflare Pages** | `https://<proj>.pages.dev` |

**도메인 전략(1차): 각 서비스 무료 서브도메인.** 커스텀 도메인은 나중에. 이 선택이
아래 §4의 "크로스사이트 쿠키" 코드 변경을 **필수**로 만든다(BE와 FE 도메인이 다르기 때문).

---

## 배포 완료 상태 (2026-07-27 · 실제 값)

| 구성 | 값 |
|---|---|
| GCP 프로젝트 | `ai-character-chat-501906` (번호 612311629427) |
| 리전 | `asia-southeast1` (Neon 싱가포르와 co-locate) |
| Backend (Cloud Run) | `https://ai-character-chat-api-612311629427.asia-southeast1.run.app` |
| web (Pages) | `https://ai-character-chat-web.pages.dev` |
| admin (Pages) | `https://ai-character-chat-admin.pages.dev` |
| R2 버킷 | `ai-chracter-chat` (CORS: 두 pages.dev origin으로 제한) |
| Neon | main head `ec416a217f5d`까지 마이그레이션 적용 |

- env 주입: `gcloud ... --env-vars-file`(YAML). 소스는 로컬 `apps/api/.env`(gitignore), `.dockerignore`가 `.env` 제외.
- **남은 수동 작업**: Google OAuth redirect URI 등록 → `<Backend>/auth/google/callback`
- **알려진 한계**: 이메일 print 스텁(이메일 가입 미완, Google 로그인만 동작) · 이미지 생성 미배포(Ralph 진행 중, 병합 후 재배포)

---

## 1. 사전작업 — 계정 & 프로비저닝 (사용자 수작업)

### 1-1. Neon (PostgreSQL)
1. neon.tech 가입 → 프로젝트 생성 (region은 Cloud Run과 가까운 곳, 예: `ap-southeast-1`).
2. 연결 문자열 복사. Neon이 주는 형태: `postgresql://user:pass@ep-xxx.region.aws.neon.tech/dbname?sslmode=require`
3. **이 앱은 asyncpg를 쓰므로 두 가지를 손봐야 한다**:
   - 스킴: `postgresql://` → `postgresql+asyncpg://`
   - `?sslmode=require`(psycopg 문법)는 asyncpg가 이해 못 함 → 제거. SSL은 §4의 코드 변경으로 처리.
   - 최종 `DATABASE_URL` = `postgresql+asyncpg://user:pass@ep-xxx.region.aws.neon.tech/dbname`

### 1-2. Upstash (Redis)
1. upstash.com 가입 → Redis DB 생성 (Global 아님, 단일 region 무료로 충분).
2. **TLS 엔드포인트**(`rediss://...`) 복사 → `REDIS_URL`. (redis-py는 `rediss://` 스킴만으로 TLS 자동, 코드 변경 없음.)
3. 무료 한도: 월 command 수 상한 존재 — 저트래픽이면 충분하나 대시보드에서 사용량 모니터.

### 1-3. Cloudflare R2 (스토리지)
1. Cloudflare 가입 → R2 활성화 → 버킷 생성 (예: `ai-character-chat-assets`).
2. **R2 API 토큰** 발급 (Object Read & Write) → Access Key ID / Secret Access Key 확보.
3. 계정 ID 확인 → 엔드포인트 `https://<accountid>.r2.cloudflarestorage.com`.
4. **R2 버킷 CORS 설정(필수)** — presigned PUT 업로드가 브라우저 직접 PUT이라, CORS 없으면
   preflight에서 막힌다(코드 주석에도 "미해결 인프라 갭"으로 기록됨). 버킷 CORS policy 예:
   ```json
   [
     {
       "AllowedOrigins": ["https://<web>.pages.dev", "https://<admin>.pages.dev"],
       "AllowedMethods": ["GET", "PUT", "HEAD"],
       "AllowedHeaders": ["*"],
       "MaxAgeSeconds": 3600
     }
   ]
   ```
5. 주의: R2 무료 10GB. **생성 이미지(image-gen 기능)가 붙으면 여기부터 병목** — 용량 모니터.

### 1-4. Google Cloud (Cloud Run) + Gemini
1. Google Cloud 프로젝트 생성, billing 계정 연결(무료 한도 내 과금 0, 카드 등록은 필요).
2. `gcloud` CLI 설치 & 인증: 세션에서 `! gcloud auth login` 입력해 직접 로그인.
3. Cloud Run / Cloud Build API 활성화: `gcloud services enable run.googleapis.com cloudbuild.googleapis.com`
4. **Gemini API 키**: Google AI Studio(aistudio.google.com)에서 발급 → `GEMINI_API_KEY`.
   - 채팅·이미지 생성 **공용 키 1개**. 이미지 모델 `gemini-2.5-flash-image` 가용성 확인.

### 1-5. Google OAuth (로그인)
1. GCP 콘솔 → API & Services → Credentials → OAuth 2.0 Client ID (Web application).
2. **Authorized redirect URI** 추가: `https://<be>.run.app/auth/google/callback`
   - Cloud Run URL은 첫 배포 후에야 확정되므로, 1차 배포 → URL 확보 → 여기 등록 순서.
3. `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` 확보.

---

## 2. 시크릿 / 환경변수 레퍼런스

### 2-1. 백엔드 런타임 (Cloud Run env vars)

| 변수 | 값 | 비고 |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...?ssl=require` (Neon) | `sslmode`→`ssl`, 스킴 변환. §4-2 |
| `REDIS_URL` | `rediss://...` (Upstash) | TLS 자동 |
| `GEMINI_API_KEY` | AI Studio 키 | 채팅+이미지 공용 |
| `GEMINI_MODEL_NAME` | (기본 `gemini-2.5-flash`) | 보통 생략 |
| `GEMINI_IMAGE_MODEL_NAME` | (기본 `gemini-2.5-flash-image`) | image-gen 병합 후 유효 |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | OAuth 자격증명 | §1-5 |
| `API_BASE_URL` | `https://<be>.run.app` | OAuth redirect_uri 조립 |
| `FRONTEND_BASE_URL` | `https://<web>.pages.dev` | |
| `CORS_ALLOW_ORIGINS` | `["https://<web>.pages.dev","https://<admin>.pages.dev"]` | **JSON 배열 문자열**(pydantic `list[str]` 파싱) |
| `SESSION_COOKIE_SECURE` | `true` | HTTPS 필수 |
| `SESSION_COOKIE_SAMESITE` | `none` | §4 코드 변경 후 유효. 크로스도메인 필수 |
| `S3_ENDPOINT_URL` | `https://<accountid>.r2.cloudflarestorage.com` | R2 |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | R2 API 토큰 키쌍 | boto3가 프로세스 env로 읽음 |
| `AWS_REGION` | `auto` | R2 규약 |
| `S3_BUCKET_NAME` | R2 버킷명 | 기본값이 dev용이라 override 필수 |

> `CORS_ALLOW_ORIGINS` 함정: pydantic-settings는 `list[str]` 필드를 env에서 **JSON으로 파싱**한다.
> 반드시 `["https://a","https://b"]` 형태의 JSON 문자열로 넣을 것 (콤마 구분 평문 아님).

### 2-2. 프론트엔드 빌드타임 (Cloudflare Pages env)

| 변수 | 값 | 비고 |
|---|---|---|
| `VITE_API_BASE_URL` | `https://<be>.run.app` | **빌드 시 번들에 고정**. web·admin 각각 설정 |

> Vite env는 런타임이 아니라 빌드타임. BE URL이 바뀌면 FE를 재빌드해야 한다.

---

## 3. 배포 절차

### 3-1. BE → Cloud Run (Dockerfile 기반, 이미 `:8000` 준비됨)
```bash
cd apps/api
gcloud run deploy ai-character-chat-api \
  --source . \
  --region asia-northeast3 \
  --allow-unauthenticated \
  --port 8000 \
  --set-env-vars "DATABASE_URL=...,REDIS_URL=...,GEMINI_API_KEY=...,..." \
  # 시크릿류는 --set-env-vars 대신 Secret Manager + --set-secrets 권장
```
- `--source .`는 기존 `apps/api/Dockerfile`로 빌드 → Cloud Run 배포(Cloud Build 경유).
- 첫 배포 후 나온 `*.run.app` URL을 §1-5 OAuth redirect URI와 §2 `API_BASE_URL`/FE `VITE_API_BASE_URL`에 반영.
- 시크릿은 `--set-env-vars` 평문 대신 **Secret Manager**(`--set-secrets`)를 권장.

### 3-2. DB 마이그레이션 (Neon 대상, 최초 1회 + 스키마 변경 시)
```bash
cd apps/api
DATABASE_URL="postgresql+asyncpg://...neon..." uv run alembic upgrade head
```
- 로컬에서 Neon을 향해 실행하면 된다(별도 마이그레이션 잡 불필요).
- 시드가 필요하면 `scripts/`의 시드 스크립트를 같은 `DATABASE_URL`로.

### 3-3. FE → Cloudflare Pages (web, admin 각각)
- Pages 프로젝트 2개 생성(web, admin). 빌드 설정:
  - **Build command**: `pnpm install --frozen-lockfile && pnpm --filter @ai-character-chat/web build` (admin은 filter 교체)
  - **Build output directory**: `apps/web/dist` (admin은 `apps/admin/dist`)
  - **Root directory**: 저장소 루트 (모노레포)
  - **Env var**: `VITE_API_BASE_URL=https://<be>.run.app`
- SPA fallback: `apps/{web,admin}/public/_redirects`가 이미 추가됨(`/* /index.html 200`) → Vite가 `dist/`로 복사.

---

## 4. 필수 코드 변경 (승인 후 적용 — 아직 미적용)

무료 서브도메인 토폴로지(BE≠FE 도메인)에서 **없으면 로그인이 아예 동작 안 하는** 쿠키 변경 1개.
(DB SSL은 코드 변경 없이 `DATABASE_URL`의 `?ssl=require`로 해결됨 — 실연결 검증 완료, §4-2.)

### 4-1. 세션 쿠키 SameSite — 크로스사이트 필수 (⚠️ 보안 트레이드오프)
현재 `apps/api/src/api/session/cookies.py` / `admin/cookies.py`가 `samesite="lax"` **하드코딩**.
lax 쿠키는 크로스사이트 XHR(fetch)에 실리지 않아 `*.pages.dev` → `*.run.app` 로그인이 깨진다.

- **트레이드오프**: `SameSite=None`은 크로스사이트 요청에 쿠키를 실어보내므로 CSRF 표면이 넓어진다.
  단, `Secure`(HTTPS 전용) + `HttpOnly`는 유지되고, CORS `allow_origins`가 우리 FE 두 도메인으로
  고정돼 있어 실질 위험은 제한적. 커스텀 도메인(BE·FE를 같은 상위도메인으로)으로 가면 `lax`로 되돌릴 수 있다.
- **권장 패치**: `samesite`를 설정값으로 뽑아 dev는 `lax`, prod는 `none` 주입.
  ```python
  # config.py Settings에 추가
  session_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
  # cookies.py 두 곳: samesite="lax" → samesite=settings.session_cookie_samesite
  ```
  → prod env: `SESSION_COOKIE_SAMESITE=none`, `SESSION_COOKIE_SECURE=true`.

### 4-2. DB 엔진 SSL — env로 해결됨 (코드 변경 불필요, 검증 완료)
Neon은 SSL 필수지만, `DATABASE_URL`을 `postgresql+asyncpg://...?ssl=require`로 주면
`create_async_engine(settings.database_url)`가 그대로 SSL 연결한다(asyncpg가 URL 쿼리의 `ssl=require`를 해석).
→ 실제 Neon(PostgreSQL 18.4)에 `SELECT 1` 성공으로 확인, `db/session.py` 무변경.
- dev 로컬(`...@localhost`)은 `?ssl=require`가 없어 non-SSL 그대로 → 영향 없음.
- ⚠️ psycopg 문법 `?sslmode=require`는 asyncpg가 이해 못 한다 → 반드시 `?ssl=require`.

### 4-3. (완료) SPA fallback
`apps/{web,admin}/public/_redirects` 추가됨. 별도 작업 불필요.

---

## 5. 배포 후 스모크 검증
1. `GET https://<be>.run.app/health` → `{"status":"ok"}`
2. web에서 Google 로그인 → 세션 쿠키가 실제로 설정/전송되는지(개발자도구 Network, `Set-Cookie`/요청 Cookie).
3. 자산 업로드(presigned PUT) → R2 CORS 통과 확인.
4. 채팅 SSE 스트리밍 응답 수신.
5. admin 로그인(별도 쿠키 `admin_session_id`).

---

## 6. 알려진 갭 / 런칭 전 판단 필요

- **이메일 발송이 print 스텁**(`apps/api/src/api/core/email.py`). Google 로그인은 동작하지만
  **이메일/비밀번호 가입의 인증 코드가 실제로 발송되지 않는다** → 이메일 가입 경로는 사실상 미동작.
  실사용자를 받으려면 Resend 등 연동 필요(함수 본문만 교체). **런칭 블로커 여부는 로그인 정책에 따라 판단.**
- **`GET /me/generated-images`는 현재 빈 배열 스텁**(US-097). 실제 생성 이미지 조회는 image-gen 기능
  병합 후에야 동작 → 배포 env(`GEMINI_IMAGE_MODEL_NAME`)와 R2 용량 계획은 그 병합에 맞춰 갱신.
- **Cloud Run 요청 타임아웃**: SSE 채팅 응답은 짧아 무관하나, 장시간 스트림이 생기면 재확인.
- **Cloud Run 콜드스타트**: 0으로 스케일다운 → 첫 요청 수 초 지연. 필요 시 min-instances=1(무료 벗어남).

---

## 7. image-gen 병합 시 반영 체크
- `config.py`에 이미 있는 `gemini_image_model_name`이 실제 파이프라인에서 소비되는지 확인.
- 생성 이미지가 R2에 쌓이는 경로/키 규칙 → 용량 모니터 대상 추가.
- 새로 생기는 env(있다면)를 §2-1 표에 추가.
