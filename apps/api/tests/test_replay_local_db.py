"""측정 도구가 DB 를 읽기 전에 거는 운영 DB 거부. 허용 목록 밖의 호스트는 모두 거부한다 — 실제 사용자 대화를 측정·생성
모델에 다시 보내지 않기 위해서다."""

import pytest

from replay.local_db import ensure_local_database


@pytest.mark.parametrize(
    "database_url",
    [
        pytest.param("postgresql+asyncpg://postgres:secret@postgres:5432/ai_character_chat", id="prod-compose-host"),
        pytest.param("postgresql+asyncpg://u:p@db.example.com:5432/x", id="remote-host"),
        pytest.param("postgresql+asyncpg://u:p@10.0.0.5:5432/x", id="private-ip"),
        pytest.param("postgresql+asyncpg://u:p@/x?host=/var/run/postgresql", id="unix-socket-without-host"),
    ],
)
def test_non_local_database_is_refused_with_the_tool_and_host_named(database_url: str) -> None:
    with pytest.raises(SystemExit) as refused:
        ensure_local_database(database_url, tool="측정도구.py")
    message = str(refused.value)
    assert "측정도구.py" in message
    assert "호스트" in message


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_local_database_hosts_are_allowed(host: str) -> None:
    ensure_local_database(f"postgresql+asyncpg://postgres:postgres@{host}:5458/ai_character_chat", tool="x")

