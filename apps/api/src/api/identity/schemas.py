from datetime import datetime

from api.core.schema import CamelModel


class StartIdentityVerificationResponse(CamelModel):
    """브라우저가 포트원 본인인증 창에 그대로 넘기는 값. 상점 id·채널키는 웹 빌드에 넣지 않고 이 응답으로만 내린다."""

    identity_verification_id: str
    store_id: str
    channel_key: str


class CompleteIdentityVerificationResponse(CamelModel):
    verified_at: datetime
