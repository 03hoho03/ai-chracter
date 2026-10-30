"""측정·시드 도구가 DB 를 읽거나 쓰기 전에 거는 운영 DB 거부.

운영 DB 호스트는 compose 서비스명(`postgres`)이지만, 거부 목록이 아니라 허용 목록으로 판정한다 — DB 를 다른 곳으로
옮기면 거부 목록은 조용히 뚫린다. 이 모듈은 import 만으로 환경 변수를 바꾸거나 저장소 클라이언트를 만들지 않는다 —
시드 스크립트를 그대로 import 하면 그런 부작용이 함께 와서 규칙만 여기로 옮겼다."""

from sqlalchemy.engine import URL, make_url

LOCAL_DB_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
# 드라이버가 주소 칸 대신 실제로 접속하는 곳으로 쓰는 쿼리 키. `host` 는 asyncpg·psycopg 둘 다(여러 개·쉼표 구분·포트 붙음),
# `hostaddr` 는 psycopg(libpq)가 이름 풀이 없이 그 주소로 바로 붙는다.
_QUERY_HOST_KEYS = ("host", "hostaddr")


def _without_port(token: str) -> str:
    token = token.strip()
    if token.startswith("["):
        return token[1:].split("]", 1)[0]
    # 콜론이 둘 이상이면 괄호 없는 IPv6 라 포트를 뗄 수 없다 — 그대로 두면 허용 목록에 없을 때 거부된다.
    return token.split(":", 1)[0] if token.count(":") == 1 else token


def _query_hosts(url: URL) -> list[str]:
    hosts: list[str] = []
    for key in _QUERY_HOST_KEYS:
        raw = url.query.get(key)
        values = [raw] if isinstance(raw, str) else list(raw or ())
        hosts += [_without_port(token) for value in values for token in value.split(",")]
    return hosts


def ensure_local_database(database_url: str, *, tool: str) -> None:
    """로컬 DB 가 아니면 `SystemExit`. 호스트가 없는 URL(유닉스 소켓)도 로컬로 단정할 수 없어 거부한다. 주소 칸이 로컬이어도
    쿼리의 `host`·`hostaddr` 가 하나라도 허용 목록 밖이면 거부한다 — 드라이버는 그 쿼리 값으로 접속하므로 주소 칸만 보면
    `localhost/?host=운영` 이 가드를 지나 운영 DB 에 붙는다."""
    url = make_url(database_url)
    host = url.host
    if host not in LOCAL_DB_HOSTS:
        raise SystemExit(f"{tool} 는 로컬 DB 에서만 돈다(DATABASE_URL 호스트: {host!r}). 운영 DB 를 가리키면 거부한다.")
    outside = [query_host for query_host in _query_hosts(url) if query_host not in LOCAL_DB_HOSTS]
    if outside:
        raise SystemExit(
            f"{tool} 는 로컬 DB 에서만 돈다(DATABASE_URL 쿼리의 접속 호스트: {outside!r}). 운영 DB 를 가리키면 거부한다."
        )
