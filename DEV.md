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

## 4) (선택) 원격 접속 — 태블릿/폰에서 실기기 확인

이 서비스의 North Star가 "늦은 밤 침대에서 혼자"라 실기기 확인이 중요하다. Mac에서 돌아가는 dev 서버를
[Tailscale](https://tailscale.com)의 `serve`로 감싸면 태일넷 안의 다른 기기에서 **HTTPS 단일 오리진**으로 접속할 수 있다.
web과 API가 같은 오리진이 되므로 CORS·쿠키 문제가 아예 발생하지 않고, 진짜 인증서라 Google 로그인도 그대로 동작한다.

```
https://<호스트>.<테일넷>.ts.net/      → localhost:5173  (web)
https://<호스트>.<테일넷>.ts.net/api/  → localhost:8000  (API, /api 프리픽스는 serve가 제거)
```

### 1회 준비

1. **테일넷 HTTPS 켜기** — [관리 콘솔 → DNS](https://login.tailscale.com/admin/dns) 아래 **HTTPS Certificates → Enable HTTPS**.
   안 켜면 `tailscale cert`가 `your Tailscale account does not support getting TLS certs`로 실패한다.
2. **내 MagicDNS 이름 확인** — `tailscale status --json | jq -r .Self.DNSName` (끝의 `.` 제외).
3. **serve 설정** (tailscaled에 영구 저장 → 재부팅해도 유지, 1회만):
   ```sh
   tailscale serve --bg --set-path=/api http://localhost:8000
   tailscale serve --bg http://localhost:5173
   tailscale serve status   # 확인
   ```
4. **Google Cloud Console** 승인된 리디렉션 URI에 추가 (localhost 항목은 그대로 두고 병기):
   ```
   https://<호스트>.<테일넷>.ts.net/api/auth/google/callback
   ```
5. **env 전환** — `apps/api/.env`:
   ```sh
   API_BASE_URL=https://<호스트>.<테일넷>.ts.net/api
   FRONTEND_BASE_URL=https://<호스트>.<테일넷>.ts.net
   ```
   `apps/web/.env.local` (신규, gitignore 대상):
   ```sh
   VITE_API_BASE_URL=https://<호스트>.<테일넷>.ts.net/api
   ```

`apps/web/vite.config.ts`의 `server.allowedHosts: [".ts.net"]`은 이미 커밋되어 있다 — 없으면 Vite가
`Blocked request. This host is not allowed.`로 막는다.

### 사용

서버 기동 명령은 §2 그대로다(`--host` 플래그 불필요 — serve가 localhost로 프록시한다). 준비가 끝나면 위 URL로 접속만 하면 된다.

- **Mac에서도 이 URL을 쓴다.** `http://localhost:5173`으로 열면 API만 ts.net이라 cross-site가 되어 세션 쿠키가 안 붙고,
  Google 로그인 리디렉션도 ts.net으로 간다. 로컬 전용으로 되돌리려면 위 env 3개를 localhost로 되돌린다.
- SSE 채팅 스트리밍과 Vite HMR 웹소켓 모두 serve를 통과하는 것을 확인했다(버퍼링·업그레이드 실패 없음).
- `SESSION_COOKIE_SECURE`는 `false`로 둔다. HTTPS에서도 쿠키는 정상 동작하고, `true`로 올리면 http 접속 여지가 사라진다.

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
- **캐릭터 목록이 비어 있음**: `pytest`가 세션 종료 시 `alembic downgrade base`까지 돌려 테이블을 비운다(`apps/api/CLAUDE.md` 참고).
  `cd apps/api && uv run alembic upgrade head && uv run --env-file .env python scripts/seed_dev.py`로 복구.
- **`.env`에 JSON 값(리스트 등)을 넣었더니 API가 `SettingsError`로 기동 실패**: `uv run --env-file`의 dotenv 파서가 값 안의 `"`를
  셸 인용부호로 보고 벗겨낸다(`["a","b"]` → `[a,b]` → JSON 파싱 실패). **전체를 홑따옴표로 감쌀 것**: `KEY='["a","b"]'`.
  `--env-file` 없이 띄우면 pydantic이 `.env`를 직접 읽어 이 문제가 안 나타나므로 재현 조건에 주의.
- **`pnpm ... dev -- --host` 의 플래그가 무시됨**: pnpm 9는 `--` 구분자를 받지 않는다. `--`를 빼고 `pnpm ... dev --host`로 쓸 것.
- **원격 접속 시 `Blocked request. This host is not allowed.`**: `apps/web/vite.config.ts`의 `server.allowedHosts` 확인.
  raw IP 접속에는 안 걸리고 호스트명(MagicDNS 등) 접속에서만 발생한다.
