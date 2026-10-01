import io

import pytest
from PIL import Image

from api.assets.image_processing import (
    ReferenceImageRejectedError,
    generate_thumbnail,
    read_image_size,
    validate_reference_image,
)


def _png_bytes(width: int, height: int) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), color=(120, 40, 200)).save(output, format="PNG")
    return output.getvalue()


def _open(thumbnail_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(thumbnail_bytes))


def _rgb_color_key_transparent_png_bytes(width: int, height: int) -> bytes:
    """RGB 모드 + PNG tRNS 색상-키 투명(전체 알파 밴드는 없고 '이 색은 투명'이라는 정보만
    있다). 왼쪽 절반을 그 색으로 채운다."""
    transparent_color = (99, 99, 99)
    image = Image.new("RGB", (width, height), color=(10, 20, 30))
    image.paste(transparent_color, (0, 0, width // 2, height))
    image.info["transparency"] = transparent_color
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_generate_thumbnail_landscape_shrinks_long_edge_to_512() -> None:
    result = _open(generate_thumbnail(_png_bytes(1024, 768)))
    assert result.format == "WEBP"
    assert result.size == (512, 384)


def test_generate_thumbnail_portrait_shrinks_long_edge_to_512() -> None:
    result = _open(generate_thumbnail(_png_bytes(768, 1024)))
    assert result.format == "WEBP"
    assert result.size == (384, 512)


def test_generate_thumbnail_square_shrinks_to_512() -> None:
    result = _open(generate_thumbnail(_png_bytes(1024, 1024)))
    assert result.format == "WEBP"
    assert result.size == (512, 512)


def test_generate_thumbnail_small_source_is_not_upscaled() -> None:
    result = _open(generate_thumbnail(_png_bytes(300, 200)))
    assert result.format == "WEBP"
    assert result.size == (300, 200)


def test_generate_thumbnail_preserves_transparency_from_a_non_alpha_source() -> None:
    """뮤테이션: image_processing.py:48 의 `convert("RGBA")`가 `convert(None)`
    으로 바뀌어도 기존 4개 테스트가 안 죽었다 — 전부 불투명 `Image.new("RGB", ...)` 소스였다.

    계획서는 "실제 알파 채널이 있는 소스"를 쓰라고 했지만 실측해 보니 그걸로는 이 변형이 안
    갈린다 — 이미 RGBA/LA/P+alpha 모드인 소스는 Pillow 의 WebP 저장 코드
    (`WebPImagePlugin._convert_frame`)가 `has_transparency_data`를 보고 알아서 RGBA 로
    승격시켜서, 우리 쪽 `convert()` 호출과 무관하게 결과가 같아진다(Pillow 12.3.0 실측). 이
    변형이 실제로 갈리는 건 **RGB 모드 + PNG tRNS 색상-키 투명**(알파 밴드 없이 '이 색은
    투명'이라는 정보만 있는 소스)뿐이다 — `_convert_frame`은 "RGB"를 이미 지원 모드로 보고
    통과시키므로, 우리 쪽 `convert("RGBA")`가 그 색상-키를 실제 알파로 바꿔주지 않으면 투명
    정보가 통째로 사라진다.
    """
    result = _open(generate_thumbnail(_rgb_color_key_transparent_png_bytes(100, 100)))
    assert result.mode == "RGBA"
    transparent_pixel = result.getpixel((0, 0))
    opaque_pixel = result.getpixel((90, 0))
    assert isinstance(transparent_pixel, tuple)
    assert isinstance(opaque_pixel, tuple)
    assert transparent_pixel[3] == 0  # tRNS 로 지정한 색 영역은 완전 투명이어야 한다
    assert opaque_pixel[3] == 255  # 나머지는 불투명이어야 한다


# ---- 참조 이미지 검증 --------------------------------------------------------
# 집 PC 계약은 참조를 base64 8,000,000자 이하·각 변 64~4096px 로 받는다. 우리가 고를 수 있게
# 하는 참조는 이 서비스가 만든 이미지뿐이라 정상 경로에선 위반이 나오지 않지만, 검증이 빠지면
# 위반은 서버 400 으로만 드러나고 원인을 가를 수 없다. 경계 양쪽을 다 본다 — 한쪽만 보면
# 비교 연산자가 `<=` 에서 `<` 로 바뀌어도 못 잡는다.


def _encoded(width: int, height: int, image_format: str) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), color=(120, 40, 200)).save(output, format=image_format)
    return output.getvalue()


def _padded_png(total_bytes: int) -> bytes:
    """유효한 PNG 뒤에 0 을 덧대 전체 길이를 맞춘다. 검증은 헤더만 읽으므로 뒤쪽 바이트는
    길이 판정에만 쓰인다."""
    png = _png_bytes(64, 64)
    return png + b"\x00" * (total_bytes - len(png))


def _rejection(data: bytes) -> str | None:
    try:
        validate_reference_image(data)
    except ReferenceImageRejectedError as exc:
        return exc.reason
    return None


def test_reference_image_encoding_to_exactly_eight_million_chars_is_accepted() -> None:
    # 6,000,000 바이트는 base64 로 정확히 8,000,000자다.
    assert _rejection(_padded_png(6_000_000)) is None


def test_reference_image_encoding_past_eight_million_chars_is_too_large() -> None:
    assert _rejection(_padded_png(6_000_001)) == "too_large"


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        pytest.param(64, 64, None, id="smallest-edge"),
        pytest.param(4096, 4096, None, id="largest-edge"),
        pytest.param(63, 64, "resolution_out_of_range", id="width-below"),
        pytest.param(64, 63, "resolution_out_of_range", id="height-below"),
        pytest.param(4097, 64, "resolution_out_of_range", id="width-above"),
        pytest.param(64, 4097, "resolution_out_of_range", id="height-above"),
    ],
)
def test_reference_image_edges_must_be_between_64_and_4096(width: int, height: int, expected: str | None) -> None:
    assert _rejection(_encoded(width, height, "PNG")) == expected


@pytest.mark.parametrize("image_format", ["PNG", "JPEG", "WEBP"])
def test_reference_image_accepts_formats_earlier_generators_may_have_stored(image_format: str) -> None:
    """지금 생성기는 WebP 를 주지만 그 전 생성기가 남긴 생성 이미지도 참조로 고를 수 있다."""
    assert _rejection(_encoded(128, 128, image_format)) is None


def test_reference_image_rejects_formats_outside_the_contract() -> None:
    assert _rejection(_encoded(128, 128, "GIF")) == "unsupported_format"


def test_reference_image_rejects_bytes_that_are_not_an_image() -> None:
    assert _rejection(b"not an image at all") == "undecodable"


@pytest.mark.parametrize("image_format", ["PNG", "WEBP", "JPEG"])
def test_read_image_size_returns_width_then_height(image_format: str) -> None:
    assert read_image_size(_encoded(300, 200, image_format)) == (300, 200)


def test_read_image_size_rejects_bytes_that_are_not_an_image() -> None:
    with pytest.raises(OSError):
        read_image_size(b"not an image")
