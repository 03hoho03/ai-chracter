"""`scripts/novel_job_cost_report.py` — 소설 작업 행의 호출 기록(`novel_jobs.llm_calls`)으로 작업 종류 × 모델별 원가 분포를 내는 읽기
전용 스크립트."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import novel_job_cost_report as script
from api.core.rate_limit import KST
from api.db.models import ChatRoom, Novel, NovelJob
from api.llm.pricing import estimate_cost_usd
from factories import _make_user_with_clover_lot, _open_room, _queue_job, _room_messages

_OPUS = "claude-opus-5-5"


def _call(model: str, *, prompt: int | None = 1_000, output: int = 100, failure: str | None = None) -> dict[str, Any]:
    """소설 작업이 남기는 원소 꼴. `prompt` 가 None 이면 사용량 없이 끝난 호출(토큰 칸이 없다)이다."""
    usage: dict[str, Any] = (
        {}
        if prompt is None
        else {
            "promptTokens": prompt,
            "cachedTokens": 0,
            "cacheWriteTokens": None,
            "outputTokens": output,
            "thoughtsTokens": None,
        }
    )
    return {
        "callSite": "novelize_chapter",
        "model": model,
        **usage,
        "backend": "anthropic",
        "durationMs": 1200,
        "promptSetId": None,
        "stage": "legacy_generate",
        "routeSource": None,
        "failure": failure,
    }


def _row(
    kind: str, model: str | None, status: str, calls: list[dict[str, Any]], *, charged: int, refunded: int | None = None
) -> script.JobRow:
    return script.JobRow(
        kind=kind,
        model=model,
        status=status,
        failure_code=None if status == "succeeded" else "llm_error",
        charged_amount=charged,
        refunded_amount=refunded,
        llm_calls=calls,
    )


def _usd(model: str, *, prompt: int, output: int) -> float:
    value = estimate_cost_usd(model, input_tokens=prompt, cached_tokens=0, output_tokens=output, thoughts_tokens=0)
    assert value is not None
    return value


def test_jobs_are_grouped_by_kind_and_model_with_per_job_cost_and_failure_counts() -> None:
    """작업 원가는 그 행의 원소 합이고, 종류 × 모델 묶음마다 작업 수·성공/실패·원가 분포·차감과 환불 합을 낸다. 사용량 없는 원소는
    `missing`, 단가표에 없는 모델의 원소는 `unpriced` 로 세고, 그런 원소가 든 작업은 분포에서 빼 따로 센다. 실패 원소의 사유는
    따로 모은다. 빨강 조건: 원소 합이 아닌 첫 원소만 치거나, 단가 없는 작업이 0 원으로 분포에 섞이거나, 차감에서 환불을 빼먹는다."""
    rows = [
        _row("chapter_generate", "opus", "succeeded", [_call(_OPUS), _call(_OPUS, prompt=3_000)], charged=170),
        _row("chapter_generate", "opus", "failed", [_call(_OPUS, prompt=None, failure="blocked")], charged=170, refunded=170),
        _row("chapter_generate", "opus", "failed", [_call("fixture-unpriced")], charged=170, refunded=170),
        _row("outline_generate", None, "succeeded", [_call(_OPUS, failure="truncated")], charged=10),
    ]

    summary = script.summarize(rows)

    groups = {(g.kind, g.model): g for g in summary.groups}
    chapter = groups[("chapter_generate", "opus")]
    first = _usd(_OPUS, prompt=1_000, output=100) + _usd(_OPUS, prompt=3_000, output=100)
    assert (chapter.jobs, chapter.succeeded, chapter.failed, chapter.calls) == (3, 1, 2, 4)
    assert (chapter.missing, chapter.unpriced, chapter.unpriced_jobs) == (1, 1, 1)
    assert chapter.total_usd == pytest.approx(first)
    assert chapter.p50_usd == 0.0
    assert chapter.max_usd == pytest.approx(first)
    assert (chapter.charged, chapter.refunded) == (510, 340)
    outline = groups[("outline_generate", "-")]
    assert (outline.jobs, outline.calls, outline.charged, outline.refunded) == (1, 1, 10, 0)
    assert summary.failures == {"blocked": 1, "truncated": 1}

    report = script.format_report(summary)
    assert report.splitlines()[0].split() == [
        "kind",
        "model",
        "jobs",
        "ok",
        "failed",
        "calls",
        "missing",
        "unpriced",
        "total_usd",
        "p50_usd",
        "p90_usd",
        "max_usd",
        "charged",
        "refunded",
    ]
    assert "call failures blocked=1 truncated=1" in report


@pytest.mark.usefixtures("novel_prices_for_flow_tests")
async def test_read_jobs_returns_the_rows_made_in_the_kst_range_and_the_filters(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """KST 날짜 범위(양끝 포함)와 종류·모델 거르개로 작업 행을 읽는다. 빨강 조건: 범위를 UTC 로 잘라 KST 자정 근처 행이 빠지거나,
    거르개가 무시된다."""
    owner = await _make_user_with_clover_lot(db_session, clover_balance=200)
    room = await _open_room(db_client, db_session, turns=2, lane="character", user=owner)
    chat_room = await db_session.get_one(ChatRoom, room.room_id)
    novel = Novel(
        user_id=owner.id,
        chat_room_id=room.room_id,
        content_id=chat_room.content_id,
        content_type="character",
        content_title="원작",
        character_name="캐릭터",
        protagonist_name="서진",
    )
    db_session.add(novel)
    await db_session.commit()
    messages = await _room_messages(db_session, room.room_id)
    job = await _queue_job(db_session, novel.id, messages[0], room.turns[1][1])
    # KST 10월 20일 0시 30분 = UTC 10월 19일 15시 30분 — UTC 로 자르면 전날로 빠진다.
    made = datetime(2026, 10, 20, 0, 30, tzinfo=KST)
    await db_session.execute(
        sa.update(NovelJob)
        .where(NovelJob.id == job.id)
        .values(created_at=made.astimezone(UTC), model="opus", llm_calls=[_call(_OPUS)])
    )
    await db_session.commit()
    day = date(2026, 10, 20)

    inside = await script.read_jobs(db_session, day, day, kind=None, model=None)
    filtered = await script.read_jobs(db_session, day, day, kind="chapter_generate", model="opus")
    other_kind = await script.read_jobs(db_session, day, day, kind="ai_edit", model=None)
    day_before = await script.read_jobs(db_session, day - timedelta(days=1), day - timedelta(days=1), kind=None, model=None)

    assert [(r.kind, r.model, r.status, r.charged_amount, r.llm_calls) for r in inside] == [
        ("chapter_generate", "opus", "queued", 40, [_call(_OPUS)])
    ]
    assert filtered == inside
    assert (other_kind, day_before) == ([], [])
