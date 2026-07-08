import uuid

import httpx

from api.chat.preview_session import get_preview_session
from api.content.schemas import CharacterDraftPayload, StoryDraftPayload
from api.core.config import settings
from api.core.redis import redis_client


async def _login_as(client: httpx.AsyncClient, user_id: uuid.UUID) -> None:
    resp = await client.post("/dev/session-echo", json={"data": {"user_id": str(user_id)}})
    assert resp.status_code == 201


def _character_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "아리아",
        "oneLiner": "한 줄 소개",
        "thumbnailAssetId": None,
        "intro": "안녕하세요, 아리아예요",
        "exampleDialogues": [],
        "characterPrompt": "너는 아리아다.",
        "playguide": None,
        "situationalImages": [],
        "description": "상세 설명",
        "genreId": None,
        "target": None,
        "hashtags": [],
        "visibility": "private",
    }
    payload.update(overrides)
    return payload


def _story_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "잃어버린 도시",
        "oneLiner": "한 줄 소개",
        "thumbnailAssetId": None,
        "promptTemplate": "basic",
        "settingText": "세계관 설명",
        "developmentExample": None,
        "customPrompt": None,
        "startingSetups": [],
        "keywordNotes": [],
        "shortcuts": [],
        "description": "상세 설명",
        "genreId": None,
        "target": None,
        "hashtags": [],
        "visibility": "private",
    }
    payload.update(overrides)
    return payload


def _starting_setup_item(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "name": "시작설정1",
        "prologue": "프롤로그",
        "openingMessage": None,
        "playguide": None,
        "suggestedReplies": [],
        "statDefs": [],
        "endings": [],
    }
    item.update(overrides)
    return item


async def test_start_preview_session_requires_login(api_client: httpx.AsyncClient) -> None:
    api_client.cookies.clear()
    resp = await api_client.post("/preview-sessions", json=_character_payload())
    assert resp.status_code == 401


async def test_start_preview_session_character_seeds_intro_message(api_client: httpx.AsyncClient) -> None:
    api_client.cookies.clear()
    await _login_as(api_client, uuid.uuid4())

    resp = await api_client.post("/preview-sessions", json=_character_payload(intro="안녕하세요, 아리아예요"))
    assert resp.status_code == 201
    session_id = resp.json()["previewSessionId"]
    assert isinstance(session_id, str) and session_id

    state = await get_preview_session(session_id)
    assert state is not None
    assert isinstance(state.payload, CharacterDraftPayload)
    assert state.payload.name == "아리아"
    assert len(state.messages) == 1
    assert state.messages[0].content == "안녕하세요, 아리아예요"
    assert state.messages[0].role == "assistant"
    assert state.stats == {}
    assert state.turn_count == 0
    assert state.ending_reached is False


async def test_start_preview_session_story_seeds_first_starting_setup(api_client: httpx.AsyncClient) -> None:
    api_client.cookies.clear()
    await _login_as(api_client, uuid.uuid4())

    stat_id = str(uuid.uuid4())
    resp = await api_client.post(
        "/preview-sessions",
        json=_story_payload(
            startingSetups=[
                _starting_setup_item(
                    openingMessage="오프닝 메시지",
                    statDefs=[
                        {
                            "id": stat_id,
                            "name": "체력",
                            "icon": "heart",
                            "color": "rose",
                            "minValue": 0,
                            "maxValue": 100,
                            "initialValue": 50,
                            "unit": None,
                            "description": "체력 스탯",
                        }
                    ],
                ),
                _starting_setup_item(name="시작설정2"),
            ]
        ),
    )
    assert resp.status_code == 201
    session_id = resp.json()["previewSessionId"]

    state = await get_preview_session(session_id)
    assert state is not None
    assert isinstance(state.payload, StoryDraftPayload)
    assert len(state.messages) == 1
    # openingMessage takes priority over prologue when both are set (matches
    # `_insert_opening_message`'s `setup.opening_message or setup.prologue`).
    assert state.messages[0].content == "오프닝 메시지"
    assert state.stats == {stat_id: 50.0}


async def test_start_preview_session_story_falls_back_to_prologue(api_client: httpx.AsyncClient) -> None:
    api_client.cookies.clear()
    await _login_as(api_client, uuid.uuid4())

    resp = await api_client.post(
        "/preview-sessions",
        json=_story_payload(startingSetups=[_starting_setup_item(prologue="시작합니다", openingMessage=None)]),
    )
    assert resp.status_code == 201
    state = await get_preview_session(resp.json()["previewSessionId"])
    assert state is not None
    assert state.messages[0].content == "시작합니다"


async def test_start_preview_session_story_without_starting_setups_has_empty_state(
    api_client: httpx.AsyncClient,
) -> None:
    api_client.cookies.clear()
    await _login_as(api_client, uuid.uuid4())

    resp = await api_client.post("/preview-sessions", json=_story_payload(startingSetups=[]))
    assert resp.status_code == 201
    state = await get_preview_session(resp.json()["previewSessionId"])
    assert state is not None
    assert state.messages == []
    assert state.stats == {}


async def test_start_preview_session_sets_24h_ttl(api_client: httpx.AsyncClient) -> None:
    api_client.cookies.clear()
    await _login_as(api_client, uuid.uuid4())

    resp = await api_client.post("/preview-sessions", json=_character_payload())
    assert resp.status_code == 201
    session_id = resp.json()["previewSessionId"]

    ttl = await redis_client.ttl(f"preview-session:{session_id}")
    assert 0 < ttl <= settings.preview_session_ttl_seconds
