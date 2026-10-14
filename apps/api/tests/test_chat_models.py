import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone, UTC

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from api.chat.memory_rewind import rewind_memory
from api.chat.room_deletion import delete_chat_rooms
from api.db.models import (
    CharacterImageExposure,
    ChatMessage,
    ChatMessageReport,
    ChatMemoryEpisode,
    ChatMemoryExtraction,
    ChatMemoryFact,
    ChatMemoryFactExtraction,
    ChatMessageRole,
    ChatRoom,
    ChatRoomMemorySnapshot,
    ChatRoomStat,
    ChatTurn,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    DiscardedResponse,
    Genre,
    ModerationStatus,
    Novel,
    NovelChapterRevision,
    ReportStatus,
    StoryEndingUnlock,
    StoryMediaExposure,
    User,
)
from factories import (
    _make_chat_turn,
    _make_memory_episode,
    _make_memory_extraction,
    _make_memory_fact,
    _make_memory_fact_extraction,
    _make_novel_tree,
    _make_user,
)


async def _make_published_version(db_session: AsyncSession, user: User) -> ContentVersion:
    genre_result = await db_session.execute(sa.select(Genre).limit(1))
    genre = genre_result.scalar_one()

    content = Content(
        type=ContentType.STORY,
        creator_user_id=user.id,
        genre_id=genre.id,
        target=ContentTarget.ALL,
        hashtags=[],
        visibility=ContentVisibility.PUBLIC,
        moderation_status=ModerationStatus.NORMAL,
    )
    db_session.add(content)
    await db_session.flush()

    version = ContentVersion(
        content_id=content.id,
        version_number=1,
        published_at=datetime.now(UTC),
        detail_description="발행된 버전",
    )
    db_session.add(version)
    await db_session.flush()

    return version


async def _make_chat_room(db_session: AsyncSession, **overrides: object) -> ChatRoom:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    version = await _make_published_version(db_session, user)

    defaults: dict[str, object] = {
        "user_id": user.id,
        "content_id": version.content_id,
        "content_version_id": version.id,
    }
    defaults.update(overrides)
    room = ChatRoom(**defaults)
    db_session.add(room)
    await db_session.flush()
    return room


async def test_chat_room_pins_to_content_version_with_defaults(db_session: AsyncSession) -> None:
    room = await _make_chat_room(db_session)

    assert room.turn_count == 0
    assert room.ending_reached is False
    assert room.version_auto_upgraded is False
    assert room.ending_entity_id is None
    assert room.name is None


async def test_chat_message_attaches_to_chat_room(db_session: AsyncSession) -> None:
    room = await _make_chat_room(db_session)

    message = ChatMessage(chat_room_id=room.id, role=ChatMessageRole.USER, content="안녕하세요")
    db_session.add(message)
    await db_session.flush()

    assert message.role == ChatMessageRole.USER


async def test_chat_messages_inserted_in_one_transaction_sort_by_created_at_in_insert_order(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    """메시지 순서는 `ORDER BY created_at` 하나로만 정해진다(타이브레이커 없음). 기본값이
    트랜잭션 시작 시각이면 한 트랜잭션에 넣은 메시지가 전부 같은 값을 가져, 동률은 힙의
    물리 순서대로 나온다 — 그 사이에 다른 커넥션의 VACUUM이 앞서 죽은 행의 슬롯을 풀면
    뒤에 넣은 행이 앞 슬롯에 들어가 순서가 뒤집힌다(테스트 하나가 외부 트랜잭션 하나로
    감싸이는 이 하네스에서 autovacuum이 끼면 실제로 생긴다). 문장 실행 시각이 기본값이면
    물리 순서와 무관하게 삽입 순서가 나와야 한다."""
    room = await _make_chat_room(db_session)

    # 롤백된 행이 슬롯을 차지한 채로 남게 한다(앞 테스트가 넣었다 롤백한 행의 재현).
    async with db_session.begin_nested() as savepoint:
        db_session.add_all(
            [ChatMessage(chat_room_id=room.id, role=ChatMessageRole.USER, content="버려짐") for _ in range(5)]
        )
        await db_session.flush()
        await savepoint.rollback()

    contents = ["오프닝", "유저", "원래응답"]
    for index, content in enumerate(contents):
        role = ChatMessageRole.USER if content == "유저" else ChatMessageRole.ASSISTANT
        db_session.add(ChatMessage(chat_room_id=room.id, role=role, content=content))
        await db_session.flush()
        if index == 0:
            async with db_engine.connect() as other:
                autocommit = await other.execution_options(isolation_level="AUTOCOMMIT")
                await autocommit.execute(sa.text("VACUUM (INDEX_CLEANUP ON) chat_messages"))

    rows = (
        await db_session.execute(
            sa.select(ChatMessage.content, ChatMessage.created_at)
            .where(ChatMessage.chat_room_id == room.id)
            .order_by(ChatMessage.created_at.asc())
        )
    ).all()

    assert [row.content for row in rows] == contents
    assert len({row.created_at for row in rows}) == len(contents)


async def test_chat_room_stat_composite_pk_allows_multiple_stats_per_room(
    db_session: AsyncSession,
) -> None:
    room = await _make_chat_room(db_session)

    stat_a = ChatRoomStat(chat_room_id=room.id, stat_entity_id=uuid.uuid4(), current_value=50)
    stat_b = ChatRoomStat(chat_room_id=room.id, stat_entity_id=uuid.uuid4(), current_value=10)
    db_session.add_all([stat_a, stat_b])
    await db_session.flush()

    assert stat_a.chat_room_id == stat_b.chat_room_id
    assert stat_a.stat_entity_id != stat_b.stat_entity_id


# `alembic check` 는 기존 테이블의 복합 PK 구성을 비교하지 않는다(alembic 1.18.5 의
# autogenerate/compare 에 primary_key 비교자가 없다) — chat_room_stats 의 복합 PK는
# 이 테스트에서만 검증된다.
async def test_chat_room_stat_rejects_duplicate_composite_pk(db_session: AsyncSession) -> None:
    room = await _make_chat_room(db_session)
    stat_entity_id = uuid.uuid4()

    db_session.add(ChatRoomStat(chat_room_id=room.id, stat_entity_id=stat_entity_id, current_value=50))
    await db_session.flush()

    db_session.add(ChatRoomStat(chat_room_id=room.id, stat_entity_id=stat_entity_id, current_value=60))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_story_ending_unlock_accumulates_per_user_and_starting_setup(
    db_session: AsyncSession,
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    unlock = StoryEndingUnlock(
        user_id=user.id,
        starting_setup_entity_id=uuid.uuid4(),
        ending_entity_id=uuid.uuid4(),
    )
    db_session.add(unlock)
    await db_session.flush()

    assert unlock.first_reached_at is not None


# `alembic check` 는 기존 테이블의 복합 PK 구성을 비교하지 않는다(alembic 1.18.5 의
# autogenerate/compare 에 primary_key 비교자가 없다) — story_ending_unlocks 의 복합 PK는
# 이 테스트에서만 검증된다.
async def test_story_ending_unlock_rejects_duplicate_composite_pk(
    db_session: AsyncSession,
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    starting_setup_entity_id = uuid.uuid4()
    ending_entity_id = uuid.uuid4()

    db_session.add(
        StoryEndingUnlock(
            user_id=user.id,
            starting_setup_entity_id=starting_setup_entity_id,
            ending_entity_id=ending_entity_id,
        )
    )
    await db_session.flush()

    db_session.add(
        StoryEndingUnlock(
            user_id=user.id,
            starting_setup_entity_id=starting_setup_entity_id,
            ending_entity_id=ending_entity_id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_character_image_exposure_accumulates_per_user_and_content(
    db_session: AsyncSession,
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    version = await _make_published_version(db_session, user)

    exposure = CharacterImageExposure(
        user_id=user.id,
        content_id=version.content_id,
        image_entity_id=uuid.uuid4(),
    )
    db_session.add(exposure)
    await db_session.flush()

    assert exposure.first_exposed_at is not None


# `alembic check` 는 기존 테이블의 복합 PK 구성을 비교하지 않는다(alembic 1.18.5 의
# autogenerate/compare 에 primary_key 비교자가 없다) — character_image_exposures 의
# 복합 PK는 이 테스트에서만 검증된다.
async def test_character_image_exposure_rejects_duplicate_composite_pk(
    db_session: AsyncSession,
) -> None:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    version = await _make_published_version(db_session, user)
    image_entity_id = uuid.uuid4()

    db_session.add(
        CharacterImageExposure(
            user_id=user.id,
            content_id=version.content_id,
            image_entity_id=image_entity_id,
        )
    )
    await db_session.flush()

    db_session.add(
        CharacterImageExposure(
            user_id=user.id,
            content_id=version.content_id,
            image_entity_id=image_entity_id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


# `alembic check` 는 복합 PK 구성을 비교하지 않는다 — story_media_exposures 의 복합 PK 는 이
# 테스트에서만 검증된다.
async def test_story_media_exposure_rejects_duplicate_composite_pk(db_session: AsyncSession) -> None:
    """A cell is recorded once per user and story; another cell, or the same cell for another
    user, is a separate row."""
    user, other_user = _make_user(), _make_user()
    db_session.add_all([user, other_user])
    await db_session.flush()
    version = await _make_published_version(db_session, user)
    cell_entity_id = uuid.uuid4()

    db_session.add_all(
        [
            StoryMediaExposure(user_id=user.id, content_id=version.content_id, cell_entity_id=cell_entity_id),
            StoryMediaExposure(user_id=user.id, content_id=version.content_id, cell_entity_id=uuid.uuid4()),
            StoryMediaExposure(user_id=other_user.id, content_id=version.content_id, cell_entity_id=cell_entity_id),
        ]
    )
    await db_session.flush()

    db_session.add(
        StoryMediaExposure(user_id=user.id, content_id=version.content_id, cell_entity_id=cell_entity_id)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def _add_assistant_message(db_session: AsyncSession, room: ChatRoom, content: str) -> ChatMessage:
    message = ChatMessage(chat_room_id=room.id, role=ChatMessageRole.ASSISTANT, content=content)
    db_session.add(message)
    await db_session.flush()
    return message


def _report(room: ChatRoom, message: ChatMessage, reporter_user_id: uuid.UUID) -> ChatMessageReport:
    return ChatMessageReport(
        reporter_user_id=reporter_user_id,
        chat_room_id=room.id,
        chat_message_id=message.id,
        reason="other",
        status=ReportStatus.PENDING,
        evidence_response=message.content,
    )


# `alembic check` 는 CHECK 제약을 비교하지 않는다 — 버려진 응답 수가 1 이상이라는 불변식은
# 이 테스트에서만 검증된다.
async def test_discarded_response_rejects_zero_count(db_session: AsyncSession) -> None:
    room = await _make_chat_room(db_session)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                sa.insert(DiscardedResponse).values(
                    user_id=room.user_id, chat_room_id=room.id, kind="regenerate", discarded_count=0
                )
            )


# `alembic check` 는 CHECK 제약을 비교하지 않는다 — 턴 기록의 종류와 차감 출처가 정해진 값뿐이라는 두 불변식은
# 아래 두 테스트에서만 검증된다.
async def test_chat_turn_rejects_unknown_kind(db_session: AsyncSession) -> None:
    room = await _make_chat_room(db_session)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(_make_chat_turn(room.id, kind="preview"))


async def test_chat_turn_rejects_unknown_charge_source(db_session: AsyncSession) -> None:
    room = await _make_chat_room(db_session)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(_make_chat_turn(room.id, charge_source="token"))


async def test_chat_turn_insert_without_recall_column_gets_empty_list(db_session: AsyncSession) -> None:
    """회상 목록 칸을 모르는 옛 이미지의 턴 기록 INSERT(배포 겹침·이미지 롤백)가 DB 기본값으로 성공한다. 기본값을 떼면
    그 INSERT 가 NOT NULL 위반으로 실패하고 응답 커밋까지 함께 깨진다 — `alembic check` 는 기본값을 비교하지 않는다."""
    room = await _make_chat_room(db_session)
    turn_id = uuid.uuid4()

    await db_session.execute(
        sa.text(
            "INSERT INTO chat_turns (id, chat_room_id, assistant_message_id, kind, turn_number, chat_model, "
            "charge_source, clover_amount) VALUES (:id, :room, :message, 'send', 1, 'gemini', 'free', 0)"
        ),
        {"id": turn_id, "room": room.id, "message": uuid.uuid4()},
    )

    assert await db_session.scalar(sa.select(ChatTurn.memory_recall).where(ChatTurn.id == turn_id)) == []


# --- 장면 기억 · 추출 기록 -------------------------------------------------------------------------
#
# `alembic check` 는 CHECK 제약을 비교하지 않는다 — 아래 거부 테스트가 이 두 테이블 CHECK 의 유일한 검증이다. 거부 테스트는
# 예외가 났다는 것만이 아니라 **어느 제약**이 거부했는지 본다(다른 제약이 우연히 같은 값을 막아도 초록이 되지 않게).


async def _make_snapshot(db_session: AsyncSession, room: ChatRoom) -> ChatRoomMemorySnapshot:
    snapshot = ChatRoomMemorySnapshot(
        chat_room_id=room.id,
        cursor_created_at=datetime.now(UTC),
        cursor_message_id=uuid.uuid4(),
        summary_text="요약",
        source="auto",
    )
    db_session.add(snapshot)
    await db_session.flush()
    return snapshot


def _violated_constraint(error: IntegrityError) -> str | None:
    """asyncpg 가 알려 준, 행을 거부한 제약 이름."""
    name = getattr(error.orig.__cause__, "constraint_name", None) if error.orig is not None else None
    return name if isinstance(name, str) else None


_AT = datetime(2026, 1, 1, tzinfo=UTC)
_FIRST_ID = uuid.UUID(int=1)
_SECOND_ID = uuid.UUID(int=2)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param(
            {
                "title": "가" * 60,
                "detail": "나" * 300,
                "nouns": [f"명사{i}" for i in range(30)],
                "keywords": [f"구절{i}" for i in range(8)],
                "evidence": ["근거 하나", "근거 둘"],
                "importance": 5,
                "asserted_by": "mixed",
            },
            id="max",
        ),
        pytest.param(
            {"title": "가", "detail": "나", "nouns": [], "importance": 1, "ordinal": 0, "asserted_by": "narration"},
            id="min",
        ),
        pytest.param({"asserted_by": "character"}, id="character"),
        pytest.param({"asserted_by": "user"}, id="user"),
        pytest.param(
            {
                "start_created_at": _AT,
                "start_message_id": _FIRST_ID,
                "end_created_at": _AT,
                "end_message_id": _SECOND_ID,
                "start_turn": 4,
                "end_turn": 5,
            },
            id="range-ties-on-time",
        ),
    ],
)
async def test_memory_episode_accepts_values_on_the_boundary(
    db_session: AsyncSession, overrides: dict[str, object]
) -> None:
    room = await _make_chat_room(db_session)
    snapshot = await _make_snapshot(db_session, room)

    db_session.add(_make_memory_episode(room.id, snapshot.id, **overrides))
    await db_session.flush()

    count = await db_session.scalar(
        sa.select(sa.func.count()).select_from(ChatMemoryEpisode).where(ChatMemoryEpisode.snapshot_id == snapshot.id)
    )
    assert count == 1


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        pytest.param({"asserted_by": "narrator"}, "ck_chat_memory_episodes_asserted_by", id="asserted-by"),
        pytest.param({"importance": 0}, "ck_chat_memory_episodes_importance", id="importance-0"),
        pytest.param({"importance": 6}, "ck_chat_memory_episodes_importance", id="importance-6"),
        pytest.param({"ordinal": -1}, "ck_chat_memory_episodes_ordinal", id="ordinal"),
        pytest.param({"start_turn": 3, "end_turn": 2}, "ck_chat_memory_episodes_turn_order", id="turn-order"),
        pytest.param(
            {
                "start_created_at": _AT + timedelta(seconds=1),
                "start_message_id": _FIRST_ID,
                "end_created_at": _AT,
                "end_message_id": _SECOND_ID,
            },
            "ck_chat_memory_episodes_range_order",
            id="range-order-time",
        ),
        pytest.param(
            {
                "start_created_at": _AT,
                "start_message_id": _SECOND_ID,
                "end_created_at": _AT,
                "end_message_id": _FIRST_ID,
            },
            "ck_chat_memory_episodes_range_order",
            id="range-order-id",
        ),
        pytest.param({"title": ""}, "ck_chat_memory_episodes_title_length", id="title-0"),
        pytest.param({"title": "가" * 61}, "ck_chat_memory_episodes_title_length", id="title-61"),
        pytest.param({"detail": ""}, "ck_chat_memory_episodes_detail_length", id="detail-0"),
        pytest.param({"detail": "나" * 301}, "ck_chat_memory_episodes_detail_length", id="detail-301"),
        pytest.param(
            {"nouns": [f"명사{i}" for i in range(31)]}, "ck_chat_memory_episodes_nouns_count", id="nouns-31"
        ),
        pytest.param(
            {"keywords": [f"구절{i}" for i in range(9)]}, "ck_chat_memory_episodes_keywords_count", id="keywords-9"
        ),
        pytest.param(
            {"evidence": ["하나", "둘", "셋"]}, "ck_chat_memory_episodes_evidence_count", id="evidence-3"
        ),
    ],
)
async def test_memory_episode_rejects_values_outside_its_checks(
    db_session: AsyncSession, overrides: dict[str, object], constraint: str
) -> None:
    room = await _make_chat_room(db_session)
    snapshot = await _make_snapshot(db_session, room)

    with pytest.raises(IntegrityError) as raised:
        async with db_session.begin_nested():
            db_session.add(_make_memory_episode(room.id, snapshot.id, **overrides))

    assert _violated_constraint(raised.value) == constraint


async def test_memory_episode_without_keywords_and_evidence_gets_empty_lists(db_session: AsyncSession) -> None:
    """추출 결과에 구절·근거가 없으면 칸을 비워 넣는다 — DB 기본값이 빈 배열이어야 NOT NULL 에 막히지 않는다."""
    room = await _make_chat_room(db_session)
    snapshot = await _make_snapshot(db_session, room)
    episode = _make_memory_episode(room.id, snapshot.id)
    db_session.add(episode)
    await db_session.flush()

    row = (
        await db_session.execute(
            sa.select(ChatMemoryEpisode.keywords, ChatMemoryEpisode.evidence).where(
                ChatMemoryEpisode.id == episode.id
            )
        )
    ).one()
    assert (row.keywords, row.evidence) == ([], [])


async def test_memory_extraction_accepts_each_status_with_its_count(db_session: AsyncSession) -> None:
    """뽑는 중·실패는 장면 수가 없고, 끝난 기록은 0 을 포함한 장면 수가 있다(장면이 없는 구간도 끝난 것이다)."""
    room = await _make_chat_room(db_session)
    rows: list[dict[str, object]] = [
        {"status": "running", "episode_count": None},
        {"status": "failed", "episode_count": None, "attempts": 3},
        {"status": "done", "episode_count": 0},
    ]
    for overrides in rows:
        snapshot = await _make_snapshot(db_session, room)
        db_session.add(_make_memory_extraction(room.id, snapshot.id, **overrides))
    await db_session.flush()

    count = await db_session.scalar(
        sa.select(sa.func.count()).select_from(ChatMemoryExtraction).where(ChatMemoryExtraction.chat_room_id == room.id)
    )
    assert count == len(rows)


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        pytest.param({"status": "pending", "episode_count": None}, "ck_chat_memory_extractions_status", id="status"),
        pytest.param({"attempts": 0}, "ck_chat_memory_extractions_attempts", id="attempts-0"),
        pytest.param({"status": "done", "episode_count": None}, "ck_chat_memory_extractions_done_count", id="done-no-count"),
        pytest.param({"status": "running", "episode_count": 2}, "ck_chat_memory_extractions_done_count", id="running-count"),
    ],
)
async def test_memory_extraction_rejects_values_outside_its_checks(
    db_session: AsyncSession, overrides: dict[str, object], constraint: str
) -> None:
    room = await _make_chat_room(db_session)
    snapshot = await _make_snapshot(db_session, room)

    with pytest.raises(IntegrityError) as raised:
        async with db_session.begin_nested():
            db_session.add(_make_memory_extraction(room.id, snapshot.id, **overrides))

    assert _violated_constraint(raised.value) == constraint


@pytest.mark.parametrize(
    ("make", "constraint"),
    [
        pytest.param(_make_memory_episode, "chat_memory_episodes_snapshot_id_fkey", id="episode"),
        pytest.param(_make_memory_extraction, "chat_memory_extractions_snapshot_id_fkey", id="extraction"),
    ],
)
async def test_episode_insert_for_missing_snapshot_is_rejected(
    db_session: AsyncSession, make: Callable[..., object], constraint: str
) -> None:
    """추출이 끝날 때 스냅샷이 이미 지워졌으면(그 구간 대화가 되감겼다) 결과를 넣지 못해야 한다 — 지운 대화의 장면이
    남지 않게 하는 마지막 방어선이 이 FK 다."""
    room = await _make_chat_room(db_session)

    with pytest.raises(IntegrityError) as raised:
        async with db_session.begin_nested():
            db_session.add(make(room.id, uuid.uuid4()))

    assert _violated_constraint(raised.value) == constraint


# --- 사실 기억 · 추출 기록 -------------------------------------------------------------------------
#
# 장면 기억 절과 같은 규칙이다 — `alembic check` 는 CHECK 를 비교하지 않으므로 아래 거부 테스트가 유일한 검증이고, 거부
# 테스트는 어느 제약이 거부했는지까지 본다. 상한마다 통과하는 끝값과 막히는 바로 다음 값을 함께 둔다(한쪽만 두면 상한이
# 한 칸 밀려도 초록이다).

# 사실(속성) 행의 칸 조합. 팩토리 기본값은 관계 행이다.
_ATTRIBUTE_FACT: dict[str, object] = {
    "kind": "fact",
    "object": None,
    "attribute": "직업",
    "fact_key": "fact|민수|직업",
    "value": "제빵사",
}


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param(
            {
                "subject": "가" * 60,
                "object": "나" * 60,
                "value": "다" * 200,
                "fact_key": "라" * 200,
                "speaker": "마" * 60,
                "known_by": ["바" * 60 for _ in range(10)],
                "importance": 5,
                "ordinal": 19,
                "truth_status": "disproved",
                "asserted_by": "narration",
            },
            id="relation-max",
        ),
        pytest.param(
            {
                **_ATTRIBUTE_FACT,
                "subject": "가",
                "attribute": "나",
                "value": "다",
                "fact_key": "k",
                "speaker": "마",
                "known_by": ["바"],
                "importance": 1,
                "ordinal": 0,
                "truth_status": "claimed",
                "asserted_by": "character",
            },
            id="fact-min",
        ),
        pytest.param({**_ATTRIBUTE_FACT, "attribute": "나" * 60}, id="attribute-max"),
        pytest.param({"known_by": None, "speaker": None}, id="public-without-speaker"),
        pytest.param(
            {
                "start_created_at": _AT,
                "start_message_id": _FIRST_ID,
                "end_created_at": _AT,
                "end_message_id": _SECOND_ID,
                "start_turn": 4,
                "end_turn": 5,
            },
            id="range-ties-on-time",
        ),
    ],
)
async def test_memory_fact_accepts_values_on_the_boundary(
    db_session: AsyncSession, overrides: dict[str, object]
) -> None:
    room = await _make_chat_room(db_session)
    snapshot = await _make_snapshot(db_session, room)

    db_session.add(_make_memory_fact(room.id, snapshot.id, **overrides))
    await db_session.flush()

    count = await db_session.scalar(
        sa.select(sa.func.count()).select_from(ChatMemoryFact).where(ChatMemoryFact.snapshot_id == snapshot.id)
    )
    assert count == 1


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        # 알 수 없는 종류는 종류별 칸 정합도 어기지만, Postgres 는 CHECK 를 이름 순으로 검사해 종류 제약이 먼저 거부한다.
        pytest.param({"kind": "event"}, "ck_chat_memory_facts_kind", id="kind"),
        pytest.param({"object": None}, "ck_chat_memory_facts_kind_columns", id="relation-without-object"),
        pytest.param({"attribute": "직업"}, "ck_chat_memory_facts_kind_columns", id="relation-with-attribute"),
        pytest.param(
            {**_ATTRIBUTE_FACT, "attribute": None}, "ck_chat_memory_facts_kind_columns", id="fact-without-attribute"
        ),
        pytest.param({**_ATTRIBUTE_FACT, "object": "지아"}, "ck_chat_memory_facts_kind_columns", id="fact-with-object"),
        pytest.param({"truth_status": "rumored"}, "ck_chat_memory_facts_truth_status", id="truth-status"),
        # 장면 기억은 섞임(`mixed`)을 받지만 사실 한 줄은 말한 쪽이 하나다.
        pytest.param({"asserted_by": "mixed"}, "ck_chat_memory_facts_asserted_by", id="asserted-by"),
        pytest.param({"importance": 0}, "ck_chat_memory_facts_importance", id="importance-0"),
        pytest.param({"importance": 6}, "ck_chat_memory_facts_importance", id="importance-6"),
        pytest.param({"ordinal": -1}, "ck_chat_memory_facts_ordinal", id="ordinal--1"),
        pytest.param({"ordinal": 20}, "ck_chat_memory_facts_ordinal", id="ordinal-20"),
        pytest.param({"start_turn": 3, "end_turn": 2}, "ck_chat_memory_facts_turn_order", id="turn-order"),
        pytest.param(
            {
                "start_created_at": _AT,
                "start_message_id": _SECOND_ID,
                "end_created_at": _AT,
                "end_message_id": _FIRST_ID,
            },
            "ck_chat_memory_facts_range_order",
            id="range-order-id",
        ),
        pytest.param({"subject": ""}, "ck_chat_memory_facts_subject_length", id="subject-0"),
        pytest.param({"subject": "가" * 61}, "ck_chat_memory_facts_subject_length", id="subject-61"),
        pytest.param({"object": "나" * 61}, "ck_chat_memory_facts_object_length", id="object-61"),
        pytest.param(
            {**_ATTRIBUTE_FACT, "attribute": "나" * 61}, "ck_chat_memory_facts_attribute_length", id="attribute-61"
        ),
        pytest.param({"speaker": ""}, "ck_chat_memory_facts_speaker_length", id="speaker-0"),
        pytest.param({"speaker": "마" * 61}, "ck_chat_memory_facts_speaker_length", id="speaker-61"),
        pytest.param({"value": ""}, "ck_chat_memory_facts_value_length", id="value-0"),
        pytest.param({"value": "다" * 201}, "ck_chat_memory_facts_value_length", id="value-201"),
        pytest.param({"fact_key": ""}, "ck_chat_memory_facts_fact_key_length", id="fact-key-0"),
        pytest.param({"fact_key": "라" * 201}, "ck_chat_memory_facts_fact_key_length", id="fact-key-201"),
        # "아무도 모른다"와 "모른다"를 NULL 하나로 둔다 — 빈 배열이 들어오면 읽는 쪽이 두 뜻을 갈라야 한다.
        pytest.param({"known_by": []}, "ck_chat_memory_facts_known_by_count", id="known-by-empty"),
        pytest.param(
            {"known_by": [f"인물{i}" for i in range(11)]}, "ck_chat_memory_facts_known_by_count", id="known-by-11"
        ),
        pytest.param({"known_by": ["민수", "바" * 61]}, "ck_chat_memory_facts_known_by_items", id="known-by-item-61"),
        pytest.param({"known_by": ["민수", None]}, "ck_chat_memory_facts_known_by_items", id="known-by-null-item"),
    ],
)
async def test_memory_fact_rejects_values_outside_its_checks(
    db_session: AsyncSession, overrides: dict[str, object], constraint: str
) -> None:
    room = await _make_chat_room(db_session)
    snapshot = await _make_snapshot(db_session, room)

    with pytest.raises(IntegrityError) as raised:
        async with db_session.begin_nested():
            db_session.add(_make_memory_fact(room.id, snapshot.id, **overrides))

    assert _violated_constraint(raised.value) == constraint


async def test_memory_fact_extraction_accepts_each_status_with_its_count(db_session: AsyncSession) -> None:
    """뽑는 중·실패는 사실 수가 없고, 끝난 기록은 0 을 포함한 사실 수가 있다(사실이 없는 구간도 끝난 것이다)."""
    room = await _make_chat_room(db_session)
    rows: list[dict[str, object]] = [
        {"status": "running", "fact_count": None},
        {"status": "failed", "fact_count": None, "attempts": 3},
        {"status": "done", "fact_count": 0},
    ]
    for overrides in rows:
        snapshot = await _make_snapshot(db_session, room)
        db_session.add(_make_memory_fact_extraction(room.id, snapshot.id, **overrides))
    await db_session.flush()

    count = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(ChatMemoryFactExtraction)
        .where(ChatMemoryFactExtraction.chat_room_id == room.id)
    )
    assert count == len(rows)


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        pytest.param({"status": "pending", "fact_count": None}, "ck_chat_memory_fact_extractions_status", id="status"),
        pytest.param({"attempts": 0}, "ck_chat_memory_fact_extractions_attempts", id="attempts-0"),
        pytest.param(
            {"status": "done", "fact_count": None}, "ck_chat_memory_fact_extractions_done_count", id="done-no-count"
        ),
        pytest.param(
            {"status": "running", "fact_count": 2}, "ck_chat_memory_fact_extractions_done_count", id="running-count"
        ),
    ],
)
async def test_memory_fact_extraction_rejects_values_outside_its_checks(
    db_session: AsyncSession, overrides: dict[str, object], constraint: str
) -> None:
    room = await _make_chat_room(db_session)
    snapshot = await _make_snapshot(db_session, room)

    with pytest.raises(IntegrityError) as raised:
        async with db_session.begin_nested():
            db_session.add(_make_memory_fact_extraction(room.id, snapshot.id, **overrides))

    assert _violated_constraint(raised.value) == constraint


@pytest.mark.parametrize(
    ("make", "constraint"),
    [
        pytest.param(_make_memory_fact, "chat_memory_facts_snapshot_id_fkey", id="fact"),
        pytest.param(_make_memory_fact_extraction, "chat_memory_fact_extractions_snapshot_id_fkey", id="extraction"),
    ],
)
async def test_fact_insert_for_missing_snapshot_is_rejected(
    db_session: AsyncSession, make: Callable[..., object], constraint: str
) -> None:
    """추출이 끝날 때 스냅샷이 이미 지워졌으면(그 구간 대화가 되감겼다) 결과를 넣지 못해야 한다 — 지운 대화의 사실이
    남지 않게 하는 마지막 방어선이 이 FK 다."""
    room = await _make_chat_room(db_session)

    with pytest.raises(IntegrityError) as raised:
        async with db_session.begin_nested():
            db_session.add(make(room.id, uuid.uuid4()))

    assert _violated_constraint(raised.value) == constraint


async def test_chat_turn_insert_without_facts_column_gets_empty_list(db_session: AsyncSession) -> None:
    """사실 목록 칸을 모르는 옛 이미지의 턴 기록 INSERT(배포 겹침·이미지 롤백)가 DB 기본값으로 성공한다. 기본값을 떼면
    그 INSERT 가 NOT NULL 위반으로 실패하고 응답 커밋까지 함께 깨진다 — `alembic check` 는 기본값을 비교하지 않는다."""
    room = await _make_chat_room(db_session)
    turn_id = uuid.uuid4()

    await db_session.execute(
        sa.text(
            "INSERT INTO chat_turns (id, chat_room_id, assistant_message_id, kind, turn_number, chat_model, "
            "charge_source, clover_amount) VALUES (:id, :room, :message, 'send', 1, 'gemini', 'free', 0)"
        ),
        {"id": turn_id, "room": room.id, "message": uuid.uuid4()},
    )

    assert await db_session.scalar(sa.select(ChatTurn.memory_facts).where(ChatTurn.id == turn_id)) == []


@pytest.mark.parametrize("path", ["rewind", "reset", "room-deletion"])
async def test_snapshot_delete_statements_succeed_over_fact_rows(db_session: AsyncSession, path: str) -> None:
    """되감기·초기화(`rewind_memory`)와 방 삭제·탈퇴(`delete_chat_rooms`)의 스냅샷 DELETE 문장은 사실 계층 테이블을
    모르던 이미지의 것과 같다. 사실 행과 그 추출 기록이 있는 DB 위에서 그 문장이 FK 위반 없이 끝나고 두 테이블이
    비어야, 배포 겹침·이미지 롤백 동안 옛 이미지의 되감기·삭제가 500 이 되지 않는다(근거는 스냅샷 FK 의 CASCADE)."""
    room = await _make_chat_room(db_session)
    snapshot = await _make_snapshot(db_session, room)
    db_session.add(_make_memory_fact(room.id, snapshot.id))
    db_session.add(_make_memory_fact_extraction(room.id, snapshot.id))
    await db_session.flush()

    if path == "rewind":
        await rewind_memory(db_session, room.id, (snapshot.cursor_created_at, snapshot.cursor_message_id))
    elif path == "reset":
        await rewind_memory(db_session, room.id, None)
    else:
        await delete_chat_rooms(db_session, [room.id])

    facts = await db_session.scalar(
        sa.select(sa.func.count()).select_from(ChatMemoryFact).where(ChatMemoryFact.chat_room_id == room.id)
    )
    extractions = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(ChatMemoryFactExtraction)
        .where(ChatMemoryFactExtraction.chat_room_id == room.id)
    )
    assert (facts, extractions) == (0, 0)


async def test_room_deletion_keeps_discarded_responses_and_reports_with_references_cleared(
    db_session: AsyncSession,
) -> None:
    """방 삭제·탈퇴가 쓰는 `delete_chat_rooms` 는 두 테이블을 지우지 않는다. 방·메시지를 가리키던
    칸이 비워지지 않으면 방 DELETE 가 FK 위반으로 실패하고, 행을 지우면 지표·신고가 사라진다."""
    room = await _make_chat_room(db_session)
    message = await _add_assistant_message(db_session, room, "신고된 응답")
    discarded = DiscardedResponse(
        user_id=room.user_id, chat_room_id=room.id, kind="regenerate", discarded_count=1
    )
    report = _report(room, message, room.user_id)
    db_session.add_all([discarded, report])
    await db_session.flush()

    await delete_chat_rooms(db_session, [room.id])

    discarded_row = (
        await db_session.execute(
            sa.select(DiscardedResponse.chat_room_id, DiscardedResponse.user_id).where(
                DiscardedResponse.id == discarded.id
            )
        )
    ).one()
    assert discarded_row.chat_room_id is None
    assert discarded_row.user_id == room.user_id
    report_row = (
        await db_session.execute(
            sa.select(
                ChatMessageReport.chat_room_id,
                ChatMessageReport.chat_message_id,
                ChatMessageReport.evidence_response,
            ).where(ChatMessageReport.id == report.id)
        )
    ).one()
    assert report_row.chat_room_id is None
    assert report_row.chat_message_id is None
    assert report_row.evidence_response == "신고된 응답"


async def test_room_deletion_keeps_the_novel_made_from_it_with_room_reference_cleared(
    db_session: AsyncSession,
) -> None:
    """소설은 방과 따로 남는 문서다. `delete_chat_rooms` 는 소설 테이블을 모르고, 방 참조는 FK 의 `SET NULL` 이
    비운다 — 이 동작이 빠지면 방 삭제가 FK 위반으로 실패한다."""
    room = await _make_chat_room(db_session)
    tree = await _make_novel_tree(db_session, room.user_id, chat_room_id=room.id)

    await delete_chat_rooms(db_session, [room.id])

    novel_row = (
        await db_session.execute(sa.select(Novel.chat_room_id, Novel.user_id).where(Novel.id == tree.novel.id))
    ).one()
    assert novel_row.chat_room_id is None
    assert novel_row.user_id == room.user_id
    revision_count = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(NovelChapterRevision)
        .where(NovelChapterRevision.chapter_id == tree.chapter.id)
    )
    assert revision_count == 2


async def test_message_deletion_keeps_reports_with_message_reference_cleared(
    db_session: AsyncSession,
) -> None:
    """재생성·메시지 삭제가 신고된 메시지를 지워도 신고는 남는다. 같은 신고자가 신고한 메시지 둘이
    지워져 메시지 칸이 둘 다 NULL 이 되어도 유니크 제약에 걸리지 않아야 한다."""
    room = await _make_chat_room(db_session)
    first = await _add_assistant_message(db_session, room, "첫 응답")
    second = await _add_assistant_message(db_session, room, "둘째 응답")
    reports = [_report(room, first, room.user_id), _report(room, second, room.user_id)]
    db_session.add_all(reports)
    await db_session.flush()

    await db_session.execute(sa.delete(ChatMessage).where(ChatMessage.id.in_([first.id, second.id])))

    rows = (
        await db_session.execute(
            sa.select(ChatMessageReport.chat_room_id, ChatMessageReport.chat_message_id).where(
                ChatMessageReport.id.in_([report.id for report in reports])
            )
        )
    ).all()
    assert [(row.chat_room_id, row.chat_message_id) for row in rows] == [(room.id, None), (room.id, None)]
