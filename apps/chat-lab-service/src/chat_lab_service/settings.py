"""환경 변수 `LAB_*` 에서 읽는 설정.

인증을 끄거나 건너뛰는 칸은 없다. 풀 크기·보관 기간·크기 상한은 바꿀 일이 생기면 코드로 바꾸는 상수라 여기 두지 않는다.
"""

from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

# 목록은 JSON 배열이 아니라 쉼표 구분으로 받는다 — JSON 배열은 따옴표가 들어가 저장소의 env 파일 형식 규칙에 걸린다. 빈 목록은
# 기동에서 막는다. 비면 모두가 404 를 받아 장애처럼 보인다.
CommaList = Annotated[frozenset[str], NoDecode, Field(min_length=1)]


class DatabaseSettings(BaseSettings):
    """DB 주소 하나 — 마이그레이션은 이것만 읽어 Access 설정 없이 돈다."""

    # 설정 검증 오류 글에 받은 값을 싣지 않는다(DB 주소에는 비밀번호가 있다).
    model_config = SettingsConfigDict(env_prefix="LAB_", hide_input_in_errors=True)

    database_url: SecretStr

    # 필수 칸을 환경에서 채우는 생성 꼴(`DatabaseSettings()`, `_env_file=` 인자)을 타입 검사가 받게 한다. 없으면 mypy 가
    # 칸마다 인자를 요구하고 `_env_file` 을 모르는 인자로 본다.
    def __init__(self, **values: Any) -> None:
        super().__init__(**values)

    @field_validator("database_url")
    @classmethod
    def _parsable(cls, value: SecretStr) -> SecretStr:
        try:
            make_url(value.get_secret_value())
        except (ArgumentError, ValueError):
            # 포트를 숫자로 읽다 난 오류는 그 조각을 글에 싣는데, 비밀번호에 이스케이프하지 않은 `@` 가 있으면 그 조각에
            # 비밀번호 일부가 섞인다. 어느 설정이 틀렸는지만 알린다.
            raise ValueError("LAB_DATABASE_URL 을 URL 로 읽지 못했다") from None
        return value


class Settings(DatabaseSettings):
    access_issuer: str
    access_aud: str = Field(min_length=1)
    read_emails: CommaList
    upload_client_ids: CommaList
    web_dir: Path = Path("/app/web")

    # 위 `DatabaseSettings.__init__` 과 같은 이유 — 타입 검사는 칸을 가진 클래스마다 생성 꼴을 새로 만든다.
    def __init__(self, **values: Any) -> None:
        super().__init__(**values)

    @field_validator("access_issuer")
    @classmethod
    def _issuer_shape(cls, value: str) -> str:
        # 토큰의 `iss` 와 글자 그대로 비교하고 공개키 주소의 앞부분이 되므로 끝 `/` 하나도 다르면 모든 토큰이 떨어진다.
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.netloc or parts.path or parts.query or parts.fragment:
            raise ValueError("https:// 로 시작하고 경로·끝 '/' 가 없는 Access 팀 주소여야 한다")
        return value

    @field_validator("read_emails", "upload_client_ids", mode="before")
    @classmethod
    def _split_commas(cls, value: object) -> object:
        if isinstance(value, str):
            return frozenset(item.strip() for item in value.split(",") if item.strip())
        return value

    @field_validator("read_emails")
    @classmethod
    def _casefold_emails(cls, value: frozenset[str]) -> frozenset[str]:
        return frozenset(email.casefold() for email in value)
