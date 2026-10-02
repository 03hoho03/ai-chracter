"""발행 심사를 통과한 입력을 기억해, 아무것도 바뀌지 않은 재발행에서 심사 LLM 호출을 건너뛴다.

심사 LLM 이 보는 것은 렌더된 심사 문장과 이미지(바이트·형식, 순서대로)뿐이고, 판정을 내리는 것은 활성 심사
세트와 실제 모델이다. 이 다섯에 콘텐츠 id 를 더한 값이 직전에 통과한 심사와 완전히 같을 때만 건너뛴다. 콘텐츠
id 를 넣는 건 통과를 작품 하나에 묶으려는 것이다 — 다른 작품이 같은 그림을 들고 와도 각자 심사받는다. 심사 문장에는
작가 글이 없고 이미지 목록 라벨(칸의 인물·장면 이름 포함)만 있으므로, 글만 고친 재발행은 건너뛰고 칸 이름을 바꾸면
다시 심사한다.

기억은 통과 직후에만 쓰고 거부·호출 실패·파싱 실패는 남기지 않는다. 읽기가 실패하거나 늦으면 기억이 없는
것으로 본다 — 발행 심사는 실패하면 막는(fail-closed) 경로라, 생략은 통과를 확인했을 때만 한다.
"""

import asyncio
import hashlib
import logging
import uuid
from collections.abc import Sequence

from api.core.redis import redis_client
from api.core.sentry import capture_dependency_failure

logger = logging.getLogger(__name__)

PASSED_KEY_PREFIX = "publish_filter_passed:"
# 키 하나가 값 한 글자짜리라 한 달을 둬도 부담이 없다. 오래된 통과로 잘못 건너뛰는 일은 기한이 아니라 키가
# 막는다 — 입력이 하나라도 바뀌면 다른 키가 된다.
PASSED_TTL_SECONDS = 30 * 24 * 60 * 60
# 앱과 Redis 는 같은 VM 의 도커 네트워크라 정상 왕복은 1ms 안팎이다. 공용 클라이언트에 소켓 timeout 이 없어
# 이 상한이 없으면 응답 없는 Redis 가 발행 요청을 무한정 붙잡는다. 넘기면 심사를 그대로 한다.
REDIS_TIMEOUT_SECONDS = 0.1


def screening_key(
    *,
    content_id: uuid.UUID,
    prompt_set_id: uuid.UUID,
    model: str,
    prompt: str,
    images: Sequence[tuple[bytes, str]],
) -> str:
    """입력마다 길이를 앞에 붙여 이어 붙인 뒤 해시한다. 길이가 없으면 경계를 옮긴 두 입력(글자 하나를 옆
    칸으로)이 같은 바이트열이 되어 같은 키를 얻는다."""
    digest = hashlib.sha256()
    parts: list[bytes] = [content_id.bytes, prompt_set_id.bytes, model.encode(), prompt.encode()]
    for data, mime_type in images:
        parts += [mime_type.encode(), data]
    for part in parts:
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return f"{PASSED_KEY_PREFIX}{digest.hexdigest()}"


async def has_passed(key: str) -> bool:
    """이 입력이 통과한 적이 있으면 참. 확인하지 못하면(Redis 오류·timeout) 거짓 — 심사를 한다."""
    try:
        async with asyncio.timeout(REDIS_TIMEOUT_SECONDS):
            return bool(await redis_client.exists(key))
    except Exception as exc:
        logger.warning("발행 심사 통과 기억을 읽지 못했다 — 심사를 그대로 한다", exc_info=True)
        capture_dependency_failure(exc, dependency="redis")
        return False


async def remember_pass(key: str) -> None:
    """통과를 남긴다. 실패해도 이번 발행은 막지 않는다 — 다음 재발행이 한 번 더 심사할 뿐이다."""
    try:
        async with asyncio.timeout(REDIS_TIMEOUT_SECONDS):
            await redis_client.set(key, "1", ex=PASSED_TTL_SECONDS)
    except Exception as exc:
        logger.warning("발행 심사 통과를 기억하지 못했다 — 다음 재발행은 다시 심사한다", exc_info=True)
        capture_dependency_failure(exc, dependency="redis")
