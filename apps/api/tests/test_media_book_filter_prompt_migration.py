"""publish_filter 레인에 미디어 북 슬롯(`media_book` 1행)을 넣는 데이터 마이그레이션 `bd29dd69bc0f`의 검증.

마이그레이션 자체는 다시 돌리지 않는다(`test_media_judgment_prompt_migration.py`와 같은 방식). 세션 스코프
스키마(`_migrated_schema`)가 이미 `upgrade head`를 했으므로 published 분기는 "마이그레이션 뒤 DB 상태"를
단언하고, 순수 함수·`_patch_draft`·`_delete_draft_rows`는 직접 부른다(뒤 둘은 테스트마다 롤백되는
`db_session`의 커넥션에 `run_sync`로).

head 에서는 발행 심사를 이미지 전용으로 바꾼 뒤 리비전(`859b0fb86629`)이 publish_filter 세트의 작가 글 슬롯 행을
백업 테이블로 옮겨 두었다. 그래서 이 리비전이 만든 세트는 지금 섹션과 백업 행을 합쳐 본다. 초안 경로는 이 리비전
이전 배치를 손으로 만든 초안으로 시험한다 — head 의 세트를 복제하면 이미 이미지 전용 배치라 가드가 먼저 멈춘다."""

import importlib.util
import uuid
from pathlib import Path
from string import Formatter
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import PromptLane, load_active_prompt_set
from api.db.models.prompt import PromptSection, PromptSet, PublishFilterTextSectionBackup

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("bd29dd69bc0f")
# 이 리비전이 복사한 원본 — publish_filter 레인은 레인을 나눈 리비전이 심은 세트 하나뿐이었다.
_PREVIOUS_SET_ID: uuid.UUID = _load("a69cbd40dec8").NEW_SET_IDS["publish_filter"]
_STORY_SET_ID: uuid.UUID = _load("2519dde454e0").NEW_SET_ID

_NEW_KEY = ("publish_filter", "story", "media_book", "")
_VERDICT_KEY = ("publish_filter", "both", "verdict_instruction", "")

# 이 리비전 이전 publish_filter 세트의 배치(`(channel, scope, slot, variant, order)`) — 레인을 나눈 리비전이 심은
# 그대로다. 가드 테스트는 여기서 한 칸씩 어긋나게 만든다.
_SEED_LAYOUT: list[tuple[str, str, str, str, int]] = [
    ("publish_filter", "character", "intro_instruction", "", 1),
    ("publish_filter", "story", "intro_instruction", "", 1),
    ("publish_filter", "both", "name", "", 2),
    ("publish_filter", "both", "one_liner", "", 3),
    ("publish_filter", "character", "intro", "", 4),
    ("publish_filter", "story", "setting_text", "", 5),
    ("publish_filter", "story", "development_example_legacy", "", 6),
    ("publish_filter", "story", "custom_prompt", "", 7),
    ("publish_filter", "story", "rules", "", 8),
    ("publish_filter", "story", "user_goal", "", 9),
    ("publish_filter", "story", "development_examples_pairs", "", 10),
    ("publish_filter", "character", "example_dialogues", "", 11),
    ("publish_filter", "character", "character_prompt", "", 12),
    ("publish_filter", "both", "detail_description", "", 13),
    ("publish_filter", "story", "starting_setups", "", 14),
    ("publish_filter", "both", "verdict_instruction", "", 15),
]


async def _sections_of(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    db_session.expire_all()
    return list((await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))).all())


def _keyed(sections: list[PromptSection]) -> dict[tuple[str, str, str, str], tuple[str, bool, int]]:
    return {(s.channel, s.scope, s.slot, s.variant): (s.body, s.conditional, s.order) for s in sections}


async def _before_image_only(
    db_session: AsyncSession, set_id: uuid.UUID
) -> dict[tuple[str, str, str, str], tuple[str, bool, int]]:
    """이미지 전용 리비전 이전의 그 세트 — 지금 섹션에서 그 리비전이 더한 `image_list` 를 빼고 백업 행을 합친다."""
    keyed = _keyed(await _sections_of(db_session, set_id))
    del keyed[("publish_filter", "both", "image_list", "")]
    backups = (
        await db_session.scalars(
            sa.select(PublishFilterTextSectionBackup).where(PublishFilterTextSectionBackup.prompt_set_id == set_id)
        )
    ).all()
    return keyed | {(b.channel, b.scope, b.slot, b.variant): (b.body, b.conditional, b.order) for b in backups}


# ---- 문안 성질 --------------------------------------------------------------------------------


def test_media_book_body_uses_exactly_the_allowed_placeholder() -> None:
    """렌더 `values`에 없는 이름이 body 에 있으면 그 발행의 심사 렌더가 실패한다(발행 500). 플레이스홀더가
    하나도 없으면 미디어 북이 없는 스토리에서도 섹션이 드롭되지 않는다."""
    assert [name for _, name, _, _ in Formatter().parse(_M.MEDIA_BOOK_BODY) if name] == ["media_book_lines"]


# ---- 가드 ----------------------------------------------------------------------------------------


def test_assert_layout_returns_the_current_order_of_the_verdict_row() -> None:
    assert _M._assert_layout(_SEED_LAYOUT) == 15


def test_assert_layout_follows_a_moved_verdict_row() -> None:
    """삽입 자리는 절대 order 가 아니라 판정 지시문 행의 지금 order 다(운영자가 어드민에서 order 를 바꿀 수 있다)."""
    moved = [(c, s, slot, v, 20 if slot == "verdict_instruction" else o) for c, s, slot, v, o in _SEED_LAYOUT]
    assert _M._assert_layout(moved) == 20


def test_assert_layout_raises_when_the_slot_is_already_there() -> None:
    with pytest.raises(RuntimeError, match="media_book 행이 이미 있다"):
        _M._assert_layout([*_SEED_LAYOUT, ("publish_filter", "story", "media_book", "", 15)])


def test_assert_layout_raises_when_a_slot_is_missing() -> None:
    with pytest.raises(RuntimeError, match="슬롯 집합"):
        _M._assert_layout([row for row in _SEED_LAYOUT if row[2] != "rules"])


def test_assert_layout_raises_when_starting_setups_is_not_before_the_verdict() -> None:
    """미디어 북 줄은 시작 설정 뒤·판정 지시문 앞에 둔다 — 둘을 동시에 만족할 수 없는 배치면 멈춘다."""
    swapped = [(c, s, slot, v, 16 if slot == "starting_setups" else o) for c, s, slot, v, o in _SEED_LAYOUT]
    with pytest.raises(RuntimeError, match="starting_setups"):
        _M._assert_layout(swapped)


def test_build_published_rows_shifts_rows_from_the_insert_order_and_adds_one_row() -> None:
    source = [
        ("publish_filter", "story", "starting_setups", "", "body:setups", True, 14),
        ("publish_filter", "both", "verdict_instruction", "", "body:verdict", False, 15),
        ("publish_filter", "character", "intro_instruction", "", "body:intro", False, 1),
    ]
    set_id = uuid.UUID("00000000-0000-0000-0000-000000000003")

    built = _M._build_published_rows(source, set_id, 15)

    assert all(row["prompt_set_id"] == set_id for row in built)
    assert len({row["id"] for row in built}) == len(built)
    assert [
        (r["channel"], r["scope"], r["slot"], r["variant"], r["body"], r["conditional"], r["order"]) for r in built
    ] == [
        ("publish_filter", "story", "starting_setups", "", "body:setups", True, 14),
        ("publish_filter", "both", "verdict_instruction", "", "body:verdict", False, 16),
        ("publish_filter", "character", "intro_instruction", "", "body:intro", False, 1),
        ("publish_filter", "story", "media_book", "", _M.MEDIA_BOOK_BODY, True, 15),
    ]


# ---- 마이그레이션 뒤 DB 상태 — published 분기 ----------------------------------------------------


async def test_this_revisions_set_carries_the_media_book_row(db_session: AsyncSession) -> None:
    """회귀 방지 — 이 리비전이 만든 세트(지금 섹션 + 뒤 리비전이 백업으로 옮긴 행)는 판정 지시문의 order 가 하나
    밀린 것과 `media_book` 행 말고는 원본과 바이트까지 같다. 활성은 아니지만 어드민에서 복원할 수 있는 옛 버전이다."""
    this_set = await db_session.get(PromptSet, _M.NEW_SET_ID)
    assert this_set is not None
    assert this_set.note == _M._NOTE
    assert this_set.version == "7"

    source_set = await db_session.get(PromptSet, _PREVIOUS_SET_ID)
    assert source_set is not None
    labels = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")
    assert [getattr(this_set, a) for a in labels] == [getattr(source_set, a) for a in labels]

    new = await _before_image_only(db_session, _M.NEW_SET_ID)
    old = await _before_image_only(db_session, _PREVIOUS_SET_ID)
    assert new.pop(_NEW_KEY) == (_M.MEDIA_BOOK_BODY, True, 15)
    verdict_body, verdict_conditional, verdict_order = old.pop(_VERDICT_KEY)
    assert new.pop(_VERDICT_KEY) == (verdict_body, verdict_conditional, verdict_order + 1)
    assert new == old


async def test_other_lanes_keep_their_active_sets(db_session: AsyncSession) -> None:
    story, _ = await load_active_prompt_set(db_session, lane="story")
    assert story.id == _STORY_SET_ID


# ---- `_patch_draft` ------------------------------------------------------------------------


async def _make_draft(
    db_session: AsyncSession, lane: PromptLane, layout: list[tuple[str, str, str, str, int]]
) -> uuid.UUID:
    """`layout` 배치의 초안. 본문은 슬롯마다 다른 표지 글이다."""
    draft = PromptSet(
        version=None,
        status="draft",
        lane=lane,
        user_label="사용자",
        story_assistant_label="진행자",
        story_example_label="서술자",
        character_assistant_label="캐릭터",
    )
    db_session.add(draft)
    await db_session.flush()
    draft_id = draft.id
    for channel, scope, slot, variant, order in layout:
        db_session.add(
            PromptSection(
                prompt_set_id=draft_id,
                channel=channel,
                scope=scope,
                slot=slot,
                variant=variant,
                body=f"<{slot}/{scope}>",
                conditional=False,
                order=order,
            )
        )
    await db_session.flush()
    return draft_id


async def test_patch_draft_adds_the_row_in_place(db_session: AsyncSession) -> None:
    """이 리비전 이전 배치의 초안에 1행이 판정 지시문 자리에 들어가고 판정 지시문만 한 칸 밀린다."""
    draft_id = await _make_draft(db_session, "publish_filter", _SEED_LAYOUT)
    before = _keyed(await _sections_of(db_session, draft_id))

    connection = await db_session.connection()
    assert await connection.run_sync(_M._patch_draft) is True

    after = _keyed(await _sections_of(db_session, draft_id))
    assert after.pop(_NEW_KEY) == (_M.MEDIA_BOOK_BODY, True, 15)
    verdict_body, verdict_conditional, verdict_order = before.pop(_VERDICT_KEY)
    assert after.pop(_VERDICT_KEY) == (verdict_body, verdict_conditional, verdict_order + 1)
    assert after == before


async def test_patch_draft_leaves_other_lane_drafts_alone(db_session: AsyncSession) -> None:
    """story 초안만 있으면 할 일이 없다 — 레인 조건이 빠지면 story 초안을 publish_filter 배치로 검사하다 멈추거나
    엉뚱한 레인에 행을 넣는다."""
    story_draft = await _make_draft(db_session, "story", _SEED_LAYOUT)
    before = _keyed(await _sections_of(db_session, story_draft))

    connection = await db_session.connection()
    assert await connection.run_sync(_M._patch_draft) is False

    assert _keyed(await _sections_of(db_session, story_draft)) == before


async def test_patch_draft_raises_when_the_draft_already_has_the_slot(db_session: AsyncSession) -> None:
    await _make_draft(db_session, "publish_filter", [*_SEED_LAYOUT, ("publish_filter", "story", "media_book", "", 15)])

    connection = await db_session.connection()
    with pytest.raises(RuntimeError, match="media_book 행이 이미 있다"):
        await connection.run_sync(_M._patch_draft)


# ---- 되돌리기 ------------------------------------------------------------------------------


async def test_delete_draft_rows_restores_the_draft_layout(db_session: AsyncSession) -> None:
    """되돌리기는 publish_filter 초안의 미디어 북 행을 지우고 판정 지시문 order 를 되돌린다 — 초안 upsert 가
    섹션을 통째로 바꿔 PK 가 달라졌을 수 있어 PK 가 아니라 슬롯으로 찾는다. published 세트 행은 남는다."""
    draft_id = await _make_draft(db_session, "publish_filter", _SEED_LAYOUT)
    original = _keyed(await _sections_of(db_session, draft_id))
    connection = await db_session.connection()
    await connection.run_sync(_M._patch_draft)
    published_before = _keyed(await _sections_of(db_session, _M.NEW_SET_ID))

    await connection.run_sync(_M._delete_draft_rows)

    assert _keyed(await _sections_of(db_session, draft_id)) == original
    assert _keyed(await _sections_of(db_session, _M.NEW_SET_ID)) == published_before
