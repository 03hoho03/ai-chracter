from datetime import date

MINIMUM_AGE_THRESHOLD = 14
# 클로즈드 베타는 성인만 받는다 — 가입 하한(만 14세)과 별개로 베타 지정 때만 확인한다.
BETA_MINIMUM_AGE = 19
# 결제는 성인만 한다 — 미성년자의 결제는 법정대리인이 취소할 수 있어, 본인인증한 생년월일로 만 19세를 확인한다. 베타
# 하한과 값이 같아도 근거가 달라 따로 둔다.
PAYMENT_MINIMUM_AGE = 19
# 크리에이터 정산 신청은 성인만 한다 — 정산은 지급 약정이고 미성년자의 약정은 법정대리인이 취소할 수 있어, 본인인증한
# 생년월일로 만 19세를 확인한다. 결제 하한과 값이 같아도 근거가 달라 따로 둔다.
CREATOR_PAYOUT_MINIMUM_AGE = 19


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


def is_under_payment_minimum_age(birth_date: date, today: date) -> bool:
    """만 19세 미만은 결제할 수 없다."""
    return calculate_age(birth_date, today) < PAYMENT_MINIMUM_AGE


def is_under_creator_payout_minimum_age(birth_date: date, today: date) -> bool:
    """만 19세 미만은 크리에이터 정산을 신청할 수 없다."""
    return calculate_age(birth_date, today) < CREATOR_PAYOUT_MINIMUM_AGE
