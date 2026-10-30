"""head 의 채팅 레인 체인 커버리지 — 체인 모델 축의 모든 모델이 두 채팅 레인(스토리·캐릭터)마다 활성 세트를 갖고, 그 세트의 슬롯이
어드민 게시 검증이 그 체인에 요구하는 슬롯과 같다.

판정·기억·생성 슬롯을 더하는 마이그레이션은 저마다 다룰 체인 목록을 손으로 적는다. 그 목록이 체인 하나(예: 채팅 글쓰기
`haiku_writer`)를 빠뜨려도 그 마이그레이션의 테스트는 초록이고, 결과는 그 체인 게시가 "누락"으로 막히거나 그 모델 방만 새 문안
없이 도는 조용한 차이다. 이 테스트는 체인 목록을 타입(`PromptSetModelId`)에서, 기대 슬롯을 게시 검증의 표에서 읽으므로 새 id 를
더하는 쪽도 슬롯을 더하는 쪽도 함께 걸린다. 세션 스코프 스키마가 `upgrade head` 를 이미 했으므로 그 상태를 읽기만 한다."""

from typing import get_args

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.prompts import _expected_slots
from api.chat.prompt_builder import PromptLane, load_active_prompt_set
from api.llm.chat_models import PromptSetModelId

_CHAT_LANES: tuple[PromptLane, ...] = ("story", "character")
_CHAINS = [(lane, model) for lane in _CHAT_LANES for model in get_args(PromptSetModelId)]


@pytest.mark.parametrize(("lane", "model"), _CHAINS, ids=[f"{lane}-{model}" for lane, model in _CHAINS])
async def test_every_chat_chain_has_an_active_set_with_exactly_the_slots_publishing_requires(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    _, sections = await load_active_prompt_set(db_session, lane=lane, model=model)

    present = {(s.channel, s.scope, s.slot) for s in sections}
    expected = {
        (channel, scope, slot) for channel, slots in _expected_slots(lane, model).items() for scope, slot in slots
    }
    assert present == expected, {"missing": sorted(expected - present), "extra": sorted(present - expected)}
