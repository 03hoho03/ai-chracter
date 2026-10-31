"""채팅 글쓰기 모델 Haiku 의 프롬프트 체인 둘(story·character)을 심는 데이터 마이그레이션 `45e57ce4d815` 의 검증.

마이그레이션 자체는 다시 돌리지 않는다(앞의 문안 리비전 테스트와 같은 방식). 세션 스코프 스키마(`_migrated_schema`)가 이미
`upgrade head` 를 했으므로 시드는 "마이그레이션 뒤 DB 상태"를 단언하고, `seed_published_sets`·`delete_seeded_rows` 는 테스트마다
롤백되는 `db_session` 의 커넥션에 `run_sync` 로 직접 부른다.

기대값은 마이그레이션의 행 조립으로 만들지 않는다 — DB 에 있는 Sonnet 활성 세트를 이 파일이 따로 읽어 견준다."""

import importlib.util
import uuid
from datetime import timedelta
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.prompts import _validate_prompt_draft_for_publish
from api.chat.prompt_builder import PromptLane, load_active_prompt_set
from api.db.models.prompt import PromptSection, PromptSet, PromptSetSemver
from api.llm.chat_models import PromptSetModelId
from factories import seed_revisions_above, undo_seeded_rows_above

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("45e57ce4d815")
_LANES: tuple[PromptLane, ...] = ("story", "character")
_LABELS = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")
# 이 리비전 아래의 시드 리비전 하나(채팅 레인 판정 전용 체인을 심은 리비전). 그 리비전 테스트의 "직후 상태" 되돌리기가 이 리비전의
# 시드도 지우는지 본다.
_OLDER_SEED_REVISION = "1a843a0b2d8f"

Row = tuple[str, str, str, str, str, bool, int]


@pytest.fixture(autouse=True)
async def _undo_later_revisions(db_session: AsyncSession) -> None:
    await (await db_session.connection()).run_sync(undo_seeded_rows_above, _M.revision)


def _rows(sections: list[PromptSection]) -> list[Row]:
    return sorted((s.channel, s.scope, s.slot, s.variant, s.body, s.conditional, s.order) for s in sections)


async def _count(db_session: AsyncSession, sql: str) -> int:
    return int((await db_session.execute(sa.text(sql))).scalar_one())


async def _lane_only_active(db_session: AsyncSession, lane: str) -> uuid.UUID:
    found: uuid.UUID = (
        await db_session.execute(
            sa.text(
                "SELECT id FROM prompt_sets WHERE status = 'published' AND lane = :lane"
                " ORDER BY published_at DESC LIMIT 1"
            ),
            {"lane": lane},
        )
    ).scalar_one()
    return found


@pytest.mark.parametrize("lane", _LANES)
async def test_each_chat_lane_gets_a_byte_copy_of_its_sonnet_active_set(
    db_session: AsyncSession, lane: PromptLane
) -> None:
    """라벨 넷과 모든 채널 행이 Sonnet 활성 세트와 바이트·order 까지 같다 — 판정·요약 채널도 함께(게시 검증이 요구한다)."""
    seeded, seeded_sections = await load_active_prompt_set(db_session, lane=lane, model="haiku_writer")
    source, source_sections = await load_active_prompt_set(db_session, lane=lane, model="sonnet")

    assert seeded.id == _M.NEW_SET_IDS[lane]
    assert (seeded.status, seeded.model) == ("published", "haiku_writer")
    assert [getattr(seeded, label) for label in _LABELS] == [getattr(source, label) for label in _LABELS]
    assert _rows(seeded_sections) == _rows(source_sections)
    assert {"system", "generation"} <= {s.channel for s in seeded_sections}


@pytest.mark.parametrize("lane", _LANES)
async def test_the_seed_copies_sonnet_even_when_the_other_writing_chains_differ_from_it(
    db_session: AsyncSession, lane: PromptLane
) -> None:
    """테스트 DB 에서는 글쓰기 체인들의 활성 세트가 같은 행일 수 있어, 위 바이트 비교만으로는 어느 체인을 베꼈는지 가리지 못한다.
    Opus·Gemini 활성 세트의 생성 채널 행 하나와 라벨 하나를 바꿔 Sonnet 과 다르게 만든 뒤 다시 심으면 사본은 Sonnet 과만 같다."""
    connection = await db_session.connection()
    await connection.run_sync(_M.delete_seeded_rows)
    others: tuple[PromptSetModelId, ...] = ("opus", "gemini")
    for model in others:
        other, other_sections = await load_active_prompt_set(db_session, lane=lane, model=model)
        target = next(s for s in other_sections if s.channel == "generation")
        target.body = f"{target.body}\n{model} 만 다른 줄"
        other.user_label = f"{other.user_label}·{model}"
    await db_session.flush()

    await connection.run_sync(_M.seed_published_sets)

    db_session.expire_all()
    seeded, seeded_sections = await load_active_prompt_set(db_session, lane=lane, model="haiku_writer")
    sonnet, sonnet_sections = await load_active_prompt_set(db_session, lane=lane, model="sonnet")
    assert seeded.id == _M.NEW_SET_IDS[lane]
    assert _rows(seeded_sections) == _rows(sonnet_sections)
    assert seeded.user_label == sonnet.user_label
    for model in others:
        other, other_sections = await load_active_prompt_set(db_session, lane=lane, model=model)
        assert _rows(seeded_sections) != _rows(other_sections), model
        assert seeded.user_label != other.user_label, model


@pytest.mark.parametrize("lane", _LANES)
async def test_the_seed_is_published_a_second_before_gemini_so_lane_only_reads_still_pick_gemini(
    db_session: AsyncSession, lane: PromptLane
) -> None:
    """모델로 거르는 조회는 체인에 세트가 하나라 늘 시드를 고르고, 모델 열을 모르는 레인만 보는 옛 조회는 시드를 집지 않는다."""
    seeded, _ = await load_active_prompt_set(db_session, lane=lane, model="haiku_writer")
    gemini, _ = await load_active_prompt_set(db_session, lane=lane, model="gemini")

    assert seeded.published_at is not None and gemini.published_at is not None
    assert seeded.published_at == gemini.published_at - timedelta(seconds=1)
    assert await _lane_only_active(db_session, lane) != seeded.id


@pytest.mark.parametrize("lane", _LANES)
async def test_the_seed_is_the_first_semver_of_its_chain_and_passes_publish_validation(
    db_session: AsyncSession, lane: PromptLane
) -> None:
    seeded, sections = await load_active_prompt_set(db_session, lane=lane, model="haiku_writer")
    semver = (
        await db_session.scalars(sa.select(PromptSetSemver).where(PromptSetSemver.prompt_set_id == seeded.id))
    ).one()

    assert (semver.lane, semver.model, semver.major, semver.minor, semver.patch) == (lane, "haiku_writer", 1, 0, 0)
    assert semver.base_set_id is None
    _validate_prompt_draft_for_publish(seeded, sections, lane=lane, model="haiku_writer")


async def test_seeding_again_over_an_existing_chain_stops(db_session: AsyncSession) -> None:
    connection = await db_session.connection()

    with pytest.raises(RuntimeError, match="이미 세트가"):
        await connection.run_sync(_M.seed_published_sets)


async def test_a_sonnet_source_without_generation_channels_stops(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_M.delete_seeded_rows)
    source, _ = await load_active_prompt_set(db_session, lane="story", model="sonnet")
    await db_session.execute(
        sa.delete(PromptSection).where(PromptSection.prompt_set_id == source.id, PromptSection.channel == "generation")
    )

    with pytest.raises(RuntimeError, match="생성 채널이 없다"):
        await connection.run_sync(_M.seed_published_sets)


async def test_reseeding_after_the_undo_reproduces_the_chain_and_keeps_gemini_active(db_session: AsyncSession) -> None:
    """되돌린 뒤 다시 올리면 같은 id·같은 행으로 돌아오고, Gemini 활성 세트와 레인만 보는 활성 세트는 바뀌지 않는다. 버전은 전
    레인·전 모델 게시 최대 + 1 이다."""
    connection = await db_session.connection()
    before = {lane: (await load_active_prompt_set(db_session, lane=lane, model="gemini"))[0].id for lane in _LANES}
    lane_only = {lane: await _lane_only_active(db_session, lane) for lane in _LANES}
    await connection.run_sync(_M.delete_seeded_rows)
    top = await _count(db_session, "SELECT max(CAST(version AS INTEGER)) FROM prompt_sets WHERE status = 'published'")

    await connection.run_sync(_M.seed_published_sets)

    db_session.expire_all()
    for offset, lane in enumerate(_LANES, start=1):
        seeded, _ = await load_active_prompt_set(db_session, lane=lane, model="haiku_writer")
        assert (seeded.id, seeded.version) == (_M.NEW_SET_IDS[lane], str(top + offset))
        assert (await load_active_prompt_set(db_session, lane=lane, model="gemini"))[0].id == before[lane]
        assert await _lane_only_active(db_session, lane) == lane_only[lane]


async def test_the_undo_removes_every_haiku_writer_row_including_admin_drafts_and_later_versions(
    db_session: AsyncSession,
) -> None:
    """어드민이 그 체인에 둘째 판을 게시하고 초안을 둔 뒤에도 되돌리기가 멈추지 않는다 — 둘째 판의 판 행이 시드를 기준판으로
    가리켜도 판 행을 먼저 지워 FK 에 걸리지 않는다. 다시 불러도 같은 결과다."""
    seeded, sections = await load_active_prompt_set(db_session, lane="story", model="haiku_writer")
    assert seeded.published_at is not None
    later = PromptSet(
        version="999001",
        status="published",
        lane="story",
        model="haiku_writer",
        user_label=seeded.user_label,
        story_assistant_label=seeded.story_assistant_label,
        story_example_label=seeded.story_example_label,
        character_assistant_label=seeded.character_assistant_label,
        published_at=seeded.published_at + timedelta(seconds=10),
    )
    draft = PromptSet(
        version=None,
        status="draft",
        lane="story",
        model="haiku_writer",
        user_label=seeded.user_label,
        story_assistant_label=seeded.story_assistant_label,
        story_example_label=seeded.story_example_label,
        character_assistant_label=seeded.character_assistant_label,
    )
    db_session.add_all([later, draft])
    await db_session.flush()
    for target in (later, draft):
        db_session.add_all(
            PromptSection(
                prompt_set_id=target.id,
                channel=s.channel,
                scope=s.scope,
                slot=s.slot,
                variant=s.variant,
                body=s.body,
                conditional=s.conditional,
                order=s.order,
            )
            for s in sections
        )
    db_session.add(
        PromptSetSemver(
            prompt_set_id=later.id,
            lane="story",
            model="haiku_writer",
            major=1,
            minor=0,
            patch=1,
            level="patch",
            base_set_id=seeded.id,
        )
    )
    await db_session.flush()
    connection = await db_session.connection()

    await connection.run_sync(_M.delete_seeded_rows)
    await connection.run_sync(_M.delete_seeded_rows)

    assert await _count(db_session, "SELECT count(*) FROM prompt_sets WHERE model = 'haiku_writer'") == 0
    assert await _count(db_session, "SELECT count(*) FROM prompt_set_semvers WHERE model = 'haiku_writer'") == 0
    assert await _count(db_session, "SELECT count(*) FROM prompt_sets WHERE model = 'sonnet'") > 0


async def test_older_seed_revision_tests_undo_this_seed_too(db_session: AsyncSession) -> None:
    """옛 시드 리비전 테스트는 "그 리비전 직후 상태"를 만들려고 위 시드 리비전을 되돌린다 — 이 리비전에 되돌리기 함수가 있어야 그
    목록에 들고, 남은 Haiku 세트가 전역 게시 버전 최대값을 올려 그 테스트의 버전 단언을 어긋나게 하지 않는다."""
    assert _M.revision in seed_revisions_above(_OLDER_SEED_REVISION)
    assert seed_revisions_above(_M.revision) == []
    connection = await db_session.connection()

    await connection.run_sync(undo_seeded_rows_above, _OLDER_SEED_REVISION)

    assert await _count(db_session, "SELECT count(*) FROM prompt_sets WHERE model = 'haiku_writer'") == 0
