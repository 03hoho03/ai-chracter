import hashlib
import hmac

import bcrypt
from starlette.concurrency import run_in_threadpool

from api.core.config import settings

# bcrypt 한 번은 수백 ms 가 걸리는 CPU 작업이라 이벤트 루프에서 돌리면 그동안 이 프로세스의 다른
# 요청이 전부 멈춘다. bcrypt 는 해시 계산 중 GIL 을 놓으므로 스레드풀로 옮기면 루프가 실제로 풀린다.
# 호출부마다 감싸지 않고 여기서 한 번에 비동기로 바꾼다 — 동기 판이 남아 있으면 그걸 다시 부르는
# 실수를 막을 수단이 없다. `await` 를 빠뜨리면 코루틴이 항상 참이라 `not verify_password(...)` 가
# 오답을 통과시키므로, mypy 의 `truthy-bool` 검사가 그 누락을 잡게 켜 두었다(pyproject.toml).


async def hash_password(password: str) -> str:
    hashed = await run_in_threadpool(bcrypt.hashpw, password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


async def verify_password(password: str, password_hash: str) -> bool:
    return await run_in_threadpool(
        bcrypt.checkpw, password.encode("utf-8"), password_hash.encode("utf-8")
    )


def hash_withdrawn_email(email: str) -> str:
    """재가입 차단 대조는 salt 없는 **조회**라 bcrypt를
    쓸 수 없고(매번 다른 해시가 나와 조회가 불가능하다), 순수 SHA-256은 이메일 공간이 좁아
    사전 공격으로 되돌릴 수 있다. 서버 비밀키를 붙인 HMAC-SHA256으로 그 둘을 피한다."""
    return hmac.new(
        settings.withdrawn_email_hmac_key.encode("utf-8"), email.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def hash_identity_ci(ci: str) -> str:
    """본인인증 CI 를 저장·대조용 HMAC-SHA256 으로 바꾼다. 이메일 해시와 같은 이유(조회가 되어야 하고, 서버 비밀키 없이는
    되돌리거나 다른 곳의 CI 와 맞춰 볼 수 없어야 한다)지만 키는 따로 쓴다(`core/config.py` 의 `identity_ci_hmac_key` 설명)."""
    return hmac.new(settings.identity_ci_hmac_key.encode("utf-8"), ci.encode("utf-8"), hashlib.sha256).hexdigest()
