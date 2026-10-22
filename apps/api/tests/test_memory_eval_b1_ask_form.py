"""질문 꼴 표지 — 관문 범주 항목이 어떤 꼴로 묻는지(전제 위 후속 질문·닫힌 확인 질문·사용자 거짓말과 행동 요구)를 칸 하나로
적고, 꼴을 층 이름에 넣어 꼴마다 따로 반씩 나뉘게 한다. 심기 표 검사기와 대본 검사기가 같은 규칙(허용 값, 층 이름과 칸 일치,
층 크기 짝수)으로 본다. 칸이 없는 기존 심기 표는 층 이름이 그대로라 검사 결과가 바뀌지 않는다. 값은 모두 지어낸 것이다."""

from typing import Any

from memory_eval.b1 import check_chunks, plants_tool

FILLER_USER = "*천천히 걸어간다* 그래, 오늘은 어디까지 가 볼까."
FILLER_NARR = "*바람이 조용히 불고 거리는 평소처럼 한산하다.* " * 6


def _premise(i: int, form: str | None = None, *, subtype: str = "character_claim") -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": f"fp-{i:02d}",
        "category": "false_premise",
        "subtype": subtype,
        "people": ["민지"],
        "question": f"지어낸 확인 질문 하나를 길게 적어 둔다 번호 {i}",
        "plants": [
            {"turn": 40 + i, "line": "assistant", "assertedBy": "character", "keywords": [f"꾸룽{i}"], "plan": "p"}
        ],
        "truthCue": "진실 단서",
        "answer_key": {"mode": "judge"},
    }
    if form is not None:
        entry["askForm"] = form
    entry["stratum"] = plants_tool.stratum_of(entry)
    return entry


def _rules(report: dict[str, list[str]]) -> set[str]:
    return set(report)


def _rows() -> list[dict[str, Any]]:
    return [{"turn": t, "user": FILLER_USER, "assistant": FILLER_NARR} for t in range(1, 301)]


ASK_FORM_RULES = {
    "모르는 질문 꼴",
    "질문 꼴을 쓸 수 없는 범주",
    "사용자 거짓말 꼴인데 사용자 거짓말 항목이 아님",
    "층 이름과 질문 꼴 불일치",
}


def test_the_ask_form_goes_into_the_stratum_name_so_each_form_is_split_half_and_half() -> None:
    assert plants_tool.stratum_of(_premise(0, "premise_followup")) == "false_premise:premise_followup"
    assert plants_tool.stratum_of(_premise(0, "closed_confirm")) == "false_premise:closed_confirm"
    secret = {"category": "secret", "layer": "main", "askForm": "closed_confirm"}
    assert plants_tool.stratum_of(secret) == "secret:main:closed_confirm"


def test_an_entry_without_the_ask_form_keeps_its_old_stratum_name() -> None:
    assert plants_tool.stratum_of(_premise(0)) == "false_premise"
    assert plants_tool.stratum_of(_premise(0, plants_tool.DEFAULT_ASK_FORM)) == "false_premise"
    assert plants_tool.stratum_of({"category": "secret", "layer": "early"}) == "secret:early"


def test_the_plants_check_accepts_the_new_forms_and_reports_no_ask_form_rule() -> None:
    items = [_premise(0, "premise_followup"), _premise(1, "premise_followup")]
    items += [_premise(2, "closed_confirm"), _premise(3, "closed_confirm")]
    items += [_premise(4, "lie_action", subtype="user_lie"), _premise(5, "lie_action", subtype="user_lie")]
    report = plants_tool.check({"plants": items}, "")
    assert not _rules(report) & (ASK_FORM_RULES | {"층 크기 홀수"})


def test_the_plants_check_refuses_an_unknown_form_a_form_on_a_non_gate_category_and_a_misplaced_lie_form() -> None:
    detail = {**_premise(2, "premise_followup"), "id": "d-01", "category": "detail", "subtype": "object"}
    detail["stratum"] = "detail"
    items = [_premise(0, "leading"), _premise(1, "lie_action"), detail]
    report = plants_tool.check({"plants": items}, "")
    assert report["모르는 질문 꼴"] == ["fp-00"]
    assert report["사용자 거짓말 꼴인데 사용자 거짓말 항목이 아님"] == ["fp-01"]
    assert report["질문 꼴을 쓸 수 없는 범주"] == ["d-01"]


def test_the_plants_check_refuses_a_stratum_name_that_does_not_match_the_ask_form() -> None:
    stale = _premise(0, "closed_confirm")
    stale["stratum"] = "false_premise"
    report = plants_tool.check({"plants": [stale, _premise(1, "closed_confirm")]}, "")
    assert report["층 이름과 질문 꼴 불일치"] == ["fp-00"]


def test_an_odd_form_stratum_is_refused_even_when_the_category_total_is_even() -> None:
    items = [_premise(0, "premise_followup"), _premise(1, "closed_confirm")]
    report = plants_tool.check({"plants": items}, "")
    assert sorted(report["층 크기 홀수"]) == ["false_premise:closed_confirm 1", "false_premise:premise_followup 1"]


def test_fill_writes_the_form_stratum_and_leaves_an_absent_form_absent() -> None:
    definitions = {
        "claimVerdicts": {"rejected": "r", "accepted": "a", "unaddressed": "u"},
        "claimNote": "n",
        "lieVerdicts": {"rejected": "r", "accepted": "a", "unaddressed": "u"},
        "lieNote": "n",
    }
    with_form, without = _premise(0, "closed_confirm"), _premise(1)
    del with_form["stratum"], without["stratum"]
    plants_tool.fill({"plants": [with_form, without]}, definitions)
    assert with_form["stratum"] == "false_premise:closed_confirm"
    assert without["stratum"] == "false_premise" and "askForm" not in without


def test_the_script_check_applies_the_same_ask_form_rules() -> None:
    stale = _premise(2, "closed_confirm")
    stale["stratum"] = "false_premise"
    items = [_premise(0, "leading"), _premise(1, "lie_action"), stale, _premise(3, "premise_followup")]
    report = check_chunks.check({"plants": items}, "", _rows(), 12, False, "asterisk")
    assert report["모르는 질문 꼴"] == ["fp-00"]
    assert report["사용자 거짓말 꼴인데 사용자 거짓말 항목이 아님"] == ["fp-01"]
    assert report["층 이름과 질문 꼴 불일치"] == ["fp-02"]
    assert "false_premise:premise_followup 1" in report["질문 꼴 층 크기 홀수"]


def test_the_script_check_reports_no_ask_form_rule_for_a_table_without_the_field() -> None:
    items = [_premise(0), _premise(1), _premise(2)]
    report = check_chunks.check({"plants": items}, "", _rows(), 12, False, "asterisk")
    assert not _rules(report) & (ASK_FORM_RULES | {"질문 꼴 층 크기 홀수"})
