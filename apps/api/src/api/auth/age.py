from datetime import date

MINIMUM_AGE_THRESHOLD = 14
# 클로즈드 베타는 성인만 받는다 — 가입 하한(만 14세)과 별개로 베타 지정 때만 확인한다.
BETA_MINIMUM_AGE = 19


def calculate_age(birth_date: date, today: date) -> int:
    age = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


def is_under_minimum_age(birth_date: date, today: date) -> bool:
    """만 14세 미만은 가입을 거부한다."""
    return calculate_age(birth_date, today) < MINIMUM_AGE_THRESHOLD


def is_under_beta_minimum_age(birth_date: date, today: date) -> bool:
    """만 19세 미만은 베타 참가자로 지정하지 않는다."""
    return calculate_age(birth_date, today) < BETA_MINIMUM_AGE
