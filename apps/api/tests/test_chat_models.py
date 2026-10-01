import uuid
from datetime import datetime, timezone, UTC

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from api.chat.room_deletion import delete_chat_rooms
from api.db.models import (
    CharacterImageExposure,
    ChatMessage,
    ChatMessageReport,
    ChatMessageRole,
    ChatRoom,
    ChatRoomStat,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    DiscardedResponse,
    Genre,
    ModerationStatus,
    ReportStatus,
    StoryEndingUnlock,
    StoryMediaExposure,
    User,
)
from factories import _make_user


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


async def test_chat_message_report_rejects_same_reporter_reporting_same_message_twice(
    db_session: AsyncSession,
) -> None:
    room = await _make_chat_room(db_session)
    message = await _add_assistant_message(db_session, room, "응답")
    db_session.add(_report(room, message, room.user_id))
    await db_session.flush()

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(_report(room, message, room.user_id))
            await db_session.flush()


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
