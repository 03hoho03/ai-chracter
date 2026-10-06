"""테스트 전역에서 본문이 글자까지 같았던 셋업 헬퍼. 80개
파일에 복사돼 있던 것 중 완전 동일본(또는 docstring만 다른 것)을 여기로 옮겼고,
변종이 있던 나머지(호출부를 안 깨는 시그니처로 합친 것)도 더했다.

LLM 페이크 주입(`_override_llm_client`/`_clear_llm_override`)·SSE 파싱(`_parse_sse_events`)·
`_make_published_character`도 같은 기준으로 합쳤다 — 여기 있는 것과 **의미가 같은** 사본만
가져왔고, 모양이 다른 변종(큐 기반 LLM 페이크, `example_dialogues`가 빈 캐릭터 팩토리 등)은
각 파일에 그대로 뒀다."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, UTC
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from api.chat.prompt_builder import ImageMatchJudgmentResult
from api.core.config import settings
from api.core.security import hash_password
from api.db.models import (
    AdminUser,
    Asset,
    AssetKind,
    AssetStatus,
    CharacterVersionDetail,
    ChatMessage,
    ChatMessageRole,
    ChatRoom,
    ChatRoomMemorySnapshot,
    CloverLedger,
    CloverLot,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Ending,
    FeatureName,
    Genre,
    LegalDocument,
    MediaBookCell,
    MediaBookPerson,
    MediaBookScene,
    ModerationStatus,
    Novel,
    NovelChapter,
    NovelChapterRevision,
    NovelJob,
    StartingSetup,
    StatDef,
    StoryPromptTemplate,
    StoryVersionDetail,
    User,
    UserFeatureGrant,
    UserPersona,
)
from api.db.session import engine
from api.llm.client import LLMCallContext, LLMClient
from api.llm.dependencies import get_llm_client
from api.main import app
from api.session.store import create_session


# migration c49014ae5b62가 시드해둔 terms/privacy
# 게시본(version "2026-09-06", requires_reconsent=True)이 세션 내내 사라지지 않는 ambient
# 상태다 — `_make_user`는 DB를 조회하지 않는 순수 헬퍼라 "현재 게시본이 몇 버전인지"를 알
# 수 없으므로, 어떤 게시본보다 큰 값을 기본값으로 둬 "이미 동의한 사용자"를 재현한다.
# `_reconsent_required`는 zero-padded ISO 날짜 문자열 비교라 "9999-12-31"이 서버가 강제하는
# `\d{4}-\d{2}-\d{2}` 포맷 안에서 사실상 최댓값이다.
_FAR_FUTURE_LEGAL_VERSION = "9999-12-31"


def _make_user(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4()}@example.com",
        "nickname": "테스터",
        "birth_date": date(2000, 1, 1),
        "terms_agreed_at": datetime.now(UTC),
        "privacy_agreed_at": datetime.now(UTC),
        "terms_version": _FAR_FUTURE_LEGAL_VERSION,
        "privacy_version": _FAR_FUTURE_LEGAL_VERSION,
    }
    defaults.update(overrides)
    return User(**defaults)


async def _make_user_with_clover_lot(
    db_session: AsyncSession, *, clover_balance: int, **overrides: object
) -> User:
    """`clover_balance`를 세팅한 유저와, 그 값과 정확히 같은 **무기한** 로트 1행
    (`kind="legacy_balance"`)을 함께 커밋한다.

    Σ(`clover_lots.remaining`) == `users.clover_balance`
    불변식을 테스트 셋업부터 지키기 위한 공용 헬퍼다. 기존 51곳이 쓰는
    `_make_user(clover_balance=N)`는 DB를 안 건드리는 순수 팩토리라 로트를 만들 수 없다 —
    이 헬퍼는 `_make_asset`처럼 `db_session`을 받아 직접 커밋하는 변종이다. `clover_balance`가
    0이면 로트를 만들지 않는다(마이그레이션 백필과 같은 규칙).

    🔴 **만료 있는 로트가 필요한 테스트는 이 헬퍼를 쓰지 않고 `CloverLot`을 직접 만든다.**
    만료 인자를 받게 열어 두지 않는 이유는 둘이다 — ① 지금 그걸 쓰는 호출부가 0곳이고
    ② 명명 인자로 열어 두면 `**overrides`로 전달하는 호출부(`test_clover_gate.py` 등 3곳)에서
    mypy가 `dict[str, object]`를 `datetime | None`에 못 맞춰 `[arg-type]`으로 막는다.
    """
    overrides["clover_balance"] = clover_balance
    user = _make_user(**overrides)
    db_session.add(user)
    await db_session.flush()
    if clover_balance > 0:
        db_session.add(
            CloverLot(
                user_id=user.id,
                granted_amount=clover_balance,
                remaining=clover_balance,
                expires_at=None,
                kind="legacy_balance",
            )
        )
        await db_session.flush()
    return user


def _patch_httpx(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], object],
    *,
    module: str = "api.llm.local_image",
) -> None:
    """`module`(기본 local_image)이 만드는 httpx.AsyncClient에 MockTransport를 주입한다."""
    real_client = httpx.AsyncClient

    def factory(**kwargs: object) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(f"{module}.httpx.AsyncClient", factory)


def _set_signing_clock(monkeypatch: pytest.MonkeyPatch, at: datetime) -> None:
    """GET 주소 서명 두 갈래의 시계를 함께 `at`(UTC aware)으로 고정한다 — 구간 서명은
    `api.core.s3._utcnow` 를, 요청마다 새로 하는 서명은 botocore 의 `get_current_datetime` 을 읽는다.
    둘을 같이 고정해야 호출부가 어느 서명을 쓰는지가 결과 URL 로 갈린다."""

    def fixed(remove_tzinfo: bool = True) -> datetime:
        return at.replace(tzinfo=None) if remove_tzinfo else at

    monkeypatch.setattr("api.core.s3._utcnow", lambda: at)
    monkeypatch.setattr("botocore.auth.get_current_datetime", fixed)


# 인증 없이 임의 `user_id`로 쿠키를 굽던
# `POST /dev/session-echo`(삭제됨) 대신 세션을 직접 만들어 쿠키에 넣는다. 호출
# `create_session(user_id)`는 프로덕션 로그인 경로 세 곳(`auth/router.py`의 `google_callback`(구글
# 콜백) · `onboarding_google`(구글 온보딩) · `login`(비밀번호 로그인))과 같은 형태라 세션 값과
# 유저별 역인덱스(`user_sessions:{user_id}`)까지 똑같이 쌓인다 — 그래서 이 헬퍼로 선 세션은 실제
# 로그인 세션과 구분되지 않는다(줄번호로 가리키면 썩는다 — 심볼로 가리킬 것).
# ⚠️ 한 테스트에서 HTTP 로그인(`/auth/login` 등)과 이 헬퍼를 섞지 말 것 — 응답 `Set-Cookie`로
# 들어온 쿠키에는 도메인이 붙고 여기서 넣는 쿠키에는 안 붙어, 같은 이름의 쿠키가 둘이 되고
# 쿠키를 읽는 순간 `httpx.CookieConflict`가 난다(현재 스위트에 그 조합은 0건이다).
# 더 나쁜 쪽은 쿠키를 읽지 않는 경우다 — 전송 시점에는 예외가 없고 `Cookie: session_id=A;
# session_id=B`로 둘 다 한 헤더에 실려 나가는데, Starlette의 `cookie_parser`는 `;`로 자른
# 조각을 dict에 그대로 덮어쓰므로 **뒤에 넣은 쿠키가 이긴다**(실측: jar 순서가 그대로 헤더
# 순서가 된다). 즉 예외 없이 조용히 잘못된 유저로 요청이 나간다.
async def _login_as(client: httpx.AsyncClient, user_id: uuid.UUID) -> None:
    session_id = await create_session(user_id)
    client.cookies.set(settings.session_cookie_name, session_id)


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
        email=str(defaults["email"]), password_hash=await hash_password(str(defaults["password"]))
    )
    db_session.add(admin)
    await db_session.flush()
    return {**defaults, "id": admin.id}


async def _grant_novelize(db_session: AsyncSession, user_id: uuid.UUID) -> UserFeatureGrant:
    """소설화 허용 행 하나를 flush 한다(커밋은 호출자)."""
    return await _grant_feature(db_session, user_id, "novelize")


async def _grant_feature(db_session: AsyncSession, user_id: uuid.UUID, feature: FeatureName) -> UserFeatureGrant:
    """기능 허용 행 하나를 flush 한다(커밋은 호출자). 허용한 운영자 행이 FK 로 필요해 함께 만든다 — 로그인할
    운영자가 아니라서 비밀번호 해시를 계산하지 않는다."""
    admin = AdminUser(email=f"admin-{uuid.uuid4()}@example.com", password_hash="unused")
    db_session.add(admin)
    await db_session.flush()
    grant = UserFeatureGrant(user_id=user_id, feature=feature, granted_by=admin.id)
    db_session.add(grant)
    await db_session.flush()
    return grant


@dataclass
class NovelTree:
    novel: Novel
    chapter: NovelChapter
    first_revision: NovelChapterRevision
    reverting_revision: NovelChapterRevision
    generate_job: NovelJob
    finished_job: NovelJob
    active_job: NovelJob


async def _make_novel_tree(
    db_session: AsyncSession, user_id: uuid.UUID, *, chat_room_id: uuid.UUID | None = None
) -> NovelTree:
    """소설 한 권과 그 아래 행을 FK 가 모두 이어지게 flush 한다(커밋은 호출자). 되돌리기 개정이 앞 개정을, 장 생성
    작업이 자기가 만든 개정을, AI 수정 작업이 장·기준 개정을 가리키고 진행 중 작업도 하나 있어, 지우는 순서가 틀리면
    FK 위반이 난다."""
    novel = Novel(
        user_id=user_id,
        chat_room_id=chat_room_id,
        content_id=uuid.uuid4(),
        content_type="character",
        content_title="원작",
        character_name="인물",
    )
    db_session.add(novel)
    await db_session.flush()
    now = datetime.now(UTC)
    chapter = NovelChapter(
        novel_id=novel.id,
        ordinal=1,
        start_message_id=uuid.uuid4(),
        start_message_created_at=now,
        end_message_id=uuid.uuid4(),
        end_message_created_at=now,
        assistant_message_count=1,
        source_hash="0" * 64,
    )
    db_session.add(chapter)
    await db_session.flush()
    first_revision = NovelChapterRevision(chapter_id=chapter.id, revision_no=1, body="첫 본문", source="generate")
    db_session.add(first_revision)
    await db_session.flush()
    reverting_revision = NovelChapterRevision(
        chapter_id=chapter.id,
        revision_no=2,
        body="첫 본문",
        source="revert",
        reverted_from_revision_id=first_revision.id,
    )
    generate_job = NovelJob(
        novel_id=novel.id,
        user_id=user_id,
        kind="chapter_generate",
        status="succeeded",
        chapter_id=chapter.id,
        result_revision_id=first_revision.id,
        charged_amount=1,
    )
    finished_job = NovelJob(
        novel_id=novel.id,
        user_id=user_id,
        kind="ai_edit",
        status="succeeded",
        chapter_id=chapter.id,
        base_revision_id=first_revision.id,
        charged_amount=1,
    )
    active_job = NovelJob(
        novel_id=novel.id, user_id=user_id, kind="chapter_generate", status="running", charged_amount=1
    )
    db_session.add_all([reverting_revision, generate_job, finished_job, active_job])
    await db_session.flush()
    return NovelTree(novel, chapter, first_revision, reverting_revision, generate_job, finished_job, active_job)


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


def _put_via_presigned_url(upload_url: str, body: bytes, content_type: str = "image/png") -> None:
    """브라우저처럼 발급받은 서명 URL 로 바로 PUT 한다 — 서버가 어느 키에 서명했는지 테스트가 몰라도 된다.
    서명에 Content-Type 이 묶여 있어 발급 때 보낸 값과 같아야 한다."""
    resp = httpx.put(upload_url, content=body, headers={"Content-Type": content_type})
    resp.raise_for_status()


async def _add_media_book_cell(
    db_session: AsyncSession,
    content_version_id: uuid.UUID,
    image_asset_id: uuid.UUID,
    blurred_asset_id: uuid.UUID | None = None,
) -> MediaBookCell:
    """인물 하나·장면 하나와 그 자리의 칸 하나를 버전에 넣는다. 칸의 글·스위치는 기본값과 다른 값을
    넣어 복제·복원 테스트가 "그대로 옮겼는가"를 기본값과 구분할 수 있게 한다."""
    person = MediaBookPerson(entity_id=uuid.uuid4(), content_version_id=content_version_id, name="민아", order=0)
    scene = MediaBookScene(entity_id=uuid.uuid4(), content_version_id=content_version_id, name="교실", order=0)
    cell = MediaBookCell(
        entity_id=uuid.uuid4(),
        content_version_id=content_version_id,
        person_entity_id=person.entity_id,
        scene_entity_id=scene.entity_id,
        image_asset_id=image_asset_id,
        blurred_asset_id=blurred_asset_id,
        situation_description="창가에서 웃는다",
        unlock_hint="첫 만남",
        exclude_from_chat=True,
    )
    db_session.add_all([person, scene, cell])
    await db_session.flush()
    return cell


async def _add_named_media_cell(
    db_session: AsyncSession,
    version_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    person: str,
    scene: str,
    *,
    entity_id: uuid.UUID | None = None,
    size: tuple[int, int] | None = (300, 400),
    situation_description: str = "",
    exclude_from_chat: bool = False,
) -> tuple[MediaBookCell, Asset]:
    """버전에 `person`×`scene` 칸 하나를 READY 원본 자산과 함께 넣는다. 축은 이름이 같으면 다시 쓰고, 없으면
    새로 만든다(새 축의 order 는 그 버전에 이미 있는 축 수 — 넣은 순서가 축 순서다)."""
    person_row = await db_session.scalar(
        sa.select(MediaBookPerson).where(
            MediaBookPerson.content_version_id == version_id, MediaBookPerson.name == person
        )
    )
    if person_row is None:
        person_count = await db_session.scalar(
            sa.select(sa.func.count()).select_from(MediaBookPerson).where(MediaBookPerson.content_version_id == version_id)
        )
        person_row = MediaBookPerson(
            entity_id=uuid.uuid4(), content_version_id=version_id, name=person, order=person_count or 0
        )
        db_session.add(person_row)
    scene_row = await db_session.scalar(
        sa.select(MediaBookScene).where(MediaBookScene.content_version_id == version_id, MediaBookScene.name == scene)
    )
    if scene_row is None:
        scene_count = await db_session.scalar(
            sa.select(sa.func.count()).select_from(MediaBookScene).where(MediaBookScene.content_version_id == version_id)
        )
        scene_row = MediaBookScene(
            entity_id=uuid.uuid4(), content_version_id=version_id, name=scene, order=scene_count or 0
        )
        db_session.add(scene_row)
    asset = Asset(
        owner_user_id=owner_user_id,
        storage_key=f"assets/situational-image/{uuid.uuid4()}.webp",
        kind=AssetKind.ORIGINAL,
        status=AssetStatus.READY,
        width=size[0] if size is not None else None,
        height=size[1] if size is not None else None,
    )
    db_session.add(asset)
    await db_session.flush()
    cell = MediaBookCell(
        entity_id=entity_id or uuid.uuid4(),
        content_version_id=version_id,
        person_entity_id=person_row.entity_id,
        scene_entity_id=scene_row.entity_id,
        image_asset_id=asset.id,
        situation_description=situation_description,
        exclude_from_chat=exclude_from_chat,
    )
    db_session.add(cell)
    await db_session.flush()
    return cell, asset


async def _make_published(
    db_session: AsyncSession,
    *,
    kind: str = "terms",
    version: str = "2024-01-01",
    body_markdown: str = "게시된 내용",
    requires_reconsent: bool = False,
    published_at: datetime | None = None,
) -> LegalDocument:
    document = LegalDocument(
        kind=kind,
        version=version,
        body_markdown=body_markdown,
        status="published",
        requires_reconsent=requires_reconsent,
        published_at=published_at or datetime.now(UTC),
    )
    db_session.add(document)
    await db_session.flush()
    return document


async def _make_published_character(
    db_session: AsyncSession, *, creator_user_id: uuid.UUID, genre_id: uuid.UUID, intro: str = "인트로"
) -> Content:
    """채팅 경로가 요구하는 최소 발행 캐릭터. `example_dialogues`가 비어 있지 않은 변종이라
    프롬프트에 예시 대화가 실린다 — 빈 리스트를 쓰는 변종(`test_chat_room_api.py` 등)과는
    렌더 결과가 달라 합치지 않았다."""
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
            intro=intro,
            example_dialogues=[{"userLine": "밥 먹었어?", "characterLine": "아직이야옹"}],
            character_prompt="프롬프트",
        )
    )
    await db_session.flush()

    content.current_published_version_id = version.id
    await db_session.flush()
    return content


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


async def _story_with_setup(
    db_session: AsyncSession, *, opening_message: str | None, prologue: str = "프롤로그"
) -> tuple[uuid.UUID, Content, StartingSetup]:
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
        prologue=prologue,
        opening_message=opening_message,
        order=1,
    )
    db_session.add(setup)
    await db_session.flush()
    return user.id, content, setup


async def _make_default_persona(db_session: AsyncSession, user_id: uuid.UUID, name: str) -> UserPersona:
    """대화 프로필을 만들어 사용자의 기본 프로필로 둔다 — 그 뒤 만드는 방은 이 프로필을 고른 채 시작한다."""
    persona = UserPersona(user_id=user_id, name=name)
    db_session.add(persona)
    await db_session.flush()
    user = await db_session.get(User, user_id)
    assert user is not None
    user.default_persona_id = persona.id
    return persona


async def _add_epilogue_ending(db_session: AsyncSession, setup: StartingSetup, epilogue: str, order: int = 1) -> Ending:
    ending = Ending(
        entity_id=uuid.uuid4(),
        starting_setup_id=setup.id,
        name=f"엔딩 {order}",
        turn_count_gate=1,
        judgment_prompt="떠났는가?",
        epilogue=epilogue,
        hint="힌트",
        order=order,
    )
    db_session.add(ending)
    await db_session.flush()
    return ending


class _FakeLLMClient(LLMClient):
    """단일 응답 페이크. `generate`는 `tokens`를 그대로 흘리고 `error`가 있으면 대신 raise하며,
    `generate_structured`는 `structured_result`를 돌려준다(없으면 `NotImplementedError` — 그
    경로가 불리면 안 되는 테스트가 바로 깨지라고).

    ⚠️ **호출 순서대로 소비되는 큐**가 필요한 스위트(엔딩 파이프라인·미리보기)는 이걸 쓰지 않고
    자기 파일의 큐 기반 페이크를 쓴다 — 같은 이름이지만 다른 물건이다."""

    def __init__(
        self,
        tokens: list[str] | None = None,
        error: Exception | None = None,
        structured_result: ImageMatchJudgmentResult | None = None,
        structured_error: Exception | None = None,
    ) -> None:
        self.tokens = tokens or []
        self.error = error
        self.structured_result = structured_result
        self.structured_error = structured_error
        self.received_prompt: str | None = None
        self.received_judgment_prompt: str | None = None
        self.generate_structured_called = False
        self.usages: list[LLMCallContext] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.usages.append(usage)
        self.received_prompt = prompt
        if self.error is not None:
            raise self.error
        for token in self.tokens:
            yield token

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.usages.append(usage)
        self.generate_structured_called = True
        self.received_judgment_prompt = prompt
        if self.structured_error is not None:
            raise self.structured_error
        if self.structured_result is None:
            raise NotImplementedError
        return self.structured_result


class _NeverCalledLLMClient(LLMClient):
    """LLM보다 먼저 실패해야 하는 테스트용 — LLM이 조금이라도 불리면 그 자체가 실패다."""

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        raise AssertionError("먼저 실패해야 할 검증보다 앞서 LLM이 호출됐다")
        yield ""  # pragma: no cover

    async def generate_structured(self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext) -> Any:
        raise AssertionError("먼저 실패해야 할 검증보다 앞서 LLM이 호출됐다")


# `LLMClient`로 받는다 — 이 저장소의 페이크는 파일마다 모양이 다르고(큐 기반·발행 심사용 등)
# 전부 `LLMClient` 하위라, 구체 페이크로 좁히면 이 헬퍼를 공유할 수 없다.
def _override_llm_client(fake: LLMClient) -> None:
    app.dependency_overrides[get_llm_client] = lambda: fake


def _clear_llm_override() -> None:
    app.dependency_overrides.pop(get_llm_client, None)


def _parse_sse_events(body: str) -> list[dict[str, Any]]:
    events = []
    for chunk in body.split("\n\n"):
        for line in chunk.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line.removeprefix("data: ")))
    return events


_GOLDEN_PROMPTS_DIR = Path(__file__).parent / "golden" / "prompts"


def _read_golden_prompt(filename: str) -> str:
    """`CHARACTER_CHAT_SYSTEM_INSTRUCTION` 같은 삭제된 프롬프트 상수 대신, 실제로 나가는
    문안과 바이트 단위로 같음이 이미 증명된 골든 파일에서 기대값을 읽는다
    (tests/test_prompt_goldens.py)."""
    return (_GOLDEN_PROMPTS_DIR / filename).read_text(encoding="utf-8")


# --- 긴 대화방(요약 접기·되감기 테스트) ---------------------------------------------


@dataclass(frozen=True)
class Room:
    room_id: uuid.UUID
    user_id: uuid.UUID
    base: datetime
    # 턴 번호(1부터) → (사용자 메시지, 어시스턴트 메시지)
    turns: dict[int, tuple[ChatMessage, ChatMessage]]


def _user_text(turn: int, length: int) -> str:
    return f"[U{turn:02d}]".ljust(length, "가")


def _assistant_text(turn: int, length: int) -> str:
    return f"[A{turn:02d}]".ljust(length, "나")


async def _open_room(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    *,
    turns: int,
    lane: str = "character",
    message_length: int = 20,
    user: User | None = None,
) -> Room:
    """방을 API로 만들고(오프닝은 앱이 넣는다) `turns`턴을 `created_at`을 명시해 심는다. 오프닝을
    하루 전으로 옮기고 그 뒤 1초 간격이라, 요청이 새로 넣는 메시지가 항상 가장 뒤에 온다."""
    if user is None:
        user = _make_user()
        db_session.add(user)
        await db_session.flush()
    genre = await _get_genre(db_session)
    if lane == "character":
        content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
        body: dict[str, str] = {"contentId": str(content.id), "contentType": "character"}
    else:
        content = await _make_published_story(db_session, creator_user_id=user.id, genre_id=genre.id)
        assert content.current_published_version_id is not None
        setup = StartingSetup(
            entity_id=uuid.uuid4(),
            content_version_id=content.current_published_version_id,
            name="첫 만남",
            prologue="낯선 마을에 도착했다.",
            opening_message="다시 만났네요!",
            order=1,
        )
        db_session.add(setup)
        await db_session.flush()
        db_session.add(
            StatDef(
                entity_id=uuid.uuid4(),
                starting_setup_id=setup.id,
                name="[STAT]신뢰",
                icon="heart",
                color="#ff0000",
                min_value=0,
                max_value=100,
                initial_value=73,
                unit=None,
                description="신뢰 스탯",
                order=1,
            )
        )
        body = {"contentId": str(content.id), "contentType": "story", "startingSetupId": str(setup.id)}
    await db_session.commit()

    await _login_as(db_client, user.id)
    created = await db_client.post("/chat-rooms", json=body)
    assert created.status_code == 201, created.text
    room_id = uuid.UUID(created.json()["id"])

    base = datetime.now(UTC) - timedelta(days=1)
    await db_session.execute(sa.update(ChatMessage).where(ChatMessage.chat_room_id == room_id).values(created_at=base))
    seeded: dict[int, tuple[ChatMessage, ChatMessage]] = {}
    for turn in range(1, turns + 1):
        pair = (
            ChatMessage(
                id=uuid.uuid4(),
                chat_room_id=room_id,
                role=ChatMessageRole.USER,
                content=_user_text(turn, message_length),
                created_at=base + timedelta(seconds=2 * turn - 1),
            ),
            ChatMessage(
                id=uuid.uuid4(),
                chat_room_id=room_id,
                role=ChatMessageRole.ASSISTANT,
                content=_assistant_text(turn, message_length),
                created_at=base + timedelta(seconds=2 * turn),
            ),
        )
        db_session.add_all(pair)
        seeded[turn] = pair
    await db_session.flush()
    await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room_id).values(turn_count=turns))
    await db_session.commit()
    return Room(room_id=room_id, user_id=user.id, base=base, turns=seeded)


async def _plant_snapshot(db_session: AsyncSession, room: Room, *, turn: int, text: str) -> None:
    assistant = room.turns[turn][1]
    db_session.add(
        ChatRoomMemorySnapshot(
            chat_room_id=room.room_id,
            cursor_created_at=assistant.created_at,
            cursor_message_id=assistant.id,
            summary_text=text,
            source="auto",
        )
    )
    await db_session.commit()


@dataclass(frozen=True)
class SnapshotRow:
    cursor_created_at: datetime
    cursor_message_id: uuid.UUID
    summary_text: str
    previous_text: str | None
    source: str


async def _snapshots(db_session: AsyncSession, room: Room) -> list[SnapshotRow]:
    rows = (
        await db_session.execute(
            sa.select(
                ChatRoomMemorySnapshot.cursor_created_at,
                ChatRoomMemorySnapshot.cursor_message_id,
                ChatRoomMemorySnapshot.summary_text,
                ChatRoomMemorySnapshot.previous_text,
                ChatRoomMemorySnapshot.source,
            )
            .where(ChatRoomMemorySnapshot.chat_room_id == room.room_id)
            .order_by(ChatRoomMemorySnapshot.cursor_created_at)
        )
    ).all()
    return [SnapshotRow(*row) for row in rows]


async def _memory_version(db_session: AsyncSession, room: Room) -> int | None:
    version: int | None = await db_session.scalar(
        sa.select(ChatRoom.memory_version).where(ChatRoom.id == room.room_id)
    )
    return version


async def _wait_until_lock_wait(observer: AsyncConnection, *, seconds: float) -> None:
    """`asyncio.sleep`로 타이밍을 추측하는 대신, 가입 요청(이메일 가입·소셜 온보딩)의 INSERT가 실제로 users 테이블에
    대한 쓰기 잠금(`RowExclusiveLock`)을 이미 쥔 채 인터로퍼의 트랜잭션 종료를 기다리는
    상태(`pg_locks`의 미승인 `transactionid` 대기)에 들어갔는지 `pg_locks`로 직접 관측한다.
    `pg_stat_activity.query`는 이 시나리오에서 신뢰할 수 없었다 — 실제로는 INSERT가 블록된
    상태인데도 그 이전 SELECT의 텍스트를 그대로 보여줬다(직접 재현해 확인). `pg_locks`는
    질의 텍스트가 아니라 실제 잠금 상태이므로 이 문제가 없다. 제한 시간 안에 관측되지 않으면
    조용히 넘어가지 않고 실패시킨다."""
    try:
        async with asyncio.timeout(seconds):
            while True:
                waiting = await observer.scalar(
                    sa.text(
                        "SELECT count(*) FROM pg_locks blocked"
                        " WHERE blocked.locktype = 'transactionid' AND NOT blocked.granted"
                        " AND EXISTS ("
                        "   SELECT 1 FROM pg_locks holding"
                        "   WHERE holding.pid = blocked.pid"
                        "     AND holding.locktype = 'relation'"
                        "     AND holding.relation = 'users'::regclass"
                        "     AND holding.mode = 'RowExclusiveLock'"
                        "     AND holding.granted"
                        " )"
                    )
                )
                if waiting:
                    return
                await asyncio.sleep(0.01)
    except TimeoutError:
        raise AssertionError(
            f"{seconds}초 안에 가입 요청 커넥션이 users 테이블 잠금 대기 상태로 관측되지"
            " 않았다 (pg_locks: RowExclusiveLock 보유 + transactionid 미승인 대기)"
        ) from None


async def _assert_blocked(task: "asyncio.Task[object]", *, block_seconds: float = 0.5) -> None:
    """`task`가 DB 락에 막혀 있다는 것을 단언한다.

    🔴 **이 단언이 독립 커넥션 경쟁 테스트를 항진명제에서 구한다.** 최종 상태만 보면 두 연산이
    순차로 돌아도 같은 값이 나오므로, "정말 동시에 같은 행을 다퉜는가"는 여기서만 증명된다.
    `shield`로 감싸는 이유는 `wait_for`의 타임아웃이 task를 취소해 버리면 뒤에서 결과를 받을
    수 없기 때문이다.

    타이밍 의존이 한 방향뿐이라 안전하다 — 막힌 쪽은 상대가 커밋하기 전에는 **원리적으로**
    진행할 수 없으므로 타임아웃이 반드시 난다. 반대로 느슨하게 잡아 실패하는 경우는 없다.

    (인자 이름이 `timeout`이 아닌 것은 ruff `ASYNC109` 때문이다 — 그 규칙은 타임아웃을
    인자로 넘기지 말고 `asyncio.timeout`을 쓰라고 하는데, 여기서 재는 것은 "제한 시간"이
    아니라 **"이만큼 기다려도 안 끝난다"**는 성질이라 의미가 다르다.)
    """
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(asyncio.shield(task), block_seconds)


@contextmanager
def _open_transaction_probe() -> Generator[set[int], None, None]:
    """지금 루트 트랜잭션이 열려 있는(= 커넥션을 쥔) ORM 세션들의 집합을 실시간으로 유지한다.

    외부 호출(LLM·S3·메일)을 기다리는 동안 DB 커넥션을 쥐지 않는다는 성질을 재려고 만들었다.
    `engine.pool.checkedout()` 은 `db_client` 픽스처에서 쓸 수 없다 — 그 픽스처는 테스트 전체를 커넥션 하나에
    묶어 두어 값이 요청 전·중·후 내내 1이다. 세션 트랜잭션 이벤트는 같은 픽스처 위에서도 세션마다 따로 오고,
    실서버에서 "세션의 루트 트랜잭션이 열려 있다"는 "그 세션이 풀에서 커넥션을 빌려 쥐고 있다"와 같다
    (세션은 루트 트랜잭션이 커넥션을 처음 쓸 때 빌리고 그 트랜잭션이 끝날 때 돌려준다).

    SAVEPOINT 는 루트가 아니라 세지 않는다. 외부 호출 페이크는 이 집합의 크기를 **기록만** 하고 단언은 요청이
    끝난 뒤에 한다 — 페이크 안에서 던지면 요약 접기처럼 예외를 전부 삼키는 자리가 신호를 지운다."""
    open_sessions: set[int] = set()

    def _after_begin(session: Session, transaction: SessionTransaction, _connection: Connection) -> None:
        if transaction.parent is None:
            open_sessions.add(id(session))

    def _after_transaction_end(session: Session, transaction: SessionTransaction) -> None:
        if transaction.parent is None:
            open_sessions.discard(id(session))

    sa.event.listen(Session, "after_begin", _after_begin)
    sa.event.listen(Session, "after_transaction_end", _after_transaction_end)
    try:
        yield open_sessions
    finally:
        sa.event.remove(Session, "after_begin", _after_begin)
        sa.event.remove(Session, "after_transaction_end", _after_transaction_end)


_P = ParamSpec("_P")
_T = TypeVar("_T")


def _noting_open_transactions(
    open_sessions: set[int], seen: list[tuple[str, int]], name: str, func: Callable[_P, _T]
) -> Callable[_P, _T]:
    """`func`(저장소 호출처럼 스레드에서 도는 동기 함수)를 부를 때마다 `(name, 그 순간 열린 루트 트랜잭션 수)` 를
    `seen` 에 적고 진짜 함수를 부른다. `open_sessions` 는 `_open_transaction_probe` 가 주는 집합이다. 단언은 요청이
    끝난 뒤 `seen` 으로 한다 — 이유는 그 프로브의 docstring."""

    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        seen.append((name, len(open_sessions)))
        return func(*args, **kwargs)

    return wrapper


def _noting_open_transactions_async(
    open_sessions: set[int], seen: list[tuple[str, int]], name: str, func: Callable[_P, Awaitable[_T]]
) -> Callable[_P, Awaitable[_T]]:
    """`_noting_open_transactions` 의 코루틴 함수판(집 PC capabilities 조회·메일 발송처럼 루프 위에서 기다리는 호출)."""

    async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        seen.append((name, len(open_sessions)))
        return await func(*args, **kwargs)

    return wrapper


# --- 소설 라우트 ----------------------------------------------------------------------


async def _allow_novelize(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, user_id: uuid.UUID) -> None:
    """소설화를 켜고 `user_id` 를 명단에 더한 뒤 허용 행을 넣고 커밋한다. 앞서 더한 계정은 명단에 남는다."""
    monkeypatch.setattr(settings, "novelize_enabled", True)
    monkeypatch.setattr(settings, "novelize_grant_allowlist", [*settings.novelize_grant_allowlist, user_id])
    await _grant_novelize(db_session, user_id)
    await db_session.commit()


async def _allow_chat_premium(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, user_id: uuid.UUID) -> None:
    """채팅 상위 모델을 켜고 `user_id` 를 명단에 더한 뒤 허용 행을 넣고 커밋한다. 앞서 더한 계정은 명단에 남는다."""
    monkeypatch.setattr(settings, "chat_premium_models_enabled", True)
    monkeypatch.setattr(
        settings, "chat_premium_model_allowlist", [*settings.chat_premium_model_allowlist, user_id]
    )
    await _grant_feature(db_session, user_id, "chat_premium_models")
    await db_session.commit()


async def _novel_setup(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    *,
    turns: int = 3,
    lane: str = "character",
    persona: str | None = "서진",
) -> tuple[Room, uuid.UUID]:
    """잔액 100 클로버인 새 사용자로 `turns` 턴짜리 방을 열고(로그인된다), 소설화를 허용한 뒤 방의 소설을 라우트로
    만든다. `persona` 가 있으면 그 이름의 대화 프로필을 방에 걸어 두어 소설의 주인공 이름이 된다."""
    owner = await _make_user_with_clover_lot(db_session, clover_balance=100)
    room = await _open_room(db_client, db_session, turns=turns, lane=lane, user=owner)
    if persona is not None:
        profile = UserPersona(user_id=owner.id, name=persona)
        db_session.add(profile)
        await db_session.flush()
        await db_session.execute(sa.update(ChatRoom).where(ChatRoom.id == room.room_id).values(persona_id=profile.id))
    await _allow_novelize(db_session, monkeypatch, owner.id)
    created = await db_client.post(f"/chat-rooms/{room.room_id}/novel")
    assert created.status_code == 201, created.text
    return room, uuid.UUID(created.json()["id"])


async def _room_messages(db: AsyncSession, room_id: uuid.UUID) -> list[ChatMessage]:
    rows = await db.scalars(
        sa.select(ChatMessage)
        .where(ChatMessage.chat_room_id == room_id)
        .order_by(ChatMessage.created_at, ChatMessage.id)
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


async def _add_chapter(
    db_session: AsyncSession,
    novel_id: uuid.UUID,
    room: Room,
    start: ChatMessage,
    end: ChatMessage,
    body: str = "첫 문단이다.\n\n둘째 문단이다.\n\n셋째 문단이다.",
) -> NovelChapter:
    """작업을 거치지 않고 장 하나와 첫 개정을 넣고 커밋한다. 장의 구간 모양(응답 수·해시)은 지금 방 원문으로 계산한다
    — 재생성의 원문 변경 검사가 이 값과 비교한다."""
    from api.novelize.source import segment_hash

    messages = await _room_messages(db_session, room.room_id)
    segment = messages[messages.index(start) : messages.index(end) + 1]
    ordinal = await db_session.scalar(
        sa.select(sa.func.coalesce(sa.func.max(NovelChapter.ordinal), 0)).where(NovelChapter.novel_id == novel_id)
    )
    chapter = NovelChapter(
        novel_id=novel_id,
        ordinal=(ordinal or 0) + 1,
        start_message_id=start.id,
        start_message_created_at=start.created_at,
        end_message_id=end.id,
        end_message_created_at=end.created_at,
        assistant_message_count=sum(1 for m in segment if m.role == ChatMessageRole.ASSISTANT),
        source_hash=segment_hash(segment),
    )
    db_session.add(chapter)
    await db_session.flush()
    db_session.add(NovelChapterRevision(chapter_id=chapter.id, revision_no=1, body=body, source="generate"))
    await db_session.commit()
    return chapter


async def _queue_job(
    db_session: AsyncSession, novel_id: uuid.UUID, start: ChatMessage, end: ChatMessage
) -> NovelJob:
    """차감까지 한 진행 대기 장 생성 작업 하나(단가 40). 실행은 띄우지 않는다."""
    from api.novelize.billing import create_charged_job

    novel = await db_session.get_one(Novel, novel_id)
    job = NovelJob(
        novel_id=novel_id,
        user_id=novel.user_id,
        kind="chapter_generate",
        start_message_id=start.id,
        start_message_created_at=start.created_at,
        end_message_id=end.id,
        end_message_created_at=end.created_at,
    )
    return await create_charged_job(db_session, job=job, expected_cost=40, now=datetime.now(UTC))


async def _novel_ledger(db: AsyncSession, user_id: uuid.UUID) -> list[tuple[str, int]]:
    """사용자의 소설화 원장 행(종류, 금액) — 금액·종류 순."""
    rows = await db.execute(
        sa.select(CloverLedger.kind, CloverLedger.amount)
        .where(CloverLedger.user_id == user_id, CloverLedger.kind.in_(("novelize_spend", "novelize_refund")))
        .order_by(CloverLedger.amount, CloverLedger.kind)
    )
    return [(kind, amount) for kind, amount in rows.all()]


@dataclass(frozen=True)
class EndingPriorityScenario:
    """엔딩 우선 스탯 판정 순서를 실채팅·빌더 미리보기에 같은 입력으로 넣어 같은 결과가 나오는지 보는 시나리오.

    `stats` 는 스탯 이름 → 초기값, `stat_changes` 는 이번 턴 스탯 판정이 내는 새 값이다. `endings` 는 목록 순서대로
    (이름, 우선 스탯 이름 또는 None, `스탯 >= 문턱` 규칙 하나 또는 None). `verdicts` 는 엔딩 판정 모델이 차례로 낼
    답이고, `judged` 는 판정 모델을 부른 엔딩 이름 순서, `reached` 는 발동한 엔딩 이름이다. 판정한 엔딩은 판정 문안에
    `ending_priority_marker(이름)` 을 넣어 판정 프롬프트에서 찾는다."""

    stats: dict[str, int]
    stat_changes: dict[str, int]
    endings: list[tuple[str, str | None, tuple[str, int] | None]]
    verdicts: list[bool]
    judged: list[str]
    reached: str | None


def ending_priority_marker(name: str) -> str:
    return f"판정표지-{name}"


def judged_ending_names(prompts: list[str], scenario: EndingPriorityScenario) -> list[str]:
    """판정 프롬프트마다 어느 엔딩의 판정 문안이 실렸는지 이름으로 바꾼다(스탯 판정 프롬프트는 건너뛴다)."""
    names = [name for name, _, _ in scenario.endings]
    return [name for prompt in prompts for name in names if ending_priority_marker(name) in prompt]


_ROUTE_ENDINGS: list[tuple[str, str | None, tuple[str, int] | None]] = [
    ("처음", None, None),
    ("도희", "도희", ("도희", 55)),
    ("유나", "유나", ("유나", 55)),
    ("세빈", "세빈", ("세빈", 55)),
    ("노말", None, None),
]

ENDING_PRIORITY_SCENARIOS = [
    pytest.param(
        # 조감독 장기 측정의 턴 105 모양 — 루트 셋, 규칙이 거짓인 배드, 시계가 0 이라 규칙이 참인 노말(무리 뒤). 이번 턴
        # 판정이 세빈을 95 → 100 으로 올려 반영 뒤 값으로 비교해야 세빈이 1등이다. 세빈이 아니오면 도희·유나로 내려가지
        # 않고, 노말로도 떨어지지 않는다 — 그 턴은 엔딩 없이 끝난다.
        EndingPriorityScenario(
            stats={"도희": 98, "유나": 86, "세빈": 95, "상영회까지": 0},
            stat_changes={"세빈": 100},
            endings=[
                ("도희", "도희", ("도희", 55)),
                ("유나", "유나", ("유나", 55)),
                ("세빈", "세빈", ("세빈", 55)),
                ("배드", None, ("유나", 90)),
                ("노말", None, ("상영회까지", 0)),
            ],
            verdicts=[False],
            judged=["세빈"],
            reached=None,
        ),
        id="turn-105-highest-only-then-no-ending",
    ),
    pytest.param(
        # 도희·세빈 동점이면 목록 순서로 둘 다, 무리는 도희 자리(처음 다음)에 선다. 세빈에서 발동한다.
        EndingPriorityScenario(
            stats={"도희": 100, "유나": 86, "세빈": 100},
            stat_changes={},
            endings=_ROUTE_ENDINGS,
            verdicts=[False, False, True],
            judged=["처음", "도희", "세빈"],
            reached="세빈",
        ),
        id="tie-in-list-order",
    ),
    pytest.param(
        # 동점 둘이 모두 아니오면 무리 뒤의 노말도 판정하지 않고 그 턴을 끝낸다.
        EndingPriorityScenario(
            stats={"도희": 100, "유나": 86, "세빈": 100},
            stat_changes={},
            endings=_ROUTE_ENDINGS,
            verdicts=[False, False, False],
            judged=["처음", "도희", "세빈"],
            reached=None,
        ),
        id="tie-all-decline-ends-turn",
    ),
    pytest.param(
        # 무리 앞의 우선 스탯 없는 엔딩이 발동하면 무리는 판정하지 않는다.
        EndingPriorityScenario(
            stats={"도희": 100, "유나": 86, "세빈": 90},
            stat_changes={},
            endings=_ROUTE_ENDINGS,
            verdicts=[True],
            judged=["처음"],
            reached="처음",
        ),
        id="earlier-ending-reached-first",
    ),
    pytest.param(
        # 우선 스탯 엔딩이 하나도 규칙을 넘지 않은 턴은 무리가 없어 지금처럼 목록 순서대로 노말까지 판정한다.
        EndingPriorityScenario(
            stats={"도희": 40, "유나": 40, "세빈": 40},
            stat_changes={},
            endings=_ROUTE_ENDINGS,
            verdicts=[False, True],
            judged=["처음", "노말"],
            reached="노말",
        ),
        id="no-group-keeps-list-order",
    ),
]
