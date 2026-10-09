"""소설 프롬프트를 `novel` 레인으로 옮기는 데이터 마이그레이션 `a7a87e3ba631`의 검증.

마이그레이션 자체는 다시 돌리지 않는다(`test_prompt_model_sets_migration.py`와 같은 방식). 세션 스코프 스키마
(`_migrated_schema`)가 이미 `upgrade head`를 했으므로 시드는 "마이그레이션 뒤 DB 상태"를 단언하고, 순수 함수와
`seed_novel_lane`·`delete_novel_sets`는 직접 부른다(뒤 둘은 테스트마다 롤백되는 `db_session`의 커넥션에 `run_sync`로).
왕복(upgrade/downgrade)은 세션 스키마의 teardown 이 `downgrade base` 로 탄다."""

import importlib.util
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.prompts import _validate_prompt_draft_for_publish
from api.chat.prompt_builder import PromptLane, load_active_prompt_set
from api.db.models.prompt import PromptSection, PromptSet
from api.llm.chat_models import ChatModelId
from api.novelize import output
from api.novelize.prompts import build_novelize_chapter_prompt

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("a7a87e3ba631")
_NOVELIZE = set(_M.CHANNELS)
# 이 리비전 뒤에 story 레인 Gemini 체인에 스탯 규칙 판정 채널을 더한 세트를 게시하는 리비전 — head 상태에서는 그 세트가
# story 활성 세트이고 버전도 이 리비전의 세트들보다 뒤다.
_STAT_RULE_SET_ID: uuid.UUID = _load("d9768bc0cfee").NEW_SET_ID

Row = tuple[str, str, str, str, str, bool, int]


async def _rows(db_session: AsyncSession, set_id: uuid.UUID) -> list[Row]:
    sections = (
        await db_session.scalars(
            sa.select(PromptSection)
            .where(PromptSection.prompt_set_id == set_id)
            .execution_options(populate_existing=True)
        )
    ).all()
    return sorted((s.channel, s.scope, s.slot, s.variant, s.body, s.conditional, s.order) for s in sections)


async def _active_id(db_session: AsyncSession, lane: PromptLane, model: ChatModelId = "gemini") -> uuid.UUID:
    db_session.expire_all()
    return (await load_active_prompt_set(db_session, lane=lane, model=model))[0].id


async def _novelize_rows_of_chat(db_session: AsyncSession, lane: PromptLane) -> list[Row]:
    return [row for row in await _rows(db_session, await _active_id(db_session, lane)) if row[0] in _NOVELIZE]


# ---- 마이그레이션 뒤 DB 상태 -------------------------------------------------------------------


async def test_the_copy_set_is_the_chat_novelize_rows_byte_for_byte(db_session: AsyncSession) -> None:
    """첫 소설 판(A)은 옛 문안을 소설 탭에서 복원할 수 있게 남긴 사본이다 — 바이트·order·conditional 이 원본 그대로다."""
    copy_rows = await _rows(db_session, _M.NEW_SET_IDS["gemini-copy"])

    assert copy_rows == await _novelize_rows_of_chat(db_session, "story")
    assert copy_rows == await _novelize_rows_of_chat(db_session, "character")
    assert {row[0] for row in copy_rows} == _NOVELIZE


async def test_each_novel_chain_has_its_new_set_active(db_session: AsyncSession) -> None:
    """(novel, 모델)마다 활성 세트가 하나다 — 없으면 그 모델 화 생성이 실패하고 어드민 소설 탭 초안 조회가 500 이다."""
    assert await _active_id(db_session, "novel") == _M.NEW_SET_IDS["gemini"]
    assert await _active_id(db_session, "novel", "sonnet") == _M.NEW_SET_IDS["sonnet"]
    assert await _active_id(db_session, "novel", "opus") == _M.NEW_SET_IDS["opus"]


async def test_the_new_gemini_set_changes_only_the_chapter_channel_and_claude_chains_copy_it(
    db_session: AsyncSession,
) -> None:
    copy_rows = await _rows(db_session, _M.NEW_SET_IDS["gemini-copy"])
    v2_rows = await _rows(db_session, _M.NEW_SET_IDS["gemini"])
    v2_chapter = [row for row in v2_rows if row[0] == "novelize_chapter"]

    assert [row for row in v2_rows if row[0] != "novelize_chapter"] == [
        row for row in copy_rows if row[0] != "novelize_chapter"
    ]
    assert [row[2] for row in sorted(v2_chapter, key=lambda row: row[6])] == [slot for slot, _, _ in _M.CHAPTER_SLOTS]
    # 작품 설정·이름·설정 노트·원문 슬롯은 원본 행 그대로다.
    kept = {row[2]: row[4] for row in copy_rows if row[0] == "novelize_chapter"}
    assert {row[2]: row[4] for row in v2_chapter if row[2] in {"work_setting", "user_name", "setting_notes", "turn_context"}} == {
        slot: kept[slot] for slot in ("work_setting", "user_name", "setting_notes", "turn_context")
    }
    for model in ("sonnet", "opus"):
        assert await _rows(db_session, _M.NEW_SET_IDS[model]) == v2_chapter


@pytest.mark.parametrize(
    ("set_key", "model"),
    [
        pytest.param("gemini", "gemini", id="gemini"),
        pytest.param("sonnet", "sonnet", id="sonnet"),
        pytest.param("opus", "opus", id="opus"),
    ],
)
async def test_seeded_sets_pass_the_novel_lane_publish_check(
    db_session: AsyncSession, set_key: str, model: ChatModelId
) -> None:
    """시드가 소설 레인 게시 검증(슬롯 집합·자리표시자·order)을 그대로 통과한다 — 통과하지 못하면 어드민이 시드를 열어
    그대로 다시 게시하는 것조차 막힌다."""
    prompt_set = await db_session.get_one(PromptSet, _M.NEW_SET_IDS[set_key])
    sections = list(
        (await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == prompt_set.id))).all()
    )
    _validate_prompt_draft_for_publish(prompt_set, sections, lane="novel", model=model)


async def test_versions_follow_the_global_sequence_and_the_copy_is_older(db_session: AsyncSession) -> None:
    sets = {key: await db_session.get_one(PromptSet, set_id) for key, set_id in _M.NEW_SET_IDS.items()}
    versions = [int(sets[key].version or 0) for key in ("gemini-copy", "gemini", "sonnet", "opus")]
    others = await db_session.scalar(
        sa.select(sa.func.max(sa.cast(PromptSet.version, sa.Integer))).where(
            PromptSet.status == "published",
            PromptSet.lane.not_in(("novel", "novel_screen")),
            PromptSet.id != _STAT_RULE_SET_ID,
        )
    )
    assert others is not None
    assert versions == [others + 1, others + 2, others + 3, others + 4]
    copy_at, v2_at = sets["gemini-copy"].published_at, sets["gemini"].published_at
    assert copy_at is not None and v2_at is not None and copy_at < v2_at


async def test_chat_lanes_keep_their_active_sets_and_frozen_novelize_rows(db_session: AsyncSession) -> None:
    """옛 이미지로 되돌리면 옛 코드는 채팅 레인 Gemini 세트에서 소설 문안을 읽는다 — 그 세트와 행이 그대로여야 이미지만
    되돌리는 롤백이 된다."""
    chat_sets = {**_load("3bb2cc159b6d").NEW_SET_IDS, "story": _STAT_RULE_SET_ID}
    for lane in ("story", "character"):
        assert await _active_id(db_session, lane) == chat_sets[lane]
        assert len(await _novelize_rows_of_chat(db_session, lane)) == 16


# ---- 화 생성 문안의 출력 형식 = 파서의 문법 --------------------------------------------------------

_FORMAT_START = "[출력 형식]"


async def test_the_seeded_output_format_is_the_grammar_the_parser_reads(db_session: AsyncSession) -> None:
    """지시문이 요구하는 출력 형식과 파서가 읽는 머리 줄·필드·구분 줄이 같은 글자여야 한다 — 어긋나면 모델이 지시를
    그대로 따라도 모든 묶음이 형식 위반 실패·전액 환불이다. 시드한 소설 Gemini 세트를 실제 빌더로 렌더해, 「출력 형식」
    블록의 각 줄을 파서의 정규식·필드 이름에 맞대고, 그 블록을 그대로 채운 출력이 파싱되는지 본다."""
    chat_set, chat_sections = await load_active_prompt_set(db_session, lane="story")
    _, novel_sections = await load_active_prompt_set(db_session, lane="novel")
    built = build_novelize_chapter_prompt(
        chat_set=chat_set,
        chat_sections=chat_sections,
        sections=novel_sections,
        is_story_chat=True,
        work_setting="설정",
        user_name="서진",
        setting_notes="",
        previous_excerpt="",
        turn_lines="[턴 1] 진행자: 왔어?",
        episode_count=2,
        episode_chars=5000,
        novel_title_rule="이번에는 소설 제목도 쓴다.",
    )
    assert "이 구간을 정확히 2화로 나눈다. 한 화는 공백 포함 5000자 안팎이다.\n이번에는 소설 제목도 쓴다." in built.prompt

    lines = built.system_instruction.split(_FORMAT_START, 1)[1].splitlines()[2:11]
    title_header, _title, first, title_field, summary_field, characters_field, separator, _body, second = lines
    assert output._NOVEL_TITLE_HEADER.match(title_header)
    first_match, second_match = output._EPISODE_HEADER.match(first), output._EPISODE_HEADER.match(second)
    assert first_match is not None and first_match.group(1) == "1"
    assert second_match is not None and second_match.group(1) == "2"
    assert [line.split(":", 1)[0] for line in (title_field, summary_field, characters_field)] == list(output._FIELDS)
    assert separator == output._SEPARATOR

    # 블록을 그대로 따른 출력 — 괄호 안 설명만 값으로 바꿨다.
    body = "비가 내리는 저녁이었다."
    filled = "\n".join(
        [
            title_header,
            "빗소리의 계절",
            first,
            "제목: 비 오는 정류장",
            "요약: 서진이 도윤을 만났다.",
            "등장인물: 서진, 도윤",
            separator,
            body,
            second,
            "제목: 우산",
            "요약: 도윤이 우산을 건넸다.",
            "등장인물: 도윤",
            separator,
            body,
        ]
    )
    parsed = output.parse_batch_output(filled)
    assert parsed.novel_title == "빗소리의 계절"
    assert [(e.title, e.characters, e.body) for e in parsed.episodes] == [
        ("비 오는 정류장", ("서진", "도윤"), body),
        ("우산", ("도윤",), body),
    ]
    # 지시문이 본문에 쓰지 말라는 줄 머리가 파서가 구조 줄로 거부하는 머리와 같다.
    forbidden = re.findall(r"`(===|---)`", built.system_instruction)
    assert set(forbidden) == {"===", "---"}


# ---- 가정 검사·시드·지우기 -------------------------------------------------------------------------

_SAMPLE: list[Row] = [
    (channel, "both", "instruction", "", f"{channel} 지시", False, 0) for channel in _M.CHANNELS
]


def test_assert_layout_refuses_an_existing_novel_set() -> None:
    with pytest.raises(RuntimeError, match="이미 세트가 1개"):
        _M.assert_layout(_SAMPLE, _SAMPLE, 1)


def test_assert_layout_refuses_a_source_without_a_novelize_channel() -> None:
    with pytest.raises(RuntimeError, match=r"\[character\].*novelize_revise"):
        _M.assert_layout(_SAMPLE, _SAMPLE[:2], 0)


def test_assert_layout_refuses_lanes_whose_novelize_rows_differ() -> None:
    """두 레인의 문안이 다르면 한 벌로 옮길 때 한쪽이 사라진다 — 멈추고 운영에서 맞춘 뒤 다시 배포한다."""
    changed = [*_SAMPLE[:2], ("novelize_revise", "both", "instruction", "", "다른 지시", False, 0)]
    with pytest.raises(RuntimeError, match="novelize_revise"):
        _M.assert_layout(_SAMPLE, changed, 0)
    _M.assert_layout(_SAMPLE, list(reversed(_SAMPLE)), 0)  # 순서만 다르면 같다


def test_v2_chapter_rows_need_the_kept_source_slots() -> None:
    with pytest.raises(RuntimeError, match="work_setting"):
        _M.v2_chapter_rows(_SAMPLE)


async def _seed(db_session: AsyncSession, now: datetime) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_M.delete_novel_sets)
    await connection.run_sync(lambda conn: _M.seed_novel_lane(conn, now))


async def test_seeding_again_after_deleting_makes_each_chain_active(db_session: AsyncSession) -> None:
    """지운 뒤 다시 심으면(downgrade → upgrade) 체인마다 새 세트가 활성이다 — 같은 트랜잭션의 시각으로 넣어도 Gemini
    체인의 두 판이 동률이 되지 않는다."""
    await _seed(db_session, datetime.now(UTC))

    assert await _active_id(db_session, "novel") == _M.NEW_SET_IDS["gemini"]
    assert await _active_id(db_session, "novel", "sonnet") == _M.NEW_SET_IDS["sonnet"]
    assert await _active_id(db_session, "novel", "opus") == _M.NEW_SET_IDS["opus"]


async def test_seeding_stops_when_the_chat_lanes_disagree(db_session: AsyncSession) -> None:
    _, sections = await load_active_prompt_set(db_session, lane="character")
    next(s for s in sections if s.channel == "novelize_boundary" and s.slot == "instruction").body = "운영이 고친 지시"
    await db_session.flush()

    with pytest.raises(RuntimeError, match="story·character 의 소설화 행이 다르다"):
        await _seed(db_session, datetime.now(UTC))


async def test_delete_removes_admin_made_novel_rows_too(db_session: AsyncSession) -> None:
    """downgrade 는 리터럴 id 만이 아니라 `novel` 레인 전부를 지운다 — 어드민 초안·게시본이 남으면 옛 코드가 모르는 레인
    행이 테이블에 남는다."""
    draft = PromptSet(
        version=None,
        status="draft",
        lane="novel",
        model="opus",
        user_label="a",
        story_assistant_label="b",
        story_example_label="c",
        character_assistant_label="d",
    )
    db_session.add(draft)
    await db_session.flush()
    draft_id = draft.id
    db_session.add(
        PromptSection(
            prompt_set_id=draft_id, channel="novelize_chapter", scope="both", slot="instruction", variant="",
            body="초안", conditional=False, order=0,
        )
    )
    await db_session.flush()

    connection = await db_session.connection()
    await connection.run_sync(_M.delete_novel_sets)

    db_session.expire_all()
    assert (await db_session.scalar(sa.select(sa.func.count()).where(PromptSet.lane == "novel"))) == 0
    assert await db_session.scalar(sa.select(sa.func.count()).select_from(PromptSection).where(
        PromptSection.prompt_set_id == draft_id
    )) == 0
    assert await _active_id(db_session, "story") is not None
