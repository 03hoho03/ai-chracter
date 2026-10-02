import hashlib
import hmac
import mimetypes
import posixpath
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import quote, urlsplit

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError, NoCredentialsError

from api.core.config import settings

if TYPE_CHECKING:
    # boto3-stubs is a dev-only dependency (not installed in the prod image, see
    # pyproject.toml's [dependency-groups]) — this import must not happen at runtime.
    from mypy_boto3_s3 import S3Client

# Every environment sets an endpoint (Cloudflare R2 in production, moto in dev and
# tests) and addresses it path-style, `{endpoint}/{bucket}/{key}` with no bucket
# subdomain. `generate_presigned_get_url` builds exactly that URL shape itself and
# refuses to run without an endpoint.
_client_config = BotoConfig(s3={"addressing_style": "path"}) if settings.s3_endpoint_url else None

# An explicit session rather than `boto3.client(...)`, so the stable GET signer can
# read the same credentials this client signs with through public API.
_session = boto3.session.Session()

s3_client: "S3Client" = _session.client(
    "s3",
    region_name=settings.aws_region,
    endpoint_url=settings.s3_endpoint_url,
    config=_client_config,
)


def build_object_key(purpose: str, asset_id: uuid.UUID, content_type: str) -> str:
    extension = mimetypes.guess_extension(content_type) or ""
    return f"assets/{purpose}/{asset_id}{extension}"


def build_upload_key(storage_key: str) -> str:
    """`assets/profile-image/abc.png` -> `uploads/tmp/profile-image/abc.png`.

    The browser PUTs to this temporary key, never to the stored key: the upload URL
    stays valid for minutes after the upload is completed, and if it pointed at the
    stored key it could overwrite an image after it had been checked. The prefix sits
    apart from `assets/` and `backup/` so a bucket lifecycle rule can expire leftovers
    under it without touching anything else.
    """
    return f"uploads/tmp/{storage_key.removeprefix('assets/')}"


def build_thumbnail_key(storage_key: str) -> str:
    """`assets/profile-image/abc.png` -> `assets/profile-image/abc_thumb.webp`."""
    base, _extension = posixpath.splitext(storage_key)
    return f"{base}_thumb.webp"


def generate_presigned_put_url(key: str, content_type: str) -> tuple[str, datetime]:
    """Local signing only, no network call — safe to call from an async context directly."""
    expires_in = settings.s3_presigned_url_expires_seconds
    url = s3_client.generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.s3_bucket_name, "Key": key, "ContentType": content_type},
        ExpiresIn=expires_in,
    )
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
    return url, expires_at


def _utcnow() -> datetime:
    return datetime.now(UTC)


def build_windowed_presigned_get_url(
    key: str,
    now: datetime,
    *,
    endpoint_url: str,
    region: str,
    bucket: str,
    access_key: str,
    secret_key: str,
    session_token: str | None,
    window_seconds: int,
) -> str:
    """SigV4 query-string presigned GET for a path-style endpoint, signed at the start
    of the `window_seconds`-long UTC window containing `now` (timezone-aware) and
    valid for twice that length.

    Every call inside one window returns the same URL for the same key. Browsers
    cache images by URL, so a list refetch that hands back the same URLs keeps the
    images on screen instead of re-downloading every one of them, which showed as
    cards flashing empty. Since the signature dates from the window start, a URL
    received at any moment has more than `window_seconds` and at most
    `2 * window_seconds` of validity left: the minimum equals what a freshly signed
    `window_seconds` URL used to guarantee, and a leaked URL lives at most twice that.

    The result is byte-for-byte what botocore's `generate_presigned_url("get_object")`
    produces for the same signing time. botocore has no public way to choose that
    time, which is why the signature is computed here.
    """
    window_start = int(now.timestamp()) // window_seconds * window_seconds
    amz_date = datetime.fromtimestamp(window_start, UTC).strftime("%Y%m%dT%H%M%SZ")
    scope = f"{amz_date[:8]}/{region}/s3/aws4_request"

    endpoint = urlsplit(endpoint_url)
    # The signed Host is lowercase without a default port; the URL keeps the
    # endpoint's netloc as written.
    host = endpoint.hostname or ""
    if endpoint.port is not None and endpoint.port != {"http": 80, "https": 443}.get(endpoint.scheme):
        host = f"{host}:{endpoint.port}"
    # An endpoint path prefix (the dev endpoint is `https://<host>/s3`) stays in front
    # of the bucket, with or without a trailing slash.
    path = f"{endpoint.path.rstrip('/')}/{quote(bucket, safe='-._~')}/{quote(key, safe='/~')}"

    params = [
        ("X-Amz-Algorithm", "AWS4-HMAC-SHA256"),
        ("X-Amz-Credential", f"{access_key}/{scope}"),
        ("X-Amz-Date", amz_date),
        ("X-Amz-Expires", str(2 * window_seconds)),
        ("X-Amz-SignedHeaders", "host"),
    ]
    if session_token is not None:
        params.append(("X-Amz-Security-Token", session_token))
    encoded = [f"{name}={quote(value, safe='-._~')}" for name, value in params]

    canonical_request = "\n".join(
        ["GET", path, "&".join(sorted(encoded)), f"host:{host}\n", "host", "UNSIGNED-PAYLOAD"]
    )
    string_to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical_request.encode()).hexdigest()]
    )
    signing_key = f"AWS4{secret_key}".encode()
    for part in (amz_date[:8], region, "s3", "aws4_request"):
        signing_key = hmac.new(signing_key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()

    # The URL keeps the parameters in the order above with the signature last.
    query = "&".join([*encoded, f"X-Amz-Signature={signature}"])
    return f"{endpoint.scheme}://{endpoint.netloc}{path}?{query}"


def generate_presigned_get_url(key: str) -> str:
    """Local signing only, no network call — safe to call from an async context directly.

    The URL stays the same for every request within each
    `s3_presigned_url_expires_seconds` window and is valid for twice that long; see
    `build_windowed_presigned_get_url` for why.
    """
    if settings.s3_endpoint_url is None:
        raise RuntimeError("S3_ENDPOINT_URL must be set to sign path-style GET URLs")
    credentials = _session.get_credentials()
    if credentials is None:
        raise NoCredentialsError()
    frozen = credentials.get_frozen_credentials()
    if frozen.access_key is None or frozen.secret_key is None:
        raise NoCredentialsError()
    return build_windowed_presigned_get_url(
        key,
        _utcnow(),
        endpoint_url=settings.s3_endpoint_url,
        region=settings.aws_region,
        bucket=settings.s3_bucket_name,
        access_key=frozen.access_key,
        secret_key=frozen.secret_key,
        session_token=frozen.token,
        window_seconds=settings.s3_presigned_url_expires_seconds,
    )


def generate_per_request_presigned_get_url(key: str) -> str:
    """Signed afresh on every call and valid for `s3_presigned_url_expires_seconds`
    from now — for objects that should not stay reachable any longer than that.

    Local signing only, no network call — safe to call from an async context directly.
    """
    url: str = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket_name, "Key": key},
        ExpiresIn=settings.s3_presigned_url_expires_seconds,
    )
    return url


def download_object(key: str) -> bytes:
    """Blocking network call — run via `starlette.concurrency.run_in_threadpool`."""
    response = s3_client.get_object(Bucket=settings.s3_bucket_name, Key=key)
    return response["Body"].read()


def upload_object(key: str, body: bytes, content_type: str) -> None:
    """Blocking network call — run via `starlette.concurrency.run_in_threadpool`."""
    s3_client.put_object(Bucket=settings.s3_bucket_name, Key=key, Body=body, ContentType=content_type)


def delete_object(key: str) -> None:
    """Blocking network call — run via `starlette.concurrency.run_in_threadpool`."""
    s3_client.delete_object(Bucket=settings.s3_bucket_name, Key=key)


def get_object_size(key: str) -> int | None:
    """Blocking network call — run via `starlette.concurrency.run_in_threadpool`.

    Returns the object's size in bytes, or None if it does not exist — one
    head_object serves both the existence check and the size check.
    """
    try:
        response = s3_client.head_object(Bucket=settings.s3_bucket_name, Key=key)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")
        if error_code in ("404", "NoSuchKey"):
            return None
        raise
    return response["ContentLength"]
