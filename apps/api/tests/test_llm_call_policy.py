from typing import get_args

from api.llm.call_policy import CALL_POLICIES, LLMCallSite


def test_every_call_site_has_a_policy_row() -> None:
    # 행이 빠진 call_site 는 타임아웃을 고를 때 `KeyError` 로 호출이 실패한다. 없는 이름을 키로 넣는 쪽은 표의 타입이
    # 막으므로, 여기서 잡는 것은 빠진 행이다.
    assert set(CALL_POLICIES) == set(get_args(LLMCallSite))
