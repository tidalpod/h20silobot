"""Vendor authentication for the vendor portal"""

from typing import Optional
from fastapi import Request


async def get_current_vendor(request: Request) -> Optional[dict]:
    """Get current vendor from session"""
    return request.session.get("vendor")


def login_vendor(request: Request, vendor_data: dict):
    """Store vendor info in session (separate from admin 'user' and tenant keys)"""
    request.session["vendor"] = vendor_data


def logout_vendor(request: Request):
    """Clear only the vendor session key, preserving admin/tenant sessions"""
    request.session.pop("vendor", None)


def require_vendor(request: Request) -> Optional[dict]:
    """Check if vendor is logged in"""
    vendor = request.session.get("vendor")
    if not vendor:
        return None
    return vendor
