# apps/api

- `uv`로 관리되는 독립 Python 프로젝트. pnpm workspace/turborepo 범위 밖이므로 루트 `pnpm run typecheck` 등에 걸리지 않는다 — 이 앱의 quality check(`uv run mypy src migrations`, `uv run pytest` 등)는 항상 `apps/api` 안에서 별도로 실행해야 한다.
- src-layout: 패키지명은 `api`(`src/api/`), 모듈 경로는 `api.main`/`api.core.config`/`api.db.session` 식으로 임포트한다. `uv sync`가 이 패키지를 editable로 설치하므로 `uv run` 안에서는 항상 `import api...`가 그대로 동작한다.
- DB 연결 문자열은 `api.core.config.settings.database_url` (pydantic-settings, `.env`/`DATABASE_URL` env var)이 유일한 source of truth다. `alembic.ini`의 `sqlalchemy.url`은 플레이스홀더일 뿐이며 `migrations/env.py`가 기동 시점에 `config.set_main_option`으로 덮어쓴다 — 마이그레이션용 DB URL을 따로 관리하지 않는다.
- `migrations/env.py`의 `target_metadata`는 `api.db.base.Base.metadata`를 가리킨다. 새 모델은 반드시 이 `Base`를 상속해야 `alembic revision --autogenerate`가 인식한다.
- mypy는 `pyproject.toml`의 `[tool.mypy]`에서 `strict = true`로 설정되어 있다. 새 모듈 추가 시 타입 힌트 누락이 있으면 바로 실패한다.
