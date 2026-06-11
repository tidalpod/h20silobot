"""FastAPI application entry point"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
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
    if db_success and web_config.has_twilio:
        from webapp.services.showing_reminders import reminder_loop
        reminder_task = asyncio.create_task(reminder_loop())
        logger.info("Showing reminder service started")

        from webapp.services.inspection_reminders import inspection_reminder_loop
        inspection_reminder_task = asyncio.create_task(inspection_reminder_loop())
        logger.info("Inspection reminder service started")

    yield

    # Cancel reminder tasks on shutdown
    for task in [reminder_task, inspection_reminder_task]:
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
)

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


@app.get("/debug/uploads")
async def debug_uploads():
    """Debug endpoint to check upload configuration"""
    props_dir = UPLOAD_DIR / "properties"
    files = []
    if props_dir.exists():
        files = [f.name for f in props_dir.iterdir()][:20]

    return {
        "upload_path_env": os.environ.get("UPLOAD_PATH", "NOT SET (using default)"),
        "actual_upload_path": str(UPLOAD_PATH),
        "upload_dir_exists": UPLOAD_DIR.exists(),
        "properties_dir_exists": props_dir.exists(),
        "file_count": len(list(props_dir.iterdir())) if props_dir.exists() else 0,
        "sample_files": files,
        "is_volume": not str(UPLOAD_PATH).startswith(str(BASE_DIR))
    }
