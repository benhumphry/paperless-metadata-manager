"""Custom field management endpoints."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.paperless_client import CustomField, PaperlessClient

router = APIRouter(prefix="/api/custom_fields", tags=["custom_fields"])


class CustomFieldListResponse(BaseModel):
    """Response containing list of custom fields."""

    custom_fields: list[dict]
    total: int


def custom_field_to_dict(custom_field: CustomField) -> dict:
    """Convert CustomField to dictionary for JSON response."""
    return {
        "id": custom_field.id,
        "name": custom_field.name,
        "data_type": custom_field.data_type,
        "type_name": custom_field.type_name,
    }


@router.get("", response_model=CustomFieldListResponse)
async def list_custom_fields(
    settings: Settings = Depends(get_settings),
):
    """Get all custom fields."""
    async with PaperlessClient(
        settings.paperless_base_url,
        settings.paperless_api_token,
    ) as client:
        custom_fields = await client.get_all_custom_fields()
        sorted_custom_fields = sorted(custom_fields, key=lambda x: x.name.lower())

        return CustomFieldListResponse(
            custom_fields=[custom_field_to_dict(cf) for cf in sorted_custom_fields],
            total=len(sorted_custom_fields),
        )
