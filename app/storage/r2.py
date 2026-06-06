"""Cloudflare R2 (S3-compatible) storage for WhatsApp media."""

from __future__ import annotations

import logging
import mimetypes
from functools import lru_cache

import boto3
from botocore.client import BaseClient

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

_MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/heic": ".heic",
    "image/heif": ".heif",
}


def extension_for_mime(mime_type: str) -> str:
    normalized = (mime_type or "").split(";", 1)[0].strip().lower()
    if normalized in _MIME_EXTENSIONS:
        return _MIME_EXTENSIONS[normalized]
    guessed = mimetypes.guess_extension(normalized)
    return guessed or ".bin"


class R2Storage:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client: BaseClient | None = None

    def is_configured(self) -> bool:
        return bool(
            self._settings.r2_account_id
            and self._settings.r2_access_key_id
            and self._settings.r2_secret_access_key
            and self._settings.r2_bucket_name
            and self._settings.r2_public_url_base
        )

    def _get_client(self) -> BaseClient:
        if self._client is None:
            endpoint = (
                self._settings.r2_endpoint_url
                or f"https://{self._settings.r2_account_id}.r2.cloudflarestorage.com"
            )
            self._client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=self._settings.r2_access_key_id,
                aws_secret_access_key=self._settings.r2_secret_access_key,
                region_name=self._settings.r2_region,
            )
        return self._client

    def build_object_key(
        self, *, whatsapp_user_id: str, whatsapp_message_id: str, mime_type: str
    ) -> str:
        prefix = self._settings.r2_key_prefix.strip("/")
        ext = extension_for_mime(mime_type)
        parts = [prefix] if prefix else []
        parts.extend([whatsapp_user_id, f"{whatsapp_message_id}{ext}"])
        return "/".join(parts)

    def public_url_for_key(self, key: str) -> str:
        base = self._settings.r2_public_url_base.rstrip("/")
        return f"{base}/{key.lstrip('/')}"

    def upload_image(
        self,
        *,
        whatsapp_user_id: str,
        whatsapp_message_id: str,
        data: bytes,
        mime_type: str,
    ) -> tuple[str, str]:
        if not self.is_configured():
            raise RuntimeError("R2 storage is not configured")

        key = self.build_object_key(
            whatsapp_user_id=whatsapp_user_id,
            whatsapp_message_id=whatsapp_message_id,
            mime_type=mime_type,
        )
        content_type = (mime_type or "image/jpeg").split(";", 1)[0].strip()
        client = self._get_client()
        client.put_object(
            Bucket=self._settings.r2_bucket_name,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        url = self.public_url_for_key(key)
        logger.info(
            "R2 upload ok key=%s bytes=%d mime=%s",
            key,
            len(data),
            content_type,
        )
        return key, url


@lru_cache
def get_r2_storage() -> R2Storage:
    return R2Storage(get_settings())
