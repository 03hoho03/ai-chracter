"""묶음 1 문안 시제품 — 요약 비밀 표기 슬롯과 사실 known_by 지시문 후보를 얼린 개발 투입 템플릿의 복제본에서 다시 돌리고, 개발 키로만
지표를 낸다.

- 후보 파일: 요약 슬롯은 `{room_people}` 하나만 받고 이름이 0개일 때의 고정 문구가 따로 있다. 사실 지시문은 플레이스홀더를 받지
  않는다(운영 렌더러가 그 채널 지시문에 값을 넣지 않는다).
- 방 이름 목록: 작품 이름(캐릭터)·미디어 북 인물·사실 행 이름에서, 원래 표기를 지키고 사용자 이름과 2자 미만을 뺀다.
- 슬롯은 요약 지시문 바로 뒤에 렌더되고, 섹션 원본은 바꾸지 않는다(DB 의 프롬프트도 건드리지 않는다).
- 다시 접기는 원래 스냅샷과 같은 구간을 접어야 하고, 접기 j 의 이름은 그보다 앞 스냅샷의 사실 행에서만 온다.
- 지표는 개발 보기의 문항만 센다 — 시험 문항이 요약·행에 아무리 잘 드러나도 숫자가 바뀌지 않고, 시험 id 를 건네면 거부한다.
- 지표는 후보마다 다르게 나올 수 있다(표기·노출·보존이 요약 글에 따라 갈린다)."""

import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, TypeVar

import httpx
import pytest
import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.chat.prompt_builder import (
    MemoryFactItem,
    MemoryFactResult,
    MemorySummaryResult,
    PromptNames,
    render_prompt_channel,
)
from api.db.models import ChatMemoryFact, ChatRoomMemorySnapshot, PromptSection
from api.llm.client import LLMCallContext, LLMClient
from factories import _make_memory_fact, _make_memory_fact_extraction, _open_room, _plant_snapshot
from memory_eval import holdout
from memory_eval import wording_metrics as wm
from memory_eval import wording_proto as wp
from memory_eval.ledger import BudgetExceededError
from memory_eval.plants import PlantSet

T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------- 후보 파일


def _write_json(path: Path, obj: Any) -> Path:
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return path


def test_summary_candidate_needs_room_people_and_a_no_names_phrase(tmp_path: Path) -> None:
    good = _write_json(
        tmp_path / "a.json",
        {
            "version": "a1",
            "slot": "비밀은 (이름·이름만 앎) 으로 적는다. 방 인물: {room_people}",
            "noNames": "아직 없음",
        },
    )
    candidate = wp.load_summary_candidate(good)
    assert (candidate.version, candidate.no_names) == ("a1", "아직 없음")
    assert candidate.sha256 == hashlib.sha256(good.read_bytes()).hexdigest()

    for bad, match in (
        ({"version": "a1", "slot": "이름 목록 없음", "noNames": "없음"}, "room_people"),
        ({"version": "a1", "slot": "{room_people} {user_name}", "noNames": "없음"}, "user_name"),
        ({"version": "a1", "slot": "{room_people}", "noNames": ""}, "noNames"),
        ({"version": "", "slot": "{room_people}", "noNames": "없음"}, "version"),
        ({"version": "a1", "slot": "{room_people", "noNames": "없음"}, "중괄호"),
    ):
        with pytest.raises(SystemExit, match=match):
            wp.load_summary_candidate(_write_json(tmp_path / "bad.json", bad))


def test_fact_candidate_takes_no_placeholder(tmp_path: Path) -> None:
    candidate = wp.load_fact_candidate(
        _write_json(tmp_path / "f.json", {"version": "k1", "instruction": "규칙 {{예}}"})
    )
    assert candidate.instruction == "규칙 {{예}}"
    with pytest.raises(SystemExit, match="existing_facts"):
        wp.load_fact_candidate(_write_json(tmp_path / "g.json", {"version": "k1", "instruction": "{existing_facts}"}))


# ---------------------------------------------------------------- 방 이름 목록


def test_room_people_keeps_spelling_and_drops_user_and_short_names() -> None:
    rows: list[dict[str, Any]] = [
        {"kind": "relation", "subject": "편소담", "object": "연가람", "attribute": None, "speaker": "유", "known_by": None},
        {"kind": "fact", "subject": "탁여솔", "object": None, "attribute": "장비 수강료", "speaker": None,
         "known_by": ["탁여솔", "사용자", "Kim  Ji"]},
        {"kind": "fact", "subject": "편소담 ", "object": None, "attribute": "비밀", "speaker": "석해람",
         "known_by": ["kim ji"]},
    ]  # fmt: skip
    people = wp.room_people(
        char_name=None, media_book_names=["배경", "탁여솔"], fact_rows=rows, user_names=["사용자", "석해람"]
    )
    # 미디어 북 → 사실 행 순, 처음 나온 표기, 사용자 이름(프로필·기본 호칭)과 1자 이름은 빠지고 사실의 속성은 이름이 아니다.
    assert people == ["배경", "탁여솔", "편소담", "연가람", "Kim  Ji"]
    assert wp.room_people(char_name="길나빈", media_book_names=[], fact_rows=[], user_names=["사용자"]) == ["길나빈"]


def test_excluded_user_names_cover_profile_fallback_and_fact_label() -> None:
    assert set(wp.excluded_user_names(PromptNames(persona_name=None, char_name=None))) >= {"사용자", "당신"}
    assert "석해람" in wp.excluded_user_names(PromptNames(persona_name="석해람", char_name=None))


# ---------------------------------------------------------------- 섹션


def _section(channel: str, slot: str, order: int, body: str, *, conditional: bool = False) -> PromptSection:
    return PromptSection(
        prompt_set_id=uuid.uuid4(),
        channel=channel,
        scope="both",
        slot=slot,
        variant="",
        body=body,
        conditional=conditional,
        order=order,
    )


def _summary_sections() -> list[PromptSection]:
    return [
        _section("memory_summary", "instruction", 1, "요약 지시문"),
        _section("memory_summary", "user_name", 2, "사용자의 이름: {user_name}", conditional=True),
        _section("memory_summary", "previous_summary", 3, "[직전 요약]\n{previous_summary}", conditional=True),
        _section("memory_summary", "turn_context", 4, "[대화]\n{turn_lines}"),
        _section("memory_fact", "instruction", 0, "옛 사실 지시문"),
    ]


def test_summary_slot_renders_right_after_instruction_without_touching_sections() -> None:
    candidate = wp.SummaryCandidate(version="a1", slot="방 인물: {room_people}", no_names="아직 없음", sha256="x")
    sections = _summary_sections()
    before = [(s.slot, s.body) for s in sections]
    values = {"previous_summary": "", "turn_lines": "사용자: 안녕", "user_name": ""}

    named = wp.with_summary_slot(sections, wp.summary_slot_text(candidate, ["편소담", "{괄호}"]))
    text = render_prompt_channel(named, channel="memory_summary", scope="story", values=values)
    assert text == "요약 지시문\n\n방 인물: 편소담, {괄호}\n\n[대화]\n사용자: 안녕"

    empty = wp.with_summary_slot(sections, wp.summary_slot_text(candidate, []))
    text = render_prompt_channel(empty, channel="memory_summary", scope="character", values=values)
    assert text.startswith("요약 지시문\n\n방 인물: 아직 없음\n\n")
    assert [(s.slot, s.body) for s in sections] == before

    with pytest.raises(SystemExit, match="이미"):
        wp.with_summary_slot(named, "또")
    with pytest.raises(SystemExit, match="지시문"):
        wp.with_summary_slot([s for s in sections if s.slot != "instruction"], "x")


def test_operational_secret_marking_slot_is_swapped_for_the_candidate_slot() -> None:
    """운영 슬롯(conditional, 운영 마이그레이션이 심은 것)이 든 세트에서는 그 행을 빼고 시제품 슬롯을 끼운다 — 둘 다 실리면 시제품
    문안을 잰 프롬프트가 아니다."""
    candidate = wp.SummaryCandidate(version="a1", slot="방 인물: {room_people}", no_names="아직 없음", sha256="x")
    operational = _section("memory_summary", "secret_marking", 1, "[운영 표기]\n{room_people}", conditional=True)
    sections = [*_summary_sections()[:1], operational, *_summary_sections()[1:]]
    swapped = wp.with_summary_slot(sections, wp.summary_slot_text(candidate, ["편소담"]))
    values = {"previous_summary": "", "turn_lines": "사용자: 안녕", "user_name": "", "room_people": "운영 이름"}
    text = render_prompt_channel(swapped, channel="memory_summary", scope="story", values=values)
    assert text == "요약 지시문\n\n방 인물: 편소담\n\n[대화]\n사용자: 안녕"
    assert operational in sections  # 원본 목록은 그대로다


def test_fact_instruction_is_replaced_in_a_copy() -> None:
    sections = _summary_sections()
    replaced = wp.with_fact_instruction(sections, "새 규칙 {{예}}")
    text = render_prompt_channel(replaced, channel="memory_fact", scope="story", values={})
    assert text == "새 규칙 {예}"
    assert next(s for s in sections if s.channel == "memory_fact").body == "옛 사실 지시문"
    with pytest.raises(SystemExit, match="지시문"):
        wp.with_fact_instruction([s for s in sections if s.channel != "memory_fact"], "x")


def test_work_db_must_not_be_a_template() -> None:
    wp.require_work_db("lm_eval_b1_proto", "lm_eval_b1dev-gate_cp300_frozen")
    for name in ("lm_eval_b1dev-gate_cp300_frozen", "lm_eval_x_frozen", "aichar_dev"):
        with pytest.raises(SystemExit):
            wp.require_work_db(name, "lm_eval_b1dev-gate_cp300_frozen")


# ---------------------------------------------------------------- 견적


def test_dry_run_estimate_uses_ledger_means_and_candidate_size() -> None:
    rows: list[dict[str, Any]] = [
        {"stage": "b1dev-gate", "callSite": "chat_memory_summary", "model": "claude-haiku-5-5",
         "inputTokens": 6000, "outputTokens": 2000, "costUsd": 0},
        {"stage": "b1dev-gate", "callSite": "chat_memory_summary", "model": "claude-haiku-5-5",
         "inputTokens": 4000, "outputTokens": 1000, "costUsd": 0},
        {"stage": "b1dev-seoyun", "callSite": "chat_memory_summary", "model": "claude-haiku-5-5",
         "inputTokens": 99999, "outputTokens": 99999, "costUsd": 0},
    ]  # fmt: skip
    usage = wp.ledger_usage(rows, stage="b1dev-gate", call_site="chat_memory_summary")
    assert usage == {"calls": 2, "meanInputTokens": 5000.0, "meanOutputTokens": 1500.0, "model": "claude-haiku-5-5"}
    estimate = wp.dry_run_estimate(calls=28, usage=usage, extra_input_chars=1000, margin=1.0)
    # Haiku 5.5: 입력 0.10 · 출력 0.50 (백만 토큰당). 덧붙는 글은 글자당 1토큰으로 넉넉히 센다.
    per_call = (6000 * 0.10 + 1500 * 0.50) / 1_000_000
    assert estimate["perCallUsd"] == pytest.approx(per_call)
    assert estimate["totalUsd"] == pytest.approx(per_call * 28)
    with pytest.raises(SystemExit, match="원장"):
        wp.ledger_usage(rows, stage="b1dev-filmclub", call_site="chat_memory_summary")


# ---------------------------------------------------------------- 지표 — 개발 키 한정


def _secret(item_id: str, owner: str, knowers: list[str], words: list[str], *, unaware: str | None) -> dict[str, Any]:
    return {
        "id": item_id,
        "category": "secret",
        "stratum": "secret:main",
        "secretOwner": owner,
        "unawareCharacter": unaware,
        "plant_turns": [12],
        "ask_checkpoints": [100, 300],
        "keywords": [words[0]],
        "answer_key": {"mode": "judge", "leak_bundles": [words]},
        "expected_fact": {"kind": "fact", "subject": owner, "attribute": "비밀", "value": " ".join(words),
                          "truth_status": "confirmed", "known_by": [*knowers, "사용자"]},
    }  # fmt: skip


def _relation(item_id: str, a: str, b: str) -> dict[str, Any]:
    return {
        "id": item_id,
        "category": "relation",
        "stratum": "relation",
        "plant_turns": [5, 40],
        "ask_checkpoints": [300],
        "keywords": ["앞치마", "사물함 번호"],
        "plants": [{"keywords": ["앞치마"], "turn": 5}, {"keywords": ["사물함 번호"], "turn": 40}],
        "answer_key": {"mode": "judge", "correct": "냉전 — 번호를 바꿨다"},
        "expected_fact": {"kind": "relation", "subject": a, "object": b, "value": "냉전", "known_by": None},
    }


def _claim(item_id: str, said_by: str, words: list[str]) -> dict[str, Any]:
    """미확인 주장 문항(범주는 디테일, 정답 사실이 claimed)."""
    return {
        "id": item_id,
        "category": "detail",
        "stratum": "detail",
        "plant_turns": [12],
        "ask_checkpoints": [100, 300],
        "keywords": [words[0]],
        "answer_key": {"mode": "judge", "leak_bundles": [words]},
        "expected_fact": {"kind": "fact", "subject": said_by, "attribute": "경력", "value": " ".join(words),
                          "truth_status": "claimed", "said_by": said_by, "known_by": None},
    }  # fmt: skip


def _plants_and_split(tmp_path: Path) -> tuple[Path, Path]:
    raw = {
        "lane": "story",
        "checkpoints": [100, 300],
        "plants": [
            _secret("d-sec1", "탁여솔", ["탁여솔"], ["곗돈", "수강료"], unaware=None),
            _secret("d-sec2", "편소담", ["편소담", "곽미르"], ["인형극단", "면접"], unaware="육시온"),
            _secret("t-sec1", "변찬솔", ["변찬솔"], ["축음기", "열쇠"], unaware=None),
            _relation("d-rel1", "편소담", "연가람"),
            _relation("t-rel1", "피온유", "맹다올"),
            _claim("t-claim1", "피온유", ["제비뽑기", "추첨"]),
        ],
    }
    plants = _write_json(tmp_path / "plants.json", raw)
    split = tmp_path / "split"
    split.mkdir()
    _write_json(split / holdout.DEV_IDS_FILE, ["d-sec1", "d-sec2", "d-rel1"])
    _write_json(split / holdout.TEST_IDS_FILE, ["t-sec1", "t-rel1", "t-claim1"])
    _write_json(split / holdout.MANIFEST_FILE, {"seed": 1, "plantsSha256": holdout.sha256_file(plants)})
    # 시험 정답 파일은 일부러 깨진 채로 둔다 — 개발 보기가 열면 JSON 오류로 드러난다.
    (split / holdout.TEST_KEYS_FILE).write_text("{깨짐", encoding="utf-8")
    return plants, split


SUMMARY_HEADER = {"kind": "header", "run": "summary", "version": "a1", "checkpointSnapshots": {"100": 1, "300": 2}}


def _summary_records(cp100: str, cp300: str) -> list[dict[str, Any]]:
    return [{"kind": "fold", "index": 1, "summary": cp100}, {"kind": "fold", "index": 2, "summary": cp300}]


TEST_ITEMS_EVERYWHERE = (
    "변찬솔가 축음기 열쇠를 숨겼다(변찬솔만 앎). 피온유와 맹다올는 냉전했다. 피온유는 제비뽑기에 추첨됐다고 주장했다. "
    "제비뽑기 추첨금으로 집을 샀다."
)


def test_summary_metrics_count_only_dev_items(tmp_path: Path) -> None:
    plant_set = wm.dev_view(*_plants_and_split(tmp_path))
    summary = (
        "[관계]\n소담와 가람은 사물함 번호 일로 냉전했다.\n[지난 일]\n여솔가 곗돈을 깨 수강료을 냈다(여솔만 앎). "
        "소담는 미르 앞에서 면접 결과를 숨겼다."
    )
    counts = wm.summary_metrics(plant_set, SUMMARY_HEADER, _summary_records(summary, summary))
    assert counts["300"] == {
        "secretItems": 2,
        "secretMarked": 1,
        "secretBodyExposed": 1,
        "relationItems": 1,
        "relationKept": 1,
        "relationLatestCue": 1,
        # 개발 절반에는 미확인 주장 문항이 없다 — 시험 절반의 주장 문항은 아래 글로도 세지 않는다.
        "claimItems": 0,
        "claimSourced": 0,
        "claimFactualized": 0,
    }
    # 시험 문항이 표기·노출·보존·출처 표기·사실 둔갑를 모두 갖춘 글을 더해도 개발 숫자는 그대로다(주장 칸도 0).
    louder = wm.summary_metrics(
        plant_set, SUMMARY_HEADER, _summary_records(summary, summary + "\n" + TEST_ITEMS_EVERYWHERE)
    )
    assert louder == counts


def test_summary_metrics_separate_marking_from_body_exposure(tmp_path: Path) -> None:
    """같은 비밀을 표기와 함께 내용으로·내용 없이 털어놓은 사실만·표기 없이 내용으로 적은 요약이 서로 다른 숫자를 낸다. 표기와
    함께 적힌 내용은 노출이 아니다(노출은 표기 밖에 드러난 내용만)."""
    plant_set = wm.dev_view(*_plants_and_split(tmp_path))

    def secret_counts(text: str) -> tuple[int, int]:
        row = wm.summary_metrics(plant_set, SUMMARY_HEADER, _summary_records(text, text))["100"]
        return row["secretMarked"], row["secretBodyExposed"]

    assert secret_counts("여솔가 곗돈을 깨 수강료을 냈다(여솔만 앎).") == (1, 0)
    # 내용 없이 "누가 누구에게 무엇을 털어놓았다"만 — 무엇(단서 하나)과 주인 이름이 함께 있어 표기로 잡힌다.
    assert secret_counts("여솔가 사용자에게 수강료 일을 털어놓았다(여솔만 앎).") == (1, 0)
    assert secret_counts("소담가 미르에게만 면접 이야기를 털어놓았다(소담·미르만 앎).") == (1, 0)
    assert secret_counts("동아리방에서 회의를 했다.") == (0, 0)
    assert secret_counts("여솔가 곗돈을 깨 수강료을 냈다.") == (0, 1)


def test_owner_name_with_a_marker_alone_does_not_mark_another_secret(tmp_path: Path) -> None:
    """주인 이름과 아는 사람 표기만 있고 그 비밀의 단서가 하나도 없는 마디는 그 주인의 다른 비밀을 표기한 것이 아니다."""
    plant_set = wm.dev_view(*_plants_and_split(tmp_path))
    text = "여솔가 사용자에게 고민을 털어놓았다(여솔·사용자만 앎)."
    row = wm.summary_metrics(plant_set, SUMMARY_HEADER, _summary_records(text, text))["100"]
    assert (row["secretMarked"], row["secretBodyExposed"]) == (0, 0)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("여솔가 곗돈을 깨 수강료을 냈다(여솔만 아는 일).", id="아는"),
        pytest.param("여솔가 곗돈을 깨 수강료을 냈다(여솔만 압니다).", id="압니다"),
        pytest.param("여솔가 곗돈을 깨 수강료을 냈다. (여솔·사용자만 앎)", id="마침표 뒤 괄호"),
    ],
)
def test_marker_forms_and_a_trailing_parenthesis_mark_without_exposing(tmp_path: Path, text: str) -> None:
    plant_set = wm.dev_view(*_plants_and_split(tmp_path))
    row = wm.summary_metrics(plant_set, SUMMARY_HEADER, _summary_records(text, text))["100"]
    assert (row["secretMarked"], row["secretBodyExposed"]) == (1, 0)


def test_list_item_with_two_sentences_is_one_segment_but_a_paragraph_is_split(tmp_path: Path) -> None:
    """줄 머리 `-` 목록 항목은 문장이 둘이어도 한 마디라 마지막 문장 뒤 표기 괄호가 항목 전체를 표기한다. 목록이 아닌 문단은
    문장마다 나뉘어 표기 괄호가 없는 앞 문장이 노출로 남는다."""
    plant_set = wm.dev_view(*_plants_and_split(tmp_path))

    def secret_counts(text: str) -> tuple[int, int]:
        row = wm.summary_metrics(plant_set, SUMMARY_HEADER, _summary_records(text, text))["100"]
        return row["secretMarked"], row["secretBodyExposed"]

    list_item = "[비밀]\n- 여솔가 곗돈을 깨 수강료을 냈다. 아무에게도 말하지 않았다 (여솔만 앎)"
    assert secret_counts(list_item) == (1, 0)
    paragraph = "[지난 일]\n여솔가 곗돈을 깨 수강료을 냈다. 아무에게도 말하지 않았다 (여솔만 앎)"
    assert secret_counts(paragraph) == (0, 1)
    # 표기 괄호가 다음 줄에 와도 목록 항목에 붙는다.
    assert secret_counts("[비밀]\n- 여솔가 곗돈을 깨 수강료을 냈다. 아무에게도 말하지 않았다\n(여솔만 앎)") == (1, 0)


def test_marker_parenthesis_does_not_keep_a_relation(tmp_path: Path) -> None:
    plant_set = wm.dev_view(*_plants_and_split(tmp_path))
    marked_only = "소담가 다른 이야기를 했다(소담·가람만 앎)."
    assert wm.summary_metrics(plant_set, SUMMARY_HEADER, _summary_records("", marked_only))["300"]["relationKept"] == 0
    kept = "소담와 가람은 냉전했다(소담·가람만 앎)."
    assert wm.summary_metrics(plant_set, SUMMARY_HEADER, _summary_records("", kept))["300"]["relationKept"] == 1


def _claim_view(tmp_path: Path, said_by: str) -> PlantSet:
    """미확인 주장 문항 하나(개발)만 든 보기. 말한 사람만 바꿔 가며 쓴다."""
    claim = _claim("d-claim1", said_by, ["연날리기 시합", "우승기"])
    raw = {
        "lane": "story",
        "checkpoints": [100, 300],
        "plants": [claim, _secret("t-sec1", "변찬솔", ["변찬솔"], ["축음기", "열쇠"], unaware=None)],
    }
    plants = _write_json(tmp_path / "claim-plants.json", raw)
    split = tmp_path / "claim-split"
    split.mkdir()
    _write_json(split / holdout.DEV_IDS_FILE, ["d-claim1"])
    _write_json(split / holdout.TEST_IDS_FILE, ["t-sec1"])
    _write_json(split / holdout.MANIFEST_FILE, {"seed": 1, "plantsSha256": holdout.sha256_file(plants)})
    (split / holdout.TEST_KEYS_FILE).write_text("{깨짐", encoding="utf-8")
    return wm.dev_view(plants, split)


def _claim_counts(plant_set: PlantSet, text: str, header: dict[str, Any] = SUMMARY_HEADER) -> tuple[int, int]:
    row = wm.summary_metrics(plant_set, header, _summary_records(text, text))["100"]
    return row["claimSourced"], row["claimFactualized"]


@pytest.mark.parametrize(
    ("text", "header"),
    [
        pytest.param("당신은 연날리기 시합에서 우승기을 받았다고 주장했다.", SUMMARY_HEADER, id="당신"),
        pytest.param("사용자는 연날리기 시합에서 우승기을 받았다고 주장했다.", SUMMARY_HEADER, id="사용자"),
        pytest.param(
            "라온은 연날리기 시합에서 우승기을 받았다고 주장했다.",
            {**SUMMARY_HEADER, "userNames": ["라온", "사용자"]},
            id="머리 줄 이름",
        ),
    ],
)
def test_a_user_claim_is_sourced_under_any_name_the_summary_calls_the_user(
    tmp_path: Path, text: str, header: dict[str, Any]
) -> None:
    """사용자가 한 주장은 말한 사람이 고정 표기("사용자")로 적혀 있지만 요약은 사용자를 방마다 다르게 부른다("당신"·프로필
    이름). 그 호칭 가운데 하나와 출처 말이 함께 있으면 출처를 붙여 적은 것이다."""
    assert _claim_counts(_claim_view(tmp_path, "사용자"), text, header) == (1, 0)


def _scene(detail: str, asserted_by: str, *, scene_id: str = "e1", title: str = "장면") -> dict[str, Any]:
    return {"id": scene_id, "title": title, "detail": detail, "asserted_by": asserted_by, "end_turn": 20,
            "known_by": []}  # fmt: skip


def _claim_scene_counts(plant_set: PlantSet, rows: list[dict[str, Any]]) -> tuple[int, int, int]:
    counts = wm.episode_metrics(plant_set, {"userNames": ["사용자"]}, rows)
    return counts["claimsCharacter"], counts["claimNarrationMixed"], counts["claimNarrationSourced"]


def test_a_user_claim_with_one_cue_and_a_user_name_is_found_in_a_scene_but_not_counted_as_narration(
    tmp_path: Path,
) -> None:
    """장면 쪽도 같은 맞추기를 쓴다 — 단서 하나와 사용자 호칭이 함께 있으면 그 주장을 담은 장면이다. 다만 서술 둔갑은
    인물이 한 미확인 주장만 센다 — 사용자가 한 말은 사용자 자신이 아는 일이라 서술로 적혀도 인물의 지식이 오염되지 않는다."""
    plant_set = _claim_view(tmp_path, "사용자")
    rows = [_scene("당신은 우승기 이야기를 꺼냈다.", "narration")]
    counts = wm.episode_metrics(plant_set, {"userNames": ["사용자"]}, rows)
    assert (counts["claimFound"], counts["claimsCharacter"]) == (1, 0)
    assert (counts["claimNarrationMixed"], counts["claimNarrationSourced"]) == (0, 0)


@pytest.mark.parametrize(
    "detail",
    [
        pytest.param("도하는 연날리기 시합에서 우승기을 받았다고 말했다.", id="다고 말했다"),
        pytest.param('도하가 "연날리기 시합 우승기은 내 거야"라며 웃었다.', id="따옴표 인용"),
    ],
)
def test_a_character_claim_narrated_with_its_source_is_sourced_not_mixed(tmp_path: Path, detail: str) -> None:
    """서술로 적었어도 본문에 말한 인물과 전언 표지(또는 따옴표 인용)가 있으면 출처를 밝힌 서술이다 — 둔갑으로 세지 않고 따로 센다."""
    assert _claim_scene_counts(_claim_view(tmp_path, "방도하"), [_scene(detail, "narration")]) == (1, 0, 1)


def test_a_character_claim_narrated_without_a_source_is_mixed(tmp_path: Path) -> None:
    """말한 인물도 전언 표지도 없이 일어난 일처럼 서술한 장면이 둔갑이다(안전 기준)."""
    plant_set = _claim_view(tmp_path, "방도하")
    rows = [_scene("도하는 연날리기 시합에서 우승기을 받았다.", "narration")]
    assert _claim_scene_counts(plant_set, rows) == (1, 1, 0)


def test_one_unsourced_narration_scene_makes_the_claim_mixed_even_beside_a_sourced_one(tmp_path: Path) -> None:
    """한 문항은 둔갑과 출처 서술 가운데 하나로만 센다 — 출처 없는 서술 장면이 하나라도 있으면 둔갑이다."""
    plant_set = _claim_view(tmp_path, "방도하")
    rows = [
        _scene("도하는 연날리기 시합에서 우승기을 받았다고 말했다.", "narration", scene_id="e1"),
        _scene("도하는 연날리기 시합에서 우승기을 받았다.", "narration", scene_id="e2"),
    ]
    assert _claim_scene_counts(plant_set, rows) == (1, 1, 0)


def test_a_character_claim_in_a_character_scene_is_neither_mixed_nor_sourced(tmp_path: Path) -> None:
    plant_set = _claim_view(tmp_path, "방도하")
    rows = [_scene("도하는 연날리기 시합에서 우승기을 받았다.", "character")]
    assert _claim_scene_counts(plant_set, rows) == (1, 0, 0)


def _detail_view(tmp_path: Path) -> PlantSet:
    """확인된 디테일 문항 하나와 혼자 본 비밀 하나(둘 다 개발). 개발 디테일 문항은 단서가 낱말 하나뿐이다."""
    detail = {
        "id": "d-det1",
        "category": "detail",
        "stratum": "detail",
        "plant_turns": [12],
        "ask_checkpoints": [300],
        "keywords": ["청동 문진"],
        "answer_key": {"mode": "judge", "leak_bundles": [["청동 문진"]]},
        "expected_fact": {"kind": "fact", "subject": "방도하", "attribute": "물건", "value": "청동 문진",
                          "truth_status": "confirmed", "known_by": None},
    }  # fmt: skip
    secret = {**_secret("d-sec1", "탁여솔", ["탁여솔"], ["곗돈", "수강료"], unaware=None), "subtype": "witnessed"}
    raw = {
        "lane": "story",
        "checkpoints": [100, 300],
        "plants": [detail, secret, _secret("t-sec1", "변찬솔", ["변찬솔"], ["축음기", "열쇠"], unaware=None)],
    }
    plants = _write_json(tmp_path / "detail-plants.json", raw)
    split = tmp_path / "detail-split"
    split.mkdir()
    _write_json(split / holdout.DEV_IDS_FILE, ["d-det1", "d-sec1"])
    _write_json(split / holdout.TEST_IDS_FILE, ["t-sec1"])
    _write_json(split / holdout.MANIFEST_FILE, {"seed": 1, "plantsSha256": holdout.sha256_file(plants)})
    (split / holdout.TEST_KEYS_FILE).write_text("{깨짐", encoding="utf-8")
    return wm.dev_view(plants, split)


def test_a_detail_scene_matches_on_its_single_cue_and_the_narration_share_is_computed(tmp_path: Path) -> None:
    """디테일 문항은 단서가 하나뿐이라 단서 둘(또는 단서와 이름)을 요구하면 영원히 장면을 못 찾는다 — 단서 하나로 맞춘다. 다른
    범주는 그대로 단서 둘(또는 단서와 이름)이 있어야 한다."""
    plant_set = _detail_view(tmp_path)
    rows = [
        _scene("책상 위에 청동 문진이 놓여 있었다.", "narration", scene_id="e1"),
        _scene("누군가 청동 문진을 빌려 갔다고 했다.", "character", scene_id="e2"),
        _scene("곗돈 이야기가 잠깐 나왔다.", "narration", scene_id="e3"),
    ]
    counts = wm.episode_metrics(plant_set, {"userNames": ["사용자"]}, rows)
    assert (counts["detailItems"], counts["detailEpisodes"], counts["detailNarrationEpisodes"]) == (1, 2, 1)
    assert counts["witnessedFound"] == 0
    report = wm.report("episodes", "x", {"w": {"all": counts}})
    assert report["pooled"]["all"]["detailNarrationShare"] == 0.5


def test_a_character_claim_still_needs_that_character_name(tmp_path: Path) -> None:
    """인물이 한 주장은 사용자 호칭으로 대신하지 않는다."""
    plant_set = _claim_view(tmp_path, "방도하")
    assert _claim_counts(plant_set, "당신은 연날리기 시합에서 우승기을 받았다고 주장했다.") == (0, 0)
    assert _claim_counts(plant_set, "도하는 연날리기 시합에서 우승기을 받았다고 주장했다.") == (1, 0)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("도하를 막내라고 부르는 사범 앞에서 연날리기 시합 우승기을 받았다.", (0, 1), id="호칭 라고"),
        pytest.param("도하는 연날리기 시합 우승기이 자기 것이라고 말했다.", (1, 0), id="라고 말했다"),
    ],
)
def test_naming_ra_go_is_not_a_source_word(tmp_path: Path, text: str, expected: tuple[int, int]) -> None:
    """호칭 "…라고 부르는" 은 출처 말이 아니라 호칭이다. 출처는 "라고" 뒤에 주장·말·했다 같은 말이 이어질 때만 센다."""
    assert _claim_counts(_claim_view(tmp_path, "방도하"), text) == expected


def test_fact_metrics_drop_the_same_user_names_as_the_runner(tmp_path: Path) -> None:
    """사실 행의 아는 사람에서 빼는 사용자 이름은 실행기가 방 이름 목록에서 뺀 이름(머리 줄)과 같다 — 프로필 이름·기본 호칭도."""
    plant_set = wm.dev_view(*_plants_and_split(tmp_path))
    header = {**FACT_HEADER, "userNames": ["석해람", "당신", "사용자"]}
    for known in (["탁여솔", "석해람"], ["탁여솔", "당신"], ["탁여솔", "사용자"]):
        rows = [_row(1, 0, "탁여솔", "곗돈을 깨 수강료을 냈다", known), DONE]
        assert wm.fact_metrics(plant_set, header, rows)["100"]["knownByKept"] == 1
    # 머리 줄에 없으면 실행기의 기본값(프로필 없음)과 같다 — "당신" 은 빠지고 "석해람" 은 모르는 인물이다.
    assert (
        wm.fact_metrics(plant_set, FACT_HEADER, [_row(1, 0, "탁여솔", "곗돈 수강료", ["탁여솔", "당신"]), DONE])["100"][
            "knownByKept"
        ]
        == 1
    )
    assert (
        wm.fact_metrics(plant_set, FACT_HEADER, [_row(1, 0, "탁여솔", "곗돈 수강료", ["탁여솔", "석해람"]), DONE])[
            "100"
        ]["knownByKept"]
        == 0
    )


def test_fact_metrics_refuse_a_result_without_the_done_line(tmp_path: Path) -> None:
    plant_set = wm.dev_view(*_plants_and_split(tmp_path))
    with pytest.raises(SystemExit, match="완료"):
        wm.fact_metrics(plant_set, FACT_HEADER, [_row(1, 0, "탁여솔", "곗돈을 깨 수강료을 냈다", ["탁여솔"])])


def test_metrics_refuse_test_ids_and_test_items(tmp_path: Path) -> None:
    plant_set = wm.dev_view(*_plants_and_split(tmp_path))
    with pytest.raises(SystemExit, match="시험"):
        wm.summary_metrics(plant_set, SUMMARY_HEADER, _summary_records("", ""), item_ids=["d-sec1", "t-sec1"])
    with pytest.raises(KeyError):
        wm.summary_metrics(plant_set, SUMMARY_HEADER, _summary_records("", ""), item_ids=["없는-문항"])
    only = wm.summary_metrics(
        plant_set,
        SUMMARY_HEADER,
        _summary_records("", "여솔가 곗돈을 깨 수강료을 냈다(여솔만 앎)."),
        item_ids=["d-sec1"],
    )
    assert (only["300"]["secretItems"], only["300"]["secretMarked"], only["300"]["relationItems"]) == (1, 1, 0)

    leaked = PlantSet(
        raw=plant_set.raw,
        plants=[*plant_set.plants, {**plant_set.plants[0], "id": "t-x", "split": "test"}],
        abstains=[],
    )
    with pytest.raises(SystemExit, match="개발"):
        wm.summary_metrics(leaked, SUMMARY_HEADER, _summary_records("", ""))
    with pytest.raises(SystemExit, match="개발"):
        wm.fact_metrics(leaked, FACT_HEADER, [DONE])


FACT_HEADER = {"kind": "header", "run": "facts", "version": "k1", "checkpointSnapshots": {"100": 1, "300": 2}}
DONE = {"kind": "done"}


def _row(
    index: int, ordinal: int, subject: str, value: str, known_by: list[str] | None, **extra: Any
) -> dict[str, Any]:
    attribute = extra.pop("attribute", "비밀")
    return {
        "kind": "fact",
        "snapshotIndex": index,
        "ordinal": ordinal,
        "factKind": "fact",
        "subject": subject,
        "object": None,
        "attribute": attribute,
        "factKey": f"fact|{subject}|{attribute}",
        "value": value,
        "knownBy": known_by,
        **extra,
    }


def test_fact_metrics_count_only_dev_items_and_read_the_latest_row(tmp_path: Path) -> None:
    plant_set = wm.dev_view(*_plants_and_split(tmp_path))
    rows: list[dict[str, Any]] = [
        # cp100(스냅샷 1까지): 여솔 비밀은 아는 사람이 맞지만 값에 주인이 없다. 같은 스냅샷에 같은 키가 둘이다.
        _row(1, 0, "탁여솔", "곗돈을 깨 수강료을 냈다", ["탁여솔", "사용자"]),
        _row(1, 1, "탁여솔", "곗돈 깬 일을 숨긴다", ["탁여솔"]),
        # 스냅샷 2: 여솔 비밀의 새 행은 아는 사람에 모르는 인물이 끼었다. 소담 비밀은 표기·주인 모두 맞다(성 없는 이름도 같은 사람).
        _row(2, 0, "탁여솔", "여솔가 곗돈을 깨 수강료을 냈다", ["탁여솔", "육시온", "사용자"]),
        _row(2, 1, "편소담", "소담가 인형극단 면접에서 떨어졌다", ["소담", "미르", "사용자"]),
        # 시험 문항 행은 아무리 맞아도 세지 않는다.
        _row(2, 2, "변찬솔", "변찬솔가 축음기 열쇠를 숨겼다", ["변찬솔", "사용자"]),
        _row(2, 3, "변찬솔", "변찬솔가 축음기 열쇠를 숨겼다", ["변찬솔", "사용자"]),
        DONE,
    ]
    counts = wm.fact_metrics(plant_set, FACT_HEADER, rows)
    assert counts["100"] == {"secretItems": 2, "secretRowFound": 1, "knownByKept": 1, "ownerMarked": 0,
                             "duplicateKeyRows": 1}  # fmt: skip
    assert counts["300"] == {"secretItems": 2, "secretRowFound": 2, "knownByKept": 1, "ownerMarked": 2,
                             "duplicateKeyRows": 1}  # fmt: skip


def test_report_pools_works_and_turns_counts_into_rates() -> None:
    per_work = {
        "gate": {"300": {"secretItems": 2, "secretMarked": 1, "secretBodyExposed": 0, "relationItems": 0,
                         "relationKept": 0, "relationLatestCue": 0}},
        "seoyun": {"300": {"secretItems": 2, "secretMarked": 2, "secretBodyExposed": 1, "relationItems": 1,
                           "relationKept": 1, "relationLatestCue": 0}},
    }  # fmt: skip
    report = wm.report("summary", "a1", per_work)
    pooled = report["pooled"]["300"]
    assert pooled["secretMarkedRate"] == pytest.approx(3 / 4)
    assert pooled["secretBodyExposureRate"] == pytest.approx(1 / 4)
    assert pooled["relationKeptRate"] == 1.0
    assert report["works"]["gate"]["300"]["relationKeptRate"] is None
    assert report["order"] == ["secretMarkedRate", "-secretBodyExposureRate", "relationKeptRate"]
    # 주장 칸이 생기기 전의 결과다 — 주장 비율은 0 이 아니라 모름이다.
    assert pooled["claimSourcedRate"] is None and pooled["claimFactualizedRate"] is None
    assert "claimItems" not in pooled
    assert report["works"]["seoyun"]["300"]["claimSourcedRate"] is None
    # 숫자·이름표만 — 글은 하나도 없다.
    flat = json.dumps(report, ensure_ascii=False)
    assert "요약" not in flat and "곗돈" not in flat


def _summary_counts(secret_marked: int, claim: tuple[int, int, int] | None) -> dict[str, int]:
    row = {"secretItems": 2, "secretMarked": secret_marked, "secretBodyExposed": 0, "relationItems": 0,
           "relationKept": 0, "relationLatestCue": 0}  # fmt: skip
    if claim is not None:
        row |= dict(zip(("claimItems", "claimSourced", "claimFactualized"), claim, strict=True))
    return row


def test_report_pools_claim_counts_when_every_work_has_them() -> None:
    per_work = {"gate": {"300": _summary_counts(1, (2, 1, 1))}, "seoyun": {"300": _summary_counts(2, (1, 1, 0))}}
    report = wm.report("summary", "a1", per_work)
    pooled = report["pooled"]["300"]
    assert (pooled["claimItems"], pooled["claimSourced"], pooled["claimFactualized"]) == (3, 2, 1)
    assert pooled["claimSourcedRate"] == pytest.approx(2 / 3)
    assert pooled["claimFactualizedRate"] == pytest.approx(1 / 3)
    assert report["works"]["gate"]["300"]["claimFactualizedRate"] == pytest.approx(1 / 2)


@pytest.mark.parametrize("old_first", [True, False], ids=["옛 결과가 앞", "옛 결과가 뒤"])
def test_report_leaves_claim_rates_unknown_when_only_some_works_have_them(old_first: bool) -> None:
    """작품 일부에만 주장 칸이 있으면 합친 주장 칸과 비율은 통째로 모름이다 — 칸이 있는 작품만 더하면 합친 숫자가 전체 작품의
    숫자처럼 읽힌다. 작품마다 숫자와 다른 칸의 합친 비율은 그대로다."""
    works = [("gate", _summary_counts(1, None)), ("seoyun", _summary_counts(2, (2, 1, 1)))]
    per_work = {name: {"300": counts} for name, counts in (works if old_first else works[::-1])}
    report = wm.report("summary", "a1", per_work)
    pooled = report["pooled"]["300"]
    assert pooled["claimSourcedRate"] is None and pooled["claimFactualizedRate"] is None
    assert not {"claimItems", "claimSourced", "claimFactualized"} & set(pooled)
    assert pooled["secretMarkedRate"] == pytest.approx(3 / 4)
    assert report["works"]["seoyun"]["300"]["claimSourcedRate"] == pytest.approx(1 / 2)
    assert report["works"]["gate"]["300"]["claimSourcedRate"] is None


# ---------------------------------------------------------------- 다시 돌리기(작업 DB)


class RecordingLLM(LLMClient):
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        raise RuntimeError("생성은 하지 않는다")
        yield ""  # pragma: no cover

    async def generate_structured(
        self,
        prompt: str,
        response_schema: type[T],
        images: list[tuple[bytes, str]] | None = None,
        *,
        usage: LLMCallContext,
    ) -> T:
        self.prompts.append(prompt)
        if response_schema is MemorySummaryResult:
            return response_schema.model_validate({"summary": f"다시 접은 요약 {len(self.prompts)}"})
        assert response_schema is MemoryFactResult
        item = MemoryFactItem(
            kind="fact", subject="탁여솔", object="", attribute="수강료", value=f"새 행 {len(self.prompts)}",
            truth_status="confirmed", asserted_by="narration", speaker="", known_by=["탁여솔"], importance=3,
            start_line=1, end_line=2,
        )  # fmt: skip
        return response_schema.model_validate({"facts": [item.model_dump()]})


async def _room_snapshots(db_session: AsyncSession, room_id: uuid.UUID) -> list[Any]:
    """스냅샷 칸 값(행 튜플) — ORM 객체가 아니라서 뒤의 `expire_all`·재조회가 앞서 받은 값을 만료시키지 않는다."""
    db_session.expire_all()
    snapshot = ChatRoomMemorySnapshot
    rows = await db_session.execute(
        sa.select(snapshot.id, snapshot.cursor_created_at, snapshot.cursor_message_id, snapshot.summary_text)
        .where(snapshot.chat_room_id == room_id)
        .order_by(snapshot.cursor_created_at, snapshot.cursor_message_id)
    )
    return list(rows)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def test_summary_replay_refolds_the_same_spans_with_names_from_earlier_snapshots_only(
    db_client: httpx.AsyncClient, db_session: AsyncSession, tmp_path: Path
) -> None:
    room = await _open_room(db_client, db_session, turns=40, lane="story")
    other = await _open_room(db_client, db_session, turns=12, lane="story")
    await _plant_snapshot(db_session, room, turn=10, text="원래 요약 1")
    await _plant_snapshot(db_session, room, turn=20, text="원래 요약 2")
    await _plant_snapshot(db_session, other, turn=10, text="다른 방 요약")
    first, second = await _room_snapshots(db_session, room.room_id)
    db_session.add(_make_memory_fact(room.room_id, first.id, kind="fact", subject="탁여솔", object=None,
                                     attribute="수강료", fact_key="fact|탁여솔|수강료", known_by=["탁여솔", "사용자"]))  # fmt: skip
    db_session.add(_make_memory_fact(room.room_id, second.id, ordinal=0, subject="육시온", object="편소담",
                                     fact_key="relation|육시온|편소담"))  # fmt: skip
    await db_session.commit()

    candidate = wp.SummaryCandidate(version="a1", slot="[방 인물] {room_people}", no_names="아직 없음", sha256="s")
    llm = RecordingLLM()
    out = tmp_path / "summary.jsonl"
    result = await wp.replay_summaries(
        async_sessionmaker(bind=db_session.bind, expire_on_commit=False),
        llm,
        room_id=room.room_id,
        lane="story",
        candidate=candidate,
        out_path=out,
        header={"kind": "header", "run": "summary"},
        writing_model="opus",
        expect_snapshots=2,
    )
    assert result["folds"] == 2
    # 첫 접기: 앞 스냅샷이 없어 사실 이름이 0개 → 고정 문구. 둘째 접기: 첫 스냅샷의 행 이름만(둘째 스냅샷의 이름은 아직 없다).
    assert "[방 인물] 아직 없음" in llm.prompts[0]
    assert "[방 인물] 탁여솔\n" in llm.prompts[1] and "육시온" not in llm.prompts[1]
    assert "사용자" not in llm.prompts[1].split("[방 인물]")[1].split("\n")[0]

    after = await _room_snapshots(db_session, room.room_id)
    assert [(s.cursor_created_at, s.cursor_message_id) for s in after] == [
        (first.cursor_created_at, first.cursor_message_id),
        (second.cursor_created_at, second.cursor_message_id),
    ]
    assert [s.summary_text for s in after] == ["다시 접은 요약 1", "다시 접은 요약 2"]
    assert [s.summary_text for s in await _room_snapshots(db_session, other.room_id)] == ["다른 방 요약"]

    lines = _read_jsonl(out)
    assert lines[0] == {"kind": "header", "run": "summary", "userNames": ["당신", "사용자"]}
    assert [(r["index"], r["roomPeopleCount"], r["noNames"], r["summary"]) for r in lines[1:]] == [
        (1, 0, True, "다시 접은 요약 1"),
        (2, 1, False, "다시 접은 요약 2"),
    ]
    with pytest.raises(SystemExit, match="이미"):
        await wp.replay_summaries(
            async_sessionmaker(bind=db_session.bind, expire_on_commit=False), llm, room_id=room.room_id,
            lane="story", candidate=candidate, out_path=out, header={}, writing_model="opus", expect_snapshots=2,
        )  # fmt: skip


async def test_summary_replay_refuses_a_snapshot_count_other_than_the_checkpoint(
    db_client: httpx.AsyncClient, db_session: AsyncSession, tmp_path: Path
) -> None:
    room = await _open_room(db_client, db_session, turns=40, lane="story")
    await _plant_snapshot(db_session, room, turn=10, text="원래 요약 1")
    candidate = wp.SummaryCandidate(version="a1", slot="{room_people}", no_names="없음", sha256="s")
    with pytest.raises(SystemExit, match="스냅샷"):
        await wp.replay_summaries(
            async_sessionmaker(bind=db_session.bind, expire_on_commit=False), RecordingLLM(), room_id=room.room_id,
            lane="story", candidate=candidate, out_path=tmp_path / "s.jsonl", header={}, writing_model="opus", expect_snapshots=2,
        )  # fmt: skip
    assert [s.summary_text for s in await _room_snapshots(db_session, room.room_id)] == ["원래 요약 1"]


async def test_budget_stop_before_a_call_is_not_swallowed_by_the_fold(
    db_client: httpx.AsyncClient, db_session: AsyncSession, tmp_path: Path
) -> None:
    room = await _open_room(db_client, db_session, turns=40, lane="story")
    await _plant_snapshot(db_session, room, turn=10, text="원래 요약 1")
    llm = RecordingLLM()

    def stop() -> None:
        raise BudgetExceededError("상한")

    candidate = wp.SummaryCandidate(version="a1", slot="{room_people}", no_names="없음", sha256="s")
    with pytest.raises(BudgetExceededError):
        await wp.replay_summaries(
            async_sessionmaker(bind=db_session.bind, expire_on_commit=False), llm, room_id=room.room_id,
            lane="story", candidate=candidate, out_path=tmp_path / "s.jsonl", header={}, writing_model="opus", expect_snapshots=1,
            before_call=stop,
        )  # fmt: skip
    assert llm.prompts == []


async def test_fact_replay_reextracts_every_snapshot_with_the_candidate_instruction(
    db_client: httpx.AsyncClient, db_session: AsyncSession, tmp_path: Path
) -> None:
    room = await _open_room(db_client, db_session, turns=20, lane="story")
    other = await _open_room(db_client, db_session, turns=10, lane="story")
    await _plant_snapshot(db_session, room, turn=10, text="요약 1")
    await _plant_snapshot(db_session, room, turn=20, text="요약 2")
    await _plant_snapshot(db_session, other, turn=10, text="다른 방 요약")
    first, _ = await _room_snapshots(db_session, room.room_id)
    (other_snapshot,) = await _room_snapshots(db_session, other.room_id)
    db_session.add(_make_memory_fact(room.room_id, first.id, value="옛 행"))
    db_session.add(_make_memory_fact_extraction(room.room_id, first.id))
    db_session.add(_make_memory_fact(other.room_id, other_snapshot.id, value="다른 방 행"))
    await db_session.commit()

    llm = RecordingLLM()
    out = tmp_path / "facts.jsonl"
    result = await wp.replay_facts(
        async_sessionmaker(bind=db_session.bind, expire_on_commit=False),
        llm,
        room_id=room.room_id,
        lane="story",
        candidate=wp.FactCandidate(version="k1", instruction="후보 사실 지시문", sha256="f"),
        out_path=out,
        header={"kind": "header", "run": "facts"},
        expect_snapshots=2,
    )
    assert result == {"snapshots": 2, "extracted": 2, "rows": 2}
    assert len(llm.prompts) == 2 and all(p.startswith("후보 사실 지시문") for p in llm.prompts)
    db_session.expire_all()
    values = (
        await db_session.scalars(
            sa.select(ChatMemoryFact.value).where(ChatMemoryFact.chat_room_id == room.room_id)
            .order_by(ChatMemoryFact.created_at)
        )
    ).all()  # fmt: skip
    assert sorted(values) == ["새 행 1", "새 행 2"]
    other_values = (
        await db_session.scalars(sa.select(ChatMemoryFact.value).where(ChatMemoryFact.chat_room_id == other.room_id))
    ).all()
    assert other_values == ["다른 방 행"]
    lines = _read_jsonl(out)
    assert lines[0] == {"kind": "header", "run": "facts", "userNames": ["당신", "사용자"]}
    # 끝 줄은 완료 표지다 — 멈춘 실행의 결과는 이 줄이 없어 지표가 거부한다.
    assert lines[-1] == {"kind": "done", "rows": 2}
    assert [(r["snapshotIndex"], r["subject"], r["knownBy"]) for r in lines[1:-1]] == [
        (1, "탁여솔", ["탁여솔"]),
        (2, "탁여솔", ["탁여솔"]),
    ]
