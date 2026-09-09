import io

from PIL import Image

from api.assets.image_processing import generate_thumbnail


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
    """뮤테이션(8단계 T-13 #5): image_processing.py:48 의 `convert("RGBA")`가 `convert(None)`
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
