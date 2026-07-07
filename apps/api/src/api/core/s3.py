import mimetypes
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from api.core.config import settings

if TYPE_CHECKING:
    # boto3-stubs is a dev-only dependency (not installed in the prod image, see
    # pyproject.toml's [dependency-groups]) — this import must not happen at runtime.
    from mypy_boto3_s3 import S3Client

# moto/MinIO-style local endpoints need path-style addressing (no bucket subdomain);
# real S3 keeps its default virtual-hosted style.
_client_config = BotoConfig(s3={"addressing_style": "path"}) if settings.s3_endpoint_url else None

s3_client: "S3Client" = boto3.client(
    "s3",
    region_name=settings.aws_region,
    endpoint_url=settings.s3_endpoint_url,
    config=_client_config,
)


def build_object_key(purpose: str, asset_id: uuid.UUID, content_type: str) -> str:
    extension = mimetypes.guess_extension(content_type) or ""
    return f"assets/{purpose}/{asset_id}{extension}"


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


def object_exists(key: str) -> bool:
    """Blocking network call — run via `starlette.concurrency.run_in_threadpool`."""
    try:
        s3_client.head_object(Bucket=settings.s3_bucket_name, Key=key)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")
        if error_code in ("404", "NoSuchKey"):
            return False
        raise
    return True
