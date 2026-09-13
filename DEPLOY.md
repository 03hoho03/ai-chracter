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

FE·BE가 같은 등록가능 도메인(`ddona.site`)에 있다 — 그래서 세션 쿠키가 `SameSite=lax`다(§2-1).
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
| 백업 | 매일 18:00 UTC → `s3://ai-chracter-chat/backup/daily/`, 7일 + 4주 보관 (§3-4) |

⚠️ **`api` 레코드의 구름은 반드시 회색이다.** 주황(프록시)이면 ACME 챌린지가 막혀 Caddy 인증서
**갱신**이 실패한다 — 발급된 인증서가 살아 있어 **두 달 뒤에** 죽는다. apex·`www`·`admin`은 Pages가
만드는 **주황**이 정답이다. 프록시 상태는 대시보드 표시가 아니라 응답으로 확인한다: `api`가
Cloudflare 애니캐스트 IP(`104.x`/`172.67.x`)가 아니라 VM 고정 IP를 그대로 답하면 회색이다.

### 0-2. 현재 형상의 근거

되짚을 일이 반드시 생기므로 남긴다. **결과가 아니라 근거**다 — 값은 §0-1을 본다.

| 갈림길 | 고른 것 | 근거 |
|---|---|---|
| HTTPS | **Caddy + 도메인** | Let's Encrypt 자동 갱신. Tailscale Funnel은 검증 단계용이라 최종형을 두 번 만들게 된다 |
| DB·Redis 위치 | **둘 다 VM 컨테이너** | 앱↔DB 네트워크 홉 0. 대가로 백업이 전적으로 우리 책임이라 **백업을 1단계로 앞당겼다** |
| 배포 인증 | **Workload Identity Federation** | 조직 정책이 SA 키 발급을 막는다(`iam.disableServiceAccountKeyCreation`). 결과적으로 낫다 — **GitHub에 만료 없는 자격증명이 없다** |
| VM 파일 소유 | **root + sudo 배포** | OS Login은 접속 주체마다 POSIX 사용자가 달라, 사람 계정 소유로 두면 배포 SA가 git·docker·`.env` 셋 다 막힌다 |
| 백업 위치 | **자산 버킷의 `backup/`** | 기존 R2 토큰이 그 버킷 전용이라 새 토큰 없이 쓰려면 이 방법뿐. 대신 prune이 백업 파일명 형태에 **정확히** 맞는 것만 지우게 해 자산과 격리했다 |
| `/health` vs `/ready` | **둘 다 둔다** | `/health`는 얕아야 한다(Caddy·compose healthcheck·배포 검증이 의존). 자원 장애 감지는 `/ready`가 맡는다 |
| 이미지 생성 → 집 PC 경로 | **Cloudflare Tunnel + Access 서비스 토큰** | VM에 데몬·컨테이너 네트워크 변경·키 로테이션이 필요 없다. 세마포어(§5)가 매 HTTP 호출을 생성 1건으로 묶어 두므로 엣지 요청 제한에 다가가지 않는다. 체크포인트 스왑을 도입하면 그 전제가 깨져 Tailscale로 돌아간다 |

**기각한 것**: Caddy `flush_interval -1` — 있으나 없으나 SSE 도착 간격이 같았다(300ms 간격 5개 실측:
0.28/0.58/0.89/1.19s vs 0.30/0.60/0.91/1.21s). Caddy 2가 `text/event-stream`을 감지해 자동 flush 한다.
언젠가 스트리밍이 뭉쳐 도착하면 그때 `Caddyfile`에 넣어 본다. · 전용 백업 버킷(토큰 비용 대비 이득이
작았다 — R2 CORS는 읽기 권한을 주지 않으므로 자산 노출 우려는 애초에 틀린 근거였다).

### 0-3. 안 쓰는데 남아 있는 것

| 대상 | 상태 | 비고 |
|---|---|---|
| GCP 프로젝트 `ai-character-chat-501906` | 유지 | **Google OAuth 클라이언트가 여기 있다**(§1-3) — 지우면 로그인이 죽는다 |
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
집 PC의 자가 호스팅 추론 서버다 — §5.

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

**29개 키다**: 앱 런타임 24개(아래 표에서 생략 가능한 `GEMINI_MODEL_NAME`·`LOCAL_IMAGE_TIMEOUT_SECONDS`·
`LOCAL_IMAGE_CAPABILITIES_TTL_SECONDS`·`LOCAL_IMAGE_QUEUE_LIMIT`·`EXPOSE_API_DOCS` 5개 제외) + compose용
5개(`API_IMAGE`·`SITE_ADDRESS`·`POSTGRES_PASSWORD`·`POSTGRES_DB`·`DDONA_ENV_FILE`). `apps/api/.env`는
**로컬 개발용이며 배포와 무관하다.**

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
| `GEMINI_MODEL_NAME` | 기본 `gemini-2.5-flash` | 보통 생략 |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | OAuth 자격증명 | §1-3 |
| `LOCAL_IMAGE_BASE_URL` | 집 PC 서버를 가리키는 터널 origin | **이미지 생성 필수** — 비어 있으면 capabilities가 전부 불가로 내려가 생성이 사전 차단된다. §5 |
| `LOCAL_IMAGE_ACCESS_CLIENT_ID` / `LOCAL_IMAGE_ACCESS_CLIENT_SECRET` | Cloudflare Access 서비스 토큰 | **이미지 생성 필수**. §5 |
| `LOCAL_IMAGE_MODEL_WIRE_ID` | 집 PC가 보고하는 **실제** 모델 id | **이미지 생성 필수.** 기본값은 공개 id(`v1`)와 같아 로컬·테스트는 설정 없이 돌지만, 운영에서 집 PC의 값과 다르면 교차 검증에서 전부 걸러져 생성이 사전 차단된다. **이 값을 소스에 두지 않는 것이 요점이다**(§5) |
| `LOCAL_IMAGE_STYLE_WIRE_ID` | 집 PC가 보고하는 **실제** 스타일 id | **이미지 생성 필수.** 위와 같다(기본값 `base`) |
| `LOCAL_IMAGE_TIMEOUT_SECONDS` | 기본 `90` | 안전한 기본값 — 보통 생략. 근거는 §5의 실측치 |
| `LOCAL_IMAGE_CAPABILITIES_TTL_SECONDS` | 기본 `30` | 안전한 기본값 — 보통 생략 |
| `LOCAL_IMAGE_QUEUE_LIMIT` | 기본 `4` | 안전한 기본값 — 보통 생략 |
| `EXPOSE_API_DOCS` | 기본 `false` | 안전한 기본값(닫힘) — **운영에서는 절대 켜지 않는다.** 켜면 `/docs`·`/openapi.json`이 열려 이미지 모델의 불투명 id 은닉(§5)이 무의미해진다 |
| `S3_ENDPOINT_URL` | `https://<accountid>.r2.cloudflarestorage.com` | R2 |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | R2 API 토큰 키쌍 | boto3가 프로세스 env로 읽는다 |
| `AWS_REGION` | `auto` | R2 규약 |
| `S3_BUCKET_NAME` | `ai-chracter-chat` | 기본값이 dev용이라 override 필수 |
| `EMAIL_PROVIDER` | `resend` | 미설정 시 `console`(발송 안 함). `email-goal-prompt.md E-3` |
| `RESEND_API_KEY` | `re_...` | Resend API 키. `E-1` |
| `EMAIL_FROM` | `noreply@ddona.site` | `ddona.site` 도메인이 Resend에서 검증돼야 한다. `E-4` |
| `FORWARDED_ALLOW_IPS` | `172.18.0.0/16` | **uvicorn이 직접 읽는 env**(pydantic 설정 아님). ⚠️ **`*`를 쓰지 말 것** — uvicorn `proxy_headers.py`는 `*`(always_trust)일 때 `X-Forwarded-For` 체인의 **맨 앞** 값을 그대로 쓰는데, Caddy는 실제 IP를 **뒤에 덧붙이므로** 클라이언트가 보낸 위조 헤더가 채택된다(IP rate limit을 헤더 한 줄로 우회 가능). 대역을 주면 체인을 **역순**으로 훑어 신뢰 대역 밖 첫 값(=Caddy가 붙인 진짜 IP)을 고른다. 값은 `ddona_default`의 실측 subnet이며, 단일 IP 대신 대역인 이유는 컨테이너 재생성 시 도커가 IP를 재배정하기 때문이다. 실측: 프로덕션 uvicorn 액세스 로그의 클라이언트 IP가 `127.0.0.1`(헬스체크)과 `172.18.0.3`(`ddona-caddy-1` 컨테이너) 둘뿐이었다 — 실사용자 전원이 한 IP로 보인다. 원인은 uvicorn이 `forwarded_allow_ips` 미지정 시 `127.0.0.1`로 떨어뜨려 도커 브리지의 Caddy가 보낸 `X-Forwarded-For`를 신뢰하지 않는 것이다. 이게 없으면 IP 기반 rate limit이 전 사용자 공유 버킷이 된다. `*`가 안전한 이유는 api 컨테이너가 호스트에 포트를 게시하지 않아 Caddy 외에는 닿을 수 없기 때문이다(이 파일의 `docker-compose.prod.yml` 설명이 그 설계를 이미 명시한다). 부수효과: `guardian_consents.ip_address`도 이때부터 진짜 IP가 된다(기존 저장값은 전부 프록시 IP다). `E-6a` |

> **`CORS_ALLOW_ORIGINS` 함정**: pydantic-settings는 `list[str]` 필드를 env에서 **JSON으로 파싱**한다.
> 반드시 `["https://a","https://b"]` 형태로 넣을 것(콤마 구분 평문 아님).

### 2-2. FE 빌드타임 (Cloudflare Pages 환경변수)

| 변수 | 값 | 비고 |
|---|---|---|
| `VITE_API_BASE_URL` | `https://api.ddona.site` | **빌드 시 번들에 고정**. web·admin 각각, Production+Preview 둘 다 |

Vite env는 런타임이 아니라 빌드타임이다 — BE URL이 바뀌면 FE를 재빌드해야 한다.

### 2-3. web Worker 런타임 (⚠️ 빠지면 조용히 무효)

web 프로젝트 → Settings → Environment variables. **Production과 Preview 양쪽 모두** plaintext로.

| 변수 | 값 | 없으면 |
|---|---|---|
| `PUBLIC_ORIGIN` | `https://ddona.site` | canonical·og:url·sitemap이 **요청 host를 따라간다** → 프리뷰 배포가 자기 URL로 색인되어 중복 콘텐츠가 된다. **`legacyRedirect`의 목적지이기도 해서** 비어 있으면 옛 도메인 리다이렉트가 통째로 꺼진다(자기 자신으로 가는 루프를 막는 가드) |
| `API_BASE_URL` | `https://api.ddona.site` | Worker가 조회가 필요한 SEO 경로(상세·프로필 메타, sitemap, og 프록시)를 **통째로 건너뛴다**. 사이트는 멀쩡히 돌아서 티가 안 난다 |

- **`VITE_API_BASE_URL`(§2-2)과 별개다** — 저건 빌드타임에 번들에 박히고 이건 Worker가 런타임에
  읽는다. **둘 다** 필요하다.
- **Preview에도 `PUBLIC_ORIGIN`은 프로덕션 오리진**을 넣는다(프리뷰 URL이 아니라). Worker는
  `요청 host ≠ PUBLIC_ORIGIN host`일 때만 `X-Robots-Tag: noindex`를 붙이므로(`worker/indexing.ts`),
  Preview에서 비어 있으면 프리뷰 색인 차단이 함께 꺼진다.
- 런타임 변수는 **저장만으로 반영되지 않는다** — 저장 후 재배포(또는 최신 배포 Retry)해야 한다.

---

## 3. 배포 절차

### 3-1. BE → GCE VM

**자동배포가 정상 경로다.** `main` push 시 `.github/workflows/deploy-api.yml`이 이미지 빌드 →
Artifact Registry push → IAP SSH로 VM 교체 → 인터넷 쪽 `/health` 확인까지 한다(실측 1분 35초).
트리거 경로는 `apps/api/**` · `docker-compose.prod.yml` · `Caddyfile` · 워크플로 자신이다.
**GitHub Secrets에 넣는 값은 없다** — WIF라 키를 저장하지 않는다.

```sh
# VM 접속 (22번은 인터넷에 안 열려 있다)
gcloud compute ssh ddona-api --zone=asia-northeast3-a --tunnel-through-iap

# 스택 상태 · 로그
cd /opt/ddona/app
sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env ps
sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env logs -f api
```

**롤백**(실측) — `.env`의 태그 한 줄을 되돌리고 다시 올린다:
```sh
sudo sed -i "s|^API_IMAGE=.*|API_IMAGE=asia-northeast3-docker.pkg.dev/ddona-ai-character-chat/ddona/api:<이전SHA>|" /opt/ddona/.env
sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env up -d --wait api
```
과거 태그는 `gcloud artifacts docker tags list asia-northeast3-docker.pkg.dev/ddona-ai-character-chat/ddona/api`.

⚠️ **배포 성공 판정은 `/health` 200만으로 부족하다.** 옛 컨테이너도 200을 준다. 그래서 워크플로가
`docker inspect`로 실행 중 이미지가 새 태그인지 대조한다 — 손으로 배포할 때도 같이 확인할 것.

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

⚠️ **`PG_DOCKER_NETWORK=ddona_default`가 없으면 안 된다** — 운영 Postgres는 포트를 게시하지 않으므로
기본 bridge로 뜬 `pg_dump`/`psql` 컨테이너에서 닿지 않는다.

⚠️ **볼륨 두 개는 지우면 안 된다.** `pgdata`는 `/var/lib/postgresql`(부모)에 걸려 있고 — PG 18+는
버전별 하위 디렉터리에 데이터를 두므로 관례대로 `/data`에 걸면 기동을 거부한다 — `caddy_data`가
없으면 재시작마다 인증서를 새로 받다가 Let's Encrypt 레이트리밋에 걸린다.

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
토큰을 함께 보낸다 — 이 경로를 고른 근거는 §0-2. 실제 클라이언트는 `llm/dependencies.py`가
`LocalImageClient`(`llm/local_image.py`)로만 만든다.

사용자에게 노출되는 것은 불투명 id 한 쌍뿐이다 — 모델 `v1`(표시명 "v1"), 스타일 `base`(표시명 "기본").
체크포인트·LoRA·프리셋 문안·샘플러 파라미터는 전부 집 PC 소유이고, 서버는 프롬프트 원문과 이 두 id,
`aspect_ratio` 문자열만 보낸다. 서버↔집 PC 계약은 `tasks/local-image-gen-contract.md`(저장소 밖,
`.gitignore` 대상)에 있다.

생성 잡은 기존과 동일하게 응답(202) 뒤 `asyncio.create_task`로 돌고, 이미지는 그대로 R2에 올라간다.
서버는 모듈 수준 `asyncio.Semaphore(1)`로 GPU 호출을 직렬화하고(프로덕션이 uvicorn 단일 프로세스라 이
정도로 충분하다 — §0-2), 별도 카운터(`LOCAL_IMAGE_QUEUE_LIMIT`, 기본 4)로 대기열 깊이를 제한해 초과
요청은 잡을 만들지 않고 즉시 429로 거절한다. 생성 전에는 `GET /capabilities`를 TTL 캐시
(`LOCAL_IMAGE_CAPABILITIES_TTL_SECONDS`, 기본 30초)로 프로브해 집 PC가 꺼져 있으면 **생성 시도 전에**
503으로 차단한다.

**측정치**(집 PC 팀의 계약 이행 확인서 기준):

| 항목 | 값 |
|---|---|
| 생성 시간(정상 상태) | 약 17~20초 |
| 생성 시간(종횡비 버킷 전환 직후 첫 요청) | **27~34초** — `torch.backends.cudnn.benchmark`가 그 해상도의 커널을 처음 탐색·캐시하는 비용이다. **`LOCAL_IMAGE_TIMEOUT_SECONDS`가 45초가 아니라 90초인 이유가 이 값이다** |
| 재부팅 후 콜드스타트 | 약 5.4초(프로세스 기동 → `/capabilities` 첫 200) |
| VRAM | 상주 0 MiB(오프로드 훅, forward 시점까지 GPU에 올리지 않음) · 생성 피크 **5494 MiB** |

---

## 6. 알려진 갭

- **이미지 생성이 집 PC 한 대의 가동률에 종속된다.** 그 PC의 다운타임이 곧 이 기능의 실패율이다 —
  폴백이 없다(Cloudflare의 모델을 없앤 것은 의도적 결정이라, 조용히 낮은 품질로 대체되면 애초에
  로컬로 옮긴 이유가 무너진다). 사용자가 보는 것은 깨진 폼이 아니라 제출 전 사전 차단(503, §5)이다.
- **생성 시점 안전 필터가 없다.** Cloudflare 내장 필터가 유일한 사전 필터였는데 그게 사라졌다.
  `moderation/`은 신고·이의제기·관리자 조치뿐인 사후 대응이고, 생성물은 공개 캐릭터 썸네일·상황
  이미지로 바로 흐를 수 있다. 부적절한 이미지가 신고될 때까지 공개될 수 있다는 뜻이고, 의도적으로
  수용한 리스크다. 문제가 실제로 나타나면 그때 사전 필터를 다시 연다.
- **스테이징 환경 없음**: main push → 바로 prod. 대신 BE는 태그 한 줄 롤백(§3-1), FE는 Pages 이전
  배포로 롤백 가능 → 문제 시 1순위는 롤백, fix는 그 다음.
- **Pages 프리뷰에서는 API 연동 확인 불가**: `CORS_ALLOW_ORIGINS`가 prod 두 도메인만 허용해 PR
  프리뷰(랜덤 서브도메인)에서 CORS로 막힌다. 필요해지면 완화.
- **즉시 롤백 스위치(옛 스택)는 없다.** 인프라 장애 복구는 "VM 재구축 → compose → R2 백업 복원"이고
  시간이 걸린다.

---

## 7. SEO 운영

web은 순수 클라이언트 SPA라 크롤러가 빈 `<head>`를 본다. `apps/web/worker/`(Pages Advanced Mode
`dist/_worker.js`)가 **봇 UA에만** 완성된 `<head>`를 주입하고 `/sitemap.xml`·`/robots.txt`·`/og/*`
프록시를 제공한다. 선행 조건은 §2-3의 Worker 런타임 변수다.

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
