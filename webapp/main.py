"""FastAPI application entry point"""

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

    # Initialize database
    db_success = await init_db()
    if not db_success:
        logger.warning("Database connection failed - some features may be unavailable")
    else:
        logger.info("Database connected successfully")

    yield

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
from .routes.portal_payments import router as portal_payments_router
from .routes.payments_admin import router as payments_admin_router
from .routes.lease_builder import router as lease_builder_router
from .routes.pwa import router as pwa_router
# Recertification is now built into property/tenant - dates tracked there
# from .routes.recertifications import router as recertifications_router

# PWA routes must be registered before portal/vendor prefix routes
app.include_router(pwa_router)
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(properties_router, prefix="/properties")
app.include_router(tenants_router, prefix="/tenants")
app.include_router(notifications_router, prefix="/notifications")
app.include_router(bills_router, prefix="/bills")
app.include_router(api_router, prefix="/api")
app.include_router(phas_router, prefix="/phas")
app.include_router(inspections_router)
app.include_router(sms_router)
app.include_router(legal_router)
app.include_router(public_router)
app.include_router(maintenance_router, prefix="/maintenance")
app.include_router(lease_builder_router, prefix="/leases/builder")
app.include_router(leases_router, prefix="/leases")
app.include_router(portal_router, prefix="/portal")
app.include_router(vendor_portal_router, prefix="/vendor")
app.include_router(invoices_router, prefix="/invoices")
app.include_router(projects_router, prefix="/projects")
app.include_router(portal_payments_router, prefix="/portal")
app.include_router(payments_admin_router, prefix="/payments")
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
