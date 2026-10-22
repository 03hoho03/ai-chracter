"""노벨 공개 전 삽화 심사 — 심사할 그림 목록, 프롬프트, 그림 내려받기, 심사 호출, 통과 기억, 운영자 내림.

**무엇을 심사하나**: 공개(처음 공개·다음 화·다시 공개)가 얼릴 개정에서 문단에 붙은 그림 전부다. 위치 확인 필요인 그림은 독자에게
나가지 않으므로 싣지 않는다. 독자가 보는 것과 같은 바이트를 보도록 크게 그리는 정지 변형(`_display.webp`)을 내려받아 심사한다 —
움직이는 그림도 이 정지 변형 한 장이다(삽화는 정지 그림으로만 보인다).

**문안**: 작품 발행 심사와 같은 `publish_filter` 레인의 활성 세트를 쓴다(같은 판정 기준). 서두 슬롯은 소설의 원작 종류
(`story`·`character`) 범위를 고르고, 이미지 목록 줄은 코드가 만든 삽화 자리 이름("삽화 — 3문단 뒤")이다. 그래서 운영 프롬프트에
새 행이 없어도 돈다. 모델은 발행 심사와 같은 스위치다(call_site 가 발행 심사 집합에 있다).

**통과 기억**: 그림 바이트의 sha256·모델·심사 문안 판(활성 세트 id 와 범위)이 키다. 같은 바이트를 다른 자산으로 다시 올려도 다시
부르지 않고, 모델이나 문안이 바뀌면 다시 심사한다. **운영자 내림이 기억보다 먼저다** — 내린 바이트는 기억이 있어도 공개하지 않는다.

**운영자 내림**: 그림 하나(자산)의 정지 변형 바이트 sha 를 내림 표에 남기고 그 sha 의 통과 기억을 지운다. 읽기는 자산 행에
적힌 바이트 sha(공개 심사·내림이 내려받을 때 적는다)나 자산 id 로 내림 표를 이어 그 그림 자리를 비우고 사유를 싣는다
(`illustration_reads.py`) — 같은 파일을 담은 다른 자산도 이미 얼린 판에서 함께 비워진다."""

import hashlib
import logging
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.chat.prompt_builder import PromptLane, PromptRenderError, render_prompt_channel
from api.content.publish import PublishFilterResult
from api.core.config import settings
from api.core.s3 import build_display_key, download_object
from api.db.models.media import Asset
from api.db.models.novel import (
    NovelContentType,
    NovelIllustrationPlacement,
    NovelIllustrationScreenPass,
    NovelIllustrationSource,
    NovelIllustrationTakedown,
)
from api.db.models.prompt import PromptSection
from api.llm.client import LLMCallContext, LLMCallSite, LLMClient, LLMPolicyViolationError, structured_model

logger = logging.getLogger(__name__)

NOVEL_ILLUSTRATION_SCREEN_CALL_SITE: LLMCallSite = "novel_illustration_screen"
NOVEL_ILLUSTRATION_SCREEN_LANE: PromptLane = "publish_filter"
_CHANNEL = "publish_filter"
# 그림 정지 변형의 형식. 변형은 늘 WebP 로 만든다(`core/s3.py` 의 변형 키).
_DISPLAY_CONTENT_TYPE = "image/webp"
# 안전 차단으로 판정이 없을 때 거부 기록에 남기는 사유. 운영 기록용이다(게시자 화면에는 사유를 싣지 않는다).
_BLOCKED_REASON = "안전 기준 차단"
TAKEN_DOWN_REASON = "운영자가 내린 그림"


@dataclass(frozen=True)
class PlannedPicture:
    """공개가 얼릴 개정의 문단에 붙은 그림 한 장 — 심사할 자산과 독자 화면의 자리(문단 번호·앞뒤)."""

    asset_id: uuid.UUID
    storage_key: str
    source: NovelIllustrationSource
    paragraph: int
    placement: NovelIllustrationPlacement


@dataclass(frozen=True)
class IllustrationVerdict:
    passed: bool
    reason: str | None
    model: str


def screening_model() -> str:
    """삽화 심사가 실제로 쓸 모델. 통과 기억의 키도 이 값이다 — 클라이언트와 같은 함수로 구해야 모델을 바꾼 뒤 옛 모델의 통과로
    건너뛰지 않는다."""
    return structured_model(NOVEL_ILLUSTRATION_SCREEN_CALL_SITE, settings.gemini_model_name)


def prompt_version(prompt_set_id: uuid.UUID, scope: NovelContentType) -> str:
    """통과 기억의 문안 판. 게시한 세트는 고쳐지지 않고(고치면 새 세트를 게시한다) 범위마다 서두가 다르므로 세트 id 와 범위다."""
    return f"{prompt_set_id}:{scope}"


def picture_label(paragraph: int, placement: NovelIllustrationPlacement) -> str:
    """심사 프롬프트의 이미지 목록에 싣는 그림 자리 이름. 문단 번호는 1부터 센다."""
    return f"삽화 — {paragraph + 1}문단 {'앞' if placement == 'before' else '뒤'}"


def build_novel_illustration_screen_prompt(
    sections: Sequence[PromptSection], *, scope: NovelContentType, labels: Sequence[str]
) -> str:
    """심사 호출의 프롬프트. 그림은 같은 호출의 이미지로 이 목록과 같은 순서로 싣는다. 렌더 결과가 비면 `PromptRenderError` —
    빈 프롬프트로 과금 호출을 내지 않는다."""
    lines = "\n".join(f"{position}. {label}" for position, label in enumerate(labels, start=1))
    prompt = render_prompt_channel(sections, channel=_CHANNEL, scope=scope, values={"image_lines": lines})
    if not prompt.strip() or not labels:
        raise PromptRenderError(f"channel={_CHANNEL!r} 삽화 심사 프롬프트가 비었다")
    return prompt


def download_display(storage_key: str) -> bytes:
    """Blocking network call — run via `run_in_threadpool`. 그림의 정지 변형 바이트. 못 읽으면 저장소 예외를 그대로 올린다 —
    호출부가 공개를 멈춘다(그림을 빼고 심사하면 미심사 그림이 얼린다)."""
    return download_object(build_display_key(storage_key))


async def download_pictures(pictures: Sequence[PlannedPicture]) -> list[bytes]:
    return [await run_in_threadpool(download_display, picture.storage_key) for picture in pictures]


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def taken_down_shas(db: AsyncSession, shas: Iterable[str]) -> set[str]:
    wanted = set(shas)
    if not wanted:
        return set()
    rows = await db.scalars(
        select(NovelIllustrationTakedown.content_sha256).where(NovelIllustrationTakedown.content_sha256.in_(wanted))
    )
    return set(rows.all())


async def record_display_shas(db: AsyncSession, pairs: Iterable[tuple[uuid.UUID, str]]) -> None:
    """내려받은 그림 바이트의 sha 를 그 자산 행에 적는다 — 화 읽기가 이 값으로 같은 파일을 담은 다른 자산의 내림을 본다. 커밋은
    호출자."""
    for asset_id, sha in dict(pairs).items():
        await db.execute(update(Asset).where(Asset.id == asset_id).values(display_sha256=sha))


async def remembered_shas(db: AsyncSession, shas: Iterable[str], *, model: str, version: str) -> set[str]:
    wanted = set(shas)
    if not wanted:
        return set()
    rows = await db.scalars(
        select(NovelIllustrationScreenPass.content_sha256).where(
            NovelIllustrationScreenPass.content_sha256.in_(wanted),
            NovelIllustrationScreenPass.model == model,
            NovelIllustrationScreenPass.prompt_version == version,
        )
    )
    return set(rows.all())


async def remember_passes(db: AsyncSession, shas: Iterable[str], *, model: str, version: str) -> None:
    """통과한 바이트를 기억한다(이미 있으면 그대로). 커밋은 호출자."""
    rows = [{"content_sha256": sha, "model": model, "prompt_version": version} for sha in sorted(set(shas))]
    if rows:
        await db.execute(insert(NovelIllustrationScreenPass).values(rows).on_conflict_do_nothing())


async def screen_novel_illustrations(
    llm_client: LLMClient, *, prompt: str, images: Sequence[bytes], user_id: uuid.UUID
) -> IllustrationVerdict:
    """그림 심사를 한 번 부른다(그림 여럿을 한 호출에). 안전 차단은 판정이 없는 장애가 아니라 실린 그림이 차단 기준에 걸린 것이라
    거부로 돌려준다. 그 밖의 호출 실패(`LLMClientError`)는 그대로 올린다 — 호출부가 공개하지 않고 장애로 알린다."""
    model = screening_model()
    try:
        result = await llm_client.generate_structured(
            prompt,
            PublishFilterResult,
            images=[(data, _DISPLAY_CONTENT_TYPE) for data in images],
            usage=LLMCallContext(call_site=NOVEL_ILLUSTRATION_SCREEN_CALL_SITE, user_id=user_id, room_id=None),
        )
    except LLMPolicyViolationError as exc:
        logger.warning("novel_illustration_screen_blocked user_id=%s: %s", user_id, exc)
        return IllustrationVerdict(passed=False, reason=_BLOCKED_REASON, model=model)
    if result.passed:
        return IllustrationVerdict(passed=True, reason=None, model=model)
    return IllustrationVerdict(passed=False, reason=result.reason, model=model)


async def record_takedown(db: AsyncSession, *, asset_id: uuid.UUID, sha: str, reason: str) -> datetime | None:
    """내림 한 줄을 남기고 그 바이트의 통과 기억을 지운다. 남긴 시각을 돌려주고, 같은 바이트가 이미 내려가 있으면 아무것도 쓰지
    않고 None. 커밋은 호출자."""
    inserted: datetime | None = await db.scalar(
        insert(NovelIllustrationTakedown)
        .values(content_sha256=sha, asset_id=asset_id, reason=reason)
        .on_conflict_do_nothing()
        .returning(NovelIllustrationTakedown.created_at)
    )
    if inserted is None:
        return None
    await db.execute(delete(NovelIllustrationScreenPass).where(NovelIllustrationScreenPass.content_sha256 == sha))
    return inserted
