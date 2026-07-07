# apps/api

FastAPI + SQLAlchemy 2.0(async) + Alembic 백엔드. `uv`로 관리되는 독립 Python 프로젝트이며 pnpm workspace 범위 밖에 있다 (`techspec-overview-backend.md` §2).

## 개발

```sh
uv sync                                    # 의존성 설치
cp .env.example .env                       # 로컬 DATABASE_URL 설정
uv run uvicorn api.main:app --reload       # 개발 서버 (http://localhost:8000)
uv run mypy src migrations                 # 타입체크
uv run alembic revision --autogenerate -m "..."  # 마이그레이션 생성
uv run alembic upgrade head                # 마이그레이션 적용
```
