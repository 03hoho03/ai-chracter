"""소설화 과금 — 작업 생성과 함께 하는 선차감, 실패 확정 때의 단일 환불, 작업 상태의 조건부 전이.

채팅 게이트(`core/rate_limit_gate.py`)를 쓰지 않는다. 그쪽은 SSE 라우트라 `Depends` 안에서 자기 트랜잭션으로
차감하지만, 소설화는 202 JSON 이라 라우트 본문에서 예외를 내도 안전하고, 차감이 작업 행 생성과 같은 트랜잭션이어야
한다(차감만 남고 작업이 없거나 그 반대가 생기지 않게). 그래서 요청 세션 하나에 얹는다. 면제 계정 분기도 없다 — 채팅·
이미지 상한을 면제받는 운영 계정도 소설화는 똑같이 낸다.

**락 순서는 모든 경로에서 users → novel_jobs → clover_lots 다.** 작업 생성·환불·소설 삭제·탈퇴가 모두 사용자 행을
먼저 잠그므로 한 사용자의 이 경로들은 사용자 행에서 줄을 선다. 그 덕에 "진행 중 작업이 있나"·"오늘 몇 번 했나"를
사용자 잠금 아래에서 읽으면 다른 요청이 그 사이에 작업을 끼워 넣을 수 없다. 예외로 성공 저장은 사용자 행 없이 작업 행 →
소설 행 순서로 잠근다 — 그래서 소설 삭제는 소설 행을 먼저 잠그면 안 된다(삭제는 소설 행을 쥔 채 작업 행을, 성공 저장은
작업 행을 쥔 채 소설 행을 기다려 교착이 된다).

**상태 전이는 전부 조건부 UPDATE 다**(`transition_job`). 만료 정리와 정상 종료가 같은 작업을 동시에 끝내려 해도 조건
(지금 상태)에 맞는 쪽 하나만 행을 받고, 받지 못한 쪽은 아무것도 하지 않는다 — 환불이 두 번 나가거나 이미 환불된
작업에 장이 저장되지 않는 이유가 이것 하나다."""

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, time
from typing import Any, assert_never

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clover
from api.core.config import settings
from api.core.rate_limit import KST, seconds_until_kst_midnight
from api.core.rate_limit_gate import _too_many_requests
from api.db.models.auth import User
from api.db.models.novel import Novel, NovelChapter, NovelJob, NovelJobFailureCode, NovelJobKind, NovelJobStatus
from api.llm.chat_models import DEFAULT_CHAT_MODEL, ChatModelId, novel_chapter_cost, parse_chat_model_id

ACTIVE_JOB_STATUSES: tuple[NovelJobStatus, ...] = ("queued", "running")
# 하루 상한에 세는 상태. 환불된 실패를 세면 우리 쪽 실패가 사용자의 하루 기회를 깎는다.
_COUNTED_JOB_STATUSES: tuple[NovelJobStatus, ...] = ("queued", "running", "succeeded")
_CHAPTER_JOB_KINDS: tuple[NovelJobKind, ...] = ("chapter_generate", "chapter_regenerate")

_NOVELIZE_WINDOW = "novelize"


def job_price(kind: NovelJobKind, model: ChatModelId = DEFAULT_CHAT_MODEL) -> int:
    """작업 한 번의 클로버 단가. 장 생성·재생성은 고른 글쓰기 모델의 장 가격이고, AI 수정은 모델과 무관하다(언제나
    Gemini 로 돈다). 단가 상수를 부를 때마다 모듈 전역으로 읽는다 — 값을 붙잡아 두면 테스트가 바꿀 수 없고, 화면에
    금액을 내려주는 응답도 이 함수 하나에서 읽어야 차감액과 어긋나지 않는다."""
    if kind == "chapter_generate":
        return novel_chapter_cost(model, regenerate=False)
    if kind == "chapter_regenerate":
        return novel_chapter_cost(model, regenerate=True)
    if kind == "ai_edit":
        return clover.NOVELIZE_AI_EDIT_COST
    if kind == "chain_generate":
        # 연쇄 부모의 금액은 남은 대화의 묶음 수에 달려 작업 종류만으로 정해지지 않는다 — 부모 전용 계산이 따로 한다.
        raise ValueError("chain_generate 의 금액은 job_price 로 계산하지 않는다")
    assert_never(kind)


def chapter_job_model(job: NovelJob) -> ChatModelId:
    """장 작업에 적힌 모델을 레지스트리 id 로 읽는다. 빈 값은 모델 칸이 생기기 전의 작업이라 기본 모델이다. 레지스트리
    밖 값(작업이 도는 사이 배포로 모델을 내렸다)은 예외다 — 값을 낸 모델로 쓸 수 없는데 기본 모델로 바꿔 쓰면 다른
    모델의 글을 받게 되므로, 실행 경로가 실패·환불로 끝낸다. 허용은 여기서 보지 않는다(과금할 때 판정했다)."""
    if job.model is None:
        return DEFAULT_CHAT_MODEL
    model = parse_chat_model_id(job.model)
    if model is None:
        raise ValueError(f"소설화 작업 {job.id} 의 모델이 레지스트리에 없다: {job.model}")
    return model


async def _lock_user(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """사용자 행을 `FOR NO KEY UPDATE` 로 잠근다. 작업 행 INSERT 가 FK 로 거는 `KEY SHARE` 와는 부딪히지 않고, 같은
    사용자의 다른 과금 경로(작업 생성·환불·클로버 차감의 UPDATE)와는 부딪혀 줄을 세운다. 행이 없으면 False."""
    locked = await db.scalar(select(User.id).where(User.id == user_id).with_for_update(key_share=True))
    return locked is not None


async def _starts_after_last_chapter(db: AsyncSession, job: NovelJob) -> bool:
    """장 생성 작업의 시작이 지금 마지막 장의 끝보다 뒤인가. 라우트는 다음 장 시작을 잠금 전에 정하므로, 그 사이 앞
    작업이 같은 구간으로 장을 저장했으면 이 작업은 이미 장이 된 구간을 다시 만든다. 사용자 잠금 뒤에 다시 본다 —
    결과 저장은 사용자 행을 잡지 않지만, 잠금을 얻은 뒤의 조회는 그때까지 커밋된 장을 본다."""
    assert job.start_message_created_at is not None and job.start_message_id is not None
    last_end = (
        await db.execute(
            select(NovelChapter.end_message_created_at, NovelChapter.end_message_id)
            .where(NovelChapter.novel_id == job.novel_id)
            .order_by(NovelChapter.ordinal.desc())
            .limit(1)
        )
    ).first()
    return last_end is None or tuple(last_end) < (job.start_message_created_at, job.start_message_id)


async def create_charged_job(db: AsyncSession, *, job: NovelJob, expected_cost: int, now: datetime) -> NovelJob:
    """요청 세션 `db` 에서 `job` 을 진행 대기(`queued`)로 넣고 단가만큼 차감한 뒤 커밋한다. 넣은 작업을 돌려준다.

    `job` 은 호출자가 종류·소설·사용자와 입력(구간 또는 문단 범위)을 채운 새 행이다. 상태·차감액·heartbeat 는 여기서
    채운다. 소유·작품 상태·원문 해시처럼 요청 자체를 거절하는 판정은 이 함수를 부르기 **전에** 끝낸다 — 거절된 요청은
    원장에 아무것도 남기지 않는다. 부르기 전에 쓴 것이 있으면 먼저 커밋해 둔다: 거절할 때 이 함수가 롤백한다.

    거절은 모두 `HTTPException` 이다(라우트 본문이 그대로 내보낸다).
    - 404 `NOVEL_NOT_FOUND`·`NOVEL_CHAPTER_NOT_FOUND`: 사용자 잠금을 기다리는 사이 소설이나 작업이 가리키는 장이
      지워졌다.
    - 409 `NOVEL_NOTHING_NEW`(장 생성만): 사용자 잠금을 기다리는 사이 앞 작업이 이 작업의 시작을 덮는 장을 저장했다
      (두 탭에서 동시에 다음 장을 만든 경우). 화면은 경계 제안을 다시 받는다.
    - 409 `NOVELIZE_PRICE_CHANGED` + `currentCost`: 사용자가 확인한 금액(`expected_cost`)이 지금 단가와 다르다. 단가가
      배포로 바뀌는 사이 열어 둔 확인 화면의 금액으로 차감하지 않으려는 것이다. 장 작업의 단가는 작업에 적힌 모델의
      가격이다(`job.model`, 허용 판정은 호출자가 먼저 한다). DB 를 건드리기 전에 판정한다.
    - 409 `NOVEL_JOB_IN_PROGRESS`: 이 소설에 진행 중(대기·실행) 작업이 있다.
    - 429 `USER_LIMIT`(`window: "novelize"`): 같은 시작 메시지의 장 생성·재생성이 오늘(KST) 상한에 닿았다. 재시도 초는
      상한이 풀리는 KST 자정까지다.
    - 429 `CLOVER_REQUIRED`(`window: "novelize"`): 잔액 부족. 이 경우 참인 재시도 시각은 없지만, 클로버가 다시 생기는
      가장 이른 정기 시점이 출석이 다시 열리는 KST 자정이라 그때까지의 초를 싣는다.

    순서는 단가 확인 → 사용자 잠금 → 소설·장 존재 확인 → 다음 장 시작 재확인(장 생성만) → 진행 중 확인 → 하루 상한 → 작업 INSERT → 차감(clover_lots 잠금)이다. 진행 중
    확인과 상한을 사용자 잠금 뒤에 읽으므로 같은 사용자의 동시 요청이 둘 다 통과하지 못한다(부분 유니크 인덱스는
    마지막 방어선으로 남는다)."""
    price = job_price(job.kind, chapter_job_model(job))
    if expected_cost != price:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "NOVELIZE_PRICE_CHANGED", "currentCost": price},
        )

    if not await _lock_user(db, job.user_id):
        # 인증을 통과한 요청이라 도달할 수 없다. 도달했다면 500 이 맞다.
        raise ValueError(f"소설화 작업을 만들 사용자를 찾지 못했다: {job.user_id}")

    # 라우트는 소설·장을 잠금 없이 읽고 들어온다. 그 뒤 소설 삭제나 마지막 장 삭제가 사용자 행을 쥔 채 지우고 커밋하면,
    # 여기서 기다리던 요청이 지워진 행을 가리키는 작업을 넣다가 FK 위반(500)이 난다. 지우는 경로가 모두 사용자 행을
    # 먼저 잡으므로 잠금을 얻은 뒤의 조회는 커밋된 삭제를 보고, 잠금을 쥔 동안에는 새 삭제가 끼어들 수 없다. AI 수정의
    # 기준 개정은 장과 함께만 지워지므로 장 확인 하나로 덮인다.
    if await db.scalar(select(Novel.id).where(Novel.id == job.novel_id)) is None:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "NOVEL_NOT_FOUND"})
    if (
        job.chapter_id is not None
        and await db.scalar(select(NovelChapter.id).where(NovelChapter.id == job.chapter_id)) is None
    ):
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "NOVEL_CHAPTER_NOT_FOUND"})
    if job.kind == "chapter_generate" and not await _starts_after_last_chapter(db, job):
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "NOVEL_NOTHING_NEW"})

    active = await db.scalar(
        select(NovelJob.id).where(NovelJob.novel_id == job.novel_id, NovelJob.status.in_(ACTIVE_JOB_STATUSES)).limit(1)
    )
    if active is not None:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "NOVEL_JOB_IN_PROGRESS"})

    if job.kind in _CHAPTER_JOB_KINDS:
        today_start = datetime.combine(clover.kst_today(now), time.min, tzinfo=KST)
        attempts = await db.scalar(
            select(func.count())
            .select_from(NovelJob)
            .where(
                NovelJob.novel_id == job.novel_id,
                NovelJob.start_message_id == job.start_message_id,
                NovelJob.kind.in_(_CHAPTER_JOB_KINDS),
                NovelJob.status.in_(_COUNTED_JOB_STATUSES),
                NovelJob.created_at >= today_start,
            )
        )
        if (attempts or 0) >= settings.novelize_chapter_daily_limit:
            await db.rollback()
            raise _too_many_requests(job.user_id, _NOVELIZE_WINDOW, seconds_until_kst_midnight(now))

    job.status = "queued"
    job.charged_amount = price
    # 만료 정리가 DB 시계로 비교하므로 앱 시계가 아니라 DB 시각을 넣는다.
    job.heartbeat_at = await db.scalar(select(func.now()))
    db.add(job)
    await db.flush()

    if await clover.spend(db, user_id=job.user_id, amount=price, kind="novelize_spend") is None:
        await db.rollback()
        raise _too_many_requests(job.user_id, _NOVELIZE_WINDOW, seconds_until_kst_midnight(now), code="CLOVER_REQUIRED")

    await db.commit()
    return job


async def transition_job(
    db: AsyncSession, *, job_id: uuid.UUID, expected: Sequence[NovelJobStatus], values: Mapping[str, Any]
) -> int | None:
    """작업 상태가 `expected` 중 하나일 때만 `values` 를 쓴다. 바뀌었으면 그 작업의 차감액을, 조건이 맞지 않았으면
    (이미 다른 경로가 끝냈거나 작업이 지워졌으면) `None` 을 돌려준다. 커밋은 호출자가 한다.

    작업을 끝내는 쪽은 저장보다 이 전이를 **먼저** 한다 — 성공이면 `running → succeeded` 가 행을 받은 뒤에야 장·개정을
    넣고, 받지 못하면 결과를 버린다. 그래야 만료 정리가 먼저 실패·환불한 작업에 장이 저장되지 않고, 소설 삭제가 먼저
    작업 행을 지웠을 때 지워진 소설에 장을 넣으려다 FK 위반이 나지 않는다."""
    return await db.scalar(
        update(NovelJob)
        .where(NovelJob.id == job_id, NovelJob.status.in_(expected))
        .values(**values)
        .returning(NovelJob.charged_amount)
    )


async def refund_job(db: AsyncSession, *, job_id: uuid.UUID, failure_code: NovelJobFailureCode) -> int | None:
    """진행 중(대기·실행) 작업을 실패로 확정하고 차감액을 돌려준다. 환불한 금액을, 이미 끝났거나 없는 작업이면 `None`
    을 돌려준다. 커밋은 호출자가 하고, 소설 삭제처럼 같은 트랜잭션에서 더 할 일이 없으면 곧바로 커밋한다.

    실행 경로의 실패 처리·만료 정리·소설 삭제가 모두 이 함수 하나를 쓴다. 순서: 작업의 사용자를 락 없이 읽고 → 사용자
    행 잠금 → 조건부 전이(실패·사유·`refunded_at`) → 행을 받았을 때만 지급. 전이·지급·`refunded_at` 이 한 트랜잭션이라
    커밋이 실패하면 셋 다 없던 일이 되고 작업은 진행 중으로 남는다 — heartbeat 가 멈춘 그 작업을 만료 정리가 다시 이
    함수로 환불한다. 그래서 채팅의 `refund_in_new_transaction`(실패를 삼키고 재시도가 없다)을 쓰지 않는다.

    같은 전이에서 AI 수정의 지시문·결과 본문을 비운다. 실패한 수정은 적용할 결과가 없어 사용자가 쓴 지시문을 보관할
    이유가 없다. 행은 남긴다(차감 기록의 짝). 장 생성·재생성 작업은 두 칸을 쓰지 않아 늘 NULL 이라 종류를 가리지 않는다.

    탈퇴나 소설 삭제로 작업 행이 먼저 지워졌으면 아무것도 하지 않는다 — 탈퇴는 잔액을 통째로 소멸시키므로 뒤늦은
    환불이 그 뒤에 잔액을 되살리면 안 된다."""
    user_id = await db.scalar(select(NovelJob.user_id).where(NovelJob.id == job_id))
    # 단일 환불만 보면 아래 조건부 전이로 충분해 보이지만, 사용자 행을 먼저 잡는 것은 탈퇴와의 교착을 막기 위해서다.
    # 탈퇴는 사용자 행을 잡은 뒤 작업 행을 지운다. 여기서 작업 행부터 바꾸고 지급 때 사용자 행을 잡으면 두 경로가
    # 서로의 행을 기다려 한쪽이 교착 오류로 끊긴다(탈퇴 요청이면 500).
    if user_id is None or not await _lock_user(db, user_id):
        return None
    refunded = await transition_job(
        db,
        job_id=job_id,
        expected=ACTIVE_JOB_STATUSES,
        values={
            "status": "failed",
            "failure_code": failure_code,
            "refunded_at": func.now(),
            "finished_at": func.now(),
            "instruction": None,
            "result_text": None,
        },
    )
    if refunded is None:
        return None
    if refunded > 0:
        await clover.grant(db, user_id=user_id, amount=refunded, kind="novelize_refund")
    return refunded


async def refund_active_jobs(db: AsyncSession, *, novel_id: uuid.UUID, failure_code: NovelJobFailureCode) -> int:
    """소설의 진행 중 작업을 모두 환불하고 환불 합계를 돌려준다. 소설을 지우기 직전, 같은 트랜잭션에서 부른다(커밋은
    호출자) — 지우고 나면 그 작업은 실행 경로가 실패해도 환불할 행이 없다."""
    job_ids = (
        await db.scalars(
            select(NovelJob.id).where(NovelJob.novel_id == novel_id, NovelJob.status.in_(ACTIVE_JOB_STATUSES))
        )
    ).all()
    total = 0
    for job_id in job_ids:
        total += await refund_job(db, job_id=job_id, failure_code=failure_code) or 0
    return total
