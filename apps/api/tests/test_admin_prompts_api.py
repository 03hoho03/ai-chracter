"""어드민 프롬프트 API.

`admin/legal.py`의 SAVEPOINT/upsert 패턴을 그대로 따르므로 시나리오도 그쪽과 겹친다
(초안 upsert의 경쟁 처리, 게시의 SAVEPOINT+409).

라우트가 레인 스코프(`/admin/prompt-sets/{lane}/...`)로
바뀌었고, R-1~R-8 규칙도 레인별 표(`_EXPECTED_ROWS_BY_LANE` 등)로 쪼개졌다.
"게시가 실제로 성공하는지"를 보는 테스트는 이제 **실제 검증을 그대로 태운다** —
레인 스코프 초안(42/22/4행)이 그 레인의 표와 정확히 일치하므로 우회가 필요 없다.
R-1~R-7 규칙 자체를 직접 고정하는 테스트들은 story 레인의 실제 활성 세트(42행)를
baseline으로 쓴다(`legacy` 48행은 더 이상 어느 레인의 표와도 정확히 일치하지 않는다 —
새 레인별 표는 각각 story/character/publish_filter가 실제로 쓰는 부분집합이다).

마이그레이션 `b72c33c70240`(M2)이 story·character 레인에
`generation/user_persona` 행을 더한 **새 published 세트**를 만들고, 마이그레이션 `c328445d4c2d`가
같은 방식으로 채팅방 기억 행을 더한 세트를 또 만들고, 마이그레이션 `2519dde454e0`이 story 레인에만 미디어
북 칸 판정 행을 더한 세트를, 마이그레이션 `bd29dd69bc0f`가 publish_filter 레인에 미디어 북 칸 줄 행을 더한
세트를, 마이그레이션 `859b0fb86629`가 publish_filter 레인을 이미지 전용 문안으로 바꾼 세트를, 마이그레이션
`2417f5829bb1`이 story 레인에 상황 노트 행을 더한 세트를, 마이그레이션 `8e895c898730`이 두 레인에 사용자 이름 한 줄
행을 더한 세트를, 마이그레이션 `3bb2cc159b6d`가 두 레인에 소설화 채널 행을 더한 세트를 만든다. 그래서 테스트 DB의 Gemini
published는 레인별로 story v1·v2·v4·v6·v9·v10·v12, character v1·v3·v5·v11·v13, publish_filter v1·v7·v8이고, 활성은
story v12·character v13·publish_filter v8이다. 마이그레이션 `e6aa289fea62`가 Claude 세트 4개(story sonnet v14·opus v15,
character sonnet v16·opus v17)를 더하고, 소설 프롬프트 레인 마이그레이션이 `novel` 레인 세트 4개(gemini 옛 문안 v18·
새 문안 v19, sonnet v20, opus v21)를 더하고, 마이그레이션 `d9768bc0cfee`가 story 레인에 스탯 규칙 판정 행을 더한 Gemini
세트 v22를 만들어 story 활성이 v22가 되고, 노벨 텍스트 심사 레인 마이그레이션이 `novel_screen` 레인 Gemini 세트 v23을
심고, 판정 문안 체인 마이그레이션이 story·character 레인마다 판정·요약 행을 더한 Claude 세트 둘과 판정 전용(haiku) 세트
하나(story sonnet v24·opus v25·haiku v26, character sonnet v27·opus v28·haiku v29)를 심으므로 다음 게시 버전은 "30"부터다
(전 레인·전 모델 대상 자동 증가).
채팅 레인 Gemini 초안 응답은 얼린 소설화 행을 싣지 않는다(`_visible_section_count`).
섹션 수는 `_expected_section_count`로 코드 표에서 도출한다 — DB 행은 마이그레이션이
만드므로 동어반복이 아니다.
"""

import logging
import uuid
from string import Formatter
from typing import cast

import httpx
import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from redis.exceptions import RedisError

from api.admin import prompts as admin_prompts
from api.chat.prompt_builder import ALLOWED_PLACEHOLDERS, PromptLane, load_active_prompt_set, system_instruction_for
from api.chat.prompt_set_cache import get_cached_active_prompt_set, set_cached_active_prompt_set
from api.core.redis import redis_client
from api.db.models.moderation import AdminActionLog
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.story import StoryPromptTemplate
from api.llm.chat_models import ChatModelId, PromptSetModelId
from factories import _create_admin, _login_as, _login_as_admin, _make_user


async def _login_new_admin(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)


async def _assert_requires_admin_session(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    method: str,
    path: str,
    json: dict[str, object] | None = None,
) -> None:
    resp = await db_client.request(method.upper(), path, json=json)
    assert resp.status_code == 401

    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    # 세션이 아예 안 서도 admin 401은 나오므로, 먼저 "이
    # 유저로는 실제로 인증된다"를 고정해야 위 무세션 401과 구분되는 명제가 남는다(공허한 통과 방지).
    assert (await db_client.get("/me")).status_code == 200

    resp = await db_client.request(method.upper(), path, json=json)
    assert resp.status_code == 401


def _expected_section_count(lane: PromptLane) -> int:
    return sum(len(rows) for rows in admin_prompts._EXPECTED_ROWS_BY_LANE[lane].values())


_NOVELIZE_CHANNELS = {"novelize_boundary", "novelize_chapter", "novelize_revise"}


def _visible_section_count(lane: PromptLane) -> int:
    """채팅 레인 Gemini 초안 응답의 섹션 수 — 얼린 소설화 행은 화면에 싣지 않는다."""
    rows = admin_prompts._EXPECTED_ROWS_BY_LANE[lane]
    return sum(len(r) for channel, r in rows.items() if channel not in _NOVELIZE_CHANNELS)


async def _make_valid_draft(db_client: httpx.AsyncClient, lane: str, model: str = "gemini") -> dict[str, object]:
    """GET(초안 없으면 그 (레인, 모델)의 활성 세트 복제본)→PUT 왕복으로, 지금 시드와 바이트
    단위로 같은 내용의 진짜 초안 행을 만든다."""
    get_resp = await db_client.get(f"/admin/prompt-sets/{lane}/draft", params={"model": model})
    assert get_resp.status_code == 200
    cloned = get_resp.json()

    put_resp = await db_client.put(
        f"/admin/prompt-sets/{lane}/draft",
        params={"model": model},
        json={"labels": cloned["labels"], "sections": cloned["sections"]},
    )
    assert put_resp.status_code == 200
    body: dict[str, object] = put_resp.json()
    return body


async def _get_section(
    db_session: AsyncSession, draft_id: uuid.UUID, *, channel: str, slot: str, variant: str = ""
) -> PromptSection:
    section = await db_session.scalar(
        sa.select(PromptSection).where(
            PromptSection.prompt_set_id == draft_id,
            PromptSection.channel == channel,
            PromptSection.slot == slot,
            PromptSection.variant == variant,
        )
    )
    assert section is not None
    return section


def _select_active_id(lane: str) -> sa.Select[tuple[uuid.UUID]]:
    return (
        sa.select(PromptSet.id)
        .where(PromptSet.status == "published", PromptSet.lane == lane)
        .order_by(PromptSet.published_at.desc())
        .limit(1)
    )


def _select_legacy_id() -> sa.Select[tuple[uuid.UUID]]:
    """레인 분리 이전의 48행 통짜 세트(새 코드는 읽지 않지만 목록·복원 거부 테스트가
    이 행의 존재 자체를 고정한다)."""
    return sa.select(PromptSet.id).where(PromptSet.lane == "legacy", PromptSet.status == "published")


async def _story_prompt_set_and_sections(
    db_session: AsyncSession,
) -> tuple[PromptSet, list[PromptSection]]:
    """`_validate_prompt_draft_for_publish`가 레인별 표를 보게 된 뒤로는
    story 레인의 실제 활성 세트(42행)가 그 표와 정확히 일치하는 유일한 baseline이다
    (legacy 48행은 story/character/publish_filter 어느 표와도 더 이상 정확히 일치하지
    않는다). R-1~R-7 규칙 자체를 직접 고정하는 테스트들이 여기서 baseline을 가져온다."""
    story_id = await db_session.scalar(_select_active_id("story"))
    assert story_id is not None
    prompt_set = await db_session.get(PromptSet, story_id)
    assert prompt_set is not None
    sections = list(
        (
            await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == story_id))
        ).all()
    )
    assert len(sections) == _expected_section_count("story")
    return prompt_set, sections


def _find_section(sections: list[PromptSection], *, channel: str, slot: str, variant: str = "") -> PromptSection:
    for section in sections:
        if section.channel == channel and section.slot == slot and section.variant == variant:
            return section
    raise AssertionError(f"section not found: {channel}/{slot}/{variant!r}")


# ---- 인증 ---------------------------------------------------------------------

_ADMIN_SESSION_GUARD_CASES = [
    pytest.param("get", "/admin/prompt-sets", None, id="list"),
    pytest.param("get", "/admin/prompt-sets/story/draft", None, id="get-draft"),
    pytest.param("put", "/admin/prompt-sets/story/draft", {"labels": {}, "sections": []}, id="put-draft"),
    pytest.param("post", "/admin/prompt-sets/story/draft/preview", None, id="preview"),
    pytest.param("post", "/admin/prompt-sets/story/publish", {"note": "x"}, id="publish"),
    pytest.param("get", f"/admin/prompt-sets/{uuid.uuid4()}", None, id="get-by-id"),
    pytest.param("post", f"/admin/prompt-sets/{uuid.uuid4()}/restore", None, id="restore"),
]


@pytest.mark.parametrize(("method", "path", "json"), _ADMIN_SESSION_GUARD_CASES)
async def test_requires_admin_session(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    method: str,
    path: str,
    json: dict[str, object] | None,
) -> None:
    await _assert_requires_admin_session(db_client, db_session, method, path, json=json)


# ---- 초안 조회·저장 -------------------------------------------------------------


async def test_get_draft_with_no_draft_returns_active_set_clone(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _login_new_admin(db_client, db_session)

    resp = await db_client.get("/admin/prompt-sets/story/draft")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] is None
    assert body["labels"]["userLabel"] == "사용자"
    assert len(body["sections"]) == _visible_section_count("story")
    assert not {s["channel"] for s in body["sections"]} & _NOVELIZE_CHANNELS


async def test_draft_upsert_creates_new_draft_when_none_exists(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _login_new_admin(db_client, db_session)

    draft = await _make_valid_draft(db_client, "story")
    assert draft["id"] is not None

    drafts = (
        await db_session.scalars(sa.select(PromptSet).where(PromptSet.status == "draft"))
    ).all()
    assert len(drafts) == 1
    assert str(drafts[0].id) == draft["id"]
    assert drafts[0].lane == "story"


async def test_draft_upsert_replaces_sections_entirely(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """섹션 전체 교체다 — 이전 내용 중 이번 PUT에 없는 슬롯은 사라져야 한다. 얼린 소설화 행만은 서버가 다시 채운다."""
    await _login_new_admin(db_client, db_session)
    first = await _make_valid_draft(db_client, "story")
    draft_id = uuid.UUID(str(first["id"]))

    labels = first["labels"]
    single_section = [
        {
            "channel": "system",
            "scope": "both",
            "slot": "priority_tail",
            "variant": "",
            "body": "[교체] 우선순위 문장",
            "conditional": False,
            "order": 7,
        }
    ]
    resp = await db_client.put(
        "/admin/prompt-sets/story/draft", json={"labels": labels, "sections": single_section}
    )
    assert resp.status_code == 200

    remaining = (
        await db_session.scalars(
            sa.select(PromptSection).where(PromptSection.prompt_set_id == draft_id)
        )
    ).all()
    chat_rows = [s for s in remaining if s.channel not in _NOVELIZE_CHANNELS]
    assert len(chat_rows) == 1
    assert chat_rows[0].slot == "priority_tail"
    assert chat_rows[0].body == "[교체] 우선순위 문장"
    assert len(remaining) - 1 == sum(len(r) for r in admin_prompts._FROZEN_NOVELIZE_ROWS.values())


async def test_draft_upsert_concurrent_insert_race_falls_back_to_update_not_500(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`admin/legal.py`의 동시성 테스트와 같은 흉내 방식 — `_get_draft`의 첫 호출만
    `None`을 반환하게 해 "다른 요청이 먼저 초안을 커밋한" 순간을 재현한다.

    패치를 걸기 **전에** 클론용 GET을 먼저 해 둔다 — `GET .../draft`도 내부에서
    `_get_draft`를 부르므로, 패치 이후에 GET까지 하면 그 GET이 "첫 호출"을 미리
    소비해 버려 정작 `PUT`(아래에서 재현하려는 경쟁의 당사자)은 두 번째 호출부터
    시작해 경쟁 분기를 영영 타지 않는다."""
    await _login_new_admin(db_client, db_session)
    get_resp = await db_client.get("/admin/prompt-sets/story/draft")
    cloned = get_resp.json()

    real_get_draft = admin_prompts._get_draft
    call_count = 0

    async def _get_draft_missing_once(db: AsyncSession, lane: PromptLane, model: ChatModelId) -> PromptSet | None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return None
        return await real_get_draft(db, lane, model)

    monkeypatch.setattr(admin_prompts, "_get_draft", _get_draft_missing_once)

    # "동시에 먼저 커밋된 다른 요청의 초안" 역할 — 같은 레인이어야 유니크 인덱스가 걸린다.
    raced_in = PromptSet(
        id=uuid.uuid4(),
        version=None,
        status="draft",
        lane="story",
        note="",
        user_label="경쟁-사용자",
        story_assistant_label="경쟁-진행자",
        story_example_label="경쟁-서술자",
        character_assistant_label="경쟁-캐릭터",
    )
    db_session.add(raced_in)
    await db_session.commit()

    resp = await db_client.put(
        "/admin/prompt-sets/story/draft", json={"labels": cloned["labels"], "sections": cloned["sections"]}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(raced_in.id)
    assert body["labels"]["userLabel"] == cloned["labels"]["userLabel"]

    drafts = (await db_session.scalars(sa.select(PromptSet).where(PromptSet.status == "draft"))).all()
    assert len(drafts) == 1


_DUPLICATE_SECTIONS = [
    {
        "channel": "system", "scope": "both", "slot": "priority_tail", "variant": "",
        "body": "A", "conditional": False, "order": 7,
    },
    {
        "channel": "system", "scope": "both", "slot": "priority_tail", "variant": "",
        "body": "B", "conditional": False, "order": 7,
    },
]


async def test_draft_upsert_rejects_duplicate_section_keys_when_no_draft_exists(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """초안이 없는 상태에서 요청 본문 자체에 같은
    `(channel, scope, slot, variant)`가 두 번 들어오면 500이 아니라 422를 받아야 한다.
    이 사전 검사가 없을 때는 SAVEPOINT 롤백이 방금 만든 draft 행까지 되감아
    `assert draft is not None`이 깨지며 500이 났다(고치기 전 실패로 직접 확인함)."""
    await _login_new_admin(db_client, db_session)
    get_resp = await db_client.get("/admin/prompt-sets/story/draft")
    labels = get_resp.json()["labels"]

    resp = await db_client.put(
        "/admin/prompt-sets/story/draft", json={"labels": labels, "sections": _DUPLICATE_SECTIONS}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["rule"] == "duplicate-section-key"

    drafts = (await db_session.scalars(sa.select(PromptSet).where(PromptSet.status == "draft"))).all()
    assert len(drafts) == 0  # 실패한 시도가 부분적인 draft 행을 남기지 않는다


async def test_draft_upsert_rejects_duplicate_section_keys_when_draft_already_exists(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """같은 결함, 초안이 이미 있는 경우 — `except` 블록의 재삽입이 `db.commit()` 시점에
    감싸이지 않은 `IntegrityError`로 그대로 크래시했다(고치기 전 실패로 직접 확인함)."""
    await _login_new_admin(db_client, db_session)
    existing = await _make_valid_draft(db_client, "story")

    resp = await db_client.put(
        "/admin/prompt-sets/story/draft",
        json={"labels": existing["labels"], "sections": _DUPLICATE_SECTIONS},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["rule"] == "duplicate-section-key"

    # 실패한 시도가 기존 초안의 섹션을 건드리지 않고 그대로 남긴다.
    remaining = (
        await db_session.scalars(
            sa.select(PromptSection).where(
                PromptSection.prompt_set_id == uuid.UUID(str(existing["id"]))
            )
        )
    ).all()
    assert len(remaining) == _expected_section_count("story")


# ---- 레인 격리 -------------------------------------------------------------------


async def test_replace_draft_content_integrity_error_recovery_only_touches_own_lane(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_replace_draft_content`의 `except IntegrityError` 복구 경로가 **자기
    레인 초안만** 건드리는지. character 레인 초안이 이미 있는 상태에서 story 레인 PUT이
    경쟁(IntegrityError) 경로를 타도 character 초안의 섹션(14행)은 그대로여야 한다 —
    `except` 블록의 `_get_draft`가 레인 필터를 빠뜨리면(또는 `assert draft.lane == lane`이
    없으면) 이 복구가 엉뚱한 레인의 초안을 덮어쓸 수 있다."""
    await _login_new_admin(db_client, db_session)
    character_draft = await _make_valid_draft(db_client, "character")
    character_id = uuid.UUID(str(character_draft["id"]))

    get_resp = await db_client.get("/admin/prompt-sets/story/draft")
    cloned = get_resp.json()

    real_get_draft = admin_prompts._get_draft
    call_count = 0

    async def _get_draft_missing_once(db: AsyncSession, lane: PromptLane, model: ChatModelId) -> PromptSet | None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return None
        return await real_get_draft(db, lane, model)

    monkeypatch.setattr(admin_prompts, "_get_draft", _get_draft_missing_once)

    raced_in = PromptSet(
        id=uuid.uuid4(),
        version=None,
        status="draft",
        lane="story",
        note="",
        user_label="경쟁-사용자",
        story_assistant_label="경쟁-진행자",
        story_example_label="경쟁-서술자",
        character_assistant_label="경쟁-캐릭터",
    )
    db_session.add(raced_in)
    await db_session.commit()

    resp = await db_client.put(
        "/admin/prompt-sets/story/draft", json={"labels": cloned["labels"], "sections": cloned["sections"]}
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == str(raced_in.id)

    remaining_character_sections = (
        await db_session.scalars(
            sa.select(PromptSection).where(PromptSection.prompt_set_id == character_id)
        )
    ).all()
    assert len(remaining_character_sections) == _expected_section_count("character")


# ---- 목록·상세 -----------------------------------------------------------------


async def test_list_returns_metadata_only_and_marks_active(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _login_new_admin(db_client, db_session)
    await _make_valid_draft(db_client, "story")

    resp = await db_client.get("/admin/prompt-sets")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert "sections" not in items[0]

    published = [item for item in items if item["status"] == "published"]
    draft = [item for item in items if item["status"] == "draft"]
    # Gemini: story v1·v2·v4·v6·v9·v10·v12, character v1·v3·v5·v11·v13, publish_filter v1·v7·v8 (모듈 docstring — 세트를
    # 만든 여덟 마이그레이션이 v2·v3, v4·v5, v6, v7, v8, v9, v10·v11, v12·v13을 만든다). Claude: v14~v17. 소설: v18~v21.
    # 스탯 규칙 판정: story v22. 노벨 텍스트 심사: v23. 판정 문안 체인: v24~v29.
    assert len(published) == 31
    assert len(draft) == 1
    active = [item for item in published if item["isActive"]]
    # (레인, 모델)마다 하나 — Claude 세트는 원본 Gemini 세트보다 published_at 이 과거지만 모델이 달라 각자 활성이다.
    assert {(item["lane"], item["model"], item["version"]) for item in active} == {
        ("story", "gemini", "22"),
        ("character", "gemini", "13"),
        ("publish_filter", "gemini", "8"),
        ("story", "sonnet", "24"),
        ("story", "opus", "25"),
        ("story", "haiku", "26"),
        ("character", "sonnet", "27"),
        ("character", "opus", "28"),
        ("character", "haiku", "29"),
        ("novel", "gemini", "19"),
        ("novel", "sonnet", "20"),
        ("novel", "opus", "21"),
        ("novel_screen", "gemini", "23"),
    }
    # 레인별 마지막 마이그레이션 이전 세트 열은 비활성이다(소설 레인은 옛 문안을 옮긴 첫 판).
    assert {(item["lane"], item["version"]) for item in published if not item["isActive"]} == {
        ("story", "1"),
        ("story", "2"),
        ("story", "4"),
        ("story", "6"),
        ("story", "9"),
        ("story", "10"),
        ("story", "12"),
        ("character", "1"),
        ("character", "3"),
        ("character", "5"),
        ("character", "11"),
        ("publish_filter", "1"),
        ("publish_filter", "7"),
        ("novel", "18"),
        ("story", "14"),
        ("story", "15"),
        ("character", "16"),
        ("character", "17"),
    }
    assert draft[0]["isActive"] is False
    assert {item["version"] for item in published} == {str(n) for n in range(1, 30)}


async def test_get_by_id_returns_full_sections(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _login_new_admin(db_client, db_session)
    active_id = await db_session.scalar(_select_active_id("story"))

    resp = await db_client.get(f"/admin/prompt-sets/{active_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sections"]) == _expected_section_count("story")
    assert body["version"] == "22"  # story 활성은 스탯 규칙 판정 채널 행을 더한 마이그레이션의 세트다
    assert body["lane"] == "story"


async def test_get_by_id_missing_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _login_new_admin(db_client, db_session)
    resp = await db_client.get(f"/admin/prompt-sets/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_get_by_id_legacy_lane_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`lane='legacy'`는 새 코드가 읽지 않는 격리 버킷이다. 응답의 `lane` 필드가
    `PromptLane`(legacy 제외)이라 legacy 행은 애초에 표현할 수 없어 404로 취급한다."""
    await _login_new_admin(db_client, db_session)
    legacy_id = await db_session.scalar(_select_legacy_id())

    resp = await db_client.get(f"/admin/prompt-sets/{legacy_id}")
    assert resp.status_code == 404


# ---- 미리보기 -------------------------------------------------------------------


async def test_preview_reuses_the_real_renderer(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """별도 조립 코드를 만들지 않았다는 증거 — 미리보기가 낸 `system·스토리·basic` 텍스트가
    `system_instruction_for()`를 직접 호출한 결과와 바이트 단위로 같아야 한다.

    `_build_preview_items`가 레인별로 갈라진 뒤로는 story 레인 미리보기에 `publish_filter` 항목이 없다
    (publish_filter 레인 전용이다). `image_judgment` 는 두 레인에 다 있다 — story 는 미디어 북 칸 판정,
    character 는 상황별 이미지 판정이다. 소설화 항목은 `novel` 레인 미리보기에만 있다(채팅 레인 행은 얼린 옛 문안)."""
    await _login_new_admin(db_client, db_session)
    active_id = await db_session.scalar(_select_active_id("story"))
    sections = (
        await db_session.scalars(
            sa.select(PromptSection).where(PromptSection.prompt_set_id == active_id)
        )
    ).all()
    expected = system_instruction_for(list(sections), is_story_chat=True, template=StoryPromptTemplate.BASIC)

    resp = await db_client.post("/admin/prompt-sets/story/draft/preview")
    assert resp.status_code == 200
    items = resp.json()["items"]
    story_system_basic = next(i for i in items if i["channel"] == "system" and "basic" in i["label"])
    assert story_system_basic["text"] == expected

    channels = {item["channel"] for item in items}
    assert channels == {
        "system",
        "generation",
        "stat_rule_judgment",
        "ending_judgment",
        "memory_summary",
        "image_judgment",
    }


async def test_preview_uses_the_draft_when_one_exists(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """초안이 있으면 활성 세트가 아니라 초안 내용으로 미리보기한다."""
    await _login_new_admin(db_client, db_session)
    draft = await _make_valid_draft(db_client, "story")
    draft_id = uuid.UUID(str(draft["id"]))
    tail = await _get_section(db_session, draft_id, channel="system", slot="priority_tail")
    tail.body = "[초안 전용] 우선순위 문장"
    await db_session.commit()

    resp = await db_client.post("/admin/prompt-sets/story/draft/preview")
    assert resp.status_code == 200
    story_system = next(
        i for i in resp.json()["items"] if i["channel"] == "system" and "스토리" in i["label"]
    )
    assert "[초안 전용] 우선순위 문장" in story_system["text"]


async def test_novel_preview_without_chapter_rows_shows_a_notice_instead_of_failing(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """화 생성 행이 빠진 소설 초안(게시는 슬롯 검사가 막는다)도 미리보기 전체가 500 으로 죽지 않고, 화 생성 항목만 안내로
    바뀌고 나머지 항목은 그대로 렌더된다."""
    await _login_new_admin(db_client, db_session)
    draft = await _make_valid_draft(db_client, "novel")
    await db_session.execute(
        sa.delete(PromptSection).where(
            PromptSection.prompt_set_id == uuid.UUID(str(draft["id"])),
            PromptSection.channel == "novelize_chapter",
        )
    )
    await db_session.commit()

    resp = await db_client.post("/admin/prompt-sets/novel/draft/preview")
    assert resp.status_code == 200
    items = resp.json()["items"]
    chapter = [i for i in items if i["channel"] == "novelize_chapter"]
    others = [i for i in items if i["channel"] != "novelize_chapter"]
    assert [i["label"] for i in chapter] == ["novelize_chapter · 스토리", "novelize_chapter · 캐릭터"]
    assert all(i["text"].startswith("이 초안으로는 이 채널을 미리 볼 수 없습니다") for i in chapter)
    assert all("필수 슬롯이 없다" in i["text"] for i in chapter)
    assert len(others) == 4 and not any(i["text"].startswith("이 초안으로는") for i in others)


@pytest.mark.parametrize(
    ("lane", "expected_count"),
    [
        pytest.param("story", 10, id="story"),
        pytest.param("character", 4, id="character"),
        pytest.param("publish_filter", 2, id="publish_filter"),
        pytest.param("novel", 6, id="novel"),
    ],
)
async def test_preview_item_count_per_lane(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: str, expected_count: int
) -> None:
    """리뷰가 찾은 공백 — `_character_preview_items`/`_publish_filter_preview_items`가
    story 레인 미리보기 테스트에만 가려져 미커버였다. R-7의 `StopIteration` → 500이
    `publish_filter` 레인에서만 터지던 결함이었던 선례를 생각하면 같은 부류가 숨어 있을 수
    있어 레인 전부 200 + 항목 수(story 10 / character 4 / publish_filter 2 / novel 6 — 소설은 경계 제안·화 생성·문단
    수정 × 스토리·캐릭터 원작)를 직접 고정한다."""
    await _login_new_admin(db_client, db_session)

    resp = await db_client.post(f"/admin/prompt-sets/{lane}/draft/preview")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == expected_count


@pytest.mark.parametrize("lane", [pytest.param("story", id="story"), pytest.param("character", id="character")])
async def test_preview_renders_the_persona_section_only_in_generation_items(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: str
) -> None:
    """generation 미리보기는 샘플 프로필을 채운다. 비워 두면
    conditional 드롭으로 섹션이 사라져 운영자가 `user_persona` 문안이 어떻게 렌더되는지
    볼 수 없다. 판정 채널 항목에는 들어가지 않는다. 머리글은 확정 문안의 첫 줄."""
    await _login_new_admin(db_client, db_session)

    resp = await db_client.post(f"/admin/prompt-sets/{lane}/draft/preview")
    assert resp.status_code == 200
    items = resp.json()["items"]
    generation = [item for item in items if item["channel"] == "generation"]
    others = [item for item in items if item["channel"] != "generation"]
    assert generation and others
    assert all("[사용자 정보]" in item["text"] for item in generation)
    assert all("[사용자 정보]" not in item["text"] for item in others)


_SAMPLE_USER_NAME_LINE = "대화 속 사용자의 이름: [샘플] 하늘"
# 레인별로 이름 한 줄을 받는 항목. 나머지 항목(system)은 그 줄이 0줄이어야 한다. 판정 전용 세트(haiku)는 생성 항목 없이
# 판정·요약 항목만 있다.
_NAME_LINE_LABELS = {
    "story": {
        "generation · 스토리 · basic",
        "generation · 스토리 · custom",
        "stat_rule_judgment",
        "ending_judgment",
        "image_judgment",
        "memory_summary",
    },
    "character": {"generation · 캐릭터", "image_judgment", "memory_summary"},
}


@pytest.mark.parametrize("model", [pytest.param(None, id="gemini"), "sonnet", "opus", "haiku"])
@pytest.mark.parametrize("lane", ["story", "character"])
async def test_preview_shows_the_sample_user_name_line_in_every_item_that_takes_a_name(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: str, model: str | None
) -> None:
    """미리보기는 이름 한 줄 섹션을 고정 샘플 이름으로 채워 운영자가 그 문안을 생성·판정·요약 채널 모두에서 보게 한다.
    실채팅에서 이 줄이 비는 경우(생성 채널은 늘, 판정·요약은 프로필이 없을 때)와 달리 미리보기는 비우지 않는다 —
    비우면 conditional 드롭으로 섹션이 사라진다. 샘플 프로필 이름도 같은 글자라 이름 부분 문자열이 아니라 줄 전체를 센다."""
    await _login_new_admin(db_client, db_session)

    resp = await db_client.post(f"/admin/prompt-sets/{lane}/draft/preview", params={"model": model} if model else {})
    assert resp.status_code == 200
    items = resp.json()["items"]
    expected = {
        label for label in _NAME_LINE_LABELS[lane] if model != "haiku" or not label.startswith("generation")
    }
    assert {item["label"]: item["text"].count(_SAMPLE_USER_NAME_LINE) for item in items} == {
        item["label"]: (1 if item["label"] in expected else 0) for item in items
    }
    assert {item["label"] for item in items} >= expected
    generation = [item for item in items if item["channel"] == "generation"]
    assert all("[사용자 이름]" in item["text"] for item in generation)
    assert bool(generation) is (model != "haiku")


def test_preview_sample_names_replace_author_macros_with_the_sample_names() -> None:
    """샘플 글에는 `{{user}}` 가 없어 미리보기 출력으로는 치환 이름을 볼 수 없다 — 샘플 이름 묶음을 직접 확인한다."""
    assert admin_prompts._SAMPLE_STORY_NAMES.expand("{{user}}") == "[샘플] 하늘"
    assert admin_prompts._SAMPLE_CHARACTER_NAMES.expand("{{user}}") == "[샘플] 하늘"
    assert admin_prompts._SAMPLE_CHARACTER_NAMES.expand("{{char}}") == "[샘플] 캐릭터"
    assert admin_prompts._SAMPLE_STORY_NAMES.expand("{{char}}") == "{{char}}"


# ---- 게시 — happy path ----------------------------------------------------------


async def test_publish_without_draft_returns_400(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _login_new_admin(db_client, db_session)
    resp = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "메모"})
    assert resp.status_code == 400


async def test_publish_valid_unmodified_draft_succeeds_with_next_version(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _login_new_admin(db_client, db_session)
    await _make_valid_draft(db_client, "story")

    resp = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "정기 점검 후 재게시"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == "30"
    assert body["status"] == "published"
    assert body["lane"] == "story"
    assert body["note"] == "정기 점검 후 재게시"
    assert len(body["sections"]) == _expected_section_count("story")

    # 게시 후에도 초안 행은 남는다(legal과 같다).
    drafts = (await db_session.scalars(sa.select(PromptSet).where(PromptSet.status == "draft"))).all()
    assert len(drafts) == 1

    logs = (
        await db_session.scalars(
            sa.select(AdminActionLog).where(AdminActionLog.action_type == "prompt-set-publish")
        )
    ).all()
    assert len(logs) == 1
    assert logs[0].reason_text == "정기 점검 후 재게시"
    assert logs[0].target_user_id is None
    assert logs[0].target_content_id is None
    assert logs[0].target_chat_room_id is None


async def test_publish_assigns_sequential_integer_versions(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _login_new_admin(db_client, db_session)
    await _make_valid_draft(db_client, "story")
    first = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "v30"})
    assert first.json()["version"] == "30"

    await _make_valid_draft(db_client, "story")
    second = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "v31"})
    assert second.json()["version"] == "31"


async def test_next_version_is_global_monotonic_not_per_lane(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`_next_published_version`에 레인 필터가 없다("안 넣는 것"이 결정이다).
    세트를 만든 마이그레이션들이 story v2·v4·v6·v9·v10·v12·character v3·v5·v11·v13·publish_filter v7·v8을 만든 테스트
    DB(+ Claude 세트 v14~v17, 소설 세트 v18~v21, 스탯 규칙 판정 story 세트 v22, 노벨 텍스트 심사 세트 v23, 판정 문안 체인
    세트 v24~v29)에서, story가 v30·v31을 게시한 뒤 character 게시가 v32를 받아야 한다(레인별
    독립 증가라면 character의 다음 게시는 v18일 것이다) —
    이 테스트는 그 레인 필터의 **부재**를 고정한다."""
    await _login_new_admin(db_client, db_session)

    await _make_valid_draft(db_client, "story")
    first = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "story v30"})
    assert first.json()["version"] == "30"

    await _make_valid_draft(db_client, "story")
    second = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "story v31"})
    assert second.json()["version"] == "31"

    await _make_valid_draft(db_client, "character")
    third = await db_client.post("/admin/prompt-sets/character/publish", json={"note": "character v32"})
    assert third.json()["version"] == "32"


async def test_publishing_one_lane_does_not_affect_other_lanes_active_set(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """레인 독립성: story 게시 뒤 character 활성본의 id·섹션이 그대로다."""
    await _login_new_admin(db_client, db_session)

    character_active_id_before = await db_session.scalar(_select_active_id("character"))
    assert character_active_id_before is not None
    character_sections_before = {
        (s.channel, s.scope, s.slot, s.variant, s.body)
        for s in (
            await db_session.scalars(
                sa.select(PromptSection).where(PromptSection.prompt_set_id == character_active_id_before)
            )
        ).all()
    }

    await _make_valid_draft(db_client, "story")
    resp = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "story 게시"})
    assert resp.status_code == 200

    character_active_id_after = await db_session.scalar(_select_active_id("character"))
    assert character_active_id_after == character_active_id_before

    character_sections_after = {
        (s.channel, s.scope, s.slot, s.variant, s.body)
        for s in (
            await db_session.scalars(
                sa.select(PromptSection).where(PromptSection.prompt_set_id == character_active_id_after)
            )
        ).all()
    }
    assert character_sections_after == character_sections_before


async def test_publish_invalidates_the_active_prompt_set_cache(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _login_new_admin(db_client, db_session)
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story")
    await set_cached_active_prompt_set("story", prompt_set, sections, model="gemini")
    assert await get_cached_active_prompt_set("story", model="gemini") is not None

    await _make_valid_draft(db_client, "story")
    resp = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "캐시 무효화 확인"})
    assert resp.status_code == 200

    assert await get_cached_active_prompt_set("story", model="gemini") is None


async def test_publish_succeeds_even_when_cache_invalidation_fails(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """DB 커밋(진짜 소스)이 이미 성공했으면 캐시 무효화 실패로 게시 자체를 500으로
    만들지 않는다 — `admin/prompts.py`의 결정과 근거 주석 참고.

    이 흡수는 그대로 두되, `redis` 태그로 Bugsink
    이벤트에도 승격돼야 한다."""

    async def _raise_redis_error(*args: object, **kwargs: object) -> None:
        raise RedisError("connection refused")

    monkeypatch.setattr(redis_client, "delete", _raise_redis_error)

    captured: list[str] = []
    monkeypatch.setattr(
        admin_prompts,
        "capture_dependency_failure",
        lambda *_a, dependency, **_k: captured.append(dependency),
    )

    await _login_new_admin(db_client, db_session)
    await _make_valid_draft(db_client, "story")

    with caplog.at_level(logging.WARNING):
        resp = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "캐시 실패해도 성공"})

    assert resp.status_code == 200
    assert resp.json()["version"] == "30"
    assert any(record.levelno >= logging.WARNING for record in caplog.records)
    assert captured == ["redis"]


async def test_publish_version_conflict_returns_409(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_next_published_version`을 이미 게시된 버전("1")으로 고정해, 부분 유니크 인덱스
    (`ix_prompt_sets_lane_version_published`)에 실제로 걸리게 만든다."""

    async def _stale_version(_db: AsyncSession) -> str:
        return "1"

    monkeypatch.setattr(admin_prompts, "_next_published_version", _stale_version)

    await _login_new_admin(db_client, db_session)
    await _make_valid_draft(db_client, "story")

    resp = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "충돌"})
    assert resp.status_code == 409

    published = (
        await db_session.scalars(
            sa.select(PromptSet).where(
                PromptSet.status == "published", PromptSet.lane == "story", PromptSet.model == "gemini"
            )
        )
    ).all()
    # story Gemini published는 v1(a69cbd40dec8)·v2(b72c33c70240)·v4(c328445d4c2d)·v6(2519dde454e0)·v9(2417f5829bb1)·
    # v10(8e895c898730)·v12(3bb2cc159b6d)·v22(d9768bc0cfee) 여덟이다 — 실패한 시도가 아홉째를 남기지 않는다.
    assert len(published) == 8


# ---- 롤백 (restore) -------------------------------------------------------------


async def test_restore_clones_old_version_into_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _login_new_admin(db_client, db_session)
    seed_id = uuid.UUID(str(await db_session.scalar(_select_active_id("story"))))
    seed_tail = await _get_section(db_session, seed_id, channel="system", slot="priority_tail")
    original_body = seed_tail.body

    draft = await _make_valid_draft(db_client, "story")
    draft_id = uuid.UUID(str(draft["id"]))
    draft_tail = await _get_section(db_session, draft_id, channel="system", slot="priority_tail")
    draft_tail.body = "[망가뜨림] 우선순위"
    await db_session.commit()
    bad_publish = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "잘못된 게시"})
    # 문안 교체 자체는 R-1~R-8 어느 규칙도 어기지 않는다(플레이스홀더도 없고 order도 그대로) —
    # 그래서 실제 검증을 태워도 통과한다. 그 "나쁜" 내용을 롤백이 되돌리는지가 이 테스트의 핵심이다.
    assert bad_publish.status_code == 200

    restore_resp = await db_client.post(f"/admin/prompt-sets/{seed_id}/restore")
    assert restore_resp.status_code == 200
    restored = restore_resp.json()
    restored_tail = next(s for s in restored["sections"] if s["slot"] == "priority_tail")
    assert restored_tail["body"] == original_body

    republish = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "롤백"})
    assert republish.status_code == 200
    republish_tail = next(s for s in republish.json()["sections"] if s["slot"] == "priority_tail")
    assert republish_tail["body"] == original_body


@pytest.mark.parametrize("lane", ["story", "character"])
async def test_restoring_persona_slot_set_then_publishing_passes_r1(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: PromptLane
) -> None:
    """활성 세트(슬롯 마이그레이션들이 만든 세트 — `user_persona`·기억 행 포함)를 초안으로
    복원해 게시하면 R-1을 통과한다. 코드 표(`_EXPECTED_ROWS_BY_LANE`)와 DB가 같이 갔다는
    왕복 확인이다(R-2 — 한쪽만 있으면 "누락"이나 "잉여"로 게시가 전부 막힌다)."""
    await _login_new_admin(db_client, db_session)
    active_id = await db_session.scalar(_select_active_id(lane))

    restore_resp = await db_client.post(f"/admin/prompt-sets/{active_id}/restore")
    assert restore_resp.status_code == 200
    assert any(s["slot"] == "user_persona" for s in restore_resp.json()["sections"])
    assert any(s["channel"] == "memory_summary" for s in restore_resp.json()["sections"])

    publish_resp = await db_client.post(f"/admin/prompt-sets/{lane}/publish", json={"note": "복원 게시"})
    assert publish_resp.status_code == 200, publish_resp.json()


async def test_restore_missing_id_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _login_new_admin(db_client, db_session)
    resp = await db_client.post(f"/admin/prompt-sets/{uuid.uuid4()}/restore")
    assert resp.status_code == 404


async def test_restore_rejects_legacy_lane_with_422(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`lane='legacy'`(레인 분리 이전) 세트는 복원 대상이 아니다."""
    await _login_new_admin(db_client, db_session)
    legacy_id = await db_session.scalar(_select_legacy_id())
    assert legacy_id is not None

    resp = await db_client.post(f"/admin/prompt-sets/{legacy_id}/restore")
    assert resp.status_code == 422
    assert resp.json()["detail"]["rule"] == "legacy-lane"

    drafts = (await db_session.scalars(sa.select(PromptSet).where(PromptSet.status == "draft"))).all()
    assert len(drafts) == 0  # 거부된 시도가 초안 행을 만들지 않는다


# ---- 목록에서 legacy 제외 -----------------------------------------------------------


async def test_list_excludes_legacy_and_marks_exactly_one_active_per_lane_and_model(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`GET /admin/prompt-sets` 응답에 legacy 행이 없고 `isActive`가
    정확히 13개((레인, 모델)마다 하나씩 — 채팅·심사 Gemini 4 + 채팅 Claude 4 + 판정 전용 2 + 소설 3)다."""
    await _login_new_admin(db_client, db_session)

    resp = await db_client.get("/admin/prompt-sets")
    assert resp.status_code == 200
    items = resp.json()["items"]

    lanes = {item["lane"] for item in items}
    assert "legacy" not in lanes
    assert lanes == {"story", "character", "publish_filter", "novel", "novel_screen"}

    active_items = [item for item in items if item["isActive"]]
    assert len(active_items) == 13
    assert sorted((item["lane"], item["model"]) for item in active_items) == [
        ("character", "gemini"),
        ("character", "haiku"),
        ("character", "opus"),
        ("character", "sonnet"),
        ("novel", "gemini"),
        ("novel", "opus"),
        ("novel", "sonnet"),
        ("novel_screen", "gemini"),
        ("publish_filter", "gemini"),
        ("story", "gemini"),
        ("story", "haiku"),
        ("story", "opus"),
        ("story", "sonnet"),
    ]


# ---- 게시 검증 R-1~R-8 — `_validate_prompt_draft_for_publish` 직접 호출 -------------
#
# R-1~R-7 규칙 자체(무엇이 위반인지)를 직접 고정한다. story 레인의 실제 활성 세트(42행)가
# `_EXPECTED_ROWS_BY_LANE["story"]`와 정확히 일치하는 baseline이라, 슬롯 하나를 빼거나
# body/label/order 하나를 망가뜨리면 그 규칙만 걸린다. R-8은 별도 절(아래)에서 HTTP
# 라우트를 거쳐 고정한다 — R-6과 실제로 다른 답을 내는 입력이 핵심이라 레인 표 안의
# 진짜 섹션 두 개(scope만 다른)를 써야 한다.


async def test_publish_rejects_missing_slot_r1(db_session: AsyncSession) -> None:
    prompt_set, sections = await _story_prompt_set_and_sections(db_session)
    tail = _find_section(sections, channel="system", slot="priority_tail")
    sections = [s for s in sections if s is not tail]

    with pytest.raises(HTTPException) as exc_info:
        admin_prompts._validate_prompt_draft_for_publish(prompt_set, sections, lane="story")
    assert cast(dict[str, object], exc_info.value.detail)["rule"] == "R-1"


async def test_publish_rejects_missing_template_variant_r2(db_session: AsyncSession) -> None:
    prompt_set, sections = await _story_prompt_set_and_sections(db_session)
    custom_variant = _find_section(sections, channel="system", slot="template_instruction", variant="custom")
    sections = [s for s in sections if s is not custom_variant]

    with pytest.raises(HTTPException) as exc_info:
        admin_prompts._validate_prompt_draft_for_publish(prompt_set, sections, lane="story")
    assert cast(dict[str, object], exc_info.value.detail)["rule"] == "R-2"


async def test_publish_rejects_missing_base_content_custom_variant_r2(db_session: AsyncSession) -> None:
    """`base_content`의 `custom` variant가 빠지면 CUSTOM
    템플릿 스토리도 `variant=""` 행(`{setting_text}`)으로 폴백하는데, CUSTOM 스토리는
    `setting_text`가 정상적으로 비어 있어 `conditional=True`인 이 섹션이 통째로
    드롭된다 — "다른 문안으로 대체"가 아니라 작품 설정(세계관/커스텀 프롬프트) 전체
    소실이다."""
    prompt_set, sections = await _story_prompt_set_and_sections(db_session)
    custom_base_content = _find_section(sections, channel="generation", slot="base_content", variant="custom")
    sections = [s for s in sections if s is not custom_base_content]

    with pytest.raises(HTTPException) as exc_info:
        admin_prompts._validate_prompt_draft_for_publish(prompt_set, sections, lane="story")
    assert cast(dict[str, object], exc_info.value.detail)["rule"] == "R-2"


async def test_publish_rejects_blank_body_r3(db_session: AsyncSession) -> None:
    prompt_set, sections = await _story_prompt_set_and_sections(db_session)
    prologue = _find_section(sections, channel="generation", slot="prologue")
    prologue.body = "   "

    with pytest.raises(HTTPException) as exc_info:
        admin_prompts._validate_prompt_draft_for_publish(prompt_set, sections, lane="story")
    assert cast(dict[str, object], exc_info.value.detail)["rule"] == "R-3"


async def test_publish_rejects_disallowed_placeholder_r4(db_session: AsyncSession) -> None:
    prompt_set, sections = await _story_prompt_set_and_sections(db_session)
    prologue = _find_section(sections, channel="generation", slot="prologue")
    prologue.body = "[시작 상황]\n{prologue} {not_a_real_placeholder}"

    with pytest.raises(HTTPException) as exc_info:
        admin_prompts._validate_prompt_draft_for_publish(prompt_set, sections, lane="story")
    assert cast(dict[str, object], exc_info.value.detail)["rule"] == "R-4"


async def test_publish_rejects_unbalanced_braces_r4(db_session: AsyncSession) -> None:
    prompt_set, sections = await _story_prompt_set_and_sections(db_session)
    prologue = _find_section(sections, channel="generation", slot="prologue")
    prologue.body = "[시작 상황]\n{prologue"

    with pytest.raises(HTTPException) as exc_info:
        admin_prompts._validate_prompt_draft_for_publish(prompt_set, sections, lane="story")
    assert cast(dict[str, object], exc_info.value.detail)["rule"] == "R-4"


async def test_publish_rejects_blank_label_r5(db_session: AsyncSession) -> None:
    prompt_set, sections = await _story_prompt_set_and_sections(db_session)
    prompt_set.user_label = "  "

    with pytest.raises(HTTPException) as exc_info:
        admin_prompts._validate_prompt_draft_for_publish(prompt_set, sections, lane="story")
    assert cast(dict[str, object], exc_info.value.detail)["rule"] == "R-5"


async def test_publish_rejects_label_with_colon_r5(db_session: AsyncSession) -> None:
    prompt_set, sections = await _story_prompt_set_and_sections(db_session)
    prompt_set.user_label = "사용자:"

    with pytest.raises(HTTPException) as exc_info:
        admin_prompts._validate_prompt_draft_for_publish(prompt_set, sections, lane="story")
    assert cast(dict[str, object], exc_info.value.detail)["rule"] == "R-5"


async def test_publish_rejects_duplicate_order_in_same_group_r6(db_session: AsyncSession) -> None:
    prompt_set, sections = await _story_prompt_set_and_sections(db_session)
    rule_open_turn = _find_section(sections, channel="system", slot="rule_open_turn")
    rule_user_agency = _find_section(sections, channel="system", slot="rule_user_agency")
    rule_open_turn.order = rule_user_agency.order

    with pytest.raises(HTTPException) as exc_info:
        admin_prompts._validate_prompt_draft_for_publish(prompt_set, sections, lane="story")
    assert cast(dict[str, object], exc_info.value.detail)["rule"] == "R-6"


async def test_publish_rejects_priority_tail_not_last_r7(db_session: AsyncSession) -> None:
    prompt_set, sections = await _story_prompt_set_and_sections(db_session)
    tail = _find_section(sections, channel="system", slot="priority_tail")
    tail.order = 1

    with pytest.raises(HTTPException) as exc_info:
        admin_prompts._validate_prompt_draft_for_publish(prompt_set, sections, lane="story")
    assert cast(dict[str, object], exc_info.value.detail)["rule"] == "R-7"


# ---- R-8 + 레인별 R-2/R-5/R-7 회귀 가드 ------------------------------------------


async def test_publish_rejects_order_collision_across_scopes_r8_not_r6(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """R-8 절에서 가장 중요한 테스트다. R-6의 그룹
    키에 `scope`가 들어 있어 `(system, both, '', order)`와 `(system, story, '', order)`를
    다른 그룹으로 본다 — 그래서 두 행의 order를 같게 만들어도 R-6은 통과한다. 하지만 story
    scope로 렌더링할 때는 둘 다 선택돼 order가 실제로 충돌한다 — R-8만 그걸 잡아야 한다.
    단언은 반드시 `detail["rule"] == "R-8"`이어야 한다 — 422만 보면 R-6이 잡았을 때와
    구분되지 않아 R-8이 죽은 코드여도 초록이 된다."""
    await _login_new_admin(db_client, db_session)
    draft = await _make_valid_draft(db_client, "story")
    draft_id = uuid.UUID(str(draft["id"]))
    sections = list(
        (
            await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == draft_id))
        ).all()
    )

    both_scope_section = _find_section(sections, channel="system", slot="rule_response_format")
    story_scope_section = _find_section(sections, channel="system", slot="self_definition")
    # (system, both, '', order=N) + (system, story, '', order=N) — R-6은 scope가 달라 그룹이
    # 갈리므로 통과하지만, story scope 렌더 선택에는 둘 다 들어가 order가 충돌한다.
    story_scope_section.order = both_scope_section.order
    await db_session.commit()

    resp = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "R-8 회귀"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["rule"] == "R-8"


@pytest.mark.parametrize("lane", ["character", "publish_filter"])
async def test_publish_succeeds_for_lanes_without_required_variant_slots_r2(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: str
) -> None:
    """R-2(variant 전종 필수)는 story 레인 전용이 됐다
    (`_REQUIRED_VARIANT_SLOTS_BY_LANE`가 character·publish_filter에는 빈 dict다). 레인
    필터를 안 쪼개면 이 두 레인은 그 슬롯이 아예 없어 영원히 R-2로 거부된다 — 주석이
    아니라 테스트로 "공허 통과"를 고정한다."""
    await _login_new_admin(db_client, db_session)
    await _make_valid_draft(db_client, lane)

    resp = await db_client.post(f"/admin/prompt-sets/{lane}/publish", json={"note": "R-2 공허 통과"})
    assert resp.status_code == 200


async def test_publish_filter_lane_publish_succeeds_not_500_r7(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`publish_filter` 레인엔 `system`
    채널이 아예 없다. 기본값 없는 `next()`는 여기서 `StopIteration` → 500이었다. 기본값
    있는 `next()` + `other_orders` 가드가 있으면 500이 아니라 정상 게시가 통과한다."""
    await _login_new_admin(db_client, db_session)
    await _make_valid_draft(db_client, "publish_filter")

    resp = await db_client.post("/admin/prompt-sets/publish_filter/publish", json={"note": "R-7 회귀 가드"})
    assert resp.status_code == 200


async def test_publish_filter_lane_allows_blank_labels_r5(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`publish_filter` 레인은 화자 라벨을 하나도 안 쓴다 — 발행 심사에는 대화 줄이 없고 이미지 목록만
    실린다(`_LABEL_FIELDS_BY_LANE["publish_filter"]`가 빈 튜플). 라벨이 전부 공백이어도 통과해야 한다."""
    await _login_new_admin(db_client, db_session)
    draft = await _make_valid_draft(db_client, "publish_filter")
    labels = dict(cast(dict[str, object], draft["labels"]))
    for key in ("userLabel", "characterAssistantLabel", "storyAssistantLabel", "storyExampleLabel"):
        labels[key] = "   "
    put_resp = await db_client.put(
        "/admin/prompt-sets/publish_filter/draft", json={"labels": labels, "sections": draft["sections"]}
    )
    assert put_resp.status_code == 200

    resp = await db_client.post("/admin/prompt-sets/publish_filter/publish", json={"note": "라벨 공백 통과"})
    assert resp.status_code == 200


async def test_story_lane_rejects_blank_story_assistant_label_r5(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """위 테스트의 짝 — story 레인은 `storyAssistantLabel`을 실제로 쓰므로
    (`_LABEL_FIELDS_BY_LANE["story"]`) 같은 입력이 422여야 한다."""
    await _login_new_admin(db_client, db_session)
    draft = await _make_valid_draft(db_client, "story")
    labels = dict(cast(dict[str, object], draft["labels"]))
    labels["storyAssistantLabel"] = "   "
    put_resp = await db_client.put(
        "/admin/prompt-sets/story/draft", json={"labels": labels, "sections": draft["sections"]}
    )
    assert put_resp.status_code == 200

    resp = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "라벨 공백 거부"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["rule"] == "R-5"


# ---- 허용 플레이스홀더 단일 소스 — 세 레인 활성 세트 --------------------------------


@pytest.mark.parametrize("lane", ["story", "character", "publish_filter"])
async def test_seed_sections_use_only_allowed_placeholders(db_session: AsyncSession, lane: PromptLane) -> None:
    """R-4의 허용 목록(`ALLOWED_PLACEHOLDERS`)이 지금 시드된 레인별 활성 세트 전부를
    통과하는지 고정한다 — 렌더러 호출부의 `values` 딕셔너리에서 뽑아낸 목록이므로, 실제로
    렌더되는 문안을 스스로 거부하면 안 된다. legacy 세트는 어떤 코드도 렌더하지 않아 대상이 아니다
    (그 안의 발행 심사 행은 지금 슬롯 목록에 없다)."""
    _, sections = await load_active_prompt_set(db_session, lane=lane)

    for section in sections:
        fields = [name for _, name, _, _ in Formatter().parse(section.body) if name is not None]
        allowed = ALLOWED_PLACEHOLDERS[(section.channel, section.slot)]
        unknown = {name for name in fields if name not in allowed}
        assert not unknown, f"{section.channel}/{section.slot}: {unknown}"


# ---- 모델별 세트 — `?model=` ------------------------------------------------------------
#
# story·character 레인은 (레인, 모델)마다 독립 체인이다. Claude 세트(sonnet·opus)는 생성 채널(system·generation)과 그 레인의
# 판정·요약 채널을, 판정 전용 세트(haiku)는 판정·요약 채널만 갖는다 — 마이그레이션이 Gemini 활성 세트에서 복사해 심었다.

_JUDGMENT_CHANNELS: dict[str, set[str]] = {
    "story": {"stat_rule_judgment", "ending_judgment", "image_judgment", "memory_summary"},
    "character": {"image_judgment", "memory_summary"},
}
_GENERATION_CHANNELS = {"system", "generation"}


def _claude_channels(lane: str) -> set[str]:
    return _GENERATION_CHANNELS | _JUDGMENT_CHANNELS[lane]


def _section_count(lane: PromptLane, channels: set[str]) -> int:
    rows = admin_prompts._EXPECTED_ROWS_BY_LANE[lane]
    return sum(len(rows[channel]) for channel in channels)


_CHAT_LANES = [pytest.param("story", id="story"), pytest.param("character", id="character")]


@pytest.mark.parametrize("lane", _CHAT_LANES)
async def test_claude_draft_without_a_draft_returns_that_models_active_set(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: PromptLane
) -> None:
    """초안이 없으면 그 (레인, 모델)의 활성 세트 사본 — 같은 레인의 Gemini 세트가 아니다(채널 수가 다르다)."""
    await _login_new_admin(db_client, db_session)
    sonnet_set, sonnet_sections = await load_active_prompt_set(db_session, lane=lane, model="sonnet")

    resp = await db_client.get(f"/admin/prompt-sets/{lane}/draft", params={"model": "sonnet"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] is None
    assert body["model"] == "sonnet"
    assert {s["channel"] for s in body["sections"]} == _claude_channels(lane)
    assert len(body["sections"]) == len(sonnet_sections) == _section_count(lane, _claude_channels(lane))
    assert body["labels"]["userLabel"] == sonnet_set.user_label


async def test_draft_without_model_query_is_the_gemini_chain(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """모델을 모르는 옛 어드민 화면은 쿼리 없이 부른다 — 그대로 Gemini 세트를 편집해야 한다."""
    await _login_new_admin(db_client, db_session)

    resp = await db_client.get("/admin/prompt-sets/story/draft")

    assert resp.json()["model"] == "gemini"
    assert len(resp.json()["sections"]) == _visible_section_count("story")


async def test_claude_and_gemini_drafts_are_separate_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """초안은 (레인, 모델)마다 하나 — Sonnet 초안을 저장해도 Gemini 쪽은 여전히 초안이 없고, Opus 초안도 따로 생긴다."""
    await _login_new_admin(db_client, db_session)

    sonnet = await _make_valid_draft(db_client, "story", "sonnet")
    opus = await _make_valid_draft(db_client, "story", "opus")

    assert sonnet["id"] != opus["id"]
    gemini = await db_client.get("/admin/prompt-sets/story/draft")
    assert gemini.json()["id"] is None
    drafts = (await db_session.scalars(sa.select(PromptSet).where(PromptSet.status == "draft"))).all()
    assert sorted((d.lane, d.model) for d in drafts) == [("story", "opus"), ("story", "sonnet")]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        pytest.param("GET", "/admin/prompt-sets/publish_filter/draft", id="get-draft"),
        pytest.param("PUT", "/admin/prompt-sets/publish_filter/draft", id="put-draft"),
        pytest.param("POST", "/admin/prompt-sets/publish_filter/draft/preview", id="preview"),
        pytest.param("POST", "/admin/prompt-sets/publish_filter/publish", id="publish"),
    ],
)
async def test_publish_filter_lane_rejects_a_non_gemini_model(
    db_client: httpx.AsyncClient, db_session: AsyncSession, method: str, path: str
) -> None:
    await _login_new_admin(db_client, db_session)
    body: dict[str, object] | None = None
    if method == "PUT":
        body = {"labels": {"userLabel": "a", "storyAssistantLabel": "b", "storyExampleLabel": "c",
                           "characterAssistantLabel": "d"}, "sections": []}
    elif path.endswith("/publish"):
        body = {"note": ""}

    resp = await db_client.request(method, path, params={"model": "sonnet"}, json=body)

    assert resp.status_code == 422
    assert resp.json()["detail"]["rule"] == "lane-model"
    drafts = (await db_session.scalars(sa.select(PromptSet).where(PromptSet.status == "draft"))).all()
    assert drafts == []


@pytest.mark.parametrize("lane", _CHAT_LANES)
async def test_claude_set_passes_publish_validation_only_as_a_claude_set(
    db_session: AsyncSession, lane: PromptLane
) -> None:
    """R-1 의 기대 집합이 모델로 갈린다 — 마이그레이션이 심은 Claude 세트는 Claude 로는 통과하고, 같은 내용을 Gemini
    세트로 게시하려 하면 옛 스탯 판정·소설화 채널이 빠졌다고, 판정 전용 세트로 게시하려 하면 생성 채널이 잉여라고 R-1 이다."""
    prompt_set, sections = await load_active_prompt_set(db_session, lane=lane, model="opus")

    admin_prompts._validate_prompt_draft_for_publish(prompt_set, sections, lane=lane, model="opus")
    others: tuple[PromptSetModelId, ...] = ("gemini", "haiku")
    for other in others:
        with pytest.raises(HTTPException) as exc_info:
            admin_prompts._validate_prompt_draft_for_publish(prompt_set, sections, lane=lane, model=other)
        assert cast(dict[str, str], exc_info.value.detail)["rule"] == "R-1"


@pytest.mark.parametrize("lane", _CHAT_LANES)
async def test_judgment_only_set_passes_publish_validation_only_as_a_judgment_only_set(
    db_session: AsyncSession, lane: PromptLane
) -> None:
    """판정 전용 세트에는 생성 채널이 없다 — Claude 로 게시하면 누락, 거꾸로 Gemini 세트를 판정 전용으로 게시하면 잉여다."""
    haiku_set, haiku_sections = await load_active_prompt_set(db_session, lane=lane, model="haiku")
    gemini_set, gemini_sections = await load_active_prompt_set(db_session, lane=lane)

    admin_prompts._validate_prompt_draft_for_publish(haiku_set, haiku_sections, lane=lane, model="haiku")
    cases: list[tuple[PromptSet, list[PromptSection], PromptSetModelId]] = [
        (haiku_set, haiku_sections, "sonnet"),
        (gemini_set, gemini_sections, "haiku"),
    ]
    for prompt_set, sections, model in cases:
        with pytest.raises(HTTPException) as exc_info:
            admin_prompts._validate_prompt_draft_for_publish(prompt_set, sections, lane=lane, model=model)
        assert cast(dict[str, str], exc_info.value.detail)["rule"] == "R-1"


async def test_claude_draft_with_the_retired_stat_judgment_channel_is_rejected_r1(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """옛 스탯 판정 채널(`stat_judgment`)은 Gemini 체인에만 남아 있다 — Claude 세트에 섞이면 아무 호출도 읽지 않는 잉여다."""
    await _login_new_admin(db_client, db_session)
    _, gemini_sections = await load_active_prompt_set(db_session, lane="story")
    sonnet = (await db_client.get("/admin/prompt-sets/story/draft", params={"model": "sonnet"})).json()
    stat_rows = [
        {"channel": s.channel, "scope": s.scope, "slot": s.slot, "variant": s.variant, "body": s.body,
         "conditional": s.conditional, "order": s.order}
        for s in gemini_sections
        if s.channel == "stat_judgment"
    ]
    assert stat_rows
    put = await db_client.put(
        "/admin/prompt-sets/story/draft",
        params={"model": "sonnet"},
        json={"labels": sonnet["labels"], "sections": [*sonnet["sections"], *stat_rows]},
    )
    assert put.status_code == 200

    resp = await db_client.post("/admin/prompt-sets/story/publish", params={"model": "sonnet"}, json={"note": ""})

    assert resp.status_code == 422
    assert resp.json()["detail"]["rule"] == "R-1"


async def test_claude_publish_becomes_that_models_active_set_and_invalidates_only_its_key(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _login_new_admin(db_client, db_session)
    gemini_before, gemini_sections = await load_active_prompt_set(db_session, lane="story")
    opus_before, _ = await load_active_prompt_set(db_session, lane="story", model="opus")
    sonnet_before, sonnet_sections = await load_active_prompt_set(db_session, lane="story", model="sonnet")
    await set_cached_active_prompt_set("story", gemini_before, gemini_sections, model="gemini")
    await set_cached_active_prompt_set("story", sonnet_before, sonnet_sections, model="sonnet")
    await _make_valid_draft(db_client, "story", "sonnet")

    resp = await db_client.post("/admin/prompt-sets/story/publish", params={"model": "sonnet"}, json={"note": "s"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == "sonnet"
    assert body["version"] == "30"
    assert len(body["sections"]) == _section_count("story", _claude_channels("story"))
    # 얼린 소설화 행은 채팅 Gemini 체인에만 있다 — Claude 채팅 체인 게시에 끼워 넣지 않는다.
    assert {s["channel"] for s in body["sections"]} == _claude_channels("story")
    db_session.expire_all()
    sonnet_after, _ = await load_active_prompt_set(db_session, lane="story", model="sonnet")
    assert str(sonnet_after.id) == body["id"]
    assert (await load_active_prompt_set(db_session, lane="story"))[0].id == gemini_before.id
    assert (await load_active_prompt_set(db_session, lane="story", model="opus"))[0].id == opus_before.id
    assert await get_cached_active_prompt_set("story", model="sonnet") is None
    assert await get_cached_active_prompt_set("story", model="gemini") is not None


async def test_restore_of_a_claude_set_goes_into_that_models_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """복원은 요청에서 모델을 받지 않는다 — 원본 세트의 모델 체인 초안으로 들어간다."""
    await _login_new_admin(db_client, db_session)
    opus_set, opus_sections = await load_active_prompt_set(db_session, lane="character", model="opus")

    resp = await db_client.post(f"/admin/prompt-sets/{opus_set.id}/restore")

    assert resp.status_code == 200
    assert resp.json()["model"] == "opus"
    assert len(resp.json()["sections"]) == len(opus_sections)
    drafts = (await db_session.scalars(sa.select(PromptSet).where(PromptSet.status == "draft"))).all()
    assert [(d.lane, d.model) for d in drafts] == [("character", "opus")]

    detail = await db_client.get(f"/admin/prompt-sets/{opus_set.id}")
    assert detail.json()["model"] == "opus"


@pytest.mark.parametrize("lane", _CHAT_LANES)
async def test_claude_preview_matches_the_gemini_preview_item_for_item(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: str
) -> None:
    """Claude 세트는 생성 문안과 판정·요약 문안을 모두 갖는다 — 미리보기도 그 항목을 다 내고, 시드가 Gemini 세트의 사본이라
    Gemini 미리보기와 라벨·순서·글이 같다."""
    await _login_new_admin(db_client, db_session)

    claude = await db_client.post(f"/admin/prompt-sets/{lane}/draft/preview", params={"model": "sonnet"})
    gemini = await db_client.post(f"/admin/prompt-sets/{lane}/draft/preview")

    assert claude.status_code == 200
    claude_items = claude.json()["items"]
    assert {item["channel"] for item in claude_items} == _claude_channels(lane)
    assert claude_items == gemini.json()["items"]


async def test_claude_preview_of_a_draft_restored_from_before_the_judgment_rows_shows_generation_only(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """판정·요약 행을 심기 전의 Claude 버전도 복원은 된다(게시는 누락으로 막힌다). 그 초안의 미리보기는 없는 채널을 렌더하다
    실패하지 않고 있는 생성 항목만 낸다."""
    await _login_new_admin(db_client, db_session)
    old_set = await db_session.scalar(
        sa.select(PromptSet)
        .where(PromptSet.lane == "story", PromptSet.model == "sonnet", PromptSet.status == "published")
        .order_by(PromptSet.published_at.asc())
        .limit(1)
    )
    assert old_set is not None
    restored = await db_client.post(f"/admin/prompt-sets/{old_set.id}/restore")
    assert {s["channel"] for s in restored.json()["sections"]} == _GENERATION_CHANNELS

    resp = await db_client.post("/admin/prompt-sets/story/draft/preview", params={"model": "sonnet"})

    assert resp.status_code == 200
    assert {item["channel"] for item in resp.json()["items"]} == _GENERATION_CHANNELS


# ---- 판정 전용 체인(haiku) ---------------------------------------------------------------------


@pytest.mark.parametrize("lane", _CHAT_LANES)
async def test_judgment_only_draft_without_a_draft_is_its_judgment_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: PromptLane
) -> None:
    await _login_new_admin(db_client, db_session)
    haiku_set, haiku_sections = await load_active_prompt_set(db_session, lane=lane, model="haiku")

    resp = await db_client.get(f"/admin/prompt-sets/{lane}/draft", params={"model": "haiku"})

    assert resp.status_code == 200
    body = resp.json()
    assert (body["id"], body["model"]) == (None, "haiku")
    assert {s["channel"] for s in body["sections"]} == _JUDGMENT_CHANNELS[lane]
    assert len(body["sections"]) == len(haiku_sections) == _section_count(lane, _JUDGMENT_CHANNELS[lane])
    assert body["labels"]["userLabel"] == haiku_set.user_label


@pytest.mark.parametrize("lane", _CHAT_LANES)
async def test_judgment_only_preview_has_only_the_judgment_items_of_the_gemini_preview(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: str
) -> None:
    """판정 전용 세트에는 생성 행이 없다 — 생성 항목을 만들면 렌더할 행이 없다. 판정·요약 항목은 Gemini 미리보기와 같다."""
    await _login_new_admin(db_client, db_session)

    haiku = await db_client.post(f"/admin/prompt-sets/{lane}/draft/preview", params={"model": "haiku"})
    gemini = await db_client.post(f"/admin/prompt-sets/{lane}/draft/preview")

    assert haiku.status_code == 200
    assert haiku.json()["items"] == [
        item for item in gemini.json()["items"] if item["channel"] in _JUDGMENT_CHANNELS[lane]
    ]
    assert {item["channel"] for item in haiku.json()["items"]} == _JUDGMENT_CHANNELS[lane]


@pytest.mark.parametrize("lane", _CHAT_LANES)
async def test_judgment_only_draft_publishes_and_becomes_that_chains_active_set(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: PromptLane
) -> None:
    """story 판정 전용 세트에는 variant 를 반드시 갖춰야 하는 생성 슬롯이 없다 — 그 검사를 레인 기준으로 하면 영원히 게시할
    수 없다. 게시는 그 체인 캐시 키만 지운다."""
    await _login_new_admin(db_client, db_session)
    gemini_before, gemini_sections = await load_active_prompt_set(db_session, lane=lane)
    haiku_before, haiku_sections = await load_active_prompt_set(db_session, lane=lane, model="haiku")
    await set_cached_active_prompt_set(lane, gemini_before, gemini_sections, model="gemini")
    await set_cached_active_prompt_set(lane, haiku_before, haiku_sections, model="haiku")
    await _make_valid_draft(db_client, lane, "haiku")

    resp = await db_client.post(f"/admin/prompt-sets/{lane}/publish", params={"model": "haiku"}, json={"note": "h"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["model"] == "haiku"
    assert {s["channel"] for s in body["sections"]} == _JUDGMENT_CHANNELS[lane]
    db_session.expire_all()
    assert str((await load_active_prompt_set(db_session, lane=lane, model="haiku"))[0].id) == body["id"]
    assert (await load_active_prompt_set(db_session, lane=lane))[0].id == gemini_before.id
    assert await get_cached_active_prompt_set(lane, model="haiku") is None
    assert await get_cached_active_prompt_set(lane, model="gemini") is not None


async def test_judgment_only_versions_are_listed_fetched_and_restored(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """채팅 모델 목록 밖의 id 라도 판정 전용 세트는 버전 이력에 보이고, 열리고, 그 체인 초안으로 복원된다."""
    await _login_new_admin(db_client, db_session)
    haiku_set, haiku_sections = await load_active_prompt_set(db_session, lane="story", model="haiku")

    listed = await db_client.get("/admin/prompt-sets")
    detail = await db_client.get(f"/admin/prompt-sets/{haiku_set.id}")
    restored = await db_client.post(f"/admin/prompt-sets/{haiku_set.id}/restore")

    haiku_items = [item for item in listed.json()["items"] if item["model"] == "haiku"]
    assert {(item["lane"], item["isActive"]) for item in haiku_items} == {("story", True), ("character", True)}
    assert detail.status_code == 200
    assert (detail.json()["model"], len(detail.json()["sections"])) == ("haiku", len(haiku_sections))
    assert restored.status_code == 200
    assert restored.json()["model"] == "haiku"
    drafts = (await db_session.scalars(sa.select(PromptSet).where(PromptSet.status == "draft"))).all()
    assert [(d.lane, d.model) for d in drafts] == [("story", "haiku")]


@pytest.mark.parametrize("lane", ["novel", "publish_filter", "novel_screen"])
async def test_judgment_only_model_is_rejected_outside_the_chat_lanes(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: str
) -> None:
    """판정 전용 체인은 채팅 판정·요약을 위한 것이라 스토리·캐릭터 레인에만 있다."""
    await _login_new_admin(db_client, db_session)

    resp = await db_client.get(f"/admin/prompt-sets/{lane}/draft", params={"model": "haiku"})

    assert resp.status_code == 422
    assert resp.json()["detail"]["rule"] == "lane-model"


# ---- 소설 레인과 채팅 레인의 얼린 소설 행 ---------------------------------------------------
#
# 소설 문안은 `novel` 레인((novel, 모델) 체인 셋)에서만 고친다. 채팅 레인 Gemini 체인의 소설화 행은 옛 이미지가 읽는 옛
# 문안이라 얼려 둔다 — 화면에 싣지 않고, 저장·복원·게시 때 서버가 직전 게시본의 값을 넣는다.


def _rows(sections: list[PromptSection]) -> set[tuple[str, str, str, str, str, bool, int]]:
    return {(s.channel, s.scope, s.slot, s.variant, s.body, s.conditional, s.order) for s in sections}


def _frozen(sections: list[PromptSection]) -> set[tuple[str, str, str, str, str, bool, int]]:
    return {row for row in _rows(sections) if row[0] in _NOVELIZE_CHANNELS}


@pytest.mark.parametrize(
    ("model", "channels"),
    [
        pytest.param("gemini", _NOVELIZE_CHANNELS, id="gemini"),
        pytest.param("sonnet", {"novelize_chapter"}, id="sonnet"),
        pytest.param("opus", {"novelize_chapter"}, id="opus"),
    ],
)
async def test_novel_draft_opens_for_every_model_chain(
    db_client: httpx.AsyncClient, db_session: AsyncSession, model: ChatModelId, channels: set[str]
) -> None:
    """소설 탭은 세 모델 탭을 다 그린다 — 체인이 하나라도 비어 있으면 초안 조회가 500 이다. Claude 체인은 화 생성만 그
    체인을 읽어 그 채널만 있다."""
    await _login_new_admin(db_client, db_session)

    resp = await db_client.get("/admin/prompt-sets/novel/draft", params={"model": model})

    assert resp.status_code == 200
    assert {s["channel"] for s in resp.json()["sections"]} == channels


async def test_novel_sonnet_publish_passes_with_only_the_chapter_channel_and_rejects_others_r1(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """Claude 세트의 R-1 기대 집합은 레인마다 다르다 — 채팅 레인 집합(system·generation)을 소설 레인에 쓰면 화 생성만 가진
    소설 Claude 체인은 영원히 게시할 수 없다. 반대로 다른 채널이 섞이면 아무 호출도 읽지 않는 잉여다."""
    await _login_new_admin(db_client, db_session)
    await _make_valid_draft(db_client, "novel", "sonnet")

    ok = await db_client.post("/admin/prompt-sets/novel/publish", params={"model": "sonnet"}, json={"note": "n"})
    assert ok.status_code == 200, ok.text
    assert {s["channel"] for s in ok.json()["sections"]} == {"novelize_chapter"}
    db_session.expire_all()
    assert str((await load_active_prompt_set(db_session, lane="novel", model="sonnet"))[0].id) == ok.json()["id"]

    _, gemini_sections = await load_active_prompt_set(db_session, lane="novel")
    sonnet = (await db_client.get("/admin/prompt-sets/novel/draft", params={"model": "sonnet"})).json()
    boundary_rows = [
        {"channel": s.channel, "scope": s.scope, "slot": s.slot, "variant": s.variant, "body": s.body,
         "conditional": s.conditional, "order": s.order}
        for s in gemini_sections
        if s.channel == "novelize_boundary"
    ]
    put = await db_client.put(
        "/admin/prompt-sets/novel/draft",
        params={"model": "sonnet"},
        json={"labels": sonnet["labels"], "sections": [*sonnet["sections"], *boundary_rows]},
    )
    assert put.status_code == 200
    mixed = await db_client.post("/admin/prompt-sets/novel/publish", params={"model": "sonnet"}, json={"note": ""})
    assert mixed.status_code == 422
    assert mixed.json()["detail"]["rule"] == "R-1"


async def test_novel_publish_leaves_the_chat_sets_alone(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """소설 문안을 게시해도 채팅 세트 버전은 바뀌지 않는다 — 소설을 고치려고 채팅 문안을 다시 게시하던 결합을 끊은 것이다."""
    await _login_new_admin(db_client, db_session)
    story_before = (await load_active_prompt_set(db_session, lane="story"))[0].id
    character_before = (await load_active_prompt_set(db_session, lane="character"))[0].id
    await _make_valid_draft(db_client, "novel")

    resp = await db_client.post("/admin/prompt-sets/novel/publish", json={"note": "소설"})

    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    assert str((await load_active_prompt_set(db_session, lane="novel"))[0].id) == resp.json()["id"]
    assert (await load_active_prompt_set(db_session, lane="story"))[0].id == story_before
    assert (await load_active_prompt_set(db_session, lane="character"))[0].id == character_before


async def test_chat_draft_put_with_changed_novel_rows_keeps_and_publishes_the_frozen_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """배포 전부터 열린 편집 탭은 소설화 행을 보낸다. 그 행을 고쳐 보내도 저장·게시되는 값은 직전 게시본의 얼린 값이다."""
    await _login_new_admin(db_client, db_session)
    _, active_sections = await load_active_prompt_set(db_session, lane="story")
    frozen = _frozen(active_sections)
    shown = (await db_client.get("/admin/prompt-sets/story/draft")).json()
    tampered = [
        {"channel": s.channel, "scope": s.scope, "slot": s.slot, "variant": s.variant, "body": f"[바꿈] {s.body}",
         "conditional": s.conditional, "order": s.order}
        for s in active_sections
        if s.channel in _NOVELIZE_CHANNELS
    ]

    put = await db_client.put(
        "/admin/prompt-sets/story/draft",
        json={"labels": shown["labels"], "sections": [*shown["sections"], *tampered]},
    )
    assert put.status_code == 200
    assert not {s["channel"] for s in put.json()["sections"]} & _NOVELIZE_CHANNELS
    stored = await _sections_of_set(db_session, uuid.UUID(put.json()["id"]))
    assert _frozen(stored) == frozen

    published = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "채팅만"})
    assert published.status_code == 200, published.text
    assert _frozen(await _sections_of_set(db_session, uuid.UUID(published.json()["id"]))) == frozen


async def test_restoring_a_set_from_before_the_novel_rows_publishes_with_the_frozen_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """소설화 행이 없던 옛 버전(character v11)을 복원해도 게시 슬롯 검사가 "누락"으로 막지 않고, 얼린 값이 그대로 실린다.
    character 레인으로 보는 것은 story 레인의 소설화 이전 버전이 그 뒤에 더한 스탯 규칙 판정 채널이 없어 그 채널 "누락"으로
    막히기 때문이다(그 리비전이 받아들인 제약) — 얼린 행과 무관한 이유로 실패한다."""
    await _login_new_admin(db_client, db_session)
    _, active_sections = await load_active_prompt_set(db_session, lane="character")
    frozen = _frozen(active_sections)
    old_id = await db_session.scalar(
        sa.select(PromptSet.id).where(
            PromptSet.lane == "character", PromptSet.status == "published", PromptSet.version == "11"
        )
    )
    assert old_id is not None
    assert not _frozen(await _sections_of_set(db_session, old_id))

    restored = await db_client.post(f"/admin/prompt-sets/{old_id}/restore")
    assert restored.status_code == 200
    published = await db_client.post("/admin/prompt-sets/character/publish", json={"note": "되돌림"})

    assert published.status_code == 200, published.text
    assert _frozen(await _sections_of_set(db_session, uuid.UUID(published.json()["id"]))) == frozen


async def test_a_draft_saved_before_the_freeze_publishes_the_frozen_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """얼림 규칙 전에 저장된 초안(운영에는 채팅 레인 초안이 있다)의 소설화 행이 달라도, 게시하는 값은 직전 게시본의
    얼린 값이다 — 저장 경로를 거치지 않은 초안도 게시 때 한 번 더 갈아 끼운다."""
    await _login_new_admin(db_client, db_session)
    _, active_sections = await load_active_prompt_set(db_session, lane="story")
    frozen = _frozen(active_sections)
    draft = await _make_valid_draft(db_client, "story")
    await db_session.execute(
        sa.update(PromptSection)
        .where(
            PromptSection.prompt_set_id == uuid.UUID(str(draft["id"])),
            PromptSection.channel.in_(_NOVELIZE_CHANNELS),
        )
        .values(body="[옛 초안] 다른 문안")
    )
    await db_session.commit()

    published = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "옛 초안"})

    assert published.status_code == 200, published.text
    assert _frozen(await _sections_of_set(db_session, uuid.UUID(published.json()["id"]))) == frozen


async def test_novel_preview_reads_labels_and_the_rating_rule_from_the_chat_gemini_set(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """소설 미리보기는 실호출과 같은 세트로 렌더한다 — 원문 줄 라벨과 등급 규칙은 원작 종류의 채팅 Gemini 세트에서 온다.
    Claude 체인은 화 생성 항목만이다."""
    await _login_new_admin(db_client, db_session)
    story_set, story_sections = await load_active_prompt_set(db_session, lane="story")
    rule = next(s.body for s in story_sections if s.channel == "system" and s.slot == "rule_rating")

    gemini = (await db_client.post("/admin/prompt-sets/novel/draft/preview")).json()["items"]
    opus = (await db_client.post("/admin/prompt-sets/novel/draft/preview", params={"model": "opus"})).json()["items"]

    story_chapter = next(i for i in gemini if i["label"] == "novelize_chapter · 스토리")
    assert rule in story_chapter["text"]
    assert f"[턴 1] {story_set.story_assistant_label}: [샘플] 왔어?" in story_chapter["text"]
    assert "[이번 묶음]" in story_chapter["text"] and "[인물 메모]" in story_chapter["text"]
    assert [i["label"] for i in opus] == ["novelize_chapter · 스토리", "novelize_chapter · 캐릭터"]


async def _sections_of_set(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    return list(
        (
            await db_session.scalars(
                sa.select(PromptSection)
                .where(PromptSection.prompt_set_id == set_id)
                .execution_options(populate_existing=True)
            )
        ).all()
    )


async def test_novel_screen_lane_publishes_its_seed_and_previews_with_sample_text(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """노벨 텍스트 심사 레인은 시드 그대로 게시 검증을 통과하고, 미리보기는 지시문 뒤에 샘플 글을 심사할 글 자리에 싣는다.
    심사는 모델을 고르지 않아 Claude 체인은 422 다."""
    await _login_new_admin(db_client, db_session)
    await _make_valid_draft(db_client, "novel_screen")

    preview = await db_client.post("/admin/prompt-sets/novel_screen/draft/preview")
    published = await db_client.post("/admin/prompt-sets/novel_screen/publish", json={"note": "재게시"})
    claude = await db_client.get("/admin/prompt-sets/novel_screen/draft", params={"model": "sonnet"})

    assert preview.status_code == 200
    (item,) = preview.json()["items"]
    assert item["channel"] == "novel_screen"
    assert "[판정 방법]" in item["text"] and "=== chapter_body: 본문 ===\n[샘플] 첫 문단이다." in item["text"]
    assert (published.status_code, published.json()["version"]) == (200, "30")
    assert (claude.status_code, claude.json()["detail"]["rule"]) == (422, "lane-model")
