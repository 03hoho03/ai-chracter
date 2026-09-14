"""admin 라우터가 탈퇴 유저(nickname NULL)를 렌더링할 때 쓰는 표시용 상수
(legal-revision-goal-prompt.md LR-27). inquiries.py·contents.py 두 곳에서 같은 값을
써야 해서 리터럴을 복사하는 대신 여기로 뽑는다."""

WITHDRAWN_USER_NICKNAME = "(탈퇴한 사용자)"
