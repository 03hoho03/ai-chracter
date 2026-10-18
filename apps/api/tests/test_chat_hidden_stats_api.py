"""플레이어에게 숨긴 스탯이 플레이어 응답에서만 빠지고 판정·엔딩은 그대로 쓰는지.

규칙(결과를 보기 전에 적었다):
- 방 응답(방 만들기·조회·이름 바꾸기·초기화·최신 버전으로·시작설정 바꾸기·버전 안내 확인·직전 응답 되돌리기)의 스냅숏
  스탯 정의와 스탯 값에서 숨긴 스탯만 빠진다. 값은 보이는 정의 기준으로 싣는다 — 정의가 없는 고아 값도 빠진다. 작가
  본인의 방도 같다.
- 스냅숏의 엔딩 스탯 규칙은 언제나 빈 목록이다. 엔딩 판정은 여전히 규칙(숨긴 스탯에 건 것 포함)대로 돈다.
- 스냅숏에는 판정 재료(스탯의 판정용 설명, 엔딩의 판정 문안·에필로그·힌트)가 키째 없다. 도달한 엔딩의 에필로그는 방 응답의
  엔딩 칸에 실린다.
- 턴 스트림(보내기·수정·재생성)에서 숨긴 스탯의 `statChange` 는 나가지 않는다. 그 턴에 바뀐 숨긴 스탯 가운데 익명 신호를 켠
  것이 하나라도 있으면 `hiddenStatSignal` 하나를 `statChange` 자리에서 낸다 — 몇 개가 바뀌었든 하나이고, 스탯 id·이름·방향·
  크기는 싣지 않는다. 신호를 끈 숨긴 스탯만 바뀌었거나 숨긴 스탯이 바뀌지 않았으면 내지 않는다.
- "그 턴에 바뀌었다" 는 턴 시작 값(반영 전 값) 대비다. 재생성은 옛 응답이 남긴 지금 값이 아니라 옛 응답의 효과를 되돌린 값과
  재판정 결과를 비교한다 — 옛 응답과 같은 결과여도 이번 턴에 바뀌었으면 신호가 서고, 시작값으로 돌아갔으면 서지 않는다.

방에는 판정 스탯 셋이 있다 — 보이는 "호감"(규칙 a1 +3), 숨긴 "속마음"(규칙 b1 +5), 숨긴 "의심"(규칙 c1 +4). 셋 다 시작값
37 이다. 엔딩 "고백"은 숨긴 "속마음" ≥ 40 에 걸려 있다."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import EndingJudgmentResult, StatRuleJudgmentResult
from api.db.models import (
    ChatMessage,
    ChatMessageRole,
    ChatRoomStat,
    Content,
    Ending,
    EndingRule,
    EndingRuleOperator,
    StartingSetup,
    StatDef,
)
from api.db.models.story import StatRule
from api.llm.client import LLMCallContext, LLMClient
from factories import (
    _clear_llm_override,
    _login_as,
    _make_user,
    _override_llm_client,
    _parse_sse_events,
    _story_with_setup,
)


class _JudgeLLM(LLMClient):
    """생성은 한 토큰, 스탯 판정은 `fired` 를 차례로 꺼내고, 엔딩 판정은 `ending` 대로 답한다. 다른 구조화 호출은 실패다."""

    def __init__(self, *fired: list[str], ending: bool = False) -> None:
        self._fired = list(fired)
        self._ending = ending

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        yield "응답"

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        if response_schema is StatRuleJudgmentResult:
            return StatRuleJudgmentResult(fired_rule_ids=self._fired.pop(0))
        assert response_schema is EndingJudgmentResult
        return EndingJudgmentResult(triggered=self._ending)


@dataclass
class _Story:
    author_id: uuid.UUID
    content: Content
    setup: StartingSetup
    shown: str
    hidden: str
    doubt: str


def _stat(setup: StartingSetup, name: str, order: int, *, hidden: bool, signal: bool) -> StatDef:
    return StatDef(
        entity_id=uuid.uuid4(),
        starting_setup_id=setup.id,
        name=name,
        icon="heart",
        color="rose",
        min_value=0,
        max_value=100,
        initial_value=37,
        description=f"{name} 판정 설명",
        order=order,
        hidden_from_player=hidden,
        player_description=f"{name} 플레이어 설명",
        signal_hidden_change=signal,
    )


async def _hidden_story(db_session: AsyncSession, *, signal: bool = True) -> _Story:
    author_id, content, setup = await _story_with_setup(db_session, opening_message="어서 와")
    shown = _stat(setup, "호감", 0, hidden=False, signal=False)
    hidden = _stat(setup, "속마음", 1, hidden=True, signal=signal)
    doubt = _stat(setup, "의심", 2, hidden=True, signal=signal)
    db_session.add_all([shown, hidden, doubt])
    await db_session.flush()
    for stat, condition, delta in ((shown, "감싸 준다", 3), (hidden, "속을 털어놓는다", 5), (doubt, "말을 바꾼다", 4)):
        db_session.add(StatRule(entity_id=uuid.uuid4(), stat_def_id=stat.id, condition=condition, delta=delta, order=0))
    ending = Ending(
        entity_id=uuid.uuid4(),
        starting_setup_id=setup.id,
        name="고백",
        turn_count_gate=1,
        judgment_prompt="마음을 털어놓았는가?",
        epilogue="끝",
        hint="고백 힌트",
        order=1,
    )
    db_session.add(ending)
    await db_session.flush()
    db_session.add(
        EndingRule(
            entity_id=uuid.uuid4(),
            ending_id=ending.id,
            stat_def_entity_id=hidden.entity_id,
            operator=EndingRuleOperator.GTE,
            threshold=40,
            order=1,
        )
    )
    await db_session.commit()
    return _Story(author_id, content, setup, str(shown.entity_id), str(hidden.entity_id), str(doubt.entity_id))


async def _player_room(db_client: httpx.AsyncClient, db_session: AsyncSession, story: _Story) -> uuid.UUID:
    """작가가 아닌 플레이어의 방."""
    player = _make_user()
    db_session.add(player)
    await db_session.commit()
    await _login_as(db_client, player.id)
    return await _create_room(db_client, story)


async def _create_room(db_client: httpx.AsyncClient, story: _Story) -> uuid.UUID:
    created = await _post_room(db_client, story)
    assert created.status_code == 201, created.text
    return uuid.UUID(created.json()["id"])


async def _post_room(db_client: httpx.AsyncClient, story: _Story) -> httpx.Response:
    return await db_client.post(
        "/chat-rooms",
        json={"contentId": str(story.content.id), "contentType": "story", "startingSetupId": str(story.setup.id)},
    )


async def _turn(
    db_client: httpx.AsyncClient, method: str, path: str, body: dict[str, object] | None, fake: _JudgeLLM
) -> list[dict[str, Any]]:
    _override_llm_client(fake)
    try:
        resp = await db_client.request(method, path, json=body)
    finally:
        _clear_llm_override()
    assert resp.status_code == 200, resp.text
    events = _parse_sse_events(resp.text)
    assert events[-1]["type"] == "done", resp.text
    return events


async def _send(db_client: httpx.AsyncClient, room_id: uuid.UUID, fake: _JudgeLLM) -> list[dict[str, Any]]:
    return await _turn(db_client, "POST", f"/chat-rooms/{room_id}/messages", {"content": "말해 줘"}, fake)


async def _last_message(db_session: AsyncSession, room_id: uuid.UUID, role: ChatMessageRole) -> uuid.UUID:
    db_session.expire_all()
    message_id = await db_session.scalar(
        sa.select(ChatMessage.id)
        .where(ChatMessage.chat_room_id == room_id, ChatMessage.role == role)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
    )
    assert message_id is not None
    return message_id


async def _room_stat(db_session: AsyncSession, room_id: uuid.UUID, stat_id: str) -> float:
    row = await db_session.get(ChatRoomStat, (room_id, uuid.UUID(stat_id)), populate_existing=True)
    assert row is not None
    return float(row.current_value)


def _assert_player_snapshot(body: dict[str, Any], story: _Story) -> None:
    snapshot = body["contentSnapshot"]
    assert [stat["id"] for stat in snapshot["stats"]] == [story.shown]
    assert list(body["stats"]) == [story.shown]
    assert [ending["statRules"] for ending in snapshot["endings"]] == [[]]
    assert [sorted(stat) for stat in snapshot["stats"]] == [
        ["color", "icon", "id", "initialValue", "maxValue", "minValue", "name", "playerDescription", "unit"]
    ]
    assert [sorted(ending) for ending in snapshot["endings"]] == [["id", "name", "statRules", "turnCountGate"]]


def _types(events: list[dict[str, Any]]) -> list[str]:
    return [event["type"] for event in events]


async def test_every_room_response_leaves_out_the_hidden_stats_and_the_judgment_material(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """방 응답을 돌려주는 여덟 경로가 모두 숨긴 두 스탯의 정의·값만 빼고 보이는 스탯은 남긴다. 정의가 없는 고아 값도 빠진다.
    스냅숏의 스탯·엔딩에는 판정 재료 칸이 없고 엔딩 규칙은 빈 목록이다. 숨긴 스탯 값은 DB 에 그대로 남아 판정이 읽는다."""
    story = await _hidden_story(db_session)
    player = _make_user()
    db_session.add(player)
    await db_session.commit()
    await _login_as(db_client, player.id)
    created = await _post_room(db_client, story)
    assert created.status_code == 201, created.text
    room_id = uuid.UUID(created.json()["id"])
    db_session.add(ChatRoomStat(chat_room_id=room_id, stat_entity_id=uuid.uuid4(), current_value=12))
    await db_session.commit()

    responses: dict[str, httpx.Response] = {"create": created}
    responses["get"] = await db_client.get(f"/chat-rooms/{room_id}")
    responses["rename"] = await db_client.patch(f"/chat-rooms/{room_id}", json={"name": "새 이름"})
    responses["pin-latest-version"] = await db_client.post(f"/chat-rooms/{room_id}/pin-latest-version")
    responses["acknowledge-version-upgrade"] = await db_client.post(
        f"/chat-rooms/{room_id}/acknowledge-version-upgrade"
    )
    await _send(db_client, room_id, _JudgeLLM(["b1"]))
    await _turn(db_client, "POST", f"/chat-rooms/{room_id}/regenerate", None, _JudgeLLM(["c1"]))
    current_reply = await _last_message(db_session, room_id, ChatMessageRole.ASSISTANT)
    responses["restore-previous"] = await db_client.post(
        f"/chat-rooms/{room_id}/messages/{current_reply}/restore-previous"
    )
    responses["reset"] = await db_client.post(f"/chat-rooms/{room_id}/reset")
    responses["change-starting-setup"] = await db_client.post(
        f"/chat-rooms/{room_id}/change-starting-setup", json={"startingSetupId": str(story.setup.id)}
    )

    for path, resp in responses.items():
        assert resp.status_code in (200, 201), (path, resp.text)
        _assert_player_snapshot(resp.json(), story)
    assert await _room_stat(db_session, room_id, story.hidden) == 37
    assert await _room_stat(db_session, room_id, story.doubt) == 37


async def test_the_author_room_hides_the_stats_too(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """작가 본인이 연 방도 플레이어 화면이라 같이 숨긴다(작가가 숨긴 스탯을 보는 곳은 빌더 미리보기다)."""
    story = await _hidden_story(db_session)
    await _login_as(db_client, story.author_id)
    room_id = await _create_room(db_client, story)

    resp = await db_client.get(f"/chat-rooms/{room_id}")

    assert resp.status_code == 200
    _assert_player_snapshot(resp.json(), story)


async def test_the_room_snapshot_carries_the_player_description_of_visible_stats_only(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """방 스냅숏의 보이는 스탯에는 플레이어용 설명이 실리고(판정용 설명과 다른 칸), 숨긴 스탯의 설명은 스탯째 빠진다.
    설명이 없는 스탯은 null 로 실린다."""
    story = await _hidden_story(db_session)
    bare = _stat(story.setup, "체력", 3, hidden=False, signal=False)
    bare.player_description = None
    db_session.add(bare)
    await db_session.commit()
    room_id = await _player_room(db_client, db_session, story)

    resp = await db_client.get(f"/chat-rooms/{room_id}")

    assert resp.status_code == 200
    stats = resp.json()["contentSnapshot"]["stats"]
    assert [(stat["id"], stat["playerDescription"]) for stat in stats] == [
        (story.shown, "호감 플레이어 설명"),
        (str(bare.entity_id), None),
    ]
    assert "속마음 플레이어 설명" not in resp.text


@pytest.mark.parametrize(
    ("signal", "fired", "expected_types"),
    [
        pytest.param(
            True, ["a1", "b1", "c1"], ["token", "statChange", "hiddenStatSignal", "done"], id="two-hidden-one-signal"
        ),
        pytest.param(True, ["b1"], ["token", "hiddenStatSignal", "done"], id="one-hidden-signal"),
        pytest.param(False, ["a1", "b1", "c1"], ["token", "statChange", "done"], id="signal-off"),
        pytest.param(True, ["a1"], ["token", "statChange", "done"], id="no-hidden-change"),
    ],
)
async def test_a_turn_streams_only_visible_stat_changes_and_one_anonymous_signal(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    signal: bool,
    fired: list[str],
    expected_types: list[str],
) -> None:
    """엔딩 문턱(속마음 ≥ 40)을 넘겨도 판정이 거절하는 턴. 숨긴 스탯 값은 DB 에서 바뀐다."""
    story = await _hidden_story(db_session, signal=signal)
    room_id = await _player_room(db_client, db_session, story)

    events = await _send(db_client, room_id, _JudgeLLM(fired))

    assert _types(events) == expected_types
    assert [(e["statId"], e["newValue"]) for e in events if e["type"] == "statChange"] == (
        [(story.shown, 40)] if "a1" in fired else []
    )
    assert [e for e in events if e["type"] == "hiddenStatSignal"] == (
        [{"type": "hiddenStatSignal"}] if "hiddenStatSignal" in expected_types else []
    )
    assert await _room_stat(db_session, room_id, story.hidden) == (42 if "b1" in fired else 37)


async def test_an_ending_on_a_hidden_stat_is_still_reached(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """엔딩 판정의 입력은 숨김과 무관하다 — 숨긴 스탯이 문턱을 넘긴 턴에 엔딩에 닿는다. 신호는 엔딩 앞에 나간다."""
    story = await _hidden_story(db_session)
    room_id = await _player_room(db_client, db_session, story)

    events = await _send(db_client, room_id, _JudgeLLM(["b1"], ending=True))

    assert _types(events) == ["token", "hiddenStatSignal", "endingReached", "done"]
    room = await db_client.get(f"/chat-rooms/{room_id}")
    assert room.json()["endingReached"] is True
    # 스냅숏에서 에필로그가 빠져도 도달한 엔딩의 에필로그는 방 응답의 엔딩 칸으로 다시 받는다.
    assert room.json()["ending"]["epilogue"] == "끝"
    _assert_player_snapshot(room.json(), story)


async def test_editing_a_message_streams_the_signal_instead_of_hidden_stat_changes(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    story = await _hidden_story(db_session)
    room_id = await _player_room(db_client, db_session, story)
    await _send(db_client, room_id, _JudgeLLM([]))
    user_message = await _last_message(db_session, room_id, ChatMessageRole.USER)

    events = await _turn(
        db_client,
        "PATCH",
        f"/chat-rooms/{room_id}/messages/{user_message}",
        {"content": "고쳐 말한다"},
        _JudgeLLM(["a1", "b1", "c1"]),
    )

    assert _types(events) == ["token", "statChange", "hiddenStatSignal", "done"]
    assert [e["statId"] for e in events if e["type"] == "statChange"] == [story.shown]


async def test_regenerating_signals_hidden_stats_changed_from_the_turn_start(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """재생성의 신호는 턴 시작 값(37) 대비 재판정 결과로 정한다. 옛 응답이 남긴 지금 값과 같아도(42 → 42) 이번 턴에 바뀌었으니
    신호가 서고, 시작값으로 돌아가면(42 → 37) 지금 값과는 달라도 이번 턴에 바뀐 것이 없으니 서지 않는다. 보이는 스탯의
    `statChange` 는 그대로 지금 값 대비다(화면이 지금 값을 들고 있다)."""
    story = await _hidden_story(db_session)
    room_id = await _player_room(db_client, db_session, story)
    await _send(db_client, room_id, _JudgeLLM([]))
    path = f"/chat-rooms/{room_id}/regenerate"

    changed = await _turn(db_client, "POST", path, None, _JudgeLLM(["a1", "b1", "c1"]))
    same_as_old = await _turn(db_client, "POST", path, None, _JudgeLLM(["a1", "b1", "c1"]))
    back_to_start = await _turn(db_client, "POST", path, None, _JudgeLLM(["a1"]))

    assert _types(changed) == ["token", "statChange", "hiddenStatSignal", "done"]
    assert [e["statId"] for e in changed if e["type"] == "statChange"] == [story.shown]
    assert _types(same_as_old) == ["token", "hiddenStatSignal", "done"]
    assert _types(back_to_start) == ["token", "done"]
    assert await _room_stat(db_session, room_id, story.hidden) == 37
