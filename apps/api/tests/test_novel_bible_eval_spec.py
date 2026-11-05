"""정본 기억 측정 하네스의 합성 명세 — 정답(심은 사건·사실·지식)과 탐침의 짝 화 목록을 읽기 전에 꼴을 본다.

명세가 틀리면 측정이 조용히 엉뚱한 분모를 센다(범위 밖 문단을 가리킨 정답은 맞힐 수 없고, 없는 화에 기댄 탐침은 늘 정본 불완전이다).
그래서 읽는 순간 거절한다. 픽스처와 아래 문장은 모두 합성이다."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from novel_bible_eval.spec import NON_CONFLICT_SUBKINDS, EvalSet, load_set

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


def test_an_immutable_mark_on_a_planted_fact_that_is_not_an_attribute_is_rejected() -> None:
    raw = _raw()
    raw["novels"][0]["chapters"][0]["facts"][0]["immutable"] = True  # 소지 — 슬롯 검증이 버려 맞힐 수 없다
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


# ── 원작·플레이·장면 구성안·회상 관계·지식 주어 종류·탐침 세부 종류 ─────────────────────────────

_DROP = object()  # 그 칸을 지운다
Edit = tuple[tuple[str | int, ...], Any]


def _edited(*edits: Edit) -> dict[str, Any]:
    """픽스처의 소설 하나에서 경로마다 값을 바꾼(또는 지운) 원본."""
    raw = _raw()
    for path, value in edits:
        target = raw["novels"][0]
        for step in path[:-1]:
            target = target[step]
        if value is _DROP:
            del target[path[-1]]
        else:
            target[path[-1]] = value
    return raw


def test_the_fixture_carries_a_source_a_play_row_a_scene_outline_a_relation_and_subject_kinds() -> None:
    (novel,) = load_set(FIXTURE).novels
    assert novel.source is not None and novel.source.kind == "story" and len(novel.source.notes) == 1
    assert [(row.visible_from, row.subject) for row in novel.play] == [(2, "서하")]
    assert [chapter.scenes is None for chapter in novel.chapters] == [True, True, False]
    scenes = novel.chapters[2].scenes
    assert scenes is not None and [(scene.start, scene.flashback) for scene in scenes] == [(1, False), (2, True), (3, False)]
    relation = novel.chapters[2].events[1].relation
    assert relation is not None and (relation.kind, relation.chapter, relation.event) == ("before", 1, 1)
    kinds = [known.subject_kind for chapter in novel.chapters for known in chapter.knowledge]
    assert kinds == ["character", "object"]
    assert [probe.subkind for probe in novel.probes] == [None, None, "dead_in_flashback", "speculation_or_rumor"]


def test_each_non_conflict_branch_but_the_free_one_has_a_fixed_list_of_subkinds() -> None:
    assert {group: len(names) for group, names in NON_CONFLICT_SUBKINDS.items()} == {"A": 10, "B": 4, "C": 19}
    names = [name for group in NON_CONFLICT_SUBKINDS.values() for name in group]
    assert len(set(names)) == len(names)


_RELATION = {"kind": "before", "chapter": 1, "event": 1}
_B4 = ((("probes", 0, "expected_rule"), "immutable_attribute_mismatch"),)


@pytest.mark.parametrize(
    "edits",
    [
        pytest.param([(("chapters", 0, "knowledge", 0, "subject_kind"), _DROP)], id="knowledge-without-subject-kind"),
        pytest.param([(("chapters", 0, "facts", 0, "attribute_aliases"), ["가진 등불"])],
                     id="attribute-aliases-without-an-attribute"),
        pytest.param([(("chapters", 2, "events", 0, "relation"), _RELATION)], id="relation-on-a-main-line-event"),
        pytest.param([(("chapters", 2, "events", 1, "relation", "chapter"), 3)], id="relation-to-its-own-chapter"),
        pytest.param([(("chapters", 2, "events", 1, "relation", "event"), 3)], id="relation-to-a-missing-event"),
        pytest.param(
            [(("probes", 2, "depends_on"), [1, 3]),
             (("probes", 2, "chapter", "events", 0, "relation"), {"kind": "after", "chapter": 3, "event": 2})],
            id="relation-to-a-flashback-the-prior-list-does-not-show",
        ),
        pytest.param([(("probes", 2, "chapter", "events", 0, "relation"), {"kind": "overlap", "chapter": 2, "event": 1})],
                     id="probe-relation-to-a-chapter-it-does-not-lean-on"),
        pytest.param([(("chapters", 0, "scenes"), [])], id="empty-scene-list"),
        pytest.param([(("chapters", 2, "scenes", 0, "start"), 2)], id="scenes-not-starting-at-the-first-paragraph"),
        pytest.param([(("chapters", 2, "scenes", 2, "start"), 2)], id="scenes-not-ascending"),
        pytest.param([(("chapters", 2, "scenes", 2, "start"), 6)], id="scene-starting-past-the-last-paragraph"),
        pytest.param([(("source",), _DROP), (("chapters", 2, "facts", 0, "source_difference"), _DROP)],
                     id="play-rows-without-a-source"),
        pytest.param([(("play", 0, "object"), "도윤")], id="play-row-with-both-target-and-attribute"),
        pytest.param([(("play", 0, "attribute"), _DROP)], id="play-row-with-neither-target-nor-attribute"),
        pytest.param([(("play", 0, "visible_from"), 0)], id="play-row-visible-from-a-chapter-the-novel-lacks"),
        pytest.param([(("chapters", 1, "facts", 1, "play_difference"), 2)], id="play-difference-to-a-missing-row"),
        pytest.param([(("play", 0, "visible_from"), 3)], id="play-difference-before-the-row-is-visible"),
        pytest.param([(("chapters", 2, "facts", 0, "source_difference", "label"), "K2")],
                     id="source-difference-to-a-missing-note"),
        pytest.param([(("chapters", 2, "facts", 0, "source_difference", "quote"), "원작에 없는 구절")],
                     id="source-difference-quoting-text-the-source-lacks"),
        pytest.param([(("probes", 2, "subkind"), "speculation_or_rumor")], id="subkind-of-another-branch"),
        pytest.param([(("probes", 3, "subkind"), _DROP)], id="non-conflict-probe-without-a-subkind"),
        pytest.param([(("probes", 3, "group"), "D")], id="free-chapter-probe-with-a-subkind"),
        pytest.param([(("probes", 0, "subkind"), "dead_in_flashback")], id="conflict-probe-with-a-subkind"),
        pytest.param(list(_B4), id="closed-value-conflict-without-its-expected-pair"),
        pytest.param([(("probes", 0, "closed"), {"category": "enum:혈액형", "values": ["A형", "B형"]})],
                     id="expected-pair-on-another-rule"),
        pytest.param([*_B4, (("probes", 0, "closed"), {"category": "enum:혈액형", "values": ["A형", "검은색"]})],
                     id="expected-pair-across-categories"),
        pytest.param([*_B4, (("probes", 0, "closed"), {"category": "enum:혈액형", "values": ["A형", "에이형"]})],
                     id="expected-pair-of-the-same-value"),
        pytest.param([*_B4, (("probes", 0, "closed"), {"category": "enum:색", "values": ["A형", "B형"]})],
                     id="expected-pair-under-the-wrong-category"),
        pytest.param([*_B4, (("probes", 0, "closed"), {"category": "enum:혈액형", "values": ["A형"]})],
                     id="expected-pair-with-one-value"),
    ],
)
def test_a_spec_the_harness_could_not_seed_or_score_is_rejected(edits: list[Edit]) -> None:
    _rejects(_edited(*edits))


@pytest.mark.parametrize(
    "closed",
    [
        pytest.param({"category": "enum:혈액형", "values": ["A형", "비형"]}, id="dictionary"),
        pytest.param({"category": "number:cm", "values": ["170cm", "182 cm"]}, id="number"),
    ],
)
def test_a_closed_value_conflict_probe_names_the_category_and_the_two_values_the_rule_reads(
    closed: dict[str, Any],
) -> None:
    EvalSet.model_validate(_edited(*_B4, (("probes", 0, "closed"), closed)))


def test_a_free_chapter_probe_has_no_subkind() -> None:
    EvalSet.model_validate(_edited((("probes", 3, "group"), "D"), (("probes", 3, "subkind"), _DROP)))


def test_the_warning_probe_for_a_reappearance_inside_an_unrelated_flashback_carries_the_alive_fact_and_the_return() -> None:
    # 사망 뒤 관계 없는 회상 속에서 살아 있는 인물이 그 뒤 주선 장면에 다시 나오는 화 — 순서가 정해지지 않아 경고를 기대한다.
    # 명세가 이 꼴(관계 없는 회상 사건, 그 문단의 삶 사실, 뒤 문단의 주선 사건에 같은 인물)을 실을 수 있어야 그 경고를 잰다.
    (novel,) = load_set(FIXTURE).novels
    probe = next(probe for probe in novel.probes if probe.expected_rule == "order_undetermined")
    flashback, later = probe.chapter.events
    (alive,) = probe.chapter.facts
    assert (flashback.actuality, flashback.relation) == ("flashback", None)
    assert (alive.kind, alive.values, alive.paragraph in flashback.paragraphs) == ("life", ["alive"], True)
    assert later.actuality == "present" and min(later.paragraphs) > max(flashback.paragraphs)
    assert alive.subject in flashback.present and alive.subject in later.present
