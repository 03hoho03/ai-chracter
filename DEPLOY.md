# 배포 런북 — GCE VM (BE) + Cloudflare Pages (FE) + R2

> **상태: 2026-09-02 GCE 이전 완료.** BE는 `https://api.ddona.site`(서울 GCE VM)이고
> Cloud Run·Neon·Upstash는 **살아 있되 쓰이지 않는다**(§0-1). main push 자동배포는 §3-4.
>
> ⚠️ **§1·§2-1·§3-1·§7 등 "Cloud Run" 서술은 이전 전 기록이다** — 롤백·대조용으로 남겼다.
> 지금 프로덕션을 다루려면 §0-1과 §3-1을 볼 것.

## 0. 확정 스택

| 컴포넌트 | 서비스 | 주소 |
|---|---|---|
| BE (FastAPI + Postgres + Redis + Caddy) | **GCE VM** `ddona-api` (`asia-northeast3-a`, e2-medium) | `https://api.ddona.site` |
| PostgreSQL 18 | VM 컨테이너 (볼륨 `pgdata`) | 내부 전용 |
| Redis 8 | VM 컨테이너 (AOF, 볼륨 `redisdata`) | 내부 전용 |
| 오브젝트 스토리지 (자산·생성 이미지·**DB 백업**) | **Cloudflare R2** | `https://<accountid>.r2.cloudflarestorage.com` |
| FE web (정적 SPA) | **Cloudflare Pages** | `https://ddona.site` |
| FE admin (정적 SPA) | **Cloudflare Pages** | `https://admin.ddona.site` |

**FE도 `ddona.site`로 모였다(2026-09-02).** 존은 Cloudflare, 등록은 가비아 그대로다.
옛 `*.pages.dev`는 계속 살아 있고, web은 Worker가 새 도메인으로 넘긴다
(`apps/web/worker/legacyRedirect.ts` — 302로 배포해 실측한 뒤 **2026-09-02에 301로 승격**했다).
**admin의 옛 주소는 넘기지 않는다** — admin은 `_worker.js`가 없는 정적 SPA라 host 조건을 걸 자리가
없다(`_redirects`는 경로만 본다).

FE·BE가 같은 등록가능 도메인(`ddona.site`)에 모였으므로 `SESSION_COOKIE_SAMESITE`를
**`lax`로 되돌렸다(2026-09-02, 백로그 G-5 완료)** — §4-1.

### 0-1. GCE 이전 후 실제 값 (2026-09-02)

| 구성 | 값 |
|---|---|
| GCP 프로젝트 | `ddona-ai-character-chat` (번호 377499972563, 계정 `ghwjd321@gmail.com`) |
| VM | `ddona-api` / `asia-northeast3-a` / e2-medium / Ubuntu 24.04 / 30GB |
| 고정 IP | `34.64.43.39` (`ddona-api-ip`) |
| DNS | **Cloudflare**(2026-09-02 가비아에서 NS 이관, 등록기관은 가비아 그대로). `api` A → 위 IP, **DNS only(회색 구름)** |
| HTTPS | Caddy 자동 발급(Let's Encrypt). `Caddyfile`은 저장소 루트 |
| 이미지 저장소 | `asia-northeast3-docker.pkg.dev/ddona-ai-character-chat/ddona/api` |
| VM 상의 형상 | `/opt/ddona/app`(git checkout) · `/opt/ddona/.env`(0600) · **전부 root 소유** |
| 방화벽 | 80·443 공개 / 22는 IAP 대역(`35.235.240.0/20`)만 |
| 백업 | 매일 18:00 UTC → `s3://ai-chracter-chat/backup/daily/`, 7일 + 4주 보관 |

**옛 스택은 정리했다(2026-09-02).** Cloud Run 서비스 `ai-character-chat-api`와 옛 프로젝트의
Artifact Registry(`cloud-run-source-deploy`, 1.36GB)를 삭제했고, Neon·Upstash도 콘솔에서 지웠다.
Cloud Build 트리거 `ai-chat-deploy`는 비활성화 상태로 남아 있다(실행 대상이 없어 무해).

⚠️ **즉시 롤백 스위치는 이제 없다.** 삭제 전 최종본을 R2에 박아뒀고 그게 유일한 복구 경로다:
```
s3://ai-chracter-chat/backup/archive/neon-final-20260902.dump      # 29테이블 1,732행
s3://ai-chracter-chat/backup/archive/upstash-final-20260902.jsonl  # 세션 7키
```
`archive/` 는 **7일/4주 순환 대상이 아니다**(`backup_db.py` 의 prune 은 `daily/`·`weekly/` 만 본다).
복구는 "VM 재구축 → compose → 복원"이며 시간이 걸린다 — 상시 백업은 `backup/daily/` 쪽이다.

### 0-1-1. 이전 때 고른 것과 그 이유 (2026-09-02)

되짚을 일이 반드시 생기므로 남긴다. **결과가 아니라 근거**다 — 값이 궁금하면 §0-1을 본다.

| 갈림길 | 고른 것 | 근거 |
|---|---|---|
| HTTPS | **Caddy + 도메인** | Let's Encrypt 자동 갱신. Tailscale Funnel은 검증 단계용이라 최종형을 두 번 만들게 된다 |
| DB·Redis 위치 | **둘 다 VM 컨테이너** | 앱↔DB 네트워크 홉 0(전엔 서울↔싱가포르). 대가로 백업이 전적으로 우리 책임이 되어 **백업을 1단계로 앞당겼다** |
| **Redis 데이터** | **옮기지 않음** | 전부 TTL 있는 휘발성이고, 이관하면 버전 호환·TTL 보존 등 실패 지점이 늘어난다. 대가는 **컷오버 시 전원 로그아웃**(예정된 동작이지 버그가 아니다). 스냅샷만 R2에 남겼다 |
| 컷오버 | **짧은 계획 다운타임** | 쓰기 차단 → 최종 덤프 → 복원 순서라 **유실 창이 구조적으로 0**이다. 논리 복제는 이 규모에 과하다 |
| 배포 인증 | **Workload Identity Federation** | 원래 계획은 SA 키였는데 조직 정책이 키 발급을 막았다. 결과적으로 낫다 — **GitHub에 만료 없는 자격증명이 없다** |
| VM 파일 소유 | **root + sudo 배포** | OS Login은 접속 주체마다 POSIX 사용자가 달라, 사람 계정 소유로 두면 배포 SA가 git·docker·`.env` 셋 다 막힌다 |
| 백업 위치 | **자산 버킷의 `backup/`** | 기존 R2 토큰이 그 버킷 전용이라 새 토큰 없이 쓰려면 이 방법뿐. 대신 prune이 백업 파일명 형태에 **정확히** 맞는 것만 지우게 해 자산과 격리했다 |
| `/health` vs `/ready` | **둘 다 둔다** | `/health`는 얕아야 한다(Caddy·배포 검증이 의존). 자원 장애 감지는 `/ready`가 맡는다 |

**기각한 것**: Caddy `flush_interval -1`(있으나 없으나 SSE 도착 간격이 같아 근거가 성립하지 않았다) ·
전용 백업 버킷(토큰 비용 대비 이득이 작았고, CORS 우려는 애초에 틀린 근거였다 — R2 CORS는 읽기 권한을 주지 않는다).

### 0-2. 안 쓰는데 남아 있는 것

| 대상 | 상태 | 비고 |
|---|---|---|
| GCP 프로젝트 `ai-character-chat-501906` | 유지 | **Google OAuth 클라이언트가 여기 있다**(§1-5) — 지우면 로그인이 죽는다 |
| Cloud Build 트리거 `ai-chat-deploy` | 비활성화 | 대상이 사라져 무해. 되살리려면 §3-4의 PATCH 방법 |
| Cloudflare Pages web/admin | **현역** | 커스텀 도메인은 `ddona.site`/`admin.ddona.site`. 배포 대상은 그대로 Pages다 |

---

## 배포 완료 상태 (2026-08-04 · 실제 값)

| 구성 | 값 |
|---|---|
| GCP 프로젝트 | `ai-character-chat-501906` (번호 612311629427) |
| 리전 | `asia-southeast1` (Neon 싱가포르와 co-locate) |
| Backend (Cloud Run) | `https://ai-character-chat-api-612311629427.asia-southeast1.run.app` |
| web (Pages) | `https://ai-character-chat-web.pages.dev` |
| admin (Pages) | `https://ai-character-chat-admin.pages.dev` |
| R2 버킷 | `ai-chracter-chat` (CORS: 두 pages.dev origin으로 제한) |
| Neon | main head까지 마이그레이션 적용(image-gen `asset_kind=GENERATED` 포함) |
| GitHub | `github.com/03hoho03/ai-chracter` (public) |
| CI/CD | main push 시 경로별 자동배포 — §3-4 참고 |

- env 주입: `gcloud ... --env-vars-file`(YAML). 소스는 로컬 `apps/api/.env`(gitignore), `.dockerignore`가 `.env` 제외.
- **알려진 한계**: 이메일 print 스텁(이메일 가입 미완, Google 로그인만 동작) · 스테이징 환경 없음(즉시 롤백 + fix-forward 전략) · Pages 프리뷰 배포는 CORS 미허용이라 API 연동 확인 불가

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

> **현행 CORS 오리진은 `https://ddona.site` · `https://admin.ddona.site` 둘뿐이다**(2026-09-02
> 도메인 전환 후 옛 `*.pages.dev` 둘 제거). 확인·변경은 대시보드 없이도 된다:
> ```sh
> pnpm exec wrangler r2 bucket cors list ai-chracter-chat
> pnpm exec wrangler r2 bucket cors set ai-chracter-chat --file cors.json
> ```
> ⚠️ **wrangler의 파일 형식은 위 대시보드용 JSON과 다르다.** 공식 문서가 예시로 주는
> `[{"AllowedOrigins":…}]`(S3 스타일)을 넘기면 *"must contain a 'rules' array"* 로 거부된다.
> wrangler가 읽는 건 R2 API 형식이다(`cli.js`의 `rule.allowed?.origins` 접근으로 확인):
> ```json
> { "rules": [ { "allowed": { "origins": [...], "methods": [...], "headers": ["*"] },
>                "maxAgeSeconds": 3600 } ] }
> ```
> 거부될 때 기존 설정은 **건드리지 않는다**(실측) — 형식을 틀려도 CORS가 날아가지는 않는다.

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

### 2-1. 백엔드 런타임 env

**현행 위치는 VM의 `/opt/ddona/.env`(root 소유, 0600)이고 22개 키다** — 아래 17개 + compose용 5개
(`API_IMAGE`·`SITE_ADDRESS`·`POSTGRES_PASSWORD`·`POSTGRES_DB`·`DDONA_ENV_FILE`).
**GCE 이전(2026-09-02 오전)으로 셋**, **도메인 전환(같은 날 오후)으로 셋** 더 바뀌었다:

| 변수 | 이전 후 값 |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:…@postgres:5432/ai_character_chat` (VM 컨테이너) |
| `REDIS_URL` | `redis://redis:6379/0` (VM 컨테이너) |
| `API_BASE_URL` | `https://api.ddona.site` |
| `FRONTEND_BASE_URL` | `https://ddona.site` — 도메인 전환. OAuth 콜백 뒤 돌려보낼 목적지다(§8-5) |
| `CORS_ALLOW_ORIGINS` | `["https://ddona.site","https://admin.ddona.site"]` — 옛 `*.pages.dev` 둘은 컷오버 후 뺐다 |
| `SESSION_COOKIE_SAMESITE` | `lax` — §4-1 |

⚠️ **`apps/api/.env`는 로컬 개발용이다**(localhost DB/Redis + Tailscale 호스트). 예전에 이 문서가
"env 주입 소스는 로컬 `apps/api/.env`"라고 적었는데 **지금은 사실이 아니다** — 2026-09-02 확인.
Cloud Run 시절 값이 필요하면 `gcloud run services describe … --format=export`가 유일한 소스다.

아래 표는 **이전 전 Cloud Run 기준 원본**이다(값 자체는 대부분 그대로 쓰인다).

| 변수 | 값 | 비고 |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...?ssl=require` (Neon) | `sslmode`→`ssl`, 스킴 변환. §4-2 |
| `REDIS_URL` | `rediss://...` (Upstash) | TLS 자동 |
| `GEMINI_API_KEY` | AI Studio 키 | 채팅+이미지 공용 |
| `GEMINI_MODEL_NAME` | (기본 `gemini-2.5-flash`) | 보통 생략 |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | OAuth 자격증명 | §1-5 |
| `CLOUDFLARE_ACCOUNT_ID` | R2 엔드포인트 hex와 동일 | 이미지 생성(Workers AI). §7 |
| `CLOUDFLARE_API_TOKEN` | Workers AI 권한 토큰(R2 토큰과 별개) | 이미지 생성(Workers AI). §7 |
| `API_BASE_URL` | `https://<be>.run.app` | OAuth redirect_uri 조립 |
| `FRONTEND_BASE_URL` | `https://<web>.pages.dev` | |
| `CORS_ALLOW_ORIGINS` | `["https://<web>.pages.dev","https://<admin>.pages.dev"]` | **JSON 배열 문자열**(pydantic `list[str]` 파싱) |
| `SESSION_COOKIE_SECURE` | `true` | HTTPS 필수 |
| `SESSION_COOKIE_SAMESITE` | ~~`none`~~ → **현행 `lax`** | 2026-09-02 도메인 통합으로 되돌렸다(§4-1). 이 표의 나머지는 Cloud Run 시절 원본이다 |
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

> web에는 이것 말고 **Worker 런타임 변수**(`PUBLIC_ORIGIN`·`API_BASE_URL`)가 따로 필요하다 — §8-1.

---

## 3. 배포 절차

### 3-1. BE → GCE VM (현행)

**자동배포가 정상 경로다.** `main`에 push하면 `.github/workflows/deploy-api.yml`이 이미지 빌드 →
Artifact Registry push → IAP SSH로 VM 교체 → 인터넷 쪽 `/health` 확인까지 한다(실측 1분 35초).
GitHub Secrets에 넣는 값은 **없다** — Workload Identity Federation이라 키를 저장하지 않는다.

```sh
# VM 접속 (22번은 인터넷에 안 열려 있다)
gcloud compute ssh ddona-api --zone=asia-northeast3-a --tunnel-through-iap

# 스택 상태 · 로그
cd /opt/ddona/app
sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env ps
sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env logs -f api
```

**롤백**(실측 확인) — `.env`의 태그 한 줄을 되돌리고 다시 올린다:
```sh
sudo sed -i "s|^API_IMAGE=.*|API_IMAGE=asia-northeast3-docker.pkg.dev/ddona-ai-character-chat/ddona/api:<이전SHA>|" /opt/ddona/.env
sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env up -d --wait api
```
과거 태그는 `gcloud artifacts docker tags list asia-northeast3-docker.pkg.dev/ddona-ai-character-chat/ddona/api`로 본다.

**백업 · 복원**(둘 다 실제로 돌려본 절차다):
```sh
# 백업은 크론이 매일 돈다. 수동 실행:
sudo /opt/ddona/backup.sh

# 복원 — 대상 DB를 비우고 넣는다(restore_db 는 빈 DB 를 전제한다).
#   운영 DB 를 실수로 덮어쓰지 않도록 대상은 항상 명시적으로 만든다.
cd /opt/ddona/app
C="sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env"
$C stop api
$C exec -T postgres psql -U postgres -d postgres -c "DROP DATABASE ai_character_chat WITH (FORCE);"
$C exec -T postgres psql -U postgres -d postgres -c "CREATE DATABASE ai_character_chat;"
cd /opt/ddona/scripts
sudo TARGET_DATABASE_URL="$(sudo grep ^DATABASE_URL= /opt/ddona/.env | cut -d= -f2-)" \
     PG_DOCKER_NETWORK=ddona_default PYTHONPATH=. python3 -m ops.restore_db /경로/백업.dump
cd /opt/ddona/app && $C up -d --wait api
```
R2에서 백업을 내려받으려면 `aws s3 cp s3://ai-chracter-chat/backup/daily/<파일> .`
(`--endpoint-url`은 `S3_ENDPOINT_URL`).

⚠️ **`PG_DOCKER_NETWORK=ddona_default`가 없으면 안 된다** — 운영 Postgres는 포트를 게시하지
않으므로 기본 bridge로 뜬 `pg_dump`/`psql` 컨테이너에서 닿지 않는다.

---

### 3-1-old. BE → Cloud Run (이전 전 기록 · 롤백용)

**수동 배포**(로컬에서 즉시 재배포하고 싶을 때):
```bash
cd apps/api
gcloud run deploy ai-character-chat-api \
  --source . \
  --region asia-southeast1 \
  --allow-unauthenticated \
  --port 8000 \
  --no-cpu-throttling \
  --memory 512Mi \
  --cpu 1 \
  --max-instances 20
```
- `--source .`는 기존 `apps/api/Dockerfile`로 빌드 → Cloud Run 배포(Cloud Build 경유).
- **`--set-env-vars`를 생략하면 기존 리비전의 env vars/시크릿이 그대로 유지된다**(실증 완료) — 매번 전체 env를 다시 넣을 필요 없음. env를 실제로 바꿀 때만 `--update-env-vars KEY=VALUE`(부분 갱신) 또는 `--env-vars-file`(전체 교체)을 쓴다.
- 첫 배포 후 나온 `*.run.app` URL을 §1-5 OAuth redirect URI와 §2 `API_BASE_URL`/FE `VITE_API_BASE_URL`에 반영(이미 완료됨).
- `--no-cpu-throttling`은 필수(§7 참고 — 이미지 생성 백그라운드 잡이 CPU 스로틀링에 걸려 hang되는 문제 실증됨).

**자동 배포**는 main push로 트리거된다 — §3-4 참고. 수동 배포는 긴급 hotfix나 트리거 우회가 필요할 때만.

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

### 3-4. 자동 배포 (CI/CD, 2026-08-04 구축)

`main`에 push하면 변경된 경로에 해당하는 컴포넌트만 자동 재배포된다. 세 파이프라인 모두 GitHub Actions CI(`api.yml`/`web.yml`/`admin.yml`, typecheck·lint·test·build)와는 별개다 — CI는 품질 게이트, 아래는 배포 자체.

**BE — Cloud Build 트리거**
- Cloud Build 2nd-gen GitHub connection(`ai-chracter-github`, region=`asia-southeast1`) + 트리거 `ai-chat-deploy`
- 감지 경로(Included files filter): `apps/api/**`
- 빌드 레시피 `apps/api/cloudbuild.yaml`: docker build → Artifact Registry push(`cloud-run-source-deploy` repo, 태그=커밋 SHORT_SHA) → `gcloud run deploy --image=...`(env-vars 미지정이라 기존 설정 유지)
- 사전 조건: Secret Manager API 활성화, Cloud Build P4SA(`service-{num}@gcp-sa-cloudbuild...`)에 `roles/secretmanager.admin`, 레거시 Cloud Build SA(`{num}@cloudbuild.gserviceaccount.com`)에 `roles/run.developer` + `roles/iam.serviceAccountUser` + `roles/artifactregistry.writer`.
- **⚠️ `gcloud builds triggers create/update github`가 400(`INVALID_ARGUMENT`)** — **2026-09-02에 원인을 밝혔다**: 이 트리거는 **2세대**(`repositoryEventConfig` 필드, `github` 필드 없음)인데 그 CLI 경로는 1세대 `github` 필드를 가정한다. REST의 부분 PATCH(`?updateMask=disabled`)도 같은 이유로 실패한다. **전체 리소스를 updateMask 없이 PATCH하면 통과한다**:
  ```sh
  T=$(gcloud auth print-access-token); P=ai-character-chat-501906; R=asia-southeast1
  curl -s -H "Authorization: Bearer $T" \
    "https://cloudbuild.googleapis.com/v1/projects/$P/locations/$R/triggers/ai-chat-deploy" > t.json
  python3 -c "import json;d=json.load(open('t.json'));d['disabled']=True;[d.pop(k,None) for k in ('id','createTime','resourceName')];json.dump(d,open('t2.json','w'))"
  curl -s -X PATCH -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
    "https://cloudbuild.googleapis.com/v1/projects/$P/locations/$R/triggers/ai-chat-deploy" -d @t2.json
  ```
  Console UI로도 된다. **이 트리거는 현재 `disabled: true`다**(GCE 이전으로 대체됨, §0-1). Console에서 만든 트리거는 기본으로 `{project-num}-compute@developer.gserviceaccount.com`(Editor 롤)을 실행 SA로 씀 — 레거시 Cloud Build SA와 별개라 권한도 따로 부여해야 함.
- 수동 재실행: `gcloud builds triggers run ai-chat-deploy --branch=main --region=asia-southeast1`

**web/admin — Cloudflare Pages Git 연동**
- 각 프로젝트 Settings → Build → "Connect to a repository"로 사후 연결 가능(예전엔 Direct Upload 프로젝트는 불가능했으나 지금은 됨, 확인일 2026-08-04)
- Root directory는 **비워서 repo 루트 유지**(pnpm workspace 설치 때문에 필수) — Build output directory만 `apps/web/dist`/`apps/admin/dist`로 지정
- Build command: `pnpm install --frozen-lockfile && pnpm --filter @ai-character-chat/{web|admin} build`
- **Build watch paths 기본값이 `*`(전체 감시)** → `apps/{web|admin}/*, packages/*, pnpm-lock.yaml, pnpm-workspace.yaml`로 축소(그대로 두면 BE만 바뀌어도 FE가 재배포됨)
- **⚠️ Cloudflare의 와일드카드는 `*` **하나가 이미 `/`를 가로질러** 매칭한다("matches zero or more characters, including path separators"). `**`는 지원하지 않으므로 `apps/web/**`로 쓰면 아무것도 매칭되지 않아 **모든 푸시가 조용히 스킵된다**(Deployments 목록에 "No deployment available"로 표시). 2026-08-05에 실제로 이 상태였고, `apps/web` 변경 커밋 2개가 배포되지 않았다. 반드시 `*` 하나만 쓸 것.
- 스킵된 커밋을 뒤늦게 배포하려면 대시보드 Deployments에서 **Retry deployment** — watch paths를 고쳐도 과거 푸시가 소급 빌드되지는 않는다.
- `VITE_API_BASE_URL`을 Production + Preview 둘 다 plaintext variable로 등록

---

## 4. 필수 코드 변경 (승인 후 적용 — 아직 미적용)

무료 서브도메인 토폴로지(BE≠FE 도메인)에서 **없으면 로그인이 아예 동작 안 하는** 쿠키 변경 1개.
(DB SSL은 코드 변경 없이 `DATABASE_URL`의 `?ssl=require`로 해결됨 — 실연결 검증 완료, §4-2.)

### 4-1. 세션 쿠키 SameSite — **`lax`로 되돌렸다 (2026-09-02)**

**현재 프로덕션은 `SESSION_COOKIE_SAMESITE=lax`다.** FE가 `ddona.site`/`admin.ddona.site`로,
BE가 `api.ddona.site`로 **같은 등록가능 도메인**에 모여 크로스사이트가 아니게 됐다(백로그 G-5 완료).
아래는 그 전 기록이다.

되돌리며 실측한 것:
- **기존 로그인 사용자는 로그아웃되지 않는다** — 설정은 *새로 발급되는* 쿠키에만 걸리고, 브라우저에
  이미 있는 `SameSite=None` 쿠키는 same-site 요청에도 그대로 실린다(`/me` 200 확인).
- **새 로그인도 완주한다** — Google → `api.ddona.site/auth/google/callback`은 크로스사이트
  **최상위 GET 내비게이션**이라 `lax`가 쿠키 발급을 허용하고, 그 뒤 `ddona.site` → `api.ddona.site`
  XHR은 same-site라 쿠키가 실린다(로그아웃 → 재로그인 → `/me` 200 실측).
- OAuth state는 쿠키가 아니라 **Redis**에 있어(`store_oauth_state`) 크로스사이트 쿠키가 필요한
  지점이 애초에 없다.
- **코드 변경 0줄** — `session_cookie_samesite`가 이미 설정값이다. VM `.env` 한 줄 + 재기동뿐.

⚠️ 대가: **옛 `ai-character-chat-admin.pages.dev`에서는 로그인이 안 된다.** admin은 `_worker.js`가
없어 옛 주소를 리다이렉트할 자리가 없고, 거기서는 여전히 크로스사이트다. **의도된 결과**이며
`admin.ddona.site`를 쓴다.

---

**아래는 크로스사이트 시절 기록이다(2026-08-04, 롤백·대조용).**

당시 `apps/api/src/api/session/cookies.py` / `admin/cookies.py`가 `samesite="lax"` **하드코딩**이었다.
lax 쿠키는 크로스사이트 XHR(fetch)에 실리지 않아 `*.pages.dev` → `*.run.app` 로그인이 깨졌다.

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
- **스테이징 환경 없음**: main push → 바로 prod 자동배포(§3-4). 대신 Cloud Run 리비전/Pages 배포 둘 다 즉시 롤백 가능(트래픽 스위칭만, 재빌드 불필요) → 문제 발생 시 1순위는 롤백, fix는 그 다음.
- **Pages 프리뷰 배포는 API 연동 확인 불가**: BE `CORS_ALLOW_ORIGINS`가 prod 두 도메인만 허용해서 PR 프리뷰(랜덤 서브도메인)에서 API 호출이 CORS로 막힘. 필요해지면 CORS 완화.
- **Cloud Run 요청 타임아웃**: SSE 채팅 응답은 짧아 무관하나, 장시간 스트림이 생기면 재확인.
- **~~Cloud Run 콜드스타트~~ → 2026-09-02 GCE 이전으로 해소됐다.** 이전 후 `https://api.ddona.site/health`가 연속 5회 **0.134~0.141초로 균일**하다(Cloud Run 중앙값 6.9초). 아래는 그때의 진단 기록이며, 같은 방법이 다른 콜드스타트 조사에 재사용 가능하다.
- **(옛 기록) Cloud Run 콜드스타트**: min-instances가 0이라(minScale 어노테이션 없음) 트래픽이 뜸하면 20~30분 만에도 스케일다운되고, 하루에 여러 번 콜드스타트가 난다. 필요 시 min-instances=1(무료 벗어남 — `cpu-throttling=false`라 idle 시간도 전부 과금).
  - **비용은 이미지 pull이 아니라 `import api.main`에 있다**(2026-09-01 실측, 같은 이미지로 임시 probe 서비스를 띄워 컨테이너 진입 시각을 찍어 확인): 컨테이너 생성+pull은 **0.13~0.19초**뿐이고 나머지 전부가 python 부팅+import다. Cloud Run이 이미지를 **lazy loading으로 스트리밍**하기 때문에 pull 비용이 사라진 게 아니라 import가 실제로 읽는 파일에만, 그 시점에 네트워크 페치로 지불된다. **그래서 이미지 크기(353MB)를 깎는 건 효과가 없고, "import가 읽는 바이트/모듈 수"를 줄이는 것만 효과가 있다** — 같은 import가 로컬 1 vCPU 컨테이너(페이지캐시 있음)에선 1.6초, Cloud Run에선 11.6초였다.
  - 실측 개선: `google.genai`와 Pillow를 기동 경로에서 들어내(`llm/gemini_image.py` 분리 + `get_llm_client()`/`image_processing.py`/`cloudflare_image.py`의 함수 내 import) import가 읽는 양이 72.6MB/1534모듈 → 46.6MB/960모듈로 줄었고, 콜드스타트 중앙값이 **11.6초 → 6.9초**가 됐다(각 3회, 범위 10.5~14.2 → 6.0~7.0). 남은 몫은 sqlalchemy 12MB·asyncpg 10.5MB·pydantic_core 4.3MB로 전부 기동에 실제로 필요한 것들이다.
  - 진단이 다시 필요하면 이 방법을 재사용할 것: 프로덕션 이미지 그대로 `gcloud run deploy <probe> --command=sh --args='^|^-c|echo "[boot] container-entry"; exec uvicorn api.main:app --host 0.0.0.0 --port 8000'`로 비공개 probe 서비스를 띄우면, 로그의 `Starting new instance` → `[boot] container-entry` → `Started server process` 세 줄이 pull/import를 갈라준다. 리비전을 새로 올릴 때마다(`--update-env-vars`로 충분) 콜드스타트를 강제할 수 있다.

---

## 7. image-gen 병합 (완료, 2026-07-28)
main 병합 + 배포 완료. Gemini 이미지 모델은 무료 티어 quota 0이라 **Cloudflare Workers AI**(FLUX.1-schnell/SDXL)로 교체해서 씀 — `GEMINI_IMAGE_MODEL_NAME`은 더 이상 안 쓰임, `CLOUDFLARE_ACCOUNT_ID`/`CLOUDFLARE_API_TOKEN`이 대신 필요(§2-1에 추가함). 생성 이미지는 R2에 저장.

**2026-09-01 UI 차단 → 2026-09-02 해제.** Cloud Run의 request-based 과금(`--cpu-throttling`)에서는
응답 뒤 `asyncio.create_task`로 도는 생성 잡이 CPU 회수 구간에 걸려 `running`에 멈췄고, 그래서
프론트에서 버튼을 한시적으로 막았었다(`apps/web/.../generate-images/model/availability.ts`).
**GCE 이전으로 스로틀링이 사라져 잡이 완주하는 것을 실측 확인**(status `succeeded`, R2에 283KB
JPEG 저장)한 뒤 그 플래그 파일과 소비처 분기를 **삭제**했다 — 되돌릴 스위치가 아니라 없어진 문제다.

---

## 8. SEO 등록 (web 전용 · 2026-08-19)

web은 순수 클라이언트 SPA라 크롤러가 빈 `<head>`를 본다. `apps/web/worker/`(Pages Advanced Mode `dist/_worker.js`)가 **봇 UA에만** 완성된 `<head>`를 주입하고 `/sitemap.xml`·`/robots.txt`·`/og/*` 프록시를 만들어 준다. 코드가 배포돼도 **아래 등록을 하지 않으면 효과가 0이다.**

### 8-1. Pages 런타임 환경변수 (선행 조건, ⚠️ 빠지면 조용히 무효)

web 프로젝트 → Settings → Environment variables. **Production과 Preview 양쪽 모두** plaintext로 등록한다.

| 변수 | 값 | 없으면 |
|---|---|---|
| `PUBLIC_ORIGIN` | `https://ddona.site` | canonical·og:url·sitemap이 **요청 host를 따라간다** → 프리뷰 배포가 자기 URL로 색인되어 프로덕션과 중복 콘텐츠가 된다. **`legacyRedirect`의 목적지이기도 하다** — 비어 있으면 옛 도메인 리다이렉트가 통째로 꺼진다(자기 자신으로 가는 루프를 막는 가드다) |
| `API_BASE_URL` | `https://api.ddona.site` | Worker가 조회가 필요한 SEO 경로(상세·프로필 메타, sitemap, og 프록시)를 **통째로 건너뛴다**. 사이트는 멀쩡히 돌아서 티가 안 난다 |

- **`VITE_API_BASE_URL`(§2-2)과 별개다** — 저건 빌드타임에 번들에 박히는 값이고 이건 Worker가 런타임에 읽는다. **둘 다** 필요하다.
- **Preview에도 `PUBLIC_ORIGIN`은 프로덕션 오리진**을 넣는다(프리뷰 URL이 아니라). Worker는 `요청 host ≠ PUBLIC_ORIGIN host`일 때만 `X-Robots-Tag: noindex`를 붙이므로(`worker/indexing.ts`), Preview에서 비어 있으면 프리뷰 색인 차단이 함께 꺼진다.
- 런타임 변수는 **저장만으로 반영되지 않는다** — 저장 후 재배포(또는 Deployments → 최신 배포 Retry)해야 Worker가 읽는다.

**반영 확인**(재배포 후):

> ⚠️ **`robots.txt`에는 캐시버스터를 붙여야 한다.** `handleRobots`는 캐시 헤더를 안 붙이는데
> (`worker/robots.ts`) **Cloudflare 엣지가 `.txt`를 기본 4시간 캐시한다**(실측
> `cf-cache-status: HIT` / `cache-control: max-age=14400`). 그냥 `curl`하면 환경변수 교체 **전**
> 값이 나와 **검증이 거짓말을 한다** — 2026-09-02 도메인 전환 때 실제로 이걸로 오진했다.
> 아래처럼 `?cb=$RANDOM`을 붙이거나 Caching → Configuration → Purge Everything을 먼저 누른다.

```bash
ORIGIN=https://ddona.site
curl -s "$ORIGIN/robots.txt?cb=$RANDOM" | tail -2             # Sitemap: $ORIGIN/sitemap.xml
curl -s $ORIGIN/sitemap.xml | grep -c "<loc>"                 # 1 이상
curl -s -A "Googlebot/2.1" $ORIGIN/ | grep -c 'rel="canonical"'   # 1 (PUBLIC_ORIGIN 확인)
curl -s -A "Googlebot/2.1" $ORIGIN/content/character/<id> | grep -o "<title>.*</title>"   # 캐릭터 이름 (API_BASE_URL 확인)
```
상세 `<title>`이 홈 문구(`또나 — AI 캐릭터 챗`) 그대로면 `API_BASE_URL`이 안 들어갔거나 재배포를 안 한 것이다.

### 8-2. 구글 서치콘솔

1. **속성 추가** — [search.google.com/search-console](https://search.google.com/search-console) → 속성 추가 → **URL 접두어**에 `https://ai-character-chat-web.pages.dev` (`pages.dev`는 DNS를 우리가 못 만지므로 도메인 속성은 불가)
2. **소유권 확인 — HTML 태그** — 발급된 `<meta name="google-site-verification" content="..." />`를 `apps/web/index.html`의 `<head>`에 넣고 커밋 → main push로 배포된 뒤 "확인" 클릭
   - **봇 요청에서도 이 태그는 살아남는다** — `injectHead`(`worker/html.ts`)는 자기가 주입하는 키(title·description·og:*·canonical·robots)와 같은 키의 태그만 지우고 `name:google-site-verification`은 건드리지 않는다. 확인용 fetch는 `Google-Site-Verification` UA라 애초에 봇 분기에도 안 걸린다.
   - ⚠️ **HTML 파일 업로드 방식은 `apps/web/public/`에 커밋해도 동작하지 않는다.** 이 문서가 오랫동안 "확장자가 있어 정적 자산으로 나간다"고 적어 뒀는데 **틀렸다**(2026-09-02 실측). `dist/`까지는 복사되지만 Pages 자산 서버가 클린 URL 정책으로 `/foo.html` → `/foo`를 **308**로 돌려주고(`env.ASSETS.fetch()`가 그 308을 그대로 준다), 확장자가 사라진 경로는 `KNOWN_ROUTES`에 없어 우리 Worker가 **404**를 준다. 검증기는 `.html` URL을 치므로 실패한다. **파일 방식이 필요하면 `worker/siteVerification.ts`에 경로와 본문을 등록한다**(자산 검사보다 앞에서 Worker가 직접 응답한다).
3. **sitemap 제출** — 색인 생성 → Sitemaps → `sitemap.xml` 입력 후 제출
4. **URL 검사로 캐릭터 페이지 1개 색인 요청** — 캐릭터 상세 URL(`/content/character/{id}`) 하나를 URL 검사 → **게재된 URL 테스트** → **테스트한 페이지 보기 → HTML**에서 `<title>`에 캐릭터 이름이 들어갔는지 확인한 뒤 "색인 생성 요청". 순서가 중요하다 — "색인 생성 요청"은 구글이 이미 가진 버전을 쓰고, 라이브 HTML을 새로 가져오는 건 "게재된 URL 테스트"뿐이다.
   - **이 라이브 테스트는 `Googlebot`이 아니라 `Google-InspectionTool` UA로 온다**(리치 결과 테스트도 같다). `worker/crawler.ts`의 토큰 목록에 `google-inspectiontool`이 들어 있어야 주입된 HTML이 보인다 — 빠뜨리면 **실제 색인은 멀쩡한데 확인 도구에서만 주입 전 HTML이 보여** 기능이 고장난 것처럼 읽힌다(2026-08-20에 실제로 겪음).

### 8-3. 네이버 서치어드바이저

1. **사이트 등록** — [searchadvisor.naver.com](https://searchadvisor.naver.com) → 웹마스터 도구 → 사이트 등록에 `https://ai-character-chat-web.pages.dev`
2. **소유권 확인 — HTML 태그** — `<meta name="naver-site-verification" content="..." />`를 §8-2와 같은 자리(`apps/web/index.html`)에 넣고 배포 후 확인
3. **사이트맵 제출** — 요청 → 사이트맵 제출에 `https://ai-character-chat-web.pages.dev/sitemap.xml`
- 네이버 Yeti는 JS 렌더링이 제한적이라 **봇 메타 주입이 네이버에서는 색인 가부를 직접 가른다**(구글은 JS를 실행하므로 주입은 속도·정확도 문제에 가깝다). 등록 후 "요청 → 웹 페이지 수집"으로 캐릭터 페이지 1개를 넣어 수집 결과 title을 확인할 것.

### 8-4. admin 색인 차단

`apps/admin/public/robots.txt`(`User-agent: *` / `Disallow: /`)가 Vite 빌드로 `apps/admin/dist/`에 복사된다. **admin은 별도 Pages 프로젝트라 web의 robots.txt(Worker가 생성)와 무관하다** — web 쪽을 고쳐도 admin에는 아무 영향이 없다. admin은 서치콘솔·서치어드바이저에 등록하지 않는다.

### 8-5. 커스텀 도메인 전환 체크리스트

**2026-09-02에 `ddona.site`로 실행했다.** 진행 상태와 남은 절차는
`tasks/plan-domain-cutover-ddona.md` / `tasks/preview-progress.md`에 있고, 여기에는 **다시 하게 될 때
알아야 할 것**만 남긴다.

1. **DNS: apex를 쓰려면 NS 이관이 사실상 필수다.** Pages의 apex 커스텀 도메인은 존이 Cloudflare에
   있어야 붙고, 가비아 DNS는 apex CNAME/ALIAS를 주지 않는다. 도메인 등록기관은 가비아 그대로 두는
   **NS 이관**이면 되고 무료다(레지스트라 이전이 아니다).
   - ⚠️ **NS를 옮기기 전에 Cloudflare 존에 `api` A 레코드를 먼저 만든다.** 양쪽 NS가 같은 답을 하게
     해 두면 전환 순간에 BE가 안 끊긴다. 순서를 뒤집으면 NXDOMAIN 구간이 생긴다.
   - ⚠️ **구름 색이 레코드마다 다르다**: `api`는 **회색(DNS only)** — 주황이면 ACME 챌린지가 막혀
     Caddy 인증서 **갱신**이 실패한다(발급된 인증서가 살아 있어 **두 달 뒤에** 죽는다).
     apex·`www`·`admin`은 Pages가 만드는 **주황**이 정답이다.
   - 프록시 상태는 대시보드 표시가 아니라 **응답으로 확인한다** — `api`가 Cloudflare 애니캐스트
     IP(`104.x`/`172.67.x`)가 아니라 VM 고정 IP를 그대로 답하면 회색이다.
2. `PUBLIC_ORIGIN`을 새 도메인으로 교체(**Production·Preview 양쪽**) → **재배포**(저장만으로는 반영 안 됨).
3. **`apps/web/index.html`의 `og:image` 절대 URL 교체** — 홈 og:image만 하드코딩이다(상세·프로필은
   Worker가 `PUBLIC_ORIGIN`으로 만든다). 빠뜨리면 홈 공유 미리보기만 옛 도메인을 가리킨 채 남는다.
4. BE `CORS_ALLOW_ORIGINS`(§2-1)와 R2 CORS(§1-3)에 새 오리진 **추가**(옛 것은 컷오버가 끝날 때까지
   유지), BE `FRONTEND_BASE_URL`을 새 도메인으로 **교체**.
   - ⚠️ **Google OAuth 콘솔은 손대지 않는다.** 이 문서가 오랫동안 "OAuth redirect URI에 새 도메인을
     추가하지 않으면 로그인이 죽는다"고 적어 뒀는데 **근거가 틀렸다** — `redirect_uri`는
     `api_base_url`에서만 만들어지고(`auth/google_oauth.py`의 `callback_redirect_uri`), FE는 Google에
     직접 요청하지 않으므로 Authorized JavaScript origins도 필요 없다. **FE 도메인은 OAuth 설정에
     등장하지 않는다.** 실제로 바꿔야 하는 건 콜백 뒤 되돌려보낼 목적지인 `FRONTEND_BASE_URL`이다.
   - 검증은 **허용되면 안 되는 오리진까지 함께** 쏜다. 네 오리진 전부 통과했다는 것만으로는
     검사가 판별하는지 알 수 없다(대조군이 헤더를 못 받아야 비로소 증거가 된다).
5. **옛 `*.pages.dev` → 새 도메인 리다이렉트는 web Worker가 한다**(`worker/legacyRedirect.ts`).
   커스텀 도메인을 붙여도 `*.pages.dev`는 계속 살아 있고, 이력서에 낸 링크가 그것이다.
   - ⚠️ **프로덕션 host 정확 일치로만 건다.** `endsWith`/`includes`는 프리뷰
     (`<hash>.…pages.dev`)와 브랜치 별칭까지 날려 PR에서 변경분을 볼 수 없게 만든다.
   - ⚠️ 목적지는 `env.PUBLIC_ORIGIN`을 **직접** 읽는다. `resolvePublicOrigin()`은 값이 없을 때
     요청 오리진으로 폴백하므로 쓰면 **자기 자신으로 가는 무한 루프**가 된다.
   - **302로 먼저 배포하고(`Cache-Control: no-store` 동반) 실측한 뒤 301로 올린다.** 301은 브라우저가
     오래 캐시해 되돌릴 수 없고, no-store가 302 단계의 되돌림 가능성을 가정이 아니라 사실로 만든다.
   - **admin은 리다이렉트할 자리가 없다** — `_worker.js`가 없는 정적 SPA이고 `_redirects`는 host를
     못 본다. 옛 admin 주소는 그대로 남고, `SameSite=lax`로 되돌린 뒤에는 거기서 로그인이 안 된다
     (의도된 결과다).
6. 서치콘솔 **새 속성 추가** → 옛 속성에서 **설정 → 주소 변경**. 주소 변경 도구는 **301**을 요구하므로
   5의 승격 뒤에 한다. sitemap 재제출 + 네이버 새 사이트 등록·사이트맵 재제출.
   - ⚠️ **소유확인 태그를 `index.html`에 하나 더 넣지 말 것.** 같은 `name`의 meta가 둘이 되면 크롤러
     대부분이 앞의 것만 읽어 **새 속성 확인이 조용히 실패한다**. 구글은 DNS를 이제 우리가 통제하므로
     **도메인 속성 + DNS TXT**로 확인하면 하위 URL 접두어 속성이 자동 확인된다. 네이버는 DNS 확인이
     없으므로 **HTML 파일 업로드**(`apps/web/public/`에 커밋)를 쓴다 — 파일명이 달라 충돌하지 않는다.
     기존 태그는 **지우지 않는다**(옛 속성이 이전 기간 동안 살아 있어야 한다).
7. FE·BE가 같은 등록가능 도메인에 모였으므로 `SESSION_COOKIE_SAMESITE`를 `lax`로 되돌린다(§4).
   **코드 변경 0줄** — VM env만 바꾸고 재기동한다. 옛 도메인들이 정리된 **뒤에** 한다.
8. 확인: `curl -s "https://<새도메인>/robots.txt?cb=$RANDOM"`의 `Sitemap:` 줄과
   `curl -s -A "Googlebot/2.1" https://<새도메인>/ | grep canonical`이 둘 다 새 도메인이어야 한다
   (캐시버스터를 빼면 안 되는 이유는 §8-1).
