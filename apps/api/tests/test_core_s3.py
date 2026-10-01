import functools
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, parse_qsl, urlsplit

import boto3
import botocore.auth
import pytest
from botocore.client import Config as BotoConfig

from api.core import s3
from api.core.config import settings
from api.core.s3 import build_object_key, build_thumbnail_key, build_windowed_presigned_get_url

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

_WINDOW = 900
_ACCESS_KEY = "AKIDEXAMPLE"
_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
_BUCKET = "ai-chracter-chat"


def test_build_object_key_content_thumbnail_webp() -> None:
    asset_id = uuid.uuid4()
    key = build_object_key("content-thumbnail", asset_id, "image/webp")
    assert key == f"assets/content-thumbnail/{asset_id}.webp"


def test_build_object_key_falls_back_to_no_extension_for_unrecognized_content_type() -> None:
    """뮤테이션: `build_object_key` 의 `guess_extension(content_type) or ""` 가
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


def _sign(
    key: str,
    now: datetime,
    *,
    endpoint_url: str = "http://127.0.0.1:5001",
    region: str = "auto",
    session_token: str | None = None,
) -> str:
    return build_windowed_presigned_get_url(
        key,
        now,
        endpoint_url=endpoint_url,
        region=region,
        bucket=_BUCKET,
        access_key=_ACCESS_KEY,
        secret_key=_SECRET_KEY,
        session_token=session_token,
        window_seconds=_WINDOW,
    )


@functools.cache
def _botocore_client(endpoint_url: str, region: str, session_token: str | None) -> "S3Client":
    # 명시적 자격증명이라 conftest 가 넣은 env 와 무관하게 같은 키로 서명한다.
    session = boto3.session.Session(
        aws_access_key_id=_ACCESS_KEY,
        aws_secret_access_key=_SECRET_KEY,
        aws_session_token=session_token,
    )
    return session.client(
        "s3",
        region_name=region,
        endpoint_url=endpoint_url,
        config=BotoConfig(s3={"addressing_style": "path"}),
    )


def _freeze_botocore_clock(monkeypatch: pytest.MonkeyPatch, at: datetime) -> None:
    def fixed(remove_tzinfo: bool = True) -> datetime:
        return at.replace(tzinfo=None) if remove_tzinfo else at

    monkeypatch.setattr(botocore.auth, "get_current_datetime", fixed)


def _signed_at_and_expires(url: str) -> tuple[datetime, int]:
    query = parse_qs(urlsplit(url).query)
    signed_at = datetime.strptime(query["X-Amz-Date"][0], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    return signed_at, int(query["X-Amz-Expires"][0])


@pytest.mark.parametrize(
    "key",
    [
        pytest.param("assets/content-thumbnail/0b6f.png", id="plain"),
        pytest.param("assets/content-thumbnail/0b6f_thumb.webp", id="thumb"),
        pytest.param("assets/x/a b+한글~!*'()=&.png", id="special-chars"),
    ],
)
@pytest.mark.parametrize(
    ("now", "window_start"),
    [
        pytest.param(datetime(2026, 10, 1, 10, 7, 30, tzinfo=UTC), datetime(2026, 10, 1, 10, 0, tzinfo=UTC), id="mid"),
        pytest.param(
            datetime(2026, 10, 1, 10, 14, 59, tzinfo=UTC), datetime(2026, 10, 1, 10, 0, tzinfo=UTC), id="before-edge"
        ),
        pytest.param(
            datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC), datetime(2026, 9, 30, 23, 45, tzinfo=UTC), id="pre-midnight"
        ),
    ],
)
@pytest.mark.parametrize(
    "endpoint_url",
    [
        pytest.param("http://127.0.0.1:5001", id="port"),
        pytest.param("https://host.example.com/s3", id="path-prefix"),
        pytest.param("https://host.example.com/s3/", id="path-prefix-slash"),
        pytest.param("https://Host.Example.com:443", id="default-port-mixed-case"),
    ],
)
@pytest.mark.parametrize("region", ["auto", "ap-northeast-2"])
@pytest.mark.parametrize("session_token", [None, "FwoGZXIvYXdzEXAMPLE/token+="], ids=["no-token", "token"])
def test_windowed_presigned_get_url_matches_botocore_signed_at_window_start(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    now: datetime,
    window_start: datetime,
    endpoint_url: str,
    region: str,
    session_token: str | None,
) -> None:
    """moto 는 서명을 검증하지 않으므로 서명 정확성의 유일한 증명은 botocore 와의 대조다.
    botocore 의 서명 시각을 구간 시작으로 고정하고 만료를 구간의 2배로 주면 URL 이 글자까지 같아야 한다.
    """
    _freeze_botocore_clock(monkeypatch, window_start)
    expected = _botocore_client(endpoint_url, region, session_token).generate_presigned_url(
        "get_object", Params={"Bucket": _BUCKET, "Key": key}, ExpiresIn=2 * _WINDOW
    )

    actual = _sign(key, now, endpoint_url=endpoint_url, region=region, session_token=session_token)

    actual_parts, expected_parts = urlsplit(actual), urlsplit(expected)
    assert actual_parts[:3] == expected_parts[:3]  # scheme, netloc, path
    # 순서까지 포함한 (이름, 값) 목록 — 서명값과 파라미터 순서를 함께 본다.
    assert parse_qsl(actual_parts.query) == parse_qsl(expected_parts.query)
    assert actual == expected


def test_windowed_presigned_get_url_is_identical_within_one_window() -> None:
    key = "assets/content-thumbnail/0b6f_thumb.webp"
    first = _sign(key, datetime(2026, 10, 1, 10, 0, 1, tzinfo=UTC))
    last = _sign(key, datetime(2026, 10, 1, 10, 14, 59, tzinfo=UTC))
    assert first == last


def test_windowed_presigned_get_url_changes_at_window_boundary() -> None:
    key = "assets/content-thumbnail/0b6f_thumb.webp"
    boundary = datetime(2026, 10, 1, 10, 15, tzinfo=UTC)
    assert _sign(key, boundary - timedelta(seconds=1)) != _sign(key, boundary)


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 10, 1, 10, 0, tzinfo=UTC),
        datetime(2026, 10, 1, 10, 0, 1, tzinfo=UTC),
        datetime(2026, 10, 1, 10, 7, 30, tzinfo=UTC),
        datetime(2026, 10, 1, 10, 14, 59, tzinfo=UTC),
        datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC),
    ],
)
def test_windowed_presigned_get_url_remaining_validity_is_between_one_and_two_windows(now: datetime) -> None:
    """받은 시점부터 남은 유효시간이 한 구간(15분) 초과, 두 구간(30분) 이하여야 한다 — 하한은 요청마다
    새로 서명하던 시절의 보장과 같다.
    """
    signed_at, expires = _signed_at_and_expires(_sign("assets/a.png", now))
    remaining = (signed_at + timedelta(seconds=expires) - now).total_seconds()
    assert _WINDOW < remaining <= 2 * _WINDOW


def test_generate_presigned_get_url_is_stable_within_a_window_of_the_configured_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = settings.s3_presigned_url_expires_seconds
    start = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    monkeypatch.setattr(s3, "_utcnow", lambda: start + timedelta(seconds=1))
    first = s3.generate_presigned_get_url("assets/a.png")
    monkeypatch.setattr(s3, "_utcnow", lambda: start + timedelta(seconds=window - 1))
    last = s3.generate_presigned_get_url("assets/a.png")

    assert first == last
    assert _signed_at_and_expires(first) == (start, 2 * window)


def test_generate_presigned_get_url_requires_an_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "s3_endpoint_url", None)
    with pytest.raises(RuntimeError, match="S3_ENDPOINT_URL"):
        s3.generate_presigned_get_url("assets/a.png")


def test_generate_per_request_presigned_get_url_signs_fresh_each_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """문의 첨부처럼 노출을 늘리지 않을 곳은 요청마다 새로 서명하고 설정값 그대로 만료된다."""
    at = datetime(2026, 10, 1, 10, 0, 1, tzinfo=UTC)
    _freeze_botocore_clock(monkeypatch, at)
    first = s3.generate_per_request_presigned_get_url("assets/a.png")
    _freeze_botocore_clock(monkeypatch, at + timedelta(seconds=1))
    second = s3.generate_per_request_presigned_get_url("assets/a.png")

    assert first != second
    assert _signed_at_and_expires(first) == (at, settings.s3_presigned_url_expires_seconds)
