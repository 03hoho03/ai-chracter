import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, assert_never, get_args

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.concurrency import run_in_threadpool

from api.assets.image_processing import THUMBNAIL_CONTENT_TYPE, generate_thumbnail
from api.core.config import settings
from api.core.s3 import build_object_key, build_thumbnail_key, generate_presigned_get_url, upload_object
from api.db.models.media import Asset, AssetKind, AssetStatus
from api.db.session import get_db_session, get_session_factory
from api.images.jobs import ImageGenerationJobStatus, create_job, enqueue_generation, get_job, update_job
from api.images.models import (
    IMAGE_MODELS,
    IMAGE_STYLE_PRESETS_BY_ID,
    AspectRatio,
    ImageBlockedReason,
    ImageModelId,
    ImageStylePreset,
)
from api.images.schemas import (
    GenerateImageRequest,
    GenerateImageResponse,
    ImageJobImageItem,
    ImageJobStatusResponse,
    ImageModelItem,
    ImageStyleItem,
)
from api.llm.client import LLMClientError
from api.llm.dependencies import get_image_client
from api.llm.image import ImageClient
from api.llm.local_image import LocalImageBlockedError, get_capabilities, release_admission, try_admit
from api.session.dependencies import get_current_user_id

# local-image-gen-contract.md LC-1: 정적 레지스트리 ↔ 로컬 capabilities 불일치는 조용한
# 기능 축소로 나타나므로 로그가 유일한 신호다. uvicorn이 root logger에 핸들러를 안 붙여
# info는 사라지지만 WARNING 이상은 logging.lastResort로 stderr에 찍힌다
# (`chat/router.py:100-103` 선례) — print가 아니다.
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/images", tags=["images"])


@dataclass(frozen=True)
class _GenerationResult:
    """`_generate_and_store_one`의 3치 결과 — `bool` 2치로는 "차단"을 표현할 자리가
    없었다(guard-goal-prompt.md §1-5). `outcome`이 Literal이라 `_run_generation`의
    분기 누락을 mypy `assert_never`가 잡는다(guard-techspec.md GT-2,
    `llm/dependencies.py`의 기존 `assert_never` 패턴)."""

    outcome: Literal["succeeded", "blocked", "failed"]
    blocked_reason: ImageBlockedReason | None = None


async def _generate_and_store_one(
    image_client: ImageClient,
    session_factory: async_sessionmaker[AsyncSession],
    job_id: str,
    owner_user_id: uuid.UUID,
    prompt: str,
    style: ImageStylePreset,
    aspect_ratio: AspectRatio,
) -> _GenerationResult:
    try:
        data, mime_type = await image_client.generate_image(prompt, style, aspect_ratio)
        asset_id = uuid.uuid4()
        storage_key = build_object_key("generated", asset_id, mime_type)
        await run_in_threadpool(upload_object, storage_key, data, mime_type)
        # Invariant: a READY image asset always has a `{key}_thumb.webp` variant.
        # The bytes are already in memory, so no download_object round-trip. A
        # thumbnail failure falls through to the except blocks below (return
        # "failed") before the Asset row is created — never READY with only the
        # original.
        thumbnail_bytes = await run_in_threadpool(generate_thumbnail, data)
        await run_in_threadpool(
            upload_object, build_thumbnail_key(storage_key), thumbnail_bytes, THUMBNAIL_CONTENT_TYPE
        )

        async with session_factory() as session:
            session.add(
                Asset(
                    id=asset_id,
                    owner_user_id=owner_user_id,
                    storage_key=storage_key,
                    kind=AssetKind.GENERATED,
                    status=AssetStatus.READY,
                )
            )
            await session.commit()

        await update_job(job_id, completed_increment=1, asset_id=asset_id)
        return _GenerationResult(outcome="succeeded")
    except LocalImageBlockedError as exc:
        # guard-techspec.md GT-1: `LocalImageBlockedError`는 `LLMClientError`의
        # 하위 클래스라 아래 `except LLMClientError`보다 먼저 잡아야 한다 — 순서가
        # 바뀌면 차단이 조용히 일반 실패로 접힌다.
        return _GenerationResult(outcome="blocked", blocked_reason=exc.reason)
    except LLMClientError:
        return _GenerationResult(outcome="failed")
    except Exception as exc:
        # 생성/업로드/저장 중 예기치 못한 오류가 백그라운드 태스크를 조용히 죽여 잡이 running에
        # 영원히 멈추는 것을 방지한다(uvicorn이 root logger 핸들러를 안 붙여서 print로 남긴다).
        print(f"[imggen] job={job_id} unexpected generation error: {type(exc).__name__}: {exc}", flush=True)
        return _GenerationResult(outcome="failed")


async def _run_generation(
    job_id: str,
    owner_user_id: uuid.UUID,
    image_client: ImageClient,
    session_factory: async_sessionmaker[AsyncSession],
    prompt: str,
    style: ImageStylePreset,
    aspect_ratio: AspectRatio,
    count: int,
) -> None:
    # local-image-gen-progress.md P2-R: 이 잡을 위한 admission은 라우터의 `try_admit()`
    # 호출 하나에 대응한다(이미지 개수와 무관) — 잡이 끝나면(성공/실패 모두) 반드시
    # 반납해야 한다. 안 그러면 이 잡이 상한 슬롯을 영구 점유해 게이트가 막힌다.
    try:
        await update_job(job_id, status=ImageGenerationJobStatus.RUNNING)
        results = await asyncio.gather(
            *[
                _generate_and_store_one(
                    image_client, session_factory, job_id, owner_user_id, prompt, style, aspect_ratio
                )
                for _ in range(count)
            ]
        )

        # guard-techspec.md GT-3 / guard-progress.md I-1: `_generate_and_store_one`의
        # 반환이 3치가 되면서 `if any(results):`를 그대로 두면, 파이썬은 non-bool
        # 멤버를 전부 truthy로 보므로 전부 차단(succeeded 0건)이어도 이 줄이 True가
        # 되어 잡이 SUCCEEDED로 잘못 끝난다. 성공/차단을 직접 센다 — `assert_never`가
        # 세 번째 outcome을 빠짐없이 처리했는지 mypy로 강제한다.
        succeeded_count = 0
        failed_count = 0
        blocked_reasons: list[ImageBlockedReason] = []
        for result in results:
            if result.outcome == "succeeded":
                succeeded_count += 1
            elif result.outcome == "blocked":
                assert result.blocked_reason is not None
                blocked_reasons.append(result.blocked_reason)
            elif result.outcome == "failed":
                failed_count += 1
            else:
                assert_never(result.outcome)

        blocked_count = len(blocked_reasons)
        blocked_reason: ImageBlockedReason | None = None
        if blocked_reasons:
            blocked_reason = blocked_reasons[0]
            # guard-goal-prompt.md G-5: 사유만 남긴다 — 사용자 id·프롬프트 원문은
            # 절대 넣지 않는다.
            logger.warning("local image generation blocked: reason=%s count=%d", blocked_reason, blocked_count)
            distinct_reasons = set(blocked_reasons)
            if len(distinct_reasons) > 1:
                # guard-techspec.md GT-3: 프롬프트 가드는 결정적이라 한 잡 안에서
                # 사유가 섞일 수 없다(G-6) — 섞이면 로컬이 계약(LC-4b)을 어긴
                # 것이므로 조용히 넘기지 않는다.
                logger.warning(
                    "local image generation blocked reasons mismatched within one job: reasons=%s",
                    sorted(distinct_reasons),
                )
            if failed_count > 0:
                # guard-progress.md 적대적 리뷰: GT-3의 표는 성공/차단 수만 키로
                # 삼아 "차단과 무관한 진짜 실패가 함께 일어났다"는 칸이 아예 없었다
                # — 그 조합은 순수 전부-차단 잡과 구분 불가능하게 FAILED+error=None
                # 으로 끝나 진짜 회귀의 흔적이 `print()`뿐이 된다. 사용자 화면은
                # 그대로 정책 차단으로 두고(사실이다), 운영자에게만 별개의 신호를
                # 남긴다.
                logger.warning(
                    "local image generation blocked alongside a non-block failure: "
                    "blocked_reason=%s blocked_count=%d failed_count=%d",
                    blocked_reason,
                    blocked_count,
                    failed_count,
                )

        if succeeded_count > 0:
            await update_job(
                job_id,
                status=ImageGenerationJobStatus.SUCCEEDED,
                blocked_count=blocked_count,
                blocked_reason=blocked_reason,
            )
        elif blocked_count > 0:
            # guard-goal-prompt.md G-6: 문구는 FE가 조립한다 — error는 진짜 실패에만
            # 쓰고 차단에는 쓰지 않는다.
            await update_job(
                job_id,
                status=ImageGenerationJobStatus.FAILED,
                blocked_count=blocked_count,
                blocked_reason=blocked_reason,
            )
        else:
            await update_job(job_id, status=ImageGenerationJobStatus.FAILED, error="이미지 생성에 모두 실패했습니다")
    finally:
        release_admission()


def _known_styles(wire_style_ids: tuple[str, ...]) -> list[ImageStyleItem]:
    """local-image-gen-goal-prompt.md LG-19: 로컬이 보고하는 건 **와이어** 스타일 id다 —
    공개 id로 되매핑한 뒤에야 정적 라벨 레지스트리와 교차할 수 있다. N=1이라 매핑은
    스칼라 비교 하나다(LG-16, style이 여럿이 되면 이 함수가 다시 설계된다). 서버가 모르는
    id는 무시한다(contract LC-1과 같은 규칙을 모델뿐 아니라 스타일에도 적용)."""
    items: list[ImageStyleItem] = []
    for wire_style_id in wire_style_ids:
        if wire_style_id != settings.local_image_style_wire_id:
            continue
        spec = IMAGE_STYLE_PRESETS_BY_ID.get(ImageStylePreset.BASE.value)
        if spec is not None:
            items.append(ImageStyleItem(id=spec.id, name=spec.name))
    return items


# 로컬이 보고하는 aspect_ratio는 (JSON을 거쳐 온) 평범한 str이라 `AspectRatio` Literal로
# 정적으로 좁혀지지 않는다 — dict 조회로 좁히고, 서버가 모르는 값은 `_known_styles`와 같은
# 규칙으로 무시한다.
_ASPECT_RATIO_VALUES: dict[str, AspectRatio] = {ratio: ratio for ratio in get_args(AspectRatio)}


def _known_aspect_ratios(aspect_ratios: tuple[str, ...]) -> list[AspectRatio]:
    items: list[AspectRatio] = []
    for aspect_ratio in aspect_ratios:
        known = _ASPECT_RATIO_VALUES.get(aspect_ratio)
        if known is not None:
            items.append(known)
    return items


@router.get("/models")
async def list_image_models(
    owner_user_id: uuid.UUID = Depends(get_current_user_id),
) -> list[ImageModelItem]:
    """생성에 쓸 수 있는 모델 + 각 모델이 지원하는 종횡비/스타일. 정적 레지스트리(불투명
    id + 표시명)와 집 PC의 capabilities(가용성 + 지원 목록)를 교차한다(local-image-gen-
    techspec.md LT-6). 로컬이 안 준 정적 id는 불가로 내리고, 서버가 모르는 로컬 id는
    무시한다 — 불일치는 조용한 기능 축소로 나타나므로 WARNING으로 남긴다(contract LC-1).

    local-image-gen-goal-prompt.md LG-19: 로컬은 공개 id가 아니라 **와이어** id를
    보고한다 — 조회 키를 와이어 id로 바꾸지 않으면 이 교차가 항상 실패한다.

    LG-20: `available`은 capability 존재 여부가 아니라 "실제로 생성 가능"을 뜻해야 한다 —
    매핑된 style이 하나도 없으면 capability가 있어도 false다(이 경우도 WARNING)."""
    capabilities = await get_capabilities()
    local_ids = {model.model_id for model in capabilities.models}
    missing = {spec.id for spec in IMAGE_MODELS if settings.local_image_model_wire_id not in local_ids}
    if missing:
        logger.warning("local image capabilities missing registered model ids: %s", sorted(missing))

    items: list[ImageModelItem] = []
    for spec in IMAGE_MODELS:
        capability = capabilities.capability_for(settings.local_image_model_wire_id)
        if capability is None:
            items.append(
                ImageModelItem(
                    id=spec.id, name=spec.name, supported_aspect_ratios=[], available=False, styles=[]
                )
            )
            continue
        styles = _known_styles(capability.styles)
        if not styles:
            # LG-20: capability는 있지만 매핑되는 style이 하나도 없다 — id 불일치(위)와는
            # 다른 조용한 기능 축소라 구분되는 문구로 남긴다.
            logger.warning("local image capability for registered model id %s maps to no usable style", spec.id)
        items.append(
            ImageModelItem(
                id=spec.id,
                name=spec.name,
                supported_aspect_ratios=_known_aspect_ratios(capability.aspect_ratios),
                available=bool(styles),
                styles=styles,
            )
        )
    return items


@router.post("/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate_images(
    payload: GenerateImageRequest,
    owner_user_id: uuid.UUID = Depends(get_current_user_id),
    image_client_factory: Callable[[ImageModelId], ImageClient] = Depends(get_image_client),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> GenerateImageResponse:
    # local-image-gen-goal-prompt.md LG-8: 가용성 사전 확인을 맨 앞에 둔다 — 불가면 503,
    # 일시적 상태이고 클라이언트 잘못이 아니다. capabilities 전체가 불가이거나, 요청한
    # 모델이 로컬이 지금 보고하지 않는 모델이면 둘 다 같은 503으로 접는다.
    #
    # LG-19: 로컬은 공개 id(`payload.model`)가 아니라 와이어 id를 보고한다 — 조회 키를
    # 와이어 id로 바꾸지 않으면 이 확인이 항상 실패해 모든 생성이 503으로 막힌다.
    capabilities = await get_capabilities()
    capability = None if not capabilities.ready else capabilities.capability_for(settings.local_image_model_wire_id)
    if capability is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Image generation is currently unavailable"
        )

    if payload.aspect_ratio not in capability.aspect_ratios:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"model '{payload.model}' does not support aspect ratio '{payload.aspect_ratio}'",
        )
    # LG-19: capability.styles는 로컬이 보고한 와이어 style id들이다 — 비교 전에
    # 공개 style을 와이어로 매핑해야 한다(N=1이라 스칼라 하나, LG-16). 사용자에게 보이는
    # detail은 공개 값(`payload.style.value`)을 그대로 쓴다 — 와이어 id를 노출하지 않는다.
    if settings.local_image_style_wire_id not in capability.styles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"model '{payload.model}' does not support style '{payload.style.value}'",
        )

    # local-image-gen-techspec.md LT-3 / P2-R: 검사+증가가 `try_admit()` 하나의 동기
    # 함수 안에 있어 그 사이에 await가 끼어들 수 없다(원자적인 것은 `+=1` 자체가 아니라
    # 이 동기 블록이다) — 상한이 걸렸는데도 거절하지 않으면 한 사용자가 GPU 직렬
    # 처리량(LG-6)을 몇 분씩 독점한다.
    if not try_admit():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many generation requests are queued"
        )

    try:
        image_client = image_client_factory(payload.model)
        job = await create_job(owner_user_id, payload.count)
        await enqueue_generation(
            _run_generation,
            job.job_id,
            owner_user_id,
            image_client,
            session_factory,
            payload.prompt,
            payload.style,
            payload.aspect_ratio,
            payload.count,
        )
    except Exception:
        # admit과 백그라운드 인계 사이(예: `create_job`의 Redis 순단)에서 실패하면
        # `_run_generation`이 아예 시작되지 않아 그쪽의 finally가 못 돈다 — 여기서
        # 직접 반납하지 않으면 이 슬롯이 영구 점유돼 상한에서 게이트가 막힌다.
        release_admission()
        raise
    return GenerateImageResponse(job_id=job.job_id)


@router.get("/jobs/{job_id}")
async def get_image_job(
    job_id: str,
    owner_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db_session),
) -> ImageJobStatusResponse:
    job = await get_job(job_id, owner_user_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    images: list[ImageJobImageItem] = []
    for asset_id in job.asset_ids:
        asset = await db.get(Asset, asset_id)
        if asset is None:
            continue
        image_url = await run_in_threadpool(generate_presigned_get_url, asset.storage_key)
        images.append(ImageJobImageItem(asset_id=asset_id, image_url=image_url))

    return ImageJobStatusResponse(
        status=job.status,
        requested_count=job.requested_count,
        completed_count=job.completed_count,
        images=images,
        error=job.error,
        blocked_count=job.blocked_count,
        blocked_reason=job.blocked_reason,
    )
