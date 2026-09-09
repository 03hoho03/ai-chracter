"""프롬프트 DB 이관 0단계 골든 대조.

`scripts/dump_prompt_goldens.py`의 `GOLDEN_CASES`를 그대로 재사용한다 — 골든 파일을 만든
바로 그 인자로 지금 코드를 다시 호출해 문자열 완전 일치를 본다. DB·네트워크·LLM을 쓰지
않는 동기 테스트다.

지금 시점엔 전부 통과한다(현재 코드끼리 비교). 나중 단계에서 렌더러를 갈아엎은 뒤 여기가
깨지기 시작하면 그게 "프롬프트가 바뀌었다"는 신호다.
"""

from collections.abc import Callable

import pytest

from dump_prompt_goldens import GOLDEN_CASES, GOLDEN_DIR


@pytest.mark.parametrize(
    ("filename", "build"), GOLDEN_CASES, ids=[filename for filename, _ in GOLDEN_CASES]
)
def test_prompt_golden_matches(filename: str, build: Callable[[], str]) -> None:
    expected = (GOLDEN_DIR / filename).read_text(encoding="utf-8")
    assert build() == expected
