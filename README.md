# 또나 (ddona)

AI 캐릭터·스토리를 직접 만들고, 다른 사람이 만든 캐릭터와 롤플레이 대화를 나누는 반응형 웹 서비스. 이용 연령과 콘텐츠 등급은 [PRODUCT.md](PRODUCT.md)의 Product Purpose 절과 [CONTENT_POLICY.md](CONTENT_POLICY.md)에 있다.

- 서비스: https://ddona.site
- 어드민: https://admin.ddona.site
- API: https://api.ddona.site

## 구성

pnpm + Turborepo 모노레포다. 백엔드(`apps/api`)만 `uv`로 관리되는 독립 Python 프로젝트라 pnpm 워크스페이스 밖에 있다.

| 경로 | 내용 | 스택 |
|---|---|---|
| `apps/web` | 사용자 앱 — 탐색, 채팅, 캐릭터·스토리 빌더 | React 19, Vite, TanStack Router/Query, Jotai, RHF + zod, Cloudflare Pages(+ Worker) |
| `apps/admin` | 운영자 앱 — 신고·이의제기·문의 처리, 콘텐츠·사용자 관리, 공지·약관, 프롬프트 세트, 이용 지표 | React 19, Vite, TanStack Router/Query, Recharts |
| `apps/api` | 백엔드 | FastAPI, SQLAlchemy 2.0(async), Alembic, PostgreSQL, Redis, Google Gemini |
| `packages/ui` | 공용 컴포넌트와 디자인 토큰(`src/styles/globals.css`) | Tailwind CSS |
| `packages/api-types` | `apps/api`의 OpenAPI 스펙에서 코드젠한 TypeScript 타입 | openapi-typescript |
| `packages/config` | 공용 tsconfig·ESLint 설정 | |
| `ops/` | 운영 VM의 cron·백업·로그 로테이션 스크립트 | |

## 빠르게 시작하기

사전 준비: Docker Desktop, Node + pnpm 9, [uv](https://docs.astral.sh/uv/), Google OAuth 클라이언트, Gemini API 키.

```sh
./dev-up.sh   # Postgres·Redis·로컬 S3 기동 → .env 생성 → 마이그레이션 → 시드
```

처음 실행했다면 `apps/api/.env`에 `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GEMINI_API_KEY`를 채우고 한 번 더 실행한다. 그다음 터미널을 나눠 서버를 띄운다.

```sh
# API (http://localhost:8000) — --env-file 을 빼면 썸네일 URL 서명이 실패한다
cd apps/api && uv run --env-file .env uvicorn api.main:app --reload --port 8000

# web (http://localhost:5173)
pnpm install && pnpm --filter @ai-character-chat/web dev

# admin (http://localhost:5174, 선택)
pnpm --filter @ai-character-chat/admin dev
```

시드 계정, 실기기 접속(Tailscale), 여러 체크아웃이 인프라를 나눠 쓰는 법, 트러블슈팅은 [DEV.md](DEV.md)에 있다.

## 자주 쓰는 명령

```sh
# 프론트엔드 (저장소 루트)
pnpm lint
pnpm typecheck
pnpm test
pnpm build

# 백엔드 (apps/api) — 로컬 Postgres/Redis 가 떠 있어야 한다
uv run ruff check src migrations scripts tests
uv run mypy src migrations scripts tests
uv run pytest --cov
```

API 스키마를 바꿨다면 FE 타입을 다시 만들고 두 생성물을 함께 커밋한다. 어긋나면 CI가 막는다.

```sh
cd apps/api && uv run python scripts/export_openapi.py          # openapi.json
pnpm --filter @ai-character-chat/api-types run codegen          # generated.ts
```

## CI

`.github/workflows/`의 워크플로는 경로 필터가 걸려 있어 바뀐 영역의 것만 PR과 main 푸시에서 돈다.

- **api** — ruff, mypy, `alembic check`, `openapi.json` 드리프트, pytest(커버리지 95% 미만이면 실패), Docker 빌드
- **web / admin** — typecheck, 테스트(web), 빌드
- **lint** — ESLint, `generated.ts` 드리프트
- **citations** — 코드·문서에 gitignore된 내부 문서명이나 결정 번호를 인용하지 않았는지 검사
- **deploy-api** — `apps/api` 등이 바뀐 main 푸시 때 API 이미지를 빌드해 운영 VM에 배포

## 문서

| 문서 | 내용 |
|---|---|
| [PRODUCT.md](PRODUCT.md) | 사용자, 제품 목적, 브랜드 성격, 디자인 원칙 |
| [DESIGN.md](DESIGN.md) | 비주얼 시스템 — 색, 타이포, 레이아웃, 모션. UI를 고치기 전에 읽는다 |
| [DEV.md](DEV.md) | 로컬 개발 환경 전체 |
| [DEPLOY.md](DEPLOY.md) | 운영 인프라(GCE VM + Cloudflare Pages + R2)와 배포·백업 런북 |
| [apps/api/README.md](apps/api/README.md) | 백엔드 개발 명령 |
| `CLAUDE.md` (각 디렉터리) | 영역별 구현 규약과 함정 |
