import hashlib
import hmac

import bcrypt

from api.core.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def hash_withdrawn_email(email: str) -> str:
    """legal-revision-goal-prompt.md LR-8: 재가입 차단 대조는 salt 없는 **조회**라 bcrypt를
    쓸 수 없고(매번 다른 해시가 나와 조회가 불가능하다), 순수 SHA-256은 이메일 공간이 좁아
    사전 공격으로 되돌릴 수 있다. 서버 비밀키를 붙인 HMAC-SHA256으로 그 둘을 피한다."""
    return hmac.new(
        settings.withdrawn_email_hmac_key.encode("utf-8"), email.encode("utf-8"), hashlib.sha256
    ).hexdigest()
