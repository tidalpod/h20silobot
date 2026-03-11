"""Cloudflare R2 / local filesystem storage abstraction.

When R2 credentials are configured, files are uploaded to R2 and full public
URLs are returned.  When not configured (or on upload failure), files are
written to the local filesystem under UPLOAD_PATH and a /uploads/... path is
returned — fully backwards-compatible with the existing StaticFiles mount.
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from webapp.config import web_config

logger = logging.getLogger(__name__)

# Local upload base — same logic used everywhere else in the codebase
UPLOAD_BASE = os.environ.get("UPLOAD_PATH") or (
    "/app/uploads" if Path("/app/uploads").exists()
    else str(Path(__file__).resolve().parent.parent / "static" / "uploads")
)


class StorageService:
    """Thin wrapper around R2 (via boto3 S3 client) with local fallback."""

    def __init__(self):
        self._s3 = None
        self._bucket: str = ""
        self._public_url: str = ""
        self._upload_base = Path(UPLOAD_BASE)

        if web_config.has_r2:
            try:
                import boto3
                self._s3 = boto3.client(
                    "s3",
                    endpoint_url=f"https://{web_config.r2_account_id}.r2.cloudflarestorage.com",
                    aws_access_key_id=web_config.r2_access_key_id,
                    aws_secret_access_key=web_config.r2_access_key_secret,
                    region_name="auto",
                )
                self._bucket = web_config.r2_bucket_name
                self._public_url = web_config.r2_public_url.rstrip("/")
                logger.info(f"[STORAGE] R2 configured: bucket={self._bucket}, url={self._public_url}")
            except Exception as e:
                logger.error(f"[STORAGE] Failed to initialize R2 client: {e}")
                self._s3 = None
        else:
            logger.info("[STORAGE] R2 not configured — using local filesystem")

    @property
    def using_r2(self) -> bool:
        return self._s3 is not None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Upload bytes and return the URL (R2 public URL or /uploads/key)."""
        if self._s3:
            try:
                self._s3.put_object(
                    Bucket=self._bucket,
                    Key=key,
                    Body=data,
                    ContentType=content_type,
                )
                url = f"{self._public_url}/{key}"
                logger.info(f"[STORAGE] Uploaded to R2: {url}")
                return url
            except Exception as e:
                logger.error(f"[STORAGE] R2 upload failed, falling back to local: {e}")

        # Local fallback
        return self._write_local(key, data)

    def upload_from_path(self, key: str, local_path: str, content_type: str = "application/octet-stream") -> str:
        """Upload a file from a local path to storage. Returns the URL."""
        path = Path(local_path)
        if not path.exists():
            logger.error(f"[STORAGE] File not found: {local_path}")
            return f"/uploads/{key}"

        if self._s3:
            try:
                self._s3.upload_file(
                    Filename=str(path),
                    Bucket=self._bucket,
                    Key=key,
                    ExtraArgs={"ContentType": content_type},
                )
                url = f"{self._public_url}/{key}"
                logger.info(f"[STORAGE] Uploaded to R2 from path: {url}")
                return url
            except Exception as e:
                logger.error(f"[STORAGE] R2 upload_from_path failed, falling back to local: {e}")

        # Local fallback — copy to upload dir if not already there
        dest = self._upload_base / key
        if path.resolve() != dest.resolve():
            dest.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(str(path), str(dest))
        return f"/uploads/{key}"

    def delete(self, key_or_url: str) -> None:
        """Delete a file by key or URL (handles both R2 and local URLs)."""
        key = self._extract_key(key_or_url)
        if not key:
            return

        if self._s3:
            try:
                self._s3.delete_object(Bucket=self._bucket, Key=key)
                logger.info(f"[STORAGE] Deleted from R2: {key}")
            except Exception as e:
                logger.error(f"[STORAGE] R2 delete failed: {e}")

        # Also try local delete (for migration period — files may exist in both places)
        local_path = self._upload_base / key
        if local_path.exists():
            local_path.unlink()
            logger.info(f"[STORAGE] Deleted local file: {local_path}")

    def download(self, key_or_url: str) -> Optional[bytes]:
        """Download file contents. Returns bytes or None."""
        key = self._extract_key(key_or_url)
        if not key:
            return None

        # Try local first (faster, and covers migration period)
        local_path = self._upload_base / key
        if local_path.exists():
            return local_path.read_bytes()

        # Try R2
        if self._s3:
            try:
                response = self._s3.get_object(Bucket=self._bucket, Key=key)
                return response["Body"].read()
            except Exception as e:
                logger.error(f"[STORAGE] R2 download failed: {e}")

        return None

    def download_to_temp(self, key_or_url: str, suffix: str = "") -> Optional[str]:
        """Download to a temp file and return its path. Caller must clean up."""
        data = self.download(key_or_url)
        if data is None:
            return None
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.write(fd, data)
        os.close(fd)
        return path

    def url(self, key: str) -> str:
        """Construct the URL for a key without uploading."""
        if self._s3:
            return f"{self._public_url}/{key}"
        return f"/uploads/{key}"

    def resolve_local_path(self, key_or_url: str) -> Optional[Path]:
        """Resolve to a local file path if the file is local. Returns None for R2-only files."""
        key = self._extract_key(key_or_url)
        if not key:
            return None
        local_path = self._upload_base / key
        if local_path.exists():
            return local_path
        return None

    def is_remote_url(self, url: str) -> bool:
        """Check if a URL is a remote (R2/CDN) URL vs a local /uploads/ path."""
        return url.startswith("http://") or url.startswith("https://")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _extract_key(self, key_or_url: str) -> str:
        """Normalize a URL or path to a bare storage key.

        Handles:
          - https://cdn.example.com/properties/abc.jpg → properties/abc.jpg
          - /uploads/properties/abc.jpg → properties/abc.jpg
          - properties/abc.jpg → properties/abc.jpg
        """
        if not key_or_url:
            return ""

        # Strip R2 public URL prefix
        if self._public_url and key_or_url.startswith(self._public_url):
            return key_or_url[len(self._public_url):].lstrip("/")

        # Strip /uploads/ prefix
        if key_or_url.startswith("/uploads/"):
            return key_or_url[len("/uploads/"):]

        # Already a bare key
        if not key_or_url.startswith("http"):
            return key_or_url

        # Unknown remote URL — try to extract path after the domain
        from urllib.parse import urlparse
        parsed = urlparse(key_or_url)
        return parsed.path.lstrip("/")

    def _write_local(self, key: str, data: bytes) -> str:
        """Write to local filesystem and return /uploads/ URL."""
        filepath = self._upload_base / key
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "wb") as f:
            f.write(data)
        return f"/uploads/{key}"


# Singleton instance
storage = StorageService()
