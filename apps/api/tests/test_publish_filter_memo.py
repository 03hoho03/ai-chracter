import uuid
from typing import Any

from api.content.publish_filter_memo import PASSED_KEY_PREFIX, PASSED_TTL_SECONDS, has_passed, remember_pass, screening_key
from api.core.redis import redis_client

_CONTENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_SET_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
_BASE: dict[str, Any] = {
    "content_id": _CONTENT_ID,
    "prompt_set_id": _SET_ID,
    "model": "gemini-a",
    "thinking_budget": None,
    "prompt": "심사 문장",
    "images": [(b"first", "image/png"), (b"second", "image/webp")],
}


def test_screening_key_is_stable_for_the_same_input() -> None:
    assert screening_key(**_BASE) == screening_key(**dict(_BASE, images=list(_BASE["images"])))
    assert screening_key(**_BASE).startswith(PASSED_KEY_PREFIX)


def test_screening_key_changes_with_every_input() -> None:
    """심사 결과를 바꿀 수 있는 입력은 하나만 달라도 다른 키가 된다. 경계가 흐려 두 입력이 같은 바이트열로
    이어지는 경우(글자를 옆 칸으로 옮김)도 구분한다."""
    variants: list[dict[str, Any]] = [
        dict(_BASE, content_id=uuid.UUID("00000000-0000-0000-0000-000000000009")),
        dict(_BASE, prompt_set_id=uuid.UUID("00000000-0000-0000-0000-000000000009")),
        dict(_BASE, model="gemini-b"),
        dict(_BASE, thinking_budget=0),
        dict(_BASE, thinking_budget=512),
        dict(_BASE, prompt="심사 문장."),
        dict(_BASE, images=[(b"first", "image/png"), (b"second!", "image/webp")]),
        dict(_BASE, images=[(b"first", "image/png"), (b"second", "image/png")]),
        dict(_BASE, images=[(b"second", "image/webp"), (b"first", "image/png")]),
        dict(_BASE, images=[(b"first", "image/png")]),
        dict(_BASE, images=[]),
        dict(_BASE, images=[(b"irst", "image/pngf"), (b"second", "image/webp")]),
        dict(_BASE, model="gemini-a심", prompt="사 문장"),
    ]
    keys = {screening_key(**variant) for variant in variants}
    assert len(keys) == len(variants)
    assert screening_key(**_BASE) not in keys


async def test_remembered_pass_is_found_and_expires_in_thirty_days() -> None:
    key = screening_key(**dict(_BASE, content_id=uuid.uuid4()))
    assert await has_passed(key) is False

    await remember_pass(key)

    assert await has_passed(key) is True
    ttl = await redis_client.ttl(key)
    assert PASSED_TTL_SECONDS - 60 < ttl <= PASSED_TTL_SECONDS
    assert PASSED_TTL_SECONDS == 30 * 24 * 60 * 60
