"""엔딩 층 스탯 맞추기 — 체크포인트 고정과 달리 엔딩에 닿는 값을 받아들이고 닿는 엔딩을 알린다. 없는 스탯·숫자 아님·범위
밖은 그대로 거부하고, 측정 작업 DB 가 아니면 DB 에 닿기 전에 거부한다."""

import json
import uuid
from pathlib import Path

import pytest

from api.chat.schemas import EndingRuleItem, EndingRuleListItem
from api.core.config import settings
from api.db.models.story import EndingRuleOperator, LogicalOp
from memory_eval.ending_stats import validate_ending_stats
from memory_eval.pinned_stats import PinnedStatDef

DOHEE, COUNTDOWN = uuid.uuid4(), uuid.uuid4()
DEFS = [
    PinnedStatDef(entity_id=str(DOHEE), name="도희 호감도", min_value=0, max_value=100),
    PinnedStatDef(entity_id=str(COUNTDOWN), name="상영회까지", min_value=0, max_value=46),
]
ENDINGS: list[tuple[str, list[EndingRuleListItem]]] = [
    (
        "다음 작품의 첫 장",
        [
            EndingRuleItem(
                id=uuid.uuid4(), stat_id=DOHEE, operator=EndingRuleOperator.GTE, threshold=55, next_op=LogicalOp.AND
            ),
            EndingRuleItem(
                id=uuid.uuid4(), stat_id=COUNTDOWN, operator=EndingRuleOperator.LTE, threshold=0, next_op=None
            ),
        ],
    ),
    ("규칙 없는 엔딩", []),
]
CURRENT = {str(DOHEE): 20.0, str(COUNTDOWN): 46.0}


def test_values_that_reach_an_ending_are_accepted_and_the_reached_ending_is_named() -> None:
    resolved, errors, reached = validate_ending_stats({"도희 호감도": 60, "상영회까지": 0}, DEFS, ENDINGS, CURRENT)
    assert errors == []
    assert resolved == {str(DOHEE): 60.0, str(COUNTDOWN): 0.0}
    assert reached == ["다음 작품의 첫 장"]


def test_values_short_of_every_ending_name_no_ending() -> None:
    _, errors, reached = validate_ending_stats({"도희 호감도": 54}, DEFS, ENDINGS, {**CURRENT, str(COUNTDOWN): 0.0})
    assert (errors, reached) == ([], [])


def test_unknown_stat_non_number_and_out_of_range_are_still_refused() -> None:
    _, errors, _ = validate_ending_stats(
        {"없는 스탯": 1, "도희 호감도": "많이", "상영회까지": 47}, DEFS, ENDINGS, CURRENT
    )
    assert {e.split(":")[0] for e in errors} == {"없는 스탯", "숫자 아님", "범위 밖"}


def test_the_command_refuses_a_database_outside_the_measurement_prefix_before_touching_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://u:p@localhost:5432/ai_character_chat")
    stats = tmp_path / "stats.json"
    stats.write_text(json.dumps({"도희 호감도": 60}), encoding="utf-8")
    code = main(["--run", str(tmp_path / "run"), "ending-stats", "--room", str(uuid.uuid4()), "--stats", str(stats)])
    assert code == 2
    assert "lm_eval_" in capsys.readouterr().err
