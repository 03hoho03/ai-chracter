"""노벨 공개 전 텍스트 심사 — 프롬프트 빌더, 응답 스키마, 심사 호출, 게시자당 하루 거부 상한.

심사하는 것은 공개 화면에 보이는 글 전부다(소설 제목·소개, 화 제목·작가의 말·본문). 무엇을 이번에 심사할지는 호출부가
정한다 — 처음 공개하는 화와 공개 뒤 바뀐 화·바뀐 소설 제목·소개만 싣는다. 이미 심사를 통과해 얼려 둔 글을 다시 보낼
이유가 없다.

문안은 `novel_screen` 레인 프롬프트 세트의 같은 이름 채널에 있다(Gemini 세트 하나). `instruction` 슬롯만
`system_instruction` 으로 보내고 심사할 글은 본문으로 보낸다 — 게시자가 쓴 글이 지시처럼 읽히지 않게 역할 규칙과 다른
통로에 둔다(소설화 호출과 같은 배치). 활성 세트 캐시는 쓰지 않고 매번 DB 를 읽는다.

모델은 발행 심사와 같은 스위치를 따른다(call_site 가 `PUBLISH_FILTER_CALL_SITES` 에 있다). 사고 설정은 넘기지 않는다 —
판정·심사 호출의 공통 규칙이다(`llm/gemini.py` 의 `generate_structured` 주석).

상한은 둘이다. 심사에 걸린 횟수는 게시자마다 KST 하루 상한이 있다 — 걸린 글을 조금씩 고쳐 끝없이 다시 내는 것을 막는
상한이라 통과·장애는 세지 않는다. 그와 별개로 심사 호출 자체를 게시자당 시간당 고정 창으로 센다(통과·거부·장애 모두) —
통과한 화의 제목을 한 글자씩 고쳐 다시 내면 매번 그 화 전체가 다시 심사되므로, 거부만 세면 호출 수에 끝이 없다. 레이트리밋
면제 계정은 두 상한 모두 적용하지 않고, Redis 가 실패하면 다른 상한들처럼 통과시킨다."""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import get_args

from pydantic import BaseModel, Field
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import PromptLane, PromptRenderError, render_prompt_channel, select_sections_for_render
from api.core.config import settings
from api.core.rate_limit import KST, seconds_until_kst_midnight
from api.core.rate_limit_gate import (
    _enforce_hourly_limit,
    _report_redis_failure,
    _too_many_requests,
    is_rate_limit_exempt,
)
from api.core.redis import redis_client
from api.db.models.novel import NovelScreeningPart
from api.db.models.prompt import PromptSection
from api.llm.client import LLMCallContext, LLMCallSite, LLMClient, LLMPolicyViolationError, structured_model
from api.novelize.prompts import NovelizePrompt

logger = logging.getLogger(__name__)

NOVEL_SCREEN_LANE: PromptLane = "novel_screen"
NOVEL_SCREEN_CHANNEL = "novel_screen"
NOVEL_SCREEN_CALL_SITE: LLMCallSite = "novel_publish_screen"
_INSTRUCTION_SLOT = "instruction"
_REQUIRED_SLOTS = frozenset({_INSTRUCTION_SLOT, "screened_text"})

# 게시자 한 명이 KST 하루에 심사에 걸릴 수 있는 횟수. 정책값이지 실측값이 아니다 — 걸린 화를 고쳐 다시 내는 정상 게시자는
# 하루 몇 번이면 충분하다고 보고 고른 수다. 게이트는 호출 시점에 모듈 전역으로 읽는다(테스트가 바꿔 끼울 수 있게).
NOVEL_SCREEN_DAILY_REJECTION_LIMIT = 3
# 게시자 한 명이 한 시간(고정 창)에 부를 수 있는 심사 호출 수. 작품 발행 심사의 시간당 상한과 같은 값·같은 꼴이다 — 정상
# 게시자는 한 요청에 한 화씩 공개하므로 한 시간에 열 화를 넘게 새로 공개하거나 고쳐 다시 낼 일이 드물다고 보고 고른 정책값이다.
# 호출 시점에 모듈 전역으로 읽는다(테스트가 바꿔 끼울 수 있게).
NOVEL_SCREEN_HOURLY_CALL_LIMIT = 10
_CALL_SCOPE = "novel_screen_calls"
# 두 상한의 429 `window`. 다른 429 와 같은 바디 모양을 쓰고 이 값으로 어느 기능의 상한인지 가른다.
NOVEL_SCREEN_LIMIT_WINDOW = "novel_screen"
# `rate_limit:` 으로 시작해야 테스트의 자동 정리(`conftest.py` 의 `_flush_rate_limit_keys`)에 함께 지워진다.
_REJECTION_KEY_PREFIX = "rate_limit:novel_screen_rejections"

# 머리 줄에 함께 싣는 자리 이름. 키는 응답의 `flagged_parts` 값과 같은 글자다.
_PART_LABELS: dict[NovelScreeningPart, str] = {
    "novel_title": "소설 제목",
    "synopsis": "소개",
    "chapter_title": "화 제목",
    "author_note": "작가의 말",
    "chapter_body": "본문",
}


@dataclass(frozen=True)
class NovelScreenItem:
    """심사할 글 한 자리. `text` 는 비어 있지 않다(빈 칸은 호출부가 싣지 않는다)."""

    part: NovelScreeningPart
    text: str


class NovelScreenResult(BaseModel):
    """텍스트 심사의 응답 스키마. 필드 설명은 모델에게 가는 스키마에 그대로 실린다."""

    passed: bool = Field(description="공개해도 되면 true, 기준에 걸리는 글이 하나라도 있으면 false.")
    flagged_parts: list[NovelScreeningPart] = Field(
        description="통과가 아니면 기준에 걸린 글의 자리 키(머리 줄의 키)를 모두 넣는다. 통과면 빈 목록."
    )
    reason: str | None = Field(
        description="통과가 아니면 어느 대목이 어느 기준에 걸리는지 한두 문장. 글을 길게 옮겨 적지 않는다. 통과면 null."
    )


@dataclass(frozen=True)
class NovelScreenVerdict:
    """심사 한 번의 판정. `flagged_parts` 는 이번에 실은 자리로 좁힌 값이다(모델이 싣지 않은 자리를 짚어도 버린다)."""

    passed: bool
    flagged_parts: tuple[NovelScreeningPart, ...]
    reason: str | None
    model: str


def _screened_text(items: Sequence[NovelScreenItem]) -> str:
    return "\n\n".join(f"=== {item.part}: {_PART_LABELS[item.part]} ===\n{item.text}" for item in items)


def build_novel_screen_prompt(sections: Sequence[PromptSection], items: Sequence[NovelScreenItem]) -> NovelizePrompt:
    """심사 호출의 지시문과 본문. 필수 슬롯이 없거나 렌더 결과가 비면 `PromptRenderError` — 빈 프롬프트로 과금 호출을
    내지 않는다. 실을 글이 없어도 같은 예외다(호출부는 심사할 것이 있을 때만 부른다)."""
    if not items:
        raise PromptRenderError(f"channel={NOVEL_SCREEN_CHANNEL!r} 심사할 글이 없다")
    present = {s.slot for s in select_sections_for_render(sections, channel=NOVEL_SCREEN_CHANNEL, scope="both")}
    missing = sorted(_REQUIRED_SLOTS - present)
    if missing:
        raise PromptRenderError(f"channel={NOVEL_SCREEN_CHANNEL!r} 필수 슬롯이 없다: {missing}")
    channel_sections = [s for s in sections if s.channel == NOVEL_SCREEN_CHANNEL]
    instruction = render_prompt_channel(
        [s for s in channel_sections if s.slot == _INSTRUCTION_SLOT],
        channel=NOVEL_SCREEN_CHANNEL,
        scope="both",
        values={},
    )
    prompt = render_prompt_channel(
        [s for s in channel_sections if s.slot != _INSTRUCTION_SLOT],
        channel=NOVEL_SCREEN_CHANNEL,
        scope="both",
        values={"screened_text": _screened_text(items)},
    )
    if not instruction.strip() or not prompt.strip():
        raise PromptRenderError(f"channel={NOVEL_SCREEN_CHANNEL!r} 렌더 결과가 비었다")
    return NovelizePrompt(system_instruction=instruction, prompt=prompt)


async def screen_novel_text(
    llm_client: LLMClient,
    *,
    sections: Sequence[PromptSection],
    items: Sequence[NovelScreenItem],
    user_id: uuid.UUID,
) -> NovelScreenVerdict:
    """심사를 한 번 부른다. 안전 차단(`LLMPolicyViolationError`)은 판정이 없는 장애가 아니라 실린 글이 차단 기준에 걸린
    것이라 거부로 돌려준다 — 어느 자리인지 모르므로 실은 자리 전부를 짚는다. 그 밖의 호출 실패(`LLMClientError`)와 렌더
    실패(`PromptRenderError`)는 그대로 올린다 — 호출부가 공개하지 않고(fail-closed) 장애로 알린다."""
    built = build_novel_screen_prompt(sections, items)
    model = structured_model(NOVEL_SCREEN_CALL_SITE, settings.gemini_model_name)
    screened = tuple(item.part for item in items)
    try:
        result = await llm_client.generate_structured_with_instruction(
            built.prompt,
            NovelScreenResult,
            system_instruction=built.system_instruction,
            usage=LLMCallContext(call_site=NOVEL_SCREEN_CALL_SITE, user_id=user_id, room_id=None),
        )
    except LLMPolicyViolationError as exc:
        logger.warning("novel_screen_blocked user_id=%s: %s", user_id, exc)
        return NovelScreenVerdict(passed=False, flagged_parts=screened, reason="안전 기준 차단", model=model)
    if result.passed:
        return NovelScreenVerdict(passed=True, flagged_parts=(), reason=None, model=model)
    flagged = tuple(part for part in get_args(NovelScreeningPart) if part in result.flagged_parts and part in screened)
    return NovelScreenVerdict(passed=False, flagged_parts=flagged, reason=result.reason, model=model)


def _rejection_key(user_id: uuid.UUID, now: datetime) -> str:
    return f"{_REJECTION_KEY_PREFIX}:{user_id}:{now.astimezone(KST).date().isoformat()}"


async def rejections_left(db: AsyncSession, user_id: uuid.UUID, now: datetime) -> int | None:
    """오늘 더 걸릴 수 있는 횟수. 면제 계정이거나 Redis 를 읽지 못하면 None(상한을 적용하지 않는다)."""
    if await is_rate_limit_exempt(user_id, db):
        return None
    try:
        raw = await redis_client.get(_rejection_key(user_id, now))
    except RedisError:
        logger.warning("노벨 심사 거부 횟수를 읽지 못했다 — 상한을 적용하지 않는다", exc_info=True)
        _report_redis_failure()
        return None
    used = int(raw) if raw is not None else 0
    return max(NOVEL_SCREEN_DAILY_REJECTION_LIMIT - used, 0)


async def enforce_rejection_limit(db: AsyncSession, user_id: uuid.UUID, now: datetime) -> None:
    """심사 LLM 을 부르기 직전에 본다. 오늘 상한만큼 걸렸으면 KST 자정까지 429."""
    left = await rejections_left(db, user_id, now)
    if left == 0:
        raise _too_many_requests(user_id, NOVEL_SCREEN_LIMIT_WINDOW, seconds_until_kst_midnight(now))


async def enforce_call_limit(db: AsyncSession, user_id: uuid.UUID) -> None:
    """심사 LLM 을 부르기 직전에 한 번 센다 — 세는 단위가 요청이 아니라 심사 호출이라 심사할 글이 없는 요청(바뀐 것이
    없는 다시 공개)은 세지 않는다. 상한을 넘었으면 창이 끝날 때까지 429."""
    await _enforce_hourly_limit(
        user_id, db, scope=_CALL_SCOPE, limit=NOVEL_SCREEN_HOURLY_CALL_LIMIT, window=NOVEL_SCREEN_LIMIT_WINDOW
    )


async def count_rejection(user_id: uuid.UUID, now: datetime) -> None:
    """거부 한 번을 센다. 창은 KST 자정까지라 키에 날짜를 섞고 첫 증가에서만 만료를 건다. 면제 계정도 세지만 상한을
    적용하지 않으므로 영향이 없다. Redis 가 실패하면 세지 못한 채 넘어간다(상한 검사도 같은 장애에서 통과시킨다)."""
    key = _rejection_key(user_id, now)
    try:
        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, seconds_until_kst_midnight(now), nx=True)
            await pipe.execute()
    except RedisError:
        logger.warning("노벨 심사 거부 횟수를 세지 못했다", exc_info=True)
        _report_redis_failure()
