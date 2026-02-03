"""Authentication routes"""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from database.connection import get_session
from database.models import WebUser
from .utils import hash_password, verify_password
from .dependencies import login_user, logout_user, get_current_user

router = APIRouter(tags=["auth"])

# Templates
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/"):
    """Render login page"""
    user = await get_current_user(request)
    if user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request, "next": next, "error": None}
    )


@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/")
):
    """Handle login form submission"""
    async with get_session() as session:
        result = await session.execute(
            select(WebUser).where(WebUser.email == email.lower())
        )
        user = result.scalar_one_or_none()

        if not user or not verify_password(password, user.password_hash):
            return templates.TemplateResponse(
                "auth/login.html",
                {"request": request, "next": next, "error": "Invalid email or password"},
                status_code=400
            )

        if not user.is_active:
            return templates.TemplateResponse(
                "auth/login.html",
                {"request": request, "next": next, "error": "Account is disabled"},
                status_code=400
            )

        # Update last login
        user.last_login = datetime.utcnow()
        await session.commit()

        # Store in session
        login_user(request, user)

    return RedirectResponse(url=next, status_code=303)


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Render registration page"""
    user = await get_current_user(request)
    if user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        "auth/register.html",
        {"request": request, "error": None}
    )


@router.post("/register", response_class=HTMLResponse)
async def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    name: str = Form("")
):
    """Handle registration form submission"""
    # Validate passwords match
    if password != password_confirm:
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "error": "Passwords do not match"},
            status_code=400
        )

    # Validate password length
    if len(password) < 8:
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "error": "Password must be at least 8 characters"},
            status_code=400
        )

    async with get_session() as session:
        # Check if email exists
        result = await session.execute(
            select(WebUser).where(WebUser.email == email.lower())
        )
        existing = result.scalar_one_or_none()

        if existing:
            return templates.TemplateResponse(
                "auth/register.html",
                {"request": request, "error": "Email already registered"},
                status_code=400
            )

        # Check if this is the first user (make them admin)
        result = await session.execute(select(WebUser))
        is_first_user = result.first() is None

        # Create user
        user = WebUser(
            email=email.lower(),
            password_hash=hash_password(password),
            name=name or None,
            is_admin=is_first_user,  # First user is admin
            is_active=True
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        # Log them in
        login_user(request, user)

    return RedirectResponse(url="/", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    """Handle logout"""
    logout_user(request)
    return RedirectResponse(url="/login", status_code=303)


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    """User profile page"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        "auth/profile.html",
        {"request": request, "user": user, "success": None, "error": None}
    )


@router.post("/profile", response_class=HTMLResponse)
async def update_profile(
    request: Request,
    name: str = Form(""),
    current_password: str = Form(""),
    new_password: str = Form(""),
    new_password_confirm: str = Form("")
):
    """Update user profile"""
    user_data = await get_current_user(request)
    if not user_data:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(WebUser).where(WebUser.id == user_data["id"])
        )
        user = result.scalar_one_or_none()

        if not user:
            return RedirectResponse(url="/login", status_code=303)

        # Update name
        user.name = name or None

        # Update password if provided
        if new_password:
            if not current_password:
                return templates.TemplateResponse(
                    "auth/profile.html",
                    {"request": request, "user": user_data, "error": "Current password required", "success": None}
                )

            if not verify_password(current_password, user.password_hash):
                return templates.TemplateResponse(
                    "auth/profile.html",
                    {"request": request, "user": user_data, "error": "Current password is incorrect", "success": None}
                )

            if new_password != new_password_confirm:
                return templates.TemplateResponse(
                    "auth/profile.html",
                    {"request": request, "user": user_data, "error": "New passwords do not match", "success": None}
                )

            if len(new_password) < 8:
                return templates.TemplateResponse(
                    "auth/profile.html",
                    {"request": request, "user": user_data, "error": "Password must be at least 8 characters", "success": None}
                )

            user.password_hash = hash_password(new_password)

        await session.commit()

        # Update session with new name
        login_user(request, user)

    return templates.TemplateResponse(
        "auth/profile.html",
        {"request": request, "user": request.session.get("user"), "success": "Profile updated successfully", "error": None}
    )
