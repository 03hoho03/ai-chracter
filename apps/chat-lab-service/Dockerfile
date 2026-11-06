# syntax=docker/dockerfile:1
#
# chat-lab 호스팅 서비스 이미지. 빌드 명령은 같은 폴더 README.md 의 「4. 이미지 만들기·옮기기(운영자 Mac → VM)」 한 곳에 적는다.
#
# 기본 빌드 컨텍스트가 이 폴더라 `apps/api`·측정 런 폴더·저장소 루트 `.env` 는 구조적으로 이미지에 들어올 수 없다. 웹 정적
# 파일은 이름 붙은 빌드 컨텍스트 `web` 로만 받는다 — 웹 빌드는 이미지 밖에서 끝내고 결과 폴더 하나만 넘기므로 이미지 안에는
# pnpm·Node 가 없다. 이름 붙은 빌드 컨텍스트를 읽으려고 첫 줄에서 Dockerfile 문법 판을 지정한다.

FROM python:3.11-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.15 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# 의존을 먼저 깐다 — 소스만 바뀐 빌드가 이 층을 다시 쓴다.
COPY uv.lock pyproject.toml ./
RUN uv sync --locked --no-install-project --no-dev

# 실행에 쓰는 것만 경로를 지정해 복사한다. 폴더째 복사하면 `.dockerignore` 에서 빠뜨린 파일(로컬 env·시험 자료)이 따라 들어온다.
# `alembic.ini`·`migrations` 는 손 배포의 마이그레이션 단계(`alembic upgrade head`)가 이 이미지 안에서 읽는다.
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --locked --no-dev

FROM python:3.11-slim-bookworm

# 서비스 사용자는 홈·로그인 셸 없이 만든다.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin lab

WORKDIR /app
# 앱·웹 파일은 root 소유(COPY 기본)로 두고 서비스 사용자는 읽기만 한다 — 프로세스가 뚫려도 자기 코드와 정적 파일을 고쳐
# 다음 요청에 심을 수 없다. 프로젝트는 `/app/src` 를 가리키는 편집 설치라 빌드 단계와 같은 `/app` 자리로 옮긴다.
COPY --from=builder /app /app
COPY --from=web . /app/web

# 서비스 사용자는 `/app` 에 쓸 수 없어 실행 중 바이트코드 파일을 남기려는 시도가 늘 실패한다 — 시도 자체를 끈다. 의존 패키지는
# 빌드 때(`UV_COMPILE_BYTECODE`) 미리 컴파일해 두었다.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1
USER lab

EXPOSE 8000

# 접근 기록은 서비스가 요청마다 DB 에 한 행으로 남기므로 uvicorn 접근 로그는 끈다(컨테이너 로그 용량도 아낀다).
CMD ["uvicorn", "chat_lab_service.main:create_app_from_env", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
