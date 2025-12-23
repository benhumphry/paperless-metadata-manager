"""Tag management endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.paperless_client import (
    PaperlessClient,
    Tag,
    find_low_usage_tags,
    group_tags_by_prefix,
    group_tags_hybrid,
)

router = APIRouter(prefix="/api/tags", tags=["tags"])
templates = Jinja2Templates(directory="app/templates")


class TagListResponse(BaseModel):
    """Response containing list of tags."""

    tags: list[dict]
    total: int
    page: int
    page_size: int
    total_pages: int


class DeleteRequest(BaseModel):
    """Request to delete tags."""

    tag_ids: list[int]


class MergeRequest(BaseModel):
    """Request to merge tags."""

    source_ids: list[int]
    target_name: str


class UpdateRequest(BaseModel):
    """Request to update a tag."""

    name: str | None = None
    color: str | None = None
    match: str | None = None
    matching_algorithm: int | None = None
    is_insensitive: bool | None = None


class MergePreviewResponse(BaseModel):
    """Preview of merge operation."""

    source_tags: list[dict]
    target_name: str
    total_documents: int
    document_ids: list[int]


class OperationResponse(BaseModel):
    """Generic operation response."""

    success: bool
    message: str
    affected_count: int = 0


def tag_to_dict(tag: Tag) -> dict:
    """Convert Tag to dictionary for JSON response."""
    return {
        "id": tag.id,
        "name": tag.name,
        "slug": tag.slug,
        "color": tag.color,
        "matching_algorithm": tag.matching_algorithm,
        "match_type": tag.match_type_name,
        "is_auto": tag.is_auto,
        "document_count": tag.document_count,
    }


@router.get("", response_model=TagListResponse)
async def list_tags(
    page: int = 1,
    page_size: int = 50,
    filter: str | None = None,
    settings: Settings = Depends(get_settings),
):
    """Get all tags with document counts (paginated)."""
    async with PaperlessClient(
        settings.paperless_base_url,
        settings.paperless_api_token,
    ) as client:
        tags = await client.get_all_tags()

        # Apply filter if provided
        if filter:
            filter_lower = filter.lower()
            tags = [t for t in tags if filter_lower in t.name.lower()]

        sorted_tags = sorted(tags, key=lambda x: x.name.lower())

        # Calculate pagination
        total = len(sorted_tags)
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 1
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size

        paginated_tags = sorted_tags[start_idx:end_idx]

        return TagListResponse(
            tags=[tag_to_dict(t) for t in paginated_tags],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )


@router.get("/low-usage", response_model=TagListResponse)
async def list_low_usage_tags(
    max_docs: int = 1,
    page: int = 1,
    page_size: int = 50,
    exclude_auto: bool = True,
    settings: Settings = Depends(get_settings),
):
    """Get tags with low document counts (candidates for deletion, paginated)."""
    async with PaperlessClient(
        settings.paperless_base_url,
        settings.paperless_api_token,
    ) as client:
        all_tags = await client.get_all_tags()
        low_usage = find_low_usage_tags(
            all_tags,
            max_docs=max_docs,
            exclude_patterns=settings.exclude_pattern_list,
            exclude_auto=exclude_auto,
        )
        sorted_tags = sorted(low_usage, key=lambda x: x.name.lower())

        # Calculate pagination
        total = len(sorted_tags)
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 1
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size

        paginated_tags = sorted_tags[start_idx:end_idx]

        return TagListResponse(
            tags=[tag_to_dict(t) for t in paginated_tags],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )


@router.get("/merge-suggestions")
async def get_merge_suggestions(
    prefix: str | None = None,
    min_prefix_length: int = 3,
    similarity_threshold: float = 0.6,
    enable_semantic: bool = True,
    settings: Settings = Depends(get_settings),
):
    """Get suggested tag groups for merging.

    Args:
        prefix: Optional prefix filter to narrow results
        min_prefix_length: Minimum prefix length for prefix-based grouping (default: 3)
        similarity_threshold: Minimum similarity score for semantic grouping (default: 0.6)
        enable_semantic: Whether to enable semantic grouping (default: True)
    """
    async with PaperlessClient(
        settings.paperless_base_url,
        settings.paperless_api_token,
    ) as client:
        all_tags = await client.get_all_tags()

        # Filter by prefix if specified
        if prefix:
            all_tags = [t for t in all_tags if t.name.lower().startswith(prefix.lower())]

        # Use hybrid grouping that combines prefix and semantic matching
        groups = group_tags_hybrid(
            all_tags,
            min_prefix_length=min_prefix_length,
            similarity_threshold=similarity_threshold,
            enable_semantic=enable_semantic,
        )

        return {
            "groups": {
                group_key: {
                    "tags": [tag_to_dict(t) for t in tags],
                    "total_documents": sum(t.document_count for t in tags),
                    "suggested_name": _get_suggested_name(group_key, tags),
                    "group_type": "semantic" if group_key.startswith("semantic:") else "prefix",
                }
                for group_key, tags in sorted(groups.items())
            },
            "total_groups": len(groups),
        }


def _get_suggested_name(group_key: str, tags: list[Tag]) -> str:
    """Generate a suggested merge name based on group type and tags.

    Args:
        group_key: The group key (e.g., 'prefix:account' or 'semantic:expense')
        tags: List of tags in the group

    Returns:
        Suggested name for merging these tags
    """
    if group_key.startswith("prefix:"):
        # For prefix groups, capitalize the prefix
        return group_key.replace("prefix:", "").capitalize()
    elif group_key.startswith("semantic:"):
        # For semantic groups, use the representative word capitalized
        return group_key.replace("semantic:", "").capitalize()
    else:
        # Fallback: use most common tag name
        return max(tags, key=lambda t: t.document_count).name if tags else group_key


@router.patch("/{tag_id}", response_model=OperationResponse)
async def update_tag(
    tag_id: int,
    request: UpdateRequest,
    settings: Settings = Depends(get_settings),
):
    """Update a tag."""
    try:
        async with PaperlessClient(
            settings.paperless_base_url,
            settings.paperless_api_token,
        ) as client:
            # Build update dict with only provided fields
            update_data = {k: v for k, v in request.dict().items() if v is not None}
            if not update_data:
                raise HTTPException(status_code=400, detail="No fields to update")

            await client.update_tag(tag_id, **update_data)
            return OperationResponse(
                success=True,
                message=f"Updated tag successfully",
                affected_count=1,
            )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update tag: {str(e)}",
        )


@router.post("/delete", response_model=OperationResponse)
async def delete_tags(
    request: DeleteRequest,
    settings: Settings = Depends(get_settings),
):
    """Delete multiple tags."""
    if not request.tag_ids:
        raise HTTPException(status_code=400, detail="No tag IDs provided")

    try:
        async with PaperlessClient(
            settings.paperless_base_url,
            settings.paperless_api_token,
        ) as client:
            await client.bulk_delete_tags(request.tag_ids)
            return OperationResponse(
                success=True,
                message=f"Deleted {len(request.tag_ids)} tags",
                affected_count=len(request.tag_ids),
            )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete tags: {str(e)}",
        )


@router.post("/merge/preview", response_model=MergePreviewResponse)
async def preview_merge(
    request: MergeRequest,
    settings: Settings = Depends(get_settings),
):
    """Preview a merge operation before executing."""
    if not request.source_ids:
        raise HTTPException(status_code=400, detail="No source tag IDs provided")
    if not request.target_name:
        raise HTTPException(status_code=400, detail="No target name provided")

    async with PaperlessClient(
        settings.paperless_base_url,
        settings.paperless_api_token,
    ) as client:
        all_tags = await client.get_all_tags()
        tag_map = {t.id: t for t in all_tags}

        source_tags = [tag_map[tid] for tid in request.source_ids if tid in tag_map]
        if not source_tags:
            raise HTTPException(status_code=404, detail="No valid source tags found")

        # Collect all document IDs
        all_doc_ids = set()
        for tag in source_tags:
            docs = await client.get_documents_with_tag(tag.id)
            all_doc_ids.update(d.id for d in docs)

        return MergePreviewResponse(
            source_tags=[tag_to_dict(t) for t in source_tags],
            target_name=request.target_name,
            total_documents=len(all_doc_ids),
            document_ids=list(all_doc_ids),
        )


@router.post("/merge", response_model=OperationResponse)
async def merge_tags(
    request: MergeRequest,
    settings: Settings = Depends(get_settings),
):
    """Merge multiple tags into a single target tag."""
    if not request.source_ids:
        raise HTTPException(status_code=400, detail="No source tag IDs provided")
    if not request.target_name:
        raise HTTPException(status_code=400, detail="No target name provided")

    async with PaperlessClient(
        settings.paperless_base_url,
        settings.paperless_api_token,
    ) as client:
        all_tags = await client.get_all_tags()
        tag_map = {t.id: t for t in all_tags}

        source_tags = [tag_map[tid] for tid in request.source_ids if tid in tag_map]
        if not source_tags:
            raise HTTPException(status_code=404, detail="No valid source tags found")

        # Find or create target tag
        target_tag = await client.get_tag_by_name(request.target_name)
        if not target_tag:
            target_tag = await client.create_tag(request.target_name)

        # Collect all document IDs from source tags
        all_doc_ids = set()
        for tag in source_tags:
            docs = await client.get_documents_with_tag(tag.id)
            all_doc_ids.update(d.id for d in docs)

        # Add target tag to all documents
        if all_doc_ids:
            await client.add_tag_to_documents(list(all_doc_ids), target_tag.id)

        # Delete source tags (except target if it was one of the sources)
        tags_to_delete = [t.id for t in source_tags if t.id != target_tag.id]
        if tags_to_delete:
            await client.bulk_delete_tags(tags_to_delete)

        return OperationResponse(
            success=True,
            message=f"Merged {len(source_tags)} tags into '{request.target_name}'",
            affected_count=len(all_doc_ids),
        )
