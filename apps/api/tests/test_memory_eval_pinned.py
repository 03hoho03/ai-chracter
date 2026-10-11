"""체크포인트별 스탯 고정 — 파일 값 검사(없는 스탯·범위 밖·엔딩 문턱)와 복원 뒤 지문 대조."""

import uuid
from typing import Any

import pytest

from api.chat.schemas import EndingRuleItem, EndingRuleListItem
from api.db.models.story import EndingRuleOperator, LogicalOp
from memory_eval.pinned_stats import PinnedStatDef, pinned_diff, pinned_for_checkpoint, validate_pinned

DOHEE, YUNA, COUNTDOWN = (uuid.uuid4() for _ in range(3))
DEFS = [
    PinnedStatDef(entity_id=str(DOHEE), name="도희 호감도", min_value=0, max_value=100),
    PinnedStatDef(entity_id=str(YUNA), name="유나 호감도", min_value=0, max_value=100),
    PinnedStatDef(entity_id=str(COUNTDOWN), name="상영회까지", min_value=0, max_value=46),
]


def _rule(stat: uuid.UUID, op: EndingRuleOperator, threshold: float, next_op: LogicalOp | None) -> EndingRuleItem:
    return EndingRuleItem(id=uuid.uuid4(), stat_id=stat, operator=op, threshold=threshold, next_op=next_op)


# 도희 엔딩: 도희 ≥ 55 AND 상영회까지 ≤ 0
ENDINGS: list[tuple[str, list[EndingRuleListItem]]] = [
    (
        "다음 작품의 첫 장",
        [_rule(DOHEE, EndingRuleOperator.GTE, 55, LogicalOp.AND), _rule(COUNTDOWN, EndingRuleOperator.LTE, 0, None)],
    ),
    ("규칙 없는 엔딩", []),
]
CURRENT = {str(DOHEE): 20.0, str(YUNA): 20.0, str(COUNTDOWN): 46.0}


def test_valid_values_pass_and_resolve_to_entity_ids() -> None:
    resolved, errors, notes = validate_pinned({"도희 호감도": 70, "상영회까지": 12}, DEFS, ENDINGS, CURRENT)
    assert errors == []
    assert resolved == {str(DOHEE): 70.0, str(COUNTDOWN): 12.0}
    # 규칙 없는 엔딩은 스탯으로 막을 수 없다 — 거부가 아니라 알림.
    assert any("규칙 없는 엔딩" in n for n in notes)


def test_all_problems_are_reported_together() -> None:
    _, errors, _ = validate_pinned(
        {"없는 스탯": 1, "유나 호감도": 101, "도희 호감도": 60, "상영회까지": 0}, DEFS, ENDINGS, CURRENT
    )
    kinds = {e.split(":")[0] for e in errors}
    assert kinds == {"없는 스탯", "범위 밖", "엔딩 문턱"}


@pytest.mark.parametrize(("value", "ok"), [(0, True), (100, True), (-1, False), (100.5, False)])
def test_range_boundaries_are_inclusive(value: float, ok: bool) -> None:
    _, errors, _ = validate_pinned({"유나 호감도": value}, DEFS, ENDINGS, CURRENT)
    assert (errors == []) is ok


def test_ending_threshold_uses_current_values_for_stats_not_in_the_file() -> None:
    # 파일이 상영회까지만 0 으로 고정해도, 지금 도희 값이 문턱 위면 엔딩에 닿는다.
    _, errors, _ = validate_pinned({"상영회까지": 0}, DEFS, ENDINGS, {**CURRENT, str(DOHEE): 60.0})
    assert any(e.startswith("엔딩 문턱") for e in errors)
    _, errors, _ = validate_pinned({"상영회까지": 0}, DEFS, ENDINGS, CURRENT)
    assert errors == []


def test_non_numeric_value_is_rejected() -> None:
    _, errors, _ = validate_pinned({"도희 호감도": "많이"}, DEFS, ENDINGS, CURRENT)
    assert errors and errors[0].startswith("숫자 아님")


def test_checkpoint_entry_must_exist() -> None:
    doc: dict[str, Any] = {"50": {"도희 호감도": 30}}
    assert pinned_for_checkpoint(doc, 50) == {"도희 호감도": 30}
    with pytest.raises(SystemExit):
        pinned_for_checkpoint(doc, 100)


def test_pinned_diff_compares_restored_fingerprint_stats_numerically() -> None:
    assert pinned_diff({str(DOHEE): "70.0", str(YUNA): "20"}, {str(DOHEE): 70.0}) == []
    assert pinned_diff({str(DOHEE): "71"}, {str(DOHEE): 70.0}) == [f"{DOHEE}: 고정 70.0 → 지금 71"]
    assert pinned_diff({}, {str(DOHEE): 70.0}) == [f"{DOHEE}: 고정 70.0 → 지금 없음"]


def test_preflight_checks_every_checkpoint_in_order_carrying_earlier_pins() -> None:
    from memory_eval.pinned_stats import validate_sequence

    doc = {"50": {"도희 호감도": 60, "상영회까지": 30}, "100": {"상영회까지": 0}}
    errors = validate_sequence(doc, [50, 100, 300], DEFS, ENDINGS, CURRENT)
    # 100 은 50 에서 고정한 도희 60 을 이어받아 엔딩에 닿고, 300 항목은 없다.
    assert any(e.startswith("CP100 엔딩 문턱") for e in errors)
    assert any(e.startswith("CP300 항목 없음") for e in errors)
    assert not any(e.startswith("CP50") for e in errors)
    assert validate_sequence({"50": {"도희 호감도": 30}}, [50], DEFS, ENDINGS, CURRENT) == []
