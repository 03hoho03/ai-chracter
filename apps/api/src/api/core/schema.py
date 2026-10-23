from pydantic import AfterValidator, BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base for request/response schemas: snake_case Python attrs, camelCase JSON."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


def _reject_nul(value: str) -> str:
    if "\x00" in value:
        raise ValueError("must not contain NUL characters")
    return value


# Postgres text 는 NUL 문자를 담지 못해 그대로 쓰면 DB 가 거절하고 500 이 난다. 사용자가 쓴 글을 저장하는 입력 칸에
# `Annotated[str, ..., NoNul]` 로 붙여 요청 검증 오류(422)로 미리 돌려준다.
NoNul = AfterValidator(_reject_nul)
