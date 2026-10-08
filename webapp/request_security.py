"""Request-origin helpers that do not blindly trust forwarded headers."""

from __future__ import annotations

import ipaddress
import os

from webapp.config import web_config


def is_same_origin_embeddable_path(path: str) -> bool:
    """Return whether a response is an authenticated same-origin file preview."""
    return path.startswith(("/uploads/", "/protected-files/"))


def client_ip(request) -> str:
    peer = request.client.host if request.client else "unknown"
    # Railway overwrites X-Real-IP at its public edge with the originating
    # client address. Only honor it when Railway's environment marker exists;
    # other deployments still require an explicit proxy allowlist.
    railway_real_ip = (
        request.headers.get("x-real-ip", "").strip()
        if os.getenv("RAILWAY_ENVIRONMENT")
        else ""
    )
    trusted_proxies = {
        value.strip() for value in web_config.trusted_proxy_ips.split(",") if value.strip()
    }
    forwarded = request.headers.get("x-forwarded-for", "")
    if railway_real_ip:
        candidate = railway_real_ip
    elif peer in trusted_proxies and forwarded:
        candidate = forwarded.split(",", 1)[0].strip()
    else:
        candidate = peer
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return "unknown"
