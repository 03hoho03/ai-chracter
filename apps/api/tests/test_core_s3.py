import uuid

from api.core.s3 import build_object_key


def test_build_object_key_content_thumbnail_webp() -> None:
    asset_id = uuid.uuid4()
    key = build_object_key("content-thumbnail", asset_id, "image/webp")
    assert key == f"assets/content-thumbnail/{asset_id}.webp"
