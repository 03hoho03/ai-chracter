"""등급 규칙 어긋남 판정과 통째 복원의 채널 집합 맞추기.

소설 호출이 붙이는 등급 규칙은 소설 레인 세트의 `novelize_rating` 에 있고, 대화가 붙이는 등급 규칙은 채팅 Gemini 세트의
`system/rule_rating` 에 있다. 두 곳은 같은 원작 종류끼리(채팅 story ↔ 소설 체인 scope story, 채팅 character ↔ 소설 체인
scope character) 같은 글이어야 하지만 서버가 막지는 않는다 — 게시·복원·게시 전 변경 조회 응답에 어긋남 칸을 실어 운영자가
알게 한다. 고친 본문은 모두 합성 문장이다."""

import hashlib
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
from api.novelize.prompts import render_rating
from factories import _create_admin, _login_as_admin

_EDIT = " [합성 등급 문장]"
_NOVEL_MODELS: tuple[PromptSetModelId, ...] = ("gemini", "sonnet", "opus")


async def _login_new_admin(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)


def _md5_or_none(text: str) -> str | None:
    return hashlib.md5(text.encode()).hexdigest() if text else None


async def _save_draft(
    db_client: httpx.AsyncClient,
    lane: str,
    model: str = "gemini",
    *,
    rating_scope: str | None = None,
) -> dict[str, Any]:
    """지금 초안(없으면 활성판)을 저장한다. `rating_scope` 를 주면 그 체인의 등급 규칙 행 중 그 범위 렌더에 들어가는 행 본문
    끝에 합성 문장을 붙인다 — 소설 레인은 `novelize_rating` 의 그 scope 행, 채팅 레인은 `system/rule_rating` 행이다."""
    got = await db_client.get(f"/admin/prompt-sets/{lane}/draft", params={"model": model})
    assert got.status_code == 200, got.text
    draft = got.json()
    if rating_scope is not None:
        channel = "novelize_rating" if lane == "novel" else "system"
        rows = [
            s
            for s in draft["sections"]
            if s["channel"] == channel and s["slot"] == "rule_rating" and s["scope"] in (rating_scope, "both")
        ]
        assert rows
        rows[0]["body"] += _EDIT
    put = await db_client.put(
        f"/admin/prompt-sets/{lane}/draft",
        params={"model": model},
        json={"labels": draft["labels"], "sections": draft["sections"]},
    )
    assert put.status_code == 200, put.text
    body: dict[str, Any] = put.json()
    return body


async def _changes(db_client: httpx.AsyncClient, lane: str, model: str = "gemini") -> list[dict[str, Any]]:
    resp = await db_client.get(f"/admin/prompt-sets/{lane}/draft/changes", params={"model": model})
    assert resp.status_code == 200, resp.text
    drift: list[dict[str, Any]] = resp.json()["ratingDrift"]
    return drift


def _shape(drift: list[dict[str, Any]]) -> list[tuple[str, str, str, bool]]:
    return [(item["scope"], item["otherLane"], item["otherModel"], item["differs"]) for item in drift]


async def _active_rating_md5(
    db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId, *, scope: str
) -> tuple[uuid.UUID, str | None]:
    prompt_set, sections = await load_active_prompt_set(db_session, lane=lane, model=model)
    channel = "novelize_rating" if lane == "novel" else "system"
    return prompt_set.id, _md5_or_none(render_rating(sections, channel=channel, scope=scope))


# ---- 어긋남 판정 ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("model", [pytest.param(m, id=m) for m in _NOVEL_MODELS])
async def test_an_untouched_novel_draft_matches_both_chat_rules(
    db_client: httpx.AsyncClient, db_session: AsyncSession, model: PromptSetModelId
) -> None:
    """손대지 않은 소설 초안은 원작 종류마다 채팅 Gemini 활성의 등급 규칙과 같다 — 항목 둘, 모두 같음. 상대 세트 id·지문은 그
    활성판의 것이다. 깨지는 시나리오: 마이그레이션이 옮긴 등급 규칙이 원본과 바이트가 달라 첫 화면부터 어긋남이 뜨거나, 짝을
    잘못 지어 story 규칙을 character 규칙과 견준다."""
    await _login_new_admin(db_client, db_session)
    await _save_draft(db_client, "novel", model)

    drift = await _changes(db_client, "novel", model)

    assert _shape(drift) == [
        ("story", "story", "gemini", False),
        ("character", "character", "gemini", False),
    ]
    for item in drift:
        other_id, other_md5 = await _active_rating_md5(db_session, item["otherLane"], "gemini", scope=item["scope"])
        assert (item["otherSetId"], item["otherMd5"]) == (str(other_id), other_md5)
        assert item["thisMd5"] == other_md5 is not None


async def test_editing_only_the_story_rule_of_a_novel_draft_differs_only_on_the_story_side(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """초안만 다르고 활성끼리는 같아도 어긋남이다 — 초안의 story 등급 규칙을 고치면 story 항목만 다르다고 하고 character 항목은
    같다. 깨지는 시나리오: 활성끼리만 견줘 게시하려는 초안의 어긋남을 못 보거나, scope 를 가리지 않아 character 쪽도 다르다고
    한다."""
    await _login_new_admin(db_client, db_session)
    await _save_draft(db_client, "novel", rating_scope="story")

    drift = await _changes(db_client, "novel")

    assert _shape(drift) == [
        ("story", "story", "gemini", True),
        ("character", "character", "gemini", False),
    ]
    assert drift[0]["thisMd5"] != drift[0]["otherMd5"]


async def test_editing_the_story_chat_rule_differs_from_all_three_novel_chains_and_never_from_character(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """채팅 story 초안의 등급 규칙을 고치면 소설 세 체인의 scope story 등급 규칙 셋과 견주어 모두 다르다. 항목은 모두 scope
    story 이고 character 쪽과는 견주지 않는다. 손대기 전에는 셋 다 같다. 깨지는 시나리오: 소설 Claude 체인을 빼먹어 그 체인의
    등급 규칙만 옛 글로 남는 것을 못 보거나, story 규칙을 character 와도 견줘 늘 다르다고 한다."""
    await _login_new_admin(db_client, db_session)
    await _save_draft(db_client, "story")
    before = await _changes(db_client, "story")
    await _save_draft(db_client, "story", rating_scope="story")
    after = await _changes(db_client, "story")

    assert _shape(before) == [("story", "novel", m, False) for m in _NOVEL_MODELS]
    assert _shape(after) == [("story", "novel", m, True) for m in _NOVEL_MODELS]
    for item in after:
        other_id, other_md5 = await _active_rating_md5(db_session, "novel", item["otherModel"], scope="story")
        assert (item["otherSetId"], item["otherMd5"]) == (str(other_id), other_md5)


async def test_the_character_chat_chain_compares_only_against_the_character_scope(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _login_new_admin(db_client, db_session)
    await _save_draft(db_client, "character", rating_scope="character")

    drift = await _changes(db_client, "character")

    assert _shape(drift) == [("character", "novel", m, True) for m in _NOVEL_MODELS]


@pytest.mark.parametrize(
    ("lane", "model"),
    [
        pytest.param("story", "sonnet", id="story-sonnet"),
        pytest.param("character", "opus", id="character-opus"),
        pytest.param("story", "haiku", id="story-haiku"),
        pytest.param("publish_filter", "gemini", id="publish-filter"),
    ],
)
async def test_chains_outside_the_comparison_carry_an_empty_list(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: PromptLane, model: PromptSetModelId
) -> None:
    """등급 규칙 사본의 원본은 채팅 Gemini 체인이다 — Claude 채팅·판정 전용·심사 체인은 견주지 않고 게시 전 조회와 게시 응답에
    빈 목록을 싣는다."""
    await _login_new_admin(db_client, db_session)
    await _save_draft(db_client, lane, model)

    assert await _changes(db_client, lane, model) == []
    published = await db_client.post(f"/admin/prompt-sets/{lane}/publish", params={"model": model}, json={"note": "n"})
    assert published.status_code == 200, published.text
    assert published.json()["ratingDrift"] == []


async def test_publish_whole_restore_section_restore_and_changes_report_the_same_drift_without_blocking(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """같은 등급 규칙에 대해 게시 전 조회·게시 응답·그 판의 통째 복원·그 채널의 섹션 복원이 같은 어긋남을 싣는다. 다르다고
    해도 게시는 막지 않는다. 깨지는 시나리오: 경로마다 다른 함수로 계산해 화면 하나는 같다고, 다른 하나는 다르다고 하거나,
    어긋남을 거절로 바꿔 운영자가 등급 규칙을 한 곳씩 고쳐 게시할 수 없게 된다."""
    await _login_new_admin(db_client, db_session)
    await db_session.execute(
        sa.update(PromptSet)
        .where(PromptSet.status == "published")
        .values(published_at=PromptSet.published_at - timedelta(days=3))
    )
    await db_session.commit()
    await _save_draft(db_client, "novel", rating_scope="story")

    changes = await _changes(db_client, "novel")
    published = await db_client.post("/admin/prompt-sets/novel/publish", json={"note": "등급 규칙 손질"})
    assert published.status_code == 200, published.text
    published_id = published.json()["id"]
    whole = await db_client.post(f"/admin/prompt-sets/{published_id}/restore")
    section = await db_client.post(
        f"/admin/prompt-sets/{published_id}/sections/novelize_rating/restore", json={}
    )

    assert _shape(changes)[0] == ("story", "story", "gemini", True)
    assert whole.status_code == 200, whole.text
    assert section.status_code == 200, section.text
    assert published.json()["ratingDrift"] == changes
    assert whole.json()["ratingDrift"] == changes
    assert section.json()["ratingDrift"] == changes


async def test_draft_reads_and_saves_carry_an_empty_drift_list(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """어긋남은 게시·복원·게시 전 조회에만 싣는다 — 초안 조회와 저장, 세트 상세는 빈 목록이다."""
    await _login_new_admin(db_client, db_session)
    saved = await _save_draft(db_client, "novel", rating_scope="story")
    got = (await db_client.get("/admin/prompt-sets/novel/draft")).json()
    active, _ = await load_active_prompt_set(db_session, lane="novel")
    detail = (await db_client.get(f"/admin/prompt-sets/{active.id}")).json()

    assert saved["ratingDrift"] == got["ratingDrift"] == detail["ratingDrift"] == []


async def test_a_draft_rating_rule_that_does_not_render_marks_only_its_item_instead_of_failing_the_changes_read(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """초안 저장은 자리표시자를 검사하지 않아 짝 없는 중괄호가 든 등급 규칙도 저장된다 — 게시 전 변경 조회는 200 이고, 그 scope
    항목만 렌더 불가 표지(지문 없음, 다름)를 달고 다른 scope 항목은 그대로 견준다. 깨지는 시나리오: 렌더 예외가 그대로 올라가
    조회 전체가 500 이 되어 운영자가 무엇이 잘못됐는지 화면에서 볼 수 없다."""
    await _login_new_admin(db_client, db_session)
    draft = (await db_client.get("/admin/prompt-sets/novel/draft")).json()
    (row,) = [
        s
        for s in draft["sections"]
        if (s["channel"], s["slot"], s["scope"]) == ("novelize_rating", "rule_rating", "story")
    ]
    row["body"] += " 합성 문장 {"
    put = await db_client.put(
        "/admin/prompt-sets/novel/draft", json={"labels": draft["labels"], "sections": draft["sections"]}
    )
    assert put.status_code == 200, put.text

    drift = await _changes(db_client, "novel")

    assert [(item["scope"], item["unrenderable"], item["differs"]) for item in drift] == [
        ("story", True, True),
        ("character", False, False),
    ]
    assert drift[0]["thisMd5"] is None
    assert drift[0]["otherMd5"] is not None


async def test_the_novel_lane_now_checks_the_three_labels_it_reads_r5(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """소설 호출은 원문 줄 라벨을 소설 세트에서 읽으므로 소설 레인도 사용자·진행자·캐릭터 라벨을 게시 검사한다. 깨지는
    시나리오: 빈 진행자 라벨로 게시돼 다음 화 생성의 원문 줄이 `: 왔어?` 처럼 화자 없이 나간다."""
    await _login_new_admin(db_client, db_session)
    got = (await db_client.get("/admin/prompt-sets/novel/draft")).json()
    put = await db_client.put(
        "/admin/prompt-sets/novel/draft",
        json={"labels": {**got["labels"], "storyAssistantLabel": "   "}, "sections": got["sections"]},
    )
    assert put.status_code == 200, put.text

    resp = await db_client.post("/admin/prompt-sets/novel/publish", json={"note": "라벨 공백"})

    assert resp.status_code == 422
    assert resp.json()["detail"]["rule"] == "R-5"


# ---- 통째 복원의 채널 집합 -----------------------------------------------------------------------------------


async def _insert_old_novel_set(
    db_session: AsyncSession,
    model: PromptSetModelId,
    *,
    drop_channels: frozenset[str] = frozenset(),
    extra_channel: str | None = None,
) -> PromptSet:
    """그 체인 활성판을 베껴 활성판보다 하루 앞선 게시본을 넣는다(활성판은 그대로다). `drop_channels` 채널 행은 빼고,
    `extra_channel` 은 그 체인이 가질 수 없는 채널 행 하나를 더한다."""
    active, sections = await load_active_prompt_set(db_session, lane="novel", model=model)
    assert active.published_at is not None
    old = PromptSet(
        id=uuid.uuid4(),
        version=await admin_prompts._next_published_version(db_session),
        status="published",
        lane="novel",
        model=model,
        note="합성 옛 판",
        user_label=active.user_label,
        story_assistant_label=active.story_assistant_label,
        story_example_label=active.story_example_label,
        character_assistant_label=active.character_assistant_label,
        published_at=active.published_at - timedelta(days=1),
    )
    db_session.add(old)
    await db_session.flush()
    rows = [
        (s.channel, s.scope, s.slot, s.variant, s.body, s.conditional, s.order)
        for s in sections
        if s.channel not in drop_channels
    ]
    if extra_channel is not None:
        rows.append((extra_channel, "both", "instruction", "", "합성 잉여 문안", False, 0))
    for channel, scope, slot, variant, body, conditional, order in rows:
        db_session.add(
            PromptSection(
                id=uuid.uuid4(),
                prompt_set_id=old.id,
                channel=channel,
                scope=scope,
                slot=slot,
                variant=variant,
                body=body,
                conditional=conditional,
                order=order,
            )
        )
    await db_session.commit()
    return old


def _rows_of(sections: list[dict[str, Any]], channel: str) -> list[tuple[str, str, str, str, bool, int]]:
    return sorted(
        (s["scope"], s["slot"], s["variant"], s["body"], s["conditional"], s["order"])
        for s in sections
        if s["channel"] == channel
    )


async def test_restoring_a_novel_set_from_before_the_rating_channel_fills_it_from_the_active_set(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """등급 규칙 채널이 없던 옛 소설 판을 통째로 복원하면 그 채널을 활성판 행으로 채우고 응답에 이름을 싣는다 — 초안이 게시
    검사를 통과한다. 깨지는 시나리오: 소설 레인이 등급 규칙을 읽게 된 뒤 옛 판 통째 복원이 늘 "누락"으로 막히고, 화면에는 그
    채널을 되살릴 손이 없다."""
    await _login_new_admin(db_client, db_session)
    _, active_sections = await load_active_prompt_set(db_session, lane="novel")
    active_rows = _rows_of(
        [
            {"channel": s.channel, "scope": s.scope, "slot": s.slot, "variant": s.variant, "body": s.body,
             "conditional": s.conditional, "order": s.order}
            for s in active_sections
        ],
        "novelize_rating",
    )
    old = await _insert_old_novel_set(db_session, "gemini", drop_channels=frozenset({"novelize_rating"}))

    restored = await db_client.post(f"/admin/prompt-sets/{old.id}/restore")

    assert restored.status_code == 200, restored.text
    body = restored.json()
    assert (body["filledChannels"], body["droppedChannels"]) == (["novelize_rating"], [])
    assert _rows_of(body["sections"], "novelize_rating") == active_rows
    published = await db_client.post("/admin/prompt-sets/novel/publish", json={"note": "옛 판 되돌림"})
    assert published.status_code == 200, published.text


async def test_restoring_a_set_with_a_channel_the_chain_cannot_have_drops_it(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """그 체인의 기대 채널 밖 채널이 든 판을 통째로 복원하면 그 채널을 버리고 응답에 이름을 싣는다. 깨지는 시나리오: 잉여
    채널이 초안에 들어가 게시가 "잉여"로 막히는데, 화면에는 섹션을 지우는 손이 없다."""
    await _login_new_admin(db_client, db_session)
    old = await _insert_old_novel_set(db_session, "sonnet", extra_channel="stat_judgment")

    restored = await db_client.post(f"/admin/prompt-sets/{old.id}/restore")

    assert restored.status_code == 200, restored.text
    body = restored.json()
    assert (body["droppedChannels"], body["filledChannels"]) == (["stat_judgment"], [])
    assert not [s for s in body["sections"] if s["channel"] == "stat_judgment"]
    published = await db_client.post("/admin/prompt-sets/novel/publish", params={"model": "sonnet"}, json={"note": "n"})
    assert published.status_code == 200, published.text


async def test_restoring_a_set_with_the_same_channel_set_drops_and_fills_nothing(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _login_new_admin(db_client, db_session)
    active, active_sections = await load_active_prompt_set(db_session, lane="novel", model="opus")

    restored = await db_client.post(f"/admin/prompt-sets/{active.id}/restore")

    assert restored.status_code == 200, restored.text
    body = restored.json()
    assert (body["droppedChannels"], body["filledChannels"]) == ([], [])
    assert len(body["sections"]) == len(active_sections)
