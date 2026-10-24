"""장면 헤더 — 작가가 켠 스토리 방에서 매 턴 응답 뒤 판정 모델이 지금 장면의 장소·시간을 적고, 그 값이 AI 메시지에 저장되고
스트림(`sceneChange`)과 메시지 응답으로 나가는지.

"직전 장면"(판정이 이어받을 값) 규칙: 마지막 AI 메시지에 장면이 저장돼 있으면 그 장면, 비어 있으면 그 메시지가 오프닝(AI 턴
없음)일 때만 시작설정의 첫 장면이고 아니면(토글 전 메시지·버전을 옮긴 방) 첫 장면으로 떨어지지 않고 비운다. 재생성은 바꾸는 응답
이전 메시지 기준이다.
판정이 비운 칸·길이를 넘긴 칸·판정 실패는 직전 장면을 그대로 잇는다. 생성 프롬프트에는 싣지 않는다.

판정 호출은 가짜 클라이언트가 호출 위치별 큐로 답하고 받은 프롬프트를 남긴다 — 직전 장면이 프롬프트에 실렸는지로 이어받을
값을 본다."""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.preview_session import get_preview_session
from api.chat.prompt_builder import (
    EndingJudgmentResult,
    SceneJudgmentResult,
    StatRuleJudgmentResult,
)
from api.chat.schemas import StoryScene
from api.db.models import ChatMessage, ChatMessageRole, ChatRoom, StartingSetup
from api.db.models.chat import ChatPreviousResponse
from api.db.models.prompt import PromptSection
from api.db.models.story import StoryVersionDetail
from api.llm.client import LLMCallContext, LLMClient, LLMClientError
from factories import (
    Room,
    _clear_llm_override,
    _login_as,
    _make_user,
    _open_room,
    _override_llm_client,
    _parse_sse_events,
)

_INITIAL = {"place": "낡은 등대", "time": "동트기 전"}


class _SceneLLM(LLMClient):
    """호출 위치별 응답 큐. 장면 판정 응답이 예외면 그것을 던진다. 받은 (호출 위치, 프롬프트)를 차례로 남긴다."""

    def __init__(self, *, scene: list[SceneJudgmentResult | Exception], tokens: tuple[str, ...] = ("응답이다.",)) -> None:
        self._scene = list(scene)
        self._tokens = tokens
        self.calls: list[tuple[str, str]] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.calls.append((usage.call_site, prompt))
        for token in self._tokens:
            yield token

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.calls.append((usage.call_site, prompt))
        if response_schema is SceneJudgmentResult:
            answer = self._scene.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        if response_schema is StatRuleJudgmentResult:
            return StatRuleJudgmentResult(fired_rule_ids=[])
        if response_schema is EndingJudgmentResult:
            return EndingJudgmentResult(triggered=False)
        raise NotImplementedError(response_schema)

    def prompts(self, call_site: str) -> list[str]:
        return [prompt for site, prompt in self.calls if site == call_site]


async def _setup_of(db_session: AsyncSession, room: Room) -> StartingSetup:
    version_id, setup_entity_id = (
        await db_session.execute(
            sa.select(ChatRoom.content_version_id, ChatRoom.starting_setup_entity_id).where(ChatRoom.id == room.room_id)
        )
    ).one()
    setup = await db_session.scalar(
        sa.select(StartingSetup).where(
            StartingSetup.content_version_id == version_id, StartingSetup.entity_id == setup_entity_id
        )
    )
    assert setup is not None
    return setup


async def _story_room(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    *,
    turns: int,
    enabled: bool = True,
    initial: dict[str, str] | None = _INITIAL,
) -> Room:
    room = await _open_room(db_client, db_session, turns=turns, lane="story")
    setup = await _setup_of(db_session, room)
    await db_session.execute(
        sa.update(StoryVersionDetail)
        .where(StoryVersionDetail.content_version_id == setup.content_version_id)
        .values(scene_header_enabled=enabled)
    )
    setup.initial_scene_place = initial["place"] if initial else None
    setup.initial_scene_time = initial["time"] if initial else None
    await db_session.commit()
    return room


async def _set_scene(db_session: AsyncSession, message: ChatMessage, scene: dict[str, str | None] | None) -> None:
    await db_session.execute(sa.update(ChatMessage).where(ChatMessage.id == message.id).values(scene=scene))
    await db_session.commit()


async def _last_assistant(db_session: AsyncSession, room: Room) -> ChatMessage:
    message = await db_session.scalar(
        sa.select(ChatMessage)
        .where(ChatMessage.chat_room_id == room.room_id, ChatMessage.role == ChatMessageRole.ASSISTANT)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    assert message is not None
    return message


async def _request(
    db_client: httpx.AsyncClient, fake: LLMClient, method: str, path: str, body: dict[str, object] | None = None
) -> list[dict[str, Any]]:
    _override_llm_client(fake)
    try:
        response = await db_client.request(method, path, json=body)
    finally:
        _clear_llm_override()
    assert response.status_code == 200, response.text
    return _parse_sse_events(response.text)


async def _send(db_client: httpx.AsyncClient, fake: LLMClient, room: Room, content: str = "옥상으로 가자") -> list[dict[str, Any]]:
    return await _request(db_client, fake, "POST", f"/chat-rooms/{room.room_id}/messages", {"content": content})


def _scene_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if event["type"] == "sceneChange"]


def _done(events: list[dict[str, Any]]) -> dict[str, Any]:
    (done,) = [event for event in events if event["type"] == "done"]
    final: dict[str, Any] = done["finalMessage"]
    return final


# ── 새 턴: 저장·스트림·응답 ─────────────────────────────────────────────────────────────────────


async def test_first_turn_judges_from_the_initial_scene_and_saves_streams_and_returns_the_scene(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """오프닝뿐인 방의 첫 턴은 시작설정의 첫 장면을 직전 장면으로 판정 프롬프트에 싣는다. 판정이 장소만 적고 시간을 비우면 시간은
    첫 장면을 잇는다. 그 장면이 AI 메시지에 저장되고 `sceneChange`(그 메시지 id)와 `done` 의 메시지, 방 재조회에 같이 실린다.
    생성 프롬프트에는 장면이 없다."""
    room = await _story_room(db_client, db_session, turns=0)
    fake = _SceneLLM(scene=[SceneJudgmentResult(place="  학교 옥상 ", time=None)])

    events = await _send(db_client, fake, room)

    expected = {"place": "학교 옥상", "time": "동트기 전"}
    (scene_prompt,) = fake.prompts("chat_scene_judgment")
    assert "낡은 등대" in scene_prompt and "동트기 전" in scene_prompt and "옥상으로 가자" in scene_prompt
    (generation_prompt,) = fake.prompts("chat_generate")
    assert "낡은 등대" not in generation_prompt
    saved = await _last_assistant(db_session, room)
    assert saved.scene == expected
    assert _scene_events(events) == [{"type": "sceneChange", "messageId": str(saved.id), **expected}]
    assert _done(events)["scene"] == expected
    assert [event["type"] for event in events][-2:] == ["sceneChange", "done"]

    room_body = (await db_client.get(f"/chat-rooms/{room.room_id}")).json()
    assert room_body["messages"][-1]["scene"] == expected
    assert room_body["messages"][0]["scene"] is None
    assert room_body["contentSnapshot"]["sceneHeaderEnabled"] is True
    assert room_body["contentSnapshot"]["initialScene"] == _INITIAL


async def test_a_turn_judges_from_the_last_assistant_scene_and_sends_the_event_even_when_unchanged(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """AI 턴이 있는 방은 마지막 AI 메시지의 장면을 잇는다(첫 장면이 아니다). 판정이 둘 다 비워 장면이 그대로여도 `sceneChange` 를
    보낸다."""
    room = await _story_room(db_client, db_session, turns=2)
    await _set_scene(db_session, room.turns[1][1], {"place": "교실", "time": "아침"})
    await _set_scene(db_session, room.turns[2][1], {"place": "운동장", "time": "점심"})
    fake = _SceneLLM(scene=[SceneJudgmentResult(place=None, time=None)])

    events = await _send(db_client, fake, room)

    (scene_prompt,) = fake.prompts("chat_scene_judgment")
    assert "운동장" in scene_prompt and "교실" not in scene_prompt and "낡은 등대" not in scene_prompt
    assert (await _last_assistant(db_session, room)).scene == {"place": "운동장", "time": "점심"}
    assert [(e["place"], e["time"]) for e in _scene_events(events)] == [("운동장", "점심")]


async def test_a_room_whose_last_assistant_scene_is_empty_does_not_fall_back_to_the_initial_scene(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """토글을 켜기 전 메시지나 버전을 옮긴 방처럼 마지막 AI 메시지의 장면이 비어 있으면 직전 장면이 없다 — 첫 장면을 싣지 않고
    직전 장면 섹션째 빠진다. 판정이 비우면 장면도 빈 채로 남는다(헤더가 빈다)."""
    room = await _story_room(db_client, db_session, turns=3)
    fake = _SceneLLM(scene=[SceneJudgmentResult(place=None, time="밤")])

    await _send(db_client, fake, room)

    (scene_prompt,) = fake.prompts("chat_scene_judgment")
    assert "낡은 등대" not in scene_prompt and "동트기 전" not in scene_prompt
    assert (await _last_assistant(db_session, room)).scene == {"place": None, "time": "밤"}


async def test_a_room_without_an_initial_scene_judges_with_no_previous_scene(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _story_room(db_client, db_session, turns=0, initial=None)
    fake = _SceneLLM(scene=[SceneJudgmentResult(place="편의점", time=None)])

    events = await _send(db_client, fake, room)

    assert (await _last_assistant(db_session, room)).scene == {"place": "편의점", "time": None}
    assert _done(events)["scene"] == {"place": "편의점", "time": None}
    snapshot = (await db_client.get(f"/chat-rooms/{room.room_id}")).json()["contentSnapshot"]
    assert snapshot["initialScene"] is None


@pytest.mark.parametrize(
    ("judged", "expected"),
    [
        pytest.param(SceneJudgmentResult(place="가" * 24, time="나" * 25), {"place": "가" * 24, "time": "동트기 전"}, id="time-too-long"),
        pytest.param(SceneJudgmentResult(place="가" * 25, time="  "), {"place": "낡은 등대", "time": "동트기 전"}, id="place-too-long-time-blank"),
    ],
)
async def test_a_field_over_the_limit_or_blank_inherits_the_previous_scene(
    db_client: httpx.AsyncClient, db_session: AsyncSession, judged: SceneJudgmentResult, expected: dict[str, str]
) -> None:
    """앞뒤 공백을 뗀 뒤 24자를 넘는 칸·빈 칸은 그 칸만 직전 장면을 잇는다(24자는 받는다)."""
    room = await _story_room(db_client, db_session, turns=0)

    await _send(db_client, _SceneLLM(scene=[judged]), room)

    assert (await _last_assistant(db_session, room)).scene == expected


async def test_a_failed_scene_judgment_keeps_the_previous_scene_and_the_rest_of_the_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """판정이 실패하면 그 메시지 장면은 직전 장면 그대로다. 다른 판정·커밋·`done` 은 영향받지 않는다."""
    room = await _story_room(db_client, db_session, turns=1)
    await _set_scene(db_session, room.turns[1][1], {"place": "교실", "time": "아침"})
    fake = _SceneLLM(scene=[LLMClientError("장면 판정 실패")])

    events = await _send(db_client, fake, room)

    assert (await _last_assistant(db_session, room)).scene == {"place": "교실", "time": "아침"}
    assert [(e["place"], e["time"]) for e in _scene_events(events)] == [("교실", "아침")]
    assert _done(events)["content"] == "응답이다."
    assert fake.prompts("chat_stat_judgment")
    assert await db_session.scalar(sa.select(ChatRoom.turn_count).where(ChatRoom.id == room.room_id)) == 2


async def test_scene_judgment_keeps_running_after_the_ending(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """엔딩에 도달한 방도 스탯·엔딩 판정은 멈추지만 장면 판정은 계속한다(미디어 북 칸 판정과 같다)."""
    room = await _story_room(db_client, db_session, turns=1)
    await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(ending_reached=True))
    await db_session.commit()
    fake = _SceneLLM(scene=[SceneJudgmentResult(place="바닷가", time="해질녘")])

    await _send(db_client, fake, room)

    assert fake.prompts("chat_stat_judgment") == []
    assert (await _last_assistant(db_session, room)).scene == {"place": "바닷가", "time": "해질녘"}


async def test_a_set_without_the_channel_skips_the_judgment_and_keeps_the_previous_scene(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """배포 직후 캐시에 남은 옛 세트처럼 판정 세트에 이 채널 행이 없으면 렌더가 비어 판정을 부르지 않고 직전 장면을 잇는다."""
    room = await _story_room(db_client, db_session, turns=0)
    await db_session.execute(sa.delete(PromptSection).where(PromptSection.channel == "scene_judgment"))
    await db_session.commit()
    fake = _SceneLLM(scene=[])

    events = await _send(db_client, fake, room)

    assert fake.prompts("chat_scene_judgment") == []
    assert (await _last_assistant(db_session, room)).scene == _INITIAL
    assert [(e["place"], e["time"]) for e in _scene_events(events)] == [("낡은 등대", "동트기 전")]


async def test_a_room_with_the_toggle_off_makes_no_scene_call_event_or_scene(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _story_room(db_client, db_session, turns=1, enabled=False)
    fake = _SceneLLM(scene=[])

    events = await _send(db_client, fake, room)

    assert fake.prompts("chat_scene_judgment") == []
    assert _scene_events(events) == []
    assert _done(events)["scene"] is None
    assert (await _last_assistant(db_session, room)).scene is None
    snapshot = (await db_client.get(f"/chat-rooms/{room.room_id}")).json()["contentSnapshot"]
    assert snapshot["sceneHeaderEnabled"] is False


# ── 수정·재생성·삭제·되돌리기 ───────────────────────────────────────────────────────────────────


async def test_edit_judges_from_the_scene_before_the_edited_message(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """수정은 고친 사용자 메시지 앞까지로 되감은 새 턴이라, 그 앞 마지막 AI 메시지의 장면을 잇는다."""
    room = await _story_room(db_client, db_session, turns=2)
    await _set_scene(db_session, room.turns[1][1], {"place": "교실", "time": "아침"})
    await _set_scene(db_session, room.turns[2][1], {"place": "운동장", "time": "점심"})
    fake = _SceneLLM(scene=[SceneJudgmentResult(place=None, time="저녁")])

    events = await _request(
        db_client, fake, "PATCH", f"/chat-rooms/{room.room_id}/messages/{room.turns[2][0].id}", {"content": "고쳐 말하자"}
    )

    (scene_prompt,) = fake.prompts("chat_scene_judgment")
    assert "교실" in scene_prompt and "운동장" not in scene_prompt
    assert (await _last_assistant(db_session, room)).scene == {"place": "교실", "time": "저녁"}
    assert len(_scene_events(events)) == 1


async def test_regenerate_judges_from_the_scene_before_the_replaced_response_and_undo_swaps_scenes(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """재생성은 바꾸는 응답 이전 메시지의 장면을 잇는다(바꾸는 응답 자신의 장면이 아니다). 직전 응답 되돌리기는 장면을 본문과
    함께 맞바꾼다 — 되살린 응답은 원래 장면으로, 보관 행은 밀려난 응답의 장면으로. 그 뒤 새 턴은 되살린 응답의 장면을 잇는다."""
    room = await _story_room(db_client, db_session, turns=2)
    await _set_scene(db_session, room.turns[1][1], {"place": "교실", "time": "아침"})
    await _set_scene(db_session, room.turns[2][1], {"place": "운동장", "time": "점심"})
    fake = _SceneLLM(scene=[SceneJudgmentResult(place="도서관", time=None)])

    events = await _request(db_client, fake, "POST", f"/chat-rooms/{room.room_id}/regenerate")

    (scene_prompt,) = fake.prompts("chat_scene_judgment")
    assert "교실" in scene_prompt and "운동장" not in scene_prompt
    regenerated = await _last_assistant(db_session, room)
    assert regenerated.scene == {"place": "도서관", "time": "아침"}
    assert [e["messageId"] for e in _scene_events(events)] == [str(regenerated.id)]
    kept = await db_session.get(ChatPreviousResponse, room.room_id, populate_existing=True)
    assert kept is not None and kept.scene == {"place": "운동장", "time": "점심"}

    restored = await db_client.post(f"/chat-rooms/{room.room_id}/messages/{regenerated.id}/restore-previous")

    assert restored.status_code == 200, restored.text
    assert restored.json()["messages"][-1]["scene"] == {"place": "운동장", "time": "점심"}
    assert (await _last_assistant(db_session, room)).scene == {"place": "운동장", "time": "점심"}
    kept = await db_session.get(ChatPreviousResponse, room.room_id, populate_existing=True)
    assert kept is not None and kept.scene == {"place": "도서관", "time": "아침"}

    after_undo = _SceneLLM(scene=[SceneJudgmentResult(place=None, time=None)])
    await _send(db_client, after_undo, room)
    (next_prompt,) = after_undo.prompts("chat_scene_judgment")
    assert "운동장" in next_prompt and "도서관" not in next_prompt


async def test_a_second_regenerate_keeps_the_first_regenerated_scene(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """보관 행은 방당 하나라 두 번째 재생성은 행을 덮는다 — 그때 장면도 함께 덮어야 되돌리기가 밀려난 응답의 장면을 되살린다."""
    room = await _story_room(db_client, db_session, turns=1)
    await _request(db_client, _SceneLLM(scene=[SceneJudgmentResult(place="도서관", time="오후")]), "POST", f"/chat-rooms/{room.room_id}/regenerate")
    await _request(db_client, _SceneLLM(scene=[SceneJudgmentResult(place="매점", time="오후")]), "POST", f"/chat-rooms/{room.room_id}/regenerate")

    kept = await db_session.get(ChatPreviousResponse, room.room_id, populate_existing=True)
    assert kept is not None and kept.scene == {"place": "도서관", "time": "오후"}
    assert (await _last_assistant(db_session, room)).scene == {"place": "매점", "time": "오후"}


async def _delete_turn(db_client: httpx.AsyncClient, room: Room, turn: int) -> None:
    for message in room.turns[turn]:
        deleted = await db_client.delete(f"/chat-rooms/{room.room_id}/messages/{message.id}")
        assert deleted.status_code == 200, deleted.text


async def test_after_deleting_the_last_turn_the_next_turn_judges_from_the_remaining_last_scene(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    room = await _story_room(db_client, db_session, turns=2)
    await _set_scene(db_session, room.turns[1][1], {"place": "교실", "time": "아침"})
    await _set_scene(db_session, room.turns[2][1], {"place": "운동장", "time": "점심"})
    await _delete_turn(db_client, room, 2)
    fake = _SceneLLM(scene=[SceneJudgmentResult(place=None, time=None)])

    await _send(db_client, fake, room)

    (scene_prompt,) = fake.prompts("chat_scene_judgment")
    assert "교실" in scene_prompt and "운동장" not in scene_prompt
    assert (await _last_assistant(db_session, room)).scene == {"place": "교실", "time": "아침"}


async def test_deleting_back_to_the_opening_returns_to_the_initial_scene(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """AI 턴을 모두 지워 오프닝만 남으면 다시 첫 장면을 잇는다."""
    room = await _story_room(db_client, db_session, turns=1)
    await _set_scene(db_session, room.turns[1][1], {"place": "교실", "time": "아침"})
    await _delete_turn(db_client, room, 1)
    fake = _SceneLLM(scene=[SceneJudgmentResult(place=None, time=None)])

    await _send(db_client, fake, room)

    assert (await _last_assistant(db_session, room)).scene == _INITIAL


async def test_deleting_only_the_user_message_keeps_the_scene_saved_on_the_answer(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """사용자 메시지만 지워 그 답 앞에 사용자 메시지가 없어져도, 답에 저장된 장면이 있으면 그것을 잇는다 — 오프닝처럼 보인다고
    첫 장면으로 되돌아가지 않는다."""
    room = await _story_room(db_client, db_session, turns=1)
    user_message, answer = room.turns[1]
    await _set_scene(db_session, answer, {"place": "교실", "time": "아침"})
    deleted = await db_client.delete(f"/chat-rooms/{room.room_id}/messages/{user_message.id}")
    assert deleted.status_code == 200, deleted.text
    fake = _SceneLLM(scene=[SceneJudgmentResult(place=None, time=None)])

    await _send(db_client, fake, room)

    (scene_prompt,) = fake.prompts("chat_scene_judgment")
    assert "교실" in scene_prompt and "낡은 등대" not in scene_prompt
    assert (await _last_assistant(db_session, room)).scene == {"place": "교실", "time": "아침"}


# ── 빌더 미리보기 ──────────────────────────────────────────────────────────────────────────────


def _preview_payload(*, scene_header: bool) -> dict[str, object]:
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
                "openingMessage": "어서 와.",
                "playguide": None,
                "suggestedReplies": [],
                "statDefs": [],
                "endings": [],
                "initialScenePlace": "낡은 등대",
                "initialSceneTime": None,
            }
        ],
        "keywordNotes": [],
        "shortcuts": [],
        "description": "상세 설명",
        "genreId": None,
        "target": None,
        "hashtags": [],
        "visibility": "private",
        "sceneHeaderEnabled": scene_header,
    }


async def test_preview_judges_from_the_session_scene_and_moves_it_turn_by_turn(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """장면 헤더를 켠 초안의 미리보기는 첫 시작설정의 첫 장면에서 시작해, 턴마다 세션의 지금 장면을 이어 판정하고 그 장면을
    세션·스트림에 남긴다. 끈 초안은 호출·이벤트가 없다."""
    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    started = await db_client.post("/preview-sessions", json=_preview_payload(scene_header=True))
    assert started.status_code == 201, started.text
    session_id = started.json()["previewSessionId"]
    state = await get_preview_session(session_id)
    assert state is not None and state.story_scene == StoryScene(place="낡은 등대", time=None)

    first = _SceneLLM(scene=[SceneJudgmentResult(place=None, time="자정")])
    events = await _request(db_client, first, "POST", f"/preview-sessions/{session_id}/messages", {"content": "들어가자"})
    second = _SceneLLM(scene=[SceneJudgmentResult(place="지하실", time=None)])
    await _request(db_client, second, "POST", f"/preview-sessions/{session_id}/messages", {"content": "내려가자"})

    assert "낡은 등대" in first.prompts("preview_scene_judgment")[0]
    assert [(e["place"], e["time"]) for e in _scene_events(events)] == [("낡은 등대", "자정")]
    assert _done(events)["scene"] == {"place": "낡은 등대", "time": "자정"}
    assert "자정" in second.prompts("preview_scene_judgment")[0]
    state = await get_preview_session(session_id)
    assert state is not None and state.story_scene == StoryScene(place="지하실", time="자정")

    off = await db_client.post("/preview-sessions", json=_preview_payload(scene_header=False))
    off_id = off.json()["previewSessionId"]
    silent = _SceneLLM(scene=[])
    off_events = await _request(db_client, silent, "POST", f"/preview-sessions/{off_id}/messages", {"content": "들어가자"})
    assert silent.prompts("preview_scene_judgment") == [] and _scene_events(off_events) == []
    off_state = await get_preview_session(off_id)
    assert off_state is not None and off_state.story_scene is None
