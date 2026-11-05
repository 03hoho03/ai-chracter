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
    # 속성 이름은 명세의 이름이나 그 다른 표기 중 하나면 맞다. 주어 종류는 견주지 않는다 — 이름이 개체를 가린다.
    planted = [PlantedFact(subject="등대지기", kind="attribute", attribute="눈 색", attribute_aliases=["눈동자 색"],
                           values=["잿빛"], immutable=True, paragraph=1)]
    other = ExtractedFact(_prop("등대지기", "attribute", "잿빛", attribute="눈동자  색", subject_kind="object"), True)
    assert matched_facts(planted, [other], {}) == 1
    unlisted = ExtractedFact(_prop("등대지기", "attribute", "잿빛", attribute="눈색"), True)
    assert matched_facts(planted, [unlisted], {}) == 0
    known = [PlantedKnowledge(knower="서하", kind="knows", subject="등대", subject_kind="object", fact_kind="attribute",
                              attribute="세워진 때", attribute_aliases=["지어진 때"], values=["백 년 전"], paragraph=1)]
    found = [ExtractedKnowledge("서하", "knows", _prop("등대", "attribute", "백 년 전", attribute="지어진 때"))]
    assert matched_knowledge(known, found, {}) == 1
    assert direction_counts(known, [ExtractedKnowledge("등대", "knows", _prop("서하", "attribute", "백 년 전",
                                                                           attribute="지어진 때"))], {}) == (1, 1)


# ── 차단 세부 — 규칙별·세부 종류별 오탐, 충돌 규칙별 재현율, 닫힌 값 범주·항목 ───────────────────────

_EYE_BLACK = {
    "key": "eye-black", "kind": "conflict", "group": "immutable_attribute_mismatch",
    "expected_rule": "immutable_attribute_mismatch", "closed": {"category": "enum:색", "values": ["잿빛", "검은색"]},
    "depends_on": [3],
    "chapter": {
        "paragraphs": ["등대지기의 두 눈은 본디 검은색이었다."],
        "facts": [{"subject": "등대지기", "kind": "attribute", "attribute": "눈 색", "values": ["검은색"],
                   "immutable": True, "paragraph": 1}],
    },
}
_BLOOD_TYPE = {
    "key": "blood-type", "kind": "conflict", "group": "immutable_attribute_mismatch",
    "expected_rule": "immutable_attribute_mismatch", "closed": {"category": "enum:혈액형", "values": ["A형", "B형"]},
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


def test_number_units_are_categories_and_have_no_dictionary_items() -> None:
    # 반복 2 의 2화가 키 170cm·180cm 로 막힌다 — 탐침은 반복 1 정본에 기대 그대로 남아 분모는 기본 6 + 비충돌 2.
    blocked = _outcome(2, "blocked", block=("immutable_attribute_mismatch",), repeat=2,
                       closed=(_closed("number:cm", "170", "180"),))
    outcomes = [*_clean_run(), _outcome(1, repeat=2), blocked, _outcome(3, repeat=2)]
    closed = metrics.blocking(load_set(FIXTURE), outcomes).closed
    assert _counts(closed.false_positive_by_category) == {"number:cm": (1, 8)}
    assert closed.false_positive_by_item == {}


def test_the_removal_table_puts_the_before_and_after_values_side_by_side_under_a_biased_after_header() -> None:
    eval_set = _with_closed_probes()
    before = _detailed_run()
    after = [o.model_copy(update={"status": "committed", "block_rules": [], "closed": []})
             if (o.repeat, o.ordinal, o.probe) == (2, 2, None) else o for o in before]
    table = removal_report(eval_set, before, after, removed=["enum:혈액형/A"])
    assert table["removed"] == ["enum:혈액형/A"]
    rows = {row["name"]: row for row in table["rows"]}
    first = rows["block_false_positive"]
    assert (first["before"]["k"], first["before"]["n"], first["after"]["k"], first["after"]["n"]) == (2, 8, 1, 8)
    assert first["after"]["upper"] == pytest.approx(metrics.upper_bound(1, 8))
    rule = rows["block_false_positive.immutable_attribute_mismatch"]
    assert (rule["before"]["k"], rule["after"]["k"]) == (2, 1)
    recall = rows["block_recall.immutable_attribute_mismatch"]
    assert (recall["before"]["k"], recall["before"]["n"], recall["after"]["k"]) == (1, 2, 1)
    item = rows["block_false_positive.enum:혈액형/A"]
    assert (item["before"]["k"], item["after"]["k"]) == (1, 0)
    markdown = removal_markdown(table)
    header = next(line for line in markdown.splitlines() if line.startswith("| 지표"))
    assert "빼기 전" in header and "같은 세트로 고르고 다시 잰 값이라 낙관 쪽으로 기운다" in header
    assert "enum:혈액형/A" in markdown


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


@pytest.mark.parametrize(
    ("kind", "target_paragraph", "flashback_paragraph", "expected"),
    [
        pytest.param("before", 1, 2, (1, 1), id="kind-and-target-right"),
        pytest.param("after", 1, 2, (0, 1), id="kind-wrong"),
        # 1화 둘째 사건의 대상 블록이다.
        pytest.param("before", 3, 2, (0, 1), id="target-another-event"),
        # 같은 사건이 덮는 문단이지만 앱이 그 사건으로 푸는 대상 블록(첫 문단)이 아니다.
        pytest.param("before", 2, 2, (0, 1), id="target-inside-the-event-but-not-its-anchor"),
        # 회상 사건을 맞히지 못하면 그 관계는 분모에 들지 않는다.
        pytest.param("before", 1, 3, (0, 0), id="flashback-not-matched"),
    ],
)
def test_relation_accuracy_resolves_the_target_block_to_the_planted_target_event(
    kind: str, target_paragraph: int, flashback_paragraph: int, expected: tuple[int, int]
) -> None:
    # 3화 회상 사건(2문단)이 1화 첫 사건(1·2문단) 앞이다 — 앱은 그 사건을 앞 차례 사건이 덮지 않는 첫 블록(1문단)으로 가리킨다.
    eval_set = load_set(FIXTURE)
    first, third = [uuid.uuid4() for _ in range(4)], [uuid.uuid4() for _ in range(5)]
    job = _flashback_job(third, flashback_paragraph, (kind, first[target_paragraph - 1]))
    outcomes = [_outcome(1, blocks=first), _outcome(2), _outcome(3, jobs=(job,), blocks=third)]
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
    calls = [{"stage": "events.extract", "backend": "gemini", "model": "gemini-3.5-flash-lite"}]
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
    # 합성 원고를 Claude 계열이 써서 Claude 어댑터의 재현율이 부풀 수 있다는 한계를 표에 함께 적는다.
    assert any("Claude" in line for line in lines)
