"""소설 작업 갈래 판정과 갈래 표 — 작업 행의 종류 칸과 하위 칸(연쇄 부모·장면 구성안 리비전·여러 문단 패치)을 읽어 실행 경로 열
개 중 하나를 고르는 판정, 갈래마다 붙은 사실 칸, 실행 경로가 갈래로 핸들러를 찾는 등록부를 본다. DB 를 타지 않는다.

기대값은 코드에서 끌어내지 않고 손으로 적은 리터럴이다 — 사실 칸 하나를 잘못 옮기면 그 칸을 읽는 워커 고르기·하루 상한·집필권
잠금이 다른 작업 행을 고르게 되는데, 그 차이가 여기서 먼저 깨진다."""

import uuid
from typing import Any, get_args

import pytest

from api.db.models.novel import Novel, NovelJob, NovelJobKind
from api.llm.client import LLMCallContext
from api.novelize import runner
from api.novelize.job_variants import VARIANT_FACTS, JobVariant, kinds_where, split_kinds, variant_of


def _job(
    kind: str,
    *,
    parent: bool = False,
    episode_outline: bool = False,
    block_edit: bool = False,
) -> NovelJob:
    return NovelJob(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        novel_id=uuid.uuid4(),
        kind=kind,
        model="sonnet",
        parent_job_id=uuid.uuid4() if parent else None,
        episode_outline_id=uuid.uuid4() if episode_outline else None,
        block_edit={"targets": []} if block_edit else None,
        chapter_id=uuid.uuid4(),
        outline_id=uuid.uuid4(),
        outline_episode_key=uuid.uuid4(),
    )


@pytest.mark.parametrize(
    ("kind", "parent", "episode_outline", "block_edit", "expected"),
    [
        pytest.param("chapter_generate", False, False, False, "legacy_generate", id="generate-alone"),
        pytest.param("chapter_generate", True, False, False, "chain_child", id="generate-under-a-parent"),
        pytest.param("chain_generate", False, False, False, "chain_parent", id="chain-parent"),
        pytest.param("chapter_regenerate", False, False, False, "legacy_regenerate", id="regenerate-old-flow"),
        pytest.param("chapter_regenerate", False, True, False, "outline_regenerate", id="regenerate-outline-flow"),
        pytest.param("ai_edit", False, False, False, "paragraph_edit", id="edit-one-range"),
        pytest.param("ai_edit", False, False, True, "block_edit", id="edit-many-blocks"),
        pytest.param("outline_generate", False, False, False, "outline", id="outline"),
        pytest.param("episode_outline_generate", False, False, False, "episode_outline", id="episode-outline"),
        pytest.param("outline_chapter_generate", False, True, False, "manuscript", id="manuscript"),
        # 작업 표의 CHECK 가 막지 않지만 라우트가 만들지 않는 조합 — 갈래를 가르지 않는 하위 칸은 무시한다.
        pytest.param("chapter_generate", False, True, False, "legacy_generate", id="generate-with-scene-outline"),
        pytest.param("chapter_regenerate", True, False, False, "legacy_regenerate", id="regenerate-with-parent"),
        pytest.param(
            "chapter_regenerate", True, True, False, "outline_regenerate", id="outline-regenerate-with-parent"
        ),
        pytest.param("ai_edit", False, True, False, "paragraph_edit", id="edit-with-scene-outline"),
        pytest.param("ai_edit", True, False, True, "block_edit", id="block-edit-with-parent"),
        pytest.param("outline_generate", True, False, False, "outline", id="outline-with-parent"),
        pytest.param("outline_chapter_generate", True, True, False, "manuscript", id="manuscript-with-parent"),
    ],
)
def test_variant_of_reads_only_the_column_that_splits_its_kind(
    kind: NovelJobKind, parent: bool, episode_outline: bool, block_edit: bool, expected: JobVariant
) -> None:
    """종류마다 그 종류를 가르는 하위 칸 하나만 읽는다(장 생성은 연쇄 부모, 다시 만들기는 장면 구성안 리비전, AI 수정은 패치 칸).
    깨지는 시나리오: 판정이 다른 종류의 하위 칸까지 읽어 연쇄 부모가 붙은 다시 만들기를 연쇄 자식으로 보거나, 패치 칸이 있는 AI
    수정을 문단 수정으로 돌려 엉뚱한 입력·저장을 탄다."""
    assert variant_of(_job(kind, parent=parent, episode_outline=episode_outline, block_edit=block_edit)) == expected


def test_variant_of_refuses_a_kind_it_does_not_know() -> None:
    """모르는 종류는 어느 갈래로도 흘려보내지 않는다. 깨지는 시나리오: 새 종류를 만드는 api 와 그 종류를 모르는 옛 워커가 겹친
    배포에서, 판정이 마지막 갈래(장 생성)로 흘러 과금된 엉뚱한 결과를 저장한다."""
    with pytest.raises(AssertionError):
        variant_of(_job("future_kind"))


# 갈래 → (종류, 호출 위치, 작업 모델을 싣는가, 화를 쓰는가, 집필권을 잠그는가, 워커가 도는가, 하루 상한 묶음, 연쇄 실행 전용)
_FACTS: dict[str, tuple[str, str | None, bool, bool, bool, bool, str | None, bool]] = {
    "legacy_generate": ("chapter_generate", "novelize_chapter", True, True, True, True, "start_message", False),
    "chain_child": ("chapter_generate", "novelize_chapter", True, True, True, False, None, False),
    "chain_parent": ("chain_generate", None, True, False, False, False, None, True),
    "legacy_regenerate": ("chapter_regenerate", "novelize_chapter", True, True, False, True, "start_message", False),
    "outline_regenerate": ("chapter_regenerate", "novelize_chapter", True, True, False, True, "episode_outline", False),
    "paragraph_edit": ("ai_edit", "novelize_revise", False, False, False, True, None, False),
    "block_edit": ("ai_edit", "novelize_revise", False, False, False, True, None, False),
    "outline": ("outline_generate", "novelize_outline", True, False, False, True, None, False),
    "episode_outline": ("episode_outline_generate", "novelize_episode_outline", True, False, False, True, None, False),
    "manuscript": (
        "outline_chapter_generate",
        "novelize_chapter",
        True,
        True,
        True,
        True,
        "episode_outline",
        False,
    ),
}


def test_every_variant_carries_the_facts_written_by_hand() -> None:
    """갈래마다 사실 칸이 손으로 적은 값과 같고, 갈래 표가 갈래 열 개를 빠짐없이 덮는다. 깨지는 시나리오: 사실 칸 하나를 잘못 옮겨
    워커가 연쇄 자식을 집거나, 다시 만들기가 집필권을 잠그거나, AI 수정이 작업 모델로 불려 다른 공급자로 간다."""
    assert set(VARIANT_FACTS) == set(get_args(JobVariant)) == set(_FACTS)
    actual = {
        variant: (
            facts.kind,
            facts.call_site,
            facts.model_in_context,
            facts.writes_chapter,
            facts.locks_writing,
            facts.worker_runs,
            facts.daily_limit_group,
            facts.chain_only,
        )
        for variant, facts in VARIANT_FACTS.items()
    }
    assert actual == _FACTS
    # 판정과 표가 같은 종류를 말한다 — 표의 종류로 만든 행이 그 갈래로 판정된다(하위 칸은 갈래가 요구하는 대로).
    for variant, facts in VARIANT_FACTS.items():
        row = _job(
            facts.kind,
            parent=variant == "chain_child",
            episode_outline=variant in ("outline_regenerate", "manuscript"),
            block_edit=variant == "block_edit",
        )
        assert variant_of(row) == variant


def test_kind_projections_of_the_facts() -> None:
    """사실 칸을 종류로 옮긴 집합과, 한 종류 안에서 갈래끼리 사실이 갈려 종류만으로는 거를 수 없는 종류. 종류 단위 SQL 은 이 갈린
    종류를 다른 조건(워커 고르기의 연쇄 부모 칸)으로 따로 거르거나 일부러 함께 센다(하루 상한이 연쇄 자식도 센다). 깨지는
    시나리오: 갈래를 더하면서 갈린 종류가 생겼는데 종류 단위 SQL 이 그 갈래까지 집는다."""
    assert set(kinds_where(worker_runs=True)) == set(get_args(NovelJobKind)) - {"chain_generate"}
    assert set(kinds_where(writes_chapter=True)) == {
        "chapter_generate",
        "chapter_regenerate",
        "outline_chapter_generate",
    }
    assert set(kinds_where(locks_writing=True)) == {"chapter_generate", "outline_chapter_generate"}
    assert set(kinds_where(daily_limit_group="start_message")) == {"chapter_generate", "chapter_regenerate"}
    assert set(kinds_where(daily_limit_group="episode_outline")) == {"chapter_regenerate", "outline_chapter_generate"}
    assert set(kinds_where(call_site="novelize_revise")) == {"ai_edit"}
    assert split_kinds(worker_runs=True) == {"chapter_generate"}
    assert split_kinds(daily_limit_group="start_message") == {"chapter_generate", "chapter_regenerate"}
    assert split_kinds(daily_limit_group="episode_outline") == {"chapter_regenerate"}
    assert split_kinds(writes_chapter=True) == frozenset()
    assert split_kinds(locks_writing=True) == frozenset()
    assert split_kinds(call_site="novelize_revise") == frozenset()


def test_the_runner_has_one_handler_per_variant_sharing_the_variant_facts() -> None:
    """실행 경로의 등록부가 갈래 열 개를 빠짐없이 덮고, 핸들러가 내보이는 사실은 갈래 표의 그 객체다. 깨지는 시나리오: 갈래를 더하고
    핸들러를 빠뜨려 그 갈래가 실행에서 길을 잃거나, 핸들러가 사실을 따로 베껴 표와 어긋난다."""
    assert set(runner.HANDLERS) == set(VARIANT_FACTS) == set(get_args(JobVariant))
    for variant, handler in runner.HANDLERS.items():
        assert handler.facts is VARIANT_FACTS[variant]


class _Chapters:
    """다시 만들 화를 찾는 세션 흉내 — 구성 흐름 화 다시 만들기의 입력 단계가 화 행 하나만 읽는다."""

    def __init__(self) -> None:
        self.chapter = object()

    async def get(self, _model: Any, _key: Any) -> object:
        return self.chapter


@pytest.mark.parametrize(
    ("variant", "builder"),
    [
        pytest.param("legacy_generate", "build_chapter_input", id="legacy_generate"),
        pytest.param("chain_child", "build_chapter_input", id="chain_child"),
        pytest.param("legacy_regenerate", "build_chapter_input", id="legacy_regenerate"),
        pytest.param("outline_regenerate", "build_outline_regenerate_input", id="outline_regenerate"),
        pytest.param("paragraph_edit", "build_revise_input", id="paragraph_edit"),
        pytest.param("block_edit", "build_block_edit_input", id="block_edit"),
        pytest.param("outline", "build_outline_input", id="outline"),
        pytest.param("episode_outline", "build_episode_outline_input", id="episode_outline"),
        pytest.param("manuscript", "build_outline_chapter_input", id="manuscript"),
    ],
)
async def test_each_handler_builds_its_input_through_the_runner_name_looked_up_at_call_time(
    monkeypatch: pytest.MonkeyPatch, variant: JobVariant, builder: str
) -> None:
    """핸들러는 입력 조립 함수를 실행 모듈의 이름으로, 부를 때 찾는다 — 그 이름을 바꿔 끼우면 핸들러가 바꾼 쪽을 부른다. 깨지는
    시나리오: 핸들러가 함수 참조를 클래스 속성이나 딕셔너리에 담아 두어, 원작 문안을 읽지 않으려고 입력 조립을 바꿔 끼우는 테스트가
    진짜 조립을 타거나, 갈래가 다른 입력 조립으로 이어진다."""
    calls: list[str] = []

    async def fake(*_args: Any, **_kwargs: Any) -> str:
        calls.append(builder)
        return "입력"

    monkeypatch.setattr(runner, builder, fake)
    facts = VARIANT_FACTS[variant]
    job = _job(
        facts.kind,
        parent=variant == "chain_child",
        episode_outline=variant in ("outline_regenerate", "manuscript"),
        block_edit=variant == "block_edit",
    )
    novel = Novel(id=job.novel_id, user_id=job.user_id, chat_room_id=uuid.uuid4())

    assert await runner.HANDLERS[variant].build_input(_Chapters(), job, novel) == "입력"  # type: ignore[arg-type]
    assert calls == [builder]


@pytest.mark.parametrize("variant", [pytest.param(v, id=v) for v in VARIANT_FACTS if v != "chain_parent"])
def test_each_handler_calls_at_its_call_site_with_the_job_model_only_when_the_facts_say_so(variant: JobVariant) -> None:
    """호출 문맥은 갈래의 호출 위치로 만들고, 작업 모델은 사실 칸이 싣는다고 할 때만 싣는다(AI 수정은 기본 모델). 깨지는 시나리오:
    AI 수정이 작업 모델로 불려 상위 모델 라우팅을 타거나, 구성안이 기본 모델로 불려 값을 낸 모델의 글을 받지 못한다."""
    facts = VARIANT_FACTS[variant]
    job = _job(facts.kind, parent=variant == "chain_child", block_edit=variant == "block_edit")
    novel = Novel(id=job.novel_id, user_id=job.user_id, chat_room_id=uuid.uuid4())
    assert facts.call_site is not None

    usage = runner.HANDLERS[variant].context(job, novel)

    base = LLMCallContext(call_site=facts.call_site, user_id=job.user_id, room_id=novel.chat_room_id)
    expected = LLMCallContext(
        call_site=facts.call_site, user_id=job.user_id, room_id=novel.chat_room_id, model="sonnet"
    )
    assert usage == (expected if variant not in ("paragraph_edit", "block_edit") else base)
