# chat-lab 호스팅 서비스

측정 런 묶음을 팀이 함께 보는 곳(`lab.ddona.site`)이다. 운영자가 자기 Mac 의 측정 서버(`apps/chat-lab`, 서버 코드는
`apps/api/scripts/chat_lab/`)에서 만든 런 묶음을 올리고, 팀원은 브라우저에서 Google 로 로그인해 같은 웹 화면으로 본다.

- **올리기**: 운영자 Mac 의 업로드 CLI(측정 서버에서 묶음을 받아 올리는 명령)가 Cloudflare Access 서비스 토큰으로 올린다. 사람
  로그인으로는 올릴 수 없다. 명령과 자격 파일은 `apps/chat-lab/README.md` 「올리기」 절에 있다.
- **읽기·지우기**: 허용 목록에 든 팀원이 Google 로그인으로 목록·판·묶음을 보고, 런을 지운다. 서비스 토큰으로는 읽을 수 없다.
- 서비스는 또나 앱 코드(`apps/api`)와 측정 서버 코드를 import 하지 않는다. LLM 호출도 없다.

## 구성

```
 운영자 Mac                                         팀원 브라우저
 측정 서버(로컬 DB · 런 폴더)                          │
   └─ 업로드 CLI ── 서비스 토큰 ──┐                     │ Google 로그인
                                  ▼                     ▼
          Cloudflare Access — lab.ddona.site 전체를 막고, 허용한 사람·토큰의 요청에만 JWT 를 붙여 넘긴다
                                  │
                                  ▼ Cloudflare Tunnel — VM 의 cloudflared 가 바깥으로 먼저 연 연결(VM 포트 게시 0)
 VM · compose 프로젝트 ddona-lab
     cloudflared ── 망 lab_edge ──▶ chat-lab-service :8000 — JWT 를 다시 검증, 허용 목록 대조, 요청마다 접근 기록
                                          │ 망 ddona_default
                                          ▼
 VM · compose 프로젝트 ddona(또나)
     postgres — DB chat_lab(역할 chat_lab). 또나 DB 와 같은 인스턴스
```

- 이미지 하나에 서비스(FastAPI)와 웹 정적 파일(`apps/chat-lab` 의 호스팅 모드 빌드 결과 — `apps/chat-lab/README.md`
  「호스팅 모드」)이 함께 든다. 웹은 이미지 밖에서 빌드해 넣는다.
- 배포 묶음은 이 폴더에 있다: `Dockerfile`·`.dockerignore`·`docker-compose.lab.yml`. 또나 앱 배포(deploy-api)의 트리거 밖이라 손으로
  배포한다(「손 배포」 절).
- CI 는 `.github/workflows/chat-lab-service.yml`(린트·타입·스키마 드리프트·마이그레이션 대조·테스트, PR 에서 이미지 빌드).

## 설정 키

모두 env 로 받고(접두사 `LAB_`), 운영에서는 compose 의 `env_file`(VM 의 서비스 env 파일, 「3. 파일 자리(VM)」)로 들어간다. 값은 저장소 어디에도 적지 않는다
— 이 표도 꼴만 적는다. 이름이 `.env.example` 로 끝나는 견본 파일은 만들지 않는다: `ops/check_env.py --examples` 가 키 출처를 등록하지
않은 그런 파일을 실패시킨다.

| 키 | 뜻 | 비밀 | 꼴 |
|---|---|---|---|
| `LAB_DATABASE_URL` | 서비스와 마이그레이션이 쓰는 DB 주소 | **예** — 비밀번호가 들어 있다 | `postgresql+asyncpg://chat_lab:<비밀번호>@postgres:5432/chat_lab` |
| `LAB_ACCESS_ISSUER` | Access 발급자. 토큰의 `iss` 와 정확히 비교하고, 공개키 주소 `<발급자>/cdn-cgi/access/certs` 를 만든다 | 아니오 | Zero Trust 팀 도메인을 `https://` 로 시작해 끝 `/` 없이. 어기면 기동 실패 |
| `LAB_ACCESS_AUD` | Access 앱의 AUD 태그. 토큰의 `aud` 에 들어 있어야 한다 | 아니오(식별자) | Access 앱 화면의 AUD 태그 그대로 |
| `LAB_READ_EMAILS` | 읽기·지우기를 허용할 사람 이메일. 대소문자는 가리지 않는다 | 아니오(개인정보 — 저장소에 적지 않는다) | 쉼표로 이은 목록. 비면 기동 실패 |
| `LAB_UPLOAD_CLIENT_IDS` | 올리기를 허용할 서비스 토큰의 Client ID(토큰 JWT 의 `common_name`) | 아니오 — 비밀은 Client Secret 이고 올리는 쪽에만 있다 | 쉼표로 이은 목록. 비면 기동 실패 |
| `LAB_WEB_DIR` | 웹 정적 파일 폴더 | 아니오 | 기본 `/app/web`(이미지 안 자리). 운영에서는 적지 않는다 |

- 인증을 끄거나 건너뛰는 설정은 없다.
- 마이그레이션(`alembic`)은 `LAB_DATABASE_URL` 하나만 읽는다 — Access 설정 없이 돈다.
- 풀 크기·접근 기록 보관 기간·크기 상한은 설정이 아니라 코드의 상수다.

## 로컬 개발

```sh
cd apps/chat-lab-service
uv sync --locked

# 시험. 시험 DB 이름은 `_test` 로 끝나야 한다 — 세션이 그 DB 를 지우고 다시 만든다. 다른 세션과 부딪히지 않게 이름을 가른다.
# 저장소의 개발 Postgres(`docker-compose.dev.yml`)를 그대로 쓰면 된다.
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/chat_lab_service_<이름>_test uv run pytest

# 마이그레이션
LAB_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/<DB 이름> uv run alembic upgrade head

# 웹이 쓰는 서비스 스키마를 떨군다 → apps/chat-lab/service-openapi.json. 커밋한다 — CI 가 다시 떨궈 커밋본과 맞춰 본다.
uv run python scripts/dump_openapi.py

# CI 와 같은 검사
uv run ruff check src migrations scripts tests
uv run ruff format --check src migrations scripts tests
uv run mypy src migrations scripts tests
```

로컬에서 서비스를 띄워도 `/api/health` 밖의 요청은 Access JWT 가 없어 모두 401 이다. 동작은 시험(가짜 공개키·서명한 시험 토큰)으로
본다.

## 라우트와 상태 코드

| 메서드 | 경로 | 신원 | 하는 일 |
|---|---|---|---|
| GET·HEAD | `/api/health` | 보지 않는다 | `{"status":"ok"}` 고정. DB·판·설정을 싣지 않는다. 바깥에서는 Access 를 지나야 닿는다 |
| GET | `/api/runs` | 사람 | 런 목록 — 런마다 최신 판과 살아 있는 판 수, 목록 칸(`run`). 최신 판의 올린 때 내림차순 |
| GET | `/api/runs/{runId}/versions` | 사람 | 그 런의 살아 있는 판 목록(최신 먼저) |
| GET·HEAD | `/api/runs/{runId}/versions/{sha256}/bundle` | 사람 | 묶음 본문. gzip 을 받는 클라이언트에는 올린 바이트 그대로(`Content-Encoding: gzip`), 아니면 풀어서 |
| POST | `/api/runs/{runId}/versions` | 서비스 토큰 | 올리기. 아래 「올리기」 |
| DELETE | `/api/runs/{runId}` | 사람 | 런 지우기. `Content-Type: application/json`, 본문 `{"runId": "<경로와 같은 값>"}` |
| GET·HEAD | `/`·`/assets/*` | 사람 | 웹 정적 파일 |

- **401** `unauthenticated`: JWT 가 없거나 무효(서명·발급자·aud·만료·알고리즘 …). 본문은 하나이고 세부 이유는 접근 기록에만 남는다.
- **404** `notFound`: 허용 목록 밖, 그 경로에 맞지 않는 신원(사람 경로에 서비스 토큰 등), 진짜 없음 — 셋이 바이트까지 같은 본문이다.
  신원이 틀리면 경로 인자 꼴 검사보다 먼저 404 다.
- **403 은 쓰지 않는다.** 403 은 Access 가 요청을 막을 때의 몫이라, 사용자가 본 403 은 언제나 Access 쪽이고 서비스의 거부(401·404)와
  섞이지 않는다. 허용 밖에는 "있지만 못 본다"를 알리지 않으려고 없음과 같은 404 를 준다.
- **405**: 있는 경로의 다른 메서드. **413** `tooLarge`: 크기 상한을 넘었다. **422**: 올린 묶음·머리·삭제 본문의 꼴(이유 값은
  `apps/chat-lab/service-openapi.json` 의 `ServiceError`)과 경로 인자 꼴(FastAPI 검증, `reason` 없음). **503**: Access 공개키를 받지
  못했다(`keysUnavailable`), DB 에 닿지 않는다(`dbUnavailable`). **500** `internal`.
- 모든 응답에 `X-Content-Type-Options: nosniff`·`Content-Security-Policy: frame-ancestors 'none'`·`Referrer-Policy: no-referrer`.
  `/api/*` 와 오류 응답은 `Cache-Control: no-store`, 정적 파일은 `no-cache`(ETag 로 다시 확인).

### 올리기

- 본문은 묶음 JSON 을 gzip 으로 압축한 바이트(`Content-Type: application/gzip`), 올리기 머리는 요청 헤더 `X-Lab-Upload-Header` 에 JSON
  으로 싣는다. 머리는 측정 서버의 올리기 머리 응답 그대로다 — 형식은 `apps/chat-lab/README.md` 「묶음 계약 판과 출처 칸」. 출처 칸이
  실패면 받지 않는다.
- **크기 상한**: 압축 바이트 8MiB, 푼 바이트 32MiB. 상한과 같은 크기는 받는다. 실제로 읽은 바이트로 세므로 `Content-Length` 를 적지
  않은 청크 전송도 같은 상한에 걸리고, 압축 폭탄도 32MiB 를 조금 넘는 데서 멈춘다. 올리기 머리와 삭제 본문은 4KiB 가 상한이고, 넘으면
  413 이 아니라 422(`badUploadHeader`·`badDeleteBody`)다.
- 계약 판(`contractVersion`)은 정수 1 이상이면 그대로 저장한다. 그 판을 읽을 수 있는지는 웹이 판정한다.
- 응답: 새 판은 201 `created`. 같은 런에 같은 내용(압축 푼 JSON 바이트의 sha256 이 같다)이 살아 있으면 200 `exists` — 저장된 만든
  커밋·출처·올린 이는 처음 것 그대로다. 지운 판과 같은 내용이면 200 `restored`(아래 「지우기」).

## 런과 판

### 같은 런 식별

서비스는 측정 서버의 `runId` 를 그대로 런의 이름으로 쓴다. `runId` 는 런 루트 기준 드라이버 로그 경로에서 나오므로
(`apps/chat-lab/README.md` 「묶음 id」) 묶음 폴더를 `archive/` 로 옮기거나 측정 서버의 `--root` 를 바꿔 런 루트 기준 상대 경로가
달라지면 같은 런이 **다른 런**으로 들어온다. 옛 런은 저절로 사라지지 않는다 — 필요하면 사람이 지운다. 자리가 같은데 내용이 바뀌면(방 공유 주의가 바뀐 경우 포함) 같은
`runId` 의 **새 판**이다.

### 최신 판

- 최신 판 = 그 런의 지우지 않은 판 가운데 처음 들어온 순서로 가장 늦은 판이다.
- 같은 내용을 다시 올리면 새 판이 생기지 않는다. 그래서 A → B → A 로 올리면 최신은 B 로 남는다.
- 판 번호는 들어온 순서다. 지운 판도 번호를 차지해 남은 판의 번호가 바뀌지 않는다.

### 지우기

- 런을 지우면 그 `runId` 의 모든 판이 지워진다. 묶음 본문만 비우고 판 행(sha256·올린 이·지운 이·지운 때)은 남긴다. 지운 런은
  목록에서 빠지고, 판 목록·묶음 꺼내기·다시 지우기는 404 다.
- 지운 판과 같은 내용을 다시 올리면 그 판이 되살아난다(`restored`). 되살린 판의 올린 이·때·만든 커밋·출처는 이번 올리기 값이다.

## 접근 기록

- 앱에 닿은 요청은 거부(401·404·405·413·422·503)까지 모두 DB 표 `access_log` 에 한 행씩 남는다: 시각, 신원 종류(`none`·`human`·
  `service`·`unknown`)와 신원(사람 이메일·서비스 토큰 Client ID), 메서드, 경로 틀(`/api/runs/{runId}` 꼴, 정적은 `/{static}`, 맞는
  라우트가 없으면 `unmatched`), runId, sha256, 원문 포함 묶음을 내줬는가, 상태, 거부 이유, 클라이언트 IP(`CF-Connecting-IP` 가 IP 로
  읽힐 때만).
- 남기지 않는 것: JWT, 어떤 헤더 값, 본문, 경로 원문.
- **90일** 지난 행은 서비스가 기동할 때 한 번, 그 뒤 24시간마다 스스로 지운다. VM 크론은 없다.
- **기록 밖**: 앱에 닿지 않은 요청. Access 가 막은 요청은 VM 에 오지 않는다(Cloudflare 의 Access 기록에 남는다). uvicorn 이 HTTP 로
  읽지 못한 요청도 앱 전에 끝난다. uvicorn 자체 접근 로그는 끈다.
- 기록을 쓰지 못해도 응답은 그대로 나가고, 컨테이너 로그에 "접근 기록을 쓰지 못했다" 와 예외 이름만 남는다.

## 백업 없음 — 복구는 다시 올리기

DB `chat_lab` 은 백업하지 않는다. 또나의 일일 백업은 또나 DB 하나만 덤프하므로 `chat_lab` 은 거기에도 없다. 잃으면 다시 올려 되살린다:
로컬에 남은 올리기 기록의 목록을 업로드 CLI 로 다시 올린다(기록 파일의 자리·칸과 다시 올리는 명령은 `apps/chat-lab/README.md`
「올리기」). 그러려면 **원본 런 폴더와 그 런을 돈 로컬 DB 가 남아 있어야 한다**(올리기
머리의 출처 칸을 로컬 DB 로 다시 계산한다). 원본이 한 PC 에만 있으면 그 PC 를 잃을 때 서비스 데이터도 함께 잃는다. 다시 올려도 되살지
않는 것: 접근 기록, 지우기 이력(누가 언제 지웠나), 원본을 지운 런. 되살아도 달라지는 것: 올린 때·올린 이는 다시 올린 값이 되고, 판
번호와 최신 판은 다시 올린 순서를 따른다 — A → B → A 로 올려 최신이 B 이던 런을 B, A 순으로 다시 올리면 최신이 A 다.

## 손 배포

**원칙.** VM 명령은 운영자가 승인한 단계마다 하나씩 돈다. VM 호스트 설정(sysctl·Docker 데몬 설정·방화벽·systemd)은 바꾸지 않는다.
비밀값(DB 비밀번호·Tunnel 토큰)은 사람이 자기 터미널의 표준 입력으로만 넣는다 — 채팅·명령행·셸 기록·에이전트 세션에 값이 남지 않게.
VM 접속은 `gcloud compute ssh ddona-api --zone=asia-northeast3-a --tunnel-through-iap`(DEPLOY.md 「BE → GCE VM」 절과 같다).

아래 명령에서 쓰는 줄임:

```sh
L="sudo docker compose -p ddona-lab -f /opt/ddona/lab/docker-compose.lab.yml --env-file /opt/ddona/lab/image.env"
```

### 1. 대시보드 쪽(사람)

아래 순서대로 만든다. **Access 앱을 Tunnel 공개 호스트보다 먼저** 만든다 — 공개 호스트가 생기는 순간 `lab.ddona.site` 가 바깥에
열리므로, 그때 이미 Access 가 그 도메인 전체를 막고 있어야 한다. Access 앱이 고를 로그인 방법과 Service Auth 정책이 고를 서비스 토큰은
앱보다 먼저 있어야 한다.

- **Google 로그인 방법**: Google Cloud 에 OAuth 클라이언트(웹 애플리케이션)를 만들고, 리디렉션 URI 는 Access 의 로그인 방법 화면이
  보여 주는 콜백 주소를 넣는다. 클라이언트는 또나 로그인이 쓰는 옛 GCP 프로젝트(DEPLOY.md 「Google OAuth (로그인)」 절)가 아니라 배포
  프로젝트에 만든다 — OAuth 동의 화면은 프로젝트당 하나라 옛 프로젝트의 동의 화면을 바꾸면 또나 로그인이 막힐 수 있다.
- **서비스 토큰**: 만들 때 한 번 보이는 Client Secret 은 업로드하는 Mac 의 자격 파일에만 둔다(꼴·권한·만드는 명령은
  `apps/chat-lab/README.md` 「올리기」). Client ID 가 `LAB_UPLOAD_CLIENT_IDS` 가 된다.
- **Access 앱**: 자체 호스팅 앱, 도메인 `lab.ddona.site` 전체(경로 없음), 로그인 방법은 Google 하나. 정책 둘 — 팀원 이메일을 허용하는
  Allow 정책, 업로드 서비스 토큰을 허용하는 **Service Auth** 정책(Allow 로 두면 토큰 요청도 로그인 화면으로 돌려보낸다. Include →
  Service Token 으로 그 토큰을 직접 고른다 — Any Access Service Token 은 계정의 모든 토큰이 지나므로 고르지 않는다). 앱의 AUD
  태그와 팀 도메인이 `LAB_ACCESS_AUD`·`LAB_ACCESS_ISSUER` 가 된다.
- **Tunnel**: Cloudflare 대시보드의 **Networking > Tunnels** 에서 cloudflared Tunnel 을 만든다(Zero Trust 대시보드 메뉴가 아니다 —
  [공식 안내](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/)).
  설치 화면에 나오는 토큰은 3단계에서 VM 파일로 넣는다. 그다음 그 Tunnel 의 **Routes** 탭에서 Add route → Published application 으로
  공개 호스트를 단다 — 서브도메인 `lab`, 도메인 `ddona.site`, **Service URL** 한 칸에 `http://chat-lab-service:8000`. 대상은 서비스
  이름으로만 적고 IP 로 적지 않는다 — cloudflared 가 붙은 망은 일반 브리지라 IP 로 적으면 호스트·다른 주소로도 길이 날 수 있다.

### 2. DB·역할 만들기(VM, 사람)

비밀번호는 사람이 자기 터미널에서 `openssl rand -hex 24`(영숫자 48자라 URL 인코딩이 필요 없다)로 만들고 아래 프롬프트에 붙여 넣는다.

```sh
sudo docker exec -it ddona-postgres-1 psql -U postgres
```

```sql
CREATE ROLE chat_lab NOLOGIN CONNECTION LIMIT 5;
CREATE DATABASE chat_lab OWNER chat_lab;
REVOKE ALL ON DATABASE chat_lab FROM PUBLIC;
\password chat_lab
ALTER ROLE chat_lab LOGIN;
```

- 역할을 로그인 없이 만들고 비밀번호를 정한 뒤에 로그인을 켠다. `\password` 는 psql 이 해시로 바꿔 보내므로 원문이 서버 로그·psql 기록에
  남지 않는다.
- 연결 상한 5 = 서비스 풀 3 + 마이그레이션 1 + 여유 1. 또나와 나눠 쓰는 인스턴스의 연결을 lab 이 그 이상 쓰지 못한다.
- 또나 DB 의 기본 접속 권한(PUBLIC CONNECT)은 건드리지 않는다 — `chat_lab` 역할은 또나 DB 에 접속은 되지만 표 권한이 없다. 만든 뒤
  읽을 수 있는 표가 0 인지 본다(읽기만):

```sh
sudo docker exec -i ddona-postgres-1 psql -U postgres -d ai_character_chat -Atc "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relkind IN ('r','v','m','p') AND n.nspname NOT IN ('pg_catalog','information_schema') AND has_table_privilege('chat_lab', c.oid, 'SELECT');"   # 0
```

### 3. 파일 자리(VM)

| 자리 | 내용 | 소유·권한 | 비밀 |
|---|---|---|---|
| `/opt/ddona/lab.env` | 서비스 env(「설정 키」의 다섯 줄) | `root:root` `0600` | 예 — 사람만 쓴다 |
| `/opt/ddona/lab-tunnel-token` | Tunnel 토큰 한 줄 | `root:65532` `0440`(cloudflared 이미지의 실행 사용자 uid 65532 가 그룹으로 읽는다) | 예 |
| `/opt/ddona/lab/docker-compose.lab.yml` | 병합 커밋의 이 폴더 compose 사본 | `root:root` `0644` | 아니오 |
| `/opt/ddona/lab/image.env` | `LAB_SERVICE_IMAGE=chat-lab-service:<태그>` 한 줄(보간 전용) | `root:root` `0644` | 아니오 |

또나 env(`/opt/ddona/.env`)는 어디에도 쓰지 않는다. 비밀 두 파일은 빈 파일을 권한부터 정해 만든 뒤, 사람이 값을 표준 입력으로 붙여
넣는다(붙여 넣고 Enter, 그리고 Ctrl-D). `tee` 는 이미 있는 파일의 권한을 바꾸지 않는다.

```sh
sudo install -d -o root -g root -m 0755 /opt/ddona/lab
sudo install -o root -g root -m 0600 /dev/null /opt/ddona/lab.env
sudo install -o root -g 65532 -m 0440 /dev/null /opt/ddona/lab-tunnel-token
sudo tee /opt/ddona/lab.env > /dev/null              # 사람: 다섯 줄 붙여 넣기 → Enter → Ctrl-D
sudo tee /opt/ddona/lab-tunnel-token > /dev/null     # 사람: 토큰 한 줄 붙여 넣기 → Enter → Ctrl-D

# 확인 — 값 없이 권한·크기와 키 이름만
sudo stat -c '%n %U:%G %a %s' /opt/ddona/lab.env /opt/ddona/lab-tunnel-token
sudo cut -d= -f1 /opt/ddona/lab.env
```

### 4. 이미지 만들기·옮기기(운영자 Mac → VM)

선행 조건: 웹 호스팅 모드와 업로드 CLI 가 main 에 들어온 뒤의 커밋에서 빌드한다 — 그 전 커밋의 웹은 런 목록을 로컬 측정 서버에서
찾아 이 서비스에서는 목록이 뜨지 않는다. 호스팅 모드가 무엇을 바꾸는지는 `apps/chat-lab/README.md` 「호스팅 모드」 절에 있다.

레지스트리를 쓰지 않는다. 병합 커밋의 깨끗한 트리에서 웹과 이미지를 만든다 — 태그(커밋 앞 7자리)가 이미지 내용과 맞고, 웹과 서비스가
같은 커밋에서 나오게 하려는 것이다.

```sh
SHA=<병합 커밋>
TAG=${SHA:0:7}
git worktree add --detach "/tmp/lab-build-$TAG" "$SHA"
cd "/tmp/lab-build-$TAG"
pnpm install --frozen-lockfile
VITE_CHAT_LAB_MODE=hosted pnpm --filter chat-lab run build   # → apps/chat-lab/dist
docker build --platform linux/amd64 --provenance=false \
  --build-context web=apps/chat-lab/dist -t "chat-lab-service:$TAG" apps/chat-lab-service
docker save "chat-lab-service:$TAG" | gzip > "/tmp/chat-lab-service-$TAG.tar.gz"
gcloud compute scp --zone=asia-northeast3-a --tunnel-through-iap \
  "/tmp/chat-lab-service-$TAG.tar.gz" apps/chat-lab-service/docker-compose.lab.yml ddona-api:/tmp/
```

VM 에서(`TAG` 는 같은 값):

```sh
gunzip -c "/tmp/chat-lab-service-$TAG.tar.gz" | sudo docker load
sudo install -o root -g root -m 0644 /tmp/docker-compose.lab.yml /opt/ddona/lab/docker-compose.lab.yml
echo "LAB_SERVICE_IMAGE=chat-lab-service:$TAG" | sudo tee /opt/ddona/lab/image.env
rm "/tmp/chat-lab-service-$TAG.tar.gz" /tmp/docker-compose.lab.yml
```

`--provenance=false` 는 증명(attestation) 항목을 붙이지 않고 이미지 하나만 만든다 — VM 으로 옮길 것은 그 이미지뿐이다. Mac 쪽
정리: `git worktree remove "/tmp/lab-build-$TAG"`, 압축 파일 삭제.

### 5. 마이그레이션 → 기동 → 확인(VM)

마이그레이션은 기동과 다른 단계다. 서비스는 기동할 때 DB 리비전이 코드의 head 와 같은지 보고 다르면 뜨지 않는다 — 마이그레이션을
빠뜨린 배포가 요청마다 500 이 아니라 기동 실패로 드러난다. 그래서 순서를 바꾸면 서비스가 뜨지 않는다.

```sh
$L run --rm -T chat-lab-service alembic upgrade head < /dev/null
$L up -d --wait
$L ps                                                   # Restarting 이 아닌지
$L exec -T chat-lab-service python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/health').read().decode())"   # {"status":"ok"}
$L logs --since 10m cloudflared | grep 'Registered tunnel connection'
sudo docker stats --no-stream ddona-lab-chat-lab-service-1 ddona-lab-cloudflared-1   # compose 의 mem_limit 을 실측으로 다시 볼 때
```

서비스에는 상태 검사(healthcheck)를 두지 않는다 — 검사 요청마다 접근 기록이 한 행씩 쌓이기 때문이다. 그래서 `--wait` 는 컨테이너가
실행 중이 되기만 기다리고, 기동이 실패해 재시작을 되풀이해도(예: 마지막 이메일을 빼 `LAB_READ_EMAILS` 가 비어 설정 검증이 실패) 통과할
수 있다. 기동 확인은 위의 `$L ps`(Restarting 이 아닌지)와 health 줄이 한다 — 아래 다른 절의 `--wait` 뒤에도 이 두 줄을 이어서 돈다.

그 뒤 사람이 브라우저로 `https://lab.ddona.site/` 에 들어가 Google 로그인 → 목록이 뜨는지 본다. 목록 대신 "이 화면은 로컬 빌드다"
안내가 뜨면 호스팅 모드가 아닌 웹이 이미지에 실린 것이다 — 「4. 이미지 만들기·옮기기(운영자 Mac → VM)」의 웹 빌드 줄
(`VITE_CHAT_LAB_MODE=hosted`)로 이미지를 다시 만든다.

### 6. 옛 이미지 정리(VM)

VM 에는 lab 이미지가 배포마다 쌓인다. 또나 배포 워크플로의 이미지 정리는 api 이미지 저장소만 넘기므로 lab 이미지는 손으로 정리한다 —
같은 스크립트에 저장소 이름만 바꿔 넘기면 최근 3개와 실행 중인 이미지만 남긴다.

```sh
sudo env PYTHONPATH=/opt/ddona/app/apps/api/scripts /usr/bin/python3 -m ops.prune_api_images --repo chat-lab-service --keep 3
```

## 롤백

순서는 **Tunnel 끊기 → 컨테이너 내리기 → DB 지우기**다. 빠르고 되돌릴 수 있는 것부터 한다 — 바깥 길을 끊으면 그 즉시 아무도
서비스에 닿지 않고, 되돌릴 수 없는 DB 지우기는 맨 끝이다.

1. **바깥 길 끊기.** 급하면 `$L stop cloudflared` — 그 즉시 바깥에서 닿지 않는다(`restart: unless-stopped` 라 손으로 멈춘 것은 다시
   뜨지 않는다). 다시 쓰지 않을 거면 대시보드에서 공개 호스트 이름 `lab.ddona.site` 를 지운다.
2. **컨테이너 내리기.** `$L down` — `ddona-lab` 프로젝트의 컨테이너와 망 `lab_edge` 만 지운다. `ddona` 프로젝트와 `ddona_default` 는
   그대로다.
3. **DB 지우기 — 되돌릴 수 없다.** 백업이 없으므로 먼저 「백업 없음 — 복구는 다시 올리기」 절대로 로컬 올리기 기록과 원본이 남아
   있는지 확인한다.

   ```sh
   sudo docker exec -i ddona-postgres-1 psql -U postgres -c 'DROP DATABASE chat_lab WITH (FORCE);'
   sudo docker exec -i ddona-postgres-1 psql -U postgres -c 'DROP ROLE chat_lab;'
   ```

4. **정리(선택).** VM: `sudo rm -r /opt/ddona/lab`, 비밀 두 파일은 열지 않고 `sudo rm /opt/ddona/lab.env /opt/ddona/lab-tunnel-token`,
   이미지는 `sudo docker image ls chat-lab-service` 로 본 태그를 `sudo docker image rm` 으로. 대시보드: Access 앱·서비스 토큰·Google
   로그인 방법·Tunnel(남아 있으면 DNS 의 `lab` 레코드도), Google Cloud 의 OAuth 클라이언트.
5. **코드 revert 는 떠 있는 lab 을 바꾸지 않는다.** 손 배포라 저장소 변경이 VM 으로 가는 길이 없다 — 위 단계가 롤백이다.

### 부분 롤백 — 이전 이미지로

```sh
# 1) 돌아갈 태그의 마이그레이션 head(이미지 안 파일만 읽고 DB 에 닿지 않는다)와 지금 DB 리비전
sudo docker run --rm chat-lab-service:<옛 태그> alembic heads
$L run --rm -T chat-lab-service alembic current < /dev/null
# 2) 둘이 다르면 서비스를 멈추고, 그 리비전을 아는 지금 이미지로 스키마를 내린다
$L stop chat-lab-service
$L run --rm -T chat-lab-service alembic downgrade <1 의 옛 head> < /dev/null
# 3) 이미지 참조를 옛 태그로 바꿔 띄운다
echo "LAB_SERVICE_IMAGE=chat-lab-service:<옛 태그>" | sudo tee /opt/ddona/lab/image.env
$L up -d --wait
$L ps                                                   # Restarting 이 아닌지 — 상태 검사가 없어 --wait 는 기동 실패를 잡지 못한다
# 이어서 「5. 마이그레이션 → 기동 → 확인(VM)」의 health 줄을 돈다
```

옛 태그가 정리돼 VM 에 없으면 그 커밋에서 「4. 이미지 만들기·옮기기(운영자 Mac → VM)」를 다시 한다.

## VM 재구축

VM 을 옮겨도 DNS 는 그대로다 — 공개 호스트 이름은 Tunnel 을 가리키고, Tunnel 은 VM 의 cloudflared 가 바깥으로 연 연결이라 VM 주소와
무관하다. 새 VM 에서 또나 스택이 뜬 뒤 「손 배포」를 「2. DB·역할 만들기(VM, 사람)」부터 같은 순서로 한다(Tunnel 토큰은 같은 것을 다시 넣는다). 데이터는
「백업 없음 — 복구는 다시 올리기」 절대로 다시 올린다. 옛 VM 의 cloudflared 가 아직 떠 있으면 같은 Tunnel 에 커넥터가 둘 붙어 요청이 두
VM 으로 나뉜다 — 옛 쪽을 먼저 멈춘다.

## 팀원 추가·빼기

**두 곳**을 함께 고친다: Access 정책의 이메일과 서비스의 `LAB_READ_EMAILS`. 더할 때 한쪽만 하면 그 사람은 Access 에서 막히거나,
Access 는 지나도 서비스에서 404 를 받는다.

뺄 때는 **서비스 쪽부터** 뺀다. Access 는 이미 로그인한 사람의 정책을 그 세션이 끝날 때 다시 본다(세션 기본 24시간) — 정책에서 빼도
그 사람은 세션이 남은 동안 Access 를 지나고, `LAB_READ_EMAILS` 에도 남아 있으면 서비스도 통과시킨다. 그 즉시 막는 수단은 둘이다:
`LAB_READ_EMAILS` 에서 빼고 서비스 컨테이너를 다시 만드는 것(아래 명령), 그리고 Zero Trust 의 사용자 화면에서 그 사람의 세션을
취소하는 것. Access 정책에서 빼는 것은 다음 로그인을 막는다.

```sh
sudo -e /opt/ddona/lab.env                                      # 사람: LAB_READ_EMAILS 줄만 고친다
$L up -d --wait --force-recreate chat-lab-service               # env 는 컨테이너를 만들 때 읽힌다
$L ps                                                   # Restarting 이 아닌지 — 상태 검사가 없어 --wait 는 기동 실패를 잡지 못한다
# 이어서 「5. 마이그레이션 → 기동 → 확인(VM)」의 health 줄을 돈다
```

## 비밀값 규칙

| 값 | 비밀 | 있는 곳 |
|---|---|---|
| DB 비밀번호(`LAB_DATABASE_URL` 안) | 예 | VM 의 서비스 env 파일(「3. 파일 자리(VM)」), Postgres(해시) |
| Tunnel 토큰 | 예 | VM 의 Tunnel 토큰 파일(「3. 파일 자리(VM)」), Cloudflare 대시보드 |
| 서비스 토큰 Client Secret | 예 | 업로드하는 Mac 뿐 — VM 에도 서비스에도 없다 |
| Google OAuth 클라이언트 비밀 | 예 | Google Cloud, Access 로그인 방법 설정 |
| Access 팀 도메인·AUD 태그·서비스 토큰 Client ID·허용 이메일 | 아니오 — 그래도 저장소에 적지 않는다 | VM 의 서비스 env 파일, 대시보드 |

- 비밀값은 채팅·명령행·셸 기록·저장소·에이전트 세션에 붙이지 않는다. 넣는 것은 사람이 표준 입력으로 한다.
- 에이전트는 비밀 두 파일을 열지 않고, `docker compose config`·Env 를 싣는 `docker inspect`·`docker exec … env`·`printenv` 를 쓰지
  않는다(모두 `lab.env` 값을 그대로 보인다). 확인은 「3. 파일 자리(VM)」의 값 없는 명령으로 한다.

## 운영 노트

- **Google OAuth 클라이언트는 6개월 동안 쓰이지 않으면 Google 이 자동으로 지운다.** 예고 메일이 오면 lab 에 한 번 로그인한다. 이미
  지워졌으면 30일 안에 Google Cloud 에서 되살린다.
- **서비스 토큰은 만료된다(기본 1년).** 만료되면 올리기가 Access 에서 막혀 서비스까지 오지 않는다. 만료 전에 대시보드에서 기간을
  늘린다. 새 토큰으로 바꾸면 Client ID 가 달라지므로 세 곳을 함께 바꾼다 — Access 앱 Service Auth 정책이 고른 토큰,
  `LAB_UPLOAD_CLIENT_IDS`(「팀원 추가·빼기」와 같은 재생성), 업로드하는 Mac 의 자격 파일(`apps/chat-lab/README.md` 「올리기」).
  정책을 빠뜨리면 올리기가 Access 에서 막혀 업로드 CLI 가 3xx·401·403 문구로 끝난다.
- cloudflared 가 UDP 수신 버퍼 경고를 남겨도 VM 커널 설정을 바꾸지 않는다. 특히 `sysctl --system` 은 Docker 가 켜 둔 IP 포워딩을 꺼
  또나 트래픽까지 끊은 적이 있다(DEPLOY.md 「겹침 대비 운영 설정 — Postgres max_connections · 스왑」 절).

## 또나 쪽에 주는 결과

또나 런북(DEPLOY.md)의 「chat-lab 호스팅 서비스 — 별도 compose, 별도 배포」 절이 이 절을 가리킨다.

- **앱 배포와 무관하다.** deploy-api 의 트리거 경로에 이 폴더가 없고, 교체 스크립트는 `ddona` 프로젝트의 서비스만 이름으로 다룬다.
  또나를 배포해도 lab 은 재시작되지 않고, lab 을 바꾸려면 「손 배포」를 손으로 돈다.
- **lab 서비스 컨테이너가 `ddona_default` 망에 붙어 있다**(Bugsink 와 같다). 또나 스택을 `down` 할 때는 lab 을 먼저 내리고, 또나를
  다시 띄운 뒤 lab 을 띄운다 — 또나의 `down` 은 그 망을 지우려 하는데 붙은 컨테이너가 있으면 지우지 못하고, lab 은 그 망이 없으면
  뜨지 않는다(`external`).

  ```sh
  $L down
  # … 또나 down · up (DEPLOY.md) …
  $L up -d --wait
  $L ps                                                   # Restarting 이 아닌지 — 상태 검사가 없어 --wait 는 기동 실패를 잡지 못한다
  # 이어서 「5. 마이그레이션 → 기동 → 확인(VM)」의 health 줄을 돈다
  ```

- **같은 Postgres 인스턴스를 쓴다.** `chat_lab` 역할이 연결을 최대 5개 더 쓴다. Postgres 를 재시작하면 그동안 lab 의 DB 요청도 실패한다
  (503 `dbUnavailable`).
- **`chat_lab` DB 는 백업 밖이다.** 또나 DB 를 복원하려고 Postgres 볼륨을 새로 만들면 `chat_lab` 도 사라진다 — 그때는 「손 배포」의
  「2. DB·역할 만들기(VM, 사람)」부터 다시 하고 다시 올린다.
