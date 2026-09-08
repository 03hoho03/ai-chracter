import uuid

from api.core.s3 import build_object_key, build_thumbnail_key


def test_build_object_key_content_thumbnail_webp() -> None:
    asset_id = uuid.uuid4()
    key = build_object_key("content-thumbnail", asset_id, "image/webp")
    assert key == f"assets/content-thumbnail/{asset_id}.webp"


def test_build_object_key_falls_back_to_no_extension_for_unrecognized_content_type() -> None:
    """뮤테이션(8단계 T-13 #9): s3.py:31 의 `guess_extension(content_type) or ""` 가
    `or "XXXX"`로 바뀌어도 죽지 않았다 — `image/webp`만 테스트해 `guess_extension`이 None을
    내는 폴백 분기를 아무도 안 탔다.
    """
    asset_id = uuid.uuid4()
    key = build_object_key("content-thumbnail", asset_id, "application/x-totally-made-up-type")
    assert key == f"assets/content-thumbnail/{asset_id}"


def test_build_thumbnail_key_replaces_extension() -> None:
    key = build_thumbnail_key("assets/profile-image/abc.png")
    assert key == "assets/profile-image/abc_thumb.webp"


def test_build_thumbnail_key_without_extension() -> None:
    key = build_thumbnail_key("assets/profile-image/abc")
    assert key == "assets/profile-image/abc_thumb.webp"
