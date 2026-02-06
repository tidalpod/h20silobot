"""Public legal pages - Privacy Policy and Terms & Conditions"""

from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["legal"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_policy(request: Request):
    """Public privacy policy page"""
    return templates.TemplateResponse("legal/privacy.html", {"request": request})


@router.get("/terms", response_class=HTMLResponse)
async def terms_and_conditions(request: Request):
    """Public terms and conditions page"""
    return templates.TemplateResponse("legal/terms.html", {"request": request})
