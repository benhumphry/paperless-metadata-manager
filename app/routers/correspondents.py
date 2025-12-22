"""Correspondent management endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.paperless_client import (
    Correspondent,
    PaperlessClient,
    find_low_usage_correspondents,
    group_correspondents_by_prefix,
)

router = APIRouter(prefix="/api/correspondents", tags=["correspondents"])


class CorrespondentListResponse(BaseModel):
    """Response containing list of correspondents."""

    correspondents: list[dict]
    total: int
    page: int
    page_size: int
    total_pages: int


class DeleteRequest(BaseModel):
    """Request to delete correspondents."""

    correspondent_ids: list[int]


class MergeRequest(BaseModel):
    """Request to merge correspondents."""

    source_ids: list[int]
    target_name: str


class UpdateRequest(BaseModel):
    """Request to update a correspondent."""

    name: str | None = None
    match: str | None = None
    matching_algorithm: int | None = None
    is_insensitive: bool | None = None


class OperationResponse(BaseModel):
    """Generic operation response."""

    success: bool
    message: str
    affected_count: int = 0


def correspondent_to_dict(correspondent: Correspondent) -> dict:
    """Convert Correspondent to dictionary for JSON response."""
    return {
        "id": correspondent.id,
        "name": correspondent.name,
        "slug": correspondent.slug,
        "matching_algorithm": correspondent.matching_algorithm,
        "match_type": correspondent.match_type_name,
        "is_auto": correspondent.is_auto,
        "document_count": correspondent.document_count,
    }


@router.get("", response_model=CorrespondentListResponse)
async def list_correspondents(
    page: int = 1,
    page_size: int = 50,
    filter: str | None = None,
    settings: Settings = Depends(get_settings),
):
    """Get all correspondents with document counts (paginated)."""
    async with PaperlessClient(
        settings.paperless_base_url,
        settings.paperless_api_token,
    ) as client:
        correspondents = await client.get_all_correspondents()

        # Apply filter if provided
        if filter:
            filter_lower = filter.lower()
            correspondents = [c for c in correspondents if filter_lower in c.name.lower()]

        sorted_correspondents = sorted(correspondents, key=lambda x: x.name.lower())

        # Calculate pagination
        total = len(sorted_correspondents)
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 1
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size

        paginated_correspondents = sorted_correspondents[start_idx:end_idx]

        return CorrespondentListResponse(
            correspondents=[correspondent_to_dict(c) for c in paginated_correspondents],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )


@router.get("/low-usage", response_model=CorrespondentListResponse)
async def list_low_usage_correspondents(
    max_docs: int = 0,
    page: int = 1,
    page_size: int = 50,
    settings: Settings = Depends(get_settings),
):
    """Get correspondents with low document counts (candidates for deletion, paginated)."""
    async with PaperlessClient(
        settings.paperless_base_url,
        settings.paperless_api_token,
    ) as client:
        all_correspondents = await client.get_all_correspondents()
        low_usage = find_low_usage_correspondents(
            all_correspondents,
            max_docs=max_docs,
            exclude_patterns=settings.exclude_pattern_list,
        )
        sorted_correspondents = sorted(low_usage, key=lambda x: x.name.lower())

        # Calculate pagination
        total = len(sorted_correspondents)
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 1
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size

        paginated_correspondents = sorted_correspondents[start_idx:end_idx]

        return CorrespondentListResponse(
            correspondents=[correspondent_to_dict(c) for c in paginated_correspondents],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )


@router.get("/merge-suggestions")
async def get_merge_suggestions(
    prefix: str | None = None,
    min_prefix_length: int = 3,
    settings: Settings = Depends(get_settings),
):
    """Get suggested correspondent groups for merging."""
    async with PaperlessClient(
        settings.paperless_base_url,
        settings.paperless_api_token,
    ) as client:
        all_correspondents = await client.get_all_correspondents()

        # Filter by prefix if specified
        if prefix:
            all_correspondents = [
                c for c in all_correspondents if c.name.lower().startswith(prefix.lower())
            ]

        groups = group_correspondents_by_prefix(all_correspondents, min_prefix_length)

        return {
            "groups": {
                prefix: {
                    "correspondents": [correspondent_to_dict(c) for c in correspondents],
                    "total_documents": sum(c.document_count for c in correspondents),
                    "suggested_name": prefix.capitalize(),
                }
                for prefix, correspondents in sorted(groups.items())
            },
            "total_groups": len(groups),
        }


@router.patch("/{correspondent_id}", response_model=OperationResponse)
async def update_correspondent(
    correspondent_id: int,
    request: UpdateRequest,
    settings: Settings = Depends(get_settings),
):
    """Update a correspondent."""
    try:
        async with PaperlessClient(
            settings.paperless_base_url,
            settings.paperless_api_token,
        ) as client:
            # Build update dict with only provided fields
            update_data = {k: v for k, v in request.dict().items() if v is not None}
            if not update_data:
                raise HTTPException(status_code=400, detail="No fields to update")

            await client.update_correspondent(correspondent_id, **update_data)
            return OperationResponse(
                success=True,
                message=f"Updated correspondent successfully",
                affected_count=1,
            )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update correspondent: {str(e)}",
        )


@router.post("/delete", response_model=OperationResponse)
async def delete_correspondents(
    request: DeleteRequest,
    settings: Settings = Depends(get_settings),
):
    """Delete multiple correspondents."""
    if not request.correspondent_ids:
        raise HTTPException(status_code=400, detail="No correspondent IDs provided")

    try:
        async with PaperlessClient(
            settings.paperless_base_url,
            settings.paperless_api_token,
        ) as client:
            await client.bulk_delete_correspondents(request.correspondent_ids)
            return OperationResponse(
                success=True,
                message=f"Deleted {len(request.correspondent_ids)} correspondents",
                affected_count=len(request.correspondent_ids),
            )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete correspondents: {str(e)}",
        )


@router.post("/merge", response_model=OperationResponse)
async def merge_correspondents(
    request: MergeRequest,
    settings: Settings = Depends(get_settings),
):
    """Merge multiple correspondents into a single target correspondent."""
    if not request.source_ids:
        raise HTTPException(status_code=400, detail="No source correspondent IDs provided")
    if not request.target_name:
        raise HTTPException(status_code=400, detail="No target name provided")

    async with PaperlessClient(
        settings.paperless_base_url,
        settings.paperless_api_token,
    ) as client:
        all_correspondents = await client.get_all_correspondents()
        correspondent_map = {c.id: c for c in all_correspondents}

        source_correspondents = [
            correspondent_map[cid] for cid in request.source_ids if cid in correspondent_map
        ]
        if not source_correspondents:
            raise HTTPException(status_code=404, detail="No valid source correspondents found")

        # Find or create target correspondent
        target_correspondent = await client.get_correspondent_by_name(request.target_name)
        if not target_correspondent:
            target_correspondent = await client.create_correspondent(request.target_name)

        # Collect all document IDs from source correspondents
        all_doc_ids = set()
        for correspondent in source_correspondents:
            docs = await client.get_documents_with_correspondent(correspondent.id)
            all_doc_ids.update(d.id for d in docs)

        # Set target correspondent on all documents
        if all_doc_ids:
            await client.set_correspondent_on_documents(list(all_doc_ids), target_correspondent.id)

        # Delete source correspondents (except target if it was one of the sources)
        correspondents_to_delete = [
            c.id for c in source_correspondents if c.id != target_correspondent.id
        ]
        if correspondents_to_delete:
            await client.bulk_delete_correspondents(correspondents_to_delete)

        return OperationResponse(
            success=True,
            message=f"Merged {len(source_correspondents)} correspondents into '{request.target_name}'",
            affected_count=len(all_doc_ids),
        )
