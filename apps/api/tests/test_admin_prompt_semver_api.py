"""어드민 게시가 체인·섹션 판을 매기는 규칙과 게시 전 바뀐 섹션 조회 API.

체인은 (레인, 모델) 세트 줄기, 섹션은 채널 하나 또는 화자 라벨 넷 묶음(`speaker_labels`)이다. 테스트 DB 는 마이그레이션이
체인마다 활성 세트 하나를 1.0.0 으로 매긴 상태에서 시작한다 — 채팅 두 레인 Gemini 체인만 그 뒤 옛 소설화 채널을 뺀 판이
1.0.1 로 활성이고, 그 판의 남은 섹션은 1.0.0 을 그대로 물려받았다. 고친 본문은 모두 합성 문장이다."""

import uuid
from datetime import timedelta
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin import prompt_semver
from api.admin import prompts as admin_prompts
from api.chat.prompt_builder import PromptLane, load_active_prompt_set
from api.db.models.prompt import PromptSection, PromptSectionSemver, PromptSet, PromptSetSemver
from api.llm.chat_models import PromptSetModelId
from factories import _create_admin, _login_as_admin

_EDIT = " [합성 수정]"


async def _login_new_admin(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)


async def _save_draft(
    db_client: httpx.AsyncClient,
    lane: str,
    model: str = "gemini",
    *,
    edit: tuple[str, ...] = (),
    labels: dict[str, str] | None = None,
) -> None:
    """활성 세트(또는 지금 초안)를 받아 `edit` 채널마다 첫 행 본문 끝에 합성 문구를 붙여 초안으로 저장한다."""
    got = await db_client.get(f"/admin/prompt-sets/{lane}/draft", params={"model": model})
    assert got.status_code == 200
    draft = got.json()
    for channel in edit:
        rows = sorted((s for s in draft["sections"] if s["channel"] == channel), key=lambda s: (s["order"], s["slot"]))
        rows[0]["body"] += _EDIT
    put = await db_client.put(
        f"/admin/prompt-sets/{lane}/draft",
        params={"model": model},
        json={
            "labels": {**draft["labels"], **(labels or {})},
            "sections": draft["sections"],
        },
    )
    assert put.status_code == 200, put.text


async def _publish(db_client: httpx.AsyncClient, lane: str, model: str = "gemini", **body: Any) -> httpx.Response:
    return await db_client.post(
        f"/admin/prompt-sets/{lane}/publish", params={"model": model}, json={"note": "합성 게시", **body}
    )


def _sections_by_channel(body: dict[str, Any]) -> dict[str, tuple[str, str | None]]:
    return {item["channel"]: (item["semver"], item["level"]) for item in body["sectionSemvers"]}


async def _chain_row(db_session: AsyncSession, set_id: uuid.UUID) -> PromptSetSemver:
    row = await db_session.scalar(sa.select(PromptSetSemver).where(PromptSetSemver.prompt_set_id == set_id))
    assert row is not None
    return row


async def _backfilled_set_id(db_session: AsyncSession, lane: str, model: str) -> uuid.UUID:
    set_id = await db_session.scalar(
        sa.select(PromptSetSemver.prompt_set_id).where(
            PromptSetSemver.lane == lane, PromptSetSemver.model == model, PromptSetSemver.level.is_(None)
        )
    )
    assert set_id is not None
    return set_id


async def _set_count(db_session: AsyncSession) -> tuple[int | None, int | None]:
    return (
        await db_session.scalar(sa.select(sa.func.count()).select_from(PromptSet)),
        await db_session.scalar(sa.select(sa.func.count()).select_from(PromptSetSemver)),
    )


# ── 게시 번호 매기기 ────────────────────────────────────────────────────────
async def test_publishing_one_edited_channel_raises_only_that_channel_and_the_chain(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """한 채널만 고쳐 게시하면 그 채널과 체인이 patch 로 오르고 다른 채널·라벨은 1.0.0 을 단계 없이 물려받으며, 기준판은 직전
    활성판이다. 다른 모델 체인의 게시를 먼저 끼워, 기준판 조회가 모델을 가리지 않으면 번호가 섞이는 것을 잡는다. 깨지는
    시나리오: 안 바뀐 섹션까지 올라 무엇이 바뀌었는지 판으로 못 읽거나, 다른 모델 체인의 판을 이어 받는다."""
    await _login_new_admin(db_client, db_session)
    await _save_draft(db_client, "story", "opus", edit=("system",))
    assert (await _publish(db_client, "story", "opus")).json()["semver"] == "1.0.1"
    base_id = (await load_active_prompt_set(db_session, lane="story"))[0].id

    await _save_draft(db_client, "story", edit=("system",))
    resp = await _publish(db_client, "story")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["semver"] == "1.0.2"
    sections = _sections_by_channel(body)
    assert sections.pop("system") == ("1.0.1", "patch")
    assert set(sections.values()) == {("1.0.0", None)}
    assert "speaker_labels" in sections
    assert body["removedSections"] == []
    chain = await _chain_row(db_session, uuid.UUID(body["id"]))
    assert (chain.level, chain.base_set_id) == ("patch", base_id)


async def test_the_chain_takes_the_largest_level_of_its_changed_sections(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """두 채널을 고쳐 하나만 minor 로 고르면 그 채널은 minor, 나머지는 patch, 체인은 minor 다. 깨지는 시나리오: 체인이 가장
    작은 단계나 첫 섹션의 단계를 따라 기능 추가가 체인 번호에 드러나지 않는다."""
    await _login_new_admin(db_client, db_session)
    await _save_draft(db_client, "story", edit=("generation", "system"))

    body = (await _publish(db_client, "story", levels={"system": "minor"})).json()

    assert body["semver"] == "1.1.0"
    sections = _sections_by_channel(body)
    assert sections["system"] == ("1.1.0", "minor")
    assert sections["generation"] == ("1.0.1", "patch")


async def test_a_major_publish_resets_the_lower_parts_and_the_next_patch_continues_from_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """minor → major → patch 로 이어 게시하면 체인이 1.1.0 → 2.0.0 → 2.0.1 이다. 깨지는 시나리오: major 상승이 뒷자리를 되돌리지
    않아 2.1.0 이 되고, 다음 게시가 기준판이 아닌 판에서 이어진다."""
    await _login_new_admin(db_client, db_session)
    semvers = []
    for level in ("minor", "major", "patch"):
        await _save_draft(db_client, "character", edit=("system",))
        resp = await _publish(db_client, "character", levels={"system": level})
        assert resp.status_code == 200, resp.text
        semvers.append((resp.json()["semver"], _sections_by_channel(resp.json())["system"]))

    assert semvers == [
        ("1.1.0", ("1.1.0", "minor")),
        ("2.0.0", ("2.0.0", "major")),
        ("2.0.1", ("2.0.1", "patch")),
    ]


async def test_a_level_for_an_unchanged_section_is_rejected_before_anything_is_written(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """바뀌지 않은 섹션에 단계를 고르면 422 이고 세트도 판도 늘지 않는다. 깨지는 시나리오: 화면이 본 차이와 서버가 본 차이가
    어긋났는데 단계를 조용히 버려, 공지급이라 고른 변경이 patch 로 나간다."""
    await _login_new_admin(db_client, db_session)
    await _save_draft(db_client, "story", edit=("system",))
    before = await _set_count(db_session)

    resp = await _publish(db_client, "story", levels={"generation": "major"})

    assert resp.status_code == 422
    assert resp.json()["detail"]["rule"] == "semver-level-for-unchanged-section"
    assert "generation" in resp.json()["detail"]["message"]
    assert await _set_count(db_session) == before


async def test_publishing_an_unchanged_draft_still_succeeds_and_raises_only_the_chain(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """고치지 않은 초안의 게시도 지금처럼 성공하고, 체인만 patch 로 오르며 섹션은 전부 단계 없이 물려받는다."""
    await _login_new_admin(db_client, db_session)
    await _save_draft(db_client, "story")

    body = (await _publish(db_client, "story")).json()

    assert body["semver"] == "1.0.2"
    assert set(_sections_by_channel(body).values()) == {("1.0.0", None)}


async def test_a_chain_without_a_base_starts_at_one_even_when_the_screen_sends_levels(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """판이 하나도 없는 체인은 바뀐 섹션 조회가 전부 시작판으로 알리고, 그 체인의 첫 게시는 단계를 보내도 막히지 않고 체인·
    섹션 전부 1.0.0 이다. 없는 섹션 이름은 422 다. 깨지는 시나리오: 새 모델 체인의 첫 게시가 화면이 채운 단계 때문에 막힌다."""
    await _login_new_admin(db_client, db_session)
    await db_session.execute(
        sa.delete(PromptSetSemver).where(PromptSetSemver.lane == "story", PromptSetSemver.model == "opus")
    )
    await _save_draft(db_client, "story", "opus", edit=("system",))

    changes = (await db_client.get("/admin/prompt-sets/story/draft/changes", params={"model": "opus"})).json()
    assert (changes["baseSetId"], changes["baseSemver"]) == (None, None)
    assert {item["change"] for item in changes["sections"]} == {"initial"}
    assert {item["currentSemver"] for item in changes["sections"]} == {None}

    rejected = await _publish(db_client, "story", "opus", levels={"nowhere": "patch"})
    assert rejected.status_code == 422

    resp = await _publish(
        db_client, "story", "opus", levels={"system": "major"}, baseSetId=None, draftHash=changes["draftHash"]
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["semver"] == "1.0.0"
    assert set(_sections_by_channel(resp.json()).values()) == {("1.0.0", None)}


async def _insert_unnumbered_published_copy(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId, channel: str
) -> uuid.UUID:
    """판을 모르는 옛 이미지의 게시를 흉내낸다 — 활성 세트를 복사해 `channel` 첫 행 본문만 고친 게시 세트를 판 행 없이 넣고,
    가장 늦은 게시 시각을 줘 활성으로 만든다."""
    active, sections = await load_active_prompt_set(db_session, lane=lane, model=model)
    latest = await db_session.scalar(sa.select(sa.func.max(PromptSet.published_at)))
    assert latest is not None
    copy = PromptSet(
        id=uuid.uuid4(),
        version="99999",
        status="published",
        lane=lane,
        model=model,
        note="",
        user_label=active.user_label,
        story_assistant_label=active.story_assistant_label,
        story_example_label=active.story_example_label,
        character_assistant_label=active.character_assistant_label,
        published_at=latest + timedelta(seconds=1),
    )
    db_session.add(copy)
    await db_session.flush()
    first = min((s for s in sections if s.channel == channel), key=lambda s: (s.order, s.slot))
    for section in sections:
        db_session.add(
            PromptSection(
                prompt_set_id=copy.id,
                channel=section.channel,
                scope=section.scope,
                slot=section.slot,
                variant=section.variant,
                body=section.body + (_EDIT if section is first else ""),
                conditional=section.conditional,
                order=section.order,
            )
        )
    await db_session.flush()
    return copy.id


async def test_changes_published_by_an_old_image_are_counted_against_the_base_not_the_active_set(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """번호 없는 게시가 사이에 끼어도 다음 게시는 판이 가장 큰 세트와 견주어, 그 사이에 바뀐 채널을 바뀜으로 센다. 깨지는
    시나리오: 활성판과 견주면 옛 이미지가 고친 채널이 안 바뀜으로 셈해져 기준판의 1.0.0 을 다른 내용으로 물려받는다."""
    await _login_new_admin(db_client, db_session)
    await _insert_unnumbered_published_copy(db_session, "story", "sonnet", "system")
    await _save_draft(db_client, "story", "sonnet")

    body = (await _publish(db_client, "story", "sonnet")).json()

    assert _sections_by_channel(body)["system"] == ("1.0.1", "patch")
    assert await _conflicting_section_numbers(db_session) == []


async def test_a_base_or_draft_that_moved_after_the_changes_view_is_a_conflict(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """바뀐 섹션 조회 뒤 다른 게시가 기준판을 바꿨거나 다른 관리자가 초안을 고쳤으면 게시가 409 로 멈추고, 그대로면 통과한다.
    깨지는 시나리오: 화면이 보지도 고르지도 않은 변경이 patch 로 게시된다."""
    await _login_new_admin(db_client, db_session)
    await _save_draft(db_client, "character", edit=("system",))
    seen = (await db_client.get("/admin/prompt-sets/character/draft/changes")).json()

    await _save_draft(db_client, "character", edit=("generation",))
    moved_draft = await _publish(
        db_client, "character", levels={"system": "major"}, baseSetId=seen["baseSetId"], draftHash=seen["draftHash"]
    )
    assert moved_draft.status_code == 409
    assert moved_draft.json()["detail"]["rule"] == "semver-draft-changed"

    stale_base = await _publish(db_client, "character", baseSetId=str(uuid.uuid4()))
    assert stale_base.status_code == 409
    assert stale_base.json()["detail"]["rule"] == "semver-base-moved"

    fresh = (await db_client.get("/admin/prompt-sets/character/draft/changes")).json()
    ok = await _publish(
        db_client, "character", levels={"system": "major"}, baseSetId=fresh["baseSetId"], draftHash=fresh["draftHash"]
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["semver"] == "2.0.0"


async def test_two_publishes_from_the_same_base_conflict_instead_of_forking_the_chain(
    db_client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """같은 기준판을 읽은 두 게시 중 뒤 것은 409 이고 세트도 판도 남기지 않는다. 깨지는 시나리오: 1.0.1 과 1.1.0 이 같은
    기준판에서 갈라져 둘 다 저장된다."""
    await _login_new_admin(db_client, db_session)
    stale = await prompt_semver.load_base(db_session, "story", "gemini")
    await _save_draft(db_client, "story", edit=("system",))
    assert (await _publish(db_client, "story")).status_code == 200
    before = await _set_count(db_session)

    async def _stale_base(_db: AsyncSession, _lane: str, _model: str) -> prompt_semver.ChainBase | None:
        return stale

    monkeypatch.setattr(admin_prompts, "load_base", _stale_base)
    await _save_draft(db_client, "story", edit=("generation",))
    resp = await _publish(db_client, "story", levels={"generation": "minor", "system": "minor"})

    assert resp.status_code == 409
    assert await _set_count(db_session) == before


@pytest.mark.parametrize(
    ("lane", "expected"),
    [
        # 소설 Gemini 체인은 등급 규칙 채널을 심은 마이그레이션이 그 채널을 minor 로 올려 1.1.0 에서 시작한다.
        pytest.param("novel", "1.1.1", id="novel"),
        pytest.param("publish_filter", "1.0.1", id="publish_filter"),
        pytest.param("novel_screen", "1.0.1", id="novel_screen"),
    ],
)
async def test_every_lane_is_numbered_without_changing_which_set_is_active(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: PromptLane, expected: str
) -> None:
    """소설·심사 레인 게시도 판이 매겨지고, 그 레인의 활성 세트는 판과 무관하게 가장 늦게 게시한 세트다."""
    await _login_new_admin(db_client, db_session)
    await db_session.execute(
        sa.update(PromptSet)
        .where(PromptSet.status == "published")
        .values(published_at=PromptSet.published_at - timedelta(days=3))
    )
    await _save_draft(db_client, lane)

    body = (await _publish(db_client, lane)).json()

    assert body["semver"] == expected
    active, _ = await load_active_prompt_set(db_session, lane=lane)
    assert str(active.id) == body["id"]


async def test_the_changes_view_matches_what_the_publish_records(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """바뀐 섹션 조회가 알린 바뀜 집합·기준판과 이어지는 게시가 기록한 것이 같다. 깨지는 시나리오: 미리보기와 실제 게시가 다른
    판정을 해 화면이 고르게 한 섹션과 올라간 섹션이 다르다."""
    await _login_new_admin(db_client, db_session)
    await _save_draft(db_client, "story", edit=("generation", "memory_fact"), labels={"userLabel": "합성 사용자"})

    changes = (await db_client.get("/admin/prompt-sets/story/draft/changes")).json()
    body = (await _publish(db_client, "story")).json()

    seen = {item["channel"] for item in changes["sections"] if item["change"] != "unchanged"}
    recorded = {channel for channel, (_, level) in _sections_by_channel(body).items() if level is not None}
    assert seen == recorded == {"generation", "memory_fact", "speaker_labels"}
    assert changes["baseSemver"] == "1.0.1"
    assert (await _chain_row(db_session, uuid.UUID(body["id"]))).base_set_id == uuid.UUID(changes["baseSetId"])
    assert {item["currentSemver"] for item in changes["sections"]} == {"1.0.0"}


async def test_a_section_without_a_number_row_in_the_base_is_numbered_as_a_returning_section(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """기준판에 내용은 있지만 판 행이 없는 섹션(측정 도구가 게시 세트의 섹션을 제자리에서 덮어 생긴다)은 새로 들어온 섹션처럼
    그 체인에서 그 섹션의 가장 큰 번호에서 이어 올리고, 바뀐 섹션 조회도 같은 섹션을 새로 들어왔다고 알린다. 깨지는 시나리오:
    안 바뀐 섹션이라 기준판 번호를 물려받으려다 그 번호가 없어 게시가 500 으로 죽고, 조회 화면에는 아무 차이도 안 보인다."""
    await _login_new_admin(db_client, db_session)
    await _save_draft(db_client, "story", edit=("system",))
    first = await _publish(db_client, "story", levels={"system": "minor"})
    assert first.status_code == 200, first.text
    await db_session.execute(
        sa.delete(PromptSectionSemver).where(
            PromptSectionSemver.prompt_set_id == uuid.UUID(first.json()["id"]), PromptSectionSemver.channel == "system"
        )
    )
    await db_session.commit()
    await _save_draft(db_client, "story")

    changes = (await db_client.get("/admin/prompt-sets/story/draft/changes")).json()
    resp = await _publish(db_client, "story")

    assert resp.status_code == 200, resp.text
    assert {item["channel"]: item["change"] for item in changes["sections"] if item["change"] != "unchanged"} == {
        "system": "added"
    }
    sections = _sections_by_channel(resp.json())
    assert sections.pop("system") == ("1.0.1", "patch")
    assert set(sections.values()) == {("1.0.0", None)}
    assert resp.json()["semver"] == "1.1.1"


async def test_dropping_a_base_section_without_a_number_row_still_shows_it_as_removed(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """기준판에 판 행 없이 내용만 있는 섹션을 초안에서 지우면, 바뀐 섹션 조회가 그 섹션을 빠진 섹션으로 알린다. 판 행이
    없다는 것은 번호를 물려받을 수 없다는 뜻일 뿐, 기준판에 그 내용이 있었던 사실은 그대로다. 깨지는 시나리오: 기준판 비교
    내용을 판 행 있는 섹션으로만 좁혀, 지운 섹션이 조회 화면 어디에도 안 보인다."""
    await _login_new_admin(db_client, db_session)
    await _save_draft(db_client, "story", edit=("system",))
    first = await _publish(db_client, "story", levels={"system": "minor"})
    assert first.status_code == 200, first.text
    await db_session.execute(
        sa.delete(PromptSectionSemver).where(
            PromptSectionSemver.prompt_set_id == uuid.UUID(first.json()["id"]), PromptSectionSemver.channel == "system"
        )
    )
    await db_session.commit()
    draft = (await db_client.get("/admin/prompt-sets/story/draft")).json()
    put = await db_client.put(
        "/admin/prompt-sets/story/draft",
        json={"labels": draft["labels"], "sections": [s for s in draft["sections"] if s["channel"] != "system"]},
    )
    assert put.status_code == 200, put.text

    changes = (await db_client.get("/admin/prompt-sets/story/draft/changes")).json()

    assert {
        item["channel"]: (item["change"], item["currentSemver"])
        for item in changes["sections"]
        if item["change"] != "unchanged"
    } == {"system": ("removed", None)}


async def test_changes_view_without_a_draft_is_400(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await _login_new_admin(db_client, db_session)
    resp = await db_client.get("/admin/prompt-sets/story/draft/changes")
    assert resp.status_code == 400


# ── 목록·상세 ──────────────────────────────────────────────────────────────
async def test_list_and_detail_show_the_semver_only_for_numbered_sets(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """판을 매길 때 활성이던 판은 "1.0.0", 그 뒤 옛 소설화 채널을 뺀 활성판은 "1.0.1", 판을 매기기 전의 게시본은 null 이고
    정수 번호는 그대로다. 상세는 섹션 판을 싣는다."""
    await _login_new_admin(db_client, db_session)
    backfilled_id = await _backfilled_set_id(db_session, "story", "gemini")
    active_id = (await load_active_prompt_set(db_session, lane="story"))[0].id

    items = {item["id"]: item for item in (await db_client.get("/admin/prompt-sets")).json()["items"]}
    story_gemini = [item for item in items.values() if (item["lane"], item["model"]) == ("story", "gemini")]
    numbered = {str(backfilled_id), str(active_id)}
    assert {item["semver"] for item in story_gemini if item["id"] not in numbered} == {None}
    assert (items[str(backfilled_id)]["semver"], items[str(active_id)]["semver"]) == ("1.0.0", "1.0.1")
    assert all(item["version"] is not None and item["version"].isdigit() for item in story_gemini)

    detail = (await db_client.get(f"/admin/prompt-sets/{active_id}")).json()
    assert detail["semver"] == "1.0.1"
    assert set(_sections_by_channel(detail).values()) == {("1.0.0", None)}
    assert {item["channel"] for item in detail["sections"]} | {"speaker_labels"} == set(_sections_by_channel(detail))
    old = next(item for item in story_gemini if item["semver"] is None)
    old_detail = (await db_client.get(f"/admin/prompt-sets/{old['id']}")).json()
    assert (old_detail["semver"], old_detail["sectionSemvers"], old_detail["removedSections"]) == (None, [], [])


# ── head 불변식 ────────────────────────────────────────────────────────────
async def _conflicting_section_numbers(db_session: AsyncSession) -> list[tuple[Any, ...]]:
    """같은 체인에서 같은 (섹션, 번호)가 서로 다른 내용을 가리키는 묶음."""
    rows = await db_session.execute(
        sa.text(
            "WITH content AS ("
            "  SELECT prompt_set_id, channel, md5(string_agg(concat_ws('|', scope, slot, variant, body, conditional,"
            "    \"order\"), E'\\n' ORDER BY scope, slot, variant, \"order\", body)) AS digest"
            "  FROM prompt_sections GROUP BY prompt_set_id, channel"
            "  UNION ALL"
            "  SELECT id, 'speaker_labels', md5(concat_ws('|', user_label, story_assistant_label, story_example_label,"
            "    character_assistant_label)) FROM prompt_sets"
            ")"
            " SELECT v.lane, v.model, s.channel, s.major, s.minor, s.patch"
            " FROM prompt_section_semvers s"
            " JOIN prompt_set_semvers v ON v.prompt_set_id = s.prompt_set_id"
            " LEFT JOIN content c ON c.prompt_set_id = s.prompt_set_id AND c.channel = s.channel"
            " GROUP BY v.lane, v.model, s.channel, s.major, s.minor, s.patch"
            " HAVING count(DISTINCT coalesce(c.digest, '')) > 1"
        )
    )
    return [tuple(row) for row in rows]


async def test_every_active_chain_set_is_numbered_and_numbers_mean_one_content(db_session: AsyncSession) -> None:
    """legacy 를 뺀 모든 체인의 활성 세트에 판이 있고, 같은 체인에서 같은 (섹션, 번호)는 늘 같은 내용이다. 깨지는 시나리오:
    게시 세트를 넣는 문안 마이그레이션이 판 매기기 블록을 빠뜨리거나, 번호를 매긴 게시본을 제자리에서 고친다."""
    unnumbered = (
        await db_session.execute(
            sa.text(
                "SELECT a.lane, a.model FROM ("
                "  SELECT DISTINCT ON (lane, model) id, lane, model FROM prompt_sets"
                "  WHERE status = 'published' AND lane <> 'legacy'"
                "  ORDER BY lane, model, published_at DESC, id DESC"
                ") a LEFT JOIN prompt_set_semvers v ON v.prompt_set_id = a.id WHERE v.id IS NULL"
            )
        )
    ).all()
    assert unnumbered == []
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(PromptSectionSemver))
    assert await _conflicting_section_numbers(db_session) == []
