"""테스트 전역에서 본문이 글자까지 같았던 셋업 헬퍼. `goal-prompt.md §4 T-2`가 80개
파일에 복사돼 있던 것 중 완전 동일본(또는 docstring만 다른 것)만 여기로 옮겼다.
`goal-prompt.md §4 T-3`이 변종이 있던 나머지(호출부를 안 깨는 시그니처로 합친 것)를 더했다."""

import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import date, datetime, UTC
from pathlib import Path

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.security import hash_password
from api.db.models import (
    AdminUser,
    Asset,
    AssetKind,
    AssetStatus,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Genre,
    ModerationStatus,
    StoryPromptTemplate,
    StoryVersionDetail,
    User,
)
from api.db.session import engine


def _make_user(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4()}@example.com",
        "nickname": "테스터",
        "birth_date": date(2000, 1, 1),
        "terms_agreed_at": datetime.now(UTC),
        "privacy_agreed_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return User(**defaults)


async def _login_as(client: httpx.AsyncClient, user_id: uuid.UUID) -> None:
    resp = await client.post("/dev/session-echo", json={"data": {"user_id": str(user_id)}})
    assert resp.status_code == 201


async def _login_as_admin(db_client: httpx.AsyncClient, payload: dict[str, object]) -> None:
    resp = await db_client.post(
        "/admin/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert resp.status_code == 204


@contextmanager
def _count_queries() -> Generator[Callable[[], int], None, None]:
    """`before_cursor_execute` 이벤트로 실행된 SQL 문 개수를 센다."""
    count = 0

    def _before_cursor_execute(*_args: object, **_kwargs: object) -> None:
        nonlocal count
        count += 1

    sa.event.listen(engine.sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield lambda: count
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", _before_cursor_execute)


async def _get_genre(db_session: AsyncSession, name: str | None = None) -> Genre:
    stmt = sa.select(Genre).where(Genre.name == name) if name is not None else sa.select(Genre).limit(1)
    result = await db_session.execute(stmt)
    return result.scalars().one()


async def _create_admin(db_session: AsyncSession, **overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "email": f"admin-{uuid.uuid4()}@example.com",
        "password": "adminpassword123",
    }
    defaults.update(overrides)
    admin = AdminUser(
        email=str(defaults["email"]), password_hash=hash_password(str(defaults["password"]))
    )
    db_session.add(admin)
    await db_session.flush()
    return {**defaults, "id": admin.id}


async def _make_asset(
    db_session: AsyncSession,
    owner_user_id: uuid.UUID,
    storage_key_prefix: str = "assets/test/",
    kind: AssetKind = AssetKind.ORIGINAL,
    status: AssetStatus = AssetStatus.PENDING,
) -> Asset:
    asset = Asset(
        owner_user_id=owner_user_id,
        storage_key=f"{storage_key_prefix}{uuid.uuid4()}",
        kind=kind,
        status=status,
    )
    db_session.add(asset)
    await db_session.flush()
    return asset


async def _make_published_story(
    db_session: AsyncSession,
    *,
    creator_user_id: uuid.UUID,
    genre_id: uuid.UUID,
    prompt_template: StoryPromptTemplate = StoryPromptTemplate.BASIC,
) -> Content:
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
            prompt_template=prompt_template,
            setting_text="세계관 설정",
        )
    )
    await db_session.flush()

    content.current_published_version_id = version.id
    await db_session.flush()
    return content


_GOLDEN_PROMPTS_DIR = Path(__file__).parent / "golden" / "prompts"


def _read_golden_prompt(filename: str) -> str:
    """`CHARACTER_CHAT_SYSTEM_INSTRUCTION` 같은 삭제된 프롬프트 상수 대신, 실제로 나가는
    문안과 바이트 단위로 같음이 이미 증명된 골든 파일에서 기대값을 읽는다
    (prompt-db-goal-prompt.md D-13, tests/test_prompt_goldens.py)."""
    return (_GOLDEN_PROMPTS_DIR / filename).read_text(encoding="utf-8")
