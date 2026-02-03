"""PHA (Public Housing Authority) management routes"""

from pathlib import Path

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from database.connection import get_session
from database.models import PHA
from webapp.auth.dependencies import get_current_user

router = APIRouter(tags=["phas"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def list_phas(request: Request):
    """List all PHAs"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(PHA).order_by(PHA.name)
        )
        phas = result.scalars().all()

    return templates.TemplateResponse(
        "phas/list.html",
        {
            "request": request,
            "user": user,
            "phas": phas,
        }
    )


@router.get("/new", response_class=HTMLResponse)
async def new_pha_form(request: Request):
    """Show new PHA form"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        "phas/form.html",
        {
            "request": request,
            "user": user,
            "pha": None,
            "error": None,
        }
    )


@router.post("/new", response_class=HTMLResponse)
async def create_pha(
    request: Request,
    name: str = Form(...),
    contact_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    fax: str = Form(""),
    address: str = Form(""),
    city: str = Form(""),
    state: str = Form(""),
    zip_code: str = Form(""),
    website: str = Form(""),
    notes: str = Form("")
):
    """Create a new PHA"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        pha = PHA(
            name=name,
            contact_name=contact_name or None,
            email=email.lower() if email else None,
            phone=phone or None,
            fax=fax or None,
            address=address or None,
            city=city or None,
            state=state.upper() if state else None,
            zip_code=zip_code or None,
            website=website or None,
            notes=notes or None
        )
        session.add(pha)
        await session.commit()

        return RedirectResponse(url="/phas", status_code=303)


@router.get("/{pha_id}", response_class=HTMLResponse)
async def pha_detail(request: Request, pha_id: int):
    """Show PHA detail page"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(PHA).where(PHA.id == pha_id)
        )
        pha = result.scalar_one_or_none()

        if not pha:
            raise HTTPException(status_code=404, detail="PHA not found")

    return templates.TemplateResponse(
        "phas/detail.html",
        {
            "request": request,
            "user": user,
            "pha": pha,
        }
    )


@router.get("/{pha_id}/edit", response_class=HTMLResponse)
async def edit_pha_form(request: Request, pha_id: int):
    """Show edit PHA form"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(PHA).where(PHA.id == pha_id)
        )
        pha = result.scalar_one_or_none()

        if not pha:
            raise HTTPException(status_code=404, detail="PHA not found")

    return templates.TemplateResponse(
        "phas/form.html",
        {
            "request": request,
            "user": user,
            "pha": pha,
            "error": None,
        }
    )


@router.post("/{pha_id}/edit", response_class=HTMLResponse)
async def update_pha(
    request: Request,
    pha_id: int,
    name: str = Form(...),
    contact_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    fax: str = Form(""),
    address: str = Form(""),
    city: str = Form(""),
    state: str = Form(""),
    zip_code: str = Form(""),
    website: str = Form(""),
    notes: str = Form("")
):
    """Update a PHA"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(PHA).where(PHA.id == pha_id)
        )
        pha = result.scalar_one_or_none()

        if not pha:
            raise HTTPException(status_code=404, detail="PHA not found")

        pha.name = name
        pha.contact_name = contact_name or None
        pha.email = email.lower() if email else None
        pha.phone = phone or None
        pha.fax = fax or None
        pha.address = address or None
        pha.city = city or None
        pha.state = state.upper() if state else None
        pha.zip_code = zip_code or None
        pha.website = website or None
        pha.notes = notes or None

        await session.commit()

        return RedirectResponse(url=f"/phas/{pha_id}", status_code=303)


@router.post("/{pha_id}/delete")
async def delete_pha(request: Request, pha_id: int):
    """Delete a PHA"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(PHA).where(PHA.id == pha_id)
        )
        pha = result.scalar_one_or_none()

        if not pha:
            raise HTTPException(status_code=404, detail="PHA not found")

        await session.delete(pha)
        await session.commit()

    return RedirectResponse(url="/phas", status_code=303)
