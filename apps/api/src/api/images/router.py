import asyncio
import dataclasses
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, assert_never, get_args

from fastapi import APIRouter, Depends, HTTPException, status
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.concurrency import run_in_threadpool

from api.assets.image_processing import (
    THUMBNAIL_CONTENT_TYPE,
    ReferenceImageRejectedError,
    generate_variants,
    read_image_size,
    run_image_work,
    validate_reference_image,
)
from api.core import clover
from api.core.config import settings
from api.core.rate_limit_gate import (
    ImageCharge,
    enforce_image_rate_limit,
    image_queue_full,
    refund_image_charge,
)
from api.core.s3 import (
    build_object_key,
    download_object,
    generate_presigned_get_url,
    upload_object,
)
from api.core.redis import redis_client
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
    keep_admission_alive,
    release_admission,
    try_admit,
)
from api.session.dependencies import get_current_user_id

# 정적 레지스트리 ↔ 로컬 capabilities 불일치는 조용한
# 기능 축소로 나타나므로 로그가 유일한 신호다. uvicorn이 root logger에 핸들러를 안 붙여
# info는 사라지지만 WARNING 이상은 logging.lastResort로 stderr에 찍힌다
# (`chat/router.py:100-103` 선례) — print가 아니다.
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/images", tags=["images"])


@dataclass(frozen=True)
class _GenerationResult:
    """`_generate_and_store_one`의 결과 — `bool` 2치로는 "차단"을 표현할 자리가
    없었다. `outcome`이 Literal이라 `_run_generation`의
    분기 누락을 mypy `assert_never`가 잡는다(`llm/dependencies.py`의 기존 `assert_never`
    패턴). `input_error`는 그 안전망을 그대로 활용해 추가한 네 번째 값이다."""

    outcome: Literal["succeeded", "blocked", "input_error", "failed"]
    blocked_reason: ImageBlockedReason | None = None
    input_error: ImageInputError | None = None


class _ReferenceImageUnusableError(Exception):
    """참조 원본을 읽지 못했거나 계약 한도를 벗어났다. `LLMClientError`의 하위가 아니다 — 집 PC
    장애(`local_image`)와 섞이지 않게 따로 잡아 따로 태그한다. `cause`는 실패 종류만 담는다."""

    def __init__(self, cause: str) -> None:
        self.cause = cause
        super().__init__(f"reference image unusable: {cause}")


async def _load_reference_image(storage_key: str) -> bytes:
    """참조 원본을 저장소에서 읽어 계약 한도를 확인한다. 장마다 부르므로 `count=2`면 같은 원본을
    두 번 읽는다 — 한 번만 읽으려고 모든 장을 시작하기 전(`_run_generation`의 `gather` 앞)으로
    옮기면, 거기서 난 실패는 잡을 RUNNING에, 요청 행을 pending에 남긴다."""
    try:
        data = await run_in_threadpool(download_object, storage_key)
    except Exception as exc:
        # 원본이 202 뒤에 지워졌거나 저장소가 순단했다. 종류를 가리지 않고 참조 실패로 접는다 —
        # 좁히면 모르는 예외가 아래 광역 `except`로 떨어져 운영 신호 없이 사라진다.
        raise _ReferenceImageUnusableError("download_failed") from exc
    try:
        await run_in_threadpool(validate_reference_image, data)
    except ReferenceImageRejectedError as exc:
        raise _ReferenceImageUnusableError(exc.reason) from exc
    return data


async def _generate_and_store_one(
    image_client: ImageClient,
    session_factory: async_sessionmaker[AsyncSession],
    job_id: str,
    owner_user_id: uuid.UUID,
    request_id: uuid.UUID,
    prompt: str,
    style: ImageStylePreset,
    aspect_ratio: AspectRatio,
    reference_storage_key: str | None,
) -> _GenerationResult:
    try:
        reference_image = (
            await _load_reference_image(reference_storage_key) if reference_storage_key is not None else None
        )
        data, mime_type = await image_client.generate_image(
            prompt, style, aspect_ratio, reference_image=reference_image
        )
        asset_id = uuid.uuid4()
        storage_key = build_object_key("generated", asset_id, mime_type)
        await run_in_threadpool(upload_object, storage_key, data, mime_type)
        # Invariant: a READY image asset always has every variant (`generate_variants`).
        # The bytes are already in memory, so no download_object round-trip. A
        # variant failure falls through to the except blocks below (return
        # "failed") before the Asset row is created — never READY with only the
        # original.
        variants = await run_image_work(generate_variants, storage_key, data)
        for variant_key, variant_bytes in variants:
            await run_in_threadpool(upload_object, variant_key, variant_bytes, THUMBNAIL_CONTENT_TYPE)
        width, height = await run_in_threadpool(read_image_size, data)

        async with session_factory() as session:
            session.add(
                Asset(
                    id=asset_id,
                    owner_user_id=owner_user_id,
                    storage_key=storage_key,
                    kind=AssetKind.GENERATED,
                    status=AssetStatus.READY,
                    # plain Text 컬럼이라
                    # `.value`를 명시한다(apps/api/CLAUDE.md 모델 규약).
                    style=style.value,
                    # 이 asset을 낳은 요청 행.
                    request_id=request_id,
                    width=width,
                    height=height,
                )
            )
            await session.commit()

        await update_job(job_id, completed_increment=1, asset_id=asset_id)
        return _GenerationResult(outcome="succeeded")
    except LocalImageBlockedError as exc:
        # `LocalImageBlockedError`는 `LLMClientError`의
        # 하위 클래스라 아래 `except LLMClientError`보다 먼저 잡아야 한다 — 순서가
        # 바뀌면 차단이 조용히 일반 실패로 접힌다.
        return _GenerationResult(outcome="blocked", blocked_reason=exc.reason)
    except LocalImageInputError as exc:
        # `LocalImageInputError`도 `LLMClientError`의
        # 하위 클래스라 같은 이유로 아래 `except LLMClientError`보다 먼저 잡는다.
        return _GenerationResult(outcome="input_error", input_error=exc.input_error)
    except _ReferenceImageUnusableError as exc:
        # 마지막 광역 `except`로 떨어지면 `print` 한 줄뿐이라 Bugsink에 남지 않는다. 로그에는 실패
        # 종류만 싣는다 — 저장 키·사용자 id·프롬프트는 싣지 않는다.
        logger.warning("reference image unusable: %s", exc.cause)
        capture_dependency_failure(exc, dependency="reference_image")
        return _GenerationResult(outcome="failed")
    except LLMClientError as exc:
        # 예외 인스턴스를 바인딩하지 않으면 상태
        # 코드·detail이 통째로 버려져 400·422·429·500·503·타임아웃이 운영 로그에서
        # 구분 불가능하다. `local_image.py`가 이미 상태 코드+`detail`만 실어 메시지를
        # 만들어 뒀으므로(프롬프트 에코 가능성 배제) 그 문자열을 그대로 남긴다.
        logger.warning("local image generation call failed: %s", exc)
        # 자가호스팅 이미지 생성 다운(집 PC)을 이벤트로도 승격한다.
        capture_dependency_failure(exc, dependency="local_image")
        return _GenerationResult(outcome="failed")
    except Exception as exc:
        # 생성/업로드/저장 중 예기치 못한 오류가 백그라운드 태스크를 조용히 죽여 잡이 running에
        # 영원히 멈추는 것을 방지한다(uvicorn이 root logger 핸들러를 안 붙여서 print로 남긴다).
        print(f"[imggen] job={job_id} unexpected generation error: {type(exc).__name__}: {exc}", flush=True)
        return _GenerationResult(outcome="failed")


async def _refund_unmade_images(
    owner_user_id: uuid.UUID,
    charge: ImageCharge,
    unmade_count: int,
    session_factory: async_sessionmaker[AsyncSession],
    job_id: str,
) -> None:
    """202 이후의 실패는 이 저장소에서
    환불이 0건이었다 — 무료 토큰버킷일 때는 감내할 수 있었지만 클로버는 사용자가 지불한 것이라,
    가드 차단·입력 오류·생성 실패·부분 성공이 전부 "돈만 사라지고 이미지는 0장"이 된다.

    되돌리는 양은 **못 만든 장수**다: 부분 성공에서 전량을 돌려주면 받은 이미지가 공짜가 되고,
    전량을 소모하면 못 받은 몫까지 낸다. `_run_generation`의 정상 경로와 예외 경로가 **이 함수
    하나**를 공유한다 — 두 자리에 식을 복제하면 나중에 한쪽만 고쳐진다.

    🔴 이 함수의 예외가 호출부로 새면 잡이 RUNNING에 무기한 멈추거나(정상 경로) 원래 예외를
    가린다(예외 경로). `refund_image_charge`는 자원별로 예외를 삼키지만, 삼키지 않는 경로가 새로
    생겨도 그렇게 되지 않도록 여기서 한 겹 더 막는다 — 환불 기록은 부가 기능이고 잡 종료와 원래
    예외 전파는 불변식이다."""
    if unmade_count <= 0:
        return
    try:
        await refund_image_charge(
            owner_user_id,
            # 영수증에서 못 만든 장수의 몫을 나눈다. 게이트가 `count * IMAGE_UNIT_COST`로 만들어 나눗셈이 정확히
            # 떨어진다. 지금 단가로 다시 곱하지 않는 이유: 차감과 환급 사이에 단가가 바뀌면 환급액이 그 차감의 배분을
            # 넘어 환급이 통째로 거부되거나(오른 경우) 덜 돌려준다(내린 경우). `source="token"`·`"skipped"`면 0이다.
            dataclasses.replace(
                charge,
                count=unmade_count,
                clover_amount=charge.clover_amount * unmade_count // charge.count,
            ),
            session_factory,
        )
    except Exception as exc:
        logger.warning("image generation refund failed: job=%s error=%s", job_id, type(exc).__name__)
        capture_dependency_failure(exc, dependency="clover")


async def _run_generation(
    job_id: str,
    owner_user_id: uuid.UUID,
    admission: str,
    request_id: uuid.UUID,
    image_client: ImageClient,
    session_factory: async_sessionmaker[AsyncSession],
    prompt: str,
    style: ImageStylePreset,
    aspect_ratio: AspectRatio,
    charge: ImageCharge,
    reference_storage_key: str | None,
) -> None:
    # 이 잡을 위한 admission은 라우터의 `try_admit()`
    # 호출 하나에 대응한다(이미지 개수와 무관) — 잡이 끝나면(성공/실패 모두) 반드시
    # 반납해야 한다. 안 그러면 이 잡이 만료까지 상한 슬롯을 점유해 그 유저가 429를 받는다.
    # 칸은 짧은 만료로 잡혀 있어(죽은 워커의 칸을 회수하려고) 잡이 도는 동안 갱신 태스크가 만료를 민다.
    #
    # 이 둘은 `try` **밖**에서 초기화한다 — 아래 `except`가
    # 집계 도중 터진 경우에도 "그 시점까지 성공한 장수"를 읽어야 하기 때문이다. `try` 안에
    # 두면 `update_job(RUNNING)`이 터졌을 때 이름 자체가 없어 `UnboundLocalError`가 난다.
    succeeded_count = 0
    refund_settled = False
    heartbeat = asyncio.create_task(keep_admission_alive(redis_client, admission))
    try:
        await update_job(job_id, status=ImageGenerationJobStatus.RUNNING)
        results = await asyncio.gather(
            *[
                _generate_and_store_one(
                    image_client,
                    session_factory,
                    job_id,
                    owner_user_id,
                    request_id,
                    prompt,
                    style,
                    aspect_ratio,
                    reference_storage_key,
                )
                for _ in range(charge.count)
            ]
        )

        # `_generate_and_store_one`의
        # 반환이 3치가 되면서 `if any(results):`를 그대로 두면, 파이썬은 non-bool
        # 멤버를 전부 truthy로 보므로 전부 차단(succeeded 0건)이어도 이 줄이 True가
        # 되어 잡이 SUCCEEDED로 잘못 끝난다. 성공/차단을 직접 센다 — `assert_never`가
        # 세 번째 outcome을 빠짐없이 처리했는지 mypy로 강제한다.
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

        # 집계가 끝났으므로 여기서 환불액이 확정된다(`_refund_unmade_images` 참조).
        # `refund_settled`를 세우는 것이 **이 지점 이후의 실패에서 아래 `except`가 두 번째
        # 환불을 하지 않게** 막는다 — 두 번 돌려주면 없던 돈이 생긴다. 돌려줄 것이 0장이어도
        # "정산은 끝났다"가 참이므로 `if` 밖에서 세운다. 환급을 기다리기 **전에** 세운다 — 환급이 커밋된 뒤 이 `await` 가
        # 돌아오기 전에 취소가 닿으면, 뒤에 세우는 쪽은 아래 `except` 가 같은 몫을 한 번 더 돌려준다.
        refund_settled = True
        await _refund_unmade_images(
            owner_user_id, charge, charge.count - succeeded_count, session_factory, job_id
        )

        blocked_count = len(blocked_reasons)
        blocked_reason: ImageBlockedReason | None = None
        if blocked_reasons:
            blocked_reason = blocked_reasons[0]
            # 사유만 남긴다 — 사용자 id·프롬프트 원문은
            # 절대 넣지 않는다.
            logger.warning("local image generation blocked: reason=%s count=%d", blocked_reason, blocked_count)
            distinct_reasons = set(blocked_reasons)
            if len(distinct_reasons) > 1:
                # 프롬프트 가드는 결정적이라 `prompt`는 한 잡 안에서
                # 다른 사유와 섞일 수 없다 — 섞이면 로컬이 계약을 어긴
                # 것이므로 조용히 넘기지 않는다. 참조 이미지는 같은 참조를 장마다 따로
                # 검사하므로 `reference`와 `image`가 섞이는 경우도 이 경고가 남긴다.
                logger.warning(
                    "local image generation blocked reasons mismatched within one job: reasons=%s",
                    sorted(distinct_reasons),
                )
            if failed_count > 0:
                # 처음 설계의 결과 판정 표는 성공/차단 수만 키로
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
                # 문법 오류·길이 초과는
                # 결정적이라 한 잡 안에서 사유가 섞일 수 없다 — 섞이면 프록시 흔들림
                # 등 계약 밖 사건이므로 위 blocked_reasons 불일치 경고와 같은 패턴으로
                # 조용히 넘기지 않는다.
                logger.warning(
                    "local image generation input errors mismatched within one job: input_errors=%s",
                    sorted(distinct_input_errors),
                )

        # 종료 상태 판정 규칙: 아래 Redis 잡 갱신과
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
            # test_generate_unexpected_error_marks_job_failed의
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
            # 문구는 FE가 조립한다 — error는 진짜 실패에만
            # 쓰고 차단에는 쓰지 않는다.
            await update_job(
                job_id,
                status=ImageGenerationJobStatus.FAILED,
                blocked_count=blocked_count,
                blocked_reason=blocked_reason,
            )
        elif input_error_count > 0:
            # 성공과 공존하는 경우는 위 succeeded_count
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
    except BaseException:
        # 차감(게이트) 이후 · 정산(`refund_settled`) 이전에 터지는
        # 구간. `update_job(RUNNING)`의 Redis 순단과 집계 루프의 `assert`가 여기 들어온다 —
        # 그동안 이 구간에는 환불할 자리가 아예 없어서 사용자가 이미지를 한 장도 못 받고
        # 클로버만 잃었다. 채팅은 같은 구간을 이미 닫았으므로(`chat/turn_settlement.py` 의 정산 가드)
        # 이미지만 열어 두면 같은 사고에 두 경로가 다르게 동작한다.
        #
        # 되돌리는 양은 정상 경로와 같은 **"진행된 만큼"**이다 — `succeeded_count`가 루프에서
        # 증가하므로 집계 도중 터져도 그 시점까지 성공한 장수는 사용자가 실제로 받았다.
        #
        # `BaseException` 이다 — 재배포·종료로 잡 태스크가 취소(`CancelledError`)돼도 못 만든 장수는 돌려준다. 취소를
        # 삼키지는 않는다: bare `raise`라 원래 예외(취소 포함)가 그대로 올라가고, `finally`가 그 뒤에 돌아 admission
        # 반납도 그대로다. 잡은 asyncio 태스크라 취소가 한 번 전달되고 끝나므로, 이 블록의 `await` 는 다시 취소되지 않는다.
        if not refund_settled:
            await _refund_unmade_images(
                owner_user_id, charge, charge.count - succeeded_count, session_factory, job_id
            )
        raise
    finally:
        heartbeat.cancel()
        await release_admission(redis_client, admission)


def _style_items(served_style_ids: tuple[str, ...]) -> list[ImageStyleItem]:
    """style 축의 공개 id와 와이어 id가
    같아 매핑 없이 원소별로 판정한다. 레지스트리 전체를 항상 내리고, 로컬이
    보고한 집합에 있는 것만 available=true로 표시한다. (이전 `_known_styles`는 로컬
    보고값으로 **걸렀다** — 그러면 준비 중 스타일이 응답에서 사라져 "없는 것"과
    구분되지 않는다.)

    `served`를 bool이 아니라 집합으로 두는 것 자체가 방어다 — bool로 두면 `and`로
    잇고 싶어지고, 그 순간 "하나라도 서빙되면 전부 available" 버그가 열린다(이
    함수가 레지스트리 전체를 내리게 바뀌었을 때 모델의 `available=bool(styles)`가
    항진명제가 되며 이미 한 번 이 함정에 물렸다).
    """
    served = set(served_style_ids)
    return [
        ImageStyleItem(id=spec.id, name=spec.name, available=spec.id in served)
        for spec in IMAGE_STYLE_PRESETS
    ]


# 로컬이 보고하는 aspect_ratio는 (JSON을 거쳐 온) 평범한 str이라 `AspectRatio` Literal로
# 정적으로 좁혀지지 않는다 — dict 조회로 좁히고, 서버가 모르는 값은 무시한다. (`_style_items`는
# 이 규칙을 쓰지 않는다 — 레지스트리 전체를 항상 내리고
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
    db: AsyncSession = Depends(get_db_session),
) -> list[ImageModelItem]:
    """생성에 쓸 수 있는 모델 + 각 모델이 지원하는 종횡비/스타일. 정적 레지스트리(불투명
    id + 표시명)와 집 PC의 capabilities(가용성 + 지원 목록)를 교차한다.
    로컬이 안 준 정적 id는 불가로 내리고, 서버가 모르는 로컬 id는
    무시한다 — 불일치는 조용한 기능 축소로 나타나므로 WARNING으로 남긴다.

    로컬은 공개 id가 아니라 **와이어** id를
    보고한다 — 조회 키를 와이어 id로 바꾸지 않으면 이 교차가 항상 실패한다.

    `available`은 capability 존재 여부가 아니라 "실제로 생성 가능"을 뜻해야 한다 —
    매핑된 style이 하나도 없으면 capability가 있어도 false다(이 경우도 WARNING).

    `db` 는 인증 의존성과 같은 요청 세션이다 — 그 조회가 연 트랜잭션을 집 PC 조회(캐시가 비면 최대 5초) 전에 닫아
    커넥션을 쥐지 않으려고 받는다."""
    await db.commit()
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
                    id=spec.id,
                    name=spec.name,
                    supported_aspect_ratios=[],
                    available=False,
                    styles=[],
                    supports_reference_image=False,
                )
            )
            continue
        styles = _style_items(capability.styles)
        # `_style_items`가 레지스트리 전체(항상
        # 7개)를 내리면서 `bool(styles)`는 항진명제가 됐다 — styles가 비는 경우가
        # 없어져 이 조건이 늘 True였다. `available`의 뜻("실제로 생성 가능")을 지키려면
        # available 플래그로 직접 물어야 한다.
        if not any(style.available for style in styles):
            # capability는 있지만 매핑되는 style이 하나도 없다 — id 불일치(위)와는
            # 다른 조용한 기능 축소라 구분되는 문구로 남긴다.
            logger.warning("local image capability for registered model id %s maps to no usable style", spec.id)
        available = any(style.available for style in styles)
        items.append(
            ImageModelItem(
                id=spec.id,
                name=spec.name,
                supported_aspect_ratios=_known_aspect_ratios(capability.aspect_ratios),
                available=available,
                styles=styles,
                supports_reference_image=settings.local_image_reference_enabled and available,
            )
        )
    return items


async def _resolve_reference_storage_key(
    reference_asset_id: uuid.UUID | None,
    owner_user_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
) -> str | None:
    """참조가 없으면 None. 있으면 기능이 켜져 있는지(요청마다 다시 본다 — 모델 목록을 받은 뒤
    꺼졌을 수 있다)와 그 asset이 본인의 완성된 생성 이미지인지 확인하고 저장 키를 돌려준다.

    꺼져 있는데 참조가 오면 무시하지 않고 400이다 — 무시하면 참조 없이 만든 이미지가 과금돼 나간다.
    없음·남의 것·생성 이미지 아님(업로드·크롭)은 전부 같은 404다 — 남의 asset이 있는지 드러내지
    않는다(생성 이미지 삭제와 같은 규칙). FE는 두 `detail` 문자열로 안내를 가른다."""
    if reference_asset_id is None:
        return None
    if not settings.local_image_reference_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="reference image disabled")
    async with session_factory() as session:
        storage_key = await session.scalar(
            select(Asset.storage_key).where(
                Asset.id == reference_asset_id,
                Asset.owner_user_id == owner_user_id,
                Asset.kind == AssetKind.GENERATED,
                Asset.status == AssetStatus.READY,
            )
        )
    if storage_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="reference image not found")
    return storage_key


@router.post(
    "/generate", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_legal_consent)]
)
async def generate_images(
    payload: GenerateImageRequest,
    owner_user_id: uuid.UUID = Depends(get_current_user_id),
    # 토큰 차감은 라우트 본문이 아니라 이 `Depends` 자리에서
    # 일어난다(`require_legal_consent` 뒤 — 재동의 403이 429보다 먼저다). 게이트가 라우트와
    # 같은 바디 모델을 선언해 장수(`count`)만큼 깎고, 그 영수증이 아래 환불의 근거가 된다.
    charge: ImageCharge = Depends(enforce_image_rate_limit),
    image_client_factory: Callable[[ImageModelId], ImageClient] = Depends(get_image_client),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
    # 인증·게이트 의존성과 같은 요청 세션. 그 조회들이 연 트랜잭션을 집 PC 조회 전에 닫으려고 받는다.
    db: AsyncSession = Depends(get_db_session),
) -> GenerateImageResponse:
    # 토큰은 잡이 실제로 생성(202)될 때만 소모된다 — 차감 이후 202 이전에
    # 끝나는 경로는 예외 종류를 가리지 않고 **전부** 환불한다(큐 가득·가용성 503·비율/스타일
    # 400, 그리고 `create_job`/`session.commit()`의 500).
    # 한 종류만 환불하면 나머지 경로에서 생성되지도 않은 이미지가 사용자의 상한에서 사라진다.
    try:
        # 가용성 사전 확인을 맨 앞에 둔다 — 불가면 503,
        # 일시적 상태이고 클라이언트 잘못이 아니다. capabilities 전체가 불가이거나, 요청한
        # 모델이 로컬이 지금 보고하지 않는 모델이면 둘 다 같은 503으로 접는다.
        #
        # 로컬은 공개 id(`payload.model`)가 아니라 와이어 id를 보고한다 — 조회 키를
        # 와이어 id로 바꾸지 않으면 이 확인이 항상 실패해 모든 생성이 503으로 막힌다.
        #
        # 집 PC 조회(캐시가 비면 최대 5초) 전에 의존성들의 조회 트랜잭션을 닫아 커넥션을 돌려준다(롤백은 세션의 객체를
        # 만료시켜 쓰지 않는다). 커밋 실패도 이미 깎은 토큰·클로버를 돌려받도록 바깥 `try` 안에 둔다.
        await db.commit()
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
        # 레지스트리 기준으로 판정한다 — `_style_items`가
        # 요청된 스타일이 레지스트리에 있는지와 지금 서빙되고 있는지(available)를 함께 본다.
        # style 축은 공개 id와 와이어 id가 같아
        # capability.styles를 매핑 없이 그대로 집합 비교한다. 사용자에게 보이는 detail은
        # 공개 값(`payload.style.value`)을 그대로 쓴다.
        style_items = _style_items(capability.styles)
        if not any(item.available and item.id == payload.style.value for item in style_items):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"model '{payload.model}' does not support style '{payload.style.value}'",
            )

        # 참조 거절 둘(기능 꺼짐 400, 쓸 수 없는 참조 404)도 이 바깥 `try` 안에 있어야 한다 — 게이트가
        # 이미 차감했으므로 밖(`Depends`·바디 검증)으로 빼면 차감만 남고 환불되지 않는다.
        # 저장소 왕복은 여기서 하지 않는다(요청이 커넥션을 쥔 채 기다리게 된다) — 잡에는 저장 키만
        # 넘기고 원본은 장마다 잡 안에서 읽는다.
        reference_storage_key = await _resolve_reference_storage_key(
            payload.reference_asset_id, owner_user_id, session_factory
        )

        # 검사+추가가 `try_admit()` 안의 Redis 스크립트 한 번이라
        # 다른 요청(다른 워커 포함)이 그 사이에 끼어들 수 없다 — 상한이 걸렸는데도 거절하지
        # 않으면 한 사용자가 GPU 직렬 처리량을 몇 분씩 독점한다. 검사는 전역 상한 +
        # 유저별 1칸 둘이고, 429 바디는 유저 상한 429와 `code`로만 갈린다.
        #
        # Redis 를 못 쓰면 칸을 셀 수 없으므로 거절한다(503). 채팅 레이트리밋은 Redis 장애 때
        # 통과시키지만(fail-open) 여기서 통과시키면 워커마다 집 PC 를 부르는 잡이 무제한으로 쌓인다
        # — 집 PC 보호가 우선이다. 바깥 `except` 가 이미 깎은 토큰·클로버를 돌려준다.
        try:
            admission = await try_admit(redis_client, owner_user_id)
        except RedisError as exc:
            logger.warning("image generation admission unavailable: %s", type(exc).__name__)
            capture_dependency_failure(exc, dependency="redis")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Image generation is currently unavailable"
            ) from exc
        if admission is None:
            raise image_queue_full(owner_user_id)

        try:
            image_client = image_client_factory(payload.model)
            job = await create_job(owner_user_id, payload.count)
            # 접수 시 INSERT — 프롬프트·모델·비율·스타일이
            # 전부 모여 있는 유일한 지점이 여기다. `create_job` 성공 뒤·`enqueue_generation` 앞에
            # 둔다: 더 앞에 두면 429/503 사전 차단 경로에도 행이 생기고, asset의 FK 때문에
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
                    reference_asset_id=payload.reference_asset_id,
                )
                session.add(request_row)
                await session.commit()
            await enqueue_generation(
                _run_generation,
                job.job_id,
                owner_user_id,
                admission,
                request_row.id,
                image_client,
                session_factory,
                payload.prompt,
                payload.style,
                payload.aspect_ratio,
                # `charge.count`가 곧 `payload.count`다(게이트가 네 분기 전부 그렇게 만든다).
                # 영수증을 통째로 넘기는 이유는 202 이후 환불이 **무엇으로 냈는지**를 알아야
                # 하기 때문이다 — 장수만 넘기면 자원을 못 가린다.
                charge,
                # 바이트가 아니라 저장 키다 — 잡 인자는 직렬화 가능한 값으로 둔다(잡 실행을 외부
                # 큐로 바꿀 때 그대로 넘어가게).
                reference_storage_key,
            )
        except Exception:
            # admit과 백그라운드 인계 사이(예: `create_job`의 Redis 순단)에서 실패하면
            # `_run_generation`이 아예 시작되지 않아 그쪽의 finally가 못 돈다 — 여기서
            # 직접 반납하지 않으면 이 슬롯이 영구 점유돼 상한에서 게이트가 막힌다.
            await release_admission(redis_client, admission)
            raise
    except Exception:
        # 안쪽 `except Exception`(반납)보다 바깥이다 — 반납과 환불은 서로 다른 자원이고,
        # 잡 인계 도중의 실패는 둘 다 필요하다. 환불은 차감이 실제로 있었을 때만 동작한다
        # (`ImageCharge.source`) — 예외 계정·Redis fail-open은 no-op이다.
        # `HTTPException`만 잡으면 `create_job`(Redis)·`session.commit()`(Postgres)의 500에서
        # 토큰이 유실돼 DB 순단 뒤 최대 10시간 429가 이어진다(리뷰 실측).
        # `session_factory`를 넘기는 이유는 클로버로 낸 요청의 환불이 별도 트랜잭션이기
        # 때문이다.
        await refund_image_charge(owner_user_id, charge, session_factory)
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
