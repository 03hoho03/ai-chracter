"""테스트 전역에서 본문이 글자까지 같았던 셋업 헬퍼. `goal-prompt.md §4 T-2`가 80개
파일에 복사돼 있던 것 중 완전 동일본(또는 docstring만 다른 것)만 여기로 옮겼다.
`goal-prompt.md §4 T-3`이 변종이 있던 나머지(호출부를 안 깨는 시그니처로 합친 것)를 더했다.

LLM 페이크 주입(`_override_llm_client`/`_clear_llm_override`)·SSE 파싱(`_parse_sse_events`)·
`_make_published_character`도 같은 기준으로 합쳤다 — 여기 있는 것과 **의미가 같은** 사본만
가져왔고, 모양이 다른 변종(큐 기반 LLM 페이크, `example_dialogues`가 빈 캐릭터 팩토리 등)은
각 파일에 그대로 뒀다."""

import json
import uuid
from collections.abc import AsyncIterator, Callable, Generator
from contextlib import contextmanager
from datetime import date, datetime, UTC
from pathlib import Path
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import ImageMatchJudgmentResult
from api.core.config import settings
from api.core.security import hash_password
from api.db.models import (
    AdminUser,
    Asset,
    AssetKind,
    AssetStatus,
    CharacterVersionDetail,
    CloverLot,
    Content,
    ContentTarget,
    ContentType,
    ContentVersion,
    ContentVisibility,
    Genre,
    LegalDocument,
    ModerationStatus,
    StoryPromptTemplate,
    StoryVersionDetail,
    User,
)
from api.db.session import engine
from api.llm.client import LLMCallContext, LLMClient
from api.llm.dependencies import get_llm_client
from api.main import app
from api.session.store import create_session


# consent-gate-goal-prompt.md CG-3/CG-4: migration c49014ae5b62가 시드해둔 terms/privacy
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

    clover-page-goal-prompt.md CE-4의 Σ(`clover_lots.remaining`) == `users.clover_balance`
    불변식을 테스트 셋업부터 지키기 위한 공용 헬퍼다(CE-35). 기존 51곳이 쓰는
    `_make_user(clover_balance=N)`는 DB를 안 건드리는 순수 팩토리라 로트를 만들 수 없다 —
    이 헬퍼는 `_make_asset`처럼 `db_session`을 받아 직접 커밋하는 변종이다. `clover_balance`가
    0이면 로트를 만들지 않는다(마이그레이션 백필과 같은 규칙 — T-5).

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


# secure-issue-goal-prompt.md SEC-2: 인증 없이 임의 `user_id`로 쿠키를 굽던
# `POST /dev/session-echo`(SEC-1 에서 삭제됨) 대신 세션을 직접 만들어 쿠키에 넣는다. 호출
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

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        self.received_prompt = prompt
        if self.error is not None:
            raise self.error
        for token in self.tokens:
            yield token

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
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
    (prompt-db-goal-prompt.md D-13, tests/test_prompt_goldens.py)."""
    return (_GOLDEN_PROMPTS_DIR / filename).read_text(encoding="utf-8")
