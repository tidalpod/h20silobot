"""FastAPI application entry point"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .config import web_config
from database.connection import init_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Paths
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# Upload directory - Railway volume or local fallback
# Try env var first, then Railway volume at /app/uploads, then local fallback
UPLOAD_PATH = os.environ.get("UPLOAD_PATH") or (
    "/app/uploads" if Path("/app/uploads").exists() else str(BASE_DIR / "static" / "uploads")
)
UPLOAD_DIR = Path(UPLOAD_PATH)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Debug logging for upload path configuration
logger.info(f"=== UPLOAD PATH DEBUG ===")
logger.info(f"UPLOAD_PATH env var: {os.environ.get('UPLOAD_PATH', 'NOT SET')}")
logger.info(f"Using upload path: {UPLOAD_PATH}")
logger.info(f"Upload directory exists: {UPLOAD_DIR.exists()}")
logger.info(f"Upload directory is dir: {UPLOAD_DIR.is_dir()}")
# Check properties subdirectory
props_dir = UPLOAD_DIR / "properties"
if props_dir.exists():
    files = list(props_dir.iterdir())
    logger.info(f"Properties folder has {len(files)} files")
    if files:
        logger.info(f"Sample files: {[f.name for f in files[:5]]}")
else:
    logger.info(f"Properties folder does not exist yet")
logger.info(f"===========================")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("Starting Blue Deer Web App...")

    # Debug: log email config status
    logger.info(f"[CONFIG] SENDGRID_API_KEY set: {bool(web_config.sendgrid_api_key)}")
    logger.info(f"[CONFIG] EMAIL_FROM set: {bool(web_config.email_from)} ({web_config.email_from[:20] if web_config.email_from else 'empty'})")
    logger.info(f"[CONFIG] Email configured: {web_config.has_sendgrid}")

    # Initialize database
    db_success = await init_db()
    if not db_success:
        logger.warning("Database connection failed - some features may be unavailable")
    else:
        logger.info("Database connected successfully")

    # Run showing reminder migration
    try:
        from database.migrations.add_showing_reminder import run_migration
        await run_migration()
    except Exception as e:
        logger.warning(f"Showing reminder migration skipped: {e}")

    # Run inspection reminder migration
    try:
        from database.migrations.add_inspection_reminder import run_migration as run_inspection_migration
        await run_inspection_migration()
    except Exception as e:
        logger.warning(f"Inspection reminder migration skipped: {e}")

    # Run recert reminder migration
    try:
        from database.migrations.add_recert_reminder_log import run_migration as run_recert_migration
        await run_recert_migration()
    except Exception as e:
        logger.warning(f"Recert reminder migration skipped: {e}")

    # Run vault migration
    try:
        from database.migrations.add_vault import run_migration as run_vault_migration
        await run_vault_migration()
    except Exception as e:
        logger.warning(f"Vault migration skipped: {e}")

    # Run bill alert migration
    try:
        from database.migrations.add_bill_alert import run_migration as run_bill_alert_migration
        await run_bill_alert_migration()
    except Exception as e:
        logger.warning(f"Bill alert migration skipped: {e}")

    # Run bill alert renotify migration
    try:
        from database.migrations.add_bill_alert_renotify import run_migration as run_bill_alert_renotify_migration
        await run_bill_alert_renotify_migration()
    except Exception as e:
        logger.warning(f"Bill alert renotify migration skipped: {e}")

    # Auto-cleanup orphaned photo records (files lost between deploys)
    # Skip when using R2 — files persist independently of deploys
    if db_success:
        try:
            from webapp.services.storage_service import storage
            if storage.using_r2:
                logger.info("[CLEANUP] Skipping orphan cleanup — using R2 storage")
            else:
                from sqlalchemy import select
                from database.connection import get_session
                from database.models import PropertyPhoto, Property

                props_dir = UPLOAD_DIR / "properties"
                async with get_session() as session:
                    result = await session.execute(select(PropertyPhoto))
                    all_photos = result.scalars().all()
                    deleted = 0
                    affected_props = set()
                    for photo in all_photos:
                        filename = photo.url.split("/")[-1]
                        filepath = props_dir / filename
                        if not filepath.exists():
                            affected_props.add(photo.property_id)
                            await session.delete(photo)
                            deleted += 1
                    # Clear featured_photo_url for affected properties
                    for prop_id in affected_props:
                        res = await session.execute(
                            select(Property).where(Property.id == prop_id)
                        )
                        prop = res.scalar_one_or_none()
                        if prop and prop.featured_photo_url:
                            fname = prop.featured_photo_url.split("/")[-1]
                            if not (props_dir / fname).exists():
                                prop.featured_photo_url = None
                    if deleted:
                        logger.info(f"[CLEANUP] Removed {deleted} orphaned photo records from {len(affected_props)} properties")
        except Exception as e:
            logger.warning(f"Photo cleanup skipped: {e}")

    # Start background showing reminder service
    reminder_task = None
    inspection_reminder_task = None
    ledger_task = None
    if db_success:
        try:
            from webapp.services.ledger_service import ensure_all_monthly_rent_charges, monthly_charge_loop
            await ensure_all_monthly_rent_charges()
            ledger_task = asyncio.create_task(monthly_charge_loop())
            logger.info("Monthly rent charge service started")
        except Exception as e:
            logger.warning(f"Monthly rent charge service skipped: {e}")

    if db_success and web_config.has_twilio:
        from webapp.services.showing_reminders import reminder_loop
        reminder_task = asyncio.create_task(reminder_loop())
        logger.info("Showing reminder service started")

        from webapp.services.inspection_reminders import inspection_reminder_loop
        inspection_reminder_task = asyncio.create_task(inspection_reminder_loop())
        logger.info("Inspection reminder service started")

    yield

    # Cancel reminder tasks on shutdown
    for task in [reminder_task, inspection_reminder_task, ledger_task]:
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    logger.info("Shutting down Blue Deer Web App...")


# Create FastAPI app
app = FastAPI(
    title="Blue Deer Property Management",
    description="Property management and water bill tracking system",
    version="1.0.0",
    lifespan=lifespan
)

# Add session middleware
app.add_middleware(
    SessionMiddleware,
    secret_key=web_config.secret_key,
    session_cookie=web_config.session_cookie_name,
    max_age=web_config.session_max_age,
    same_site=web_config.session_same_site,
    https_only=web_config.session_cookie_secure,
)


@app.middleware("http")
async def security_and_cache_headers(request: Request, call_next):
    """Enforce same-origin form posts and apply browser security defaults."""
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    public_scheme = forwarded_proto.split(",")[0].strip().lower()
    if public_scheme in {"http", "https"}:
        request.scope["scheme"] = public_scheme

    if request.method not in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        source = request.headers.get("origin") or request.headers.get("referer")
        if source:
            source_host = urlparse(source).netloc.lower()
            request_host = request.headers.get("x-forwarded-host", request.headers.get("host", "")).lower()
            if source_host and source_host != request_host:
                return JSONResponse({"detail": "Cross-origin request rejected"}, status_code=403)

    response = await call_next(request)
    is_upload = request.url.path.startswith("/uploads/")
    frame_ancestors = "'self'" if is_upload else "'none'"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN" if is_upload else "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://unpkg.com https://cdn.jsdelivr.net https://cdn.plaid.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data: blob: https:; "
        "font-src 'self' data:; connect-src 'self' https://*.plaid.com https://*.stripe.com; "
        "frame-src 'self' https:; "
        f"frame-ancestors {frame_ancestors}; base-uri 'self'; "
        "form-action 'self' https://checkout.stripe.com",
    )

    if public_scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "public, max-age=604800")
    elif response.headers.get("content-type", "").startswith("text/html"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response

# Mount static files
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Mount uploads directory (Railway volume or local)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# Template context processor
def get_template_context(request: Request, **kwargs):
    """Add common context variables to templates"""
    return {
        "request": request,
        "user": request.session.get("user"),
        **kwargs
    }


# Import and include routers
from .auth.routes import router as auth_router
from .routes.dashboard import router as dashboard_router
from .routes.properties import router as properties_router
from .routes.tenants import router as tenants_router
from .routes.notifications import router as notifications_router
from .routes.bills import router as bills_router
from .routes.api import router as api_router
from .routes.phas import router as phas_router
from .routes.inspections import router as inspections_router
from .routes.sms import router as sms_router
from .routes.legal import router as legal_router
from .routes.public import router as public_router
from .routes.maintenance import router as maintenance_router
from .routes.leases import router as leases_router
from .routes.portal import router as portal_router
from .routes.vendor_portal import router as vendor_portal_router
from .routes.invoices import router as invoices_router
from .routes.projects import router as projects_router
from .routes.showings import router as showings_router
from .routes.portal_payments import router as portal_payments_router
from .routes.payments_admin import router as payments_admin_router
from .routes.entity_accounts import router as entity_accounts_router
from .routes.lease_builder import router as lease_builder_router
from .routes.assets import router as assets_router
from .routes.pwa import router as pwa_router
from .routes.applications import router as applications_router
from .routes.leads import router as leads_router
from .routes.esign_public import router as esign_public_router
from .routes.packets import router as packets_router
# Recertification is now built into property/tenant - dates tracked there
# from .routes.recertifications import router as recertifications_router

# PWA routes must be registered before portal/vendor prefix routes
app.include_router(pwa_router)
app.include_router(esign_public_router)
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(assets_router, prefix="/assets")
app.include_router(properties_router, prefix="/properties")
app.include_router(tenants_router, prefix="/tenants")
app.include_router(notifications_router, prefix="/notifications")
app.include_router(bills_router, prefix="/bills")
app.include_router(api_router, prefix="/api")
app.include_router(phas_router, prefix="/phas")
app.include_router(inspections_router)
app.include_router(sms_router)
app.include_router(legal_router)
app.include_router(applications_router)
app.include_router(leads_router, prefix="/leads")
app.include_router(public_router)
app.include_router(maintenance_router, prefix="/maintenance")
app.include_router(lease_builder_router, prefix="/leases/builder")
app.include_router(leases_router, prefix="/leases")
app.include_router(portal_router, prefix="/portal")
app.include_router(vendor_portal_router, prefix="/vendor")
app.include_router(invoices_router, prefix="/invoices")
app.include_router(projects_router, prefix="/projects")
app.include_router(showings_router, prefix="/showings")
app.include_router(portal_payments_router, prefix="/portal")
app.include_router(entity_accounts_router, prefix="/payments")
app.include_router(payments_admin_router, prefix="/payments")
app.include_router(packets_router, prefix="/packets")
# Recertification routes removed - dates tracked on property/tenant directly
# app.include_router(recertifications_router, prefix="/recertifications")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    from database.connection import is_connected
    return {
        "status": "healthy",
        "database": "connected" if is_connected() else "disconnected"
    }


@app.get("/healthz")
async def liveness_check():
    """Lightweight platform liveness check that does not expose internals."""
    return {"status": "ok"}
