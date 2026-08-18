import uuid

from api.core.s3 import build_object_key, build_thumbnail_key


def test_build_object_key_content_thumbnail_webp() -> None:
    asset_id = uuid.uuid4()
    key = build_object_key("content-thumbnail", asset_id, "image/webp")
    assert key == f"assets/content-thumbnail/{asset_id}.webp"


def test_build_thumbnail_key_replaces_extension() -> None:
    key = build_thumbnail_key("assets/profile-image/abc.png")
    assert key == "assets/profile-image/abc_thumb.webp"


def test_build_thumbnail_key_without_extension() -> None:
    key = build_thumbnail_key("assets/profile-image/abc")
    assert key == "assets/profile-image/abc_thumb.webp"
