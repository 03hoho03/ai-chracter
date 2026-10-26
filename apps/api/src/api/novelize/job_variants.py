"""소설 작업 갈래 — 작업 행 하나가 어느 실행 경로로 도는지(갈래)와, 갈래마다 붙은 사실.

작업 행의 종류 칸(`kind`)만으로는 실행 경로가 갈리지 않는다. 장 생성은 혼자 도는 생성과 연쇄 부모 아래의 자식으로, 다시 만들기는
옛 흐름 묶음과 구성 흐름 화(장면 구성안 리비전이 있다)로, AI 수정은 연속 범위 문단 수정과 여러 문단 수정(패치 칸이 있다)으로 다시
나뉜다. `variant_of` 가 종류와 그 종류를 가르는 하위 칸 하나만 읽어 갈래 열 개 중 하나를 고르고, 실행 경로는 그 갈래로 핸들러를
찾는다(`runner.HANDLERS`). 판정이 모든 종류를 덮는지는 타입 검사가 보므로, 종류를 더하고 갈래를 빠뜨리면 실행 경로로 흘러가기
전에 막힌다.

이 모듈은 `db.models.novel`·`llm.call_policy` 밖의 `api` 모듈을 import 하지 않는 잎 모듈이다. 입력 조립(`inputs.py`)이
`variant_of` 로 갈래를 읽고 실행 모듈(`runner.py`)이 입력 조립을 import 하므로, 판정을 실행 모듈에 두면 입력 조립 → 실행 모듈
순환이 된다. 핸들러(행동)는 실행 모듈에 두고 핸들러가 `facts` 로 이 표의 객체를 그대로 내보인다 — 사실을 두 곳에 베끼지 않는다.

사실 칸을 읽는 곳은 실행 모듈(`call_site`·`model_in_context`·`chain_only`)과, 실행 모듈을 거치지 않고 이 잎 모듈을 바로 읽는
자리들이다 — 워커 목록(`worker_runs`), 마지막 장 모델 읽기(`writes_chapter`), 집필권 잠금 시각(`locks_writing`), 하루 상한
묶음 고르기와 세기(`daily_limit_group`), 작업 응답·미결 수정 목록·수정 적용과 버리기·낡은 수정 비우기(`call_site`·
`model_in_context`), 작업 시작과 연쇄 진행 응답(`chain_only`).
소설화 모듈에서 kind 로 직접 가르는 곳은 갈래 표뿐이다 — 실행 모듈도 갈래로 고른다(`tests/test_novelize_kind_literal_guard.py`
가 지킨다 — 작업 행 만들기·가격 함수 같은 값 자리는 허용 문맥이다).

`kinds_where` 는 사실 칸을 종류로 옮긴다(종류 단위 SQL 이 쓴다). 한 종류 안에서 갈래끼리 사실이 갈리면(`split_kinds`) 종류만으로는
그 사실대로 거를 수 없다 — 그 SQL 은 다른 조건으로 따로 거르거나(워커 고르기의 연쇄 부모 칸 조건) 일부러 함께 센다."""

from dataclasses import dataclass
from typing import Literal, assert_never, get_args

from api.db.models.novel import NovelJob, NovelJobKind
from api.llm.call_policy import LLMCallSite

JobVariant = Literal[
    "legacy_generate",
    "chain_child",
    "chain_parent",
    "legacy_regenerate",
    "outline_regenerate",
    "paragraph_edit",
    "block_edit",
    "outline",
    "episode_outline",
    "manuscript",
]

# 하루 상한을 무엇 하나에 묶어 세는가 — 같은 시작 메시지의 장 생성·옛 흐름 다시 만들기, 같은 장면 구성안의 원고·구성 흐름 다시 만들기.
DailyLimitGroup = Literal["start_message", "episode_outline"]


def variant_of(job: NovelJob) -> JobVariant:
    """작업 행의 갈래. 종류마다 그 종류를 가르는 하위 칸 하나만 읽고, 다른 종류의 하위 칸은 보지 않는다. 모르는 종류는
    `AssertionError` 다 — 실행 경로가 내부 오류로 환불한다."""
    kind = job.kind
    match kind:
        case "chapter_generate":
            return "legacy_generate" if job.parent_job_id is None else "chain_child"
        case "chain_generate":
            return "chain_parent"
        case "chapter_regenerate":
            return "legacy_regenerate" if job.episode_outline_id is None else "outline_regenerate"
        case "ai_edit":
            return "paragraph_edit" if job.block_edit is None else "block_edit"
        case "outline_generate":
            return "outline"
        case "episode_outline_generate":
            return "episode_outline"
        case "outline_chapter_generate":
            return "manuscript"
        case _:
            assert_never(kind)


@dataclass(frozen=True)
class VariantFacts:
    """갈래 하나의 사실.

    - `call_site`: 모델 호출 위치. 연쇄 부모는 직접 부르지 않아 None.
    - `model_in_context`: 작업에 적힌 모델로 부르고 응답에 그 모델을 싣는가. AI 수정만 아니다(기본 모델로 부르고 응답 모델 칸이 빈다).
    - `writes_chapter`: 화를 쓰는가(마지막 장 모델 읽기가 고르는 작업).
    - `locks_writing`: 첫 화를 저장하면 집필권을 잠그는가 — 새 화를 만드는 갈래만. 다시 만들기는 이미 있는 화를 고친다.
    - `worker_runs`: 소설화 워커가 대기열에서 집는가. 연쇄 부모는 api 안에서, 연쇄 자식은 부모가 직접 돌린다.
    - `daily_limit_group`: 하루 상한을 무엇에 묶어 세는가. None 이면 하루 상한이 없다.
    - `chain_only`: 연쇄 실행으로만 돈다 — 묶음 하나짜리 실행 경로에 들어오면 내부 오류다."""

    kind: NovelJobKind
    call_site: LLMCallSite | None
    model_in_context: bool
    writes_chapter: bool
    locks_writing: bool
    worker_runs: bool
    daily_limit_group: DailyLimitGroup | None
    chain_only: bool


VARIANT_FACTS: dict[JobVariant, VariantFacts] = {
    "legacy_generate": VariantFacts(
        kind="chapter_generate",
        call_site="novelize_chapter",
        model_in_context=True,
        writes_chapter=True,
        locks_writing=True,
        worker_runs=True,
        daily_limit_group="start_message",
        chain_only=False,
    ),
    "chain_child": VariantFacts(
        kind="chapter_generate",
        call_site="novelize_chapter",
        model_in_context=True,
        writes_chapter=True,
        locks_writing=True,
        worker_runs=False,
        daily_limit_group=None,
        chain_only=False,
    ),
    "chain_parent": VariantFacts(
        kind="chain_generate",
        call_site=None,
        model_in_context=True,
        writes_chapter=False,
        locks_writing=False,
        worker_runs=False,
        daily_limit_group=None,
        chain_only=True,
    ),
    "legacy_regenerate": VariantFacts(
        kind="chapter_regenerate",
        call_site="novelize_chapter",
        model_in_context=True,
        writes_chapter=True,
        locks_writing=False,
        worker_runs=True,
        daily_limit_group="start_message",
        chain_only=False,
    ),
    "outline_regenerate": VariantFacts(
        kind="chapter_regenerate",
        call_site="novelize_chapter",
        model_in_context=True,
        writes_chapter=True,
        locks_writing=False,
        worker_runs=True,
        daily_limit_group="episode_outline",
        chain_only=False,
    ),
    "paragraph_edit": VariantFacts(
        kind="ai_edit",
        call_site="novelize_revise",
        model_in_context=False,
        writes_chapter=False,
        locks_writing=False,
        worker_runs=True,
        daily_limit_group=None,
        chain_only=False,
    ),
    "block_edit": VariantFacts(
        kind="ai_edit",
        call_site="novelize_revise",
        model_in_context=False,
        writes_chapter=False,
        locks_writing=False,
        worker_runs=True,
        daily_limit_group=None,
        chain_only=False,
    ),
    "outline": VariantFacts(
        kind="outline_generate",
        call_site="novelize_outline",
        model_in_context=True,
        writes_chapter=False,
        locks_writing=False,
        worker_runs=True,
        daily_limit_group=None,
        chain_only=False,
    ),
    "episode_outline": VariantFacts(
        kind="episode_outline_generate",
        call_site="novelize_episode_outline",
        model_in_context=True,
        writes_chapter=False,
        locks_writing=False,
        worker_runs=True,
        daily_limit_group=None,
        chain_only=False,
    ),
    "manuscript": VariantFacts(
        kind="outline_chapter_generate",
        call_site="novelize_chapter",
        model_in_context=True,
        writes_chapter=True,
        locks_writing=True,
        worker_runs=True,
        daily_limit_group="episode_outline",
        chain_only=False,
    ),
}


def facts_of(job: NovelJob) -> VariantFacts:
    """작업 행의 갈래 사실. 판정은 `variant_of` 그대로라 모르는 종류는 `AssertionError` 다."""
    return VARIANT_FACTS[variant_of(job)]


def _matches(facts: VariantFacts, wanted: dict[str, object]) -> bool:
    return all(getattr(facts, name) == value for name, value in wanted.items())


def kinds_where(**wanted: object) -> tuple[NovelJobKind, ...]:
    """주어진 사실 칸 값을 모두 가진 갈래가 하나라도 있는 종류. 순서는 `NovelJobKind` 의 순서다."""
    hits = {facts.kind for facts in VARIANT_FACTS.values() if _matches(facts, wanted)}
    return tuple(kind for kind in get_args(NovelJobKind) if kind in hits)


def split_kinds(**wanted: object) -> frozenset[NovelJobKind]:
    """주어진 사실 칸 값을 가진 갈래와 갖지 않은 갈래가 함께 있는 종류 — 종류만으로는 그 사실대로 거를 수 없다."""
    hits = {facts.kind for facts in VARIANT_FACTS.values() if _matches(facts, wanted)}
    misses = {facts.kind for facts in VARIANT_FACTS.values() if not _matches(facts, wanted)}
    return frozenset(hits & misses)
