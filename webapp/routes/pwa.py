"""PWA support routes - manifests and service workers for all portals"""

import json

from fastapi import APIRouter
from fastapi.responses import Response

router = APIRouter(tags=["pwa"])

# --- Icon definitions (shared across manifests) ---

ICON_SIZES = [72, 96, 128, 144, 152, 192, 384, 512]


def _icons(prefix: str = "") -> list[dict]:
    """Generate icon entries for a manifest."""
    icons = [
        {
            "src": f"/static/images/icons/icon-{size}x{size}.png",
            "sizes": f"{size}x{size}",
            "type": "image/png",
        }
        for size in ICON_SIZES
    ]
    icons.append({
        "src": "/static/images/icons/icon-512x512-maskable.png",
        "sizes": "512x512",
        "type": "image/png",
        "purpose": "maskable",
    })
    return icons


# --- Manifests ---

@router.get("/manifest.json", include_in_schema=False)
async def admin_manifest():
    manifest = {
        "name": "Blue Deer Property Management",
        "short_name": "Blue Deer",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#1e3a8a",
        "icons": _icons(),
    }
    return Response(
        content=json.dumps(manifest, indent=2),
        media_type="application/manifest+json",
    )


@router.get("/portal/manifest.json", include_in_schema=False)
async def tenant_manifest():
    manifest = {
        "name": "Blue Deer Tenant Portal",
        "short_name": "Tenant Portal",
        "start_url": "/portal/",
        "scope": "/portal/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#2563eb",
        "icons": _icons(),
    }
    return Response(
        content=json.dumps(manifest, indent=2),
        media_type="application/manifest+json",
    )


@router.get("/vendor/manifest.json", include_in_schema=False)
async def vendor_manifest():
    manifest = {
        "name": "Blue Deer Vendor Portal",
        "short_name": "Vendor Portal",
        "start_url": "/vendor/",
        "scope": "/vendor/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#7e22ce",
        "icons": _icons(),
    }
    return Response(
        content=json.dumps(manifest, indent=2),
        media_type="application/manifest+json",
    )


# --- Service Workers ---

_SW_JS = """// Blue Deer Service Worker — {portal_name}
const CACHE_NAME = '{cache_name}-v1';
const SCOPE = '{scope}';

// Static assets to pre-cache
const PRECACHE_URLS = [
    SCOPE,
    '/static/images/logo.png',
    '/static/images/favicon.png',
];

// Install: pre-cache shell
self.addEventListener('install', (event) => {{
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
    );
    self.skipWaiting();
}});

// Activate: clean old caches
self.addEventListener('activate', (event) => {{
    event.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
        )
    );
    self.clients.claim();
}});

// Fetch strategy
self.addEventListener('fetch', (event) => {{
    const url = new URL(event.request.url);

    // Skip API calls and uploads — always go to network
    if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/uploads/')) {{
        return;
    }}

    // Skip non-GET requests
    if (event.request.method !== 'GET') {{
        return;
    }}

    // HTML pages: network-first with cache fallback
    if (event.request.headers.get('Accept')?.includes('text/html')) {{
        event.respondWith(
            fetch(event.request)
                .then((response) => {{
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
                    return response;
                }})
                .catch(() => caches.match(event.request))
        );
        return;
    }}

    // Static assets: cache-first with network fallback
    if (url.pathname.startsWith('/static/')) {{
        event.respondWith(
            caches.match(event.request).then((cached) => {{
                if (cached) return cached;
                return fetch(event.request).then((response) => {{
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
                    return response;
                }});
            }})
        );
        return;
    }}
}});
"""


@router.get("/sw.js", include_in_schema=False)
async def admin_sw():
    js = _SW_JS.format(
        portal_name="Admin",
        cache_name="bluedeer-admin",
        scope="/",
    )
    return Response(content=js, media_type="application/javascript")


@router.get("/portal/sw.js", include_in_schema=False)
async def tenant_sw():
    js = _SW_JS.format(
        portal_name="Tenant Portal",
        cache_name="bluedeer-tenant",
        scope="/portal/",
    )
    return Response(content=js, media_type="application/javascript")


@router.get("/vendor/sw.js", include_in_schema=False)
async def vendor_sw():
    js = _SW_JS.format(
        portal_name="Vendor Portal",
        cache_name="bluedeer-vendor",
        scope="/vendor/",
    )
    return Response(content=js, media_type="application/javascript")
