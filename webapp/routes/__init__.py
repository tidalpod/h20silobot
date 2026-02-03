"""Web application routes"""

from .dashboard import router as dashboard_router
from .properties import router as properties_router
from .tenants import router as tenants_router
from .notifications import router as notifications_router
from .bills import router as bills_router
from .api import router as api_router

__all__ = [
    "dashboard_router",
    "properties_router",
    "tenants_router",
    "notifications_router",
    "bills_router",
    "api_router",
]
