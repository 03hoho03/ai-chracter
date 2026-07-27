from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from api.llm.client import LLMClientError, LLMPolicyViolationError
from api.llm.image import GeminiImageClient, ImageStylePreset


def _make_client(monkeypatch: pytest.MonkeyPatch, generate_content: Any) -> GeminiImageClient:
    client = GeminiImageClient(api_key="test-key")
    fake_client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    monkeypatch.setattr(client, "_client", fake_client)
    return client


def _image_response(data: bytes = b"fake-png-bytes", mime_type: str = "image/png") -> SimpleNamespace:
    return SimpleNamespace(
        prompt_feedback=None,
        candidates=[
            genai_types.Candidate(
                finish_reason=genai_types.FinishReason.STOP,
                content=genai_types.Content(
                    parts=[genai_types.Part(inline_data=genai_types.Blob(data=data, mime_type=mime_type))]
                ),
            )
        ],
    )


def _api_error() -> genai_errors.APIError:
    return genai_errors.APIError(code=503, response_json={"error": {"message": "unavailable"}})


async def test_generate_image_extracts_bytes_and_mime_type(monkeypatch: pytest.MonkeyPatch) -> None:
    async def generate_content(**_: Any) -> SimpleNamespace:
        return _image_response(data=b"fake-png-bytes", mime_type="image/png")

    client = _make_client(monkeypatch, generate_content)

    data, mime_type = await client.generate_image("a cat", ImageStylePreset.NONE, "1:1")

    assert data == b"fake-png-bytes"
    assert mime_type == "image/png"


async def test_generate_image_applies_style_preset_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    received: dict[str, Any] = {}

    async def generate_content(**kwargs: Any) -> SimpleNamespace:
        received.update(kwargs)
        return _image_response()

    client = _make_client(monkeypatch, generate_content)

    await client.generate_image("a cat", ImageStylePreset.ANIME, "1:1")

    assert received["contents"] == "a cat, anime style, cel shading, clean lineart"


async def test_generate_image_none_preset_sends_prompt_unmodified(monkeypatch: pytest.MonkeyPatch) -> None:
    received: dict[str, Any] = {}

    async def generate_content(**kwargs: Any) -> SimpleNamespace:
        received.update(kwargs)
        return _image_response()

    client = _make_client(monkeypatch, generate_content)

    await client.generate_image("a cat", ImageStylePreset.NONE, "1:1")

    assert received["contents"] == "a cat"


async def test_generate_image_passes_aspect_ratio_via_image_config(monkeypatch: pytest.MonkeyPatch) -> None:
    received: dict[str, Any] = {}

    async def generate_content(**kwargs: Any) -> SimpleNamespace:
        received.update(kwargs)
        return _image_response()

    client = _make_client(monkeypatch, generate_content)

    await client.generate_image("a cat", ImageStylePreset.NONE, "16:9")

    assert received["config"].image_config.aspect_ratio == "16:9"


async def test_generate_image_raises_policy_violation_on_blocked_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    async def generate_content(**_: Any) -> SimpleNamespace:
        return SimpleNamespace(
            prompt_feedback=genai_types.GenerateContentResponsePromptFeedback(
                block_reason=genai_types.BlockedReason.SAFETY
            ),
            candidates=None,
        )

    client = _make_client(monkeypatch, generate_content)

    with pytest.raises(LLMPolicyViolationError):
        await client.generate_image("a cat", ImageStylePreset.NONE, "1:1")


async def test_generate_image_raises_policy_violation_on_blocked_output(monkeypatch: pytest.MonkeyPatch) -> None:
    async def generate_content(**_: Any) -> SimpleNamespace:
        return SimpleNamespace(
            prompt_feedback=None,
            candidates=[genai_types.Candidate(finish_reason=genai_types.FinishReason.PROHIBITED_CONTENT)],
        )

    client = _make_client(monkeypatch, generate_content)

    with pytest.raises(LLMPolicyViolationError):
        await client.generate_image("a cat", ImageStylePreset.NONE, "1:1")


async def test_generate_image_raises_when_no_image_data(monkeypatch: pytest.MonkeyPatch) -> None:
    async def generate_content(**_: Any) -> SimpleNamespace:
        return SimpleNamespace(
            prompt_feedback=None,
            candidates=[
                genai_types.Candidate(
                    finish_reason=genai_types.FinishReason.STOP,
                    content=genai_types.Content(parts=[genai_types.Part(text="sorry, no image")]),
                )
            ],
        )

    client = _make_client(monkeypatch, generate_content)

    with pytest.raises(LLMClientError):
        await client.generate_image("a cat", ImageStylePreset.NONE, "1:1")


async def test_generate_image_wraps_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def generate_content(**_: Any) -> SimpleNamespace:
        raise _api_error()

    client = _make_client(monkeypatch, generate_content)

    with pytest.raises(LLMClientError):
        await client.generate_image("a cat", ImageStylePreset.NONE, "1:1")


async def test_generate_image_wraps_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def generate_content(**_: Any) -> SimpleNamespace:
        raise httpx.ConnectTimeout("timed out")

    client = _make_client(monkeypatch, generate_content)

    with pytest.raises(LLMClientError):
        await client.generate_image("a cat", ImageStylePreset.NONE, "1:1")
