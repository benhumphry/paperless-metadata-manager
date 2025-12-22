"""Document type management endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.paperless_client import (
    DocumentType,
    PaperlessClient,
    find_low_usage_document_types,
    group_document_types_by_prefix,
)

router = APIRouter(prefix="/api/document_types", tags=["document_types"])


class DocumentTypeListResponse(BaseModel):
    """Response containing list of document types."""

    document_types: list[dict]
    total: int
    page: int
    page_size: int
    total_pages: int


class DeleteRequest(BaseModel):
    """Request to delete document types."""

    document_type_ids: list[int]


class MergeRequest(BaseModel):
    """Request to merge document types."""

    source_ids: list[int]
    target_name: str


class UpdateRequest(BaseModel):
    """Request to update a document type."""

    name: str | None = None
    match: str | None = None
    matching_algorithm: int | None = None
    is_insensitive: bool | None = None


class MergePreviewResponse(BaseModel):
    """Preview of merge operation."""

    source_document_types: list[dict]
    target_name: str
    total_documents: int
    document_ids: list[int]


class OperationResponse(BaseModel):
    """Generic operation response."""

    success: bool
    message: str
    affected_count: int = 0


def document_type_to_dict(document_type: DocumentType) -> dict:
    """Convert DocumentType to dictionary for JSON response."""
    return {
        "id": document_type.id,
        "name": document_type.name,
        "slug": document_type.slug,
        "matching_algorithm": document_type.matching_algorithm,
        "match_type": document_type.match_type_name,
        "is_auto": document_type.is_auto,
        "document_count": document_type.document_count,
    }


@router.get("", response_model=DocumentTypeListResponse)
async def list_document_types(
    page: int = 1,
    page_size: int = 50,
    filter: str | None = None,
    settings: Settings = Depends(get_settings),
):
    """Get all document types with document counts (paginated)."""
    async with PaperlessClient(
        settings.paperless_base_url,
        settings.paperless_api_token,
    ) as client:
        document_types = await client.get_all_document_types()

        # Apply filter if provided
        if filter:
            filter_lower = filter.lower()
            document_types = [dt for dt in document_types if filter_lower in dt.name.lower()]

        sorted_document_types = sorted(document_types, key=lambda x: x.name.lower())

        # Calculate pagination
        total = len(sorted_document_types)
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 1
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size

        paginated_document_types = sorted_document_types[start_idx:end_idx]

        return DocumentTypeListResponse(
            document_types=[document_type_to_dict(dt) for dt in paginated_document_types],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )


@router.get("/low-usage", response_model=DocumentTypeListResponse)
async def list_low_usage_document_types(
    max_docs: int = 0,
    page: int = 1,
    page_size: int = 50,
    exclude_auto: bool = True,
    settings: Settings = Depends(get_settings),
):
    """Get document types with low document counts (candidates for deletion, paginated)."""
    async with PaperlessClient(
        settings.paperless_base_url,
        settings.paperless_api_token,
    ) as client:
        all_document_types = await client.get_all_document_types()
        low_usage = find_low_usage_document_types(
            all_document_types,
            max_docs=max_docs,
            exclude_patterns=settings.exclude_pattern_list,
            exclude_auto=exclude_auto,
        )
        sorted_document_types = sorted(low_usage, key=lambda x: x.name.lower())

        # Calculate pagination
        total = len(sorted_document_types)
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 1
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size

        paginated_document_types = sorted_document_types[start_idx:end_idx]

        return DocumentTypeListResponse(
            document_types=[document_type_to_dict(dt) for dt in paginated_document_types],
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
    """Get suggested document type groups for merging."""
    async with PaperlessClient(
        settings.paperless_base_url,
        settings.paperless_api_token,
    ) as client:
        all_document_types = await client.get_all_document_types()

        # Filter by prefix if specified
        if prefix:
            all_document_types = [
                dt for dt in all_document_types if dt.name.lower().startswith(prefix.lower())
            ]

        groups = group_document_types_by_prefix(all_document_types, min_prefix_length)

        return {
            "groups": {
                prefix: {
                    "document_types": [document_type_to_dict(dt) for dt in document_types],
                    "total_documents": sum(dt.document_count for dt in document_types),
                    "suggested_name": prefix.capitalize(),
                }
                for prefix, document_types in sorted(groups.items())
            },
            "total_groups": len(groups),
        }


@router.patch("/{document_type_id}", response_model=OperationResponse)
async def update_document_type(
    document_type_id: int,
    request: UpdateRequest,
    settings: Settings = Depends(get_settings),
):
    """Update a document type."""
    try:
        async with PaperlessClient(
            settings.paperless_base_url,
            settings.paperless_api_token,
        ) as client:
            # Build update dict with only provided fields
            update_data = {k: v for k, v in request.dict().items() if v is not None}
            if not update_data:
                raise HTTPException(status_code=400, detail="No fields to update")

            await client.update_document_type(document_type_id, **update_data)
            return OperationResponse(
                success=True,
                message=f"Updated document type successfully",
                affected_count=1,
            )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update document type: {str(e)}",
        )


@router.post("/delete", response_model=OperationResponse)
async def delete_document_types(
    request: DeleteRequest,
    settings: Settings = Depends(get_settings),
):
    """Delete multiple document types."""
    if not request.document_type_ids:
        raise HTTPException(status_code=400, detail="No document type IDs provided")

    try:
        async with PaperlessClient(
            settings.paperless_base_url,
            settings.paperless_api_token,
        ) as client:
            await client.bulk_delete_document_types(request.document_type_ids)
            return OperationResponse(
                success=True,
                message=f"Deleted {len(request.document_type_ids)} document types",
                affected_count=len(request.document_type_ids),
            )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete document types: {str(e)}",
        )


@router.post("/merge/preview", response_model=MergePreviewResponse)
async def preview_merge(
    request: MergeRequest,
    settings: Settings = Depends(get_settings),
):
    """Preview a merge operation before executing."""
    if not request.source_ids:
        raise HTTPException(status_code=400, detail="No source document type IDs provided")
    if not request.target_name:
        raise HTTPException(status_code=400, detail="No target name provided")

    async with PaperlessClient(
        settings.paperless_base_url,
        settings.paperless_api_token,
    ) as client:
        all_document_types = await client.get_all_document_types()
        document_type_map = {dt.id: dt for dt in all_document_types}

        source_document_types = [
            document_type_map[dtid] for dtid in request.source_ids if dtid in document_type_map
        ]
        if not source_document_types:
            raise HTTPException(status_code=404, detail="No valid source document types found")

        # Collect all document IDs
        all_doc_ids = set()
        for document_type in source_document_types:
            docs = await client.get_documents_with_document_type(document_type.id)
            all_doc_ids.update(d.id for d in docs)

        return MergePreviewResponse(
            source_document_types=[document_type_to_dict(dt) for dt in source_document_types],
            target_name=request.target_name,
            total_documents=len(all_doc_ids),
            document_ids=list(all_doc_ids),
        )


@router.post("/merge", response_model=OperationResponse)
async def merge_document_types(
    request: MergeRequest,
    settings: Settings = Depends(get_settings),
):
    """Merge multiple document types into a single target document type."""
    if not request.source_ids:
        raise HTTPException(status_code=400, detail="No source document type IDs provided")
    if not request.target_name:
        raise HTTPException(status_code=400, detail="No target name provided")

    async with PaperlessClient(
        settings.paperless_base_url,
        settings.paperless_api_token,
    ) as client:
        all_document_types = await client.get_all_document_types()
        document_type_map = {dt.id: dt for dt in all_document_types}

        source_document_types = [
            document_type_map[dtid] for dtid in request.source_ids if dtid in document_type_map
        ]
        if not source_document_types:
            raise HTTPException(status_code=404, detail="No valid source document types found")

        # Find or create target document type
        target_document_type = await client.get_document_type_by_name(request.target_name)
        if not target_document_type:
            target_document_type = await client.create_document_type(request.target_name)

        # Collect all document IDs from source document types
        all_doc_ids = set()
        for document_type in source_document_types:
            docs = await client.get_documents_with_document_type(document_type.id)
            all_doc_ids.update(d.id for d in docs)

        # Set target document type on all documents
        if all_doc_ids:
            await client.set_document_type_on_documents(list(all_doc_ids), target_document_type.id)

        # Delete source document types (except target if it was one of the sources)
        document_types_to_delete = [
            dt.id for dt in source_document_types if dt.id != target_document_type.id
        ]
        if document_types_to_delete:
            await client.bulk_delete_document_types(document_types_to_delete)

        return OperationResponse(
            success=True,
            message=f"Merged {len(source_document_types)} document types into '{request.target_name}'",
            affected_count=len(all_doc_ids),
        )
