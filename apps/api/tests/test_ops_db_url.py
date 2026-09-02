"""`ops.db_url` 변환 규약 — 백업 스크립트 전체가 여기에 얹혀 있다.

이 변환이 조용히 틀리면 백업이 **안 도는 게 아니라 안 도는 줄 모르게** 된다(크론이 실패해도
아무도 안 본다). 그래서 실제 운영 URL 형태를 그대로 고정해 둔다.
"""

import pytest

from ops.db_url import describe, to_libpq_url


def test_asyncpg_스킴과_ssl_파라미터를_동시에_바꾼다() -> None:
    """운영에서 실제로 쓰는 형태. 둘 중 하나만 바꾸면 libpq 가 각각 다른 이유로 거부한다."""
    converted = to_libpq_url("postgresql+asyncpg://u:p@host.neon.tech/neondb?ssl=require")
    assert converted == "postgresql://u:p@host.neon.tech/neondb?sslmode=require"


def test_이미_libpq_형태면_그대로다() -> None:
    """멱등이어야 한다 — 변환된 URL 이 다시 들어와도 깨지지 않는다."""
    url = "postgresql://u:p@localhost:5432/db?sslmode=disable"
    assert to_libpq_url(url) == url


def test_파라미터가_없으면_스킴만_바꾼다() -> None:
    assert to_libpq_url("postgresql+asyncpg://u:p@localhost/db") == "postgresql://u:p@localhost/db"


def test_다른_파라미터는_보존한다() -> None:
    """Neon 은 `channel_binding` 을 붙여 준다. ssl 만 건드리고 나머지는 통과시켜야 한다."""
    converted = to_libpq_url("postgresql+asyncpg://u:p@h/db?ssl=require&channel_binding=require")
    assert "channel_binding=require" in converted
    assert "sslmode=require" in converted


def test_모르는_ssl_값은_터뜨린다() -> None:
    """조용히 통과시키면 TLS 없이 붙거나 연결이 죽는다. 둘 다 백업 시점에 알아야 한다."""
    with pytest.raises(ValueError, match="모르는 ssl 값"):
        to_libpq_url("postgresql+asyncpg://u:p@h/db?ssl=maybe")


def test_describe_는_자격증명을_빼고_보여준다() -> None:
    """로그에 남는 문자열이라 비밀번호가 섞이면 안 된다."""
    described = describe("postgresql://user:secret@host.neon.tech/neondb")
    assert described == "host.neon.tech/neondb"
    assert "secret" not in described
