import asyncio
import io
import threading
import time
from collections.abc import Callable, Sequence

import pytest
from PIL import Image

from api.assets import image_processing
from api.assets.image_processing import (
    IMAGE_WORK_CONCURRENCY,
    ImageTooLargeError,
    ReferenceImageRejectedError,
    generate_blurred_image,
    generate_display_image,
    generate_thumbnail,
    generate_variants,
    read_frame_count,
    read_image_size,
    run_image_work,
    validate_reference_image,
)
from api.core.s3 import build_display_key, build_frame_sheet_key, build_thumbnail_key, build_variant_keys


def _png_bytes(width: int, height: int) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), color=(120, 40, 200)).save(output, format="PNG")
    return output.getvalue()


def _gif_bytes(colors: list[tuple[int, int, int]], size: tuple[int, int] = (64, 48)) -> bytes:
    """프레임마다 단색인 움직이는 GIF. 색이 프레임 번호를 대신해, 프레임 모음의 칸 색으로 어느 프레임이 실렸는지 가린다."""
    frames = [Image.new("RGB", size, color=color) for color in colors]
    output = io.BytesIO()
    frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
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


def test_generate_display_image_landscape_shrinks_long_edge_to_1024() -> None:
    result = _open(generate_display_image(_png_bytes(2048, 1536)))
    assert result.format == "WEBP"
    assert result.size == (1024, 768)


def test_generate_display_image_portrait_shrinks_long_edge_to_1024() -> None:
    result = _open(generate_display_image(_png_bytes(1536, 2048)))
    assert result.format == "WEBP"
    assert result.size == (768, 1024)


def test_generate_display_image_source_between_both_edges_is_not_upscaled() -> None:
    """썸네일 한도(512)보다 크고 표시용 한도(1024)보다 작은 원본 — 표시용 변형은 원본 크기 그대로여야 한다.
    512 와 1024 사이를 고른 것은 한도를 썸네일 값으로 잘못 쓰면 여기서 줄어들어 갈리기 때문이다."""
    result = _open(generate_display_image(_png_bytes(800, 600)))
    assert result.format == "WEBP"
    assert result.size == (800, 600)


def test_generate_variants_produces_every_variant_key_with_its_own_size() -> None:
    """만드는 변형의 키가 전부 지우는 키 목록(`build_variant_keys`)에 있어야 한다 — 빠지면 만든 사본이 자산 삭제·
    탈퇴 파기에서 남는다. 정지 그림에는 프레임 모음이 없다."""
    storage_key = "assets/generated/abc.png"
    variants = generate_variants(storage_key, _png_bytes(2048, 1536))

    assert [key for key, _ in variants] == [build_thumbnail_key(storage_key), build_display_key(storage_key)]
    assert {key for key, _ in variants} <= set(build_variant_keys(storage_key))
    sizes = {key: _open(body).size for key, body in variants}
    assert sizes == {
        "assets/generated/abc_thumb.webp": (512, 384),
        "assets/generated/abc_display.webp": (1024, 768),
    }
    assert all(_open(body).format == "WEBP" for _, body in variants)


def test_generate_variants_adds_a_frame_sheet_for_an_animated_gif() -> None:
    """움직이는 그림은 썸네일·표시용(첫 프레임) 곁에 프레임 모음을 하나 더 만든다. 발행 심사가 첫 프레임만 보면 뒤
    프레임에만 있는 장면이 심사를 지나가므로, 심사는 프레임을 고르게 뽑아 한 장에 붙인 이것을 본다."""
    storage_key = "assets/situational-image/abc.gif"
    variants = dict(generate_variants(storage_key, _gif_bytes([(255, 0, 0), (0, 255, 0), (0, 0, 255)])))

    assert list(variants) == list(build_variant_keys(storage_key))
    thumbnail = _open(variants[build_thumbnail_key(storage_key)]).convert("RGB")
    assert _is_close(thumbnail.getpixel((32, 24)), (255, 0, 0))
    sheet = _open(variants[build_frame_sheet_key(storage_key)])
    assert sheet.format == "WEBP"
    # 3장은 2열 격자다: 왼쪽 위·오른쪽 위·왼쪽 아래.
    _assert_tiles(sheet, columns=2, rows=2, expected=[(255, 0, 0), (0, 255, 0), (0, 0, 255), None])


def test_frame_sheet_samples_nine_frames_evenly_from_first_to_last() -> None:
    """프레임이 9장을 넘으면 처음과 마지막을 포함해 고르게 9장을 뽑는다 — 끝 장면만 다른 움짤도 심사에 실린다."""
    colors = [(index * 12, 255 - index * 12, (index * 40) % 256) for index in range(20)]
    sheet = _open(dict(generate_variants("a.gif", _gif_bytes(colors)))[build_frame_sheet_key("a.gif")])

    expected = [colors[round(slot * 19 / 8)] for slot in range(9)]
    _assert_tiles(sheet, columns=3, rows=3, expected=expected)


def test_frame_sheet_fits_a_1024_long_edge_and_keeps_the_frame_aspect() -> None:
    """900×1200 프레임 9장은 3×3 격자에서 칸이 256×341(비율 3:4, 세 칸 높이가 1024 를 넘지 않게 반올림)이다."""
    colors = [(index * 20, 0, 0) for index in range(9)]
    variants = dict(generate_variants("a.gif", _gif_bytes(colors, size=(900, 1200))))
    sheet = _open(variants[build_frame_sheet_key("a.gif")])

    assert sheet.size == (3 * 256, 3 * 341)


def test_read_frame_count_counts_animation_frames_and_treats_still_images_as_one() -> None:
    assert read_frame_count(_gif_bytes([(0, 0, 0), (9, 9, 9), (99, 99, 99)])) == 3
    assert read_frame_count(_png_bytes(10, 10)) == 1


def test_animated_image_over_the_total_pixel_limit_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """프레임 하나는 작아도 프레임 수만큼 풀어야 한다. 5MB 안에서도 단색 프레임은 수천 장이 들어가므로, 프레임 수 ×
    프레임 픽셀에 상한을 둔다."""
    data = _gif_bytes([(0, 0, 0), (9, 9, 9), (99, 99, 99)], size=(40, 30))
    monkeypatch.setattr(image_processing, "MAX_ANIMATED_DECODE_PIXELS", 3 * 40 * 30 - 1)

    with pytest.raises(ImageTooLargeError) as raised:
        generate_variants("a.gif", data)

    assert raised.value.actual_pixels == 3 * 40 * 30
    assert raised.value.max_pixels == 3 * 40 * 30 - 1


def _is_close(actual: object, expected: tuple[int, int, int], tolerance: int = 24) -> bool:
    assert isinstance(actual, tuple)
    return all(abs(int(a) - b) <= tolerance for a, b in zip(actual, expected, strict=False))


def _assert_tiles(
    sheet: Image.Image, *, columns: int, rows: int, expected: Sequence[tuple[int, int, int] | None]
) -> None:
    """격자 칸마다 가운데 색을 본다. `None` 은 빈 칸(투명)이다. WebP 손실 압축 오차만큼은 허용한다."""
    rgba = sheet.convert("RGBA")
    tile_width, tile_height = rgba.width // columns, rgba.height // rows
    for index, color in enumerate(expected):
        row, column = divmod(index, columns)
        pixel = rgba.getpixel((column * tile_width + tile_width // 2, row * tile_height + tile_height // 2))
        assert isinstance(pixel, tuple)
        if color is None:
            assert pixel[3] == 0, f"칸 {index} 는 비어 있어야 한다: {pixel}"
        else:
            assert pixel[3] == 255 and _is_close(pixel[:3], color), f"칸 {index}: {pixel} != {color}"


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


def _bilevel_png_bytes(width: int, height: int) -> bytes:
    """1비트 단색 PNG — 픽셀은 많고 바이트는 작다(화면을 거치지 않고 올린 큰 그림을 흉내 낸다)."""
    output = io.BytesIO()
    Image.new("1", (width, height)).save(output, format="PNG")
    return output.getvalue()


_DECODERS: list[Callable[[bytes], bytes]] = [generate_thumbnail, generate_display_image, generate_blurred_image]


@pytest.mark.parametrize("decode", _DECODERS, ids=lambda decode: decode.__name__)
def test_decoders_reject_images_over_the_pixel_limit_before_decoding(
    decode: Callable[[bytes], bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    """상한을 넘는 그림은 픽셀을 풀기 전에 거부한다 — 풀고 나서 거부하면 메모리는 이미 쓴 뒤다."""
    monkeypatch.setattr(image_processing, "MAX_DECODE_PIXELS", 40 * 30 - 1)
    # 만드는 쪽(`save`)도 픽셀을 풀므로 감시를 걸기 전에 만든다.
    data = _bilevel_png_bytes(40, 30)
    loads: list[object] = []
    real_load = Image.Image.load

    def counting_load(self: Image.Image) -> object:
        loads.append(self)
        return real_load(self)

    monkeypatch.setattr(Image.Image, "load", counting_load)

    with pytest.raises(ImageTooLargeError) as raised:
        decode(data)

    assert raised.value.actual_pixels == 40 * 30
    assert loads == []


@pytest.mark.parametrize("decode", _DECODERS, ids=lambda decode: decode.__name__)
def test_decoders_accept_images_exactly_at_the_pixel_limit(
    decode: Callable[[bytes], bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(image_processing, "MAX_DECODE_PIXELS", 40 * 30)

    assert decode(_bilevel_png_bytes(40, 30))


def test_default_pixel_limit_rejects_a_small_file_with_many_pixels() -> None:
    """기본 상한(9M)에서 3001×3000 은 거부되고, 파일은 바이트 상한(수 MB)보다 훨씬 작다."""
    data = _bilevel_png_bytes(3001, 3000)
    assert len(data) < 100_000

    with pytest.raises(ImageTooLargeError) as raised:
        generate_thumbnail(data)

    assert raised.value.actual_pixels == 3001 * 3000


def test_pillow_decompression_bomb_becomes_the_same_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pillow 가 스스로 거부하는 폭탄은 `OSError`·`ValueError` 가 아니라서 호출자의 except 를 빠져나간다 — 같은
    오류로 바꿔야 업로드 완료가 정리 후 400 을 낸다."""
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    data = _bilevel_png_bytes(20, 20)

    with pytest.raises(ImageTooLargeError) as raised:
        generate_thumbnail(data)

    assert raised.value.actual_pixels is None
    assert isinstance(raised.value, ValueError)


async def test_run_image_work_caps_concurrency_and_finishes_every_job() -> None:
    """이미지 작업은 동시에 한도까지만 돌고, 한도보다 많이 몰려도 전부 끝난다(기다리는 쪽이 스레드를 잡지 않아
    교착이 없다)."""
    lock = threading.Lock()
    counts = {"running": 0, "peak": 0}

    def job(index: int) -> int:
        with lock:
            counts["running"] += 1
            counts["peak"] = max(counts["peak"], counts["running"])
        try:
            time.sleep(0.05)
            return index
        finally:
            with lock:
                counts["running"] -= 1

    results = await asyncio.wait_for(asyncio.gather(*(run_image_work(job, index) for index in range(8))), timeout=5)

    assert results == list(range(8))
    assert counts["peak"] == IMAGE_WORK_CONCURRENCY
