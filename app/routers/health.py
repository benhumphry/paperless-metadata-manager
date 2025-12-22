"""Health check endpoints."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.paperless_client import PaperlessClient

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    paperless_connected: bool
    paperless_version: str | None = None
    error: str | None = None


@router.get("/health")
async def health_check(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Basic health check - always returns healthy if app is running."""
    return HealthResponse(
        status="healthy",
        paperless_connected=False,
        paperless_version=None,
    )


@router.get("/health/full")
async def full_health_check(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Full health check including Paperless-ngx connection."""
    try:
        async with PaperlessClient(
            settings.paperless_base_url,
            settings.paperless_api_token,
        ) as client:
            info = await client.test_connection()
            return HealthResponse(
                status="healthy",
                paperless_connected=True,
                paperless_version=info.version,
            )
    except Exception as e:
        return HealthResponse(
            status="degraded",
            paperless_connected=False,
            error=str(e),
        )
