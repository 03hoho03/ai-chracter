"""다양성 매트릭스(`seed_content/data/diversity_matrix.json`) 검증.

두 종류가 섞여 있다: 커밋된 실물 데이터가 §7 을 그대로 전사했는지 보는 테스트와,
`validate_matrix()` 가 규칙 위반을 실제로 잡아내는지 보는 테스트.
"""

import json
from pathlib import Path

import pytest
from seed_content.loader import SeedContentError
from seed_content.matrix import (
    MAJOR_SLUG,
    MIN_AXIS_DIFFERENCE,
    SLOTS_PER_AXIS_VALUE,
    SLOTS_PER_GENRE,
    MatrixSlot,
    load_matrix,
    validate_matrix,
)

# tasks/prd-genre-seed-content.md §7 의 30개 슬러그를 장르·슬롯 순서 그대로 옮긴 것.
# 전사 과정에서 슬러그가 빠지거나 오타가 나면 여기서 걸린다.
EXPECTED_SLUGS = [
    "romance-3rdloop",
    "romance-lockedwith",
    "romance-threeoffering",
    "fantasy-burnlife",
    "fantasy-guildkitchen",
    "fantasy-inkcity",
    "mystery-elevator",
    "mystery-onair12",
    "mystery-teahouse",
    "sf-backup",
    "sf-longnight",
    "sf-norespawn",
    "daily-rooftop",
    "daily-lostandfound",
    "daily-lastorder",
    "school-relay",
    "school-notebook",
    "school-honorcode",
    "horror-sevenrules",
    "horror-callerid",
    "horror-yeondeung",
    "comedy-fakefather",
    "comedy-demonintern",
    "comedy-condolence",
    "wuxia-oneform",
    "wuxia-snowinn",
    "wuxia-lastguard",
    "healing-4am",
    "healing-walkinglog",
    "healing-seedvillage",
]

EXPECTED_GENRE_IDS = {
    "로맨스": "b8a1e6b0-1c1a-4b8a-9b0a-000000000001",
    "판타지": "b8a1e6b0-1c1a-4b8a-9b0a-000000000002",
    "미스터리·스릴러": "b8a1e6b0-1c1a-4b8a-9b0a-000000000003",
    "SF": "b8a1e6b0-1c1a-4b8a-9b0a-000000000004",
    "일상": "b8a1e6b0-1c1a-4b8a-9b0a-000000000005",
    "학원": "b8a1e6b0-1c1a-4b8a-9b0a-000000000006",
    "공포": "b8a1e6b0-1c1a-4b8a-9b0a-000000000007",
    "개그·코미디": "b8a1e6b0-1c1a-4b8a-9b0a-000000000008",
    "무협·액션": "b8a1e6b0-1c1a-4b8a-9b0a-000000000009",
    "힐링": "b8a1e6b0-1c1a-4b8a-9b0a-00000000000a",
}


@pytest.fixture(scope="module")
def slots() -> list[MatrixSlot]:
    return load_matrix()


def _same_genre(slots: list[MatrixSlot], genre: str) -> list[MatrixSlot]:
    return sorted((s for s in slots if s.genre == genre), key=lambda s: s.slot)


def test_matrix_transcribes_all_thirty_slugs(slots: list[MatrixSlot]) -> None:
    assert [s.slug for s in slots] == EXPECTED_SLUGS


def test_every_genre_has_three_slots_with_the_master_genre_id(slots: list[MatrixSlot]) -> None:
    assert set(EXPECTED_GENRE_IDS) == {s.genre for s in slots}
    for genre, genre_id in EXPECTED_GENRE_IDS.items():
        group = _same_genre(slots, genre)
        assert len(group) == SLOTS_PER_GENRE
        assert [s.slot for s in group] == [1, 2, 3]
        assert {str(s.genre_id) for s in group} == {genre_id}


def test_only_the_major_slot_is_hand_written(slots: list[MatrixSlot]) -> None:
    assert [s.slug for s in slots if s.hand_written] == [MAJOR_SLUG]


def test_every_slot_carries_the_generator_inputs(slots: list[MatrixSlot]) -> None:
    for slot in slots:
        assert slot.title and slot.one_liner and slot.setting
        assert len(slot.stats) == 3
        assert slot.starting_setups
        assert slot.forbidden


def test_axis_distribution_matches_the_spec_table(slots: list[MatrixSlot]) -> None:
    """§7 말미 검증 표: 5개 축과 target 모두 값별로 정확히 10개."""
    axes = {
        "tone": [s.axes.tone for s in slots],
        "relation": [s.axes.relation for s in slots],
        "verb": [s.axes.verb for s in slots],
        "space": [s.axes.space for s in slots],
        "endingPressure": [s.axes.ending_pressure for s in slots],
        "target": [s.target for s in slots],
    }
    for axis, values in axes.items():
        counts = {value: values.count(value) for value in set(values)}
        assert sorted(counts.values()) == [SLOTS_PER_AXIS_VALUE] * 3, f"{axis}: {counts}"


def test_same_genre_slots_differ_in_at_least_four_axes(slots: list[MatrixSlot]) -> None:
    for genre in EXPECTED_GENRE_IDS:
        group = _same_genre(slots, genre)
        for left, right in ((group[0], group[1]), (group[0], group[2]), (group[1], group[2])):
            different = sum(
                1 for a, b in zip(left.axes.as_tuple(), right.axes.as_tuple(), strict=True) if a != b
            )
            assert different >= MIN_AXIS_DIFFERENCE, f"{left.slug} ↔ {right.slug}: {different}"


def test_forbidden_accumulates_earlier_slots_of_the_same_genre(slots: list[MatrixSlot]) -> None:
    """앞 슬롯의 금지 목록(= 장르 클리셰 + 그 앞 슬롯 소재)이 뒤 슬롯에 그대로 포함된다."""
    for genre in EXPECTED_GENRE_IDS:
        group = _same_genre(slots, genre)
        for earlier, later in zip(group, group[1:], strict=False):
            assert set(earlier.forbidden) < set(later.forbidden), f"{genre}: {later.slug}"


def test_validate_matrix_rejects_too_similar_slots(slots: list[MatrixSlot]) -> None:
    broken = [s.model_copy(deep=True) for s in slots]
    # 로맨스 2번 슬롯의 좌표를 1번과 한 축만 다르게 만든다.
    broken[1].axes = broken[0].axes.model_copy(update={"tone": "피폐"})

    with pytest.raises(SeedContentError, match="축 1개만 다르다"):
        validate_matrix(broken)


def test_validate_matrix_rejects_broken_distribution(slots: list[MatrixSlot]) -> None:
    broken = [s.model_copy(deep=True) for s in slots]
    broken[1].target = "male"

    with pytest.raises(SeedContentError, match="축 'target' 의 분포"):
        validate_matrix(broken)


def test_validate_matrix_rejects_duplicate_slug(slots: list[MatrixSlot]) -> None:
    broken = [s.model_copy(deep=True) for s in slots]
    broken[1].slug = broken[0].slug

    with pytest.raises(SeedContentError, match="slug 가 중복됐다"):
        validate_matrix(broken)


def test_validate_matrix_rejects_extra_hand_written_slot(slots: list[MatrixSlot]) -> None:
    broken = [s.model_copy(deep=True) for s in slots]
    broken[1].hand_written = True

    with pytest.raises(SeedContentError, match="handWritten"):
        validate_matrix(broken)


def test_validate_matrix_rejects_wrong_slot_count(slots: list[MatrixSlot]) -> None:
    with pytest.raises(SeedContentError, match="슬롯이 2개다"):
        validate_matrix([s.model_copy(deep=True) for s in slots if s.slug != "romance-threeoffering"])


def test_load_matrix_reports_the_file_name_on_bad_json(tmp_path: Path) -> None:
    path = tmp_path / "diversity_matrix.json"
    path.write_text("{ not json", encoding="utf-8")

    with pytest.raises(SeedContentError, match="diversity_matrix.json"):
        load_matrix(path)


def test_load_matrix_reports_the_file_name_on_unknown_axis_value(
    tmp_path: Path, slots: list[MatrixSlot]
) -> None:
    raw = [json.loads(s.model_dump_json(by_alias=True)) for s in slots]
    raw[0]["axes"]["tone"] = "훈훈"
    path = tmp_path / "diversity_matrix.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(SeedContentError, match="diversity_matrix.json"):
        load_matrix(path)
