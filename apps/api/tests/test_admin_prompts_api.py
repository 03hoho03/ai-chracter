"""prompt-db-goal-prompt.md §9 (4단계) — 어드민 프롬프트 API.

`admin/legal.py`의 SAVEPOINT/upsert 패턴을 그대로 따르므로 시나리오도 그쪽과 겹친다
(초안 upsert의 경쟁 처리, 게시의 SAVEPOINT+409).

prompt-scope-techspec.md(C4) — 라우트가 레인 스코프(`/admin/prompt-sets/{lane}/...`)로
바뀌었다. R-1~R-7(§9-2) 규칙 **내용**의 레인별 분할(`_EXPECTED_ROWS_BY_LANE` 등)은 C5
소관이라 이 파일에서는 손대지 않는다 — 그래서 여기서는 아직 레인별로 쪼개지지 않은
`_validate_prompt_draft_for_publish`를 **레인 스코프 라우트를 거치지 않고 직접 호출**해
R-1~R-7 각각을 계속 고정한다(`lane='legacy'` 세트가 옛 48행 구조를 그대로 들고 있어
그 함수가 여전히 기대하는 입력 모양과 일치한다). 그 밖의 "게시가 실제로 성공하는지"를
보는 테스트(버전 채번·캐시 무효화·롤백)는 `_validate_prompt_draft_for_publish`를
`monkeypatch`로 우회한다 — 레인 스코프 초안(26/13/16행)은 아직 레인을 모르는 그 함수
기준으로는 항상 R-1에 걸리기 때문이다(C5가 `_EXPECTED_ROWS_BY_LANE`을 넣어야 풀린다).
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
from factories import _create_admin, _login_as, _login_as_admin, _make_user


def _bypass_publish_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """R-1~R-7 **내용**의 레인별 분할은 C5 소관이라, 레인 스코프 초안(26/13/16행)은 아직
    레인을 모르는 `_validate_prompt_draft_for_publish` 기준으로는 항상 R-1(슬롯 불일치)에
    걸린다. 이 파일에서 "게시가 성공하는지"만 보는 테스트는 그 검증을 우회해 C4가 배선한
    쓰기 경로(버전 채번·캐시 무효화·레인 격리)만 따로 검사한다.

    🔴 **TODO(C5): C5 가 `_EXPECTED_ROWS_BY_LANE` 을 넣으면 이 헬퍼와 아래 8개 호출을 전부
    제거하고 실제 게시 검증을 타게 되돌려라.** 안 그러면 그 8개 테스트가 게시 게이트 없이
    영구히 초록으로 남는다 — 그리고 **이 우회는 저절로 드러나지 않는다.**
    `lambda *_a, **_k: None` 은 C5 가 `_validate_prompt_draft_for_publish` 에 `lane` 키워드
    인자를 추가해도 그대로 받아 넘겨 깨지지 않기 때문이다. `TODO(C5)` 로 grep 해서 찾아라."""
    monkeypatch.setattr(admin_prompts, "_validate_prompt_draft_for_publish", lambda *_a, **_k: None)


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
    # secure-issue-goal-prompt.md SEC-2: 세션이 아예 안 서도 admin 401은 나오므로, 먼저 "이
    # 유저로는 실제로 인증된다"를 고정해야 위 무세션 401과 구분되는 명제가 남는다(공허한 통과 방지).
    assert (await db_client.get("/me")).status_code == 200

    resp = await db_client.request(method.upper(), path, json=json)
    assert resp.status_code == 401


async def _make_valid_draft(db_client: httpx.AsyncClient, lane: str) -> dict[str, object]:
    """GET(초안 없으면 그 레인의 활성 세트 복제본)→PUT 왕복으로, 지금 시드와 바이트
    단위로 같은 내용의 진짜 초안 행을 만든다."""
    get_resp = await db_client.get(f"/admin/prompt-sets/{lane}/draft")
    assert get_resp.status_code == 200
    cloned = get_resp.json()

    put_resp = await db_client.put(
        f"/admin/prompt-sets/{lane}/draft",
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
    """레인 분리 이전의 48행 통짜 세트 — `_validate_prompt_draft_for_publish`가 아직 아는
    유일한 "정확히 일치하는" 입력 모양이라, R-1~R-7 규칙 자체를 직접 고정하는 테스트들이
    여기서 baseline을 가져온다(PS-6 — 새 코드는 읽지 않지만, 그 문안 자체는 옛 구조 그대로다)."""
    return sa.select(PromptSet.id).where(PromptSet.lane == "legacy", PromptSet.status == "published")


async def _legacy_prompt_set_and_sections(
    db_session: AsyncSession,
) -> tuple[PromptSet, list[PromptSection]]:
    legacy_id = await db_session.scalar(_select_legacy_id())
    assert legacy_id is not None
    prompt_set = await db_session.get(PromptSet, legacy_id)
    assert prompt_set is not None
    sections = list(
        (
            await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == legacy_id))
        ).all()
    )
    assert len(sections) == 48
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
    assert len(body["sections"]) == 26


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
    """섹션 전체 교체다 — 이전 내용 중 이번 PUT에 없는 슬롯은 사라져야 한다."""
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
    assert len(remaining) == 1
    assert remaining[0].slot == "priority_tail"
    assert remaining[0].body == "[교체] 우선순위 문장"


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

    async def _get_draft_missing_once(db: AsyncSession, lane: PromptLane) -> PromptSet | None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return None
        return await real_get_draft(db, lane)

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
    """적대적 리뷰 결함 ② 재현 — 초안이 없는 상태에서 요청 본문 자체에 같은
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
    assert len(remaining) == 26


# ---- 레인 격리 (F-7①, C4-T12) ---------------------------------------------------


async def test_replace_draft_content_integrity_error_recovery_only_touches_own_lane(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C4-2/F-7① — `_replace_draft_content`의 `except IntegrityError` 복구 경로가 **자기
    레인 초안만** 건드리는지. character 레인 초안이 이미 있는 상태에서 story 레인 PUT이
    경쟁(IntegrityError) 경로를 타도 character 초안의 섹션(13행)은 그대로여야 한다 —
    `except` 블록의 `_get_draft`가 레인 필터를 빠뜨리면(또는 `assert draft.lane == lane`이
    없으면) 이 복구가 엉뚱한 레인의 초안을 덮어쓸 수 있다."""
    await _login_new_admin(db_client, db_session)
    character_draft = await _make_valid_draft(db_client, "character")
    character_id = uuid.UUID(str(character_draft["id"]))

    get_resp = await db_client.get("/admin/prompt-sets/story/draft")
    cloned = get_resp.json()

    real_get_draft = admin_prompts._get_draft
    call_count = 0

    async def _get_draft_missing_once(db: AsyncSession, lane: PromptLane) -> PromptSet | None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return None
        return await real_get_draft(db, lane)

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
    assert len(remaining_character_sections) == 13


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
    assert len(published) == 3  # story/character/publish_filter
    assert len(draft) == 1
    assert all(item["isActive"] for item in published)
    assert draft[0]["isActive"] is False
    assert {item["version"] for item in published} == {"1"}


async def test_get_by_id_returns_full_sections(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _login_new_admin(db_client, db_session)
    active_id = await db_session.scalar(_select_active_id("story"))

    resp = await db_client.get(f"/admin/prompt-sets/{active_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sections"]) == 26
    assert body["version"] == "1"
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
    """PS-6 — `lane='legacy'`는 새 코드가 읽지 않는 격리 버킷이다. 응답의 `lane` 필드가
    `PromptLane`(legacy 제외)이라 legacy 행은 애초에 표현할 수 없어 404로 취급한다."""
    await _login_new_admin(db_client, db_session)
    legacy_id = await db_session.scalar(_select_legacy_id())

    resp = await db_client.get(f"/admin/prompt-sets/{legacy_id}")
    assert resp.status_code == 404


# ---- 미리보기 (T-44/D-10) -------------------------------------------------------


async def test_preview_reuses_the_real_renderer(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """별도 조립 코드를 만들지 않았다는 증거 — 미리보기가 낸 `system·캐릭터` 텍스트가
    `system_instruction_for()`를 직접 호출한 결과와 바이트 단위로 같아야 한다."""
    await _login_new_admin(db_client, db_session)
    active_id = await db_session.scalar(_select_active_id("story"))
    sections = (
        await db_session.scalars(
            sa.select(PromptSection).where(PromptSection.prompt_set_id == active_id)
        )
    ).all()
    expected = system_instruction_for(list(sections), is_story_chat=False)

    resp = await db_client.post("/admin/prompt-sets/story/draft/preview")
    assert resp.status_code == 200
    items = resp.json()["items"]
    character_system = next(i for i in items if i["channel"] == "system" and "캐릭터" in i["label"])
    assert character_system["text"] == expected

    channels = {item["channel"] for item in items}
    assert channels == {
        "system",
        "generation",
        "stat_judgment",
        "ending_judgment",
        "image_judgment",
        "publish_filter",
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
    character_system = next(
        i for i in resp.json()["items"] if i["channel"] == "system" and "캐릭터" in i["label"]
    )
    assert "[초안 전용] 우선순위 문장" in character_system["text"]


# ---- 게시 — happy path ----------------------------------------------------------


async def test_publish_without_draft_returns_400(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _login_new_admin(db_client, db_session)
    resp = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "메모"})
    assert resp.status_code == 400


async def test_publish_valid_unmodified_draft_succeeds_with_next_version(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bypass_publish_validation(monkeypatch)
    await _login_new_admin(db_client, db_session)
    await _make_valid_draft(db_client, "story")

    resp = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "정기 점검 후 재게시"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == "2"
    assert body["status"] == "published"
    assert body["lane"] == "story"
    assert body["note"] == "정기 점검 후 재게시"
    assert len(body["sections"]) == 26

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
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bypass_publish_validation(monkeypatch)
    await _login_new_admin(db_client, db_session)
    await _make_valid_draft(db_client, "story")
    first = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "v2"})
    assert first.json()["version"] == "2"

    await _make_valid_draft(db_client, "story")
    second = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "v3"})
    assert second.json()["version"] == "3"


async def test_next_version_is_global_monotonic_not_per_lane(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C4-T13 — PS-2: `_next_published_version`에 레인 필터가 없다("안 넣는 것"이 결정이다).
    story가 v2·v3을 게시한 뒤 character 게시가 v4를 받아야 한다(레인별 독립 증가라면
    character의 첫 게시는 v1일 것이다) — 이 테스트는 그 레인 필터의 **부재**를 고정한다."""
    _bypass_publish_validation(monkeypatch)
    await _login_new_admin(db_client, db_session)

    await _make_valid_draft(db_client, "story")
    first = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "story v2"})
    assert first.json()["version"] == "2"

    await _make_valid_draft(db_client, "story")
    second = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "story v3"})
    assert second.json()["version"] == "3"

    await _make_valid_draft(db_client, "character")
    third = await db_client.post("/admin/prompt-sets/character/publish", json={"note": "character v4"})
    assert third.json()["version"] == "4"


async def test_publishing_one_lane_does_not_affect_other_lanes_active_set(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C4-T14 — 레인 독립성: story 게시 뒤 character 활성본의 id·섹션이 그대로다."""
    _bypass_publish_validation(monkeypatch)
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
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bypass_publish_validation(monkeypatch)
    await _login_new_admin(db_client, db_session)
    prompt_set, sections = await load_active_prompt_set(db_session, lane="story")
    await set_cached_active_prompt_set("story", prompt_set, sections)
    assert await get_cached_active_prompt_set("story") is not None

    await _make_valid_draft(db_client, "story")
    resp = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "캐시 무효화 확인"})
    assert resp.status_code == 200

    assert await get_cached_active_prompt_set("story") is None


async def test_publish_succeeds_even_when_cache_invalidation_fails(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """DB 커밋(진짜 소스)이 이미 성공했으면 캐시 무효화 실패로 게시 자체를 500으로
    만들지 않는다 — `admin/prompts.py`의 결정과 근거 주석 참고.

    monitoring-techspec.md MT-6: 이 흡수는 그대로 두되, `redis` 태그로 Bugsink
    이벤트에도 승격돼야 한다."""
    _bypass_publish_validation(monkeypatch)

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
    assert resp.json()["version"] == "2"
    assert any(record.levelno >= logging.WARNING for record in caplog.records)
    assert captured == ["redis"]


async def test_publish_version_conflict_returns_409(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_next_published_version`을 이미 게시된 버전("1")으로 고정해, 부분 유니크 인덱스
    (`ix_prompt_sets_lane_version_published`)에 실제로 걸리게 만든다."""
    _bypass_publish_validation(monkeypatch)

    async def _stale_version(_db: AsyncSession) -> str:
        return "1"

    monkeypatch.setattr(admin_prompts, "_next_published_version", _stale_version)

    await _login_new_admin(db_client, db_session)
    await _make_valid_draft(db_client, "story")

    resp = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "충돌"})
    assert resp.status_code == 409

    published = (
        await db_session.scalars(
            sa.select(PromptSet).where(PromptSet.status == "published", PromptSet.lane == "story")
        )
    ).all()
    assert len(published) == 1  # 실패한 시도가 새 published 행을 남기지 않는다


# ---- 롤백 (restore) -------------------------------------------------------------


async def test_restore_clones_old_version_into_draft(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bypass_publish_validation(monkeypatch)
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
    assert bad_publish.status_code == 200  # 검증을 우회했으니 문안만 나쁜 게시가 통과한다

    restore_resp = await db_client.post(f"/admin/prompt-sets/{seed_id}/restore")
    assert restore_resp.status_code == 200
    restored = restore_resp.json()
    restored_tail = next(s for s in restored["sections"] if s["slot"] == "priority_tail")
    assert restored_tail["body"] == original_body

    republish = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "롤백"})
    assert republish.status_code == 200
    republish_tail = next(s for s in republish.json()["sections"] if s["slot"] == "priority_tail")
    assert republish_tail["body"] == original_body


async def test_restore_missing_id_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _login_new_admin(db_client, db_session)
    resp = await db_client.post(f"/admin/prompt-sets/{uuid.uuid4()}/restore")
    assert resp.status_code == 404


async def test_restore_rejects_legacy_lane_with_422(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """C4-T15 — PS-6: `lane='legacy'`(레인 분리 이전) 세트는 복원 대상이 아니다."""
    await _login_new_admin(db_client, db_session)
    legacy_id = await db_session.scalar(_select_legacy_id())
    assert legacy_id is not None

    resp = await db_client.post(f"/admin/prompt-sets/{legacy_id}/restore")
    assert resp.status_code == 422
    assert resp.json()["detail"]["rule"] == "legacy-lane"

    drafts = (await db_session.scalars(sa.select(PromptSet).where(PromptSet.status == "draft"))).all()
    assert len(drafts) == 0  # 거부된 시도가 초안 행을 만들지 않는다


# ---- 목록에서 legacy 제외 (TS-C, C4-T16) ------------------------------------------


async def test_list_excludes_legacy_and_marks_exactly_three_active(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """C4-T16 — TS-C: `GET /admin/prompt-sets` 응답에 legacy 행이 없고 `isActive`가
    정확히 3개(레인마다 하나씩)다."""
    await _login_new_admin(db_client, db_session)

    resp = await db_client.get("/admin/prompt-sets")
    assert resp.status_code == 200
    items = resp.json()["items"]

    lanes = {item["lane"] for item in items}
    assert "legacy" not in lanes
    assert lanes == {"story", "character", "publish_filter"}

    active_items = [item for item in items if item["isActive"]]
    assert len(active_items) == 3
    assert {item["lane"] for item in active_items} == {"story", "character", "publish_filter"}


# ---- 게시 검증 R-1~R-7 — `_validate_prompt_draft_for_publish` 직접 호출 -------------
#
# C5가 `_EXPECTED_ROWS_BY_LANE`으로 쪼개기 전까지, 이 함수는 여전히 레인 분리 이전의
# 48행 통짜 구조 하나만 안다(`admin/prompts.py`의 `_EXPECTED_ROWS`). 레인 스코프 라우트는
# 한 번에 한 레인(26/13/16행)만 제출할 수 있어 그 구조를 더 이상 재현할 수 없으므로,
# 여기서는 HTTP 라우트를 거치지 않고 `_validate_prompt_draft_for_publish`를 legacy 레인의
# 48행 데이터로 직접 호출해 규칙 자체(변경되지 않았다)를 계속 고정한다.


async def test_publish_rejects_missing_slot_r1(db_session: AsyncSession) -> None:
    prompt_set, sections = await _legacy_prompt_set_and_sections(db_session)
    tail = _find_section(sections, channel="system", slot="priority_tail")
    sections = [s for s in sections if s is not tail]

    with pytest.raises(HTTPException) as exc_info:
        admin_prompts._validate_prompt_draft_for_publish(prompt_set, sections)
    assert cast(dict[str, object], exc_info.value.detail)["rule"] == "R-1"


async def test_publish_rejects_missing_template_variant_r2(db_session: AsyncSession) -> None:
    prompt_set, sections = await _legacy_prompt_set_and_sections(db_session)
    custom_variant = _find_section(sections, channel="system", slot="template_instruction", variant="custom")
    sections = [s for s in sections if s is not custom_variant]

    with pytest.raises(HTTPException) as exc_info:
        admin_prompts._validate_prompt_draft_for_publish(prompt_set, sections)
    assert cast(dict[str, object], exc_info.value.detail)["rule"] == "R-2"


async def test_publish_rejects_missing_base_content_custom_variant_r2(db_session: AsyncSession) -> None:
    """적대적 리뷰 결함 ① 재현 — `base_content`의 `custom` variant가 빠지면 CUSTOM
    템플릿 스토리도 `variant=""` 행(`{setting_text}`)으로 폴백하는데, CUSTOM 스토리는
    `setting_text`가 정상적으로 비어 있어 `conditional=True`인 이 섹션이 통째로
    드롭된다 — "다른 문안으로 대체"가 아니라 작품 설정(세계관/커스텀 프롬프트) 전체
    소실이다."""
    prompt_set, sections = await _legacy_prompt_set_and_sections(db_session)
    custom_base_content = _find_section(sections, channel="generation", slot="base_content", variant="custom")
    sections = [s for s in sections if s is not custom_base_content]

    with pytest.raises(HTTPException) as exc_info:
        admin_prompts._validate_prompt_draft_for_publish(prompt_set, sections)
    assert cast(dict[str, object], exc_info.value.detail)["rule"] == "R-2"


async def test_publish_rejects_blank_body_r3(db_session: AsyncSession) -> None:
    prompt_set, sections = await _legacy_prompt_set_and_sections(db_session)
    prologue = _find_section(sections, channel="generation", slot="prologue")
    prologue.body = "   "

    with pytest.raises(HTTPException) as exc_info:
        admin_prompts._validate_prompt_draft_for_publish(prompt_set, sections)
    assert cast(dict[str, object], exc_info.value.detail)["rule"] == "R-3"


async def test_publish_rejects_disallowed_placeholder_r4(db_session: AsyncSession) -> None:
    prompt_set, sections = await _legacy_prompt_set_and_sections(db_session)
    prologue = _find_section(sections, channel="generation", slot="prologue")
    prologue.body = "[시작 상황]\n{prologue} {not_a_real_placeholder}"

    with pytest.raises(HTTPException) as exc_info:
        admin_prompts._validate_prompt_draft_for_publish(prompt_set, sections)
    assert cast(dict[str, object], exc_info.value.detail)["rule"] == "R-4"


async def test_publish_rejects_unbalanced_braces_r4(db_session: AsyncSession) -> None:
    prompt_set, sections = await _legacy_prompt_set_and_sections(db_session)
    prologue = _find_section(sections, channel="generation", slot="prologue")
    prologue.body = "[시작 상황]\n{prologue"

    with pytest.raises(HTTPException) as exc_info:
        admin_prompts._validate_prompt_draft_for_publish(prompt_set, sections)
    assert cast(dict[str, object], exc_info.value.detail)["rule"] == "R-4"


async def test_publish_rejects_blank_label_r5(db_session: AsyncSession) -> None:
    prompt_set, sections = await _legacy_prompt_set_and_sections(db_session)
    prompt_set.user_label = "  "

    with pytest.raises(HTTPException) as exc_info:
        admin_prompts._validate_prompt_draft_for_publish(prompt_set, sections)
    assert cast(dict[str, object], exc_info.value.detail)["rule"] == "R-5"


async def test_publish_rejects_label_with_colon_r5(db_session: AsyncSession) -> None:
    prompt_set, sections = await _legacy_prompt_set_and_sections(db_session)
    prompt_set.user_label = "사용자:"

    with pytest.raises(HTTPException) as exc_info:
        admin_prompts._validate_prompt_draft_for_publish(prompt_set, sections)
    assert cast(dict[str, object], exc_info.value.detail)["rule"] == "R-5"


async def test_publish_rejects_duplicate_order_in_same_group_r6(db_session: AsyncSession) -> None:
    prompt_set, sections = await _legacy_prompt_set_and_sections(db_session)
    rule_open_turn = _find_section(sections, channel="system", slot="rule_open_turn")
    rule_user_agency = _find_section(sections, channel="system", slot="rule_user_agency")
    rule_open_turn.order = rule_user_agency.order

    with pytest.raises(HTTPException) as exc_info:
        admin_prompts._validate_prompt_draft_for_publish(prompt_set, sections)
    assert cast(dict[str, object], exc_info.value.detail)["rule"] == "R-6"


async def test_publish_rejects_priority_tail_not_last_r7(db_session: AsyncSession) -> None:
    prompt_set, sections = await _legacy_prompt_set_and_sections(db_session)
    tail = _find_section(sections, channel="system", slot="priority_tail")
    tail.order = 1

    with pytest.raises(HTTPException) as exc_info:
        admin_prompts._validate_prompt_draft_for_publish(prompt_set, sections)
    assert cast(dict[str, object], exc_info.value.detail)["rule"] == "R-7"


# ---- 허용 플레이스홀더 단일 소스 — legacy 48행 고정 --------------------------------


async def test_seed_sections_use_only_allowed_placeholders(db_session: AsyncSession) -> None:
    """§9-2 R-4의 허용 목록(`ALLOWED_PLACEHOLDERS`)이 지금 시드된 48행(legacy) 전부를
    통과하는지 고정한다 — 렌더러 호출부의 `values` 딕셔너리에서 뽑아낸 목록이므로, 실제로
    쓰이는 문안을 스스로 거부하면 안 된다."""
    _, sections = await _legacy_prompt_set_and_sections(db_session)

    for section in sections:
        fields = [name for _, name, _, _ in Formatter().parse(section.body) if name is not None]
        allowed = ALLOWED_PLACEHOLDERS[(section.channel, section.slot)]
        unknown = {name for name in fields if name not in allowed}
        assert not unknown, f"{section.channel}/{section.slot}: {unknown}"
