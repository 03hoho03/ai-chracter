"""작가의 소설화 허락(`contents.novel_permission`)과 소설의 집필권 잠금이 소설 라우트와 방 응답에 미치는 것.

권리는 첫 화가 저장된 순간 생긴다(집필권 잠금). 잠긴 소설은 작가가 허락을 나중에 낮춰도 다음 화·연쇄·다시 만들기·AI
수정·읽기가 그대로다 — 화를 다 지워도 잠금은 남는다. 잠기기 전의 소설(빈 소설, 또는 잠금 칸을 모르는 옛 코드가 화만
남긴 소설)은 아무 권리도 선점하지 않아, 남의 작품이 허용 안 함이면 모델을 부르는 경로 여섯(경계 제안·화 생성·연쇄 견적·
연쇄·다시 만들기·AI 수정)이 모두 차감·모델 호출 전에 403 이다. 작가 본인 작품은 잠금과 무관하게 언제나 된다.

예외 하나: 잠금은 없는데 그 소설에 성공한 화 생성 작업이 있으면, 잠금 칸을 모르는 옛 코드가 첫 화를 저장한 것이다
(배포가 겹치는 동안). 그때는 거절하지 않고 그 자리에서 출처 `backfill`·권한 모름으로 잠그고 통과시킨다.

허락은 소설을 만든 **뒤에** 바꾼다. 작업을 띄우는 함수는 기록 없이 버리는 페이크로 바꿔 끼운다 — 여기서는 라우트가
받아들이는지(2xx)·거절하는지만 본다. 모델 클라이언트는 불린 횟수만 세고 실패로 답한다(경계 제안은 제안 없이 200)."""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clover
from api.db.models import ChatRoom, Content, Novel, NovelChapter, NovelChapterRevision, NovelJob, User
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, T
from api.novelize import router as novelize_router
from factories import (
    Room,
    _add_chapter,
    _allow_novelize,
    _clear_llm_override,
    _lock_novel,
    _make_user,
    _novel_ledger,
    _novel_setup,
    _open_room,
    _override_llm_client,
    _room_messages,
)

pytestmark = pytest.mark.usefixtures("novel_prices_for_flow_tests")

_PERMISSIONS = ("forbidden", "private", "public")
_ACTORS = ("owner", "other")
_FORBIDDEN = (403, {"code": "CONTENT_NOVELIZE_FORBIDDEN"})


class _CountingLLM(LLMClient):
    """불린 횟수만 센다. 부르면 공급자 실패로 답한다 — 경계 제안은 그 실패를 제안 없음(200)으로 받는다."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.calls += 1
        raise LLMClientError("모델을 부르지 않는 테스트")
        yield ""  # pragma: no cover

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.calls += 1
        raise LLMClientError("모델을 부르지 않는 테스트")

    async def generate_structured_with_instruction(
        self, prompt: str, response_schema: type[T], *, system_instruction: str, usage: LLMCallContext
    ) -> T:
        self.calls += 1
        raise LLMClientError("모델을 부르지 않는 테스트")


@pytest.fixture(autouse=True)
def _jobs_not_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """작업은 띄우지 않는다(라우트는 작업을 넣기만 한다)."""

    async def drop(_factory: Any, _llm: Any, _job_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr(novelize_router, "enqueue_job", drop)
    monkeypatch.setattr(novelize_router, "enqueue_chain_job", drop)


@pytest.fixture(autouse=True)
def llm() -> Iterator[_CountingLLM]:
    fake = _CountingLLM()
    _override_llm_client(fake)
    yield fake
    _clear_llm_override()


async def _set_work(db_session: AsyncSession, room_id: uuid.UUID, *, actor: str, permission: str) -> None:
    """방의 원작에 허락을 걸고, `actor` 가 "other" 면 원작의 작가를 다른 회원으로 바꾼다(방 주인은 그대로)."""
    content_id = await db_session.scalar(sa.select(ChatRoom.content_id).where(ChatRoom.id == room_id))
    values: dict[str, object] = {"novel_permission": permission}
    if actor == "other":
        creator = _make_user()
        db_session.add(creator)
        await db_session.flush()
        values["creator_user_id"] = creator.id
    await db_session.execute(sa.update(Content).where(Content.id == content_id).values(**values))
    await db_session.commit()


async def _room_without_novel(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, *, actor: str, permission: str
) -> Room:
    room = await _open_room(db_client, db_session, turns=1)
    await _allow_novelize(db_session, monkeypatch, room.user_id)
    await _set_work(db_session, room.room_id, actor=actor, permission=permission)
    return room


async def _empty_novel(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, *, actor: str, permission: str
) -> tuple[Room, uuid.UUID]:
    """3턴 방의 빈 소설(화 0, 잠금 없음)을 만든 **뒤** 허락을 건다. 잔액은 연쇄 한 번을 낼 만큼 넉넉하다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=3)
    await clover.grant(db_session, user_id=room.user_id, amount=2000, kind="admin_grant")
    await db_session.commit()
    await _set_work(db_session, room.room_id, actor=actor, permission=permission)
    return room, novel_id


async def _novel_with_chapter(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    *,
    actor: str,
    permission: str,
    locked: bool = True,
) -> tuple[Room, uuid.UUID, uuid.UUID]:
    """3턴 방의 소설(첫 화 하나)을 만든 **뒤** 허락을 건다. 잔액은 연쇄 한 번을 낼 만큼 넉넉하다. `locked` 면 첫 화를
    실제로 저장했을 때처럼 잠금도 함께 쓴다(그때 허락은 나만 보는 소설이었다). 아니면 화만 있고 잠금이 없다 — 잠금 칸을
    모르는 옛 코드가 첫 화를 저장한 상태다."""
    room, novel_id = await _novel_setup(db_client, db_session, monkeypatch, turns=3)
    await clover.grant(db_session, user_id=room.user_id, amount=2000, kind="admin_grant")
    messages = await _room_messages(db_session, room.room_id)
    chapter = await _add_chapter(db_session, novel_id, room, messages[0], room.turns[1][1])
    if locked:
        await _lock_novel(db_session, novel_id, permission="private")
    await _set_work(db_session, room.room_id, actor=actor, permission=permission)
    return room, novel_id, chapter.id


async def _request(
    action: str,
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    room: Room,
    novel_id: uuid.UUID,
    chapter_id: uuid.UUID | None,
) -> httpx.Response:
    if action == "open_existing":
        return await db_client.post(f"/chat-rooms/{room.room_id}/novel")
    if action == "proposal":
        return await db_client.post(f"/novels/{novel_id}/chapter-proposal")
    if action == "next_chapter":
        return await db_client.post(
            f"/novels/{novel_id}/chapters", json={"endMessageId": str(room.turns[2][1].id), "expectedCost": 40}
        )
    if action == "chain_estimate":
        return await db_client.get(f"/novels/{novel_id}/chain-estimate")
    if action == "chain":
        return await db_client.post(
            f"/novels/{novel_id}/chain", json={"model": "gemini", "expectedCost": 120, "maxBatches": 1}
        )
    if action == "read":
        return await db_client.get(f"/novels/{novel_id}")
    assert chapter_id is not None
    if action == "regenerate":
        return await db_client.post(f"/novels/{novel_id}/chapters/{chapter_id}/regenerate", json={"expectedCost": 40})
    assert action == "ai_edit"
    revision_id = await db_session.scalar(
        sa.select(NovelChapterRevision.id).where(NovelChapterRevision.chapter_id == chapter_id)
    )
    return await db_client.post(
        f"/novels/{novel_id}/chapters/{chapter_id}/ai-edits",
        json={
            "baseRevisionId": str(revision_id),
            "paragraphStart": 0,
            "paragraphEnd": 0,
            "instruction": "더 쓸쓸하게",
            "expectedCost": 20,
        },
    )


# 모델을 부르는 경로 여섯과 받아들였을 때의 상태 코드.
_MODEL_ROUTES = {
    "proposal": 200,
    "next_chapter": 202,
    "chain_estimate": 200,
    "chain": 202,
    "regenerate": 202,
    "ai_edit": 202,
}
# 화가 없어도 부를 수 있는 경로. 다시 만들기·AI 수정은 고칠 화가 있어야 한다.
_ROUTES_WITHOUT_A_CHAPTER = ("proposal", "next_chapter", "chain_estimate", "chain")

_EXISTING_NOVEL_ACTIONS = {"open_existing": 200, "read": 200, **_MODEL_ROUTES}


async def _job_count(db_session: AsyncSession, novel_id: uuid.UUID) -> int:
    return int(
        await db_session.scalar(sa.select(sa.func.count()).select_from(NovelJob).where(NovelJob.novel_id == novel_id))
        or 0
    )


async def _balance(db_session: AsyncSession, user_id: uuid.UUID) -> int:
    return int(await db_session.scalar(sa.select(User.clover_balance).where(User.id == user_id)) or 0)


async def _lock(db_session: AsyncSession, novel_id: uuid.UUID) -> tuple[object, ...]:
    novel = await db_session.scalar(
        sa.select(Novel).where(Novel.id == novel_id).execution_options(populate_existing=True)
    )
    assert novel is not None
    return (
        novel.writing_locked_at,
        novel.writing_lock_source,
        novel.writing_lock_permission,
        novel.writing_lock_content_version_id,
    )


async def _batch_of(db_session: AsyncSession, chapter_id: uuid.UUID) -> uuid.UUID:
    batch_id = await db_session.scalar(sa.select(NovelChapter.batch_id).where(NovelChapter.id == chapter_id))
    assert batch_id is not None
    return batch_id


async def _add_finished_chapter_job(db_session: AsyncSession, novel_id: uuid.UUID, status: str) -> None:
    """끝난 화 생성 작업 행 하나(차감 0). 성공이면 그 소설에 첫 화가 한 번은 저장됐다는 기록이다."""
    novel = await db_session.get_one(Novel, novel_id)
    db_session.add(
        NovelJob(
            novel_id=novel_id,
            user_id=novel.user_id,
            kind="chapter_generate",
            status=status,
            charged_amount=0,
            failure_code="internal" if status == "failed" else None,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
    )
    await db_session.commit()


@pytest.mark.parametrize("actor", _ACTORS)
@pytest.mark.parametrize("permission", _PERMISSIONS)
async def test_new_novel_is_refused_only_to_someone_else_when_the_creator_forbids_it(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    permission: str,
    actor: str,
) -> None:
    """작가 본인은 허락과 무관하게 자기 작품의 대화를 소설로 만든다. 403 은 "허용 안 함 × 다른 회원"뿐이고 소설 행을
    남기지 않는다."""
    room = await _room_without_novel(db_client, db_session, monkeypatch, actor=actor, permission=permission)

    resp = await db_client.post(f"/chat-rooms/{room.room_id}/novel")

    novels = await db_session.scalar(sa.select(sa.func.count()).select_from(Novel).where(Novel.chat_room_id == room.room_id))
    if (permission, actor) == ("forbidden", "other"):
        assert (resp.status_code, resp.json()["detail"]) == _FORBIDDEN
        assert novels == 0
    else:
        assert resp.status_code == 201, resp.text
        assert novels == 1


@pytest.mark.parametrize("permission", ["forbidden", "private"])
@pytest.mark.parametrize("action", _ROUTES_WITHOUT_A_CHAPTER)
async def test_an_empty_novel_of_someone_elses_work_follows_the_current_permission(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _CountingLLM,
    action: str,
    permission: str,
) -> None:
    """빈 소설은 권리를 선점하지 않는다 — 소설을 만든 뒤 작가가 허용 안 함으로 바꾸면 남의 빈 소설에서 모델을 부르는
    경로가 403 이고, 차감·작업 행·모델 호출이 없다(연쇄 견적도 같은 판정을 지난다). 허락이 남아 있으면 같은 요청이
    받아들여진다 — 이 셋업이 다른 이유로 거절되지 않는다는 대조군이다."""
    room, novel_id = await _empty_novel(db_client, db_session, monkeypatch, actor="other", permission=permission)
    balance = await _balance(db_session, room.user_id)

    resp = await _request(action, db_client, db_session, room, novel_id, None)

    if permission == "private":
        assert resp.status_code == _MODEL_ROUTES[action], resp.text
        return
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == _FORBIDDEN[1]
    assert await _job_count(db_session, novel_id) == 0
    assert await _novel_ledger(db_session, room.user_id) == []
    assert await _balance(db_session, room.user_id) == balance
    assert llm.calls == 0
    assert (await _lock(db_session, novel_id))[0] is None


@pytest.mark.parametrize("earlier_job", ["none", "failed"])
@pytest.mark.parametrize("action", list(_MODEL_ROUTES))
async def test_chapters_without_a_lock_or_a_successful_chapter_job_hold_no_right(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    llm: _CountingLLM,
    action: str,
    earlier_job: str,
) -> None:
    """잠금 없이 화만 있고 성공한 화 생성 작업 기록도 없으면 첫 화가 저장된 적이 있다는 근거가 없다 — 빈 소설과 같이
    허용 안 함이면 여섯 경로 모두 403·무과금·모델 호출 0 이고, 잠금을 써 넣지 않는다. 실패한 작업은 근거가 아니다."""
    room, novel_id, chapter_id = await _novel_with_chapter(
        db_client, db_session, monkeypatch, actor="other", permission="forbidden", locked=False
    )
    if earlier_job == "failed":
        await _add_finished_chapter_job(db_session, novel_id, "failed")
    jobs_before = await _job_count(db_session, novel_id)
    balance = await _balance(db_session, room.user_id)

    resp = await _request(action, db_client, db_session, room, novel_id, chapter_id)

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == _FORBIDDEN[1]
    assert await _job_count(db_session, novel_id) == jobs_before
    assert await _novel_ledger(db_session, room.user_id) == []
    assert await _balance(db_session, room.user_id) == balance
    assert llm.calls == 0
    assert await _lock(db_session, novel_id) == (None, None, None, None)


@pytest.mark.parametrize("action", list(_MODEL_ROUTES))
async def test_an_unlocked_novel_whose_first_chapter_was_saved_is_locked_on_the_spot_and_let_through(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    """배포가 겹치는 동안 잠금 칸을 모르는 옛 코드가 첫 화를 저장하면 잠금 없이 화와 성공한 화 생성 작업만 남는다. 허용
    안 함이라 거절하려는 순간 그 기록을 보고 출처 `backfill`·권한 모름(그때 권한을 알 수 없다)으로 잠근 뒤 통과시킨다.
    잠금은 요청이 끝난 뒤에도 남아 있어야 한다 — 거절 대신 통과로 바뀐 판정이 다음 요청에서 다시 갈리지 않게."""
    room, novel_id, chapter_id = await _novel_with_chapter(
        db_client, db_session, monkeypatch, actor="other", permission="forbidden", locked=False
    )
    await _add_finished_chapter_job(db_session, novel_id, "succeeded")

    resp = await _request(action, db_client, db_session, room, novel_id, chapter_id)

    assert resp.status_code == _MODEL_ROUTES[action], resp.text
    locked_at, source, permission, version_id = await _lock(db_session, novel_id)
    assert locked_at is not None
    assert (source, permission, version_id) == ("backfill", None, None)


@pytest.mark.parametrize("action", list(_EXISTING_NOVEL_ACTIONS))
@pytest.mark.parametrize("actor", _ACTORS)
@pytest.mark.parametrize("permission", _PERMISSIONS)
async def test_a_locked_novel_keeps_working_whatever_the_permission_becomes(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    permission: str,
    actor: str,
    action: str,
) -> None:
    """첫 화가 저장되어 잠긴 소설은 허락을 낮춰도 그대로다 — 방에서 다시 열기·경계 제안·다음 화·연쇄 견적·연쇄·다시
    만들기·AI 수정·읽기 모두."""
    room, novel_id, chapter_id = await _novel_with_chapter(
        db_client, db_session, monkeypatch, actor=actor, permission=permission
    )

    resp = await _request(action, db_client, db_session, room, novel_id, chapter_id)

    assert resp.status_code == _EXISTING_NOVEL_ACTIONS[action], resp.text


@pytest.mark.parametrize("locked", [False, True])
@pytest.mark.parametrize("action", list(_MODEL_ROUTES))
async def test_the_creator_can_always_write_from_their_own_work(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    locked: bool,
) -> None:
    """작가 본인 작품은 허용 안 함이어도, 잠금이 없어도 여섯 경로가 모두 된다 — 허락은 남에게 거는 조건이다."""
    room, novel_id, chapter_id = await _novel_with_chapter(
        db_client, db_session, monkeypatch, actor="owner", permission="forbidden", locked=locked
    )

    resp = await _request(action, db_client, db_session, room, novel_id, chapter_id)

    assert resp.status_code == _MODEL_ROUTES[action], resp.text


async def test_the_lock_survives_deleting_every_chapter(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """잠금은 풀리지 않는다 — 남의 작품에서 첫 화로 잠근 소설이 허용 안 함으로 바뀐 뒤 유일한 묶음을 지워 화가 0이
    되어도, 다음 화를 받아들이고 방 응답도 새 소설을 막지 않는다. 잠금 칸은 지우기 전 값 그대로다."""
    room, novel_id, chapter_id = await _novel_with_chapter(
        db_client, db_session, monkeypatch, actor="other", permission="forbidden"
    )
    before = await _lock(db_session, novel_id)
    batch_id = await _batch_of(db_session, chapter_id)

    deleted = await db_client.delete(f"/novels/{novel_id}/batches/{batch_id}")
    assert deleted.status_code == 204, deleted.text

    resp = await _request("next_chapter", db_client, db_session, room, novel_id, None)
    room_resp = await db_client.get(f"/chat-rooms/{room.room_id}")

    assert resp.status_code == 202, resp.text
    assert await _lock(db_session, novel_id) == before
    assert room_resp.json()["novelCreationBlocked"] is False


@pytest.mark.parametrize(
    ("permission", "actor", "novel", "blocked"),
    [
        pytest.param("forbidden", "other", "none", True, id="forbidden-other-no-novel"),
        pytest.param("private", "other", "none", False, id="allowed"),
        pytest.param("forbidden", "owner", "none", False, id="creator-themself"),
        pytest.param("forbidden", "other", "empty", True, id="empty-novel-holds-no-right"),
        pytest.param("forbidden", "other", "locked", False, id="locked-novel"),
        pytest.param("forbidden", "other", "locked_then_emptied", False, id="locked-novel-with-every-chapter-deleted"),
    ],
)
async def test_room_response_says_whether_a_new_novel_is_blocked(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    permission: str,
    actor: str,
    novel: str,
    blocked: bool,
) -> None:
    """세 조건(허용 안 함 · 작가가 아님 · 이 방에 잠긴 소설 없음)이 모두일 때만 참이다 — 하나씩 뒤집으면 거짓. 잠기지
    않은 빈 소설은 소설 없음과 같다(이어 쓸 수 없으니 막힌 것으로 보여야 한다). 잠긴 소설은 화를 다 지워도 잠긴 소설이다."""
    if novel == "none":
        room = await _room_without_novel(db_client, db_session, monkeypatch, actor=actor, permission=permission)
    elif novel == "empty":
        room, _ = await _empty_novel(db_client, db_session, monkeypatch, actor=actor, permission=permission)
    else:
        room, novel_id, chapter_id = await _novel_with_chapter(
            db_client, db_session, monkeypatch, actor=actor, permission=permission
        )
        if novel == "locked_then_emptied":
            batch_id = await _batch_of(db_session, chapter_id)
            deleted = await db_client.delete(f"/novels/{novel_id}/batches/{batch_id}")
            assert deleted.status_code == 204, deleted.text

    resp = await db_client.get(f"/chat-rooms/{room.room_id}")

    assert resp.status_code == 200
    assert resp.json()["novelCreationBlocked"] is blocked
