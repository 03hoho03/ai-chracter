"""정본 기억 측정 하네스의 합성 명세 — 정답(심은 사건·사실·지식)과 탐침의 짝 화 목록을 읽기 전에 꼴을 본다.

명세가 틀리면 측정이 조용히 엉뚱한 분모를 센다(범위 밖 문단을 가리킨 정답은 맞힐 수 없고, 없는 화에 기댄 탐침은 늘 정본 불완전이다).
그래서 읽는 순간 거절한다. 픽스처와 아래 문장은 모두 합성이다."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from api.novel_bible.rules import blocking
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


def _blood(*values: str, canonical: tuple[str, ...] | None = None) -> dict[str, Any]:
    pair: dict[str, Any] = {"category": "enum:혈액형", "values": list(values)}
    return pair if canonical is None else {**pair, "canonical": list(canonical)}

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
            [(("probes", 2, "depends_on"), [1, 2, 3]),
             (("probes", 2, "chapter", "events", 0, "relation"), {"kind": "after", "chapter": 3, "event": 2})],
            id="relation-to-a-flashback-the-prior-list-does-not-show",
        ),
        pytest.param([(("probes", 2, "chapter", "events", 0, "relation"), {"kind": "overlap", "chapter": 3, "event": 1})],
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
        pytest.param([(("probes", 0, "closed"), _blood("A형", "B형", canonical=("A", "B")))],
                     id="expected-pair-on-another-rule"),
        pytest.param([*_B4, (("probes", 0, "closed"), _blood("A형", "검은색", canonical=("A", "검정")))],
                     id="expected-pair-across-categories"),
        pytest.param([*_B4, (("probes", 0, "closed"), _blood("A형", "에이형", canonical=("A", "A")))],
                     id="expected-pair-of-the-same-value"),
        pytest.param([*_B4, (("probes", 0, "closed"), {**_blood("A형", "B형", canonical=("A", "B")), "category": "enum:색"})],
                     id="expected-pair-under-the-wrong-category"),
        pytest.param([*_B4, (("probes", 0, "closed"), _blood("A형", canonical=("A",)))], id="expected-pair-with-one-value"),
        # 사전 값은 정규 값을 함께 적는다 — 사전에서 항목을 뺀 코드로 같은 세트를 다시 읽을 때 기대 항목이 그대로 남게.
        pytest.param([*_B4, (("probes", 0, "closed"), _blood("A형", "B형"))], id="dictionary-pair-without-canonical-values"),
        pytest.param([*_B4, (("probes", 0, "closed"), _blood("A형", "B형", canonical=("A", "O")))],
                     id="canonical-value-the-dictionary-does-not-read"),
        pytest.param([*_B4, (("probes", 0, "closed"), {"category": "number:cm", "values": ["170cm", "182 cm"],
                                                        "canonical": ["170", "182"]})],
                     id="number-pair-with-canonical-values"),
    ],
)
def test_a_spec_the_harness_could_not_seed_or_score_is_rejected(edits: list[Edit]) -> None:
    _rejects(_edited(*edits))


@pytest.mark.parametrize(
    "closed",
    [
        pytest.param({"category": "enum:혈액형", "values": ["A형", "비형"], "canonical": ["A", "B"]}, id="dictionary"),
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


# ── 앱에서 맞힐 수 없는 정답 — 회상 장면의 주선 사건·진 플레이 행·기댈 화가 빠진 탐침 ─────────────────────

_MAP = {"subject": "서하", "attribute": "지도"}
_FIXTURE_PLAY = {"visible_from": 2, **_MAP, "value": "바싹 마른 지도"}  # 픽스처의 플레이 행 그대로
_SAME_KEY_LATER = {"visible_from": 2, **_MAP, "value": "구겨진 지도"}
_SAME_KEY_EARLIER = {"visible_from": 1, **_MAP, "value": "구겨진 지도"}
_SAME_KEY_AFTER_THE_CHAPTER = {"visible_from": 3, **_MAP, "value": "구겨진 지도"}
# 1화에 접힌, 2화의 행과 같은 값을 반증한 행 — 앱은 뒤의 같은 값 행보다 이 반증 행을 싣는다.
_SAME_VALUE_DISPROVED = {"visible_from": 1, **_MAP, "value": "바싹 마른 지도", "truth_status": "disproved"}
_WET_MAP = {"subject": "서하", "kind": "possession", "values": ["젖은 지도"], "paragraph": 1}
_BELIEVES_DEAD = {
    "knower": "서하", "kind": "believes", "subject": "도윤", "subject_kind": "character", "fact_kind": "life",
    "values": ["dead"], "paragraph": 1,
}


@pytest.mark.parametrize(
    ("edits", "reason"),
    [
        # 사건 슬롯은 장면 구성안이 회상이라고 한 장면에서 시작하는 사건을 늘 회상으로 저장한다.
        pytest.param([(("chapters", 2, "events", 1, "actuality"), "present"), (("chapters", 2, "events", 1, "relation"), _DROP)],
                     "회상 장면", id="main-line-event-in-a-flashback-scene"),
        pytest.param([(("probes", 2, "chapter", "events", 0, "actuality"), "present")],
                     "회상 장면", id="probe-main-line-event-in-a-flashback-scene"),
        pytest.param(
            [(("chapters", 1, "scenes"), [{"title": "지도", "flashback": True, "start": 1}, {"title": "폭풍", "start": 2}]),
             (("chapters", 2, "events", 1, "relation", "chapter"), 2)],
            "회상 장면", id="relation-to-an-event-the-outline-makes-a-flashback",
        ),
        # 앱은 같은 사실 키의 채팅 기억 행을 그 화 끝까지 키마다 이긴 행 하나로 줄여 싣는다.
        pytest.param([(("play",), [_FIXTURE_PLAY, _SAME_KEY_LATER])], "이긴 행",
                     id="play-difference-to-a-row-a-later-row-of-the-same-key-replaces"),
        pytest.param([(("play",), [_FIXTURE_PLAY, _SAME_VALUE_DISPROVED])], "이긴 행",
                     id="play-difference-to-a-row-an-earlier-disproval-of-the-same-value-outranks"),
        # 탐침은 그 개체를 처음 소개한 기본 화와 짝 사실이 든 기본 화에 기댄다.
        pytest.param([(("probes", 3, "depends_on"), [2, 3])], "빠졌다", id="probe-missing-the-chapter-that-introduced-its-people"),
        pytest.param([(("probes", 2, "depends_on"), [1])], "빠졌다", id="probe-missing-the-death-its-flashback-shows"),
        pytest.param([(("probes", 3, "depends_on"), [1, 3]), (("probes", 3, "chapter", "facts"), [_WET_MAP])], "빠졌다",
                     id="probe-missing-the-chapter-of-a-fact-on-the-same-thing"),
        pytest.param([(("probes", 3, "depends_on"), [1, 3]), (("probes", 3, "chapter", "knowledge"), [_BELIEVES_DEAD])],
                     "빠졌다", id="probe-missing-the-chapter-of-the-fact-its-knowledge-is-about"),
        pytest.param([(("probes", 3, "depends_on"), [1, 3]), (("probes", 3, "chapter", "events", 0, "present"), ["서하", "뱃사람"])],
                     "빠졌다", id="probe-naming-a-person-by-an-alias"),
        # 앱은 회상 관계의 대상을 그 사건만 덮는 첫 블록으로 푼다 — 같은 화에서 차례가 앞선 주선 사건이 그 사건의 문단을 모두
        # 덮으면 대상 블록이 없어 관계를 버린다. 차례는 첫 문단 순이다.
        pytest.param([(("chapters", 0, "events", 1, "paragraphs"), [2]), (("chapters", 2, "events", 1, "relation", "event"), 2)],
                     "덮", id="relation-to-an-event-an-earlier-event-covers"),
        # 앱은 화 안 사건을 첫 문단 순으로 저장하고, 매처는 정답 목록 차례대로 저장된 사건과 짝짓는다. 정답을 다른 차례로 적으면
        # 짝이 뒤바뀌어(A[2,3]·B[1,2] 는 A 가 저장된 B 를 가져간다) 바른 사건을 고른 관계가 틀림으로 셈해진다.
        pytest.param([(("chapters", 0, "events", 0, "paragraphs"), [2, 3]), (("chapters", 0, "events", 1, "paragraphs"), [1, 2])],
                     "첫 문단 순", id="overlapping-events-not-in-first-paragraph-order"),
        pytest.param([(("chapters", 0, "events", 0, "paragraphs"), [3, 4]), (("chapters", 0, "events", 1, "paragraphs"), [1, 2])],
                     "첫 문단 순", id="separate-events-not-in-first-paragraph-order"),
        pytest.param([(("chapters", 0, "events", 0, "paragraphs"), [2]), (("chapters", 0, "events", 1, "paragraphs"), [1, 2, 3, 4])],
                     "첫 문단 순", id="event-listed-after-one-it-starts-before"),
    ],
)
def test_an_answer_the_app_cannot_produce_or_a_probe_missing_a_chapter_it_leans_on_is_rejected(
    edits: list[Edit], reason: str
) -> None:
    with pytest.raises(ValidationError, match=reason):
        EvalSet.model_validate(_edited(*edits))


@pytest.mark.parametrize(
    "edits",
    [
        # 사건의 장면은 첫 문단의 장면이다 — 주선 장면에서 시작해 회상 장면으로 넘어가는 사건은 주선 사건으로 남는다.
        pytest.param([(("chapters", 2, "events", 0, "paragraphs"), [1, 2])], id="main-line-event-starting-before-the-flashback"),
        # 같은 키라도 먼저 접힌 행은 뒤에 접힌 행에 진다 — 명세 차례가 아니라 접힌 차례다.
        pytest.param([(("play",), [_FIXTURE_PLAY, _SAME_KEY_EARLIER])], id="play-difference-to-the-row-folded-last"),
        # 그 화 끝 뒤에 접힌 같은 키 행은 그 화의 플레이에 없다.
        pytest.param([(("play",), [_FIXTURE_PLAY, _SAME_KEY_AFTER_THE_CHAPTER])], id="same-key-row-folded-after-the-chapter"),
        pytest.param([(("play",), [_FIXTURE_PLAY, _SAME_VALUE_DISPROVED]), (("chapters", 1, "facts", 1, "play_difference"), 2)],
                     id="play-difference-to-the-disproval-that-wins"),
        # 탐침에만 나오는 개체는 기댈 기본 화가 없다.
        pytest.param([(("probes", 3, "depends_on"), []), (("probes", 3, "chapter", "events", 0, "present"), ["섬사람"])],
                     id="probe-whose-people-appear-only-in-it"),
        # 앞 사건과 겹쳐도 그 사건만 덮는 문단이 하나라도 있으면 앱이 그 문단으로 관계를 푼다.
        pytest.param([(("chapters", 0, "events", 1, "paragraphs"), [2, 3]), (("chapters", 2, "events", 1, "relation", "event"), 2)],
                     id="relation-to-an-event-partly-covered-by-an-earlier-one"),
    ],
)
def test_an_answer_the_app_can_produce_is_accepted(edits: list[Edit]) -> None:
    EvalSet.model_validate(_edited(*edits))


def test_a_set_whose_dictionary_item_was_removed_still_reads_when_the_removal_is_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 열거형 사전 항목을 빼는 것은 앱 사전에서 그 줄을 지우는 코드 변경이다. 뺀 뒤에도 같은 세트(같은 탐침·같은 분모)를 읽어야
    # 빼기 전·뺀 뒤를 견줄 수 있다 — 뺀 항목으로 알린 값만 받고, 그 밖의 읽지 못하는 값은 여전히 거절한다.
    without_a = {surface: value for surface, value in blocking.CLOSED_ATTRIBUTE_VALUES.items() if value != ("혈액형", "A")}
    monkeypatch.setattr(blocking, "CLOSED_ATTRIBUTE_VALUES", without_a)
    path = tmp_path / "set.json"
    path.write_text(json.dumps(_edited(*_B4, (("probes", 0, "closed"), _blood("A형", "B형", canonical=("A", "B"))))),
                    encoding="utf-8")
    with pytest.raises(ValidationError):
        load_set(path)
    with pytest.raises(ValidationError):
        load_set(path, removed=["enum:혈액형/O"])
    (probe, *_) = load_set(path, removed=["enum:혈액형/A"]).novels[0].probes
    assert probe.closed is not None and probe.closed.items() == ["enum:혈액형/A", "enum:혈액형/B"]
