"""소설 레인 세 체인에 구성안 문안(새 두 채널)과 화 생성의 새 두 슬롯을 심는 데이터 마이그레이션 `b389c2317149` 의 검증.

마이그레이션 자체는 다시 돌리지 않는다(앞의 문안 리비전 테스트와 같은 방식). 세션 스코프 스키마(`_migrated_schema`)가 이미
`upgrade head` 를 했으므로 시드는 "마이그레이션 뒤 DB 상태"를 단언하고, `seed_published_sets`·`_patch_drafts`·`delete_seeded_rows`
는 테스트마다 롤백되는 `db_session` 의 커넥션에 `run_sync` 로 직접 부른다.

기대 행은 이 파일이 직접 적는다(이전 활성 세트 행 그대로 + 새 행) — 마이그레이션의 행 조립으로 기대값을 만들면 그 조립이 틀려도
테스트가 같이 틀린다. 문안 원문은 적지 않고 지문(md5)과 자리표시자로 고정한다."""

import hashlib
import importlib.util
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from string import Formatter
from types import ModuleType

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.prompts import _validate_prompt_draft_for_publish
from api.chat.prompt_builder import ALLOWED_PLACEHOLDERS, load_active_prompt_set
from api.db.models.prompt import PromptSection, PromptSet
from api.llm.chat_models import PromptSetModelId
from api.novelize.prompts import build_novelize_chapter_prompt
from factories import undo_seeded_rows_above

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load("b389c2317149")
# 그 뒤 소설 레인 Gemini 체인에 여러 문단 수정 문안을 더한 리비전(아래 기대 행이 그 행을 얹는다). 이 파일은 "이 리비전 직후
# 상태"를 보므로 테스트마다 위 시드 리비전 전부를 실제 downgrade 순서로 먼저 되돌린다(테스트 트랜잭션이 끝나면 롤백된다).
_LATER = _load("174f78b92e5c")


@pytest.fixture(autouse=True)
async def _undo_later_revisions(db_session: AsyncSession) -> None:
    await (await db_session.connection()).run_sync(undo_seeded_rows_above, _M.revision)


def _synthetic_rows(channel: str, slots: tuple[str, ...]) -> list[PromptSection]:
    return [
        PromptSection(channel=channel, scope="both", slot=slot, variant="", body="합성 문안", conditional=False, order=order)
        for order, slot in enumerate(slots)
    ]


# 뒤 리비전이 세 체인에 더한 등급 규칙 두 행의 꼴 — 본문은 합성 문장이다(같은 행을 이전·새 세트에 함께 얹어 견준다).
_LATER_RATING_ROWS = [
    PromptSection(
        channel="novelize_rating",
        scope=scope,
        slot="rule_rating",
        variant="",
        body="[수위]\n합성 등급 규칙",
        conditional=False,
        order=0,
    )
    for scope in ("story", "character")
]


def _with_later_rows(sections: list[PromptSection], model: str) -> list[PromptSection]:
    """지금 코드의 게시 검증·렌더는 뒤 리비전들이 더한 채널도 요구한다 — 이 리비전의 세트·초안에 그 행만 얹어 본다. 세 체인 모두
    등급 규칙 두 행, Gemini 체인은 여러 문단 수정 두 채널, Claude 체인은 경계 제안·문단 수정·여러 문단 수정·묶음 재검사 네 채널."""
    blocks = [
        PromptSection(channel=c, scope=sc, slot=sl, variant=v, body=b, conditional=cond, order=o)
        for c, sc, sl, v, b, cond, o in _LATER.NEW_CHANNEL_ROWS
    ]
    if model == "gemini":
        return [*sections, *blocks, *_LATER_RATING_ROWS]
    return [
        *sections,
        *blocks,
        *_synthetic_rows("novelize_boundary", ("instruction", "user_name", "max_turns", "turn_context")),
        *_synthetic_rows(
            "novelize_revise", ("instruction", "work_setting", "setting_notes", "paragraphs", "target_range", "user_request")
        ),
        *_LATER_RATING_ROWS,
    ]


# 이 리비전 직전 소설 레인 세 체인의 활성 세트(소설 레인을 처음 심은 리비전 — 그 사이에 소설 레인을 게시한 리비전이 없다).
_SEEDED_LANE = _load("a7a87e3ba631").NEW_SET_IDS
_PREVIOUS_SET_IDS: dict[str, uuid.UUID] = {model: _SEEDED_LANE[model] for model in ("gemini", "sonnet", "opus")}
_MODELS: tuple[PromptSetModelId, ...] = ("gemini", "sonnet", "opus")

Key = tuple[str, str, str, str]
Value = tuple[str, bool, int]

_LABELS = ("user_label", "story_assistant_label", "story_example_label", "character_assistant_label")


def _md5(body: str) -> str:
    return hashlib.md5(body.encode()).hexdigest()


def _fields(body: str) -> list[str]:
    return sorted({name for _, name, _, _ in Formatter().parse(body) if name})


# 시드 문안의 지문 — 글자 하나가 바뀌어도 여기서 깨진다.
_BODY_MD5: dict[tuple[str, str], str] = {
    ("novelize_outline", "instruction"): "25ab7f2b41f72a9a340e8c1cf939cbc5",
    ("novelize_outline", "work_setting"): "cf3649203c26e5781c78b346f0e3ec7e",
    ("novelize_outline", "user_name"): "388da4b15eb6333490f0eb41ced7563f",
    ("novelize_outline", "setting_notes"): "6a5abf8d781734e1d138e177efe91d84",
    ("novelize_outline", "character_notes"): "195cbd02eb923869af3818d1ef337903",
    ("novelize_outline", "previous_summaries"): "ca36903ab2610c7ce197541bef4f21d2",
    ("novelize_outline", "continuity_context"): "5eb6cc5d8a136f751b7d4db7b60bca47",
    ("novelize_outline", "outline_plan"): "94a9c0f4ad6bdfa68a1eae680ec958f2",
    ("novelize_outline", "turn_context"): "253ebd082c47070c53b8a1d67f203d01",
    ("novelize_episode_outline", "instruction"): "9d7373b95b07b4e930d7bd623edd29ce",
    ("novelize_episode_outline", "work_setting"): "cf3649203c26e5781c78b346f0e3ec7e",
    ("novelize_episode_outline", "user_name"): "388da4b15eb6333490f0eb41ced7563f",
    ("novelize_episode_outline", "setting_notes"): "6a5abf8d781734e1d138e177efe91d84",
    ("novelize_episode_outline", "character_notes"): "195cbd02eb923869af3818d1ef337903",
    ("novelize_episode_outline", "previous_summaries"): "ca36903ab2610c7ce197541bef4f21d2",
    ("novelize_episode_outline", "episode_outline"): "b32cc0aff2ad60e6a94a302fb7483c29",
    ("novelize_episode_outline", "continuity_context"): "5eb6cc5d8a136f751b7d4db7b60bca47",
    ("novelize_episode_outline", "turn_context"): "253ebd082c47070c53b8a1d67f203d01",
    ("novelize_chapter", "scene_plan"): "a46fbe3c4c8a7d98ec5c79b7bcb5819c",
    ("novelize_chapter", "continuity_context"): "5eb6cc5d8a136f751b7d4db7b60bca47",
}

# 새 두 채널의 (slot → conditional, order). 두 채널 모두 scope `both`, variant 없음.
_OUTLINE_LAYOUT: dict[str, tuple[bool, int]] = {
    "instruction": (False, 0),
    "work_setting": (False, 1),
    "user_name": (False, 2),
    "setting_notes": (True, 3),
    "character_notes": (True, 4),
    "previous_summaries": (True, 5),
    "continuity_context": (True, 6),
    "outline_plan": (False, 7),
    "turn_context": (False, 8),
}
_EPISODE_LAYOUT: dict[str, tuple[bool, int]] = {
    **{slot: value for slot, value in _OUTLINE_LAYOUT.items() if slot not in ("continuity_context", "outline_plan")},
    "episode_outline": (False, 6),
    "continuity_context": (True, 7),
}
_NEW_CHAPTER_SLOTS = ("scene_plan", "continuity_context")


async def _sections_of(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    """세트의 섹션을 세션과 떨어진 사본으로 읽는다 — 다음 조회의 만료가 앞서 읽은 섹션을 다시 읽으려 들지 않게."""
    db_session.expire_all()
    rows = (await db_session.scalars(sa.select(PromptSection).where(PromptSection.prompt_set_id == set_id))).all()
    return [
        PromptSection(
            channel=s.channel,
            scope=s.scope,
            slot=s.slot,
            variant=s.variant,
            body=s.body,
            conditional=s.conditional,
            order=s.order,
        )
        for s in rows
    ]


def _keyed(sections: list[PromptSection]) -> dict[Key, Value]:
    return {(s.channel, s.scope, s.slot, s.variant): (s.body, s.conditional, s.order) for s in sections}


async def _active_id(db_session: AsyncSession, model: PromptSetModelId) -> uuid.UUID:
    db_session.expire_all()
    return (await load_active_prompt_set(db_session, lane="novel", model=model))[0].id


async def _get_set(db_session: AsyncSession, set_id: uuid.UUID) -> PromptSet:
    prompt_set = await db_session.get(PromptSet, set_id)
    assert prompt_set is not None
    return prompt_set


async def _copy_set(
    db_session: AsyncSession, source_id: uuid.UUID, *, status: str, published_at: datetime | None, edit: str = ""
) -> uuid.UUID:
    """`source_id` 세트를 복제한다. `edit` 가 있으면 화 생성 지시문 끝에 붙인다(어드민이 고친 문안 흉내)."""
    source = await _get_set(db_session, source_id)
    copy = PromptSet(
        version="9001" if status == "published" else None,
        status=status,
        lane="novel",
        model=source.model,
        **{label: getattr(source, label) for label in _LABELS},
        published_at=published_at,
    )
    db_session.add(copy)
    await db_session.flush()
    copy_id = copy.id
    for s in await _sections_of(db_session, source_id):
        body = s.body + edit if (s.channel, s.slot) == ("novelize_chapter", "instruction") else s.body
        db_session.add(
            PromptSection(
                prompt_set_id=copy_id,
                channel=s.channel,
                scope=s.scope,
                slot=s.slot,
                variant=s.variant,
                body=body,
                conditional=s.conditional,
                order=s.order,
            )
        )
    await db_session.flush()
    return copy_id


async def _undo(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_M.delete_seeded_rows)


async def _seed(db_session: AsyncSession) -> None:
    connection = await db_session.connection()
    await connection.run_sync(_M.seed_published_sets)


# ---- 문안 상수 ------------------------------------------------------------------------------


def test_seed_bodies_use_only_the_placeholders_the_renderer_allows() -> None:
    """새 행의 자리표시자는 렌더 함수가 넘기는 이름(허용 목록)과 정확히 같다 — 남는 이름이 있으면 렌더가 깨지고, 모자라면 그
    값이 모델에 가지 않는다. 문안의 바뀜은 지문으로 고정한다."""
    rows = [*_M.NEW_CHANNEL_ROWS, *[("novelize_chapter", "both", slot, "", body, True, 0) for slot, body in _M.NEW_CHAPTER_ROWS]]
    for channel, _scope, slot, _variant, body, _conditional, _order in rows:
        assert _fields(body) == sorted(ALLOWED_PLACEHOLDERS[(channel, slot)]), (channel, slot)
    assert {(row[0], row[2]): _md5(row[4]) for row in rows} == _BODY_MD5


def test_the_new_channels_and_chapter_slots_have_the_intended_layout() -> None:
    """두 채널의 슬롯·conditional·order, 화 생성의 새 두 슬롯이 conditional 인 것을 고정한다. 깨지는 시나리오: 연속성 참고가
    conditional 이 아니어서 맥락 구간이 없는 호출에 빈 머리글이 나가거나, 화 생성 새 슬롯이 conditional 이 아니어서 옛 흐름이
    렌더 실패(값 없음)한다."""
    layout = {
        channel: {row[2]: (row[5], row[6]) for row in _M.NEW_CHANNEL_ROWS if row[0] == channel}
        for channel in _M.NEW_CHANNELS
    }
    assert layout == {"novelize_outline": _OUTLINE_LAYOUT, "novelize_episode_outline": _EPISODE_LAYOUT}
    assert {row[1] for row in _M.NEW_CHANNEL_ROWS} == {"both"} and {row[3] for row in _M.NEW_CHANNEL_ROWS} == {""}
    assert _M.chapter_rows([("novelize_chapter", "both", "turn_context", "", "x", False, 8)]) == [
        ("novelize_chapter", "both", "scene_plan", "", _M.SCENE_PLAN_BODY, True, 9),
        ("novelize_chapter", "both", "continuity_context", "", _M.CONTINUITY_CONTEXT_BODY, True, 10),
    ]


# ---- 시드 결과(head 상태) --------------------------------------------------------------------


@pytest.mark.parametrize("model", _MODELS)
async def test_each_chain_is_active_at_its_seed_which_is_the_previous_set_plus_the_new_rows(
    db_session: AsyncSession, model: PromptSetModelId
) -> None:
    """세 체인 모두 새 세트가 활성이고, 그 세트는 이전 활성 세트의 행 전부(본문·conditional·order 그대로) + 새 두 채널 열여덟 행
    + 화 생성의 새 두 행(이전 화 생성 행 뒤로 이어 붙인 order)이다. 라벨도 그대로다. 깨지는 시나리오: 사본이 이전 행을 하나라도
    잃어 옛 흐름 렌더가 바뀌거나, Claude 체인에 구성안 행이 없어 Opus 구성안이 빈 프롬프트가 된다."""
    assert await _active_id(db_session, model) == _M.NEW_SET_IDS[model]
    previous = _keyed(await _sections_of(db_session, _PREVIOUS_SET_IDS[model]))
    seeded = _keyed(await _sections_of(db_session, _M.NEW_SET_IDS[model]))

    assert {key: value for key, value in seeded.items() if key in previous} == previous
    added = {key: value for key, value in seeded.items() if key not in previous}
    last_chapter_order = max(order for (channel, *_), (_b, _c, order) in previous.items() if channel == "novelize_chapter")
    expected_chapter = {
        ("novelize_chapter", "both", slot, ""): (True, last_chapter_order + offset)
        for offset, slot in enumerate(_NEW_CHAPTER_SLOTS, start=1)
    }
    expected = {
        **{("novelize_outline", "both", slot, ""): value for slot, value in _OUTLINE_LAYOUT.items()},
        **{("novelize_episode_outline", "both", slot, ""): value for slot, value in _EPISODE_LAYOUT.items()},
        **expected_chapter,
    }
    assert {key: (cond, order) for key, (_body, cond, order) in added.items()} == expected
    previous_set = await _get_set(db_session, _PREVIOUS_SET_IDS[model])
    seeded_set = await _get_set(db_session, _M.NEW_SET_IDS[model])
    assert [getattr(seeded_set, label) for label in _LABELS] == [getattr(previous_set, label) for label in _LABELS]
    assert seeded_set.published_at is not None and previous_set.published_at is not None
    assert seeded_set.published_at > previous_set.published_at


async def test_versions_continue_the_global_sequence_in_fixed_order(db_session: AsyncSession) -> None:
    versions = [int((await _get_set(db_session, _M.NEW_SET_IDS[model])).version or 0) for model in _MODELS]
    assert versions[1] == versions[0] + 1 and versions[2] == versions[1] + 1


@pytest.mark.parametrize("model", _MODELS)
async def test_seeded_sets_pass_publish_validation_and_the_previous_sets_no_longer_do(
    db_session: AsyncSession, model: PromptSetModelId
) -> None:
    """새 세트는 지금 코드의 게시 검증(슬롯 집합·자리표시자 허용 목록)을 통과하고, 이전 세트는 새 행이 없어 "누락"으로 막힌다 —
    코드 표와 시드가 같이 움직였다는 증거다."""
    prompt_set, sections = await load_active_prompt_set(db_session, lane="novel", model=model)
    _validate_prompt_draft_for_publish(prompt_set, _with_later_rows(sections, model), lane="novel", model=model)

    previous = await _get_set(db_session, _PREVIOUS_SET_IDS[model])
    with pytest.raises(HTTPException):
        _validate_prompt_draft_for_publish(
            previous, await _sections_of(db_session, _PREVIOUS_SET_IDS[model]), lane="novel", model=model
        )


@pytest.mark.parametrize("model", _MODELS)
async def test_the_old_flow_chapter_prompt_renders_byte_for_byte_the_same_from_the_seed(
    db_session: AsyncSession, model: PromptSetModelId
) -> None:
    """옛 흐름(장면 계획·연속성 참고 값을 넘기지 않는 화 생성)의 렌더가 이전 세트와 새 세트에서 바이트까지 같다 — 새 두 행이
    conditional 이라 섹션째 빠진다. 깨지는 시나리오: 마이그레이션 직후 옛 흐름의 화 생성 프롬프트가 바뀌어(빈 머리글, 렌더
    실패) 값을 낸 화가 다른 글이 되거나 실패·환불된다."""
    previous_sections = await _sections_of(db_session, _PREVIOUS_SET_IDS[model])
    seeded_sections = await _sections_of(db_session, _M.NEW_SET_IDS[model])
    # 섹션을 읽을 때 세션을 만료시키므로 라벨을 읽을 세트는 그 뒤에 읽는다. 라벨은 소설 Gemini 체인 세트 한 곳에서 읽는다.
    label_set = await _get_set(db_session, _PREVIOUS_SET_IDS["gemini"])

    def render(sections: list[PromptSection]) -> str:
        built = build_novelize_chapter_prompt(
            label_set=label_set,
            sections=[*sections, *_LATER_RATING_ROWS],
            is_story_chat=True,
            work_setting="작품 설정",
            user_name="서진",
            setting_notes="노트",
            previous_excerpt="앞 화 끝",
            turn_lines="[턴 1] 진행자: 왔어?",
            character_notes="도윤: 친구",
            previous_summaries="1화: 만남",
            episode_count=2,
            novel_title_rule="제목도 쓴다.",
        )
        return f"{built.system_instruction}\n---\n{built.prompt}"

    previous = render(previous_sections)
    seeded = render(seeded_sections)

    assert seeded == previous


# ---- 되돌리기·다시 올리기 ----------------------------------------------------------------------


async def test_downgrade_then_upgrade_swaps_every_chain_back_and_forth(db_session: AsyncSession) -> None:
    await _undo(db_session)

    for model in _MODELS:
        assert await _active_id(db_session, model) == _PREVIOUS_SET_IDS[model]
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[model]) is None
    remaining = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(PromptSection)
        .where(PromptSection.channel.in_(("novelize_outline", "novelize_episode_outline")))
    )
    assert remaining == 0

    await _seed(db_session)

    for model in _MODELS:
        assert await _active_id(db_session, model) == _M.NEW_SET_IDS[model]


async def test_upgrade_refuses_to_run_twice(db_session: AsyncSession) -> None:
    with pytest.raises(RuntimeError, match="이미 있다"):
        await _seed(db_session)


@pytest.mark.parametrize(
    ("channel", "slot"),
    [
        pytest.param("novelize_outline", "instruction", id="outline-channel"),
        pytest.param("novelize_chapter", "scene_plan", id="chapter-slot"),
    ],
)
async def test_upgrade_stops_when_a_chain_already_has_a_new_row(
    db_session: AsyncSession, channel: str, slot: str
) -> None:
    """어느 체인의 활성 세트에 새 행이 이미 있으면 세 체인 어디에도 넣지 않은 채 멈춘다. 깨지는 시나리오: 같은 슬롯이 두 행이 되어
    게시 검증이 그 체인을 영영 막는다."""
    await _undo(db_session)
    latest = (await _get_set(db_session, _PREVIOUS_SET_IDS["sonnet"])).published_at
    assert latest is not None
    edited = await _copy_set(
        db_session, _PREVIOUS_SET_IDS["sonnet"], status="published", published_at=latest + timedelta(seconds=5)
    )
    db_session.add(
        PromptSection(
            prompt_set_id=edited, channel=channel, scope="both", slot=slot, variant="", body="x", conditional=True, order=99
        )
    )
    await db_session.flush()

    with pytest.raises(RuntimeError, match="novel/sonnet"):
        await _seed(db_session)

    for model in _MODELS:
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[model]) is None


async def test_upgrade_copies_admin_edited_sets_whose_chains_were_published_at_different_times(
    db_session: AsyncSession,
) -> None:
    """운영 꼴 — 체인마다 어드민이 다른 시각에 고쳐 게시했고(gemini → sonnet → opus 순, 레인 전체로는 opus 가 최신), 화 생성
    지시문이 시드와 다르다. 그래도 멈추지 않고 체인마다 그 체인의 활성 세트(어드민 수정본)를 바이트째 옮겨 새 세트가 각 체인의
    활성이 된다. 깨지는 시나리오: 레인만 보는 활성 조회가 Gemini 를 집는지 보는 검사가 남아 운영 배포가 멈추거나, 시드 원문으로
    덮어 운영자가 고친 문안이 사라진다."""
    await _undo(db_session)
    # 체인마다 한 시간씩 늦게 게시해 레인 전체의 최신은 opus 다. 지금보다 뒤(시계가 어긋난 서버의 게시)로 두어, 새 세트 시각이
    # "지금"이 아니라 "그 체인 활성 + 1초"여야 활성이 되는 경우까지 본다.
    published = [(await _get_set(db_session, _PREVIOUS_SET_IDS[model])).published_at for model in _MODELS]
    previous_at = max(at for at in published if at is not None)
    edited = {
        model: await _copy_set(
            db_session,
            _PREVIOUS_SET_IDS[model],
            status="published",
            published_at=previous_at + timedelta(hours=offset),
            edit=f"\n(운영 수정 {model})",
        )
        for offset, model in enumerate(_MODELS, start=1)
    }

    await _seed(db_session)

    for model in _MODELS:
        assert await _active_id(db_session, model) == _M.NEW_SET_IDS[model]
        source = _keyed(await _sections_of(db_session, edited[model]))
        seeded = _keyed(await _sections_of(db_session, _M.NEW_SET_IDS[model]))
        assert {key: value for key, value in seeded.items() if key in source} == source
        assert seeded[("novelize_chapter", "both", "instruction", "")][0].endswith(f"(운영 수정 {model})")


async def test_downgrade_stops_when_the_admin_published_after_the_seed(db_session: AsyncSession) -> None:
    """시드 뒤에 어드민이 세 체인 중 하나라도 새 버전을 게시했으면 아무것도 지우지 않고 멈춘다."""
    seeded = await _get_set(db_session, _M.NEW_SET_IDS["opus"])
    assert seeded.published_at is not None
    await _copy_set(db_session, _M.NEW_SET_IDS["opus"], status="published", published_at=seeded.published_at + timedelta(seconds=1))

    with pytest.raises(RuntimeError, match="novel/opus"):
        await _undo(db_session)

    for model in _MODELS:
        assert await db_session.get(PromptSet, _M.NEW_SET_IDS[model]) is not None


# ---- `_patch_drafts` ------------------------------------------------------------------------


@pytest.mark.parametrize("model", _MODELS)
async def test_patch_drafts_adds_the_rows_in_place_the_draft_publishes_and_downgrade_removes_them(
    db_session: AsyncSession, model: PromptSetModelId
) -> None:
    """새 행이 없는 초안(배포 전 이전 활성본에서 만든 초안)에 같은 새 행을 넣어 지금 코드의 게시 검증을 통과하게 하고, 되돌리면
    그 행만 지워 원래 초안으로 돌아간다. 이미 다 있는 초안은 건드리지 않는다. 깨지는 시나리오: 배포 뒤 운영자가 하던 초안이
    "누락"으로 게시되지 않거나, 되돌리기가 초안의 다른 행까지 지운다."""
    draft_id = await _copy_set(db_session, _PREVIOUS_SET_IDS[model], status="draft", published_at=None)
    before = _keyed(await _sections_of(db_session, draft_id))
    connection = await db_session.connection()

    patched_what = await connection.run_sync(_M._patch_drafts)
    patched = _keyed(await _sections_of(db_session, draft_id))
    assert sorted(patched_what) == sorted(
        [(model, "novelize_outline"), (model, "novelize_episode_outline"), (model, "novelize_chapter")]
    )
    assert {key: value for key, value in patched.items() if key in before} == before
    seeded = _keyed(await _sections_of(db_session, _M.NEW_SET_IDS[model]))
    assert {key: value for key, value in patched.items() if key not in before} == {
        key: value for key, value in seeded.items() if key not in before
    }
    sections = await _sections_of(db_session, draft_id)
    draft = await _get_set(db_session, draft_id)
    _validate_prompt_draft_for_publish(draft, _with_later_rows(sections, model), lane="novel", model=model)

    assert await connection.run_sync(_M._patch_drafts) == []

    await connection.run_sync(_M._delete_draft_rows)
    assert _keyed(await _sections_of(db_session, draft_id)) == before
