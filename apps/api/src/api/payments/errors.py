"""결제 도메인 예외. Bugsink 로 올라가는 메시지에는 고정 문자열·필드 이름·예외 클래스 이름만 싣는다.

포트원 SDK 의 예외와 역직렬화 실패 메시지는 응답 원문(고객 이름·전화·이메일)을 담는다. 그래서 포트원 쪽 실패는
여기 예외로 바꿔 원 예외를 체인에도 남기지 않고(`payments/portone.py`), 결제 객체도 메시지에 넣지 않는다.
"""


class PortOneUnavailableError(Exception):
    """포트원 호출이 결과를 주지 못했다(시간 초과·연결 실패·오류 응답·해석할 수 없는 응답). 결과를 모르는 상태라
    호출부는 재시도할 수 있는 실패로 다룬다. `operation` 은 부른 동작, `reason` 은 원 예외의 클래스 이름뿐이다."""

    def __init__(self, operation: str, reason: str) -> None:
        super().__init__(f"portone {operation} failed: {reason}")
        self.operation = operation
        self.reason = reason


class PortOneCancelRejectedError(Exception):
    """포트원이 취소 요청을 확정적으로 거절했다(취소 가능 잔액 불일치·이미 취소됨·결제 안 됨·PG 거절 등). 결과를 모르는
    `PortOneUnavailableError` 와 달리 "취소되지 않았다"가 확정이다. `reason` 은 거절 예외의 클래스 이름뿐이다."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"portone cancel rejected: {reason}")
        self.reason = reason


class PaymentMismatchError(Exception):
    """포트원이 결제 완료라고 하는데 주문과 맞지 않는다(금액·통화·상점·채널 중 하나). 지급하지 않고 수동 처리로 넘긴
    건을 Bugsink 에 남기는 데 쓴다. `field` 는 어긋난 항목 이름뿐이다."""

    def __init__(self, field: str) -> None:
        super().__init__(f"payment mismatch: {field}")
        self.field = field


class PaymentOwnerWithdrawnError(Exception):
    """결제가 확정됐는데 주문자가 이미 탈퇴했다 — 지급하지 않고 수동 환불로 넘긴 건을 Bugsink 에 남긴다."""


class PaymentWebhookConfigError(Exception):
    """웹훅 비밀이 비었거나 형식이 틀려 서명을 검증할 수 없다. 모든 웹훅이 거절되는 설정 사고라 Bugsink 에 남긴다."""


class PaymentRefundStuckError(Exception):
    """우리 취소 기록의 합이 포트원이 말하는 취소액과 다르다 — 맞추지 못한 취소가 남아 있다는 신호다."""
