"""Authenticated delivery for private documents in local or R2 storage."""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Request
from fastapi.responses import Response

from webapp.services import esign_service
from webapp.services.storage_service import storage


router = APIRouter(tags=["protected-files"])


def _file_response(key: str):
    data = storage.download(key)
    if data is None:
        return Response(status_code=404)
    content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
    return Response(
        data,
        media_type=content_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'inline; filename="{key.rsplit("/", 1)[-1]}"',
        },
    )


@router.get("/media-files/{key:path}")
async def public_media_file(key: str):
    """Proxy non-sensitive media without exposing the R2 bucket itself."""
    if storage.is_protected_key(key):
        return Response(status_code=404)
    response = _file_response(key)
    response.headers["Cache-Control"] = "public, max-age=604800"
    return response


@router.get("/protected-files/{key:path}")
async def protected_file(request: Request, key: str):
    has_session = any(request.session.get(name) for name in ("user", "tenant", "vendor"))
    signing_token = request.query_params.get("signing_token", "")
    has_signing_access = bool(signing_token and esign_service.verify_signing_token(signing_token))
    if not has_session and not has_signing_access:
        return Response(status_code=404)
    if not storage.is_protected_key(key):
        return Response(status_code=404)

    return _file_response(key)
