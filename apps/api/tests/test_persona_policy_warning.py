"""정책 차단 안내 문구의 분기.

`ChatPolicyWarningEvent.message`는 **그 턴 생성 프롬프트에 대화 프로필 섹션이 실제로
렌더됐을 때만** 프로필 안내 문구로 바뀐다. 판정 기준은 "값이 비지 않았다" **그리고** "그 턴의
활성 세트에서 `select_sections_for_render`가 `user_persona` 슬롯을 골랐다"다.

- 프로필 있음/없음 × 실채팅/재생성/미리보기(3곳의 `yield ChatPolicyWarningEvent`).
- 프로필은 있는데 활성 세트에 슬롯이 없는 경우(캐시 TTL 창): 배포 직후 Redis 캐시에
  슬롯 추가 마이그레이션(`b72c33c70240`) 이전 세트가 남아 있는 상황을 그대로 만든다 — 테스트 DB에
  남아 있는 `a69cbd40dec8`의 레인 세트(그 마이그레이션이 복사한 원본, 슬롯 없는 character 게시본)를 캐시에 심는다. 이때는 섹션이 들어가지 않았으므로 기존 문구다.
- 어느 경우든 클로버는 되돌리지 않는다. 셋업은
  `test_clover_chat_refund.py`의 관례(셋업 뒤에 상한을 0으로 패치)를 따른다.
"""

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_set_cache import set_cached_active_prompt_set
from api.core import clover, rate_limit_gate
from api.db.models import User, UserPersona
from api.db.models.clover import CloverLedger
from api.db.models.prompt import PromptSection, PromptSet
from api.llm.client import LLMPolicyViolationError
from factories import (
    _clear_llm_override,
    _FakeLLMClient,
    _get_genre,
    _login_as,
    _make_published_character,
    _make_user_with_clover_lot,
    _override_llm_client,
    _parse_sse_events,
)

# 확정 문구(기존 `_POLICY_WARNING_MESSAGE`)에서 글자 그대로 옮겼다.
# 라우터 상수를 import해 비교하지 않는 이유: 상수끼리 비교하면 상수가 틀려도 통과한다.
_DEFAULT_MESSAGE = "메시지 생성이 콘텐츠 정책에 의해 중단되었습니다."
_PERSONA_MESSAGE = "메시지 생성이 콘텐츠 정책에 의해 중단되었습니다. 대화 프로필 내용이 원인일 수 있어요."

_START_BALANCE = 100

_SURFACES = ["send", "regenerate", "preview"]


async def _cache_pre_m2_character_set(db_session: AsyncSession) -> None:
    """캐시 TTL 창을 만든다 — 활성 세트 캐시에 슬롯 없는 옛 세트가 남아 있는 상태."""
    has_persona_slot = (
        select(PromptSection.id)
        .where(PromptSection.prompt_set_id == PromptSet.id, PromptSection.slot == "user_persona")
        .exists()
    )
    # 슬롯 추가 마이그레이션 이전 character 게시본 — 테스트 DB에서는 `a69cbd40dec8`이 심은 레인 세트 하나다.
    prompt_set = await db_session.scalar(
        select(PromptSet).where(PromptSet.lane == "character", PromptSet.status == "published", ~has_persona_slot)
    )
    assert prompt_set is not None
    sections = list(
        (await db_session.scalars(select(PromptSection).where(PromptSection.prompt_set_id == prompt_set.id))).all()
    )
    await set_cached_active_prompt_set("character", prompt_set, sections)


async def _run_policy_turn(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    *,
    surface: str,
    with_persona: bool,
    stale_cache: bool = False,
) -> tuple[User, list[dict[str, Any]]]:
    """기본 프로필이 있는(또는 없는) 유저로 `surface`에서 정책 위반 턴을 일으킨다.

    프로필은 **기본**으로 걸어 둔다 — 새 방은 기본으로 시작하고, 미리보기는 작가의 기본을
    쓴다. 그래서 세 경로가 같은 셋업으로 프로필을 싣는다.
    """
    user = await _make_user_with_clover_lot(
        db_session,
        clover_balance=_START_BALANCE,
        clover_spend_confirmed_on=clover.kst_today(datetime.now(UTC)),
    )
    if with_persona:
        persona = UserPersona(user_id=user.id, name="하늘", gender="female", description="밤하늘을 좋아한다")
        db_session.add(persona)
        await db_session.flush()
        user.default_persona_id = persona.id
    await db_session.commit()
    await _login_as(db_client, user.id)

    if surface == "preview":
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
        created = await db_client.post("/preview-sessions", json=payload)
        assert created.status_code == 201
        url = f"/preview-sessions/{created.json()['previewSessionId']}/messages"
    else:
        genre = await _get_genre(db_session)
        content = await _make_published_character(db_session, creator_user_id=user.id, genre_id=genre.id)
        await db_session.commit()
        room = await db_client.post("/chat-rooms", json={"contentId": str(content.id), "contentType": "character"})
        assert room.status_code == 201
        assert room.json()["personaId"] == (str(user.default_persona_id) if with_persona else None)
        room_id = room.json()["id"]
        url = f"/chat-rooms/{room_id}/messages"
        if surface == "regenerate":
            # 재생성은 "마지막 메시지가 AI 응답"인 상태를 요구한다 — 상한 패치 전이라 무료분으로 통과.
            _override_llm_client(_FakeLLMClient(tokens=["첫", "응답"]))
            try:
                sent = await db_client.post(url, json={"content": "안녕"})
            finally:
                _clear_llm_override()
            assert sent.status_code == 200
            url = f"/chat-rooms/{room_id}/regenerate"

    # 셋업 전송이 캐시를 채웠을 수 있으므로 그 뒤에 덮어쓴다.
    if stale_cache:
        await _cache_pre_m2_character_set(db_session)

    # 여기서부터 클로버로 낸다.
    monkeypatch.setattr(rate_limit_gate, "CHAT_DAILY_LIMIT", 0)
    _override_llm_client(_FakeLLMClient(error=LLMPolicyViolationError("blocked")))
    try:
        if surface == "regenerate":
            resp = await db_client.post(url)
        else:
            resp = await db_client.post(url, json={"content": "안녕"})
    finally:
        _clear_llm_override()
    assert resp.status_code == 200

    await db_session.refresh(user)
    return user, _parse_sse_events(resp.text)


async def _assert_not_refunded(db_session: AsyncSession, user: User) -> None:
    """정책 위반은 소모로 둔다. 원장에 차감 한 행만 있고 환불 행이 없다."""
    assert user.clover_balance == _START_BALANCE - clover.CHAT_TURN_COST
    rows = (await db_session.scalars(select(CloverLedger).where(CloverLedger.user_id == user.id))).all()
    assert [(row.kind, row.amount) for row in rows] == [("chat_spend", -clover.CHAT_TURN_COST)]


@pytest.mark.parametrize("surface", _SURFACES)
@pytest.mark.parametrize(
    ("with_persona", "expected"),
    [(True, _PERSONA_MESSAGE), (False, _DEFAULT_MESSAGE)],
    ids=["persona", "no-persona"],
)
async def test_policy_warning_mentions_persona_only_when_the_persona_section_was_rendered(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
    with_persona: bool,
    expected: str,
) -> None:
    user, events = await _run_policy_turn(
        db_client, db_session, monkeypatch, surface=surface, with_persona=with_persona
    )

    assert events == [{"type": "policyWarning", "message": expected}]
    await _assert_not_refunded(db_session, user)


@pytest.mark.parametrize("surface", _SURFACES)
async def test_policy_warning_keeps_default_message_when_the_active_set_has_no_persona_slot(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
) -> None:
    """캐시 TTL 창 — 프로필 값은 비어 있지 않지만 그 턴의 세트에 슬롯이 없어 섹션이
    들어가지 않았다. 값만 보고 판정하면 여기서 문구가 잘못 바뀐다(모듈 docstring의 판정 기준)."""
    user, events = await _run_policy_turn(
        db_client, db_session, monkeypatch, surface=surface, with_persona=True, stale_cache=True
    )

    assert events == [{"type": "policyWarning", "message": _DEFAULT_MESSAGE}]
    await _assert_not_refunded(db_session, user)
