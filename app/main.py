"""Paperless-ngx Tag Manager - FastAPI Application."""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import __version__
from app.config import Settings, get_settings
from app.paperless_client import PaperlessClient
from app.routers import correspondents, custom_fields, document_types, health, tags

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    settings = get_settings()
    logger.info(f"Starting Paperless Tag Manager v{__version__}")
    logger.info(f"Paperless URL: {settings.paperless_base_url}")
    logger.info(f"Exclude patterns: {settings.exclude_pattern_list}")
    yield
    logger.info("Shutting down Paperless Tag Manager")


app = FastAPI(
    title="Paperless-ngx Tag Manager",
    description="Bulk tag management for Paperless-ngx",
    version=__version__,
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include routers
app.include_router(health.router)
app.include_router(tags.router)
app.include_router(correspondents.router)
app.include_router(document_types.router)
app.include_router(custom_fields.router)

# Templates
templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, settings: Settings = Depends(get_settings)):
    """Render the main page."""
    # Test connection to get status
    connected = False
    version = None
    error = None

    try:
        async with PaperlessClient(
            settings.paperless_base_url,
            settings.paperless_api_token,
        ) as client:
            info = await client.test_connection()
            connected = True
            version = info.version
    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "paperless_url": settings.paperless_base_url,
            "connected": connected,
            "version": version,
            "error": error,
            "app_version": __version__,
            "exclude_patterns": ", ".join(settings.exclude_pattern_list),
        },
    )
