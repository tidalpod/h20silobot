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


@router.get("/login/phone", response_class=HTMLResponse)
async def phone_login_page(request: Request, next: str = "/"):
    """Phone login page for admin users"""
    user = await get_current_user(request)
    if user:
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        "auth/phone_login.html",
        {"request": request, "next": next, "error": None}
    )


@router.post("/login/phone", response_class=HTMLResponse)
async def phone_login_send_code(request: Request, phone: str = Form(...), next: str = Form("/")):
    """Send SMS verification code for admin login"""
    from webapp.services.admin_verification_service import send_admin_verification_code

    result = await send_admin_verification_code(phone)
    if not result["success"]:
        return templates.TemplateResponse(
            "auth/phone_login.html",
            {"request": request, "next": next, "error": result["error"], "phone": phone},
            status_code=400
        )

    request.session["admin_phone"] = phone
    request.session["admin_next"] = next
    return RedirectResponse(url="/login/verify", status_code=303)


@router.get("/login/verify", response_class=HTMLResponse)
async def phone_verify_page(request: Request):
    """Code verification page for admin login"""
    phone = request.session.get("admin_phone")
    if not phone:
        return RedirectResponse(url="/login/phone", status_code=303)

    return templates.TemplateResponse(
        "auth/phone_verify.html",
        {"request": request, "phone": phone, "error": None}
    )


@router.post("/login/verify", response_class=HTMLResponse)
async def phone_verify_code(request: Request, code: str = Form(...)):
    """Verify SMS code and log in admin user"""
    from webapp.services.admin_verification_service import verify_admin_code

    phone = request.session.get("admin_phone")
    if not phone:
        return RedirectResponse(url="/login/phone", status_code=303)

    result = await verify_admin_code(phone, code)
    if not result["success"]:
        return templates.TemplateResponse(
            "auth/phone_verify.html",
            {"request": request, "phone": phone, "error": result["error"]},
            status_code=400
        )

    # Log in the user
    login_user(request, result["user"])
    next_url = request.session.pop("admin_next", "/")
    request.session.pop("admin_phone", None)

    return RedirectResponse(url=next_url, status_code=303)


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Registration is disabled - redirect to login"""
    return RedirectResponse(url="/login", status_code=303)


@router.post("/register", response_class=HTMLResponse)
async def register(request: Request):
    """Registration is disabled"""
    return RedirectResponse(url="/login", status_code=303)


# ============ ADMIN USER MANAGEMENT ============

@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request):
    """Admin page to manage users"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    if not user.get("is_admin"):
        return RedirectResponse(url="/", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(WebUser).order_by(WebUser.created_at.desc())
        )
        users = result.scalars().all()

    return templates.TemplateResponse(
        "auth/admin_users.html",
        {"request": request, "user": user, "users": users}
    )


@router.get("/admin/users/new", response_class=HTMLResponse)
async def admin_new_user_page(request: Request):
    """Admin page to create new user"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    if not user.get("is_admin"):
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        "auth/admin_new_user.html",
        {"request": request, "user": user, "error": None}
    )


@router.post("/admin/users/new", response_class=HTMLResponse)
async def admin_create_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    name: str = Form(""),
    phone: str = Form(""),
    telegram_id: str = Form(""),
    is_admin: str = Form("")
):
    """Admin creates a new user"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    if not user.get("is_admin"):
        return RedirectResponse(url="/", status_code=303)

    # Validate passwords match
    if password != password_confirm:
        return templates.TemplateResponse(
            "auth/admin_new_user.html",
            {"request": request, "user": user, "error": "Passwords do not match"},
            status_code=400
        )

    # Validate password length
    if len(password) < 8:
        return templates.TemplateResponse(
            "auth/admin_new_user.html",
            {"request": request, "user": user, "error": "Password must be at least 8 characters"},
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
                "auth/admin_new_user.html",
                {"request": request, "user": user, "error": "Email already registered"},
                status_code=400
            )

        # Create user
        new_user = WebUser(
            email=email.lower(),
            password_hash=hash_password(password),
            name=name or None,
            phone=phone.strip() or None,
            telegram_id=int(telegram_id.strip()) if telegram_id.strip() else None,
            is_admin=is_admin.lower() == "true" if is_admin else False,
            is_active=True
        )
        session.add(new_user)
        await session.commit()

    return RedirectResponse(url="/admin/users", status_code=303)


@router.get("/admin/users/{user_id}/edit", response_class=HTMLResponse)
async def admin_edit_user_page(request: Request, user_id: int):
    """Admin page to edit a user"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    if not user.get("is_admin"):
        return RedirectResponse(url="/", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(WebUser).where(WebUser.id == user_id)
        )
        edit_user = result.scalar_one_or_none()
        if not edit_user:
            return RedirectResponse(url="/admin/users", status_code=303)

    return templates.TemplateResponse(
        "auth/admin_edit_user.html",
        {"request": request, "user": user, "edit_user": edit_user, "error": None, "success": None}
    )


@router.post("/admin/users/{user_id}/edit", response_class=HTMLResponse)
async def admin_update_user(
    request: Request,
    user_id: int,
    name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    telegram_id: str = Form(""),
    is_admin: str = Form(""),
    is_active: str = Form(""),
    new_password: str = Form(""),
    new_password_confirm: str = Form("")
):
    """Admin updates a user"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    if not user.get("is_admin"):
        return RedirectResponse(url="/", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(WebUser).where(WebUser.id == user_id)
        )
        edit_user = result.scalar_one_or_none()
        if not edit_user:
            return RedirectResponse(url="/admin/users", status_code=303)

        def render_error(error):
            return templates.TemplateResponse(
                "auth/admin_edit_user.html",
                {"request": request, "user": user, "edit_user": edit_user, "error": error, "success": None},
                status_code=400
            )

        # Check email uniqueness if changed
        if email.lower() != edit_user.email:
            existing = await session.execute(
                select(WebUser).where(WebUser.email == email.lower(), WebUser.id != user_id)
            )
            if existing.scalar_one_or_none():
                return render_error("Email already in use by another user")

        # Update fields
        edit_user.name = name.strip() or None
        edit_user.email = email.lower().strip()
        edit_user.phone = phone.strip() or None
        edit_user.telegram_id = int(telegram_id.strip()) if telegram_id.strip() else None
        edit_user.is_admin = is_admin == "true"
        edit_user.is_active = is_active == "true"

        # Reset password if provided
        if new_password:
            if new_password != new_password_confirm:
                return render_error("Passwords do not match")
            if len(new_password) < 8:
                return render_error("Password must be at least 8 characters")
            edit_user.password_hash = hash_password(new_password)

        await session.commit()

    return RedirectResponse(url="/admin/users", status_code=303)


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
    phone: str = Form(""),
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

        # Update name and phone
        user.name = name or None
        user.phone = phone.strip() or None

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
