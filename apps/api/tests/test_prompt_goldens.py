"""프롬프트 DB 이관 2단계 게이트 — DB 시드에서 읽은 활성 세트를 렌더러로 조립한 결과가
0단계 골든 25개와 바이트 단위로 같은지 본다(prompt-db-goal-prompt.md D-13, V-1).

`scripts/dump_prompt_goldens.py`의 `GOLDEN_CASES`를 그대로 재사용한다 — 골든 파일을 만든
바로 그 입력 픽스처로 지금 렌더러를 다시 호출해 문자열 완전 일치를 본다("자기 사본 함정"
방지, `25a6ae1`이 겪은 것과 같은 실수를 막기 위해 픽스처 정의처를 물리적으로 하나로 둔다).
활성 세트(`PromptSet`/`PromptSection`)만 이 테스트가 `db_session`으로 새로 읽는다 —
`GOLDEN_CASES`의 각 콜러블 자체는 여전히 그 값을 인자로만 받는 순수 함수 호출이다.
"""

from collections.abc import Callable

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.prompt import PromptSection, PromptSet
from dump_prompt_goldens import GOLDEN_CASES, GOLDEN_DIR


@pytest_asyncio.fixture
async def active_prompt_set(db_session: AsyncSession) -> tuple[PromptSet, list[PromptSection]]:
    """`_migrated_schema`(세션 스코프 autouse)가 심어 둔 활성 세트를 그대로 읽는다 — 이
    픽스처가 DB에 닿는 유일한 지점이고, 렌더러 자체(`build_*`)는 여전히 순수 함수다."""
    prompt_set = (await db_session.scalars(select(PromptSet).where(PromptSet.status == "published"))).one()
    sections = list(
        (await db_session.scalars(select(PromptSection).where(PromptSection.prompt_set_id == prompt_set.id))).all()
    )
    return prompt_set, sections


@pytest.mark.parametrize(
    ("filename", "build"), GOLDEN_CASES, ids=[filename for filename, _ in GOLDEN_CASES]
)
async def test_prompt_golden_matches(
    filename: str,
    build: Callable[[PromptSet, list[PromptSection]], str],
    active_prompt_set: tuple[PromptSet, list[PromptSection]],
) -> None:
    prompt_set, sections = active_prompt_set
    expected = (GOLDEN_DIR / filename).read_text(encoding="utf-8")
    assert build(prompt_set, sections) == expected
