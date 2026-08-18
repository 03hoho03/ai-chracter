import io

from PIL import Image

from api.assets.image_processing import generate_thumbnail


def _png_bytes(width: int, height: int) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), color=(120, 40, 200)).save(output, format="PNG")
    return output.getvalue()


def _open(thumbnail_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(thumbnail_bytes))


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
