from api.core.schema import CamelModel


class CloverBalanceResponse(CamelModel):
    """clover-techspec.md §4-2. Python은 snake_case, JSON은 camelCase다."""

    balance: int
    # 오늘(KST) 이미 확인했는가 — false면 FE가 소진 시 확인 모달을 띄운다
    # (clover-goal-prompt.md CL-19).
    spend_confirmed_today: bool
    # 오늘(KST) 출석을 아직 안 받았는가 — true면 FE가 attendance를 POST한다
    # (clover-techspec.md CT-10).
    attendance_claimable: bool


class CloverAttendanceResponse(CamelModel):
    # 오늘 이미 받았으면 false다. **에러가 아니다** — 멱등을 서버가 보장하므로
    # (clover-techspec.md CT-10) FE가 여러 번 불러도 200이고, `useEffect` 경합도 안전하다.
    granted: bool
    balance: int


class CloverMissionItem(CamelModel):
    """clover-page-goal-prompt.md CE-13. `achieved`·`claimed`는 매 조회마다 EXISTS로 다시
    계산한다 — 저장된 상태가 아니다(T-13)."""

    key: str
    reward: int
    achieved: bool
    # 원장에 이 미션의 멱등키가 이미 있는가 — true면 FE가 "청구완료"로 표시한다.
    claimed: bool


class CloverMissionsResponse(CamelModel):
    missions: list[CloverMissionItem]


class CloverMissionClaimResponse(CamelModel):
    # 이미 청구했으면 false다 — 출석(`CloverAttendanceResponse.granted`)과 같은 규칙,
    # **에러가 아니다**.
    granted: bool
    balance: int
