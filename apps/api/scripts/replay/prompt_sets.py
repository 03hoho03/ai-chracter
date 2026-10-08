"""리플레이 갈래마다 쓸 프롬프트 세트 고르기.

- 현행(window) 갈래는 그 턴의 실제를 다시 만든다. 그래서 (레인, 그 턴에 생성한 모델)의 게시본 중 **턴 N 사용자 메시지
  시각보다 먼저 게시된 것 가운데 가장 최신**을 쓴다. 지금 활성 세트를 쓰면 측정 뒤 마이그레이션·어드민 게시가 새로
  만든 세트로 조립하게 된다. 게시 시각이 턴보다 늦게 찍힌 세트는 이 규칙으로 고를 수 없어, 사용자가 id 로 지정할 수
  있다(그 세트의 레인·모델이 그 턴과 같아야 한다).
- 모델 축은 지금 바꿀 후보를 시험하는 것이라 그 모델의 **지금** 활성 세트를 쓴다(`load_active_prompt_set` 그대로).
- 세트 축은 id 로 고른 게시본·초안, 또는 (레인, 모델)의 초안이다.

섹션은 `load_active_prompt_set` 과 같은 정렬로 읽는다 — 렌더러는 같은 슬롯의 행을 이 순서로 보고 고르므로 정렬이 다르면
같은 세트에서도 다른 프롬프트가 나올 수 있다. 어드민의 섹션 읽기는 정렬 키가 달라 쓰지 않는다.
"""

import uuid
from dataclasses import dataclass, replace
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import PromptLane, PromptSetNotFoundError, load_active_prompt_set
from api.db.models.prompt import PromptSection, PromptSet
from api.llm.chat_models import ChatModelId
from replay.logs import ReplayRefusedError


@dataclass(frozen=True)
class ChosenSet:
    """고른 세트와 그 섹션, 그리고 고른 규칙(plan 기록에 남긴다)."""

    prompt_set: PromptSet
    sections: list[PromptSection]
    rule: str


async def load_sections(db: AsyncSession, prompt_set_id: uuid.UUID) -> list[PromptSection]:
    return list(
        (
            await db.scalars(
                select(PromptSection)
                .where(PromptSection.prompt_set_id == prompt_set_id)
                .order_by(
                    PromptSection.channel,
                    PromptSection.order,
                    PromptSection.scope,
                    PromptSection.slot,
                    PromptSection.variant,
                )
            )
        ).all()
    )


async def window_set(db: AsyncSession, *, lane: PromptLane, model: ChatModelId, before: datetime) -> ChosenSet:
    prompt_set = await db.scalar(
        select(PromptSet)
        .where(
            PromptSet.status == "published",
            PromptSet.lane == lane,
            PromptSet.model == model,
            PromptSet.published_at < before,
        )
        .order_by(PromptSet.published_at.desc())
        .limit(1)
    )
    if prompt_set is None:
        raise ReplayRefusedError(f"{before.isoformat()} 이전에 게시된 (레인 {lane}, 모델 {model}) 세트가 없다")
    return ChosenSet(prompt_set, await load_sections(db, prompt_set.id), "publishedBeforeTurn")


async def window_set_by_id(db: AsyncSession, set_id: uuid.UUID, *, lane: PromptLane, model: ChatModelId) -> ChosenSet:
    """사용자가 지정한 현행 갈래의 세트. 현행 갈래는 그 턴에 실제로 생성한 모델로 부르므로, 다른 모델의 세트면 덤프와
    맞더라도 그때와 다른 조건이 되어 거부한다."""
    chosen = await set_by_id(db, set_id, lane=lane)
    if chosen.prompt_set.model != model:
        raise ReplayRefusedError(
            f"세트 {set_id} 는 모델 {chosen.prompt_set.model} 의 세트다(그 턴의 생성 모델은 {model})"
        )
    return replace(chosen, rule="window-set")


async def active_set(db: AsyncSession, *, lane: PromptLane, model: ChatModelId) -> ChosenSet:
    try:
        prompt_set, sections = await load_active_prompt_set(db, lane=lane, model=model)
    except PromptSetNotFoundError as exc:
        raise ReplayRefusedError(str(exc)) from None
    return ChosenSet(prompt_set, sections, "activeNow")


async def set_by_id(db: AsyncSession, set_id: uuid.UUID, *, lane: PromptLane) -> ChosenSet:
    prompt_set = await db.get(PromptSet, set_id)
    if prompt_set is None:
        raise ReplayRefusedError(f"프롬프트 세트가 없다: {set_id}")
    if prompt_set.lane != lane:
        raise ReplayRefusedError(f"세트 {set_id} 는 레인 {prompt_set.lane} 이다(이 방은 {lane})")
    return ChosenSet(prompt_set, await load_sections(db, prompt_set.id), "byId")


async def draft_set(db: AsyncSession, *, lane: PromptLane, model: ChatModelId) -> ChosenSet:
    prompt_set = await db.scalar(
        select(PromptSet).where(PromptSet.status == "draft", PromptSet.lane == lane, PromptSet.model == model)
    )
    if prompt_set is None:
        raise ReplayRefusedError(f"(레인 {lane}, 모델 {model}) 초안이 없다")
    return ChosenSet(prompt_set, await load_sections(db, prompt_set.id), "draft")
