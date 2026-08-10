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
- 시드된 계정으로 바로 로그인해도 된다(비밀번호는 아래 [시드 콘텐츠](#시드-콘텐츠-스토리-30개--캐릭터) 참고).
- 홈에는 '미아' 외에 장르별 시드 스토리 30개도 함께 올라와 있다.

## 4) (선택) 원격 접속 — 태블릿/폰에서 실기기 확인

이 서비스의 North Star가 "늦은 밤 침대에서 혼자"라 실기기 확인이 중요하다. Mac에서 돌아가는 dev 서버를
[Tailscale](https://tailscale.com)의 `serve`로 감싸면 태일넷 안의 다른 기기에서 **HTTPS 단일 오리진**으로 접속할 수 있다.
web과 API가 같은 오리진이 되므로 CORS·쿠키 문제가 아예 발생하지 않고, 진짜 인증서라 Google 로그인도 그대로 동작한다.

```
https://<호스트>.<테일넷>.ts.net/      → localhost:5173  (web)
https://<호스트>.<테일넷>.ts.net/api/  → localhost:8000  (API, /api 프리픽스는 serve가 제거)
https://<호스트>.<테일넷>.ts.net/s3/   → localhost:5001  (moto, 썸네일·이미지)
```

**`/s3`를 빠뜨리면 이미지가 하나도 안 나온다.** 자산 URL은 `S3_ENDPOINT_URL`을 그대로 붙여 서명하므로,
그 값이 `http://localhost:5001`인 채로 다른 기기에서 접속하면 그 `localhost`는 **보고 있는 기기 자신**을
가리켜 전부 깨진다(썸네일·상황별 이미지 전부). 화면엔 깨진 이미지만 보이고 콘솔 에러도 안 뜬다.

### 1회 준비

1. **테일넷 HTTPS 켜기** — [관리 콘솔 → DNS](https://login.tailscale.com/admin/dns) 아래 **HTTPS Certificates → Enable HTTPS**.
   안 켜면 `tailscale cert`가 `your Tailscale account does not support getting TLS certs`로 실패한다.
2. **내 MagicDNS 이름 확인** — `tailscale status --json | jq -r .Self.DNSName` (끝의 `.` 제외).
3. **serve 설정** (tailscaled에 영구 저장 → 재부팅해도 유지, 1회만):
   ```sh
   tailscale serve --bg --set-path=/api http://localhost:8000
   tailscale serve --bg --set-path=/s3 http://localhost:5001
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
   S3_ENDPOINT_URL=https://<호스트>.<테일넷>.ts.net/s3
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
- **이미지가 `NoSuchBucket`으로 깨지면** moto 컨테이너의 `S3_IGNORE_SUBDOMAIN_BUCKETNAME=1`이 안 걸린 것이다
  (`docker-compose.dev.yml`에 있다 — 옛 컨테이너가 떠 있으면 `docker compose -f docker-compose.dev.yml up -d --force-recreate moto s3-init`).
  moto는 기본적으로 Host 헤더의 첫 라벨을 버킷 이름으로 보는 virtual-hosted-style이라, serve를 앞에 두면
  버킷명을 `<호스트>`로 착각한다. moto는 인메모리라 재생성하면 객체가 사라지니 **시드를 다시 돌릴 것.**
- **tailscale IP 직결(`http://100.x.y.z:5001`)로 우회하지 말 것** — curl로는 되지만 web이 HTTPS라
  브라우저가 mixed content로 막아 화면에선 여전히 안 보인다.
- 이건 dev 전용 문제다. 운영은 R2가 자체 도메인으로 HTTPS 서명 URL을 주므로 해당 없음.

## 시드 콘텐츠 (스토리 30개 + 캐릭터)

`./dev-up.sh`(또는 `cd apps/api && uv run --env-file .env python scripts/seed_dev.py`)가 장르 10종 × 3개 = **스토리 30개**와
메이저 캐릭터 1개, 그리고 기존 샘플 캐릭터 '미아'를 전부 **발행 상태**로 넣는다. 고정 UUID 업서트라 몇 번을 돌려도 행이 늘지 않고,
`docker compose -f docker-compose.dev.yml down -v`로 DB를 통째로 날려도 `./dev-up.sh` 한 번이면 같은 상태로 돌아온다.

### 계정

| 역할 | 이메일 | 비밀번호 | 시드가 만드나 |
|---|---|---|---|
| 작가 — 시드 콘텐츠 전부의 소유자 | `seed-creator@example.com` | `password1234` | O |
| 독자 | `test@example.com` | `password1234` | O |
| 관리자(`apps/admin`, 5174) | `admin@example.com` | `password1234` | **X — 아래 참고** |

**관리자 계정은 시드가 만들지 않는다.** `admin_users`는 공개 가입이 없는 완전 별도 테이블이라
`seed_dev.py`가 손대지 않는다 — 즉 `docker compose ... down -v`로 DB를 날리면 이 계정만 사라지고
`./dev-up.sh`로도 돌아오지 않는다. 없으면 admin 화면에 로그인할 방법 자체가 없으니 다시 넣을 것:

```sh
cd apps/api && H=$(uv run python -c "from api.core.security import hash_password; print(hash_password('password1234'))") \
  && docker exec ai-character-chat-dev-postgres-1 psql -U postgres -d ai_character_chat \
    -c "insert into admin_users (id, email, password_hash) values (gen_random_uuid(), 'admin@example.com', '$H')
        on conflict (email) do update set password_hash = excluded.password_hash;"
```

신고 처리 화면(`/reports/{id}`)은 **PENDING 신고가 있어야** 렌더된다 — web에서 아무 콘텐츠나
'더보기 → 신고'로 하나 만들면 된다(자기 콘텐츠도 신고할 수 있다).

작가 계정으로 로그인하면 시드된 콘텐츠를 **빌더에서 소유자로 열어** 볼 수 있다 — 시드가 콘텐츠마다
발행본 옆에 초안 버전을 하나 같이 넣기 때문이다(프로덕션 발행이 다음 편집용 초안을 남기는 것과 같은 모양).
초안을 고쳐 발행하면 v2 가 생기고, 그 콘텐츠로 이미 열려 있던 대화방은 v1 에 고정된 채 `latestVersionAvailable=true`
가 되어 `POST /chat-rooms/{id}/pin-latest-version` 으로 옮겨탈 수 있다(메시지·턴 수는 보존). 단 **재시드는
발행본을 in-place 로 덮어쓸 뿐 새 버전을 만들지 않으므로**, 손으로 발행한 v2 가 있으면 재시드가 발행 포인터를
v1 로 되돌린다.
(`POST /auth/login` 성공 응답은 200이 아니라 `204 No Content` + `Set-Cookie: session_id=...`다.)

### 데이터 파일

콘텐츠의 진실은 DB가 아니라 리포에 커밋된 JSON이다.

```
apps/api/scripts/seed_content/data/
├── stories/{slug}.json        # 스토리 30개 (파일명 = slug)
├── characters/{slug}.json     # 캐릭터
├── diversity_matrix.json      # 30개 콘셉트 원본 (tasks/prd-genre-seed-content.md §7의 전사본)
└── image_prompts.json         # 이미지 생성 프롬프트
```

**스토리 문구를 고칠 때는 빌더나 DB가 아니라 JSON을 고치고 시드를 다시 돌린다** — 시드는 자기 UUID 행을 파일 값으로 덮어쓰므로
빌더에서 손으로 고친 내용은 다음 시드에 지워진다. JSON에는 UUID를 적지 않는다(로더가 파일 안의 **위치**로 파생한다).
그래서 이미 시드된 콘텐츠의 리스트(엔딩·스탯·키워드북 등) 중간에 항목을 끼워 넣으면 그 뒤 항목의 id가 전부 밀린다 — **새 항목은 항상 뒤에 붙일 것.**
고친 JSON은 `cd apps/api && uv run pytest tests/test_seed_content_data.py`가 DB 없이 검증한다(발행 검증 + 엔딩 규칙 도달 가능성).

### 이미지

`apps/api/scripts/seed_content/images/`는 **gitignore**다(생성물 바이너리를 리포에 넣지 않는다). 그래서 새 머신에서는 썸네일·상황 이미지가
장르별 색으로 그려진 **절차적 목업 PNG**로 뜬다 — 채팅·발행·이미지 매칭 동작에는 영향이 없다.

진짜 애니메 이미지가 필요하면 `apps/api/.env`에 `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_API_TOKEN`을 채우고:

```sh
cd apps/api
uv run --env-file .env python scripts/generate_seed_images.py --dry-run    # 키 없이 조립된 프롬프트만 출력
uv run --env-file .env python scripts/generate_seed_images.py             # 아직 없는 것만 생성
uv run --env-file .env python scripts/generate_seed_images.py --only romance-3rdloop-dj --force
```

- 파일명 규약: 콘텐츠 썸네일 `{콘텐츠slug}.png`, 상황 이미지 `{캐릭터slug}-scene{n}.png`(1-based). 이 이름이 아니면 시드가 목업으로 폴백한다.
- 생성 후 시드를 다시 돌려야 S3(moto)에 올라간다. moto는 인메모리라 컨테이너를 재생성할 때마다 시드가 매번 재업로드한다.
- **재생성한 이미지는 원본과 픽셀 단위로 같지 않다.** Cloudflare Workers AI에 시드값을 보낼 수 없어 같은 프롬프트라도 매번 다른 그림이 나온다 — 커밋된 건 프롬프트뿐이고, 원본 픽셀은 어디에도 보존되지 않는다.

## 구성 요소

| 서비스 | 포트 | 비고 |
|---|---|---|
| Postgres | 5432 | 볼륨(`pgdata`)으로 데이터 유지 |
| Redis | 6379 | 세션·이메일코드·미리보기세션(휘발성) |
| moto (S3 호환) | 5001 | **인메모리** — 컨테이너 재생성 시 업로드 객체 소실 (macOS 5000=AirPlay 회피) |
| API | 8000 | `uv run --env-file .env uvicorn ...` |
| web | 5173 | 기본 다크 |

### 여러 체크아웃이 이 인프라를 나눠 쓸 때

워크트리나 두 번째 클론에서 동시에 작업할 때, 컨테이너는 하나를 공유해도 된다. **충돌하는 건 pytest끼리다** —
기본값이 어느 체크아웃에서나 같은 `ai_character_chat_test`/Redis 1번인데, 스위트가 끝날 때 `alembic downgrade base`로
그 안의 테이블을 전부 지운다. 한쪽이 테스트 중일 때 다른 쪽이 끝나면 그대로 깨진다. 체크아웃마다 다른 값을 주면 된다:

```sh
export TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ai_character_chat_<이름>_test
export TEST_REDIS_URL=redis://localhost:6379/<인덱스>
```

- **`.env`에 적으면 안 된다** — `conftest.py`가 `os.environ`을 직접 읽으므로, `uv run pytest`처럼 `--env-file` 없이
  돌리면 `.env`는 프로세스 환경에 주입되지 않아 조용히 무시되고 기본 DB로 간다. `export`가 확실하다.
- **DB 이름은 `_test`로 끝날 것** — 아니면 `conftest`가 `RuntimeError`로 거부한다(오설정 시 실패 모드가 "dev DB 전체 삭제"라 방어함).
  DB 자체는 없으면 자동 생성되므로 미리 만들 필요 없다.
- **Redis 인덱스 배분**: `0` = dev, `1` = 기본 pytest, `2`~`15` = 병렬 체크아웃용. 1번을 재사용하면 기본 실행과 부딪힌다.
- dev DB(`ai_character_chat`)와 S3는 신경 쓸 것 없다 — pytest는 dev DB를 건드리지 않고, S3는 `conftest`가
  인프로세스 moto를 랜덤 포트로 띄워 이미 프로세스마다 격리돼 있다.

오버라이드가 왜 그렇게 동작하는지(직접 대입 vs `setdefault`, import 순서)는 `apps/api/CLAUDE.md`의 "테스트 DB 인프라" 항목에 있다.

## 트러블슈팅

- **썸네일이 깨져 보임(이미지 404)**: moto는 인메모리라 `docker compose down`/재생성 시 업로드된 이미지가 사라집니다. `uv run --env-file .env python apps/api/... ` 대신 루트에서 `./dev-up.sh`를 다시 돌리면(또는 `cd apps/api && uv run --env-file .env python scripts/seed_dev.py`) 재업로드됩니다. 채팅 자체는 이미지와 무관하게 동작합니다.
- **모든 화면 500 + `NoCredentialsError`**: API를 `--env-file .env` 없이 띄운 경우입니다. boto3가 자격증명을 못 찾은 것이니 위 명령대로 `--env-file .env`로 실행하세요.
- **Google 로그인 후 redirect_uri_mismatch**: Cloud Console 승인된 리디렉션 URI가 `http://localhost:8000/auth/google/callback`와 정확히 일치해야 합니다.
- **채팅 응답이 안 옴 / LLM 에러**: `.env`의 `GEMINI_API_KEY` 확인.
- **`pnpm typecheck`가 zod 등 이상한 에러**: 먼저 `pnpm install`(stale node_modules).
- **DB를 완전히 초기화하고 싶을 때**: `docker compose -f docker-compose.dev.yml down -v` 후 `./dev-up.sh`.
- **캐릭터 목록이 비어 있음**: `cd apps/api && uv run alembic upgrade head && uv run --env-file .env python scripts/seed_dev.py`로 복구.
  (`pytest`는 dev DB를 건드리지 않는다 — 별도의 `ai_character_chat_test`를 쓴다. `apps/api/CLAUDE.md` 참고.)
- **시드 캐릭터의 문구/프롬프트를 고치고 싶을 때**: `apps/api/scripts/seed_dev.py`를 고친 뒤 그대로 다시 실행하면 된다.
  고정 UUID upsert라 재실행이 스크립트의 값으로 덮어쓴다. 직접 만든 대화방·자산은 건드리지 않는다.
  (단 '미아' 얘기다 — 시드 스토리 30개와 메이저 캐릭터는 `seed_dev.py`가 아니라 `seed_content/data/`의 JSON이 원본이다. 위 [시드 콘텐츠](#시드-콘텐츠-스토리-30개--캐릭터) 참고.)
- **`.env`에 JSON 값(리스트 등)을 넣었더니 API가 `SettingsError`로 기동 실패**: `uv run --env-file`의 dotenv 파서가 값 안의 `"`를
  셸 인용부호로 보고 벗겨낸다(`["a","b"]` → `[a,b]` → JSON 파싱 실패). **전체를 홑따옴표로 감쌀 것**: `KEY='["a","b"]'`.
  `--env-file` 없이 띄우면 pydantic이 `.env`를 직접 읽어 이 문제가 안 나타나므로 재현 조건에 주의.
- **`pnpm ... dev -- --host` 의 플래그가 무시됨**: pnpm 9는 `--` 구분자를 받지 않는다. `--`를 빼고 `pnpm ... dev --host`로 쓸 것.
- **원격 접속 시 `Blocked request. This host is not allowed.`**: `apps/web/vite.config.ts`의 `server.allowedHosts` 확인.
  raw IP 접속에는 안 걸리고 호스트명(MagicDNS 등) 접속에서만 발생한다.
