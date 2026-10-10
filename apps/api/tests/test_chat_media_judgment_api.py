"""스토리 대화 중 미디어 북 칸 판정 — 턴마다 판정 LLM 이 노출 제외가 아닌 칸 하나를 골라 응답 아래 그림
한 장을 붙인다.

- 실채팅(`POST /chat-rooms/{id}/messages`): 스탯 판정과 칸 판정을 함께(동시에) 부르고, 한쪽 실패가 다른
  쪽 결과를 지우지 않는다. 최초 엔딩 뒤에도 칸 판정은 계속한다(스탯·엔딩 판정은 멈춘다). 고른 칸은
  메시지의 `image_id`(칸 entity_id)와 노출 기록(보관함 해금)에 남는다.
- 재생성: 같은 판정을 다시 하고 엔딩 여부와 무관하다. 스탯·엔딩 판정은 원래대로 하지 않는다.
- 미리보기: 페이로드의 칸으로 판정하고 노출은 기록하지 않는다. 칸 그림은 요청자 소유의 준비된 자산만
  서명하고, 아니면 차감 전에 거부한다.

LLM 페이크는 응답 스키마로 결과를 고른다 — 판정 둘이 동시에 불리므로 호출 순서에 기대는 큐는 쓸 수 없다."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat import turn_store
from api.chat.prompt_builder import (
    EndingJudgmentResult,
    ImageMatchJudgmentResult,
    StatRuleJudgmentResult,
    load_active_prompt_set,
)
from api.chat.prompt_set_cache import set_cached_active_prompt_set
from api.db.models import (
    Asset,
    AssetKind,
    AssetStatus,
    ChatMessage,
    ChatRoom,
    ChatRoomStat,
    Content,
    Ending,
    MediaBookCell,
    SituationalImage,
    StartingSetup,
    StatDef,
    StatRule,
    StoryMediaExposure,
    User,
)
from api.llm.client import LLMCallContext, LLMClient, LLMClientError, LLMPolicyViolationError
from factories import (
    _add_named_media_cell,
    _clear_llm_override,
    _get_genre,
    _login_as,
    _make_published_character,
    _make_published_story,
    _make_user,
    _override_llm_client,
    _parse_sse_events,
)

_ASSISTANT_REPLY = "민아가 창가에서 웃는다."


class _JudgingLLMClient(LLMClient):
    """구조화 응답을 스키마로 고른다. 값이 예외면 그 판정에서 raise 한다. 모든 판정 호출의
    `(call_site, 스키마, 프롬프트)` 를 남긴다.

    `rendezvous=True` 면 스탯 판정과 칸 판정이 서로를 기다린다 — 둘이 동시에 떠 있을 때만 둘 다 끝나고,
    차례로 불리면 먼저 불린 쪽이 시간 초과로 실패한다."""

    def __init__(
        self,
        *,
        stat: Any = None,
        ending: Any = None,
        image: Any = None,
        rendezvous: bool = False,
    ) -> None:
        self._results: dict[type, Any] = {
            StatRuleJudgmentResult: stat if stat is not None else StatRuleJudgmentResult(fired_rule_ids=[]),
            EndingJudgmentResult: ending if ending is not None else EndingJudgmentResult(triggered=False),
            ImageMatchJudgmentResult: image
            if image is not None
            else ImageMatchJudgmentResult(matched_image_entity_id=None),
        }
        self.calls: list[tuple[str, type, str]] = []
        self._rendezvous = rendezvous
        self._arrived: dict[type, asyncio.Event] = {
            StatRuleJudgmentResult: asyncio.Event(),
            ImageMatchJudgmentResult: asyncio.Event(),
        }

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        yield _ASSISTANT_REPLY

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.calls.append((usage.call_site, response_schema, prompt))
        if self._rendezvous and response_schema in self._arrived:
            self._arrived[response_schema].set()
            other = ImageMatchJudgmentResult if response_schema is StatRuleJudgmentResult else StatRuleJudgmentResult
            try:
                await asyncio.wait_for(self._arrived[other].wait(), timeout=2)
            except TimeoutError as exc:
                raise LLMClientError("다른 판정이 동시에 불리지 않았다") from exc
        result = self._results[response_schema]
        if isinstance(result, Exception):
            raise result
        return result

    def schemas(self) -> list[type]:
        return [schema for _, schema, _ in self.calls]

    def prompt_for(self, schema: type) -> str:
        (prompt,) = [p for _, s, p in self.calls if s is schema]
        return prompt


async def _story(
    db_session: AsyncSession, *, opening_message: str = "다시 만났네요!", user: User | None = None
) -> tuple[User, Content, StartingSetup, StatDef]:
    if user is None:
        user = _make_user()
        db_session.add(user)
        await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
    assert content.current_published_version_id is not None
    setup = StartingSetup(
        entity_id=uuid.uuid4(),
        content_version_id=content.current_published_version_id,
        name="첫 만남",
        prologue="낯선 마을에 도착했다.",
        opening_message=opening_message,
        order=1,
    )
    db_session.add(setup)
    await db_session.flush()
    stat_def = StatDef(
        entity_id=uuid.uuid4(),
        starting_setup_id=setup.id,
        name="호감도",
        icon="heart",
        color="#ff0000",
        min_value=0,
        max_value=100,
        initial_value=50,
        unit=None,
        description="호감도 스탯",
        order=1,
    )
    db_session.add(stat_def)
    await db_session.flush()
    # 규칙 하나(a1, +10) — 규칙이 있어야 스탯 판정이 불린다. 발동하면 50 이 60 이 된다.
    db_session.add(StatRule(entity_id=uuid.uuid4(), stat_def_id=stat_def.id, condition="반긴다", delta=10, order=0))
    await db_session.flush()
    return user, content, setup, stat_def


async def _open_story_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, user: User, content: Content, setup: StartingSetup
) -> uuid.UUID:
    await db_session.commit()
    await _login_as(db_client, user.id)
    resp = await db_client.post(
        "/chat-rooms", json={"contentId": str(content.id), "contentType": "story", "startingSetupId": str(setup.id)}
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


async def _send(db_client: httpx.AsyncClient, room_id: uuid.UUID, fake: LLMClient) -> list[dict[str, Any]]:
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "민아에게 인사한다"})
    finally:
        _clear_llm_override()
    assert resp.status_code == 200, resp.text
    return _parse_sse_events(resp.text)


async def _regenerate(db_client: httpx.AsyncClient, room_id: uuid.UUID, fake: LLMClient) -> list[dict[str, Any]]:
    _override_llm_client(fake)
    try:
        resp = await db_client.post(f"/chat-rooms/{room_id}/regenerate")
    finally:
        _clear_llm_override()
    assert resp.status_code == 200, resp.text
    return _parse_sse_events(resp.text)


async def _exposed_cells(db_session: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        await db_session.scalars(
            sa.select(StoryMediaExposure.cell_entity_id).where(StoryMediaExposure.user_id == user_id)
        )
    )


def _judged(cell_id: uuid.UUID) -> ImageMatchJudgmentResult:
    return ImageMatchJudgmentResult(matched_image_entity_id=str(cell_id))


async def _mark_ending_reached(db_session: AsyncSession, room_id: uuid.UUID) -> None:
    await db_session.execute(
        sa.update(ChatRoom).where(ChatRoom.id == room_id).values(ending_reached=True, ending_reached_at_turn=1)
    )
    await db_session.commit()


# ---- 실채팅 --------------------------------------------------------------------------------------


async def test_story_turn_attaches_media_cell_image_and_records_exposure(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user, content, setup, _ = await _story(db_session)
    assert content.current_published_version_id is not None
    cell, _ = await _add_named_media_cell(
        db_session, content.current_published_version_id, user.id, "민아", "창가", situation_description="창가에서 웃는다"
    )
    room_id = await _open_story_room(db_client, db_session, user, content, setup)
    fake = _JudgingLLMClient(image=_judged(cell.entity_id))

    events = await _send(db_client, room_id, fake)

    final = events[-1]["finalMessage"]
    assert final["imageId"] == str(cell.entity_id)
    assert final["imageUrl"]
    assert (final["imageWidth"], final["imageHeight"]) == (300, 400)
    assert sorted(fake.schemas(), key=str) == sorted([StatRuleJudgmentResult, ImageMatchJudgmentResult], key=str)
    assert ("chat_media_book_image", ImageMatchJudgmentResult) in [(site, schema) for site, schema, _ in fake.calls]
    assert await _exposed_cells(db_session, user.id) == [cell.entity_id]
    stored = await db_session.scalar(sa.select(ChatMessage.image_id).where(ChatMessage.id == uuid.UUID(final["id"])))
    assert stored == cell.entity_id

    # 다시 불러온 방도 같은 칸을 같은 크기로 그린다 — 스토리 메시지의 image_id 는 미디어 북 칸이다.
    room = (await db_client.get(f"/chat-rooms/{room_id}")).json()
    message = room["messages"][-1]
    assert message["imageId"] == str(cell.entity_id)
    assert message["imageUrl"]
    assert (message["imageWidth"], message["imageHeight"]) == (300, 400)


async def test_story_media_judgment_lists_cells_with_names_and_situation(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user, content, setup, _ = await _story(db_session)
    version_id = content.current_published_version_id
    assert version_id is not None
    with_situation, _ = await _add_named_media_cell(
        db_session, version_id, user.id, "민아", "창가", situation_description="창가에서 웃는다"
    )
    without_situation, _ = await _add_named_media_cell(db_session, version_id, user.id, "민아", "교실")
    room_id = await _open_story_room(db_client, db_session, user, content, setup)
    fake = _JudgingLLMClient()

    await _send(db_client, room_id, fake)

    prompt = fake.prompt_for(ImageMatchJudgmentResult)
    assert f"imageEntityId={with_situation.entity_id}, 인물=민아, 장면=창가, 상황 설명=창가에서 웃는다\n" in prompt
    assert f"imageEntityId={without_situation.entity_id}, 인물=민아, 장면=교실\n" in prompt


async def test_story_turn_skips_media_judgment_when_all_cells_excluded(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user, content, setup, _ = await _story(db_session)
    assert content.current_published_version_id is not None
    await _add_named_media_cell(db_session, content.current_published_version_id, user.id, "민아", "창가", exclude_from_chat=True)
    room_id = await _open_story_room(db_client, db_session, user, content, setup)
    fake = _JudgingLLMClient()

    events = await _send(db_client, room_id, fake)

    assert fake.schemas() == [StatRuleJudgmentResult]
    assert events[-1]["finalMessage"]["imageId"] is None


async def test_story_turn_ignores_judged_cell_id_not_in_candidates(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """판정이 노출 제외 칸을 골라도(후보 목록에 없던 id) 붙이지도 기록하지도 않는다."""
    user, content, setup, _ = await _story(db_session)
    version_id = content.current_published_version_id
    assert version_id is not None
    await _add_named_media_cell(db_session, version_id, user.id, "민아", "창가")
    excluded, _ = await _add_named_media_cell(db_session, version_id, user.id, "민아", "옥상", exclude_from_chat=True)
    room_id = await _open_story_room(db_client, db_session, user, content, setup)
    fake = _JudgingLLMClient(image=_judged(excluded.entity_id))

    events = await _send(db_client, room_id, fake)

    assert str(excluded.entity_id) not in fake.prompt_for(ImageMatchJudgmentResult)
    assert events[-1]["finalMessage"]["imageId"] is None
    assert await _exposed_cells(db_session, user.id) == []


@pytest.mark.parametrize(
    "judgment_error",
    [
        pytest.param(LLMClientError("판정 실패"), id="llm-error"),
        pytest.param(LLMPolicyViolationError("Gemini 가 안전 기준으로 판정 응답을 막았다"), id="safety-block"),
    ],
)
async def test_story_turn_keeps_stat_changes_when_media_judgment_fails(
    db_client: httpx.AsyncClient, db_session: AsyncSession, judgment_error: LLMClientError
) -> None:
    user, content, setup, _ = await _story(db_session)
    assert content.current_published_version_id is not None
    await _add_named_media_cell(db_session, content.current_published_version_id, user.id, "민아", "창가")
    room_id = await _open_story_room(db_client, db_session, user, content, setup)
    fake = _JudgingLLMClient(
        stat=StatRuleJudgmentResult(fired_rule_ids=["a1"]),
        image=judgment_error,
    )

    events = await _send(db_client, room_id, fake)

    assert [e["type"] for e in events if e["type"] != "token"] == ["statChange", "done"]
    assert events[-1]["finalMessage"]["imageId"] is None
    stat_value = await db_session.scalar(
        sa.select(ChatRoomStat.current_value).where(ChatRoomStat.chat_room_id == room_id)
    )
    assert stat_value is not None and float(stat_value) == 60


@pytest.mark.parametrize(
    "judgment_error",
    [
        pytest.param(LLMClientError("스탯 판정 실패"), id="llm-error"),
        pytest.param(LLMPolicyViolationError("Gemini 가 안전 기준으로 판정 응답을 막았다"), id="safety-block"),
    ],
)
async def test_story_turn_keeps_media_image_when_stat_judgment_fails(
    db_client: httpx.AsyncClient, db_session: AsyncSession, judgment_error: LLMClientError
) -> None:
    user, content, setup, _ = await _story(db_session)
    assert content.current_published_version_id is not None
    cell, _ = await _add_named_media_cell(db_session, content.current_published_version_id, user.id, "민아", "창가")
    room_id = await _open_story_room(db_client, db_session, user, content, setup)
    fake = _JudgingLLMClient(stat=judgment_error, image=_judged(cell.entity_id))

    events = await _send(db_client, room_id, fake)

    assert [e["type"] for e in events if e["type"] != "token"] == ["done"]
    assert events[-1]["finalMessage"]["imageId"] == str(cell.entity_id)
    assert await _exposed_cells(db_session, user.id) == [cell.entity_id]


def _fail_once_with_real_sql(monkeypatch: pytest.MonkeyPatch, matches: Callable[[Any], bool]) -> None:
    """`matches` 에 맞는 첫 문장 대신 `SELECT 1/0` 을 실제로 보내 Postgres 트랜잭션을 진짜 aborted 로 만든다 —
    순수 파이썬 예외로는 흡수 뒤 커밋이 aborted 트랜잭션에 부딪히는 파열을 재현할 수 없다."""
    original_execute = AsyncSession.execute
    failed = False

    async def _execute(self: AsyncSession, statement: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal failed
        if not failed and matches(statement):
            failed = True
            return await original_execute(self, sa.text("SELECT 1/0"))
        return await original_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", _execute)


async def test_story_turn_media_candidate_query_failure_keeps_stat_changes(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, content, setup, _ = await _story(db_session)
    assert content.current_published_version_id is not None
    await _add_named_media_cell(db_session, content.current_published_version_id, user.id, "민아", "창가")
    room_id = await _open_story_room(db_client, db_session, user, content, setup)
    _fail_once_with_real_sql(
        monkeypatch,
        lambda statement: isinstance(statement, sa.Select)
        and len(statement.column_descriptions) == 4
        and statement.column_descriptions[0]["entity"] is MediaBookCell,
    )
    fake = _JudgingLLMClient(
        stat=StatRuleJudgmentResult(fired_rule_ids=["a1"])
    )

    events = await _send(db_client, room_id, fake)

    assert fake.schemas() == [StatRuleJudgmentResult]
    assert [e["type"] for e in events if e["type"] != "token"] == ["statChange", "done"]
    stat_value = await db_session.scalar(
        sa.select(ChatRoomStat.current_value).where(ChatRoomStat.chat_room_id == room_id)
    )
    assert stat_value is not None and float(stat_value) == 60


async def test_story_turn_exposure_record_failure_drops_the_image_but_keeps_the_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, content, setup, _ = await _story(db_session)
    assert content.current_published_version_id is not None
    cell, _ = await _add_named_media_cell(db_session, content.current_published_version_id, user.id, "민아", "창가")
    room_id = await _open_story_room(db_client, db_session, user, content, setup)
    _fail_once_with_real_sql(
        monkeypatch,
        lambda statement: isinstance(statement, sa.Insert) and statement.table.name == "story_media_exposures",
    )
    fake = _JudgingLLMClient(
        stat=StatRuleJudgmentResult(fired_rule_ids=["a1"]),
        image=_judged(cell.entity_id),
    )

    events = await _send(db_client, room_id, fake)

    final = events[-1]["finalMessage"]
    assert final["imageId"] is None
    assert [e["type"] for e in events if e["type"] != "token"] == ["statChange", "done"]
    assert await _exposed_cells(db_session, user.id) == []
    stored = await db_session.scalar(sa.select(ChatMessage.image_id).where(ChatMessage.id == uuid.UUID(final["id"])))
    assert stored is None


async def test_story_turn_cell_signing_failure_finishes_without_image(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, content, setup, _ = await _story(db_session)
    assert content.current_published_version_id is not None
    cell, _ = await _add_named_media_cell(db_session, content.current_published_version_id, user.id, "민아", "창가")
    room_id = await _open_story_room(db_client, db_session, user, content, setup)

    async def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("서명 실패")

    monkeypatch.setattr(turn_store, "resolve_media_tag_images", _boom)
    fake = _JudgingLLMClient(image=_judged(cell.entity_id))

    events = await _send(db_client, room_id, fake)

    assert events[-1]["type"] == "done"
    assert events[-1]["finalMessage"]["imageId"] is None
    assert events[-1]["finalMessage"]["imageUrl"] is None


async def test_story_turn_runs_stat_and_media_judgments_concurrently(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """두 판정이 서로를 기다리는 페이크 — 차례로 부르면 먼저 불린 쪽이 시간 초과로 실패해 그 결과가 빠진다."""
    user, content, setup, _ = await _story(db_session)
    assert content.current_published_version_id is not None
    cell, _ = await _add_named_media_cell(db_session, content.current_published_version_id, user.id, "민아", "창가")
    room_id = await _open_story_room(db_client, db_session, user, content, setup)
    fake = _JudgingLLMClient(
        stat=StatRuleJudgmentResult(fired_rule_ids=["a1"]),
        image=_judged(cell.entity_id),
        rendezvous=True,
    )

    events = await _send(db_client, room_id, fake)

    assert [e["type"] for e in events if e["type"] != "token"] == ["statChange", "done"]
    assert events[-1]["finalMessage"]["imageId"] == str(cell.entity_id)


async def test_story_turn_judging_an_already_exposed_cell_still_attaches_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """같은 장면은 다시 온다 — 이미 보관함에 해금된 칸을 또 고른 턴도 그림이 붙고 노출 기록은 한 줄 그대로다
    (기록이 멱등이 아니면 두 번째 기록이 실패해 그 턴의 그림이 빠진다)."""
    user, content, setup, _ = await _story(db_session)
    assert content.current_published_version_id is not None
    cell, _ = await _add_named_media_cell(db_session, content.current_published_version_id, user.id, "민아", "창가")
    db_session.add(StoryMediaExposure(user_id=user.id, content_id=content.id, cell_entity_id=cell.entity_id))
    room_id = await _open_story_room(db_client, db_session, user, content, setup)

    events = await _send(db_client, room_id, _JudgingLLMClient(image=_judged(cell.entity_id)))

    assert events[-1]["finalMessage"]["imageId"] == str(cell.entity_id)
    assert await _exposed_cells(db_session, user.id) == [cell.entity_id]


async def test_story_turn_after_ending_still_attaches_media_cell_image(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user, content, setup, _ = await _story(db_session)
    assert content.current_published_version_id is not None
    cell, _ = await _add_named_media_cell(db_session, content.current_published_version_id, user.id, "민아", "창가")
    db_session.add(
        Ending(
            entity_id=uuid.uuid4(),
            starting_setup_id=setup.id,
            name="엔딩",
            turn_count_gate=1,
            judgment_prompt="떠났는가?",
            epilogue="끝.",
            hint="힌트",
            order=1,
        )
    )
    room_id = await _open_story_room(db_client, db_session, user, content, setup)
    await _mark_ending_reached(db_session, room_id)
    fake = _JudgingLLMClient(image=_judged(cell.entity_id), ending=EndingJudgmentResult(triggered=True))

    events = await _send(db_client, room_id, fake)

    assert fake.schemas() == [ImageMatchJudgmentResult]
    assert events[-1]["finalMessage"]["imageId"] == str(cell.entity_id)
    assert await _exposed_cells(db_session, user.id) == [cell.entity_id]


async def test_story_judgment_turn_lines_exclude_media_tags(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """첫 메시지는 칸 id 형태 태그를 담아 저장된다 — 판정의 대화 기록에는 실리지 않는다."""
    user, content, setup, _ = await _story(db_session, opening_message="문이 열린다.\n\n{{img::민아/창가}}\n\n민아가 웃는다.")
    assert content.current_published_version_id is not None
    await _add_named_media_cell(db_session, content.current_published_version_id, user.id, "민아", "창가")
    room_id = await _open_story_room(db_client, db_session, user, content, setup)
    fake = _JudgingLLMClient()

    await _send(db_client, room_id, fake)

    prompt = fake.prompt_for(ImageMatchJudgmentResult)
    assert "{{img::" not in prompt
    assert "문이 열린다.\n\n민아가 웃는다." in prompt


async def test_story_media_judgment_uses_story_assistant_label(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user, content, setup, _ = await _story(db_session)
    assert content.current_published_version_id is not None
    await _add_named_media_cell(db_session, content.current_published_version_id, user.id, "민아", "창가")
    room_id = await _open_story_room(db_client, db_session, user, content, setup)
    prompt_set, _ = await load_active_prompt_set(db_session, lane="story")
    assert prompt_set.story_assistant_label != prompt_set.character_assistant_label
    fake = _JudgingLLMClient()

    await _send(db_client, room_id, fake)

    prompt = fake.prompt_for(ImageMatchJudgmentResult)
    assert f"{prompt_set.story_assistant_label}: {_ASSISTANT_REPLY}" in prompt
    assert f"{prompt_set.character_assistant_label}: " not in prompt


async def test_story_turn_skips_media_judgment_when_prompt_renders_empty(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """배포 직후 활성 세트 캐시(최대 300초)에는 칸 판정 채널이 없는 옛 세트가 남는다 — 그동안은 빈
    프롬프트로 판정을 부르지 않고 그림 없이 턴을 마친다(스탯 판정은 그대로)."""
    user, content, setup, _ = await _story(db_session)
    assert content.current_published_version_id is not None
    await _add_named_media_cell(db_session, content.current_published_version_id, user.id, "민아", "창가")
    room_id = await _open_story_room(db_client, db_session, user, content, setup)
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story")
    await set_cached_active_prompt_set(
        "story", prompt_set, [s for s in sections if s.channel != "image_judgment"], model="gemini"
    )
    fake = _JudgingLLMClient()

    events = await _send(db_client, room_id, fake)

    assert fake.schemas() == [StatRuleJudgmentResult]
    assert events[-1]["type"] == "done"
    assert events[-1]["finalMessage"]["imageId"] is None


async def test_character_turn_done_message_carries_no_image_dimensions(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """캐릭터 상황별 이미지는 지금처럼 고정 비율 칸으로 그린다 — 크기를 알아도 싣지 않는다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    assert content.current_published_version_id is not None
    asset = Asset(
        owner_user_id=user.id,
        storage_key=f"assets/situational-image/{uuid.uuid4()}.webp",
        kind=AssetKind.ORIGINAL,
        status=AssetStatus.READY,
        width=300,
        height=400,
    )
    db_session.add(asset)
    await db_session.flush()
    image = SituationalImage(
        entity_id=uuid.uuid4(),
        content_version_id=content.current_published_version_id,
        image_asset_id=asset.id,
        trigger_condition="웃을 때",
        order=0,
    )
    db_session.add(image)
    await db_session.commit()
    await _login_as(db_client, user.id)
    room_resp = await db_client.post("/chat-rooms", json={"contentId": str(content.id), "contentType": "character"})
    room_id = uuid.UUID(room_resp.json()["id"])
    fake = _JudgingLLMClient(image=_judged(image.entity_id))

    events = await _send(db_client, room_id, fake)

    final = events[-1]["finalMessage"]
    assert final["imageId"] == str(image.entity_id)
    assert final["imageUrl"]
    assert final.get("imageWidth") is None
    assert final.get("imageHeight") is None
    assert [site for site, _, _ in fake.calls] == ["chat_situational_image"]


# ---- 재생성 ---------------------------------------------------------------------------------------


async def test_regenerate_story_message_rejudges_media_cell(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user, content, setup, _ = await _story(db_session)
    assert content.current_published_version_id is not None
    cell, _ = await _add_named_media_cell(db_session, content.current_published_version_id, user.id, "민아", "창가")
    room_id = await _open_story_room(db_client, db_session, user, content, setup)
    await _send(db_client, room_id, _JudgingLLMClient())
    fake = _JudgingLLMClient(image=_judged(cell.entity_id))

    events = await _regenerate(db_client, room_id, fake)

    # 마지막 턴의 기록이 있어 스탯도 다시 판정한다 — 칸 판정과 함께 부르므로 순서는 보지 않는다.
    assert sorted(schema.__name__ for schema in fake.schemas()) == ["ImageMatchJudgmentResult", "StatRuleJudgmentResult"]
    final = events[-1]["finalMessage"]
    assert final["imageId"] == str(cell.entity_id)
    assert (final["imageWidth"], final["imageHeight"]) == (300, 400)
    assert await _exposed_cells(db_session, user.id) == [cell.entity_id]
    stored = await db_session.scalar(sa.select(ChatMessage.image_id).where(ChatMessage.id == uuid.UUID(final["id"])))
    assert stored == cell.entity_id


async def test_regenerate_rejudging_the_same_cell_still_attaches_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """원 턴이 이미 그 칸을 노출로 기록했고 재생성도 같은 칸을 고른다 — 그림이 붙고 노출 기록은 한 줄이다."""
    user, content, setup, _ = await _story(db_session)
    assert content.current_published_version_id is not None
    cell, _ = await _add_named_media_cell(db_session, content.current_published_version_id, user.id, "민아", "창가")
    room_id = await _open_story_room(db_client, db_session, user, content, setup)
    first = await _send(db_client, room_id, _JudgingLLMClient(image=_judged(cell.entity_id)))
    assert first[-1]["finalMessage"]["imageId"] == str(cell.entity_id)

    events = await _regenerate(db_client, room_id, _JudgingLLMClient(image=_judged(cell.entity_id)))

    assert events[-1]["finalMessage"]["imageId"] == str(cell.entity_id)
    assert await _exposed_cells(db_session, user.id) == [cell.entity_id]


async def test_regenerate_after_ending_rejudges_media_cell(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user, content, setup, _ = await _story(db_session)
    assert content.current_published_version_id is not None
    cell, _ = await _add_named_media_cell(db_session, content.current_published_version_id, user.id, "민아", "창가")
    room_id = await _open_story_room(db_client, db_session, user, content, setup)
    await _send(db_client, room_id, _JudgingLLMClient())
    await _mark_ending_reached(db_session, room_id)
    fake = _JudgingLLMClient(image=_judged(cell.entity_id))

    events = await _regenerate(db_client, room_id, fake)

    assert fake.schemas() == [ImageMatchJudgmentResult]
    assert events[-1]["finalMessage"]["imageId"] == str(cell.entity_id)


async def test_regenerate_story_message_without_candidates_makes_no_judgment_call(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user, content, setup, _ = await _story(db_session)
    room_id = await _open_story_room(db_client, db_session, user, content, setup)
    await _send(db_client, room_id, _JudgingLLMClient())
    fake = _JudgingLLMClient()

    events = await _regenerate(db_client, room_id, fake)

    # 칸 후보가 없어 칸 판정은 부르지 않는다 — 마지막 턴의 스탯 재판정만 나간다.
    assert [site for site, _, _ in fake.calls] == ["chat_stat_judgment"]
    assert events[-1]["finalMessage"]["imageId"] is None


# ---- 미리보기 -------------------------------------------------------------------------------------


async def _ready_asset(db_session: AsyncSession, owner_user_id: uuid.UUID) -> Asset:
    asset = Asset(
        owner_user_id=owner_user_id,
        storage_key=f"assets/situational-image/{uuid.uuid4()}.webp",
        kind=AssetKind.ORIGINAL,
        status=AssetStatus.READY,
        width=640,
        height=480,
    )
    db_session.add(asset)
    await db_session.flush()
    return asset


def _preview_payload(
    *,
    cells: list[dict[str, object]],
    people: list[dict[str, object]],
    scenes: list[dict[str, object]],
    endings: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "name": "잃어버린 도시",
        "oneLiner": "한 줄 소개",
        "thumbnailAssetId": None,
        "promptTemplate": "basic",
        "settingText": "세계관 설명",
        "developmentExample": None,
        "customPrompt": None,
        "startingSetups": [
            {
                "id": str(uuid.uuid4()),
                "name": "시작설정1",
                "prologue": "프롤로그",
                "openingMessage": None,
                "playguide": None,
                "suggestedReplies": [],
                "statDefs": [],
                "endings": endings or [],
            }
        ],
        "keywordNotes": [],
        "shortcuts": [],
        "description": "상세 설명",
        "genreId": None,
        "target": None,
        "hashtags": [],
        "visibility": "private",
        "mediaBook": {"people": people, "scenes": scenes, "cells": cells},
    }


def _one_cell_media_book(asset_id: uuid.UUID, *, exclude: bool = False) -> tuple[uuid.UUID, dict[str, Any]]:
    person_id, scene_id, cell_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    return cell_id, {
        "people": [{"id": str(person_id), "name": "민아"}],
        "scenes": [{"id": str(scene_id), "name": "창가"}],
        "cells": [
            {
                "id": str(cell_id),
                "personId": str(person_id),
                "sceneId": str(scene_id),
                "imageAssetId": str(asset_id),
                "situationDescription": "창가에서 웃는다",
                "unlockHint": "",
                "excludeFromChat": exclude,
            }
        ],
    }


async def _start_preview(db_client: httpx.AsyncClient, payload: dict[str, object]) -> str:
    resp = await db_client.post("/preview-sessions", json=payload)
    assert resp.status_code == 201, resp.text
    session_id = resp.json()["previewSessionId"]
    assert isinstance(session_id, str)
    return session_id


async def _send_preview(db_client: httpx.AsyncClient, session_id: str, fake: LLMClient) -> httpx.Response:
    _override_llm_client(fake)
    try:
        return await db_client.post(f"/preview-sessions/{session_id}/messages", json={"content": "민아에게 인사한다"})
    finally:
        _clear_llm_override()


async def test_preview_turn_judges_media_cell_without_exposure(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _ready_asset(db_session, user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)
    cell_id, media_book = _one_cell_media_book(asset.id)
    session_id = await _start_preview(db_client, _preview_payload(**media_book))
    fake = _JudgingLLMClient(image=_judged(cell_id))

    resp = await _send_preview(db_client, session_id, fake)

    assert resp.status_code == 200, resp.text
    final = _parse_sse_events(resp.text)[-1]["finalMessage"]
    assert final["imageId"] == str(cell_id)
    assert final["imageUrl"]
    assert (final["imageWidth"], final["imageHeight"]) == (640, 480)
    assert ("preview_media_book_image", ImageMatchJudgmentResult) in [(s, c) for s, c, _ in fake.calls]
    assert "인물=민아, 장면=창가, 상황 설명=창가에서 웃는다" in fake.prompt_for(ImageMatchJudgmentResult)
    assert await _exposed_cells(db_session, user.id) == []


async def test_preview_turn_skips_media_judgment_when_all_cells_excluded(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _ready_asset(db_session, user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)
    _, media_book = _one_cell_media_book(asset.id, exclude=True)
    session_id = await _start_preview(db_client, _preview_payload(**media_book))
    fake = _JudgingLLMClient()

    resp = await _send_preview(db_client, session_id, fake)

    assert resp.status_code == 200, resp.text
    # 페이로드에 스탯이 없어 스탯 판정도 불리지 않는다 — 판정 호출이 하나도 없어야 한다.
    assert fake.schemas() == []


async def test_preview_turn_after_ending_judges_media_cell(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _ready_asset(db_session, user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)
    cell_id, media_book = _one_cell_media_book(asset.id)
    ending = {
        "id": str(uuid.uuid4()),
        "name": "해피엔딩",
        "turnCountGate": 1,
        "judgmentPrompt": "행복한 결말에 도달했는가",
        "epilogue": "끝.",
        "hint": None,
        "statRules": [],
    }
    session_id = await _start_preview(db_client, _preview_payload(**media_book, endings=[ending]))
    first = await _send_preview(db_client, session_id, _JudgingLLMClient(ending=EndingJudgmentResult(triggered=True)))
    assert [e["type"] for e in _parse_sse_events(first.text) if e["type"] != "token"] == ["endingReached", "done"]
    fake = _JudgingLLMClient(image=_judged(cell_id), ending=EndingJudgmentResult(triggered=True))

    resp = await _send_preview(db_client, session_id, fake)

    assert fake.schemas() == [ImageMatchJudgmentResult]
    assert _parse_sse_events(resp.text)[-1]["finalMessage"]["imageId"] == str(cell_id)


async def test_preview_ending_epilogue_carries_cell_id_tags_and_url_map(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """미리보기 에필로그는 페이로드 그대로라 이름 형태다 — 실채팅처럼 칸 id 형태로 바꾸고 그림 맵을 싣는다.
    없는 이름의 태그는 지운다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _ready_asset(db_session, user.id)
    await db_session.commit()
    await _login_as(db_client, user.id)
    cell_id, media_book = _one_cell_media_book(asset.id)
    ending = {
        "id": str(uuid.uuid4()),
        "name": "해피엔딩",
        "turnCountGate": 1,
        "judgmentPrompt": "행복한 결말에 도달했는가",
        "epilogue": "끝났다.\n\n{{img::민아/창가}}\n\n{{img::수아/창가}}\n\n안녕.",
        "hint": None,
        "statRules": [],
    }
    session_id = await _start_preview(db_client, _preview_payload(**media_book, endings=[ending]))

    resp = await _send_preview(db_client, session_id, _JudgingLLMClient(ending=EndingJudgmentResult(triggered=True)))

    (event,) = [e for e in _parse_sse_events(resp.text) if e["type"] == "endingReached"]
    assert event["epilogue"] == f"끝났다.\n\n{{{{img::{cell_id}}}}}\n\n안녕."
    assert list(event["mediaTagImages"]) == [str(cell_id)]
    assert event["mediaTagImages"][str(cell_id)]["width"] == 640


def _two_cell_media_book(
    usable_asset_id: uuid.UUID, unusable_asset_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID, dict[str, Any]]:
    """민아×창가(쓸 수 있는 자산)와 민아×옥상(쓸 수 없는 자산) 두 칸."""
    person_id, window_id, roof_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    usable_cell, unusable_cell = uuid.uuid4(), uuid.uuid4()

    def cell(cell_id: uuid.UUID, scene_id: uuid.UUID, asset_id: uuid.UUID) -> dict[str, object]:
        return {
            "id": str(cell_id),
            "personId": str(person_id),
            "sceneId": str(scene_id),
            "imageAssetId": str(asset_id),
            "situationDescription": "",
            "unlockHint": "",
            "excludeFromChat": False,
        }

    return usable_cell, unusable_cell, {
        "people": [{"id": str(person_id), "name": "민아"}],
        "scenes": [{"id": str(window_id), "name": "창가"}, {"id": str(roof_id), "name": "옥상"}],
        "cells": [cell(usable_cell, window_id, usable_asset_id), cell(unusable_cell, roof_id, unusable_asset_id)],
    }


async def _assert_preview_drops_unusable_cell(
    db_client: httpx.AsyncClient, user_id: uuid.UUID, usable: Asset, unusable: Asset
) -> None:
    """쓸 수 없는 자산의 칸은 판정 후보·에필로그 그림에서 빠지고(그 칸의 태그는 지워진다) 턴은 정상으로 끝난다.
    판정이 그 칸을 골라도 붙지 않는다 — 서명하지 않은 칸이라 URL 이 없다."""
    await _login_as(db_client, user_id)
    usable_cell, unusable_cell, media_book = _two_cell_media_book(usable.id, unusable.id)
    ending = {
        "id": str(uuid.uuid4()),
        "name": "해피엔딩",
        "turnCountGate": 1,
        "judgmentPrompt": "행복한 결말에 도달했는가",
        "epilogue": "끝.\n\n{{img::민아/창가}}\n\n{{img::민아/옥상}}",
        "hint": None,
        "statRules": [],
    }
    session_id = await _start_preview(db_client, _preview_payload(**media_book, endings=[ending]))
    fake = _JudgingLLMClient(image=_judged(unusable_cell), ending=EndingJudgmentResult(triggered=True))

    resp = await _send_preview(db_client, session_id, fake)

    assert resp.status_code == 200, resp.text
    events = _parse_sse_events(resp.text)
    prompt = fake.prompt_for(ImageMatchJudgmentResult)
    assert str(usable_cell) in prompt
    assert str(unusable_cell) not in prompt
    assert events[-1]["type"] == "done"
    assert events[-1]["finalMessage"]["imageId"] is None
    (ending_event,) = [e for e in events if e["type"] == "endingReached"]
    assert list(ending_event["mediaTagImages"]) == [str(usable_cell)]
    assert ending_event["epilogue"] == f"끝.\n\n{{{{img::{usable_cell}}}}}"


async def test_preview_drops_cell_whose_asset_is_owned_by_another_user(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """미리보기가 남의 자산 서명기가 되지 않게 칸 자산은 요청자 소유만 서명한다 — 아닌 칸만 조용히 빠진다."""
    other = _make_user()
    db_session.add(other)
    await db_session.flush()
    foreign_asset = await _ready_asset(db_session, other.id)
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    own_asset = await _ready_asset(db_session, user.id)
    await db_session.commit()

    await _assert_preview_drops_unusable_cell(db_client, user.id, own_asset, foreign_asset)


async def test_preview_drops_cell_whose_asset_is_not_ready(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    own_asset = await _ready_asset(db_session, user.id)
    pending_asset = await _ready_asset(db_session, user.id)
    pending_asset.status = AssetStatus.PENDING
    await db_session.commit()

    await _assert_preview_drops_unusable_cell(db_client, user.id, own_asset, pending_asset)
