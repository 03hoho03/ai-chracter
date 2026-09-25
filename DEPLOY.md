# 배포 런북 — GCE VM (BE) + Cloudflare Pages (FE) + R2

> **현행 스택만 적는다.** Cloud Run · Neon · Upstash 시절 기록은 2026-09-07에 걷어냈다
> (그 인프라는 2026-09-02에 삭제됐다). 옛 서술이 필요하면 git 이력에 있다.

## 0. 스택

| 컴포넌트 | 서비스 | 주소 |
|---|---|---|
| BE (FastAPI + Postgres + Redis + Caddy) | **GCE VM** `ddona-api` (`asia-northeast3-a`, e2-medium) | `https://api.ddona.site` |
| PostgreSQL 18 | VM 컨테이너 (볼륨 `pgdata`) | 내부 전용 |
| Redis 8 | VM 컨테이너 (AOF, 볼륨 `redisdata`) | 내부 전용 |
| 오브젝트 스토리지 (자산·생성 이미지·**DB 백업**) | **Cloudflare R2** 버킷 `ai-chracter-chat` | `https://<accountid>.r2.cloudflarestorage.com` |
| FE web (정적 SPA + Worker) | **Cloudflare Pages** | `https://ddona.site` |
| FE admin (정적 SPA) | **Cloudflare Pages** | `https://admin.ddona.site` |

FE·BE가 같은 등록가능 도메인(`ddona.site`)에 있다 — 그래서 세션 쿠키가 `SameSite=lax`다("BE 런타임" 절).
옛 `*.pages.dev` 주소는 계속 살아 있고 web은 Worker가 301로 넘긴다
(`apps/web/worker/legacyRedirect.ts`). **admin의 옛 주소는 넘기지 않는다** — admin은 `_worker.js`가
없는 정적 SPA라 host 조건을 걸 자리가 없고(`_redirects`는 경로만 본다), `lax` 쿠키라 거기서는
로그인도 안 된다. 의도된 결과이며 `admin.ddona.site`를 쓴다.

### 0-1. 실제 값

| 구성 | 값 |
|---|---|
| GCP 프로젝트 | `ddona-ai-character-chat` (번호 377499972563, 계정 `ghwjd321@gmail.com`) |
| VM | `ddona-api` / `asia-northeast3-a` / e2-medium / Ubuntu 24.04 / 30GB |
| 고정 IP | `34.64.43.39` (`ddona-api-ip`) |
| DNS | **Cloudflare**(등록기관은 가비아, NS만 이관). `api` A → 위 IP, **DNS only(회색 구름)** |
| HTTPS | Caddy 자동 발급(Let's Encrypt). `Caddyfile`은 저장소 루트 |
| 이미지 저장소 | `asia-northeast3-docker.pkg.dev/ddona-ai-character-chat/ddona/api` (태그=커밋 SHA 7자리) |
| VM 상의 형상 | `/opt/ddona/app`(git checkout) · `/opt/ddona/.env`(0600) · **전부 root 소유** |
| 방화벽 | 80·443 공개 / 22는 IAP 대역(`35.235.240.0/20`)만 |
| 백업 | 매일 18:00 UTC → `s3://ai-chracter-chat/backup/daily/`, 7일 + 4주 보관 ("백업 · 복원" 절) |

⚠️ **`api` 레코드의 구름은 반드시 회색이다.** 주황(프록시)이면 ACME 챌린지가 막혀 Caddy 인증서
**갱신**이 실패한다 — 발급된 인증서가 살아 있어 **두 달 뒤에** 죽는다. apex·`www`·`admin`은 Pages가
만드는 **주황**이 정답이다. 프록시 상태는 대시보드 표시가 아니라 응답으로 확인한다: `api`가
Cloudflare 애니캐스트 IP(`104.x`/`172.67.x`)가 아니라 VM 고정 IP를 그대로 답하면 회색이다.

### 0-2. 현재 형상의 근거

되짚을 일이 반드시 생기므로 남긴다. **결과가 아니라 근거**다 — 값은 "실제 값" 절을 본다.

| 갈림길 | 고른 것 | 근거 |
|---|---|---|
| HTTPS | **Caddy + 도메인** | Let's Encrypt 자동 갱신. Tailscale Funnel은 검증 단계용이라 최종형을 두 번 만들게 된다 |
| DB·Redis 위치 | **둘 다 VM 컨테이너** | 앱↔DB 네트워크 홉 0. 대가로 백업이 전적으로 우리 책임이라 **백업을 1단계로 앞당겼다** |
| 배포 인증 | **Workload Identity Federation** | 조직 정책이 SA 키 발급을 막는다(`iam.disableServiceAccountKeyCreation`). 결과적으로 낫다 — **GitHub에 만료 없는 자격증명이 없다** |
| VM 파일 소유 | **root + sudo 배포** | OS Login은 접속 주체마다 POSIX 사용자가 달라, 사람 계정 소유로 두면 배포 SA가 git·docker·`.env` 셋 다 막힌다 |
| 백업 위치 | **자산 버킷의 `backup/`** | 기존 R2 토큰이 그 버킷 전용이라 새 토큰 없이 쓰려면 이 방법뿐. 대신 prune이 백업 파일명 형태에 **정확히** 맞는 것만 지우게 해 자산과 격리했다 |
| `/health` vs `/ready` | **둘 다 둔다** | `/health`는 얕아야 한다(Caddy·compose healthcheck·배포 검증이 의존). 자원 장애 감지는 `/ready`가 맡는다 |
| 이미지 생성 → 집 PC 경로 | **Cloudflare Tunnel + Access 서비스 토큰** | VM에 데몬·컨테이너 네트워크 변경·키 로테이션이 필요 없다. 세마포어("이미지 생성" 절)가 매 HTTP 호출을 생성 1건으로 묶어 두므로 엣지 요청 제한에 다가가지 않는다. 체크포인트 스왑을 도입하면 그 전제가 깨져 Tailscale로 돌아간다 |

**기각한 것**: Caddy `flush_interval -1` — 있으나 없으나 SSE 도착 간격이 같았다(300ms 간격 5개 실측:
0.28/0.58/0.89/1.19s vs 0.30/0.60/0.91/1.21s). Caddy 2가 `text/event-stream`을 감지해 자동 flush 한다.
언젠가 스트리밍이 뭉쳐 도착하면 그때 `Caddyfile`에 넣어 본다. · 전용 백업 버킷(토큰 비용 대비 이득이
작았다 — R2 CORS는 읽기 권한을 주지 않으므로 자산 노출 우려는 애초에 틀린 근거였다).

### 0-3. 안 쓰는데 남아 있는 것

| 대상 | 상태 | 비고 |
|---|---|---|
| GCP 프로젝트 `ai-character-chat-501906` | 유지 | **Google OAuth 클라이언트가 여기 있다**("Google OAuth" 절) — 지우면 로그인이 죽는다 |
| `apps/api/cloudbuild.yaml` · `apps/api/scripts/ops/cloudrun_to_dotenv.py` | 사문 | Cloud Run 시절 산물. 실행 대상이 없다 |
| Cloud Build 트리거 `ai-chat-deploy`(옛 프로젝트) | 비활성화 | 대상이 사라져 무해 |
| R2 `backup/archive/` | 유지 | 이전 직전 최종본(`neon-final-20260902.dump`·`upstash-final-20260902.jsonl`). **prune 대상이 아니다** — `backup_db.py`는 `daily/`·`weekly/`만 본다 |

---

## 1. 외부 서비스

### 1-1. Cloudflare R2

버킷 `ai-chracter-chat` 하나에 자산·생성 이미지·DB 백업이 전부 산다. R2 API 토큰(Object Read &
Write) 키쌍이 `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`로 들어간다.

**CORS는 필수다** — 자산 업로드가 브라우저에서 R2로 직접 PUT(presigned)이라 없으면 preflight에서
막힌다. **현행 허용 오리진은 `https://ddona.site` · `https://admin.ddona.site` 둘뿐이다.**

```sh
pnpm exec wrangler r2 bucket cors list ai-chracter-chat
pnpm exec wrangler r2 bucket cors set ai-chracter-chat --file cors.json
```

⚠️ **wrangler의 파일 형식은 대시보드용 JSON과 다르다.** 공식 문서가 예시로 주는
`[{"AllowedOrigins":…}]`(S3 스타일)을 넘기면 *"must contain a 'rules' array"*로 거부된다. wrangler가
읽는 건 R2 API 형식이다(`cli.js`의 `rule.allowed?.origins` 접근으로 확인):

```json
{ "rules": [ { "allowed": { "origins": ["https://ddona.site", "https://admin.ddona.site"],
                            "methods": ["GET", "PUT", "HEAD"], "headers": ["*"] },
              "maxAgeSeconds": 3600 } ] }
```

형식이 틀려 거부돼도 **기존 설정은 건드리지 않는다**(실측) — CORS가 날아가지는 않는다.
R2 무료 한도는 10GB이고 **생성 이미지가 여기부터 병목**이다 — 용량 모니터.

### 1-2. Gemini

Google AI Studio에서 발급한 키 1개(`GEMINI_API_KEY`)를 채팅에 쓴다. 이미지 생성은 Gemini가 아니라
집 PC의 자가 호스팅 추론 서버다 — "이미지 생성" 절.

### 1-3. Google OAuth (로그인)

옛 GCP 프로젝트 `ai-character-chat-501906`의 OAuth 2.0 Client ID(Web application)를 그대로 쓴다.

- **Authorized redirect URI**: `https://api.ddona.site/auth/google/callback`
- ⚠️ **FE 도메인은 OAuth 설정에 등장하지 않는다.** `redirect_uri`는 `api_base_url`에서만 조립되고
  (`auth/google_oauth.py`의 `callback_redirect_uri`), FE는 Google에 직접 요청하지 않으므로 Authorized
  JavaScript origins도 필요 없다. FE 도메인이 바뀔 때 실제로 고칠 값은 콜백 뒤 돌려보낼 목적지인
  `FRONTEND_BASE_URL`이다.
- OAuth state는 쿠키가 아니라 **Redis**에 있다(`store_oauth_state`).

---

## 2. 환경변수

### 2-1. BE 런타임 — VM의 `/opt/ddona/.env` (root, 0600)

**39개 키다**(2026-09-25 VM 실측, 키 이름만 셈): 아래 표 25개(생략 가능한 `LOCAL_IMAGE_TIMEOUT_SECONDS`·
`LOCAL_IMAGE_CAPABILITIES_TTL_SECONDS`·`LOCAL_IMAGE_QUEUE_LIMIT`·`EXPOSE_API_DOCS` 4개 제외) + compose용
5개(`API_IMAGE`·`SITE_ADDRESS`·`POSTGRES_PASSWORD`·`POSTGRES_DB`·`DDONA_ENV_FILE`) + "Bugsink" 절의 6개
(`BUGSINK_*` 3개·`INGEST_SHARED_SECRET`·`SENTRY_DSN`·`SENTRY_ENVIRONMENT`) + 크론 알림 3개
(`DISCORD_WEBHOOK_URL`·`HEALTHCHECKS_BACKUP_PING_URL`은 "백업 · 복원" 절, `HEALTHCHECKS_RESOURCE_PING_URL`은 "VM 리소스 감시" 절). `apps/api/.env`는 **로컬 개발용이며 배포와 무관하다.**

| 변수 | 값 | 비고 |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:…@postgres:5432/ai_character_chat` | 컨테이너 간 통신, SSL 없음 |
| `REDIS_URL` | `redis://redis:6379/0` | 컨테이너 |
| `API_BASE_URL` | `https://api.ddona.site` | OAuth redirect_uri 조립 |
| `FRONTEND_BASE_URL` | `https://ddona.site` | OAuth 콜백 뒤 돌려보낼 목적지 |
| `CORS_ALLOW_ORIGINS` | `["https://ddona.site","https://admin.ddona.site"]` | **JSON 배열 문자열** |
| `SESSION_COOKIE_SECURE` | `true` | HTTPS 필수 |
| `SESSION_COOKIE_SAMESITE` | `lax` | FE·BE가 같은 등록가능 도메인이라 가능 |
| `GEMINI_API_KEY` | AI Studio 키 | 채팅 |
| `GEMINI_MODEL_NAME` | `gemini-3.5-flash-lite`(코드 기본값은 `gemini-2.5-flash`) | 2026-09-24부터 프로덕션에 명시. 되돌리려면 이 한 줄만 지우고 `up -d --wait api` — `.env` 백업을 통째로 복원하지 말 것(자동배포가 같은 파일의 `API_IMAGE`를 고친다) |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | OAuth 자격증명 | "Google OAuth" 절 |
| `WITHDRAWN_EMAIL_HMAC_KEY` | `openssl rand -hex 32` 등으로 발급한 무작위 값 | 탈퇴 재가입 차단용 HMAC 키. **한번 정하면 바꾸지 말 것** — 바뀌면 과거에 적립한 해시와 새 조회의 해시가 어긋나 재가입 차단이 조용히 멈춘다(모든 조회가 미스가 된다. 에러가 나지 않아 알아채기 어렵다) |
| `LOCAL_IMAGE_BASE_URL` | 집 PC 서버를 가리키는 터널 origin | **이미지 생성 필수** — 비어 있으면 capabilities가 전부 불가로 내려가 생성이 사전 차단된다. "이미지 생성" 절 |
| `LOCAL_IMAGE_ACCESS_CLIENT_ID` / `LOCAL_IMAGE_ACCESS_CLIENT_SECRET` | Cloudflare Access 서비스 토큰 | **이미지 생성 필수**. "이미지 생성" 절 |
| `LOCAL_IMAGE_MODEL_WIRE_ID` | 집 PC가 보고하는 **실제** 모델 id | **이미지 생성 필수.** 기본값은 공개 id(`v1`)와 같아 로컬·테스트는 설정 없이 돌지만, 운영에서 집 PC의 값과 다르면 교차 검증에서 전부 걸러져 생성이 사전 차단된다. **이 값을 소스에 두지 않는 것이 요점이다**("이미지 생성" 절) |
| `LOCAL_IMAGE_TIMEOUT_SECONDS` | 기본 `90` | 안전한 기본값 — 보통 생략. 근거는 "이미지 생성" 절의 실측치 |
| `LOCAL_IMAGE_CAPABILITIES_TTL_SECONDS` | 기본 `30` | 안전한 기본값 — 보통 생략 |
| `LOCAL_IMAGE_QUEUE_LIMIT` | 기본 `4` | 안전한 기본값 — 보통 생략 |
| `EXPOSE_API_DOCS` | 기본 `false` | 안전한 기본값(닫힘) — **운영에서는 절대 켜지 않는다.** 켜면 `/docs`·`/openapi.json`이 열려 이미지 모델의 불투명 id 은닉("이미지 생성" 절)이 무의미해진다 |
| `S3_ENDPOINT_URL` | `https://<accountid>.r2.cloudflarestorage.com` | R2 |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | R2 API 토큰 키쌍 | boto3가 프로세스 env로 읽는다 |
| `AWS_REGION` | `auto` | R2 규약 |
| `S3_BUCKET_NAME` | `ai-chracter-chat` | 기본값이 dev용이라 override 필수 |
| `EMAIL_PROVIDER` | `resend` | 미설정 시 `console`(발송 안 함) |
| `RESEND_API_KEY` | `re_...` | Resend API 키 |
| `EMAIL_FROM` | `noreply@ddona.site` | `ddona.site` 도메인이 Resend에서 검증돼야 한다 |
| `FORWARDED_ALLOW_IPS` | `172.18.0.0/16` | **uvicorn이 직접 읽는 env**(pydantic 설정 아님). ⚠️ **`*`를 쓰지 말 것** — uvicorn `proxy_headers.py`는 `*`(always_trust)일 때 `X-Forwarded-For` 체인의 **맨 앞** 값을 그대로 쓰는데, Caddy는 실제 IP를 **뒤에 덧붙이므로** 클라이언트가 보낸 위조 헤더가 채택된다(IP rate limit을 헤더 한 줄로 우회 가능). 대역을 주면 체인을 **역순**으로 훑어 신뢰 대역 밖 첫 값(=Caddy가 붙인 진짜 IP)을 고른다. 값은 `ddona_default`의 실측 subnet이며, 단일 IP 대신 대역인 이유는 컨테이너 재생성 시 도커가 IP를 재배정하기 때문이다. 실측: 프로덕션 uvicorn 액세스 로그의 클라이언트 IP가 `127.0.0.1`(헬스체크)과 `172.18.0.3`(`ddona-caddy-1` 컨테이너) 둘뿐이었다 — 실사용자 전원이 한 IP로 보인다. 원인은 uvicorn이 `forwarded_allow_ips` 미지정 시 `127.0.0.1`로 떨어뜨려 도커 브리지의 Caddy가 보낸 `X-Forwarded-For`를 신뢰하지 않는 것이다. 이게 없으면 IP 기반 rate limit이 전 사용자 공유 버킷이 된다. **api 컨테이너가 호스트에 포트를 게시하지 않는 것은 이 위협을 막지 못한다** — 포트 미게시가 막는 것은 "uvicorn에 직접 TCP로 붙어 peer 주소를 위장하는" 쪽이고, `*`가 여는 것은 "평범한 사용자로서 Caddy를 통과하는 정상 HTTPS 요청에 `X-Forwarded-For: 1.2.3.4` 한 줄을 얹는" 쪽이라 api 컨테이너에 직접 닿을 필요가 없다(`Caddyfile`의 api 라우트는 `reverse_proxy api:8000` 한 줄뿐이고(`/_ingest/*`만 `handle_path`로 bugsink에 따로 간다) `trusted_proxies`도 `header_up X-Forwarded-For` 덮어쓰기도 없어 클라이언트가 보낸 체인이 보존된 채 실제 IP가 뒤에 붙는다). 실측 반증: 대역 설정 상태에서 `X-Forwarded-For: 1.2.3.4`를 얹어 보냈지만 로그에는 실제 공인 IP가 찍혔다 — `*`였다면 `1.2.3.4`가 찍혔을 것이다(2026-09-12). 부수효과: `guardian_consents.ip_address`도 이때부터 진짜 IP가 된다(기존 저장값은 전부 프록시 IP다) |

> **`CORS_ALLOW_ORIGINS` 함정**: pydantic-settings는 `list[str]` 필드를 env에서 **JSON으로 파싱**한다.
> 반드시 `["https://a","https://b"]` 형태로 넣을 것(콤마 구분 평문 아님).

### 2-2. FE 빌드타임 (Cloudflare Pages 환경변수)

| 변수 | 값 | 비고 |
|---|---|---|
| `VITE_API_BASE_URL` | `https://api.ddona.site` | **빌드 시 번들에 고정**. web·admin 각각, Production+Preview 둘 다 |

Vite env는 런타임이 아니라 빌드타임이다 — BE URL이 바뀌면 FE를 재빌드해야 한다.

### 2-3. web Worker 런타임 (⚠️ 빠지면 조용히 무효)

web 프로젝트 → Settings → Environment variables(현 UI는 **Variables and Secrets**).
**Production과 Preview 양쪽 모두** plaintext로.

> ⚠️ **"FE 빌드타임" 절과 입력란이 같다.** Cloudflare Pages에는 변수 화면이 하나뿐이고 "런타임 변수"라는
> 별도 메뉴가 없다 — 절을 나눈 것은 **누가 읽느냐**의 구분이다. "FE 빌드타임" 절은 `vite build`가 읽어
> 번들에 박고, 여기 것은 배포된 `dist/_worker.js`가 요청마다 읽는다. `VITE_` 접두어가 붙은
> 것만 브라우저 번들에 들어간다(그래서 `SENTRY_AUTH_TOKEN`에는 절대 붙이지 않는다, "Bugsink" 절).
> 2026-09-16 실제로 이 절 제목 때문에 "런타임 입력란을 못 찾겠다"는 혼선이 있었다.

| 변수 | 값 | 없으면 |
|---|---|---|
| `PUBLIC_ORIGIN` | `https://ddona.site` | canonical·og:url·sitemap이 **요청 host를 따라간다** → 프리뷰 배포가 자기 URL로 색인되어 중복 콘텐츠가 된다. **`legacyRedirect`의 목적지이기도 해서** 비어 있으면 옛 도메인 리다이렉트가 통째로 꺼진다(자기 자신으로 가는 루프를 막는 가드) |
| `API_BASE_URL` | `https://api.ddona.site` | Worker가 조회가 필요한 SEO 경로(상세·프로필 메타, sitemap, og 프록시)를 **통째로 건너뛴다**. 사이트는 멀쩡히 돌아서 티가 안 난다 |
| `INGEST_SHARED_SECRET` | VM `/opt/ddona/.env`의 같은 이름 값과 **반드시 일치**해야 한다("Bugsink" 절) — ⚠️ **Production에만**, 아래 예외 참고 | `/_ingest/*` 프록시(`worker/ingestProxy.ts`)가 `X-Ingest-Secret` 헤더를 못 붙여 Caddy가 **모든 envelope 요청에 401**을 준다 — 브라우저 에러가 전부 Bugsink에 도착하지 못한 채 소실된다 |

- **`VITE_API_BASE_URL`("FE 빌드타임" 절)과 별개다** — 저건 빌드타임에 번들에 박히고 이건 Worker가 런타임에
  읽는다. **둘 다** 필요하다.
- **Preview에도 `PUBLIC_ORIGIN`은 프로덕션 오리진**을 넣는다(프리뷰 URL이 아니라). Worker는
  `요청 host ≠ PUBLIC_ORIGIN host`일 때만 `X-Robots-Tag: noindex`를 붙이므로(`worker/indexing.ts`),
  Preview에서 비어 있으면 프리뷰 색인 차단이 함께 꺼진다.
- **`INGEST_SHARED_SECRET`은 위 "Production과 Preview 양쪽 모두" 지침의 예외다 — Production에만
  넣는다.** 근거는 "Bugsink" 절의 "환경 범위는 Production만이다" 참고.
- 런타임 변수는 **저장만으로 반영되지 않는다** — 저장 후 재배포(또는 최신 배포 Retry)해야 한다.

---

## 3. 배포 절차

### 3-1. BE → GCE VM

**자동배포가 정상 경로다.** `main` push 시 `.github/workflows/deploy-api.yml`이 이미지 빌드 →
Artifact Registry push → IAP SSH로 VM 교체 → 인터넷 쪽 `/health` 확인까지 한다(실측 1분 35초).
트리거 경로는 `apps/api/**` · `docker-compose.prod.yml` · `Caddyfile` · 저장소 루트 `ops/**` ·
워크플로 자신이다.
**GitHub Secrets에 넣는 값은 없다** — WIF라 키를 저장하지 않는다.

```sh
# VM 접속 (22번은 인터넷에 안 열려 있다)
gcloud compute ssh ddona-api --zone=asia-northeast3-a --tunnel-through-iap

# 스택 상태 · 로그
cd /opt/ddona/app
sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env ps
sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env logs -f api

# caddy 접근 로그는 파일로만 쓴다 — `logs caddy`에는
# 더는 뜨지 않는다. 호스트 bind mount라 컨테이너에 안 들어가고 호스트에서 바로 본다.
sudo tail -f /opt/ddona/logs/caddy/access.log
```

**최초 1회 — 접근 로그 회전(logrotate) 설치**. Caddy 내장
롤링(`roll_size`/`roll_keep_for`)은 **회전된** 파일만 기간으로 정리하고, 회전 자체는 크기
기준이라 트래픽이 적으면 활성 `access.log`가 30일을 훌쩍 넘겨도 안 잘린다 — 개정 처리방침
제4조 5항("30일간 보관")을 지키는 보장이 저장소 밖(호스트 crontab)에 살게 되므로, 이 절차를
빠뜨리면 그 약속이 조용히 깨진다. VM을 새로 만들 때마다, 그리고 이번 전환 때 한 번 해야 한다.

```sh
# 1. bind mount 소스 디렉터리를 미리 만든다. 안 만들어도 Docker가 컨테이너 기동 시 root
#    소유로 자동 생성하지만(이 VM은 애초에 /opt/ddona 전체가 root 소유라 문제 없다), logrotate
#    설치를 이 mkdir 뒤에 두어 순서를 명시적으로 고정한다.
sudo mkdir -p /opt/ddona/logs/caddy

# 2. 저장소의 설정을 심볼릭 링크한다(복사가 아니라 링크인 이유: /opt/ddona/app은 배포마다
#    `git reset --hard origin/main`으로 갱신되므로, 링크해두면 정책을 고칠 때 재설치 없이
#    다음 배포부터 자동 반영된다).
sudo ln -sf /opt/ddona/app/ops/logrotate.d/ddona-caddy /etc/logrotate.d/ddona-caddy

# 3. dry-run으로 문법·동작을 검증한다(-f 없이는 실제로 회전하지 않는다).
sudo logrotate -d /etc/logrotate.d/ddona-caddy
```

**롤백**(실측) — `.env`의 태그 한 줄을 되돌리고 다시 올린다:
```sh
sudo sed -i "s|^API_IMAGE=.*|API_IMAGE=asia-northeast3-docker.pkg.dev/ddona-ai-character-chat/ddona/api:<이전SHA>|" /opt/ddona/.env
sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env up -d --wait api
```
과거 태그는 `gcloud artifacts docker tags list asia-northeast3-docker.pkg.dev/ddona-ai-character-chat/ddona/api`.

⚠️ **배포 성공 판정은 `/health` 200만으로 부족하다.** 옛 컨테이너도 200을 준다. 그래서 워크플로가
`docker inspect`로 실행 중 이미지가 새 태그인지 대조한다 — 손으로 배포할 때도 같이 확인할 것.

⚠️ **`Caddyfile`만 바뀐 배포는 `caddy reload`가 성공해도 컨테이너 안 내용이 안 바뀔 수 있다**
(2026-09-15 실측). `docker-compose.prod.yml`이 그대로면 `up -d --wait api caddy`는 caddy
컨테이너를 재생성하지 않고(`Caddyfile` 내용만으로는 compose의 config-hash가 안 바뀐다), 대신
`deploy-api.yml`이 `caddy reload --config /etc/caddy/Caddyfile`을 명시적으로 부른다. 그런데
`Caddyfile`은 **파일 단위 bind mount**(`./Caddyfile:/etc/caddy/Caddyfile:ro`)이고, 매 배포가
`git reset --hard origin/main`으로 호스트 파일을 갱신할 때 **덮어쓰지 않고 새로 만들어 inode가
바뀌면**, 컨테이너 쪽 마운트는 옛 inode를 계속 가리킨다 — 컨테이너 안에서 읽는
`/etc/caddy/Caddyfile`은 여전히 옛 내용이다. `caddy reload`는 이 옛 내용을 "변경 없음"으로
조용히 재적재할 뿐이라 **에러 없이 끝난다.**

- **증상**: 배포 워크플로 성공(`DEPLOY_EXIT=0`), `caddy reload`도 에러 없이 끝났는데 `Caddyfile`
  변경이 실제로는 반영 안 됨.
- **확인 방법**: 호스트 파일(`/opt/ddona/app/Caddyfile`)은 이미 새 내용이므로 그걸 봐서는 속는다 —
  **컨테이너 안** 파일을 봐야 한다.
  ```sh
  sudo docker exec ddona-caddy-1 grep '<바뀐 줄>' /etc/caddy/Caddyfile
  ```
- **해결**: 컨테이너를 강제로 재생성한다.
  ```sh
  sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env \
    up -d --force-recreate --wait caddy
  ```
- **`deploy-api.yml`의 reload 재시도 루프(5회, admin API 준비 대기)와는 다른 문제다** — 그 루프는
  caddy가 **방금 재생성됐을 때** admin API(`127.0.0.1:2019`)가 아직 안 떠서 `connection refused`가
  나는 타이밍 경합을 다룬다. 이건 정반대로 **컨테이너가 재생성되지 않았을 때** bind mount가 새
  파일을 못 보는 문제라, 재시도해도 고쳐지지 않는다 — 매번 같은 옛 inode를 다시 읽을 뿐이다.

### 3-2. DB 마이그레이션

**기본은 파이프라인이 처리한다.** `deploy-api.yml`이 `compose pull api` 직후, `up -d` 직전에 새
이미지로 `compose run --rm -T api alembic upgrade head`를 돌린다. 사람이 따로 돌릴 일은 원칙적으로
없다.

**수동으로 미리 적용해야 할 때**(2026-09-06에 실제로 성공시킨 절차):
```bash
gcloud compute ssh ddona-api --zone=asia-northeast3-a --tunnel-through-iap --project=ddona-ai-character-chat

sudo /opt/ddona/backup.sh   # 먼저 백업

# 현재 리비전
sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env \
  exec -T postgres psql -U postgres -d ai_character_chat -c 'SELECT version_num FROM alembic_version;'

# 적용 (배포된 이미지로. 아직 배포 안 된 마이그레이션은 파일을 /tmp에 올려 bind-mount 한다)
sudo docker run --rm --network ddona_default --env-file /opt/ddona/.env \
  <IMAGE>:<TAG> alembic upgrade head
```

⚠️ **순서 고정: 마이그레이션은 반드시 `up -d`보다 먼저 돈다.** `main.py`의 lifespan 훅이 기동마다
`rebuild_suspended_user_markers()`를 불러 `users.suspended_at`을 SELECT 한다 — 스키마가 없는 채로 새
이미지가 뜨면 `UndefinedColumnError`로 죽고 healthcheck·배포 검증이 함께 실패해 **API가 내려간 채로
남는다.** 미리 적용해 두면 파이프라인의 자동 마이그레이션은 멱등이라 no-op이 된다.

### 3-3. FE → Cloudflare Pages (web, admin 각각)

Pages 프로젝트 2개, 각각 Git 연동으로 `main` push 시 자동 빌드:

- **Build command**: `pnpm install --frozen-lockfile && pnpm --filter @ai-character-chat/web build`
  (admin은 filter 교체)
- **Build output directory**: `apps/web/dist` / `apps/admin/dist`
- **Root directory**: **비워서 repo 루트 유지** (pnpm workspace 설치 때문에 필수)
- **Build watch paths**: `apps/{web|admin}/*, packages/*, pnpm-lock.yaml, pnpm-workspace.yaml`
  (기본값 `*`는 전체 감시라 BE만 바뀌어도 FE가 재배포된다)
- SPA fallback은 `apps/{web,admin}/public/_redirects`(`/* /index.html 200`)로 이미 되어 있다.

⚠️ **Cloudflare 와일드카드는 `*` 하나가 이미 `/`를 가로질러 매칭한다**("including path separators").
`**`는 지원하지 않으므로 `apps/web/**`로 쓰면 아무것도 매칭되지 않아 **모든 푸시가 조용히
스킵된다**(Deployments에 "No deployment available"). 2026-08-05에 실제로 이 상태로 커밋 2개가
배포되지 않았다. 반드시 `*` 하나만 쓸 것. 스킵된 커밋은 대시보드에서 **Retry deployment** — watch
paths를 고쳐도 과거 푸시가 소급 빌드되지는 않는다.

⚠️ **이미지 생성 count 상한을 낮추는 배포는 전환 구간에 짧은 비대칭이 있다.** BE는 GitHub Actions,
FE는 Cloudflare Pages 자체 Git 연동이라 같은 push라도 두 배포가 끝나는 시점이 다르다(순서 보장 없음).
그 사이 구 FE 번들이 살아 있으면 사용자가 여전히 `count` 3~4를 고를 수 있는데, 새 BE는 상한을 2로
낮췄으므로 그 제출은 **422를 한 번** 받는다(`styles`·`available` 필드 추가는 필드 추가뿐이라 구 FE에
무해하다). 이미 열려 있던 탭은 SPA라 새로고침 전까지 구 번들을 그대로 쓴다. **서버에서 값을 조용히
클램프하지 않는다** — 조용한 축소가 눈에 보이는 422보다 나쁘다는 판단이다. 양쪽 배포가 끝나면 저절로
사라진다.

### 3-4. 백업 · 복원

백업은 VM 크론이 매일 18:00 UTC에 돈다(`apps/api/scripts/ops/backup_db.py`, `-Fc --no-owner
--no-acl`). 보관은 일 7개 + 주 4개이고, 삭제 대상을 백업 파일명 패턴에 정확히 맞는 키로 제한해
같은 버킷의 자산과 격리한다.

```sh
sudo /opt/ddona/backup.sh   # 수동 실행

# 복원 — restore_db 는 빈 DB 를 전제한다. 운영 DB 를 실수로 덮지 않도록 대상을 명시적으로 만든다.
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

**`/opt/ddona/backup.sh` 심볼릭 링크 — 전환 완료(2026-09-25 VM 확인), 재구축 시 1회**(`ops/bugsink-vacuum.sh`·`ops/logrotate.d`와
같은 이유: `/opt/ddona/app`은 배포마다 `git reset --hard`되므로 링크만 걸어두면 이후 갱신이 자동이다).

2026-09-16까지 `/opt/ddona/backup.sh`는 **저장소에 없는 VM 로컬 파일**(9/2자)이었다. 그래서 모니터링 도입 때
`.env`에 추가한 `HEALTHCHECKS_BACKUP_PING_URL`·`DISCORD_WEBHOOK_URL`을 `backup_db.py`에 넘기지 못했고,
**백업은 매일 성공하는데 healthchecks.io dead-man's switch와 R2 용량 경고만 조용히 죽어 있었다** —
알림 키가 없으면 `ping()`/`notify()`가 예외 없이 건너뛰도록 설계돼 있어(백업을 죽이지 않으려고)
증상이 전혀 없었고, 실측 전까지 아무도 몰랐다. 그래서 `ops/backup.sh`를 저장소에 올리고 링크로 바꿨다.

```sh
sudo ln -sf /opt/ddona/app/ops/backup.sh /opt/ddona/backup.sh
ls -l /opt/ddona/backup.sh    # → /opt/ddona/app/ops/backup.sh 를 가리켜야 한다
sudo /opt/ddona/backup.sh     # 수동 1회 — healthchecks.io 대시보드에 check-in 이 찍히는지 본다
```

⚠️ `/etc/cron.d/ddona-backup`은 아직 `ops/cron.d/`에 없는 VM 로컬 파일이다(같은 드리프트). 크론은
`/opt/ddona/backup.sh`를 부르므로 위 링크만으로 동작하지만, 재구축 시에는 이 파일도 손으로 만들어야 한다.

**`/opt/ddona/scripts` 심볼릭 링크 — 설치 완료(2026-09-25 VM 확인), 재구축 시 1회**.
전환 전 `/opt/ddona/scripts`는 심볼릭 링크가 아니라 **실제 디렉터리**였고, 배포(`deploy-api.yml`)는
`/opt/ddona/app`만 `git reset --hard`하므로 이 디렉터리는 배포 때마다 갱신되지 않고 그대로
남았다 — 실측(2026-09-15) `backup_db.py`가 크론 사본 8,139B(9/2 판) vs 저장소 12,230B(9/15)로
md5가 달랐다. 이 드리프트 때문에 `delete_expired_withdrawn_emails`(처리방침 제4조 2항·
약관 제14조 4항의 파기 의무)가 9/15에 저장소에 들어간 뒤로 **프로덕션 크론에서 한 번도 실행되지
않았다**(크론 사본 0건 vs 저장소 2건, `/var/log/ddona-backup.log`에 파기 기록 0건). 다만
`withdrawn_emails` 행이 아직 0건이라 실제 위반은 아니고 휴면 결함이었다.

**해법은 복사가 아니라 심볼릭 링크다** — 이유는 위 logrotate 절차와 같다: `/opt/ddona/app`은
배포마다 `git reset --hard origin/main`으로 갱신되므로, 링크해두면 `ops/*`를 고칠 때 재설치 없이
다음 배포부터 자동 반영된다.

```sh
sudo rm -rf /opt/ddona/scripts
sudo ln -s /opt/ddona/app/apps/api/scripts /opt/ddona/scripts
```

**검증**:
```sh
# 1. 크론 사본이 저장소와 같아졌는지
md5sum /opt/ddona/scripts/ops/backup_db.py /opt/ddona/app/apps/api/scripts/ops/backup_db.py

# 2. 다음 18:00 UTC 백업 크론 로그에 파기 라인이 찍히는지
sudo tail -f /var/log/ddona-backup.log
```

**부작용**: 링크가 걸리면 `ops/*` 전체가 프로덕션 크론의 시스템 python3(+boto3,
`PYTHONPATH=/opt/ddona/scripts`)에서 import 가능해야 한다는 제약을 실제로 받는다.
`apps/api/tests/test_ops_production_cron_importable.py`가 그 시스템 python3로 실제 불리는
`backup_db.py`·`restore_db.py` 각각에 대해 이 제약을 `ast`로 고정한다.

⚠️ **`PG_DOCKER_NETWORK=ddona_default`가 없으면 안 된다** — 운영 Postgres는 포트를 게시하지 않으므로
기본 bridge로 뜬 `pg_dump`/`psql` 컨테이너에서 닿지 않는다.

⚠️ **볼륨 두 개는 지우면 안 된다.** `pgdata`는 `/var/lib/postgresql`(부모)에 걸려 있고 — PG 18+는
버전별 하위 디렉터리에 데이터를 두므로 관례대로 `/data`에 걸면 기동을 거부한다 — `caddy_data`가
없으면 재시작마다 인증서를 새로 받다가 Let's Encrypt 레이트리밋에 걸린다.

**백업 알림 · check-in · R2 용량 감시**. `backup_db.py`가
Discord 웹훅(`ops/notify.py`)·healthchecks.io check-in·R2 용량 임계 알림을 전부 겸한다 — 새
스크립트·새 크론·새 Cloudflare 토큰은 없다.

| 변수 | 값 | 비고 |
|---|---|---|
| `DISCORD_WEBHOOK_URL` | Discord 채널의 웹훅 URL | 없으면 `ops/notify.py`의 `notify()`가 조용히 건너뛴다(실패가 아니다) — 알림 미설정이 백업을 죽이면 안 된다 |
| `HEALTHCHECKS_BACKUP_PING_URL` | healthchecks.io에서 발급한 체크의 ping URL(예: `https://hc-ping.com/<uuid>`) | `main()` 진입부(`/start`)·성공 직전(접미사 없음)·`__main__`의 실패 처리(`/fail`) 세 지점에서 접미사만 바꿔 호출한다(healthchecks.io 관례). 없으면 조용히 건너뛴다 |
| `R2_CAPACITY_THRESHOLD_BYTES` | 기본 `10737418240`(10GiB, R2 무료 한도) | prune 직후 버킷 전체 용량(`aws s3 ls --recursive --summarize`)이 이 값 이상이면 Discord로만 알린다. 값이 숫자가 아니면 `RuntimeError`로 갈아 끼워 백업 크론의 `except (RuntimeError, KeyError)`가 잡는다(그냥 `ValueError`로 두면 그 가드 밖으로 새 나가 실패 ping도 못 보낸다) |

**`ops/backup.sh`의 `export` 목록에 위 두 키(`DISCORD_WEBHOOK_URL`·`HEALTHCHECKS_BACKUP_PING_URL`)가
들어 있어야 한다** — 백업에 필요한 키만 뽑아 export하므로, 목록에서 빠지면 `/opt/ddona/.env`에 값이
있어도 크론 프로세스에는 전달되지 않는다(`.env`를 통째로 source하지 않는 이유는 `backup.sh` 주석
참고 — JSON 값이 쉘 문법과 부딪친다).

⚠️ **`__main__`의 `except (RuntimeError, KeyError)` 밖의 예외(예: docker 미기동으로 인한
`FileNotFoundError`)는 실패 ping이 나가지 않는다.** 의도적으로 넓히지 않았다 — 이 가드는 원래
"사전에 식별한 실패 모드"만 좁게 잡도록 설계돼 있고, 예상 못한 예외까지
뭉뚱그려 삼키면 새 버그 클래스를 조용히 숨긴다. 그 대신 start ping 이후 **healthchecks.io 자체의
grace time 초과 감지**가 이 경우를 대신 잡는다 — 두 경로가 서로를 덮는 설계다.

### 3-5. Bugsink(에러 트래커) — 별도 compose, 별도 배포

자가호스팅 Bugsink(Sentry 호환)는 `docker-compose.prod.yml`과
**다른 compose 프로젝트**(`docker-compose.monitoring.yml`)이고 **앱 배포와 별도로 손으로** 기동한다.

**왜 별도 compose·별도 배포인가.** "BE → GCE VM" 절의 자동배포는 `up -d --wait api caddy`로 **서비스명을 명시**한다
— 여기에 Bugsink를 얹으면 앱을 배포할 때마다 에러 추적기도 같이 재시작돼, "배포가 뭔가 깨뜨리는 바로
그 창"에서 에러 추적이 눈을 감는다. 그래서 Bugsink는 이 워크플로가 아예 건드리지 않는
별도 파일이다 — `.github/workflows/deploy-api.yml`의 트리거 경로에 `docker-compose.monitoring.yml`이
없으므로 **이 서비스는 앱 배포로 뜨지 않는다.** 이미지를 갈아끼우거나 설정을 바꿀 때도 아래 명령을
손으로 다시 돈다.

```sh
cd /opt/ddona/app
sudo docker compose -f docker-compose.monitoring.yml --env-file /opt/ddona/.env up -d
sudo docker compose -f docker-compose.monitoring.yml --env-file /opt/ddona/.env ps   # healthy 확인
sudo docker stats --no-stream ddona-monitoring-bugsink-1   # mem_limit(1g)을 실측으로 다시 조정할 때
```

**`/opt/ddona/.env`에 추가해야 하는 값**(이 표의 6개 키 — `BUGSINK_*` 3개·`INGEST_SHARED_SECRET`·
`SENTRY_DSN`·`SENTRY_ENVIRONMENT` — 는 전부 "BE 런타임" 절의 39개 키 카운트에 포함되지만, 값·근거의 유일한
소스는 이 절이다 — "BE 런타임" 절 표에는 행을 따로 만들지 않는다):

| 변수 | 값 | 비고 |
|---|---|---|
| `BUGSINK_SECRET_KEY` | `openssl rand -base64 50` | Django SECRET_KEY. `django-insecure` 접두어 없이 |
| `BUGSINK_CREATE_SUPERUSER` | `관리자이메일:비밀번호` | 최초 1회만 동작한다 — 사용자가 이미 1명이라도 있으면 무시된다(공식 소스 `bsmain/management/commands/prestart.py` 확인). 부트스트랩 후 값을 지우지 않고 둬도 안전하다 |
| `BUGSINK_BASE_URL` | `https://ddona.site/_ingest` | `api.ddona.site`가 아니다 — DSN·이메일 링크가 이 값으로 조립되고, 브라우저 ingest는 `ddona.site`(Worker 경유)를 쓴다. `/_ingest` 프리픽스는 DSN·관리자 UI가 그 경로 아래로 들어가게 만든다(Bugsink는 이 프리픽스를 `FORCE_SCRIPT_NAME`으로 링크 생성에만 쓰고, 실제 라우팅은 `Caddyfile`이 프리픽스를 벗겨서 맞춘다 — 아래 "DSN 발급 절차"·`Caddyfile` 참조) |
| `INGEST_SHARED_SECRET` | 무작위 값(`openssl rand -hex 32`) | `Caddyfile`이 **`/_ingest/api/*/envelope/`(에러 이벤트 수신 경로)에만** 거는 게이트 값. 관리자 UI(`/_ingest/` 나머지)는 이 시크릿 없이 통과하고 Bugsink 자체 로그인으로 보호된다(사용자 결정 — 가입은 이미 `CB_NOBODY`로 잠겨 있어 시크릿의 목적은 로그인 페이지를 숨기는 게 아니라 익명 POST 홍수를 막는 것). Caddy 쪽 배선은 `docker-compose.prod.yml`에 돼 있다 — 배포 순서는 아래 "배포 순서 위험" 참조 |
| `SENTRY_DSN` | Bugsink에서 프로젝트 생성 후 발급되는 DSN | API(`apps/api`)가 자기 에러를 Bugsink로 보내는 값. 비어 있으면 `_init_sentry()`가 조용히 비활성으로 남는다(테스트로 고정된 동작이지 에러가 아니다) |
| `SENTRY_ENVIRONMENT` | `production` | ⚠️ **필수.** 빠뜨리면 기본값 `"development"`가 그대로 남아 프로덕션 이벤트가 Bugsink에서 개발 환경으로 표시된다(`config.py` 주석 — 이 저장소에 스테이징이 없어 프로덕션·dev를 가르는 유일한 값) |

**`SENTRY_DSN` 발급 절차**(최초 1회):
1. 위 명령으로 기동 후 `BUGSINK_BASE_URL`(`https://ddona.site/_ingest/` — **트레일링 슬래시
   필수**. `Caddyfile`의 매처가 `/_ingest/*`라 슬래시 없는 `/_ingest`는 이 라우트에 안 걸리고
   `api:8000`으로 흘러가 404가 난다 — 로컬 caddy 컨테이너로 확인)로 접속해 `BUGSINK_CREATE_SUPERUSER`의
   `email:password`로 로그인한다. 이 경로는 시크릿을 요구하지 않는다(위 표 참조).
2. 프로젝트를 하나 만든다(예: `ddona-api`). Bugsink가 DSN을 보여준다 — 형태는
   `https://<key>@ddona.site/_ingest/<project_id>`다.
3. **API(백엔드) 자신의 `SENTRY_DSN`에는 위 값을 그대로 쓰지 않는다.** `api` 컨테이너는 Bugsink와
   같은 `ddona_default` 네트워크에 있어 Caddy·Worker를 거칠 이유가 없다 — host만 내부 서비스명으로
   바꿔 `http://<key>@bugsink:8000/<project_id>`로 쓴다(key·project_id는 2단계와 동일, host만
   다름, **경로에 `/_ingest`를 넣지 않는다** — 그 프리픽스는 Caddy가 벗겨주는 것을 전제로 한
   공개 DSN에만 있고, bugsink 컨테이너 자신은 `/_ingest`를 모른다). 이 내부 DSN이 실제로 통하려면
   `docker-compose.monitoring.yml`의 `ALLOWED_HOSTS`에 `bugsink`가 들어 있어야 한다 — 빠지면
   `bugsink:8000`으로 보낸 요청의 `Host: bugsink` 헤더가 Django `ALLOWED_HOSTS` 검증에서 막혀
   HTTP 400이 나고, sentry-sdk는 이 실패를 조용히 삼킨다(같은 파일 주석 참조).
   2단계의 공개 DSN(`ddona.site` 경유)은 **web SDK(`apps/web/src/app/sentry.ts`)용**이고 Cloudflare Pages
   빌드 환경변수(`VITE_SENTRY_DSN`, 아래)에 들어간다.

   **실제 envelope 경로가 무엇인지 확인한 근거**(사용하는 sentry-sdk가 DSN에서 URL을 어떻게
   계산하는지를 봐야 한다 — Bugsink가 어떻게 생성하겠다고 "의도"했는지만으로는 부족하다):
   `apps/api/.venv/lib/python3.11/site-packages/sentry_sdk/utils.py`(설치 버전 2.69.1)의
   `Dsn`/`Auth.get_api_url`을 직접 읽었다. DSN `https://<key>@ddona.site/_ingest/<id>`에서
   `Dsn.path`는 경로에서 project_id를 뗀 나머지 + `/`(=`/_ingest/`)이고, `Auth.get_api_url`이
   `f"{scheme}://{host}{path}api/{id}/envelope/"`를 조립한다 — 즉 브라우저·API가 실제로 POST하는
   경로는 **`/_ingest/api/<project_id>/envelope/`**다. 로컬 caddy 컨테이너에 이 정확한 경로로
   실제 요청을 보내 5종 시나리오(시크릿 정상/누락/오답, 관리자 UI, `/_ingest` 밖 경로)로 확인했다
   (`Caddyfile` 주석 참조).

**Cloudflare Pages 빌드 환경변수**(web 프로젝트, "FE 빌드타임" 절과 같은 자리 — web SDK용. 없으면
`initSentry()`가 `init`을 부르지 않는다):

| 변수 | 값 |
|---|---|
| `VITE_SENTRY_DSN` | 위 2단계의 공개 DSN(`https://<key>@ddona.site/_ingest/<project_id>`) |

**소스맵 업로드용 변수 — `apps/web/vite.config.ts`가 아니라 `@sentry/vite-plugin`(정확히는
`@sentry/bundler-plugins`의 `normalizeUserOptions`)이 `process.env`에서 직접 읽는다**(공식 지원
경로, `vite.config.ts`는 옵션으로 넘기지 않는다). `SENTRY_AUTH_TOKEN`이 있을 때만 플러그인 자체가
`plugins` 배열에 들어가므로, 토큰만 있고 아래 세 값이 없으면 플러그인은 활성화된 채 잘못된
대상으로 업로드를 시도한다:

| 변수 | 무엇인지 |
|---|---|
| `SENTRY_AUTH_TOKEN` | Bugsink에서 발급하는 인증 토큰. **이 값이 있을 때만** 소스맵 생성·업로드가 켜지고, 없으면 `build.sourcemap`을 아예 끄므로 `dist`에 `.map`이 남지 않는다(빌드는 정상 종료). ⚠️ **`VITE_` 접두어를 절대 붙이지 않는다** — 붙이면 브라우저 번들에 그대로 인라인된다 |
| `SENTRY_ORG` | 이 Bugsink/Sentry 인스턴스에서 위 프로젝트가 속한 조직(org) slug. Bugsink 관리자 UI에서 확인한다 |
| `SENTRY_PROJECT` | 위 2단계에서 만든 프로젝트의 slug(예: `ddona-api`로 만들었다면 그 값) |
| `SENTRY_URL` | 이 Bugsink 인스턴스의 베이스 URL. **비우면 플러그인이 기본값인 SaaS `https://sentry.io`로 떨어져** 이 인증정보로는 인증에 실패한다 — 다만 빌드 자체는 깨지지 않는다(에러 로그만 남고 `vite build`는 exit 0으로 끝난다), 그래서 실패가 눈에 안 띄기 쉽다 |

⚠️ `@sentry/vite-plugin`이 Bugsink API와 실제로 호환되는지는 **미검증**이다 — 안 되면 `sentry-cli` 직접 호출로 후퇴한다.

**환경 범위는 Production만이다 — 위 빌드 변수 5개와 "web Worker 런타임" 절의 `INGEST_SHARED_SECRET`은 Preview에
넣지 않는다.** `apps/web/src/app/sentry.ts`가 `environment: import.meta.env.MODE`를 쓰는데,
`apps/web/package.json`의 `build` 스크립트는 `--mode` 없이 `vite build`를 부른다 — Cloudflare
Pages의 Preview 배포도 같은 빌드 커맨드를 쓰므로 `MODE`는 Preview에서도 그대로 `production`이다.
지금 이 값들을 Preview에도 넣으면 Preview 배포에서 난 에러와 실사용자 프로덕션 에러가 Bugsink에서
**구분되지 않고 섞인다** — 섞이면 "진짜 사용자에게 난 에러인가"를 판단할 수 없다. 그리고 Preview에
`VITE_SENTRY_DSN`이 없으면 `initSentry()`가 `init`을 아예 안 부르므로(위 `sentry.ts` 발췌),
`INGEST_SHARED_SECRET`도 Preview에는 불필요하다(프록시를 부를 SDK가 없다) — "web Worker 런타임" 절의 "Production과
Preview 양쪽 모두" 지침은 `PUBLIC_ORIGIN`·`API_BASE_URL`에만 해당하고 `INGEST_SHARED_SECRET`은
예외다. **나중에 Preview 에러도 보려면 `environment`가 `MODE`가 아니라 실제 배포 환경(Production/
Preview)을 구분하는 값을 읽도록 코드를 먼저 바꾸고 나서 Preview에도 값을 켜는 것이 순서다** —
지금 켜면 구분 없이 섞인다.

**가입 차단 확인.** `docker-compose.monitoring.yml`이 `USER_REGISTRATION: CB_NOBODY`를 명시한다(기본값
`CB_MEMBERS`도 익명 공개가입은 이미 404지만 — `users/views.py:signup`이 `USER_REGISTRATION != CB_ANYBODY`면
404를 낸다(공식 소스 확인) — 로그인한 팀 관리자가 새 사용자를 초대하는 경로는 `CB_MEMBERS`에서
계속 열려 있다. `CB_NOBODY`는 그 경로까지 잠가 단일 운영자 인스턴스로 명시적으로 고정한다). 확인:
로그아웃 상태로 `https://ddona.site/_ingest/accounts/signup/`(관리자 UI 프리픽스, 위 표 참조)에
접속해 404가 뜨는지 확인한다.

🔴 **배포 순서 위험 — `INGEST_SHARED_SECRET`은 배선됐지만 값이 `/opt/ddona/.env`에 먼저 있어야 한다.**
`Caddyfile`의 `/_ingest/*` 라우트는 `{$INGEST_SHARED_SECRET}`(Caddy 프로세스 자신의 환경변수)를
읽는다. `docker-compose.prod.yml`의 `caddy` 서비스는 이제 `environment`로 이 값을 주입한다 — 하지만
그 주입이 읽는 `${INGEST_SHARED_SECRET}` 자체가 `/opt/ddona/.env`에 없으면 똑같은 실패가
재발한다(아래 실측 참조). 즉 **compose 배선만으로는 부족하고, 이 compose 변경을 적용하기 전에
`/opt/ddona/.env`에 값을 먼저 넣어야 한다** — 순서가 바뀌면 값이 아예 없는 것과 같다.

**완전히 빠진 환경변수도, 빈 문자열로 설정한 환경변수도 Caddyfile 자체를 깨뜨린다 — 둘이 다르지
않다.** 로컬에서 `INGEST_SHARED_SECRET`을 (a) 아예 안 주고, (b) `INGEST_SHARED_SECRET=""`로 주고
각각 이 `Caddyfile`을 `caddy validate`로 어댑트해 실측했다 — **두 경우 모두 토씨 하나 안 틀리고
같은 에러가 난다**:

```
Error: adapting config using caddyfile: parsing caddyfile tokens for 'handle_path': parsing
caddyfile tokens for 'route': malformed header matcher: expected both field and value, at
/etc/caddy/Caddyfile:45, at /etc/caddy/Caddyfile:50
```

`header X-Ingest-Secret {$INGEST_SHARED_SECRET}`에서 변수가 완전 미설정이든 빈 문자열이든 Caddy는
같은 빈 값으로 치환하고, 치환된 토큰이 비어 있으면 `header` 매처가 인자 1개만 받아 파싱 에러다 —
`{$SITE_ADDRESS}` 블록 전체(=`api:8000`으로 가는 기존 프록시 포함)가 **적재 자체에 실패**한다.
실제 영향은 이 라우트를 언제 적용하느냐에 따라 갈린다:

- **`Caddyfile`만 바뀐 상태로 배포**(현재 `deploy-api.yml`의 정상 경로 — 바인드 마운트만 바뀌면
  compose가 caddy 컨테이너를 재생성하지 않고, 대신 `caddy reload`를 명시적으로 부른다, "BE → GCE VM" 절) —
  reload는 새 설정이 안 먹으면 **기존에 돌고 있던 옛 설정을 그대로 유지**한다(Caddy의 트랜잭션 성격
  reload). `deploy-api.yml`의 재시도 루프가 5회 실패 후 `exit 1`로 배포를 **실패 처리**한다(이미
  있는 안전장치, `deploy-api.yml` 주석 "Caddyfile 문법 오류 같은 진짜 실패를 배포 성공으로 만들면 안 되기
  때문"). 즉 **사이트는 안 죽지만 CI는 빨갛게 실패하고 `/_ingest/*`는 적용되지 않는다.**
- **caddy 컨테이너가 처음부터 새로 뜨는 경우**(VM 재구축, `docker-compose.prod.yml` 자체 변경으로
  강제 재생성 등) — `caddy run`이 시작 시점에 똑같은 파싱 에러로 **컨테이너가 즉시 종료**한다(로컬
  실측: `Exited (1)`). 이 경우는 **`api.ddona.site` 전체가 내려간다.**

**`docker-compose.prod.yml`의 `caddy.environment`에는 이제 `INGEST_SHARED_SECRET: ${INGEST_SHARED_SECRET}`
가 들어 있다.** 이걸 처음 배포에 반영할 때는 순서가 중요하다: 위 표대로 `/opt/ddona/.env`에 값을
**먼저** 채워 넣고 나서 이 compose 변경을 적용한다. 그리고 **환경변수는 컨테이너 생성 시점에
고정되므로** `caddy reload`가 아니라 `$C up -d --wait caddy`로 컨테이너를 **재생성**해야 한다
(`Caddyfile` 내용만 바뀐 경우 reload로 충분한 것과 다르다).

### 3-6. Bugsink 이벤트 보유기간 파기 — vacuum cron

"Bugsink" 절의 `MAX_EVENT_AGE_DAYS: "30"`
(`docker-compose.monitoring.yml`)은 "30일보다 오래된 이벤트는 지운다"는 **기준값**만 고정한다 —
실제로 지우는 건 `bugsink-manage vacuum --old-events` 관리 명령이고, 공식 이미지는 이 명령을 도는
스케줄러를 컨테이너 안에 두지 않는다(`Dockerfile` CMD 확인 — gunicorn+snappea만 상시 실행). 값만
고정하고 이 크론이 없으면 처리방침이 약속하는 "수집일로부터 30일간 보관 후 파기"는 실행되지
않는다.

`apps/api/scripts/ops/vacuum_bugsink.py`가 `docker exec ddona-monitoring-bugsink-1 bugsink-manage
vacuum --old-events`를 돌린다. 컨테이너 이름은 추측이 아니다 — `docker-compose.monitoring.yml`의
`name: ddona-monitoring` + 서비스 `bugsink`(replica 1개)를 Compose V2 관례대로 조합한 이름이고,
`docker compose config`로 프로젝트·서비스 이름을 확인한 뒤 로컬에서 실제로 `docker compose up`한
컨테이너 이름을 실측했다("Bugsink" 절의 `docker stats --no-stream ddona-monitoring-bugsink-1`과 같은 이름).
`docker compose exec`가 아니라 `docker exec <고정 이름>`을 쓰는 이유는 이 스크립트가
`docker-compose.monitoring.yml`의 경로나 실행 시점 cwd를 몰라도 되게 하기 위해서다.

**최초 1회 — `ops/bugsink-vacuum.sh` + cron.d 심볼릭 링크 설치**("백업 · 복원" 절의 `/opt/ddona/scripts` 절차,
`ops/logrotate.d/ddona-caddy` 절차와 같은 이유 — `/opt/ddona/app`은 배포마다 `git reset --hard`되므로
링크해두면 재설치 없이 다음 배포부터 반영된다):

```sh
sudo ln -sf /opt/ddona/app/ops/bugsink-vacuum.sh /opt/ddona/bugsink-vacuum.sh
sudo ln -sf /opt/ddona/app/ops/cron.d/ddona-bugsink-vacuum /etc/cron.d/ddona-bugsink-vacuum
```

`ops/bugsink-vacuum.sh`는 `/opt/ddona/.env`를 통째로 source하지 않고 `DISCORD_WEBHOOK_URL`만 뽑아
export한 뒤 `PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.vacuum_bugsink`를 부른다 —
`resource-check.sh`와 같은 이유(JSON 값이 쉘 문법과 부딪친다).

**검증 — "설치했다"가 아니라 "실제로 지워지는 것"을 확인한다**(설치만 확인하면 Caddy 접근 로그
30일 보관이 logrotate 설치를 빠뜨려 조용히 깨졌던 것과 같은 실패 모드를 반복한다):

```sh
# 1. 수동 1회 실행 — 정상 종료·"Vacuum complete." 로그 확인
sudo -u root /opt/ddona/bugsink-vacuum.sh
tail /var/log/ddona-bugsink-vacuum.log

# 2. 삭제 로직 자체가 실제로 이벤트를 지우는지 — 30일을 기다리지 않고 확인한다.
#    `--max-event-age-days 0`으로 "지금 기준 0일보다 오래된"(=현재 존재하는 전부) 이벤트를 지워
#    개수가 실제로 줄어드는지 본다. 사람이 컨테이너 안에서 직접 돌리는 일회성 확인 커맨드이지
#    cron이 쓰는 경로가 아니다(cron은 항상 compose env의 MAX_EVENT_AGE_DAYS=30을 그대로 쓴다).
sudo docker exec ddona-monitoring-bugsink-1 bugsink-manage showstat event_count   # 삭제 전
sudo docker exec ddona-monitoring-bugsink-1 bugsink-manage vacuum --old-events --max-event-age-days 0
sudo docker exec ddona-monitoring-bugsink-1 bugsink-manage showstat event_count   # 삭제 후 — 줄었는지

# 3. 다음 05:00 UTC에 크론이 실제로 도는지
tail -f /var/log/ddona-bugsink-vacuum.log
```

**컨테이너가 안 떠 있을 때**: `docker exec`가 그 자체로 nonzero exit(로컬 실측:
`Error response from daemon: container ... is not running` / `No such container`)를 내고,
`ops/vacuum_bugsink.py`는 이 실패를 삼키지 않고 `ops/notify.py`로 Discord에 알린다. 별도
healthchecks.io dead man's switch는 만들지 않았다 — 이 작업의 범위는 "vacuum이 실제로 도는가"이지
"bugsink 서비스 자체의 생사"가 아니고(후자는 "Bugsink" 절이 손으로 기동/재기동하는 별개 관심사), Discord
알림 하나로 "아무도 모르게 실패한다"는 이 작업의 실제 위험은 이미 닫힌다.

⚠️ 매일 05:00 UTC로 골랐다 — `ddona-backup`(18:00 UTC, "백업 · 복원" 절)과 겹치지 않으면 충분하다. vacuum
자체가 이벤트 삭제 쿼리 한 번이라 `pg_dump`보다 훨씬 가볍고, 보관기간이 30일 단위라 몇 시간
지연이 "30일간 보관 후 파기" 약속을 깨지 않는다 — 시간대를 더 정교하게 고를 이유가 없다.

### 3-7. VM 리소스 감시 — cron이 `free`/`df`를 직접 읽는다

GCP Cloud Monitoring을 쓰지 않는 이유 —
`instance/memory/balloon/ram_used`가 우리 VM에서 `free -m`과 2배 차이가 났고(실측 1.78GB vs
890MB), 그 메트릭 자체가 e2 계열 전용이라 인스턴스 타입을 바꾸면 조용히 사라진다. 대신
`apps/api/scripts/ops/check_resources.py`가 5분마다 `free`/`df`를 직접 읽어 임계 초과 시
Discord로 알리고, 같은 실행이 healthchecks.io로도 ping해 VM 자체의 생사를 VM 밖에서 본다.

| 변수 | 값 | 비고 |
|---|---|---|
| `DISCORD_WEBHOOK_URL` | "백업 · 복원" 절의 백업 알림과 같은 키 | 두 스크립트가 같은 채널로 함께 쏜다 — 채널을 분리하고 싶어지면 그때 `ops/notify.py`에 인자를 뺀다 |
| `HEALTHCHECKS_RESOURCE_PING_URL` | healthchecks.io에서 **백업과 별도로** 발급한 체크의 ping URL | 체크를 분리하는 이유는 백업(1일 1회)과 리소스 감시(5분마다)가 예정 주기가 달라 같은 체크를 공유하면 한쪽의 실행이 다른 쪽의 미실행을 가려버리기 때문이다 |
| `MEMORY_ALERT_THRESHOLD_PERCENT` | 기본 `90` | `(total - available) / total`(`free -m`) 기준. `used` 컬럼이 아니라 `available`을 쓰는 이유는 buff/cache를 실사용량으로 착각하면 상시로 울기 때문이다 |
| `DISK_ALERT_THRESHOLD_PERCENT` | 기본 `85` | `df /`의 `Use%` 컬럼 기준 |

**최초 1회 — `ops/resource-check.sh` + cron.d 심볼릭 링크 설치**("백업 · 복원" 절의 `/opt/ddona/scripts`
절차, `ops/logrotate.d/ddona-caddy` 절차와 같은 이유 — `/opt/ddona/app`은 배포마다
`git reset --hard`되므로 링크해두면 재설치 없이 다음 배포부터 반영된다):

```sh
sudo ln -sf /opt/ddona/app/ops/resource-check.sh /opt/ddona/resource-check.sh
sudo ln -sf /opt/ddona/app/ops/cron.d/ddona-resource-check /etc/cron.d/ddona-resource-check
```

`ops/resource-check.sh`는 `/opt/ddona/.env`를 통째로 source하지 않고 필요한 두 키
(`DISCORD_WEBHOOK_URL`·`HEALTHCHECKS_RESOURCE_PING_URL`)만 뽑아 export한 뒤
`PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.check_resources`를 부른다 — `backup.sh`와
같은 이유(JSON 값이 쉘 문법과 부딪친다)이고, 이 wrapper도 (`backup.sh`처럼) 저장소에 있어
드리프트가 생기지 않는다.

**검증**(사용 중인 `/etc/cron.d` 문법·심볼릭 링크 처리가 `logrotate.d`와 다를 수 있다 — 최초
설치 시 실측으로 확인한다):
```sh
sudo -u root /opt/ddona/resource-check.sh   # 수동 1회 실행 — 정상 종료·로그 확인
tail -f /var/log/ddona-resource-check.log   # 다음 5분 주기에 크론이 실제로 도는지
```

"백업 · 복원" 절의 백업 스크립트와 같은 이유로 `check_resources.py`의 `__main__`도 `(RuntimeError, ValueError)` 밖의
예외에서는 실패를 남기지 않는다 — healthchecks.io의 grace time 초과 감지가 대신 잡는다.

### 3-8. 이미지 생성 요청 파기 — purge cron

`image_generation_requests`의 `status IN ('blocked',
'failed')` 행은 프롬프트 원문을 그대로 담고 있어 이 서비스에서 가장 민감한 텍스트다. 삭제
트리거가 없으면 탈퇴 전까지 무기한 남으므로, `created_at`으로부터 90일 뒤 이 크론이 지운다.
`succeeded`(이미지가 나온 요청)·`pending`은 나이와 무관하게 손대지 않는다 — 그쪽 보유기간은
"이미지와 같은 수명"으로 따로 정해져 있다.

`apps/api/scripts/ops/purge_image_requests.py`가 `ops.pg.run_sh`로 컨테이너 안 `psql`을 직접
띄워 운영 DB에 붙어 `DELETE ... RETURNING`을 날린다("백업 · 복원" 절의 `delete_expired_withdrawn_emails`와
같은 방식) — `ops/cron.d/ddona-bugsink-vacuum`처럼 `docker exec`로 남의 컨테이너에 들어가는
방식이 아니다.

**최초 1회 — `ops/purge-image-requests.sh` + cron.d 심볼릭 링크 설치**("Bugsink 이벤트 보유기간 파기" 절의 `ops/bugsink-vacuum.sh`
절차, `ops/logrotate.d/ddona-caddy` 절차와 같은 이유 — `/opt/ddona/app`은 배포마다
`git reset --hard`되므로 링크해두면 재설치 없이 다음 배포부터 반영된다):

```sh
sudo ln -sf /opt/ddona/app/ops/purge-image-requests.sh /opt/ddona/purge-image-requests.sh
sudo ln -sf /opt/ddona/app/ops/cron.d/ddona-image-request-purge /etc/cron.d/ddona-image-request-purge
```

`ops/purge-image-requests.sh`는 `/opt/ddona/.env`를 통째로 source하지 않고 `DATABASE_URL`·
`DISCORD_WEBHOOK_URL`만 뽑아 export한 뒤 `PG_DOCKER_NETWORK=ddona_default`를 고정하고
`PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.purge_image_requests`를 부른다 —
`resource-check.sh`와 같은 이유(JSON 값이 쉘 문법과 부딪친다)로 필요한 키만 뽑되, `docker exec`가
아니라 운영 DB에 직접 붙는 만큼 "백업 · 복원" 절의 `backup.sh`처럼 `DATABASE_URL`·`PG_DOCKER_NETWORK`가
반드시 있어야 한다(운영 Postgres는 포트를 게시하지 않는다).

**검증 — "설치했다"가 아니라 "실제로 지워지는 것"을 확인한다**("Bugsink 이벤트 보유기간 파기" 절과 같은 이유 — 설치만
확인하면 실제 삭제가 조용히 안 도는 드리프트를 놓친다):

```sh
# 1. 수동 1회 실행 — 정상 종료·"파기" 또는 "파기 대상 없음" 로그 확인
sudo -u root /opt/ddona/purge-image-requests.sh
tail /var/log/ddona-image-request-purge.log

# 2. 다음 06:00 UTC에 크론이 실제로 도는지
tail -f /var/log/ddona-image-request-purge.log
```

**DB 접속이 안 되면**(`PG_DOCKER_NETWORK` 누락 등) `run_sh`가 nonzero exit + stderr를 내고
`purge_image_requests.py`는 이 실패를 삼키지 않고 `ops/notify.py`로 Discord에 알린다.

⚠️ 매일 06:00 UTC로 골랐다 — `ddona-bugsink-vacuum`(05:00 UTC)과 한 시간 버퍼를 두고
`ddona-backup`(18:00 UTC, "백업 · 복원" 절)과는 겹치지 않는다. 이 작업(DELETE 한 번)도 pg_dump보다 훨씬
가벼워 시간대를 더 정교하게 고를 이유가 없다.

### 3-9. 클로버 만료 — expire cron

출석·미션(과 백필) 클로버는 지급일(KST) 자정 + 8일에
만료된다. 차감·잔액 판정 경로(`core/clover.py`)는 만료 필터를 걸지 않는다 — **만료의
진실은 이 크론뿐이다.** 이 크론이 며칠 죽어도 Σ 불변식은 깨지지 않지만(배치 실행 전에 쓰인
만료분은 이미 `remaining`이 줄어 있다), 만료분이 계속 쓰이는 유저에게 유리한 방향의 오차가
생긴다 — 그래서 크론이 실제로 도는지 아래 검증 절차로 확인한다.

`apps/api/scripts/ops/expire_clover.py`가 `ops.pg.run_sh`로 컨테이너 안 `psql`을 직접 띄워
운영 DB에 붙어, 만료 로트를 `remaining = 0`으로 줄이고 `users.clover_balance`를 차감하고
`clover_ledger`에 `expire_burn` 행을 남기는 것을 **한 트랜잭션**(`BEGIN`~`COMMIT`)으로 실행한다
("이미지 생성 요청 파기" 절과 같은 방식 — `docker exec`가 아니라 직접 접속).

**최초 1회 — `ops/expire-clover.sh` + cron.d 심볼릭 링크 설치**("이미지 생성 요청 파기" 절과 같은 이유 —
`/opt/ddona/app`은 배포마다 `git reset --hard`되므로 링크해두면 재설치 없이 다음 배포부터
반영된다):

```sh
sudo ln -sf /opt/ddona/app/ops/expire-clover.sh /opt/ddona/expire-clover.sh
sudo ln -sf /opt/ddona/app/ops/cron.d/ddona-clover-expire /etc/cron.d/ddona-clover-expire
```

`ops/expire-clover.sh`는 `/opt/ddona/.env`를 통째로 source하지 않고 `DATABASE_URL`·
`DISCORD_WEBHOOK_URL`만 뽑아 export한 뒤 `PG_DOCKER_NETWORK=ddona_default`를 고정하고
`PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.expire_clover`를 부른다 — "이미지 생성 요청 파기" 절과 같은
이유로 필요한 키만 뽑되, 운영 DB에 직접 붙는 만큼 `DATABASE_URL`·`PG_DOCKER_NETWORK`가 반드시
있어야 한다(운영 Postgres는 포트를 게시하지 않는다).

**검증 — "설치했다"가 아니라 "실제로 소멸되는 것"을 확인한다**("Bugsink 이벤트 보유기간 파기" 절·"이미지 생성 요청 파기" 절과 같은 이유 — 설치만
확인하면 만료 처리가 조용히 안 도는 드리프트를 놓친다. 이 배치는 되돌릴 수 없는 소멸이므로
특히 중요하다):

```sh
# 1. 수동 1회 실행 — 정상 종료·"clover_lots 만료: N명 잔액 차감" 또는 "만료 대상 없음" 로그 확인
sudo -u root /opt/ddona/expire-clover.sh
tail /var/log/ddona-clover-expire.log

# 2. 다음 15:05 UTC(KST 00:05)에 크론이 실제로 도는지
tail -f /var/log/ddona-clover-expire.log
```

**DB 접속이 안 되면**(`PG_DOCKER_NETWORK` 누락 등) `run_sh`가 nonzero exit + stderr를 내고
`expire_clover.py`는 이 실패를 삼키지 않고 `ops/notify.py`로 Discord에 알린다.

⚠️ 매일 15:05 UTC(= KST 00:05, 다음날) — 만료 시각(KST 자정) 직후로 골랐다.
`ddona-bugsink-vacuum`(05:00 UTC)·`ddona-image-request-purge`(06:00 UTC)와 겹치지 않는다.

---

## 4. 배포 후 스모크 검증

1. `curl https://api.ddona.site/health` → `{"status":"ok"}` · `/ready`로 DB·Redis까지 확인
2. web에서 Google 로그인 → 세션 쿠키가 실제로 설정/전송되는지(Network의 `Set-Cookie`/요청 Cookie)
3. 자산 업로드(presigned PUT) → R2 CORS 통과 확인
4. 채팅 SSE 스트리밍 수신
5. admin 로그인(별도 쿠키 `admin_session_id`)

---

## 5. 이미지 생성

**집 PC의 자가 호스팅 추론 서버**를 쓴다. 서버는 NSSM Windows 서비스로 등록돼 상시 구동되고(재부팅
자동 기동, 크래시 자동 재시작), `127.0.0.1:8100`에만 바인드한다(외부 노출 없음). VM은 **Cloudflare
Tunnel**로 그 origin에 도달하고 `CF-Access-Client-Id`/`CF-Access-Client-Secret` 헤더로 Access 서비스
토큰을 함께 보낸다 — 이 경로를 고른 근거는 "현재 형상의 근거" 절. 실제 클라이언트는 `llm/dependencies.py`가
`LocalImageClient`(`llm/local_image.py`)로만 만든다.

사용자에게 노출되는 것은 불투명 id뿐이다 — 모델 id 1개(`v1`, 표시명 "v1")와 스타일 id 7개
(`soft_portrait`~`deco_cute`, 표시명은 `images/models.py`의 `IMAGE_STYLE_PRESETS` 참고).
체크포인트·LoRA·프리셋 문안·샘플러 파라미터는 전부 집 PC 소유이고, 서버는 프롬프트 원문과 이 두 id,
`aspect_ratio` 문자열만 보낸다. 서버 쪽 계약 구현은 `llm/local_image.py`다.

생성 잡은 기존과 동일하게 응답(202) 뒤 `asyncio.create_task`로 돌고, 이미지는 그대로 R2에 올라간다.
서버는 모듈 수준 `asyncio.Semaphore(1)`로 GPU 호출을 직렬화하고(프로덕션이 uvicorn 단일 프로세스라 이
정도로 충분하다 — "현재 형상의 근거" 절), 별도 카운터(`LOCAL_IMAGE_QUEUE_LIMIT`, 기본 4)로 대기열 깊이를 제한해 초과
요청은 잡을 만들지 않고 즉시 429로 거절한다. **여기에 유저별 상한이 겹친다**(`core/rate_limit_gate.py`) —
유저별 큐 1칸(같은 사람의 두 번째 동시 요청은 `QUEUE_FULL`)과 토큰 버킷(용량 10장·시간당 1장 충전, 초과분은
클로버로 차감하고 잔액 부족이면 `CLOVER_REQUIRED`, 그날 차감 동의 전이면 `CLOVER_CONFIRM_REQUIRED`)이고, 거절은
모두 `{"detail": {"code", "retryAfterSeconds", "window"}}` 한 모양이라 `code`로만 갈린다. 예외 계정
(`users.rate_limit_exempt`)은 **토큰 버킷만** 면제되고 큐 두 개는 그대로 받는다. 같은 모듈이 채팅 4경로에도
429를 낸다(분당 10은 `USER_LIMIT`·`window` `minute`, 일일 30 초과분은 클로버 차감으로 넘어가 부족·미동의면
`CLOVER_REQUIRED`/`CLOVER_CONFIRM_REQUIRED`·`window` `clover`) — 서버 로그의 `user_limit_exceeded`는
이미지·채팅 공용이라 `code`/`window`로 가른다. auth 발송 상한의 429(`core/rate_limit.py`, 가입·재발송·
비밀번호 재설정)도 같은 모양이다(`window` `auth`, `auth/router.py`의 `_auth_too_many_requests`). 생성 전에는 `GET /capabilities`를 TTL 캐시
(`LOCAL_IMAGE_CAPABILITIES_TTL_SECONDS`, 기본 30초)로 프로브해 집 PC가 꺼져 있으면 **생성 시도 전에**
503으로 차단한다.

**측정치**(집 PC 팀의 계약 이행 확인서 기준):

| 항목 | 값 |
|---|---|
| 생성 시간(정상 상태) | 약 17~20초 |
| 생성 시간(종횡비 버킷 전환 직후 첫 요청) | **27~34초** — `torch.backends.cudnn.benchmark`가 그 해상도의 커널을 처음 탐색·캐시하는 비용이다. **`LOCAL_IMAGE_TIMEOUT_SECONDS`가 45초가 아니라 90초인 이유가 이 값이다** |
| 재부팅 후 콜드스타트 | 약 5.4초(프로세스 기동 → `/capabilities` 첫 200) |
| VRAM | 상주 0 MiB(오프로드 훅, forward 시점까지 GPU에 올리지 않음) · 생성 피크 **5494 MiB** |

집 PC는 콘텐츠 정책 가드도 운영한다 — 생성 전(프롬프트) · 생성 후(이미지) 2단계로 판정하고,
위반이 의심되면 `422`를 낸다. 서버는 그것을 사용자에게 "정책 차단"으로 알린다.

---

## 6. 알려진 갭

- **이미지 생성이 집 PC 한 대의 가동률에 종속된다.** 그 PC의 다운타임이 곧 이 기능의 실패율이다 —
  폴백이 없다(Cloudflare의 모델을 없앤 것은 의도적 결정이라, 조용히 낮은 품질로 대체되면 애초에
  로컬로 옮긴 이유가 무너진다). 사용자가 보는 것은 깨진 폼이 아니라 제출 전 사전 차단(503, "이미지 생성" 절)이다.
- **스테이징 환경 없음**: main push → 바로 prod. 대신 BE는 태그 한 줄 롤백("BE → GCE VM" 절), FE는 Pages 이전
  배포로 롤백 가능 → 문제 시 1순위는 롤백, fix는 그 다음.
- **Pages 프리뷰에서는 API 연동 확인 불가**: `CORS_ALLOW_ORIGINS`가 prod 두 도메인만 허용해 PR
  프리뷰(랜덤 서브도메인)에서 CORS로 막힌다. 필요해지면 완화.
- **즉시 롤백 스위치(옛 스택)는 없다.** 인프라 장애 복구는 "VM 재구축 → compose → R2 백업 복원"이고
  시간이 걸린다.

---

## 7. SEO 운영

web은 순수 클라이언트 SPA라 크롤러가 빈 `<head>`를 본다. `apps/web/worker/`(Pages Advanced Mode
`dist/_worker.js`)가 **봇 UA에만** 완성된 `<head>`를 주입하고 `/sitemap.xml`·`/robots.txt`·`/og/*`
프록시를 제공한다. 선행 조건은 "web Worker 런타임" 절의 Worker 런타임 변수다.

### 7-1. 반영 확인

> ⚠️ **`robots.txt`에는 캐시버스터를 붙여야 한다.** `handleRobots`는 캐시 헤더를 안 붙이는데
> **Cloudflare 엣지가 `.txt`를 기본 4시간 캐시한다**(실측 `cf-cache-status: HIT` /
> `max-age=14400`). 그냥 `curl`하면 환경변수 교체 **전** 값이 나와 **검증이 거짓말을 한다** —
> 2026-09-02에 실제로 이걸로 오진했다. `?cb=$RANDOM`을 붙이거나 Purge Everything을 먼저 누른다.

```bash
ORIGIN=https://ddona.site
curl -s "$ORIGIN/robots.txt?cb=$RANDOM" | tail -2             # Sitemap: $ORIGIN/sitemap.xml
curl -s $ORIGIN/sitemap.xml | grep -c "<loc>"                 # 1 이상
curl -s -A "Googlebot/2.1" $ORIGIN/ | grep -c 'rel="canonical"'   # 1 (PUBLIC_ORIGIN 확인)
curl -s -A "Googlebot/2.1" $ORIGIN/content/character/<id> | grep -o "<title>.*</title>"   # 캐릭터 이름 (API_BASE_URL 확인)
```
상세 `<title>`이 홈 문구(`또나 — AI 캐릭터 챗`) 그대로면 `API_BASE_URL`이 안 들어갔거나 재배포를 안 한 것이다.

**FE 번들이 반영됐는지는 해시가 아니라 청크 *내용*으로 판정한다.** 위 명령들은 Worker가 만드는
SEO 경로만 본다 — 화면을 고친 커밋이 실제로 나갔는지는 확인해 주지 않는다.

> ⚠️ **로컬 `dist`의 파일명과 프로덕션 파일명을 비교하지 말 것.** 같은 커밋이라도 빌드 환경이
> 다르면 콘텐츠 해시가 다르게 나온다(2026-09-08 실측: 같은 소스에서 로컬
> `chat._roomId-BR8s3q6N.js` / 프로덕션 `chat._roomId-DSV7K84W.js`). 이름이 다른 것을 "미배포"의
> 증거로 쓰면 **이미 배포된 것을 안 나갔다고 오진한다** — 실제로 그렇게 25분을 썼다. 서로 다를 수
> 있는 두 값을 비교하는 것이라 아무것도 논증하지 못한다.

> ⚠️ **HTTP 200은 파일이 있다는 뜻이 아니다.** `env.ASSETS.fetch()`가 없는 경로에도 `index.html`을
> 200으로 준다(`apps/web/CLAUDE.md`). 청크를 직접 요청할 때는 반드시 **`content-type`**을 본다 —
> `text/html`이면 그 파일은 **없는** 것이다.

라우트 컴포넌트는 `autoCodeSplitting`으로 지연 청크가 되므로 엔트리 번들(`index-*.js`)을 grep해도
안 나온다. 엔트리에서 그 라우트의 청크 이름을 뽑아 받은 뒤 내용을 본다:

```bash
ORIGIN=https://ddona.site
ENTRY=$(curl -s "$ORIGIN/?cb=$RANDOM" | grep -o 'assets/index-[A-Za-z0-9_-]*\.js' | head -1)
CHUNK=$(curl -s "$ORIGIN/$ENTRY" | grep -o 'chat\._roomId-[A-Za-z0-9_-]*\.js' | sort -u)   # 라우트별로 교체
curl -s -D- -o /tmp/c.js "$ORIGIN/assets/$CHUNK" | grep -i content-type   # application/javascript 여야 한다
grep -c '<바뀐 클래스나 문자열>' /tmp/c.js                                  # 1 이상이면 반영됨
```

### 7-2. 소유확인이 지금 걸려 있는 방식

`ddona.site`와 옛 `*.pages.dev` 속성이 **둘 다 살아 있어야 한다**(주소 변경 기간). 그래서 확인 수단이
속성마다 다르다:

| 속성 | 구글 | 네이버 |
|---|---|---|
| `ddona.site` | 도메인 속성 + **DNS TXT**(Cloudflare) | **HTML 파일** — `worker/siteVerification.ts`에 경로·본문 등록 |
| 옛 `*.pages.dev` | `index.html`의 `google-site-verification` meta | `index.html`의 `naver-site-verification` meta |

- ⚠️ **같은 `name`의 meta를 하나 더 넣지 말 것.** 크롤러 대부분이 앞의 것만 읽어 새 속성 확인이
  조용히 실패한다. `index.html`의 두 meta는 **옛 속성용이며 지우지 않는다.**
- ⚠️ **소유확인 HTML 파일을 `apps/web/public/`에 커밋하면 동작하지 않는다**(2026-09-02 실측). `dist/`
  까지는 복사되지만 Pages 자산 서버가 클린 URL 정책으로 `/foo.html` → `/foo`를 **308**로 돌려주고,
  확장자가 사라진 경로는 `KNOWN_ROUTES`에 없어 Worker가 404를 준다. 검증기는 `.html` URL을 치므로
  실패한다. **반드시 `worker/siteVerification.ts`에 등록한다**(자산 검사보다 앞에서 응답한다).
- 봇 응답에서도 meta는 살아남는다 — `injectHead`(`worker/html.ts`)는 자기가 주입하는 키
  (title·description·og:*·canonical·robots)와 같은 키만 지운다.

### 7-3. 색인 요청과 진단

캐릭터 상세(`/content/character/{id}`) URL 검사 → **게재된 URL 테스트** → HTML에서 `<title>`에 캐릭터
이름이 들어갔는지 확인한 뒤 "색인 생성 요청". 순서가 중요하다 — "색인 생성 요청"은 구글이 이미 가진
버전을 쓰고, 라이브 HTML을 새로 가져오는 건 "게재된 URL 테스트"뿐이다.

⚠️ **이 라이브 테스트는 `Googlebot`이 아니라 `Google-InspectionTool` UA로 온다**(리치 결과 테스트도
같다). `worker/crawler.ts`의 토큰 목록에 `google-inspectiontool`이 있어야 주입된 HTML이 보인다 —
빠뜨리면 **실제 색인은 멀쩡한데 확인 도구에서만 주입 전 HTML이 보여** 고장난 것처럼 읽힌다
(2026-08-20에 실제로 겪음).

네이버 Yeti는 JS 렌더링이 제한적이라 **봇 메타 주입이 네이버에서는 색인 가부를 직접 가른다**(구글은
JS를 실행하므로 주입은 속도·정확도 문제에 가깝다). "요청 → 웹 페이지 수집"으로 캐릭터 페이지 하나를
넣어 수집 결과 title을 확인할 것.

### 7-4. admin 색인 차단

`apps/admin/public/robots.txt`(`User-agent: *` / `Disallow: /`)가 Vite 빌드로 `apps/admin/dist/`에
복사된다. **admin은 별도 Pages 프로젝트라 web의 robots.txt(Worker 생성)와 무관하다.** admin은
서치콘솔·서치어드바이저에 등록하지 않는다.

### 7-5. 홈 og:image는 하드코딩이다

`apps/web/index.html`의 `og:image`만 절대 URL로 박혀 있다(현재 `https://ddona.site/og-default.png`).
상세·프로필은 Worker가 `PUBLIC_ORIGIN`으로 만든다 — 도메인이 또 바뀌면 이 한 줄을 같이 고쳐야 홈
공유 미리보기가 옛 도메인을 가리킨 채 남지 않는다.
