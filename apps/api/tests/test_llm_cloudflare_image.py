import base64
import io
import json
from collections.abc import Callable

import httpx
import pytest
from PIL import Image

from api.llm.client import LLMClientError
from api.llm.cloudflare_image import CloudflareImageClient
from api.llm.image import ImageStylePreset

_FLUX = "@cf/black-forest-labs/flux-1-schnell"
_SDXL = "@cf/stabilityai/stable-diffusion-xl-base-1.0"


def _patch_httpx(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    """cloudflare_image가 만드는 httpx.AsyncClient에 MockTransport를 주입한다."""
    real_client = httpx.AsyncClient

    def factory(**kwargs: object) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("api.llm.cloudflare_image.httpx.AsyncClient", factory)


def _client(cf_model: str, *, send_dimensions: bool) -> CloudflareImageClient:
    return CloudflareImageClient(
        cf_model, send_dimensions=send_dimensions, account_id="acc", api_token="tok"
    )


async def test_flux_decodes_base64_json_to_jpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {"image": base64.b64encode(b"flux-bytes").decode()}})

    _patch_httpx(monkeypatch, handler)
    data, mime = await _client(_FLUX, send_dimensions=False).generate_image(
        "a cat", ImageStylePreset.ANIME, "1:1"
    )
    assert data == b"flux-bytes"
    assert mime == "image/jpeg"


async def test_sdxl_returns_binary_and_sends_dimensions(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"sdxl-png", headers={"content-type": "image/png"})

    _patch_httpx(monkeypatch, handler)
    data, mime = await _client(_SDXL, send_dimensions=True).generate_image(
        "a cat", ImageStylePreset.NONE, "16:9"
    )
    assert data == b"sdxl-png"
    assert mime == "image/png"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["width"] == 1024
    assert body["height"] == 576


async def test_flux_omits_dimensions(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"result": {"image": base64.b64encode(b"x").decode()}})

    _patch_httpx(monkeypatch, handler)
    await _client(_FLUX, send_dimensions=False).generate_image("a cat", ImageStylePreset.NONE, "1:1")
    body = captured["body"]
    assert isinstance(body, dict)
    assert "width" not in body and "height" not in body


async def test_http_error_maps_to_llm_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"errors": [{"message": "quota exceeded"}]})

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError):
        await _client(_FLUX, send_dimensions=False).generate_image("a cat", ImageStylePreset.ANIME, "1:1")


async def test_empty_json_image_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {}})

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError):
        await _client(_FLUX, send_dimensions=False).generate_image("a cat", ImageStylePreset.ANIME, "1:1")


def _solid_color_png(color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, format="PNG")
    return buffer.getvalue()


async def test_blank_solid_color_image_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cloudflare's safety filter swaps flagged output for a solid-color image instead
    of erroring — this must surface as a failure, not a "successful" empty result."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_solid_color_png((0, 0, 0)), headers={"content-type": "image/png"})

    _patch_httpx(monkeypatch, handler)
    with pytest.raises(LLMClientError):
        await _client(_SDXL, send_dimensions=True).generate_image("a cat", ImageStylePreset.ANIME, "1:1")


async def test_non_blank_image_with_few_colors_is_not_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guard against an overly aggressive blank check: an image with a couple of flat
    colors (not literally solid) must still pass through."""

    def handler(_request: httpx.Request) -> httpx.Response:
        image = Image.new("RGB", (8, 8), (0, 0, 0))
        for x in range(4):
            for y in range(8):
                image.putpixel((x, y), (255, 255, 255))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return httpx.Response(200, content=buffer.getvalue(), headers={"content-type": "image/png"})

    _patch_httpx(monkeypatch, handler)
    data, mime = await _client(_SDXL, send_dimensions=True).generate_image(
        "a cat", ImageStylePreset.ANIME, "1:1"
    )
    assert mime == "image/png"
    assert len(data) > 0
