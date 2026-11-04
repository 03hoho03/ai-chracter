"""정본 기억 측정 하네스의 합성 명세 — 정답(심은 사건·사실·지식)과 탐침의 짝 화 목록을 읽기 전에 꼴을 본다.

명세가 틀리면 측정이 조용히 엉뚱한 분모를 센다(범위 밖 문단을 가리킨 정답은 맞힐 수 없고, 없는 화에 기댄 탐침은 늘 정본 불완전이다).
그래서 읽는 순간 거절한다. 픽스처와 아래 문장은 모두 합성이다."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from novel_bible_eval.spec import EvalSet, load_set

FIXTURE = Path(__file__).parent / "fixtures" / "novel_bible_eval" / "small_set.json"


def _raw() -> dict[str, Any]:
    raw: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return raw


def test_the_ci_fixture_reads_as_one_novel_of_three_chapters_and_four_probes() -> None:
    eval_set = load_set(FIXTURE)
    (novel,) = eval_set.novels
    assert len(novel.chapters) == 3
    assert [probe.kind for probe in novel.probes] == ["conflict", "warning", "non_conflict", "non_conflict"]
    assert "합성" in eval_set.note


def _rejects(raw: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        EvalSet.model_validate(raw)


def test_a_planted_event_outside_the_chapter_paragraphs_is_rejected() -> None:
    raw = _raw()
    raw["novels"][0]["chapters"][0]["events"][0]["paragraphs"] = [1, 9]
    _rejects(raw)


def test_a_planted_fact_quoting_a_missing_paragraph_is_rejected() -> None:
    raw = _raw()
    raw["novels"][0]["chapters"][0]["facts"][0]["paragraph"] = 0
    _rejects(raw)


def test_a_paragraph_that_would_split_into_two_blocks_is_rejected() -> None:
    raw = _raw()
    raw["novels"][0]["chapters"][0]["paragraphs"][0] = "첫 줄이다.\n\n둘째 줄이다."
    _rejects(raw)


def test_a_probe_leaning_on_a_chapter_the_novel_does_not_have_is_rejected() -> None:
    raw = _raw()
    raw["novels"][0]["probes"][0]["depends_on"] = [4]
    _rejects(raw)


def test_a_conflict_probe_must_expect_a_blocking_rule_and_a_warning_probe_a_warning_rule() -> None:
    raw = _raw()
    raw["novels"][0]["probes"][0]["expected_rule"] = "order_undetermined"
    _rejects(raw)
    raw = _raw()
    raw["novels"][0]["probes"][1]["expected_rule"] = "exit_then_appearance"
    _rejects(raw)


def test_a_non_conflict_probe_names_one_of_the_four_groups_and_expects_no_rule() -> None:
    raw = _raw()
    raw["novels"][0]["probes"][2]["group"] = "E"
    _rejects(raw)
    raw = _raw()
    raw["novels"][0]["probes"][2]["expected_rule"] = "exit_then_appearance"
    _rejects(raw)


def test_probe_keys_are_unique_across_the_set() -> None:
    raw = _raw()
    raw["novels"][0]["probes"][1]["key"] = raw["novels"][0]["probes"][0]["key"]
    _rejects(raw)
