"""소설 장 라우트 — 다음 장 경계 제안, 장 생성, 재생성, 마지막 장 삭제.

장 생성·재생성 라우트는 작업을 띄우는 함수(`enqueue_job`)를 기록용 페이크로 바꿔 끼운다 — 작업 실행은
`test_novelize_runner.py` 가 따로 시험하고, 여기서는 라우트가 무엇을 검사하고 어떤 작업 행을 만들어 넘기는지를 본다.
끝에서 실제 띄우기까지 한 번 이어 본다.

방은 `_open_room` 이 만든다. 메시지는 오프닝 하나 + `turns` 쌍이라, 턴으로 세면 오프닝이 1턴(사용자 줄 없음)이고
`room.turns[n]` 은 n+1 턴이다."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import timedelta
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models import ChatMessage, ChatMessageRole, Content, ModerationStatus, Novel, NovelChapter, NovelJob
from api.db.models.novel import NovelChapterRevision
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, T
from api.novelize import router as novelize_router
from api.novelize import runner
from api.novelize.prompts import NovelizeBoundaryResult
from factories import (
    Room,
    _add_chapter,
    _clear_llm_override,
    _novel_ledger,
    _novel_setup,
    _open_transaction_probe,
    _override_llm_client,
    _queue_job,
    _room_messages,
)

_CHAPTER_BODY = "비가 내리는 저녁이었다. 서진은 가방을 내려놓고 창가에 섰다.\n\n" + "도윤이 잔을 밀어 주었다. " * 20


class _NovelRouteLLM(LLMClient):
    """경계 제안은 `end_turn`·`reason` 을 돌려주거나 `error` 를 낸다. 장 생성(끝의 실제 띄우기 시험)은 `_CHAPTER_BODY`
    를 흘린다. 경계 제안이 불릴 때 열린 DB 세션 수를 `open_at_call` 에 적는다."""

    def __init__(self, *, end_turn: int = 3, reason: str = "첫날 대화가 마무리된다.", error: Exception | None = None):
        self.end_turn = end_turn
        self.reason = reason
        self.error = error
        self.boundary_calls: list[tuple[str, str, LLMCallContext]] = []
        self.open_sessions: set[int] | None = None
        self.open_at_call: list[int] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        yield _CHAPTER_BODY

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        raise AssertionError("소설화는 지시문 없는 구조화 호출을 쓰지 않는다")

    async def generate_structured_with_instruction(
        self, prompt: str, response_schema: type[T], *, system_instruction: str, usage: LLMCallContext
    ) -> T:
        self.boundary_calls.append((prompt, system_instruction, usage))
        if self.open_sessions is not None:
            self.open_at_call.append(len(self.open_sessions))
        if self.error is not None:
            raise self.error
        assert response_schema is NovelizeBoundaryResult
        return response_schema.model_validate({"end_turn": self.end_turn, "reason": self.reason})


@pytest.fixture
def llm() -> Iterator[_NovelRouteLLM]:
    fake = _NovelRouteLLM()
    _override_llm_client(fake)
    yield fake
    _clear_llm_override()


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """라우트가 띄운 작업 id. 실제로 돌리지는 않는다."""
    seen: list[uuid.UUID] = []

    async def record(_factory: Any, _llm: Any, job_id: uuid.UUID) -> None:
        seen.append(job_id)

    monkeypatch.setattr(novelize_router, "enqueue_job", record)
    return seen


async def _job_row(db: AsyncSession, job_id: uuid.UUID) -> NovelJob:
    return await db.get_one(NovelJob, job_id, populate_existing=True)


async def _restrict(db: AsyncSession, novel_id: uuid.UUID) -> None:
    content_id = (await db.get_one(Novel, novel_id)).content_id
    await db.execute(
        sa.update(Content).where(Content.id == content_id).values(moderation_status=ModerationStatus.RESTRICTED)
    )
    await db.commit()


async def _forget_room(db: AsyncSession, novel_id: uuid.UUID) -> None:
    """방이 지워진 소설과 같은 상태(방 FK 가 SET NULL 로 빈 것)를 만든다."""
    await db.execute(sa.update(Novel).where(Novel.id == novel_id).values(chat_room_id=None))
    await db.commit()


# ── 경계 제안 ───────────────────────────────────────────────────────────────
async def test_first_proposal_starts_at_the_opening_lists_turns_and_maps_the_suggestion(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _NovelRouteLLM,
    committing_request_session: None,
) -> None:
    """요청 세션을 요청마다 새로 여는 픽스처를 쓴다 — 테스트 세션을 그대로 쓰면 그 세션의 트랜잭션이 측정 전에
    시작돼 있어 "모델 호출 때 열린 세션 수"가 커밋 여부와 상관없이 0 으로 나온다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    opening = messages[0]

    with _open_transaction_probe() as open_sessions:
        llm.open_sessions = open_sessions
        resp = await db_client.post(f"/novels/{novel_id}/chapter-proposal")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["startMessageId"] == str(opening.id)
    expected = [opening, room.turns[1][1], room.turns[2][1], room.turns[3][1]]
    assert [(c["messageId"], c["ordinal"]) for c in body["candidates"]] == [
        (str(m.id), n) for n, m in enumerate(expected, start=1)
    ]
    assert body["candidates"][1]["excerpt"].startswith("[A01]")
    assert body["suggestion"] == {"endMessageId": str(room.turns[2][1].id), "reason": "첫날 대화가 마무리된다."}
    assert body["cost"] == 20
    (prompt, system_instruction, usage) = llm.boundary_calls[0]
    assert (usage.call_site, usage.user_id, usage.room_id) == ("novelize_boundary", room.user_id, room.room_id)
    assert "[턴 2] 사용자: [U01]" in prompt and "[턴 4] 캐릭터: [A03]" in prompt
    assert "[턴 1]부터 [턴 4]까지" in prompt
    assert "편집자" in system_instruction
    # 모델을 부르는 동안 요청 세션도 커넥션을 쥐지 않는다(커밋해 돌려준 뒤 부른다).
    assert llm.open_at_call == [0]
    assert await _novel_ledger(db_session, room.user_id) == []


async def test_proposal_caps_the_candidates_at_the_turn_limit_and_clamps_a_wild_suggestion(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _NovelRouteLLM
) -> None:
    monkeypatch.setattr(settings, "novelize_chapter_max_turns", 2)
    llm.end_turn = 9
    llm.reason = "  " + "가" * 300
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)

    body = (await db_client.post(f"/novels/{novel_id}/chapter-proposal")).json()

    assert [c["messageId"] for c in body["candidates"]] == [
        str((await _room_messages(db_session, room.room_id))[0].id),
        str(room.turns[1][1].id),
    ]
    assert body["suggestion"]["endMessageId"] == str(room.turns[1][1].id)
    assert body["suggestion"]["reason"] == "가" * 100
    assert "[턴 1]부터 [턴 2]까지" in llm.boundary_calls[0][0]


async def test_failed_proposal_still_answers_200_with_the_candidates(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _NovelRouteLLM
) -> None:
    llm.error = LLMClientError("boom")
    _room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)

    resp = await db_client.post(f"/novels/{novel_id}/chapter-proposal")

    assert resp.status_code == 200, resp.text
    assert resp.json()["suggestion"] is None
    assert len(resp.json()["candidates"]) == 4


async def test_next_proposal_starts_right_after_the_last_chapter(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _NovelRouteLLM
) -> None:
    llm.end_turn = 1
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    await _add_chapter(db_session, novel_id, room, messages[0], room.turns[1][1])

    body = (await db_client.post(f"/novels/{novel_id}/chapter-proposal")).json()

    assert body["startMessageId"] == str(room.turns[2][0].id)
    assert [c["messageId"] for c in body["candidates"]] == [str(room.turns[2][1].id), str(room.turns[3][1].id)]
    assert body["suggestion"]["endMessageId"] == str(room.turns[2][1].id)
    assert "[턴 1] 사용자: [U02]" in llm.boundary_calls[0][0]


async def test_proposal_start_uses_the_stored_end_key_after_the_end_message_is_deleted(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _NovelRouteLLM
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    await _add_chapter(db_session, novel_id, room, messages[0], room.turns[2][1])
    await db_session.execute(sa.delete(ChatMessage).where(ChatMessage.id == room.turns[2][1].id))
    await db_session.commit()

    body = (await db_client.post(f"/novels/{novel_id}/chapter-proposal")).json()

    assert body["startMessageId"] == str(room.turns[3][0].id)


async def test_proposal_after_a_room_reset_starts_at_the_new_opening(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _NovelRouteLLM
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    await _add_chapter(db_session, novel_id, room, messages[0], room.turns[3][1])
    assert (await db_client.post(f"/chat-rooms/{room.room_id}/reset")).status_code == 200

    body = (await db_client.post(f"/novels/{novel_id}/chapter-proposal")).json()

    (new_opening,) = await _room_messages(db_session, room.room_id)
    assert new_opening.id != messages[0].id
    assert body["startMessageId"] == str(new_opening.id)
    assert [c["messageId"] for c in body["candidates"]] == [str(new_opening.id)]


async def test_proposal_with_nothing_new_is_409_without_calling_the_model(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _NovelRouteLLM
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    await _add_chapter(db_session, novel_id, room, messages[0], room.turns[3][1])

    covered = await db_client.post(f"/novels/{novel_id}/chapter-proposal")
    # 응답이 아직 없는 사용자 메시지만 새로 있어도 장으로 만들 턴이 없다.
    db_session.add(
        ChatMessage(
            chat_room_id=room.room_id,
            role=ChatMessageRole.USER,
            content="아직 답 없음",
            created_at=room.base + timedelta(minutes=5),
        )
    )
    await db_session.commit()
    dangling = await db_client.post(f"/novels/{novel_id}/chapter-proposal")

    assert [covered.status_code, dangling.status_code] == [409, 409]
    assert dangling.json()["detail"] == {"code": "NOVEL_NOTHING_NEW"}
    assert llm.boundary_calls == []


async def test_proposal_is_rate_limited_per_hour_without_an_exemption(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _NovelRouteLLM
) -> None:
    monkeypatch.setattr(settings, "novelize_proposal_hourly_limit", 2)
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    await db_session.execute(sa.text("UPDATE users SET rate_limit_exempt = true WHERE id = :u"), {"u": room.user_id})
    await db_session.commit()

    statuses = [(await db_client.post(f"/novels/{novel_id}/chapter-proposal")).status_code for _ in range(3)]
    over = await db_client.post(f"/novels/{novel_id}/chapter-proposal")

    assert statuses == [200, 200, 429]
    assert over.json()["detail"]["code"] == "USER_LIMIT" and over.json()["detail"]["window"] == "novelize"
    assert len(llm.boundary_calls) == 2


# ── 모델을 부르는 세 라우트의 공통 거절 ─────────────────────────────────────
async def _model_route_requests(
    db_client: httpx.AsyncClient, db_session: AsyncSession, room: Room, novel_id: uuid.UUID
) -> list[httpx.Response]:
    messages = await _room_messages(db_session, room.room_id)
    chapter = await _add_chapter(db_session, novel_id, room, messages[0], room.turns[1][1])
    return [
        await db_client.post(f"/novels/{novel_id}/chapter-proposal"),
        await db_client.post(
            f"/novels/{novel_id}/chapters", json={"endMessageId": str(room.turns[2][1].id), "expectedCost": 20}
        ),
        await db_client.post(f"/novels/{novel_id}/chapters/{chapter.id}/regenerate", json={"expectedCost": 20}),
    ]


async def test_restricted_work_blocks_the_model_routes_before_any_charge(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _NovelRouteLLM,
    enqueued: list[uuid.UUID],
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    await _restrict(db_session, novel_id)

    responses = await _model_route_requests(db_client, db_session, room, novel_id)

    assert [(r.status_code, r.json()["detail"]) for r in responses] == [(403, {"code": "CONTENT_RESTRICTED"})] * 3
    assert (llm.boundary_calls, enqueued) == ([], [])
    assert await _novel_ledger(db_session, room.user_id) == []
    # 읽기는 막지 않는다.
    assert (await db_client.get(f"/novels/{novel_id}")).status_code == 200


async def test_missing_work_row_is_treated_as_restricted(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _NovelRouteLLM
) -> None:
    _room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    await db_session.execute(sa.update(Novel).where(Novel.id == novel_id).values(content_id=uuid.uuid4()))
    await db_session.commit()

    resp = await db_client.post(f"/novels/{novel_id}/chapter-proposal")

    assert resp.status_code == 403 and resp.json()["detail"] == {"code": "CONTENT_RESTRICTED"}


async def test_novel_whose_room_is_gone_cannot_get_new_chapters(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _NovelRouteLLM,
    enqueued: list[uuid.UUID],
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    chapter = await _add_chapter(db_session, novel_id, room, messages[0], room.turns[1][1])
    await _forget_room(db_session, novel_id)

    responses = [
        await db_client.post(f"/novels/{novel_id}/chapter-proposal"),
        await db_client.post(
            f"/novels/{novel_id}/chapters", json={"endMessageId": str(room.turns[2][1].id), "expectedCost": 20}
        ),
        await db_client.post(f"/novels/{novel_id}/chapters/{chapter.id}/regenerate", json={"expectedCost": 20}),
    ]

    assert [(r.status_code, r.json()["detail"]) for r in responses] == [(409, {"code": "NOVEL_ROOM_GONE"})] * 3
    assert await _novel_ledger(db_session, room.user_id) == []


# ── 장 생성 ─────────────────────────────────────────────────────────────────
async def test_creating_a_chapter_charges_queues_a_job_from_the_server_computed_start(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _NovelRouteLLM,
    enqueued: list[uuid.UUID],
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    opening = (await _room_messages(db_session, room.room_id))[0]
    end = room.turns[2][1]

    resp = await db_client.post(f"/novels/{novel_id}/chapters", json={"endMessageId": str(end.id), "expectedCost": 20})

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert (body["kind"], body["status"], body["chargedAmount"], body["refunded"]) == (
        "chapter_generate",
        "queued",
        20,
        False,
    )
    job = await _job_row(db_session, uuid.UUID(body["id"]))
    assert (job.start_message_id, job.end_message_id, job.end_message_created_at) == (
        opening.id,
        end.id,
        end.created_at,
    )
    assert enqueued == [job.id]
    assert await _novel_ledger(db_session, room.user_id) == [("novelize_spend", -20)]


@pytest.mark.parametrize("pick", ["user_message", "beyond_limit", "unknown"])
async def test_chapter_end_outside_the_candidate_turns_is_422_without_a_charge(
    pick: str,
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _NovelRouteLLM,
    enqueued: list[uuid.UUID],
) -> None:
    monkeypatch.setattr(settings, "novelize_chapter_max_turns", 2)
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    end_id = {
        "user_message": room.turns[1][0].id,
        "beyond_limit": room.turns[2][1].id,
        "unknown": uuid.uuid4(),
    }[pick]

    resp = await db_client.post(f"/novels/{novel_id}/chapters", json={"endMessageId": str(end_id), "expectedCost": 20})

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == {"code": "NOVEL_CHAPTER_END_INVALID"}
    assert (enqueued, await _novel_ledger(db_session, room.user_id)) == ([], [])


async def test_chapter_without_a_protagonist_name_is_422_until_one_is_given(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _NovelRouteLLM,
    enqueued: list[uuid.UUID],
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, persona=None)
    payload = {"endMessageId": str(room.turns[1][1].id), "expectedCost": 20}

    missing = await db_client.post(f"/novels/{novel_id}/chapters", json=payload)
    await db_client.put(f"/novels/{novel_id}/protagonist-name", json={"protagonistName": "서진"})
    given = await db_client.post(f"/novels/{novel_id}/chapters", json=payload)

    assert missing.status_code == 422 and missing.json()["detail"] == {"code": "NOVEL_PROTAGONIST_NAME_REQUIRED"}
    assert given.status_code == 202
    assert len(enqueued) == 1
    assert await _novel_ledger(db_session, room.user_id) == [("novelize_spend", -20)]


async def test_chapter_with_a_stale_price_is_409_with_the_current_one(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _NovelRouteLLM,
    enqueued: list[uuid.UUID],
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)

    resp = await db_client.post(
        f"/novels/{novel_id}/chapters", json={"endMessageId": str(room.turns[1][1].id), "expectedCost": 15}
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == {"code": "NOVELIZE_PRICE_CHANGED", "currentCost": 20}
    assert (enqueued, await _novel_ledger(db_session, room.user_id)) == ([], [])


async def test_dead_job_is_expired_before_a_new_chapter_instead_of_blocking_it(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _NovelRouteLLM,
    enqueued: list[uuid.UUID],
    committing_request_session: None,
) -> None:
    """진행 중 409 는 작업 생성이 롤백하며 낸다 — 요청 세션이 테스트 셋업과 같은 트랜잭션이면 그 롤백이 셋업까지
    지우므로 요청마다 SAVEPOINT 세션을 쓴다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    live_id = (await _queue_job(db_session, novel_id, messages[0], room.turns[1][1])).id
    payload = {"endMessageId": str(room.turns[1][1].id), "expectedCost": 20}

    blocked = await db_client.post(f"/novels/{novel_id}/chapters", json=payload)
    await db_session.execute(
        sa.update(NovelJob).where(NovelJob.id == live_id).values(heartbeat_at=sa.func.now() - timedelta(hours=1))
    )
    await db_session.commit()
    after_expiry = await db_client.post(f"/novels/{novel_id}/chapters", json=payload)

    assert blocked.status_code == 409 and blocked.json()["detail"] == {"code": "NOVEL_JOB_IN_PROGRESS"}
    assert after_expiry.status_code == 202, after_expiry.text
    assert (await _job_row(db_session, live_id)).failure_code == "expired"
    assert await _novel_ledger(db_session, room.user_id) == [
        ("novelize_spend", -20),
        ("novelize_spend", -20),
        ("novelize_refund", 20),
    ]


async def test_created_chapter_job_really_runs_and_the_poll_sees_the_chapter(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _NovelRouteLLM
) -> None:
    monkeypatch.setattr(settings, "novelize_heartbeat_interval_seconds", 3600)
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)

    created = await db_client.post(
        f"/novels/{novel_id}/chapters", json={"endMessageId": str(room.turns[1][1].id), "expectedCost": 20}
    )
    # 테스트 커넥션은 하나라 백그라운드 작업이 끝나기 전에 같은 커넥션으로 읽으면 부딪힌다 — 태스크를 기다린다.
    await asyncio.gather(*runner._background_tasks)
    polled = await db_client.get(f"/novels/{novel_id}/jobs/{created.json()['id']}")
    detail = await db_client.get(f"/novels/{novel_id}")

    assert polled.json()["status"] == "succeeded", polled.text
    assert [c["ordinal"] for c in detail.json()["chapters"]] == [1]
    assert detail.json()["activeJob"] is None


# ── 재생성 ──────────────────────────────────────────────────────────────────
async def test_regenerating_an_earlier_chapter_queues_a_job_over_the_same_segment(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _NovelRouteLLM,
    enqueued: list[uuid.UUID],
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    first = await _add_chapter(db_session, novel_id, room, messages[0], room.turns[1][1])
    await _add_chapter(db_session, novel_id, room, room.turns[2][0], room.turns[3][1])

    resp = await db_client.post(f"/novels/{novel_id}/chapters/{first.id}/regenerate", json={"expectedCost": 20})

    assert resp.status_code == 202, resp.text
    job = await _job_row(db_session, uuid.UUID(resp.json()["id"]))
    assert (job.kind, job.chapter_id, job.start_message_id, job.end_message_id) == (
        "chapter_regenerate",
        first.id,
        messages[0].id,
        room.turns[1][1].id,
    )
    assert enqueued == [job.id]


@pytest.mark.parametrize("change", ["user_edit", "reply_regenerated", "message_deleted"])
async def test_regenerating_after_the_source_changed_is_409_without_a_charge(
    change: str,
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _NovelRouteLLM,
    enqueued: list[uuid.UUID],
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    chapter = await _add_chapter(db_session, novel_id, room, messages[0], room.turns[2][1])
    if change == "user_edit":
        await db_session.execute(
            sa.update(ChatMessage).where(ChatMessage.id == room.turns[1][0].id).values(content="고친 말")
        )
    elif change == "reply_regenerated":
        await db_session.execute(
            sa.update(ChatMessage).where(ChatMessage.id == room.turns[2][1].id).values(content="다시 만든 응답")
        )
    else:
        await db_session.execute(sa.delete(ChatMessage).where(ChatMessage.id == room.turns[1][1].id))
    await db_session.commit()

    resp = await db_client.post(f"/novels/{novel_id}/chapters/{chapter.id}/regenerate", json={"expectedCost": 20})

    assert resp.status_code == 409 and resp.json()["detail"] == {"code": "NOVEL_SOURCE_CHANGED"}
    assert (enqueued, await _novel_ledger(db_session, room.user_id)) == ([], [])


async def test_regenerating_a_chapter_of_another_novel_is_404(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _NovelRouteLLM,
    enqueued: list[uuid.UUID],
) -> None:
    other_room, other_id = await _novel_setup(db_client, db_session, monkeypatch)
    other_chapter = await _add_chapter(
        db_session, other_id, other_room, (await _room_messages(db_session, other_room.room_id))[0], other_room.turns[1][1]
    )
    _room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)

    resp = await db_client.post(f"/novels/{novel_id}/chapters/{other_chapter.id}/regenerate", json={"expectedCost": 20})

    assert resp.status_code == 404 and resp.json()["detail"] == {"code": "NOVEL_CHAPTER_NOT_FOUND"}


# ── 마지막 장 삭제 ──────────────────────────────────────────────────────────
async def test_deleting_the_last_chapter_keeps_its_jobs_and_rewinds_the_next_start(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, llm: _NovelRouteLLM
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    first = await _add_chapter(db_session, novel_id, room, messages[0], room.turns[1][1])
    last = await _add_chapter(db_session, novel_id, room, room.turns[2][0], room.turns[3][1])
    revision = await db_session.scalar(sa.select(NovelChapterRevision).where(NovelChapterRevision.chapter_id == last.id))
    assert revision is not None
    job = NovelJob(
        novel_id=novel_id,
        user_id=room.user_id,
        kind="ai_edit",
        status="succeeded",
        chapter_id=last.id,
        base_revision_id=revision.id,
        result_revision_id=revision.id,
        charged_amount=5,
    )
    db_session.add(job)
    await db_session.commit()

    resp = await db_client.delete(f"/novels/{novel_id}/chapters/{last.id}")
    proposal = await db_client.post(f"/novels/{novel_id}/chapter-proposal")

    assert resp.status_code == 204, resp.text
    remaining = (await db_session.scalars(sa.select(NovelChapter.id).where(NovelChapter.novel_id == novel_id))).all()
    assert remaining == [first.id]
    revisions = await db_session.scalar(
        sa.select(sa.func.count()).select_from(NovelChapterRevision).where(NovelChapterRevision.chapter_id == last.id)
    )
    assert revisions == 0
    kept = await _job_row(db_session, job.id)
    assert (kept.chapter_id, kept.base_revision_id, kept.result_revision_id) == (None, None, None)
    assert proposal.json()["startMessageId"] == str(room.turns[2][0].id)


async def test_only_the_last_chapter_can_be_deleted_and_not_while_a_job_runs(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch)
    messages = await _room_messages(db_session, room.room_id)
    first = await _add_chapter(db_session, novel_id, room, messages[0], room.turns[1][1])
    last = await _add_chapter(db_session, novel_id, room, room.turns[2][0], room.turns[2][1])

    not_last = await db_client.delete(f"/novels/{novel_id}/chapters/{first.id}")
    await _queue_job(db_session, novel_id, room.turns[3][0], room.turns[3][1])
    running = await db_client.delete(f"/novels/{novel_id}/chapters/{last.id}")
    missing = await db_client.delete(f"/novels/{novel_id}/chapters/{uuid.uuid4()}")

    assert not_last.status_code == 409 and not_last.json()["detail"] == {"code": "NOVEL_CHAPTER_NOT_LAST"}
    assert running.status_code == 409 and running.json()["detail"] == {"code": "NOVEL_JOB_IN_PROGRESS"}
    assert missing.status_code == 404 and missing.json()["detail"] == {"code": "NOVEL_CHAPTER_NOT_FOUND"}
    count = await db_session.scalar(
        sa.select(sa.func.count()).select_from(NovelChapter).where(NovelChapter.novel_id == novel_id)
    )
    assert count == 2
