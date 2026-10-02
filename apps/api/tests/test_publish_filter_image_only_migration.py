"""발행 심사를 이미지 전용으로 바꾸는 데이터 마이그레이션 `859b0fb86629`의 검증.

마이그레이션 자체는 다시 돌리지 않는다(`test_media_book_filter_prompt_migration.py`와 같은 방식). 세션 스코프
스키마(`_migrated_schema`)가 이미 `upgrade head`를 했으므로 "마이그레이션 뒤 DB 상태"를 단언하고, 되돌리기·변환
함수는 테스트마다 롤백되는 `db_session`의 커넥션에 `run_sync`로 직접 부른다.

테스트 DB 의 publish_filter 세트는 레인을 나눈 리비전의 16행 세트(`a69cbd40dec8`)와 미디어 북 칸 슬롯을 더한 17행
세트(`bd29dd69bc0f`) 둘이고, 둘 다 시드 문안 그대로다 — 운영과 달리 여기서는 시드 문안을 가정해도 참이다."""

import importlib.util
import uuid
from pathlib import Path
from string import Formatter
from types import ModuleType

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.prompts import _validate_prompt_draft_for_publish
from api.chat.prompt_builder import load_active_prompt_set, render_prompt_channel
from api.db.models.prompt import PromptSection, PromptSet, PublishFilterTextSectionBackup
from factories import _create_admin, _login_as_admin

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("859b0fb86629")
_SEED_SET_ID: uuid.UUID = _load("a69cbd40dec8").NEW_SET_IDS["publish_filter"]
_MEDIA_BOOK_SET_ID: uuid.UUID = _load("bd29dd69bc0f").NEW_SET_ID

# 시드 문안 — 서두·판정 본문은 변환이 한 글자도 바꾸지 않아야 한다.
_SEED_BODIES: dict[tuple[str, str], str] = {
    (row["scope"], row["slot"]): row["body"]
    for row in _load("bd258b26c34a").SEED_SECTIONS
    if row["channel"] == "publish_filter" and row["slot"] in ("intro_instruction", "verdict_instruction")
}

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
_MEDIA_BOOK_LAYOUT: list[tuple[str, str, str, str, int]] = [
    *(row if row[2] != "verdict_instruction" else (*row[:4], 16) for row in _SEED_LAYOUT),
    ("publish_filter", "story", "media_book", "", 15),
]
_SET_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

_Row = tuple[uuid.UUID, str, str, str, str, str, bool, int]


async def _rows_of(db_session: AsyncSession, set_id: uuid.UUID) -> set[_Row]:
    """섹션 id 까지 포함한 그 세트의 행 전부."""
    db_session.expire_all()
    sections = (await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))).all()
    return {(s.id, s.channel, s.scope, s.slot, s.variant, s.body, s.conditional, s.order) for s in sections}


async def _backup_rows_of(db_session: AsyncSession, set_id: uuid.UUID) -> set[_Row]:
    backups = (
        await db_session.scalars(
            sa.select(PublishFilterTextSectionBackup).where(PublishFilterTextSectionBackup.prompt_set_id == set_id)
        )
    ).all()
    return {(b.id, b.channel, b.scope, b.slot, b.variant, b.body, b.conditional, b.order) for b in backups}


def _slots(rows: set[_Row]) -> dict[tuple[str, str], tuple[str, int]]:
    return {(scope, slot): (body, order) for _, _, scope, slot, _, body, _, order in rows}


# ---- 가드 ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "layout",
    [pytest.param(_SEED_LAYOUT, id="16-rows"), pytest.param(_MEDIA_BOOK_LAYOUT, id="17-rows")],
)
def test_assert_layout_accepts_both_layouts_and_puts_the_list_after_the_intro(
    layout: list[tuple[str, str, str, str, int]],
) -> None:
    assert _M._assert_layout(_SET_ID, layout) == 2


def test_assert_layout_follows_a_moved_intro() -> None:
    """목록 자리는 고정 order 가 아니라 서두 order 중 큰 값 바로 뒤다(운영자가 어드민에서 order 를 바꿀 수 있다)."""
    moved = [(c, s, slot, v, 5 if (s, slot) == ("story", "intro_instruction") else o) for c, s, slot, v, o in _SEED_LAYOUT]
    assert _M._assert_layout(_SET_ID, moved) == 6


@pytest.mark.parametrize(
    "layout",
    [
        pytest.param([row for row in _SEED_LAYOUT if row[2] != "rules"], id="missing-slot"),
        pytest.param([*_SEED_LAYOUT, ("publish_filter", "both", "image_list", "", 2)], id="already-converted"),
        pytest.param([*_SEED_LAYOUT, ("generation", "both", "history", "", 3)], id="other-channel"),
        pytest.param([*_SEED_LAYOUT, _SEED_LAYOUT[2]], id="duplicate-row"),
        pytest.param(
            [(c, s, slot, v, 2 if slot == "verdict_instruction" else o) for c, s, slot, v, o in _SEED_LAYOUT],
            id="no-room-before-verdict",
        ),
    ],
)
def test_assert_layout_raises_on_an_unexpected_layout(layout: list[tuple[str, str, str, str, int]]) -> None:
    """본문이 아니라 슬롯 집합과 순서만 본다. 어긋나면 세트 id 를 알리며 멈춘다."""
    with pytest.raises(RuntimeError, match=str(_SET_ID)):
        _M._assert_layout(_SET_ID, layout)


# ---- 마이그레이션 뒤 DB 상태 ------------------------------------------------------------------------


async def test_active_set_is_the_new_image_only_set(db_session: AsyncSession) -> None:
    """새 문안이 새 게시 세트로 활성이 되고, 그 세트는 게시 검증을 그대로 통과한다(어드민 복원·재게시 가능)."""
    active, sections = await load_active_prompt_set(db_session, lane="publish_filter")
    assert active.id == _M.NEW_SET_ID
    assert active.version == "8"
    assert active.note == _M._NOTE
    assert {(s.scope, s.slot): (s.body, s.order) for s in sections} == {
        ("character", "intro_instruction"): (_M.CHARACTER_INTRO_BODY, 1),
        ("story", "intro_instruction"): (_M.STORY_INTRO_BODY, 1),
        ("both", "image_list"): (_M.IMAGE_LIST_BODY, 2),
        ("both", "verdict_instruction"): (_M.VERDICT_BODY, 3),
    }
    _validate_prompt_draft_for_publish(active, sections, lane="publish_filter")
    placeholders = {
        s.slot: [name for _, name, _, _ in Formatter().parse(s.body) if name is not None] for s in sections
    }
    assert placeholders == {
        "intro_instruction": [],
        "image_list": ["image_lines"],
        "verdict_instruction": [],
    }


@pytest.mark.parametrize("scope", ["character", "story"])
async def test_new_intro_screens_images_only_and_leaves_fit_out(db_session: AsyncSession, scope: str) -> None:
    """서두는 캐릭터·스토리 모두 그림만 심사하고, 라벨은 식별용이며, 그림이 작품과 어울리는지는 보지 않는다고 적는다."""
    _, sections = await load_active_prompt_set(db_session, lane="publish_filter")

    rendered = render_prompt_channel(sections, channel="publish_filter", scope=scope, values={"image_lines": "<목록>"})

    assert "그림이 작품과 어울리는지는 심사 대상이 아니다" in rendered
    assert "라벨은 이미지를 가리키기 위한 식별용이며 심사 대상이 아니다" in rendered
    assert "목록의 라벨로" in rendered
    assert rendered.index("[첨부 이미지 목록]") < rendered.index("<목록>") < rendered.index("passed=true")


@pytest.mark.parametrize(
    ("set_id", "verdict_order", "backup_count"),
    [
        pytest.param(_SEED_SET_ID, 15, 13, id="16-row-set"),
        pytest.param(_MEDIA_BOOK_SET_ID, 16, 14, id="17-row-set"),
    ],
)
async def test_old_sets_keep_their_intro_and_verdict_and_gain_the_list(
    db_session: AsyncSession, set_id: uuid.UUID, verdict_order: int, backup_count: int
) -> None:
    """옛 세트는 서두·판정의 본문과 order 를 그대로 두고 이미지 목록 행만 얻는다. 작가 글 행은 전부 백업에 있다."""
    assert _slots(await _rows_of(db_session, set_id)) == {
        ("character", "intro_instruction"): (_SEED_BODIES[("character", "intro_instruction")], 1),
        ("story", "intro_instruction"): (_SEED_BODIES[("story", "intro_instruction")], 1),
        ("both", "image_list"): (_M.IMAGE_LIST_BODY, 2),
        ("both", "verdict_instruction"): (_SEED_BODIES[("both", "verdict_instruction")], verdict_order),
    }
    backups = await _backup_rows_of(db_session, set_id)
    assert len(backups) == backup_count
    assert not {slot for _, _, _, slot, _, _, _, _ in backups} & {"intro_instruction", "verdict_instruction"}


async def test_legacy_set_is_untouched(db_session: AsyncSession) -> None:
    """legacy 세트에도 publish_filter channel 행이 있지만 아무도 렌더하지 않는다 — 레인으로 걸러 손대지 않는다."""
    legacy_ids = (
        await db_session.scalars(sa.select(PromptSet.id).where(PromptSet.lane == "legacy", PromptSet.status == "published"))
    ).all()
    assert legacy_ids
    for legacy_id in legacy_ids:
        rows = await _rows_of(db_session, legacy_id)
        assert len(rows) == 48
        assert len([row for row in rows if row[1] == "publish_filter"]) == 16
        assert await _backup_rows_of(db_session, legacy_id) == set()


# ---- 되돌리기 ------------------------------------------------------------------------------


async def test_restore_brings_back_the_old_sets_exactly_and_drops_the_new_set(db_session: AsyncSession) -> None:
    """되돌리면 옛 세트가 원래 id·순서·본문 그대로 16행·17행으로 돌아오고, 새 세트는 사라져 직전 세트가 다시 활성이다."""
    expected = {}
    for set_id in (_SEED_SET_ID, _MEDIA_BOOK_SET_ID):
        current = {row for row in await _rows_of(db_session, set_id) if row[3] != "image_list"}
        expected[set_id] = current | await _backup_rows_of(db_session, set_id)

    connection = await db_session.connection()
    await connection.run_sync(_M._restore_sets)

    assert await _rows_of(db_session, _SEED_SET_ID) == expected[_SEED_SET_ID]
    assert len(expected[_SEED_SET_ID]) == 16
    assert await _rows_of(db_session, _MEDIA_BOOK_SET_ID) == expected[_MEDIA_BOOK_SET_ID]
    assert len(expected[_MEDIA_BOOK_SET_ID]) == 17
    assert await db_session.get(PromptSet, _M.NEW_SET_ID) is None
    assert await _rows_of(db_session, _M.NEW_SET_ID) == set()
    assert (await db_session.scalar(sa.select(sa.func.count()).select_from(PublishFilterTextSectionBackup))) == 0
    active, _ = await load_active_prompt_set(db_session, lane="publish_filter")
    assert active.id == _MEDIA_BOOK_SET_ID


async def test_convert_after_restore_reproduces_the_head_state(db_session: AsyncSession) -> None:
    """되돌린 뒤 다시 변환하면 head 상태가 행 id 까지 그대로 나온다(왕복)."""
    head = {set_id: await _rows_of(db_session, set_id) for set_id in (_SEED_SET_ID, _MEDIA_BOOK_SET_ID, _M.NEW_SET_ID)}
    head_backups = {set_id: await _backup_rows_of(db_session, set_id) for set_id in (_SEED_SET_ID, _MEDIA_BOOK_SET_ID)}
    connection = await db_session.connection()
    await connection.run_sync(_M._restore_sets)

    converted = await connection.run_sync(_M._convert_sets)
    await connection.run_sync(_M._publish_new_set)

    assert sorted(converted) == sorted([_SEED_SET_ID, _MEDIA_BOOK_SET_ID])
    for set_id, rows in head.items():
        assert await _rows_of(db_session, set_id) == rows
    for set_id, rows in head_backups.items():
        assert await _backup_rows_of(db_session, set_id) == rows


async def test_convert_stops_on_a_draft_with_an_unexpected_layout(db_session: AsyncSession) -> None:
    """초안도 변환 대상이라 같은 가드를 받는다 — 어긋난 초안이 있으면 아무것도 바꾸지 않고 그 초안 id 로 멈춘다."""
    connection = await db_session.connection()
    await connection.run_sync(_M._restore_sets)
    draft = PromptSet(
        version=None,
        status="draft",
        lane="publish_filter",
        user_label="사용자",
        story_assistant_label="진행자",
        story_example_label="서술자",
        character_assistant_label="캐릭터",
    )
    db_session.add(draft)
    await db_session.flush()
    draft_id = draft.id
    for channel, scope, slot, variant, order in _SEED_LAYOUT:
        if slot != "rules":
            db_session.add(
                PromptSection(
                    prompt_set_id=draft_id,
                    channel=channel,
                    scope=scope,
                    slot=slot,
                    variant=variant,
                    body=f"<{slot}>",
                    conditional=False,
                    order=order,
                )
            )
    await db_session.flush()
    before = await _rows_of(db_session, _SEED_SET_ID)

    with pytest.raises(RuntimeError, match=str(draft_id)):
        await connection.run_sync(_M._convert_sets)

    assert await _rows_of(db_session, _SEED_SET_ID) == before


async def test_restore_stops_when_a_set_was_published_after_the_upgrade(db_session: AsyncSession) -> None:
    """업그레이드 뒤 운영자가 게시한 발행 심사 세트가 있으면 되돌리기는 그 id 를 알리며 멈추고 아무것도 지우지 않는다 —
    그 세트가 활성으로 남으면 옛 코드의 발행이 전부 실패하고, 게시 이력을 마이그레이션이 몰래 지우지도 않는다."""
    active, sections = await load_active_prompt_set(db_session, lane="publish_filter")
    later = PromptSet(
        version="99",
        status="published",
        lane="publish_filter",
        user_label=active.user_label,
        story_assistant_label=active.story_assistant_label,
        story_example_label=active.story_example_label,
        character_assistant_label=active.character_assistant_label,
        published_at=active.published_at,
    )
    db_session.add(later)
    await db_session.flush()
    later_id = later.id
    for s in sections:
        db_session.add(
            PromptSection(
                prompt_set_id=later_id,
                channel=s.channel,
                scope=s.scope,
                slot=s.slot,
                variant=s.variant,
                body=s.body,
                conditional=s.conditional,
                order=s.order,
            )
        )
    await db_session.flush()

    connection = await db_session.connection()
    with pytest.raises(RuntimeError, match=str(later_id)):
        await connection.run_sync(_M._restore_sets)

    assert await db_session.get(PromptSet, _M.NEW_SET_ID) is not None
    assert len(await _backup_rows_of(db_session, _SEED_SET_ID)) == 13


# ---- 옛 버전 복원 ------------------------------------------------------------------------------


@pytest.mark.parametrize("set_id", [pytest.param(_SEED_SET_ID, id="16-row-set"), pytest.param(_MEDIA_BOOK_SET_ID, id="17-row-set")])
async def test_converted_old_set_can_be_restored_and_published(
    db_client: httpx.AsyncClient, db_session: AsyncSession, set_id: uuid.UUID
) -> None:
    """변환된 옛 버전은 어드민에서 복원해 다시 게시할 수 있다 — 슬롯 집합이 지금 코드의 표와 같다."""
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    restored = await db_client.post(f"/admin/prompt-sets/{set_id}/restore")
    assert restored.status_code == 200
    published = await db_client.post("/admin/prompt-sets/publish_filter/publish", json={"note": "옛 버전 복원"})
    assert published.status_code == 200
