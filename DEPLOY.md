# 배포 런북 — GCE VM (BE) + Cloudflare Pages (FE) + R2

> **현행 스택만 적는다.** Cloud Run · Neon · Upstash 시절 기록은 2026-09-07에 걷어냈다
> (그 인프라는 2026-09-02에 삭제됐다). 옛 서술이 필요하면 git 이력에 있다.

## 0. 스택

| 컴포넌트 | 서비스 | 주소 |
|---|---|---|
| BE (FastAPI + Postgres + Redis + Caddy) | **GCE VM** `ddona-api` (`asia-northeast3-a`, e2-highcpu-4) | `https://api.ddona.site` |
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
| VM | `ddona-api` / `asia-northeast3-a` / e2-highcpu-4 / Ubuntu 24.04 / 30GB |
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
| VM 사양 | **e2-highcpu-4**(2026-10-04 e2-medium 에서 변경) | 동시 채팅 300명 부하 측정에서 e2-medium 은 공유 코어 한도(지속 용량 1코어분)에 걸려 버티지 못했고, e2-highcpu-4 + 워커 4 + 풀 10+7 이 통과했다. 메모리는 둘 다 4GB 라 그대로 충분했다. 무료 체험 크레딧이 끝나면 실요금(월 약 12만 원)이 나가므로 체험 종료 전에 사양을 다시 판단한다 |
| `/health` vs `/ready` | **둘 다 둔다** | `/health`는 얕아야 한다(Caddy·compose healthcheck·배포 검증이 의존) — DB·Redis를 건드리지 않고 프로세스 생존과 컨테이너 안 드레인 플래그 파일(`/tmp/draining`)만 본다. 플래그가 서면 503이 되어 Caddy가 그 색을 업스트림에서 뺀다("BE → GCE VM" 절의 blue/green 교체). 자원 장애 감지는 `/ready`가 맡고, 외부 업타임 감시도 `/ready`를 본다 — 그래서 교체 중 드레인 503은 외부 경보로 이어지지 않는다 |
| 이미지 생성 → 집 PC 경로 | **Cloudflare Tunnel + Access 서비스 토큰** | VM에 데몬·컨테이너 네트워크 변경·키 로테이션이 필요 없다. 생성 직렬화("이미지 생성" 절)가 매 HTTP 호출을 생성 1건으로 묶어 두므로 엣지 요청 제한에 다가가지 않는다. 체크포인트 스왑을 도입하면 그 전제가 깨져 Tailscale로 돌아간다. **요청 본문 크기 상한은 참조 상한보다 크다** — 참조 이미지를 실으면 요청 하나가 base64 최대 8,000,000자(약 8MB)를 싣는다. 실측(2026-09-29 KST, 운영 VM → Tunnel/Access → 집 PC, 측정 방법은 "참조 이미지 켜기 · 끄기 · 롤백" 절): 실제 생성 이미지 참조 126,056자 → `200 image/webp`(14:11:06→14:11:37), 무작위 1400×1400 PNG 7,852,932자 → `200 image/webp`(14:11:38→14:11:51), Cloudflare `413`·HTML 오류 없음. 서버팀 확인: cloudflared 설정에 본문 크기 제한이 없고 집 PC 서버 앱도 본문 전체 제한 없이 필드 단위로만 검증하므로, 경로 상한은 Cloudflare 플랜 기본값(Free·Pro 100MB)이다 |

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

**업로드는 임시 접두사를 거친다.** 서명 URL은 `uploads/tmp/{purpose}/{id}{ext}`를 가리키고,
`POST /assets/{id}/complete`가 그 객체를 내려받아 크기·디코드를 검사한 뒤 **같은 바이트**를
`assets/{purpose}/{id}{ext}`(DB의 `storage_key`)에 올리고 임시 객체를 지운다. 완료 뒤에도 서명 URL은 남은
시간 동안 살아 있지만 임시 키만 가리키므로 검사가 끝난 원본을 덮을 수 없다. 완료되지 않은 업로드와 삭제에 실패한
임시 객체는 `uploads/tmp/`에 남는다. CORS 규칙은 접두사 조건이 없어 바꿀 필요가 없다.

**`uploads/tmp/`에는 1일 만료 수명 규칙이 걸려 있다**(2026-10-02 19:07 UTC 적용, 규칙 이름 `expire-upload-tmp`,
접두사 `uploads/tmp/`, 1일 뒤 만료). 버킷에 원래 있던 "Default Multipart Abort Rule"은 그대로 두었다. 이 접두사는
`assets/`·`backup/`과 겹치지 않아 자산·DB 백업에 닿지 않는다. 확인·되돌리기는 `apps/web`에서:

```sh
pnpm exec wrangler r2 bucket lifecycle list ai-chracter-chat
pnpm exec wrangler r2 bucket lifecycle add ai-chracter-chat expire-upload-tmp uploads/tmp/ --expire-days 1   # 적용에 쓴 명령
pnpm exec wrangler r2 bucket lifecycle remove ai-chracter-chat --name expire-upload-tmp   # 되돌리기
```

`lifecycle set --file`은 **설정 전체를 바꿔** 기존 규칙(버킷 기본 규칙 포함)을 지울 수 있으니 쓰지 않는다 —
규칙을 더하거나 뺄 때는 하나씩 다루는 `add`/`remove`를 쓴다.

### 1-2. Gemini

Google AI Studio에서 발급한 키 1개(`GEMINI_API_KEY`)를 채팅에 쓴다. 이미지 생성은 Gemini가 아니라
집 PC의 자가 호스팅 추론 서버다 — "이미지 생성" 절.

**판정·발행 심사 모델 스위치** — 구조화 호출 가운데 판정(스탯·엔딩·그림 매칭 따로)과 발행 심사만
`GEMINI_STAT_JUDGMENT_MODEL_NAME`·`GEMINI_ENDING_JUDGMENT_MODEL_NAME`·`GEMINI_IMAGE_JUDGMENT_MODEL_NAME`·
`GEMINI_PUBLISH_FILTER_MODEL_NAME`("BE 런타임" 절 표)로 따로 돌릴 수 있다. 어느 호출이 어느 쪽인지는
`apps/api/src/api/llm/client.py` 의 `STAT_JUDGMENT_CALL_SITES`·`ENDING_JUDGMENT_CALL_SITES`·
`IMAGE_JUDGMENT_CALL_SITES`·`PUBLISH_FILTER_CALL_SITES` 가 정한다(기억 요약·생성은 늘 `GEMINI_MODEL_NAME`).
판정·심사 호출에는 사고 설정을 넘기지 않는다(전용 사고 예산 키 없음). 판정 실패는 채팅에서 조용히 흡수되므로,
모델을 바꾼 뒤에는 아래 집계(또는 어드민 사용량 화면의 판정 비율)에서 바꾼 종류의 판정 call_site 호출 수가
생성(`chat_generate`·미리보기는 `preview_generate`) 대비 급락하지 않는지 본다. 전환 당일에는 같은
call_site 가 옛·새 모델 두 행으로 나뉘어 각 행의 비율이 낮아 보인다 — 두 행을 더해 본다. 단 집계가 잡는
것은 응답을 못 받은 실패(없는 모델명·429 등)뿐이다 — 응답은 왔는데 스키마로 파싱되지 않는 실패는 토큰이
이미 과금된 호출이라 집계에 정상 호출과 똑같이 더해진다. 그건 Bugsink 에서 본다: 판정 쪽은
`dependency=gemini` 태그 이벤트 가운데 메시지가 `Gemini structured response could not be parsed` 로
시작하는 것(같은 태그에 생성 실패·API 오류도 섞인다), 발행 심사 쪽은 흡수되지 않고 발행이 500 으로 나가므로
`dependency` 태그 없는 처리되지 않은 `LLMClientError` 이벤트(메시지는 같다)다. 안전 기준에 막힌 응답은
여기 잡히지 않는다 — 판정 쪽은 메시지가 `Gemini blocked the structured prompt via safetySettings`(또는
`… structured output …`)인 이벤트로, 발행 심사 쪽은 발행 400 과 API 로그의 `publish_filter_blocked` 경고
줄로만 남고 Bugsink 이벤트는 없으니, 새 모델이 더 많이 막는지는 파싱 실패 수로 알 수 없다. 되돌리기는 env 줄을
지우거나 값을 비우고 `sudo bash ops/swap-api.sh`("env 반영 재기동" 절).

**사용량 집계** — 호출마다 call_site·실제 모델별 호출 수와 토큰(입력·캐시 적중·출력·사고·합계, 입력
토큰이 비어 온 호출 수)을 Redis 해시 `llm_usage:{KST 날짜}`에 더한다(보존 400일, 사용자·방 단위 없음).
`gemini_usage` 로그 줄과 달리 배포를 넘겨 남는다(운영 Redis 는 AOF + named volume). 읽기 전용 표:

```sh
cd /opt/ddona/app && sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env \
  exec -T api_$(sudo bash ops/active-color.sh) python scripts/llm_usage_report.py --days 7          # 기간 합계
# --from/--to(KST 날짜) · --by-day(날짜별) · --call-site · --model 로 좁힌다
```

Redis 가 느리거나 죽어 있으면 기록은 100ms 안에 포기하고 그 호출만 빠진다(채팅·발행은 그대로) —
경고 로그 `llm_usage 기록 실패` 와 Bugsink `dependency=redis` 이벤트로 보인다.

### 1-3. Google OAuth (로그인)

옛 GCP 프로젝트 `ai-character-chat-501906`의 OAuth 2.0 Client ID(Web application)를 그대로 쓴다.

- **Authorized redirect URI**: `https://api.ddona.site/auth/google/callback`
- ⚠️ **FE 도메인은 OAuth 설정에 등장하지 않는다.** `redirect_uri`는 `api_base_url`에서만 조립되고
  (`auth/google_oauth.py`의 `callback_redirect_uri`), FE는 Google에 직접 요청하지 않으므로 Authorized
  JavaScript origins도 필요 없다. FE 도메인이 바뀔 때 실제로 고칠 값은 콜백 뒤 돌려보낼 목적지인
  `FRONTEND_BASE_URL`이다.
- OAuth state는 **Redis**(`store_oauth_state`)에 두고, 로그인을 시작한 브라우저에도 같은 값을 HttpOnly
  쿠키(`oauth_state_google`, `Path=/`)로 심어 콜백에서 대조한다(`auth/oauth_common.py`의
  `resolve_oauth_state`). 가입 대기 토큰도 URL이 아니라 HttpOnly 쿠키(`oauth_pending_google`)로 내린다.

### 1-4. 카카오 로그인

카카오 디벨로퍼스 앱 하나를 쓴다. 콘솔 설정 요약:

- **카카오 로그인 사용**: 켬. **OpenID Connect**: 끔(우리는 `id_token` 을 쓰지 않는다).
- **동의항목**: 카카오계정(이메일) `account_email` 만. 프로필 항목은 받지 않는다.
- **Redirect URI**: `https://api.ddona.site/auth/kakao/callback` (dev 용 tailscale 오리진 3벌의
  `…/api/auth/kakao/callback` 도 함께 등록돼 있다 — `DEV.md`). FE 도메인은 구글과 같은 이유로 등장하지 않는다.
- **클라이언트 시크릿**: 켬(토큰 교환에 필수로 싣는다). PKCE 는 쓰지 않는다 — 카카오가 `code_verifier` 를
  검증하지 않는 것을 실측했다(`auth/kakao_oauth.py` 모듈 docstring).
- 신규 가입은 인증된 이메일만 받는다. 카카오가 이메일을 주지 않거나 미인증·무효면 로그인 화면으로
  `?error=kakao_email_required` 와 함께 돌아간다. 회원번호로 찾은 기존 회원은 이메일 상태와 무관하게
  로그인된다(가입 뒤 이메일 동의를 철회해도 막히지 않는다). 같은 이메일의 기존 계정(이메일·구글)에 **자동 연동하지 않고**
  `?error=kakao_email_taken&method=…` 로 원래 가입 수단을 안내한다(이메일 인증을 마치지 않은 가입 기록만
  카카오 가입이 대체한다).
- state·가입 대기 토큰은 구글과 같은 방식이다(Redis + HttpOnly 쿠키 `oauth_state_kakao`·`oauth_pending_kakao`, `Path=/`).
- **연결 해제 웹훅**: 배포 **후** 콘솔 [앱] > [웹훅] > [연결 해제 웹훅]에 `https://api.ddona.site/auth/kakao/unlink`
  를 등록한다(메서드는 GET·POST 둘 다 받는다). 웹훅이 오면 우리 탈퇴와 같은 파기(1년 재가입 차단 기록 포함)를 한다.
  - 카카오는 `Authorization: KakaoAK {대표 어드민 키}` 로 인증해 보낸다. 그래서 **`KAKAO_ADMIN_KEY` 는 Primary(대표)
    어드민 키여야 한다** — 다른 어드민 키를 넣거나 콘솔에서 키를 재발급·교체하고 VM 값을 안 바꾸면 웹훅이 전부 401 이
    되고 연결 해제가 조용히 유실된다.
  - 🔴 **연결 해제 웹훅은 재전송이 없다.** 3초 안에 200 을 못 주거나 API 가 내려가 있던 동안의 연결 해제는 다시 오지
    않는다(배포 재기동 창 포함). 오래 실패가 이어지면 카카오가 웹훅을 [일시 중지]로 돌리고 앱 멤버에게 메일을 보낸다 —
    그 메일을 받으면 원인을 고친 뒤 콘솔에서 [사용함]으로 되돌린다.
- 우리 쪽 탈퇴(`DELETE /me`)는 커밋 뒤 `KAKAO_ADMIN_KEY` 로 연결 끊기 API 를 부른다(실패해도 탈퇴는 성공, 로그·Bugsink
  `kakao_oauth` 태그로 남는다). 서비스가 직접 끊은 연결에는 카카오가 웹훅을 보내지 않는다.

---

## 2. 환경변수

### 2-1. BE 런타임 — VM의 `/opt/ddona/.env` (root, 0600)

**52개 키다**(2026-10-06 VM 실측, 키 이름만 셈): 아래 표 92개 중 38개(생략 가능한 `LOCAL_IMAGE_TIMEOUT_SECONDS`·
`LOCAL_IMAGE_CAPABILITIES_TTL_SECONDS`·`LOCAL_IMAGE_QUEUE_LIMIT`·`EXPOSE_API_DOCS`·`GEMINI_IMAGE_JUDGMENT_MODEL_NAME`·`GEMINI_PUBLISH_FILTER_MODEL_NAME`·`GEMINI_THINKING_BUDGET`·`MEMORY_WINDOW_*` 3개·`GEMINI_*_TIMEOUT_MS` 5개·`GEMINI_NOVELIZE_*` 7개·소설화 조정용 `NOVELIZE_*` 19개, 실측 때 넣지 않은 상위 모델 키 13개(`BEDROCK_*` 9개·`CHAT_PREMIUM_*` 2개·`NOVELIZE_PREMIUM_*` 2개), 모두 54개 제외 —
소설화를 켤 때 넣는 `NOVELIZE_ENABLED`·`NOVELIZE_GRANT_ALLOWLIST` 2개는 운영에서 켜 두었으므로 셈에 들어간다) + compose용
5개(그때는 `API_IMAGE`·`SITE_ADDRESS`·`POSTGRES_PASSWORD`·`POSTGRES_DB`·`DDONA_ENV_FILE` — api 가 blue/green 두 색으로 나뉜 뒤
compose 가 읽는 이미지 키는 `API_IMAGE_BLUE`·`API_IMAGE_GREEN` 둘이고 `API_IMAGE` 는 읽지 않는다. 두 키가 생기고 옛 줄이 지워지면
6개가 되므로 그때 아래 명령으로 다시 센다) + "Bugsink(에러 트래커)" 절의 6개
(`BUGSINK_*` 3개·`INGEST_SHARED_SECRET`·`SENTRY_DSN`·`SENTRY_ENVIRONMENT`) + 크론 알림 3개
(`DISCORD_WEBHOOK_URL`·`HEALTHCHECKS_BACKUP_PING_URL`은 "백업 · 복원" 절, `HEALTHCHECKS_RESOURCE_PING_URL`은 "VM 리소스 감시" 절). `apps/api/.env`는 **로컬 개발용이며 배포와 무관하다.**
이 수는 날짜가 붙은 실측값이라 VM에 키를 넣거나 빼면 낡는다 — 그때 VM에서 다시 세어 이 문장을 고친다
(예: `sudo grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' /opt/ddona/.env | sort -u | wc -l`). 키 개수는 이 문장 한 곳에만 적는다.

| 변수 | 값 | 비고 |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:…@postgres:5432/ai_character_chat` | 컨테이너 간 통신, SSL 없음 |
| `REDIS_URL` | `redis://redis:6379/0` | 컨테이너 |
| `API_BASE_URL` | `https://api.ddona.site` | OAuth redirect_uri 조립 |
| `FRONTEND_BASE_URL` | `https://ddona.site` | OAuth 콜백 뒤 돌려보낼 목적지 |
| `CORS_ALLOW_ORIGINS` | `https://ddona.site,https://admin.ddona.site` | **쉼표 구분**(공백 없이). 예전 표기인 JSON 배열(`["https://a","https://b"]`)도 같은 리스트로 읽히지만 큰따옴표가 아래 "env 파일 형식" 에 어긋난다 |
| `SESSION_COOKIE_SECURE` | `true` | HTTPS 필수 |
| `SESSION_COOKIE_SAMESITE` | `lax` | FE·BE가 같은 등록가능 도메인이라 가능 |
| `GEMINI_API_KEY` | AI Studio 키 | 채팅 |
| `GEMINI_MODEL_NAME` | `gemini-3.5-flash-lite`(코드 기본값은 `gemini-2.5-flash`) | 2026-09-24부터 프로덕션에 명시. 되돌리려면 이 한 줄만 지우고 `sudo bash ops/swap-api.sh`("env 반영 재기동" 절) — `.env` 백업을 통째로 복원하지 말 것(교체 스크립트가 같은 파일의 `API_IMAGE_BLUE`·`API_IMAGE_GREEN`을 고친다) |
| `GEMINI_STAT_JUDGMENT_MODEL_NAME` / `GEMINI_ENDING_JUDGMENT_MODEL_NAME` / `GEMINI_IMAGE_JUDGMENT_MODEL_NAME` | 기본 비어 있음 | 판정 호출(실채팅·미리보기)을 종류별로 다른 모델로 돌리는 스위치 — 스탯 / 엔딩 / 그림 매칭(상황 이미지·미디어 북 칸). 줄이 없거나 값이 비면(`KEY=`) `GEMINI_MODEL_NAME`(지금 동작). 어느 호출이 어느 종류인지와 확인 방법은 "Gemini" 절 |
| `GEMINI_PUBLISH_FILTER_MODEL_NAME` | 기본 비어 있음 | 발행 심사만 따로 바꾸는 같은 꼴의 스위치. ⚠️ 심사는 실패하면 발행이 500으로 막히므로(fail-closed) 바꾼 직후 발행 1회로 확인한다. 바꾸면 무변경 재발행도 한 번씩 다시 심사한다(통과 기억이 실제 심사 모델에 묶인다) |
| `GEMINI_THINKING_BUDGET` | 기본 비어 있음 | 채팅 생성의 사고 예산(비면 사고 설정을 넘기지 않음, `0` = 끔). ⚠️ `gemini-3.5-flash-lite` 는 `0` 을 400 으로 거부했다(2026-10-02, 구조화 호출에서 실측 — 스트리밍 생성은 측정하지 않았다) — 그 모델에 `0` 을 넣지 않는다 |
| `GEMINI_GENERATE_TIMEOUT_MS` | 설정 안 함(기본 `45000`) | 채팅·미리보기 생성 호출의 타임아웃(ms). 스트리밍이라 "다음 청크까지"의 상한이다. 시간 초과는 다른 네트워크 실패와 같다 — 오류 이벤트로 끝나고 채팅은 차감한 클로버를 돌려준다. 정상 생성이 잘리면(Bugsink 에서 `LLMClientError` 중 timeout 문구가 늘면) 값을 키워 넣고 `sudo bash ops/swap-api.sh` |
| `GEMINI_JUDGMENT_TIMEOUT_MS` | 설정 안 함(기본 `20000`) | 판정 호출(스탯·엔딩·그림 매칭, 미리보기 포함)의 타임아웃(ms). 시간 초과는 판정 실패와 같아 그 턴의 판정만 건너뛴다(엔딩 판정은 `gemini_usage` 줄 없이 "판정 실패" 로그만 남는다). 판정 윈도우 두 스위치를 끄면 긴 방의 판정 입력이 대화 전체가 되어 이 값에 걸릴 수 있다 |
| `GEMINI_MEMORY_SUMMARY_TIMEOUT_MS` | 설정 안 함(기본 `60000`) | 기억 요약 접기 호출의 타임아웃(ms). 턴 뒤 background 라 사용자가 기다리지 않고, 실패는 백오프 뒤 다시 한다 |
| `GEMINI_PUBLISH_FILTER_TIMEOUT_MS` | 설정 안 함(기본 `60000`) | 발행 심사 호출의 타임아웃(ms). 시간 초과는 거부가 아니라 503 `PUBLISH_SCREENING_UNAVAILABLE`("잠시 뒤 다시 발행")이다 — 이의제기 대상이 생기지는 않지만, 시간당 심사 횟수는 호출 앞에서 세므로 한 번을 쓴다 |
| `GEMINI_CLIENT_TIMEOUT_MS` | 설정 안 함(기본 `60000`) | 클라이언트 기본 타임아웃(ms). 모든 호출이 위 값 중 하나를 요청에 싣고 이것은 빠진 호출의 안전망이다. 재시도는 하지 않는다. 턴 락 TTL(60초)은 생성 + 판정 상한의 합보다 짧을 수 있다 — 넘친 턴은 해제 때 경고만 남는다 |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | OAuth 자격증명 | "Google OAuth" 절 |
| `KAKAO_REST_API_KEY` / `KAKAO_CLIENT_SECRET` | 카카오 로그인 자격증명 | "카카오 로그인" 절. 둘 중 하나라도 비면 카카오 로그인 시작이 `?error=kakao_failed` 로 돌아온다 |
| `KAKAO_ADMIN_KEY` | 카카오 **Primary(대표)** 어드민 키 | "카카오 로그인" 절. 탈퇴 시 연결 끊기 + 연결 해제 웹훅 인증. 비면 웹훅은 전부 401, 연결 끊기는 경고 로그만 |
| `WITHDRAWN_EMAIL_HMAC_KEY` | `openssl rand -hex 32` 등으로 발급한 무작위 값 | 탈퇴 재가입 차단용 HMAC 키. **한번 정하면 바꾸지 말 것** — 바뀌면 과거에 적립한 해시와 새 조회의 해시가 어긋나 재가입 차단이 조용히 멈춘다(모든 조회가 미스가 된다. 에러가 나지 않아 알아채기 어렵다) |
| `LOCAL_IMAGE_BASE_URL` | 집 PC 서버를 가리키는 터널 origin | **이미지 생성 필수** — 비어 있으면 capabilities가 전부 불가로 내려가 생성이 사전 차단된다. "이미지 생성" 절 |
| `LOCAL_IMAGE_ACCESS_CLIENT_ID` / `LOCAL_IMAGE_ACCESS_CLIENT_SECRET` | Cloudflare Access 서비스 토큰 | **이미지 생성 필수**. "이미지 생성" 절 |
| `LOCAL_IMAGE_MODEL_WIRE_ID` | 집 PC가 보고하는 **실제** 모델 id | **이미지 생성 필수.** 기본값은 공개 id(`v1`)와 같아 로컬·테스트는 설정 없이 돌지만, 운영에서 집 PC의 값과 다르면 교차 검증에서 전부 걸러져 생성이 사전 차단된다. **이 값을 소스에 두지 않는 것이 요점이다**("이미지 생성" 절) |
| `LOCAL_IMAGE_TIMEOUT_SECONDS` | 기본 `90` | 안전한 기본값 — 보통 생략. 근거는 "이미지 생성" 절의 실측치 |
| `LOCAL_IMAGE_CAPABILITIES_TTL_SECONDS` | 기본 `30` | 안전한 기본값 — 보통 생략 |
| `LOCAL_IMAGE_QUEUE_LIMIT` | 기본 `4` | 안전한 기본값 — 보통 생략 |
| `LOCAL_IMAGE_REFERENCE_ENABLED` | `true`(코드 기본값은 `false`) | 본인이 만든 생성 이미지를 참조로 집 PC에 싣는 기능의 스위치. **운영에서 켜져 있다**(2026-09-29부터). 끄면(`false` 또는 줄 삭제) 생성 화면에 참조 행이 안 뜨고, 참조를 실은 요청은 `400 reference image disabled`로 거절·환불된다. 켜는 조건·켜기·끄기·롤백은 "참조 이미지 켜기 · 끄기 · 롤백" 절. 줄을 지우면 위 키 개수 문장을 다시 센다 |
| `EXPOSE_API_DOCS` | 기본 `false` | 안전한 기본값(닫힘) — **운영에서는 절대 켜지 않는다.** 켜면 `/docs`·`/openapi.json`이 열려 이미지 모델의 불투명 id 은닉("이미지 생성" 절)이 무의미해진다 |
| `S3_ENDPOINT_URL` | `https://<accountid>.r2.cloudflarestorage.com` | R2 |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | R2 API 토큰 키쌍 | boto3가 프로세스 env로 읽는다 |
| `AWS_REGION` | `auto` | R2 규약 |
| `S3_BUCKET_NAME` | `ai-chracter-chat` | 기본값이 dev용이라 override 필수 |
| `EMAIL_PROVIDER` | `resend` | 미설정 시 `console`(발송 안 함) |
| `RESEND_API_KEY` | `re_...` | Resend API 키 |
| `EMAIL_FROM` | `noreply@ddona.site` | `ddona.site` 도메인이 Resend에서 검증돼야 한다 |
| `FORWARDED_ALLOW_IPS` | `172.18.0.0/16` | **uvicorn이 직접 읽는 env**(pydantic 설정 아님). ⚠️ **`*`를 쓰지 말 것** — uvicorn `proxy_headers.py`는 `*`(always_trust)일 때 `X-Forwarded-For` 체인의 **맨 앞** 값을 그대로 쓰는데, Caddy는 실제 IP를 **뒤에 덧붙이므로** 클라이언트가 보낸 위조 헤더가 채택된다(IP rate limit을 헤더 한 줄로 우회 가능). 대역을 주면 체인을 **역순**으로 훑어 신뢰 대역 밖 첫 값(=Caddy가 붙인 진짜 IP)을 고른다. 값은 `ddona_default`의 실측 subnet이며, 단일 IP 대신 대역인 이유는 컨테이너 재생성 시 도커가 IP를 재배정하기 때문이다. 실측: 프로덕션 uvicorn 액세스 로그의 클라이언트 IP가 `127.0.0.1`(헬스체크)과 `172.18.0.3`(`ddona-caddy-1` 컨테이너) 둘뿐이었다 — 실사용자 전원이 한 IP로 보인다. 원인은 uvicorn이 `forwarded_allow_ips` 미지정 시 `127.0.0.1`로 떨어뜨려 도커 브리지의 Caddy가 보낸 `X-Forwarded-For`를 신뢰하지 않는 것이다. 이게 없으면 IP 기반 rate limit이 전 사용자 공유 버킷이 된다. **api 컨테이너가 호스트에 포트를 게시하지 않는 것은 이 위협을 막지 못한다** — 포트 미게시가 막는 것은 "uvicorn에 직접 TCP로 붙어 peer 주소를 위장하는" 쪽이고, `*`가 여는 것은 "평범한 사용자로서 Caddy를 통과하는 정상 HTTPS 요청에 `X-Forwarded-For: 1.2.3.4` 한 줄을 얹는" 쪽이라 api 컨테이너에 직접 닿을 필요가 없다(`Caddyfile`의 api 라우트는 두 색을 업스트림으로 든 `reverse_proxy api_blue:8000 api_green:8000` 블록 하나뿐이고(`/_ingest/*`만 `handle_path`로 bugsink에 따로 간다) `trusted_proxies`도 `header_up X-Forwarded-For` 덮어쓰기도 없어 클라이언트가 보낸 체인이 보존된 채 실제 IP가 뒤에 붙는다). 실측 반증: 대역 설정 상태에서 `X-Forwarded-For: 1.2.3.4`를 얹어 보냈지만 로그에는 실제 공인 IP가 찍혔다 — `*`였다면 `1.2.3.4`가 찍혔을 것이다(2026-09-12). 부수효과: `guardian_consents.ip_address`도 이때부터 진짜 IP가 된다(기존 저장값은 전부 프록시 IP다) |
| `WEB_CONCURRENCY` | **운영 `4`**(기본 `1`) | **uvicorn이 직접 읽는 env**(pydantic 설정 아님) — 워커 프로세스 수. Dockerfile CMD 에 `--workers` 가 없어서 이 값이 기본값이 된다(`--workers` 를 CMD 에 쓰면 이 env 가 무시된다). 워커는 앱을 각자 새로 import 하므로 DB 풀·메모리(1프로세스 약 190MB)·Redis 장애 보고·집 PC capabilities 프로브가 워커 수만큼 늘어난다. 이미지 생성 직렬화·대기열은 Redis 에 있어 워커 수와 무관하다. 올릴 때 아래 풀 크기를 함께 줄인다. 운영 값 4 는 동시 채팅 300명 부하 측정을 통과한 조합이다 |
| `DB_POOL_SIZE` | **운영 `10`**(기본 `5`) | 워커 하나의 SQLAlchemy 풀 상시 크기(1 이상). 기본값은 이 설정이 생기기 전과 같다. ⚠️ **2 × 워커 수 × (`DB_POOL_SIZE` + `DB_MAX_OVERFLOW`) ≤ 170** — blue/green 교체 중에는 옛 색이 드레인하는 동안 새 색도 떠 있어 두 색의 풀이 함께 열린다. Postgres `max_connections` 200 에서 크론·백업·배포 마이그레이션·관리 접속 몫 30 을 남긴다(앱 DB 사용자가 슈퍼유저라 예약 연결이 관리 접속을 따로 지켜 주지 않는다). 운영 값은 2 × 4 × (10 + 7) = 136 ≤ 170 이고, 한 색만 떠 있는 평소에는 68 이다. 200 은 Postgres 기본값이 아니라 운영에서 따로 올린 값이다 — 설정·확인·되돌리기와 볼륨을 새로 만들 때 다시 넣는 법은 "겹침 대비 운영 설정" 절 |
| `DB_MAX_OVERFLOW` | **운영 `7`**(기본 `10`) | 풀이 다 찼을 때 잠깐 더 여는 연결 수. 위 식에 들어간다 |
| `DB_POOL_TIMEOUT` | **운영 `30`**(기본값과 같다) | 풀이 다 찼을 때 연결을 기다리는 초. 넘기면 그 요청이 500 이다 |
| `IMAGE_DECODE_CONCURRENCY` | **운영 `1`**(기본 `3`) | 워커 하나에서 동시에 도는 이미지 디코드·블러·변형 생성 건수 상한(1 이상, 넘치면 기다린다). 기본값은 이 설정이 생기기 전과 같다. ⚠️ 워커마다 따로 세므로 **워커 수 × 이 값 × 건당 최대 메모리 ≤ VM 가용 메모리의 절반**으로 정한다 — 건당 최대 메모리는 픽셀 상한 9M 그림의 블러·변형 생성 실측 피크 약 217MB 다. 운영 값 1 은 워커 4 × 1 × 약 217MB ≈ 868MB 가 부하 중 가용 메모리의 절반(약 950MB) 안에 드는 값이고, 2 면 넘는다. `WEB_CONCURRENCY` 를 올릴 때 함께 본다 |
| `MEMORY_WINDOW_GENERATION` | 설정 안 함(기본 `true`) | 긴 방의 생성 프롬프트에서 요약이 덮은 메시지를 빼는 히스토리 윈도우. `false` 면 전체 히스토리를 싣는다 — 요약 품질 사고 때 재기동만으로 예전 동작으로 돌아가는 스위치이고, 끄면 아래 두 판정 스위치도 무시된다 |
| `MEMORY_WINDOW_ENDING_JUDGMENT` | 설정 안 함(기본 `true`) | 엔딩 판정에도 윈도우를 씌운다(요약이 덮은 원문 대신 현재 요약을 싣는다). `false` 는 판정 품질 사고 때 되돌리는 용도다 — 끄면 판정이 대화 전체를 실어 긴 방에서 토큰 원가·지연이 턴 수만큼 늘고 판정 타임아웃·컨텍스트 한도에 닿을 수 있다. 되돌리기는 VM `.env` 에 `MEMORY_WINDOW_ENDING_JUDGMENT=false`·`MEMORY_WINDOW_IMAGE_JUDGMENT=false` 두 줄을 추가 → 아래 형식 검사 → `sudo bash ops/swap-api.sh`(`restart` 는 env 를 다시 읽지 않는다 — "env 반영 재기동" 절). 넣으면 위 VM 키 수를 다시 센다 |
| `MEMORY_WINDOW_IMAGE_JUDGMENT` | 설정 안 함(기본 `true`) | 그림 매칭 판정 — 캐릭터 상황 이미지와 스토리 미디어 북 칸 둘 다 — 에도 윈도우를 씌운다(최근 원문만 싣고 요약은 싣지 않는다). 미디어 북 칸 판정은 엔딩 뒤·재생성까지 매 턴 돌아 끄면 가장 크게 늘어난다. 끄는 법·주의는 위와 같다 |
| `NOVELIZE_ENABLED` | 켤 때 `true`(코드 기본값은 `false`) | 소설화(대화를 장편 소설의 장으로 옮겨 쓰기) 전역 스위치. 쓰려면 이 스위치·아래 명단·어드민이 준 계정별 허용 셋이 모두 있어야 한다 — 코드 기본값이 닫힘이라 이 줄 없이 배포하면 닫힌 채 뜬다. 끄면 재기동 뒤 모든 소설 화면·API 가 403 이고 허용 행은 남는다(다시 켜면 그대로 돌아온다). 켜기·끄기·회수·롤백은 "소설화 켜기 · 끄기 · 회수 · 롤백" 절 |
| `NOVELIZE_GRANT_ALLOWLIST` | 허용할 수 있는 계정 id, **쉼표 구분**(공백·따옴표 없이) | 어드민이 허용을 줄 때와 사용자가 접근할 때 둘 다 본다 — 명단 밖 계정에는 어드민이 허용을 줄 수 없고(422), 명단에서 빼고 재기동하면 허용 행이 남아 있어도 바로 막힌다. 비면 아무에게도 줄 수 없다(기본값). UUID 가 아닌 항목이 있으면 api 가 기동하지 못한다. 개인정보 처리방침이 소설화를 적기 전에는 운영자 계정만 넣는다 |
| `GEMINI_NOVELIZE_MODEL_NAME` | 설정 안 함(기본값은 `apps/api/.env.example` 주석 줄) | 소설화 장 생성·문단 수정 모델. 장 경계 제안은 이 키가 아니라 `GEMINI_MODEL_NAME` 을 쓴다. 값이 비면 `GEMINI_MODEL_NAME` |
| `GEMINI_NOVELIZE_MAX_OUTPUT_TOKENS` | 설정 안 함(기본값은 `.env.example`) | 장 생성·문단 수정의 출력 상한(사고 토큰 포함). 여기서 잘린 결과는 저장하지 않고 실패·환불하므로, 낮추면 원가만 버린다. 아주 작게 넣고 재기동하면 잘림 → 실패 → 환불 1회를 운영에서 일부러 관측할 수 있다(확인 뒤 줄을 지우고 다시 재기동) |
| `GEMINI_NOVELIZE_THINKING_BUDGET` / `GEMINI_NOVELIZE_THINKING_LEVEL` | 설정 안 함(둘 다 비면 모델 기본 사고) | 소설화 사고 예산(정수) 또는 사고 수준(`MINIMAL`·`LOW`·`MEDIUM`·`HIGH`). ⚠️ **둘 중 하나만** — 둘 다 있으면 api 가 기동하지 못한다(한 요청에 둘을 함께 받으면 거부하는 모델이 있어, 뜬 채로 두면 장마다 실패·환불만 반복한다) |
| `GEMINI_NOVELIZE_CHAPTER_TIMEOUT_MS` / `GEMINI_NOVELIZE_REVISE_TIMEOUT_MS` / `GEMINI_NOVELIZE_BOUNDARY_TIMEOUT_MS` | 설정 안 함(기본값은 `.env.example`) | 장 생성(스트리밍이라 "다음 청크까지") / 문단 수정 / 장 경계 제안(사용자가 화면에서 기다린다)의 타임아웃(ms). 장 생성·문단 수정은 백그라운드 작업이라 Cloudflare 응답 상한(100초)과 무관하다. 장 생성·문단 수정의 시간 초과는 실패·환불이고, 경계 제안(무과금)의 시간 초과는 제안 없이 후보 턴만 보인다 |
| `NOVELIZE_CHAPTER_MAX_TURNS` / `NOVELIZE_CHAPTER_MAX_TURNS_SONNET` / `NOVELIZE_CHAPTER_MAX_TURNS_OPUS` | 설정 안 함(기본 `45` / `20` / `20`) | 생성 한 번(묶음 하나)이 담는 원문 턴(AI 응답) 수의 상한 — 모델마다 따로다. 경계 제안이 이만큼의 후보 턴을 보이고, 생성은 끝 메시지가 이 범위 밖이면 거절한다. 첫 키는 Gemini 값이다(키 이름은 모델이 하나뿐이던 때의 것). 운영 `.env` 에 이 키가 없으면 코드 기본값 `45` 가 그대로 쓰이고, 있으면 그 값이 이긴다 |
| `NOVELIZE_K_MAX_GEMINI` / `NOVELIZE_K_MAX_SONNET` / `NOVELIZE_K_MAX_OPUS` | 설정 안 함(기본 `3` / `1` / `1`) | 묶음 하나가 나뉘는 화 수의 상한(모델별). 화 수는 원문 분량으로 정하고 이 값에서 자른다. 연쇄 생성("남은 대화 한 번에")은 묶음마다 이 상한만큼의 화 값을 미리 받는다 |
| `NOVELIZE_EPISODE_TARGET_CHARS` / `NOVELIZE_SOURCE_RATIO` | 설정 안 함(기본 `5000` / `0.8`) | 화 하나의 목표 길이(공백 포함 글자)와 원문 글자를 본문 글자로 바꾸는 비율. 화 수 = 원문 글자 × 비율 ÷ 목표 길이를 반올림한 값(위 상한에서 자른다) |
| `NOVELIZE_CHAPTER_DAILY_LIMIT` / `NOVELIZE_PROPOSAL_HOURLY_LIMIT` | 설정 안 함(기본값은 `.env.example`) | 같은 시작 메시지에서 하루(KST)에 낼 수 있는 묶음 생성·다시 만들기 작업 수(진행 중·성공만 센다) / 무과금 경계 제안의 시간당 상한. 면제 계정도 똑같이 센다 |
| `NOVELIZE_CHAIN_MAX_BATCHES` / `NOVELIZE_CHAIN_TIMEOUT_MARGIN_SECONDS` | 설정 안 함(기본 `5` / `60`) | 연쇄 생성 한 번이 만드는 묶음 수의 상한(한 번에 묶이는 클로버의 상한이기도 하다) / 연쇄 부모 작업의 전체 시간 상한에 더하는 고정 여유(초). 그 상한은 계획한 묶음 수 × (`NOVELIZE_JOB_TIMEOUT_SECONDS` + `GEMINI_NOVELIZE_BOUNDARY_TIMEOUT_MS` 의 초) + 이 여유다(기본값이면 묶음 5개에 5 × 390 + 60 = 2,010초). 넘으면 부모가 실패하고 아직 쓰지 않은 몫을 환불한다 |
| `NOVELIZE_PREVIOUS_SUMMARIES_MAX_CHARS` / `NOVELIZE_SNAPSHOT_LIMIT` | 설정 안 함(기본 `8000` / `50`) | 다음 묶음 생성에 싣는 지난 화 요약 전체의 글자 상한(넘으면 오래된 화부터 뺀다) / 소설 하나의 스냅샷 개수 상한(닿으면 가장 오래된 복원 직전 자동 스냅샷부터 지우고, 이름 붙인 것만 남았으면 새 저장을 거절한다) |
| `NOVELIZE_HEARTBEAT_INTERVAL_SECONDS` / `NOVELIZE_HEARTBEAT_EXPIRY_SECONDS` / `NOVELIZE_JOB_TIMEOUT_SECONDS` | 설정 안 함(기본값은 `.env.example`) | 소설화 작업의 살아 있음 표시 주기 / 그 표시가 이만큼 끊기면 죽은 작업으로 보고 실패·환불하는 만료 / 작업 하나의 전체 상한(초). 만료는 주기보다 넉넉히 길어야 한다 — 짧으면 DB 가 잠깐 느린 것만으로 살아 있는 작업이 환불되고 결과가 버려진다. "소설화 켜기 · 끄기 · 회수 · 롤백" 절의 대기 시간이 이 값들에서 나온다 |
| `NOVELIZE_MIN_CHAPTER_CHARS` / `NOVELIZE_PREVIOUS_EXCERPT_CHARS` | 설정 안 함(기본값은 `.env.example`) | 화 본문 하나라도 이보다 짧으면 정상 종료여도 그 묶음 생성을 실패·환불하는 하한(글자) / 다음 묶음 생성에 싣는 직전 화 끝 발췌의 목표 길이(글자) |
| `BEDROCK_ACCESS_KEY_ID` / `BEDROCK_SECRET_ACCESS_KEY` | Bedrock 호출만 허용한 전용 IAM 사용자의 액세스 키 쌍 | 상위 모델(Bedrock 의 Claude) 자격. 🔴 R2 용 `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` 와 다른 키이고 그 줄들은 건드리지 않는다 — 앱이 이 두 키를 SDK 에 명시로 넘기며, 비어 있으면 호출 전에 실패한다(R2 키로 내려가지 않게). 아래 상위 모델 스위치가 하나라도 켜져 있는데 비어 있으면 api 가 기동하지 못한다. 넣는 순서는 "상위 모델(Bedrock) — 꺼진 채 배포 · 켜기 · 끄기" 절 |
| `BEDROCK_REGION` | 설정 안 함(기본 `ap-northeast-2`) | 호출 출발 리전. `AWS_REGION`(R2 의 `auto`)과 별개다. 스위치가 켜져 있는데 값만 비우면(`BEDROCK_REGION=`) 기동하지 못한다 |
| `BEDROCK_SONNET_MODEL_ID` / `BEDROCK_OPUS_MODEL_ID` | 설정 안 함(기본값은 `.env.example`) | 실제 모델 id. 새 버전으로 옮길 때 이 값만 바꾸면 방·작업에 저장된 모델 값은 그대로다. 단가표(`apps/api/src/api/llm/pricing.py`)에 없는 id 면 어드민 사용량의 원가가 "단가 없음"으로 빠진다 — 단가를 함께 넣는다 |
| `BEDROCK_CHAT_TIMEOUT_MS` / `BEDROCK_CHAPTER_TIMEOUT_MS` | 설정 안 함(기본 `45000` / `300000`) | 상위 모델 채팅 턴 / 소설 장 생성의 요청 타임아웃(ms). 스트리밍이라 "다음 청크까지"의 상한이다. 재시도는 하지 않는다 |
| `BEDROCK_CHAT_MAX_TOKENS` / `BEDROCK_CHAPTER_MAX_TOKENS` | 설정 안 함(기본 `4096` / `32768`) | 출력 상한. Bedrock 은 요청의 출력 상한만큼 분당 토큰 쿼터를 먼저 잡으므로 올리면 동시 요청이 스로틀되기 쉽다. 장이 잘리면 실패·환불이다 |
| `CHAT_PREMIUM_MODELS_ENABLED` / `CHAT_PREMIUM_MODEL_ALLOWLIST` | 켤 때 `true` / 계정 id **쉼표 구분**(코드 기본값은 꺼짐·빈 명단) | 채팅 상위 모델 스위치와 허용 가능 계정 명단. 뜻은 소설화 스위치·명단과 같다. 켜고 끄는 법은 "상위 모델(Bedrock) — 꺼진 채 배포 · 켜기 · 끄기" 절 |
| `NOVELIZE_PREMIUM_MODELS_ENABLED` / `NOVELIZE_PREMIUM_MODEL_ALLOWLIST` | 켤 때 `true` / 계정 id **쉼표 구분**(코드 기본값은 꺼짐·빈 명단) | 소설 장 상위 모델의 같은 한 벌. 소설화 자체(`NOVELIZE_ENABLED`·`NOVELIZE_GRANT_ALLOWLIST`)도 열려 있어야 쓸 수 있다 |

> **`CORS_ALLOW_ORIGINS`**: `config.py` 가 쉼표 구분과 JSON 배열을 둘 다 받는다(`[` 로 시작하면 JSON). 항목 앞뒤 공백은
> 지우고 빈 항목은 버리며, 남는 오리진이 없으면 기동에 실패한다. 새로 쓸 때는 쉼표 구분으로 쓴다.
> ⚠️ **롤백 순서**: 운영 값을 쉼표 구분으로 바꾼 뒤 쉼표 구분을 받기 전의 이미지로 롤백하려면, **먼저 이 줄을 JSON 배열(바꾸기 전 백업의 값)로
> 되돌리고** 이미지를 바꾼다 — 옛 `config.py` 는 쉼표 구분을 JSON 으로 디코드하다 실패해 api 가 기동하지 못한다.

#### env 파일 형식

`/opt/ddona/.env` 는 파서 넷이 각자 읽는다 — compose `env_file`(앱 컨테이너), compose `--env-file`(compose 파일 보간),
`docker run --env-file`, 크론 스크립트(`ops/*.sh`)의 `grep | cut`. 로컬 `apps/api/.env` 는 python-dotenv(pydantic)와
`uv run --env-file` 이 읽는다. 이들은 따옴표·`$`·`\`·공백·중복 키·`export` 를 서로 다르게 읽어서, 그런 줄이 하나라도
있으면 앱과 크론이 다른 값을 보면서 아무도 실패하지 않는다(uv 는 공백이 든 값에서 그 줄부터 파일 끝까지 버린다).
그래서 운영·로컬 모두 여섯 파서가 같은 값을 주는 표기 하나만 쓴다.

- 한 줄은 빈 줄, `#` 으로 시작하는 주석, `KEY=value` 셋 중 하나다. 키는 대문자로 시작하는 `[A-Z0-9_]`, `=` 앞뒤 공백 없음, `export` 없음.
- 값은 비우지 않는다(값이 없으면 줄을 주석으로). 값에는 공백·탭·따옴표(`"`·`'`)·`$`·`\` 가 없고, `#` 으로 시작하지 않는다.
  목록 값(`CORS_ALLOW_ORIGINS`)은 쉼표로 구분한다.
- 같은 키를 두 번 쓰지 않는다(compose·`docker run` 은 뒤 값, `ops/backup.sh` 는 앞 값, 나머지 크론 스크립트는 두 값을 줄바꿈으로 이어 붙인 값을 쓴다). CR(`\r`) 금지, 파일은 개행으로 끝난다.

**배포가 이 형식을 검사한다.** `deploy-api.yml` 은 `git reset` 직후, `.env` 를 고치거나 compose 를 부르기 전에
`ops/check_env.py --format /opt/ddona/.env` 를 돌리고 위반이면 배포를 멈춘다. 출력은 줄 번호·규칙 이름뿐이고 값도 키 이름도
찍지 않는다(키 자리의 글자가 잘린 비밀값 조각일 수 있다). 키를 고치기 전후에 VM 에서 직접 돌려 본다:

```sh
cd /opt/ddona/app && sudo python3 ops/check_env.py --format /opt/ddona/.env
```

키 이름(오타·누락)은 검사하지 않는다 — 이 파일에는 앱이 읽지 않는 compose·크론·Bugsink 키가 함께 있다.

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
> 것만 브라우저 번들에 들어간다(그래서 `SENTRY_AUTH_TOKEN`에는 절대 붙이지 않는다, "Bugsink(에러 트래커)" 절).
> 2026-09-16 실제로 이 절 제목 때문에 "런타임 입력란을 못 찾겠다"는 혼선이 있었다.

| 변수 | 값 | 없으면 |
|---|---|---|
| `PUBLIC_ORIGIN` | `https://ddona.site` | canonical·og:url·sitemap이 **요청 host를 따라간다** → 프리뷰 배포가 자기 URL로 색인되어 중복 콘텐츠가 된다. **`legacyRedirect`의 목적지이기도 해서** 비어 있으면 옛 도메인 리다이렉트가 통째로 꺼진다(자기 자신으로 가는 루프를 막는 가드) |
| `API_BASE_URL` | `https://api.ddona.site` | Worker가 조회가 필요한 SEO 경로(상세·프로필 메타, sitemap, og 프록시)를 **통째로 건너뛴다**. 사이트는 멀쩡히 돌아서 티가 안 난다 |
| `INGEST_SHARED_SECRET` | VM `/opt/ddona/.env`의 같은 이름 값과 **반드시 일치**해야 한다("Bugsink(에러 트래커)" 절) — ⚠️ **Production에만**, 아래 예외 참고 | `/_ingest/*` 프록시(`worker/ingestProxy.ts`)가 `X-Ingest-Secret` 헤더를 못 붙여 Caddy가 **모든 envelope 요청에 401**을 준다 — 브라우저 에러가 전부 Bugsink에 도착하지 못한 채 소실된다 |

- **`VITE_API_BASE_URL`("FE 빌드타임" 절)과 별개다** — 저건 빌드타임에 번들에 박히고 이건 Worker가 런타임에
  읽는다. **둘 다** 필요하다.
- **Preview에도 `PUBLIC_ORIGIN`은 프로덕션 오리진**을 넣는다(프리뷰 URL이 아니라). Worker는
  `요청 host ≠ PUBLIC_ORIGIN host`일 때만 `X-Robots-Tag: noindex`를 붙이므로(`worker/indexing.ts`),
  Preview에서 비어 있으면 프리뷰 색인 차단이 함께 꺼진다.
- **`INGEST_SHARED_SECRET`은 위 "Production과 Preview 양쪽 모두" 지침의 예외다 — Production에만
  넣는다.** 근거는 "Bugsink(에러 트래커)" 절의 "환경 범위는 Production만이다" 참고.
- 런타임 변수는 **저장만으로 반영되지 않는다** — 저장 후 재배포(또는 최신 배포 Retry)해야 한다.

---

## 3. 배포 절차

### 3-1. BE → GCE VM

**자동배포가 정상 경로다.** `main` push 시 `.github/workflows/deploy-api.yml`이 이미지 빌드 →
Artifact Registry push → IAP SSH로 VM에서 `ops/swap-api.sh <태그>`(아래 blue/green 교체) → 인터넷 쪽 `/health`
확인까지 한다(실측 1분 35초 — api 가 단일 컨테이너이던 시절 값이다. blue/green 교체는 옛 색에 남은 요청이 끝나기를
기다리므로 그만큼 길어질 수 있다).
트리거 경로는 `apps/api/**` · `docker-compose.prod.yml` · `Caddyfile` · 저장소 루트 `ops/**` ·
워크플로 자신이다.
**GitHub Secrets에 넣는 값은 없다** — WIF라 키를 저장하지 않는다.

**api 는 blue/green 두 색으로 교체한다.** compose 에 `api_blue`·`api_green` 두 서비스가 있고 평소에는 한 색만 떠
있다(서빙 중인 색 = active, 비어 있는 색 = idle). Caddy 는 두 색을 고정 업스트림으로 들고 1초마다 각 색의 `/health`를
찔러(능동 헬스체크) 200 을 주는 색에만 요청을 보낸다. 배포·롤백·env 반영 재기동이 모두 `ops/swap-api.sh` 하나를 부르고,
한 번의 교체는 이렇게 흐른다:

1. **잠금** — `/var/lib/ddona/deploy.lock`에 `flock`. 수동 교체와 자동배포가 겹치면 뒤에 온 쪽이 앞 교체가 끝날 때까지
   최대 600초 기다렸다가 이어서 하고, 넘으면 아무것도 안 바꾸고 실패한다. 워크플로의 `concurrency`는 워크플로끼리만
   막아서 이 잠금이 따로 있다 — 없으면 두 교체가 같은 active 를 보고 두 색을 함께 내릴 수 있다.
2. **active 판정** — 상태 파일 `/var/lib/ddona/active_color`(`blue`/`green` 한 줄)와 실제로 떠 있는 색을 함께 본다. 한
   색만 떠 있으면 그 색이다. 둘 다 떠 있으면(중단된 교체의 잔재) 먼저 드레인 플래그를 본다 — 한쪽에만 있으면 그쪽이 내리던 옛
   색이라 플래그 없는 색이 active 다(상태 파일은 교체 맨 끝에만 바뀌어 이 형상에선 늘 옛 색을 가리킨다). 플래그가 없으면 상태
   파일이 가리키는 색, 상태 파일도 못 믿으면 먼저 뜬 색이다.
3. **pull** — 새 이미지를 `.env`를 고치기 **전에** 받는다. 실패하면 아무것도 안 바꾸고 끝난다. VM 에 이미 있는 태그도 다시
   받는다(배포 끝의 이미지 정리가 옛 태그를 지웠을 수 있다).
4. **idle 색 준비** — `.env`의 idle 색 줄(`API_IMAGE_BLUE` 또는 `API_IMAGE_GREEN`)을 새 참조로 바꾸고, 그 이미지로
   `alembic upgrade head`(옛 색이 아직 서빙하는 동안, 새 색 기동 **전** — "DB 마이그레이션" 절의 순서 그대로. DB 가 그
   이미지보다 앞서 있으면 롤백 표시가 있을 때만 건너뛰고 없으면 멈춘다 — 아래 "롤백")를 돌린 뒤
   idle 색을 새 컨테이너로 띄운다(`--force-recreate --wait`). Caddy 로그에 그 색의 `host is up`이 찍히면 합류한 것이다.
   여기까지 어디서 실패하든 idle 색만 지우고 그 줄을 원래 값으로 되돌린 뒤 종료코드 1 로 끝난다 — 옛 색은 손대지 않아
   서비스는 그대로다.
5. **드레인** — active 색 안에 플래그 파일 `/tmp/draining`을 만들어 그 색의 `/health`를 503 으로 바꾼다. Caddy 가 1~2초
   안에 그 색을 업스트림에서 빼면 새 요청은 새 색으로만 간다. 그 뒤 `stop`(정지 유예 `stop_grace_period` 65초 안에서 하던
   요청과 SSE 턴을 마친다) → `rm`. 플래그로 먼저 빼는 이유: 그냥 멈추면 정지 중인 컨테이너로 새 연결이 몰려 매달린다.
6. **마무리** — 내려간 색의 줄도 같은 참조로 맞추고(서비스명 없는 `up -d`가 실수로 그 색을 띄워도 같은 코드가 뜨게)
   상태 파일을 새 색으로 쓴다. 마지막 로그 줄 `13) 완료: active=…`가 찍혀야 끝까지 돈 것이다.

교체 소요 시간은 옛 색에 남은 가장 긴 요청에 비례한다(최대 정지 유예 65초) — 느린 게 아니라 드레인이 기다리는 것이다.
중간에 끊겨 두 색이 다 떠 있으면 같은 명령을 다시 부르면 이어서 끝난다 — 옛 색에 드레인 플래그가 서 있으면 그 색을 마저
드레인·정지하고(같은 태그 재실행이면 거기서 끝), 플래그가 없으면 다시 만들 색을 먼저 드레인해 내린 뒤 교체한다. 어느 쪽도
서빙 중인 색을 드레인 없이 멈추지 않는다. 워크플로 실행 중 SSH 가 끊기면 교체 스크립트가 실패 정리 없이 끝날 수 있는데, 그
형상도 같은 명령(또는 같은 태그의 워크플로 재실행)이 이어서 끝낸다. Caddy 재시도는 기본값 그대로라 업스트림에
연결조차 안 된 요청과 GET 만 다른 색으로 다시 보낸다 — POST 를 넓히면 채팅 메시지가 두 번 처리돼 클로버가 두 번 차감된다.

VM 에서 쓰는 명령 셋(`cd /opt/ddona/app` 에서):

- `sudo bash ops/swap-api.sh [태그]` — 교체. 태그를 생략하면 지금 active 가 쓰는 이미지 그대로 다시 교체한다
  ("env 반영 재기동" 절). root 로 돈다 — 상태·잠금 파일이 root 소유 `/var/lib/ddona/`에 있다. 옛 태그로 되돌리는
  롤백은 `sudo DDONA_ROLLBACK=1 bash ops/swap-api.sh <이전SHA>`(아래 "롤백").
- `sudo bash ops/active-color.sh` — 지금 서빙 중인 색(`blue`/`green`)을 한 줄로 찍는다. 컨테이너 안에서 명령을 돌릴 때
  `exec -T api_$(sudo bash ops/active-color.sh) …`로 쓴다. 아무것도 바꾸지 않지만 compose 가 0600 `/opt/ddona/.env`를
  읽어야 해서 sudo 가 필요하다. 두 색이 다 떠 있으면 드레인 플래그가 선 색(곧 내려갈 색)은 고르지 않는다. 남은 색이 없거나
  둘이고 상태 파일이 그중 하나를 가리키지 않으면(교체 중이거나 중단 잔재) 0 이 아닌 코드로 멈춘다 — 그 명령이 엉뚱한
  컨테이너로 가지 않게 하려는 것이다.
- `sudo bash ops/bootstrap-bluegreen.sh <태그>` — 단일 `api` 형상에서 처음 옮길 때 한 번만 쓴다
  ("단일 api 에서 blue/green 으로 최초 이행" 절).

```sh
# VM 접속 (22번은 인터넷에 안 열려 있다)
gcloud compute ssh ddona-api --zone=asia-northeast3-a --tunnel-through-iap

# 스택 상태 · 로그
cd /opt/ddona/app
sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env ps
cat /var/lib/ddona/active_color   # 상태 파일이 가리키는 색(실제와 대조는 위 ps)
# 두 색을 다 적는다 — 교체 중에는 둘 다 봐야 하고, 떠 있지 않은 색은 조용히 건너뛴다
sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env logs -f api_blue api_green

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

**롤백** — 평상시 배포와 같은 무중단 교체로 이전 태그를 올린다. 둘 중 하나:

```sh
# VM 에서 — 이전 커밋 SHA 앞 7자리. DDONA_ROLLBACK=1 이 롤백 표시다(아래)
cd /opt/ddona/app && sudo DDONA_ROLLBACK=1 bash ops/swap-api.sh <이전SHA>
```

또는 GitHub Actions → `deploy-api` → **Run workflow** 에서 `image_tag`에 이전 SHA 7자리를 넣는다(빌드 없이 레지스트리의 그
태그로 교체한다. 비우면 `main` 최신 커밋을 빌드해 배포한다). 어느 쪽이든 compose·`Caddyfile`·`ops/` 스크립트는 `main`
최신 그대로이고 이미지만 과거 태그다 — 수동 실행도 `git reset --hard origin/main`을 하기 때문이다. 롤백해 둔 동안 무관한 PR
이라도 `main`에 병합되면 자동배포가 새 코드로 다시 교체한다.
되돌리는 배포에 마이그레이션이 있었으면 DB 가 옛 이미지보다 앞서 있다. 교체 스크립트는 올릴 이미지 안에서 DB 리비전을 그 이미지가
아는지 먼저 보고, 모르는데 **롤백 표시**(`DDONA_ROLLBACK=1`, Actions 수동 실행은 `image_tag`를 채우면 워크플로가 붙인다)가 있으면
마이그레이션을 건너뛰고 `… 롤백 표시가 있어 … 마이그레이션 건너뜀` 로그를 남긴 채 교체를 이어 간다(옛 이미지로 `alembic upgrade head`를
돌리면 `Can't locate revision`으로 멈춰 롤백이 안 된다). 스키마는 새 것 그대로 남으니, 옛 코드가 그 스키마에서 도는지와 되돌릴
순서는 해당 기능 절을 본다. 표시가 없으면 — `main` push 배포, `image_tag`를 비운 수동 실행, 표시 없이 VM 에서 부른 교체 — 같은
상황에서 DB 리비전과 이미지가 그것을 모른다는 사실, 롤백이면 표시를 켜라는 안내를 찍고 **실패**한다(쉬는 색 줄을 되돌리고 옛 색은
계속 서빙한다). 조용히 건너뛰지 않으려는 것이다: 판정은 DB 가 이미지보다 앞선 경우와 갈라진 경우를 구분하지 못하는데, 롤백이 아닌
배포에서 이 상황은 갈라진 쪽이다(예: downgrade 없이 revert 를 병합해 DB 가 앞선 채 남은 뒤 새 마이그레이션이 든 배포) — 그때
건너뛰면 새 코드가 자기 마이그레이션 없는 스키마에서 뜨고 `/health` 는 DB 를 보지 않아 배포가 초록으로 끝난다. 롤백해 둔 동안
태그를 생략한 env 반영 재교체도 같은 상황이라 표시를 붙인다(`sudo DDONA_ROLLBACK=1 bash ops/swap-api.sh`). DB 가 이미지보다
뒤거나 같으면 표시와 상관없이 upgrade 한다. 판정 자체가 실패하면(DB 에 못 닿음 등) 건너뛰지 않고 멈춘다.
과거 태그는 `gcloud artifacts docker tags list asia-northeast3-docker.pkg.dev/ddona-ai-character-chat/ddona/api`.
배포 워크플로가 끝에서(실행 이미지 확인 뒤) `apps/api/scripts/ops/prune_api_images.py`로 VM 로컬 API 이미지를
**현재 것 포함 최근 3개**(+ 실행 중 이미지)만 남기고 지운다 — 다른 저장소 이미지(caddy·postgres 등)는 건드리지
않고, 정리가 실패해도 배포는 성공으로 두고 `::warning::` 한 줄만 남긴다. 그래서 그보다 옛 태그는 VM에 없을 수 있는데,
교체 스크립트는 언제나 `docker pull`부터 하므로 Artifact Registry에서 받아 온다.

⚠️ 배포가 도는 중에 수동 실행을 큐에 넣으면 대기열에서 밀려날 수 있다 — 워크플로 `concurrency`(`cancel-in-progress: false`)는
그룹당 **대기 1개**만 남기므로, 그 사이 `main` push 가 하나 더 오면 먼저 기다리던 수동 롤백이 취소된다. 롤백은 진행 중인
배포가 끝난 뒤 실행 목록에서 실제로 돌았는지 확인한다.

**위험한 마이그레이션은 겹침 없이 — `skip_overlap`.** 평상시 교체는 마이그레이션이 끝난 뒤에도 옛 색이 새 색 기동·healthy
(로컬 리허설 실측 약 15~35초)와 드레인(최대 65초) 동안 새 스키마 위에서 돈다. 옛 코드가 새 스키마에서 깨지는 마이그레이션(판단 기준은
`apps/api/CLAUDE.md`의 "배포 중에는 옛 코드가 새 스키마 위에서 돈다" 절)은 이 겹침을 끄고 배포한다. 수동 실행에서 `skip_overlap`을 켜면 교체 스크립트가
idle 색을 띄우지 않고 active 색을 그 자리에서 재생성한다(마이그레이션 → 재생성, 드레인 없음). 끊김은 "짧은" 정도가
아니다 — 옛 컨테이너가 하던 가장 긴 요청이 끝날 때까지(정지 유예 상한 65초) + 새 컨테이너 기동(약 15초)이다(로컬 리허설
실측 31.1초 — 26초짜리 SSE 턴 진행 중 / 10.6초 — 진행 중 요청 없음). 그동안 들어온 요청은 Caddy 에서 최대 30초
(`lb_try_duration`) 기다리다 실패할 수 있고, 클라이언트가 이미 포기한 POST 가 그 뒤에 처리될 수도 있다. 외부 감시(`/ready`) 알림도 올 수 있다. 쉬는 색 줄은 같은 참조로 맞추되 그 색 컨테이너는
만들지 않는다. 두 색이 다 떠 있던 잔재면 쉬는 색부터 내린다 — 남겨 두면 옛 코드가 새 스키마로 트래픽을 받는다.

`main` 병합은 그 자체로 겹침 교체 배포를 부르므로, 그런 PR 은 병합 커밋 메시지에 `[skip actions]`를 넣어 push 배포를
건너뛰게 한 뒤 Actions 수동 실행(`image_tag` 비움 = 그 커밋을 빌드, `skip_overlap` 켬)으로 배포한다. `[skip actions]`는
그 push 로 도는 다른 워크플로(CI·인용 검사)도 함께 건너뛰게 하니, 병합 전에 PR 에서 초록인지 본다. ⚠️ 병합 직후 **다른
병합 없이 바로** 수동 실행한다 — 수동 실행 전에 다른 PR 이 `main`에 병합되면 그 push 배포가 위험한 마이그레이션을 포함한
`main` 최신을 평상시 겹침 교체로 올린다. 수동 실행은 `main` 브랜치에서만 받는다(다른 브랜치를 고르면 첫 단계에서 실패한다). 이미 레지스트리에 있는
태그를 VM 에서 직접 올릴 때는 `sudo SKIP_OVERLAP=true bash ops/swap-api.sh <태그>`. 스크립트 첫 로그 줄 `시작: tag=… skip_overlap=true`로 탈출구가 실제로
켜졌는지 확인한다 — 워크플로가 값을 원격까지 못 넘기면 조용히 평상시 겹침 교체로 돈다.

⚠️ **배포 성공 판정은 `/health` 200만으로 부족하다.** 옛 컨테이너도 200을 준다. 그래서 워크플로가
`ops/active-color.sh`로 서빙 중인 색을 정한 뒤 `docker inspect`로 그 색(`ddona-api_<색>-1`)의 실행 이미지가 새 태그인지
대조한다 — 손으로 배포할 때도 같이 확인할 것(`sudo docker inspect --format '{{.Config.Image}}' ddona-api_$(sudo bash
ops/active-color.sh)-1`). 교체 스크립트가 0 으로 끝나고 마지막 줄이 `13) 완료`인지도 본다.

⚠️ **`Caddyfile`만 바뀐 배포는 `caddy reload`가 성공해도 컨테이너 안 내용이 안 바뀔 수 있다**
(2026-09-15 실측). `docker-compose.prod.yml`이 그대로면 배포의 `up -d --wait caddy`는 caddy
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

#### env 반영 재기동

`.env`의 앱 설정을 바꾼 뒤에는 태그 없이 교체 스크립트를 부른다:

```sh
cd /opt/ddona/app
sudo python3 ops/check_env.py --format /opt/ddona/.env
sudo bash ops/swap-api.sh          # 태그 생략 = 지금 active 의 이미지 그대로 다시 교체
```

env 는 컨테이너를 만들 때만 읽혀서(`restart`는 다시 읽지 않는다) 컨테이너를 새로 만들어야 한다. 서빙 중인 색 하나를 제자리에서
다시 만들면(`up -d --wait api_<색>`) 그동안 끊기고, 새 env 로 기동이 실패하면 서비스가 그대로 내려간다. 태그를 생략한 교체는 쉬는
색을 새 env 로 띄워 healthy 를 확인한 뒤에 옛 색을 드레인하므로 끊김이 없고, 새 env 로 기동이 실패하면 옛 색이 그대로 남는다
(종료코드 1). 그때는 `.env`를 고친 뒤 다시 부른다 — 고치지 않으면 다음 배포도 같은 이유로 실패한다. 드레인이 끝날 때까지 옛
색은 옛 env 로 하던 요청을 마저 처리한다.

#### 빈 상태에서 첫 기동

api 컨테이너가 하나도 없을 때(VM 재구축 직후 등) 쓴다. 교체 스크립트는 떠 있는 색이 있어야 하고 이행 스크립트는 옛 단일 `api`
컨테이너가 있어야 해서 둘 다 이 형상에서는 멈추고, 배포 워크플로도 "교체할 대상이 없다"로 멈춘다. 그래서 서비스명을 지정해
손으로 띄운다. **서비스명 없는 `up -d`는 쓰지 않는다** — 쉬는 색까지 떠서 Caddy 업스트림에 합류한다.

```sh
cd /opt/ddona/app
C="sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env"
REF=asia-northeast3-docker.pkg.dev/ddona-ai-character-chat/ddona/api:<SHA 7자리>

# 1. 두 색 이미지 키를 같은 참조로. 하나라도 없거나 비면 compose 가 어떤 명령도 받지 않는다(서비스명을 줘도).
#    키마다 줄 수를 보고, 0 이면 더하고 1 이면 값을 바꾼다(2 이상인 중복 키는 형식 검사가 배포를 멈춘다).
sudo grep -c '^API_IMAGE_BLUE=' /opt/ddona/.env; sudo grep -c '^API_IMAGE_GREEN=' /opt/ddona/.env
sudo sh -c "printf 'API_IMAGE_BLUE=%s\nAPI_IMAGE_GREEN=%s\n' '$REF' '$REF' >> /opt/ddona/.env"        # 둘 다 0 일 때
sudo sed -i "s|^API_IMAGE_BLUE=.*|API_IMAGE_BLUE=$REF|;s|^API_IMAGE_GREEN=.*|API_IMAGE_GREEN=$REF|" /opt/ddona/.env   # 둘 다 1 일 때
sudo python3 ops/check_env.py --format /opt/ddona/.env

# 2. DB · Redis
$C up -d --wait postgres redis

# 3. 마이그레이션 — api 를 띄우기 전에("DB 마이그레이션" 절의 순서)
$C run --rm -T api_blue alembic upgrade head

# 4. blue 와 caddy
$C up -d --wait api_blue caddy

# 5. 상태 파일
sudo mkdir -p /var/lib/ddona && echo blue | sudo tee /var/lib/ddona/active_color
sudo bash ops/active-color.sh   # blue
```

`.env` 파일이 개행으로 끝나지 않으면 1 의 `printf`가 마지막 줄에 붙는다 — 형식 검사가 잡지만, 먼저 `sudo tail -c1 /opt/ddona/.env |
od -c`로 끝이 `\n`인지 본다. 새 VM 이면 2 와 3 사이에 "겹침 대비 운영 설정" 절의 `max_connections`(새 볼륨은 기본 100)와, 데이터를
되살릴 때는 "백업 · 복원" 절의 `restore_db`(갓 만든 DB 는 비어 있어 DROP·CREATE 단계는 필요 없다)를 넣는다. 스왑·swappiness 와
로그·크론 심볼릭 링크도 같은 절들대로 다시 건다. 이 뒤로는 평상시처럼 배포·`swap-api.sh`가 돈다.

#### 단일 api 에서 blue/green 으로 최초 이행

api 를 두 색으로 나누기 전의 형상(compose 서비스 `api` 하나, 컨테이너 `ddona-api-1`)에서 옮기는 1회성 절차다. 이 전환이 `main`에
병합되면 자동배포가 VM 에 옛 `api` 컨테이너가 있는 것을 보고 이 절차를 스스로 돈다 — `ops/bootstrap-bluegreen.sh <태그>`에 이어
같은 배포 안에서 같은 태그로 `ops/swap-api.sh`를 한 번 더 돌려, 평상시 교체가 운영에서 실제로 도는지까지 본다. 그래서 이행이
끝나면 active 는 green 이다.

이행 스크립트가 하는 일:

1. 잠금(교체와 같은 파일) → 전제 확인: 옛 `api` 컨테이너가 있고 `api_green` 컨테이너는 없어야 한다. compose 가 아니라 docker
   라벨로 본다 — 이 시점엔 `.env`에 색 키가 없어 compose 가 `ps`까지 거부한다.
2. `docker pull` → `.env`에 `API_IMAGE_BLUE`·`API_IMAGE_GREEN` 두 줄을 같은 참조로(어떤 compose 호출보다 먼저) → 형식 검사.
3. 마이그레이션(옛 `api`가 아직 서빙 중) → `api_blue`를 옛 `api` 옆에 띄운다. Caddy 가 아직 옛 설정이라 blue 는 트래픽을 받지 않는다.
4. 상태 파일 `blue` → **caddy 재생성** — 새 `Caddyfile`(두 색 업스트림)·api 의존 제거·로그 상한이 여기서 반영된다. 80/443 에
   듣는 프로세스가 없는 이 몇 초가 이행이 감수하는 끊김이다. `caddy:2-alpine`은 떠다니는 태그라 재생성 때 버전이 바뀔 수 있어
   직후 `caddy version`을 로그에 찍는다.
5. blue·Caddy 정상 확인 → 옛 `api` 컨테이너 정리(`up -d --no-recreate --remove-orphans api_blue caddy`) → 마지막 줄
   `8) 부트스트랩 정리 완료`.

**재실행 가능하다.** 어디서 실패하든 같은 태그로 워크플로를 다시 돌리면(실패한 실행의 Re-run, 또는 Run workflow 의 `image_tag`)
된 단계는 건너뛰고 이어서 끝낸다. 옛 `api`가 남아 있는 한 배포는 이행 스크립트로 가고, 교체 스크립트는 그 형상을 거부한다. blue
기동 전에 실패하면 서비스는 옛 `api`+옛 caddy 로, caddy 재생성 뒤에 실패하면 blue+새 caddy 로 계속된다. caddy 재생성이 이미
끝났으면(caddy 정의 해시로 판정) 재실행은 blue·caddy 를 다시 만들지 않는다 — 끊김을 두 번 만들지 않으려는 것이다.

하기 전과 한 뒤:

- "겹침 대비 운영 설정" 절이 먼저 끝나 있어야 한다 — 이행 배포 안의 첫 교체부터 두 색이 겹친다.
- 한가한 시간에 병합한다. 외부 업타임 감시(`/ready`)가 끊기는 몇 초에 걸려 알림이 올 수 있다.
- 끊김 구간은 Caddy 접근 로그로 못 잰다 — 재생성 중엔 듣는 프로세스가 없어 로그 자체가 비어 있다. 병합 직전부터 VM 밖에서
  폴링을 띄워 두고 비-2xx·연결 실패(`000`) 구간을 본다. 이어지는 첫 교체는 접근 로그(`/opt/ddona/logs/caddy/access.log`)에서 그
  시각 구간의 비-2xx 로 본다.

  ```bash
  while :; do
    printf '%s %s\n' "$(perl -MTime::HiRes=time -e 'printf "%.3f", time')" \
      "$(curl -s -o /dev/null -w '%{http_code}' --max-time 1 https://api.ddona.site/genres)"
    sleep 0.1
  done | tee bootstrap-poll.log
  ```

- 끝난 뒤 `.env`의 옛 `API_IMAGE=` 줄은 스크립트가 지우지 않는다. compose 가 더는 읽지 않으니 지우고(`sudo sed -i '/^API_IMAGE=/d'
  /opt/ddona/.env`, 값은 출력하지 않는다) 형식 검사를 다시 돌린다. 아래 되돌리기를 하게 되면 그 줄을 다시 넣는다.
- 로그 상한이 걸렸는지 본다 — caddy 는 이행 중 재생성, 색은 교체 때 새로 만들어져 걸린다(postgres·redis 는 일부러 안 건다):
  `sudo docker inspect --format '{{.HostConfig.LogConfig}}' ddona-caddy-1 ddona-api_$(sudo bash ops/active-color.sh)-1` →
  `{json-file map[max-file:5 max-size:20m]}`.

#### blue/green 을 단일 api 로 되돌리기

blue/green 전환 자체를 되돌릴 때만 쓴다(이미지 롤백은 위 "롤백"). **순서가 고정이다** — 되돌림이 `main`에 병합되면 그 커밋의 옛
`deploy-api.yml`이 자동배포로 돌기 때문이다. 이행처럼 짧은 끊김 한 번을 감수하고, 같은 외부 폴링으로 잰다.

1. 🔴 VM `.env`에 `API_IMAGE=` 한 줄을 지금 active 색 줄과 같은 값으로 넣는다(있으면 고치고, 없으면 더한다) → 형식 검사 통과.
   값은 `sudo grep "^API_IMAGE_$(sudo bash ops/active-color.sh | tr a-z A-Z)=" /opt/ddona/.env`로 본다. 이 줄이 없으면 2 에서 옛
   워크플로의 `sed`는 아무것도 안 하고 `pull api`가 빈 image 변수로 실패해, VM 은 **파일만 옛 형상인 채 blue/green 컨테이너가
   서빙하는 혼합 상태**가 된다 — 그 상태에서 caddy 가 재생성되면(VM 재부팅 포함) `api:8000`이 없어 전면 끊긴다. 이 뒤로는 교체
   스크립트를 부르지 않는다.
2. 🔴 blue/green 전환 커밋을 `git revert`해 `main`에 병합한다. 옛 워크플로가 자동으로 `API_IMAGE`를 그 배포의 태그로 바꾸고 →
   `pull api` → `run --rm api alembic upgrade head` → `up -d --wait api caddy`로 단일 `api`를 띄운다. caddy 는 정의(api 의존
   복귀·로그 상한 제거)가 바뀌어 재생성된다(수 초 끊김). blue/green 컨테이너는 옛 compose 에 없는 고아로 떠 있다. **VM 에서만
   옛 커밋을 체크아웃하는 방식은 쓰지 않는다** — 다음 배포의 `git reset --hard origin/main`이 blue/green 파일로 되돌려 놓아 이행이
   다시 돈다(끊김 한 번 더).
3. 남은 수동 단계(`cd /opt/ddona/app`, `$C`는 "빈 상태에서 첫 기동" 절과 같다): caddy 가 2 에서 재생성되지 않았으면
   (`sudo docker inspect --format '{{.Created}}' ddona-caddy-1`로 본다) `$C up -d --force-recreate --wait caddy` →
   `$C up -d --no-recreate --remove-orphans api caddy`로 두 색 컨테이너 정리 → `sudo rm /var/lib/ddona/active_color`. `.env`의 `API_IMAGE_BLUE`·`API_IMAGE_GREEN` 줄은 옛 compose 가 안 읽고 형식 검사도 키
   이름을 안 봐서 남겨도 무해하다.

#### 겹침 대비 운영 설정 — Postgres max_connections · 스왑

blue/green 교체 중에는 새 색 기동부터 옛 색 드레인이 끝날 때까지(최대 1분 남짓) 두 색이 함께 떠 있다. 그동안:

- **DB 커넥션** — 두 색의 풀이 함께 열려 최악 2 × 워커 4 × (10 + 7) = 136 연결이 된다. Postgres 기본 `max_connections` 100 을
  넘으므로 200 으로 올려 둔다(식은 "BE 런타임" 절 `DB_POOL_SIZE` 행).
- **메모리** — api 컨테이너 하나가 운영에서 약 0.8GB 를 쓰는데 교체 중에는 둘이 된다. 3.9GB VM 에서 여유가 빠듯해 스왑 2GB 를
  완충으로 둔다 — 이 VM 은 `vm.overcommit_memory=1`이라 할당이 거절되지 않고 모자라면 OOM killer 가 프로세스를 죽인다.
  `vm.swappiness`는 기본 60 에서 10 으로 낮춘다 — 60 이면 겹침이 없는 평소에도 커널이 쉬는 페이지를 디스크로 내보낸다. 목적은
  OOM 대신 완충이지 상시 스왑이 아니다.

둘 다 저장소 밖(Postgres 볼륨·VM 설정)에 살아서 VM 재구축·볼륨 재생성 때 빠지기 쉽다 — 그때 이 절을 다시 적용한다.

**Postgres `max_connections` 200** — `ALTER SYSTEM`으로 볼륨 안 `postgresql.auto.conf`에 쓴다. 재시작해야 반영된다(reload 로는
안 된다). 재시작하는 몇 초 동안 DB 를 쓰는 요청은 실패하고 `/ready`가 503 이라 외부 감시 알림이 올 수 있으니 진행 중인 채팅 턴이
없는 한가한 시간에 한다. `restart postgres`는 api 를 따라 재시작시키지 않고, 풀에 남은 끊긴 연결은 `pool_pre_ping`이 갈아 끼운다.

```sh
cd /opt/ddona/app
C="sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env"
$C exec -T postgres psql -U postgres -c "ALTER SYSTEM SET max_connections = 200;"
# 재시작 전에는 pg_settings 가 바뀌지 않는다(setting 100, pending_restart 는 리로드 전까지 f) — 파일에 들어갔는지는 이것으로 본다
$C exec -T postgres psql -U postgres -Atc "SELECT setting, applied, error FROM pg_file_settings WHERE name = 'max_connections' AND sourcefile LIKE '%auto.conf';"   # 200|f|setting could not be applied
$C restart postgres
$C exec -T postgres psql -U postgres -Atc "SHOW max_connections;"   # 200
curl -s https://api.ddona.site/ready
```

되돌리기는 `ALTER SYSTEM RESET max_connections;` → `$C restart postgres`(볼륨의 `postgresql.conf` 값 100 으로 돌아간다). 되돌리면
"BE 런타임" 절의 식이 깨지므로 풀 크기도 함께 줄인다. 볼륨을 새로 만들면(VM 재구축, 새 볼륨으로 복원) 기본 100 으로 돌아가 있으니
위를 다시 적용한다.

**스왑 2GB + `vm.swappiness=10`**(2026-10-07 KST 운영 적용, 무중단):

```sh
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab            # 재부팅 뒤에도 켜진다
echo 'vm.swappiness = 10' | sudo tee /etc/sysctl.d/60-ddona-swap.conf  # 재부팅 뒤에도 10
sudo sysctl -p /etc/sysctl.d/60-ddona-swap.conf                       # 지금 적용 — 이 파일 하나만
swapon --show; free -m; sysctl vm.swappiness
```

🔴 **적용에 `sysctl --system`을 쓰지 않는다.** 모든 sysctl 파일을 다시 읽으면서 GCE 기본 파일
`/etc/sysctl.d/60-gce-network-security.conf`의 `net.ipv4.ip_forward=0`이 Docker 가 기동 때 켜 둔 1 을 덮어, 외부에서 컨테이너로 가는
트래픽이 전부 끊긴다(2026-10-07 운영에서 실제로 3분 42초 끊겼고 `sudo sysctl -w net.ipv4.ip_forward=1`로 복구했다). 파일 하나만
`sysctl -p <파일>`로 읽히거나 `sysctl -w vm.swappiness=10`으로 값만 바꾼다.

되돌리기: `sudo swapoff /swapfile`(스왑에 올라간 페이지를 RAM 으로 되돌리므로 그만큼 여유가 있어야 한다) →
`sudo sed -i '\|^/swapfile none swap|d' /etc/fstab` → `sudo rm /swapfile`, 그리고 `sudo rm /etc/sysctl.d/60-ddona-swap.conf` →
`sudo sysctl -w vm.swappiness=60`(여기서도 `--system`은 쓰지 않는다).

### 3-2. DB 마이그레이션

**기본은 파이프라인이 처리한다.** 교체 스크립트(`ops/swap-api.sh`)가 새 이미지를 pull 하고 `.env`의 idle 색 줄을 바꾼 직후,
idle 색을 띄우기 전에 그 색의 새 이미지로 `compose run --rm -T api_<idle> alembic upgrade head`를 돌린다(옛 색은 아직
서빙 중이다). 사람이 따로 돌릴 일은 원칙적으로 없다. 마이그레이션이 끝난 뒤에도 옛 색이 수십 초~1분 남짓 새 스키마 위에서
돌기 때문에, 옛 코드를 깨뜨리는 마이그레이션은 "BE → GCE VM" 절의 `skip_overlap`으로 배포한다.

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

⚠️ **순서 고정: 마이그레이션은 반드시 새 컨테이너 기동(`up -d`)보다 먼저 돈다.** `main.py`의 lifespan 훅이 기동마다
`rebuild_suspended_user_markers()`를 불러 `users.suspended_at`을 SELECT 한다 — 스키마가 없는 채로 새
이미지가 뜨면 `UndefinedColumnError`로 죽고 healthcheck·배포 검증이 함께 실패한다. blue/green 교체에서는 그 새 색이 healthy 가
안 되어 교체가 실패하고 옛 색이 계속 서빙하지만, "빈 상태에서 첫 기동"처럼 옛 색이 없을 때는 **API가 내려간 채로 남는다.**
미리 적용해 두면 파이프라인의 자동 마이그레이션은 멱등이라 no-op이 된다.

### 3-3. FE → Cloudflare Pages (web, admin 각각)

Pages 프로젝트 2개, 각각 Git 연동으로 `main` push 시 자동 빌드:

- **Build command**: `pnpm install --frozen-lockfile && pnpm --filter @ai-character-chat/web build`
  (admin은 filter 교체)
- **Build output directory**: `apps/web/dist` / `apps/admin/dist`
- **Root directory**: **비워서 repo 루트 유지** (pnpm workspace 설치 때문에 필수)
- **Build watch paths**: `apps/{web|admin}/*, packages/*, pnpm-lock.yaml, pnpm-workspace.yaml`
  (기본값 `*`는 전체 감시라 BE만 바뀌어도 FE가 재배포된다)
- SPA fallback은 `apps/{web,admin}/public/_redirects`(`/* /index.html 200`)로 이미 되어 있다.
- 보안 헤더(HSTS `max-age=31536000`·nosniff·X-Frame-Options·Referrer-Policy)는 저장소 코드가 내보낸다 —
  web은 Worker(`apps/web/worker/securityHeaders.ts`), admin은 `apps/admin/public/_headers`, API는
  저장소 루트 `Caddyfile`. **Cloudflare 대시보드의 HSTS 설정(SSL/TLS → Edge Certificates)은 켜지
  않는다** — 두 군데서 내면 값이 갈리고, 어느 쪽이 실제로 나가는지 저장소만 봐서는 알 수 없게 된다.

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
$C stop api_blue api_green   # 두 색 모두 — 떠 있지 않은 색은 조용히 건너뛴다
$C exec -T postgres psql -U postgres -d postgres -c "DROP DATABASE ai_character_chat WITH (FORCE);"
$C exec -T postgres psql -U postgres -d postgres -c "CREATE DATABASE ai_character_chat;"
cd /opt/ddona/scripts
sudo TARGET_DATABASE_URL="$(sudo grep ^DATABASE_URL= /opt/ddona/.env | cut -d= -f2-)" \
     PG_DOCKER_NETWORK=ddona_default PYTHONPATH=. python3 -m ops.restore_db /경로/백업.dump
# 위 명령이 성공한 경우에만 API를 다시 연다. 실패했다면 중단 상태에서 원인을 확인한다.
# 다시 여는 것은 "빈 상태에서 첫 기동" 절의 3~5단계(마이그레이션 → api_blue·caddy 기동 → 상태 파일)와 같다.
# 교체 스크립트는 떠 있는 색이 없으면 멈추므로 여기서 쓰지 않는다.
```

볼륨을 새로 만든 복원(VM 재구축 등)이면 Postgres `max_connections`가 기본 100 으로 돌아가 있다 — API 를 열기 전에
"겹침 대비 운영 설정" 절의 `ALTER SYSTEM`을 다시 적용한다.

`restore_db`는 `pg_restore` 성공 후 API를 공개하기 전에 만료된 댓글 신고 원문 증거와
채팅 응답 신고 대화 사본 증거를 제거한다. `evidence_expires_at <= 현재 시각`인 증거 칸(댓글은
본문·스티커·멘션, 채팅은 신고된 응답·직전 사용자 메시지와 신고자 메모)만 비우고 신고·조치 처리 정보는 유지한다.
파기가 실패하면 복원 명령도 실패하며 ‘복원 완료’를 출력하지 않는다.
해당 신고 테이블이 없는 이전 백업은 이 단계를 변경 없이 통과한다. 기존 일간 7일·주간 4주
순환 보관은 유지되므로, 운영 DB에서 90일 뒤 파기된 증거가 백업 사본에는 해당 사본의
순환 삭제 시점까지 남을 수 있다. 복원 시 만료 증거를 제거하는 이유다.

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

**왜 별도 compose·별도 배포인가.** "BE → GCE VM" 절의 자동배포는 api 색을 교체 스크립트로 바꾸고 caddy 는
`up -d --wait caddy`로, 모두 **서비스명을 명시**해 다룬다 — 여기에 Bugsink를 얹으면
앱을 배포할 때마다 에러 추적기도 같이 재시작돼, "배포가 뭔가 깨뜨리는 바로
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
`SENTRY_DSN`·`SENTRY_ENVIRONMENT` — 는 전부 "BE 런타임" 절의 키 개수에 포함되지만, 값·근거의 유일한
소스는 이 절이다 — "BE 런타임" 절 표에는 행을 따로 만들지 않는다):

| 변수 | 값 | 비고 |
|---|---|---|
| `BUGSINK_SECRET_KEY` | `openssl rand -base64 50 \| tr -d '\n'` | Django SECRET_KEY. `django-insecure` 접두어 없이. `tr` 을 빼먹지 않는다 — openssl 은 base64 출력을 64자마다 줄바꿈해서, 그대로 붙여 넣으면 키가 64자로 잘리고 남은 조각이 `.env` 의 독립된 줄이 된다("BE 런타임" 절 끝의 "env 파일 형식" 항목의 검사기가 그 줄을 조각 모양에 따라 `key-format` 또는 `empty-value` 로 잡아 배포를 멈추고, 줄 번호·규칙만 찍는다) |
| `BUGSINK_CREATE_SUPERUSER` | `관리자이메일:비밀번호` | 최초 1회만 동작한다 — 사용자가 이미 1명이라도 있으면 무시된다(공식 소스 `bsmain/management/commands/prestart.py` 확인). 부트스트랩 후 값을 지우지 않고 둬도 안전하다 |
| `BUGSINK_BASE_URL` | `https://ddona.site/_ingest` | `api.ddona.site`가 아니다 — DSN·이메일 링크가 이 값으로 조립되고, 브라우저 ingest는 `ddona.site`(Worker 경유)를 쓴다. `/_ingest` 프리픽스는 DSN·관리자 UI가 그 경로 아래로 들어가게 만든다(Bugsink는 이 프리픽스를 `FORCE_SCRIPT_NAME`으로 링크 생성에만 쓰고, 실제 라우팅은 `Caddyfile`이 프리픽스를 벗겨서 맞춘다 — 아래 "DSN 발급 절차"·`Caddyfile` 참조) |
| `INGEST_SHARED_SECRET` | 무작위 값(`openssl rand -hex 32`) | `Caddyfile`이 **`/_ingest/api/*/envelope/`(에러 이벤트 수신 경로)에만** 거는 게이트 값. 관리자 UI(`/_ingest/` 나머지)는 이 시크릿 없이 통과하고 Bugsink 자체 로그인으로 보호된다(사용자 결정 — 가입은 이미 `CB_NOBODY`로 잠겨 있어 시크릿의 목적은 로그인 페이지를 숨기는 게 아니라 익명 POST 홍수를 막는 것). Caddy 쪽 배선은 `docker-compose.prod.yml`에 돼 있다 — 배포 순서는 아래 "배포 순서 위험" 참조 |
| `SENTRY_DSN` | Bugsink에서 프로젝트 생성 후 발급되는 DSN | API(`apps/api`)가 자기 에러를 Bugsink로 보내는 값. 비어 있으면 `_init_sentry()`가 조용히 비활성으로 남는다(테스트로 고정된 동작이지 에러가 아니다) |
| `SENTRY_ENVIRONMENT` | `production` | ⚠️ **필수.** 빠뜨리면 기본값 `"development"`가 그대로 남아 프로덕션 이벤트가 Bugsink에서 개발 환경으로 표시된다(`config.py` 주석 — 이 저장소에 스테이징이 없어 프로덕션·dev를 가르는 유일한 값) |

**`SENTRY_DSN` 발급 절차**(최초 1회):
1. 위 명령으로 기동 후 `BUGSINK_BASE_URL`(`https://ddona.site/_ingest/` — **트레일링 슬래시
   필수**. `Caddyfile`의 매처가 `/_ingest/*`라 슬래시 없는 `/_ingest`는 이 라우트에 안 걸리고
   api 업스트림으로 흘러가 404가 난다 — 로컬 caddy 컨테이너로 확인)로 접속해 `BUGSINK_CREATE_SUPERUSER`의
   `email:password`로 로그인한다. 이 경로는 시크릿을 요구하지 않는다(위 표 참조).
2. 프로젝트를 하나 만든다(예: `ddona-api`). Bugsink가 DSN을 보여준다 — 형태는
   `https://<key>@ddona.site/_ingest/<project_id>`다.
3. **API(백엔드) 자신의 `SENTRY_DSN`에는 위 값을 그대로 쓰지 않는다.** api 색 컨테이너는 Bugsink와
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
`{$SITE_ADDRESS}` 블록 전체(=api 색으로 가는 기존 프록시 포함)가 **적재 자체에 실패**한다.
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

"Bugsink(에러 트래커)" 절의 `MAX_EVENT_AGE_DAYS: "30"`
(`docker-compose.monitoring.yml`)은 "30일보다 오래된 이벤트는 지운다"는 **기준값**만 고정한다 —
실제로 지우는 건 `bugsink-manage vacuum --old-events` 관리 명령이고, 공식 이미지는 이 명령을 도는
스케줄러를 컨테이너 안에 두지 않는다(`Dockerfile` CMD 확인 — gunicorn+snappea만 상시 실행). 값만
고정하고 이 크론이 없으면 처리방침이 약속하는 "수집일로부터 30일간 보관 후 파기"는 실행되지
않는다.

`apps/api/scripts/ops/vacuum_bugsink.py`가 `docker exec ddona-monitoring-bugsink-1 bugsink-manage
vacuum --old-events`를 돌린다. 컨테이너 이름은 추측이 아니다 — `docker-compose.monitoring.yml`의
`name: ddona-monitoring` + 서비스 `bugsink`(replica 1개)를 Compose V2 관례대로 조합한 이름이고,
`docker compose config`로 프로젝트·서비스 이름을 확인한 뒤 로컬에서 실제로 `docker compose up`한
컨테이너 이름을 실측했다("Bugsink(에러 트래커)" 절의 `docker stats --no-stream ddona-monitoring-bugsink-1`과 같은 이름).
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
"bugsink 서비스 자체의 생사"가 아니고(후자는 "Bugsink(에러 트래커)" 절이 손으로 기동/재기동하는 별개 관심사), Discord
알림 하나로 "아무도 모르게 실패한다"는 이 작업의 실제 위험은 이미 닫힌다.

⚠️ 매일 05:00 UTC로 골랐다 — `ddona-backup`(18:00 UTC, "백업 · 복원" 절)과 겹치지 않으면 충분하다. vacuum
자체가 이벤트 삭제 쿼리 한 번이라 `pg_dump`보다 훨씬 가볍고, 보관기간이 30일 단위라 몇 시간
지연이 "30일간 보관 후 파기" 약속을 깨지 않는다 — 시간대를 더 정교하게 고를 이유가 없다.

### 3-7. VM 리소스 감시 — cron이 `free`/`df`를 직접 읽는다

GCP Cloud Monitoring을 쓰지 않는 이유 —
`instance/memory/balloon/ram_used`가 우리 VM에서 `free -m`과 2배 차이가 났고(실측 1.78GB vs
890MB), 그 메트릭 자체가 e2 계열 전용이라 인스턴스 타입을 바꾸면 조용히 사라진다. 대신
`apps/api/scripts/ops/check_resources.py`가 5분마다 `free`/`df`를 직접 읽어 임계를 넘거나 다시
내려올 때 Discord로 알리고, 같은 실행이 healthchecks.io로도 ping해 VM 자체의 생사를 VM 밖에서 본다.

**알림은 상태가 바뀔 때만 간다** — 항목(메모리·디스크)별로 정상→경고에 1회, 경고→정상에 "복구" 1회.
경고가 이어지는 동안은 보내지 않고, 첫 알림이 묻혔을 때를 대비해 24시간마다 1회만 다시 보낸다. 5분마다
같은 경고를 보내면 채널이 같은 줄로 덮여 정작 새 경고가 묻히기 때문이다. 경고 값이 더 나빠져도(85%→97%)
상태는 그대로라 다시 보내지 않는다. 항목별 마지막 상태는 `/var/lib/ddona/resource-check.state`(JSON)에
남는다 — 배포마다 `git reset --hard` 되는 체크아웃 밖이어야 해서 `ops/resource-check.sh`가 디렉터리를 만들고
`--state-file`로 넘긴다. 파일이 없거나 깨졌으면 "정상, 알린 적 없음"으로 보고 다음 실행이 한 번 더 알린다
(놓치는 것보다 중복이 낫다). 보내기에 실패한 알림은 상태를 남기지 않아 다음 실행이 다시 보내고, 상태 파일을
못 쓰면 stderr에 남기고 ping까지 간다. 로그(`/var/log/ddona-resource-check.log`)의 경고 줄 끝에 `(알림)`·
`(지속 — 알림 생략)`·`(알림 실패)`가 붙어 실행마다 무엇을 했는지 보인다.

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
`PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.check_resources --state-file /var/lib/ddona/resource-check.state`를 부른다 — `backup.sh`와
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

### 댓글 신고 원문 증거 파기 — 배포 준비

신고 접수 시각부터 90일이 지난 원문 증거는 관리자 조회에서 즉시 숨기고,
`apps/api/scripts/ops/purge_comment_evidence.py`가 저장된 본문·스티커 식별자·멘션 식별자를
제거한다. 신고·조치 메타데이터는 삭제하지 않는다. 중복 신고로 원래 만료 시각을 연장하지 않는다.

같은 크론이 채팅 응답 신고의 만료 증거(신고된 응답·직전 사용자 메시지 사본과 신고자 메모)도 함께 비운다
(`apps/api/scripts/ops/purge_chat_report_evidence.py`). 채팅 신고용 크론 파일은 따로 없으므로
이 크론이 이미 설치돼 있으면 추가 설치 없이 배포만으로 적용된다. 로그도 아래 댓글 증거 로그 파일에
한 줄씩 함께 남는다.

아래는 신규 댓글 기능을 운영에 배포할 때 수행할 설치 절차이며, 저장소에 파일이 있다는
사실만으로 VM에 설치됐다고 보지 않는다. 기존 `/opt/ddona/scripts` 심볼릭 링크가
저장소의 `apps/api/scripts`를 가리키는지도 확인한다.

```sh
sudo ln -sf /opt/ddona/app/ops/purge-comment-evidence.sh /opt/ddona/purge-comment-evidence.sh
sudo ln -sf /opt/ddona/app/ops/cron.d/ddona-comment-evidence-purge /etc/cron.d/ddona-comment-evidence-purge
sudo -u root /opt/ddona/purge-comment-evidence.sh
tail /var/log/ddona-comment-evidence-purge.log
```

크론은 매시간 17분에 시스템 Python으로 실행한다. 래퍼는 `/opt/ddona/.env`에서
`DATABASE_URL`만 읽고 `PG_DOCKER_NETWORK=ddona_default`로 운영 DB에 연결한다.
API 가상환경·SQLAlchemy를 import하지 않으며 Discord·메일·공지를 발송하지 않는다.
실패는 nonzero exit와 stderr에 남으므로 로그에서 오류를 확인한다. 복원 경로도 같은
파기 함수를 사용하며, 파기가 실패한 복원 대상의 API를 다시 공개하면 안 된다.

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

### 3-10. 이미지 변형 백필 — 표시용 변형(`_display.webp`)

READY 이미지 자산은 원본 곁에 변형 두 개를 갖는다 — 목록·카드용 썸네일 `{원본키}_thumb.webp`(긴 변 512)와,
상세 화면처럼 크게 그리는 자리용 표시용 변형 `{원본키}_display.webp`(긴 변 1024, 원본이 더 작으면 원본 크기 그대로,
WebP q80). 응답은 변형 키를 **존재 확인 없이** 유도하므로, 표시용 변형을 만드는 코드가 배포되기 전에 READY 가 된
자산(운영 재고 전부)에는 이 백필로 소급해 만들어 둬야 한다. 백필 전에 응답을 표시용 변형으로 바꾸면 그 자산의
상세 이미지가 404(깨진 이미지)가 된다.

**순서가 고정이다.** ① 변형 생성·삭제·백필 스크립트를 담은 PR 병합(= API 자동 배포 — 이 시점부터 새로 READY 가 되는
자산은 표시용 변형을 함께 갖는다) → ② 아래 백필 → ③ 아래 확인 통과 → ④ 상세 응답을 표시용 변형으로 바꾸는 PR 병합.
①과 ② 사이에 생긴 자산도 이미 변형을 가지므로 ②를 다시 돌릴 필요는 없다.

**실행 위치** — VM 에서 서빙 중인 api 색의 이미지로 돈다. 스크립트는 이미지에 들어 있고(`apps/api/Dockerfile` 의
`COPY . /app`) 컨테이너 env 가 운영 DB·R2 를 이미 가리키므로 시크릿을 따로 넘기지 않는다. DB 는 읽기만 하고 R2 에
변형 객체만 더한다(있는 객체를 덮어쓰지 않는다).

```sh
gcloud compute ssh ddona-api --zone=asia-northeast3-a --tunnel-through-iap --project=ddona-ai-character-chat
cd /opt/ddona/app
C="sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env"

# `-u` 는 출력 버퍼링을 끈다. `exec -T` 의 출력은 파이프라 이것 없이는 본 실행의 진행 줄이 끝날 때까지 안 보여
# 멈춘 것처럼 보인다.

# 1. dry-run 먼저 — 첫 줄의 "대상:" 이 R2 엔드포인트·운영 버킷인지, 빠진 변형이 `_display.webp` 뿐인지, "원본 없음"
#    이 몇 건인지 본다. `_thumb.webp` 도 빠져 있다고 나오면 썸네일 불변식이 이미 깨진 자산이 있다는 뜻이다(이 백필이
#    함께 채운다).
$C exec -T api_$(sudo bash ops/active-color.sh) python -u scripts/backfill_thumbnails.py --dry-run

# 2. 본 실행 — 자산마다 원본을 받아 빠진 변형만 올린다. 개별 실패는 멈추지 않고 모아서 마지막에 요약한다.
#    exit 0 = 전부 채움 · 1 = 다시 돌려 볼 실패가 있음 · 2 = 남은 것이 원본 없는 자산뿐(아래 "원본이 없는 자산").
#    오래 걸리므로 서빙 중인 색 안(`exec`)이 아니라 같은 이미지의 일회용 컨테이너(`run --rm --no-deps`)로 돌린다 —
#    도중에 배포가 api 색을 교체하면 옛 색이 멈추면서 그 안의 `exec` 프로세스도 같이 죽지만, 일회용 컨테이너는
#    교체 대상이 아니라 끝까지 돈다(교체의 정지·삭제는 서비스 컨테이너만 건드린다).
$C run --rm --no-deps -T api_$(sudo bash ops/active-color.sh) python -u scripts/backfill_thumbnails.py

# 3. 확인(읽기 전용) — 마지막 줄이 "✓ 불변식 충족 — 변형이 빠진 READY 자산 0건" 이고 exit 0 이어야 한다(1·2 의 뜻은
#    백필과 같다). "표시용 변형 합계" 줄이 원본 대비 비율을 보인다. --verbose 는 자산별 크기·치수(객체를 내려받는다).
$C exec -T api_$(sudo bash ops/active-color.sh) python -u scripts/verify_thumbnails.py
```

**재실행 안전** — 변형이 다 있는 자산은 원본을 내려받지 않고 건너뛴다. exit 1 이면 원인(R2 일시 오류, 원본이 그림이
아님 등)을 본 뒤 같은 명령을 다시 돌리면 남은 것만 대상이 된다. 실행 도중 사용자가 지운 자산은 그 실행에서 실패로
잡히지만 다음 실행에서는 행이 없어 사라진다 — 재실행에서 사라진 실패는 무시해도 된다.

**DB 를 붙잡지 않는다** — 스크립트는 READY 자산의 저장 키 목록만 읽고 곧바로 트랜잭션을 끝낸 뒤 저장소 작업을 한다.
그래서 백필 도중 배포가 `assets` 를 고치는 마이그레이션을 돌려도 백필이 그 마이그레이션이나 뒤따르는 `assets` 조회를
막지 않는다.

**원본이 없는 자산(exit 2)** — 원본 객체가 저장소에 없으면 변형을 만들 수 없고 다시 돌려도 같다. 두 스크립트 모두 이런
자산을 "원본 없음" 목록으로 따로 출력한다. 판정: 2단계가 바꾸는 상세 응답의 이미지 자리(히어로·채팅방 헤더 아바타·콘텐츠
링크 미리보기)는 지금 **원본**을 서명하므로, 원본이 없는 자산은 그 자리가 이미 깨져 있고 2단계 뒤에도 똑같이 깨진다 —
새로 깨지는 화면이 없다. 그러므로 **확인이 exit 2 이고 남은 것이 원본 없음 목록뿐이면 2단계를 진행해도 된다.** 그 목록은
2단계와 별개의 결함으로 기록하고, 그 자산을 쓰는 작품을 DB 에서 찾아(`assets.storage_key` 로 `assets.id` 를 얻고, 그 id 를
대표 이미지·상황 이미지·미디어 북 칸으로 거는 행) 작가에게 다시 올리게 하거나 운영자가 대표 이미지를 바꾼다. 반대로
**exit 1(원본은 있는데 변형이 빠짐)이 남아 있으면 2단계를 진행하지 않는다** — 그 자산은 지금 멀쩡한 상세 화면이 2단계 뒤
404 가 된다.

**소요 추정** — 로컬 moto 실측은 시드 자산 52건(원본 중앙값 960KB PNG)에 약 8초(프로세스 기동 포함)였다. 운영은 자산마다
R2 왕복(HEAD 3회·원본 GET·변형 PUT)이 더해지므로 dry-run 이 보인 생성 대상 수 × 0.5~1초 정도로 잡는다 — 이 값은
실측이 아니라 추정이다. 한 장씩 순서대로 처리해 VM 의 CPU·메모리를 크게 점유하지 않는다. 같은 실측에서
표시용 변형은 장당 중앙값 약 46KB(최대 119KB)였다.

**상세 응답 전환 PR 을 병합하기 전에 확인할 것**
- 위 3번 확인이 exit 0 이다(또는 exit 2 이고 남은 것이 원본 없음 목록뿐이다 — 위 "원본이 없는 자산") — 병합 직전에 한 번 더 돌린다(백필 뒤 배포가 있었어도 새 자산은 변형을 갖지만, 전환 직전
  상태를 보는 것이 404 를 막는 유일한 확인이다).
- 백필 뒤 표본 하나의 표시용 변형이 실제로 열린다 — 운영 콘텐츠 하나의 대표 이미지 저장 키로 `_display.webp` 객체를
  받아 `content-type: image/webp` 와 긴 변 1024 이하를 확인한다(`verify_thumbnails.py --verbose` 의 그 자산 줄로도 된다).
- 운영 API 가 변형 생성·삭제가 들어간 이미지로 돌고 있다(`deploy-api.yml` 의 마지막 성공 실행이 그 병합 커밋 이후다).
  아니면 백필 뒤에 생긴 자산이 변형 없이 남는다.

**상세 응답 전환 PR 을 병합한 뒤 확인할 것** — 병합 = API 자동 배포라 `deploy-api.yml` 실행이 끝난 뒤에 본다.
```sh
# 공개 콘텐츠 하나(id 는 홈에서 아무거나)의 상세 응답 — 경로가 `_display.webp` 로 끝나야 한다(전환 전에는 원본 확장자).
curl -s "https://api.ddona.site/contents/<콘텐츠 id>" | jq -r .thumbnailUrl | cut -d'?' -f1
# 그 주소를 그대로 GET 해 200 과 `content-type: image/webp` 를 본다(본문은 버리고 헤더만 출력). HEAD(`curl -I`)는 쓰지
# 않는다 — 이 주소는 GET 으로 서명돼 HEAD 에는 403 이 날 수 있다.
curl -s -o /dev/null -D - "$(curl -s "https://api.ddona.site/contents/<콘텐츠 id>" | jq -r .thumbnailUrl)" | grep -iE '^HTTP|content-type'
```
- 화면에서 상세 모달 히어로와 그 작품 채팅방 헤더 아바타가 깨지지 않는다(둘 다 이 주소를 그대로 쓴다).
- 콘텐츠 링크 미리보기(`/og/content/{id}.jpg`)도 이 주소를 프록시하므로 WebP 가 나간다. 다만 Worker 가 og 이미지를
  24시간 캐시하고 링크 미리보기를 만드는 쪽(카카오 등)도 따로 캐시하므로 이미 퍼진 링크는 한동안 원본 그대로 보인다 — 바로
  바뀌지 않는 것은 정상이다. 형식: 프로필 og 가 이미 같은 방식으로 WebP(`_thumb.webp`)를 `.jpg` 주소로 내보내고 있고, 그
  미리보기가 **카카오톡**에서 보이는 것은 확인했다(2026-10-04). 페이스북 등 다른 곳에서 WebP og 가 보이는지는 확인하지 않았다.

**상세 응답 전환 되돌리기** — 그 PR 을 revert 해 병합하면(= 자동 배포) 상세 응답이 다시 원본을 서명한다. DB·저장소
변경이 없어 그것만으로 끝나고, 남은 `_display.webp` 객체는 무해하다(새 자산에도 계속 만들어진다).

**되돌리기(변형 생성)** — 변형 생성 이전 태그로 롤백해도 화면에는 영향이 없다 — 그 태그의 응답은 원본을 서명하고 원본은
그대로 있다(남은 `_display.webp` 객체는 무해). 다만 **상세 응답 전환 뒤에 그 태그로 롤백했다가 다시 올렸다면 백필과 확인을
다시 돌린다** — 롤백 기간에 READY 가 된 자산은 `_display.webp` 가 없어 다시 올린 코드에서 상세 히어로가 404 가 된다.
다만 옛 코드의 자산 삭제·탈퇴 파기는 `_display.webp` 를 모르므로, **롤백해 둔 기간에 지워진 생성 이미지와 탈퇴한
회원의 이미지는 표시용 변형이 R2 에 남는다.** 롤백했다면 그 기간에 지워진 자산의 `{원본키}_display.webp` 를 손으로 지운다.

### 3-11. 소설화 켜기 · 끄기 · 회수 · 롤백

소설화는 세 겹으로 닫혀 있다 — 전역 스위치 `NOVELIZE_ENABLED`, env 명단 `NOVELIZE_GRANT_ALLOWLIST`, 어드민 유저 상세의
계정별 허용 토글. 셋 다 있어야 그 계정에 진입점(채팅 더보기 「소설로 보기」·프로필 메뉴 「내 소설」)과 소설 API 가
열리고, 하나라도 빠지면 403 `NOVELIZE_NOT_ALLOWED` 다. 코드 기본값이 꺼짐·빈 명단이라 **배포만으로는 닫힌 채 뜬다.**
예외는 소설 삭제 하나다 — 자기 데이터를 지울 권리는 허용과 무관해서 로그인·소유권만 본다. 면제 계정도 클로버가
차감된다(소설화에는 면제 분기가 없다).

**켜기** — `.env` 에 두 줄을 더한다. 파일을 통째로 덮거나 백업본으로 복원하지 않는다(교체 스크립트가 같은 파일의
`API_IMAGE_BLUE`·`API_IMAGE_GREEN`을 고친다). 명단 값은 공백·따옴표 없는 쉼표 구분이다:

```sh
cd /opt/ddona/app
sudo sh -c 'printf "\nNOVELIZE_ENABLED=true\nNOVELIZE_GRANT_ALLOWLIST=<계정 id>,<계정 id>\n" >> /opt/ddona/.env'
sudo python3 ops/check_env.py --format /opt/ddona/.env
sudo bash ops/swap-api.sh
sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env exec -T api_$(sudo bash ops/active-color.sh) \
  python -c "from api.core.config import settings; print(settings.novelize_enabled, settings.novelize_grant_allowlist)"
```

`restart` 는 env 를 다시 읽지 않으므로 교체 스크립트를 태그 없이 불러 새 env 로 다시 띄운다("env 반영 재기동" 절). 그다음 "BE 런타임" 절의 키 개수 문장을 VM 에서 다시
세어 고친다. 키를 넣은 것만으로는 아직 아무도 못 쓴다 — 어드민 유저 상세에서 그 계정의 소설화 허용을 켜고(명단 밖
계정이면 거절된다), 클로버를 지급한다. 허용 직후 그 계정의 web 은 새로고침해야 진입점이 보인다(세션 정보를 다시 받지
않는다).

**소설 문안이 있는 곳.** 소설화는 프롬프트 세트 캐시를 쓰지 않는다 — 경계 제안·화 생성·문단 수정 모두 호출마다 DB 에서
활성 세트를 읽으므로(캐시는 채팅만 쓴다) 마이그레이션이 심은 세트도, 어드민이 게시한 판도 바로 다음 호출부터 쓰인다. 소설
문안은 어드민 프롬프트 화면의 「소설」 탭(`novel` 레인)에서 고친다. 화 생성은 작업이 고른 모델의 체인(Gemini·Sonnet·Opus)을,
경계 제안과 문단 수정은 Gemini 체인을 읽고, 등급 규칙(`system` 채널 `rule_rating`)과 화자 라벨은 원작 종류(스토리·캐릭터)의
채팅 Gemini 세트에서 읽는다. 스토리·캐릭터 레인 Gemini 세트에도 옛 소설 문안 행(`novelize_*`)이 남아 있다 — 옛 이미지로
되돌렸을 때 옛 코드가 읽는 값이라 새 코드는 읽지 않고, 어드민 채팅 탭에는 보이지 않으며, 채팅 레인을 저장·게시할 때 서버가
직전 게시본의 값을 그대로 복사한다.

**진행 중 작업 0 확인 — 끄기 · 명단 회수 · 롤백의 첫 단계.** 셋 다 교체(`ops/swap-api.sh`)를 낀다. 소설 작업은 api 프로세스
안에서 돌아서, 교체가 옛 색을 드레인하고 멈출 때(정지 유예 65초) 그 색에서 돌던 장 생성·문단 수정 작업이 죽어 진행 중으로
남고, 그 차감액은 만료 정리가 환불할 때까지 묶인다. 새 코드는 프로세스마다 기동 뒤 heartbeat 만료 + 10초(기본 70초)에 모든
소설의 죽은 작업을 한 번 환불하지만, 교체에서는 새 색이 옛 색의 드레인보다 **먼저** 뜨므로 드레인이 죽인 작업은 그 정리
시각에 아직 만료 전이라 놓칠 수 있다. **옛 이미지로 롤백하면 이 정리가 없고 스키마를 내리면 작업 행이 사라져 환불 근거가
없어진다.** 그래서 먼저 비운다:

1. (선택) 어드민에서 허용 계정들의 토글을 끈다 — 재기동 없이 새 작업이 바로 403 이 된다. 이미 돌던 작업은 끝까지 돈다.
2. 살아 있는 진행 중 작업이 0 이 될 때까지 기다린다. 작업 하나의 상한이 `NOVELIZE_JOB_TIMEOUT_SECONDS`(기본 360초)라
   단일 작업은 길어야 그만큼이다. 연쇄 생성("남은 대화 한 번에")의 부모 작업(`kind = 'chain_generate'`)은 자식 작업을
   차례로 띄우며 그동안 진행 중으로 남고, 상한이 따로다 — 계획한 묶음 수 × (`NOVELIZE_JOB_TIMEOUT_SECONDS` + 경계 제안
   타임아웃 `GEMINI_NOVELIZE_BOUNDARY_TIMEOUT_MS`) + `NOVELIZE_CHAIN_TIMEOUT_MARGIN_SECONDS`, 기본값이면 묶음 5개에
   5 × 390 + 60 = 2,010초다. 연쇄 부모만 세려면 아래 SQL 에 `AND kind = 'chain_generate'` 를 더한다. heartbeat 조건을
   빼면 이미 죽은 작업이 끝내 0 이 되지 않는다 — 그건 4단계가 따로 센다.

   ```sh
   sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
     psql -U postgres -d ai_character_chat -Atc \
     "SELECT count(*) FROM novel_jobs WHERE status IN ('queued','running') AND heartbeat_at >= now() - interval '60 seconds';"
   ```

3. 0 을 본 뒤 끄기·회수·롤백을 진행한다.
4. 사후 확인 — 같은 명령에서 조건만 `heartbeat_at < now() - interval '60 seconds'` 로 바꿔 0 이어야 한다. 실패로 가는 길은
   환불 함수 하나뿐이라 "실패인데 환불 안 됨"은 생기지 않고, 환불이 묶이는 것은 죽은 채 진행 중으로 남은 작업뿐이다.
   0 이 아니고 새 이미지가 떠 있으면 태그 없는 교체(`sudo bash ops/swap-api.sh`)를 한 번 더 한다 — 그 교체로 뜬 색의
   기동 70초 뒤 정리가, 앞 교체의 드레인이 죽여 이제 만료된 작업을 환불한다(새 작업이 없으니 이 교체는 아무것도 죽이지
   않는다). 옛 이미지라면 손으로 환불하기 전에 그 작업 id·사용자·
   `charged_amount` 를 기록으로 남긴다.

(`60 seconds` 는 `NOVELIZE_HEARTBEAT_EXPIRY_SECONDS` 기본값이다 — 바꿨으면 같이 바꾼다.)

**끄기** — 진행 중 작업 0 을 확인한 뒤 스위치 줄을 지우고 다시 올린다:

```sh
cd /opt/ddona/app
sudo sed -i '/^NOVELIZE_ENABLED=/d' /opt/ddona/.env
sudo python3 ops/check_env.py --format /opt/ddona/.env
sudo bash ops/swap-api.sh
```

모든 계정에서 소설 화면·API 가 403 이 되고 진입점이 사라진다(새로고침 뒤). 허용 행·명단·소설 데이터는 남아 다시 켜면
그대로 돌아온다. 꺼진 동안 사용자가 소설을 지우려면 탈퇴하거나 문의로 지운다(진입점이 없다). 줄을 지웠으니 키 개수
문장을 다시 센다.

**회수(한 계정)** — 어드민 유저 상세에서 그 계정의 허용 토글을 끄면 재기동 없이 바로 막힌다. 어드민을 거치지 않고
확실히 막으려면 진행 중 작업 0 확인 뒤 명단에서 그 id 를 빼고(`sudo sed -i` 로 그 줄을 고친다) 형식 검사 → `sudo bash
ops/swap-api.sh` — 허용 행이 남아 있어도 명단 밖이면 접근 시점에 막힌다.

**롤백** — 스위치를 켠 적이 있으면 되돌릴 태그와 상관없이 **진행 중 작업 0 확인 → 끄기 → 롤백** 순서다. 태그 롤백은
"BE → GCE VM" 절의 한 줄(`sudo DDONA_ROLLBACK=1 bash ops/swap-api.sh <이전SHA>` 또는 Actions 수동 실행의 `image_tag`)이다 —
아래처럼 이미지만 되돌리면 DB 가 옛 이미지보다 앞서 있어 롤백 표시 없이는 교체 스크립트가 멈춘다. 끄기 교체가 끝나고
60초(heartbeat 만료) 넘게 지난 뒤, 롤백 교체 **직전에** 위 2단계 SQL 과 4단계 SQL 이 둘 다 0 인지 다시 본다 — 첫 확인과 끄기
교체의 드레인 사이에 시작된 작업이 그 드레인으로 죽었을 수 있고, 그때는 4단계대로 태그 없는 교체로 먼저 환불한다. 롤백해 둔
동안 env 를 바꿔 다시 교체할 때(소설화를 다시 켤 때 포함)도 `sudo DDONA_ROLLBACK=1 bash ops/swap-api.sh` 로 표시를 붙인다("BE → GCE VM" 절의 "롤백").

**묶음·화 구조 배포의 겹침.** 묶음·화 구조 세 리비전(아래)은 평상시 겹침 교체로 배포한다(`skip_overlap` 불필요). 마이그레이션 뒤
옛 색이 새 스키마에서 도는 수십 초는 아래 「이미지만 되돌린다」와 같은 조건이라, 옛 코드의 장·작업 INSERT(새 칸은 nullable
이거나 기본값이 있다), 금액 없이 `refunded_at` 만 찍는 옛 환불(환불 CHECK 의 옛 코드 호환 갈래), 화·소설 삭제(새 자식 테이블은
cascade), 진행 중 1건 유니크(옛 코드의 작업은 늘 연쇄 자식이 아니라 조건이 같다), 프롬프트 조회(채팅 레인 행은 그대로이고 옛
어드민 목록은 모르는 레인을 건너뛴다)가 그대로 돈다. 남는 것은 두 색이 함께 요청을 받는 몇 초 동안 새 코드가 만든 연쇄 부모나 새
실패 사유 작업을 옛 색이 읽으면 그 소설의 상세·작업 응답 하나가 500 이 되는 것이다 — 허용 계정만 해당되고 다음 요청은 새 색으로
간다.

**묶음·화 구조 이전 이미지로 되돌릴 때 — 이미지만 되돌린다.** 소설을 묶음(생성 한 번)과 화로 나눈 세 리비전
(`4a4af1ac1df8` 묶음·화 스키마 → `3af53088351c` 작업 행·환불 → `a7a87e3ba631` 소설 프롬프트 레인)은 내리지 않아도 옛 코드가
돈다. 새 테이블은 소설·화에 `ON DELETE CASCADE` 라 옛 코드의 화·소설 삭제와 탈퇴가 막히지 않고, 화 행은 묶음 구간의 사본을
그대로 갖고, 화의 묶음 칸(`batch_id`)은 비어도 되며, 옛 코드가 읽는 소설 문안(채팅 레인에 남겨 둔 행)도 그대로다.
🔴 **전제: 진행 중 작업 0, 특히 연쇄 부모 0**(위 확인 SQL). 옛 코드는 연쇄 부모 종류(`chain_generate`)와 새 실패 사유
(`malformed`·`episode_count_mismatch`)를 모른다 — 진행 중인 새 작업이 남은 채 옛 이미지가 뜨면 그 소설의 상세·작업 폴링이
500 이 되고, 죽은 연쇄 부모를 옛 만료 정리가 환불할 때 이미 만든 묶음 몫(소비액)을 모르고 차감액 전액을 돌려준다(만든 화는
남는다). 롤백한 채 소설화를 다시 켜려면 web 도 묶음·화 구조 이전 판으로 되돌리거나, 아니면 켜지 않고 둔다 — 새 web 은 옛
API 와 맞지 않는다(상세에 묶음 목록이 없어 다시 만들기가 `batches.find` TypeError 로 깨지고, 경계 후보에 금액이 없어 화 생성
요청이 `expectedCost` 없이 가서 422 다). 옛 이미지가 떠 있는 동안 알려진 동작:

- 화가 여럿인 묶음은 옛 화면에서 같은 구간의 장 여러 개로 보인다(화 행마다 묶음 구간의 사본을 갖는다).
- 그중 하나를 옛 화면에서 다시 만들면 묶음 전체 원문이 그 장 하나에 다시 쓰인다.
- 옛 코드가 만든 장은 묶음 없는 화(`batch_id` NULL)로 남는다. 새 이미지를 다시 올리면 그 소설의 상세를 열거나 새 작업·다시
  만들기·마지막 묶음 삭제를 할 때 런타임 보정(`novelize/batches.py` 의 `ensure_batches`)이 빈 묶음을 지우고 그런 화를 묶음
  하나씩에 넣는다 — 마이그레이션이나 보정 스크립트를 따로 돌리지 않는다.
- 옛 어드민에서 스토리·캐릭터 레인의 소설 문안을 고쳐 게시하면 옛 코드는 그 문안으로 돈다. 새 이미지는 소설 레인에서
  읽으므로 그 수정은 다시 올린 뒤 따라오지 않는다 — 살릴 수정이면 어드민 「소설」 탭에 손으로 옮겨 게시한다.
- 옛 코드로 마지막 장을 지우면 스냅샷의 그 화 항목이 지워진 표시로 줄지 않는다(옛 코드는 스냅샷을 모른다). 새 이미지를
  다시 올린 뒤 그 스냅샷을 복원하면 그 화는 화가 없어 건너뛴 화(`skippedChapters`)로 나온다.
- 이 동안 소설 레인(`novel`) 세트를 SQL 로 지우지 않는다. 옛 코드는 레인으로 세트를 골라 그 세트를 읽지 않고, 다시 올릴 때
  `alembic upgrade head` 는 이미 적용된 리비전을 건너뛰어 지운 체인이 빈 채로 남는다(화 생성 실패·환불, 「소설」 탭 초안
  조회 500).

**소설화 이전 이미지까지 되돌릴 때** 알려진 문제(위 전제와 동작에 더해):

- 소설화를 쓴 계정의 **클로버 내역이 500** 이다. 소설화 차감·환불 원장 행이 남는데(원장 `kind` 는 Text 라 값 제약이 없다) 옛
  코드의 내역 API 가 모르는 `kind` 를 범주 맵에서 찾다 실패한다. 영향은 허용했던 계정뿐이다. 잔액·차감은 정상이다.
- 그 계정들의 **어드민 유저 상세가 500** 이다. 허용 토글이 남긴 감사 로그의 조치 종류를 옛 응답 스키마가 모른다.
- story·character 레인의 **어드민 프롬프트 게시가 막힌다.** 마이그레이션이 두 레인 초안에 소설화 행을 더했는데 옛 코드의
  게시 검증이 그 행을 "잉여"로 거부한다. 채팅 렌더는 소설화 채널을 읽지 않아 무사하다. 이 동안에는 두 레인을 복원·게시하지
  않는다 — 소설화 행이 없는 버전이 활성이 되면, 새 이미지를 다시 올린 뒤 그 레인 게시가 "누락"으로 막힌다(새 코드는 채팅
  레인 게시 때 남겨 둔 소설 행을 활성 세트에서 가져오는데 거기 없다). 예전에 이 경우를 고치던 "프롬프트 시드 리비전만
  내렸다 올리기"(`alembic downgrade 668c7ae16cc0` → `upgrade head`)는 더 쓰지 않는다 — 지금 head 에서는 그 위의 엔딩 우선
  스탯·모델 축·방 모델·장 작업 모델 리비전까지 내렸다 올려 그 값이 사라지고, 화가 여럿인 묶음이 하나라도 있으면 묶음·화
  스키마 리비전의 downgrade 거부에서 멈춘다.
- 그동안 허용 계정이 **탈퇴하면 소설·장·개정·작업·허용 행이 지워지지 않고 남는다.** 옛 코드의 탈퇴 파기는 소설화 테이블을
  모르고, 새 이미지를 다시 올려도 소급해 지우지 않는다 — 손으로 지운다.

**롤백 뒤 새 이미지를 다시 올릴 때** — 태그 롤백 중에는 무관한 PR 이라도 main 에 병합되면 자동 배포가 api 를 새
코드로 다시 교체하므로 그때도 같다. 마이그레이션은 이미 적용돼 다시 돌지 않고, 손으로 할 일은 없다. 옛 코드가 만든 묶음 없는
화는 위 런타임 보정이 채운다. 확인은 아래 「활성 세트 확인」 SQL 로 소설 레인 세 체인이 그대로인지 본다.

**스키마까지 되돌릴 때** — main 에 revert 커밋을 올려 옛 코드로 롤백을 굳힐 때는 그 병합 **전에** 아래 downgrade 를 마친다.
안 하면 그 배포(롤백 표시 없는 `main` push 배포)의 교체 스크립트가 DB 가 이미지보다 앞서 있음을 보고 실패한다 — 옛 색이
계속 서빙하니 downgrade 를 마친 뒤 다시 배포한다("참조 이미지 켜기 · 끄기 · 롤백" 절과 같은 경우다). 순서는 "참조 이미지 켜기 · 끄기 · 롤백" 절과 같다: **태그 롤백으로 옛 코드부터 띄우고 →
새 이미지로 downgrade**(옛 이미지에는 이 리비전 파일이 없고, 먼저 내리면 떠 있는 새 코드가 없어진 테이블을 읽다 실패한다).
마이그레이션 체인은 한 트랜잭션이라, 도중의 리비전이 거부하면 그 앞에서 내린 리비전도 함께 되돌려진다. 둘 다 되살릴 수 없는
데이터를 지우므로 백업을 먼저 뜬다.

*묶음·화 구조만 내릴 때*(목표 `2494aa0e607e`, 장 작업 모델 리비전) — 이미지만 되돌려도 옛 코드가 도므로 대개 필요 없다:

```sh
sudo /opt/ddona/backup.sh   # 먼저 백업
sudo docker run --rm --network ddona_default --env-file /opt/ddona/.env \
  <IMAGE>:<새 코드 TAG> alembic downgrade 2494aa0e607e
```

- **거부**: 화가 둘 이상인 묶음이 하나라도 있으면 묶음·화 스키마 리비전(`4a4af1ac1df8`)이, 부분 환불된 성공 작업·연쇄
  부모·연쇄 자식·새 실패 사유(`malformed`·`episode_count_mismatch`) 작업 행이 하나라도 있으면 작업 행 리비전
  (`3af53088351c`)이 아무것도 바꾸기 전에 `RuntimeError` 로 멈춘다. 오류 메시지에 정리 방법이 있다 — 여러 화 묶음은 새 코드가
  떠 있는 동안 그 소설에서 뒤에서부터 지운다(마지막 묶음 삭제).
- **성공해도 사라지는 것**: 소설 레인(`novel`) 세트 전부(어드민이 만든 초안·게시본 포함), 소설 제목·소개·표지 선택·보드
  배치, 화 제목·요약·작가의 말, 인물 카드와 화별 등장 인물, 스냅샷, 읽은 위치, 작업 행의 환불액·대상 묶음·화 수 목표·단가·
  소비액·연쇄 계획 칸. 화 본문·개정·작업 행과 채팅 레인의 소설 문안 행은 남는다.

*소설화 전체를 내릴 때*(목표 `00ce650038ba`) — **소설·장·개정·작업·계정별 허용 행이 전부 지워진다.** 지금 head 에서 이
목표로 내리면 소설화 리비전들만이 아니라 그 위에 쌓인 엔딩 우선 스탯(`a966fc016bf1`)·모델 축(`e6aa289fea62`)·방
모델(`519329713933`)·장 작업 모델(`2494aa0e607e`) 리비전과 묶음·화 구조 세 리비전까지 함께 내린다 — 엔딩의 우선 스탯 값,
Claude 프롬프트 세트, 방마다 고른 모델도 사라지고, 위 묶음·화 구조의 거부 조건이 그대로 걸린다. 그래서 먼저 위 「묶음·화
구조만 내릴 때」를 통과시키고, 상위 모델 리비전은 "상위 모델(Bedrock) — 꺼진 채 배포 · 켜기 · 끄기" 절의 롤백 순서를 본 뒤에
내린다:

```sh
sudo /opt/ddona/backup.sh   # 먼저 백업
sudo docker run --rm --network ddona_default --env-file /opt/ddona/.env \
  <IMAGE>:<새 코드 TAG> alembic downgrade 00ce650038ba
```

- 소설화 프롬프트 채널 리비전(`3bb2cc159b6d`)의 downgrade 는 그 리비전이 심은 프롬프트 세트 둘과 두 레인 초안의 소설화
  행을 지운다. 활성은 그 마이그레이션 직전 세트로 돌아간다(게시 시각 최신 규칙). 그 사이 운영자가 소설화 행이 든 새 버전을
  게시했다면 그 버전은 남아 활성이고 옛 코드에서 그 레인 게시가 계속 막힌다 — 마이그레이션 직전 활성 버전을 복원해 게시한다.
- 거꾸로 **새 코드에서 소설화 채널이 없는 버전을 복원하면 채팅 레인 게시가 "누락"으로 막힌다** — 받아들인 제약이다.
- 원장 행과 감사 로그 행은 downgrade 뒤에도 남는다 — 위 클로버 내역 500 과 어드민 유저 상세 500 은 옛 이미지가 떠 있는 한
  계속된다.

활성 세트 확인(배포 직후, 롤백 전후):

```sh
sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
  psql -U postgres -d ai_character_chat -c \
  "SELECT DISTINCT ON (lane, model) lane, model, id, version, published_at FROM prompt_sets WHERE status = 'published' AND lane IN ('story','character','novel') ORDER BY lane, model, published_at DESC;"
```

`model` 열은 모델 축 리비전(`e6aa289fea62`, 아래 3-12 절) 이후에만 있다 — 그보다 아래로 내린 DB 에서는 `model` 을 빼고
`DISTINCT ON (lane)` 으로 본다. `novel` 레인은 묶음·화 구조 이후에만 있다.

마이그레이션이 심는 세트 id 는 환경 공통 리터럴이다. 소설화 프롬프트 채널 리비전(`3bb2cc159b6d`): story
`b5305c39-e0af-4d32-ac28-578550b31fb9`, character `502dcff3-66ce-46ad-8c84-13dbba6fe81a`(버전은 배포 시점 전 레인 게시 최대 + 1,
story 먼저). 소설 프롬프트 레인 리비전(`a7a87e3ba631`): `novel` 레인 Gemini 옛 문안 사본 `43c582e7-02c3-4d63-9c8d-ea466e9db3f8`,
Gemini 활성 `85102fbf-51a6-48bb-a44f-b320eaa6325d`, Sonnet `dace3703-a59e-4d5d-b765-a64085001771`, Opus
`2b816f0c-0de0-4d23-ac90-6648c705d271` — 어드민이 게시하기 전이면 (novel, gemini)·(novel, sonnet)·(novel, opus) 행이 뒤의 셋이다.

### 3-12. 상위 모델(Bedrock) — 꺼진 채 배포 · 켜기 · 끄기

채팅 턴 생성과 소설 장 생성은 Gemini 대신 AWS Bedrock 의 Claude(Sonnet·Opus)로 돌 수 있다. 판정·요약·발행 심사·문단 수정은
고른 모델과 무관하게 Gemini 다. 상위 모델은 채팅·소설화에 한 벌씩 스위치(`CHAT_PREMIUM_MODELS_ENABLED`·
`NOVELIZE_PREMIUM_MODELS_ENABLED`)와 env 명단으로 닫혀 있고, 코드 기본값이 꺼짐·빈 명단이라 **배포만으로는 닫힌 채 뜬다.**

**꺼진 채 배포 — 키 넣는 순서.** 키는 스위치보다 먼저, 스위치 없이 넣는다. 옛 이미지는 모르는 키를 무시하므로 이미지 배포
앞뒤 어느 쪽에 넣어도 된다.

1. AWS 콘솔에서 Bedrock 모델 호출만 허용한 전용 IAM 사용자의 액세스 키를 만든다. R2 키(`AWS_ACCESS_KEY_ID` 등)를 재사용하거나
   그 줄을 고치지 않는다 — 그 줄들은 boto3 가 R2 자격으로 읽는다.
2. Bedrock 계정 설정에서 모델 호출 로깅(model invocation logging)이 꺼져 있는지 본다. 개인정보 처리방침 초안이 대화 원문을
   AWS 쪽에 남기지 않는다는 전제로 쓰였다.
3. `.env` 에 두 줄을 더한다(리전은 기본값이면 생략). 파일을 통째로 덮거나 백업본으로 복원하지 않는다(교체 스크립트가 같은
   파일의 `API_IMAGE_BLUE`·`API_IMAGE_GREEN` 을 고친다). 값은 셸 기록에 남지 않게 편집기로 넣어도 된다:

   ```sh
   cd /opt/ddona/app
   sudo sh -c 'printf "\nBEDROCK_ACCESS_KEY_ID=<키 id>\nBEDROCK_SECRET_ACCESS_KEY=<비밀 키>\n" >> /opt/ddona/.env'
   sudo python3 ops/check_env.py --format /opt/ddona/.env
   sudo bash ops/swap-api.sh
   # 값은 찍지 않고 들어갔는지만 본다 — True True ap-northeast-2 False False 여야 한다.
   sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env exec -T api_$(sudo bash ops/active-color.sh) python -c \
     "from api.core.config import settings as s; print(bool(s.bedrock_access_key_id.strip()), bool(s.bedrock_secret_access_key.strip()), s.bedrock_region, s.chat_premium_models_enabled, s.novelize_premium_models_enabled)"
   ```

4. "BE 런타임" 절의 키 개수 문장을 VM 에서 다시 세어 고친다.

키만 있고 스위치가 꺼져 있으면 아무 호출도 Bedrock 으로 가지 않는다.

**켜기.** 위 확인에서 키 두 개가 `True` 인 것을 먼저 본다 — 🔴 스위치가 켜졌는데 키나 리전이 비어 있으면 api 가 기동하지
못한다. 교체 스크립트의 새 색이 healthy 가 안 돼 교체가 실패하고(옛 색은 그대로 서빙, 종료코드 1), 그 줄을 고치기 전에는
다음 배포도 같은 이유로 실패한다. 그다음 쓸 기능의 스위치와 명단만 더한다(채팅만이면 `CHAT_PREMIUM_*` 두 줄, 소설 장까지면
`NOVELIZE_PREMIUM_*` 두 줄도):

```sh
cd /opt/ddona/app
sudo sh -c 'printf "\nCHAT_PREMIUM_MODELS_ENABLED=true\nCHAT_PREMIUM_MODEL_ALLOWLIST=<계정 id>,<계정 id>\n" >> /opt/ddona/.env'
sudo python3 ops/check_env.py --format /opt/ddona/.env
sudo bash ops/swap-api.sh
```

`restart` 는 env 를 다시 읽지 않으므로 교체 스크립트를 태그 없이 부른다("env 반영 재기동" 절). 줄을 넣었으니 키 개수 문장을 다시 센다.

**계정 허용.** 스위치와 명단만으로는 아직 아무도 못 쓴다 — 계정마다 허용 행이 있어야 한다(채팅·소설 따로).

1. 명단에 그 계정 id 가 있는지 본다(위 `CHAT_PREMIUM_MODEL_ALLOWLIST`·`NOVELIZE_PREMIUM_MODEL_ALLOWLIST`). 명단 밖 계정의 허용은
   어드민이 422 `CHAT_PREMIUM_MODELS_GRANT_NOT_ALLOWLISTED`·`NOVELIZE_PREMIUM_MODELS_GRANT_NOT_ALLOWLISTED` 로 거절한다.
2. 어드민 유저 상세에서 허용을 켠다 — API 로는 `POST /admin/users/{id}/chat-premium-models-grant`·
   `POST /admin/users/{id}/novelize-premium-models-grant` 에 `{"granted": true, "adminComment": "…"}`. 스위치가 꺼져 있어도 미리 줄
   수 있다. 소설 상위 모델은 그 계정에 소설화 허용(3-11 절)도 있어야 보인다.
3. 클로버를 지급한다. 상위 모델 턴·소설 화는 레이트리밋 면제 계정도 값을 내고(턴 Sonnet 40·Opus 65, 소설은 화 하나당
   Sonnet 105·Opus 170 이라 생성 한 번이 화 수 × 화 단가다 — `api/core/clover.py`), 하루 무료분은 Gemini 턴에만 쓰인다.
4. 그 계정의 web 을 새로고침하면(세션 정보를 다시 받는다) 채팅 더보기에 모델 선택이 보인다. 고른 모델은 방마다 저장되고 다음
   턴부터 그 모델·그 가격으로 돈다.
5. 소설 상위 모델은 장 생성·재생성 요청마다 고른다(방처럼 저장하지 않는다). 허용이 들어갔는지는 그 계정으로 소설 상세
   (`GET /novels/{id}`)를 열어 `chapterModels` 에 Sonnet·Opus 가 실렸는지로 본다 — 허용이 없으면 Gemini 하나뿐이다. 장 작업은
   요청한 모델을 `novel_jobs.model` 에 적고, 실행은 그 값으로 돈다.

회수는 어드민에서 허용을 끄는 것(재기동 없음) 또는 명단에서 지우고 `sudo bash ops/swap-api.sh` 다. 허용 행만 남은 계정도 명단 밖이면
접근 시점에 막힌다. 소설은 회수 뒤의 장 요청이 상위 모델이면 403 `NOVEL_MODEL_NOT_ALLOWED` 다(방과 달리 Gemini 로 바꿔
받지 않는다 — 장 요청의 모델은 그 가격과 함께 지금 고른 값이다). 회수 전에 값을 낸 장 작업은 회수와 무관하게 그 모델로 끝난다.

**끄기.** 스위치 줄만 지우고 다시 올린다. 키·명단 줄은 남겨 두면 다시 켤 때 스위치 한 줄이면 된다:

```sh
cd /opt/ddona/app
sudo sed -i '/^CHAT_PREMIUM_MODELS_ENABLED=/d;/^NOVELIZE_PREMIUM_MODELS_ENABLED=/d' /opt/ddona/.env
sudo python3 ops/check_env.py --format /opt/ddona/.env
sudo bash ops/swap-api.sh
```

끄거나 허용을 거둬도 **상위 모델을 고른 방은 막히지 않는다.** 방에 저장된 모델(`chat_rooms.chat_model`)은 그대로 남고, 그
방의 다음 턴은 Gemini 로 Gemini 가격(하루 무료분 포함)에 돈다. 방 응답과 모델 목록은 실제로 쓰일 모델(Gemini)을 보인다. 다시
켜면 저장된 모델로 돌아간다. 진행 중이던 턴과 소설 장 작업은 이미 값을 낸 모델로 끝난다(스위치를 껐다고 Gemini 로 바꾸지
않는다 — 상위 모델 값을 내고 Gemini 글을 받게 된다). 끄는 동안 Redis 일부 장애가 나도 Gemini 턴은 지금처럼
통과한다(상위 모델 턴만 503 `CHAT_MODEL_UNAVAILABLE` 로 거절된다 — 켜져 있을 때의 동작이다).

**키 교체·회수.** 새 키를 만든 뒤 `.env` 의 두 줄을 `sudo sed -i` 로 바꾸고 형식 검사 → `sudo bash ops/swap-api.sh` → 위 확인 명령,
그다음 AWS 콘솔에서 옛 키를 비활성화한다. 키가 새어 나갔으면 먼저 콘솔에서 비활성화한다 — 스위치가 켜져 있으면 그동안의
상위 모델 호출은 실패하고 환불된다.

**보는 곳.** Bedrock 호출 한 건마다 API 로그에 `bedrock_usage` 줄(입력·캐시 읽기·캐시 쓰기·출력 토큰)이 남고, 사용량 집계
(`llm_usage_report.py --model global.anthropic.claude-sonnet-4-6` 처럼 실제 모델 id 로 좁힌다)와 어드민 사용량 화면에 Gemini
호출과 같은 표로 나온다. 채팅에서 흡수된 실패는 Bugsink 태그 `dependency=bedrock`(쿼터 소진은 `bedrock_rate_limit`)로
Gemini 와 따로 묶인다. 소설 장 실패는 공급자와 무관하게 지금처럼 `dependency=novelize` 다.

**프롬프트 세트와 롤백.** 이 배포의 마이그레이션(`e6aa289fea62`)이 `prompt_sets` 에 모델 열을 더하고 Claude 세트 네 개
(story·character × Sonnet·Opus, 그 레인 Gemini 활성 세트의 `system`·`generation` 사본)를 게시본으로 심는다. 초안은 심지 않고,
게시 시각은 원본 Gemini 세트보다 1초 과거다 — 모델 열을 모르는 옛 코드는 레인만 보고 최신 게시본을 고르므로 계속 Gemini
세트를 집는다. 그래서:

- 어드민에서 Claude 세트를 새로 저장·게시하지 않았다면 **이미지만 되돌려도 안전하다**.
- 저장·게시했다면 이미지를 되돌리기 **전에** 어드민이 만든 Claude 행을 지운다. 남겨 두면 옛 코드가 그 초안·게시본을 레인의
  초안·최신 게시본으로 읽는다(초안 조회 500, 판정·요약 채널이 없는 세트가 활성). 마이그레이션이 심은 시드 세트 4개(아래 id)는
  **남긴다** — 시드까지 지우면 나중에 새 이미지를 다시 올릴 때 `alembic upgrade head` 가 이미 적용된 리비전을 건너뛰어 Claude
  체인이 빈 채로 남는다(어드민 초안 조회 `?model=sonnet` 500, 상위 모델 턴 실패). 시드는 남겨도 옛 코드에 안전하다 — 게시 시각이
  원본 Gemini 세트보다 1초 과거라 레인만 보는 "최신 게시본" 조회가 집지 않고, 초안이 아니라 초안 조회에도 걸리지 않는다.
  스위치가 꺼져 있으면 새 코드에도 영향이 없다. 🔴 소설 레인(`novel`)의 Claude 세트는 지우지 않는다(아래 SQL 의
  `lane <> 'novel'`) — 그 레인의 Sonnet·Opus 체인은 소설 프롬프트 레인 리비전(`a7a87e3ba631`)이 심은 것이라 위 시드 4개
  목록에 없고, 지우면 다시 올린 뒤 그 체인이 빈 채로 남아 상위 모델 화 생성이 실패·환불되고 어드민 「소설」 탭 초안 조회가
  500 이 된다. 옛 코드는 레인으로 세트를 골라 소설 레인을 읽지 않는다:

  ```sh
  sudo /opt/ddona/backup.sh   # 먼저 백업
  sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
    psql -U postgres -d ai_character_chat -c \
    "BEGIN; DELETE FROM prompt_sections WHERE prompt_set_id IN (SELECT id FROM prompt_sets WHERE model <> 'gemini' AND lane <> 'novel' AND id NOT IN ('ba2a926c-e9ed-46e0-b42c-9c21c63552f6','f3237e56-5ff6-4b27-9135-98495c0094bb','b9c2f1ec-5e8c-48ce-8fc9-ffefdc6950d2','9b308ef1-bdb9-4f23-a2d8-fb6ae6ad778c')); DELETE FROM prompt_sets WHERE model <> 'gemini' AND lane <> 'novel' AND id NOT IN ('ba2a926c-e9ed-46e0-b42c-9c21c63552f6','f3237e56-5ff6-4b27-9135-98495c0094bb','b9c2f1ec-5e8c-48ce-8fc9-ffefdc6950d2','9b308ef1-bdb9-4f23-a2d8-fb6ae6ad778c'); COMMIT;"
  ```

- 스키마까지 되돌리면(`alembic downgrade a966fc016bf1`, 순서는 위 절들과 같이 태그 롤백 먼저 — 묶음·화 구조 리비전이 위에
  있으면 그것부터, 아래 「롤백 순서」 4단계) downgrade 가 Gemini 가 아닌
  세트 전부(시드 + 어드민이 만든 것)를 지우고 인덱스를 되돌린 뒤 열을 지운다. 그 위의 방 모델·장 작업 모델 리비전(`519329713933`·
  `2494aa0e607e`, 아래)이 먼저 내려가야 하므로 이 한 줄이 셋 다 내린다. 목표는 엔딩 우선 스탯 리비전(`a966fc016bf1`)이다 —
  이 배포의 세 리비전이 그 위에 쌓여 있어, 그보다 아래(`3bb2cc159b6d`)로 내리면 엔딩의 우선 스탯 열과 값까지 지워진다.
- 앞으로 슬롯을 더하는 마이그레이션은 Gemini 두 레인뿐 아니라 Claude 체인 네 개도 다룰지 판단한다 — `system`·`generation`
  슬롯이면 Claude 체인에도 넣어야 게시 검증의 슬롯 집합이 맞는다.
- 앞으로 활성·초안 세트를 원시 SQL 로 고르는 마이그레이션은 반드시 모델로 거른다(`AND model = 'gemini'` 또는 대상 모델). 레인만
  보는 조회는 Claude 세트를 집을 수 있고, 초안을 한 행으로 읽으면 레인에 초안이 둘 이상일 때 `MultipleResultsFound` 로 깨진다.

**롤백 순서.** 1차는 스위치 끄기(위 「끄기」)다 — 재기동 한 번으로 모든 턴·장이 Gemini 로 돌고 방은 막히지 않는다. 코드까지
되돌릴 때는 스위치를 끈 뒤 태그 롤백(옛 이미지)을 하고, 스키마는 그 뒤에 내린다:

1. 스위치를 끄고 진행 중인 소설 작업이 0 인지 본다(연쇄 부모 포함, 3-11 절의 확인 SQL). 🔴 옛 이미지는 작업의 모델 칸을
   모르므로, 진행 중인 상위 모델 화 작업이 남은 채 옛 이미지가 뜨면 그 작업은 상위 모델 값을 낸 채 Gemini 로 돈다.
2. 어드민에서 Claude 세트를 저장·게시했다면 위의 Claude 행 삭제(시드 4개 제외)를 먼저 한다.
3. 태그 롤백(`sudo DDONA_ROLLBACK=1 bash ops/swap-api.sh <이전SHA>`, 진행 중 작업 재확인은 3-11 절 「롤백」)으로 옛 이미지를 띄운다. 옛 코드는 방 모델 열(`chat_rooms.chat_model`)을 모르고 읽지 않으며, 새 방도 그 열이 NULL 로
   들어가 그대로 돈다. 상위 모델 허용 행(`user_feature_grants` 의 새 기능 값)은 옛 코드가 소설화 행만 골라 읽어 영향이 없다.
   다만 어드민에서 상위 모델 허용을 켜고 끈 계정은 옛 코드에서 **어드민 유저 상세가 500** 이다 — 그 감사 로그의 조치
   종류(`user-chat-premium-models-on` 등)를 옛 응답 스키마가 모른다(3-11 절의 소설화 토글과 같은 성질). 장 작업의 모델 칸
   (`novel_jobs.model`)도 옛 코드가 읽지 않고, 새 작업은 그 칸이 NULL(Gemini)로 들어간다.
4. 스키마까지 되돌리면 옛 이미지가 떠 있는 상태에서 새 코드 이미지로 내린다. 🔴 **묶음·화 구조 리비전(`4a4af1ac1df8`·
   `3af53088351c`·`a7a87e3ba631`)이 위에 있으면 먼저 3-11 절의 「묶음·화 구조만 내릴 때」로 `2494aa0e607e` 까지 내린다** —
   아래 세 줄을 그 위에서 바로 돌리면 그 세 리비전도 함께 내리려다 거부 조건에 걸려 멈추거나, 통과하면 그 절의 묶음·화 구조 전용
   데이터가 같이 사라진다. 그다음 리비전은 위에서부터 장 작업 모델
   (`2494aa0e607e`) → 방 모델(`519329713933`) → 모델 축(`e6aa289fea62`) 순서로 엔딩 우선 스탯 리비전(`a966fc016bf1`) 위에
   쌓여 있다. 장 작업 모델 리비전만 내리면 작업마다 적은 모델이 사라지고(차감액은 남는다), 방 모델 리비전까지 내리면 방마다
   고른 모델이 사라지고(전부 Gemini), 그 아래 모델 축 리비전까지 내리면 Claude 세트 전부(시드 포함) 삭제도 함께 일어난다.
   마지막 줄보다 더 내리지 않는다 — 엔딩 우선 스탯 열은 이 배포와 무관하다:

   ```sh
   sudo /opt/ddona/backup.sh   # 먼저 백업
   # 장 작업 모델 열만
   sudo docker run --rm --network ddona_default --env-file /opt/ddona/.env <IMAGE>:<새 코드 TAG> alembic downgrade 519329713933
   # 방 모델 열까지
   sudo docker run --rm --network ddona_default --env-file /opt/ddona/.env <IMAGE>:<새 코드 TAG> alembic downgrade e6aa289fea62
   # 모델 축까지(Claude 세트 삭제 포함)
   sudo docker run --rm --network ddona_default --env-file /opt/ddona/.env <IMAGE>:<새 코드 TAG> alembic downgrade a966fc016bf1
   ```

---

## 4. 배포 후 스모크 검증

1. `curl https://api.ddona.site/health` → `{"status":"ok"}` · `/ready`로 DB·Redis까지 확인. 배포 로그에서 교체 스크립트의
   마지막 줄이 `13) 완료: active=<색> … 이미지 …:<태그>`이고 그 뒤 실행 이미지 확인 줄이 같은 태그인지도 본다(이행 배포면
   그 앞에 `8) 부트스트랩 정리 완료`) — `/health` 200 은 옛 이미지도 낸다
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
`aspect_ratio` 문자열을 보낸다. 여기에 **참조 이미지**가 붙을 수 있다 — `LOCAL_IMAGE_REFERENCE_ENABLED`가 켜져
있고 사용자가 참조를 골랐을 때만, 이 서비스가 만든 **그 사용자 본인의 생성 이미지** 원본을 저장소에서 읽어
base64로 싣는다(리사이즈 없음). 싣기 전에 서버가 형식(PNG·JPEG·WebP)·각 변 64~4096px·인코딩 길이 8,000,000자
이하를 검사하고, 참조가 없으면 필드 자체를 싣지 않는다.

생성 잡은 기존과 동일하게 응답(202) 뒤 `asyncio.create_task`로 돌고, 이미지는 그대로 R2에 올라간다.
서버는 GPU 호출을 uvicorn 워커 수와 무관하게 한 번에 하나로 직렬화하고(워커 안은 `asyncio.Semaphore(1)`,
워커 사이는 Redis 락 `local_image:generation_lock` — 집 PC 는 동시 요청을 대기열 없이 즉시 429 로 거절하므로 둘이
겹치면 그 장이 실패한다), 모든 워커가 함께 보는 대기열(Redis 정렬 집합 `local_image:admitted`,
`LOCAL_IMAGE_QUEUE_LIMIT`, 기본 4)로 깊이를 제한해 초과 요청은 잡을 만들지 않고 즉시 429로 거절한다. 락은 TTL
(생성 타임아웃 + 30초, 기본 120초)이 있고 호출 전체를 생성 타임아웃 + 15초에서 끊으며, 대기열 칸은 잡이 도는
동안 20초마다 만료(60초)를 민다 — 워커가 해제 없이 죽어도(배포 재생성) 락은 TTL 뒤, 칸은 최대 60초 뒤 풀린다(그
사이 같은 유저는 `QUEUE_FULL`). Redis 가 죽으면 생성 요청은 `503`이다(채팅과 달리 통과시키지 않는다 — 집 PC
보호가 우선). **여기에 유저별 상한이 겹친다**(`core/rate_limit_gate.py`) —
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

**측정치**(집 PC 계약 v4의 배포 전 실측, 2026-09-28. VRAM 행만 그 이전 계약 이행 확인서 값이다 — v4는 VRAM을
다시 재지 않았다):

| 항목 | 값 |
|---|---|
| 생성 시간(워밍업 뒤) | 참조 포함 약 17초 이하 |
| 생성 시간(재기동이 아닌 종횡비 버킷 전환 뒤 첫 요청) | 약 34초 — 이전 확인서는 이 비용을 `torch.backends.cudnn.benchmark`가 그 해상도의 커널을 처음 탐색·캐시하는 비용으로 설명했다 |
| 생성 시간 최악(서버 재기동 직후 첫 요청) | **약 38초** — 타임아웃 산정 기준(아래) |
| 참조 이미지를 실은 요청의 추가 시간 | 약 +2.0초(참조 디코딩·정책 검사 약 0.5초 포함). 집 PC 쪽 측정은 약 1.8M자 참조를 같은 기계 안에서 보낸 값이라, 8,000,000자에 가까운 참조는 VM→집 PC 전송 시간이 따로 붙는다(미측정) |
| 결과 이미지 검사(v4에서 한 단계 늘었다) | 약 +0.27초 — 참조 유무와 무관하게 모든 요청 |
| 재기동 후 준비 시간(기동 → 첫 응답 가능) | 중앙값 약 12.7초(12.1~15.3초, 8회) |
| VRAM | 상주 0 MiB(오프로드 훅, forward 시점까지 GPU에 올리지 않음) · 생성 피크 **5494 MiB** |

**`LOCAL_IMAGE_TIMEOUT_SECONDS`가 90초인 이유**: 최악 약 38초에 큰 참조 이미지의 전송 시간(위 표, 미측정)이 더해져도
넘지 않을 여유를 두면서, VM이 Cloudflare Tunnel을 거치므로 edge 타임아웃(무료 플랜 100초로 알려짐, 실측 없음)
아래에 머무는 값이다. 참조 요청과 참조 없는 요청이 같은 값 하나를 쓴다 — 계약은 참조 요청의 타임아웃을 더 짧게
잡지 말라고 권하는데, 값이 하나라 그렇게 될 수가 없다. 40초대로 줄이면 집 PC가 응답 없이 멈췄을 때 실패를 더
빨리 알지만, 큰 참조를 실은 최악 요청이 타임아웃 경계에 걸린다.

집 PC는 콘텐츠 정책 가드도 운영한다 — 생성 전(프롬프트) · 참조 이미지(실었을 때) · 생성 후(결과 이미지)를 판정하고,
위반이 의심되면 `422`를 낸다(`reason`이 각각 `prompt`·`reference`·`image`). 서버는 그것을 사용자에게 "정책 차단"으로
알리고, 참조 차단이면 "다른 이미지를 골라 보라"고 안내한다. **정책에 걸린 참조 이미지는 집 PC가 사후 검토용으로
보관하며 보존 기한은 정해져 있지 않다**(자동 삭제 없음) — 사용자에게는 생성 화면의 참조 행 아래 문장으로만
알린다. 공백만 있는 프롬프트는 v4 집 PC가 기본 인물로 생성해 버리므로 이 서버가 차감 전에 `422`로 먼저 거절한다.

### 5-1. 참조 이미지 켜기 · 끄기 · 롤백

`LOCAL_IMAGE_REFERENCE_ENABLED`는 코드 기본값이 꺼짐이고, **운영에서는 2026-09-29 14:12 KST에 켰다**(아래 "켜기" 절차,
`.env` 백업은 `/opt/ddona/.env.bak-20260929-ref`). 참조 필드를 모르는 집 PC는 그 필드를 **조용히 무시하고
참조 없는 이미지로 200을 주므로**, 아래 조건을 채우기 전에는 켜지 않는다 — 끈 뒤 다시 켤 때도 같다.

**켜는 조건**(전부 — 2026-09-29 충족을 확인하고 켰다):

1. 집 PC가 참조 필드를 아는 버전이다. 무비용 판별: `POST /generate`에 `"reference_image": ""`를 실으면 생성 전에
   바로 `400 {"detail":"invalid reference image"}`가 온다(모르는 버전이면 이미지 1장을 만들어 `200 image/webp`).
   2026-09-28 운영 VM에서 판별 → 아는 버전.
2. 서버팀에 켠다고 **먼저** 알렸다.
3. 요청 본문 상한 실측(아래)에서 큰 참조가 집 PC의 응답을 받았다. 2026-09-29 운영 경로에서 7,852,932자 참조가
   `200 image/webp`를 받았다(결과는 "현재 형상의 근거" 표의 집 PC 경로 행).
4. 생성 화면에서 참조 행 아래 전송·보관 안내 문장이 참조를 고르기 전부터 보인다.

**요청 본문 상한 실측** — 운영과 같은 VM → Cloudflare Tunnel/Access → 집 PC 경로로, api 컨테이너 안에서 돌린다
(설정을 컨테이너 env에서 읽으므로 Access 토큰이 명령행·셸 기록에 남지 않는다). 요청마다 이미지를 1장씩 만든다
(GPU 시간만 들고 클로버·보관함과는 무관하다).

```sh
cd /opt/ddona/app
# 실제 생성 이미지 하나의 저장 키(보통 크기 참조로 쓴다)
sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
  psql -U postgres -d ai_character_chat -Atc \
  "SELECT storage_key FROM assets WHERE kind='GENERATED' AND status='READY' ORDER BY created_at DESC LIMIT 1;"

# 그 키 + 약 7,850,000자(1400×1400 무작위 PNG, 약 5.9MB) 두 건을 보낸다. REF_KEY 를 빼면 큰 PNG 한 건만
sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env exec -T -e REF_KEY='<위 키>' api_$(sudo bash ops/active-color.sh) python - <<'EOF'
import base64, io, os
import httpx
from PIL import Image
from api.core.config import settings
from api.core.s3 import download_object

def send(label, data):
    encoded = base64.b64encode(data).decode("ascii")
    response = httpx.post(
        f"{settings.local_image_base_url}/generate",
        json={"prompt": "1girl, solo, upper body", "model": settings.local_image_model_wire_id,
              "style": "soft_portrait", "aspect_ratio": "3:4", "reference_image": encoded},
        headers={"CF-Access-Client-Id": settings.local_image_access_client_id,
                 "CF-Access-Client-Secret": settings.local_image_access_client_secret},
        timeout=settings.local_image_timeout_seconds,
    )
    content_type = response.headers.get("content-type", "")
    body = "" if content_type.startswith("image/") else response.text[:200]
    print(label, f"{len(encoded):,}자", response.status_code, content_type, body)

if os.environ.get("REF_KEY"):
    send("생성 이미지", download_object(os.environ["REF_KEY"]))
side = 1400
noise = Image.frombytes("RGB", (side, side), os.urandom(side * side * 3))
buffer = io.BytesIO()
noise.save(buffer, format="PNG")
send("큰 PNG", buffer.getvalue())
EOF
```

판정: 줄마다 `라벨 길이 상태 content-type 본문`이 찍힌다. `200 image/webp`이나 `application/json`의 `400`·`422`면 본문이
집 PC에 닿은 것이다(무작위 PNG가 정책 검사에 걸리는 것도 닿은 것이다). `413`이나 HTML 본문(Cloudflare 오류
페이지)이면 경로에 더 작은 상한이 있다 — 켜지 말고, 참조 검증의 길이 상한(`assets/image_processing.py`)을 그 아래로
낮추는 작업을 먼저 한다. 결과는 "현재 형상의 근거" 표의 집 PC 경로 행에 적는다. (2026-09-29 운영 경로에서 이 스크립트를 돌려 두 건 모두
`200 image/webp`를 받았다.)

**켜기** — `.env`에 **한 줄만 더한다.** 파일을 통째로 덮거나 백업본으로 복원하지 않는다(교체 스크립트가 같은 파일의
`API_IMAGE_BLUE`·`API_IMAGE_GREEN`을 고친다):

```sh
cd /opt/ddona/app
sudo sh -c 'printf "\nLOCAL_IMAGE_REFERENCE_ENABLED=true\n" >> /opt/ddona/.env'
sudo bash ops/swap-api.sh
sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env exec -T api_$(sudo bash ops/active-color.sh) \
  python -c "from api.core.config import settings; print(settings.local_image_reference_enabled)"   # True
```

켠 뒤: 생성 화면에서 참조를 붙여 1장 생성이 성공하는지 본다(요청 바디에 `referenceAssetId`). **2026-09-29 확인
완료** — 운영 생성 화면에서 본인 생성 이미지를 참조로 붙여 1장 생성: 요청에 `referenceAssetId`가 실렸고 `202` → 잡
`succeeded`, 차단(422) 없음. 참조를 붙이지 않은 대조 요청에는 이 필드가 없었다. "BE 런타임" 절의 키
개수 문장을 VM에서 다시 세어 고치고, 표의 이 키 행과 "생략 가능" 목록도 켠 상태에 맞게 고친다. 참조 이미지를 읽거나
검증하지 못한 실패는 Bugsink `dependency=reference_image`로, 집 PC가 참조 요청을 400으로 거절한 것은
`dependency=local_image`로 올라온다. 참조 차단(422 `reference`)은 WARNING 로그만 남고 경보는 없다.

**끄기** — 같은 줄을 `false`로 바꾸고 다시 올린다:

```sh
cd /opt/ddona/app
sudo sed -i 's/^LOCAL_IMAGE_REFERENCE_ENABLED=.*/LOCAL_IMAGE_REFERENCE_ENABLED=false/' /opt/ddona/.env
sudo bash ops/swap-api.sh
```

새로 연 생성 화면에는 참조 행이 없다. 이미 열려 있던 화면에서 참조를 실어 보내면 `400 reference image disabled`로
거절·환불되고, 화면이 "지금은 참조 이미지를 쓸 수 없어요"를 띄운 뒤 모델 목록을 다시 받아 행을 숨긴다.

**롤백** — 운영은 참조를 켠 상태이므로 **되돌릴 태그와 상관없이 먼저 끄고(재기동) 롤백한다.** 참조 필드를 싣게 한
이 기능 이전의 BE는 `referenceAssetId`를 모르는 필드로 조용히 무시해, 참조 없는 이미지를 만들고 클로버를 차감한다.
이미 열려 있던 새 FE 탭은 모델 목록을 다시 받기 전까지 그 필드를 계속 보낸다. 먼저 꺼 두면 그 사이의 그런 요청은
`400 reference image disabled`로 거절·환불되고 화면이 참조 행을 숨기며, 모델 목록을 다시 받은 탭은 필드를 더 보내지
않는다. 이미 꺼 둔 상태라면 끄는 단계는 건너뛴다.

PR #65(머지 `4e52c81`)보다 앞선 태그로 되돌릴 때는 추가로 1시간을 기다린다. 참조를 켠 동안 Redis 잡 레코드에 차단
사유 `reference`가 남아 있을 수 있고, 이 사유를 모르는 그 이전 BE로 되돌리면 그런 잡을 폴링하는
`GET /images/jobs/{id}`가 잡 레코드 검증에 실패해 500을 낸다. 잡 레코드는 마지막 갱신부터 1시간
(`image_generation_job_ttl_seconds`) 뒤 사라지므로 순서는 **끄기(재기동) → 1시간 기다림 → 태그 롤백**이다. FE도
같다 — 같은 PR보다 앞선 Pages 배포는 사유 `reference`의 안내 문구 분기가 없어 그 잡을 만나면 예외를 던지므로, Pages
롤백도 같은 1시간 뒤에 한다.

마이그레이션 `739e7f1039b1`(요청 행의 참조 컬럼, nullable)은 태그 롤백만이면 되돌리지 않는다 — 옛 코드는 그 컬럼을
모른 채 동작하고, 새 행에는 NULL이 들어간다. 되돌려야 할 때(예: main에 revert 커밋을 올려 옛 코드를 다시 배포할 때 —
그 배포는 롤백 표시가 없어 DB가 이미지보다 앞서 있으면 교체 스크립트가 실패하므로 병합 전에 downgrade 를 마친다)는 순서가 고정이다:
**태그 롤백으로 옛 코드부터 띄우고 → 새 이미지로 downgrade**. 옛 이미지에는 이 리비전 파일이 없어 downgrade를 못 하고,
downgrade를 먼저 하면 아직 떠 있는 새 코드가 없어진 컬럼을 조회하다 실패한다. downgrade는 "어떤 요청이 어떤
이미지를 참조했는지" 기록을 지운다.

```sh
sudo /opt/ddona/backup.sh   # 먼저 백업
sudo docker run --rm --network ddona_default --env-file /opt/ddona/.env \
  <IMAGE>:<새 코드 TAG> alembic downgrade 697222d13fe8
```

---

## 6. 알려진 갭

- **이미지 생성이 집 PC 한 대의 가동률에 종속된다.** 그 PC의 다운타임이 곧 이 기능의 실패율이다 —
  폴백이 없다(Cloudflare의 모델을 없앤 것은 의도적 결정이라, 조용히 낮은 품질로 대체되면 애초에
  로컬로 옮긴 이유가 무너진다). 사용자가 보는 것은 깨진 폼이 아니라 제출 전 사전 차단(503, "이미지 생성" 절)이다.
- **스테이징 환경 없음**: main push → 바로 prod. 대신 BE는 명령 한 줄 롤백(`sudo DDONA_ROLLBACK=1 bash ops/swap-api.sh <이전SHA>` 또는
  Actions 수동 실행의 `image_tag`, "BE → GCE VM" 절 — 평상시 배포와 같은 무중단 교체다), FE는 Pages 이전 배포로 롤백 가능 →
  문제 시 1순위는 롤백, fix는 그 다음.
- **무중단 교체가 지키지 못하는 것 — 컨테이너 안 백그라운드 작업.** 드레인은 Caddy 를 거치는 HTTP 요청(SSE 채팅 턴 포함)만
  기다린다. 응답을 보낸 뒤 컨테이너 안에서 도는 작업 — 이미지 생성 잡(운영 최대 약 42초), 소설 장 생성·문단 수정(상한 360초),
  턴 뒤 기억 요약 — 은 옛 색이 멈출 때 함께 끊긴다(단일 컨테이너 시절의 완전교체도 같았다). 이미지 생성은 Redis 의 락·대기열
  칸이 TTL 로 풀리고("이미지 생성" 절), 잡 기록은 1시간 TTL 까지 진행 중으로 남는다 — 끊긴 잡의 환불 경로는 확인하지 않았다.
  기억 요약은 다음 턴에 다시 한다. 소설 작업은 진행 중으로 남고, 새 프로세스가 기동 뒤 heartbeat 만료 + 10초(기본 70초)에 죽은
  작업을 한 번 일괄 환불하는데, 이 정리는 "옛 프로세스가 새 프로세스보다 먼저 죽었다"는 전제다. blue/green 에서는 옛 색이 새 색
  기동 **뒤**(healthy 약 15~35초 + 드레인 최대 65초)에 멈추므로 옛 색에서 끊긴 작업의 heartbeat 가 그 일괄 정리 시점에 아직 만료되지
  않아 놓칠 수 있다 — 놓친 작업은 그 소설을 열거나 폴링할 때의 지연 정리가 환불하고, 그때까지 차감액이 묶인다. 소설화는 허용
  명단 계정에만 열려 있어 영향이 작다.
- **드레인 유예(65초)보다 긴 요청은 교체 때 끊긴다.** 지금 가장 긴 동기 요청은 발행 자동 심사(상한 60초)다. 상위 모델(Opus)
  채팅 턴처럼 더 긴 요청을 열 때는 `docker-compose.prod.yml`의 `stop_grace_period`를 다시 정한다.
- **Pages 프리뷰에서는 API 연동 확인 불가**: `CORS_ALLOW_ORIGINS`가 prod 두 도메인만 허용해 PR
  프리뷰(랜덤 서브도메인)에서 CORS로 막힌다. 필요해지면 완화.
- **즉시 롤백 스위치(옛 스택)는 없다.** 인프라 장애 복구는 "VM 재구축 → compose → R2 백업 복원"이고
  시간이 걸린다(compose 기동·복원 순서는 "빈 상태에서 첫 기동" 절).

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
