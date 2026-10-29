"""클로버(재화) 서비스 — 잔액 판정과 원장 기록.

`core/`에 두는 이유는 게이트(`core/rate_limit_gate.py`)가 이걸 부르기 때문이다. HTTP 표면은
별도 패키지(`clover/router.py`)로 가른다.

**불변식은 `users.clover_balance`의 조건부 UPDATE 하나다**. 원장은
같은 트랜잭션에 얹는 기록이지 판정 근거가 아니다 — 순서를 뒤집어 원장을 먼저 INSERT하고 잔액을
`SUM()`으로 계산하면 동시 트랜잭션 둘이 서로의 미커밋 행을 못 봐서 **둘 다 통과한다**.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal, get_args

import anyio
from fastapi import HTTPException, status
from sqlalchemy import Integer, Uuid, case, false, func, insert, literal, literal_column, select, update
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core.config import settings
from api.core.rate_limit import KST
from api.core.sentry import capture_dependency_failure
from api.db.models.auth import User
from api.db.models.clover import (
    CloverLedger,
    CloverLot,
    CloverSpendAllocation,
    CloverSpendRefund,
    CloverSpendUsage,
    CloverSpendUsageKind,
)
from api.db.models.content import Content
from api.db.models.payment import Payment
from api.llm.backends import ChatModelId

logger = logging.getLogger(__name__)

# 아래 단가 주석의 원가 환산 기준: 1달러 1,400원, 1클로버 1원(`CLOVER_UNIT_KRW`). 판매 1원에서 부가세 10%와 PG 수수료
# 3.2%(수수료 부가세 포함 3.52%)를 빼면 0.874원, 남의 작품 유료 사용분에 붙는 원작자 몫 5%(공급가액 기준)까지 빼면 0.828원이라
# 1클로버로 원가에 쓸 수 있는 돈은 약 0.83원이다(보너스 없는 상품 기준 — 보너스 20% 상품에서는 0.828 ÷ 1.2 = 약 0.69원).
# 아래 "쓸 수 있는 돈"은 모두 단가 × 0.828 이다.
# 가격을 쓰는 함수는 아래 등록부와 상수를 **호출 시점에 이 모듈에서** 읽는다 — 기본 인자로 캡처하거나 다른 모듈에 사본을 두면
# 값을 바꿔도(테스트의 `monkeypatch` 포함) 따라오지 않는다(`core/rate_limit.py`의 상한 상수와 같은 규칙).


@dataclass(frozen=True)
class ModelPrices:
    """글쓰기 모델 하나의 클로버 단가 한 행. 이 행을 모델 id 로 모은 `CLOVER_MODEL_PRICES` 가 모델별 가격 등록부이고, 모델별 가격을
    내는 함수(`llm/chat_models.py` 의 `chat_turn_cost`·`novel_episode_unit_price`·`novel_outline_unit_price`·
    `novel_episode_outline_unit_price`)는 호출 때마다 이 표에서 읽는다. 모델과 무관한 기능 단가(이미지·AI 문단 수정·노벨 화
    소장·요약 다시 만들기)는 표 밖의 모듈 상수다.

    새 글쓰기 모델의 행을 더하는 법: 글쓰기 모델 타입(`llm/backends.py` 의 `ChatModelId`)에 id 를 더하면 이 표에 그 행이 없어
    import 가 멈춘다. 그 id 로 한 행을 더하고, 가격이 하나라도 바뀐 것이므로 `PRICE_VERSION` 을 1 올리고, 정한 값을
    `tests/test_core_clover.py` 의 정책 상수 테스트 한 곳에 적는다."""

    # 채팅 턴 하나(새 턴·재생성·수정).
    chat_turn: int
    # 소설 화 하나. 생성 한 번은 묶음 하나를 여러 화로 쓰고 화 수 × 화 단가를 낸다. 다시 만들기도 같은 호출이라 같은 화 단가이고,
    # 구성 흐름의 원고(승인한 장면 구성안으로 쓰는 화 하나)도 이 값이다.
    novel_episode: int
    # 구성 흐름의 전체 구성안 한 번과 화 하나의 장면 구성안 한 번 — 화 수와 무관한 모델별 고정가. 구성 흐름 스위치
    # (`NOVELIZE_OUTLINE_FLOW_ENABLED`)가 꺼져 있는 동안은 이 두 값으로 차감하는 경로가 없다.
    novel_outline: int
    novel_episode_outline: int


# 소설 단가(화·전체 구성안·장면 구성안·AI 문단 수정)는 1클로버 = 3원일 때 정한 값을 1원 단위로 옮기며 세 배 한 것이라 원화
# 가격과 원가 대비 비율이 그대로다. 채팅 턴 단가만 1원 단위에서 새로 정했다(아래 행 주석).
# 소설 화 Sonnet 540·Opus 900 은 실측이 없는 추정이다 — 짧은 연결 시험에서 잰 Opus 출력 토큰/글자 비로 출력 길이를 어림하고
# 입력 길이는 가정해 원가를 Sonnet 약 218~301원·Opus 약 363~501원으로 보면, 쓸 수 있는 돈(Sonnet 540 × 0.828 = 약 447원,
# Opus 900 × 0.828 = 약 745원)의 약 49~67%다.
# 전체 구성안 570·990·2,070 은 입력 상한 길이의 원가로 정했다. 고른 대화 길이와 무관한 고정가라 가장 긴 입력이 값을 정한다 — 입력
# 상한(`novelize_outline_max_input_tokens`, 14만 자) 길이의 원가가 쓸 수 있는 돈의 67% 안에 들게 3원 단위에서 고른 가장 작은 10
# 단위 값(190·330·690)의 세 배다. 상한 길이 원가(2027년 정가 기준)는 Gemini 약 $0.214(약 300원)·Sonnet 약 $0.384(약 538원)·
# Opus 약 $0.815(약 1,141원)이고, 쓸 수 있는 돈(약 472원·약 820원·약 1,715원)의 약 63%·66%·67%다. 상한 길이의 방은 화가
# 많아(상한에 가까운 견적 139,740자 방에서 22화) 짧은 방보다 출력이 훨씬 크다 — 그 방에서 잰 Gemini 구성안 원가 $0.2135(약
# 299원)는 출력을 여러 길이의 중앙값으로 쳐서 정했던 예전 값(1원 단위로 420)으로는 쓸 수 있는 돈(약 348원)의 86% 였다. Claude
# 두 값은 상한 길이에서 재지 않았고, 긴 방에서 잰 화당 출력·사고 토큰에 22화를 곱해 외삽했다. 입력 상한을 올리면 이 값도 다시
# 계산한다.
# 장면 구성안 240·540·900 은 같은 모델의 화 단가와 같게 둔 값이다. 잰 원가(p90)가 셋 다 쓸 수 있는 돈의 50% 안에 들어 그대로
# 둔다. 전체 구성안과 달리 상한 길이 원가로 정한 값이 아니다 — 상한에 가까운 아주 긴 화의 원가는 아직 재지 않았다.
CLOVER_MODEL_PRICES: dict[ChatModelId, ModelPrices] = {
    # 채팅 턴 20(20원 — 3원 단위의 10클로버 30원에서 내린 값): 조감독 작품 111턴 시뮬레이션에서 생성·칸 판정·스탯·요약·엔딩을
    # 모두 합쳐 턴당 약 $0.0047(약 6.5원)이라 원가는 쓸 수 있는 돈(20 × 0.828 = 약 16.6원)의 약 39%다. 방 하나·시뮬레이터
    # 사용자의 값이라 실사용 분포는 아직 모른다.
    # 화 240: 운영에서 기본 모델 소설화 호출 다섯 번의 평균 토큰을 이 모델의 2027년 인상 후 단가로 계산하면 호출 하나에 약 78원이고
    # 장 경계 제안 약 4.6원을 더해 약 83원이다 — 쓸 수 있는 돈(240 × 0.828 = 약 199원)의 약 42%. 집계가 호출 하나가 낸 화 수를
    # 모르는 호출당 값이라 묶음이 여러 화를 내면 화당 원가는 더 낮고, 표본이 다섯 번뿐이며 사고 토큰이 보고되지 않았을 수 있다.
    "gemini": ModelPrices(chat_turn=20, novel_episode=240, novel_outline=570, novel_episode_outline=240),
    # Sonnet 턴 110: 조감독 작품 긴 방에서 잰 Sonnet 턴 원가는 캐시 적중 $0.018(약 25원)·미적중 $0.0796(약 111원)이다. 쓸 수 있는
    # 돈(110 × 0.828 = 약 91원)에 적중 턴은 들고 미적중 턴은 넘는다. Sonnet 은 지금 채팅에서 고를 수 없어 이 값으로 차감하는 경로가
    # 없다 — 채팅에 다시 열 때 미적중 비율과 함께 다시 본다(소설 Sonnet 화는 이 행의 화 단가를 쓴다).
    "sonnet": ModelPrices(chat_turn=110, novel_episode=540, novel_outline=990, novel_episode_outline=540),
    # Opus 턴 200(200원 — 3원 단위의 200클로버 600원에서 내린 값): 운영에서 잰 Opus 5.5 채팅 턴 원가(생성과 판정 몫 포함,
    # 백그라운드 요약·추출 제외)는 캐시가 맞을 때 평균 약 45원, 캐시를 놓친 턴 평균 약 175원, 관측 최대 약 343원이다. 쓸 수 있는
    # 돈은 200 × 0.828 = 약 166원, 보너스 20% 상품에서는 200 × 0.69 = 약 138원이라 캐시가 맞은 턴은 그 안에 들고 캐시를 놓친 턴은
    # 평균부터 넘는다 — 캐시를 놓친 턴이 적자임을 알고 고른 가격이다. 표본은 운영자 시험 계정 한 명의 턴이라 실사용자의 캐시 미적중
    # 비율은 아직 모른다.
    "opus": ModelPrices(chat_turn=200, novel_episode=900, novel_outline=2_070, novel_episode_outline=900),
}


def _check_model_prices() -> None:
    """등록부에 글쓰기 모델마다 꼭 한 행이 있는지. 행이 빠진 모델은 가격 함수가 그 모델을 받는 순간 `KeyError` 로 500 이 되므로,
    모델 타입과 표가 어긋나면 기동에서 멈춘다."""
    if set(CLOVER_MODEL_PRICES) != set(get_args(ChatModelId)):
        raise RuntimeError("가격 등록부의 행이 글쓰기 모델 목록과 다르다")


_check_model_prices()

IMAGE_UNIT_COST = 90
# AI 문단 수정 한 번의 클로버 — 모델과 무관하다(언제나 기본 모델로 고친다). 수정 90: 시험 세 번에서 잰 문단 수정 원가 약
# $0.026(약 36원)이 쓸 수 있는 돈(90 × 0.828 = 약 75원)의 약 절반이다. 웹은 소설 단가의 사본을 갖지 않고 서버 응답으로만 받는다(배포 사이에
# 열어 둔 화면의 금액이 어긋나지 않게).
NOVELIZE_AI_EDIT_COST = 90
# 노벨(회원이 공개한 소설) 화 하나의 소장 가격과, 소설마다 앞에서부터 무료로 읽는 화 수. 화당 90원으로, 공개 소설 열람 가격
# 검토에서 고른 값이다(원가가 아니라 정책값). 가격 안내 응답과 구매 라우트가 호출 때마다 여기서 읽는다.
NOVEL_READ_COST = 90
NOVEL_FREE_CHAPTER_COUNT = 5
# 대화방 요약을 AI 로 다시 만드는 한 번의 클로버 — 방 모델과 무관한 고정가. 다시 만들기는 방의 글쓰기 모델이 아니라 요약 모델로
# 한 번 부른다. 모델 배정 표의 요약 칸 행이 방 모델마다 다르면 원가는 방 모델을 따를 수 있지만 가격은 그대로다. 값은 3원
# 단위에서 기본 모델 채팅 턴 하나(10)와 같게 정한 값을 1원 단위로 옮기며 세 배 한 것이다(30원 그대로). 채팅 턴 가격에서 끌어오지
# 않는다 — 턴 가격을 바꿔도 이 값은 그대로다. 가격 안내 응답과 다시 만들기 라우트가 호출 때마다 여기서 읽는다.
MEMORY_SUMMARY_REGENERATE_COST = 30
# 가격표의 버전. 위 등록부의 값이나 기능 단가·무료 화 수가 하나라도 바뀌면 1 올린다. 공개 가격 응답이 이 값을 싣고, 화면은
# 클로버를 쓰는 채팅·이미지 요청에 받은 값을 실어 보낸다 — 실제로 깎을 요청의 값이 이 값과 다르면 게이트가 깎기 전에 409
# (`CLOVER_PRICE_CHANGED`)로 멈춰, 사용자가 본 적 없는 가격으로 깎이지 않게 한다(`core/rate_limit_gate.py`).
PRICE_VERSION = 2

# `db/models/clover.py`의 `kind` 컬럼 주석과 같은 목록이다. 컬럼은 Text라 DB가 값을 막지
# 않으므로(마이그레이션 없이 넓히기 위해서다) 이 `Literal`이 유일한 강제 지점이다.
CloverKind = Literal[
    "admin_grant",
    "admin_revoke",
    "attendance_grant",
    "chat_spend",
    "image_spend",
    "chat_refund",
    "image_refund",
    "withdrawal_burn",
    # 미션 청구(`clover/router.py`)와 만료 배치(`scripts/ops/expire_clover.py`)가 쓴다.
    "mission_grant",
    "expire_burn",
    # 소설화 작업 생성 때의 선차감과, 실패 확정 때의 환불·목표보다 적은 화를 낸 성공의 차액 환불(`novelize/billing.py`).
    "novelize_spend",
    "novelize_refund",
    # 결제(`payments/service.py`): 구매로 받은 유료·보너스, 결제 취소에 따른 남은 구매분 회수, 포트원이 환불을 확정
    # 거절해 그 회수를 되돌린 것.
    "purchase_paid",
    "purchase_bonus",
    "purchase_revoke",
    "purchase_restore",
    # 노벨 화 소장 구매의 차감과, 게시자가 산 화를 지워 돌려준 환급(`novel_public/purchases.py`).
    "novel_read_spend",
    "novel_read_refund",
    # 대화방 요약 다시 만들기의 차감과, 다시 만들기가 실패해 돌려준 환불(`chat/router.py`). 사용처 행을 남기지 않는다 — 작품
    # 원작자 몫이 붙는 사용이 아니라서 정산 대상이 아니다.
    "memory_summary_spend",
    "memory_summary_refund",
    # 클로버 단위(한 개의 원화 값)를 바꿀 때 잔액을 새 단위로 옮긴 행과, 그 전환을 되돌린 행. 회원마다 이벤트 한 번에 한 행이고
    # 쓰는 쪽은 전환 마이그레이션과 되돌림 스크립트뿐이다(`db/models/clover.py` 의 `CloverUnitEvent`).
    "unit_conversion",
    "unit_conversion_revert",
]

# 위 두 단위 전환 kind. 내역 응답이 이 행을 어느 탭에나 경계 줄로 싣고, 옛 단위 표시에서 늘 빼는 열쇠다.
UNIT_CONVERSION_KINDS = ("unit_conversion", "unit_conversion_revert")

# 이 코드가 쓰는 클로버 단위 — 클로버 한 개가 몇 원인가(부가세 포함). 가격 상수·상품 수량·환불 견적이 모두 이 단위로 적혀 있다.
# 3원에서 1원으로 바꾼 것은 전환 마이그레이션(`725813c4f950`)이 DB 의 수량을 함께 세 배 한 배포에서다.
# 기동 가드(`clover/unit.py`)가 이 값과 DB 의 마지막 단위 전환 기록을 대조하고, 운영 교체 스크립트(`ops/swap-api.sh`)는 이
# 이름이 있는지로 올릴 이미지에 가드가 있는지를 판정한다 — 이름을 바꾸거나 옮기면 그 스크립트의 판정도 함께 고친다.
CLOVER_UNIT_KRW = 1

# 구매로 생기는 로트 kind. 차감 정렬은 이 둘만 이름으로 집고 나머지 kind 는 전부 무료로 본다 — 무료 kind 를 나열하면
# kind 가 늘 때(Text 라 마이그레이션 없이 는다) 빠뜨린 무료 로트가 유료 뒤로 밀린다. 둘만 집으면 누락이 생길 자리가 없다.
PURCHASE_LOT_KINDS = ("purchase_paid", "purchase_bonus")

# 소진은 만료 임박 우선, 회수는 최근 지급분부터 — 둘 다
# `_apply`의 음수-delta 분기(`guard=True`)를 공유하지만 로트를 잡는 정렬이 정반대다.
_LotOrder = Literal["expiry_first", "recency_first"]

# 차감 등급: 무료 → 구매 보너스 → 구매 유료. 현금으로 산 유료분을 가장 늦게 쓰게 해, 환불할 때 남은 유료 수량이
# 최대가 되게 한다. 같은 구매의 유료·보너스는 등급으로 갈려 동률이 없다.
_SPEND_GRADE = case(
    (CloverLot.kind == "purchase_bonus", 1),
    (CloverLot.kind == "purchase_paid", 2),
    else_=0,
)


# 정지 스위치(`settings.clover_ledger_paused`)가 켜졌을 때의 거절. 결제 꺼짐(`PAYMENTS_UNAVAILABLE`)과 같은 503 모양에 짧은 안내를
# 싣는다 — 기다리면 풀리는 일시 정지라 429 의 재시도 계약(`retryAfterSeconds`)이 아니다.
CLOVER_PAUSED_CODE = "CLOVER_PAUSED"
_CLOVER_PAUSED_MESSAGE = "클로버 사용을 잠시 멈췄어요. 몇 분 뒤 다시 시도해 주세요."


def raise_if_clover_paused() -> None:
    """정지 스위치가 켜져 있으면 503 `CLOVER_PAUSED`. 단위 전환처럼 잔액을 한꺼번에 옮기는 동안 새 차감·지급이 끼지 않게 한다.

    부르는 곳: 모든 차감이 지나는 `spend` 첫 줄, 채팅·이미지 게이트의 유료 갈래(`core/rate_limit_gate.py` — 하루 1회 확인 429 와
    가격 버전 409 보다 먼저), 그리고 공용 함수에서 막을 수 없는 지급·회수 라우트의 의존성(미션 수령·출석 수령·어드민 지급과 회수·어드민 결제
    환불 실행·주문 생성). 지급(`grant`)·구매분 회수는 결제 완료·웹훅·콘솔 취소와 함수를 같이 써서 함수에서 막으면 그것까지 멈춘다.

    막지 않는 것: 무료 대화 턴·무료 토큰 이미지(`spend` 를 부르지 않는다), 모든 환급, 결제 완료·웹훅, 만료 배치, 탈퇴 소멸 —
    이미 시작한 일의 마무리와 돈이 이미 나간 결제의 동기화는 멈추면 안 된다. 라우트 의존성으로도 쓴다(인자가 없다)."""
    if settings.clover_ledger_paused:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": CLOVER_PAUSED_CODE, "message": _CLOVER_PAUSED_MESSAGE},
        )


@dataclass(frozen=True)
class CloverSpend:
    """차감 결과. `ledger_id` 는 이 차감의 원장 행이고, 환급(`refund_spend`)이 그 배분을 찾는 열쇠다."""

    balance_after: int
    ledger_id: uuid.UUID


@dataclass(frozen=True)
class SpendUsage:
    """차감이 쓰인 곳. `spend` 가 받으면 차감과 같은 트랜잭션에 사용처 행(`CloverSpendUsage`)을 하나 더한다.

    채팅은 `content_id`·`chat_room_id`, 소설화는 `content_id`·`novel_id`(대화방이 남아 있으면 `chat_room_id` 도), 노벨
    구매는 `content_id`(원작)·`novel_id`·`publisher_user_id`, 빌더 미리보기는 아무것도 넘기지 않는다. 작품 소유자는 넘기지
    않는다 — `spend` 가 차감 트랜잭션 안에서 작품 행에서 읽는다.
    """

    kind: CloverSpendUsageKind
    content_id: uuid.UUID | None = None
    chat_room_id: uuid.UUID | None = None
    novel_id: uuid.UUID | None = None
    publisher_user_id: uuid.UUID | None = None


class CloverRefundExceedsSpendError(Exception):
    """환급액이 그 차감에서 아직 돌려주지 않은 양보다 크다. 같은 차감을 두 번 환급하려 했다는 뜻이다 — 트랜잭션을
    롤백시켜 이중 환급을 막는다(배분 CHECK 가 그 뒤의 마지막 그물이다)."""


class CloverLotShortfallError(Exception):
    """총액 CAS(`users.clover_balance`)는 통과했는데
    로트 합계가 부족한 비정상 상태(Σ 불변식이 이미 깨졌다는 뜻, 예컨대 백필 누락). 이 예외를
    잡지 않고 그대로 낸다 — 트랜잭션이 롤백돼 총액 CAS까지 되돌아가는 것이 목적이다.
    """


async def _consume_lots(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    amount: int,
    order: _LotOrder,
    spend_ledger_id: uuid.UUID | None,
) -> None:
    """로트를 `SELECT ... FOR UPDATE`로 잠가 `amount`만큼 순서대로 깎는다.

    호출 전에 총액 CAS가 이미 통과했다는 전제다(락 순서는 `_apply`가 users를 먼저
    잠근 뒤에야 이 함수가 clover_lots를 잠그는 순서로 고정된다). 여기서 부족이 나오면
    잔액 자체가 모자란 정상 부족이 아니라 Σ 불변식이 깨진 비정상 상태라
    `CloverLotShortfallError`를 던진다.

    `order`가 정렬을 가른다 — `expiry_first`는 소진, `recency_first`는 회수다.
    만료 여부로 거르지 않는다 — `remaining > 0`만 본다. 만료의 진실은 배치뿐이다.

    소진은 등급(무료 → 보너스 → 유료) 안에서 만료 임박 순이다. `id` 는 같은 트랜잭션에서 만든 로트의 `created_at`
    동률을 결정적으로 끊는 꼬리다. 회수는 무료 로트만 본다 — 구매분은 결제 환불 경로로만 회수한다.

    `spend_ledger_id` 가 있으면(차감) 로트마다 배분 행을 남긴다. 회수는 환급 대상이 아니라 `None` 이다.
    """
    statement = select(CloverLot).where(CloverLot.user_id == user_id, CloverLot.remaining > 0)
    if order == "expiry_first":
        statement = statement.order_by(
            _SPEND_GRADE,
            CloverLot.expires_at.asc().nulls_last(),
            CloverLot.created_at.asc(),
            CloverLot.id.asc(),
        )
    else:
        statement = statement.where(CloverLot.kind.not_in(PURCHASE_LOT_KINDS)).order_by(CloverLot.created_at.desc())

    lots = (await db.scalars(statement.with_for_update())).all()

    left = amount
    seq = 0
    for lot in lots:
        if left <= 0:
            break
        take = min(lot.remaining, left)
        lot.remaining -= take
        left -= take
        if spend_ledger_id is not None:
            db.add(CloverSpendAllocation(spend_ledger_id=spend_ledger_id, lot_id=lot.id, seq=seq, amount=take))
            seq += 1

    if left > 0:
        raise CloverLotShortfallError(
            f"user {user_id}: 로트 합계가 요청 {amount} 중 {left}만큼 모자라다"
        )


async def _apply(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    delta: int,
    kind: CloverKind,
    idempotency_key: str | None,
    guard: bool,
    expires_at: datetime | None = None,
    lot_order: _LotOrder = "expiry_first",
    record_allocations: bool = False,
    payment_id: uuid.UUID | None = None,
) -> CloverLedger | None:
    """잔액 UPDATE + 원장 INSERT를 한 트랜잭션에 넣는다. **커밋하지 않는다.** 원장 행을 돌려준다(유저가 없거나 가드에
    걸리면 `None`).

    `guard=True`면 `WHERE clover_balance >= -delta`를 걸어 음수로 내려가지 않게 한다 — 이
    WHERE가 없으면 동시 요청 둘이 같은 잔액을 읽고 둘 다 통과한다.

    🔴 판정에 `.rowcount`를 쓰지 않는다 — mypy strict에서 `Result[Any]`가 그 속성을 노출하지
    않는다(`admin/users.py:411-412`). `RETURNING clover_balance`가 **행을 돌려줬는가**로 가른다.
    선례는 `admin/users.py:416-423`.

    `guard`가 그대로 로트 처리 분기를 가른다.
    `guard=False`는 항상 `grant()`(양수 `delta`)만 타므로 로트 1행을 새로 만들고,
    `guard=True`는 `spend()`/`revoke()`(음수 `delta`)라 기존 로트를 `lot_order`대로 잠가
    깎는다. `kind`는 `grant()`가 이 분기를 탈 때만 넘어오는 지급 종류라 로트 `kind`로 그대로
    재사용한다(`db/models/clover.py`의 `CloverLot` docstring — 로트 kind는 지급 종류의 부분
    집합이다).

    원장 행을 로트보다 먼저 flush 한다 — 차감 배분(`record_allocations`)이 원장 id 를 FK 로 잡는데, 이 저장소는
    `relationship()` 을 쓰지 않아 단위작업의 INSERT 정렬에 기댈 수 없다.
    """
    statement = update(User).where(User.id == user_id)
    if guard:
        statement = statement.where(User.clover_balance >= -delta)

    balance_after = await db.scalar(
        statement.values(clover_balance=User.clover_balance + delta).returning(User.clover_balance)
    )
    if balance_after is None:
        return None

    ledger = CloverLedger(
        user_id=user_id,
        amount=delta,
        balance_after=balance_after,
        kind=kind,
        idempotency_key=idempotency_key,
    )
    db.add(ledger)
    # 여기서 flush하는 이유: 멱등키 중복의 `IntegrityError`가 **호출한 자리에서** 터져야
    # 라우트가 409로 번역할 수 있다. 커밋까지 미루면 예외가 커밋 지점에서 나와 어느 연산이
    # 중복이었는지 호출부가 알 수 없다. 배분이 가리킬 원장 행도 이 flush 로 먼저 생긴다.
    await db.flush()

    if guard:
        await _consume_lots(
            db,
            user_id=user_id,
            amount=-delta,
            order=lot_order,
            spend_ledger_id=ledger.id if record_allocations else None,
        )
    else:
        db.add(
            CloverLot(
                user_id=user_id,
                granted_amount=delta,
                remaining=delta,
                expires_at=expires_at,
                kind=kind,
                payment_id=payment_id,
            )
        )
    await db.flush()
    return ledger


async def spend(
    db: AsyncSession, *, user_id: uuid.UUID, amount: int, kind: CloverKind, usage: SpendUsage | None = None
) -> CloverSpend | None:
    """조건부 UPDATE + 원장 INSERT. 잔액이 모자라면 **아무것도 하지 않고 `None`**.

    성공하면 차감 후 잔액과 원장 id 를 돌려준다. 환급은 그 id 로 이 차감의 배분을 찾아 깎은 로트로 되돌린다. **커밋은 호출자가 한다** — 게이트만 별도 트랜잭션이
    필요하고 어드민·탈퇴는 호출자 세션에 얹혀야 조치와 원장이
    같이 커밋되거나 같이 롤백된다. 그래서 커밋 정책을 이 함수가 갖지 않는다.

    총액 CAS가 통과한 뒤 로트를 만료 임박 우선
    순서로 잠가 깎는다. 만료 필터는 걸지 않는다 — 만료의 진실은 배치뿐이다. 로트
    합계가 모자라면 `CloverLotShortfallError`가 나 총액 CAS까지 롤백된다.

    `usage` 를 주면 같은 트랜잭션에 사용처 행을 더한다(`_record_usage`). 이미지 차감처럼 작품 맥락이 없는 차감은 주지 않는다.

    정지 스위치가 켜져 있으면 잔액을 건드리기 전에 503 이다(`raise_if_clover_paused`) — 모든 차감이 이 함수를 지나므로 새 차감
    경로가 생겨도 여기서 막힌다. 부족(`None`)과 달리 예외라 호출부의 부족 번역(429·403)을 타지 않는다.
    """
    raise_if_clover_paused()
    ledger = await _apply(
        db,
        user_id=user_id,
        delta=-amount,
        kind=kind,
        idempotency_key=None,
        guard=True,
        lot_order="expiry_first",
        record_allocations=True,
    )
    if ledger is None:
        return None
    if usage is not None:
        await _record_usage(db, ledger_id=ledger.id, user_id=user_id, usage=usage)
    return CloverSpend(balance_after=ledger.balance_after, ledger_id=ledger.id)


async def _record_usage(db: AsyncSession, *, ledger_id: uuid.UUID, user_id: uuid.UUID, usage: SpendUsage) -> None:
    """차감 원장 행 하나에 사용처 행 하나를 더한다. **커밋하지 않는다.**

    작품 소유자는 같은 INSERT 문장 안에서 작품 행에서 읽는다(`INSERT … SELECT`). 게이트가 미리 읽어 넘기면 차감이 없는
    무료 턴에도 작품 조회가 하나 늘고, 여기서 읽으면 실제로 클로버를 쓰는 차감에만 왕복 없이 붙는다. 작품 행이 없으면
    `ValueError` 로 트랜잭션을 롤백시킨다 — 채팅·소설 경로는 차감 전에 그 작품을 이미 읽었으므로 도달하면 버그다.

    자기 플레이 여부(지불자 = 작품 소유자)도 같은 문장에서 그 작품 행으로 정한다. 미리보기는 비교할 소유자가 없어 거짓이다.

    미리보기는 작품을 가리키지 않아 읽을 것이 없으므로 받은 값을 그대로 넣는다. 작품 id 를 버리지 않고 넣는 것은, 종류를
    잘못 넘긴 호출(작품이 있는데 `preview`)이 정산에서 조용히 빠지지 않고 CHECK 에 걸려 실패하게 하려는 것이다.

    작품 행이 있으면 사용처 INSERT 의 FK 검사가 그 행에 `FOR KEY SHARE` 를 잡으므로, 같은 작품을 `FOR UPDATE` 로 잡은
    트랜잭션(댓글 쓰기·발행·소설화 허락 변경)이 끝날 때까지 차감이 기다릴 수 있다. 순환은 없다 — 그 경로들은 작품을 잡은
    뒤 사용자 행을 쓰기 잠그거나 클로버 로트를 잠그지 않고(사용자 행은 작품보다 먼저 `KEY SHARE` 로만 잡는다), 탈퇴의 작품
    UPDATE 는 키를 바꾸지 않아 `KEY SHARE` 와 충돌하지 않는다.
    """
    if usage.kind == "preview":
        db.add(
            CloverSpendUsage(
                spend_ledger_id=ledger_id,
                usage_kind=usage.kind,
                spender_user_id=user_id,
                is_self_play=False,
                content_id=usage.content_id,
                chat_room_id=usage.chat_room_id,
                novel_id=usage.novel_id,
                publisher_user_id=usage.publisher_user_id,
            )
        )
        await db.flush()
        return
    inserted = await db.scalar(
        insert(CloverSpendUsage)
        .from_select(
            [
                CloverSpendUsage.spend_ledger_id,
                CloverSpendUsage.usage_kind,
                CloverSpendUsage.spender_user_id,
                CloverSpendUsage.is_self_play,
                CloverSpendUsage.content_id,
                CloverSpendUsage.content_owner_user_id,
                CloverSpendUsage.chat_room_id,
                CloverSpendUsage.novel_id,
                CloverSpendUsage.publisher_user_id,
            ],
            select(
                literal(ledger_id, Uuid),
                literal(usage.kind),
                literal(user_id, Uuid),
                Content.creator_user_id == literal(user_id, Uuid),
                Content.id,
                Content.creator_user_id,
                literal(usage.chat_room_id, Uuid),
                literal(usage.novel_id, Uuid),
                literal(usage.publisher_user_id, Uuid),
            ).where(Content.id == usage.content_id),
        )
        .returning(CloverSpendUsage.spend_ledger_id)
    )
    if inserted is None:
        raise ValueError(f"차감 {ledger_id} 의 사용처 작품 {usage.content_id} 이 없다")


async def grant(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    amount: int,
    kind: CloverKind,
    idempotency_key: str | None = None,
    expires_at: datetime | None = None,
    payment_id: uuid.UUID | None = None,
) -> int:
    """가드 없는 증가 + 원장 INSERT + 로트 1행 생성. 증가 후 잔액을 돌려준다. **커밋은
    호출자가 한다.**

    `payment_id` 는 구매 지급(`purchase_paid`·`purchase_bonus`)만 넘긴다 — 로트가 그 결제를 가리켜야 환불이 그 구매의
    로트를 집는다. 구매 kind 와 결제 참조는 함께 있거나 함께 없어야 한다(로트 CHECK).

    `idempotency_key`가 중복이면 `IntegrityError`가 그대로 올라온다 — 라우트가 409로 번역한다.
    유니크 인덱스가 그걸 막는 유일한 수단이고, 더블클릭·재시도가
    곧 중복 지급이라 어드민 경로는 반드시 키를 넣는다.

    🔴 `expires_at`은 호출 지점이 명시해야 한다 — 만료가 붙는 무료 지급은 미션·누적 출석과 기존
    잔액 백필뿐이고, 어드민 지급과 환불은 `None`(무기한)이다. 기본값을 `None`으로 둔 이유는
    어드민 지급·환불 호출부가 만료를 안 넘겨 기본값에 기대기 때문이다 — 미션 청구
    (`clover/router.py`)는 `core.clover.earned_lot_expiry`로 계산한 값을 명시적으로 넘긴다.
    """
    ledger = await _apply(
        db,
        user_id=user_id,
        delta=amount,
        kind=kind,
        idempotency_key=idempotency_key,
        guard=False,
        expires_at=expires_at,
        payment_id=payment_id,
    )
    # 가드가 없으므로 `None`은 "유저가 없다"는 뜻뿐이다. 호출부는 전부 인증·조회를 이미 마친
    # 뒤라 도달할 수 없고, 도달했다면 그건 500이 맞다.
    if ledger is None:
        raise ValueError(f"클로버를 지급할 유저를 찾지 못했다: {user_id}")
    return ledger.balance_after


async def revoke(
    db: AsyncSession, *, user_id: uuid.UUID, amount: int, idempotency_key: str | None = None
) -> int | None:
    """어드민 회수. `spend`와 같은 조건부 UPDATE이고 `kind`만 `admin_revoke`다.

    **무료 로트만 회수한다.** 구매로 생긴 유료·보너스 로트는 결제 환불 경로로만 회수한다 — 어드민 수동 회수가 그걸
    깎으면 그 구매의 남은 유료 수량(환불 견적의 바탕)이 결제 기록 밖에서 줄어든다. 그래서 판정도 총액이 아니라 무료
    로트 합이다: 그 합이 모자라면 `None` — 라우트가 422로 번역한다. 총액 CAS 만으로 판정하면 구매 로트가 있는
    사용자에게서 총액은 통과하고 로트가 모자라 `CloverLotShortfallError` 500 이 난다.

    판정 전에 사용자 행을 `FOR UPDATE` 로 잠근다 — 합을 읽은 뒤 차감이 끼어들어 무료 로트가 줄면 판정이 낡는다. 이
    잠금은 `_apply` 의 UPDATE 와 같은 행이라 락 순서(users → clover_lots)가 그대로다.

    **음수로 내려가지 않는다**: 오지급 회수는 이미 쓴 만큼을 빚으로 남기지 않는다는 뜻이다.

    🔴 로트 소진 순서가 `spend`(만료 임박 우선)와 **정반대**다 — 회수는 최근 지급분부터
    (`created_at DESC`). 회수의 실제 쓰임이 "방금 잘못 준 걸 도로 빼는 것"이라 최근
    로트부터 빼야 오지급한 그 로트가 깨끗하게 되돌려진다.
    """
    await db.execute(select(User.id).where(User.id == user_id).with_for_update())
    revocable = await db.scalar(
        select(func.coalesce(func.sum(CloverLot.remaining), 0)).where(
            CloverLot.user_id == user_id,
            CloverLot.remaining > 0,
            CloverLot.kind.not_in(PURCHASE_LOT_KINDS),
        )
    )
    if revocable is None or revocable < amount:
        return None
    ledger = await _apply(
        db,
        user_id=user_id,
        delta=-amount,
        kind="admin_revoke",
        idempotency_key=idempotency_key,
        guard=True,
        lot_order="recency_first",
    )
    return None if ledger is None else ledger.balance_after


async def revoke_purchase_lots(
    db: AsyncSession, *, payment_id: uuid.UUID, limit: int | None = None
) -> tuple[int, int]:
    """결제 하나로 생긴 유료·보너스 로트의 남은 양을 회수한다. 회수한 `(유료, 보너스)` 를 돌려준다. **커밋은 호출자가
    한다.** 결제 취소(어드민 환불·포트원 콘솔 취소)만 부른다 — 어드민 수동 회수(`revoke`)는 구매 로트를 건드리지 않는다.

    `limit` 이 없으면 남은 전부, 있으면 그 수량까지만 유료 먼저·모자라면 보너스에서 회수한다(콘솔 부분 취소 — 취소한
    금액만큼만 가져간다). 둘 다 모자라면 있는 만큼만이다.

    남은 것이 없으면 아무것도 쓰지 않고 `(0, 0)` 이다(원장에 0 행을 남기지 않는다). 회수는 환급 대상이 아니라 배분을
    남기지 않는다.

    락 순서는 users → clover_lots(`_apply` 와 같다). 호출자는 그 앞에서 결제 행을 잠근다(payments → users → clover_lots).
    """
    user_id = await db.scalar(select(Payment.user_id).where(Payment.id == payment_id))
    if user_id is None:
        raise ValueError(f"회수할 결제를 찾지 못했다: {payment_id}")
    await db.execute(select(User.id).where(User.id == user_id).with_for_update())
    lots = (
        await db.scalars(
            select(CloverLot).where(CloverLot.payment_id == payment_id).order_by(CloverLot.id).with_for_update()
        )
    ).all()
    taken = {kind: 0 for kind in PURCHASE_LOT_KINDS}
    left = limit
    # 유료 먼저. 잠금은 위에서 id 순으로 잡았고, 여기 순서는 깎는 순서일 뿐이다.
    for lot in sorted(lots, key=lambda lot: lot.kind != "purchase_paid"):
        take = lot.remaining if left is None else min(lot.remaining, left)
        taken[lot.kind] += take
        lot.remaining -= take
        if left is not None:
            left -= take
    total = sum(taken.values())
    if total == 0:
        return 0, 0
    balance_after = await db.scalar(
        update(User)
        .where(User.id == user_id)
        .values(clover_balance=User.clover_balance - total)
        .returning(User.clover_balance)
    )
    assert balance_after is not None  # 위에서 잠근 행이다
    db.add(
        CloverLedger(user_id=user_id, amount=-total, balance_after=balance_after, kind="purchase_revoke")
    )
    await db.flush()
    return taken["purchase_paid"], taken["purchase_bonus"]


async def restore_purchase_lots(
    db: AsyncSession, *, payment_id: uuid.UUID, paid: int, bonus: int
) -> int | None:
    """`revoke_purchase_lots` 로 회수한 양을 그 결제의 로트로 되돌린다(포트원이 환불을 확정 거절했을 때). 되돌린 뒤
    잔액을 돌려준다. **커밋은 호출자가 한다.**

    **탈퇴한 회원이면 아무것도 하지 않고 `None`** — `refund_spend` 와 같은 이유(탈퇴가 소멸시킨 잔액을 되살리지 않는다)이고
    판정도 같은 잔액 UPDATE 조건(`deleted_at IS NULL`)이다.

    되돌린 양이 로트의 `granted_amount` 를 넘지 않는다: 회수량은 회수 시점의 `remaining` 이고, 그 뒤 같은 로트로 돌아올 수
    있는 환급은 그 로트에서 이미 깎인 몫뿐이라 합이 지급량 이하다(넘으면 로트 CHECK 가 롤백시킨다).
    """
    total = paid + bonus
    if total == 0:
        return None
    user_id = await db.scalar(select(Payment.user_id).where(Payment.id == payment_id))
    if user_id is None:
        raise ValueError(f"복원할 결제를 찾지 못했다: {payment_id}")
    balance_after = await db.scalar(
        update(User)
        .where(User.id == user_id, User.deleted_at.is_(None))
        .values(clover_balance=User.clover_balance + total)
        .returning(User.clover_balance)
    )
    if balance_after is None:
        logger.info("탈퇴한 회원(%s)의 구매 회수 복원은 적용하지 않는다", user_id)
        return None
    lots = {
        lot.kind: lot
        for lot in (
            await db.scalars(
                select(CloverLot).where(CloverLot.payment_id == payment_id).order_by(CloverLot.id).with_for_update()
            )
        ).all()
    }
    for kind, amount in (("purchase_paid", paid), ("purchase_bonus", bonus)):
        if amount == 0:
            continue
        lot = lots.get(kind)
        if lot is None:
            raise ValueError(f"결제 {payment_id} 에 {kind} 로트가 없다")
        lot.remaining += amount
    db.add(
        CloverLedger(user_id=user_id, amount=total, balance_after=balance_after, kind="purchase_restore")
    )
    await db.flush()
    return int(balance_after)


async def paid_balance(db: AsyncSession, *, user_id: uuid.UUID) -> int:
    """구매로 받은 클로버(유료·보너스)의 남은 양. 탈퇴하면 사라지고 환불은 탈퇴 전에만 신청할 수 있어 탈퇴 경고가 이 값을
    쓴다 — 무료 지급까지 센 전체 잔액으로 경고하면 결제한 적 없는 회원에게도 환불 안내가 뜬다. `GET /me` 가
    부르고, `GET /me/clover` 는 같은 값을 `balance_breakdown` 의 유료·보너스 합으로 낸다."""
    total = await db.scalar(
        select(func.coalesce(func.sum(CloverLot.remaining), 0)).where(
            CloverLot.user_id == user_id, CloverLot.kind.in_(PURCHASE_LOT_KINDS)
        )
    )
    return int(total or 0)


async def balance_breakdown(db: AsyncSession, *, user_id: uuid.UUID) -> tuple[int, int, int] | None:
    """잔액과, 그중 구매로 받은 유료·보너스 클로버의 남은 양(잔액, 유료, 보너스). 회원이 없으면 `None`.

    세 값을 **한 SELECT** 로 읽는다 — 문장 하나는 한 스냅샷을 보므로, 잔액과 로트 합을 따로 읽으면 그 사이 결제 지급이 커밋돼
    로트 합만 늘고 "무료 = 잔액 − 유료 − 보너스" 가 음수가 될 수 있다. 무료 몫은 호출자가 그 나머지로 낸다(무료 로트는 종류가
    여럿이라 하나씩 세면 빠뜨린다)."""

    def _remaining(kind: str) -> ColumnElement[int]:
        return (
            select(func.coalesce(func.sum(CloverLot.remaining), 0))
            .where(CloverLot.user_id == user_id, CloverLot.kind == kind)
            .scalar_subquery()
        )

    row = (
        await db.execute(
            select(User.clover_balance, _remaining("purchase_paid"), _remaining("purchase_bonus")).where(
                User.id == user_id
            )
        )
    ).one_or_none()
    if row is None:
        return None
    balance, paid, bonus = row
    return int(balance), int(paid), int(bonus)


async def burn_all(db: AsyncSession, *, user_id: uuid.UUID) -> int:
    """탈퇴 시 남은 잔액 전부를 소멸시킨다. 소멸된 금액을 돌려준다.

    🔴 **금액을 인자로 받지 않는 것이 이 함수의 요점이다.** 소멸은 "얼마를 쓴다"가 아니라
    "남은 걸 없앤다"라 `spend(amount=…)`로 표현하면 두 가지가 틀어진다 — 호출자가 읽어 둔
    잔액이 낡았을 때 ① 조건부 가드(`WHERE clover_balance >= amount`)가 걸려 **아무것도 안
    지워지고** ② 반환값을 버리면 그 실패가 조용하다. 탈퇴 라우트는 `user`를 초입에서 로드하고
    그 뒤 채팅방·메시지·asset 삭제를 거치므로 그 창이 실제로 존재한다.

    잔액이 0이면 아무것도 하지 않는다 — 의미 없는 0원 원장 행을 만들지 않는다. `WHERE
    clover_balance > 0`이 그 규칙과 "유저가 없다"를 한꺼번에 처리한다(둘 다 행이 안 돌아온다).

    🔴 **`_apply`를 쓰지 않고 자기 UPDATE를 갖는다.** `_apply`는 **상대 증감**
    (`clover_balance + delta`)이라 소멸에는 맞지 않는다 — 읽어 둔 값으로 빼는 형태가 되어,
    그 사이 차감이 커밋되면 `90 - 100 = -10`으로 `ck_users_clover_balance_non_negative`에
    걸려 **탈퇴 요청이 500이 된다**. `guard=False`는 `WHERE` 조건을 빼는 것이지 대입을
    절대값으로 만들지 않는다(앞선 판본의 docstring이 그 둘을 혼동했다).

    소멸은 **절대 대입**(`SET clover_balance = 0`)이고 소멸액은 `RETURNING OLD`로 받는다 —
    읽기와 쓰기가 한 문장이라 그 사이에 낄 창이 **없다**. PostgreSQL 18의 문법이고 CI·dev·prod가
    전부 18이다(`docker-compose.*.yml`, `api.yml`). `NEW`는 항상 0이라 볼 것이 없다.

    🔴 그 유저의 미소진 로트도 함께 0으로 만든다 — 안 그러면
    탈퇴 후에도 "만료 예정"으로 남은 유령 로트가 생긴다. `revoke`의 **부분** 무효화와 달리
    **전량** 무효화라 `_apply`/`_consume_lots`를 쓰지 않는다. 잔액이 이미 0이었어도(`burned`가
    `None`이어도) 실행한다 — 불변식이 이미 깨진 상태에서도 유령 로트를 남기지 않기 위해서다.
    """
    # `literal_column`에 타입을 주는 이유: 안 주면 `.returning()`이 `Update`를 그대로 돌려
    # `db.scalar`가 `-> None` 오버로드로 잡혀 mypy strict가 막는다.
    result = await db.execute(
        update(User)
        .where(User.id == user_id, User.clover_balance > 0)
        .values(clover_balance=0)
        .returning(literal_column("OLD.clover_balance", Integer))
    )
    burned = result.scalar_one_or_none()

    await db.execute(
        update(CloverLot)
        .where(CloverLot.user_id == user_id, CloverLot.remaining > 0)
        .values(remaining=0)
    )

    if burned is None:
        return 0
    db.add(
        CloverLedger(
            user_id=user_id,
            amount=-burned,
            balance_after=0,
            kind="withdrawal_burn",
            idempotency_key=None,
        )
    )
    # `_apply`와 같은 이유로 여기서 flush한다 — 예외가 이 자리에서 터져야 호출부가 안다.
    await db.flush()
    return int(burned)


async def spend_in_new_transaction(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    amount: int,
    kind: CloverKind,
    usage: SpendUsage | None = None,
) -> CloverSpend | None:
    """**게이트 전용**. 요청 스코프 세션의 커밋 타이밍과 무관하게
    즉시 커밋한다.

    채팅 4경로의 커밋 시점이 제각각이라(전송·편집은 생성 **전**, 재생성은 생성 **후**,
    빌더 미리보기는 `db.commit()`이 **0건**) 요청 세션에 얹으면 같은 차감이 경로마다 다르게
    동작한다 — 미리보기는 영원히 공짜가 된다.

    🔴 `session_factory`는 반드시 `Depends(get_session_factory)`로 받은 것이어야 한다.
    모듈에서 `async_session_factory`를 직접 import하면 `tests/conftest.py`의 오버라이드를 안
    타서 **테스트가 공유 DB를 건드린다.**

    `usage` 는 `spend` 에 그대로 넘긴다 — 사용처 행이 차감과 같은 커밋에 들어간다.
    """
    async with session_factory() as session:
        spent = await spend(session, user_id=user_id, amount=amount, kind=kind, usage=usage)
        if spent is None:
            return None
        await session.commit()
        return spent


async def refund_spend(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    spend_ledger_id: uuid.UUID | None,
    amount: int,
    kind: CloverKind,
    skip_lot: ColumnElement[bool] | None = None,
) -> int | None:
    """차감을 되돌린다. 환급 후 잔액을 돌려준다. **커밋은 호출자가 한다.**

    `spend_ledger_id` 가 있으면 그 차감의 배분을 깎은 순서의 **역순**(`seq DESC`)으로 되돌린다 — 차감은 무료 →
    보너스 → 유료 순으로 깎으므로, 부분 환급은 유료부터 돌려준다. 무료부터 돌려주면 못 받은 서비스 몫을 8일짜리
    무료로 돌려주고 현금으로 산 유료는 쓴 채로 남아, 그 구매의 환불 견적이 실제로 받은 서비스보다 작아진다. 역순은
    "안 쓴 꼬리"를 되돌리는 것이라 그 차감이 없었을 때와 가장 가깝다.

    이미 만료된 로트에도 그대로 되돌린다(소설화는 몇 시간 뒤에 환급한다). 새 만료를 단 새 로트로 주면 만료된 무료
    클로버에 새 수명이 붙어 차감이 없었을 때보다 많이 갖게 된다. 돌아간 만료분은 다음 만료 배치가 다시 태운다.

    아직 돌려주지 않은 양보다 많이 돌려달라면 `CloverRefundExceedsSpendError` — 같은 차감을 두 번 환급하려 했다는
    뜻이라 롤백시킨다.

    `spend_ledger_id` 가 `None` 이면(배분을 남기기 전의 차감, 배분을 모르는 옛 코드가 만든 소설화 작업) 예전처럼
    무기한 새 로트(무료 등급)로 돌려준다.

    **탈퇴한 회원이면 아무것도 하지 않고 `None`.** 탈퇴가 잔액·로트를 이미 소멸시켰는데 늦게 도착한 환급이 그 위에
    잔액을 되살리면 지울 수 없는 잔액이 남는다. 탈퇴 판정은 잔액 UPDATE 의 조건(`deleted_at IS NULL`)이라 탈퇴와
    경합해도 둘 중 하나만 이긴다.

    락 순서는 users → clover_spend_allocations → clover_lots 다. 차감은 users → clover_lots 이고 배분은 INSERT 만
    하므로 순환이 없다.

    `skip_lot` 은 `CloverLot` 에 대한 SQL 조건이다. 주면 그 조건에 맞는 로트에서 나간 배분은 **돌려주지 않고 건너뛴다** —
    건너뛴 몫은 채울 대상이 아니라서 `amount` 에서 빠지고(부족 예외도 나지 않는다), 배분의 `refunded_amount`·환급 행·잔액
    어디에도 나타나지 않으며 원장 금액도 실제로 돌려준 양이다. 전부 건너뛰면 원장 행도 남기지 않는다. 노벨 삭제 환급이 전액
    취소된 결제의 로트를 건너뛸 때 쓴다(그 로트로 되돌리면 돈과 클로버를 함께 돌려받게 된다). 주지 않으면 지금처럼 전부
    되돌린다.

    배분에서 돌려준 몫마다 환급 행(`CloverSpendRefund`)을 하나씩 남긴다 — 배분에는 시각이 없어, 정산이 "언제 돌려줬는가"를
    아는 곳이 이 행뿐이다. 돌려준 양이 0 인 배분(이미 다 돌려받았다)은 남기지 않는다. 차감 id 가 없는 환급과 탈퇴 회원
    환급은 배분을 건드리지 않으므로 남기지 않는다. 환급 행은 이미 잠근 배분과 방금 넣은 원장 행을 FK 로 가리킬 뿐이라
    락 순서를 바꾸지 않는다.
    """
    balance_after = await db.scalar(
        update(User)
        .where(User.id == user_id, User.deleted_at.is_(None))
        .values(clover_balance=User.clover_balance + amount)
        .returning(User.clover_balance)
    )
    if balance_after is None:
        logger.info("탈퇴한 회원(%s)의 클로버 환급은 적용하지 않는다", user_id)
        return None

    returned: list[tuple[uuid.UUID, int]] = []
    skipped_amount = 0
    if spend_ledger_id is None:
        db.add(CloverLot(user_id=user_id, granted_amount=amount, remaining=amount, expires_at=None, kind=kind))
    else:
        allocations = (
            await db.scalars(
                select(CloverSpendAllocation)
                .where(CloverSpendAllocation.spend_ledger_id == spend_ledger_id)
                .order_by(CloverSpendAllocation.seq.desc())
                .with_for_update()
            )
        ).all()
        # 남의 로트로는 돌려주지 않는다 — 사용자 조건에 걸러진 배분은 환급 가능량에서 빠져 아래 부족 예외로 떨어진다.
        lots = {
            lot.id: (lot, bool(skipped))
            for lot, skipped in (
                await db.execute(
                    select(CloverLot, skip_lot if skip_lot is not None else false())
                    .where(
                        CloverLot.id.in_([allocation.lot_id for allocation in allocations]),
                        CloverLot.user_id == user_id,
                    )
                    .order_by(CloverLot.id)
                    .with_for_update(of=CloverLot)
                )
            ).tuples()
        }
        left = amount
        for allocation in allocations:
            entry = lots.get(allocation.lot_id)
            if left <= 0 or entry is None:
                continue
            lot, skipped = entry
            take = min(allocation.amount - allocation.refunded_amount, left)
            if skipped:
                left -= take
                skipped_amount += take
                continue
            allocation.refunded_amount += take
            lot.remaining += take
            left -= take
            if take > 0:
                returned.append((allocation.id, take))
        if left > 0:
            raise CloverRefundExceedsSpendError(
                f"user {user_id}: 차감 {spend_ledger_id} 의 남은 환급 가능량보다 {left} 많이 돌려달라고 했다"
            )
    if skipped_amount:
        # 잔액은 맨 앞에서 `amount` 만큼 올렸다(그 UPDATE 가 사용자 행 잠금과 탈퇴 판정을 겸한다). 건너뛴 몫을 되돌린다.
        balance_after = await db.scalar(
            update(User)
            .where(User.id == user_id)
            .values(clover_balance=User.clover_balance - skipped_amount)
            .returning(User.clover_balance)
        )
        assert balance_after is not None  # 위에서 잠근 행이다
        if skipped_amount == amount:
            return int(balance_after)

    ledger = CloverLedger(
        user_id=user_id,
        amount=amount - skipped_amount,
        balance_after=balance_after,
        kind=kind,
        idempotency_key=None,
    )
    db.add(ledger)
    # 환급 행이 원장 id 를 FK 로 잡으므로 원장을 먼저 넣는다(`_apply` 와 같은 이유 — 단위작업 INSERT 정렬에 기대지 않는다).
    await db.flush()
    if returned:
        db.add_all(
            CloverSpendRefund(allocation_id=allocation_id, refund_ledger_id=ledger.id, amount=take)
            for allocation_id, take in returned
        )
        await db.flush()
    return int(balance_after)


# 환급 트랜잭션 하나에 주는 시간(아래 래퍼). 정상이면 수십 밀리초다.
REFUND_TIMEOUT_SECONDS = 10.0


async def refund_spend_in_new_transaction(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    spend_ledger_id: uuid.UUID | None,
    amount: int,
    kind: CloverKind,
) -> None:
    """`refund_spend` 를 자기 트랜잭션에서 커밋한다. 🔴 **절대 예외를 밖으로 내지 않는다.**

    호출 자리가 SSE 제너레이터 본문이거나 이미 실패가 확정된 요청의 정리라, 예외가 새면 이미 시작된 스트림을 뚫고
    나가 태스크가 취소되고 **망가진 asyncpg 커넥션이 풀로 반환돼 무관한 요청이 500**이 된다(`core/rate_limit_gate.py`
    의 모듈 docstring 이 같은 이유로 `Depends`만 쓰라고 적는다).

    실패는 `logger.warning` + `capture_dependency_failure(dependency="clover")`로만 남는다 — 자동 재시도가 없어 이게
    유일한 발견 수단이다. 남는 결과는 "그 요청의 차감이 되돌아가지 않은 것"이고 보정은 어드민 지급이다.

    본문은 취소에서 차폐(shield)된다. 끊긴 SSE 요청의 정리 중에 불리면 그 범위는 이미 취소돼 있고, anyio 취소는 한 번
    전달되고 끝나지 않아 차폐 없이는 환급 트랜잭션의 첫 `await` 에서 다시 취소된다. 명시적 환급 자리도 그 `await` 도중
    끊김이 오면 같은 일을 겪으므로 래퍼가 모든 호출자를 함께 보호한다. 차폐는 취소를 삼키지 않는다 — 범위를 나가면
    호출자의 취소가 그대로 이어진다. 시간 상한은 종료 중인 프로세스가 환급 하나로 멈추지 않게 한다.
    """
    with anyio.move_on_after(REFUND_TIMEOUT_SECONDS, shield=True) as scope:
        try:
            async with session_factory() as session:
                await refund_spend(
                    session, user_id=user_id, spend_ledger_id=spend_ledger_id, amount=amount, kind=kind
                )
                await session.commit()
        # `BaseException`이 아니라 `Exception`이다 — 취소는 삼키지 않고 호출자에게 그대로 간다.
        except Exception as exc:
            logger.warning("클로버 환불 실패 — 그 요청의 차감이 남는다", exc_info=True)
            capture_dependency_failure(exc, dependency="clover")
    if scope.cancelled_caught:
        logger.warning("클로버 환불이 시간 안에 끝나지 않았다 — 그 요청의 차감이 남는다")
        capture_dependency_failure(TimeoutError("clover refund timed out"), dependency="clover")


def kst_today(now: datetime) -> date:
    """tz-aware `now`를 KST 날짜로 바꾼다. `core/rate_limit.py`의 `KST` 고정 오프셋을 쓴다.

    naive `now`는 거부한다 — `seconds_until_kst_midnight`와 같은 이유다. `astimezone`이
    naive를 **프로세스 로컬 시간**으로 재해석해서 같은 입력이 컨테이너 TZ마다 다른 날짜를 낸다.
    차감 확인과 무료 지급 로트의 만료가 이 날짜로 판정되므로, 틀리면 확인을 하루에 두 번 묻거나 하루를 건너뛰고
    만료 시각이 하루 어긋난다.

    `now`를 인자로 받는 이유는 테스트다 — 이 저장소에 시간을 얼리는 수단이 0건이라
    (`freezegun`·`time-machine` 전부 없다) 경계 검증은 리터럴 주입으로만 된다.
    """
    if now.tzinfo is None:
        raise ValueError("tz-aware `now`가 필요하다 — `datetime.now(UTC)`를 넘길 것")
    return now.astimezone(KST).date()


def is_same_kst_day(last: date | None, now: datetime) -> bool:
    """`last`가 `now`와 같은 KST 날짜인가. `last`가 `None`(한 번도 없음)이면 `False`."""
    return last == kst_today(now)


def earned_lot_expiry(now: datetime) -> datetime:
    """미션 지급이 만드는 로트의 만료 시각 — 지급일(KST) 자정 + 8일.
    `kst_today`를 재사용해 날짜를 구하고(naive `now` 거부도 그쪽에
    위임한다), 그 날의 KST 자정에 8일을 더한다.

    🔴 7이 아니라 8인 이유: 자정으로 정규화하면 "+7일"은 실제 보유 기간을 6~7일로 만든다
    (늦게 지급될수록 짧아진다) — "7일 유효기간" 고지와 어긋난다. "+8일"이면 보유 기간이
    7~8일이라 누구도 7일보다 적게 받지 않는다.

    🔴 마이그레이션(`cf74d6d53561_clover_lots.py`)의 `_legacy_lot_expiry`가 같은 계산을
    별도로 갖는다 — 마이그레이션이 `api.*`를 import하지 않는 것이 이 저장소 관례라
    사본이 둘인 것은 의도다. **다만 두 값은 반드시 같아야 한다** — 한쪽만 고치면 백필
    로트와 미션 로트의 유효기간 규칙이 갈린다.
    """
    midnight_kst = datetime.combine(kst_today(now), time.min, tzinfo=KST)
    return midnight_kst + timedelta(days=8)


# 구매로 받은 유료·보너스 클로버의 유효기간(년). 환불정책이 "구매일로부터 5년"이라 고지한다.
PURCHASE_LOT_YEARS = 5


def purchase_lot_expiry(paid_at: datetime) -> datetime:
    """구매 로트의 만료 시각 — 결제일(KST)의 5년 뒤 같은 날 KST 자정 + 1일. 2월 29일 결제는 그해에 같은 날이 없으면
    3월 1일을 그날로 본다.

    +1일은 `earned_lot_expiry` 의 +8일과 같은 이유다: 자정으로 정규화하면 늦게 결제할수록 보유 기간이 5년보다 짧아지는데,
    하루를 더하면 누구도 5년보다 적게 갖지 않는다.
    """
    paid_on = kst_today(paid_at)
    try:
        anniversary = paid_on.replace(year=paid_on.year + PURCHASE_LOT_YEARS)
    except ValueError:
        anniversary = date(paid_on.year + PURCHASE_LOT_YEARS, 3, 1)
    return datetime.combine(anniversary, time.min, tzinfo=KST) + timedelta(days=1)
