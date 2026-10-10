"""새 턴 판정 단계에서 실패 매트릭스·SSE 스냅숏이 보지 못하는 세 성질을 지금 동작 그대로 고정한다 — 판정 코드를 옮기거나
나누는 리팩터가 이 셋을 조용히 바꾸지 못하게.

- 엔딩 판정·캐릭터 상황 이미지 판정의 LLM 실패를 **어디서** 흡수하는가. 매트릭스는 SSE·상태·Bugsink 태그만 남기는데,
  흡수 자리가 옮겨 가도 그 셋은 같고 경고 로그(로거 이름·문구)만 달라진다. 그래서 여기서는 경고 로그까지 남긴다.
- 엔딩 판정 하나가 실패한 뒤 판정 차례인 다음 엔딩을 판정하는가. 매트릭스의 엔딩 실패 칸은 판정 차례 엔딩이 하나뿐이라
  "첫 실패에서 멈춘다"와 "다음 엔딩으로 넘어간다"가 같은 기록을 낸다. 여기서는 판정 차례 엔딩을 둘 두고 첫 판정만 실패시킨다.
- 한 턴에 스탯 여럿이 바뀔 때 `statChange` 이벤트끼리의 순서. 다른 테스트는 바뀌는 스탯이 하나이거나 사전으로 비교한다.
  순서가 DB 의 행 배치(정렬 없는 읽기)에 좌우되지 않게, 방의 스탯 행은 작가 순서로 마지막인 스탯 하나에만 남긴다 — 행이
  없는 스탯은 판정이 시작값으로 본다(버전을 옮긴 방에서 새 버전에 생긴 스탯과 같은 모양).
- 재생성이 실패를 흡수하며 남기는 경고(로거 이름·문구). 재생성의 경고 몇 개는 새 턴과 문구가 다르다("재생성" 이 들어간다).
  매트릭스는 로그를 남기지 않으므로, 재생성 코드를 옮기는 리팩터가 문구나 로거 이름을 조용히 바꾸면 여기서만 갈린다.
  실패를 만드는 장치는 매트릭스와 같은 자리(활성 세트 문안·가짜 LLM·URL 서명)다.
- 빌더 미리보기가 실패를 흡수하며 남기는 경고(로거 이름·문구). 미리보기의 경고는 방 경로와 문구·인자가 다르고(방 id 가
  없고 판정 주어가 "미리보기"다), 칸 판정 프롬프트 렌더 경고는 라우터 로거로 남는다. 상태는 Redis 의 미리보기 세션에서 읽는다.
  시작설정이 없는 스토리 초안(스탯·엔딩 없이 칸 판정만 하는 턴)도 여기서 본다 — 다른 미리보기 테스트의 초안은 모두
  시작설정을 갖는다.

기대값은 지금 동작을 기록한 것이다(`fixtures/chat_turn_judgment_characterization.json`). 다시 뜨는 법은
`factories._assert_characterization`.
"""

import logging
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import sentry_sdk
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from redis.exceptions import RedisError

from api.chat.preview_session import get_preview_session
from api.chat.prompt_builder import (
    EndingJudgmentResult,
    ImageMatchJudgmentResult,
    MemorySummaryResult,
    StatRuleJudgmentResult,
)
from api.chat.prompt_set_cache import ACTIVE_PROMPT_SET_KEY_PREFIX
from api.core import s3 as s3_module
from api.core.redis import redis_client
from api.db.models import (
    AssetStatus,
    ChatMessage,
    ChatRoom,
    ChatRoomStat,
    Ending,
    PromptSection,
    StartingSetup,
    StatDef,
    StatRule,
)
from api.llm.client import LLMCallContext, LLMClient, LLMClientError
from factories import (
    _add_room_cell_and_endings,
    _add_room_situational_image,
    _assert_characterization,
    _assert_recorded_cases,
    _clear_llm_override,
    _login_as,
    _make_asset,
    _make_user,
    _open_room,
    _override_llm_client,
    _parse_sse_events,
    _preview_story_payload,
    _story_with_setup,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "chat_turn_judgment_characterization.json"

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class _JudgmentLLM(LLMClient):
    """판정마다 정해 둔 답을 낸다. 엔딩 판정은 `ending_verdicts` 를 호출 순서대로 꺼낸다(예외면 올린다). 생성은
    `generation_error` 가 있으면 토큰 없이 그 예외를 올린다. 호출마다 (메서드, 호출 위치, 엔딩 판정이면 그 판정 문안이
    가리키는 엔딩 이름)을 남긴다."""

    def __init__(
        self,
        *,
        fired_rule_ids: list[str],
        match_id: str | None,
        image_error: Exception | None = None,
        ending_verdicts: list[bool | Exception] | None = None,
        ending_markers: dict[str, str] | None = None,
        generation_error: Exception | None = None,
        stat_error: Exception | None = None,
    ) -> None:
        self._fired_rule_ids = fired_rule_ids
        self._generation_error = generation_error
        self._stat_error = stat_error
        self._match_id = match_id
        self._image_error = image_error
        self._ending_verdicts = list(ending_verdicts or [])
        self._ending_markers = ending_markers or {}
        self.calls: list[list[str | None]] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.calls.append(["generate", usage.call_site, None])
        if self._generation_error is not None:
            raise self._generation_error
        yield "오늘은 비가 와."

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        if response_schema is MemorySummaryResult:
            self.calls.append(["generate_structured", usage.call_site, None])
            return MemorySummaryResult(summary="요약")
        if response_schema is EndingJudgmentResult:
            ending = next((name for marker, name in self._ending_markers.items() if marker in prompt), None)
            self.calls.append(["generate_structured", usage.call_site, ending])
            verdict = self._ending_verdicts.pop(0)
            if isinstance(verdict, Exception):
                raise verdict
            return EndingJudgmentResult(triggered=verdict)
        self.calls.append(["generate_structured", usage.call_site, None])
        if response_schema is StatRuleJudgmentResult:
            if self._stat_error is not None:
                raise self._stat_error
            return StatRuleJudgmentResult(fired_rule_ids=self._fired_rule_ids)
        if response_schema is ImageMatchJudgmentResult:
            if self._image_error is not None:
                raise self._image_error
            return ImageMatchJudgmentResult(matched_image_entity_id=self._match_id)
        raise AssertionError(f"예상하지 못한 응답 스키마: {response_schema}")


class _Case:
    """경우 하나의 셋업 결과 — 보낼 방(미리보기면 세션), 가짜 LLM, 기록에서 id 를 바꿔 쓸 이름표. `action` 은
    보내기(`"send"`)·재생성(`"regenerate"`)·미리보기(`"preview"`)이고, `arm` 은 요청 직전에 바꿔 끼울 것(커밋 뒤 URL
    서명 실패 등)이다. 미리보기는 방이 없어 `room_id` 가 비고 `preview_session_id` 가 있다."""

    def __init__(
        self,
        room_id: uuid.UUID | None,
        fake: _JudgmentLLM,
        names: dict[str, str],
        *,
        action: str = "send",
        arm: Callable[[pytest.MonkeyPatch], None] | None = None,
        preview_session_id: str | None = None,
    ) -> None:
        self.room_id = room_id
        self.preview_session_id = preview_session_id
        self.fake = fake
        self.names = names
        self.action = action
        self.arm = arm


# ── 경우 ─────────────────────────────────────────────────────────────────────────────────


async def _story_room_with_two_due_endings(db_client: httpx.AsyncClient, db_session: AsyncSession) -> _Case:
    """스토리 방의 2턴째 — 규칙 없는 엔딩 둘이 모두 판정 차례다(게이트 2). 스탯 판정·칸 판정은 성공하고, 첫 엔딩 판정은
    LLM 실패, 두 번째는 발동이다 — 두 번째를 판정하면 엔딩에 도달하고, 판정하지 않으면 엔딩 없이 끝난다."""
    room = await _open_room(db_client, db_session, turns=1, lane="story")
    cell_id = await _add_room_cell_and_endings(db_session, room.room_id, (2, 2))
    endings = (
        await db_session.execute(
            sa.select(Ending.entity_id, Ending.name, Ending.judgment_prompt)
            .join(StartingSetup, StartingSetup.id == Ending.starting_setup_id)
            .join(
                ChatRoom,
                sa.and_(
                    ChatRoom.content_version_id == StartingSetup.content_version_id,
                    ChatRoom.starting_setup_entity_id == StartingSetup.entity_id,
                ),
            )
            .where(ChatRoom.id == room.room_id)
            .order_by(Ending.order)
        )
    ).all()
    assert len(endings) == 2
    fake = _JudgmentLLM(
        fired_rule_ids=["a1"],
        match_id=str(cell_id),
        ending_verdicts=[LLMClientError("판정 실패"), True],
        ending_markers={prompt: name for _, name, prompt in endings},
    )
    names = {str(cell_id): "<cell>", **{str(entity_id): name for entity_id, name, _ in endings}}
    return _Case(room.room_id, fake, names)


async def _character_room_with_failing_image_judgment(db_client: httpx.AsyncClient, db_session: AsyncSession) -> _Case:
    """캐릭터 방의 2턴째 — 상황 이미지 후보가 하나 있고 그 판정 LLM 이 실패한다."""
    room = await _open_room(db_client, db_session, turns=1)
    image_id = await _add_room_situational_image(db_session, room.room_id)
    fake = _JudgmentLLM(fired_rule_ids=[], match_id=str(image_id), image_error=LLMClientError("판정 실패"))
    return _Case(room.room_id, fake, {str(image_id): "<image>"})


async def _story_room_with_three_changing_stats(db_client: httpx.AsyncClient, db_session: AsyncSession) -> _Case:
    """작가 순서 가·나·다 세 스탯이 이번 턴에 모두 바뀐다. 방의 스탯 행은 다(작가 순서 마지막)에만 남기고, 판정 모델은
    규칙을 나·가·다 순서로 낸다 — 작가 순서·행 순서·응답 순서가 서로 달라 어느 것을 따르는지 기록에서 갈린다."""
    user_id, content, setup = await _story_with_setup(db_session, opening_message="어서 와")
    stats = [
        StatDef(
            entity_id=uuid.uuid4(),
            starting_setup_id=setup.id,
            name=name,
            icon="heart",
            color="rose",
            min_value=0,
            max_value=100,
            initial_value=37,
            description=f"{name} 설명",
            order=order,
        )
        for order, name in enumerate(["가", "나", "다"])
    ]
    db_session.add_all(stats)
    await db_session.flush()
    for delta, stat in zip((3, 5, 7), stats, strict=True):
        db_session.add(
            StatRule(entity_id=uuid.uuid4(), stat_def_id=stat.id, condition=f"{stat.name} 규칙", delta=delta, order=0)
        )
    await db_session.commit()

    await _login_as(db_client, user_id)
    created = await db_client.post(
        "/chat-rooms", json={"contentId": str(content.id), "contentType": "story", "startingSetupId": str(setup.id)}
    )
    assert created.status_code == 201, created.text
    room_id = uuid.UUID(created.json()["id"])
    await db_session.execute(
        sa.delete(ChatRoomStat).where(
            ChatRoomStat.chat_room_id == room_id,
            ChatRoomStat.stat_entity_id.in_([stats[0].entity_id, stats[1].entity_id]),
        )
    )
    await db_session.commit()

    fake = _JudgmentLLM(fired_rule_ids=["b1", "a1", "c1"], match_id=None)
    return _Case(room_id, fake, {str(stat.entity_id): stat.name for stat in stats})


# ── 재생성 경우 ──────────────────────────────────────────────────────────────────────────
#
# 방은 매트릭스와 같은 모양이다 — 1턴을 심은 방(스토리는 칸 하나, 캐릭터는 상황 이미지 하나)의 마지막 응답을 다시 만든다.


async def _break_channel(db_session: AsyncSession, channel: str) -> None:
    """활성 세트의 `channel` 문안(늘 렌더되는 섹션)에 값이 없는 자리표시자를 붙여 렌더가 `PromptRenderError` 로 끝나게
    한다. 셋업이 캐시에 남긴 세트를 지워 요청이 고친 문안을 읽게 한다."""
    await db_session.execute(
        sa.update(PromptSection)
        .where(PromptSection.channel == channel, PromptSection.conditional.is_(False))
        .values(body=PromptSection.body + " {characterization_missing_value}")
    )
    await db_session.commit()
    keys = await redis_client.keys(f"{ACTIVE_PROMPT_SET_KEY_PREFIX}*")
    if keys:
        await redis_client.delete(*keys)


def _fail_url_signing(monkeypatch: pytest.MonkeyPatch) -> None:
    """커밋 뒤 그림 URL 서명을 실패시킨다. 서명 함수들이 공통으로 지나는 URL 조립을 바꿔, 서명을 부르는 자리가 옮겨 가도
    빗나가지 않게 한다."""

    def boom(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("서명 실패")

    monkeypatch.setattr(s3_module, "build_windowed_presigned_get_url", boom)


async def _regenerate_story(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    *,
    break_channel: str | None = None,
    generation_error: Exception | None = None,
    image_error: Exception | None = None,
    arm: Callable[[pytest.MonkeyPatch], None] | None = None,
) -> _Case:
    room = await _open_room(db_client, db_session, turns=1, lane="story")
    cell_id = await _add_room_cell_and_endings(db_session, room.room_id, ())
    if break_channel is not None:
        await _break_channel(db_session, break_channel)
    fake = _JudgmentLLM(
        fired_rule_ids=[], match_id=str(cell_id), image_error=image_error, generation_error=generation_error
    )
    return _Case(room.room_id, fake, {str(cell_id): "<cell>"}, action="regenerate", arm=arm)


async def _regenerate_character(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    *,
    break_channel: str | None = None,
    image_error: Exception | None = None,
    arm: Callable[[pytest.MonkeyPatch], None] | None = None,
) -> _Case:
    room = await _open_room(db_client, db_session, turns=1)
    image_id = await _add_room_situational_image(db_session, room.room_id)
    if break_channel is not None:
        await _break_channel(db_session, break_channel)
    fake = _JudgmentLLM(fired_rule_ids=[], match_id=str(image_id), image_error=image_error)
    return _Case(room.room_id, fake, {str(image_id): "<image>"}, action="regenerate", arm=arm)


# ── 미리보기 경우 ────────────────────────────────────────────────────────────────────────
#
# 초안은 매트릭스와 같은 모양이다 — 스탯 하나(규칙 a1), 게이트 1 엔딩 하나, 요청자 소유의 준비된 그림을 쓴 칸 하나.
# `change` 는 세션을 열기 전에 초안을 고친다.


# 초안의 스탯에 없는 스탯 id — 엔딩 규칙이 가리켜 값 없는 스탯 경고를 낸다. 기록에서 이름표로 바꾼다.
_MISSING_STAT_ID = uuid.UUID("00000000-0000-4000-8000-00000000beef")


def _fail_preview_save(monkeypatch: pytest.MonkeyPatch) -> None:
    """미리보기 세션 저장(Redis SET)을 실패시킨다. 저장 함수가 아니라 그 클라이언트의 SET 을 바꿔, 저장을 부르는 자리가
    옮겨 가도 빗나가지 않게 한다."""
    original_set = redis_client.set

    async def set_(name: Any, value: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(name, str) and name.startswith("preview-session:"):
            raise RedisError("미리보기 세션 저장 실패")
        return await original_set(name, value, *args, **kwargs)

    monkeypatch.setattr(redis_client, "set", set_)


def _drop_starting_setups(payload: dict[str, Any]) -> None:
    payload["startingSetups"] = []


def _ending_rule_on_missing_stat(payload: dict[str, Any]) -> None:
    [setup] = payload["startingSetups"]
    [ending] = setup["endings"]
    ending["statRules"] = [
        {"kind": "rule", "id": str(uuid.uuid4()), "statId": str(_MISSING_STAT_ID), "operator": "gte", "threshold": 0}
    ]


async def _preview_story(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    *,
    change: Callable[[dict[str, Any]], None] | None = None,
    break_channel: str | None = None,
    generation_error: Exception | None = None,
    stat_error: Exception | None = None,
    image_error: Exception | None = None,
    ending_verdicts: list[bool | Exception] | None = None,
    arm: Callable[[pytest.MonkeyPatch], None] | None = None,
) -> _Case:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    asset = await _make_asset(db_session, owner_user_id=user.id, status=AssetStatus.READY)
    await db_session.commit()
    await _login_as(db_client, user.id)
    cell_id, payload = _preview_story_payload(asset.id)
    draft: dict[str, Any] = payload
    if change is not None:
        change(draft)
    started = await db_client.post("/preview-sessions", json=draft)
    assert started.status_code == 201, started.text
    session_id = started.json()["previewSessionId"]
    assert isinstance(session_id, str)
    if break_channel is not None:
        await _break_channel(db_session, break_channel)

    names = {str(cell_id): "<cell>", str(_MISSING_STAT_ID): "<missing-stat>"}
    markers: dict[str, str] = {}
    for setup in draft["startingSetups"]:
        names.update({stat["id"]: stat["name"] for stat in setup["statDefs"]})
        names.update({ending["id"]: ending["name"] for ending in setup["endings"]})
        markers.update({ending["judgmentPrompt"]: ending["name"] for ending in setup["endings"]})
    fake = _JudgmentLLM(
        fired_rule_ids=["a1"],
        match_id=str(cell_id),
        image_error=image_error,
        # 판정 차례 엔딩은 하나다. 판정하면 발동하지 않는다고 답한다(경우가 따로 정하지 않으면).
        ending_verdicts=ending_verdicts if ending_verdicts is not None else [False],
        ending_markers=markers,
        generation_error=generation_error,
        stat_error=stat_error,
    )
    return _Case(None, fake, names, action="preview", arm=arm, preview_session_id=session_id)


_CASES: dict[str, Callable[[httpx.AsyncClient, AsyncSession], Awaitable[_Case]]] = {
    "ending-judgment-error-with-a-second-due-ending/send": _story_room_with_two_due_endings,
    "situational-image-judgment-error/send-character": _character_room_with_failing_image_judgment,
    "three-stats-change-in-one-turn/send": _story_room_with_three_changing_stats,
    "generation-prompt-render-failure/regenerate": lambda client, session: _regenerate_story(
        client, session, break_channel="generation"
    ),
    "generation-error/regenerate": lambda client, session: _regenerate_story(
        client, session, generation_error=LLMClientError("생성 실패")
    ),
    "media-judgment-error/regenerate": lambda client, session: _regenerate_story(
        client, session, image_error=LLMClientError("판정 실패")
    ),
    "media-judgment-prompt-render-failure/regenerate": lambda client, session: _regenerate_story(
        client, session, break_channel="image_judgment"
    ),
    "post-commit-signing-failure/regenerate": lambda client, session: _regenerate_story(
        client, session, arm=_fail_url_signing
    ),
    "situational-image-judgment-error/regenerate-character": lambda client, session: _regenerate_character(
        client, session, image_error=LLMClientError("판정 실패")
    ),
    "situational-image-judgment-prompt-render-failure/regenerate-character": lambda client, session: (
        _regenerate_character(client, session, break_channel="image_judgment")
    ),
    "post-commit-signing-failure/regenerate-character": lambda client, session: _regenerate_character(
        client, session, arm=_fail_url_signing
    ),
    "generation-error/preview": lambda client, session: _preview_story(
        client, session, generation_error=LLMClientError("생성 실패")
    ),
    "generation-prompt-render-failure/preview": lambda client, session: _preview_story(
        client, session, break_channel="generation"
    ),
    "stat-judgment-error/preview": lambda client, session: _preview_story(
        client, session, stat_error=LLMClientError("판정 실패")
    ),
    "media-judgment-error/preview": lambda client, session: _preview_story(
        client, session, image_error=LLMClientError("판정 실패")
    ),
    "media-judgment-prompt-render-failure/preview": lambda client, session: _preview_story(
        client, session, break_channel="image_judgment"
    ),
    "ending-judgment-error/preview": lambda client, session: _preview_story(
        client, session, ending_verdicts=[LLMClientError("판정 실패")]
    ),
    "ending-rule-on-missing-stat/preview": lambda client, session: _preview_story(
        client, session, change=_ending_rule_on_missing_stat
    ),
    "preview-save-fails/preview": lambda client, session: _preview_story(client, session, arm=_fail_preview_save),
    "story-without-setup-with-cell/preview": lambda client, session: _preview_story(
        client, session, change=_drop_starting_setups
    ),
}


# ── 기록 ─────────────────────────────────────────────────────────────────────────────────


def _norm(value: object, case: _Case) -> str | None:
    """id 를 이름표로 바꾼다 — 방은 `<room>`, 미리보기 세션은 `<session>`(하이픈 없는 hex 라 따로 바꾼다), 셋업이 이름을
    붙인 것은 그 이름, 나머지는 `<id>`."""
    if value is None:
        return None
    labels = {**({str(case.room_id): "<room>"} if case.room_id is not None else {}), **case.names}
    text = str(value)
    if case.preview_session_id is not None:
        text = text.replace(case.preview_session_id, "<session>")
    return _UUID.sub(lambda m: labels.get(m.group(0), "<id>"), text)


def _event(event: dict[str, Any], case: _Case) -> dict[str, Any]:
    kind = event["type"]
    if kind == "statChange":
        return {"type": kind, "stat": _norm(event["statId"], case), "newValue": event["newValue"]}
    if kind == "endingReached":
        return {"type": kind, "ending": _norm(event["endingId"], case)}
    if kind == "done":
        final = event["finalMessage"]
        return {"type": kind, "imageId": _norm(final.get("imageId"), case), "hasImageUrl": bool(final.get("imageUrl"))}
    if kind == "error":
        return {"type": kind, "message": event["message"]}
    return {"type": kind}


async def _preview_state(case: _Case) -> dict[str, Any]:
    assert case.preview_session_id is not None
    state = await get_preview_session(case.preview_session_id)
    assert state is not None
    return {
        "turnCount": state.turn_count,
        "endingReached": state.ending_reached,
        "stats": sorted([str(_norm(stat_id, case)), str(value)] for stat_id, value in state.stats.items()),
        "messages": [[message.role.value, _norm(message.image_id, case)] for message in state.messages],
    }


async def _room_state(db_session: AsyncSession, case: _Case) -> dict[str, Any]:
    if case.room_id is None:
        return await _preview_state(case)
    room = (
        await db_session.execute(
            sa.select(ChatRoom.turn_count, ChatRoom.ending_reached, ChatRoom.ending_entity_id).where(
                ChatRoom.id == case.room_id
            )
        )
    ).one()
    last_image = await db_session.scalar(
        sa.select(ChatMessage.image_id)
        .where(ChatMessage.chat_room_id == case.room_id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
    )
    stats = (
        await db_session.execute(
            sa.select(ChatRoomStat.stat_entity_id, ChatRoomStat.current_value).where(
                ChatRoomStat.chat_room_id == case.room_id
            )
        )
    ).all()
    return {
        "turnCount": room.turn_count,
        "endingReached": room.ending_reached,
        "ending": _norm(room.ending_entity_id, case),
        "lastImage": _norm(last_image, case),
        "stats": sorted([str(_norm(stat_id, case)), str(value)] for stat_id, value in stats),
    }


@pytest.mark.parametrize("case_name", list(_CASES))
async def test_turn_judgment_case_matches_the_recorded_behavior(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    case_name: str,
) -> None:
    case = await _CASES[case_name](db_client, db_session)
    sentry: list[list[str | None]] = []

    def capture_exception(error: BaseException | None = None, **kwargs: Any) -> None:
        tags = kwargs.get("tags") or {}
        sentry.append([type(error).__name__ if error is not None else None, tags.get("dependency")])

    monkeypatch.setattr(sentry_sdk, "capture_exception", capture_exception)
    if case.arm is not None:
        case.arm(monkeypatch)
    caplog.clear()
    _override_llm_client(case.fake)
    try:
        with caplog.at_level(logging.WARNING):
            if case.action == "regenerate":
                response = await db_client.post(f"/chat-rooms/{case.room_id}/regenerate")
            elif case.action == "preview":
                response = await db_client.post(
                    f"/preview-sessions/{case.preview_session_id}/messages", json={"content": "마을을 떠나자"}
                )
            else:
                response = await db_client.post(
                    f"/chat-rooms/{case.room_id}/messages", json={"content": "마을을 떠나자"}
                )
    finally:
        _clear_llm_override()

    assert response.status_code == 200, response.text
    # 앱이 남긴 경고만 — 로거 이름까지 남겨 흡수 자리가 다른 모듈로 옮겨 가면 기록이 갈리게 한다.
    logs = [
        [record.name, record.levelname, _norm(record.getMessage(), case)]
        for record in caplog.records
        if record.name.startswith("api.") and record.levelno >= logging.WARNING
    ]
    _assert_characterization(
        FIXTURE_PATH,
        case_name,
        {
            "events": [_event(event, case) for event in _parse_sse_events(response.text)],
            "state": await _room_state(db_session, case),
            "llm": case.fake.calls,
            "sentry": sentry,
            "logs": logs,
        },
    )


def test_recorded_cases_are_exactly_the_parametrized_cases() -> None:
    _assert_recorded_cases(FIXTURE_PATH, list(_CASES))
