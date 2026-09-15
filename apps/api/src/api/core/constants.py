"""탈퇴 유저(nickname NULL)를 렌더링할 때 쓰는 표시용 상수(legal-revision-goal-prompt.md
LR-27). 원래 admin 전용(admin/constants.py)이었으나 content 라우터도 같은 값이 필요해져
(§3-2 LR-27 갱신) 두 도메인이 공유하는 core로 옮겼다 — `core/security.py`의
`hash_withdrawn_email`과 같은 전례(탈퇴 관련 공용 로직은 core에 둔다)를 따른다."""

WITHDRAWN_USER_NICKNAME = "(탈퇴한 사용자)"
