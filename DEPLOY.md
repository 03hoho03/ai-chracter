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
(`apps/web/worker/legacyRedirect.ts`). **admin의 옛 주소는 넘기지 않는다** — `lax` 쿠키라 거기서는
로그인도 안 된다. 의도된 결과이며 `admin.ddona.site`를 쓴다. admin의 `public/_worker.js`는 없는 자산
파일 요청을 404로 바꾸는 일만 한다.

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
| 백업 | 매일 18:00 UTC → `s3://ai-chracter-chat/backup/daily/`, 7일 + 4주 보관. 손으로 뜬 백업(`--manual`)은 `backup/manual/` 에 최신 5개 ("백업 · 복원" 절) |

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

**89개 키다**(2026-10-26 VM 실측, 키 이름만 셈): 아래 표 152개 중 79개(생략 가능한 조정 키 57개 — `LOCAL_IMAGE_TIMEOUT_SECONDS`·
`LOCAL_IMAGE_CAPABILITIES_TTL_SECONDS`·`LOCAL_IMAGE_QUEUE_LIMIT`·`EXPOSE_API_DOCS`·`GEMINI_IMAGE_JUDGMENT_MODEL_NAME`·`GEMINI_PUBLISH_FILTER_MODEL_NAME`·`GEMINI_THINKING_BUDGET`·`MEMORY_WINDOW_*` 3개·소설화 밖 `GEMINI_*_TIMEOUT_MS` 5개(`GENERATE`·`JUDGMENT`·`MEMORY_SUMMARY`·`PUBLISH_FILTER`·`CLIENT`)·`GEMINI_NOVELIZE_*` 8개·소설화 조정용 `NOVELIZE_*` 25개·장기 기억 조정용 9개(`MEMORY_MODEL_SCOPE`·`MEMORY_EMBED_MODEL`·`MEMORY_EMBED_DIMS`·`MEMORY_EMBED_RECALL_` 뒤에 `RRF_K`·`MAX_PLAIN`·`MAX_CUE`·`MAX_DISTANCE`·`VECTOR_LIMIT`·`DF_MAX` 가 붙는 6개), 실측 때 넣지 않은 상위 모델 Bedrock 키 9개(`BEDROCK_*`), 실측 때 넣지 않은 크리에이터 정산 키 5개(`CREATOR_PAYOUT_ENABLED`·`CREATOR_PAYOUT_RATE_BPS`·`CREATOR_PAYOUT_RETRO_DAYS`·`CREATOR_PAYOUT_MINIMUM_KRW`·`CREATOR_PAYOUT_ENCRYPTION_KEYS`), 아직 켜지 않은 스위치 3개(소설 삽화 `NOVEL_ILLUSTRATIONS_ENABLED`·소설 구성 흐름 `NOVELIZE_OUTLINE_FLOW_ENABLED`·사실 주입 `MEMORY_FACTS_INJECT`), 아직 켜지 않은 인상 키 3개(`MEMORY_IMPRESSIONS_WRITE`·`MEMORY_IMPRESSION_EVERY_N_FOLDS`·`MEMORY_IMPRESSION_MODEL`), 전체 공개 뒤 줄을 지운 노벨 미리보기 명단 1개(`NOVEL_PUBLIC_PREVIEW_ALLOWLIST`), 잔액을 한꺼번에 옮기는 동안에만 켜고 평소에는 줄을 두지 않는 클로버 정지 스위치 1개(`CLOVER_LEDGER_PAUSED`), 모두 79개 제외 —
파일에 줄이 있는 소설화 `NOVELIZE_ENABLED`·`NOVELIZE_GRANT_ALLOWLIST`·`NOVELIZE_WORKER_ENABLED`, 상위 모델 스위치·명단 3개(`CHAT_PREMIUM_MODELS_ENABLED`·`NOVELIZE_PREMIUM_*` 2개), 상위 모델 직결 키·배정 2개(`ANTHROPIC_DIRECT_API_KEY`·`LLM_CALL_SITE_BACKENDS`), 결제·본인인증 키 9개(`PORTONE_*` 5개·
`IDENTITY_CI_HMAC_KEY`·`PAYMENTS_ENABLED`·`IDENTITY_GATE_ENABLED`·`PAYMENT_DISCORD_WEBHOOK_URL`), 노벨 스위치 2개(`NOVEL_PUBLIC_ENABLED`·공개 정책 `NOVEL_PUBLIC_POLICY_V2_ENABLED`), 여러 문단 수정 스위치 1개(`NOVELIZE_MULTI_BLOCK_EDIT_ENABLED`), 장기 기억 키 13개(`MEMORY_*` 12개 — 장면·사실 추출과 모델, 장면 회상, 요약 모델·비밀 표기, 지식 범위 필터, 임베딩 쓰기·회상과 그 시간 상한, 기억 보기 `MEMORY_ITEMS_VISIBLE` — 와 `VOYAGE_API_KEY`), 스탯 판정 이벤트 스위치 1개(`STAT_EVENT_LOG`)를 포함한 나머지 73개는 셈에 들어간다) + 앱이 읽지 않지만
옛 이미지로 태그 롤백할 때를 위해 남긴 키 1개(`CHAT_PREMIUM_MODEL_ALLOWLIST`) + compose용 6개(`API_IMAGE_BLUE`·`API_IMAGE_GREEN`·`SITE_ADDRESS`·
`POSTGRES_PASSWORD`·`POSTGRES_DB`·`DDONA_ENV_FILE` — 두 색으로 나뉘기 전의 `API_IMAGE` 줄은 없다) + "Bugsink(에러 트래커)" 절의 6개
(`BUGSINK_*` 3개·`INGEST_SHARED_SECRET`·`SENTRY_DSN`·`SENTRY_ENVIRONMENT`) + 크론 알림 3개
(`DISCORD_WEBHOOK_URL`·`HEALTHCHECKS_BACKUP_PING_URL`은 "백업 · 복원" 절, `HEALTHCHECKS_RESOURCE_PING_URL`은 "VM 리소스 감시" 절). `apps/api/.env`는 **로컬 개발용이며 배포와 무관하다.**
서빙 컨테이너(`docker exec … env`)의 키 수는 이 파일 키 수가 아니다 — `env_file` 로 받은 파일 키에 베이스 이미지·Dockerfile·Docker 가 넣는 키(`PATH`·`HOSTNAME` 등)가
더해진 수라, 파일 키 수는 VM 에서 아래 명령으로 따로 센다.
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
| `PORTONE_STORE_ID` | 포트원 콘솔의 상점 id | 결제·본인인증 공통. 공개 식별자라 브라우저로도 내려간다(웹 빌드에는 넣지 않고 주문·인증 시작 응답으로 받는다). 결제 대조가 포트원 응답의 상점 id 를 이 값과 비교한다 |
| `PORTONE_PAYMENT_CHANNEL_KEY` / `PORTONE_IDENTITY_CHANNEL_KEY` | 포트원 콘솔의 결제 채널키(KG이니시스) / 본인인증 채널키(NHN KCP) | 공개 식별자. 주문마다 그때의 결제 채널키를 기록하고 결제 대조가 그 값과 비교한다 — 바꾸면 바꾸기 전에 만든 주문은 옛 키로 대조된다 |
| `PORTONE_API_SECRET` | 포트원 V2 API 시크릿 | 결제·본인인증 조회와 환불(취소) 호출. 비면 결제·본인인증이 꺼진다(기동은 막지 않는다) |
| `PORTONE_WEBHOOK_SECRET` | 포트원 콘솔의 웹훅 시크릿(`whsec_…`) | 결제 웹훅 서명 검증. 비거나 형식이 틀리면 모든 웹훅이 503 으로 돌아가 포트원이 재시도한다(Bugsink 에 남는다). 서명 시각 허용 오차가 5분이라 VM 시계(NTP)가 맞아야 한다 |
| `IDENTITY_CI_HMAC_KEY` | `openssl rand -hex 32` 등으로 발급한 무작위 값 | 본인인증 CI 를 저장하기 전에 HMAC 으로 바꾸는 키. **한번 정하면 바꾸지 말 것** — 바뀌면 이미 인증한 사람과 대조가 어긋나 같은 사람이 다른 계정으로 다시 인증할 수 있게 된다. `WITHDRAWN_EMAIL_HMAC_KEY` 와 다른 값을 쓴다. 비면 본인인증이 꺼진다 |
| `PAYMENTS_ENABLED` / `IDENTITY_GATE_ENABLED` | 켤 때 `true`(코드 기본값은 둘 다 `false`) | 결제 스위치 / 미인증 회원의 무료 대화·미션을 막는 본인인증 게이트 스위치. 결제는 스위치와 위 포트원 키 넷, 그리고 본인인증 설정(상점 id·본인인증 채널키·API 시크릿·`IDENTITY_CI_HMAC_KEY`)이 모두 있어야 열린다 — 결제는 늘 본인인증을 요구해서다. 꺼져 있어도 웹훅 시크릿이 있으면 웹훅은 처리한다(진행 중 결제와 콘솔 취소를 맞춘다) |
| `PAYMENT_DISCORD_WEBHOOK_URL` | 결제 알림용 디스코드 채널 웹훅 주소 | 결제·환불 완료 알림(상품·금액·상태만, 회원·주문을 알아볼 단서는 싣지 않는다). 비면 건너뛴다. 크론 알림의 `DISCORD_WEBHOOK_URL` 과 다른 키다 |
| `CLOVER_LEDGER_PAUSED` | 설정 안 함(기본 `false`). 클로버 단위 전환처럼 잔액을 한꺼번에 옮기는 동안에만 `true` | 클로버 정지 스위치. 켜면 클로버를 새로 깎거나 주는 경로가 503 `CLOVER_PAUSED`(짧은 안내 `message` 포함)로 멈춘다 — 모든 차감(채팅·이미지의 유료 갈래, 요약 다시 만들기, 소설화 작업 시작, 노벨 소장), 미션 수령, 어드민 지급·회수, 어드민 결제 환불 실행(진행 중 시도의 마무리 포함), 주문 생성. 채팅·이미지에서는 하루 1회 확인 429 와 가격 버전 409 보다 먼저 나간다(정지 중에는 어떤 가격으로도 깎지 않아 가격표를 다시 받게 해도 소용이 없다). 막지 않는 것: 무료 대화 턴·무료 토큰 이미지, 모든 환급, 결제 완료 확인·웹훅(포트원 콘솔 취소도 이 길로 들어와 막지 못한다), 만료 크론, 탈퇴. 🔴 켜기 전에 진행 중 환불 시도(`payment_cancellations.status = 'requested'`)를 0 으로 만든다 — 그 마무리 라우트도 정지로 막힌다. 켜기·끄기는 `.env` 에 줄을 더하거나 지운 뒤 형식 검사 → 태그 없는 교체다(`restart` 는 env 를 다시 읽지 않는다 — "env 반영 재기동" 절). 옛 색은 교체가 끝날 때까지 옛 값으로 돈다. 빈 값(`CLOVER_LEDGER_PAUSED=`)은 꺼짐으로 읽는다. 넣고 지울 때 위 VM 키 수를 다시 센다 |
| `CREATOR_PAYOUT_ENABLED` | 켤 때 `true`(코드 기본값은 `false`) | 크리에이터 정산 스위치. 스위치와 본인인증 설정(상점 id·본인인증 채널키·API 시크릿·`IDENTITY_CI_HMAC_KEY`)이 모두 있어야 열린다(지급 정보 입력·지급 신청은 `CREATOR_PAYOUT_ENCRYPTION_KEYS` 도 있어야 열리고, 정산 신청·적립·확정·조회는 키와 무관하다) — 신청 자격이 본인인증한 만 19세 이상(나이는 코드 상수라 env 가 없다)이라서다. 켜면 결제·게이트가 꺼져 있어도 본인인증 시작이 열린다. 꺼져 있으면 회원의 정산 조회·신청·지급 정보 입력·지급 신청이 503 이고, 어드민의 신청·지급 처리(승인·거절·승인 취소, 이체 기록·반려)는 스위치와 무관하게 열려 있다. 정산 신청·지급 신청 접수 알림은 `PAYMENT_DISCORD_WEBHOOK_URL` 채널을 같이 쓴다(건수·금액만, 회원을 알아볼 단서는 싣지 않는다). 🔴 켤 때 "크리에이터 정산 월 확정 — settle cron" 절의 크론 설치를 함께 한다 — 켠 뒤 크론이 없으면 월 확정이 돌지 않는다(2026-10-24 확인 기준 VM 에는 설치돼 있지 않다) |
| `CREATOR_PAYOUT_RATE_BPS` / `CREATOR_PAYOUT_RETRO_DAYS` | 설정 안 함(기본 `500` / `90`) | 정산 비율(bps, 500 = 공급가의 5%, 1~10000) / 첫 승인 때 거슬러 확정하는 소급 일수(1 이상). 범위 밖이면 api 가 뜨지 않는다. 비율은 확정할 때마다 확정 행에 남아, 바꿔도 이미 확정한 금액은 그대로다 |
| `CREATOR_PAYOUT_MINIMUM_KRW` | 설정 안 함(기본 `10000`) | 지급을 신청할 수 있는 최소 확정 잔액(원, 1 이상). 탈퇴하려는 회원은 이보다 적어도 탈퇴 화면에서 신청할 수 있다. 범위 밖이면 api 가 뜨지 않는다 |
| `CREATOR_PAYOUT_ENCRYPTION_KEYS` | 🔴 지급 기능을 열 때 넣는다. `k1:<base64url 32바이트>` | 크리에이터 지급 정보(실명·주민등록번호·계좌번호) 암호화 키 목록 `kid:키[,kid:키]`. 맨 앞 키로 암호화하고 모든 키로 복호화한다. 비면 지급만 닫힌다 — 지급 정보 입력·지급 신청이 503 이고 정산 조회 응답의 `payoutAvailable` 이 거짓이다(어드민 지급 상세·열람은 409). 정산 신청·적립·월 확정·조회는 키와 무관하게 돈다, 형식이 틀리면 api 가 뜨지 않는다. **키를 잃으면 지급 정보를 되살릴 수 없다** — 만들기·보관·회전 절차는 "크리에이터 지급 정보 암호화 키" 절. 비밀 |
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
| `DB_POOL_SIZE` | **운영 `10`**(기본 `5`) | 워커 하나의 SQLAlchemy 풀 상시 크기(1 이상). 기본값은 이 설정이 생기기 전과 같다. ⚠️ **2 × 워커 수 × (`DB_POOL_SIZE` + `DB_MAX_OVERFLOW`) ≤ 170** — blue/green 교체 중에는 옛 색이 드레인하는 동안 새 색도 떠 있어 두 색의 풀이 함께 열린다. Postgres `max_connections` 200 에서 크론·백업·배포 마이그레이션·관리 접속 몫 30 을 남긴다(앱 DB 사용자가 슈퍼유저라 예약 연결이 관리 접속을 따로 지켜 주지 않는다). 운영 값은 2 × 4 × (10 + 7) = 136 ≤ 170 이고, 한 색만 떠 있는 평소에는 68 이다. 소설화 워커를 켜면 워커 컨테이너마다 3 + 2 = 5 연결이 더해진다(워커는 compose `environment` 로 이 키와 `DB_MAX_OVERFLOW` 를 3·2 로 덮는다). 교체는 api 두 색이 겹치는 동안 워커를 하나만 두므로 최악은 136 + 5 = 141, 워커를 가는 동안(api 한 색, 옛·새 워커)은 68 + 10 = 78 이다. 200 은 Postgres 기본값이 아니라 운영에서 따로 올린 값이다 — 설정·확인·되돌리기와 볼륨을 새로 만들 때 다시 넣는 법은 "겹침 대비 운영 설정" 절 |
| `DB_MAX_OVERFLOW` | **운영 `7`**(기본 `10`) | 풀이 다 찼을 때 잠깐 더 여는 연결 수. 위 식에 들어간다 |
| `DB_POOL_TIMEOUT` | **운영 `30`**(기본값과 같다) | 풀이 다 찼을 때 연결을 기다리는 초. 넘기면 그 요청이 500 이다 |
| `IMAGE_DECODE_CONCURRENCY` | **운영 `1`**(기본 `3`) | 워커 하나에서 동시에 도는 이미지 디코드·블러·변형 생성 건수 상한(1 이상, 넘치면 기다린다). 기본값은 이 설정이 생기기 전과 같다. ⚠️ 워커마다 따로 세므로 **워커 수 × 이 값 × 건당 최대 메모리 ≤ VM 가용 메모리의 절반**으로 정한다 — 건당 최대 메모리는 픽셀 상한 9M 그림의 블러·변형 생성 실측 피크 약 217MB 다. 운영 값 1 은 워커 4 × 1 × 약 217MB ≈ 868MB 가 부하 중 가용 메모리의 절반(약 950MB) 안에 드는 값이고, 2 면 넘는다. `WEB_CONCURRENCY` 를 올릴 때 함께 본다 |
| `MEMORY_WINDOW_GENERATION` | 설정 안 함(기본 `true`) | 긴 방의 생성 프롬프트에서 요약이 덮은 메시지를 빼는 히스토리 윈도우. `false` 면 전체 히스토리를 싣는다 — 요약 품질 사고 때 재기동만으로 예전 동작으로 돌아가는 스위치이고, 끄면 아래 두 판정 스위치도 무시된다 |
| `MEMORY_WINDOW_ENDING_JUDGMENT` | 설정 안 함(기본 `true`) | 엔딩 판정에도 윈도우를 씌운다(요약이 덮은 원문 대신 현재 요약을 싣는다). `false` 는 판정 품질 사고 때 되돌리는 용도다 — 끄면 판정이 대화 전체를 실어 긴 방에서 토큰 원가·지연이 턴 수만큼 늘고 판정 타임아웃·컨텍스트 한도에 닿을 수 있다. 되돌리기는 VM `.env` 에 `MEMORY_WINDOW_ENDING_JUDGMENT=false`·`MEMORY_WINDOW_IMAGE_JUDGMENT=false` 두 줄을 추가 → 아래 형식 검사 → `sudo bash ops/swap-api.sh`(`restart` 는 env 를 다시 읽지 않는다 — "env 반영 재기동" 절). 넣으면 위 VM 키 수를 다시 센다 |
| `MEMORY_WINDOW_IMAGE_JUDGMENT` | 설정 안 함(기본 `true`) | 그림 매칭 판정 — 캐릭터 상황 이미지와 스토리 미디어 북 칸 둘 다 — 에도 윈도우를 씌운다(최근 원문만 싣고 요약은 싣지 않는다). 미디어 북 칸 판정은 엔딩 뒤·재생성까지 매 턴 돌아 끄면 가장 크게 늘어난다. 끄는 법·주의는 위와 같다 |
| `STAT_JUDGMENT_MODEL` / `ENDING_JUDGMENT_MODEL` / `IMAGE_JUDGMENT_MODEL` / `MEMORY_SUMMARY_MODEL` | **운영 `haiku`**(2026-10-13부터, 코드 기본값 `gemini`) | 스탯 판정 / 엔딩 판정 / 그림 매칭 판정(캐릭터 상황 이미지·스토리 미디어 북 칸) / 기억 요약 접기의 모델(문안 체인의 모델 id `gemini`·`haiku`·`sonnet`·`opus`, 미리보기 판정도 같은 키를 쓴다). 채팅 방 턴의 판정·요약 문안은 모델 배정 표에 그 (레인, 실효 방 모델, 단계) 칸의 행이 있으면 행이 고른 체인을 읽고, 없을 때만 이 키의 체인이다(행은 그 경로가 이 키·배정으로 푼 경로와 같을 때만 쓰인다). 부르는 모델도 같다 — 행이 쓰인 칸은 행의 부를 모델로 부르고, 행이 없거나 건너뛴 칸만 이 키의 모델로 부른다. 절은 "채팅 단계별 문안 체인·호출 모델 설정 — 켜기 · 끄기 · 되돌리기". `gemini` 면 실제 Gemini 모델은 위 `GEMINI_*_JUDGMENT_MODEL_NAME`·`GEMINI_MODEL_NAME` 이 고른다. Claude 모델은 배정이 없으면 Bedrock 으로 가고, 운영은 `LLM_CALL_SITE_BACKENDS` 에 그 호출 위치를 `anthropic` 으로 배정해 Anthropic 직결(`ANTHROPIC_HAIKU_MODEL_ID`, 설정 안 함 — 기본값은 `.env.example`)로 보낸다. 🔴 모델 줄과 그 호출 위치의 배정 항목은 **한 편집에서 함께** 바꾼다 — 모델을 `gemini` 로 돌리고 배정을 남기면(`anthropic` 은 Gemini 를 서비스하지 않는다) 배정만 지우고 `haiku` 를 남기면(운영 `.env` 에 `BEDROCK_*` 키가 없다) api 가 기동하지 못한다. 배정의 호출 위치 이름을 모르는 옛 이미지로 태그 롤백할 때도 그 항목을 먼저 지운다. 장면·사실 추출 모델(`MEMORY_EPISODE_MODEL`·`MEMORY_FACT_MODEL`)도 같은 규칙이다 |
| `MEMORY_EPISODES_EXTRACT` | **운영 `true`**(2026-10-14부터, 코드 기본값 `false`) | 요약 접기가 접은 구간을 장면 기억으로 뽑는 백그라운드 추출(턴 뒤, 접기 다음). 꺼져 있으면 아무것도 예약하지 않아 턴 동작이 이 키가 생기기 전과 같고, `MEMORY_WINDOW_GENERATION=false` 면 켜도 돌지 않는다. 추출 호출은 클로버·레이트리밋에 세지 않는다. 켜는 법은 줄 추가(`MEMORY_EPISODES_EXTRACT=true`) → 형식 검사 → `sudo bash ops/swap-api.sh` 다. 켠 직후에는 이미 요약이 접힌 기존 방의 밀린 스냅샷을 그 방의 턴마다 하나씩 소화하므로, 따라잡을 때까지 추출 원가가 접기당 1회보다 일시적으로 많다(밀린 수는 방마다 지금까지의 접기 수다). 끄기는 줄 삭제 → 형식 검사 → `sudo bash ops/swap-api.sh` — 이미 뽑은 장면은 남고 새로 뽑지 않는다 |
| `MEMORY_EPISODES_RECALL` | **운영 `true`**(2026-10-23부터, 코드 기본값 `false`) | 매 턴 방의 장면 기억에서 이번 턴과 이어질 장면을 골라 생성 프롬프트의 대화 기록 바로 뒤 섹션에 싣는다(LLM 호출 없음, 장면 읽기 한두 번). 꺼져 있으면 장면을 읽지도 않아 생성 프롬프트가 이 키가 생기기 전과 같고, `MEMORY_WINDOW_GENERATION=false` 면 켜도 돌지 않는다. 실은 장면은 턴 기록(`chat_turns.memory_recall`)에 id·점수·순위·글자 수·질의 쪽으로 남는다. 장면은 추출(`MEMORY_EPISODES_EXTRACT`)이 만들므로 추출 없이 켜면 실을 장면이 없다. 켜는 법은 줄 추가(`MEMORY_EPISODES_RECALL=true`) → 형식 검사 → `sudo bash ops/swap-api.sh`, 끄기는 줄 삭제 → 형식 검사 → `sudo bash ops/swap-api.sh` — 다음 턴부터 섹션이 빠지고 장면·기록은 남는다. 다른 기억 스위치와의 켜는 순서는 「장기 기억 — 켜는 순서 · 끄기 · 되돌리기」 절 |
| `MEMORY_EPISODE_MODEL` | **운영 `haiku`**(2026-10-13부터, 코드 기본값 `gemini`) | 장면 기억 추출의 모델(문안 체인의 모델 id). 판정·요약 모델 키와 같은 규칙이다 — `haiku`·`sonnet`·`opus` 면 그 모델이 갈 구현의 배정·자격이 있어야 기동한다 |
| `MEMORY_FACTS_EXTRACT` | **운영 `true`**(2026-10-14부터, 코드 기본값 `false`) | 요약 접기가 접은 구간을 관계·사실 기억(인물 관계와 인물 속성, 누가 말했고 무엇이 뒤집혔는지)으로 뽑는 백그라운드 추출(턴 뒤, 장면 추출 다음). 장면 추출과 따로 켜고 끈다 — 한쪽이 실패해도 다른 쪽 완료 표지는 흔들리지 않는다. 꺼져 있으면 아무것도 예약하지 않아 턴 동작이 이 키가 생기기 전과 같고, `MEMORY_WINDOW_GENERATION=false` 면 켜도 돌지 않는다. 추출 호출은 클로버·레이트리밋에 세지 않는다. 켜는 법은 줄 추가(`MEMORY_FACTS_EXTRACT=true`) → 형식 검사 → `sudo bash ops/swap-api.sh` 다. 켠 직후에는 장면 추출과 같은 이유로 기존 방의 밀린 스냅샷을 턴마다 하나씩 소화해 따라잡을 때까지 추출 원가가 일시적으로 많다. 끄기는 줄 삭제 → 형식 검사 → `sudo bash ops/swap-api.sh` — 이미 뽑은 사실은 남고 새로 뽑지 않는다 |
| `MEMORY_FACT_MODEL` | **운영 `haiku`**(2026-10-14부터, 코드 기본값 `gemini`) | 관계·사실 기억 추출의 모델(문안 체인의 모델 id). 판정·요약 모델 키와 같은 규칙이다 — `haiku`·`sonnet`·`opus` 면 그 모델이 갈 구현의 배정·자격이 있어야 기동한다 |
| `MEMORY_IMPRESSION_MODEL` | 설정 안 함(기본 `gemini`) — `MEMORY_IMPRESSIONS_WRITE` 를 켤 때 `haiku` 와 배정 `chat_memory_impression:anthropic` 을 함께 넣는다 | 인상 생성의 모델(문안 체인의 모델 id). 판정·요약 모델 키와 같은 규칙이다 — `haiku`·`sonnet`·`opus` 면 그 모델이 갈 구현의 배정·자격이 있어야 기동한다. 🔴 이 호출 위치를 모르는 옛 이미지는 `LLM_CALL_SITE_BACKENDS` 의 `chat_memory_impression` 항목을 거부해 기동하지 못하므로, 그 이미지로 되돌리기 전에 배정 항목을 먼저 지운다 |
| `MEMORY_FACTS_INJECT` | 설정 안 함(기본 `false`) | 매 턴 방의 관계·사실 기억을 키마다 지금 값으로 줄여(뒤집힌 값은 되살리지 않는다) 생성 프롬프트의 대화 기록 뒤·회상 앞 섹션에 싣는다(LLM 호출 없음, 사실 읽기 한 번, 줄 합계 700자 상한 — 상한의 앞 30% 는 관계 → 아는 사람이 정해진 사실 → 뒤집힌 사실 → 그 밖 순서, 나머지는 이번 사용자 메시지와 드문 낱말이 겹치는 사실을 먼저 채운다). 꺼져 있으면 사실을 읽지도 않아 생성 프롬프트가 이 키가 생기기 전과 같고, `MEMORY_WINDOW_GENERATION=false` 면 켜도 돌지 않는다(원문이 전체로 실리면 같은 사실이 두 번 들어간다). 실은 사실은 턴 기록(`chat_turns.memory_facts`)에 id·글자 수로 남는다. 사실은 추출(`MEMORY_FACTS_EXTRACT`)이 만들므로 추출 없이 켜면 실을 사실이 없다. 켜는 법은 줄 추가(`MEMORY_FACTS_INJECT=true`) → 형식 검사 → `sudo bash ops/swap-api.sh`, 끄기는 줄 삭제 → 형식 검사 → `sudo bash ops/swap-api.sh` — 다음 턴부터 섹션이 빠지고 사실·기록은 남는다. 🔴 임베딩 쓰기·읽기를 켠 뒤 마지막에 켠다(「장기 기억 — 켜는 순서 · 끄기 · 되돌리기」 절) |
| `MEMORY_KNOWLEDGE_FILTER` | **운영 `true`**(2026-10-23부터, 코드 기본값 `false`) | 사실 섹션을 고르기 전에, 아는 사람이 정해진 사실 중 그 사람이 이번 장면(이번 사용자 메시지·직전 응답에 이름이 나온 인물, 사용자 제외)에 없는 행을 뺀다 — 비밀을 모르는 인물만 있는 장면에서 그 비밀이 새지 않게. 거름은 사실 섹션 안에서만 걸리지만, 켠 턴은 회상 줄의 비밀 가림도 직전 응답의 대사 따옴표 안에만 나온 이름을 장면 인물로 세지 않는다(회상이 사실 섹션보다 덜 가려 그 비밀이 회상 줄로 새지 않게). 그래서 `MEMORY_FACTS_INJECT` 가 꺼져 있어도 `MEMORY_EPISODES_RECALL` 이 켜져 있으면 회상 줄이 달라질 수 있고(지금 운영이 이 조합이다), 회상과 사실 주입이 둘 다 꺼져 있을 때만 켜도 생성 프롬프트·SQL 이 같다. 🔴 켤 때는 `MEMORY_SUMMARY_SECRET_MARKING` 과 한 번에 켠다(「장기 기억 — 켜는 순서 · 끄기 · 되돌리기」 절). 끄면 다음 턴부터 걸러 내지 않는다. 🔴 `MEMORY_FACTS_INJECT` 가 켜져 있으면 이 줄을 먼저 지우지 않는다 — 사실 주입부터 끈다(처리방침의 "비밀을 아는 인물이 장면에 없으면 보내지 않는다"가 사실 쪽에서는 이 필터가 켜져 있을 때만 참이다) |
| `MEMORY_SUMMARY_SECRET_MARKING` | **운영 `true`**(2026-10-23부터, 코드 기본값 `false`) | 요약 접기 프롬프트의 지시문 바로 뒤에 비밀 표기 슬롯(비밀에 아는 사람 표기를 붙이고 그 내용을 표기 없이 다시 쓰지 않게 하는 지시와 그 방의 인물 이름 목록)을 싣는다. 꺼져 있으면 이름을 읽지도 않고 슬롯이 빠져 요약 프롬프트가 바이트까지 그대로다. 🔴 켜면 다음 접기부터 **모든 방**의 요약 글이 바뀌고, 그 요약이 생성 프롬프트와 엔딩 판정 입력에도 실린다. 끄면 다음 접기부터 슬롯이 빠지고 이미 쓴 요약은 그대로 남는다. 슬롯 문안은 프롬프트 세트 데이터라 이미지 롤백으로는 빠지지 않는다(옛 코드는 슬롯 값을 넘기지 않아 조용히 빠진다) |
| `MEMORY_MODEL_SCOPE` | 설정 안 함(기본 `opus`) | 회상·사실 주입·지식 범위 필터·요약 비밀 표기·임베딩 회상이 동작하는 방의 범위(레인과 글쓰기 모델). 기본은 두 레인의 Opus 방뿐이고, 범위 밖 방의 턴은 스위치를 다 끈 것과 같다. 추출·임베딩 쓰기와 무관하다. 값 형식과 비울 때의 주의는 「장기 기억 — 켜는 순서 · 끄기 · 되돌리기」 절 |
| `MEMORY_EMBED_WRITE` | **운영 `true`**(2026-10-23부터, 코드 기본값 `false`) | 턴 뒤 백그라운드(접기·장면 추출·사실 추출 다음)에서 방의 장면·사실 행 중 지금 모델·차원의 임베딩이 없는 것을 오래된 순서로 한 번에 64행까지 Voyage 로 임베딩해 `chat_memory_embeddings` 에 넣는다. 꺼져 있으면 예약하지 않아 Voyage 호출·임베딩 표 읽기·쓰기가 0 이다. 사용자 프롬프트는 켜도 그대로다(읽는 쪽은 `MEMORY_EMBED_RECALL`). 켜면 `VOYAGE_API_KEY` 가 있어야 기동한다. 켠 직후에는 이미 쌓인 행을 방마다 턴당 64행씩 따라잡아 그동안 임베딩 원가가 평소보다 많다. 클로버·레이트리밋에 세지 않는다. 끄면 이미 넣은 행은 남고 새로 채우지 않는다 |
| `MEMORY_EMBED_MODEL` / `MEMORY_EMBED_DIMS` | 설정 안 함(기본 `voyage-4-large` / `1024`) | 임베딩 모델 id 와 출력 차원. 임베딩 행은 모델·차원을 함께 적고 읽는 쪽이 늘 지금 값으로 거르므로, 바꾸면 그 모델·차원의 행이 없는 장면·사실을 처음부터 다시 채운다(옛 행은 남는다). 기본값이 회상 품질 측정이 고른 값이라 켤 때 줄을 넣지 않는다 — 측정과 다른 모델·차원으로 돌릴 때만 넣는다. 단가표(`apps/api/src/api/llm/pricing.py`)에 없는 모델 id 면 원가가 "단가 없음"으로 빠진다 |
| `VOYAGE_API_KEY` | Voyage 콘솔에서 만든 이 서비스 전용 API 키(영숫자·`_`·`-` 로만 된 한 줄, 따옴표·공백 없이). **운영에 있다**(2026-10-23부터) | 임베딩 쓰기·읽기의 자격. 둘 중 하나라도 켜졌는데 비어 있으면 api 가 기동하지 못한다(교체가 실패하고 옛 색이 계속 서빙한다). 🔴 꺼진 채로는 넣지 않아도 된다. 지울 때는 두 스위치 줄을 먼저 지운다. 켜기 전 조건(처리방침 게시·학습 데이터 설정)은 「장기 기억 — 켜는 순서 · 끄기 · 되돌리기」 절 |
| `MEMORY_EMBED_RECALL` | **운영 `true`**(2026-10-23부터, 코드 기본값 `false`) | 매 턴 질의 임베딩을 한 번 받아(이번 사용자 메시지 + 직전 응답) 장면 회상과 사실 섹션의 관련 몫을 명사 순위와 벡터 거리 순위의 RRF 로 고른다. `MEMORY_EPISODES_RECALL` 이나 `MEMORY_FACTS_INJECT` 가 켜진 턴에만 부른다. 질의 임베딩이 시간 상한을 넘기거나 실패하거나 방에 지금 모델·차원의 임베딩이 없으면 그 턴은 명사 단독과 바이트까지 같다. 질의 임베딩 한 칸(`{callSite, model, dims, promptTokens, latencyMs, outcome}`)이 턴 기록 `chat_turns.llm_calls` 맨 앞에 남는다. 켜면 `VOYAGE_API_KEY` 가 있어야 기동한다. 🔴 `MEMORY_EMBED_WRITE` 를 먼저 켠다 — 읽기만 켜면 임베딩 행이 없어 매 턴 결과를 쓰지 못할 Voyage 호출을 하고(원가와 첫 글자 지연만 는다) 기동 검사로도 막지 않는다. 끄면 다음 턴부터 명사 단독이다 |
| `MEMORY_EMBED_RECALL_TIMEOUT_MS` | **운영 `3000`**(2026-10-23부터, 코드 기본값 `1000`) | 질의 임베딩의 시간 상한(ms). 생성 앞에서 기다리므로 첫 글자 지연이 이만큼까지 는다 — 넘기면 기다리지 않고 그 턴은 명사 단독이다. 기본값은 운영 VM 에서 잰 Voyage 왕복(키 없이 401 을 받는 왕복 30회, 다시 쓰는 연결 p50 130 ms · p95 482 ms — 임베딩 계산이 빠진 값)에 여유를 둔 값이다. `250` 이면 그 왕복만으로도 일부 턴이 명사 단독으로 떨어진다. 실제 키의 운영 지연은 아직 재지 않았다(로컬 맥에서 실제 키로 다시 쓰는 연결은 p50 340~431 ms). 켠 뒤 턴 기록의 `outcome` 이 `timeout` 인 칸 비율로 다시 본다(아래 원가 스크립트가 센다). 운영은 `3000` 이다 — 첫 글자가 최대 3초 늦는 것을 받아들이고, 1초 상한에서 시간 초과로 임베딩 회상을 놓치던 턴을 줄이려고 늘렸다(회상 품질 측정은 `1000` 조건이라 운영 Opus 방은 "측정과 같은 섹션 선택 규칙, 질의 상한만 다름"이다). 켠 직후 운영 질의 30건은 모두 성공·시간 초과 0, 지연 p50 약 210 ms · 최대 714 ms 였다. 줄을 지우면 기본 `1000` 이다 |
| `MEMORY_EMBED_RECALL_RRF_K` | 설정 안 함(기본 `20`) | RRF `Σ 1/(k + 순위)` 의 k. 장면 회상과 사실 섹션 관련 몫이 함께 쓴다. 기본값이 측정이 고른 값이다 |
| `MEMORY_EMBED_RECALL_MAX_PLAIN` / `MEMORY_EMBED_RECALL_MAX_CUE` | 설정 안 함(기본 `1` / `3`) | 벡터 쪽이 비지 않은 턴의 회상 주입 상한 — 보통 턴 / 회상 단서("예전에"·"기억나" 등)가 있는 턴. 명사 단독의 상한과 같은 값이고 측정이 고른 값도 같다 |
| `MEMORY_EMBED_RECALL_MAX_DISTANCE` / `MEMORY_EMBED_RECALL_VECTOR_LIMIT` / `MEMORY_EMBED_RECALL_DF_MAX` | 설정 안 함(기본 `2.0` / `10` / 비어 있음) | 벡터 순위에 넣는 코사인 거리 상한 / 회상의 벡터 순위에 넣는 거리 순 앞 개수 / 흔한 명사의 절대 상한(비면 비율 기준만). 🔴 거리 상한 `2.0` 은 코사인 거리의 최댓값이라 **아무것도 거르지 않는다** — 그래서 보통 턴에도 거의 매번 가장 가까운 장면 하나가 실린다. 측정 격자에서 상한을 둔 점과 목적함수가 같아 기본값에 가장 가까운 점(`2.0`·`10`·비어 있음)을 골랐고, 보통 턴 주입률이 명사 단독 0.95 에서 1.00 으로 오르는 것을 받아들였다. 사실 섹션 관련 몫도 같은 거리 상한을 쓴다 |
| `MEMORY_ITEMS_VISIBLE` | **운영 `true`**(2026-10-24부터, 코드 기본값 `false`) — 기억 열람·잊게 하기를 적은 처리방침 판이 게시된 뒤에만 켠다 | 방 주인이 그 방의 장면·사실 기억을 보고 고르는 라우트를 연다 — 목록(`GET /chat-rooms/{id}/memory/items`), 장면·사실 잊게 하기(`DELETE /chat-rooms/{id}/memory/episodes/{episodeId}`·`DELETE /chat-rooms/{id}/memory/facts?key=`)와 사실 잊기 미리 보기(`GET /chat-rooms/{id}/memory/facts/forget-preview`), 요약 다시 만들기(`POST /chat-rooms/{id}/memory/summary/regenerate`, 유료). 꺼져 있으면 이 라우트가 모두 404 `MEMORY_ITEMS_DISABLED` 이고(인증보다 먼저 본다), 기억 응답(`GET /chat-rooms/{id}/memory`)의 `features.itemsVisible` 이 `false` 라 웹 기억 패널은 탭 없는 예전 모양(노트 편집기 하나, 목록 요청 없음)이다. 목록은 읽기만 해서 생성·요약·추출 프롬프트와 무관하다. 켜는 법은 줄 추가(`MEMORY_ITEMS_VISIBLE=true`) → 형식 검사 → `sudo bash ops/swap-api.sh`, 끄기는 줄 삭제 → 형식 검사 → `sudo bash ops/swap-api.sh` — 다음 요청부터 다시 404 이고 패널은 예전 모양으로 돌아간다. 🔴 끄거나 이미지를 되돌려도 이미 잊게 한 장면·사실은 돌아오지 않는다(실제로 지운 행이다). 잊게 하기·다시 만들기의 운영 성질은 「장기 기억 — 켜는 순서 · 끄기 · 되돌리기」 절 |
| `STAT_EVENT_LOG` | **운영 `true`**(2026-10-24부터, 코드 기본값 `false`) — 처리방침 「턴 기록」 항목에는 판정 규칙 식별자를 남긴다는 문구 한 줄이 다음 판에 더해진다 | 턴 기록(`chat_turns.stat_events`)에 그 턴 스탯 판정이 스탯마다 발동한 규칙·적용한 규칙(판본을 넘어 같은 규칙 id 와 그 판본의 규칙 행 id 쌍)·폭·범위에 잘렸는지와 카운터 스탯의 한 칸을 남긴다(조건 글은 싣지 않는다). 꺼져 있으면 칸이 DB 기본값 `[]` 이고 턴 기록 INSERT 의 칸 목록도 이 칸이 생기기 전과 같다(서버 기본값이 있는 칸이라 RETURNING 에는 이 칸이 더해진다). 켜도 꺼도 판정·생성 프롬프트와 스탯 값은 같다 — 기록만 더한다. 방의 기억 사용 범위와 무관하게 모든 방에 쓴다. 켜는 법은 줄 추가(`STAT_EVENT_LOG=true`) → 형식 검사 → `sudo bash ops/swap-api.sh`, 끄기는 줄 삭제 → 형식 검사 → `sudo bash ops/swap-api.sh` — 다음 턴부터 다시 `[]` 이고 이미 쓴 이벤트는 남는다(방 초기화·삭제·탈퇴 때 턴 기록과 함께 지워진다) |
| `MEMORY_IMPRESSIONS_WRITE` | 설정 안 함(기본 `false`) — 처리방침에 인상 항목을 게시한 뒤 켤 때 `true` | 요약 접기 몇 번마다(`MEMORY_IMPRESSION_EVERY_N_FOLDS`) 방 하나에 인상 한 행을 `chat_memory_impressions` 에 쌓는 백그라운드 작업(턴 뒤, 두 추출 다음 · 임베딩 채우기 앞). 입력은 그 접기들에서 뽑힌 장면·사실 행 전부이고 아는 사람이 정해진(비밀) 행도 든다 — 인상은 저장만 되고 응답에 쓰이지 않는다(요약 글·원문은 싣지 않는다) 묶음의 장면·사실 추출이 모두 끝나야 돈다 — 그래서 두 추출이 꺼져 있으면 아무것도 쌓이지 않는다. 기억 사용 범위(`MEMORY_MODEL_SCOPE`) 밖 방에서는 돌지 않는다. 저장만 한다 — 생성 프롬프트에 싣지 않고 화면에도 보이지 않는다. 꺼져 있으면 예약하지 않아 인상 호출도 인상 표 SELECT·INSERT 도 없다. 장면·사실 잊게 하기는 이 스위치와 무관하게 지우는 행을 근거로 쓴 인상만 지우고 잊기 세대를 올린다. 묶음마다 시도 기록(`chat_memory_impression_attempts`) 한 행이 선점·재시도 상한·호출 원가를 겸한다 — 모델 오류·응답 형식 위반·빈 글·렌더 오류(인상 channel 이 빔)는 실패로 적혀 다음 턴 뒤 다시 쥐되 묶음마다 세 번까지만 부르고, 10분이 지나도 `running` 인 선점은 죽은 작업으로 보고 다시 쥔다. 성공·실패 모두 응답을 받은 시도의 토큰을 그 묶음 행에 더하고 모델 id 는 마지막 시도의 것을 남긴다. 켜는 법은 `MEMORY_IMPRESSION_MODEL=haiku`·배정 `chat_memory_impression:anthropic`·이 줄 추가 → 형식 검사 → `sudo bash ops/swap-api.sh`, 끄기는 이 줄 삭제 → 형식 검사 → `sudo bash ops/swap-api.sh` — 이미 쌓인 행은 남는다(되감기·초기화·방 삭제·탈퇴 때, 그리고 근거로 쓴 장면·사실을 잊게 할 때 지워진다). 켜기 전 조건 전부와 되돌리는 차례는 「3-15. 장기 기억 — 켜는 순서 · 끄기 · 되돌리기」 절의 「판정 이벤트 기록 · 인상」 문단 |
| `MEMORY_IMPRESSION_EVERY_N_FOLDS` | 설정 안 함(기본 `3`) | 인상 하나가 덮는 요약 스냅샷 수. 방의 스냅샷 수가 이 값의 배수가 된 접기 뒤에 가장 새 스냅샷까지 이만큼을 묶는다 — 접기는 대략 10턴마다라 `3` 이면 약 30턴마다 한 번이다. 1 이상이어야 기동한다. 개발 측정에서 다시 정한다 |
| `NOVELIZE_ENABLED` | 켤 때 `true`(코드 기본값은 `false`) | 소설화(대화를 장편 소설의 장으로 옮겨 쓰기) 전역 스위치. 쓰려면 이 스위치·아래 명단·어드민이 준 계정별 허용 셋이 모두 있어야 한다 — 코드 기본값이 닫힘이라 이 줄 없이 배포하면 닫힌 채 뜬다. 끄면 재기동 뒤 모든 소설 화면·API 가 403 이고 허용 행은 남는다(다시 켜면 그대로 돌아온다). 켜기·끄기·회수·롤백은 "소설화 켜기 · 끄기 · 회수 · 롤백" 절 |
| `NOVELIZE_GRANT_ALLOWLIST` | 허용할 수 있는 계정 id, **쉼표 구분**(공백·따옴표 없이) | 어드민이 허용을 줄 때와 사용자가 접근할 때 둘 다 본다 — 명단 밖 계정에는 어드민이 허용을 줄 수 없고(422), 명단에서 빼고 재기동하면 허용 행이 남아 있어도 바로 막힌다. 비면 아무에게도 줄 수 없다(기본값). UUID 가 아닌 항목이 있으면 api 가 기동하지 못한다. 개인정보 처리방침이 소설화를 적기 전에는 운영자 계정만 넣는다 |
| `GEMINI_NOVELIZE_MODEL_NAME` | 설정 안 함(기본값은 `apps/api/.env.example` 주석 줄) | 소설화 장 생성·문단 수정 모델. 장 경계 제안은 이 키가 아니라 `GEMINI_MODEL_NAME` 을 쓴다. 값이 비면 `GEMINI_MODEL_NAME` |
| `GEMINI_NOVELIZE_MAX_OUTPUT_TOKENS` | 설정 안 함(기본값은 `.env.example`) | 장 생성·문단 수정의 출력 상한(사고 토큰 포함). 여기서 잘린 결과는 저장하지 않고 실패·환불하므로, 낮추면 원가만 버린다. 아주 작게 넣고 재기동하면 잘림 → 실패 → 환불 1회를 운영에서 일부러 관측할 수 있다(확인 뒤 줄을 지우고 다시 재기동) |
| `GEMINI_NOVELIZE_THINKING_BUDGET` / `GEMINI_NOVELIZE_THINKING_LEVEL` | 설정 안 함(둘 다 비면 모델 기본 사고) | 소설화 사고 예산(정수) 또는 사고 수준(`MINIMAL`·`LOW`·`MEDIUM`·`HIGH`). ⚠️ **둘 중 하나만** — 둘 다 있으면 api 가 기동하지 못한다(한 요청에 둘을 함께 받으면 거부하는 모델이 있어, 뜬 채로 두면 장마다 실패·환불만 반복한다) |
| `GEMINI_NOVELIZE_CHAPTER_TIMEOUT_MS` / `GEMINI_NOVELIZE_REVISE_TIMEOUT_MS` / `GEMINI_NOVELIZE_BOUNDARY_TIMEOUT_MS` / `GEMINI_NOVELIZE_RECHECK_TIMEOUT_MS` | 설정 안 함(기본값은 `.env.example`) | 장 생성(스트리밍이라 "다음 청크까지") / 문단 수정 / 장 경계 제안(사용자가 화면에서 기다린다) / 여러 문단 수정의 묶음 재검사(사용자가 화면에서 기다린다)의 타임아웃(ms). 장 생성·문단 수정은 백그라운드 작업이라 Cloudflare 응답 상한(100초)과 무관하다. 장 생성·문단 수정의 시간 초과는 실패·환불이고, 경계 제안(무과금)의 시간 초과는 제안 없이 후보 턴만 보이며, 재검사(무과금)의 시간 초과는 503 `NOVEL_RECHECK_UNAVAILABLE` 이고 묶음은 그대로다 |
| `NOVELIZE_CHAPTER_MAX_TURNS` / `NOVELIZE_CHAPTER_MAX_TURNS_SONNET` / `NOVELIZE_CHAPTER_MAX_TURNS_OPUS` | 설정 안 함(기본 `45` / `20` / `20`) | 생성 한 번(묶음 하나)이 담는 원문 턴(AI 응답) 수의 상한 — 모델마다 따로다. 경계 제안이 이만큼의 후보 턴을 보이고, 생성은 끝 메시지가 이 범위 밖이면 거절한다. 첫 키는 Gemini 값이다(키 이름은 모델이 하나뿐이던 때의 것). 운영 `.env` 에 이 키가 없으면 코드 기본값 `45` 가 그대로 쓰이고, 있으면 그 값이 이긴다 |
| `NOVELIZE_K_MAX_GEMINI` / `NOVELIZE_K_MAX_SONNET` / `NOVELIZE_K_MAX_OPUS` | 설정 안 함(기본 `3` / `1` / `1`) | 묶음 하나가 나뉘는 화 수의 상한(모델별). 화 수는 원문 분량으로 정하고 이 값에서 자른다. 연쇄 생성("남은 대화 한 번에")은 묶음마다 이 상한만큼의 화 값을 미리 받는다 |
| `NOVELIZE_EPISODE_TARGET_CHARS` / `NOVELIZE_SOURCE_RATIO` | 설정 안 함(기본 `5000` / `0.8`) | 화 하나의 목표 길이(공백 포함 글자)와 원문 글자를 본문 글자로 바꾸는 비율. 화 수 = 원문 글자 × 비율 ÷ 목표 길이를 반올림한 값(위 상한에서 자른다) |
| `NOVELIZE_CHAPTER_DAILY_LIMIT` / `NOVELIZE_PROPOSAL_HOURLY_LIMIT` | 설정 안 함(기본값은 `.env.example`) | 같은 시작 메시지에서 하루(KST)에 낼 수 있는 묶음 생성·다시 만들기 작업 수(진행 중·성공만 센다) / 무과금 경계 제안의 시간당 상한. 면제 계정도 똑같이 센다 |
| `NOVELIZE_CHAIN_MAX_BATCHES` / `NOVELIZE_CHAIN_TIMEOUT_MARGIN_SECONDS` | 설정 안 함(기본 `5` / `60`) | 연쇄 생성 한 번이 만드는 묶음 수의 상한(한 번에 묶이는 클로버의 상한이기도 하다) / 연쇄 부모 작업의 전체 시간 상한에 더하는 고정 여유(초). 그 상한은 계획한 묶음 수 × (`NOVELIZE_JOB_TIMEOUT_SECONDS` + `GEMINI_NOVELIZE_BOUNDARY_TIMEOUT_MS` 의 초) + 이 여유다(기본값이면 묶음 5개에 5 × 390 + 60 = 2,010초). 넘으면 부모가 실패하고 아직 쓰지 않은 몫을 환불한다 |
| `NOVELIZE_PREVIOUS_SUMMARIES_MAX_CHARS` / `NOVELIZE_SNAPSHOT_LIMIT` | 설정 안 함(기본 `8000` / `50`) | 다음 묶음 생성에 싣는 지난 화 요약 전체의 글자 상한(넘으면 오래된 화부터 뺀다) / 소설 하나의 스냅샷 개수 상한(닿으면 가장 오래된 복원 직전 자동 스냅샷부터 지우고, 이름 붙인 것만 남았으면 새 저장을 거절한다) |
| `NOVELIZE_HEARTBEAT_INTERVAL_SECONDS` / `NOVELIZE_HEARTBEAT_EXPIRY_SECONDS` / `NOVELIZE_JOB_TIMEOUT_SECONDS` | 설정 안 함(기본값은 `.env.example`) | 소설화 작업의 살아 있음 표시 주기 / 그 표시가 이만큼 끊기면 죽은 작업으로 보고 실패·환불하는 만료 / 작업 하나의 전체 상한(초). 만료는 주기보다 넉넉히 길어야 한다 — 짧으면 DB 가 잠깐 느린 것만으로 살아 있는 작업이 환불되고 결과가 버려진다. "소설화 켜기 · 끄기 · 회수 · 롤백" 절의 대기 시간이 이 값들에서 나온다. 소설화 워커를 띄우는 운영에서 작업 상한을 올리면 워커 컨테이너의 정지 유예와 교체 스크립트의 워커 슬롯 대기 상한도 함께 올린다 — 둘 다 "작업 상한 + 여유"로 잡은 값이라, 작업 상한만 올리면 교체가 돌던 작업을 유예 안에 다 기다리지 못하고 끊어 만료 환불로 넘긴다 |
| `NOVELIZE_WORKER_ENABLED` | **운영 `true`**(2026-10-24부터, 코드 기본값 `false`) | 소설화 워커 스위치. 켜면 api 는 연쇄 부모(남은 대화 한 번에)를 뺀 소설화 작업을 자기 프로세스에서 띄우지 않고 대기 행만 남기며, 따로 뜬 워커 프로세스(`python -m api.novelize.worker`)가 그 행을 집어 돌린다 — api 교체가 돌던 작업을 죽여 만료 환불로 넘기지 않게 하려는 것이다. 꺼져 있으면 모든 작업을 지금처럼 api 안에서 띄운다. 🔴 워커 프로세스 없이 켜면 새 소설화 작업이 모두 heartbeat 만료 뒤 환불로 끝난다 — 워커 컨테이너는 교체 스크립트가 이 스위치를 보고 띄우므로, 워커 서비스가 없는 compose 나 워커 모듈이 없는 옛 이미지로 되돌릴 때는 먼저 이 줄을 지운다("BE → GCE VM" 절 "롤백"). 연쇄 부모는 스위치와 무관하게 늘 api 안에서 돈다 |
| `NOVELIZE_WORKER_POLL_INTERVAL_SECONDS` / `NOVELIZE_WORKER_MAX_CONCURRENT_JOBS` | 설정 안 함(기본 `2` / `4`) | 워커가 대기 작업을 찾는 간격(초, 0 보다 커야 한다) / 워커 하나가 동시에 돌리는 작업 수 상한(1 이상). 상한이 차 있는 동안 안 집힌 작업은 heartbeat 만료 뒤 환불되므로 상한은 실사용 동시 작업 수보다 넉넉해야 한다. 상한을 올리면 워커의 DB 풀도 함께 키운다 — 작업 하나가 단계 세션과 heartbeat 세션을 함께 쥘 수 있다. api 는 이 둘을 읽지 않는다(워커 프로세스만 읽는다) |
| `NOVELIZE_MIN_CHAPTER_CHARS` / `NOVELIZE_PREVIOUS_EXCERPT_CHARS` | 설정 안 함(기본값은 `.env.example`) | 화 본문 하나라도 이보다 짧으면 정상 종료여도 그 묶음 생성을 실패·환불하는 하한(글자) / 다음 묶음 생성에 싣는 직전 화 끝 발췌의 목표 길이(글자) |
| `BEDROCK_ACCESS_KEY_ID` / `BEDROCK_SECRET_ACCESS_KEY` | Bedrock 호출만 허용한 전용 IAM 사용자의 액세스 키 쌍 | 상위 모델을 Bedrock 의 Claude 로 보낼 때의 자격 — 아래 `LLM_CALL_SITE_BACKENDS` 에 배정이 없는 호출 위치는 코드 기본 경로인 Bedrock 으로 간다(운영은 상위 모델 호출을 모두 직결에 배정해 두었다). 🔴 R2 용 `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` 와 다른 키이고 그 줄들은 건드리지 않는다 — 앱이 이 두 키를 SDK 에 명시로 넘기며, 비어 있으면 호출 전에 실패한다(R2 키로 내려가지 않게). 켜진 상위 모델 스위치가 여는 호출 중 Bedrock 으로 가는 것이 있는데 비어 있으면 api 가 기동하지 못한다. 경로와 넣는 순서는 "상위 모델(채팅 Opus 직결) — 꺼진 채 배포 · 켜기 · 끄기" 절 |
| `BEDROCK_REGION` | 설정 안 함(기본 `ap-northeast-2`) | 호출 출발 리전. `AWS_REGION`(R2 의 `auto`)과 별개다. 스위치가 켜진 호출이 Bedrock 으로 가는데 값만 비우면(`BEDROCK_REGION=`) 기동하지 못한다 |
| `BEDROCK_SONNET_MODEL_ID` / `BEDROCK_OPUS_MODEL_ID` | 설정 안 함(기본값은 `.env.example`) | 실제 모델 id. 새 버전으로 옮길 때 이 값만 바꾸면 방·작업에 저장된 모델 값은 그대로다. 단가표(`apps/api/src/api/llm/pricing.py`)에 없는 id 면 어드민 사용량의 원가가 "단가 없음"으로 빠진다 — 단가를 함께 넣는다 |
| `BEDROCK_CHAT_TIMEOUT_MS` / `BEDROCK_CHAPTER_TIMEOUT_MS` | 설정 안 함(기본 `45000` / `300000`) | 상위 모델 채팅 턴 / 소설 장 생성의 요청 타임아웃(ms). 스트리밍이라 "다음 청크까지"의 상한이다. 재시도는 하지 않는다 |
| `BEDROCK_CHAT_MAX_TOKENS` / `BEDROCK_CHAPTER_MAX_TOKENS` | 설정 안 함(기본 `4096` / `32768`) | 출력 상한. Bedrock 은 요청의 출력 상한만큼 분당 토큰 쿼터를 먼저 잡으므로 올리면 동시 요청이 스로틀되기 쉽다. 장이 잘리면 실패·환불이다 |
| `ANTHROPIC_DIRECT_API_KEY` | Anthropic 콘솔에서 만든 이 서비스 전용 API 키 | 상위 모델을 Anthropic API 로 직접 보낼 때의 자격. SDK 가 스스로 읽는 `ANTHROPIC_API_KEY` 와 이름을 나눴다. 아래 배정이 호출을 직결로 옮기는데 비어 있으면 스위치와 무관하게 api 가 기동하지 못한다. 직결의 모델 id·타임아웃·출력 상한·사고 깊이(나머지 `ANTHROPIC_*`)는 설정 안 함이 기본이다(기본값은 `.env.example`) |
| `LLM_CALL_SITE_BACKENDS` | `chat_generate:anthropic,replay_generate:anthropic,novelize_chapter:anthropic` 에 더해 판정·요약·추출 호출 위치 열 `chat_stat_judgment`·`chat_ending_judgment`·`chat_situational_image`·`chat_media_book_image`·`chat_memory_summary`·`chat_memory_episode`·`preview_stat_judgment`·`preview_ending_judgment`·`preview_media_book_image`(2026-10-13)·`chat_memory_fact`(2026-10-14)도 `:anthropic`(쉼표 구분, 공백·따옴표 없이. 코드 기본값은 배정 없음). 인상 생성 `chat_memory_impression` 은 아직 넣지 않았다 — 인상 쓰기를 켤 때 모델 줄과 함께 넣는다 | 호출 위치마다 공급자 구현을 배정한다. 배정이 없는 호출 위치의 상위 모델은 코드 기본 경로인 Bedrock 으로 간다. 판정·요약·추출 항목은 위 `STAT_JUDGMENT_MODEL` 행의 모델 줄과 짝이라 함께 넣고 함께 지운다. 🔴 운영은 채팅 세 배정을 유지한다 — 빼면 채팅 Opus 가 Bedrock 으로 가고, 스위치가 켜진 채 Bedrock 키가 없으면 api 가 기동하지 못한다. 따를 수 없는 배정(모르는 이름, 그 모델을 서비스하지 않는 구현)도 기동을 막는다. 장면 헤더 판정 호출 위치(`chat_scene_judgment`·`preview_scene_judgment`)는 줄을 두지 않고 배정을 물려받는다 — 채팅 장면은 채팅 스탯 판정을, 미리보기 장면은 채팅 장면을 거쳐 같은 배정을 따른다. **스탯 판정 배정을 바꾸면 장면 판정도 함께 움직인다**(줄을 따로 넣으면 그 이름을 모르는 옛 이미지가 뜨지 못한다). 미리보기 생성(`preview_generate`)과 미리보기 판정 넷은 채팅 짝(`chat_generate`·`chat_stat_judgment`·`chat_ending_judgment`·`chat_media_book_image`·`chat_scene_judgment`)의 배정을 물려받는다. 미리보기 줄이 없으면 짝의 배정으로 가고, 줄이 있으면 그 줄로 가는 경로가 짝을 물려받아 가는 경로와 같아야 기동한다(다르면 api 가 뜨지 않는다). 그래서 **채팅 판정 배정을 바꿀 때는 짝인 미리보기 판정 줄도 같은 편집에서 바꾼다** — 채팅 줄만 바꾸고 미리보기 줄을 남기면 기동이 거부된다. `preview_generate` 줄은 넣지 않는다(채팅 생성 배정을 물려받는다 — 그 이름을 그 호출의 모델로 읽는 옛 이미지는 `preview_generate:anthropic` 줄로 뜨지 못한다). 모델 배정 표(`prompt_routes`)의 행은 이 배정 위에 얹힌다 — 판정·요약·추출 칸의 행은 그 행을 읽는 호출 위치 전부(채팅과 미리보기 판정, 물려받는 장면 판정)에서 이 배정으로 푼 경로가 행의 경로와 같을 때만 쓰인다. 배정을 바꾼 뒤에는 "채팅 단계별 문안 체인·호출 모델 설정 — 켜기 · 끄기 · 되돌리기" 절대로 건너뛴 행을 확인한다. 절은 "상위 모델(채팅 Opus 직결) — 꺼진 채 배포 · 켜기 · 끄기" |
| `CHAT_PREMIUM_MODELS_ENABLED` | 켤 때 `true`(코드 기본값은 꺼짐) | 채팅 상위 모델 스위치. 켜면 로그인 회원 모두가 채팅방에 상위 모델(Opus)을 고를 수 있다 — 명단·계정별 허용은 없다. 운영 `.env` 에 남은 `CHAT_PREMIUM_MODEL_ALLOWLIST` 줄은 지금 이미지가 읽지 않지만 지우지 않는다(채팅 명단이 있던 옛 이미지로 태그 롤백하면 옛 판정이 그 명단을 다시 읽는다). 켜고 끄는 법은 "상위 모델(채팅 Opus 직결) — 꺼진 채 배포 · 켜기 · 끄기" 절 |
| `NOVELIZE_PREMIUM_MODELS_ENABLED` / `NOVELIZE_PREMIUM_MODEL_ALLOWLIST` | 켤 때 `true` / 계정 id **쉼표 구분**(코드 기본값은 꺼짐·빈 명단) | 소설 장 상위 모델 스위치와 허용 가능 계정 명단. 뜻은 소설화 스위치·명단과 같고, 어드민이 준 계정별 허용 행도 있어야 한다. 소설화 자체(`NOVELIZE_ENABLED`·`NOVELIZE_GRANT_ALLOWLIST`)도 열려 있어야 쓸 수 있다 |
| `NOVEL_PUBLIC_ENABLED` | 켤 때 `true`(코드 기본값은 `false`) | 노벨(공개 소설) 스위치. 소설화(`NOVELIZE_ENABLED`·명단·계정별 허용)와 별개로 이 스위치도 켜져 있어야 소설을 노벨에 공개·다시 공개할 수 있다 — 코드 기본값이 닫힘이라 이 줄 없이 배포하면 닫힌 채 뜬다. 끄면 재기동 뒤 공개·다시 공개·게시자의 공개 상태 조회가 403 `NOVEL_PUBLIC_DISABLED` 이고, 공개 상태 행은 남아 다시 켜면 그대로 돌아온다. 켜기·끄기는 "노벨(공개 소설) 켜기 · 끄기" 절 |
| `NOVEL_PUBLIC_PREVIEW_ALLOWLIST` | 미리보기 동안 계정 id, **쉼표 구분**(공백·따옴표 없이). 전체 공개 뒤에는 줄을 지운다(코드 기본값은 빈 명단) | 노벨 미리보기 명단. 비어 있으면 스위치가 켜졌을 때 모두에게 열리고, 비어 있지 않으면 스위치가 켜져 있어도 명단의 로그인 회원에게만 열린다 — 그 밖의 회원·비로그인은 스위치를 끈 것과 같은 응답이고, 인증 없는 가격 응답의 `novelPublicEnabled` 도 거짓이다. UUID 가 아닌 항목이 있으면 api 가 기동하지 못한다. 절차는 "노벨(공개 소설) 켜기 · 끄기" 절 |
| `NOVEL_PUBLIC_POLICY_V2_ENABLED` | **운영 `true`**(2026-10-25부터, 코드 기본값 `false`) | 노벨 공개 정책 스위치. 꺼져 있으면 지금 약관대로다 — 첫 공개는 자동 글 심사를 통과하면 바로 열리고, 원작자가 소설화 허락을 거두면 다음 화가 막힌다. 켜면 아직 독자에게 보인 적 없는 소설의 첫 공개가 운영자 승인(어드민 `POST /admin/novels/{id}/review`)을 기다리고, 한 번 독자에게 보인 소설(연재권 잠금)은 원작자가 허락을 거두거나 원작을 비공개로 돌리거나 탈퇴해도 다음 화를 이어 공개한다(원작 이용제한·삭제만 막는다). 원작자가 탈퇴하면 그 원작의 대화 중 첫 화를 저장하지 않은 것은 새로 소설화할 수 없다. 켜져 있으면 이미 공개한 화를 고쳐 다시 낼 때 작가의 짧은 변경 요약(1~100자)이 필요하고(없으면 422 `NOVEL_CHANGE_SUMMARY_REQUIRED` — 이 칸을 보내는 web 화면이 나가기 전에 켜면 다시 공개가 막힌다), 그 요약도 글 심사를 거쳐 산 사람의 판 고르기에 공개 시각과 함께 보인다. 산 사람 보호도 켜진다 — 산 때의 판을 고를 수 있고, 거둠·게시자 정지·판매된 소설 삭제·게시자 탈퇴 뒤에도 소장자는 계속 읽으며(게시자가 탈퇴하면 판매된 소설은 숨겨 남고 판매되지 않은 소설만 지운다, 환급 없음), 노벨 이용제한·원작 이용제한·원작 삭제는 구매를 환급한다. 운영자의 판매 중단(노벨 판매 중단, 원작 제한·삭제 때 파생 소설은 판매만 멈추기)도 켜졌을 때만 쓸 수 있다 — 목록·새 판매만 멈추고 소장자는 계속 읽으며 환급하지 않는다(꺼져 있으면 409 `NOVEL_SALES_STOP_DISABLED`). 판매된 소설 삭제는 숨김(숨길 때 게시자 탈퇴와 같이 작가 전용 데이터를 지운다 — 남는 것은 "공개 정책 스위치" 단락의 탈퇴 목록과 같다), 판매된 화가 든 마지막 묶음 삭제는 409 다. 6화부터 화마다 무료·유료를 골라 공개하고 유료 화를 무료로 바꿀 수 있으며, 그렇게 무료로 나간 번호는 그 화를 지우고 다시 만들어도 무료로만 공개한다(꺼져 있으면 6화부터 유료로 저장하고 무료로 전환은 409, 무료로 나간 번호도 지키지 않는다). 잠금 기록(첫 공개마다)과 판 행(공개마다), 화마다의 가격 칸은 스위치와 무관하게 쌓인다. 켜는 순서·롤백은 "노벨(공개 소설) 켜기 · 끄기" 절의 "공개 정책 스위치" |
| `NOVEL_ILLUSTRATIONS_ENABLED` | 개정 처리방침(삽화 항목) 게시 뒤 켤 때 `true`(코드 기본값은 `false`) | 소설 화 삽화 스위치. 꺼져 있으면 지금 약관대로다 — 작가의 삽화 붙이기·옮기기·바꾸기·떼기와 원작 그림 후보 API 가 404(캐시 안 함), 삽화 용도 업로드(`novel-illustration`)는 422, 작가의 화·개정 응답에 그림이 없고, 소설 표지로 쓴 생성 이미지도 지금처럼 지울 수 있다(표지가 빈다). 켜면 그 API 들이 열리고, 응답에 그림이 실리고, 웹 가격 응답의 `novelIllustrationsEnabled` 로 작가 화면의 진입이 열리며, 표지로 쓴 이미지는 삭제가 409 다. 스위치와 무관하게 이미 개정에 붙은 배치는 새 개정으로 이어지고 그 그림은 지울 수 없으며(409), 어느 개정도 쓰지 않게 된 업로드 삽화 파일(과 소유자가 탈퇴한 생성 이미지 — 그 그림이 하나도 남지 않은 이미지 생성 요청 행도 함께)은 소설 삭제·묶음 삭제·탈퇴·숨긴 소설 파기 때 함께 지워진다. 남의 소설이 원작 그림으로 쓰는 원작자의 생성 이미지도 삭제가 409 이고, 그 소설의 id·제목은 원작자에게 보이지 않는다. 스키마·롤백은 "소설 화 삽화 스키마" 절 |
| `NOVELIZE_OUTLINE_FLOW_ENABLED` | 개정 처리방침(구간 선택·구성안 항목) 게시 뒤 켤 때 `true`(코드 기본값은 `false`) | 소설 구성 흐름 스위치 — 작가가 소설로 옮길 대화 구간을 고르고(뺄 구간은 모델에 보내지 않는다) 구성안을 거쳐 화를 만드는 흐름. 꺼져 있으면 지금의 이어 쓰기 흐름(경계 제안·묶음 생성·연쇄·다시 만들기)만 있다. 지금은 웹 가격 응답의 `novelizeOutlineFlowEnabled`, 구간 선택 라우트(`/novels/{id}/source-selection` 조회·초안 저장·승인)와 전체 구성안 라우트(`/novels/{id}/outline` 조회·만들기(과금)·고친 판 저장·승인), 화별 장면 구성안 라우트(`/novels/{id}/outline/episodes/{key}/scenes` 조회·만들기(과금)·고친 판 저장·승인), 원고 라우트(`/novels/{id}/outline/episodes/{key}/chapter`, 과금)와 구성 흐름 화 다시 만들기(`/novels/{id}/outline/chapters/{chapterId}/regenerate`, 과금)만 이 값을 따른다(꺼져 있으면 모두 캐시하지 않는 404) — 켜면 구간 선택 행과 유료 구성안·장면 구성안·구성 흐름 화가 생기기 시작한다. 전체 구성안 단가는 입력 상한 길이의 잰 원가로 정했고(근거는 `core/clover.py` 단가 주석), 장면 구성안 단가는 화 단가와 같게 둔 값이다. 옛 다시 만들기 라우트는 스위치와 무관하게 구성 흐름 화를 409 `NOVEL_CHAPTER_OUTLINE_FLOW` 로 거절한다. 옛 이어 쓰기(경계 제안 `POST /novels/{id}/chapter-proposal`·묶음 생성 `POST /novels/{id}/chapters`·연쇄 `POST /novels/{id}/chain`)는 켜져 있는 동안 409 `NOVEL_OUTLINE_FLOW_REQUIRED` 로 거절한다 — 그 길은 승인한 선택(뺀 구간)을 보지 않고 화 번호가 가장 큰 화의 끝부터 이어 읽어, 뺀 대화까지 모델에 보내기 때문이다. 이어 쓰기로 이미 만든 화의 다시 만들기와 연쇄 견적(`GET …/chain-estimate`, 모델 호출 없음)은 그대로 받는다. 그래서 화면이 구성 흐름으로만 다음 화를 만들게 된 뒤에 켠다(켠 뒤 옛 화면에서 이어 쓰기를 누르면 409 다). 켠 채 이 거절이 없는 옛 이미지로 되돌리면 옛 이어 쓰기가 다시 열린다 — 되돌리기 전에 스위치를 끄거나 그 동안 열리는 것을 감수한다. 스키마·롤백은 "대화 구간 선택 스키마" 절 |
| `NOVELIZE_OUTLINE_MAX_EPISODES` / `NOVELIZE_OUTLINE_MAX_INPUT_TOKENS` | 설정 안 함(기본 `30` / `140000`) | 전체 구성안 한 판의 화 수 상한(모델이 이를 넘게 나누면 실패·환불, 사용자가 고친 판도 이 안이어야 한다 — 묶음 하나의 화 수 상한 `NOVELIZE_K_MAX_*` 과 다른 값) / 전체 구성안·장면 구성안·원고 호출 한 번의 입력 견적 상한(토큰 — 지금은 고른 원문 줄의 글자 수로 어림한다). 견적이 넘으면 모델을 부르기 전·차감 전에 422 `NOVEL_OUTLINE_INPUT_TOO_LARGE`(구간을 줄여 다시 고르라는 안내)다. 화 수 상한은 구성안 분포를 재기 전의 임시값이다. 입력 상한은 전체 구성안 가격이 그 길이의 원가로 정해져 있어 올리면 가격도 다시 계산해야 하니 env 로 따로 올리지 않는다. 둘 다 구성 흐름 스위치가 꺼져 있으면 쓰이지 않는다 |
| `NOVELIZE_MULTI_BLOCK_EDIT_ENABLED` | **운영 `true`**(2026-10-26부터, 코드 기본값 `false`) | 여러 문단 수정 스위치 — 작가가 같은 장면 안의 떨어진 문단 여럿을 골라 한 번에 AI 수정을 맡기고(AI 수정 단가 한 번, 블록 수 무관) 문단마다 수정안을 받는 흐름. 꺼져 있으면 지금의 연속 범위 수정(`/ai-edits`)만 있다. 웹 가격 응답의 `novelizeMultiBlockEditEnabled`, 요청 라우트(`/novels/{id}/chapters/{chapterId}/block-edits`, 과금)와 묶음 재검사 라우트(`/novels/{id}/jobs/{jobId}/bundles/{bundleId}/recheck`, 무과금 모델 호출)만 이 값을 따른다(꺼져 있으면 둘 다 캐시하지 않는 404). 이미 만든 수정안의 상세 목록(`pendingBlockEdits`)과 단위 적용·버리기(`/novels/{id}/jobs/{jobId}/patches/apply`·`.../patches/dismiss`)는 꺼져 있어도 된다 — 켰다 끈 뒤에도 받은 수정안을 쓰거나 버릴 수 있다. 연속 범위 수정은 켠 뒤에도 그대로 남는다. 스키마·롤백은 "여러 문단 수정 스키마" 절, 적용·재검사 배포·되돌리기는 같은 절의 "여러 문단 수정 적용·버리기·재검사" 단락 |
| `NOVELIZE_BLOCK_EDIT_MAX_INPUT_CHARS` | 설정 안 함(기본 `60000`) | 여러 문단 수정 한 번의 입력 견적 상한(글자 — 모델에 보낼 문맥 문단(장면 있는 화는 그 장면, 없으면 화 전체)·작품 설정·설정 노트·지시의 합). 넘으면 모델을 부르기 전·차감 전에 422 `NOVEL_EDIT_INPUT_TOO_LONG` 이다. 잰 지연으로 정한 값이다 — 수정 호출 지연은 거의 고칠 문단 수가 정하고, 출력이 잰 값의 p90 일 때 지연이 수정 타임아웃 120초의 절반 안에 드는 입력이 약 5.9만 자다(12만 자면 문단 20개 요청이 약 100초로 타임아웃에 가깝다, 4.4만 자 위는 외삽). 장면 없는 화는 화 전체를 세므로 6만 자가 넘는 화는 장면을 나누기 전에는 여러 문단 수정을 받지 못한다(연속 범위 수정은 그대로). 올리면 큰 입력의 여러 문단 요청이 타임아웃으로 실패·환불될 수 있다. 스위치가 꺼져 있으면 쓰이지 않는다 |
| `NOVELIZE_RECHECK_HOURLY_LIMIT` | 설정 안 함(기본 `10`) | 여러 문단 수정 묶음 재검사(무과금 모델 호출)의 사용자당 시간당 상한. 넘으면 모델을 부르기 전에 429 다. 면제 계정도 똑같이 센다. 재검사 원가를 재기 전의 임시값이고, 스위치가 꺼져 있으면 쓰이지 않는다 |

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
확인까지 한다(실측: 2026-10-22~10-24 deploy-api 성공 30회 중앙값 약 2분 20초, 1분 39초~4분 35초. 그중 VM 에서 pull·교체·확인하는
단계가 중앙값 약 1분 10초, 이미지 빌드·푸시가 약 40초다. 교체는 옛 색에 남은 요청이 끝나기를 기다리므로 그만큼 길어질 수 있다).
트리거 경로는 `apps/api/**` · `docker-compose.prod.yml` · `Caddyfile` · 저장소 루트 `ops/**` ·
워크플로 자신이다. 단 `apps/api/**` 중 런타임 코드가 읽지 않는 파일(`tests/`, 앱 최상위 md, `probe-runs/`,
평가 도구 `scripts/memory_eval/`·`scripts/memory_eval_cli.py`, 쓰지 않는 `cloudbuild.yaml`)만 바뀐 병합은
배포하지 않는다 — 교체해도 운영 동작이 같다. `apps/api/README.md` 는 빌드가 읽으므로 지우거나 이름을 바꾸면
다음 api 배포의 빌드에서야 드러난다.
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

소설화 워커(`worker_blue`·`worker_green`, api 와 같은 이미지로 `python -m api.novelize.worker` 를 돌린다)는 이 흐름에 두 군데
끼어 있다. 둘 다 겹침 없는 교체(`skip_overlap`)에서는 돌지 않는다.

- **워커 슬롯 비우기(로그 `5-2)`)** — 4 의 idle 줄을 고치기 전, api 를 겹치기 전. 멈춘 워커 컨테이너(정상 교체 뒤에는 정지가 끝난
  옛 워커가 늘 하나 남는다)는 곧바로 지운다. 떠 있으면서 정지 중인 옛 워커(앞 교체가 정지시켰는데 돌던 작업을 아직 마치는 중 —
  연달아 병합한 배포)만 내려갈 때까지 **최대 420초** 기다린다. api 두 색에 워커 둘이 겹쳐 메모리·DB 연결이 한꺼번에 느는 것을
  막으려는 것이다. 420초 안에 안 내려가면 api 교체는 계속하고 아래 워커 단계만 건너뛴 채 실패로 알린다.
- **워커 단계(로그 `12-1)`)** — 6 의 줄 맞춤 뒤, 상태 파일을 쓰기 전. 막 합류한 새 api 색 안에서 스위치(`NOVELIZE_WORKER_ENABLED`)와
  이미지의 워커 모듈 유무를 판정한다(`.env` 를 읽지 않는다 — 앱과 같은 설정 파서로 토큰 셋만 찍는다). 판정은
  `/var/lib/ddona/novelize_worker`(`on`/`off`)에 남아 리소스 감시 크론이 읽는다.
  - 꺼짐이거나 워커가 없는 옛 이미지면 새 워커를 띄우지 않고 떠 있던 워커를 모두 정지시킨다. 로그
    `12-1) 소설화 워커 꺼짐(판정: …) — 떠 있던 워커 N개 분리 정지`. 스위치를 끈 배포는 이 줄 하나로 지나간다.
  - 켜짐이면 빈 워커 슬롯(새 api 색 쪽이 비었으면 그쪽)에 새 워커를 띄우고(`up --no-deps --force-recreate --wait`, 최대 60초)
    healthy 가 된 **뒤에만** 옛 워커를 정지시킨다. 로그 `12-1) worker_<색> 기동(이미지 …), worker_<색> 분리 정지`. 그 사이 두
    워커가 같은 작업을 집어도 대기 → 실행 전이가 조건부라 한쪽만 돈다.
  - 옛 워커의 정지는 **분리 정지**다 — 정지 표식(`/tmp/draining`)을 세운 뒤 `docker compose stop` 을 `systemd-run` 유닛
    (`ddona-novelize-worker-stop-<색>`)으로 띄우고 스크립트는 곧바로 다음으로 간다. 옛 워커는 새 작업을 집지 않고 돌던 작업을
    정지 유예(420초) 안에서 끝까지 마친 뒤 내려간다. 유닛은 PID 1 이 띄워 교체 잠금 fd 를 물려받지 않으므로 그동안 다음 교체가
    잠금을 얻을 수 있고, 배포 SSH 가 끊겨도 정지는 끝까지 간다. 진행은 `systemctl list-units --all 'ddona-novelize-worker-stop-*'`.
  - 새 워커가 healthy 가 안 되면 api 교체는 그대로 두고(이미 새 색이 서빙 중이다) 실패한 새 워커만 지운다. 옛 워커는 정지하지
    않아 계속 작업을 받는다(옛 워커가 없었으면 새 작업은 60초 뒤 환불된다). Discord 로 알리고, 표준 출력에
    `DDONA_WORKER_STEP_FAILED …` 한 줄을 남긴 채 0 으로 끝난다 — 배포 워크플로가 그 줄을 보고 run 을 실패로 표시한다. 원인을
    고친 뒤 같은 교체(같은 태그의 워크플로 재실행, 또는 env 를 고쳤으면 태그 없는 교체)를 다시 부르면 api 를 한 번 더 갈고 빈
    슬롯에 새 워커를 띄운 뒤 옛 워커를 정지시킨다. 재실행은 매번 워커를 새 컨테이너로 갈므로, 끝난 뒤 형상(살아 있는 워커 1개 ·
    그 이미지가 이번 태그 · 실패 컨테이너와 남은 정지 유닛 없음)이 같으면 된 것이다.
  - **워커는 손으로 띄우지 않는다.** `compose up worker_<색>` 은 위 판정을 건너뛰어, 워커가 없는 옛 이미지에서는 모듈을 못 찾고
    재시작을 되풀이한다. 서비스명 없는 `up -d` 도 두 워커 색을 띄운다.

워커 단계가 교체에 더하는 시간은 판정 약 2초 + 새 워커 기동 10~20초다. 앞 교체 뒤 7분 안에 연달아 병합하면 5-2 가 옛 워커를 최대
420초 기다려 그 교체는 최대 약 9분이 된다. 잠금 대기 상한(600초)은 다른 교체 호출이 이 잠금을 기다리는 상한이다 — 워크플로끼리는
`concurrency` 가 줄 세우므로 잠금에서 만나는 것은 워크플로와 VM 수동 교체뿐이고, 수동 호출이 600초를 넘겨 기다리면 아무것도 바꾸지
않고 실패한다(안전한 실패).

교체 소요 시간은 옛 색에 남은 가장 긴 요청에 비례한다(최대 정지 유예 65초) — 느린 게 아니라 드레인이 기다리는 것이다.
드레인이 기다리는 것은 요청뿐이다. 응답 뒤에 붙인 `BackgroundTasks`(인증 메일·조회수 집계·턴 뒤 기억 요약·추출 등)는 요청의 일부라 종료 때
끝까지 기다려지고(상한은 `stop_grace_period`), 응답 연결 없이 `asyncio.create_task` 로 도는 소설화 작업(워커 스위치가 켜져 있으면 연쇄(부모와 그 부모가 직접 돌리는 자식 — 워커는 자식 행을 집지 않는다)만 — 나머지 소설화 작업 6종은 워커가
정지 신호 뒤에도 끝까지 마친다)은 기다려지지 않고 프로세스와
함께 끝난다 — 그 환불은 heartbeat 만료 정리가 맡는다("알려진 갭" 절의 무중단 교체 항목, "소설화 켜기 · 끄기 · 회수 · 롤백" 절).
중간에 끊겨 두 색이 다 떠 있으면 같은 명령을 다시 부르면 이어서 끝난다 — 옛 색에 드레인 플래그가 서 있으면 그 색을 마저
드레인·정지하고(같은 태그 재실행이면 아래 소설화 워커 단계까지 마저 하고 끝 — 끊긴 곳이 드레인이라 그 교체의 워커 단계는 아직 돌지 않았다), 플래그가 없으면 다시 만들 색을 먼저 드레인해 내린 뒤 교체한다. 어느 쪽도
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

**최초 1회 — 크론 로그 회전(logrotate)·journald 상한 설치**. `ops/cron.d`의 크론들은
`/var/log/ddona-<이름>.log`에 덧붙이기만 하고 회전 규칙이 없어 끝없이 자란다. journald 도 VM 기본
설정에 용량 상한이 없어 1GB 넘게 쌓였다. 둘 다 위 접근 로그와 같은 이유로 복사가 아니라 저장소 파일을
심볼릭 링크한다. 크론 로그 규칙은 `/var/log/ddona-*.log` 만 잡아 위 `ddona-caddy`(`/opt/ddona/logs/caddy/`)와
대상이 겹치지 않는다. 컨테이너 로그는 journald 가 아니라 Docker json-file 이 쓰므로 journald 상한과 무관하다.

```sh
# 크론 로그 회전 — 링크 후 dry-run(-d 는 실제로 회전하지 않는다). 출력에 ddona-*.log 들이
# 나오고 오류 줄이 없어야 한다.
sudo ln -sf /opt/ddona/app/ops/logrotate.d/ddona-cron /etc/logrotate.d/ddona-cron
sudo logrotate -d /etc/logrotate.d/ddona-cron

# journald 상한 — drop-in 링크 후 재시작, 이미 쌓인 분을 상한까지 줄인다.
sudo mkdir -p /etc/systemd/journald.conf.d
sudo ln -sf /opt/ddona/app/ops/journald.conf.d/ddona.conf /etc/systemd/journald.conf.d/ddona.conf
sudo systemctl restart systemd-journald
sudo journalctl --vacuum-size=200M

# 검증 — drop-in 이 읽혔는지, 사용량이 200M 이하인지
systemd-analyze cat-config systemd/journald.conf | grep -n SystemMaxUse
sudo journalctl --disk-usage
```

되돌리기 — 링크만 지우면 된다(저장소 파일은 그대로 둔다).

```sh
sudo rm /etc/logrotate.d/ddona-cron
sudo rm /etc/systemd/journald.conf.d/ddona.conf
sudo systemctl restart systemd-journald
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
스키마까지 내려야(downgrade) 하면 그 전에 되돌릴 리비전 파일을 가진 그 이미지로 함께 내려갈 리비전을 본다(옛 태그로 돌리면
목표 위 리비전이 보이지 않는다 — 그 이미지로는 이어지는 downgrade 도 멈추니 안전하지만 확인이 안 된다):

```sh
sudo docker run --rm --network ddona_default --env-file /opt/ddona/.env <IMAGE>:<그 TAG> alembic history -r <목표 리비전>:head
```

`alembic downgrade` 는 목표 위에 쌓인 리비전을 전부 내리고, 기능이 들어간 뒤에도 다른 작업의 리비전이 그
사이와 위에 계속 쌓이므로 기능 절에 적힌 사이 리비전 목록은 믿지 않고 이 출력만 본다. 출력의 마지막 줄은 목표 리비전 자신이라
내려가지 않는다 — 그 줄을 뺀 나머지, 곧 함께 내려갈 리비전 중 다른 작업의 리비전이 있으면 멈추고 그 작업 주인과 정한다.
교체 스크립트가 마이그레이션 전에 올릴 이미지 안에서 DB 리비전을 대조하는 판정(위 롤백 표시 문단의 그 판정)은 DB 의 마지막 클로버
단위 기록(`clover_unit_events`)과 올릴 이미지에 기동 가드가 있는지(단위 상수 `api.core.clover.CLOVER_UNIT_KRW` 의 존재)도 함께 본다(로그 `클로버 단위 기록: <convert|revert|none> <guard|noguard>`). 단위를 전환한
DB(`convert`)에 가드 없는 옛 이미지(`noguard`)를 올리려 하면 마이그레이션 전에 **실패**한다 — 그 이미지는 막히지 않고 떠 1클로버 = 3원으로
환불을 계산하기 때문이다. 그래서 단위 전환 뒤의 롤백 대상은 기동 가드가 들어온 태그 이상이다. 가드가 있는 이미지는 단위가 다른 DB
에서 스스로 기동하지 않는다(`apps/api/CLAUDE.md` 의 "클로버 단위 · 정지 스위치" 절) — 평상시 교체에서는 새 색만 healthy 가 안 돼
멈추고 옛 색이 계속 서빙하지만, 겹침 없는 교체(`skip_overlap`)는 그 자리 재생성이라 가드 거부가 곧 서비스 중단이다. 교체 스크립트를
거치지 않는 기동(손으로 `compose up`, "빈 상태에서 첫 기동" 절)은 이 판정을 타지 않는다.
법무 문서에 시행 예정(예약) 판이 있으면 먼저 어드민에서 철회한 뒤 시행 시각(`effective_at`)이 생기기 전 이미지로 롤백한다(옛 코드는
예약 판을 즉시 현행으로 본다).
과거 태그는 `gcloud artifacts docker tags list asia-northeast3-docker.pkg.dev/ddona-ai-character-chat/ddona/api`.
배포 워크플로가 끝에서(실행 이미지 확인 뒤) `apps/api/scripts/ops/prune_api_images.py`로 VM 로컬 API 이미지를
**현재 것 포함 최근 3개**(+ 실행 중 이미지)만 남기고 지운다 — 다른 저장소 이미지(caddy·postgres 등)는 건드리지
않고, 정리가 실패해도 배포는 성공으로 두고 `::warning::` 한 줄만 남긴다. 그래서 그보다 옛 태그는 VM에 없을 수 있는데,
교체 스크립트는 언제나 `docker pull`부터 하므로 Artifact Registry에서 받아 온다.

**소설화 워커를 켜 둔 채 롤백할 때는 스위치 끄기 → 워커 비우기 → 태그 롤백 순서다.**

```sh
cd /opt/ddona/app
# 0) "소설화 켜기 · 끄기 · 회수 · 롤백" 절 2단계 SQL — 살아 있는 진행 중 작업 수를 본다
# 1) 스위치 끄기 — 태그 없는 교체. 로그 `12-1) 소설화 워커 꺼짐 … 떠 있던 워커 N개 분리 정지`
sudo sed -i '/^NOVELIZE_WORKER_ENABLED=/d' /opt/ddona/.env
sudo python3 ops/check_env.py --format /opt/ddona/.env
sudo bash ops/swap-api.sh
# 2) 워커 비우기 — 두 줄 다 빌 때까지(최대 420초), 정지 유닛도 없어질 때까지, 그리고 0) 의 SQL 이 0
sudo docker ps -q --filter label=com.docker.compose.project=ddona --filter label=com.docker.compose.service=worker_blue
sudo docker ps -q --filter label=com.docker.compose.project=ddona --filter label=com.docker.compose.service=worker_green
systemctl list-units --all 'ddona-novelize-worker-stop-*' --no-pager
# 3) 태그 롤백
sudo DDONA_ROLLBACK=1 bash ops/swap-api.sh <이전SHA>
```

이유는 셋이다. 첫째, 스위치를 끄면 api 가 작업을 다시 자기 안에서 돌리고 워커는 새 작업을 집지 않는다 — 옛 이미지로 내리기
전에 작업을 도는 쪽을 하나로 모은다. 둘째, 워커가 비기 전에 스키마를 되돌리면(downgrade) 아직 돌던 워커의 작업이 사라지는
칸·행에 쓰다 실패하거나 작업 행이 지워져 환불 근거가 없어진다. 셋째, 스위치를 켠 채 워커 도입 이전 태그로 내리면 판정이
`off absent`(옛 설정에는 그 칸이 없다)라 재시작 루프 없이 워커를 내리지만, `.env` 의 스위치 줄이 남아 롤백해 둔 동안 무관한
PR 이 병합되면 자동배포가 새 이미지로 워커를 다시 켠다(그동안 리소스 감시는 꺼짐으로 본다). 2) 를 건너뛰어도 3) 의 5-2 가
멈춘 워커는 바로 지우고 정지 중인 워커를 최대 420초 기다린 뒤 진행한다 — 순서를 스크립트가 한 번 더 지키지만 스키마 downgrade
는 사람이 하므로 2) 를 확인하고 간다. 워커 도입 이후 태그로의 롤백(스위치 켜짐 유지)은 평상시 교체와 같다 — 롤백 이미지로 새
워커가 뜨고 옛(더 새) 워커가 비운다.

**이 워커 배포 형상 자체를 되돌리는(revert) 배포도 먼저 스위치 끄기 → 워커 비우기(위 1)·2), 두 줄 모두 빔)까지 한다.** revert 뒤의
compose 파일에는 워커 서비스가 없어 옛 교체 스크립트도 `up` 도 떠 있던 워커를 내리지 않고(고아 컨테이너), 감시도 꺼진다 — 스위치
줄이 남아 있으면 api 는 계속 대기 행만 만들고 그 고아 워커가 옛 이미지로 무기한 집는다.

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

`skip_overlap` 은 **소설화 워커를 건드리지 않는다** — 워커 슬롯 비우기(5-2)도 워커 단계(12-1)도 돌지 않아 옛 워커가 옛 코드로 새
스키마 위에서 계속 작업을 받는다. 그래서 워커를 켜 둔 운영에서는 **스위치를 끄는 교체(위 "롤백"의 1)·2))로 워커를 0 으로 만든
뒤** `skip_overlap` 배포를 한다. 진행 중 작업 0 만 확인하는 것으로는 부족하다 — 떠 있는 옛 워커가 그 뒤 새 api 가 만든 작업을
계속 집는다. 배포가 끝나면 스위치 줄을 다시 넣고 태그 없는 교체로 워커를 띄운다.

**클로버 단위 전환(1클로버 = 3원 → 1원) — 전환 배포와 되돌림.** 전환 리비전 `725813c4f950` 은 클로버 수량 칼럼을 모두 세 배
하고 잔액이 있는 회원마다 전환 원장 행과 단위 기록(`clover_unit_events` 의 `convert`)을 남긴다(무엇을 바꾸고 무엇을 안 바꾸는지는
그 리비전의 docstring). 옛 코드가 새 단위 수량을 옛 가격으로 깎으면 안 되므로 정지 스위치를 켠 채 겹침 없이 배포한다. 리비전은
돈 데이터가 있는 DB 에서 정지 스위치가 꺼져 있거나, 진행 중 소설 작업이 있거나, 단위 기록이 이미 있으면 아무것도 바꾸지 않고
실패한다(트랜잭션 전체 롤백, 옛 색이 계속 서빙). 잠금을 500ms 넘게 기다리거나 회원 표를 잡은 뒤 5초를 넘겨도 같은 실패다 — 막고
있던 트랜잭션을 본 뒤 같은 실행을 다시 한다. 순서:

```sh
cd /opt/ddona/app
C="sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env"
Q() { $C exec -T postgres psql -U postgres -d ai_character_chat -Atc "$1"; }
# 1) 진행 중 환불 시도 0 — 정지 중에는 그 마무리 라우트도 막힌다. 0 이 아니면 어드민에서 대사로 끝낸 뒤 간다
Q "SELECT count(*) FROM payment_cancellations WHERE status = 'requested';"
# 2) 정지 스위치 켜기 — 태그 없는 교체 뒤 서빙 색이 실제로 켜졌는지(True)
echo 'CLOVER_LEDGER_PAUSED=true' | sudo tee -a /opt/ddona/.env >/dev/null
sudo python3 ops/check_env.py --format /opt/ddona/.env && sudo bash ops/swap-api.sh
$C exec -T api_$(sudo bash ops/active-color.sh) python -c "from api.core.config import settings; print(settings.clover_ledger_paused)"
# 3) 소설화 워커 비우기(위 "롤백"의 1)·2)) — 진행 중 작업 0
Q "SELECT count(*) FROM novel_jobs WHERE status IN ('queued', 'running');"
# 4) 대기 주문 수를 적어 둔다 — 전환 뒤 완료되면 세 배 사본으로 새 상품과 같은 수량을 받는다(문제 아님, 견적 비교에서 줄이 늘어난다)
Q "SELECT count(*) FROM payments WHERE status = 'pending';"
# 5) 백업과 전환 전 견적(같은 접수일을 전환 뒤에도 쓴다)
sudo /opt/ddona/backup.sh --manual
$C exec -T api_$(sudo bash ops/active-color.sh) python scripts/ops/quote_refunds.py --received-on <YYYY-MM-DD> \
    | sudo tee /root/clover-quote-before.csv >/dev/null
# 6) 같은 트랜잭션에 다른 리비전이 섞이지 않게 — DB 리비전이 전환 리비전의 앞(65205c06e037)이고 올릴 이미지의 head 가 725813c4f950
Q "SELECT version_num FROM alembic_version;"
```

7) 병합 커밋 메시지에 `[skip actions]` → 곧바로 Actions 수동 실행(`skip_overlap` 켬). 8) 검산 — 같은 접수일로 견적을 다시 뽑아
`/root/clover-quote-after.csv` 와 sha256 이 같다(대기 주문이 완료됐으면 그 결제 줄만 더해진다), `Q "SELECT action, money_rows FROM
clover_unit_events;"` 가 `convert` 한 행, 전환 원장 행 수(`kind = 'unit_conversion'`) = 잔액이 0 보다 큰 회원 수, 전환 기록의
`lock_started_at` 이후 채팅·이미지·요약 환급 원장 행(`chat_refund`·`image_refund`·`memory_summary_refund`) 0. 9) 정지 스위치 줄을
지우고 태그 없는 교체, 소설화 워커 스위치를 되돌린다.

🔴 **정지를 푼 뒤에는 전환 전 단위 이미지로 롤백하지 않는다 — 앞으로 고치기만 한다.** 정지를 풀면 새 가격(20·200 처럼 3의 배수가
아닌 값)으로 깎인 차감이 쌓여 수량을 3으로 정확히 나눌 수 없다. 전환 전 단위 이미지의 기동 가드는 전환 기록을 보고 뜨지 않고, 가드가
없는 더 옛 태그는 교체 스크립트가 막는다(위 롤백 단락).

**정지를 풀기 전에 되돌려야 할 때(되돌림 런북).** 정지 스위치를 켠 채로 한다.

1. `sudo /opt/ddona/backup.sh --manual` 뒤 건조 실행 — `$C exec -T api_$(sudo bash ops/active-color.sh) python
   scripts/ops/revert_clover_unit.py`. 화면의 항목별 수가 모두 0 이고 `reverted=true` 인지 본다(건조 실행은 끝까지 해 보고 롤백한다).
   전제 위반(3의 배수가 아닌 수량, 전환 뒤 콘솔 취소, 전환 뒤 옛 영수증 환급, 두 경계 기준의 수가 다름)이면 아무것도 쓰지 않고 종료
   코드 1 이다 — 손으로 맞출지 백업 전체 복원("백업 · 복원" 절)으로 갈지 멈추고 정한다. 전체 복원이면 다시 열 때 이미지 키를 전환 전
   단위 태그로 둔다.
2. 같은 줄에 `--apply` 를 붙여 커밋한다.
3. **다른 작업 없이 곧바로** 전환 전 단위 태그로 롤백 교체(`sudo DDONA_ROLLBACK=1 bash ops/swap-api.sh <태그>`). 되돌린 순간부터
   떠 있는 새 단위 프로세스는 새 가격으로 옛 단위 데이터를 다룬다 — 기동 가드는 기동 때만 본다. 옛 단위 이미지의 가드는 되돌림
   기록을 보고 뜬다. 그 사이 정지 스위치를 끄지 않는다.
4. 견적을 다시 뽑아 전환 전 파일과 sha256 이 같은지 본 뒤 정지 스위치를 끈다.

되돌린 뒤 다시 전환하려면 원인을 고친 PR 이 새 리비전을 더한다 — 전환 리비전은 이미 적용 기록이 있어 다시 돌지 않는다(그 리비전
docstring 의 "되돌린 뒤 다시 전환할 때"). 그 PR 도 이 절의 순서 그대로 배포한다.

**겹침 없는 전환 배포 뒤 새 컨테이너가 healthy 가 되지 않으면**(서빙하는 색이 없다 — 마이그레이션은 커밋됐다): 0) 죽은 색이
재시작을 되풀이하지 않게 `$C stop api_<색>`. 1) `$C logs api_<색>` 로 원인을 본다. 이미지·설정만의 문제면 고친 태그로 다시 겹침 없는
교체를 한다(마이그레이션은 이미 적용돼 다시 돌지 않고, 가드는 전환 기록을 보고 뜬다) — 어느 쪽인지 멈추고 정한다. 2) 단위를
되돌려야 하면 `exec` 할 곳이 없으므로 일회성 컨테이너에서 위 런북 1·2 를 한다: `$C run --rm --no-deps -T api_<색> python
scripts/ops/revert_clover_unit.py`(건조) → `--apply`(`run` 은 uvicorn 이 아니라 이 명령만 돌려 기동 가드를 타지 않는다). 3) 곧바로 "빈
상태에서 첫 기동" 절의 4~5단계로 그 색을 전환 전 단위 태그로 띄운다 — 3단계 마이그레이션은 건너뛴다(DB 리비전이 그 이미지보다 앞서
`Can't locate revision` 으로 멈춘다). 4) 위 런북 4.

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
- **소설화 워커를 켜면** — DB 최악은 136 + 워커 하나 5 = 141(교체는 api 두 색이 겹치는 동안 워커를 하나만 둔다 — "BE → GCE VM"
  절의 워커 슬롯 비우기). 메모리 정점도 "api 두 색 + 워커 하나"다. 워커 하나를 약 250MiB 로 잡고 정점의 available 이 500MiB
  이상(메모리 알림 90% 선에 측정 변동 몫을 더한 선)이려면, 워커 0·api 한 색인 평소 `free -m` 의 available 이 그날 `docker stats`
  의 api 사용량 + 250 + 500 이상이어야 한다(api 964MiB 기준 **약 1,714MiB**). 스위치를 켜기 직전에 이 식으로 다시 계산하고
  미달이면 켜지 않는다.

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

sudo /opt/ddona/backup.sh --manual   # 먼저 백업 — backup/manual/ 에 올라가 일단위 보관 칸을 먹지 않는다

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
  - web은 여기에 `apps/api/src/api/content/builder_limits.json`을 더한다. 빌더 글자·개수 한도 표를 서버와 web 번들이
    함께 읽어서, 표만 고친 커밋에도 web이 다시 배포돼야 화면의 한도가 서버 검사와 같아진다. 이 값은 저장소 밖
    Pages 대시보드 설정이라 사람이 바꾼다.
- SPA fallback은 `apps/{web,admin}/public/_redirects`(`/* /index.html 200`)로 이미 되어 있다.
  단 Pages 자산 서버는 이 폴백을 없는 자산 파일(`/assets/옛-해시.js`)에도 200 HTML로 주고 확장자를 따라
  4시간 캐시시키므로, 자산 경로의 200 HTML은 Worker가 캐시 금지 404로 바꾼다 —
  web은 `apps/web/worker/handler.ts`의 `serveStaticAsset`, admin은 `apps/admin/public/_worker.js`.
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

**손으로 뜨는 백업은 반드시 `--manual` 을 붙인다.** 보관이 프리픽스별 갯수 기준이라, 붙이지 않고 뜨면
`backup/daily/` 에 하나가 더 쌓여 가장 오래된 일단위 사본이 지워진다 — 2026-10 에 하루 동안 마이그레이션 병합 전
수동 백업을 다섯 번 뜨자 10-17~10-20 일단위 사본이 밀려나 사라졌다. `--manual` 은 `backup/manual/` 에만 올리고 그 안에서 최신
5개만 남긴다(같은 파일명 패턴 검사로 지운다). `daily/`·`weekly/` 는 올리지도 정리하지도 않고, healthchecks.io
check-in 도 보내지 않는다 — 그 체크는 크론이 매일 돌았는지를 보므로 손으로 뜬 백업이 크론의 성공·실패처럼
찍히면 안 된다. 만료된 탈퇴 해시 파기와 R2 용량 경고는 크론과 똑같이 돈다.

```sh
sudo /opt/ddona/backup.sh --manual   # 수동 실행 → s3://ai-chracter-chat/backup/manual/<UTC 시각>.dump

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

R2에서 백업을 내려받으려면 `aws s3 cp s3://ai-chracter-chat/backup/<daily|weekly|manual>/<파일> .`
(`--endpoint-url`은 `S3_ENDPOINT_URL`). 마이그레이션 직전 상태로 되돌릴 때는 그 직전에 손으로 뜬 `manual/` 사본이
가장 가깝다 — 세 프리픽스를 `aws s3 ls` 로 보고 파일명(UTC 시각)으로 고른다. 어느 프리픽스에서 받았든 같은 `pg_dump -Fc`
파일이라 `restore_db` 는 내려받은 로컬 경로만 받고 절차도 같다.

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

이 확인만은 `--manual` 없이 돈다 — 크론과 같은 경로가 check-in 하는지 보는 것이 목적이라서다. 대가로 일단위 보관 칸을
하나 먹는다(가장 오래된 일단위 사본 하나가 지워진다).

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

**운영 Postgres 이미지 — 벡터 확장을 얹은 자체 이미지**. `docker-compose.prod.yml`의 postgres 는
`postgres:18-alpine`이 아니라 같은 베이스 위에 벡터 확장(pgvector)만 컴파일해 얹은
`ghcr.io/03hoho03/postgres-pgvector@sha256:…`(digest 고정, 값은 compose 파일)이다. musl 정렬·데이터 디렉터리 배치가
같아 기존 `pgdata` 볼륨을 그대로 받는다. VM 재구축·"빈 상태에서 첫 기동"의 `up -d --wait postgres redis`도 compose 파일의
이 이미지를 그대로 받으므로 따로 할 일은 없고, 2026-12 무렵 VM 사양·형상을 다시 판단할 때도 이 이미지가 기준이다.

- **이 이미지 줄(또는 postgres 설정)을 바꾸는 병합은 그 배포 중에 postgres 를 다시 만든다.** 교체 스크립트가 `--no-deps`
  없이 api 색을 띄우고 api 색이 postgres 에 `depends_on`이라, 설정이 달라진 postgres 가 함께 재생성된다(그동안 DB 가 잠깐 끊긴다).
- **새 이미지가 받아지지만 healthy 가 되지 않으면** 옛 postgres 컨테이너는 이미 지워진 뒤다. 배포는 postgres 헬스체크
  (5초 간격 20회)만큼 약 100초 기다리다 실패한다. 비상 복구는 원래 이미지 줄만 담은 override 파일을 얹어 postgres 만 되살리는 것이다
  (볼륨은 그대로라 데이터는 남아 있다).

  override 파일은 `/opt/ddona/pg-rollback.override.yml`이고 VM 에 이미 준비돼 있을 수 있다 — 있으면 내용만 확인하고,
  없으면 아래 `printf`로 만든다.

  ```sh
  cd /opt/ddona/app
  sudo cat /opt/ddona/pg-rollback.override.yml 2>/dev/null ||
    printf 'services:\n  postgres:\n    image: postgres:18-alpine\n' | sudo tee /opt/ddona/pg-rollback.override.yml
  sudo docker compose -f docker-compose.prod.yml -f /opt/ddona/pg-rollback.override.yml --env-file /opt/ddona/.env \
       up -d --no-deps --wait postgres
  ```

- **벡터 확장을 만든 뒤에는(`CREATE EXTENSION vector`) 원래 이미지로 되돌리면 그 타입을 읽지 못한다.** 되돌리기 전에 벡터
  칸과 확장을 먼저 내린다(마이그레이션 downgrade). 위 비상 복구는 확장을 아직 만들지 않은 상태에서만 그대로 쓴다.
- 백업 클라이언트(`apps/api/scripts/ops/pg.py`의 `postgres:18-alpine`)는 그대로 둔다 — `pg_dump`·`pg_restore` 는 확장 없이도
  벡터 칸을 덤프한다. 다만 **복원 대상 서버에는 확장이 있어야 하므로** 이 이미지로 뜬 postgres 에 복원한다.

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

**소설화 워커도 본다.** 교체 스크립트가 남긴 `/var/lib/ddona/novelize_worker` 가 `on` 일 때만(없거나 `off` 면 감시하지 않는다 —
크론은 `.env` 를 읽지 않는다) 두 워커 색 중 docker 헬스 상태가 healthy 이거나, 재시작한 적 없이 막 뜨는 중(starting, 재시작 0회)인 컨테이너가 하나라도 있는지
본다 — 교체가 새 워커를 막 띄운 헬스체크 유예 동안 크론이 겹쳐도 경고하지 않으려는 것이고, 재시작한 starting 은 유예 안에서 죽기를
되풀이하는 워커(크래시 루프)일 수 있어 정상으로 치지 않는다(경고에 색별 상태가 실리고, starting 인 색에만 재시작 횟수가 붙는다). 없으면 "새 소설화 작업이
60초 뒤 환불로 끝난다" 경고, 다시 생기거나 스위치를 끄면 복구 알림이다. 정지 중인 옛 워커도 내려갈 때까지 healthy 라 하나로 센다 —
새 워커 기동이 실패한 교체는 교체 스크립트의 알림이 먼저 간다. docker 를 못 읽으면 그 항목만 "상태를 읽지 못했다" 경고로 두고
메모리·디스크·ping 은 계속 간다(docker 데몬 문제가 "VM 이 죽었다" 로 보이지 않게). 지연은 크론 5분 + 헬스체크 30초다.

**알림은 상태가 바뀔 때만 간다** — 항목(메모리·디스크·소설화 워커)별로 정상→경고에 1회, 경고→정상에 "복구" 1회.
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
`PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.check_resources --state-file /var/lib/ddona/resource-check.state --worker-state-file /var/lib/ddona/novelize_worker`를 부른다 — `backup.sh`와
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

**Ops Agent 를 쓰지 않는다.** 2026-10-02 GCP OS 정책(Ops Agent 자동 설치 템플릿 배정)으로 VM 에 깔렸지만 VM 서비스 계정에
메트릭 쓰기 권한(`monitoring.timeSeries.create`)이 없어 수집기가 권한 거부 오류만 하루 수천 건(실측 약 8,600건) 쏟았다. 2026-10-24
정책 배정을 삭제하고 패키지를 제거했다(`apt-get remove`, 설정 파일은 남음). 배정 삭제만으로는 패키지·apt 소스가 남는다 — 그 apt
소스·키 파일은 `/root/osconfig-ops-agent-backup/` 로 옮겨 두었다. 감시는 이 절의 크론과 healthchecks.io 가 맡는다. VM 라벨
`goog-ops-agent-policy` 는 남아 있어, 같은 템플릿 배정이 다시 생기면 이 VM 에 붙는다.

다시 깔 때는 둘 중 하나다:
- 배정 재생성 — 지우기 전에 배정 정의를 `gcloud compute os-config os-policy-assignments describe` 로 저장해 두었다가(출력 전용
  최상위 키 `baseline`·`etag`·`name`·`revisionCreateTime`·`revisionId`·`rolloutState`·`uid` 를 뺀다)
  `gcloud compute os-config os-policy-assignments create <이름> --location=<존> --file=<저장한 YAML>` 로 만든다. 라벨이 붙어 있어
  OS Config 가 저장소·패키지를 스스로 다시 깐다.
- 손으로 — 백업 폴더의 apt 소스·키를 제자리로 되돌리고 `apt-get update && apt-get install google-cloud-ops-agent`.

어느 쪽이든 VM 서비스 계정에 메트릭·로그 쓰기 권한(Monitoring Metric Writer·Logs Writer)을 먼저 준다 — 없으면 같은 오류가 다시 쏟아진다.

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
한 줄씩 함께 남는다. 노벨·노벨 댓글 신고의 만료 증거(신고 시점 공개본·댓글 본문 사본)도 같은 방식으로
이 크론이 비운다(`apps/api/scripts/ops/purge_novel_report_evidence.py`).

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

미션(과 백필) 클로버는 지급일(KST) 자정 + 8일에
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
계정별 허용 토글. 셋 다 있어야 그 계정에 진입점(채팅 더보기 「소설로 보기」·「내 소설」 — 넓은 화면은 좌측 패널,
좁은 화면은 메뉴 드로어)과 소설 API 가
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
경계 제안과 문단 수정은 Gemini 체인을 읽는다. 등급 규칙은 그 체인 세트의 `novelize_rating` 채널(원작 종류마다 scope
`story`·`character` 한 행)에서, 원문 줄 화자 라벨은 소설 Gemini 체인 세트의 라벨 칸에서 읽는다 — 채팅 레인의 등급 규칙·라벨을
고쳐도 소설 글은 바뀌지 않으므로, 두 레인의 등급 규칙을 맞추려면 소설 탭에서도 고친다(게시·복원 응답과 게시 전 변경 조회가
갈림을 알리지만 막지는 않는다). 이 읽기를 옮긴 마이그레이션보다 앞선 이미지로 되돌린 동안에는 옛 코드가 채팅 Gemini 세트에서
읽으므로 소설 레인 등급 규칙을 고쳐도 반영되지 않고, 소설 레인 게시는 옛 검증에 막힌다. 스토리·캐릭터 레인 Gemini 세트에도 옛 소설 문안 행(`novelize_*`)이 남아 있다 — 옛 이미지로
되돌렸을 때 옛 코드가 읽는 값이라 새 코드는 읽지 않고, 어드민 채팅 탭에는 보이지 않으며, 채팅 레인을 저장·게시할 때 서버가
직전 게시본의 값을 그대로 복사한다.

**소설화 워커 켜기 · 끄기.** 워커 스위치(`NOVELIZE_WORKER_ENABLED`)를 켜면 api 는 연쇄(부모와 그 부모가 직접 돌리는 자식 — 워커는 자식 행을 집지 않는다)를 뺀 소설화 작업을 대기 행으로만
남기고, 워커 컨테이너가 그 행을 집어 돈다. 워커는 정지 신호를 받으면 돌던 작업을 끝까지 마치고 내려가므로 api 교체가 작업을
죽이지 않는다.

- 켜기 전: 진행 중 작업 0(아래 2단계 SQL), 한가한 시각, "겹침 대비 운영 설정" 절의 메모리 식을 그날 `free -m`·`docker stats` 로
  다시 계산해 충족. 처음 켜는 교체 한 번만은 새 api 합류부터 새 워커 healthy 까지(약 2분) 작업을 받을 워커가 없어 그 사이 60초를
  넘긴 작업이 환불될 수 있다.
- 켜기: `sudo sh -c 'printf "\nNOVELIZE_WORKER_ENABLED=true\n" >> /opt/ddona/.env'` → `sudo python3 ops/check_env.py --format /opt/ddona/.env`
  → `sudo bash ops/swap-api.sh`. 로그에 `12-1) worker_<색> 기동` 이 있고 `/var/lib/ddona/novelize_worker` 가 `on`, `sudo docker ps
  --filter label=com.docker.compose.service=worker_<색>` 이 healthy 인지 본다. 줄을 넣었으니 "BE 런타임" 절의 키 개수 문장을 다시 센다.
- 끄기: 스위치 줄을 지우고 형식 검사 → 태그 없는 교체. 로그 `12-1) 소설화 워커 꺼짐 … 떠 있던 워커 N개 분리 정지`. 떠 있던 워커는
  돌던 작업을 마친 뒤 내려간다(최대 420초) — 그동안 새 작업은 다시 api 안에서 돈다.
- 롤백: "BE → GCE VM" 절 "롤백"의 스위치 끄기 → 워커 비우기 → 태그 롤백 순서.

**진행 중 작업 0 확인 — 끄기 · 명단 회수 · 롤백의 첫 단계.** 셋 다 교체(`ops/swap-api.sh`)를 낀다. 워커 스위치가 꺼져 있으면 소설
작업은 api 프로세스 안에서 돌아서, 교체가 옛 색을 드레인하고 멈출 때(정지 유예 65초) 그 색에서 돌던 장 생성·문단 수정 작업이 죽어 진행 중으로
남고, 그 차감액은 만료 정리가 환불할 때까지 묶인다. 새 코드는 프로세스마다 기동 뒤 heartbeat 만료 + 10초(기본 70초)에 모든
소설의 죽은 작업을 한 번 환불하지만, 교체에서는 새 색이 옛 색의 드레인보다 **먼저** 뜨므로 드레인이 죽인 작업은 그 정리
시각에 아직 만료 전이라 놓칠 수 있다. **옛 이미지로 롤백하면 이 정리가 없고 스키마를 내리면 작업 행이 사라져 환불 근거가
없어진다.** 워커 스위치가 켜져 있으면 연쇄(부모와 그 부모가 직접 돌리는 자식 — 워커는 자식 행을 집지 않는다)를 뺀 작업은 워커에서 돌아 교체가 죽이지 않지만, 연쇄는 여전히 api 안에서
돌아 위와 같다. 그래서 먼저 비운다:

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
   `charged_amount` 를 기록으로 남긴다. 워커가 떠 있으면 이 재교체가 필요 없다 — 워커가 60초마다 모든 소설의 만료 작업을
   환불하므로(연쇄 부모 포함) 죽은 작업은 마지막 heartbeat 뒤 길어야 약 2분 안에 사용자 행동과 무관하게 환불된다.

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
sudo /opt/ddona/backup.sh --manual   # 먼저 백업
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
구조만 내릴 때」를 통과시키고, 상위 모델 리비전은 "상위 모델(채팅 Opus 직결) — 꺼진 채 배포 · 켜기 · 끄기" 절의 롤백 순서를 본 뒤에
내린다:

```sh
sudo /opt/ddona/backup.sh --manual   # 먼저 백업
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

**화 개정 블록 칸(`17f49714e5ca`·`211f81f33be5`) — 배포 · 되돌리기.** 화 개정에 문단마다의 블록 id(`block_ids`)와 본문
해시(`content_hash`) 칸을 두 리비전에 걸쳐 들였다. `17f49714e5ca` 가 두 칸을 NULL 허용으로 더하고 같은 마이그레이션에서 지금
있는 개정을 채웠고, `211f81f33be5` 가 첫머리에서 남은 빈 개정을 채운 뒤(문단마다 새 id) 두 칸을 NOT NULL 로 좁힌다. 스위치는
없다 — 바뀌는 운영 동작은 소유자 화·개정 응답의 `blocks` 칸과 직접 수정 요청의 선택 칸 `blockIds` 뿐이다. 둘 다 평상시 겹침
교체로 배포한다(`skip_overlap` 불필요): `17f49714e5ca` 의 겹침에서는 칸을 모르는 옛 이미지가 NULL 로 쓰고(NULL 허용), `211f81f33be5`
의 겹침에서 도는 옛 이미지(`17f49714e5ca` 를 아는 이미지)는 개정을 언제나 두 칸을 채워 쓴다.

🔴 **삽화 스키마(`b871b88d2a90`) 이후의 경계**: 이 단락의 NOT NULL 해제·`8f93cc8` 태그 롤백·스키마 내리기는 **DB 가 `211f81f33be5`
이고(아래 삽화 스키마 단락 ③ 까지 내린 뒤) 서빙 이미지가 삽화 스키마를 모르는 이미지(`7d4d5bf` 이하)일 때만** 쓴다. DB 가 그보다
위에 있는 채 `alembic downgrade 17f49714e5ca` 를 돌리면 삽화·자산 sha·구간 선택 리비전까지 한꺼번에 내리고, 그 표·칸을 읽는 서빙
이미지가 깨진다. 이미지만 `d0fd0ac`·`5bd30c8` 로 되돌리는 것은 그 위 스키마 단락들(삽화·자산 sha·구간 선택)의 이미지 되돌리기 판정을
지킨 채 지금 스키마 위에서 해도 된다 — 그 이미지들은 두 블록 칸을 채워 쓰고, 새 표·칸을 모른 채 돈다.

- **`211f81f33be5` 병합 전**: 운영 최신 백업이 성공했는지 본다 — 크론이 매일 18:00 UTC 에 돈다(위 「백업 · 복원」).
  `sudo tail -n 40 /var/log/ddona-backup.log` 의 마지막 실행에 업로드·순환 삭제 성공이 있고 실패·오류 줄이 없어야 한다. 남은
  빈 개정 수도 본다(0 이 정상 — 아니어도 마이그레이션이 채운다). 배포 로그에 `블록 칸이 빈 개정 N행을 채웠다` 가 찍힌다.

```sh
sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
  psql -U postgres -d ai_character_chat -At -c \
  "SELECT count(*) FROM novel_chapter_revisions WHERE block_ids IS NULL OR content_hash IS NULL;"
```

- **이미지만 `17f49714e5ca` 이상 이미지로 되돌릴 때**: 그 이미지는 두 칸을 채워 쓰므로 NOT NULL 스키마에서 그대로 돈다.
  downgrade 하지 않는다(DB 가 이미지보다 앞서 있으니 롤백 표시로 마이그레이션을 건너뛴다 — 위 「BE → GCE VM」).
- **`17f49714e5ca` 이전 이미지(두 칸을 모르는 이미지)로 되돌릴 때**: 순서가 고정이다 — 먼저 **지금 이미지로**
  `211f81f33be5` 를 downgrade(NOT NULL 해제)하고, 그다음 태그 롤백으로 옛 이미지를 띄운다. 거꾸로 하면 옛 이미지의 개정
  INSERT(생성·다시 만들기·직접 수정·되돌리기·AI 수정 적용·스냅숏 복원)가 NOT NULL 위반으로 500 이다. NOT NULL 해제는 칸·값을
  남기므로 떠 있는 새 코드가 그대로 돈다. 그 뒤 옛 이미지가 쓰는 개정은 두 칸이 NULL 이고, 새 이미지를 다시 올리면
  `211f81f33be5` 가 다시 돌며 채운다.
- **되돌릴 옛 이미지 태그는 `8f93cc8`** 이다(`17f49714e5ca` 이전 마지막 api 이미지, 리비전 `f89a3d8ed3a8`). 그 바로 뒤
  병합 `79672b7` 은 `apps/admin` 만 바꿔 deploy-api 가 돌지 않았으므로 **이미지가 없다** — `swap-api.sh` 는 pull 에서, Actions
  수동 실행은 태그 확인 단계에서 멈춘다. 태그는 deploy-api 가 돈 병합에만 있다(`gh run list --workflow deploy-api.yml` 로 확인).
- **태그 롤백은 `5bd30c8` 을 거쳐 두 번에 한다.** `211f81f33be5` 를 아는 이미지는 NULL 블록 칸을 읽지 못하므로, 거기서 바로
  `8f93cc8` 로 바꾸면 겹침(최대 약 100초) 동안 옛 이미지가 NULL 로 쓴 개정을 아직 떠 있는 새 이미지가 읽다 500 이다.
  `5bd30c8` 은 `17f49714e5ca` 를 알고 NULL 칸을 `blocks: null` 로 다룬다. 다시 올릴 때도 같은 이유로 두 번이다 — `8f93cc8` 에서
  바로 최신으로 가면 `211f81f33be5` 가 NOT NULL 을 건 뒤 겹침 동안 `8f93cc8` 의 개정 INSERT 가 NOT NULL 위반이다. 겹침을
  끄는 대안은 `SKIP_OVERLAP=true`(대신 최대 65초 + 기동 시간 끊김).
- 🔴 **되돌려 둔 동안 `main` 병합을 멈춘다**(배포 경로를 건드리는 PR). 병합되면 자동 배포가 한 번에 최신으로 교체해 위의
  겹침 실패를 그대로 겪는다.

```sh
# 1) 지금 이미지로 NOT NULL 해제
sudo docker run --rm --network ddona_default --env-file /opt/ddona/.env \
  <IMAGE>:<지금 TAG> alembic downgrade 17f49714e5ca
# 2) 태그 롤백 두 번 — 각 교체 로그 끝 줄 `13) 완료` 를 보고 다음으로
cd /opt/ddona/app
sudo DDONA_ROLLBACK=1 bash ops/swap-api.sh 5bd30c8
sudo DDONA_ROLLBACK=1 bash ops/swap-api.sh 8f93cc8
#    (겹침 끄는 대안: sudo SKIP_OVERLAP=true DDONA_ROLLBACK=1 bash ops/swap-api.sh 8f93cc8)
# 다시 올리기 — 먼저 5bd30c8(DB 를 아는 이미지라 표시 불필요, 마이그레이션 없음),
sudo bash ops/swap-api.sh 5bd30c8
# 그다음 Actions → deploy-api → Run workflow(image_tag 비움 = main 최신) 또는 다음 main push.
# 배포 로그의 `블록 칸이 빈 개정 N행을 채웠다` 의 N 이 되돌려 둔 동안 생긴 개정 수(위 빈 개정 수 쿼리)와 같아야 한다.
```

- **스키마까지 내릴 때**(`alembic downgrade f89a3d8ed3a8`): 두 칸을 지운다. 블록 id 가 사라지고, 다시 올리면 백필이 다른 새 id
  로 채운다 — 블록 id 를 가리키는 다른 표가 생긴 뒤라면 그 참조가 끊긴다. 위 「스키마까지 되돌릴 때」의 순서(옛 코드 먼저 → 새
  이미지로 downgrade)를 따른다. 이 목표는 `211f81f33be5` 도 함께 내린다.

**소설 화 삽화 스키마(`b871b88d2a90`) — 배포 · 되돌리기.** 화 개정마다의 삽화 배치 표(`novel_chapter_illustrations`, 개정 FK
`ON DELETE CASCADE`·그림 FK 지우기 거부), 개정 출처 CHECK 의 `illustration`, 심사 거부 자리 CHECK 의 `illustration`, 화 공개본·판의
`illustrations_screened_at`(NULL 허용), 삽화 심사 통과 기억 표·내림 기록 표를 한 리비전에 더한다. 스위치(`NOVEL_ILLUSTRATIONS_ENABLED`,
위 env 표)가 꺼진 채 배포하면 운영 동작이 바뀌지 않는다 — 배치 API 는 404, 응답에 그림이 없고, 배치 행·`illustration` 개정이 생기지
않는다. 평상시 겹침 교체로 배포한다(`skip_overlap` 불필요): 겹침 동안 도는 옛 이미지(`7a96144b`)는 새 표·칸을 모르고, 넓힌 CHECK 는
옛 값을 그대로 받고, 공개본·판 INSERT 는 새 칸을 NULL 로 남기며, 개정을 지우는 옛 경로(소설·묶음 삭제·탈퇴)는 배치를 CASCADE 로 함께
지운다(공개본·판 INSERT 와 개정 DELETE 는 `tests/test_novel_illustrations_migration.py` 가 옛 코드 꼴의 원시 SQL 로 확인한다).

- **병합 전**: 위 블록 칸 단락과 같이 운영 최신 백업 성공을 본다.
- **되돌리기 순서**: ① 스위치 줄을 지운다(`sudo sed -i '/^NOVEL_ILLUSTRATIONS_ENABLED=/d' /opt/ddona/.env` → `check_env.py --format`
  → api 재생성). 배치 API 가 404 가 되고 응답에서 그림이 빠진다 — 이미 붙은 배치는 DB 에 남고 다시 켜면 다시 보인다. ② 이미지를
  이 리비전 이전(`7a96144b`)으로 되돌리기 전에 아래 행 수를 본다. **`illustration` 개정이 하나라도 있으면 이미지 롤백 금지·앞으로
  고치기** — 옛 이미지의 화·개정·소설 상세 응답은 개정 출처 Literal 에 `illustration` 이 없어 그 화를 읽는 순간 500 이다. 0 이면
  (배치는 `illustration` 개정으로만 처음 생기므로 배치도 0 이다) 이미지만 되돌려도 된다(downgrade 없이 — 옛 코드는 이 스키마에서
  돈다). ③ 스키마까지 내려야 하면(`alembic downgrade 211f81f33be5`) **지금 DB 리비전까지의 파일이 모두 든 이미지**로 돌린다 —
  DB 가 `c4e1a7d93b20` 이면 `api:e3477e1` 이상(예: `api:1db9683`), 그 위 리비전이 올라가 있으면 그 리비전을 들인 이미지 이상이다(그 리비전의 downgrade 도 함께 돌아 그 단락의 막는 행에서 멈출 수 있다).
  ② 에서 이미 `7a96144b` 로 되돌린 서빙 이미지에는 이 파일들이 없어 `Can't locate revision` 으로 멈춘다(아무것도 바꾸지 않는
  실패). 막는 행(배치·`illustration` 개정·거부 기록·심사 시각·통과 기억·내림 기록)이 하나라도 있으면 downgrade 가 일부러 멈춘다. 0 일 때만
  [downgrade → revert 병합] 한 짝으로 하고, 겹침 중 `main` 병합을 멈춘다.

```sh
sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
  psql -U postgres -d ai_character_chat -At -c \
  "SELECT (SELECT count(*) FROM novel_chapter_revisions WHERE source = 'illustration'),
          (SELECT count(*) FROM novel_chapter_illustrations),
          (SELECT count(*) FROM novel_screenings WHERE 'illustration' = ANY(flagged_parts));"
```

**자산 그림 바이트 sha 칸(`c4e1a7d93b20`) — 배포 · 되돌리기.** `assets.display_sha256`(TEXT NULL)을 더한다. 소설 삽화의 공개
심사와 운영자 그림 내림이 그림을 내려받을 때 채우고, 노벨·어드민·작가 화 읽기가 이 값으로 내림 기록을 이어 같은 파일을 담은 다른
자산도 내린 그림으로 비운다. 채워 넣을 과거 값은 없다. 평상시 겹침 교체로 배포한다(`skip_overlap` 불필요): 겹침 동안 도는 옛
이미지(`1bded8ff`)는 이 칸을 매핑하지 않아 SELECT·INSERT 에 싣지 않고(새 자산 행은 NULL), 그 구간의 옛 공개 심사·내림이 칸을 채우지
않을 뿐이다 — 내린 그 자산은 옛·새 읽기 모두 자산 id 로 비운다. 스위치가 꺼진 동안에는 공개 심사가 그림을 내려받지 않아 칸이 채워지지
않는다(내림만 채운다).

- **병합 전**: 운영 최신 백업 성공을 본다.
- **되돌리기**: 이미지만 `1bded8ff` 로 되돌려도 된다(downgrade 없이 — 옛 코드는 이 칸을 모른 채 돈다). 그동안 읽기는 내림 기록의
  자산 id 로만 보므로, 같은 파일의 다른 자산(내림 응답 `alreadyTakenDown` 참으로 처리한 것)은 독자에게 다시 보인다 — 그런 내림이
  있었으면 그 자산을 담은 노벨을 이용제한으로 닫는다. 스키마까지 내리려면(`alembic downgrade b871b88d2a90`) 칸을 지울 뿐이고 막는
  행이 없다. [downgrade → revert 병합] 한 짝으로 하고 겹침 중 `main` 병합을 멈춘다(새 이미지가 칸 없는 스키마에서 돌면 자산 조회가
  깨진다).

**어드민 옛 판 읽기 · 노벨 신고 '삽화 내림으로 처리 완료' — 배포 · 되돌리기.** 마이그레이션 없음. 어드민 화 읽기의 `edition` 쿼리와
응답의 판 목록(`editions`)은 기존 판 행(`novel_chapter_editions`)만 읽고, 신고 처리 방법 `illustration_takedown` 은 신고 상태
`resolved` 를 다시 쓰며(native enum 변경 없음) 감사 로그에 새 값 `novel-report-illustration-takedown` 을 남긴다
(`admin_action_logs.action_type` 은 CHECK 없는 Text). 어드민 라우트만 넓어지므로 두 스위치(`NOVEL_PUBLIC_POLICY_V2_ENABLED`·
`NOVEL_ILLUSTRATIONS_ENABLED`)가 꺼진 채 배포해도 회원 화면은 바뀌지 않는다. 평상시 겹침 교체로 배포한다.

- **겹침**: 옛 이미지는 새 처리 방법을 422 로 거절하고 `edition` 쿼리를 무시해 지금 판을 준다 — 어드민 화면은 요청한 판이 아니라
  응답의 `edition` 으로 어느 판을 보는지 판단한다(그래서 이 처리 방법·판 고르기를 쓰는 admin 화면은 이 API 배포를 확인한 뒤에
  낸다). 새 감사 값 행이 겹침 동안 생기면 옛 이미지가 그 게시자의 회원 상세(`GET /admin/users/{id}`)를 그릴 때 조치 이력의 응답
  검증에서 500 이고, 겹침이 끝나면 풀린다.
- **되돌리기(이 처리 방법이 생기기 전 이미지로)**: 먼저 아래 SELECT 로 새 감사 값 행 수와 걸린 게시자 수를 본다. **0 이면** 이미지만
  되돌려도 된다. **1 이상이면** 옛 이미지에서 그 게시자들의 회원 상세가 계속 500 이다 — 감사 기록이라 행을 지우지 말고, 이미지
  되돌리기를 미루고 앞으로 고치는 쪽을 택한다. 꼭 되돌려야 하면 그 게시자 수만큼 회원 상세가 열리지 않는 것을 감수하고, 다시
  올리면 풀린다.

```sh
sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
  psql -U postgres -d ai_character_chat -At -c \
  "SELECT count(*), count(DISTINCT target_user_id) FROM admin_action_logs
     WHERE action_type = 'novel-report-illustration-takedown';"
```

**잘못 내린 삽화 되돌리기 — 운영 DB 수동 쓰기(사용자 승인 필요).** 내림을 푸는 라우트는 없다. 내림은 `novel_illustration_takedowns`
의 행 하나(키 = 그림 바이트의 sha256 `content_sha256`, 내린 자산 사본 `asset_id`, 독자에게 보인 사유 `reason`, `created_at`)이고,
읽기는 자산 행의 `assets.display_sha256` 또는 자산 id 로 이 표를 이어 그림 자리를 비운다. 그래서 그 행을 지우면 같은 바이트를 담은
**모든 자산·모든 노벨·모든 판**에서 함께 풀린다 — 한 노벨만 풀 수는 없다. 아래 쓰기는 운영 데이터를 바꾸는 수동 작업이므로 사용자
승인을 받은 뒤에만 한다. 앞뒤 확인은 모두 읽기 전용이다.

1. **풀 행 찾기(읽기)**: 잘못 내린 자산 id(어드민 화 읽기 응답의 `assetId`, 내림 응답의 `assetId`)로 그 자산을 비우는 내림 행을 모두
   찾는다. 보통 한 행이고, 두 행이면(자산 id 로 내린 행과 같은 바이트를 다른 자산으로 내린 행) 둘 다 지워야 풀린다.

   ```sh
   sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
     psql -U postgres -d ai_character_chat -At -c \
     "SELECT content_sha256, asset_id, created_at FROM novel_illustration_takedowns
        WHERE asset_id = '<자산 id>'
           OR content_sha256 = (SELECT display_sha256 FROM assets WHERE id = '<자산 id>');"
   ```

2. **함께 풀리는 자산 보기(읽기)**: 1 에서 나온 sha 마다 그 바이트를 담은 자산을 본다 — 이 자산들이 쓰인 모든 화에서 그림이 다시
   보인다. 다른 회원의 자산이 섞여 있으면 그것도 함께 풀리는 것이 맞는지 판단한다.

   ```sh
   sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
     psql -U postgres -d ai_character_chat -At -c \
     "SELECT a.id, a.owner_user_id FROM assets a JOIN novel_illustration_takedowns t
        ON t.content_sha256 = a.display_sha256 OR t.asset_id = a.id
        WHERE t.content_sha256 = '<1 에서 본 sha>';"
   ```

3. **지우기(쓰기, 승인 뒤)**: 지울 표는 `novel_illustration_takedowns` 하나뿐이다(다른 표가 이 행을 FK 로 가리키지 않는다). 1 에서
   본 sha 마다 아래를 한 번씩 돌린다. `DO` 블록은 한 트랜잭션이라 지운 행 수가 1 이 아니면 예외로 통째로 되돌아간다(sha 를 잘못
   옮겨 적었으면 아무것도 지우지 않고 멈춘다).

   ```sh
   sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
     psql -U postgres -d ai_character_chat -v ON_ERROR_STOP=1 -c \
     "DO \$\$ DECLARE n int; BEGIN
        DELETE FROM novel_illustration_takedowns WHERE content_sha256 = '<1 에서 본 sha>';
        GET DIAGNOSTICS n = ROW_COUNT;
        IF n <> 1 THEN RAISE EXCEPTION 'deleted % rows, rolled back', n; END IF;
      END \$\$;"
   ```

4. **확인(읽기)**: 1 의 SELECT 가 빈 결과인지 본다. 어드민 화 읽기에서 그 자리의 `withheld` 가 비고 주소가 실리는지 본다(응답
   캐시는 없다).

지우지 않는 것: 감사 로그(`novel-illustration-takedown`·`novel-report-illustration-takedown` 행 — 내렸다가 풀었다는 사실이 감사
기록이다, 푼 사실은 운영 기록에 따로 적는다), `assets.display_sha256`(그림 바이트의 사실일 뿐 내림 여부가 아니다), 그 그림으로
'삽화 내림으로 처리 완료'한 신고(처리완료로 남는다 — 다시 판단하려면 어드민에서 다시 처리한다).

**통과 기억**: 내릴 때 그 바이트의 삽화 심사 통과 기억(`novel_illustration_screen_passes` 의 그 `content_sha256` 행 전부)을 지웠고,
되돌려도 되살아나지 않는다. 그래서 이미 공개된 판은 판의 심사 시각이 그대로라 다시 심사 없이 바로 그림을 보이지만, 그 그림이 든
화를 작가가 **다시 공개하면 그 바이트를 처음처럼 다시 심사한다**(심사 호출 1회, 이번에는 거부될 수도 있다). 통과 기억 행을 손으로
넣지 않는다 — 모델·심사 문안 판 키를 손으로 맞추면 심사 없이 통과시키는 것과 같다.

**대화 구간 선택 스키마(`7738b72179c8`) — 배포 · 되돌리기.** 소설로 옮길 대화 구간을 사용자가 고른 기록을 담는 표 둘을 더한다 —
`novel_source_selections`(구간 선택 한 판: 소설마다 오르는 리비전·고를 때 본 방의 마지막 메시지 키·승인 시각, 소설 FK
`ON DELETE CASCADE`)와 `novel_source_sections`(그 판의 구간: 소설에 넣을 `include`·맥락으로만 보낼 `context`, 양 끝 메시지 키·AI 응답
수·원문 해시, 선택 FK `ON DELETE CASCADE`). 메시지 키에는 FK 가 없고 원문 사본도 없다. 같은 배포에서 소설화 코드가 방 원문을 읽는
곳을 하나(`api/novelize/source.py`)로 모았다 — 옛 흐름(경계 제안·묶음 생성·연쇄·다시 만들기)은 옮기기 전과 같은 메시지를 읽는다.
스위치(`NOVELIZE_OUTLINE_FLOW_ENABLED`, 위 env 표)는 꺼진 채 배포하고, 이 배포에는 두 표에 행을 쓰는 코드가 없다. 행을 쓰는 것은 그다음 배포의 구간 선택 라우트이고 스위치를 켠 뒤에만 열린다 — 그 뒤로는 아래 downgrade 멈춤과 위 삽화 단락 ③ 의 멈춤이 실제로 걸릴 수 있으니 행 수를 먼저 센다. 평상시 겹침 교체로
배포한다(`skip_overlap` 불필요): 겹침 동안 도는 옛 이미지(이 리비전이 배포되기 직전의 운영 이미지 — 작성 시점 `99598cf`)는 두 표를 모르고, 소설을 지우는 옛 경로(소설 삭제·탈퇴)는 소설
행을 지울 때 두 표를 CASCADE 로 함께 지우며(`tests/test_novel_source_selection_migration.py` 가 옛 코드 꼴의 원시 DELETE 로 확인한다),
메시지를 지우는 경로(방 삭제·되감기·응답 지우기)는 FK 가 없어 막히지 않는다.

- **병합 전**: 운영 최신 백업 성공을 본다.
- **되돌리기**: 이미지만 이 리비전이 배포되기 직전의 운영 이미지(작성 시점 `99598cf` — 병합 전에 `gh run list --workflow deploy-api.yml` 로
  다시 본다)로 되돌려도 된다(downgrade 없이 — 옛 코드는 두 표가 있어도 돈다). 되돌려 둔 동안 판매돼 숨겨
  남긴 소설의 작가가 탈퇴하면 옛 이미지의 작가 전용 데이터 정리가 이 표를 몰라 그 소설의 구간 선택이 남는다(소설 행이 남아 CASCADE
  도 걸리지 않는다) — 다시 올린 뒤 숨긴 소설 파기 크론("숨긴 소설 파기" 절)이 다음 실행에서 지운다. 스키마까지 내리려면(`alembic
  downgrade c4e1a7d93b20`, 이 리비전 파일이 든 이미지로) 구간 선택 행이 하나라도 있으면 downgrade 가 일부러 멈춘다 — 사용자가 고른
  구간이라 지우지 않는다. 0 일 때만 [downgrade → revert 병합] 한 짝으로 하고 겹침 중 `main` 병합을 멈춘다.

```sh
sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
  psql -U postgres -d ai_character_chat -At -c \
  "SELECT (SELECT count(*) FROM novel_source_selections), (SELECT count(*) FROM novel_source_sections);"
```

**구성안 스키마(`1962604b5292`)·구성안 문안(`b389c2317149`) — 배포 · 되돌리기.** 한 배포에 두 리비전이 함께 오른다.
- `1962604b5292`(스키마): 작업 종류 CHECK(`ck_novel_jobs_kind`)를 구성 흐름 셋(`outline_generate`·`episode_outline_generate`·
  `outline_chapter_generate`)을 더한 목록으로 바꾸고(넓히기만), `novel_jobs` 에 대상 칸 셋과 그 칸을 새 종류에만 요구하는 CHECK,
  `novel_chapters.episode_outline_id`(FK 없음)를 더하고, 표 `novel_outlines`·`novel_episode_outlines`·`novel_scene_blocks`(소설·화·구성안 FK
  `ON DELETE CASCADE`)를 만든다. 이 배포에는 새 종류 작업·구성안 행을 쓰는 코드가 없다(구성안·원고 라우트는 다음 배포, 스위치 뒤).
- `b389c2317149`(문안): 소설 레인 세 체인(gemini·sonnet·opus)마다 **그 체인 활성 세트의 바이트 사본**에 구성안 두 채널(각 9행)과
  화 생성의 conditional 두 행(장면 계획·연속성 참고)을 더한 새 게시 세트를 넣는다. 운영자가 어드민에서 고친 문안은 그대로 옮겨진다.
  옛 흐름 렌더는 바이트 그대로다(새 채널은 읽는 코드가 없고, 새 슬롯은 값을 넘기지 않아 섹션째 빠진다). 가정이 어긋나면(체인 활성
  세트 없음·화 생성 행 없음·새 행이 이미 있음) `RuntimeError` 로 배포가 멈춘다 — 데이터는 한 트랜잭션이라 그대로다.

평상시 겹침 교체로 배포한다(`skip_overlap` 불필요): 겹침 동안 도는 옛 이미지는 새 칸·표·채널을 모르고, 옛 작업·화 INSERT 는 새 칸을
비워 두며(옛 값은 넓힌 CHECK 를 통과한다), 옛 소설 삭제·탈퇴·마지막 묶음 삭제는 새 표를 CASCADE 로 함께 지운다
(`tests/test_novel_outline_schema_migration.py` 가 옛 코드 꼴의 원시 DELETE 로 확인한다). 옛 이미지의 어드민은 새 세트·초안의 새 행을
"잉여"로 보고 **소설 레인 게시만** 막는다 — 배포 뒤 열어 둔 어드민 소설 탭은 새로고침한다.

- **병합 전**(downgrade 뒤 다시 올릴 때도 같다): 운영 최신 백업 성공을 보고, 아래 첫 읽기 전용 SELECT 로 마이그레이션의 가정 검사를
  사람이 먼저 본다 — 체인마다 활성 세트가 하나씩(세 줄, 게시 시각이 미래 아님), 그 세트에 화 생성(`novelize_chapter`) 행이 있고 새 슬롯
  (`scene_plan`·`continuity_context`) 행과 새 채널 줄이 없음, 소설 레인 초안(있으면 제자리에서 채운다)과 채널별 행 수, 이 리비전의 세트 id 가
  아직 없음(0), 소설 레인 어디에도 새 채널 행이 없음(0). 문안 본문은 출력하지 않는다. 운영 `LLM_CALL_SITE_BACKENDS` 에 새 호출 위치
  이름(`novelize_outline`·`novelize_episode_outline`)을 적지 않는다 — 두
  호출은 장 생성의 배정을 물려받고, 그 이름을 모르는 옛 이미지는 그 줄이 있으면 기동하지 못한다.
- **되돌리기**: 1순위는 이미지만 이 배포 직전의 운영 이미지로 되돌리기다(downgrade 없이 — 옛 코드는 새 스키마·문안 위에서 돈다).
  판정: 진행 중인 구성 흐름 작업 0(아래 SELECT, 이 배포만으로는 늘 0). 되돌려 둔 동안 판매돼 숨긴 소설의 작가가 탈퇴하면 옛 이미지의
  작가 전용 데이터 정리가 구성안 표를 몰라 그 소설의 구성안이 남는다 — 다시 올린 뒤 그 행 수를 세어 정리한다. 스키마·문안까지
  내리려면 **이 두 리비전 파일이 든 이미지로** `alembic downgrade 7738b72179c8` 를 돌린다 — 문안 downgrade 는 시드 뒤 어드민이 소설 레인에
  새로 게시했으면 멈추고(무엇을 버릴지 사람이 정한다), 스키마 downgrade 는 구성 흐름 작업·구성안 행이 하나라도 있으면 멈춘다(값을 치른
  산출물이라 지우지 않는다). 둘 다 통과할 때만 [downgrade → revert 병합] 한 짝으로 하고 겹침 중 `main` 병합을 멈춘다. 문안 시드를 손으로
  지우지 않는다.

```sh
# 병합 전(읽기 전용): 활성 세트 · 활성 세트의 채널별 행 수와 새 슬롯 행 수 · 초안과 채널별 행 수 · 이 리비전의 세트 id 수 · 새 채널 행 수
sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
  psql -U postgres -d ai_character_chat -At \
  -c "SELECT DISTINCT ON (model) model, id, published_at, published_at > now() AS in_future FROM prompt_sets
        WHERE lane = 'novel' AND status = 'published' ORDER BY model, published_at DESC;" \
  -c "WITH active AS (SELECT DISTINCT ON (model) model, id FROM prompt_sets
                        WHERE lane = 'novel' AND status = 'published' ORDER BY model, published_at DESC)
      SELECT a.model, s.channel, count(*),
             count(*) FILTER (WHERE s.channel = 'novelize_chapter' AND s.slot IN ('scene_plan','continuity_context'))
        FROM active a JOIN prompt_sections s ON s.prompt_set_id = a.id GROUP BY 1, 2 ORDER BY 1, 2;" \
  -c "SELECT p.model, p.id, s.channel, count(*) FROM prompt_sets p JOIN prompt_sections s ON s.prompt_set_id = p.id
        WHERE p.lane = 'novel' AND p.status = 'draft' GROUP BY 1, 2, 3 ORDER BY 1, 3;" \
  -c "SELECT count(*) FROM prompt_sets WHERE id IN ('d9c50097-446d-4eef-9d20-61fe07c24825',
        '8c828e43-b3f0-4864-a635-0d9a32d96f86', '9ab6d10e-2964-4f0b-8be5-7c4a83e6ab89');" \
  -c "SELECT count(*) FROM prompt_sections s JOIN prompt_sets p ON p.id = s.prompt_set_id
        WHERE p.lane = 'novel' AND s.channel IN ('novelize_outline','novelize_episode_outline');"
# 되돌리기 판정: 구성 흐름 작업 수, 그중 진행 중, 구성안·화 구성안·장면 블록 행 수
sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
  psql -U postgres -d ai_character_chat -At -c \
  "SELECT (SELECT count(*) FROM novel_jobs WHERE kind IN ('outline_generate','episode_outline_generate','outline_chapter_generate')),
          (SELECT count(*) FROM novel_jobs WHERE kind IN ('outline_generate','episode_outline_generate','outline_chapter_generate')
             AND status IN ('queued','running')),
          (SELECT count(*) FROM novel_outlines), (SELECT count(*) FROM novel_episode_outlines),
          (SELECT count(*) FROM novel_scene_blocks);"
```


**여러 문단 수정 스키마(`a8708e3535d5`)·여러 문단 수정 문안(`174f78b92e5c`) — 배포 · 되돌리기.** 한 배포에 두 리비전이 함께 오른다.
- `a8708e3535d5`(스키마): `novel_jobs.block_edit`(JSONB, NULL 허용)과 CHECK `ck_novel_jobs_block_edit`(칸이 있으면 AI 수정이고 범위·장 전체
  결과 본문이 비어 있다)를 더한다. 칸에는 대상 블록(id·기준 해시·문단 번호)·장면·블록마다의 수정안·묶음이 담긴다.
- `174f78b92e5c`(문안): 소설 레인 **Gemini 체인만** 그 체인 활성 세트의 바이트 사본에 여러 문단 수정 채널(`novelize_revise_blocks`, 6행)과
  묶음 재검사 채널(`novelize_revise_recheck`, 4행)을 더한 새 게시 세트를 넣는다. Claude 두 체인은 그대로다. 옛 문단 수정 채널
  (`novelize_revise`)은 한 글자도 바뀌지 않아 옛 렌더는 바이트 그대로다. 가정이 어긋나면(활성 세트 없음·옛 문단 수정 행 없음·새 채널 행이
  이미 있음) `RuntimeError` 로 배포가 멈춘다.
- 스위치(`NOVELIZE_MULTI_BLOCK_EDIT_ENABLED`, 위 env 표)는 꺼진 채 배포한다 — 이 배포로 칸을 쓰는 코드는 스위치 뒤의 요청 라우트뿐이라
  꺼진 동안 칸은 늘 비어 있다.

평상시 겹침 교체로 배포한다(`skip_overlap` 불필요): 겹침 동안 도는 옛 이미지는 칸을 매핑하지 않고, 옛 작업 INSERT 는 칸을 비워 두며 CHECK 는
칸이 있는 행에만 걸린다. 옛 이미지가 칸이 있는 행을 만나도(스위치를 켠 뒤 이미지만 되돌린 경우) 상세의 미적용 목록과 낡은 미리보기 비우기는
결과 본문이 있는 행만 보아 지나치고, 옛 적용은 범위가 비어 409, 옛 버리기는 CHECK 를 통과한다(`tests/test_novel_block_edit_schema_migration.py`).
옛 이미지의 어드민은 새 세트·초안의 새 행을 "잉여"로 보고 **소설 레인 Gemini 체인 게시만** 막는다 — 배포 뒤 열어 둔 어드민 소설 탭은
새로고침한다.

- **병합 전**: 운영 최신 백업 성공을 보고, 소설 레인 Gemini 활성 세트(id·게시 시각)와 새 채널 행·초안이 아직 없음을 아래 읽기 전용
  SELECT 로 본다(새 채널 행 0, 초안이 있으면 새 채널 행이 빠진 채라 마이그레이션이 제자리에서 채운다). 운영 `LLM_CALL_SITE_BACKENDS` 는
  건드리지 않는다 — 여러 문단 수정은 옛 문단 수정과 같은 호출 위치(`novelize_revise`, Gemini 고정)를 쓴다.
- **되돌리기**: 1순위는 이미지만 이 배포 직전의 운영 이미지로 되돌리기다(downgrade 없이 — 옛 코드는 새 칸·문안 위에서 돈다). 스위치를 켠
  뒤라면 먼저 스위치 줄을 지우고(재기동), 진행 중인 여러 문단 수정 작업이 끝나기(또는 만료 환불)를 기다린 뒤 아래 SELECT 의 둘째·셋째
  값을 본다 — 대기 수정안이 남은 행이 있으면 옛 이미지에서는 그 수정안이 화면에서 사라지고 화를 지워도 문단이 행에 남으므로, 되돌리기 전에
  그 행을 "전부 버림"으로 정리한다(버린 시각을 찍고 지시문을 비우며 칸의 수정안 문단을 지운다 — 어떤 UPDATE 로 할지는 그때 행 수를 보고
  사람이 정한다). 스키마·문안까지 내리려면 **이미지를 먼저 되돌린 뒤**(칸을 지우는 순간 이 칸을 매핑한 새 이미지의 작업 조회가 모두 실패한다)
  이 두 리비전 파일이 든 이미지의 **일회성 컨테이너로** `alembic downgrade b389c2317149` 를 돌린다 — 문안 downgrade 가 먼저 돌며 시드 뒤
  어드민이 소설 레인 Gemini 체인에 새로 게시했으면 멈추고, 스키마 downgrade 는 대기 수정안이 남은 행이나 진행 중인 여러 문단 수정 작업이
  있으면 멈춘다(끝난 수정안 기록 — 상태·블록 id 만 남은 행 — 은 칸과 함께 버린다). 둘 다 통과할 때만 [이미지 롤백 → downgrade → revert
  병합] 순서로 하고 겹침 중 `main` 병합을 멈춘다. 문안 시드를 손으로 지우지 않는다.

```sh
sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
  psql -U postgres -d ai_character_chat -At -c \
  "SELECT (SELECT id || ' ' || published_at FROM prompt_sets WHERE status = 'published' AND lane = 'novel' AND model = 'gemini'
             ORDER BY published_at DESC LIMIT 1),
          (SELECT count(*) FROM prompt_sections s JOIN prompt_sets p ON p.id = s.prompt_set_id
             WHERE p.lane = 'novel' AND s.channel IN ('novelize_revise_blocks','novelize_revise_recheck')),
          (SELECT count(*) FROM prompt_sets WHERE status = 'draft' AND lane = 'novel' AND model = 'gemini');"
# 되돌리기 판정(배포 뒤): 패치 칸이 있는 작업 수, 그중 진행 중, 대기 수정안이 남은 행
sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
  psql -U postgres -d ai_character_chat -At -c \
  "SELECT (SELECT count(*) FROM novel_jobs WHERE block_edit IS NOT NULL),
          (SELECT count(*) FROM novel_jobs WHERE block_edit IS NOT NULL AND status IN ('queued','running')),
          (SELECT count(*) FROM novel_jobs WHERE block_edit IS NOT NULL AND dismissed_at IS NULL
             AND jsonb_path_exists(block_edit, '$.patches[*] ? (@.state == \"pending\")'));"
```

**여러 문단 수정 적용·버리기·재검사 — 배포 · 되돌리기(마이그레이션 없음).** 위 두 리비전 위에 코드만 오른다.
- 새 라우트 셋: 단위 적용 `POST /novels/{id}/jobs/{jobId}/patches/apply`·버리기 `.../patches/dismiss`(스위치와 무관 — 켰다 끈 뒤에도
  받은 수정안을 쓰거나 버린다), 묶음 재검사 `POST /novels/{id}/jobs/{jobId}/bundles/{bundleId}/recheck`(스위치 뒤, 무과금, 시간당 상한
  `NOVELIZE_RECHECK_HOURLY_LIMIT`). 재검사는 새 호출 위치 `novelize_revise_recheck` 로 늘 Gemini 를 부른다(경계 제안과 같은 갈래 —
  기본 모델·사고, 타임아웃 `GEMINI_NOVELIZE_RECHECK_TIMEOUT_MS`). 운영 `LLM_CALL_SITE_BACKENDS` 에 이 이름을 **넣지 않는다** — 넣으면 이
  이름을 모르는 옛 이미지가 기동하지 못해 이미지 롤백의 하한이 생긴다. 새 env 두 키는 모두 설정 안 함이 기본이다.
- 기존 경로에서 바뀌는 것은 패치 칸이 있는 행뿐이다: 화에 새 개정이 쌓인 뒤의 낡은 미리보기 비우기가 그 화의 대기 수정안 중 블록이
  바뀐 것을 낡음(문단 없음)으로 바꾸고 대기 수정안이 없어진 작업의 지시문을 비운다. 패치 작업의 환불과 옛 버리기는 대상·수정안의 기준
  해시를 모두 지운다(빈 문자열). 성공 저장·단위 적용·버리기·낡음 표시·재검사 분리는 대기 수정안이 없는 블록의 해시를 대상·수정안 양쪽에서
  지운다 — 적용·버림·낡음이 된 수정안의 블록은 이 배포 뒤의 배포에서, 모델이 수정안을 내지 않은 대상은 아래 "응답 칸 추가" 배포에서
  더했다. 옛 연속 범위 수정의 저장·목록·적용·버리기는 그대로다.
- 평상시 겹침 교체로 배포한다: 겹침 동안 도는 직전 이미지(여러 문단 수정 요청까지 있는 판)는 이 판이 쓴 행을 그대로 읽는다 — 상태
  `applied`·`stale` 과 묶음·대상 칸 꼴은 그 판에 이미 있고, 지운 해시는 문자열이라 상세 조회가 깨지지 않는다. 그 판의 옛 버리기는 일부를
  적용한 작업(결과 개정이 찬 행)을 409 로 거절한다.
- **병합 전**: 마이그레이션이 없어 백업 확인·SELECT 는 필요 없다. 스위치는 꺼진 채 둔다(켜기는 개정 처리방침 게시 뒤 별도 승인).
- **되돌리기**: 이미지만 직전 판으로 되돌린다. 스위치를 켠 뒤라면 먼저 스위치 줄을 지우고(재기동) 아래 SELECT 로 대기 수정안이 남은
  작업 수와 그중 일부를 적용한 작업 수를 본다 — 직전 판에는 단위 적용·버리기가 없어 대기 수정안은 옛 버리기(전부 버리기)로만 지울 수
  있고, 일부를 적용한 작업은 그것도 409 다. 그런 행이 있으면 되돌리기 전에 이 판에서 사용자가 버리게 두거나, 행 수를 보고 사람이 정리
  방법을 정한다.

```sh
# 되돌리기 판정: 대기 수정안이 남은 패치 작업 수, 그중 일부를 적용한 작업 수
sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
  psql -U postgres -d ai_character_chat -At -c \
  "SELECT count(*), count(*) FILTER (WHERE result_revision_id IS NOT NULL) FROM novel_jobs
     WHERE block_edit IS NOT NULL AND dismissed_at IS NULL
       AND jsonb_path_exists(block_edit, '$.patches[*] ? (@.state == \"pending\")');"
```

**소설 스튜디오 응답 칸 추가·수정안 없는 대상의 해시 지우기 — 배포 · 되돌리기(마이그레이션 없음).** 코드만 오른다. 새 스위치·env 없음.
- 응답 칸 추가만 한다(이름·뜻이 바뀐 칸 없음). 구간 선택 응답: 구간 양 끝·잠긴 구간의 `startMessageCreatedAt`·`endMessageCreatedAt`, 승인본·
  초안·기본 제안의 `roomEndMessageCreatedAt`(값은 이미 행에 있다 — 질의 수 변화 없음). 전체 구성안 응답: 낡은 판에만 그 판이 쓴 선택의
  include 구간 `sourceSections`(아니면 null). 작업 응답·상세의 진행 중 작업: 장면 구성안·원고 작업의 `episodeKey`(다른 작업은 null).
  구간 선택·구성안 라우트는 구성 흐름 스위치 뒤라 꺼짐에선 지금처럼 404 이고, 꺼짐에서 보이는 차이는 작업 응답과 상세
  `activeJob` 의 `episodeKey: null` 칸뿐이다.
- 동작 변경은 하나다: 성공한 여러 문단 수정 작업에서 모델이 수정안을 내지 않은 대상의 기준 해시도 정산 때 지운다(위 문단). 지운 값은
  기존과 같은 빈 문자열이라 직전 이미지가 그대로 읽고, 직전 이미지가 겹침 동안 남긴 해시는 다음 정산 때 이 판이 지운다. 칸이 있는 행은
  여러 문단 수정 스위치를 켠 뒤에만 생긴다.
- 평상시 겹침 교체로 배포한다(`skip_overlap` 불필요).
- **병합 전**: 마이그레이션이 없어 백업 확인은 필요 없다. 아래 SELECT 로 패치 칸이 있는 작업 수와 그중 성공 수를 본다 — 0·0 이면 남은
  해시를 정리할 행이 없다(0 이 아니어도 다음 정산 때 지워지므로 일회성 UPDATE 는 하지 않는다).
- **되돌리기**: 이미지만 직전 판으로 되돌린다(downgrade 없음). 지운 해시는 되살리지 않는다(쓸 곳이 없다). 이 칸을 읽는 web 후속이 이미
  나가 있으면 칸이 없을 때 지금 동작으로 돌아가는지 먼저 본다 — 그래서 web 후속은 이 배포를 확인한 뒤에 낸다.

```sh
# 병합 전(읽기 전용): 패치 칸이 있는 작업 수, 그중 성공
sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
  psql -U postgres -d ai_character_chat -At -c \
  "SELECT count(*), count(*) FILTER (WHERE status = 'succeeded') FROM novel_jobs WHERE block_edit IS NOT NULL;"
```

**구성안 화 턴 수·원고 모델 턴 상한·긴 화 승인 막기·모델 호출 실패 로그 — 배포 · 되돌리기(마이그레이션 없음).** 코드만 오른다. 새
스위치·env·프롬프트 없음.
- 응답 칸 추가(이름·뜻이 바뀐 칸 없음): 전체 구성안 응답의 화마다 `turnCount`(근거 안 모델 응답 수, 셀 수 없으면 null)와 상태의
  `chapterTurnCaps`(원고에 고를 수 있는 모델별 `maxTurns`), 장면 구성안 응답의 `chapterTurnCount`(승인한 장면 구성안의 장면 턴 수,
  판정 없으면 null)와 원고 모델 항목의 `maxTurns`(늘 실림)·`eligible`·`ineligibleReason`(판정 없으면 null). 두 라우트 모두 구성 흐름
  스위치 뒤라 꺼짐에선 지금처럼 404 이고 옛 흐름 응답은 그대로다.
- 동작 변경: 전체 구성안 **승인**이, 원고가 아직 안 된 화 중 이 계정이 고를 수 있는 원고 모델의 가장 큰 턴 상한을 넘는 화가 있으면 409
  `NOVEL_OUTLINE_EPISODE_TOO_LONG`(+ `maxTurns`·`episodes[{key, turnCount}]`)이다. 고친 판 저장은 막지 않는다. 턴 상한 env
  (`NOVELIZE_CHAPTER_MAX_TURNS*`)를 바꾸면 api 를 다시 띄운 뒤부터 그 값으로 판정된다.
- 소설화 모델 호출 실패 경고 로그(장 생성·문단 수정·여러 문단 수정·전체 구성안·장면 구성안)에 원인 예외 종류·HTTP 상태·공급자 오류
  종류·공급자 요청 id 가 붙는다(예외 글·본문은 넣지 않는다). 작업 종류·작업 행 칸은 바뀌지 않아, 겹침 동안 옛 이미지 워커가 작업을 받아도 결과는 같고
  로그만 옛 꼴이다.
- 평상시 겹침 교체로 배포한다(`skip_overlap` 불필요). **병합 전**: 마이그레이션이 없어 백업 확인·SELECT 는 필요 없다.
- **되돌리기**: 이미지만 직전 판으로 되돌린다(downgrade 없음). 그 사이 승인된 구성안은 그대로 쓴다. 새 칸을 읽는 web 후속이 이미 나가
  있으면 칸이 없을 때 안내만 사라지는지 먼저 본다 — 그래서 web 후속은 이 배포를 확인한 뒤에 낸다.

**소설 프롬프트 덤프 키(`NOVEL_PROMPT_DUMP_PATH`) — 배포 · 되돌리기(마이그레이션 없음).** 코드만 오른다. 측정 서버 전용 키라 운영 `.env`
에 넣지 않는다 — `PROMPT_DUMP_PATH` 처럼 "BE 런타임" 절의 키 표와 키 수 문장에 없다. 키가 없으면 소설 작업은 지금과 같이 돌고 파일을
열지 않는다. 켜면 소설 작업마다 원문 대화와 창작자 비공개 설정이 담긴 슬롯 값을 그 파일에 쓴다. 되돌리기는 이미지만 직전 판으로.

### 3-12. 상위 모델(채팅 Opus 직결) — 꺼진 채 배포 · 켜기 · 끄기

채팅 턴 생성(측정용 리플레이 포함)과 소설 장 생성은 Gemini 대신 Claude 로 돌 수 있다. 판정·요약은 모델 배정 표가 비어
있으면 고른 모델과 무관하게 판정·요약 모델 키(env 표의 `STAT_JUDGMENT_MODEL` 행, 코드 기본값 `gemini`)가 정하고, 운영은 판정·요약을 Haiku
5.5 직결로 돌린다. 표에 행을 두면 방 모델마다 판정·요약 문안 체인이 달라질 수 있다 — "채팅 단계별 문안 체인·호출 모델 설정 —
켜기 · 끄기 · 되돌리기" 절. 발행 심사·문단 수정은 고른 모델과 무관하게 Gemini 다. 채팅에서 고를 수 있는 상위 모델은 Opus 하나다 — Sonnet 은 소설 장에만 남았고, 채팅에서
내리기 전에 Sonnet 을 저장한 방은 Gemini 로 Gemini 가격에 돈다.

**빌더 미리보기 모델.** 미리보기 세션도 시작 요청(`POST /preview-sessions?model=opus`)으로 모델을 고를 수 있다 — 고른 모델은
세션 상태에 남고, 그 세션의 턴은 채팅방과 같은 규칙으로 생성·차감(그 모델의 턴 가격)·판정(모델 배정 표의 그 모델 칸)이 함께
움직인다. 상위 모델은 채팅 스위치가 켜져 있어야 고를 수 있다(꺼져 있으면 403 `CHAT_MODEL_NOT_ALLOWED`). 모델을 바꾸면 새 세션이다.
- 배포만으로 BE 에 이 칸이 생기지만 쿼리가 없는 요청(지금 웹)은 기본 Gemini 이고, 모델 배정 표의 (레인, `gemini`, 단계) 칸이
  비어 있을 때 그 세션의 시작·전송·판정·차감·세션 상태는 배포 전과 같다 — 기본 세션의 미리보기 판정도 그 칸을 읽으므로 칸에 행이
  있으면 판정 문안·부를 모델이 행을 따른다. 웹의 모델 피커는 다음 단계다.
- 옛 이미지와 새 웹이 겹치면 옛 이미지는 모르는 쿼리를 무시해 Gemini 세션을 만든다. 새 이미지가 만든 Opus 세션을 옛 이미지가
  이어 받으면 모르는 `chatModel` 칸을 버리고 Gemini 로, Gemini 가격에 돈다(값을 내고 다른 모델의 글을 받는 일은 없다).
- 이미지를 되돌린 동안 옛 이미지가 Opus 세션에 한 턴이라도 쓰면 세션 상태를 그 칸 없이 다시 저장해 모델 칸이 지워진다. 새
  이미지로 다시 올려도 그 세션은 Gemini 세션으로 남는다 — Opus 로 시험하려면 새 시작 요청으로 세션을 다시 연다.
- 경로: 운영 env 에 미리보기 생성 줄을 넣지 않는다 — Opus 미리보기는 채팅 생성(`chat_generate:anthropic`)을 물려받아 Anthropic
  직결로 간다. 미리보기 판정도 채팅 판정 짝의 배정을 물려받으며, 미리보기 판정 줄을 두면 채팅 짝과 같은 경로여야 api 가 뜬다
  (env 표 `LLM_CALL_SITE_BACKENDS` 행). 운영 env 는 두 줄이 같아 그대로 뜬다. 이 이미지부터는 운영 env 에서 미리보기 판정 줄이 빠져도
  채팅 줄을 물려받아 뜬다(전에는 Bedrock 으로 풀려 기동이 거부됐다).

**공급자 경로.** 상위 모델 호출이 어느 공급자로 가는지는 호출 위치마다 정한다. 코드 기본 경로는 AWS Bedrock 이고,
`LLM_CALL_SITE_BACKENDS` 에 배정한 호출 위치만 Anthropic API 직결(`ANTHROPIC_DIRECT_API_KEY`)로 간다. 운영은 채팅
턴(`chat_generate`)·측정용 리플레이(`replay_generate`)·소설 장(`novelize_chapter`)을 모두 `anthropic` 에 배정해 두었고
**이 배정을 유지한다** — 배정을 빼면 그 호출의 Opus 가 코드 기본 경로인 Bedrock 으로 가고, 스위치가 켜진 채 Bedrock 키가
없으면 api 가 기동을 거부한다. 이 절은 운영 경로(직결)를 기준으로 적는다. Bedrock 으로 보낼 때의 키는 env 표의 `BEDROCK_*`
행이다 — Bedrock 모델 호출만 허용한 전용 IAM 사용자 키를 쓰고, R2 키(`AWS_ACCESS_KEY_ID` 등)를 재사용하거나 그 줄을 고치지
않으며, Bedrock 계정 설정에서 모델 호출 로깅(model invocation logging)이 꺼져 있는지 먼저 본다.

**스위치.** 상위 모델은 채팅·소설화에 스위치가 하나씩(`CHAT_PREMIUM_MODELS_ENABLED`·`NOVELIZE_PREMIUM_MODELS_ENABLED`)이고
코드 기본값이 꺼짐이라 `.env` 에 스위치 줄이 없으면 **배포만으로는 닫힌 채 뜬다.** 채팅은 스위치 하나로 로그인 회원 모두에게 열린다 — 명단도 계정별
허용도 없다. 소설은 스위치에 더해 env 명단(`NOVELIZE_PREMIUM_MODEL_ALLOWLIST`)과 계정별 허용 행이 있어야 한다(아래 「소설
계정 허용」). 운영 `.env` 에 남은 `CHAT_PREMIUM_MODEL_ALLOWLIST` 줄은 **지우지 않는다** — 지금 이미지는 그 키를 읽지 않고
무시하지만, 채팅 명단이 있던 옛 이미지로 태그 롤백하면 옛 판정이 그 명단(과 어드민 허용 행)을 다시 읽는다.

**명단 이미지에서 넘어올 때.** 🔴 채팅 상위 모델을 env 명단(`CHAT_PREMIUM_MODEL_ALLOWLIST`)으로 가두던 이미지에서 이
이미지로 넘어올 때 운영 `.env` 에 `CHAT_PREMIUM_MODELS_ENABLED=true` 줄이 이미 있으면(명단으로 운영자만 열어 둔 상태), 새
이미지는 명단을 읽지 않으므로 배포되는 순간 로그인 회원 전체에게 열린다. 그래서 **병합·자동 배포 전에** 아래 「끄기」 블록으로
그 줄을 먼저 지우고, 아래 「켜기 전 확인」 명령의 마지막 값(스위치)이 `False` 인지 본 뒤 병합한다. 공개는 그 뒤 「켜기 —
공개」 순서로 따로 연다.

**켜기 전 확인.** 직결 키와 배정이 들어 있는지 본다. 값은 찍지 않는다:

```sh
cd /opt/ddona/app
sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env exec -T api_$(sudo bash ops/active-color.sh) python -c \
  "from api.core.config import settings as s; print(bool(s.anthropic_direct_api_key.strip()), {k: s.llm_call_site_backends.get(k) for k in ('chat_generate', 'replay_generate', 'novelize_chapter')}, s.chat_premium_models_enabled)"
```

`True {'chat_generate': 'anthropic', 'replay_generate': 'anthropic', 'novelize_chapter': 'anthropic'} False` 여야 한다. 첫 값이
`False` 면 키를, 배정에 `None` 이 있으면 배정을 스위치보다 먼저, 스위치 없이 넣는다. 키 없이 배정만 있으면 스위치와
무관하게 api 가 기동하지 못하므로 키 줄이 먼저다. 파일을 통째로 덮거나 백업본으로 복원하지 않는다(교체 스크립트가 같은
파일의 `API_IMAGE_BLUE`·`API_IMAGE_GREEN` 을 고친다). 키 값은 셸 기록에 남지 않게 편집기로 넣어도 된다. 배정 줄이 이미 있는데
항목이 빠졌으면 새 줄을 더하지 말고 그 줄을 고친다(같은 키가 두 번이면 형식 검사의 `duplicate-key` 위반이다):

```sh
cd /opt/ddona/app
sudo sh -c 'printf "\nANTHROPIC_DIRECT_API_KEY=<키>\n" >> /opt/ddona/.env'
sudo sh -c 'printf "\nLLM_CALL_SITE_BACKENDS=chat_generate:anthropic,replay_generate:anthropic,novelize_chapter:anthropic\n" >> /opt/ddona/.env'
sudo python3 ops/check_env.py --format /opt/ddona/.env
sudo bash ops/swap-api.sh
```

넣은 뒤 위 확인 명령을 다시 돌리고, "BE 런타임" 절의 키 개수 문장을 VM 에서 다시 세어 고친다. 키·배정만 있고 스위치가
꺼져 있으면 아무 호출도 상위 모델로 가지 않는다.

**켜기 — 공개.** 🔴 Anthropic 국외이전을 담은 개인정보처리방침이 게시·시행되고, 그 판의 가입 화면 국외이전 사본
(`apps/web/src/features/sign-up/ui/LegalConsentFields.tsx`)이 배포된 뒤에만 스위치 줄을 더한다 — 그 전에 켜면 처리방침에
없는 국외이전이 된다. 위 확인이 기대값일 때 채팅 스위치 한 줄을 더한다. 🔴 스위치가 켜졌는데 그 호출이 갈 공급자의 키가 비어
있으면 api 가 기동하지 못한다. 교체 스크립트의 새 색이 healthy 가 안 돼 교체가 실패하고(옛 색은 그대로 서빙, 종료코드 1),
그 줄을 고치기 전에는 다음 배포도 같은 이유로 실패한다:

```sh
cd /opt/ddona/app
sudo sh -c 'printf "\nCHAT_PREMIUM_MODELS_ENABLED=true\n" >> /opt/ddona/.env'
sudo python3 ops/check_env.py --format /opt/ddona/.env
sudo bash ops/swap-api.sh
```

`restart` 는 env 를 다시 읽지 않으므로 교체 스크립트를 태그 없이 부른다("env 반영 재기동" 절). 위 확인 명령의 마지막 값이
`True` 인지 보고, 줄을 넣었으니 키 개수 문장을 다시 센다. 로그인 회원이 web 을 새로고침하면(세션 정보를 다시 받는다) 채팅
화면의 모델 선택 입구(헤더 칩 또는 더보기 「AI 모델」)가 보인다. 고른 모델은 방마다 저장되고 다음 턴부터 그 모델·그 가격으로 돈다. 상위 모델 턴은 레이트리밋
면제 계정도 값을 내고(턴 단가는 `api/core/clover.py` 의 가격 등록부 `CLOVER_MODEL_PRICES` Opus 행에서 확인한다), 하루 무료분은 Gemini 턴에만
쓰인다. 소설 장의 상위 모델도 열 때는 `NOVELIZE_PREMIUM_*` 두 줄(스위치·명단)을 같은 방식으로 더한다.

**소설 계정 허용.** 소설 상위 모델은 스위치와 명단만으로는 아직 아무도 못 쓴다 — 계정마다 허용 행이 있어야 한다.

1. 명단(`NOVELIZE_PREMIUM_MODEL_ALLOWLIST`)에 그 계정 id 가 있는지 본다. 명단 밖 계정의 허용은 어드민이 422
   `NOVELIZE_PREMIUM_MODELS_GRANT_NOT_ALLOWLISTED` 로 거절한다.
2. 어드민 유저 상세에서 허용을 켠다 — API 로는 `POST /admin/users/{id}/novelize-premium-models-grant` 에
   `{"granted": true, "adminComment": "…"}`. 스위치가 꺼져 있어도 미리 줄 수 있다. 그 계정에 소설화 허용(3-11 절)도 있어야
   보인다.
3. 클로버를 지급한다. 소설 화는 레이트리밋 면제 계정도 값을 낸다(화 하나당 값은 `api/core/clover.py` 의 가격 등록부
   `CLOVER_MODEL_PRICES` Sonnet·Opus 행의 화 단가이고 생성 한 번이 화 수 × 화 단가다).
4. 소설 상위 모델은 장 생성·재생성 요청마다 고른다(방처럼 저장하지 않는다). 허용이 들어갔는지는 그 계정으로 소설 상세
   (`GET /novels/{id}`)를 열어 `chapterModels` 에 Sonnet·Opus 가 실렸는지로 본다 — 허용이 없으면 Gemini 하나뿐이다. 장 작업은
   요청한 모델을 `novel_jobs.model` 에 적고, 실행은 그 값으로 돈다.

회수는 어드민에서 허용을 끄는 것(재기동 없음) 또는 명단에서 지우고 `sudo bash ops/swap-api.sh` 다. 허용 행만 남은 계정도 명단
밖이면 접근 시점에 막힌다. 회수 뒤의 장 요청이 상위 모델이면 403 `NOVEL_MODEL_NOT_ALLOWED` 다(방과 달리 Gemini 로 바꿔 받지
않는다 — 장 요청의 모델은 그 가격과 함께 지금 고른 값이다). 회수 전에 값을 낸 장 작업은 회수와 무관하게 그 모델로 끝난다.

**끄기.** 채팅 스위치 줄만 지우고 다시 올린다. 키·배정 줄은 남겨 두면 다시 켤 때 스위치 한 줄이면 된다. 끈 동안 Opus 를
저장한 방은 판정 문안과 차감이 함께 Gemini 방 칸으로 돈다 — 모델 배정 표의 Opus 방 칸 행은 쓰이지 않는다. Opus 로 시작한 빌더
미리보기 세션도 같다(생성·차감·판정이 함께 Gemini). 소설 줄
(`NOVELIZE_PREMIUM_*`)은 건드리지 않는다 — 소설 상위 모델까지 끌 때만 `NOVELIZE_PREMIUM_MODELS_ENABLED` 줄도 같은 방식으로
지운다:

```sh
cd /opt/ddona/app
sudo sed -i '/^CHAT_PREMIUM_MODELS_ENABLED=/d' /opt/ddona/.env
sudo python3 ops/check_env.py --format /opt/ddona/.env
sudo bash ops/swap-api.sh
```

끄거나 소설 허용을 거둬도 **상위 모델을 고른 방은 막히지 않는다.** 방에 저장된 모델(`chat_rooms.chat_model`)은 그대로 남고,
그 방의 다음 턴은 Gemini 로 Gemini 가격(하루 무료분 포함)에 돈다. 방 응답과 모델 목록은 실제로 쓰일 모델(Gemini)을 보인다.
다시 켜면 저장된 모델로 돌아간다. 진행 중이던 턴과 소설 장 작업은 이미 값을 낸 모델로 끝난다(스위치를 껐다고 Gemini 로
바꾸지 않는다 — 상위 모델 값을 내고 Gemini 글을 받게 된다). 끄는 동안 Redis 일부 장애가 나도 Gemini 턴은 지금처럼
통과한다(상위 모델 턴만 503 `CHAT_MODEL_UNAVAILABLE` 로 거절된다 — 켜져 있을 때의 동작이다).

**키 교체·회수.** 새 키를 만든 뒤 `.env` 의 `ANTHROPIC_DIRECT_API_KEY` 줄을 `sudo sed -i` 로 바꾸고 형식 검사 →
`sudo bash ops/swap-api.sh` → 위 확인 명령, 그다음 Anthropic 콘솔에서 옛 키를 비활성화한다. 키가 새어 나갔으면 먼저 콘솔에서
비활성화한다 — 스위치가 켜져 있으면 그동안의 상위 모델 호출은 실패하고 환불된다. Bedrock 키(`BEDROCK_*` 두 줄)도 같은
순서이고 옛 키는 AWS 콘솔에서 비활성화한다.

**보는 곳.** 직결 호출 한 건마다 API 로그에 `anthropic_usage` 줄(입력·캐시 읽기·캐시 쓰기·출력 토큰)이 남고(Bedrock 으로 간
호출은 `bedrock_usage`), 사용량 집계(`scripts/llm_usage_report.py --model claude-opus-5-5` 처럼 실제 모델 id 로 좁힌다)와
어드민 사용량 화면에 Gemini 호출과 같은 표로 나온다. 채팅에서 흡수된 실패는 Bugsink 태그 `dependency=anthropic`(쿼터 소진은
`anthropic_rate_limit`, Bedrock 경로는 `bedrock`·`bedrock_rate_limit`)로 Gemini 와 따로 묶인다. 소설 장 실패는 공급자와
무관하게 지금처럼 `dependency=novelize` 다.

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
  500 이 된다. 옛 코드는 레인으로 세트를 골라 소설 레인을 읽지 않는다. 🔴 판정 문안 체인 리비전(`1a843a0b2d8f`, 아래)이 심은
  시드 6개(story·character × Sonnet·Opus·Haiku)도 같은 이유로 남긴다 — 이 목록에서 빼면 다시 올릴 때 그 리비전도 건너뛰어
  판정 전용 체인이 빈 채로 남고 Claude 체인은 판정·요약 행 없는 이전 세트로 돌아간다. 장면 기억 문안 리비전(`fc6f0e134782`,
  아래)이 심은 Gemini 가 아닌 시드 6개도 같은 이유로 남긴다. 아래 SQL 의 제외 목록은 리비전별로 이렇게 묶인다:
  - 모델 축(`e6aa289fea62`) 4개: `ba2a926c…`·`f3237e56…`·`b9c2f1ec…`·`9b308ef1…`
  - 판정 문안 체인(`1a843a0b2d8f`) 6개: `32b99025…`·`73026fdc…`·`e8685db5…`·`b483d5c3…`·`9a2b4dbb…`·`8114a6d6…`
  - 장면 기억 문안(`fc6f0e134782`) 6개: `99c2b0f5…`·`3db7a362…`·`2517d852…`·`9c029822…`·`952ae5d4…`·`1b13a6d3…`



  ```sh
  sudo /opt/ddona/backup.sh --manual   # 먼저 백업
  sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
    psql -U postgres -d ai_character_chat -c \
    "BEGIN; DELETE FROM prompt_sections WHERE prompt_set_id IN (SELECT id FROM prompt_sets WHERE model <> 'gemini' AND lane <> 'novel' AND id NOT IN ('ba2a926c-e9ed-46e0-b42c-9c21c63552f6','f3237e56-5ff6-4b27-9135-98495c0094bb','b9c2f1ec-5e8c-48ce-8fc9-ffefdc6950d2','9b308ef1-bdb9-4f23-a2d8-fb6ae6ad778c','32b99025-22e8-45fa-86a5-50f267b30a1b','73026fdc-e2bc-4e99-9b94-950f791d6835','e8685db5-f431-419a-9957-0db6b27ec848','b483d5c3-92dd-4dd9-ad4b-9ae6488bbcb4','9a2b4dbb-ff70-4ccf-a8b3-4cff6ca785c0','8114a6d6-b5cc-4b4a-b8ac-a8f1c25b640d','99c2b0f5-3c36-4a96-adbd-d226e430b4f8','3db7a362-b2a1-4927-82d1-f6aeb4c94e3c','2517d852-c29f-4271-83c0-b5799da1ade0','9c029822-2229-48c6-bd0e-03312c2b618b','952ae5d4-5fa9-4cba-b6ba-d5970ac119ab','1b13a6d3-2747-4348-8e63-10aafceeb1ce')); DELETE FROM prompt_sets WHERE model <> 'gemini' AND lane <> 'novel' AND id NOT IN ('ba2a926c-e9ed-46e0-b42c-9c21c63552f6','f3237e56-5ff6-4b27-9135-98495c0094bb','b9c2f1ec-5e8c-48ce-8fc9-ffefdc6950d2','9b308ef1-bdb9-4f23-a2d8-fb6ae6ad778c','32b99025-22e8-45fa-86a5-50f267b30a1b','73026fdc-e2bc-4e99-9b94-950f791d6835','e8685db5-f431-419a-9957-0db6b27ec848','b483d5c3-92dd-4dd9-ad4b-9ae6488bbcb4','9a2b4dbb-ff70-4ccf-a8b3-4cff6ca785c0','8114a6d6-b5cc-4b4a-b8ac-a8f1c25b640d','99c2b0f5-3c36-4a96-adbd-d226e430b4f8','3db7a362-b2a1-4927-82d1-f6aeb4c94e3c','2517d852-c29f-4271-83c0-b5799da1ade0','9c029822-2229-48c6-bd0e-03312c2b618b','952ae5d4-5fa9-4cba-b6ba-d5970ac119ab','1b13a6d3-2747-4348-8e63-10aafceeb1ce'); COMMIT;"
  ```

- 스키마까지 되돌리면(`alembic downgrade a966fc016bf1`, 순서는 위 절들과 같이 태그 롤백 먼저 — 묶음·화 구조 리비전이 위에
  있으면 그것부터, 아래 「롤백 순서」 4단계) downgrade 가 Gemini 가 아닌
  세트 전부(시드 + 어드민이 만든 것)를 지우고 인덱스를 되돌린 뒤 열을 지운다. 🔴 `alembic downgrade` 는 목표 위에 쌓인 리비전을
  head 부터 전부 지나가므로, 이 한 줄은 이 배포의 세 리비전(모델 축·방 모델·장 작업 모델)만 내리는 명령이 아니다 — 지금 head 에서
  돌리면 그 위에 나중에 쌓인 리비전(묶음·화 구조, 판정 문안 체인 `1a843a0b2d8f`, 그 아래 턴 기록 `42ba15156c84` 등)의
  downgrade 까지 함께 돈다. 판정 문안 체인 downgrade 는 시드 뒤 어드민의 Claude 게시가 있으면 `RuntimeError` 로 멈추고, 턴 기록
  downgrade 는 `chat_turns` 테이블을 지운다(그 리비전 코드가 떠 있으면 방 삭제·탈퇴가 실패하므로 이미지를 먼저 되돌린다). 그래서
  먼저 새 이미지로 `alembic history -r a966fc016bf1:head` 를 돌려 목표 위에 무엇이 있는지 보고, 위쪽 리비전은 각자의 롤백 절
  (아래 「판정 문안 체인」의 롤백 순서, 소설화 절의 「묶음·화 구조만 내릴 때」 등)을 위에서부터 먼저 따른 뒤 이 줄을 돌린다.
  목표는 엔딩 우선 스탯 리비전(`a966fc016bf1`)이다 — 이 배포의 세 리비전이 그 위에 쌓여 있어, 그보다 아래(`3bb2cc159b6d`)로
  내리면 엔딩의 우선 스탯 열과 값까지 지워진다.
- 앞으로 슬롯을 더하는 마이그레이션은 Gemini 두 레인뿐 아니라 다른 체인도 다룰지 판단한다 — `system`·`generation` 슬롯이면
  Claude 체인 네 개(story·character × Sonnet·Opus)에, 판정·요약 슬롯이면 그 넷과 판정 전용 체인 둘(story·character ×
  Haiku)에도 넣어야 게시 검증의 슬롯 집합이 맞는다(아래 「판정 문안 체인」).
- 앞으로 활성·초안 세트를 원시 SQL 로 고르는 마이그레이션은 반드시 모델로 거른다(`AND model = 'gemini'` 또는 대상 모델). 레인만
  보는 조회는 Claude 세트를 집을 수 있고, 초안을 한 행으로 읽으면 레인에 초안이 둘 이상일 때 `MultipleResultsFound` 로 깨진다.

**판정 문안 체인(`1a843a0b2d8f`).** 판정·요약 문안을 Gemini 가 아닌 체인에도 둔다 — 판정을 다른 모델로 돌릴 준비 데이터이고,
이 배포만으로는 어떤 호출도 그 행을 읽지 않는다(판정·요약은 계속 Gemini 세트). 마이그레이션이 레인(story·character)마다 세 세트를
게시본으로 심는다:

| 레인 | 모델 | 채널 | 판정·요약 행 수 | 게시 시각 |
|---|---|---|---|---|
| story | Sonnet·Opus | 그 체인 활성 세트 그대로(`system`·`generation`) + `stat_rule_judgment`·`ending_judgment`·`image_judgment`·`memory_summary` | 17 | 그 체인 활성과 Gemini 활성 사이의 중간값 |
| story | Haiku(판정 전용, 새 체인) | 판정·요약 채널만 | 17 | Gemini 활성 − 1초 |
| character | Sonnet·Opus | 그 체인 활성 세트 그대로 + `image_judgment`·`memory_summary` | 8 | 중간값 |
| character | Haiku(판정 전용, 새 체인) | 판정·요약 채널만 | 8 | Gemini 활성 − 1초 |

판정·요약 행은 그 레인 Gemini 활성 세트의 바이트 사본이고(옛 `stat_judgment` 은 빼고), 생성 행은 손대지 않아 생성 글은 그대로다.
게시 시각은 모델로 거르는 조회가 새 세트를, 레인만 보는 옛 조회가 여전히 Gemini 세트를 집게 고른 것이고, 둘을 함께 만족하는 시각이
없으면 마이그레이션이 `RuntimeError` 로 배포를 멈춘다(어드민이 Claude 체인을 Gemini 보다 나중에 게시한 경우). 어드민 「프롬프트
관리」의 스토리·캐릭터 레인에 「Claude Haiku · 판정 전용」 탭이 생기고, Claude 탭에도 판정·요약 채널 탭이 생긴다(탭 이름에 버전을 적지
않는 것은 같은 `haiku` 가 직결로는 Haiku 5.5, Bedrock 으로는 Haiku 4.5 이기 때문이다).

- **배포 전**: `sudo /opt/ddona/backup.sh` 백업이 최근에 돌았는지 본다(3-4 절). 배포 **직전**에 아래 읽기 전용 SELECT 로 두 레인의
  Claude 활성(`sonnet`·`opus` 의 최신 `published_at`)이 Gemini 활성보다 과거인지, Claude 초안에 판정·요약 채널 행이 없는지,
  `haiku` 세트가 없는지 다시 본다 — 어긋나면 마이그레이션이 멈춘다:

  ```sql
  SELECT lane, model, status, id, version, published_at FROM prompt_sets
   WHERE lane IN ('story','character') ORDER BY lane, model, status, published_at DESC NULLS LAST;
  SELECT p.lane, p.model, s.channel, count(*) FROM prompt_sets p JOIN prompt_sections s ON s.prompt_set_id = p.id
   WHERE p.status = 'draft' AND p.model <> 'gemini' AND p.lane IN ('story','character') GROUP BY 1,2,3 ORDER BY 1,2,3;
  ```
- **배포 뒤**: 같은 첫 SELECT 로 여섯 체인(story·character × sonnet·opus·haiku)의 최신 게시본이 아래 시드 id 이고 Gemini 활성 id 가
  배포 전과 같은지 본다. 채널 행 수(판정·요약은 story 17·character 8, Claude 세트는 거기에 생성 행)와 레인만 보는 최신 게시본이
  Gemini 세트인지도 본다:

  ```sql
  SELECT p.lane, p.model, s.channel, count(*) FROM prompt_sets p JOIN prompt_sections s ON s.prompt_set_id = p.id
   WHERE p.id IN ('32b99025-22e8-45fa-86a5-50f267b30a1b','73026fdc-e2bc-4e99-9b94-950f791d6835','e8685db5-f431-419a-9957-0db6b27ec848',
                  'b483d5c3-92dd-4dd9-ad4b-9ae6488bbcb4','9a2b4dbb-ff70-4ccf-a8b3-4cff6ca785c0','8114a6d6-b5cc-4b4a-b8ac-a8f1c25b640d')
   GROUP BY 1,2,3 ORDER BY 1,2,3;
  SELECT DISTINCT ON (lane) lane, model, id FROM prompt_sets WHERE status = 'published' AND lane IN ('story','character')
   ORDER BY lane, published_at DESC;   -- 두 줄 모두 model = gemini
  ```

  시드 id 는 story Sonnet `32b99025…`·Opus `73026fdc…`·Haiku `e8685db5…`, character Sonnet `b483d5c3…`·Opus `9a2b4dbb…`·Haiku
  `8114a6d6…` 이다.
- **배포 뒤 공지**: 배포 전부터 열어 둔 어드민 프롬프트 편집 탭은 **새로고침**한다 — 그 탭에서 저장하면 초안이 섹션 전체 교체로 판정·요약
  행을 잃고 게시가 "누락"으로 막힌다.
- **겹침·이미지 롤백**: 옛 이미지는 Claude 세트의 생성 채널만 렌더하고 판정은 Gemini 세트를 읽어 생성·판정 모두 그대로다. 옛 이미지의
  어드민 게시 검증이 새 Claude 세트를 "잉여"로 거부해 **Claude 체인 어드민 게시만** 막힌다. 판정 전용 세트는 옛 이미지에서 보이지 않는다.
  그래서 이 배포는 이미지 롤백 하한을 올리지 않는다.
- **롤백 순서**: ① 판정을 Gemini 가 아닌 모델로 돌리는 설정이 있으면 전부 Gemini 로 되돌렸는지 확인(이 배포 시점에는 그런 설정이 없어
  늘 참이다 — 판정 모델 설정이 생긴 뒤부터 의미가 있다) → ② 1순위는 이미지만 되돌리기(`sudo DDONA_ROLLBACK=1 bash ops/swap-api.sh <이전
  태그>`) → ③ 시드까지 걷어야 하면 **새 이미지로** `alembic downgrade 42ba15156c84` 를 돌린 뒤 이미지를 되돌린다(3-2 절의 `docker run
  … <IMAGE>:<새 코드 TAG>` 꼴, 먼저 백업). downgrade 는 시드 뒤에 어드민이 Claude 체인(Sonnet·Opus)에 게시한 버전이 있으면 아무것도
  지우지 않고 멈춘다 — 그때는 멈추고 판단한다. 없으면 Claude 시드 4개, Haiku 세트 전부(어드민이 만든 것 포함), Claude 초안의
  판정·요약 행을 지운다.
- 🔴 **프롬프트 옛 버전을 통째로 복원하지 않는다** — 이 배포 이전 Claude 버전은 판정·요약 행이 없어 새 코드에서 게시가 "누락"으로
  막히고, 옛 이미지에서 복원·게시하면 판정·요약 행이 사라진다. 현재 활성본에서 바뀐 섹션만 고친다.
- 🔴 **시드를 손으로 지우지 않는다** — 다시 배포할 때 `alembic upgrade head` 가 이 리비전을 건너뛰어 판정 전용 체인이 빈 채로 남고(어드민
  초안 조회 500), Claude 체인은 판정·요약 행 없는 이전 세트로 돌아가 새 코드의 Claude 게시가 막힌다. 걷어야 하면 위 ③ 의 downgrade 로만.

**장면 기억 문안(`fc6f0e134782`).** 장면 기억의 추출 지시문 채널 `memory_episode`(지시문·이야기 속 이름·앞 구간 장면 제목·접힌
대화 4행)와 생성 채널의 회상 슬롯 `memory_recall`(conditional, `history` 바로 뒤)을 채팅 두 레인의 여덟 체인(story·character ×
Gemini·Sonnet·Opus·Haiku)에 새 게시본으로 심는다 — 회상 슬롯은 글을 쓰는 세 체인에만. 새 세트는 그 체인 **활성 세트의 바이트
사본**에 행을 더한 것이라 운영자가 고친 문안(운영 요약 문안 등)이 그대로 옮겨진다. 이 배포만으로는 어떤 호출도 새 행을 읽지 않는다
(추출 호출이 아직 없고, 회상 값이 비어 섹션째 빠진다 — 생성 글은 바이트 그대로다). 버전은 전 레인 최대 + 1 부터 (story, character)
× (Gemini, Sonnet, Opus, Haiku) 순서로 8개가 붙고, 레인 활성 Gemini 세트가 바뀐다.

- **게시 시각**: 새 Gemini 세트는 `max(now, 원본 + 1초)`(레인만 보는 "최신 게시본" 조회가 계속 Gemini 를 집는다), 다른 세 체인은
  (그 체인 활성, 새 Gemini) 중간값. 레인만 보는 조회가 이미 Gemini 가 아닌 세트를 집고 있거나, 어느 세트에 새 행이 이미 있거나,
  `generation` 의 `history` 가 정확히 하나가 아니면 마이그레이션이 `RuntimeError` 로 배포를 멈춘다.
- **배포 전**: 백업이 최근에 돌았는지 본다(「백업 · 복원」 절). 아래 첫 SELECT 로 두 레인 레인만 보는 최신 게시본이 Gemini 인지 본다.
  레인만 보는 활성 조회가 Gemini 가 아닌 세트를 집어 마이그레이션이 `RuntimeError` 로 멈추면 옛 색이 계속 서비스한다 — 어드민에서
  그 레인의 Gemini 활성본을 그대로 다시 게시해 최신으로 만든 뒤 재배포한다.
- **배포 뒤**: 여덟 체인의 최신 게시본이 아래 시드 id 이고, 레인만 보는 최신 게시본이 새 Gemini 세트인지, 새 채널 행 수(체인마다
  `memory_episode` 4, 글을 쓰는 체인은 `memory_recall` 1)를 본다:

  ```sql
  SELECT DISTINCT ON (lane) lane, model, id, version FROM prompt_sets WHERE status = 'published' AND lane IN ('story','character')
   ORDER BY lane, published_at DESC;   -- 배포 뒤에는 두 줄이 아래 Gemini 시드 id
  SELECT p.lane, p.model, p.version, s.channel, s.slot FROM prompt_sets p JOIN prompt_sections s ON s.prompt_set_id = p.id
   WHERE p.id IN ('7aa4122b-a9db-4003-bbe0-ee130b46034b','99c2b0f5-3c36-4a96-adbd-d226e430b4f8','3db7a362-b2a1-4927-82d1-f6aeb4c94e3c',
                  '2517d852-c29f-4271-83c0-b5799da1ade0','a80dffe5-207a-4a95-abac-95cda93d9219','9c029822-2229-48c6-bd0e-03312c2b618b',
                  '952ae5d4-5fa9-4cba-b6ba-d5970ac119ab','1b13a6d3-2747-4348-8e63-10aafceeb1ce')
     AND (s.channel = 'memory_episode' OR s.slot = 'memory_recall') ORDER BY 1,2,4,5;
  ```

  시드 id 는 story Gemini `7aa4122b…`·Sonnet `99c2b0f5…`·Opus `3db7a362…`·Haiku `2517d852…`, character Gemini `a80dffe5…`·Sonnet
  `9c029822…`·Opus `952ae5d4…`·Haiku `1b13a6d3…` 이다.
- **배포 뒤 공지**: 배포 전부터 열어 둔 어드민 프롬프트 편집 탭은 **새로고침**한다 — 그 탭에서 저장하면 초안이 섹션 전체 교체로 새
  행을 잃고 게시가 "누락"으로 막힌다. 어드민에 「장면 기억 추출」 탭이 생긴다.
- **겹침·이미지 롤백**: 옛 이미지는 회상 값을 넘기지 않아 새 슬롯이 빠지고(생성 글 그대로), 새 채널은 읽지 않는다. 옛 이미지의
  어드민 게시 검증이 새 세트를 "잉여"로 거부해 **여덟 체인의 어드민 게시만** 막힌다. 이미지 롤백 하한을 올리지 않는다.
- **롤백 순서**: ① 1순위는 이미지만 되돌리기 → ② 시드까지 걷어야 하면 **새 이미지로** `alembic downgrade f028a5a3b9e6` 를 돌린 뒤
  이미지를 되돌린다(먼저 백업). downgrade 는 시드 뒤에 어드민이 여덟 체인 중 하나라도 새 버전을 게시했으면 아무것도 지우지 않고
  멈춘다 — 그때는 멈추고 판단한다. 없으면 시드 8개와 초안의 새 행을 지우고 초안 order 를 되돌린다.
- 🔴 **시드를 손으로 지우지 않는다**(다시 배포할 때 이 리비전을 건너뛴다), 🔴 **프롬프트 옛 버전을 통째로 복원하지 않는다**(이 배포
  이전 버전은 새 행이 없어 새 코드에서 게시가 "누락"으로 막힌다 — 현재 활성본에서 바뀐 섹션만 고친다).

**롤백 순서.** 1차는 스위치 끄기(위 「끄기」)다 — 재기동 한 번으로 모든 채팅 턴이 Gemini 로 돌고 방은 막히지 않는다(소설
장까지 되돌릴 때는 소설 스위치 줄도 지운다). 코드까지 되돌릴 때는 스위치 먼저 → 태그 롤백(옛 이미지) → Pages(web) 순서이고,
스키마는 그 뒤에 내린다. 채팅 명단이 있던 옛 이미지로 돌아가면 채팅 상위 모델은 스위치를 다시 켜도 남겨 둔
`CHAT_PREMIUM_MODEL_ALLOWLIST` 와 어드민 허용 행이 둘 다 있는 계정에만 열린다. web 은 Pages 이전 배포로 되돌리되, 처리방침에
Anthropic 을 게시한 뒤에는 가입 화면의 국외이전 고지 사본(`apps/web/src/features/sign-up/ui/LegalConsentFields.tsx`)을 게시본과
같은 판으로 유지한 채 web 을 되돌린다 — 이전 배포로 통째 돌리면 그 사본까지 옛 판이 되므로, 그때는 사본을 둔 채 되돌릴
변경만 되돌린 web 을 배포한다. 상위 모델 스키마를 처음 들인 배포까지 되돌릴 때의 순서는 다음과 같다:

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
   데이터가 같이 사라진다. 그 내림 역시 head 부터 지나가므로, 묶음·화 구조보다 위에 쌓인 리비전(판정 문안 체인·턴 기록 등)이
   있으면 그 롤백 절들을 먼저 따른다(위 「판정 문안 체인」). 그다음 리비전은 위에서부터 장 작업 모델
   (`2494aa0e607e`) → 방 모델(`519329713933`) → 모델 축(`e6aa289fea62`) 순서로 엔딩 우선 스탯 리비전(`a966fc016bf1`) 위에
   쌓여 있다. 장 작업 모델 리비전만 내리면 작업마다 적은 모델이 사라지고(차감액은 남는다), 방 모델 리비전까지 내리면 방마다
   고른 모델이 사라지고(전부 Gemini), 그 아래 모델 축 리비전까지 내리면 Claude 세트 전부(시드 포함) 삭제도 함께 일어난다.
   마지막 줄보다 더 내리지 않는다 — 엔딩 우선 스탯 열은 이 배포와 무관하다:

   ```sh
   sudo /opt/ddona/backup.sh --manual   # 먼저 백업
   # 장 작업 모델 열만
   sudo docker run --rm --network ddona_default --env-file /opt/ddona/.env <IMAGE>:<새 코드 TAG> alembic downgrade 519329713933
   # 방 모델 열까지
   sudo docker run --rm --network ddona_default --env-file /opt/ddona/.env <IMAGE>:<새 코드 TAG> alembic downgrade e6aa289fea62
   # 모델 축까지(Claude 세트 삭제 포함)
   sudo docker run --rm --network ddona_default --env-file /opt/ddona/.env <IMAGE>:<새 코드 TAG> alembic downgrade a966fc016bf1
   ```

**모델 배정 설정·이력 표(`495e9a75bb46`) — 배포 · 되돌리기.** 방 모델별로 채팅 단계마다 어느 프롬프트 체인을 읽고 어느 모델을
부를지 담을 표 둘을 더한다. 이 리비전이 오르는 배포에는 두 표를 읽는 채팅·판정 코드가 없다 — 표에 행이 있어도 채팅·판정·
미리보기는 위 env 규칙 그대로 돈다. 설정 표를 읽는 코드가 들어온 뒤의 동작은 "채팅 단계별 문안 체인·호출 모델 설정 — 켜기 ·
끄기 · 되돌리기" 절.
- 생기는 것: 설정 표 `prompt_routes`((레인, 방 모델, 단계)마다 한 행, 유니크 인덱스, 행 모양 CHECK 둘, FK 없음)와 저장 이력 표
  `prompt_route_revisions`(저장 한 번 = 한 행, 표 전체 JSONB 스냅샷, 운영자 `admin_users` FK, 되돌리기 원본 자기 참조 FK). 기존 표에는
  칸을 더하지 않는다. 업그레이드 첫 문장이 `lock_timeout 5s` 라 `admin_users` 잠금을 5초 안에 못 잡으면 실패한다 — 다시 돌리면 된다.

평상시 겹침 교체로 배포한다(`skip_overlap` 불필요): 겹침 동안 도는 옛 이미지는 두 표를 모르고 읽지도 쓰지도 않으며, 기존 표의
INSERT·SELECT 는 그대로다.

- **병합 전**: 운영 최신 백업 성공을 보고, 운영 DB 리비전이 이 파일의 `down_revision` 과 같은지(아래 읽기 전용 SELECT) 본다 — 다르면
  다른 런의 리비전이 먼저 들어간 것이니 이 리비전을 그 위로 다시 잇는다.
- **되돌리기**: 1순위는 이미지만 되돌리기다(downgrade 없이 — 옛 코드는 두 표가 있어도 무해하다). 스키마까지 내리려면 순서가
  고정이다: ① 이 표를 읽는 코드가 서빙 중이면 그 코드의 revert 를 **먼저 모두 병합·배포**하거나(그 뒤 서빙 이미지가 표를 읽지
  않으면 다음 단계의 태그 롤백은 건너뛴다), 표를 읽지 않는 이미지로 태그 롤백(`DDONA_ROLLBACK=1`)한다 → ② 이 리비전을 아는
  이미지로 downgrade → ③ 스키마까지 지우는 revert 를 병합. 읽는 코드의 revert 를 ② 뒤로 미룰 수밖에 없으면 그것과 이 revert 를
  **PR 하나로 묶어** ③ 에서 한 번에 병합한다. ②~③ 사이에는 이 작업 자신의 다른 revert 를 포함해 **어떤 `main` 병합도 하지 않는다** —
  그 사이 배포가 `alembic upgrade head` 로 방금 내린 표를 다시 만들고, 이어지는 revert 배포가 "DB 리비전을 모른다"로 멈춘다.
- downgrade 는 **이력 행이 하나라도 있으면** 아무것도 바꾸기 전에 `RuntimeError` 로 멈춘다. 어드민이 한 번이라도 저장했으면 늘
  멈춘다 — 표를 비우는 저장도 이력 한 행을 남긴다. 그때는 스키마를 남긴다: 이미지만 되돌리고, 마이그레이션 파일·ORM 모델은 남긴 채
  코드만 revert 한다(남긴 리비전이 head 사슬에 그대로 있어 다음 배포의 `alembic upgrade head` 는 no-op 이다). 이력 행을 손 SQL 로
  지워 downgrade 를 통과시키지 않는다.
- downgrade 명령은 고정 id 가 아니라 **상대 지정**(`495e9a75bb46-1`, 한 단계 아래까지)으로 친다 — 병합 전 리베이스로 앞 리비전이
  바뀔 수 있다. 치기 직전에 서빙 이미지 안 이 파일의 `down_revision` 을 읽어 `alembic history` 의 바로 아래 리비전과 같은지 보고,
  이 리비전 **위에** 다른 런의 리비전이 쌓였으면(바로 위 프롬프트 판 표 리비전과 그 위 턴 기록 배정 칸 리비전 말고 다른 것이 history 에 보이면) downgrade 가
  그것까지 내리므로 스키마는 되돌리지 않고 위의 "스키마를 남긴다"로 간다. 판 표 리비전이 함께 올라 있으면 그 리비전 downgrade 의 멈춤
  조건도 함께 걸린다. 턴 기록 배정 칸 리비전(`265a8f26c44a`)이 위에 올라 있으면 상대 지정 downgrade 가 그 칸을 먼저 지우므로, 그 칸을
  매핑한 이미지부터 칸을 모르는 이미지로 내린 뒤 downgrade 한다 — 아니면 서빙 중인 이미지의 방 턴에서 턴 기록 INSERT·읽기가 실패한다.

```sh
# 병합 전·downgrade 전 — 읽기 전용: 지금 DB 리비전과 이력 행 수(두 번째는 이 리비전이 오른 뒤에만)
sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
  psql -U postgres -d ai_character_chat -At -c "SELECT version_num FROM alembic_version;"
sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
  psql -U postgres -d ai_character_chat -At -c "SELECT (SELECT count(*) FROM prompt_routes), (SELECT count(*) FROM prompt_route_revisions);"
# downgrade(백업 먼저, 이 리비전 파일이 든 이미지로)
sudo /opt/ddona/backup.sh --manual
sudo docker run --rm --network ddona_default --env-file /opt/ddona/.env <IMAGE>:<이 리비전을 아는 TAG> alembic history -r-3:current
sudo docker run --rm --network ddona_default --env-file /opt/ddona/.env <IMAGE>:<이 리비전을 아는 TAG> alembic downgrade 495e9a75bb46-1
```

**프롬프트 체인·섹션 판 표(`d0051f733bb7`) — 배포 · 되돌리기.** 프롬프트 체인((레인, 모델) 세트 줄기)과 섹션에 `major.minor.patch`
판을 매길 표 `prompt_set_semvers`·`prompt_section_semvers` 를 더하고, 지금 체인마다 활성인 게시 세트 하나와 그 섹션 전부를 1.0.0 으로
매긴다(백필). 이 배포부터 어드민 게시가 판을 매기고 게시 응답에 판 칸이 붙는다.
- 기존 `prompt_sets`·`prompt_sections` 의 칸과 정수 `version` 번호는 바꾸지 않는다(백필은 읽기만) — 정수 번호로 세트를 대조하는
  도구가 그대로 맞는다. 업그레이드 첫 문장이 `lock_timeout 5s` 라, 겹침 중 옛 이미지 어드민의 초안 저장·게시와 부딪쳐 5초 안에
  잠금을 못 잡으면 실패한다 — 다시 돌리면 된다.
- 기준판 FK(`base_set_id`, 다음 판의 기준이 된 세트)는 `NO ACTION` 이라 **판이 쌓인 세트는 지울 수 없다** — 그 세트를 지우면 판
  사슬이 끊기고, 그 위에 쌓인 나중 게시가 활성이라 지워도 서빙 문안이 되돌아가지 않기 때문이다. 세트 FK 는 둘 다 `ON DELETE CASCADE` 다.
- 🔴 앞으로 게시 세트를 넣는 문안 마이그레이션은 이 리비전 파일의 판 매기기 블록(`_assign_semver`)을 자기 파일에 복사해 세트를 넣은
  직후 부르고, downgrade 는 넣은 세트를 기준판으로 가리키는 판 행이 있으면 읽을 수 있는 오류로 멈추게 쓴다.

평상시 겹침 교체로 배포한다(`skip_overlap` 불필요): 겹침 동안 도는 옛 이미지는 두 표를 모르고 읽지도 쓰지도 않는다. 그동안(또는
이미지만 되돌린 동안) 옛 이미지가 게시한 세트는 판 행이 없을 뿐이고, 새 이미지의 다음 게시가 그 체인에서 판이 가장 큰 세트와
견주므로 그 사이의 변경이 다음 판에 함께 셈해진다. 판 행을 손으로 채우지 않는다.

- **병합 전**: 운영 최신 백업 성공을 보고, 운영 DB 리비전이 이 파일의 `down_revision`(보통 바로 위 모델 배정 표 리비전)과 같은지,
  체인마다 활성 게시 세트가 무엇인지 아래 읽기 전용 SELECT 로 본다.
- **되돌리기**: 1순위는 이미지만 되돌리기다(downgrade 없이). 이 리비전을 아는 이미지에서 모르는 이미지로 갈 때는 교체 스크립트가 DB 리비전을
  모른다고 판정하므로 `DDONA_ROLLBACK=1` 이 필요하다. 스키마까지 내리는 순서는 위 모델 배정 표 문단과 같다 — 판 표를 읽는 게시
  코드의 revert 를 먼저 모두 병합·배포하거나 태그 롤백 → 이 리비전을 아는 이미지로 downgrade → 스키마 revert 병합, 묶을 수밖에
  없으면 revert 를 PR 하나로, downgrade 와 스키마 revert 사이에는 어떤 `main` 병합도 하지 않는다.
- downgrade 는 **단계(`level`)가 있는 체인 판(= 배포 뒤 실제 게시로 매긴 판)이 하나라도 있으면** 아무것도 바꾸기 전에 `RuntimeError`
  로 멈춘다. 배포 뒤 게시가 한 번이라도 있었으면 사실상 늘 멈춘다. 그때의 대체 절차는 위와 같다 — 이미지만 되돌리고, 마이그레이션
  파일·ORM 모델은 남긴 채 게시 코드만 revert 한다. 판 행을 손 SQL 로 지워 downgrade 를 통과시키지 않는다.
- downgrade 명령은 상대 지정 `d0051f733bb7-1` 로 친다. 치기 직전에 서빙 이미지 안 이 파일의 `down_revision` 을 읽어 `alembic history`
  의 바로 아래 리비전과 같은지 보고, 그 사이나 이 리비전 위에 다른 런의 리비전이 끼었는지 본다. 바로 위 턴 기록 배정 칸 리비전
  (`265a8f26c44a`) 말고 다른 것이 위에 쌓였으면 downgrade 가 그것까지 내리므로 스키마를 남긴다. 턴 기록 배정 칸 리비전만 위에 올라
  있으면 상대 지정 downgrade 가 그 칸을 먼저 지우므로, 그 칸을 매핑한 이미지부터 칸을 모르는 이미지로 내린 뒤 downgrade 한다 —
  아니면 서빙 중인 이미지의 방 턴에서 턴 기록 INSERT·읽기가 실패한다.

```sh
# 병합 전·downgrade 전 — 읽기 전용: 지금 DB 리비전, 체인마다 활성 게시 세트, (이 리비전이 오른 뒤) 게시로 매긴 판 수
sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
  psql -U postgres -d ai_character_chat -At -c "SELECT version_num FROM alembic_version;"
sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
  psql -U postgres -d ai_character_chat -At -c \
  "SELECT DISTINCT ON (lane, model) lane, model, id, version, published_at FROM prompt_sets WHERE status = 'published' ORDER BY lane, model, published_at DESC, id DESC;"
sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
  psql -U postgres -d ai_character_chat -At -c "SELECT count(*), count(level) FROM prompt_set_semvers;"
# downgrade(백업 먼저, 이 리비전 파일이 든 이미지로)
sudo /opt/ddona/backup.sh --manual
sudo docker run --rm --network ddona_default --env-file /opt/ddona/.env <IMAGE>:<이 리비전을 아는 TAG> alembic history -r-3:current
sudo docker run --rm --network ddona_default --env-file /opt/ddona/.env <IMAGE>:<이 리비전을 아는 TAG> alembic downgrade d0051f733bb7-1
```

**턴 기록 단계별 배정 칸(`265a8f26c44a`) — 배포 · 되돌리기.** 턴 기록 `chat_turns` 에 `stage_routes` 칸(JSONB, NOT NULL, 서버 기본값
`[]`)을 더한다. 이 배포부터 방 턴(보내기·수정·재생성)이 그 레인의 단계마다 읽은 체인·세트 id·부를 모델·경로·출처(배정 표 행·물려받은
행·모델 설정·방 모델, 건너뛴 행이면 그 단계와 이유)를 한 칸씩 적는다. 배정 표가 비어도 출처 `env`·`room` 칸으로 늘 채운다. 판 번호는
싣지 않는다(세트 id 로 판 표와 잇는다). 미리보기는 지금처럼 턴 기록이 없다. 같은 배포에서 측정 서버의 프롬프트 덤프
(`PROMPT_DUMP_PATH`)는 행이 적용된 생성·판정 줄에만 `promptSetId`·`chainModel`·`routeSource` 를 더한다 — 운영은 덤프 경로가 없어
해당 없다. `llm_calls` 칸의 모양은 바꾸지 않는다.
- 업그레이드 첫 문장이 `lock_timeout 5s` 다. 상수 기본값 칸 추가라 표를 다시 쓰지는 않지만 `chat_turns` 에 `ACCESS EXCLUSIVE` 를
  잠깐 잡아야 해서, 이 표를 만진 채 열려 있는 트랜잭션(턴 쓰기 구간, 재생성·되돌리기의 기록 읽기, 원가 보기 스크립트)이 끝나기를
  기다리고 그동안 뒤의 턴 쓰기가 줄을 선다. 5초 안에 못 잡으면 실패한다 — 다시 돌리면 된다.

평상시 겹침 교체로 배포한다(`skip_overlap` 불필요): 겹침 동안 도는 옛 이미지는 칸을 모르고, 그 턴 기록 INSERT 는 칸을 빼고 나가
기본값 `[]` 이 들어간다.

- **병합 전**: 운영 최신 백업 성공을 보고, 운영 DB 리비전이 이 파일의 `down_revision`(보통 바로 위 판 표 리비전)과 같은지 아래 읽기
  전용 SELECT 로 본다 — 다르면 다른 런의 리비전이 먼저 들어간 것이니 이 리비전을 그 위로 다시 잇는다.
- **되돌리기**: 1순위는 이미지만 되돌리기다(downgrade 없이 — 옛 코드는 이 칸이 있어도 돈다). 이 리비전을 아는 이미지에서 모르는
  이미지로 갈 때는 `DDONA_ROLLBACK=1` 이 필요하다. 스키마까지 내리려면 순서가 고정이다: ① 칸을 쓰는 코드의 revert 를 먼저 모두
  병합·배포하거나 칸을 모르는 이미지로 태그 롤백한다 — 칸을 매핑한 이미지가 서빙 중에 칸을 지우면 그 이미지의 턴 기록 INSERT 와
  기록 읽기가 실패해 모든 방 턴의 쓰기 구간이 깨진다 → ② 이 리비전을 아는 이미지로 downgrade → ③ 스키마까지 지우는 revert 를 병합.
  ②~③ 사이에는 어떤 `main` 병합도 하지 않는다(그 사이 배포의 `alembic upgrade head` 가 칸을 다시 만든다).
- downgrade 는 칸만 지우고 멈춤 조건이 없다. 버리는 것은 턴마다의 배정 스냅샷이라 사용자에게 보이지 않지만, 다시 올려도 돌아오지
  않는다(그 사이와 그 전 행은 `[]`). 배정 표 행이 어느 턴에 적용됐는지 되짚어야 할 일이 남았으면 내리기 전에 필요한 행을 따로 뽑아 둔다.
- downgrade 명령은 상대 지정 `265a8f26c44a-1` 로 친다. 치기 직전에 서빙 이미지 안 이 파일의 `down_revision` 을 읽어 `alembic history`
  의 바로 아래 리비전과 같은지 보고, 이 리비전 위에 다른 런의 리비전이 쌓였으면 downgrade 가 그것까지 내리므로 스키마는 되돌리지
  않고 이미지만 되돌린다. 아래 두 리비전(판 표·모델 배정 표)을 상대 지정으로 내리면 이 리비전이 먼저 내려가므로, 그때도 위 ① 의
  순서(칸을 쓰는 이미지를 먼저 내림)를 지킨다.

```sh
# 병합 전·downgrade 전 — 읽기 전용: 지금 DB 리비전, (이 리비전이 오른 뒤) 칸이 찬 턴 기록 수
sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
  psql -U postgres -d ai_character_chat -At -c "SELECT version_num FROM alembic_version;"
sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
  psql -U postgres -d ai_character_chat -At -c "SELECT count(*), count(*) FILTER (WHERE stage_routes <> '[]'::jsonb) FROM chat_turns;"
# downgrade(백업 먼저, 이 리비전 파일이 든 이미지로)
sudo /opt/ddona/backup.sh
sudo docker run --rm --network ddona_default --env-file /opt/ddona/.env <IMAGE>:<이 리비전을 아는 TAG> alembic history -r-3:current
sudo docker run --rm --network ddona_default --env-file /opt/ddona/.env <IMAGE>:<이 리비전을 아는 TAG> alembic downgrade 265a8f26c44a-1
```

### 3-13. 노벨(공개 소설) 켜기 · 끄기

노벨은 소설화를 쓸 수 있는 계정이 자기 소설을 공개하는 기능이라 두 겹으로 닫혀 있다 — 소설화 세 겹("소설화 켜기 · 끄기 ·
회수 · 롤백" 절)과 노벨 스위치 `NOVEL_PUBLIC_ENABLED`. 코드 기본값이 꺼짐이라 **배포만으로는 닫힌 채 뜬다.** 꺼진 동안
공개(`POST /novels/{id}/publication`)·게시자의 공개 상태 조회(`GET /novels/{id}/publication`)는 403
`NOVEL_PUBLIC_DISABLED` 다. 공개 거두기(`POST /novels/{id}/publication/withdraw`)는 스위치·소설화 허용과 무관하게 소유자면
된다 — 자기 글을 내리는 일이라 소설 삭제와 같은 원칙이다.

공개·다시 공개는 Gemini 텍스트 심사를 부른다(호출 위치 `novel_publish_screen`, 모델은 발행 심사와 같은
`GEMINI_PUBLISH_FILTER_MODEL_NAME`, 없으면 `GEMINI_MODEL_NAME`). 심사 문안은 프롬프트 세트의 `novel_screen` 레인(Gemini 세트
하나)에 있고 캐시 없이 호출마다 DB 에서 읽는다. 심사 호출이 실패하면 공개하지 않고 503 `NOVEL_SCREENING_UNAVAILABLE` 이다
(Bugsink 태그는 발행 심사와 같은 `gemini`·`gemini_rate_limit`). 심사에 걸린 횟수는 게시자마다 KST 하루 상한이 있고, 심사
호출 자체도 통과·거부·장애를 가리지 않고 게시자당 시간당 10회까지다(429 `window` 는 하루 거절 상한이 `"novel_screen_daily_reject"`,
시간당 호출 상한이 `"novel_screen_hourly"` 이고, 레이트리밋 면제 계정 제외).

**켜기 — 미리보기 → 전체 공개.** 약관·처리방침의 공개 소설 조항이 시행되기 전에는 운영자 계정만 쓰도록 미리보기 명단
`NOVEL_PUBLIC_PREVIEW_ALLOWLIST`(계정 id, 쉼표 구분)와 함께 켜고, 시행일에 명단 줄을 지워 모두에게 연다. 명단이 비어 있지
않은 동안에는 명단의 로그인 회원만 노벨을 쓴다 — 독자 라우트 전부(목록·홈 노벨·작품 정보·화·구매·읽은 자리·좋아요·댓글·
신고)와 게시자의 공개·다시 공개·공개 상태 조회. 그 밖의 회원과 비로그인은 스위치를 끈 것과 같은 응답을 받는다(아래 "끄기"의
404·403·410). 인증 없는 `GET /clover/pricing` 의 `novelPublicEnabled` 는 누가 보는지 모르므로 명단이 있는 동안 `false` 라
탭·홈 노벨·가격 행이 모두에게 숨고, 명단 회원의 화면은 `GET /me` 의 `novelPublicEnabled`(`true`)로 탭을 연다. 공개 거두기는
명단과도 무관하게 소유자면 된다.

`.env` 에 줄을 더한다(파일을 통째로 덮거나 백업본으로 복원하지 않는다 — 교체 스크립트가 같은 파일의 `API_IMAGE_BLUE`·
`API_IMAGE_GREEN` 을 고친다). 먼저 미리보기로 켠다. 줄을 더하기 **전에** 서빙 중인 색의 이미지가 명단을 아는 판인지
확인한다 — 명단 설정이 없는 옛 이미지라면 `AttributeError` 로 끝나고, 그 상태에서 줄을 더해 올리면 모두에게 열린다. 끝에
`ok` 가 찍힐 때만 다음 줄로 간다:

```sh
cd /opt/ddona/app
sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env exec -T api_$(sudo bash ops/active-color.sh) \
  python -c "from api.core.config import settings; settings.novel_public_preview_allowlist; print('ok')"
sudo sh -c 'printf "\nNOVEL_PUBLIC_ENABLED=true\nNOVEL_PUBLIC_PREVIEW_ALLOWLIST=<계정 id>,<계정 id>\n" >> /opt/ddona/.env'
sudo python3 ops/check_env.py --format /opt/ddona/.env
sudo bash ops/swap-api.sh
sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env exec -T api_$(sudo bash ops/active-color.sh) \
  python -c "from api.core.config import settings; print(settings.novel_public_enabled, settings.novel_public_preview_allowlist)"
```

명단 밖 계정(또는 로그아웃 상태)으로 `/webnovels` 가 찾을 수 없는 화면이고 헤더에 노벨 탭이 없는지, 명단 계정으로는 탭이
보이고 읽히는지 본다. 약관 시행일이 되면 명단 줄을 지우고 다시 올려 모두에게 연다 — 값을 비운 줄(`…ALLOWLIST=`)은
`check_env.py` 의 `empty-value` 위반이라 줄째 지운다:

```sh
cd /opt/ddona/app
sudo sed -i '/^NOVEL_PUBLIC_PREVIEW_ALLOWLIST=/d' /opt/ddona/.env
sudo python3 ops/check_env.py --format /opt/ddona/.env
sudo bash ops/swap-api.sh
sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env exec -T api_$(sudo bash ops/active-color.sh) \
  python -c "from api.core.config import settings; print(settings.novel_public_enabled, settings.novel_public_preview_allowlist)"
```

`True []` 가 나오면 전체 공개다. 다시 운영자만으로 좁히려면 명단 줄을 같은 방법으로 다시 넣고 올린다(공개 상태·구매·댓글은
그대로 남고, 명단 밖 회원은 그동안 스위치를 끈 것과 같은 응답을 받는다).

🔴 **명단 줄이 있는 동안 이 기능보다 옛 이미지로 되돌리면 모든 회원에게 열린다.** 옛 코드는 명단 키를 모르고 버린 채
(`Settings` 가 모르는 키를 무시한다) `NOVEL_PUBLIC_ENABLED=true` 만 읽는다. 미리보기 동안 다른 이유로 롤백할 때도 먼저
`NOVEL_PUBLIC_ENABLED` 줄부터 지운 뒤(`sudo sed -i '/^NOVEL_PUBLIC_ENABLED=/d' /opt/ddona/.env`) 롤백한다.

`restart` 는 env 를 다시 읽지 않으므로 교체 스크립트를 태그 없이 불러 새 env 로 다시 띄운다("env 반영 재기동" 절). 줄을 더하거나
지울 때마다 "BE 런타임" 절의 키 개수 문장을 VM 에서 다시 세어 고친다.

**끄기** — 스위치 줄(미리보기 명단 줄이 있으면 그것도)을 지우고 다시 올린다:

```sh
cd /opt/ddona/app
sudo sed -i '/^NOVEL_PUBLIC_ENABLED=/d;/^NOVEL_PUBLIC_PREVIEW_ALLOWLIST=/d' /opt/ddona/.env
sudo python3 ops/check_env.py --format /opt/ddona/.env
sudo bash ops/swap-api.sh
```

공개 상태·화 공개본·심사 기록과 구매(소장)·댓글·신고 기록은 남아 다시 켜면 그대로 돌아온다. 꺼진 동안 독자 라우트
(`/webnovels` 목록·홈 노벨·좋아요와 좋아요 취소·읽은 자리·화 구매·화 댓글 목록과 쓰기·노벨 신고·댓글 신고)는 404
`NOVEL_PUBLIC_DISABLED` 다. 내 댓글 지우기(`DELETE /webnovels/{id}/comments/{id}`)와 어드민 노벨 화면·조치는 스위치와
무관하게 된다. 작품 정보·화 읽기는 그 소설을 소장한 회원에게 410 `NOVEL_READING_ENDED`(`reason: "service_off"`),
나머지에게 404 다. 화면은 인증 없는 `GET /clover/pricing` 의 `novelPublicEnabled` 로 노벨 탭을 숨긴다. 줄을 지웠으니 키 개수
문장을 다시 센다.

**공개 정책 스위치(`NOVEL_PUBLIC_POLICY_V2_ENABLED`) 켜기 · 끄기** — 첫 공개 운영자 승인과 연재권 잠금, 그리고 산 사람
보호(산 때의 판 고르기, 거둠·게시자 정지·판매된 소설 삭제·게시자 탈퇴 뒤에도 소장자 열람 유지, 노벨 이용제한·원작 이용제한·
원작 삭제 때 환급, 판매된 소설 삭제와 게시자 탈퇴는 판매된 소설을 숨김)의 효력을 켠다(키 표의 설명). 개정 약관(승인 반려의 이의제기 경로, 연재권 조항)이 시행된 뒤에, 그리고 어드민의 승인 대기열 화면과 작가의 대기·반려
표시 화면이 배포된 뒤에 켠다 — 화면이 없으면 작가에게 대기 행이 "거둠"으로 보이고 운영자는 승인할 화면이 없다. 🔴 탈퇴한
작가의 팔린 소설을 숨겨 남기는 판부터는 두 가지가 더 먼저다: 그렇게 남긴 소설에서 작가 전용 데이터를 지우는 코드가 서빙 중인
이미지에 있고(탈퇴가 숨길 때 스냅숏·인물 카드·작가 읽은 자리·설정 노트·주인공 이름·작업본 제목과 소개·편집 보드·표지 연결·
공개되지 않은 화와 개정·화의 작업본 제목과 요약과 작가의 말을 지운다 — 남는 것은 공개 상태·화 공개본·판 행과 그 본문, 원작
사본·권리 잠금 칸, 남는 화와 소설 단위의 운영자 심사 기록, 신고 기록 — 공개되지 않은 화의 심사 기록은 그 화와 함께 지운다), 처리방침에 탈퇴 뒤에도 남는 정보(판매된 소설의 공개본·판, 작가 식별 정보 없이)가
개정·시행된 뒤에 켠다 — 그 전에 켜면 탈퇴한 작가의 소설이 작가 전용 데이터째 남거나 처리방침에 없는 보존이 된다. 정리 코드가
없는 옛 이미지가 배포 겹침 동안 숨긴 소설은 다음 날 "숨긴 소설 파기 — purge cron" 이 같은 정리를 한다. 🔴 다시 공개 때의
변경 요약을 받는 판부터는 셋이 더 먼저다: 요약 입력 칸을 보내는 web 작가 화면이 배포됐고(없으면 이미 공개한 화의 다시 공개가
모두 422 `NOVEL_CHANGE_SUMMARY_REQUIRED` 다), 어드민 `/prompt-sets` 의 `novel_screen` 지시문이 머리 줄 키 목록에
`change_summary(변경 요약)` 를 더한 판으로 게시됐고(지금 지시문은 키 다섯 개만 나열한다 — 판정은 그대로 되지만 요약만 걸렸을 때
모델이 짚는 자리가 빗나가 작가에게 고칠 곳을 잘못 알릴 수 있다), 처리방침의 국외 이전 항목("공개할 글")에 변경 요약이 들어간
판이 시행됐다(요약도 글 심사 모델로 간다). 순서가 고정이다(끝에 `ok` 가 찍힐 때만 다음 줄로 간다):

1. 옛 이미지가 내려갔는지 확인한다 — 서빙 중인 색의 이미지가 스위치를 아는 판인지 본다. 잠금을 모르는 옛 이미지가 남아 있는
   동안의 첫 공개는 잠금 없이 생기므로 2 를 그 뒤에 돌려야 한다.
2. 연재권 잠금 백필을 다시 돌린다. 문장은 마이그레이션 `6fbf1e9a65b8` 의 `BACKFILL_SERIAL_LOCK_SQL` 하나다(멱등 — 이미 잠긴
   소설과 대기·반려 행은 건드리지 않는다). 배포 겹침 동안 옛 이미지가 만든 첫 공개가 여기서 잠긴다 — 빠뜨리면 그 소설은
   켠 뒤에도 잠기지 않은 채라 원작자가 허락을 거두면 다음 화가 막힌다(다음 공개가 그 순간을 잠금 시각으로 찍는다). 출력의 `UPDATE n` 이 잠근 소설 수다.
3. 판 행 백필을 다시 돌린다. 문장은 마이그레이션 `d77bce2bba4c` 의 `BACKFILL_CHAPTER_EDITIONS_SQL` 하나다(멱등 — 이미 있는
   판 행은 바꾸지 않고 없는 판만 더한다). 배포 겹침 동안 옛 이미지가 다시 공개한 판은 판 행 없이 올라가는데, 그 판을 산
   사람은 켠 뒤 "산 때의 판" 대신 그 화의 가장 오래된 판을 받는다. 출력의 `INSERT 0 n` 이 채운 판 수다.
4. 앞 화 가격 백필을 다시 돌린다. 문장은 마이그레이션 `3b4b814583dc` 의 `BACKFILL_FREE_CHAPTER_PRICE_SQL` 하나다(멱등 — 이미
   0 인 행은 건드리지 않는다). 배포 겹침 동안 가격 칸을 모르는 옛 이미지가 공개한 앞 화(1~5화)는 칸 기본값 30 을 받는다. 읽는
   쪽은 앞 화를 칸과 무관하게 무료로 판정하므로 독자 화면은 이미 맞고, 이 단계는 칸 값을 화면과 같게 맞추는 정리다. 출력의
   `UPDATE n` 이 고친 화 수다.
5. 무료 번호 백필을 다시 돌린다. 문장은 마이그레이션 `2975c3a6fa6f` 의 `BACKFILL_FREE_ORDINALS_SQL` 하나다(멱등 — 이미
   남긴 번호는 그대로다). 6화 이후 무료 화는 스위치가 켜져 있을 때만 생기므로 처음 켤 때는 대개 `INSERT 0 0` 이다. 스위치가
   켜진 채 배포한 적이 있으면 겹침 동안 무료 번호 표를 모르는 옛 이미지가 무료로 만든 번호가 여기서 채워진다 — 빠뜨리면 그
   화를 지우고 다시 만들 때 유료로 낼 수 있다.
6. 닫혔는데 환급되지 않은 구매를 센다(읽기 전용). 스위치가 꺼진 동안의 노벨 이용제한·원작 이용제한·원작 삭제는 환급하지
   않는다 — 켠 뒤 그 소장자는 410 을 받는데, 환급할 쓰기가 다시 오지 않는다. 출력이 `0` 이면 7 로 간다. 0 이 아니면 같은
   조건에서 `count(*)` 를 `p.novel_id, n.content_id` 로 바꿔 대상을 적어 두고 7 로 간 뒤, 켠 상태에서 그 노벨·원작을 어드민에서
   해제했다가 다시 제한해 환급한다(꺼진 동안의 해제·재제한은 환급하지 않는다). 다시 세어 0 인지 본다. 스위치가 꺼진 동안의
   게시자 탈퇴는 지금 약관대로 환급 없이 소설을 지웠으므로 이 수에 들지 않는다. 원작 상태는 DB 에 대문자 라벨(`NORMAL`·
   `RESTRICTED`·`DELETED`)로, 노벨 공개의 운영 상태는 소문자(`normal`·`restricted`)로 저장된다. 이 수에는 이용제한된
   노벨(`np.moderation_status = 'restricted'`)의 미환급 구매도 든다 — 켠 뒤 작가의 노벨 공개 칸은 이용제한된 노벨에 "쓴
   클로버는 돌려드렸어요"라고 말하므로, 그런 노벨이 하나라도 남으면 해제·재제한으로 환급할 때까지 그 문장이 거짓이다.
   판매만 멈추기로 하고 제한·삭제한 원작(`novel_buyers_kept`)은 소장자가 계속 읽으므로 빼고 센다(켠 동안에만 생긴다).
7. 스위치 줄을 더하고 올린다.

```sh
cd /opt/ddona/app
C="sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env"
$C exec -T api_$(sudo bash ops/active-color.sh) \
  python -c "from api.core.config import settings; settings.novel_public_policy_v2_enabled; print('ok')"
$C exec -T api_$(sudo bash ops/active-color.sh) python -c \
  "import runpy; print(runpy.run_path('migrations/versions/6fbf1e9a65b8_novel_serial_lock_and_publication_review.py')['BACKFILL_SERIAL_LOCK_SQL'])" \
  | $C exec -T postgres psql -U postgres -d ai_character_chat -v ON_ERROR_STOP=1
$C exec -T api_$(sudo bash ops/active-color.sh) python -c \
  "import runpy; print(runpy.run_path('migrations/versions/d77bce2bba4c_novel_editions_and_buyer_protection.py')['BACKFILL_CHAPTER_EDITIONS_SQL'])" \
  | $C exec -T postgres psql -U postgres -d ai_character_chat -v ON_ERROR_STOP=1
$C exec -T api_$(sudo bash ops/active-color.sh) python -c \
  "import runpy; print(runpy.run_path('migrations/versions/3b4b814583dc_novel_chapter_price.py')['BACKFILL_FREE_CHAPTER_PRICE_SQL'])" \
  | $C exec -T postgres psql -U postgres -d ai_character_chat -v ON_ERROR_STOP=1
$C exec -T api_$(sudo bash ops/active-color.sh) python -c \
  "import runpy; print(runpy.run_path('migrations/versions/2975c3a6fa6f_novel_free_ordinals.py')['BACKFILL_FREE_ORDINALS_SQL'])" \
  | $C exec -T postgres psql -U postgres -d ai_character_chat -v ON_ERROR_STOP=1
$C exec -T postgres psql -U postgres -d ai_character_chat -At -v ON_ERROR_STOP=1 <<'SQL'
SELECT count(*) FROM novel_purchases p
JOIN novels n ON n.id = p.novel_id
JOIN novel_publications np ON np.novel_id = n.id
LEFT JOIN contents c ON c.id = n.content_id
WHERE p.refunded_at IS NULL AND p.buyer_user_id IS NOT NULL
  AND (np.moderation_status = 'restricted'
       OR c.id IS NULL
       OR (c.moderation_status <> 'NORMAL' AND NOT c.restricted_by_suspension AND NOT c.novel_buyers_kept));
SQL
sudo sh -c 'printf "\nNOVEL_PUBLIC_POLICY_V2_ENABLED=true\n" >> /opt/ddona/.env'
sudo python3 ops/check_env.py --format /opt/ddona/.env
sudo bash ops/swap-api.sh
$C exec -T api_$(sudo bash ops/active-color.sh) \
  python -c "from api.core.config import settings; print(settings.novel_public_policy_v2_enabled)"
```

`True` 가 나오면 켜졌다. 새 소설의 첫 공개가 어드민 노벨 목록의 승인 대기(`reviewStatus=pending`)에 들어오는지 본다. 줄을
더했으니 "BE 런타임" 절의 키 개수 문장을 다시 센다. 열려 있던 어드민 탭은 새로고침한다 — 어드민은 스위치 값을 로그인
세션 응답(`GET /admin/me`)에서 한 번만 읽어(새로 묻지 않는다) 이용제한·작품 조치 확인의 환급 문장이 새로고침 전까지 옛
스위치 값으로 남는다. web 은 가격 응답(`GET /clover/pricing`)에서 읽어 다음에 다시 받을 때 바뀐다.

운영은 2026-10-25 에 1~7 을 이 순서로 마치고 켰다(백필 넷 모두 0행, 6 의 미환급 구매 0).

**끄기·롤백 — 스위치 줄부터.** 🔴 운영은 켜져 있다. 끄기는 롤백의 고정 첫 단계가 아니라, 아래 소장자 수를 센 뒤 따로 정하는
단계다 — 켠 뒤 끄면 숨긴 소설·판매를 멈춘 노벨 등의 소장자가 환급 없이 410 을 받는다(아래). 무관한 사유의 태그 롤백은 스위치를
아는 판(`d0fd0ac` 이상)으로 끄지 않고 한다(그 판이 모르는 칸은 아래 🔴 단락들대로 따로 센다). 운영 api 이미지는 `d0fd0ac` 아래로
되돌리지 않는다 — `d0fd0ac` 은 두 블록 칸을 NOT NULL 로 좁힌 지금 스키마에서 화 개정을 채워 쓰는 가장 옛 판이고, 두 칸을 모르는
옛 이미지는 개정 INSERT 가 실패한다(위 「삽화 스키마(`b871b88d2a90`) 이후의 경계」).
끄면 지금 약관 동작으로 돌아간다 — 첫 공개가 바로 열리고 잠긴 소설도 허락을 거두면 다음 화가
막힌다. 남은 승인 대기 행은 독자에게 보이지 않은 채 남고, 작가가 다시 신청하면 처음 공개처럼 원작 허락·목록 판정을 거쳐
바로 공개된다. 운영자의 승인·반려는 스위치와 무관하게 계속 된다.

산 사람 보호도 함께 꺼진다. 켜져 있는 동안 거둔 소설·게시자가 정지된 소설·원작자 정지로 일괄 제한된 원작의 소설·숨긴 소설
(판매된 소설 삭제, 게시자 탈퇴로 숨겨 남긴 소설)·운영자가 판매를 멈춘 노벨·판매만 멈추기로 하고 제한·삭제한 원작의 소설의
소장자는 끄는 순간 환급 없이 410 을 받는다(탈퇴로 숨긴 소설은 이유 `publisher_withdrawn`, 판매 중단 노벨은 `restricted`) — 그
소장을 끝낸 쓰기는 이미 지나가서 환급할 쓰기가 다시
오지 않는다. 판매를 멈춘 노벨은 끈 뒤에도 목록·구매 밖에 남고(그 칸은 스위치와 무관하다) 판매 중단·재개는 409 라 풀 수 없다 —
다시 팔 노벨은 끄기 전에 어드민에서 재개한다. 숨긴 소설은 그 소장자들의 구매가 미환급으로 남으므로 파기 크론("숨긴 소설 파기 — purge cron" 절)도 지우지
않고 남겨 둔다. 그래서 끄기는 롤백 때만 하고, 끄기 전에 아래로 그런 소장자가 몇 명인지 본다(0 이 아니면 다시 켤 때까지
그 사람들은 읽지 못한다). 끈 동안 판매된 소설 삭제는 다시 진짜 삭제 + 환급이고, 게시자 탈퇴는 판매된 소설까지 환급 없이
지우며, 운영자 제재는 환급하지 않는다. 끈 동안에는 잠긴 소설도 원작이 비공개·원작자 탈퇴면 다음 화가 막히고, 원작자 탈퇴
뒤의 새 소설화도 다시 된다.

```sql
SELECT count(DISTINCT p.buyer_user_id) FROM novel_purchases p
JOIN novels n ON n.id = p.novel_id
JOIN novel_publications np ON np.novel_id = n.id
JOIN users u ON u.id = n.user_id
LEFT JOIN contents c ON c.id = n.content_id
WHERE p.refunded_at IS NULL AND p.buyer_user_id IS NOT NULL
  AND (np.visibility = 'withdrawn' OR n.hidden_at IS NOT NULL OR u.suspended_at IS NOT NULL
       OR c.restricted_by_suspension OR np.sales_stopped_at IS NOT NULL
       OR (c.novel_buyers_kept AND c.moderation_status <> 'NORMAL'));
```

```sh
cd /opt/ddona/app
sudo sed -i '/^NOVEL_PUBLIC_POLICY_V2_ENABLED=/d' /opt/ddona/.env
sudo python3 ops/check_env.py --format /opt/ddona/.env
sudo bash ops/swap-api.sh
```

끈 뒤에도 열려 있던 어드민 탭은 새로고침한다(켤 때와 같은 이유).

🔴 **게시자 탈퇴로 숨겨 남긴 소설이 생긴 뒤 이미지를 그 판(탈퇴가 판매 소설을 숨기는 판)보다 옛 것으로 되돌리면** 옛 코드의
소장자 조건이 탈퇴한 게시자를 빼므로, 스위치가 켜져 있어도 그 소설의 소장자는 환급 없이 410(`withdrawn`)을 받는다. 숨긴 채
남은 소설은 파기 크론이 지우지 않는다(미환급 구매가 남아 있다). 되돌리기 전에 그 소장자 수를 센다 — 0 이 아니면 되돌리지
않거나, 되돌린 동안 그 사람들이 읽지 못하는 것을 감수한다(새 이미지로 돌아오면 다시 읽는다):

```sql
SELECT count(DISTINCT p.buyer_user_id) FROM novel_purchases p
JOIN novels n ON n.id = p.novel_id
JOIN users u ON u.id = n.user_id
WHERE p.refunded_at IS NULL AND p.buyer_user_id IS NOT NULL
  AND n.hidden_at IS NOT NULL AND u.deleted_at IS NOT NULL;
```

탈퇴가 숨길 때 작가 전용 데이터를 지우는 판보다 옛 이미지(숨기기만 하는 판)로 되돌린 동안에는 스위치가 켜져 있으면 탈퇴한
작가의 숨긴 소설이 작가 전용 데이터째 남는다. 새 이미지로 돌아오면 다음 날 파기 크론이 정리한다 — 되돌린 기간이 길면 스위치를
먼저 끈다. 정리된 소설은 옛 이미지에서도 그대로 읽힌다(남은 칸만 읽는다). 작가가 지워 숨길 때도 같은 정리를 하는 판보다 옛
이미지로 되돌린 동안에는 작가가 지운 판매 소설이 작가 전용 데이터째 숨겨지고, 그 옛 이미지의 크론은 탈퇴한 게시자의 소설만
정리하므로 남는다 — 새 이미지로 돌아오면 다음 날 크론이 정리한다.

🔴 **운영자 판매 중단(마이그레이션 `e9ad8ed93e90` — 노벨 `sales_stopped_at`, 원작 `novel_buyers_kept`)이 쓰인 뒤 이미지를 그
판보다 옛 것으로 되돌리면** 옛 코드가 두 칸을 모른다. 판매를 멈춘 노벨은 옛 목록 조건에 다시 걸려 **목록에 다시 나오고 다시
팔린다**(그동안 산 구매는 새 이미지로 돌아와도 그대로 소장이다). 원작을 제한·삭제하면서 파생 소설은 판매만 멈추기로 고른
원작의 소장자는 옛 소장자 조건이 표식을 몰라 **환급 없이** 410(`source_unavailable`)을 받는다(새 이미지로 돌아오면 다시 읽는다).
판매 중단·재개 감사 로그가 있으면 그 게시자의 어드민 회원 상세가 500 이다(옛 코드가 새 조치 종류를 모른다). 이 칸들은 공개 정책
스위치가 켜져 있는 동안에만 쓰이므로 한 번도 켠 적이 없으면 셋 다 0 이다(켰다 끈 뒤에는 남아 있을 수 있다). 되돌리기 전에
센다(읽기 전용). 첫 수가 0 이 아니면 되돌리지 않거나, 그 노벨들을 먼저 어드민에서 재개한다(이용제한을 함께 걸어도 판매 중단
칸은 남는다 — 옛 이미지도 이용제한은 알아 다시 팔리지는 않지만, 이용제한은 소장자 구매를 환급하고 수는 그대로다). 둘째 수가 0 이 아니면 그 원작 소장자가
되돌린 동안 읽지 못하는 것을 감수한다. 셋째 수(감사 로그)는 지울 수 없어 한 번 생기면 0 으로 돌아오지 않는다 — 되돌린 동안 그
게시자들의 어드민 회원 상세가 500 인 것을 감수한다(독자 영향은 없다):

```sql
SELECT
  (SELECT count(*) FROM novel_publications WHERE sales_stopped_at IS NOT NULL) AS sales_stopped_novels,
  (SELECT count(*) FROM contents WHERE novel_buyers_kept AND moderation_status <> 'NORMAL') AS kept_sources,
  (SELECT count(*) FROM admin_action_logs WHERE action_type IN ('novel-sales-stop', 'novel-sales-resume')) AS sales_stop_logs;
```

이 판을 처음 배포하는 겹침 동안에는 스위치가 꺼져 있어 두 칸을 쓰는 쓰기가 409 라 옛 이미지와 어긋날 것이 없다. 스위치가 켜진
채 배포하면 겹침(1분 안팎) 동안 위 되돌리기와 같은 일이 옛 색에서 생길 수 있다. 마이그레이션까지 downgrade 하면 두 칸이 사라져
같은 결과가 영구가 된다(판매 중단 기록도 사라진다) — 이미지만 되돌린다.

🔴 **변경 요약(마이그레이션 `f89a3d8ed3a8` — 판 행 `change_summary`, 심사 기록 자리 `change_summary`)이 쓰인 뒤 이미지를 그 판보다
옛 것으로 되돌리면** 옛 코드가 요약 자리를 모른다. 짚은 자리에 `change_summary` 가 든 심사 거부 기록(요약만 걸렸든 다른
자리와 함께 걸렸든)이 그 소설의 최근 심사이면 작가의 공개 상태 조회·공개·무료로 전환 응답이 500 이고(셋 다 공개 상태를
돌려주는데 옛 응답 검증이 그 자리 값을 모른다), 그 기록이 최근 심사 20건 안에 있는 노벨의 어드민 상세도 500 이다. 판 행의 요약은 옛 코드가
읽지 않아 독자 판 고르기에서 요약만 사라진다(새 이미지로 돌아오면 다시 보인다). 요약은 공개 정책 스위치가 켜졌을 때만 받으므로
한 번도 켠 적이 없으면 아래 수는 0 이다. 되돌리기 전에 센다(읽기 전용) — 0 이 아니면 되돌리지 않거나, 그 작가들이 다시 공개해
최근 심사가 바뀔 때까지 공개 화면이 500 인 것을 감수하거나, 그 기록에서 요약 자리만 지운다(아래 UPDATE — downgrade 가 하는
것과 같고, 요약만 걸린 기록은 짚은 자리 없는 거부로 남는다):

```sql
SELECT count(*) FROM novel_screenings WHERE 'change_summary' = ANY(flagged_parts);
-- 0 이 아니고 지우기로 했을 때만:
UPDATE novel_screenings SET flagged_parts = array_remove(flagged_parts, 'change_summary')
WHERE 'change_summary' = ANY(flagged_parts);
```

마이그레이션까지 downgrade 하면 그 기록에서 요약 자리만 빼고(요약만 걸린 기록은 짚은 자리 없는 거부로 남는다) 판 행의 요약을
지운다 — 요약은 되살릴 수 없으니 이미지만 되돌린다.

이미지를 이 판보다 옛 것으로 되돌릴 때는 위 끄기를 먼저 하고 재기동한 뒤 되돌린다. 🔴 되돌리기 전에 승인 대기·반려 행이
있으면 운영자가 먼저 처리하거나 작가에게 알린다 — 옛 코드는 심사 칸을 몰라 작가에게 그 행이 "거둠"으로 보이고, 다시 열기는
DB CHECK(대기·반려 행은 공개 범위 `withdrawn`)에 걸려 500 이다(공개되지는 않는다 — 이미지 롤백 동안 이것이 정상이다).
마이그레이션까지 downgrade 하면 그 CHECK 가 사라져 작가의 다시 열기가 승인 없이 공개된다. 승인·반려 조치 로그가 생긴 뒤
옛 이미지로 되돌리면 그 게시자의 어드민 회원 상세가 500 이다(옛 코드가 새 조치 종류를 모른다 — 독자 영향은 없다). 숨긴
소설이 있으면 옛 코드는 숨김 칸을 몰라 되돌린 동안 그 소설이 작가 목록에 다시 보이고 작가가 고치거나 다시 공개할 수 있다.
새 이미지로 돌아오면 숨김이 찍힌 소설은 다시 공개돼 있어도 독자 목록·구매에서 빠지고 작가에게서도 사라진다.

**구매·삭제 환급** — 화 가격(30)과 소설마다 무료인 앞 화 수(5)는 env 가 아니라 `core/clover.py` 의 상수다(바꾸려면 배포).
화 가격을 바꾸면 이미 공개한 유료 화도 그 배포부터 새 값으로 팔린다 — 화 공개본에는 무료·유료만 남고, 이미 산 구매는 낸
값으로 남아 환급도 그 값이다.
공개 정책 스위치가 꺼져 있으면 게시자가 산 화가 든 소설·마지막 묶음을 지울 때 같은 트랜잭션에서 구매자에게 환급한다(원장
`novel_read_refund`, 이미 결제 환불된 구매분은 건너뜀). 켜져 있으면 아직 환급되지 않은 구매가 있는 소설의 삭제는 지우지
않고 숨기며(환급 없음, 소장자는 계속 읽는다), 그런 구매가 든 마지막 묶음의 삭제는 409 `NOVEL_BATCH_SOLD` 로 거절한다. 🔴 **구매가 생긴 뒤 이 판보다 옛 이미지로 되돌리면** 옛 코드의 소설·묶음 삭제는 구매를 몰라 환급
없이 지운다 — 되돌리기 전에 먼저 스위치를 끄고(위 "끄기"), 되돌린 동안 지워진 구매는 아래로 찾아 어드민 지급으로 보정한다.
`novel_purchases` 에 행이 있으면 그 리비전의 downgrade 는 거부되므로 스키마는 그대로 두고 이미지만 되돌린다.

```sql
SELECT p.buyer_user_id, p.price, p.created_at FROM novel_purchases p
LEFT JOIN novel_chapters c ON c.id = p.chapter_id
JOIN users u ON u.id = p.publisher_user_id
WHERE c.id IS NULL AND p.refunded_at IS NULL AND u.deleted_at IS NULL;
```

### 3-14. 크리에이터 정산 월 확정 — settle cron

승인된 크리에이터의 전월 적립을 매월 3일 00:00(KST)부터 확정한다(달이 끝나고 이틀 뒤 — 달 끝 무렵에 시작해 늦게 커밋된
차감·환급을 놓치지 않으려는 여유). 크론은 **매일** 돌고 할 일이 있을 때만 확정한다. 실패한 날은 다음 날 저절로 다시 돌고,
확정한 달은 달별 실행 기록(`creator_payout_batch_runs`)에 남아 다시 확정되지 않는다. 정산 스위치(`CREATOR_PAYOUT_ENABLED`)가
꺼져 있으면 아무것도 하지 않고, 켠 뒤 첫 실행이 꺼 둔 동안 밀린 달을 한 번에 확정한다.

다른 DB 크론과 달리 **psql 로 직접 붙지 않고 서빙 중인 api 컨테이너 안에서** `python -m api.creator_payout.monthly` 를
돌린다. 승인 때의 소급 확정과 같은 계산 코드(`api/creator_payout/settlement.py`)와 같은 비율 설정(`CREATOR_PAYOUT_RATE_BPS`)을
써야 해서다 — psql 사본을 두면 계산식과 설정을 읽는 곳이 둘이 된다. 래퍼 `ops/creator-payout-settle.sh` 는
`ops/active-color.sh` 로 색을 고르고 `compose exec -T api_<색>` 으로 들어간다. 교체 중이라 색을 하나로 못 고르면 그날은
실패로 끝난다(다음 날 다시 돈다). 래퍼가 `.env` 에서 읽는 것은 알림 주소 `DISCORD_WEBHOOK_URL` 하나다.

알림(Discord, `ops/notify.py` 채널): 실패(색을 못 고름·배치 실패, 고정 문구)와 확정한 달이 있는 날의 요약 —
"크리에이터 정산 확정: 2026-11 3명 1,234원 (사용처 없는 차감 0, 환급 기록 불일치 누적 0)" — 만 보낸다. 회원을 알아볼 단서는
싣지 않는다. 배치 실패는 Bugsink 에도 `dependency=creator_payout` 태그로 남는다.

요약의 감시 수 둘은 정산을 멈추지 않고 세기만 한다.
- **사용처 없는 차감**: 그 달의 채팅·소설 차감 중 어느 작품에서 썼는지 기록이 없는 것 — 정산에서 빠졌다. 배포 겹침에
  옛 이미지가 받은 요청이 남긴다(이 기능 이후 배포에서는 0 이어야 한다). 0 이 아닌 달이 이어지면 사용처를 남기지 않는
  새 차감 경로를 의심한다.
- **환급 기록 불일치(누적)**: 그 달 끝 전에 일어난 **모든** 차감의 유료 배분 중 환급 합과 환급 행 합이 다른 것 — 그
  차이는 정산에서 빠지지 않고 사용으로 남는다. 위의 사용처 없는 차감(그 달 값)과 달리 **누적값이라 줄지 않는다** — 한 번
  생긴 불일치는 뒤의 모든 달 요약에 다시 나온다. 이번 달에 새로 생겼는지는 전달 값보다 늘었는지로 본다.

**최초 1회 — 심볼릭 링크 설치**("클로버 만료 — expire cron" 절과 같은 이유 — `/opt/ddona/app` 은 배포마다
`git reset --hard` 되므로 링크해 두면 재설치 없이 다음 배포부터 반영된다):

```sh
sudo ln -sf /opt/ddona/app/ops/creator-payout-settle.sh /opt/ddona/creator-payout-settle.sh
sudo ln -sf /opt/ddona/app/ops/cron.d/ddona-creator-payout-settle /etc/cron.d/ddona-creator-payout-settle
```

래퍼는 링크를 따라가 저장소 `ops/` 의 `lib/bluegreen.sh`·`active-color.sh` 를 쓴다. 알림 모듈은 다른 크론과 같은
`/opt/ddona/scripts`(저장소 `apps/api/scripts` 링크)의 `ops.creator_payout_notify` 다.

**검증**:

```sh
# 1. 수동 1회 실행 — 정상 종료와 마지막 줄 확인. 스위치가 꺼져 있으면 "크리에이터 정산 꺼짐 — 확정하지 않음",
#    켜져 있고 할 일이 없으면 "크리에이터 정산 확정할 달 없음", 확정했으면 "크리에이터 정산 확정: …",
#    크론과 겹쳐 다른 배치가 돌고 있으면 "크리에이터 정산 다른 실행 중 — 이번 실행은 확정하지 않음"(정상 종료, 알림 없음)
sudo -u root /opt/ddona/creator-payout-settle.sh
tail /var/log/ddona-creator-payout-settle.log

# 2. 확정한 달과 감시 수
sudo docker exec ddona-postgres-1 psql -U postgres -d ai_character_chat \
  -c "SELECT * FROM creator_payout_batch_runs ORDER BY period_month"

# 3. 다음 16:35 UTC(KST 01:35)에 크론이 실제로 도는지
tail -f /var/log/ddona-creator-payout-settle.log
```

⚠️ 16:35 UTC — 다른 크론(05:00·06:00·15:05·18:00 UTC, 매시 17분, 5분마다)과 겹치지 않는다. 배포 교체와 겹치면 그날은
실패 알림이 오고 다음 날 따라잡는다. 배치끼리는 advisory 잠금으로 하나만 돌고, 겹친 쪽은 아무것도 하지 않고 정상 종료한다.

### 3-14. 크리에이터 지급 정보 암호화 키 — 만들기 · 보관 · 회전

크리에이터 지급 정보(실명·주민등록번호·계좌번호)는 api 가 `CREATOR_PAYOUT_ENCRYPTION_KEYS` 의 키로 AES-256-GCM 암호화해
DB 에 넣는다(`api/core/field_crypto.py`). DB 백업은 암호문만 R2 로 가져간다 — **키가 백업과 함께 새면 암호화가
무의미하고, 키를 잃으면 지급 정보를 되살릴 수 없다.** 값 형식은 `kid:base64url(32바이트)` 를 쉼표로 이은 목록이고
**맨 앞 키로 암호화, 목록의 모든 키로 복호화**한다. 키 id 는 `[A-Za-z0-9_-]` 1~32자다.

**처음 켤 때**:

```sh
# 1. 키 만들기(VM 이 아니라 운영자 PC 에서 — 셸 기록에 남기지 않으려면 출력만 복사한다)
python3 -c "import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
# 2. 보관: 비밀번호 관리자 + 오프라인 사본 둘. DB 백업과 같은 곳(R2)·저장소·Bugsink·디스코드에 두지 않는다.
# 3. VM .env 에 한 줄 더하고 형식 검사 → 교체(restart 는 env 를 다시 읽지 않는다 — "env 반영 재기동" 절)
cd /opt/ddona/app
sudo sh -c 'printf "\nCREATOR_PAYOUT_ENCRYPTION_KEYS=k1:<키>\n" >> /opt/ddona/.env'
sudo python3 ops/check_env.py --format /opt/ddona/.env
sudo bash ops/swap-api.sh
```

형식이 틀리면 api 가 뜨지 않는다(오류 문장에 값은 찍히지 않는다). 키가 비어 있으면 지급 정보 입력·지급 신청만 닫힌다(503,
정산 조회의 `payoutAvailable` 거짓). 정산 신청·적립·월 확정·조회는 키와 무관하다. 넣은 뒤 "BE 런타임" 절의 키 개수 문장을 VM 에서 다시 센다.

**회전**(키가 샜을 때, 또는 주기적으로):

1. 새 키를 만들어 보관한다(위 1·2).
2. `.env` 의 값 맨 앞에 `k2:<새 키>,` 를 붙인다 — 옛 키(`k1:…`)는 **뒤에 남긴다**(옛 키로 만든 행을 아직 읽어야 한다).
   형식 검사 → `sudo bash ops/swap-api.sh`. 이때부터 새로 입력되는 지급 정보는 새 키로 암호화된다.
3. 옛 키로 만든 행을 새 키로 다시 암호화한다(행마다 커밋 — 도중에 멈춰도 다시 돌리면 남은 행만 한다):

   ```sh
   sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env exec -T api_$(sudo bash ops/active-color.sh) \
     python -m api.creator_payout.reencrypt
   ```

   마지막 줄 "지급 정보 재암호화: N행, 복호화할 수 없어 건너뜀 M행". M 이 0 이 아니면 종료 코드가 1 이다 — 그 행은 목록에
   없는 키로 만들어졌다는 뜻이라 옛 키를 지우지 말고 원인을 먼저 찾는다.
4. 옛 키는 **3 이후 백업 보관 기간(일 7개 + 주 4개 — 주 사본은 일요일 백업이라 정상 동작에서 약 28일, 일요일 백업이 실패할
   때마다 7일씩 늘어난다)이 지난 뒤** 값에서 지우고 재기동한다. 그 전에 지우면 그
   기간의 백업을 복원했을 때 지급 정보를 읽지 못한다. 보관해 둔 옛 키 사본도 그때 폐기한다.

**키를 잃었을 때**: 복호화할 수 없다. 작가의 정산 화면은 열리고 등록 정보의 실명만 비어 보이며(은행·계좌 끝 4자리는
평문이라 보인다), 어드민 지급 상세·원문 열람은 409 `CREATOR_PAYOUT_INFO_UNREADABLE` 이다. 새 키를 넣고 작가에게 지급
정보를 다시 입력받는다(새 판이 새 키로 저장된다). 이미 신청된 건은 반려한 뒤 다시 신청받는다.

---

### 3-15. 장기 기억 — 켜는 순서 · 끄기 · 되돌리기

장기 기억 스위치는 env 표의 `MEMORY_*` 행이고 전부 코드 기본값이 꺼짐이라, 줄이 없으면 배포만으로는 아무것도 켜지지 않는다.
켜고 끄는 법은 모두 같다 — 편집 전 `sudo cp -p /opt/ddona/.env /opt/ddona/.env.bak-<날짜>-memory-<스위치>` → 줄 추가·삭제(같은 키가
이미 있으면 새 줄을 더하지 말고 그 줄을 고친다) → `sudo python3 ops/check_env.py --format /opt/ddona/.env` →
`sudo bash ops/swap-api.sh`("env 반영 재기동" 절). 백업은 비교용이다 — 통째로 복원하지 않는다(교체 스크립트가 같은 파일의
`API_IMAGE_BLUE`·`API_IMAGE_GREEN` 을 고친다). 줄을 넣거나 빼면 "BE 런타임" 절의 키 개수 문장을 VM 에서 다시 센다.

**지금 운영(2026-10-23).** 장면·사실 추출(`MEMORY_EPISODES_EXTRACT`·`MEMORY_FACTS_EXTRACT`)이 켜져 있고 추출·요약·판정 모델은
`haiku`(Anthropic 직결)다. 회상, 요약의 비밀 표기와 지식 범위 필터, 임베딩 쓰기·임베딩 읽기가 켜져 있고(`VOYAGE_API_KEY` 있음, 질의
임베딩 상한 `3000` ms), 사실 주입(`MEMORY_FACTS_INJECT`)은 꺼져 있다 — 회상 품질 재측정에서 사실 주입만 켜기 권고가 나오지 않았다.
`MEMORY_MODEL_SCOPE`·`MEMORY_EMBED_MODEL`·`MEMORY_EMBED_DIMS` 줄은 넣지 않아 기본값(Opus 방만 · `voyage-4-large` · `1024`)으로
돈다. 그래서 Opus 방은 회상 + 표기 + 필터 + 임베딩 회상, 그 밖의 방은 기억을 쓰지 않고, 임베딩 쓰기는 모든 방에서 돈다.
켠 순서는 아래 「켜는 순서」를 편집 두 번으로 묶었다 — 편집 ① `MEMORY_EPISODES_RECALL`·`MEMORY_SUMMARY_SECRET_MARKING`·
`MEMORY_KNOWLEDGE_FILTER`·`VOYAGE_API_KEY`·`MEMORY_EMBED_WRITE`(2026-10-23 21:17 KST 교체), 편집 ② `MEMORY_EMBED_RECALL`·
`MEMORY_EMBED_RECALL_TIMEOUT_MS=3000`(같은 날 21:47 KST 교체, 미임베딩 행 0 을 확인한 뒤). 단계 사이 관측 대신 편집마다 그 자리에서
운영 Opus 방 턴으로 오류·섹션 실림·질의 임베딩 결과를 봤다. 끌 때는 편집 단위로 ② → ①, 단계별로는 아래 「끄기」 순서다.
2026-10-24 부터는 기억 보기 스위치(`MEMORY_ITEMS_VISIBLE`)도 켜져 있다 — 아래 「기억 보기 · 잊게 하기 · 요약 다시 만들기」.
사실 추출의 비밀 규칙 문안(비밀의 주인은 늘 아는 사람에 넣고 남이 몰래 본 비밀은 주인과 본 인물, 여럿이 함께 숨긴 비밀은 그
자리의 인물 모두를 적는다, 털어놓은 장면의 관계 행 두 인물을 비밀 내용 행의 아는 사람으로 물려준다, 같은 키를 다시 쓸 때 앞서
알던 인물을 지우지 않는다, 아는 사람을 정하는 차례)과 장면 추출의 아는 사람·말한 인물 규칙 문안은 프롬프트 세트 데이터라 스위치
없이 이미 운영 문안이다.

**장면 행의 아는 사람 칸.** 장면 기억 행에도 그 장면을 아는 인물 이름 목록 칸(`chat_memory_episodes.known_by`)이 있고 장면 추출이
채운다. 뜻과 길이 규칙은 사실 행의 같은 칸과 같다 — NULL 은 공개이거나 알 수 없다는 뜻이고 빈 배열은 쓰지 않으며, 원소 1~10개,
원소마다 60자 이하(CHECK 둘). 그 장면에 실제로 있었던 인물만 넣고 대사 속에서 이름만 불린 인물은 넣지 않는다.

**기억 사용 범위(`MEMORY_MODEL_SCOPE`, 기본 `opus`).** 회상·사실 주입·지식 범위 필터·요약 비밀 표기·임베딩 회상은 그 턴의 레인과
글쓰기 모델이 이 목록에 들 때만 동작하고, 범위 밖 방의 턴은 스위치를 다 끈 것과 프롬프트·SQL 이 같다. 기본은 두 레인의 Opus 방뿐이다
— 기억 품질은 Opus 방에서만 재 보았다. 값은 쉼표 목록이고 원소는 `모델`(두 레인 모두) 또는 `레인:모델`(레인 `story`·`character`,
모델 `gemini`·`sonnet`·`opus` — 판정 전용 `haiku` 는 아니다)이며, 모르는 레인·모델이면 기동하지 않는다. 어떤 방에서도 기억을 쓰지
않으려면 값을 비우지 말고 스위치를 끈다 — 운영 env 형식 검사가 빈 값을 거부해 배포가 멈춘다. 추출(장면·사실)과 임베딩 쓰기는
범위와 무관하게 모든 방에서 돈다(쌓아 두는 일이라 그 방 대화가 바뀌지 않는다).

**켜는 순서.** 한 단계씩 켜고, 단계마다 기존 방 10~15턴으로 내용·스탯·토큰과 섹션이 실렸는지(운영 읽기 전용 SELECT 로
`chat_turns.memory_recall`·`memory_facts`)를 본 뒤 다음 단계로 간다. 이 순서만 켜는 도중의 상태가 전부 회상 품질 측정이 잰
조합과 같다 — 순서를 바꾸면 재지 않은 조합이 운영에 생긴다.

1. `MEMORY_EPISODES_RECALL=true` — 장면 회상(명사 순위만). 인물이 대사로만 말한 장면은 싣지 않고, 방 사실 행의 아는 사람 정보로
   이번 장면에 아는 사람이 없는 비밀과 근거가 겹치는 장면을 가린다 — 이 가림은 회상 스위치에 묶여 있어 `MEMORY_KNOWLEDGE_FILTER`
   없이도 걸린다. 장면 행 자신의 아는 사람 칸에 적힌 인물이 이번 장면에 아무도 없는 장면도 같은 가림으로 빠진다.
2. `MEMORY_SUMMARY_SECRET_MARKING=true` 와 `MEMORY_KNOWLEDGE_FILTER=true` 를 **한 번에**. 1 을 보류하면 2 도 보류한다(회상 없이 표기·
   필터만 켠 조합은 재지 않았다). 🔴 요약 표기는 다음 접기부터 모든 방의 요약 글을 바꾸고 그 요약이 엔딩 판정 입력에도 실린다.
   필터는 사실 주입이 꺼진 동안 생성 프롬프트를 바꾸지 않지만 측정한 조합과 같게 하려고 함께 켠다.
3. 임베딩과 사실 주입. 🔴 Voyage 로 대화 내용(장면·사실 글과 매 턴 질의 글)이 나가므로 그 국외이전을 담은 개인정보처리방침이
   켜기 최소 하루 전에 게시된 뒤에만 켠다. Voyage 조직 설정에서 학습 데이터 사용이 꺼져 있는지 먼저 본다. 그 뒤 차례로:
   1. **쓰기 먼저** — `VOYAGE_API_KEY` 와 `MEMORY_EMBED_WRITE=true` 를 한 편집에서(키 없이 스위치가
      먼저 들어가면 기동하지 못한다). 사용자 프롬프트는 그대로이고, 밀린 행을 따라잡는 동안 임베딩 원가가 평소보다 많다.
      사용량 집계의 `chat_memory_embedding` 줄과 Bugsink 로 실패율을 본다.
   2. **읽기** — 회상할 방에 행이 쌓인 뒤 `MEMORY_EMBED_RECALL=true`. 🔴 쓰기를 켜지
      않고 읽기만 켜면 매 턴 결과를 쓰지 못할 Voyage 호출만 생긴다(기동 검사가 막지 않는다).
   3. **사실 주입** — `MEMORY_FACTS_INJECT=true` 를 마지막에. 사실 주입을 임베딩 없이 켠 조합은 재지 않았다. 인물이나 진행자가
      말로만 전한 확인되지 않은 주장(`claimed`)이 키의 지금 값이면 그 키는 싣지 않는다(사용자 주장은 싣는다).

   측정이 고른 값은 모델 `voyage-4-large` · 차원 `1024` · RRF k `20` · 보통 턴 상한 `1` · 회상 단서 턴 상한 `3` · 거리 상한 `2.0`(거르지
   않음 — env 표 그 행) · 거리 순 앞 `10` · 흔한 명사 절대 상한 없음이고, 사실 섹션의 이름 정확 조회 몫
   0.3 은 코드 상수(`apps/api/src/api/chat/memory_fact_section.py` 의 `EXACT_RATIO`)다. 모두 코드 기본값이라
   스위치·키 줄 말고는 넣을 줄이 없다 — 질의 임베딩 시간 상한 하나만 예외로, 코드 기본값 `1000` ms 는 운영 env 로 `3000` 을
   준다(`MEMORY_EMBED_RECALL_TIMEOUT_MS=3000`, 회상 품질 측정은 `1000` 조건이었다 — env 표 그 행).

**알려진 성질 — 켜기 전에 정할 것.** Voyage 가 연속 3회 실패하면(키 회수·쿼터 소진·장애) 질의 임베딩과 임베딩 채우기를 함께
멈춘다 — 멈춤은 30초에서 시작해 실패가 하나 더 셀 때마다 배로 늘어 최대 900초이고, 연속 실패 수는 방과 무관한 Redis 키 하나
(`voyage_backoff`)로 두 쪽이 공유하며, 호출이 한 번 성공하면 풀린다. 채우기는 한 번에 10초 상한·세 번까지 다시 보낸 뒤의 실패를
세고, 질의 임베딩은 다시 보내지 않고 한 번만 부른다(시간 상한 — 운영 `3000` ms — 을 넘기면 명사 단독). 질의 임베딩의 시간 초과는 실패로 세지 않는다.
멈춘 동안의 질의 임베딩은 건너뛰어 임베딩 회상이 꺼진 턴과 같고(명사 단독), 채우기는 건너뛴 행을 풀린 뒤 따라잡는다. Redis 를
못 읽으면 멈춤 없이 부른다. 실패한 호출은 매번 경고 로그와 Bugsink 이벤트(`dependency=voyage`, 쿼터 소진은 `voyage_rate_limit`)를
남긴다. 같은 방에서 턴이 빠르게 겹치면 두 채우기가 같은 행을 임베딩할 수
있다 — 중복 행은 들어가지 않고 원가만 두 번이다.

- 회상을 켜면 사실 주입이 꺼져 있어도 매 턴 방 사실 행을 한 번 읽는다(대화 길이에 비례). 사실 주입까지 켜면 같은 행을 두 번 읽는다.
- 회상의 아는 사람 가림은 회상 스위치에 묶여 따로 끌 수 없다 — 끄는 길은 회상 전체(`MEMORY_EPISODES_RECALL`)다. 가림은 방 사실
  행의 아는 사람과 장면 행 자신의 아는 사람 칸 둘로 걸린다.
- `MEMORY_KNOWLEDGE_FILTER` 를 켠 턴은 직전 응답의 대사 따옴표(`"…"`·`“…”`·`「…」`·`『…』`, 작은따옴표는 속마음이라 빼지 않는다)
  안에서만 나온 이름을 장면 인물로 세지 않는다 — 사실 섹션 필터·이름 정확 조회·회상 가림이 같은 장면 인물을 쓴다. 이번 사용자
  메시지는 따옴표 안이어도 센다.

**원가 보기.** 턴에 실린 호출(생성·판정·질의 임베딩)의 호출 위치별·턴별 원가 분포는 `scripts/turn_cost_report.py`(읽기 전용
트랜잭션, 턴 기록 `chat_turns.llm_calls`), 턴 뒤 백그라운드(요약 접기·추출·임베딩 채우기)까지 포함한 일 단위 합계는
`scripts/llm_usage_report.py` 다. 🔴 두 표를 더하지 않는다 — 일 단위 집계가 턴 기록의 호출도 함께 세어 더하면 그 몫이 두 번
들어간다. 실행은 두 스크립트 모두 서빙 중인 색 안에서:

```sh
cd /opt/ddona/app && sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env \
  exec -T api_$(sudo bash ops/active-color.sh) python scripts/turn_cost_report.py --from 2026-10-16 --to 2026-10-22 --chat-model opus
```

**첫 글자 지연 보기.** 턴 기록 `chat_turns.llm_calls` 의 생성 칸에는 첫 글자 지연이 둘 붙는다 — `firstTokenMs` 는 턴 시작부터,
`streamFirstTokenMs` 는 생성 호출(스트림)을 연 때부터 처음 글이 든 조각이 올 때까지(ms)다. 둘의 차가 생성 호출 앞의 준비 시간이라
질의 임베딩·기억 읽기가 늘린 지연은 그 차로 본다. 글 없이 끝난 생성은 두 키 다 없고, 판정·임베딩 칸에는 붙지 않는다.

**기억 보기 · 잊게 하기 · 요약 다시 만들기(`MEMORY_ITEMS_VISIBLE`).** 기억 열람·잊게 하기를 적은 처리방침 판(2026-10-24 판)을
게시한 뒤 같은 날 켰다(14:46 KST 교체). 읽기와 방 주인의 삭제·다시 만들기만 여는 스위치라 위 「켜는 순서」와 따로 켜고 끈다.
끄면 라우트가 404 로 돌아가고 웹 패널은 예전 모양이 되지만, 이미 잊게 한 행은 돌아오지 않는다.

- **잊게 하기는 실제 삭제다.** 장면은 그 행 하나, 사실은 그 방의 같은 키 행 전부(옛 값 포함)를 지운다. 임베딩은 장면·사실 FK 의
  CASCADE 가 함께 지운다. 비밀 사실(아는 사람이 정해진 키)이면 근거 메시지 구간이 겹치는 장면도 함께 지우고, 그 수는 확인 대화 전에
  미리 보기 라우트가 알려 준다. 턴 기록(`chat_turns.memory_recall`·`memory_facts`)에는 실었던 행의 id 만 남고(글 없음), 정기 백업에는
  보관 기간 동안 남는다. 요약 글과 최근 원문 창은 건드리지 않는다 — 요약에서 빼려면 사용자가 요약을 고친다.
- **같은 내용이 다시 뽑힐 수 있다.** 잊게 하기는 원문을 지우지 않는다. 잊은 행을 뽑은 접힌 구간 안이나 그보다 앞의 메시지를
  고치거나 지우거나 재생성하면 되감기가 그 메시지 이상을 덮는 스냅샷을 전부 지우므로, 그 구간이 다시 접힐 때 같은 원문에서 같은
  장면·사실이 다시 뽑힐 수 있다. 아직 접히지 않은 대화나 그 뒤에 이어진 대화에 같은 내용이 있어도 다음 접기에서 새로 뽑힌다.
- **잊기 세대.** 장면이든 사실이든 잊으면 같은 트랜잭션에서 방의 잊기 세대(`chat_rooms.memory_forget_generation`, 리비전 `914b076c9291`)가
  오르고, 그때 진행 중이던 장면·사실 추출은 넣기 직전에 세대가 바뀐 것을 보면 결과를 버린다(그 시도는 실패 한 번으로 적혀 시도 한도 안에서
  다음 추출 때 다시 쥐어지므로 위와 같은 이유로 같은 내용이 다시 나올 수 있다). 장면 잊기의 세대는 장면 행을 읽는 인상 생성 때문에 오르는데,
  진행 중인 두 추출도 그 한 번을 버리게 된다. 잊기는 같은 트랜잭션에서 지우는 행을 근거로 쓴 인상(`chat_memory_impressions`)도 지운다. 옛 이미지는 이 칸을 몰라도 돈다(서버 기본값 0) —
  이미지만 되돌리는 데 downgrade 는 필요 없고, 칸을 내릴 때는 이미지를 먼저 되돌린 뒤 내린다(칸을 매핑한 이미지는 칸이 사라지면 방
  조회가 실패한다). 내려도 잊은 행은 돌아오지 않는다.
- **요약 다시 만들기**는 방 모델과 무관한 고정 10 클로버(`apps/api/src/api/core/clover.py` 의 `MEMORY_SUMMARY_REGENERATE_COST`, 웹은
  `/clover/pricing` 의 `memorySummaryRegenerateCost` 를 읽는다)이고, 깎은 뒤의 실패(요약 호출 실패·빈 요약 503, 요약을 기다리는 사이
  기억이 바뀐 409)는 전부 환불한다. 원장 kind 는 `memory_summary_spend`·`memory_summary_refund` 이고 사용처 행을 남기지 않는다(정산
  대상이 아니다). 같은 방에는 한 번에 하나만 받는다 — 진행 중이면 깎기 전에 409 `MEMORY_SUMMARY_REGENERATE_IN_PROGRESS`. 진행 표시는
  Redis 키이고 수명은 요약 호출 상한(`GEMINI_MEMORY_SUMMARY_TIMEOUT_MS`) + 30초라 배포·크래시로 남은 표시도 그 뒤 풀린다. Redis 장애면
  표시 없이 진행해 겹친 두 요청이 둘 다 깎을 수 있지만, 늦게 쓰는 쪽이 버전 충돌로 환불받는다. 호출은 요약 접기와 같은 모델
  (`MEMORY_SUMMARY_MODEL`)·같은 호출 위치(`chat_memory_summary`)라 일 단위 원가 집계에서 접기와 갈리지 않는다. 다시 만든 글은 지금
  스냅샷을 제자리에서 고치고 직전 글은 되돌리기 칸 하나에 들어간다 — 사용자가 고친 요약을 다시 만들면 고치기 전 글로는 돌아갈 수
  없다.

**판정 이벤트 기록 · 인상(`STAT_EVENT_LOG`·`MEMORY_IMPRESSIONS_WRITE`).** 판정 이벤트 기록은 2026-10-24 17:45 KST 교체부터 켜져
있고(env 표 그 행), 인상 쓰기는 꺼져 있다 — 인상 모델 줄(`MEMORY_IMPRESSION_MODEL`)과 배정 항목(`chat_memory_impression`)도 운영
`.env` 에 없다. 둘 다 위 「켜는 순서」와 따로 켜고 끈다.

- **인상 문안은 프롬프트 세트 데이터다.** 채널 `memory_impression`(지시문·장면 줄·사실 줄 세 행)은 리비전 `6558ab4d3dbc` 가 채팅
  두 레인의 여덟 체인(gemini·sonnet·opus·haiku)에 새 게시 세트로 심었고, 고칠 때는 어드민 프롬프트 세트 화면에서 게시한다. 스위치가
  꺼져 있는 동안은 어떤 호출도 이 채널을 렌더하지 않는다. 이 채널을 모르는 이미지(인상 문안 시드 이전)는 렌더는 그대로이고, 그 여덟
  체인의 어드민 게시만 새 행을 잉여로 보고 막는다.
- **인상 쓰기를 켜기 전 조건** — 셋이 모두 끝나야 켠다. 실패한 묶음의 재시도 상한(묶음마다 세 번)은 이미 코드에 있다(env 표
  `MEMORY_IMPRESSIONS_WRITE` 행).
  1. 개인정보처리방침의 대화방별 기억 항목에 인상(장면·사실 기억에서 만든, 인물 사이 감정·태도의 흐름을 적은 짧은 글 — 저장만 하고
     생성에 싣지 않는다)과 그것을 만드는 모델 호출을 더한 판이 게시돼 있다.
  2. `MEMORY_IMPRESSION_MODEL=haiku` 줄과 `LLM_CALL_SITE_BACKENDS` 의 `chat_memory_impression:anthropic` 항목을 스위치 줄과 **한
     편집에서** 넣는다(모델 줄과 배정은 짝이다 — `STAT_JUDGMENT_MODEL` 행).
  3. 운영 설정 기동 테스트가 인상 호출 위치를 빼 두는 제외(`apps/api/tests/test_config_judgment_models.py` 의
     `_NOT_YET_IN_PRODUCTION`)를 지우고, 테스트가 흉내 내는 운영 값(`apps/api/tests/factories.py` 의 `PRODUCTION_ENV_NAMES`·
     `PRODUCTION_CALL_SITE_BACKENDS`)에 같은 모델 줄과 배정을 더한다 — 그래야 운영 조합의 기동을 테스트가 계속 검사한다.
- **끄기 — 켠 역순.** 인상 쓰기를 켰다면 그것부터: 스위치 줄과 모델 줄·배정 항목을 한 편집에서 지운다(모델 줄 `haiku` 를 남기고
  배정만 지우면 운영 `.env` 에 `BEDROCK_*` 키가 없어 기동하지 못한다). 그다음 `STAT_EVENT_LOG` 줄 — 다음 턴부터 칸이 `[]` 다. 이미
  쓴 이벤트와 쌓인 인상 행은 남는다.
- **되돌리기 — 스위치 → 워커 → (문안 데이터) → 이미지 → (스키마).**
  - 🔴 배정 항목 `chat_memory_impression` 은 인상 호출 위치를 모르는 이미지(인상 표 도입 이전)로 내리기 **전에** 지운다 — 남아
    있으면 그 이미지가 모르는 이름으로 거부해 기동하지 못한다.
  - 🔴 소설화 워커가 켜져 있으면 이미지 롤백·downgrade 전에 "BE → GCE VM" 절 「롤백」의 스위치 끄기 → 워커 비우기를 먼저 한다. 그
    끄기는 태그 없는 교체라 서빙 이미지로 `alembic upgrade head` 를 다시 돌리므로 문안 downgrade 보다 **앞에** 둔다(뒤에 두면 지운
    시드가 되살아난다).
  - 이미지 롤백은 `sudo DDONA_ROLLBACK=1 bash ops/swap-api.sh <이전SHA>` 가 1순위다. 옛 이미지는 세 리비전 위에서 그대로 돈다 — 판정
    이벤트 칸과 인상 표를 모르고 지나가고(턴 기록 칸은 서버 기본값 `[]`, 스냅샷 삭제는 인상 행을 CASCADE 로 지운다), 인상 문안
    세트는 위처럼 여덟 체인의 어드민 게시만 막힌다. 🔴 다만 인상 행이 있는 채 인상 표 이전 이미지로 내리면 그 이미지의 잊게 하기는
    인상을 지우지 않는다 — 그때는 아래 2 까지 내린다.

| 순서 | 리비전 | 바꾼 것 | downgrade 목표 | downgrade 가 하는 일 · 돌릴 때 |
|---|---|---|---|---|
| 1 | `6558ab4d3dbc` | 인상 문안 채널을 더한 새 세트(8 체인)와 두 레인 초안의 그 채널 행 | `8b045061cad4` | 시드한 세트를 리터럴 id 로 지워 그 앞 활성 세트가 다시 활성이 되고, 초안의 그 채널 행을 지운다. 시드 뒤 어드민이 여덟 체인 중 하나에 게시했으면 아무것도 지우지 않고 멈춘다 — 사람이 판단한다(그 게시본을 손으로 지우지 않는다). 데이터 리비전이라 이미지 롤백 전이면 서빙 이미지로, 롤백 뒤면 이 리비전 파일을 가진 이미지의 일회성 컨테이너로 돌린다 |
| 2 | `8b045061cad4` | 인상 표 `chat_memory_impressions` | `18d0cb76b3ca` | 표를 지운다(인상 행이 사라진다). 이 표를 아는 이미지는 잊게 하기가 인상을 지우다 실패하므로 **인상 표 이전 이미지로 먼저 내린 뒤** 이 리비전 파일을 가진 이미지의 일회성 컨테이너로 돌린다 |
| 3 | `18d0cb76b3ca` | 턴 기록 `chat_turns.stat_events` 칸 | `914b076c9291` | 칸을 지운다(쌓인 이벤트가 사라진다). 칸을 매핑한 이미지는 턴 기록 INSERT·조회가 실패하므로 **판정 이벤트 칸 이전 이미지로 먼저 내린 뒤** 일회성 컨테이너로 돌린다 |

- 위(head 쪽)부터 차례로만 내려간다. 일회성 컨테이너는 아래 문안 리비전 downgrade 와 같은 꼴(`sudo docker run --rm --network ddona_default
  --env-file /opt/ddona/.env <IMAGE>:<그 리비전 파일을 가진 태그> alembic downgrade <목표>`)이고 먼저 `sudo /opt/ddona/backup.sh --manual`.
  그 전에 함께 내려갈 리비전을 "BE → GCE VM" 절의 「롤백」 대로 `alembic history` 로 확인한다.
- 🔴 downgrade 뒤 그 리비전 파일을 가진 이미지로 교체되면(`main` push 자동 배포, `image_tag` 를 비운 실행, 그런 이미지가 서빙 중일
  때의 태그 없는 교체) `alembic upgrade head` 가 지운 것을 되살린다. downgrade 와 revert 병합 사이에 다른 API 병합을 하지 않고, 롤백해
  둔 동안의 env 반영 교체는 `DDONA_ROLLBACK=1` 을 붙인다.
- revert 병합도 배포다(`apps/api/**`). 병합의 역순으로, 리비전을 지우는 revert 는 그 downgrade 를 마친 뒤에 병합한다.

**끄기 — 켠 역순.** 줄 삭제 → 형식 검사 → `sudo bash ops/swap-api.sh`. 역순이면 되돌리는 도중의 상태도 전부 잰 조합이다.
🔴 사실 주입이 켜져 있는 동안에는 `MEMORY_KNOWLEDGE_FILTER` 를 먼저 끄지 않는다 — 처리방침의 "비밀을 아는 인물이 장면에 없으면
보내지 않는다"가 사실 쪽에서는 필터가 켜져 있을 때만 참이라, 사실 주입부터 끈다. 4 를 하기 전에 서빙 컨테이너의 env 키 이름에
`MEMORY_FACTS_INJECT` 가 없는지 본다.

1. `MEMORY_FACTS_INJECT` → 다음 턴부터 사실 섹션이 빠진다(사실 행은 남는다).
2. `MEMORY_EMBED_RECALL` → 다음 턴부터 명사 단독.
3. `MEMORY_EMBED_WRITE` → 그다음 편집에서 `VOYAGE_API_KEY`. 키를 스위치보다 먼저 지우면 "켜졌는데 키 없음"으로
   기동하지 못한다. 넣은 임베딩 행은 남는다(다시 켜면 이어서 채운다).
4. `MEMORY_SUMMARY_SECRET_MARKING`·`MEMORY_KNOWLEDGE_FILTER` → 다음 접기부터 표기 없음. 이미 표기한 요약은 남는다.
5. `MEMORY_EPISODES_RECALL` → 기억 사용 스위치가 모두 꺼진 상태(추출만 도는 2026-10-23 이전 운영).

옛 이미지는 모르는 키를 무시하므로(`extra="ignore"`) 스위치 줄이 남은 채 이미지를 되돌려도 기동은 된다 — 다만 그 기능이 조용히
꺼진 채 돌므로 스위치부터 지운다.

**되돌리기 — 스위치 → (이미지 또는 데이터).** ① 위 끄기를 먼저 한다. 그다음 ②와 ③ 중 **하나**를 고른다. ② 코드만 되돌리면 이미지 롤백(`sudo DDONA_ROLLBACK=1 bash ops/swap-api.sh
<이전SHA>`, "BE → GCE VM" 절의 「롤백」)이 1순위다. 이 묶음의 스키마·데이터 변경은 아래 표의 일곱이고 옛 이미지는 그 위에서 그대로
돈다 — 임베딩 표는 모르고 지나가고(스냅샷 삭제가 CASCADE 로 끝난다), 장면 행의 아는 사람 칸은 옛 코드가 빼고 넣어 NULL 로 남고,
요약 슬롯(출처 문장 포함)은 옛 코드가 값을 넘기지 않아 빠지고, 사실·장면 추출 문안은 **옛 이미지도 새 문안을 쓴다**(DB 의 활성
세트라서 — 장면 아는 사람 칸을 모르는 옛 결과 스키마로는 그 칸이 NULL 로 남는다). 요약 슬롯을 모르는 이미지의 어드민 게시 검증은 그 슬롯을 잉여로 보고 그 체인의
게시만 막는다.
③ 데이터까지 되돌릴 때(문안을 옛것으로, 또는 revert 병합이 필요할 때)는 ② **대신** 아래 downgrade 를 새 코드 이미지로 먼저 돌리고, 그
다음에 revert(또는 이미지 롤백)한다. ②를 먼저 하면 서빙 이미지가 리비전 파일을 모르는 옛 이미지라 그 이미지로는 downgrade 가
`Can't locate revision` 으로 멈춘다 — 그때는 아래 `IMG` 에 서빙 색이 아니라 그 리비전 파일을 가진 새 코드 이미지
(`<IMAGE>:<새 코드 TAG>`, 롤백 전 커밋 SHA 7자리 태그)를 넣는다.

| 순서 | 리비전 | 바꾼 것 | downgrade 목표 | downgrade 가 하는 일 |
|---|---|---|---|---|
| 1 | `0c1a85bc5c2f` | 요약 비밀 표기 슬롯 끝에 확인되지 않은 주장의 출처를 적게 하는 문장을 더한 새 세트(8 체인) | `6fbf1e9a65b8` | 이 리비전이 만든 세트만 리터럴 id 로 지워 그 앞 활성 세트가 다시 활성이 된다(시드 뒤 어드민 게시가 있으면 멈춘다 — 그 세트를 먼저 정리) |
| 2 | `c1f3945cb802` | 사실 추출 비밀 규칙을 아는 사람을 정하는 차례가 있는 판으로 바꾼 새 세트(8 체인) | `e05462d680f0` | 이 리비전이 만든 세트만 리터럴 id 로 지워 그 앞 활성 세트가 다시 활성이 된다(시드 뒤 어드민 게시가 있으면 멈춘다 — 그 세트를 먼저 정리) |
| 3 | `eb8d3cc6d5c2` | 장면 추출 아는 사람·말한 인물 규칙 문안을 바꾼 새 세트(8 체인) + 장면 추출 결과 스키마의 `known_by` 칸 | `0346abdbcc92` | 이 리비전이 만든 세트만 리터럴 id 로 지워 그 앞 활성 세트가 다시 활성이 된다(시드 뒤 어드민 게시가 있으면 멈춘다 — 그 세트를 먼저 정리). 결과 스키마는 코드라 downgrade 뒤 이미지도 되돌린다 — 새 이미지가 옛 문안으로 돌면 규칙 없는 칸이 쌓인다 |
| 4 | `131ec072bed3` | 장면 행 `chat_memory_episodes.known_by` 칸(expand)과 CHECK 둘 | `d6abfd9f92ce` | CHECK 둘 → 칸 DROP(그 칸에 쌓인 값은 사라진다). 3 을 먼저 되돌린다 |
| 5 | `0aeadefcf159` | 요약 비밀 표기 슬롯을 더한 새 세트(8 체인) | `e4e407a62d03` | 이 리비전이 만든 세트만 리터럴 id 로 지워 그 앞 세트가 다시 활성이 된다 |
| 6 | `e4e407a62d03` | 사실 추출 비밀 규칙(아는 사람 물려받기·목격 비밀·집단 비밀·주인 이름)을 바꾼 새 세트(8 체인) | `b3b2636b9184` | 이 리비전이 만든 세트만 리터럴 id 로 지워 옛 문안이 다시 활성이 된다 |
| 7 | `b3b2636b9184` | 임베딩 표 `chat_memory_embeddings`·`vector` 확장 | `726aad108167` | 표를 지우고, 확장은 그것에 기대는 객체가 없을 때만 지운다(임베딩은 장면·사실에서 다시 만들 수 있다) |

- **리비전 하나마다 [그 리비전 파일을 가진 이미지로 downgrade → 그 PR revert 병합] 짝**이고 위 순서(위가 head 쪽)로만 내려간다 —
  `alembic downgrade` 는 목표 위에 쌓인 리비전을 전부 내리므로, 목표가 아래일수록 위의 것까지 함께 내려간다. 이 표의 리비전 사이와
  위에는 다른 작업의 리비전이 끼어 있고 계속 늘어나므로, 매번 "BE → GCE VM" 절의 「롤백」 대로 `alembic history` 로 함께 내려갈
  리비전을 확인한다.
- 🔴 downgrade 는 **그 리비전 파일을 가진 이미지**로 돌린다 — ②를 하지 않았으면 서빙 중인 색의 이미지가 그것이다. 리비전 파일이
  없는 이미지는 그 리비전을 내리지 못한다. 먼저 백업(`sudo /opt/ddona/backup.sh --manual`), 이미지는 서빙 중인 색의 것(②를 이미 했다면
  첫 줄 대신 `IMG=<IMAGE>:<새 코드 TAG>`):

  ```sh
  cd /opt/ddona/app
  IMG=$(sudo docker inspect --format '{{.Config.Image}}' ddona-api_$(sudo bash ops/active-color.sh)-1)
  sudo docker run --rm --network ddona_default --env-file /opt/ddona/.env "$IMG" alembic downgrade 6fbf1e9a65b8
  ```

- 🔴 downgrade 와 revert 병합 사이에 교체·재기동·다른 병합을 하지 않는다 — 교체 스크립트가 서빙 이미지로 `alembic upgrade head`
  를 다시 돌려 지운 것을 되살린다.
- 시드 뒤 어드민이 같은 체인에 새로 게시했으면 문안 리비전(1·2·3·5·6)의 downgrade 는 지우지 않고 멈춘다 — 사람이 판단한다. 프롬프트 시드를 손으로
  지우거나 옛 프롬프트 버전을 통째로 복원하지 않는다.
- revert 의 순서는 병합의 역순이다. 마이그레이션 없는 PR(사실 섹션 선택·하이브리드 회상·Voyage 채우기·지식 범위 필터·회상 줄의
  인물 장면·비밀 장면 거름과 사실 섹션의 인물 주장 거름·이 문서와 원가 스크립트)은 이미지 롤백이나 revert 만으로 되돌아간다. 임베딩 표를 읽고 쓰는 코드(하이브리드 회상·채우기)는 7 의
  downgrade 보다 먼저 revert 한다.
- 🔴 Postgres 이미지(pgvector 를 실은 것)를 원래 이미지로 되돌리는 것은 7 의 downgrade 가 끝난 **뒤에만** 한다 — `vector` 타입이 남은
  DB 를 확장 없는 이미지로 띄우면 그 표를 읽지 못한다.

### 3-16. 숨긴 소설 파기 — purge cron

노벨 정책 스위치(`NOVEL_PUBLIC_POLICY_V2_ENABLED`)가 켜진 뒤 노벨로 팔린 소설을 작가가 지우거나 그 게시자가 탈퇴하면, 산
사람이 계속 읽도록 소설을 숨긴다(`novels.hidden_at`). 아직 환급되지 않은 소장자가 모두 사라진(구매자가 모두 탈퇴했거나 모두 환급받은) 숨긴 소설을 이
크론이 **매일** 진짜로 지운다. 구매 행(거래 기록)은 남는다. 지울 것이 없는 날은 아무것도 바꾸지 않고, 실패한 날은 다음 날
저절로 다시 돈다. 스위치와 무관하게 돈다 — 스위치를 끈 뒤에도 남은 숨긴 소설은 소장이 끝나면 지워져야 한다.

파기 다음에 **숨긴 소설**(작가가 지워 숨긴 것과 게시자 탈퇴로 숨긴 것 모두)에 작가 전용 데이터(스냅숏·설정 노트·공개되지 않은 화 등 — 공개 정책 스위치 켜기의
조건 문단)가 남아 있으면 지운다. 작가의 삭제와 탈퇴가 숨길 때 이미 같은 정리를 하므로 대개 0편이다. 0 이 아닌 날은 정리를 모르는 옛 이미지가
배포 겹침 동안 숨긴 소설이 있었거나, 삭제·탈퇴 직전에 시작된 작가 쓰기가 그 뒤에 도착한 경우다. 독자가 읽는 공개본·판과 그 본문은
지우지 않는다.

"크리에이터 정산 월 확정 — settle cron" 절과 같이 **서빙 중인 api 컨테이너 안에서** `python -m api.novelize.hidden_purge` 를
돌린다(소설 삭제·탈퇴와 같은 삭제 코드를 쓴다). 래퍼 `ops/purge-hidden-novels.sh` 는 `ops/active-color.sh` 로 색을 고르고
`compose exec -T api_<색>` 으로 들어간다. 교체 중이라 색을 하나로 못 고르면 그날은 실패로 끝난다. 래퍼는 `.env` 를 읽지 않는다.
알림은 없다 — 실패는 Bugsink 에 `dependency=hidden_novel_purge` 태그로 남고 로그 파일에 종료 코드가 남는다.

**최초 1회 — 심볼릭 링크 설치**:

```sh
sudo ln -sf /opt/ddona/app/ops/purge-hidden-novels.sh /opt/ddona/purge-hidden-novels.sh
sudo ln -sf /opt/ddona/app/ops/cron.d/ddona-hidden-novel-purge /etc/cron.d/ddona-hidden-novel-purge
```

**검증**:

```sh
# 1. 수동 1회 실행 — 정상 종료와 마지막 줄 "숨긴 소설 파기: N편 · 숨긴 소설 정리: M편" 확인
sudo -u root /opt/ddona/purge-hidden-novels.sh
tail /var/log/ddona-hidden-novel-purge.log

# 2. 다음 17:35 UTC(KST 02:35)에 크론이 실제로 도는지
tail -f /var/log/ddona-hidden-novel-purge.log
```

⚠️ 17:35 UTC — 다른 크론(05:00·06:00·15:05·16:35·18:00 UTC, 매시 17분, 5분마다)과 겹치지 않는다.

### 3-17. 채팅 단계별 문안 체인·호출 모델 설정 — 켜기 · 끄기 · 되돌리기

모델 배정 표(`prompt_routes`, 어드민 "모델 배정" 화면 `/prompt-routing` 또는 API `PUT /admin/prompt-routing` 으로 저장)는 (레인, 실효 방 모델, 단계) 칸마다 판정·요약·추출이 읽을 문안 체인과 부를
모델을 담는다(소설 레인 칸은 아래 "소설 레인" 단락). 실효 방 모델은 방에 저장된 모델이 아니라 그 턴이 실제로 도는 모델이다 — 상위 모델 스위치가 꺼져 있으면 Opus 를
저장한 방도 Gemini 방 칸이고, 그 턴의 차감도 같은 값으로 Gemini 가격이다(한 요청에서 한 번 정해 판정 문안과 차감이 함께 쓴다).

- **표가 비어 있으면** 모든 칸이 env 규칙(위 `STAT_JUDGMENT_MODEL` 행의 키와 `LLM_CALL_SITE_BACKENDS`)과 같다. 빈 표가 기본 상태다.
- **표를 따르는 곳.** 채팅 방 턴(보내기·재생성·수정)의 스탯·장면 헤더·엔딩·그림 판정, 그 턴 뒤의 요약 접기·장면·사실 추출, 요약
  다시 만들기다. 장면 헤더 칸은 자기 행이 없으면 같은 (레인, 방 모델)의 스탯 판정 행을 물려받는다. 그림 칸은 스토리에서 미디어
  북, 캐릭터에서 상황 이미지 단계다. 빌더 미리보기 판정도 (레인, 그 턴의 실효 모델, 단계) 칸을 같은 규칙으로 읽는다 — 기본
  Gemini 세션은 `gemini` 칸이다("빌더 미리보기 모델" 단락).
- **표를 따르지 않는 칸.** 요약 접기 뒤 인상 생성은 배정 표 단계가 아니라 늘 env 설정(`MEMORY_IMPRESSION_MODEL`)의 체인과
  모델로 돈다 — 장기 기억 인상 기능이 아직 다듬어지는 중이라 단계 표 밖에 둔다. 표에 행이 있어도 인상의 문안·부를 모델은 바뀌지 않는다.
- **행은 문안 체인과 부를 모델을 함께 바꾼다.** 행이 쓰인 칸의 판정·요약·추출 호출은 행의 부를 모델을 행의 경로로 부른다 — 공급자에
  보내는 모델 id, 사용량 집계(어드민 사용량의 호출 위치·모델 칸), 측정 덤프 줄의 모델 칸이 모두 그 모델의 id 다. 행이 Gemini 로
  부르면 실제 Gemini 모델은 판정 종류의 `GEMINI_*_JUDGMENT_MODEL_NAME`(없으면 `GEMINI_MODEL_NAME`)이다. 행이 없거나 건너뛴 칸은
  판정·요약 모델 키의 모델로 부른다.
- **행이 쓰이지 않는 경우.** 그 행의 경로가 지금 env 배정으로 푼 경로와 다르거나, (부를 모델, 경로)가 허용 목록 밖이거나, 직결
  판정의 구조화 깊이가 맞지 않으면 그 칸은 env 규칙으로 돈다. env 배정을 바꾼 뒤에는 `GET /admin/prompt-routing` 의 칸마다 `skipped`
  (건너뛴 행과 이유)를 본다.
- 🔴 **행이 가리킨 체인의 게시본이 저장 뒤 사라지면**(체인을 통째로 보관 처리 등) 그 칸을 쓰는 (레인, 방 모델)의 방 턴과 요약 다시
  만들기가 깎기 전 오류로 막힌다(방 턴은 스트림 전 — 판정 세트가 없을 때와 같은 계약). 행을 지우거나 체인을 다시 게시한다.
- **켜기.** 위 저장 API 로 행을 저장한다(저장 검사가 경로·자격·체인 게시를 본다). 저장 커밋 뒤 캐시가 무효화되어 다음 턴부터 따른다(무효화가 실패해도 프롬프트 세트
  캐시와 같은 TTL 안에 바뀐다). env·재기동은 필요 없다.
- **끄기 · 되돌리기.** 그 행을 뺀 표로 저장한다(표를 비우면 전부 env 규칙). 저장 이력의 이전 스냅샷으로 되돌릴 수도 있다
  (`POST /admin/prompt-routing/revisions/{id}/restore`).
  이미지만 옛 태그로 돌려도 된다 — 표를 읽지 않는 옛 이미지는 행이 있어도 env 규칙으로 돈다. 🔴 다만 표로 문안 체인만 고르고 부를 모델은
  호출에 싣지 않던 이미지로 돌리면 행이 쓰인 칸의 문안은 행의 체인, 호출은 판정·요약 모델 키의 모델로 갈라진다 — 그 태그로
  돌리기 **전에** 부를 모델이 그 키와 다른 행을 표에서 뺀다. 스키마를 내리는 순서는 "상위 모델(채팅
  Opus 직결) — 꺼진 채 배포 · 켜기 · 끄기" 절의 모델 배정 설정·이력 표 문단이다.
- **소설 레인.** 표에는 소설 레인 칸도 있다 — 생성 세 단계(화·구성안·장면 구성안)는 작업 모델(Gemini·Sonnet·Opus)마다 한 칸,
  구조화 네 단계(문단 수정·여러 문단 수정·재검사·경계 제안)는 작업 모델과 무관한 `any` 한 칸이다. 소설 레인은 **따로 저장한다** —
  `PUT /admin/prompt-routing/novel`, 되돌리기 `POST /admin/prompt-routing/novel/revisions/{id}/restore` 가 소설 레인만 바꾼다. 위 기존
  저장·되돌리기 경로는 채팅 두 레인만 바꾸고, 요청에 실린 소설 행(소설 탭을 모르는 낡은 화면이 되돌려 보낸 것)은 버린다. 이력
  스냅샷은 어느 경로든 저장한 뒤의 표 전체이고, 이력의 `lanes` 칸이 경로를 남긴다(NULL = 채팅 경로 또는 이 칸이 생기기 전의 저장,
  `["novel"]` = 소설 경로). 낡은 기준 확인은 레인과 무관하다 — 다른 레인이 먼저 저장했어도 409 다.
  - 이 배포에서는 소설 호출이 표를 읽지 않는다 — 소설 행을 저장해도 소설 작업의 문안·모델·경로는 env 규칙 그대로다. 생성 칸은
    그 뒤에도 체인·부를 모델이 작업 모델로 고정이고(소설 차감이 작업 모델 단가다), 경로는 env 배정과 같을 때만 저장된다 — 경로를
    확인·표시하는 칸이다.
  - 🔴 소설 구조화 칸의 Claude 행은 지금 운영 env 로는 쓰일 수 없다. 소설 구조화 호출 위치에 직결 배정이 없어 Claude 모델이
    Bedrock 으로 풀리므로 저장 검사가 `backend-mismatch` 로 거부하고, 그 배정을 `LLM_CALL_SITE_BACKENDS` 에 넣으면 기동 검증이 api
    를 띄우지 않는다(그 호출 위치의 모델을 기본 모델 Gemini 로만 본다). 조회 응답의 구조화 후보마다 `skippedNow`(지금 env 로
    건너뛸지와 이유)와 `costRatio`(지금 부르는 모델 대비 원가 배수, 입력·출력 따로, 1 미만이면 더 쌈 — 차감액은 그대로)가 실린다.
  - 🔴 운영에 소설 행을 처음 넣기 **전에** 측정 하네스의 프롬프트 동기화(`scripts/memory_eval/prompt_sync.py`)가 내보낸 파일의 배정
    행을 레인으로 거르게 먼저 고친다 — 지금은 소설 행이 하나라도 든 내보내기 파일을 통째로 거부한다.
  - **되돌리기**(스키마 리비전 `2ea446be8eb9` — 생성 행 CHECK 둘을 소설 생성 세 단계까지 넓히고 이력에 `lanes` 칸을 더한다. 옛
    이미지가 쓰는 행은 넓힌 CHECK 를 만족하고 옛 매퍼의 INSERT 는 `lanes` 를 빼 NULL 이 되므로 이미지만 되돌려도 안전하다). 순서:
    ① 소설 행이 있으면 새 이미지·새 화면에서 소설 탭을 비워 저장한다(소설 경로) → ② 어드민 화면을 소설 탭 이전 배포로 → ③ 이미지
    롤백 → ④ 스키마까지 내리려면 새 이미지로 `alembic downgrade 2ea446be8eb9-1`(소설 생성 행이 남아 있으면 지우지 않고 멈추며
    "새 이미지에서 소설 레인을 비워 저장한 뒤 내린다"고 알린다) → revert 병합. 🔴 옛 이미지로 되돌린 동안 옛 배정 화면에서
    **저장하지 않는다** — 옛 저장은 표 전체 교체라 소설 행이 사라진다. 옛 이미지의 되돌리기는 소설 행이 든 스냅샷을 `unknown-stage`
    422 로 거부하므로, 스냅샷 복원은 새 이미지로 돌아온 뒤에만 하고 소설 행은 소설 되돌리기 경로로 되살린다. 새 화면의 소설 저장·
    비우기·되돌리기는 소설 경로가 없는 옛 이미지에서 404 로 막힌다.

```sh
# 읽기 전용 — 소설 행 수, 최근 이력의 저장 경로, 소설 행이 든 이력
sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
  psql -U postgres -d ai_character_chat -At -c "SELECT lane, stage, count(*) FROM prompt_routes GROUP BY 1,2 ORDER BY 1,2;"
sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
  psql -U postgres -d ai_character_chat -At -c "SELECT number, lanes, jsonb_array_length(rows) FROM prompt_route_revisions ORDER BY number DESC LIMIT 5;"
sudo docker compose -f /opt/ddona/app/docker-compose.prod.yml --env-file /opt/ddona/.env exec -T postgres \
  psql -U postgres -d ai_character_chat -At -c "SELECT number FROM prompt_route_revisions WHERE rows @> '[{\"lane\":\"novel\"}]' ORDER BY number DESC;"
```

- 저장·되돌리기는 감사 로그(`admin_action_logs`)에 `prompt-routing-save`·`prompt-routing-restore` 로 한 행씩 남는다. 대상 회원·작품이
  없는 행이라 회원 상세(감사 로그를 읽는 유일한 곳)에 실리지 않아, 이 두 종류를 모르는 옛 이미지로 되돌리기 전에 행을 확인할
  필요가 없다.
- 요약 다시 만들기의 가격(10 클로버)은 표와 무관하게 고정이다. 요약 칸 행이 방 모델마다 다르면 원가(문안 길이와 부를 모델)는 방 모델을 따를 수 있다.

### 3-18. 작품 완전 삭제 — 운영자 스크립트

앱에는 발행된 적 있는 작품을 지우는 경로가 없다 — 작가는 비공개로 돌릴 수 있을 뿐이고, 운영 조치는 상태만 `DELETED` 로
바꾸는 소프트 삭제다(행·그림·대화방이 그대로 남는다). 시드·시험 작품처럼 **기록 자체를 없애야 할 때만**
`apps/api/scripts/purge_contents.py` 를 쓴다. 기본은 계획(읽기만)이고, 적용은 한 트랜잭션, 저장소 정리는 그 뒤의 별도
명령이다 — DB 와 R2 를 한 트랜잭션으로 묶을 수 없어서, 커밋이 실패해도 그림이 먼저 사라지지 않게 순서를 나눈 것이다.

**지우는 것** — 대상 작품의 모든 버전과 그 하위 행(시작설정·상황 이미지·미디어 북 칸 등), 그 작품의 모든 대화방(다른
회원의 방 포함)과 메시지, 그 작품이 원작이거나 그 방에서 나온 소설, 회원이 그 작품에 남긴 좋아요·즐겨찾기·대화 참여·
이미지 노출·신고·엔딩 수집, 대상만 쓰던 그림(작가 이미지 보관함의 생성 이미지도 포함 — 보관함에서도 사라진다)과 소설
삭제로 쓰는 곳이 없어진 삽화 그림, 그림이 모두 없어진 이미지 생성 요청 행. **남는 것** — 운영 조치·통지·조치 기록·응답
신고·버린 응답 기록은 기록이라 행을 남기고, 작품·방·소설을 가리키던 칸만 FK(`SET NULL`)가 비운다. 계획 출력의 행 수
목록에서 이름 끝이 `:set_null` 인 줄이 그것이다.

**거부(종료 2, 쓰기 0)** — 아래 중 하나라도 있으면 계획은 거부 사유를 출력하고 적용은 아무것도 쓰지 않는다.
- 대상 작품의 댓글
- 클로버 사용처 — 작품·방·소설 세 칸 모두 본다(방·소설 칸에는 FK 가 없어 DB 가 막아 주지 않는다)
- 정산 확정 내역
- 대상 소설의 노벨 공개 상태·노벨 구매
- 홈 지정(작품 큐레이션·노벨 큐레이션)
- 대상 밖 작품의 시작설정이 대상과 같은 entity id 를 씀(엔딩 수집이 그 id 로만 이어져 있어 남의 수집까지 지워진다)
- 지울 그림을 남길 소설의 삽화·회원 프로필 이미지·문의 첨부가 씀
- ids 파일에 DB 에 없는 id 가 있음, 적용의 `--expect-contents` 가 ids 파일의 작품 수와 다름

돈·공개·남의 글이 얽힌 경우라 무엇을 남길지는 정책 결정이다. **거부되면 스크립트를 고치거나 우회하지 말고 멈춘다.**

**실행 위치** — 서빙 중인 색의 api 컨테이너 안(`exec -T api_<색>`)이다. 스크립트는 이미지에 들어 있고 컨테이너 env 가
운영 DB·R2 를 이미 가리킨다. ids 파일은 이미지에 없으니 `cp` 로 넣고, apply 가 컨테이너 안에 남기는 키 파일은 **apply
직후** VM 호스트로 꺼낸 뒤 로컬로 `gcloud compute scp` 해 둔다. 다음 배포로 색이 바뀌면 옛 컨테이너가 지워지며 그 안의
파일도 사라지는데, 행이 이미 지워진 뒤라 지울 저장소 키를 다시 만들 근거가 그 파일 하나뿐이다. **그래서 apply 부터
delete-objects 까지 main 병합(= API 자동 배포)을 미룬다.** 아래 명령은 한 SSH 세션 안에서 색이 바뀌지 않는다는 전제다.

```sh
# 0. 로컬 — ids 파일을 만든다. 한 줄에 작품 id(uuid) 하나, 빈 줄과 `#` 로 시작하는 줄은 무시한다. VM 으로 올린다.
gcloud compute scp purge-ids.txt ddona-api:/tmp/purge-ids.txt --zone=asia-northeast3-a --tunnel-through-iap --project=ddona-ai-character-chat

gcloud compute ssh ddona-api --zone=asia-northeast3-a --tunnel-through-iap --project=ddona-ai-character-chat
cd /opt/ddona/app
C="sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env"
A=api_$(sudo bash ops/active-color.sh)
$C cp /tmp/purge-ids.txt $A:/tmp/purge-ids.txt

# 1. 계획 — 읽기만 한다. 대상 작품 목록, 표별 행 수, 지울 그림·저장소 키 수, 거부 사유를 출력한다.
#    종료 0 = 진행 가능 · 2 = 거부 사유 있음(위 "거부" — 여기서 멈춘다).
$C exec -T $A python -u scripts/purge_contents.py plan --ids-file /tmp/purge-ids.txt

# 2. 수동 백업 — DB 를 되돌릴 유일한 길이다. `--manual` 을 빠뜨리면 일단위 보관 칸이 하나 밀려 지워진다("백업 · 복원" 절).
sudo /opt/ddona/backup.sh --manual

# 3. 적용 — 대상 작품 행을 잠그고 계획을 다시 세운 뒤, 거부 사유가 없으면 한 트랜잭션으로 지운다. N 은 ids 파일의 작품
#    수를 손으로 적는다(다른 목록을 지우지 않게). 지울 저장소 키는 커밋 직전에 --keys-out 에 남는다. 이미 있는 파일
#    이름은 거부한다 — 다시 돌릴 때는 새 이름을 쓴다. 종료 0 = 커밋함 · 2 = 거부(쓰기 0, 키 파일 없음).
$C exec -T $A python -u scripts/purge_contents.py apply --ids-file /tmp/purge-ids.txt --expect-contents N --keys-out /tmp/purge-keys.json

# 4. 키 파일 회수 — 바로 한다. 컨테이너 → VM 호스트 → 로컬.
$C cp $A:/tmp/purge-keys.json /tmp/purge-keys.json && sudo chown "$USER" /tmp/purge-keys.json
#    (로컬에서) gcloud compute scp ddona-api:/tmp/purge-keys.json . --zone=asia-northeast3-a --tunnel-through-iap --project=ddona-ai-character-chat

# 5. 확인 — 대상 작품·방이 0 이어야 한다(id 는 ids 파일의 것을 쉼표로 이어 넣는다). 화면에서도 그 작품 상세·작가
#    보관함·홈에 흔적이 없는지 본다. 여기서 이상하면 6 으로 가지 말고 아래 "되돌리기" 의 DB 복원을 한다.
$C exec -T postgres psql -U postgres -d ai_character_chat -c \
  "SELECT (SELECT count(*) FROM contents WHERE id IN ('<id>','<id>')) AS contents,
          (SELECT count(*) FROM chat_rooms WHERE content_id IN ('<id>','<id>')) AS chat_rooms;"
#    7 의 표본 — 키 파일 중 아직 R2 에 있는 객체 수와, 그 하나의 서명 주소를 받아 둔다(GET 이 200 이어야 한다).
$C exec -T $A python -c "import json; from api.core.s3 import get_object_size, generate_per_request_presigned_get_url as url; ks=[k for k in json.load(open('/tmp/purge-keys.json')) if get_object_size(k) is not None]; print(len(ks)); print(url(ks[0]) if ks else '')"

# 6. 저장소 정리 — --apply 없이 먼저 돌려 지울 키 수만 본다. 그 수가 3 의 출력 "저장소 키 M개" 와 같으면 --apply.
#    delete-objects 는 --apply 여부와 상관없이 먼저 키 파일의 키를 assets.storage_key 와 다시 대조해, 아직 DB 에 살아
#    있는 그림의 키가 하나라도 있으면 키 수도 내지 않고 종료 2 로 멈춘다(엉뚱한 키 파일·롤백된 적용으로 살아 있는 그림을
#    지우지 않게). 첫 줄에서 2 가 나오면 --apply 로 가지 않는다. 키 하나가 실패해도 나머지는 지우고 실패한 키를 표준 오류에 남긴다 — 종료 1 이면 같은 명령을 다시 돌린다. 이미 없는
#    키는 R2 가 성공으로 답하므로 재실행이 안전하다(변형 키 중 처음부터 없던 것도 성공으로 셈한다).
$C exec -T $A python -u scripts/purge_contents.py delete-objects --keys-file /tmp/purge-keys.json
$C exec -T $A python -u scripts/purge_contents.py delete-objects --keys-file /tmp/purge-keys.json --apply

# 7. 확인 — 5 의 python 줄을 다시 돌려 남은 객체 수가 0 인지 보고, 5 에서 받아 둔 서명 주소를 GET 해 404 를 본다
#    (서명 유효시간 안에 확인한다 — 지나면 403 이라 판정이 안 된다). HEAD(`curl -I`)는 쓰지 않는다 — GET 으로 서명된 주소다.
curl -s -o /dev/null -w '%{http_code}\n' '<5 에서 받은 주소>'
```

**apply 가 실패하면** — FK 위반 등 삭제 도중의 예외는 트랜잭션 전체가 롤백되고 키 파일은 생기지 않는다(쓰기 0). 출력의
원인을 확인한 뒤 1 의 계획부터 다시 돈다. **커밋 자체가 예외로 끝났으면** 커밋이 실제로 반영됐는지 스크립트가 알 수 없어,
키 파일을 지우지 않고 `<--keys-out>.unconfirmed`(위 예시면 `/tmp/purge-keys.json.unconfirmed`)로 남긴다. 이때는 그 파일을
4 처럼 회수하고, 5 의 SELECT 로 대상이 정말 지워졌는지 본다. 지워졌으면 그 파일을 `--keys-file` 로 6 을 돌린다. 지워지지
않았으면 그 파일은 버리고 1 부터 다시 한다 — 잘못 넘겨도 6 의 살아 있는 키 대조가 종료 2 로 막는다.

**되돌리기** — DB 는 2 의 수동 백업을 "백업 · 복원" 절의 복원 절차로 되살린다. 백업 시각 이후의 운영 데이터(가입·대화·
결제 전부)를 잃으므로 마지막 수단이다. **R2 객체는 DB 백업에 들어 있지 않아 6 의 `--apply` 뒤에는 되돌릴 수 없다** —
그래서 5 에서 DB 와 화면을 먼저 확인하고 나서 6 을 돌린다. 6 전에 DB 를 복원했다면 그 키 파일은 버린다(그대로 돌려도
살아 있는 키 대조가 종료 2 로 막는다).

### 3-19. 로컬 시드 묶음 내보내기 — 운영자 스크립트

운영 작품 몇 편을 로컬 개발용 **비공개 시드 묶음**으로 꺼낼 때 `apps/api/scripts/export_seed_bundle.py` 를 쓴다. 묶음은
로컬 시드(`seed_dev.py`)가 튜토리얼 대신 넣는 꼴 그대로다 — 작품 JSON(발행본이 있으면 발행본, 없으면 초안), 대표
이미지·미디어 북 칸·상황별 이미지 원본, 매니페스트. **읽기 전용이다** — 트랜잭션을 읽기 전용으로 열어 쓰기가 섞여도 DB 가
거부하고, 저장소에서는 내려받기만 한다. 표준 출력에는 작품 수·이미지 수·바이트·sha256 만 찍고 작품 이름·본문은 남기지
않는다.

**거부(종료 2, 묶음 파일 없음)** — 맵 줄 형식 오류·uuid 아님·slug 형식 오류(소문자·숫자·하이픈만, 첫 글자는 하이픈
아님)·같은 작품 두 번, 맵에 DB 에 없는 id 가 있음, 맵의 작품 작가가 한 명이 아님(묶음은 로컬 시드 작가 한 명의 작품이
된다), slug 가 겹침, 발행본도 초안도 없는 작품, `--out` 이나 그 옆 `.partial` 임시 파일이 이미 있음.

종료 1 이면 원본 그림을 못 받았거나 맵 파일이 없는 것 — 묶음 파일은 남지 않는다.

**실행 위치** — 서빙 중인 색의 api 컨테이너 안이다(작품 완전 삭제 절과 같다). 맵 파일은 한 줄에 `<콘텐츠 uuid> <시드
slug>` 이고 빈 줄과 `#` 줄은 건너뛴다. 조감독·민유나는 측정 도구 기본값인 `tutorial-filmclub`·`tutorial-filmclub-yuna`
를 slug 로 준다.

```sh
# 0. 로컬 — 맵을 VM 으로 올린다.
gcloud compute scp seed-map.txt ddona-api:/tmp/seed-map.txt --zone=asia-northeast3-a --tunnel-through-iap --project=ddona-ai-character-chat

gcloud compute ssh ddona-api --zone=asia-northeast3-a --tunnel-through-iap --project=ddona-ai-character-chat
cd /opt/ddona/app
C="sudo docker compose -f docker-compose.prod.yml --env-file /opt/ddona/.env"
A=api_$(sudo bash ops/active-color.sh)
$C cp /tmp/seed-map.txt $A:/tmp/seed-map.txt

# 1. 내보내기 — 종료 0 이면 마지막 줄에 바이트 수와 sha256 이 나온다. 2 면 거부(위 "거부").
$C exec -T $A python -u scripts/export_seed_bundle.py --map /tmp/seed-map.txt --out /tmp/seed-bundle.tar.gz

# 2. 꺼내기 — 컨테이너 → VM 호스트 → 로컬.
$C cp $A:/tmp/seed-bundle.tar.gz /tmp/seed-bundle.tar.gz && sudo chown "$USER" /tmp/seed-bundle.tar.gz
#    (로컬에서) gcloud compute scp ddona-api:/tmp/seed-bundle.tar.gz . --zone=asia-northeast3-a --tunnel-through-iap --project=ddona-ai-character-chat
#    (로컬에서) shasum -a 256 seed-bundle.tar.gz   # 1 의 sha256 과 같아야 한다

# 3. 지우기 — 묶음에는 비공개 작품 본문이 들어 있다. 컨테이너·VM 의 임시 파일을 지운다.
#    컨테이너 쪽은 root 로 지운다 — `cp` 로 넣은 맵 파일은 root 소유라 앱 사용자로는 못 지운다.
$C exec -T -u root $A rm -f /tmp/seed-map.txt /tmp/seed-bundle.tar.gz
rm -f /tmp/seed-map.txt /tmp/seed-bundle.tar.gz
```

**로컬에서 풀기** — 묶음 안에는 최상위 폴더가 없다. `apps/api/scripts/seed_content/private/` 에 풀고 내려받은 tar.gz 는
지운다. 그 폴더는 gitignore 이고 **커밋하지 않는다**(저장소는 공개다). 시드가 묶음을 어떻게 넣는지는 `DEV.md` 의 비공개
시드 묶음 단락에 있다.

```sh
mkdir -p apps/api/scripts/seed_content/private
tar -xzf seed-bundle.tar.gz -C apps/api/scripts/seed_content/private/ && rm seed-bundle.tar.gz
```

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
비밀번호 재설정)도 같은 모양이다(`window` `auth`, `auth/router.py`의 `_auth_too_many_requests`). 429 가 아닌 것이 하나 있다 — 클로버로 낼 채팅 턴·이미지 요청이
실어 보낸 가격표 버전(`priceVersion`)이 서버 가격표(`core/clover.py` 의 `PRICE_VERSION`)와 다르면 깎기 전에 409
`CLOVER_PRICE_CHANGED`(+ 그 요청의 지금 금액 `currentCost`)다. 버전을 싣지 않은 요청과 무료·토큰으로 지나는 요청은 대조하지 않는다. 생성 전에는 `GET /capabilities`를 TTL 캐시
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
sudo /opt/ddona/backup.sh --manual   # 먼저 백업
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
- **무중단 교체가 지키지 못하는 것 — 컨테이너 안 백그라운드 작업.** 정지는 요청(SSE 채팅 턴 포함)과 그 요청에 붙은
  `BackgroundTasks` 까지 기다린다 — 응답 뒤 `BackgroundTasks` 로 도는 턴 뒤 기억 요약·추출은 교체 때 기다려진다(상한
  `stop_grace_period` 65초, 넘으면 끊긴다. 끊기면 기억 요약은 다음 턴에 다시 한다). 요청과 상관없이 `asyncio.create_task` 로
  띄운 작업 — 이미지 생성 잡(운영 최대 약 42초), 소설 작업(상한 360초) — 은 기다리지 않고 옛 색이 멈출 때 함께
  끊긴다(단일 컨테이너 시절의 완전교체도 같았다). 소설 작업은 워커 스위치(`NOVELIZE_WORKER_ENABLED`)가 켜져 있으면 연쇄(부모와 그 부모가 직접 돌리는 자식 — 워커는 자식 행을 집지 않는다)를 뺀
  6종이 api 밖 워커에서 돌아 교체가 끊지 않는다 — api 안에 남아 끊기는 것은 연쇄와, 스위치를 끈 동안의 모든 소설 작업이다
  ("소설화 켜기 · 끄기 · 회수 · 롤백" 절). 이미지 생성은 Redis 의 락·대기열
  칸이 TTL 로 풀리고("이미지 생성" 절), 잡 기록은 1시간 TTL 까지 진행 중으로 남는다 — 끊긴 잡의 환불 경로는 확인하지 않았다.
  끊긴 소설 작업은 진행 중으로 남는다. 워커가 떠 있으면 워커가 60초마다 모든 소설의 만료 작업을 환불한다. 워커가 없으면(스위치
  꺼짐) 예전 그대로다 — 새 프로세스가 기동 뒤 heartbeat 만료 + 10초(기본 70초)에 죽은
  작업을 한 번 일괄 환불하는데, 이 정리는 "옛 프로세스가 새 프로세스보다 먼저 죽었다"는 전제다. blue/green 에서는 옛 색이 새 색
  기동 **뒤**(healthy 약 15~35초 + 드레인 최대 65초)에 멈추므로 옛 색에서 끊긴 작업의 heartbeat 가 그 일괄 정리 시점에 아직 만료되지
  않아 놓칠 수 있다 — 놓친 작업은 그 소설을 열거나 폴링할 때의 지연 정리가 환불하고, 그때까지 차감액이 묶인다. 소설화는 허용
  명단 계정에만 열려 있어 영향이 작다.
- **드레인 유예(65초)보다 긴 요청은 교체 때 끊긴다.** 지금 가장 긴 동기 요청은 발행 자동 심사(상한 60초)다. 상위 모델(Opus)
  채팅 턴은 실측 평균 11.5초·최대 16.7초로 이 유예 안에 든다. 이보다 긴 요청을 열 때는 `docker-compose.prod.yml`의
  `stop_grace_period`를 다시 정한다.
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
