"""sse-assert-goal-prompt.md CP-1/CP-2 — 시작설정 불일치 상태(방의 `starting_setup_entity_id`는
non-null인데, 방이 고정한 `content_version_id` 아래 그 `entity_id`를 가진 `StartingSetup`
행이 없음, F-2·F-3)가 SSE 제너레이터·비스트리밍 라우트를 뚫는 것을 실측으로 확인하는
재현 테스트다.

CP-1 단계에서는 이 파일이 CP-2(구현) 이전의 "빨강"을 실측으로 남기는 것이 목적이었다(SA-8,
F-9, apps/api/CLAUDE.md §테스트 정책 — 구현 뒤에 쓴 테스트는 초록이어도 신호가 없다. 소스
0줄 변경 상태에서 작성됐다). CP-2에서 `_require_starting_setup`(sse-assert-goal-prompt.md
SA-12)이 들어오면서 재현 5개는 더 이상 예외가 새지 않고 400 응답으로 정규화되므로(CP-2
판정⑥, progress SP-124), 그 5개의 단언을 `pytest.raises(...)`에서 400 응답 단언으로
재작성했다 — 판정은 같은 픽스처에서 처방 전에는 `ExceptionGroup`/`AssertionError`가
raise되고 처방 후에는 `resp.status_code == 400`이라는, 전후에 실제로 다른 값이 나오는
형태다.

템플릿은 test_prompt_render_failure_api.py다(F-9) — 같은 결함 계열(정규화 안 된 예외가
SSE를 뚫음)을 다루고, `test_send_message_without_an_active_prompt_set_fails_before_
streaming_starts`의 단언 중 **상태 코드 / 커넥션 비오염** 둘을 이 파일이 따른다. **`message_count` 불변은 여기서 재지 않는다** — `send_message`는 `_stream_new_turn`
*전에* 이미 사용자 메시지를 커밋하므로(`send_message`의 사용자 메시지 선커밋 블록) CP-1 시점의 깨진 상태에서 그
불변은 애초에 참이 아니었고, 그 판정은 CP-2 판정⑤(sse-assert-goal-prompt.md)로 올바르게
미뤄져 있다(CP-1 적대적 리뷰 발견, 2026-09-18). 다른 파일명을 쓰는 이유는 템플릿이 이미
prompt-render 결함 계열의 전용 파일이라(F-9) 결함 계열이 다른 이 재현을 섞지 않기 위해서다.

`chat_rooms.starting_setup_entity_id`에는 FK가 없어(F-9, migrations/versions/
b8e8af497520의 `chat_rooms` 테이블 생성문 — 같은 테이블의 `content_id`/`content_version_id`/
`user_id`와 달리 이 컬럼만 `ForeignKeyConstraint`가 없다) 이 불일치 상태를 코드로 직접 만들 수 있다 — 가장 짧은 경로는 스토리
방을 정상 생성한 뒤 그 `StartingSetup` 행만 지우는 것이다(`ChatRoom` 팩토리는 없다 — 이
저장소 관례대로 API로 방을 만들고 직접 행을 지운다).
"""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    CharacterVersionDetail,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    ModerationStatus,
    StartingSetup,
    StoryPromptTemplate,
    StoryVersionDetail,
    User,
)
from api.llm.client import LLMClient
from api.llm.dependencies import get_llm_client
from api.main import app
from factories import _get_genre, _login_as, _make_asset, _make_user


async def _make_published_story(db_session: AsyncSession, *, creator_user_id: uuid.UUID, genre_id: uuid.UUID) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.STORY,
        genre_id=genre_id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()
    version = ContentVersion(
        content_id=content.id, version_number=1, published_at=datetime.now(UTC), detail_description="설명"
    )
    db_session.add(version)
    await db_session.flush()
    thumbnail = await _make_asset(db_session, owner_user_id=creator_user_id)
    db_session.add(
        StoryVersionDetail(
            content_version_id=version.id,
            name="스토리",
            one_liner="한줄소개",
            thumbnail_asset_id=thumbnail.id,
            prompt_template=StoryPromptTemplate.BASIC,
            setting_text="세계관 설정",
        )
    )
    await db_session.flush()
    content.current_published_version_id = version.id
    await db_session.flush()
    return content


async def _publish_new_story_version(db_session: AsyncSession, content: Content) -> ContentVersion:
    """test_chat_room_api.py의 `_publish_new_character_version`과 같은 관례 — 두 번째 발행
    버전을 만들어 `content.current_published_version_id`가 실제로 바뀌게 한다. 발행 버전이
    하나뿐이면 `pin_latest_version`의 `room.content_version_id = content.current_published_
    version_id` 대입이 같은 값 재대입(no-op)이 돼 버전 이동을 증명하지 못한다."""
    version = ContentVersion(
        content_id=content.id, version_number=2, published_at=datetime.now(UTC), detail_description="설명 v2"
    )
    db_session.add(version)
    await db_session.flush()
    thumbnail = await _make_asset(db_session, owner_user_id=content.creator_user_id)
    db_session.add(
        StoryVersionDetail(
            content_version_id=version.id,
            name="스토리 v2",
            one_liner="한줄소개",
            thumbnail_asset_id=thumbnail.id,
            prompt_template=StoryPromptTemplate.BASIC,
            setting_text="세계관 설정 v2",
        )
    )
    await db_session.flush()
    content.current_published_version_id = version.id
    await db_session.flush()
    return version


async def _make_published_character(db_session: AsyncSession, *, creator_user_id: uuid.UUID, genre_id: uuid.UUID) -> Content:
    content = Content(
        creator_user_id=creator_user_id,
        type=ContentType.CHARACTER,
        genre_id=genre_id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()
    version = ContentVersion(
        content_id=content.id, version_number=1, published_at=datetime.now(UTC), detail_description="설명"
    )
    db_session.add(version)
    await db_session.flush()
    thumbnail = await _make_asset(db_session, owner_user_id=creator_user_id)
    db_session.add(
        CharacterVersionDetail(
            content_version_id=version.id,
            name="캐릭터",
            one_liner="한줄소개",
            thumbnail_asset_id=thumbnail.id,
            intro="인트로",
            example_dialogues=[],
            character_prompt="프롬프트",
        )
    )
    await db_session.flush()
    content.current_published_version_id = version.id
    await db_session.flush()
    return content


async def _add_starting_setup(db_session: AsyncSession, content: Content) -> StartingSetup:
    assert content.current_published_version_id is not None
    setup = StartingSetup(
        entity_id=uuid.uuid4(),
        content_version_id=content.current_published_version_id,
        name="첫 만남",
        prologue="옛날 옛적, 낯선 마을에 도착했다.",
        order=1,
    )
    db_session.add(setup)
    await db_session.flush()
    return setup


async def _make_mismatched_story_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession, user: User, genre_id: uuid.UUID
) -> uuid.UUID:
    """F-2/F-3의 재현 상태를 만든다 — 스토리 방을 정상 생성한 뒤(오프닝 메시지까지 정상
    커밋된다) 그 방이 고정한 `StartingSetup` 행만 지운다. `room.starting_setup_entity_id`는
    non-null로 남지만, 그 entity_id·content_version_id 조합을 가진 행이 더는 없다."""
    content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre_id)
    setup = await _add_starting_setup(db_session, content)

    room_resp = await db_client.post(
        "/chat-rooms",
        json={"contentId": str(content.id), "contentType": "story", "startingSetupId": str(setup.id)},
    )
    assert room_resp.status_code == 201
    room_id = uuid.UUID(room_resp.json()["id"])

    await db_session.execute(sa.delete(StartingSetup).where(StartingSetup.id == setup.id))
    await db_session.flush()

    return room_id


async def _still_alive(db_session: AsyncSession) -> int | None:
    """F-16의 스모크 체크 — "실패가 이 요청 안에 갇혔다"는 신호로만 쓴다(항진명제라
    처방 전후 모두 초록일 것으로 예상됨, F-16). 판정 근거로 쓰지 않는다."""
    return cast(int | None, await db_session.scalar(sa.select(sa.func.count()).select_from(Content)))


# sse-assert-goal-prompt.md SA-12 — `_require_starting_setup`이 던지는 400의 `detail` 문자열.
# 기존 선례 `_resolve_setup_for_content`의 `"Invalid startingSetupId"`와 의도적으로 다르다 —
# 그쪽은 클라이언트가 준 `startingSetupId`가 유효하지 않다는 뜻이고, 이쪽은 방이 이미 고정한
# 시작설정이 그 방의 버전에서 사라졌다는 서버 쪽 상태 불일치라 원인이 다르다. 같은 문구를
# 쓰면 Bugsink 이슈 그룹이 뭉쳐 진단이 나빠진다.
_MISMATCH_DETAIL = "Chat room's starting setup is missing from its pinned content version"


async def test_send_message_on_mismatched_story_room_returns_400(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """CP-2 판정①⑤⑥ (SSE 3진입점 중 하나, sse-assert-goal-prompt.md CP-2) — CP-1 시점엔
    `_starting_setup_dependency`가 조용히 돌려준 `None`을 `_build_prompt`가 "캐릭터
    챗"으로 읽어(F-3) 그 캐릭터 분기의 `assert detail is not None`에서 `ExceptionGroup`을
    뚫었다. `_require_starting_setup`(SA-12)이 그 자리를 `Depends` 단계에서 400으로 정규화한
    뒤엔 제너레이터 본문이 아예 시작되지 않는다 — SSE 라우트라도 응답은 스트림이 아니라 평범한 JSON이어야 하고
    (본문이 시작되기 전이라는 증거), 사용자 메시지도 커밋되지 않아야 한다(판정⑤)."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    await _login_as(db_client, user.id)

    room_id = await _make_mismatched_story_room(db_client, db_session, user, genre.id)

    resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})

    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["detail"] == _MISMATCH_DETAIL

    # CP-2 판정⑤ — `Depends`에서 죽어 본문이 시작되지 않으므로 사용자 메시지가 커밋되지
    # 않는다(오프닝 메시지 하나뿐이어야 한다).
    message_count = await db_session.scalar(
        sa.select(sa.func.count()).select_from(ChatMessage).where(ChatMessage.chat_room_id == room_id)
    )
    assert message_count == 1

    # F-16 스모크 — 실패가 이 요청 안에 갇혔다는 신호로만 쓴다(항진명제, 판정 근거 아님).
    assert await _still_alive(db_session) == 1


async def test_regenerate_message_on_mismatched_story_room_returns_400(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """CP-2 판정①⑥ (SSE 3진입점 중 하나) — `regenerate_message`도 같은 `_starting_setup_
    dependency`를 거치므로(`_active_prompt_set_dependency` 경유) `_build_prompt`
    본문에 닿기 전에 400으로 막힌다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    await _login_as(db_client, user.id)

    room_id = await _make_mismatched_story_room(db_client, db_session, user, genre.id)
    # regenerate 대상: 마지막 메시지가 ASSISTANT이고 메시지가 2개 이상이어야 한다
    # (`_regeneratable_last_message_dependency`). 오프닝 메시지 하나뿐이라 USER→ASSISTANT
    # 한 턴을 직접 추가한다(CP-1 적대적 리뷰 발견 — 이전엔 ASSISTANT만 이어붙여 USER 없이
    # ASSISTANT가 연속되는 비현실적 히스토리였다) — LLM 호출 없이 이 결함만 재현하는
    # 최단 경로다.
    db_session.add(ChatMessage(chat_room_id=room_id, role=ChatMessageRole.USER, content="추가 메시지"))
    db_session.add(ChatMessage(chat_room_id=room_id, role=ChatMessageRole.ASSISTANT, content="추가 응답"))
    await db_session.flush()

    resp = await db_client.post(f"/chat-rooms/{room_id}/regenerate")

    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["detail"] == _MISMATCH_DETAIL

    assert await _still_alive(db_session) == 1


async def test_edit_message_on_mismatched_story_room_returns_400(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """CP-2 판정①⑥ (SSE 3진입점 중 하나) — `edit_message`도 `_starting_setup_dependency`
    를 거치므로 `_stream_new_turn` 본문에 닿기 전에 400으로 막힌다.
    `_editable_user_message_dependency`가 USER 메시지를 요구해(오프닝은 ASSISTANT)
    수정 대상 메시지를 하나 직접 추가한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    await _login_as(db_client, user.id)

    room_id = await _make_mismatched_story_room(db_client, db_session, user, genre.id)
    user_message = ChatMessage(chat_room_id=room_id, role=ChatMessageRole.USER, content="원본 메시지")
    db_session.add(user_message)
    await db_session.flush()

    resp = await db_client.patch(
        f"/chat-rooms/{room_id}/messages/{user_message.id}", json={"content": "수정된 메시지"}
    )

    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["detail"] == _MISMATCH_DETAIL

    assert await _still_alive(db_session) == 1


async def test_get_play_guide_on_mismatched_story_room_returns_400(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """CP-2 판정①⑥ (비스트리밍 2곳 중 하나) — `get_play_guide`가 이제
    `_require_starting_setup`을 불러 불일치를 400으로 정규화한다(CP-1 시점엔
    그 캐릭터 분기의 `assert detail is not None`이 맨 `AssertionError`를 던졌다)."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    await _login_as(db_client, user.id)

    room_id = await _make_mismatched_story_room(db_client, db_session, user, genre.id)

    resp = await db_client.get(f"/chat-rooms/{room_id}/play-guide")

    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["detail"] == _MISMATCH_DETAIL

    assert await _still_alive(db_session) == 1


async def test_reset_chat_room_on_mismatched_story_room_returns_400(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """CP-2 판정①⑥ (비스트리밍 2곳 중 하나) — `reset_chat_room`이 이제
    `_require_starting_setup`에서 400을 받는다(CP-1 시점엔 `_insert_opening_
    message`의 `assert`가 맨 `AssertionError`를 던졌다). 그 자리는 메시지 삭제·turn_count
    대입 뒤지만 `db.commit()` 전이라 데이터는 안전하다(F-3)."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    await _login_as(db_client, user.id)

    room_id = await _make_mismatched_story_room(db_client, db_session, user, genre.id)

    resp = await db_client.post(f"/chat-rooms/{room_id}/reset")

    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["detail"] == _MISMATCH_DETAIL

    assert await _still_alive(db_session) == 1


async def test_get_chat_room_on_mismatched_story_room_stays_a_degraded_200(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """CP-1 판정③ — 회귀 가드. `_to_response`는 SA-1/SA-6이 **의도적으로 제외**한
    넷째 호출부다(sse-assert-goal-prompt.md SA-6). 지금도, CP-2 구현 이후에도 이 라우트는
    크래시 없이 `contentType="story"`인데 `stats`·`contentSnapshot`·`startingSetupId`가
    전부 null인 200을 돌려줘야 한다 — 이게 CP-2에서 400으로 바뀌면 처방이 `_to_response`
    까지 덮은 것이고, `pin_latest_version`이 방을 잠그는 결과로 이어진다(SA-6)."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    await _login_as(db_client, user.id)

    room_id = await _make_mismatched_story_room(db_client, db_session, user, genre.id)

    resp = await db_client.get(f"/chat-rooms/{room_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["contentType"] == "story"
    assert body["stats"] is None
    assert body["contentSnapshot"] is None
    assert body["startingSetupId"] is None


async def test_write_endpoints_stay_200_on_mismatched_story_room(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """CP-2 판정③ (SA-6 철회의 이유) — `rename_chat_room`·`pin_latest_version`·
    `acknowledge_version_upgrade`는 셋 다 `_to_response`(`_resolve_starting_setup`을 그대로
    쓴다, SA-6로 처방에서 의도적으로 제외됨)를 거치므로 불일치 방에서도 200을 유지해야
    한다. 여기가 400이 되면 `pin_latest_version`이 방을 잠근다(SA-6). 특히
    `pin_latest_version` 호출 **뒤에** `GET /chat-rooms/{room_id}`가 여전히 200이어야
    한다(F-15 — 스토리 경로 `pin_latest_version` 테스트가 이 파일 이전엔 0건이었다).

    `_publish_new_story_version`으로 두 번째 발행 버전을 만들어 `content.current_published_
    version_id`가 방의 기존 `content_version_id`와 실제로 달라지게 한 뒤 `pin_latest_version`
    을 부른다 — 발행 버전이 하나뿐이면 그 안의 대입이 같은 값 재대입(no-op)이 돼 "방 잠김
    함정(SA-6)이 안 생겼다"를 증명하지 못한다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    await _login_as(db_client, user.id)

    room_id = await _make_mismatched_story_room(db_client, db_session, user, genre.id)
    room = await db_session.get(ChatRoom, room_id)
    assert room is not None
    content = await db_session.get(Content, room.content_id)
    assert content is not None
    original_version_id = room.content_version_id

    new_version = await _publish_new_story_version(db_session, content)
    assert new_version.id != original_version_id

    rename_resp = await db_client.patch(f"/chat-rooms/{room_id}", json={"name": "새 이름"})
    assert rename_resp.status_code == 200

    pin_resp = await db_client.post(f"/chat-rooms/{room_id}/pin-latest-version")
    assert pin_resp.status_code == 200

    # 버전이 실제로 옮겨졌다 — no-op 재대입이었다면 이 단언이 통과하지 않는다.
    assert room.content_version_id == new_version.id
    assert room.content_version_id != original_version_id

    ack_resp = await db_client.post(f"/chat-rooms/{room_id}/acknowledge-version-upgrade")
    assert ack_resp.status_code == 200

    # 방이 잠기지 않았다 — pin-latest-version으로 버전이 실제로 옮겨진 뒤에도 GET이
    # 여전히 200이다(degrade 유지, SA-6).
    get_resp = await db_client.get(f"/chat-rooms/{room_id}")
    assert get_resp.status_code == 200


class _MinimalFakeLLMClient(LLMClient):
    """`test_character_room_send_message_and_play_guide_are_unaffected` 전용 — 토큰
    스트리밍만 필요하다. 이 방엔 `SituationalImage`가 없어(`_make_published_character`가
    만들지 않는다) `generate_structured`는 호출되지 않는다
    (test_chat_message_send_api.py의 `test_send_message_no_situational_images_skips_
    judgment_call`과 동일 전제)."""

    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens

    async def generate(
        self, prompt: str, system_instruction: str | None = None, stop_sequences: list[str] | None = None
    ) -> AsyncIterator[str]:
        for token in self.tokens:
            yield token

    async def generate_structured(self, prompt: str, response_schema: Any, images: Any = None) -> Any:
        raise NotImplementedError


def _parse_sse_events(body: str) -> list[dict[str, Any]]:
    """test_chat_message_send_api.py의 `_parse_sse_events`와 동일한 파서 — 그 파일을 import하지 않는
    저장소 관례(apps/api/CLAUDE.md §테스트 정책 "테스트 파일이 다른 테스트 파일을 import하는
    일은 없어야 한다")를 지키기 위해 이 파일에 다시 둔다."""
    events = []
    for chunk in body.split("\n\n"):
        for line in chunk.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line.removeprefix("data: ")))
    return events


async def test_character_room_send_message_and_play_guide_are_unaffected(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """CP-1 안전망 — `starting_setup_entity_id is None`인 정상 캐릭터 방은 이 결함 계열과
    무관하다(`_resolve_starting_setup`의 조기 반환이 캐릭터 챗의 정상 신호, SA-12).
    처방이 이 경계를 잘못 잡으면 캐릭터 방 전체가 영향을 받으므로, 재현 테스트와 같은 파일에
    캐릭터 방이 **지금 정상 동작한다**는 기준선을 남겨 둔다. **`send_message`도 실제로
    호출한다**(SSE 3경로 중 `_starting_setup_dependency`를 거치는 경로) — CP-1 적대적 리뷰가
    이름은 `send_message`를 약속하면서 본문은 play-guide/reset/get만 부른다는 것을 지적해
    채웠다(2026-09-18, 이전엔 play-guide/reset 라우트만 덮고 send_message는 무커버였다)."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    genre = await _get_genre(db_session)
    content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
    await _login_as(db_client, user.id)

    room_resp = await db_client.post(
        "/chat-rooms", json={"contentId": str(content.id), "contentType": "character"}
    )
    assert room_resp.status_code == 201
    room_id = room_resp.json()["id"]

    fake = _MinimalFakeLLMClient(tokens=["안", "녕"])
    app.dependency_overrides[get_llm_client] = lambda: fake
    try:
        send_resp = await db_client.post(f"/chat-rooms/{room_id}/messages", json={"content": "안녕"})
    finally:
        app.dependency_overrides.pop(get_llm_client, None)

    assert send_resp.status_code == 200
    assert send_resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse_events(send_resp.text)
    token_events = [e for e in events if e["type"] == "token"]
    assert [e["delta"] for e in token_events] == ["안", "녕"]
    done_events = [e for e in events if e["type"] == "done"]
    assert len(done_events) == 1
    assert done_events[0]["finalMessage"]["role"] == "assistant"
    assert done_events[0]["finalMessage"]["content"] == "안녕"

    play_guide_resp = await db_client.get(f"/chat-rooms/{room_id}/play-guide")
    assert play_guide_resp.status_code == 200

    reset_resp = await db_client.post(f"/chat-rooms/{room_id}/reset")
    assert reset_resp.status_code == 200

    get_resp = await db_client.get(f"/chat-rooms/{room_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["contentType"] == "character"
