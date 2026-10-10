"""두 상세 테이블의 작품 기본 이름 칸은 테이블에는 남고 ORM 매퍼에서는 빠져 있다.

칸을 지우는 마이그레이션은 이 코드가 배포된 다음 배포에 온다. 그 사이 배포 중에는 이 코드가 칸이 없는 스키마 위에서도
돌아야 하므로 매퍼가 그 칸을 SELECT·INSERT 에 넣으면 안 된다. 반대로 테이블 메타데이터에서 칸을 지우면 `alembic check` 가
모델과 마이그레이션의 차이로 실패한다. 칸을 지우는 마이그레이션이 들어올 때 이 테스트와 모델의 칸 선언을 함께 지운다.

매퍼에서 빠진 속성을 인스턴스에서 읽으면 예외가 아니라 클래스에 남은 칸 선언 객체가 돌아오고, 이 값은 참이라 이름 자리에
그 객체의 문자열이 실린다. 이 테스트로는 그런 읽기를 잡지 못하므로 코드에서 이 속성 이름을 찾아 남은 읽기가 없는지 본다.
"""

import pytest
from sqlalchemy import inspect

from api.db.base import Base
from api.db.models.character import CharacterVersionDetail
from api.db.models.story import StoryVersionDetail


@pytest.mark.parametrize("model", [CharacterVersionDetail, StoryVersionDetail])
def test_default_user_name_column_stays_in_the_table_but_not_in_the_mapper(
    model: type[Base],
) -> None:
    assert "default_user_name" in model.__table__.c
    assert "default_user_name" not in {attr.key for attr in inspect(model).column_attrs}
