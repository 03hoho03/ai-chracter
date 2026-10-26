"""어드민 섹션 복원 — 옛 게시본의 섹션 하나(채널 하나 또는 화자 라벨 넷 묶음 `speaker_labels`)만 지금 초안으로 가져온다.

체인 통째 복원은 다른 채널의 게시 안 한 편집까지 옛 값으로 돌리므로, 한 채널만 되돌리고 싶을 때 이 API 를 쓴다. 게시는 하지
않는다 — 복원한 섹션은 다음 게시에서 기준판과 다른 섹션으로 잡혀 새 번호로 오른다. 고친 본문은 모두 합성 문장이다."""

import uuid
from datetime import timedelta
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin import prompts as admin_prompts
from api.chat.prompt_builder import PromptLane, load_active_prompt_set
from api.db.models.prompt import PromptSection, PromptSet
from api.llm.chat_models import PromptSetModelId
from factories import _create_admin, _login_as, _login_as_admin, _make_user

_DRAFT_EDIT = " [합성 초안 편집]"
_OLD_EDIT = " [합성 옛 문안]"

Row = tuple[str, str, str, str, bool, int]


async def _login_new_admin(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)


def _rows(sections: list[dict[str, Any]], channel: str) -> list[Row]:
    return sorted(
        (s["scope"], s["slot"], s["variant"], s["body"], s["conditional"], s["order"])
        for s in sections
        if s["channel"] == channel
    )


def _db_rows(sections: list[PromptSection], channel: str) -> list[Row]:
    return sorted(
        (s.scope, s.slot, s.variant, s.body, s.conditional, s.order) for s in sections if s.channel == channel
    )


def _other_rows(sections: list[dict[str, Any]], channel: str) -> list[tuple[str, Row]]:
    return sorted(
        (s["channel"], (s["scope"], s["slot"], s["variant"], s["body"], s["conditional"], s["order"]))
        for s in sections
        if s["channel"] != channel
    )


async def _get_draft(db_client: httpx.AsyncClient, lane: str, model: str = "gemini") -> dict[str, Any]:
    got = await db_client.get(f"/admin/prompt-sets/{lane}/draft", params={"model": model})
    assert got.status_code == 200, got.text
    body: dict[str, Any] = got.json()
    return body


async def _save_draft(
    db_client: httpx.AsyncClient,
    lane: str,
    model: str = "gemini",
    *,
    edit: tuple[str, ...] = (),
    labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """지금 초안(없으면 활성판)을 받아 `edit` 채널마다 첫 행 본문 끝에 합성 문구를 붙여 저장하고 저장된 초안을 돌려준다."""
    draft = await _get_draft(db_client, lane, model)
    for channel in edit:
        rows = sorted((s for s in draft["sections"] if s["channel"] == channel), key=lambda s: (s["order"], s["slot"]))
        rows[0]["body"] += _DRAFT_EDIT
    put = await db_client.put(
        f"/admin/prompt-sets/{lane}/draft",
        params={"model": model},
        json={"labels": {**draft["labels"], **(labels or {})}, "sections": draft["sections"]},
    )
    assert put.status_code == 200, put.text
    saved: dict[str, Any] = put.json()
    return saved


async def _publish(db_client: httpx.AsyncClient, lane: str, model: str = "gemini") -> dict[str, Any]:
    resp = await db_client.post(
        f"/admin/prompt-sets/{lane}/publish", params={"model": model}, json={"note": "합성 게시"}
    )
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


async def _restore(
    db_client: httpx.AsyncClient, set_id: uuid.UUID | str, channel: str, *, overwrite: bool | None = None
) -> httpx.Response:
    payload: dict[str, Any] = {} if overwrite is None else {"overwriteDraftChanges": overwrite}
    return await db_client.post(f"/admin/prompt-sets/{set_id}/sections/{channel}/restore", json=payload)


async def _insert_old_set(
    db_session: AsyncSession,
    lane: PromptLane,
    model: PromptSetModelId = "gemini",
    *,
    edit: tuple[str, ...] = (),
    labels: dict[str, str] | None = None,
    extra_rows: tuple[tuple[str, str, str], ...] = (),
    set_model: str | None = None,
    set_lane: str | None = None,
) -> PromptSet:
    """활성판을 베껴 활성판보다 하루 앞선 게시본을 직접 넣는다(활성판은 그대로다). `edit` 채널은 첫 행 본문 끝에 합성 문구를
    붙이고, `extra_rows` 는 (채널, 범위, 슬롯) 행을 더한다. 판 행은 넣지 않는다 — 판을 매기기 전의 옛 게시본과 같다."""
    active, sections = await load_active_prompt_set(db_session, lane=lane, model=model)
    assert active.published_at is not None
    old = PromptSet(
        id=uuid.uuid4(),
        version=await admin_prompts._next_published_version(db_session),
        status="published",
        lane=set_lane or lane,
        model=set_model or model,
        note="합성 옛 판",
        user_label=(labels or {}).get("user_label", active.user_label),
        story_assistant_label=(labels or {}).get("story_assistant_label", active.story_assistant_label),
        story_example_label=(labels or {}).get("story_example_label", active.story_example_label),
        character_assistant_label=(labels or {}).get("character_assistant_label", active.character_assistant_label),
        published_at=active.published_at - timedelta(days=1),
    )
    db_session.add(old)
    await db_session.flush()
    edited: set[str] = set()
    for section in sorted(sections, key=lambda s: (s.channel, s.order, s.slot, s.variant)):
        body = section.body
        if section.channel in edit and section.channel not in edited:
            body += _OLD_EDIT
            edited.add(section.channel)
        db_session.add(
            PromptSection(
                id=uuid.uuid4(),
                prompt_set_id=old.id,
                channel=section.channel,
                scope=section.scope,
                slot=section.slot,
                variant=section.variant,
                body=body,
                conditional=section.conditional,
                order=section.order,
            )
        )
    for channel, scope, slot in extra_rows:
        db_session.add(
            PromptSection(
                id=uuid.uuid4(),
                prompt_set_id=old.id,
                channel=channel,
                scope=scope,
                slot=slot,
                variant="",
                body="합성 덧붙인 행",
                conditional=True,
                order=99,
            )
        )
    await db_session.flush()
    return old


async def _old_rows(db_session: AsyncSession, set_id: uuid.UUID, channel: str) -> list[Row]:
    sections = (await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))).all()
    return _db_rows(list(sections), channel)


async def _draft_count(db_session: AsyncSession) -> int | None:
    count: int | None = await db_session.scalar(
        sa.select(sa.func.count()).select_from(PromptSet).where(PromptSet.status == "draft")
    )
    return count


# ── 권한 ────────────────────────────────────────────────────────────────────
async def test_section_restore_requires_an_admin_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """세션이 없거나 일반 사용자 세션이면 401 이고 초안이 생기지 않는다. 깨지는 시나리오: 관리자 가드를 빠뜨려 누구나 운영
    프롬프트 초안을 옛 문안으로 바꾼다."""
    active, _ = await load_active_prompt_set(db_session, lane="story")
    assert (await _restore(db_client, active.id, "system")).status_code == 401

    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    assert (await db_client.get("/me")).status_code == 200
    assert (await _restore(db_client, active.id, "system")).status_code == 401
    assert await _draft_count(db_session) == 0


# ── 복원 ────────────────────────────────────────────────────────────────────
async def test_restoring_one_channel_keeps_the_other_channels_unpublished_edits_and_the_labels(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """다른 채널과 라벨을 고친 초안이 있을 때 한 채널을 옛 판으로 복원하면 그 채널만 옛 행이 되고 다른 채널의 편집과 라벨은
    그대로다. 깨지는 시나리오: 다른 채널을 옛 판(또는 활성판)으로 채워, 통째 복원처럼 게시 안 한 편집이 사라진다."""
    await _login_new_admin(db_client, db_session)
    old = await _insert_old_set(db_session, "story", edit=("system",))
    draft = await _save_draft(db_client, "story", edit=("generation",), labels={"userLabel": "합성 사용자"})

    resp = await _restore(db_client, old.id, "system")

    assert resp.status_code == 200, resp.text
    restored = resp.json()
    assert restored["id"] == draft["id"]
    assert _rows(restored["sections"], "system") == await _old_rows(db_session, old.id, "system")
    assert _rows(restored["sections"], "system") != _rows(draft["sections"], "system")
    assert _other_rows(restored["sections"], "system") == _other_rows(draft["sections"], "system")
    assert any(_DRAFT_EDIT in row[3] for row in _rows(restored["sections"], "generation"))
    assert restored["labels"] == draft["labels"]
    assert restored["labels"]["userLabel"] == "합성 사용자"
    # 복원 응답만 등급 규칙 비교를 싣는다 — 스토리 Gemini 체인의 등급 규칙을 소설 레인 체인 활성판의 같은 scope 와 견준 항목들이다.
    drift = restored["ratingDrift"]
    assert drift and {(item["scope"], item["otherLane"]) for item in drift} == {("story", "novel")}
    assert restored == {**await _get_draft(db_client, "story"), "ratingDrift": drift}


async def test_saving_with_the_hash_from_a_section_restore_response_succeeds(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """섹션 복원 응답도 저장된 초안 해시를 싣고, 그 해시를 돌려보내 이어서 저장하면 200 이다. 저장 응답과 조회 응답과 같은
    함수로 응답을 조립해야 성립한다. 깨지는 시나리오: 복원 응답만 해시를 빠뜨리거나 복원 전 값을 실어, 복원 뒤 첫 저장이 늘
    409 가 된다."""
    await _login_new_admin(db_client, db_session)
    old = await _insert_old_set(db_session, "story", edit=("system",))
    await _save_draft(db_client, "story", edit=("generation",))

    restored_resp = await _restore(db_client, old.id, "system")
    assert restored_resp.status_code == 200, restored_resp.text
    restored = restored_resp.json()
    assert isinstance(restored["savedDraftHash"], str)
    assert restored["allowedPlaceholders"]

    saved = await db_client.put(
        "/admin/prompt-sets/story/draft",
        json={
            "labels": {**restored["labels"], "userLabel": "합성 사용자"},
            "sections": restored["sections"],
            "baseDraftHash": restored["savedDraftHash"],
        },
    )

    assert saved.status_code == 200, saved.text
    assert saved.json()["savedDraftHash"] != restored["savedDraftHash"]


@pytest.mark.parametrize(
    ("lane", "model", "channel"),
    [
        pytest.param("character", "gemini", "system", id="character-gemini"),
        pytest.param("publish_filter", "gemini", "publish_filter", id="publish-filter"),
        pytest.param("novel", "opus", "novelize_chapter", id="novel-opus"),
    ],
)
async def test_without_a_draft_the_active_set_becomes_the_draft_with_only_that_channel_restored(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    lane: PromptLane,
    model: PromptSetModelId,
    channel: str,
) -> None:
    """그 체인에 초안이 없으면 활성판을 바탕으로 초안을 만들고 그 채널만 옛 행으로 바꾼다. 소설·심사 레인 체인도 같다. 깨지는
    시나리오: 초안이 없을 때 원본 세트 전체가 초안이 되거나 아무것도 저장되지 않는다."""
    await _login_new_admin(db_client, db_session)
    old = await _insert_old_set(db_session, lane, model, edit=(channel,), labels={"user_label": "합성 옛 사용자"})
    active = await _get_draft(db_client, lane, model)
    assert active["id"] is None

    resp = await _restore(db_client, old.id, channel)

    assert resp.status_code == 200, resp.text
    restored = resp.json()
    assert restored["id"] is not None
    assert restored["model"] == model
    assert _rows(restored["sections"], channel) == await _old_rows(db_session, old.id, channel)
    assert _rows(restored["sections"], channel) != _rows(active["sections"], channel)
    assert _other_rows(restored["sections"], channel) == _other_rows(active["sections"], channel)
    assert restored["labels"] == active["labels"]
    assert await _draft_count(db_session) == 1


async def test_a_channel_with_unpublished_edits_is_refused_until_the_request_asks_to_overwrite(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """복원할 채널 자체에 게시 안 한 편집이 있으면 409 이고 초안은 그대로다. `overwriteDraftChanges` 를 켜면 그 편집을 옛 행으로
    덮어쓰되 다른 채널의 편집은 남는다. 깨지는 시나리오: 관리자가 고치던 문안을 묻지도 않고 옛 문안으로 날린다."""
    await _login_new_admin(db_client, db_session)
    old = await _insert_old_set(db_session, "story", edit=("system",))
    draft = await _save_draft(db_client, "story", edit=("system", "generation"))

    refused = await _restore(db_client, old.id, "system")

    assert refused.status_code == 409
    assert refused.json()["detail"]["rule"] == "draft-channel-has-unpublished-edits"
    assert await _get_draft(db_client, "story") == draft

    explicit_false = await _restore(db_client, old.id, "system", overwrite=False)
    assert explicit_false.status_code == 409

    overwritten = await _restore(db_client, old.id, "system", overwrite=True)

    assert overwritten.status_code == 200, overwritten.text
    body = overwritten.json()
    assert _rows(body["sections"], "system") == await _old_rows(db_session, old.id, "system")
    assert _other_rows(body["sections"], "system") == _other_rows(draft["sections"], "system")


async def test_restoring_the_speaker_labels_changes_only_the_four_labels(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """`speaker_labels` 를 복원하면 라벨 넷만 옛 값이 되고, 옛 판에서 함께 달랐던 채널과 초안의 채널 편집은 그대로다. 깨지는
    시나리오: 라벨 복원이 섹션까지 옛 판으로 돌리거나 라벨 넷 중 일부만 옮긴다."""
    await _login_new_admin(db_client, db_session)
    old_labels = {
        "user_label": "합성 옛 사용자",
        "story_assistant_label": "합성 옛 서술자",
        "story_example_label": "합성 옛 예시",
        "character_assistant_label": "합성 옛 캐릭터",
    }
    old = await _insert_old_set(db_session, "story", edit=("system",), labels=old_labels)
    draft = await _save_draft(db_client, "story", edit=("generation",))

    resp = await _restore(db_client, old.id, "speaker_labels")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["labels"] == {
        "userLabel": "합성 옛 사용자",
        "storyAssistantLabel": "합성 옛 서술자",
        "storyExampleLabel": "합성 옛 예시",
        "characterAssistantLabel": "합성 옛 캐릭터",
    }
    assert body["sections"] == draft["sections"]


async def test_speaker_labels_with_unpublished_edits_are_refused_without_overwrite(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """초안에서 라벨을 고쳐 두었으면 라벨 복원도 409 다. 깨지는 시나리오: 라벨만 게시 안 한 편집 검사에서 빠진다."""
    await _login_new_admin(db_client, db_session)
    old = await _insert_old_set(db_session, "story", labels={"user_label": "합성 옛 사용자"})
    await _save_draft(db_client, "story", labels={"userLabel": "합성 새 사용자"})

    resp = await _restore(db_client, old.id, "speaker_labels")

    assert resp.status_code == 409
    assert resp.json()["detail"]["rule"] == "draft-channel-has-unpublished-edits"


async def test_publishing_after_a_restore_gives_the_restored_channel_a_new_number_not_the_old_one(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """한 채널을 1.0.1 → 1.0.2 로 올린 뒤 1.0.1 의 그 채널을 복원해 게시하면, 그 채널은 옛 번호가 아니라 1.0.3 으로 오르고 체인도
    오르며 다른 섹션은 번호를 물려받는다. 게시된 그 채널 내용은 1.0.1 의 것이다. 깨지는 시나리오: 복원이 옛 번호를 되살려 같은
    번호가 두 내용을 가리키거나, 복원한 섹션이 바뀐 섹션으로 잡히지 않는다.

    게시 전에 게시된 세트를 전부 사흘 앞당긴다 — 테스트 세션 시작 때 한꺼번에 돈 시드 마이그레이션이 마지막 시드 세트를 벽시계보다
    몇 초 미래에 두므로, 그대로면 방금 게시한 세트가 활성판이 되지 못해 복원이 활성판과 견주는 편집 검사가 엉뚱한 세트를 본다."""
    await _login_new_admin(db_client, db_session)
    await db_session.execute(
        sa.update(PromptSet)
        .where(PromptSet.status == "published")
        .values(published_at=PromptSet.published_at - timedelta(days=3))
    )
    await _save_draft(db_client, "character", edit=("system",))
    first = await _publish(db_client, "character")
    await _save_draft(db_client, "character", edit=("system",))
    second = await _publish(db_client, "character")
    first_semvers = {item["channel"]: item["semver"] for item in first["sectionSemvers"]}
    assert (first_semvers["system"], second["semver"]) == ("1.0.1", "1.0.2")

    restored = await _restore(db_client, first["id"], "system")
    assert restored.status_code == 200, restored.text
    third = await _publish(db_client, "character")

    assert third["semver"] == "1.0.3"
    sections = {item["channel"]: (item["semver"], item["level"]) for item in third["sectionSemvers"]}
    assert sections.pop("system") == ("1.0.3", "patch")
    assert set(sections.values()) == {("1.0.0", None)}
    assert _rows(third["sections"], "system") == _rows(first["sections"], "system")


# ── 거절 ────────────────────────────────────────────────────────────────────
async def test_an_unknown_source_set_is_404(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    await _login_new_admin(db_client, db_session)

    resp = await _restore(db_client, uuid.UUID(int=7), "system")

    assert resp.status_code == 404
    assert await _draft_count(db_session) == 0


async def test_a_draft_is_not_a_restore_source(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """초안은 되돌릴 판이 아니다 — 초안 세트를 원본으로 주면 422 이고 초안은 그대로다."""
    await _login_new_admin(db_client, db_session)
    draft = await _save_draft(db_client, "story", edit=("system",))

    resp = await _restore(db_client, draft["id"], "system")

    assert resp.status_code == 422
    assert resp.json()["detail"]["rule"] == "restore-source-not-published"
    assert await _get_draft(db_client, "story") == draft


async def test_a_legacy_lane_source_is_refused(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """레인 분리 이전 세트는 복원 대상이 아니다(통째 복원과 같은 규칙)."""
    await _login_new_admin(db_client, db_session)
    legacy_id = await db_session.scalar(
        sa.select(PromptSet.id).where(PromptSet.lane == "legacy", PromptSet.status == "published")
    )
    assert legacy_id is not None

    resp = await _restore(db_client, legacy_id, "system")

    assert resp.status_code == 422
    assert resp.json()["detail"]["rule"] == "legacy-lane"
    assert await _draft_count(db_session) == 0


async def test_a_source_of_a_model_that_no_longer_exists_is_refused(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _login_new_admin(db_client, db_session)
    old = await _insert_old_set(db_session, "story", "opus", set_model="retired-synthetic-model")

    resp = await _restore(db_client, old.id, "system")

    assert resp.status_code == 422
    assert resp.json()["detail"]["rule"] == "unknown-model"
    assert await _draft_count(db_session) == 0


async def test_a_channel_the_source_does_not_have_is_refused(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """원본에 없는 채널은 가져올 행이 없다 — 조용히 그 채널을 지우지 않고 422 다."""
    await _login_new_admin(db_client, db_session)
    active, _ = await load_active_prompt_set(db_session, lane="story", model="opus")

    resp = await _restore(db_client, active.id, "novelize_chapter")

    assert resp.status_code == 422
    assert resp.json()["detail"]["rule"] == "restore-channel-not-in-source"
    assert await _draft_count(db_session) == 0


async def test_a_channel_the_chain_cannot_have_is_refused(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """원본에는 있어도 그 체인이 가질 수 없는 채널(예: Gemini 체인에만 있는 옛 스탯 판정 채널을 가진 Claude 체인 세트)은 422
    다. 깨지는 시나리오: 체인 밖 채널이 초안에 들어가 그 체인 게시가 막힌다."""
    await _login_new_admin(db_client, db_session)
    old = await _insert_old_set(db_session, "story", "opus", extra_rows=(("stat_judgment", "story", "synthetic"),))

    resp = await _restore(db_client, old.id, "stat_judgment")

    assert resp.status_code == 422
    assert resp.json()["detail"]["rule"] == "restore-channel-not-in-chain"
    assert await _draft_count(db_session) == 0


async def test_a_frozen_novel_channel_of_a_chat_chain_is_refused(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """채팅 Gemini 체인의 얼린 소설 채널은 서버가 늘 활성판 값으로 갈아 끼우므로, 복원이 아무 일도 하지 않는다는 것을 숨기지
    않고 422 로 알린다."""
    await _login_new_admin(db_client, db_session)
    old = await _insert_old_set(db_session, "story", edit=("novelize_chapter",))

    resp = await _restore(db_client, old.id, "novelize_chapter")

    assert resp.status_code == 422
    assert resp.json()["detail"]["rule"] == "restore-frozen-channel"
    assert await _draft_count(db_session) == 0


async def test_a_source_channel_whose_slots_differ_from_the_current_ones_is_refused(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """옛 판 채널의 슬롯 집합이 지금 기대와 다르면(지금은 없는 슬롯이 있음) 422 이고 문구에 그 슬롯이 나온다. 깨지는 시나리오:
    게시 검증에서야 막힐 초안을 만들어 관리자가 원인을 찾아 헤맨다."""
    await _login_new_admin(db_client, db_session)
    old = await _insert_old_set(db_session, "story", extra_rows=(("system", "story", "synthetic_extra_slot"),))

    resp = await _restore(db_client, old.id, "system")

    assert resp.status_code == 422
    assert resp.json()["detail"]["rule"] == "restore-slots-mismatch"
    assert "synthetic_extra_slot" in resp.json()["detail"]["message"]
    assert await _draft_count(db_session) == 0
