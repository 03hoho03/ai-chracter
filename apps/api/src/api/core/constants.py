"""여러 도메인이 공유하는 탈퇴 관련 상수. `core/security.py`의 `hash_withdrawn_email`과 같은
전례(탈퇴 관련 공용 로직은 core에 둔다)를 따른다."""

from datetime import timedelta

# 탈퇴 유저(nickname NULL)를 렌더링할 때 쓰는 표시용 상수. 원래 admin 전용
# (admin/constants.py)이었으나 content 라우터도 같은 값이 필요해져 두 도메인이 공유하는 core로 옮겼다.
WITHDRAWN_USER_NICKNAME = "(탈퇴한 사용자)"

# 탈퇴일로부터 이 기간 안에는 같은 이메일(HMAC)로
# 재가입이 막힌다. `auth/router.py`의 `_reregistration_blocked`(차단 조회)와
# `scripts/ops/backup_db.py`의 만료 행 삭제가 이 값을 공유해야 "차단이 풀리는 시점"과
# "행이 파기되는 시점"이 갈라지지 않는다. 원래 auth/router.py에 있었으나 scripts에서도
# 필요해져 옮겼다.
WITHDRAWN_EMAIL_BLOCK_PERIOD = timedelta(days=365)

# 탈퇴한 인증 회원의 CI 해시(`withdrawn_identities`)를 남겨 두는 기간. 이 기간 안에는 같은 사람이 새 계정으로 1회성 미션
# 보상을 다시 받지 못하고, 지나면 행을 파기한다. 탈퇴 이메일 해시와 같은 1년이라 백업 크론이 같은 상수로 두 표를 지운다
# (`scripts/ops/backup_db.py` — 그 파일은 `api` 를 import 할 수 없어 값을 복제하고, 테스트가 둘이 같은지 본다).
WITHDRAWN_IDENTITY_RETENTION_PERIOD = WITHDRAWN_EMAIL_BLOCK_PERIOD
