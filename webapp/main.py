"""FastAPI application entry point"""

import logging
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
# Recertification is now built into property/tenant - dates tracked there
# from .routes.recertifications import router as recertifications_router

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
