"""Postgres 확장이 만드는 SQL 타입을 SQLAlchemy 칸 타입으로 옮긴 것."""

from collections.abc import Callable
from typing import Any

from sqlalchemy.engine import Dialect
from sqlalchemy.types import UserDefinedType


class HalfVec(UserDefinedType[list[float]]):
    """pgvector 의 `halfvec`(반정밀도 벡터) 칸. 차원을 적지 않는다 — 한 칸에 차원이 다른 벡터가 함께 들어간다.

    파이썬 `pgvector` 패키지 대신 이 타입을 쓰는 것은 벡터를 파이썬에서 계산하지 않아서다. 값은 `'[0.1,0.2]'` 글자로
    주고받고 거리는 SQL 의 `<=>` 가 계산한다. asyncpg 는 이 타입의 코덱이 없어 글자로 보내고 글자로 받는다.
    글자 값을 이 칸과 견주는 원시 SQL 은 `CAST(:q AS halfvec)` 로 감싼다 — 타입이 붙은 글자 바인드는 asyncpg
    방언이 `::VARCHAR` 로 내보내 `halfvec <=> character varying` 연산자가 없다는 오류가 난다.

    반정밀도라 저장한 값을 다시 읽으면 가까운 값으로 바뀌어 돌아온다."""

    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return "halfvec"

    def bind_processor(self, dialect: Dialect) -> Callable[[list[float] | None], str | None]:
        def process(value: list[float] | None) -> str | None:
            if value is None:
                return None
            return "[" + ",".join(repr(float(x)) for x in value) + "]"

        return process

    def result_processor(self, dialect: Dialect, coltype: object) -> Callable[[str | None], list[float] | None]:
        def process(value: str | None) -> list[float] | None:
            if value is None:
                return None
            return [float(x) for x in value.strip("[]").split(",")]

        return process
