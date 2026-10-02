from datetime import date, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.redis import redis_client
from api.llm.usage_store import usage_key
from factories import _create_admin, _login_as, _login_as_admin, _make_user

# 다른 테스트의 "오늘" 해시와 겹치지 않게 먼 날짜를 쓴다(KST 날짜).
DAY0 = date(2030, 3, 10)
DAY1 = DAY0 + timedelta(days=1)
LITE = "gemini-3.5-flash-lite"


async def _put(day: date, call_site: str, model: str, **metrics: int) -> None:
    await redis_client.hset(
        usage_key(day), mapping={f"{call_site}|{model}|{metric}": value for metric, value in metrics.items()}
    )


def _url(start: date, end: date) -> str:
    return f"/admin/llm-usage?from={start.isoformat()}&to={end.isoformat()}"


async def _admin_get(db_client: httpx.AsyncClient, db_session: AsyncSession, url: str) -> httpx.Response:
    await _login_as_admin(db_client, await _create_admin(db_session))
    return await db_client.get(url)


def _row(rows: list[dict[str, Any]], call_site: str, model: str = LITE, day: date | None = None) -> dict[str, Any]:
    (found,) = [
        r
        for r in rows
        if r["callSite"] == call_site and r["model"] == model and r["day"] == (day.isoformat() if day else None)
    ]
    return found


async def test_llm_usage_requires_admin_session(db_client: httpx.AsyncClient) -> None:
    resp = await db_client.get(_url(DAY0, DAY1))
    assert resp.status_code == 401


async def test_regular_user_session_cannot_access_llm_usage(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    assert (await db_client.get("/me")).status_code == 200

    resp = await db_client.get(_url(DAY0, DAY1))
    assert resp.status_code == 401


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        pytest.param(DAY1, DAY0, 400, id="to-before-from"),
        # 92일(양끝 포함)까지는 받고 93일부터 막는다.
        pytest.param(DAY0, DAY0 + timedelta(days=91), 200, id="92-days-ok"),
        pytest.param(DAY0, DAY0 + timedelta(days=92), 400, id="93-days-rejected"),
    ],
)
async def test_llm_usage_date_range_limits(
    db_client: httpx.AsyncClient, db_session: AsyncSession, start: date, end: date, expected: int
) -> None:
    resp = await _admin_get(db_client, db_session, _url(start, end))
    assert resp.status_code == expected


async def test_llm_usage_aggregates_rows_ratios_and_cost(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # DAY0: 채팅 생성 4회, 스탯 판정 3회, 기억 요약 1회, 미리보기 생성 2회·미리보기 판정 1회.
    await _put(
        DAY0, "chat_generate", LITE,
        calls=4, prompt=1_000_000, cached=200_000, candidates=100_000, thoughts=50_000, total=1_150_000,
    )  # fmt: skip
    await _put(DAY0, "chat_stat_judgment", LITE, calls=3, prompt=3000, cached=1500, candidates=300, total=3300)
    await _put(DAY0, "chat_memory_summary", LITE, calls=1, prompt=500, candidates=50, total=550)
    await _put(DAY0, "preview_generate", LITE, calls=2, prompt=800, candidates=80, total=880)
    await _put(DAY0, "preview_stat_judgment", LITE, calls=1, prompt=100, candidates=10, total=110)
    # 이미지가 실린 호출 — 입력 토큰이 비어 missing 으로 세지고 total 에만 들어 있다.
    await _put(DAY0, "publish_filter_story", LITE, calls=2, candidates=100, total=5100, missing=2)
    # 단가표에 없는 모델.
    await _put(DAY0, "chat_stat_judgment", "unknown-model", calls=1, prompt=100, candidates=10, total=110)
    # DAY1: 생성 2회에 판정 2회. 판정은 있는데 생성이 없는 계열(엔딩 판정만 있는 미리보기)도 둔다.
    await _put(DAY1, "chat_generate", LITE, calls=2, prompt=2000, candidates=200, total=2200)
    await _put(DAY1, "chat_stat_judgment", LITE, calls=2, prompt=2000, candidates=200, total=2200)
    await _put(DAY1, "preview_ending_judgment", LITE, calls=1, prompt=100, candidates=10, total=110)
    # 범위 밖 날짜는 섞이지 않는다.
    await _put(DAY1 + timedelta(days=1), "chat_generate", LITE, calls=99, prompt=1, total=1)

    resp = await _admin_get(db_client, db_session, _url(DAY0, DAY1))

    assert resp.status_code == 200
    body = resp.json()
    rows, totals = body["rows"], body["totals"]

    gen0 = _row(rows, "chat_generate", day=DAY0)
    assert gen0["calls"] == 4
    assert gen0["promptTokens"] == 1_000_000
    assert gen0["cachedTokens"] == 200_000
    assert gen0["outputTokens"] == 100_000
    assert gen0["thoughtsTokens"] == 50_000
    assert gen0["totalTokens"] == 1_150_000
    assert gen0["cacheHitRate"] == pytest.approx(0.2)
    # 판정 call_site 가 아니면 비율이 없다.
    assert gen0["judgmentRatio"] is None
    # (800k 비캐시 × 0.30 + 200k 캐시 × 0.03 + (100k 출력 + 50k 사고) × 2.50) / 1M
    assert gen0["estimatedCostUsd"] == pytest.approx(0.24 + 0.006 + 0.375)

    # 채팅 판정은 같은 날 chat_generate 로, 미리보기 판정은 preview_generate 로 나눈다.
    assert _row(rows, "chat_stat_judgment", day=DAY0)["judgmentRatio"] == pytest.approx(3 / 4)
    assert _row(rows, "chat_stat_judgment", day=DAY1)["judgmentRatio"] == pytest.approx(2 / 2)
    assert _row(rows, "preview_stat_judgment", day=DAY0)["judgmentRatio"] == pytest.approx(1 / 2)
    # 분모가 0 이면 비율을 비운다(0 으로 나누지 않는다).
    assert _row(rows, "preview_ending_judgment", day=DAY1)["judgmentRatio"] is None
    assert _row(rows, "chat_memory_summary", day=DAY0)["judgmentRatio"] is None
    # 다른 모델로 돈 판정도 같은 생성 분모를 쓴다.
    assert _row(rows, "chat_stat_judgment", "unknown-model", DAY0)["judgmentRatio"] == pytest.approx(1 / 4)

    # 입력 토큰이 비면 total − 출력 − 사고로 입력을 복원해 원가를 낸다.
    publish = _row(rows, "publish_filter_story", day=DAY0)
    assert publish["missingCalls"] == 2
    assert publish["inputTokens"] == 5000
    assert publish["cacheHitRate"] is None
    assert publish["estimatedCostUsd"] == pytest.approx((5000 * 0.30 + 100 * 2.50) / 1_000_000)

    unknown = _row(rows, "chat_stat_judgment", "unknown-model", DAY0)
    assert unknown["estimatedCostUsd"] is None

    assert {r["day"] for r in rows} == {DAY0.isoformat(), DAY1.isoformat()}

    # 기간 합계 줄은 날짜를 합치고, 비율은 합계끼리 나눈다(일자 비율의 평균이 아니다).
    stat_total = _row(totals, "chat_stat_judgment")
    assert stat_total["calls"] == 5
    assert stat_total["promptTokens"] == 5000
    assert stat_total["judgmentRatio"] == pytest.approx(5 / 6)
    assert stat_total["cacheHitRate"] == pytest.approx(1500 / 5000)

    priced_total = sum(r["estimatedCostUsd"] for r in totals if r["estimatedCostUsd"] is not None)
    assert body["estimatedCostUsdTotal"] == pytest.approx(priced_total)
    assert body["unpricedCalls"] == 1

    assert body["pricesAsOf"] == "2026-10-02"
    lite_price = next(p for p in body["prices"] if p["model"] == LITE)
    assert lite_price == {
        "model": LITE,
        "inputUsdPerMillion": 0.30,
        "cachedInputUsdPerMillion": 0.03,
        "outputUsdPerMillion": 2.50,
    }


async def test_llm_usage_empty_range_returns_no_rows(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    resp = await _admin_get(db_client, db_session, _url(DAY0, DAY1))

    assert resp.status_code == 200
    body = resp.json()
    assert body["rows"] == [] and body["totals"] == []
    assert body["estimatedCostUsdTotal"] == 0
    assert body["unpricedCalls"] == 0


async def test_llm_usage_judgment_ratio_covers_every_judgment_kind(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """판정 모델을 종류별로 나눠 옮겨도 스탯·엔딩·그림 매칭 모두 판정 비율을 받는다. 종류마다 다른 모델이어도
    분모(생성 호출)는 모델을 가리지 않고 더한다."""
    await _put(DAY0, "chat_generate", LITE, calls=4)
    await _put(DAY0, "preview_generate", LITE, calls=2)
    judgments = {
        "chat_stat_judgment": ("gemini-3.1-flash-lite", 4 / 4),
        "chat_ending_judgment": ("gemini-3.1-flash-lite", 2 / 4),
        "chat_situational_image": (LITE, 1 / 4),
        "chat_media_book_image": (LITE, 3 / 4),
        "preview_stat_judgment": ("gemini-3.1-flash-lite", 2 / 2),
        "preview_ending_judgment": ("gemini-3.1-flash-lite", 1 / 2),
        "preview_media_book_image": (LITE, 1 / 2),
    }
    for call_site, (model, ratio) in judgments.items():
        await _put(DAY0, call_site, model, calls=round(ratio * (2 if call_site.startswith("preview_") else 4)))

    resp = await _admin_get(db_client, db_session, _url(DAY0, DAY0))

    assert resp.status_code == 200
    rows = resp.json()["rows"]
    for call_site, (model, ratio) in judgments.items():
        assert _row(rows, call_site, model, DAY0)["judgmentRatio"] == pytest.approx(ratio)
    assert _row(rows, "chat_generate", day=DAY0)["judgmentRatio"] is None
