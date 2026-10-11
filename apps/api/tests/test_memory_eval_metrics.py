"""평가 하네스의 지표 계산 — 정답 일치 규칙, 윌슨 구간, 정확 McNemar, recall@k, 기울기, 층화 분할.

하네스는 병합하지 않는 실험 브랜치에만 있다. 이 테스트는 그 브랜치에서 수치 정의가 사전 등록대로인지 지킨다."""

import math

import pytest

from memory_eval.metrics import (
    answer_matches,
    mcnemar_exact_one_sided,
    normalize_match_text,
    ols_slope,
    recall_at_k,
    stratified_split,
    wilson_interval,
)


def test_normalize_removes_whitespace_and_casefolds_after_nfc() -> None:
    decomposed = "가 B"  # 자모로 쪼갠 "가" + 공백 + 대문자
    assert normalize_match_text(decomposed) == "가b"


def test_every_bundle_must_be_satisfied_by_one_of_its_spellings() -> None:
    bundles = [["말한 적 없"], ["태민"]]
    assert answer_matches("그건 태민이 한 말이고 너는 말한적 없어", bundles)
    assert not answer_matches("너는 말한 적 없어", bundles)
    assert answer_matches("우비 빌려줬잖아", [["우비", "비옷"]])
    assert answer_matches("비옷 빌려줬잖아", [["우비", "비옷"]])
    assert not answer_matches("우산 빌려줬잖아", [["우비", "비옷"]])


def test_match_ignores_spacing_on_both_sides() -> None:
    assert answer_matches("옥상정원에서 봤지", [["옥상 정원"]])
    assert answer_matches("옥상 정원에서 봤지", [["옥상정원"]])


def test_spelling_with_digits_matches_only_when_not_glued_to_other_digits() -> None:
    keys = [["1월15일", "일월십오일"]]
    assert answer_matches("1월 15일이었어", keys)
    assert not answer_matches("11월 15일이었어", keys)
    assert not answer_matches("1월 150일", keys)
    # 같은 글에 경계가 맞는 다른 자리가 있으면 일치다.
    assert answer_matches("11월15일 말고 1월15일", keys)
    assert answer_matches("일월 십오일", keys)


def test_spelling_without_digits_is_a_plain_substring() -> None:
    assert answer_matches("여덟시십분쯤", [["여덟시십분", "8시10분"]])
    assert not answer_matches("8시 100분", [["8시10분"]])


def test_wilson_interval_matches_known_values() -> None:
    low, high = wilson_interval(5, 10)
    assert low == pytest.approx(0.2366, abs=1e-4)
    assert high == pytest.approx(0.7634, abs=1e-4)
    low, high = wilson_interval(10, 10)
    assert low == pytest.approx(0.7225, abs=1e-4)
    assert high == pytest.approx(1.0)
    low, high = wilson_interval(0, 7)
    assert low == pytest.approx(0.0)
    assert high == pytest.approx(0.3543, abs=1e-4)


def test_wilson_interval_of_empty_sample_is_the_whole_range() -> None:
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_exact_mcnemar_one_sided_is_binomial_tail_of_discordant_pairs() -> None:
    # 불일치 쌍이 전부 B 편이면 5쌍부터 p < 0.05, 4쌍은 아니다.
    assert mcnemar_exact_one_sided(5, 0) == pytest.approx(1 / 32)
    assert mcnemar_exact_one_sided(4, 0) == pytest.approx(1 / 16)
    assert mcnemar_exact_one_sided(6, 1) == pytest.approx(8 / 128)
    assert mcnemar_exact_one_sided(0, 3) == pytest.approx(1.0)
    assert mcnemar_exact_one_sided(0, 0) == pytest.approx(1.0)


def test_recall_at_k_counts_gold_only_within_the_first_k() -> None:
    ranked = ["e9", "e2", "e7", "e1"]
    assert recall_at_k(ranked, {"e7"}, 3)
    assert not recall_at_k(ranked, {"e1"}, 3)
    assert recall_at_k(ranked, {"e1", "e2"}, 3)
    assert not recall_at_k(ranked, set(), 10)


def test_ols_slope_of_flat_and_rising_series() -> None:
    assert ols_slope([(t, 5000.0) for t in range(101, 301)]) == pytest.approx(0.0)
    assert ols_slope([(t, 2.0 * t + 7) for t in range(101, 301)]) == pytest.approx(2.0)
    saw = [(t, 1000.0 + 50 * (t % 10)) for t in range(101, 301)]
    assert abs(ols_slope(saw)) < 0.5


def test_ols_slope_needs_two_distinct_x() -> None:
    assert math.isnan(ols_slope([(1, 3.0)]))


def test_stratified_split_shuffles_sorted_ids_per_stratum_and_sends_ceil_half_to_dev() -> None:
    strata = {"물건": ["obj03", "obj01", "obj02"], "장소": ["loc02", "loc01"]}
    split = stratified_split(strata, seed=20261011)
    assert set(split) == {"obj01", "obj02", "obj03", "loc01", "loc02"}
    assert sum(1 for i in ("obj01", "obj02", "obj03") if split[i] == "dev") == 2
    assert sum(1 for i in ("loc01", "loc02") if split[i] == "dev") == 1
    # 입력 순서가 달라도 같은 결과(정렬 뒤 섞는다).
    again = stratified_split({"장소": ["loc01", "loc02"], "물건": ["obj02", "obj03", "obj01"]}, seed=20261011)
    assert again == split


def test_stratified_split_reproduces_python_shuffle_of_sorted_ids() -> None:
    import random

    ids = [f"x{i:02d}" for i in range(7)]
    order = sorted(ids)
    random.Random(7).shuffle(order)
    expected = {i: ("dev" if k < 4 else "test") for k, i in enumerate(order)}
    assert stratified_split({"only": list(reversed(ids))}, seed=7) == expected


@pytest.mark.parametrize(
    ("spoken", "key"),
    [
        pytest.param("여덟 시 십 분", "8시10분", id="native-hour-sino-minute"),
        pytest.param("여덟시10분", "8시10분", id="mixed-native-digit"),
        pytest.param("10시삼십분", "10시30분", id="mixed-digit-sino"),
        pytest.param("8:10", "8시10분", id="colon"),
        pytest.param("열 시 반", "10시30분", id="native-half"),
        pytest.param("10시반", "10시30분", id="digit-half"),
        pytest.param("열한시", "11시", id="native-eleven"),
        pytest.param("열두 시", "12시", id="native-twelve"),
        pytest.param("여섯시 삼십이분", "6시32분", id="sino-thirty-two"),
        pytest.param("십이월 십삼일", "12월13일", id="sino-month-day"),
        pytest.param("이월 이십구일", "2월29일", id="sino-twenty-nine"),
        pytest.param("일월 십오일", "1월15일", id="sino-one-fifteen"),
        pytest.param("십일일", "11일", id="sino-eleven-day"),
    ],
)
def test_korean_numerals_before_units_compare_as_digits(spoken: str, key: str) -> None:
    assert answer_matches(spoken, [[key]])
    assert answer_matches(f"그날 {spoken}에 봤지", [[key]])
    assert answer_matches(key, [[spoken]])


def test_numerals_are_converted_only_right_before_a_unit() -> None:
    # 하루(일)·조사(이)는 단위가 바로 뒤에 오지 않으면 숫자로 보지 않는다.
    assert normalize_match_text("생일이 언제야") == "생일이언제야"
    assert normalize_match_text("이 사람 일했어") == "이사람일했어"
    assert not answer_matches("열한시", [["1시"]])


def test_converted_digits_keep_the_digit_boundary_rule() -> None:
    assert not answer_matches("열한 시 십분", [["1시10분"]])
    assert answer_matches("한 시 십분", [["1시10분"]])
