"""Tenant authentication for the tenant portal"""

from typing import Optional
from fastapi import Request
from fastapi.responses import RedirectResponse


async def get_current_tenant(request: Request) -> Optional[dict]:
    """Get current tenant from session"""
    return request.session.get("tenant")


def login_tenant(request: Request, tenant_data: dict):
    """Store tenant info in session (separate from admin 'user' key)"""
    request.session["tenant"] = tenant_data


def logout_tenant(request: Request):
    """Clear only the tenant session key, preserving admin session"""
    request.session.pop("tenant", None)


def require_tenant(request: Request) -> Optional[dict]:
    """Check if tenant is logged in, redirect to portal login if not"""
    tenant = request.session.get("tenant")
    if not tenant:
        return None
    return tenant
