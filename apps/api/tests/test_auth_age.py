from datetime import date

from api.auth.age import calculate_age, is_under_minimum_age


def test_calculate_age_before_birthday_this_year() -> None:
    assert calculate_age(date(2010, 6, 15), date(2026, 6, 14)) == 15


def test_calculate_age_on_or_after_birthday_this_year() -> None:
    assert calculate_age(date(2010, 6, 15), date(2026, 6, 15)) == 16


def test_is_under_minimum_age_true_for_13_year_old() -> None:
    assert is_under_minimum_age(date(2013, 1, 1), date(2026, 7, 7)) is True


def test_is_under_minimum_age_false_exactly_14() -> None:
    assert is_under_minimum_age(date(2012, 7, 7), date(2026, 7, 7)) is False


def test_is_under_minimum_age_false_for_adult() -> None:
    assert is_under_minimum_age(date(2000, 1, 1), date(2026, 7, 7)) is False
