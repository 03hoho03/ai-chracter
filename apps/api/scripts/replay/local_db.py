"""측정·시드 도구가 DB 를 읽거나 쓰기 전에 거는 운영 DB 거부.

운영 DB 호스트는 compose 서비스명(`postgres`)이지만, 거부 목록이 아니라 허용 목록으로 판정한다 — DB 를 다른 곳으로
옮기면 거부 목록은 조용히 뚫린다. 이 모듈은 import 만으로 환경 변수를 바꾸거나 저장소 클라이언트를 만들지 않는다 —
시드 스크립트를 그대로 import 하면 그런 부작용이 함께 와서 규칙만 여기로 옮겼다."""

from sqlalchemy.engine import make_url

LOCAL_DB_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def ensure_local_database(database_url: str, *, tool: str) -> None:
    """로컬 DB 가 아니면 `SystemExit`. 호스트가 없는 URL(유닉스 소켓)도 로컬로 단정할 수 없어 거부한다."""
    host = make_url(database_url).host
    if host not in LOCAL_DB_HOSTS:
        raise SystemExit(
            f"{tool} 는 로컬 DB 에서만 돈다(DATABASE_URL 호스트: {host!r}). 운영 DB 를 가리키면 거부한다."
        )
