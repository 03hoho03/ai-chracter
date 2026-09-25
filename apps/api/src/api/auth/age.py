from datetime import date

MINIMUM_AGE_THRESHOLD = 14


def calculate_age(birth_date: date, today: date) -> int:
    age = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


def is_under_minimum_age(birth_date: date, today: date) -> bool:
    """만 14세 미만은 가입을 거부한다."""
    return calculate_age(birth_date, today) < MINIMUM_AGE_THRESHOLD
