"""정본 기억 측정 하네스의 매처·지표 식·구간 — 손으로 셀 수 있는 작은 예로 식이 설계대로 세는지 본다.

구간은 알려진 값과 대조한다: Wilson 9/10 은 [0.596, 0.982], 단측 Clopper–Pearson 상한은 1/10 이 0.394, 0건이면
1 − 0.05^(1/n), Cohen κ 는 일치 0.7·우연 일치 0.5 인 표에서 0.4. 합성 이름과 문장만 쓴다."""

import itertools
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from api.novel_bible.core.types import EntityName, ItemDraft, Proposal, Proposition, SideQuote, VerifiedQuote
from novel_bible_eval import metrics
from novel_bible_eval.match import (
    ExtractedEvent,
    ExtractedFact,
    ExtractedKnowledge,
    direction_counts,
    matched_events,
    matched_facts,
    matched_knowledge,
)
from novel_bible_eval.report import compare_markdown, removal_markdown, removal_report, synthetic_report, to_markdown
from novel_bible_eval.run import ChapterOutcome, ClosedClash, JobOutcome
from novel_bible_eval.spec import EvalSet, PlantedEvent, PlantedFact, PlantedKnowledge, load_set

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


def _prop(
    subject: str, kind: str, value: str, *, attribute: str | None = None, holds: bool = True,
    subject_kind: str = "character",
) -> Proposition:
    return Proposition.model_validate(
        {"subject": subject, "subject_kind": subject_kind, "kind": kind, "attribute": attribute, "value": value,
         "holds": holds}
    )


def test_a_fact_matches_by_alias_and_by_any_allowed_surface_of_the_value() -> None:
    planted = [
        PlantedFact(subject="도윤", kind="possession", values=["낡은 등불", "등불"], paragraph=1),
        PlantedFact(subject="서하", kind="attribute", attribute="눈 색", values=["회색"], paragraph=1),
        PlantedFact(subject="서하", kind="life", values=["dead"], paragraph=1),
        PlantedFact(subject="하람", kind="attribute", attribute="키", values=["작다"], immutable=True, paragraph=1),
    ]
    extracted = [
        ExtractedFact(_prop("뱃사람", "possession", " 등불 ")),  # 별칭 + 허용 표기
        ExtractedFact(_prop("서하", "attribute", "회색", attribute="눈색")),  # 속성 이름이 다르다
        ExtractedFact(_prop("서하", "life", "dead", holds=False)),  # 유지 여부가 다르다
        ExtractedFact(_prop("하람", "attribute", "작다", attribute="키")),  # 불변 표시가 다르다
    ]
    assert matched_facts(planted, extracted, {"도윤": ["뱃사람"]}) == 1


def _knows(knower: str, subject: str, value: str) -> ExtractedKnowledge:
    return ExtractedKnowledge(knower=knower, kind="knows", proposition=_prop(subject, "possession", value))


def test_direction_errors_count_swaps_and_wrong_knowers_inside_the_denominator() -> None:
    planted = [
        PlantedKnowledge(knower="도윤", kind="knows", subject="서하", fact_kind="possession", values=["등불"],
                         subject_kind="character", paragraph=1),
        PlantedKnowledge(knower="서하", kind="knows", subject="도윤", fact_kind="possession", values=["지도"],
                         subject_kind="character", paragraph=1),
        # 자기 자신에 대한 앎은 뒤바뀜이 정의되지 않아 분모에 들지 않는다
        PlantedKnowledge(knower="서하", kind="knows", subject="서하", fact_kind="possession", values=["차"],
                         subject_kind="character", paragraph=1),
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
                         subject_kind="character", paragraph=1)
        for knower in ("도윤", "하람")
    ]
    assert direction_counts(planted, [_knows("하람", "서하", "등불")], {}) == (1, 0)
    assert direction_counts(planted[::-1], [_knows("하람", "서하", "등불")], {}) == (1, 0)
    # 정답 셋·제안 셋을 어떤 순서로 적어도 같다 — 바른 짝 둘, 남은 정답 하나가 앎 주체만 틀린 제안을 받는다.
    planted.append(PlantedKnowledge(knower="하람", kind="knows", subject="도윤", fact_kind="possession",
                                    values=["지도"], subject_kind="character", paragraph=1))
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
             blocks: list[uuid.UUID] | None = None, closed: tuple[ClosedClash, ...] = ()) -> ChapterOutcome:
    return ChapterOutcome(
        novel="synthetic-1", repeat=repeat, ordinal=ordinal, probe=probe, status=status, block_rules=list(block),
        warning_rules=list(warn), block_ids=[str(b) for b in blocks or []], jobs=list(jobs), closed=list(closed),
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
        _outcome(2),
        _outcome(3, "blocked", block=("knowledge_before_fact",)),
        _outcome(4, "failed", probe="dead-returns"),  # 실패는 오탐·재현율이 아니다 — 분모에서도 빠지고 따로 센다
        _outcome(4, probe="unrelated-memory", warn=("order_undetermined",)),
        _outcome(4, "blocked", probe="harbor-memory", block=("exit_then_appearance",)),  # 짝 화 1·2 는 정본에 있다
        _outcome(4, probe="rumor"),  # 기대는 3화가 정본에 없어 빠진다
    ]
    summary = metrics.blocking(eval_set, outcomes)
    # (차단된 기본 화 1 + 차단된 비충돌 탐침 1) / (기본 확정 3 + 남은 비충돌 탐침 1)
    assert (summary.false_positive.k, summary.false_positive.n) == (2, 4)
    assert {rule: ratio.k for rule, ratio in summary.by_rule.items() if ratio.k} == {
        "knowledge_before_fact": 1, "exit_then_appearance": 1
    }
    assert {group: (r.k, r.n) for group, r in summary.by_group.items()} == {"A": (1, 1)}
    assert (summary.recall.k, summary.recall.n) == (0, 0)
    assert summary.excluded == {"non_conflict": 1}
    assert {branch: (r.k, r.n) for branch, r in summary.failed.items()} == {
        "base": (0, 3), "conflict": (1, 1), "non_conflict": (0, 2), "warning": (0, 1)
    }
    assert summary.undeterminable  # 충돌 1/1 이 실패했고 비충돌 1/2 를 뺐다 — 25% 를 넘는다

    # 2화를 막으면 탐침 넷이 모두 기댈 화를 잃는다. 충돌 탐침은 위와 달리 기대 규칙으로 막히고 경고 탐침은 기대 경고를 내지만,
    # 짝이 정본에 없으니 둘 다 재현율에 넣지 않고 비충돌 탐침과 함께 뺀다.
    outcomes = [
        _outcome(1),
        _outcome(2, "blocked", block=("knowledge_before_fact",)),
        _outcome(3),
        _outcome(4, "blocked", probe="dead-returns", block=("exit_then_appearance",)),
        _outcome(4, probe="unrelated-memory", warn=("order_undetermined",)),
        _outcome(4, "blocked", probe="harbor-memory", block=("exit_then_appearance",)),
        _outcome(4, probe="rumor"),
    ]
    summary = metrics.blocking(eval_set, outcomes)
    assert summary.excluded == {"conflict": 1, "warning": 1, "non_conflict": 2}
    assert (summary.recall.k, summary.recall.n) == (0, 0)
    assert (summary.warning_recall.k, summary.warning_recall.n) == (0, 0)
    assert (summary.false_positive.k, summary.false_positive.n) == (1, 3)


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


def _clean_run() -> list[ChapterOutcome]:
    return [
        _outcome(1), _outcome(2), _outcome(3),
        _outcome(4, probe="dead-returns"), _outcome(4, probe="unrelated-memory"),
        _outcome(4, probe="harbor-memory"), _outcome(4, probe="rumor"),
    ]


def test_commits_that_never_reached_a_verdict_are_failures_and_too_many_leave_the_verdict_open() -> None:
    eval_set = load_set(FIXTURE)
    outcomes = _clean_run()
    outcomes[2] = _outcome(3, "extracting")  # 끝 상태에 닿지 않은 확정은 막히지 않은 확정이 아니다
    outcomes[6] = _outcome(4, "failed", probe="rumor")
    summary = metrics.blocking(eval_set, outcomes)
    # 막히지 않은 확정은 끝난 기본 화 둘 + 짝 화가 정본에 있는 비충돌 탐침 하나뿐이다.
    assert (summary.false_positive.k, summary.false_positive.n) == (0, 3)
    assert {branch: (r.k, r.n) for branch, r in summary.failed.items()} == {
        "base": (1, 3), "conflict": (0, 1), "non_conflict": (1, 2), "warning": (0, 1)
    }
    assert summary.undeterminable  # 기본 화 실패 1/3 이 25% 를 넘는다

    report = synthetic_report(eval_set, outcomes, [], adapter="fake")["metrics"]
    # 관측 오탐은 0 이지만 판정하지 않고, 실패율이 그 바로 옆에 지표로 실린다.
    assert report["block_false_positive"]["pass"] is None
    assert report["block_false_positive"]["undetermined"] == "실패·정본 불완전 25% 초과"
    assert (report["commit_failure.base"]["k"], report["commit_failure.base"]["n"]) == (1, 3)
    names = list(report)
    assert names[names.index("block_false_positive") + 1].startswith("commit_failure.")


def test_an_observed_false_positive_fails_the_block_line_even_when_the_run_halted_or_too_many_commits_failed() -> None:
    eval_set = load_set(FIXTURE)
    outcomes = _clean_run()
    outcomes[0] = _outcome(1, "blocked", block=("exit_then_appearance",))
    outcomes[2] = _outcome(3, "failed")
    assert metrics.blocking(eval_set, outcomes).undeterminable  # 기본 화 실패 1/3 이 25% 를 넘는다
    for halted in (None, "합성 멈춤"):
        entry = synthetic_report(eval_set, outcomes, [], adapter="fake", halted=halted)["metrics"]
        false_positive = entry["block_false_positive"]
        # 합격선이 0건이라 이미 본 오탐 하나로 미달이 정해진다 — 표본을 더 돌려도 합격으로 뒤집히지 않는다.
        assert (false_positive["k"], false_positive["n"], false_positive["pass"]) == (1, 2, False)
        assert "undetermined" not in false_positive


def test_a_run_whose_commits_all_failed_or_that_halted_gets_no_verdict() -> None:
    eval_set = load_set(FIXTURE)
    all_failed = synthetic_report(eval_set, [_outcome(n, "failed") for n in (1, 2, 3)], [], adapter="fake")
    false_positive = all_failed["metrics"]["block_false_positive"]
    assert (false_positive["k"], false_positive["n"], false_positive["pass"]) == (0, 0, None)
    assert false_positive["undetermined"] == "분모 0"

    clean = _clean_run()
    clean[0] = _outcome(1, jobs=(JobOutcome(slot="facts", status="succeeded", attempts=1, failure_code=None,
                                            proposal=Proposal(items=()).model_dump(mode="json"), calls=[]),))
    finished = synthetic_report(eval_set, clean, [], adapter="fake")["metrics"]
    assert finished["block_false_positive"]["pass"] is True
    assert finished["recall.facts"]["pass"] is False  # 사실 0/5
    assert "direction_error" not in finished  # 지식 작업이 없는 실행은 방향 오류 지표를 내지 않는다
    halted = synthetic_report(eval_set, clean, [], adapter="fake", halted="합성 멈춤")["metrics"]
    for name in ("block_false_positive", "recall.facts"):
        assert halted[name]["pass"] is None
        assert halted[name]["undetermined"] == "멈춘 실행"


def test_the_markdown_puts_the_verdict_on_the_mean_row_of_a_repeated_metric() -> None:
    eval_set = load_set(FIXTURE)
    outcomes = [
        _outcome(1, repeat=repeat, jobs=(JobOutcome(slot="facts", status="succeeded", attempts=1, failure_code=None,
                                                    proposal=Proposal(items=()).model_dump(mode="json"), calls=[]),))
        for repeat in (1, 2)
    ]
    rows = [line for line in to_markdown(synthetic_report(eval_set, outcomes, [], adapter="fake")).splitlines()
            if line.startswith("| recall.facts")]
    assert rows == [
        "| recall.facts (반복 1) | 0.000 | 0/5 | Wilson [0.000, 0.434] | - |",
        "| recall.facts (반복 2) | 0.000 | 0/5 | Wilson [0.000, 0.434] | - |",
        "| recall.facts (평균) | 0.000 | - | - | 미달 |",
    ]


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


# ── 매처의 다른 표기 ──────────────────────────────────────────────────


def test_a_fact_and_a_knowledge_proposition_match_an_allowed_other_spelling_of_the_attribute_name() -> None:
    # 속성 이름은 명세의 이름이나 그 다른 표기 중 하나면 맞다.
    planted = [PlantedFact(subject="등대지기", kind="attribute", attribute="눈 색", attribute_aliases=["눈동자 색"],
                           values=["잿빛"], immutable=True, paragraph=1)]
    other = ExtractedFact(_prop("등대지기", "attribute", "잿빛", attribute="눈동자  색"), True)
    assert matched_facts(planted, [other], {}) == 1
    unlisted = ExtractedFact(_prop("등대지기", "attribute", "잿빛", attribute="눈색"), True)
    assert matched_facts(planted, [unlisted], {}) == 0
    known = [PlantedKnowledge(knower="서하", kind="knows", subject="등대", subject_kind="object", fact_kind="attribute",
                              attribute="세워진 때", attribute_aliases=["지어진 때"], values=["백 년 전"], paragraph=1)]
    found = [ExtractedKnowledge("서하", "knows", _prop("등대", "attribute", "백 년 전", attribute="지어진 때",
                                                     subject_kind="object"))]
    assert matched_knowledge(known, found, {}) == 1
    assert direction_counts(known, [ExtractedKnowledge("등대", "knows", _prop("서하", "attribute", "백 년 전",
                                                                           attribute="지어진 때"))], {}) == (1, 1)


def test_a_proposition_naming_its_subject_under_another_kind_is_another_entity_and_matches_nothing() -> None:
    # 앱은 개체를 (종류, 정규 이름)으로 가른다 — 인물 등대지기와 사물 등대지기는 다른 개체이고 명제 키도 다르다. 그래서 주어
    # 종류를 틀린 제안은 그 인물의 사실이 아니라(불변 속성 모순 같은 비교에도 쓰이지 않는다) 맞음으로 세면 재현율이 부푼다.
    fact = [PlantedFact(subject="등대지기", kind="attribute", attribute="눈 색", values=["잿빛"], immutable=True,
                        paragraph=1)]
    as_object = ExtractedFact(_prop("등대지기", "attribute", "잿빛", attribute="눈 색", subject_kind="object"), True)
    assert matched_facts(fact, [as_object], {}) == 0
    assert matched_facts(fact, [as_object, ExtractedFact(_prop("등대지기", "attribute", "잿빛", attribute="눈 색"), True)],
                         {}) == 1
    # 지식 재현율도 명제 주어를 같은 개체로 냈어야 맞다.
    known = [PlantedKnowledge(knower="서하", kind="knows", subject="등대", subject_kind="object", fact_kind="attribute",
                              attribute="세워진 때", values=["백 년 전"], paragraph=1)]
    person = ExtractedKnowledge("서하", "knows", _prop("등대", "attribute", "백 년 전", attribute="세워진 때"))
    assert matched_knowledge(known, [person], {}) == 0
    # 방향 오류율은 다른 지표다 — 분모는 골격과 이름 꼴로만 정하고 주어 종류를 보지 않는다. 이름이 바르면 바른 짝, 앎 주체만
    # 틀리거나 뒤바뀌었으면 주어 종류가 틀려도 오류다.
    assert direction_counts(known, [person], {}) == (1, 0)
    stranger = ExtractedKnowledge("도윤", "knows", _prop("등대", "attribute", "백 년 전", attribute="세워진 때"))
    assert direction_counts(known, [stranger], {}) == (1, 1)
    swapped_as_object = ExtractedKnowledge(
        "등대", "knows", _prop("서하", "attribute", "백 년 전", attribute="세워진 때", subject_kind="object")
    )
    assert direction_counts(known, [swapped_as_object], {}) == (1, 1)


def test_a_wrong_subject_kind_does_not_take_an_error_out_of_the_direction_denominator() -> None:
    # 한 반복에 바른 짝 61 과 앎 주체만 틀린 짝 둘, 그중 하나는 명제 주어를 사물로 냈다. 그 하나를 분모에서 빼면 1/62 = 1.61%
    # 로 합격선 3% 아래가 되지만, 설계의 분모는 이름 꼴로 정해 2/63 = 3.17% 다 — 오류 한 건이 판정을 바꾸는 자리다.
    planted = [
        PlantedKnowledge(knower="도윤", kind="knows", subject="서하", fact_kind="possession", values=[f"물건{number}"],
                         subject_kind="character", paragraph=1)
        for number in range(63)
    ]
    found = [_knows("도윤", "서하", f"물건{number}") for number in range(61)]
    found += [
        _knows("등대지기", "서하", "물건61"),
        ExtractedKnowledge("등대지기", "knows", _prop("서하", "possession", "물건62", subject_kind="object")),
    ]
    assert direction_counts(planted, found, {}) == (63, 2)
    assert 2 / 63 > 0.03 > 1 / 62


# ── 차단 세부 — 규칙별·세부 종류별 오탐, 충돌 규칙별 재현율, 닫힌 값 범주·항목 ───────────────────────

_EYE_BLACK = {
    "key": "eye-black", "kind": "conflict", "group": "immutable_attribute_mismatch",
    "expected_rule": "immutable_attribute_mismatch",
    "closed": {"category": "enum:색", "values": ["잿빛", "검은색"], "canonical": ["회색", "검정"]},
    "depends_on": [3],
    "chapter": {
        "paragraphs": ["등대지기의 두 눈은 본디 검은색이었다."],
        "facts": [{"subject": "등대지기", "kind": "attribute", "attribute": "눈 색", "values": ["검은색"],
                   "immutable": True, "paragraph": 1}],
    },
}
_BLOOD_TYPE = {
    "key": "blood-type", "kind": "conflict", "group": "immutable_attribute_mismatch",
    "expected_rule": "immutable_attribute_mismatch",
    "closed": {"category": "enum:혈액형", "values": ["A형", "B형"], "canonical": ["A", "B"]},
    "depends_on": [1],
    "chapter": {
        "paragraphs": ["서하의 혈액형은 B형이었다."],
        "facts": [{"subject": "서하", "kind": "attribute", "attribute": "혈액형", "values": ["B형"], "immutable": True,
                   "paragraph": 1}],
    },
}


def _with_closed_probes() -> EvalSet:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["novels"][0]["probes"] += [_EYE_BLACK, _BLOOD_TYPE]
    return EvalSet.model_validate(raw)


def _closed(category: str, *values: str) -> ClosedClash:
    return ClosedClash(category=category, values=list(values))


def _detailed_run() -> list[ChapterOutcome]:
    """반복 1 기본 화는 모두 커밋되어 탐침이 모두 표본에 남고, 반복 2 의 2화가 혈액형 A·O 로 막힌다(같은 규칙의 검사 결과
    둘). 탐침: 충돌 셋(사망 뒤 등장은 막힘, 눈 색은 막힘, 혈액형은 놓침), 비충돌 둘(회상 탐침은 사망 뒤 등장과 색 검정·회색
    모순으로 막힘, 소문 탐침은 통과)."""
    blood = _closed("enum:혈액형", "A", "O")
    color = _closed("enum:색", "검정", "회색")
    return [
        _outcome(1), _outcome(2), _outcome(3),
        _outcome(1, repeat=2),
        _outcome(2, "blocked", block=("immutable_attribute_mismatch",) * 2, repeat=2, closed=(blood, blood)),
        _outcome(3, repeat=2),
        _outcome(4, "blocked", probe="dead-returns", block=("exit_then_appearance",)),
        _outcome(4, probe="unrelated-memory", warn=("order_undetermined",)),
        _outcome(4, "blocked", probe="harbor-memory", block=("exit_then_appearance", "immutable_attribute_mismatch"),
                 closed=(color,)),
        _outcome(4, probe="rumor"),
        _outcome(4, "blocked", probe="eye-black", block=("immutable_attribute_mismatch",), closed=(color,)),
        _outcome(4, probe="blood-type"),
    ]


def _counts(ratios: dict[str, metrics.Ratio]) -> dict[str, tuple[int, int]]:
    return {name: (ratio.k, ratio.n) for name, ratio in ratios.items()}


def test_false_positives_per_rule_share_the_whole_denominator_and_recall_splits_by_the_expected_rule() -> None:
    summary = metrics.blocking(_with_closed_probes(), _detailed_run())
    # 오탐 분모 = 기본 확정 6 + 비충돌 탐침 2. 규칙별 분자는 그 규칙 차단이 하나 이상인 확정이다 — 한 확정이 두 규칙으로 막히면
    # 두 규칙에 하나씩 들고, 같은 규칙의 검사 결과가 둘이어도 하나다. 규칙이 막지 않았어도 네 규칙이 모두 같은 분모로
    # 실린다(0건의 상한을 보이려고).
    assert (summary.false_positive.k, summary.false_positive.n) == (2, 8)
    assert _counts(summary.by_rule) == {
        "exit_then_appearance": (1, 8), "use_before_acquisition": (0, 8), "knowledge_before_fact": (0, 8),
        "immutable_attribute_mismatch": (2, 8),
    }
    assert _counts(summary.recall_by_rule) == {
        "exit_then_appearance": (1, 1), "use_before_acquisition": (0, 0), "knowledge_before_fact": (0, 0),
        "immutable_attribute_mismatch": (1, 2),
    }
    assert (summary.recall.k, summary.recall.n) == (2, 3)


def test_non_conflict_false_positives_are_counted_for_every_listed_subkind() -> None:
    subkinds = metrics.blocking(_with_closed_probes(), _detailed_run()).by_subkind
    # 갈래 A·B·C 의 세부 종류 33개가 모두 실린다 — 탐침이 없는 종류는 0/0 이라 빠진 종류가 보고서에 보인다.
    assert len(subkinds) == 10 + 4 + 19
    assert (subkinds["dead_in_flashback"].k, subkinds["dead_in_flashback"].n) == (1, 1)
    assert (subkinds["speculation_or_rumor"].k, subkinds["speculation_or_rumor"].n) == (0, 1)
    assert (subkinds["letter_grade_immutable"].k, subkinds["letter_grade_immutable"].n) == (0, 0)


def test_closed_value_blocks_are_counted_per_category_and_per_dictionary_item() -> None:
    closed = metrics.blocking(_with_closed_probes(), _detailed_run()).closed
    # 오탐은 확정에서 읽은 두 값으로, 오탐 분모 그대로(8). 재현율은 탐침 명세의 기대 갈래·두 값으로, 그 갈래·항목을 기대한 탐침
    # 수가 분모다.
    assert _counts(closed.false_positive_by_category) == {"enum:색": (1, 8), "enum:혈액형": (1, 8)}
    assert _counts(closed.false_positive_by_item) == {
        "enum:색/검정": (1, 8), "enum:색/회색": (1, 8), "enum:혈액형/A": (1, 8), "enum:혈액형/O": (1, 8),
    }
    assert _counts(closed.recall_by_category) == {"enum:색": (1, 1), "enum:혈액형": (0, 1)}
    assert _counts(closed.recall_by_item) == {
        "enum:색/검정": (1, 1), "enum:색/회색": (1, 1), "enum:혈액형/A": (0, 1), "enum:혈액형/B": (0, 1),
    }


def test_closed_value_recall_rows_count_a_block_only_when_it_came_from_the_expected_pair() -> None:
    # 규칙 단위 재현율은 기대 규칙으로 막히면 맞다. 갈래·항목 행은 그 탐침이 기대한 갈래·두 값에서 난 차단만 맞음으로 센다 —
    # 혈액형 탐침이 다른 속성(색)이나 다른 두 값(A·O)의 모순으로 막혔다면 혈액형 A·B 를 잡은 것이 아니다.
    run = [outcome for outcome in _detailed_run() if outcome.probe != "blood-type"]
    for clash, hit in (
        (_closed("enum:색", "검정", "회색"), 0), (_closed("enum:혈액형", "A", "O"), 0), (_closed("enum:혈액형", "A", "B"), 1),
    ):
        blocked = _outcome(4, "blocked", probe="blood-type", block=("immutable_attribute_mismatch",), closed=(clash,))
        summary = metrics.blocking(_with_closed_probes(), [*run, blocked])
        assert _counts(summary.recall_by_rule)["immutable_attribute_mismatch"] == (2, 2)
        assert _counts(summary.closed.recall_by_category)["enum:혈액형"] == (hit, 1)
        items = _counts(summary.closed.recall_by_item)
        assert (items["enum:혈액형/A"], items["enum:혈액형/B"]) == ((hit, 1), (hit, 1))


def _height_set() -> EvalSet:
    """사망 뒤 등장 탐침을 키 170cm·180cm 닫힌 값 모순 탐침으로 바꾼 픽스처."""
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    probe = next(probe for probe in raw["novels"][0]["probes"] if probe["key"] == "dead-returns")
    probe["expected_rule"] = "immutable_attribute_mismatch"
    probe["closed"] = {"category": "number:cm", "values": ["170cm", "180cm"]}
    return EvalSet.model_validate(raw)


@pytest.mark.parametrize(
    ("values", "hit"),
    [
        # 앱은 수로 견준다 — 모델이 180.0cm 로 내도 같은 두 값의 모순이다.
        pytest.param(("170", "180.0"), 1, id="same-number-another-spelling"),
        pytest.param(("170", "180", "180.0"), 1, id="one-number-read-twice"),
        pytest.param(("170", "190"), 0, id="another-number"),
    ],
)
def test_a_closed_value_hit_compares_the_values_the_way_the_rule_reads_them(values: tuple[str, ...], hit: int) -> None:
    blocked = _outcome(4, "blocked", probe="dead-returns", block=("immutable_attribute_mismatch",),
                       closed=(_closed("number:cm", *values),))
    closed = metrics.blocking(_height_set(), [_outcome(1), _outcome(2), _outcome(3), blocked]).closed
    assert _counts(closed.recall_by_category) == {"number:cm": (hit, 1)}


def test_number_units_are_categories_and_have_no_dictionary_items() -> None:
    # 반복 2 의 2화가 키 170cm·180cm 로 막힌다 — 탐침은 반복 1 정본에 기대 그대로 남아 분모는 기본 6 + 비충돌 2.
    blocked = _outcome(2, "blocked", block=("immutable_attribute_mismatch",), repeat=2,
                       closed=(_closed("number:cm", "170", "180"),))
    outcomes = [*_clean_run(), _outcome(1, repeat=2), blocked, _outcome(3, repeat=2)]
    closed = metrics.blocking(load_set(FIXTURE), outcomes).closed
    assert _counts(closed.false_positive_by_category) == {"number:cm": (1, 8)}
    assert closed.false_positive_by_item == {}


def _sides(row: dict[str, Any]) -> tuple[tuple[int, int], tuple[int, int]]:
    return (row["before"]["k"], row["before"]["n"]), (row["after"]["k"], row["after"]["n"])


def test_the_removal_table_puts_the_before_and_after_values_side_by_side_under_a_biased_after_header() -> None:
    # 혈액형 A 를 뺀다. 뺀 뒤 반복 2 의 2화(혈액형 A·O 로 막혔던 기본 화)는 커밋되고, A·B 를 심은 혈액형 탐침은 차단 대신 표면
    # 차이 경고를 받는다 — 사전에서 빠진 값은 닫힌 값이 아니어서 앱이 막지 않고 경고를 낸다.
    eval_set = _with_closed_probes()
    before = _detailed_run()
    after = [
        o.model_copy(update={"status": "committed", "block_rules": [], "closed": []})
        if (o.repeat, o.ordinal, o.probe) == (2, 2, None)
        else o.model_copy(update={"warning_rules": ["attribute_surface_differs"]}) if o.probe == "blood-type" else o
        for o in before
    ]
    table = removal_report(eval_set, before, after, removed=["enum:혈액형/A"])
    assert table["removed"] == ["enum:혈액형/A"]
    rows = {row["name"]: row for row in table["rows"]}
    first = rows["block_false_positive"]
    assert _sides(first) == ((2, 8), (1, 8))
    assert first["after"]["upper"] == pytest.approx(metrics.upper_bound(1, 8))
    rule = rows["block_false_positive.immutable_attribute_mismatch"]
    assert _sides(rule) == ((2, 8), (1, 8))
    # 뺀 항목을 기대한 탐침은 뺀 뒤에도 실제 모순이라 차단 재현율 분모에 남고(빼기 전에도 놓쳤다), 경고 재현율에도 따로 든다.
    assert _sides(rows["block_recall"]) == ((2, 3), (2, 3))
    assert _sides(rows["block_recall.immutable_attribute_mismatch"]) == ((1, 2), (1, 2))
    assert _sides(rows["warning_recall"]) == ((1, 1), (2, 2))
    assert _sides(rows["warning_recall.enum:혈액형/A"]) == ((0, 0), (1, 1))
    # 뺀 뒤 0건이 된 갈래·항목의 오탐은 0/0 이 아니라 같은 확정·탐침 수(8)를 분모로 0건과 그 상한을 보인다.
    for name in ("block_false_positive.enum:혈액형/A", "block_false_positive.enum:혈액형"):
        assert _sides(rows[name]) == ((1, 8), (0, 8))
        assert rows[name]["after"]["value"] == 0.0
        assert rows[name]["after"]["upper"] == pytest.approx(1 - 0.05 ** (1 / 8))
    markdown = removal_markdown(table)
    header = next(line for line in markdown.splitlines() if line.startswith("| 지표"))
    assert "빼기 전" in header and "같은 세트로 고르고 다시 잰 값이라 낙관 쪽으로 기운다" in header
    assert "enum:혈액형/A" in markdown


def _ten_conflicts() -> EvalSet:
    """충돌 탐침 열 — 사망 뒤 등장 여덟과 혈액형 A 를 기대한 닫힌 값 모순 둘(A·B, A·O)."""
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    probes = raw["novels"][0]["probes"]
    dead = next(probe for probe in probes if probe["key"] == "dead-returns")
    blood_o: dict[str, Any] = json.loads(json.dumps(_BLOOD_TYPE))
    blood_o["key"] = "blood-type-o"
    blood_o["closed"] = {"category": "enum:혈액형", "values": ["A형", "O형"], "canonical": ["A", "O"]}
    blood_o["chapter"]["paragraphs"] = ["서하의 혈액형은 O형이었다."]
    blood_o["chapter"]["facts"][0]["values"] = ["O형"]
    probes += [{**dead, "key": f"dead-returns-{number}"} for number in range(2, 9)] + [_BLOOD_TYPE, blood_o]
    return EvalSet.model_validate(raw)


def test_a_probe_expecting_a_removed_item_stays_in_the_after_recall_and_counts_as_missed() -> None:
    # 혈액형 A 를 뺀다. A 를 기대한 두 탐침은 뺀 뒤에도 실제 모순이다 — 앱이 더는 막지 못할 뿐이다. 빼기 전에 하나(A·O)는
    # 막고 하나(A·B)는 놓쳐 9/10, 뺀 뒤에는 둘 다 경고만 받아 8/10 이다. 분모에서 빼면 8/8 로 빼서 재현율이 오른 것처럼 읽힌다.
    eval_set = _ten_conflicts()
    base = [_outcome(1), _outcome(2), _outcome(3)]
    dead = [_outcome(4, "blocked", probe=probe.key, block=("exit_then_appearance",))
            for probe in eval_set.novels[0].probes if probe.key.startswith("dead-returns")]
    assert len(dead) == 8
    before = [*base, *dead, _outcome(4, probe="blood-type"),
              _outcome(4, "blocked", probe="blood-type-o", block=("immutable_attribute_mismatch",),
                       closed=(_closed("enum:혈액형", "A", "O"),))]
    after = [*base, *dead, *(_outcome(4, probe=key, warn=("attribute_surface_differs",))
                             for key in ("blood-type", "blood-type-o"))]
    rows = {row["name"]: row for row in removal_report(eval_set, before, after, removed=["enum:혈액형/A"])["rows"]}
    assert _sides(rows["block_recall"]) == ((9, 10), (8, 10))
    assert rows["block_recall"]["after"]["value"] == pytest.approx(0.8)
    for name in ("block_recall.immutable_attribute_mismatch", "block_recall.enum:혈액형", "block_recall.enum:혈액형/A"):
        assert _sides(rows[name]) == ((1, 2), (0, 2))
    assert _sides(rows["warning_recall.enum:혈액형/A"]) == ((0, 0), (2, 2))


# ── 사건 관계 정확도 ─────────────────────────────────────────────────


def _flashback_job(blocks: list[uuid.UUID], paragraph: int, relation: tuple[str, uuid.UUID] | None) -> JobOutcome:
    items = [
        ItemDraft(local_key="event1", table="event", fields={"actuality": "flashback"}, quotes=(_quote(),),
                  covers_blocks=(blocks[paragraph - 1],)),
    ]
    if relation is not None:
        items.append(
            ItemDraft(local_key="relation1", table="event_relation", quotes=(_quote(),),
                      fields={"event": "event1", "relation": relation[0], "to_anchor_block_id": str(relation[1]),
                              "to_chapter_id": str(uuid.uuid4())})
        )
    return JobOutcome(slot="events", status="succeeded", attempts=1, failure_code=None,
                      proposal=Proposal(items=tuple(items)).model_dump(mode="json"), calls=[])


def _relation_set(first_events: list[list[int]], target_event: int) -> EvalSet:
    """1화 사건 정답의 문단을 바꾸고, 3화 회상 관계가 1화의 `target_event` 번째 사건을 가리키게 한 픽스처."""
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    chapters = raw["novels"][0]["chapters"]
    template = chapters[0]["events"][0]
    chapters[0]["events"] = [{**template, "paragraphs": paragraphs} for paragraphs in first_events]
    chapters[2]["events"][1]["relation"]["event"] = target_event
    return EvalSet.model_validate(raw)


_FIXTURE_FIRST = [[1, 2], [3, 4]]  # 픽스처 1화 사건 정답 그대로
# 1화에 주선 사건 셋 — 둘째 사건의 앱 대상 블록(3문단, 1문단은 첫 사건이 덮는다)이 셋째 사건 문단 안에 든다.
_NESTED_FIRST = [[1, 2], [1, 3], [3, 4]]


@pytest.mark.parametrize(
    ("first_events", "target_event", "first_found", "kind", "target_paragraph", "flashback_paragraph", "expected"),
    [
        pytest.param(_FIXTURE_FIRST, 1, [[1, 2], [3, 4]], "before", 1, 2, (1, 1), id="kind-and-target-right"),
        pytest.param(_FIXTURE_FIRST, 1, [[1, 2], [3, 4]], "after", 1, 2, (0, 1), id="kind-wrong"),
        # 1화 둘째 추출 사건의 대상 블록이다.
        pytest.param(_FIXTURE_FIRST, 1, [[1, 2], [3, 4]], "before", 3, 2, (0, 1), id="target-another-event"),
        # 맞는 사건이 덮는 문단이지만 앱이 어느 추출 사건에도 대상으로 주지 않는 블록이다.
        pytest.param(_FIXTURE_FIRST, 1, [[1, 2], [3, 4]], "before", 2, 2, (0, 1),
                     id="target-inside-the-event-but-not-an-anchor"),
        # 회상 사건을 맞히지 못하면 그 관계는 분모에 들지 않는다.
        pytest.param(_FIXTURE_FIRST, 1, [[1, 2], [3, 4]], "before", 1, 3, (0, 0), id="flashback-not-matched"),
        # 모델이 1화 첫 사건을 3문단까지 뽑아, 앱은 둘째 사건을 3문단이 아니라 4문단으로 가리킨다. 정답 경계로 셈한
        # 대상(3문단)과 달라도 둘째 사건을 짚었으므로 맞다.
        pytest.param(_FIXTURE_FIRST, 2, [[1, 2, 3], [3, 4]], "before", 4, 2, (1, 1),
                     id="right-event-under-extracted-boundaries"),
        # 셋째 사건을 가리킬 관계가 둘째 사건을 골랐다 — 그 대상 블록(3문단)은 셋째 사건 문단 안에 있지만 틀린 사건이다.
        pytest.param(_NESTED_FIRST, 3, _NESTED_FIRST, "before", 3, 2, (0, 1), id="wrong-event-whose-anchor-lies-inside"),
        pytest.param(_NESTED_FIRST, 3, _NESTED_FIRST, "before", 4, 2, (1, 1), id="nested-target-right"),
    ],
)
def test_relation_accuracy_resolves_the_target_block_through_the_extracted_target_chapter(
    first_events: list[list[int]], target_event: int, first_found: list[list[int]], kind: str, target_paragraph: int,
    flashback_paragraph: int, expected: tuple[int, int],
) -> None:
    # 3화 회상 사건(2문단)이 1화 사건 앞이다. 앱은 1화에서 추출·저장된 주선 사건마다, 앞 차례 사건이 덮지 않는 첫 블록을 대상
    # 블록으로 준다 — 관계는 그 블록을 1화 추출 사건으로 되풀어, 그 사건이 심은 대상 사건과 짝일 때 맞다.
    eval_set = _relation_set(first_events, target_event)
    first, third = [uuid.uuid4() for _ in range(4)], [uuid.uuid4() for _ in range(5)]
    job = _flashback_job(third, flashback_paragraph, (kind, first[target_paragraph - 1]))
    outcomes = [
        _outcome(1, jobs=(_event_job(first, first_found),), blocks=first), _outcome(2),
        _outcome(3, jobs=(job,), blocks=third),
    ]
    (accuracy,) = metrics.relation_accuracy(eval_set, outcomes) or []
    assert (accuracy.k, accuracy.n) == expected


# ── 각색 후보 재현율 ─────────────────────────────────────────────────


def _fact_job(*items: tuple[Proposition, bool, tuple[SideQuote, ...]]) -> JobOutcome:
    drafts = tuple(
        ItemDraft(local_key=f"fact{n}", table="fact", fields={"immutable": immutable}, quotes=(_quote(),),
                  proposition=proposition, side_quotes=sides)
        for n, (proposition, immutable, sides) in enumerate(items, start=1)
    )
    return JobOutcome(slot="facts", status="succeeded", attempts=1, failure_code=None,
                      proposal=Proposal(items=drafts).model_dump(mode="json"), calls=[])


_ROW = uuid.uuid4()
_NOTE = uuid.uuid4()


@pytest.mark.parametrize(
    ("play_side", "source_side", "expected"),
    [
        pytest.param(SideQuote(origin="play", chat_memory_fact_id=_ROW),
                     SideQuote(origin="source_canon", source_field="work_setting"), ((1, 1), (1, 1)), id="both-found"),
        pytest.param(SideQuote(origin="play", chat_memory_fact_id=uuid.uuid4()),
                     SideQuote(origin="source_canon", source_field="keyword_note", keyword_note_id=_NOTE),
                     ((0, 1), (0, 1)), id="other-row-and-other-source-text"),
    ],
)
def test_adaptation_recall_counts_differences_whose_matched_fact_points_at_the_planted_row_or_source_text(
    play_side: SideQuote, source_side: SideQuote, expected: tuple[tuple[int, int], tuple[int, int]]
) -> None:
    # 2화 지도 소지는 명세의 플레이 1행과, 3화 등대지기 눈 색은 원작 작품 설정(`S`)과 다르다. 심기가 돌려준 행·노트 id 로
    # 근거를 명세의 행·글로 되짚는다.
    eval_set = load_set(FIXTURE)
    second = _fact_job((_prop("서하", "possession", "젖은 지도"), False, (play_side,)))
    third = _fact_job((_prop("등대지기", "attribute", "잿빛", attribute="눈 색"), True, (source_side,)))
    ids = {"play_rows": [str(_ROW)], "notes": [str(_NOTE)]}
    outcomes = [
        _outcome(1).model_copy(update=ids),
        _outcome(2, jobs=(second,)).model_copy(update=ids),
        _outcome(3, jobs=(third,)).model_copy(update=ids),
    ]
    recall = metrics.adaptation_recall(eval_set, outcomes)
    play, source = recall["play"][0], recall["source_canon"][0]
    assert ((play.k, play.n), (source.k, source.n)) == expected


# ── 실제 모델·구현과 단계별 원가 ──────────────────────────────────────


def test_models_and_costs_are_split_by_stage_from_every_metered_call() -> None:
    calls: list[dict[str, Any]] = [
        {"stage": "events.extract", "backend": "gemini", "model": "gemini-3.5-flash-lite", "promptTokens": 1_000_000,
         "outputTokens": 0, "durationMs": 100},
        {"stage": "events.extract", "backend": "gemini", "model": "gemini-3.5-flash-lite", "promptTokens": 0,
         "outputTokens": 0, "durationMs": 300},
        {"stage": "conflicts.judge", "backend": "anthropic", "model": "claude-haiku-5-5", "promptTokens": 0,
         "outputTokens": 1_000_000, "durationMs": 50},
        {"stage": "conflicts.judge", "backend": "anthropic", "model": "unpriced-synthetic-model"},
    ]
    assert metrics.models(calls) == [
        {"stage": "conflicts.judge", "backend": "anthropic", "model": "claude-haiku-5-5", "calls": 1},
        {"stage": "conflicts.judge", "backend": "anthropic", "model": "unpriced-synthetic-model", "calls": 1},
        {"stage": "events.extract", "backend": "gemini", "model": "gemini-3.5-flash-lite", "calls": 2},
    ]
    by_stage = metrics.stage_costs(calls)
    assert by_stage["events.extract"]["usd"] == pytest.approx(0.30)
    assert by_stage["events.extract"]["median_ms"] == 200
    assert by_stage["conflicts.judge"]["usd"] == pytest.approx(0.50)
    assert by_stage["conflicts.judge"]["unpriced"] == 1


# ── 어댑터 비교표 ────────────────────────────────────────────────────


def test_the_adapter_comparison_puts_each_adapters_value_and_verdict_side_by_side() -> None:
    eval_set = load_set(FIXTURE)
    clean = _clean_run()
    blocked = _clean_run()
    blocked[5] = _outcome(4, "blocked", probe="harbor-memory", block=("exit_then_appearance",))
    calls = [
        {"stage": "events.extract", "backend": "gemini", "model": "gemini-3.5-flash-lite"},
        {"stage": "conflicts.judge", "backend": "anthropic", "model": "unpriced-synthetic-model"},
    ]
    reports = {
        "gemini": synthetic_report(eval_set, clean, [], adapter="gemini", calls=calls),
        "haiku": synthetic_report(eval_set, blocked, [], adapter="haiku"),
    }
    lines = compare_markdown(reports).splitlines()
    assert "| 지표 | gemini | haiku |" in lines
    row = next(line for line in lines if line.startswith("| block_false_positive |"))
    assert row == "| block_false_positive | 0.000 (0/5) 합격 | 0.200 (1/5) 미달 |"
    models = next(line for line in lines if line.startswith("| 실제 모델 |"))
    assert "events.extract gemini/gemini-3.5-flash-lite" in models
    # 단가표에 없는 모델의 호출은 원가 합계에서 말없이 빠지지 않고 따로 센 줄에 나온다.
    unpriced = next(line for line in lines if line.startswith("| 단가표에 없는 호출 |"))
    assert unpriced == "| 단가표에 없는 호출 | 1 | 0 |"
    # 합성 원고를 Claude 계열이 써서 Claude 어댑터의 재현율이 부풀 수 있다는 한계를 표에 함께 적는다.
    assert any("Claude" in line for line in lines)
