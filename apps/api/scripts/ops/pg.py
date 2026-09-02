"""libpq 도구(`pg_dump`/`pg_restore`/`psql`)를 도커 컨테이너로 돌린다.

**왜 호스트 설치가 아니라 도커인가.** `pg_dump` 는 자기보다 높은 버전의 서버를 거부한다. 운영
대상이 PostgreSQL 18.6(Neon 실측)이므로 18 이상이 필요한데, 맥에 18을 따로 깔면 우분투 VM 의
패키지 버전과 갈린다. 이미지 태그로 고정하면 **맥에서든 VM 에서든 같은 바이너리**가 돈다.

**왜 URL 을 argv 로 넘기지 않는가.** 접속 문자열에는 비밀번호가 들어 있고, argv 는 같은 호스트의
다른 프로세스에게 `ps` 로 보인다. `docker run -e PGURL`(값 없이 **이름만**)은 docker 클라이언트
프로세스의 환경에서 값을 가져가므로 argv 에 아무것도 남지 않는다. 그래서 컨테이너 안 명령은
`sh -c` 로 돌리고 URL 은 `"$PGURL"` 로 참조한다.
"""

import os
import subprocess
from typing import IO

# 운영 대상(Neon 18.6)보다 낮으면 pg_dump 가 거부한다. 서버를 올릴 때 여기도 같이 올린다.
PG_IMAGE = "postgres:18-alpine"


def run_sh(
    script: str,
    *,
    url: str,
    stdin: IO[bytes] | int | None = None,
    stdout: IO[bytes] | int | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """컨테이너 안에서 `script` 를 실행한다. 접속 URL 은 `"$PGURL"` 로 참조할 것.

    stdin/stdout 을 그대로 파이프하므로 덤프 파일을 호스트에 두고도 볼륨 마운트가 필요 없다.
    실패해도 예외를 던지지 않는다 — 호출부가 stderr 를 사람이 읽을 형태로 요약해야 하기 때문이다.
    """
    # 운영 스택의 Postgres 는 포트를 호스트에 게시하지 않는다(`docker-compose.prod.yml`) — 그래서
    # 기본 bridge 로 띄운 컨테이너에서는 닿지 않는다. `PG_DOCKER_NETWORK` 로 compose 네트워크
    # (`ddona_default`)를 지정하면 같은 망에 붙어 `postgres` 라는 이름으로 접속된다.
    # VM 의 백업 크론이 로컬 DB 를 덤프할 때도 이 값이 필요하다. 원격 DB(Neon)에는 무관하다.
    network = os.environ.get("PG_DOCKER_NETWORK")

    # os.environ 을 통째로 물려준다 — docker CLI 는 컨텍스트/소켓을 `DOCKER_HOST`·`HOME` 에서
    # 찾으므로 env 를 갈아끼우면 데몬을 못 찾는다. PGURL 만 덧씌운다.
    return subprocess.run(
        [
            "docker", "run", "--rm", "--interactive",
            "-e", "PGURL",  # 이름만. 값은 아래 env 로 들어가고 argv 에는 안 남는다.
            *(["--network", network] if network else []),
            PG_IMAGE,
            "sh", "-c", script,
        ],
        env={**os.environ, "PGURL": url},
        stdin=stdin,
        stdout=stdout,
        stderr=subprocess.PIPE,
    )


def scalar(sql: str, *, url: str) -> str:
    """한 값을 돌려주는 SQL 을 실행한다. 실패하면 stderr 를 담아 터뜨린다."""
    result = run_sh(f'psql "$PGURL" -At -c {shell_quote(sql)}', url=url, stdout=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode().strip())
    return result.stdout.decode().strip()


def shell_quote(value: str) -> str:
    """`sh -c` 안에 문자열을 안전하게 박는다(작은따옴표 감싸기 + 내부 따옴표 탈출)."""
    return "'" + value.replace("'", "'\\''") + "'"
