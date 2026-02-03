"""Authentication dependencies for FastAPI"""

from typing import Optional
from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse

from database.connection import get_session
from database.models import WebUser
from sqlalchemy import select


async def get_current_user(request: Request) -> Optional[dict]:
    """Get current user from session"""
    user_data = request.session.get("user")
    return user_data


async def get_current_user_from_db(request: Request) -> Optional["WebUser"]:
    """Get current user model from database"""
    user_data = request.session.get("user")
    if not user_data:
        return None

    async with get_session() as session:
        result = await session.execute(
            select(WebUser).where(WebUser.id == user_data["id"])
        )
        return result.scalar_one_or_none()


def require_auth(request: Request):
    """Dependency that requires authentication"""
    user = request.session.get("user")
    if not user:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login?next=" + str(request.url.path)}
        )
    return user


def require_admin(request: Request):
    """Dependency that requires admin authentication"""
    user = require_auth(request)
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return user


def login_user(request: Request, user: "WebUser"):
    """Store user info in session"""
    request.session["user"] = {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "is_admin": user.is_admin
    }


def logout_user(request: Request):
    """Clear user session"""
    request.session.clear()
