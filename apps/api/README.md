# apps/api

FastAPI + SQLAlchemy 2.0(async) + Alembic 백엔드. `uv`로 관리되는 독립 Python 프로젝트이며 pnpm workspace 범위 밖에 있다 (`techspec-overview-backend.md` §2).

## 개발

```sh
uv sync                                    # 의존성 설치
cp .env.example .env                       # 로컬 DATABASE_URL 설정
uv run uvicorn api.main:app --reload       # 개발 서버 (http://localhost:8000)
uv run mypy src migrations scripts         # 타입체크
uv run alembic revision --autogenerate -m "..."  # 마이그레이션 생성
uv run alembic upgrade head                # 마이그레이션 적용
uv run python scripts/export_openapi.py    # openapi.json export (FE 코드젠 입력)
```

## FE 타입 코드젠

`apps/api`의 OpenAPI 스펙을 `packages/api-types`의 TypeScript 타입으로 코드젠한다 (`techspec-overview-backend.md` §3).

```sh
uv run python scripts/export_openapi.py   # apps/api/openapi.json 갱신
pnpm --filter @ai-character-chat/api-types run codegen   # packages/api-types/src/generated.ts 갱신
```

스펙이 바뀔 때마다(엔드포인트 추가/변경) 위 두 명령을 순서대로 다시 실행하고, 갱신된 `openapi.json`/`generated.ts`를 함께 커밋한다.

## Docker

```sh
docker build -t ai-character-chat-api .
docker run --rm -p 8000:8000 ai-character-chat-api
curl http://localhost:8000/health
```

