"""정본 기억 측정 하네스의 매처·지표 식·구간 — 손으로 셀 수 있는 작은 예로 식이 설계대로 세는지 본다.

구간은 알려진 값과 대조한다: Wilson 9/10 은 [0.596, 0.982], 단측 Clopper–Pearson 상한은 1/10 이 0.394, 0건이면
1 − 0.05^(1/n), Cohen κ 는 일치 0.7·우연 일치 0.5 인 표에서 0.4. 합성 이름과 문장만 쓴다."""

import itertools
import uuid
from pathlib import Path
from typing import Any

import pytest

from api.novel_bible.core.types import EntityName, ItemDraft, Proposal, Proposition, VerifiedQuote
from novel_bible_eval import metrics
from novel_bible_eval.match import (
    ExtractedEvent,
    ExtractedKnowledge,
    direction_counts,
    matched_events,
    matched_facts,
)
from novel_bible_eval.run import ChapterOutcome, JobOutcome
from novel_bible_eval.spec import PlantedEvent, PlantedFact, PlantedKnowledge, load_set

FIXTURE = Path(__file__).parent / "fixtures" / "novel_bible_eval" / "small_set.json"


# ── 구간 ────────────────────────────────────────────────────────────


def test_wilson_matches_the_known_interval_for_nine_of_ten() -> None:
    low, high = metrics.wilson(9, 10)
    assert low == pytest.approx(0.5958, abs=1e-3)
    assert high == pytest.approx(0.9821, abs=1e-3)


def test_the_one_sided_upper_bound_matches_known_values() -> None:
    assert metrics.upper_bound(0, 136) == pytest.approx(1 - 0.05 ** (1 / 136))
    assert metrics.upper_bound(0, 63) == pytest.approx(0.0464, abs=1e-3)
    assert metrics.upper_bound(1, 10) == pytest.approx(0.3942, abs=1e-3)
    assert metrics.upper_bound(5, 5) == 1.0


def test_the_cluster_bootstrap_is_fixed_by_its_seed_and_brackets_the_pooled_ratio() -> None:
    clusters = [(1, 4), (3, 4), (0, 3), (2, 2), (4, 5)]
    first = metrics.cluster_bootstrap(clusters, seed=7)
    assert first == metrics.cluster_bootstrap(clusters, seed=7)
    pooled = sum(k for k, _ in clusters) / sum(n for _, n in clusters)
    assert first[0] <= pooled <= first[1]
    assert metrics.cluster_bootstrap([(1, 2), (2, 4)]) == (0.5, 0.5)


def test_cohen_kappa_matches_the_textbook_table() -> None:
    human = ["y"] * 25 + ["n"] * 25
    judge = ["y"] * 20 + ["n"] * 5 + ["y"] * 10 + ["n"] * 15
    assert metrics.cohen_kappa(human, judge) == pytest.approx(0.4)


# ── 매처 ────────────────────────────────────────────────────────────


def test_an_event_matches_when_its_paragraphs_overlap_and_its_actuality_agrees() -> None:
    planted = [
        PlantedEvent(paragraphs=[1, 2]),
        PlantedEvent(paragraphs=[3], actuality="flashback"),
    ]
    extracted = [
        ExtractedEvent(paragraphs=frozenset({2}), actuality="present"),
        ExtractedEvent(paragraphs=frozenset({2}), actuality="present"),  # 한 정답은 한 번만 맞는다
        ExtractedEvent(paragraphs=frozenset({3}), actuality="present"),  # 현실성이 다르다
    ]
    assert matched_events(planted, extracted) == 1


def _prop(subject: str, kind: str, value: str, *, attribute: str | None = None, holds: bool = True) -> Proposition:
    return Proposition.model_validate(
        {"subject": subject, "kind": kind, "attribute": attribute, "value": value, "holds": holds}
    )


def test_a_fact_matches_by_alias_and_by_any_allowed_surface_of_the_value() -> None:
    planted = [
        PlantedFact(subject="도윤", kind="possession", values=["낡은 등불", "등불"], paragraph=1),
        PlantedFact(subject="서하", kind="attribute", attribute="눈 색", values=["회색"], paragraph=1),
        PlantedFact(subject="서하", kind="life", values=["dead"], paragraph=1),
    ]
    extracted = [
        _prop("뱃사람", "possession", " 등불 "),  # 별칭 + 허용 표기
        _prop("서하", "attribute", "회색", attribute="눈색"),  # 속성 이름이 다르다
        _prop("서하", "life", "dead", holds=False),  # 유지 여부가 다르다
    ]
    assert matched_facts(planted, extracted, {"도윤": ["뱃사람"]}) == 1


def _knows(knower: str, subject: str, value: str) -> ExtractedKnowledge:
    return ExtractedKnowledge(knower=knower, kind="knows", proposition=_prop(subject, "possession", value))


def test_direction_errors_count_swaps_and_wrong_knowers_inside_the_denominator() -> None:
    planted = [
        PlantedKnowledge(knower="도윤", kind="knows", subject="서하", fact_kind="possession", values=["등불"],
                         paragraph=1),
        PlantedKnowledge(knower="서하", kind="knows", subject="도윤", fact_kind="possession", values=["지도"],
                         paragraph=1),
        # 자기 자신에 대한 앎은 뒤바뀜이 정의되지 않아 분모에 들지 않는다
        PlantedKnowledge(knower="서하", kind="knows", subject="서하", fact_kind="possession", values=["차"],
                         paragraph=1),
    ]
    extracted = [
        _knows("서하", "도윤", "등불"),  # 첫 정답의 뒤바뀜 — 그 정답은 바른 짝이 먼저 가져간다
        _knows("도윤", "서하", "등불"),  # 첫 정답의 바른 짝
        _knows("등대지기", "도윤", "지도"),  # 둘째 정답의 앎 주체만 틀림
        _knows("서하", "도윤", "나침반"),  # 골격(값)이 달라 어느 정답에도 들지 않는다
        _knows("서하", "서하", "차"),
    ]
    assert direction_counts(planted, extracted, {}) == (2, 1)


def test_direction_pairs_do_not_depend_on_the_order_the_answers_were_written_in() -> None:
    # 두 인물이 같은 명제를 안다. 추출은 그중 둘째 인물의 바른 짝 하나다 — 첫 인물이 그 제안을 제 쪽의 앎 주체 오류로
    # 먼저 가져가면 안 된다.
    planted = [
        PlantedKnowledge(knower=knower, kind="knows", subject="서하", fact_kind="possession", values=["등불"],
                         paragraph=1)
        for knower in ("도윤", "하람")
    ]
    assert direction_counts(planted, [_knows("하람", "서하", "등불")], {}) == (1, 0)
    assert direction_counts(planted[::-1], [_knows("하람", "서하", "등불")], {}) == (1, 0)
    # 정답 셋·제안 셋을 어떤 순서로 적어도 같다 — 바른 짝 둘, 남은 정답 하나가 앎 주체만 틀린 제안을 받는다.
    planted.append(PlantedKnowledge(knower="하람", kind="knows", subject="도윤", fact_kind="possession",
                                    values=["지도"], paragraph=1))
    found = [_knows("도윤", "서하", "등불"), _knows("하람", "서하", "등불"), _knows("등대지기", "도윤", "지도")]
    results = {
        direction_counts(list(answers), list(extracted), {})
        for answers in itertools.permutations(planted) for extracted in itertools.permutations(found)
    }
    assert results == {(3, 1)}


# ── 지표 식(결과 묶음 위) ──────────────────────────────────────────────


def _quote() -> VerifiedQuote:
    return VerifiedQuote(block_id=uuid.uuid4(), char_start=0, char_end=1, quote_sha256="0" * 64)


def _event_job(blocks: list[uuid.UUID], covered: list[list[int]], *, dropped: dict[str, int] | None = None,
               attempts: int = 1) -> JobOutcome:
    items = tuple(
        ItemDraft(
            local_key=f"event{number}", table="event", fields={"actuality": "present"},
            names={"present": (EntityName(kind="character", name="서하"),)}, quotes=(_quote(),),
            covers_blocks=tuple(blocks[index - 1] for index in paragraphs),
        )
        for number, paragraphs in enumerate(covered, start=1)
    )
    proposal = Proposal(items=items, dropped=dropped or {}).model_dump(mode="json")
    return JobOutcome(slot="events", status="succeeded", attempts=attempts, failure_code=None, proposal=proposal,
                      calls=[])


def _outcome(ordinal: int, status: str = "committed", *, probe: str | None = None, block: tuple[str, ...] = (),
             warn: tuple[str, ...] = (), jobs: tuple[JobOutcome, ...] = (), repeat: int = 1,
             blocks: list[uuid.UUID] | None = None) -> ChapterOutcome:
    return ChapterOutcome(
        novel="synthetic-1", repeat=repeat, ordinal=ordinal, probe=probe, status=status, block_rules=list(block),
        warning_rules=list(warn), block_ids=[str(b) for b in blocks or []], jobs=list(jobs),
    )


def test_recall_counts_planted_events_per_repeat_only_for_slots_that_ran() -> None:
    eval_set = load_set(FIXTURE)
    outcomes: list[ChapterOutcome] = []
    for repeat, covered in ((1, [[1], [3]]), (2, [[2]])):
        blocks = [uuid.uuid4() for _ in range(4)]
        job = _event_job(blocks, covered)
        outcomes.append(_outcome(1, jobs=(job,), repeat=repeat, blocks=blocks))
    recall = metrics.recall(eval_set, outcomes)
    assert set(recall) == {"events"}  # 사실·지식 작업이 없으면 그 지표를 내지 않는다
    # 정답 분모는 기본 세트 전체(2 + 3 + 3)다 — 뽑히지 않은 화의 정답도 놓친 것이다.
    assert [(ratio.k, ratio.n) for ratio in recall["events"]] == [(2, 8), (1, 8)]


def test_blocking_counts_false_positives_and_drops_probes_with_an_incomplete_canon() -> None:
    eval_set = load_set(FIXTURE)
    outcomes = [
        _outcome(1),
        _outcome(2, "blocked", block=("knowledge_before_fact",)),
        _outcome(3, "failed"),  # 실패는 오탐이 아니다 — 분모에서도 빠지고 따로 센다
        _outcome(4, probe="dead-returns"),  # 짝 화 2 가 정본에 없다 → 정본 불완전
        _outcome(4, probe="unrelated-memory", warn=("order_undetermined",)),  # 짝 화 2 가 없어 빠진다
        _outcome(4, "blocked", probe="harbor-memory", block=("exit_then_appearance",)),
        _outcome(4, probe="rumor"),  # 짝 화 2·3 이 둘 다 정본에 없어 빠진다
    ]
    summary = metrics.blocking(eval_set, outcomes)
    # (차단된 기본 화 1 + 차단된 비충돌 탐침 1) / (실패하지 않은 기본 확정 2 + 남은 비충돌 탐침 1)
    assert (summary.false_positive.k, summary.false_positive.n) == (2, 3)
    assert summary.by_rule == {"knowledge_before_fact": 1, "exit_then_appearance": 1}
    assert {group: (r.k, r.n) for group, r in summary.by_group.items()} == {"A": (1, 1)}
    assert (summary.recall.k, summary.recall.n) == (0, 0)
    assert summary.excluded == {"conflict": 1, "warning": 1, "non_conflict": 1}
    assert summary.failed == 1
    assert summary.undeterminable  # 충돌 1/1, 비충돌 1/2 를 뺐다 — 25% 를 넘는다


def test_blocking_recall_needs_the_expected_rule_and_warning_recall_the_expected_name() -> None:
    eval_set = load_set(FIXTURE)
    outcomes = [
        _outcome(1), _outcome(2), _outcome(3),
        _outcome(4, "blocked", probe="dead-returns", block=("exit_then_appearance",)),
        _outcome(4, probe="unrelated-memory", warn=("return_unstated",)),
        _outcome(4, probe="harbor-memory"),
        _outcome(4, probe="rumor"),
    ]
    summary = metrics.blocking(eval_set, outcomes)
    assert (summary.recall.k, summary.recall.n) == (1, 1)
    assert (summary.warning_recall.k, summary.warning_recall.n) == (0, 1)
    assert (summary.false_positive.k, summary.false_positive.n) == (0, 5)
    assert {group: (r.k, r.n) for group, r in summary.by_group.items()} == {"A": (0, 1), "C": (0, 1)}
    assert not summary.undeterminable


def test_the_quote_rate_counts_kept_items_against_items_dropped_for_their_quote() -> None:
    blocks = [uuid.uuid4() for _ in range(4)]
    job = _event_job(blocks, [[1], [2], [3]], dropped={"quote_not_found": 1, "quote_outside_event": 1,
                                                       "paragraphs_invalid": 2})
    ratio = metrics.quote_rate([_outcome(1, jobs=(job,), blocks=blocks)])
    # 문단이 틀려 버린 항목은 인용을 검사하기 전에 버렸으므로 인용 분모에 넣지 않는다.
    assert (ratio.k, ratio.n) == (3, 5)


def test_the_schema_failure_rate_counts_attempts_not_jobs() -> None:
    attempts: list[tuple[str, str | None]] = [
        ("events.extract", "schema_invalid"), ("events.extract", None), ("events.extract", "llm_error"),
        ("events.extract", None),
    ]
    ratio = metrics.schema_failure_rate(attempts)
    assert (ratio.k, ratio.n) == (1, 4)


def test_costs_and_latencies_come_from_the_call_records() -> None:
    calls: list[dict[str, Any]] = [
        {"callSite": "novel_bible_extract_events", "model": "gemini-3.5-flash-lite", "promptTokens": 1_000_000,
         "outputTokens": 0, "durationMs": 100},
        {"callSite": "novel_bible_extract_events", "model": "gemini-3.5-flash-lite", "promptTokens": 0,
         "outputTokens": 1_000_000, "durationMs": 300},
    ]
    job = JobOutcome(slot="events", status="succeeded", attempts=2, failure_code=None, proposal=None, calls=calls)
    cost = metrics.cost([_outcome(1, jobs=(job,))])
    assert cost["usd"] == pytest.approx(0.30 + 2.50)
    assert cost["calls"] == 2
    assert cost["unpriced"] == 0
    assert cost["median_ms"] == 200
