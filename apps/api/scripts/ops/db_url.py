"""앱의 `DATABASE_URL`을 libpq(`pg_dump`/`psql`/`pg_restore`)가 받는 형태로 바꾼다.

앱은 SQLAlchemy+asyncpg를 쓰므로 `DATABASE_URL`이
`postgresql+asyncpg://…?ssl=require` 꼴이다. 이걸 그대로 libpq 도구에 넘기면 **두 번 죽는다**:

    $ pg_dump "postgresql+asyncpg://…"   → invalid URI scheme
    $ pg_dump "postgresql://…?ssl=require" → invalid connection option "ssl"

드라이버 접미(`+asyncpg`)를 떼고 `ssl=` 를 `sslmode=` 로 옮겨야 통과한다. 이 변환을 스크립트마다
손으로 하면 한 곳만 빠뜨려도 백업이 조용히 안 돌므로, 표준 라이브러리만 쓰는 이 한 파일에 모은다.

**파일명이 언더스코어인 건 의도적이다** — `apps/api/scripts`가 mypy 경로(`mypy_path`)에 들어 있어
하이픈이 들어가면 모듈로 읽히지 않는다.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# asyncpg 의 `ssl` 값 → libpq 의 `sslmode` 값. asyncpg 는 불리언 문자열도 받지만 libpq 는
# 모드 이름만 받으므로 여기서 갈아 끼운다. 모르는 값은 조용히 통과시키지 않고 터뜨린다 —
# 잘못 넘어가면 TLS 없이 붙거나(유출) 연결이 실패하는데, 둘 다 백업 시점에 알아야 한다.
_SSL_TO_SSLMODE = {
    "require": "require",
    "true": "require",
    "disable": "disable",
    "false": "disable",
    "prefer": "prefer",
    "allow": "allow",
    "verify-ca": "verify-ca",
    "verify-full": "verify-full",
}


def to_libpq_url(url: str) -> str:
    """`postgresql+asyncpg://…?ssl=require` → `postgresql://…?sslmode=require`.

    이미 libpq 형태면 그대로 돌려준다(멱등). 스킴이 postgres 계열이 아니면 손대지 않는다.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.split("+", 1)[0]

    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key == "ssl":
            if value not in _SSL_TO_SSLMODE:
                raise ValueError(f"모르는 ssl 값이다: {value!r}. sslmode 로 어떻게 옮길지 정해야 한다.")
            key, value = "sslmode", _SSL_TO_SSLMODE[value]
        query.append((key, value))

    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def describe(url: str) -> str:
    """자격증명을 뺀 `host/dbname` — 로그에 "어디에 붙었는지"를 남기되 비밀은 안 남긴다."""
    parts = urlsplit(url)
    return f"{parts.hostname or '?'}{parts.path}"
