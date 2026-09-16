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
from api.core.sentry import capture_dependency_failure
from api.db.models.media import Asset, AssetKind, AssetStatus, ImageGenerationRequest
from api.db.session import get_db_session, get_session_factory
from api.images.jobs import ImageGenerationJobStatus, create_job, enqueue_generation, get_job, update_job
from api.images.models import (
    IMAGE_MODELS,
    IMAGE_STYLE_PRESETS,
    AspectRatio,
    ImageBlockedReason,
    ImageInputError,
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
from api.legal.dependencies import require_legal_consent
from api.llm.client import LLMClientError
from api.llm.dependencies import get_image_client
from api.llm.image import ImageClient
from api.llm.local_image import (
    LocalImageBlockedError,
    LocalImageInputError,
    get_capabilities,
    release_admission,
    try_admit,
)
from api.session.dependencies import get_current_user_id

# local-image-gen-contract.md LC-1: 정적 레지스트리 ↔ 로컬 capabilities 불일치는 조용한
# 기능 축소로 나타나므로 로그가 유일한 신호다. uvicorn이 root logger에 핸들러를 안 붙여
# info는 사라지지만 WARNING 이상은 logging.lastResort로 stderr에 찍힌다
# (`chat/router.py:100-103` 선례) — print가 아니다.
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/images", tags=["images"])


@dataclass(frozen=True)
class _GenerationResult:
    """`_generate_and_store_one`의 결과 — `bool` 2치로는 "차단"을 표현할 자리가
    없었다(guard-goal-prompt.md §1-5). `outcome`이 Literal이라 `_run_generation`의
    분기 누락을 mypy `assert_never`가 잡는다(guard-techspec.md GT-2,
    `llm/dependencies.py`의 기존 `assert_never` 패턴). image-style-7-goal-prompt.md
    IS-8: `input_error`는 그 안전망을 그대로 활용해 추가한 네 번째 값이다."""

    outcome: Literal["succeeded", "blocked", "input_error", "failed"]
    blocked_reason: ImageBlockedReason | None = None
    input_error: ImageInputError | None = None


async def _generate_and_store_one(
    image_client: ImageClient,
    session_factory: async_sessionmaker[AsyncSession],
    job_id: str,
    owner_user_id: uuid.UUID,
    request_id: uuid.UUID,
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
                    # image-style-7-goal-prompt.md IS-6: plain Text 컬럼이라
                    # `.value`를 명시한다(apps/api/CLAUDE.md 모델 규약).
                    style=style.value,
                    # image-monitoring-goal-prompt.md IM-4: 이 asset을 낳은 요청 행.
                    request_id=request_id,
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
    except LocalImageInputError as exc:
        # image-style-7-goal-prompt.md IS-8: `LocalImageInputError`도 `LLMClientError`의
        # 하위 클래스라 같은 이유로 아래 `except LLMClientError`보다 먼저 잡는다.
        return _GenerationResult(outcome="input_error", input_error=exc.input_error)
    except LLMClientError as exc:
        # image-style-7-goal-prompt.md IS-11: 예외 인스턴스를 바인딩하지 않으면 상태
        # 코드·detail이 통째로 버려져 400·422·429·500·503·타임아웃이 운영 로그에서
        # 구분 불가능하다. `local_image.py`가 이미 상태 코드+`detail`만 실어 메시지를
        # 만들어 뒀으므로(프롬프트 에코 가능성 배제) 그 문자열을 그대로 남긴다.
        logger.warning("local image generation call failed: %s", exc)
        # monitoring-techspec.md MT-6: 자가호스팅 이미지 생성 다운(집 PC)을 이벤트로도 승격한다.
        capture_dependency_failure(exc, dependency="local_image")
        return _GenerationResult(outcome="failed")
    except Exception as exc:
        # 생성/업로드/저장 중 예기치 못한 오류가 백그라운드 태스크를 조용히 죽여 잡이 running에
        # 영원히 멈추는 것을 방지한다(uvicorn이 root logger 핸들러를 안 붙여서 print로 남긴다).
        print(f"[imggen] job={job_id} unexpected generation error: {type(exc).__name__}: {exc}", flush=True)
        return _GenerationResult(outcome="failed")


async def _run_generation(
    job_id: str,
    owner_user_id: uuid.UUID,
    request_id: uuid.UUID,
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
                    image_client, session_factory, job_id, owner_user_id, request_id, prompt, style, aspect_ratio
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
        input_errors: list[ImageInputError] = []
        for result in results:
            if result.outcome == "succeeded":
                succeeded_count += 1
            elif result.outcome == "blocked":
                assert result.blocked_reason is not None
                blocked_reasons.append(result.blocked_reason)
            elif result.outcome == "input_error":
                assert result.input_error is not None
                input_errors.append(result.input_error)
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

        input_error_count = len(input_errors)
        input_error: ImageInputError | None = None
        if input_errors:
            input_error = input_errors[0]
            logger.warning(
                "local image generation rejected input: input_error=%s count=%d",
                input_error,
                input_error_count,
            )
            distinct_input_errors = set(input_errors)
            if len(distinct_input_errors) > 1:
                # image-style-7-goal-prompt.md IS-8 §3-8: 문법 오류·길이 초과는
                # 결정적이라 한 잡 안에서 사유가 섞일 수 없다 — 섞이면 프록시 흔들림
                # 등 계약 밖 사건이므로 위 blocked_reasons 불일치 경고와 같은 패턴으로
                # 조용히 넘기지 않는다.
                logger.warning(
                    "local image generation input errors mismatched within one job: input_errors=%s",
                    sorted(distinct_input_errors),
                )

        # image-monitoring-goal-prompt.md IM-4 종료 상태 판정 규칙 표: 아래 Redis 잡 갱신과
        # 같은 집계값으로 요청 행을 한 번 UPDATE한다. `completed_count>0`이면 부분 성공도
        # succeeded다(이미지가 한 장이라도 나왔다) — 그 다음은 blocked_count, 나머지(입력
        # 오류만 난 경우 포함)는 failed다. Redis 갱신보다 먼저 커밋해야 한다 — 뒤에 두면
        # "잡 완료 직후 release_admission 호출"을 보는 기존 테스트가 그 사이에 낀 이
        # await 때문에 레이스로 깨진다(`test_admission_is_released_when_the_job_finishes_...`).
        if succeeded_count > 0:
            request_status = "succeeded"
        elif blocked_count > 0:
            request_status = "blocked"
        else:
            request_status = "failed"
        request_error = (
            "이미지 생성에 모두 실패했습니다"
            if succeeded_count == 0 and blocked_count == 0 and input_error_count == 0
            else None
        )
        try:
            async with session_factory() as session:
                request_row = await session.get(ImageGenerationRequest, request_id)
                assert request_row is not None
                request_row.status = request_status
                request_row.completed_count = succeeded_count
                request_row.blocked_count = blocked_count
                request_row.input_error_count = input_error_count
                request_row.blocked_reason = blocked_reason
                request_row.input_error = input_error
                request_row.error = request_error
                await session.commit()
        except Exception as exc:
            # image-monitoring-goal-prompt.md IM-4 + test_generate_unexpected_error_marks_job_failed의
            # hang 방지 불변식: 요청 행 기록은 부가 기능이다 — 이 UPDATE가 실패해도(커넥션 끊김 등)
            # 아래 Redis update_job()은 반드시 실행돼야 잡이 RUNNING에 무기한 멈추지 않는다.
            logger.warning("image generation request row update failed: job=%s error=%s", job_id, type(exc).__name__)
            capture_dependency_failure(exc, dependency="db")

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
        elif input_error_count > 0:
            # image-style-7-goal-prompt.md IS-8: 성공과 공존하는 경우는 위 succeeded_count
            # 분기가 이미 가로챈다 — 문법/길이 오류는 결정적이라 원래 그 조합이 없어야
            # 정상이고(부분 input_error 안내가 FE에 없는 이유), 섞이면 위 경고가 남는다.
            await update_job(
                job_id,
                status=ImageGenerationJobStatus.FAILED,
                input_error_count=input_error_count,
                input_error=input_error,
            )
        else:
            await update_job(job_id, status=ImageGenerationJobStatus.FAILED, error="이미지 생성에 모두 실패했습니다")
    finally:
        release_admission()


def _style_items(served_style_ids: tuple[str, ...]) -> list[ImageStyleItem]:
    """image-style-7-goal-prompt.md IS-2/IS-5 — style 축의 공개 id와 와이어 id가
    같아져(IS-2) 매핑 없이 원소별로 판정한다. 레지스트리 전체를 항상 내리고, 로컬이
    보고한 집합에 있는 것만 available=true로 표시한다. (이전 `_known_styles`는 로컬
    보고값으로 **걸렀다** — 그러면 준비 중 스타일이 응답에서 사라져 "없는 것"과
    구분되지 않는다.)

    `served`를 bool이 아니라 집합으로 두는 것 자체가 방어다 — bool로 두면 `and`로
    잇고 싶어지고, 그 순간 "하나라도 서빙되면 전부 available" 버그가 열린다(같은
    함수가 image-refact-techspec.md IT-4로 이미 한 번 이 함정에 물렸다).
    """
    served = set(served_style_ids)
    return [
        ImageStyleItem(id=spec.id, name=spec.name, available=spec.id in served)
        for spec in IMAGE_STYLE_PRESETS
    ]


# 로컬이 보고하는 aspect_ratio는 (JSON을 거쳐 온) 평범한 str이라 `AspectRatio` Literal로
# 정적으로 좁혀지지 않는다 — dict 조회로 좁히고, 서버가 모르는 값은 무시한다. (`_style_items`는
# image-refact-techspec.md IT-3부터 이 규칙을 쓰지 않는다 — 레지스트리 전체를 항상 내리고
# `available`로만 표시한다.)
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
        styles = _style_items(capability.styles)
        # image-refact-techspec.md IT-4: `_style_items`(IS-5)가 레지스트리 전체(항상
        # 7개)를 내리면서 `bool(styles)`는 항진명제가 됐다 — styles가 비는 경우가
        # 없어져 이 조건이 늘 True였다. LG-20의 의도("실제로 생성 가능")를 지키려면
        # available 플래그로 직접 물어야 한다.
        if not any(style.available for style in styles):
            # LG-20: capability는 있지만 매핑되는 style이 하나도 없다 — id 불일치(위)와는
            # 다른 조용한 기능 축소라 구분되는 문구로 남긴다.
            logger.warning("local image capability for registered model id %s maps to no usable style", spec.id)
        items.append(
            ImageModelItem(
                id=spec.id,
                name=spec.name,
                supported_aspect_ratios=_known_aspect_ratios(capability.aspect_ratios),
                available=any(style.available for style in styles),
                styles=styles,
            )
        )
    return items


@router.post(  # consent-gate-goal-prompt.md CG-3/CG-4
    "/generate", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_legal_consent)]
)
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
    # image-refact-techspec.md IT-5: 레지스트리 기준으로 판정한다 — `_style_items`(IS-5)가
    # 요청된 스타일이 레지스트리에 있는지와 지금 서빙되고 있는지(available)를 함께 본다.
    # image-style-7-goal-prompt.md IS-2: style 축은 공개 id와 와이어 id가 같아
    # capability.styles를 매핑 없이 그대로 집합 비교한다. 사용자에게 보이는 detail은
    # 공개 값(`payload.style.value`)을 그대로 쓴다.
    style_items = _style_items(capability.styles)
    if not any(item.available and item.id == payload.style.value for item in style_items):
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
        # image-monitoring-goal-prompt.md IM-4: 접수 시 INSERT — 프롬프트·모델·비율·스타일이
        # 전부 모여 있는 유일한 지점이 여기다. `create_job` 성공 뒤·`enqueue_generation` 앞에
        # 둔다: 더 앞에 두면 429/503 사전 차단 경로(IM-6)에도 행이 생기고, asset의 FK 때문에
        # 이 행은 백그라운드가 돌기 전에 이미 커밋돼 있어야 한다.
        async with session_factory() as session:
            request_row = ImageGenerationRequest(
                owner_user_id=owner_user_id,
                prompt=payload.prompt,
                style=payload.style.value,
                aspect_ratio=payload.aspect_ratio,
                model=payload.model,
                requested_count=payload.count,
                status="pending",
            )
            session.add(request_row)
            await session.commit()
        await enqueue_generation(
            _run_generation,
            job.job_id,
            owner_user_id,
            request_row.id,
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
        input_error_count=job.input_error_count,
        input_error=job.input_error,
    )
