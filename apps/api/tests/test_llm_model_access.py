"""상위 모델 허용 판정과 유효 모델 폴백.

채팅은 스위치 하나만 본다. 소설은 스위치 → env 명단 → 허용 행 순서이고, 소설화 자체 허용까지 참이어야 한다.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.db.models import FeatureName
from api.llm.model_access import (
    effective_model,
    effective_room_model,
    has_chat_premium_access,
    has_novel_premium_access,
)
from factories import _grant_feature, _make_user


class _NoQuerySession:
    """어떤 속성에 닿아도 실패하는 세션 대역 — 판정이 쿼리를 내지 않았음을 본다."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"쿼리를 내면 안 된다: {name}")


async def _user(db_session: AsyncSession, *features: FeatureName) -> uuid.UUID:
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    for feature in features:
        await _grant_feature(db_session, user.id, feature)
    await db_session.commit()
    return user.id


def _open_novel(monkeypatch: pytest.MonkeyPatch, *, enabled: bool, allowlist: list[uuid.UUID]) -> None:
    monkeypatch.setattr(settings, "novelize_premium_models_enabled", enabled)
    monkeypatch.setattr(settings, "novelize_premium_model_allowlist", allowlist)


def _open_novelize(monkeypatch: pytest.MonkeyPatch, user_id: uuid.UUID) -> None:
    monkeypatch.setattr(settings, "novelize_enabled", True)
    monkeypatch.setattr(settings, "novelize_grant_allowlist", [user_id])


# ---- 채팅 ----


@pytest.mark.parametrize("enabled", [pytest.param(True, id="switch-on"), pytest.param(False, id="switch-off")])
async def test_chat_access_follows_the_switch_alone_without_reading_grant_rows(
    monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    """명단에도 허용 행에도 없는 아무 계정이 스위치를 그대로 따른다. 판정이 DB 를 읽으면 쿼리를 막는 세션 대역에서
    실패한다 — 남아 있는 옛 허용 행이 다시 판정에 끼어들지 못한다."""
    monkeypatch.setattr(settings, "chat_premium_models_enabled", enabled)

    assert await has_chat_premium_access(_NoQuerySession(), uuid.uuid4()) is enabled  # type: ignore[arg-type]


# ---- 소설 ----


async def test_novel_access_needs_its_own_grant_and_novelize_access(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = await _user(db_session, "novelize", "novelize_premium_models")
    _open_novel(monkeypatch, enabled=True, allowlist=[user_id])
    _open_novelize(monkeypatch, user_id)

    assert await has_novel_premium_access(db_session, user_id) is True


async def test_novel_access_is_denied_without_novelize_access(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """소설 상위 모델 허용만으로는 안 된다 — 소설화 자체가 꺼져 있으면 모델 선택도 없다."""
    user_id = await _user(db_session, "novelize", "novelize_premium_models")
    _open_novel(monkeypatch, enabled=True, allowlist=[user_id])
    monkeypatch.setattr(settings, "novelize_enabled", False)

    assert await has_novel_premium_access(db_session, user_id) is False


async def test_novel_access_is_denied_with_only_the_chat_grant(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """채팅 상위 모델이 열려 있고(옛 채팅 허용 행까지 남아 있고) 소설화 허용이 있어도 소설 상위 모델 허용 행이 없으면
    안 된다."""
    user_id = await _user(db_session, "novelize", "chat_premium_models")
    _open_novel(monkeypatch, enabled=True, allowlist=[user_id])
    _open_novelize(monkeypatch, user_id)
    monkeypatch.setattr(settings, "chat_premium_models_enabled", True)

    assert await has_novel_premium_access(db_session, user_id) is False
    assert await has_chat_premium_access(db_session, user_id) is True


@pytest.mark.parametrize(
    ("enabled", "allowlisted"),
    [
        pytest.param(False, True, id="switch-off"),
        pytest.param(True, False, id="not-allowlisted"),
    ],
)
async def test_novel_access_is_denied_without_a_query_when_switch_or_allowlist_fails(
    monkeypatch: pytest.MonkeyPatch, enabled: bool, allowlisted: bool
) -> None:
    user_id = uuid.uuid4()
    _open_novel(monkeypatch, enabled=enabled, allowlist=[user_id] if allowlisted else [uuid.uuid4()])
    _open_novelize(monkeypatch, user_id)

    assert await has_novel_premium_access(_NoQuerySession(), user_id) is False  # type: ignore[arg-type]


# ---- 유효 모델 ----


@pytest.mark.parametrize(
    ("stored", "allowed", "expected"),
    [
        pytest.param(None, True, "gemini", id="unset-is-gemini"),
        pytest.param("gemini", False, "gemini", id="gemini-needs-no-access"),
        pytest.param("sonnet", True, "sonnet", id="allowed-premium-stays"),
        pytest.param("opus", True, "opus", id="allowed-opus-stays"),
        pytest.param("sonnet", False, "gemini", id="revoked-falls-back"),
        pytest.param("haiku", True, "gemini", id="retired-model-falls-back"),
    ],
)
def test_effective_model(stored: str | None, allowed: bool, expected: str) -> None:
    assert effective_model(stored, allowed=allowed) == expected


@pytest.mark.parametrize(
    ("enabled", "opus_room"),
    [pytest.param(True, "opus", id="switch-on"), pytest.param(False, "gemini", id="switch-off")],
)
async def test_effective_room_model_follows_the_switch_for_any_account(
    monkeypatch: pytest.MonkeyPatch, enabled: bool, opus_room: str
) -> None:
    """허용 행이 없는 계정의 Opus 방도 스위치가 켜져 있으면 Opus 로, 꺼지면 Gemini 로 돈다. Gemini 방은 스위치와 무관하게
    Gemini 다. 어느 쪽도 쿼리를 내지 않는다(턴마다 부른다)."""
    monkeypatch.setattr(settings, "chat_premium_models_enabled", enabled)
    user_id = uuid.uuid4()

    assert await effective_room_model(_NoQuerySession(), user_id, None) == "gemini"  # type: ignore[arg-type]
    assert await effective_room_model(_NoQuerySession(), user_id, "gemini") == "gemini"  # type: ignore[arg-type]
    assert await effective_room_model(_NoQuerySession(), user_id, "opus") == opus_room  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "stored",
    [pytest.param("sonnet", id="sonnet-only-for-novels"), pytest.param("haiku", id="retired-model")],
)
async def test_a_room_storing_a_model_chat_does_not_offer_is_gemini_even_with_access(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, stored: str
) -> None:
    """Sonnet 은 레지스트리에 있지만 채팅에서는 고를 수 없다 — 그 값이 남은 방은 스위치가 켜져 있어도 Gemini 로 돈다. 소설이
    쓰는 `effective_model` 은 같은 값을 그대로 읽는다."""
    user_id = await _user(db_session)
    monkeypatch.setattr(settings, "chat_premium_models_enabled", True)

    assert await effective_room_model(db_session, user_id, stored) == "gemini"
    assert effective_model("sonnet", allowed=True) == "sonnet"
