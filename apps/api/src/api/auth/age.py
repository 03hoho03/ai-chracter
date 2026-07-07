from datetime import date

GUARDIAN_CONSENT_AGE_THRESHOLD = 14


def calculate_age(birth_date: date, today: date) -> int:
    age = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


def is_guardian_consent_required(birth_date: date, today: date) -> bool:
    """techspec-backend-auth.md §3: 만 14세 미만이면 법정대리인 동의가 필요하다."""
    return calculate_age(birth_date, today) < GUARDIAN_CONSENT_AGE_THRESHOLD
