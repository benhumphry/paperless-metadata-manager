"""Base classes and utilities for metadata routers."""

from typing import Any, Callable, Generic, TypeVar

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.paperless_client import PaperlessClient

T = TypeVar("T")


class ListResponse(BaseModel):
    """Generic paginated list response."""

    items: list[dict]
    total: int
    page: int
    page_size: int
    total_pages: int


class DeleteRequest(BaseModel):
    """Request to delete items."""

    ids: list[int]


class MergeRequest(BaseModel):
    """Request to merge items."""

    source_ids: list[int]
    target_name: str


class UpdateRequest(BaseModel):
    """Request to update an item."""

    name: str | None = None
    color: str | None = None  # Only used by tags
    match: str | None = None
    matching_algorithm: int | None = None
    is_insensitive: bool | None = None


class MergePreviewResponse(BaseModel):
    """Preview of merge operation."""

    source_items: list[dict]
    target_name: str
    total_documents: int
    document_ids: list[int]


class OperationResponse(BaseModel):
    """Generic operation response."""

    success: bool
    message: str
    affected_count: int = 0


def paginate(items: list, page: int, page_size: int) -> tuple[list, int, int]:
    """Paginate a list of items.

    Returns: (paginated_items, total, total_pages)
    """
    total = len(items)
    total_pages = (total + page_size - 1) // page_size if page_size > 0 else 1
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    return items[start_idx:end_idx], total, total_pages


class MetadataRouter(Generic[T]):
    """Factory for creating metadata CRUD routers with shared logic."""

    def __init__(
        self,
        prefix: str,
        tag: str,
        item_key: str,
        id_key: str,
        to_dict: Callable[[T], dict],
        get_all: Callable[[PaperlessClient], Any],
        find_low_usage: Callable[..., list[T]],
        get_by_name: Callable[[PaperlessClient, str], Any],
        create: Callable[[PaperlessClient, str], Any],
        update: Callable[[PaperlessClient, int, dict], Any],
        bulk_delete: Callable[[PaperlessClient, list[int]], Any],
        get_documents: Callable[[PaperlessClient, int], Any],
        set_on_documents: Callable[[PaperlessClient, list[int], int], Any],
        has_color: bool = False,
    ):
        self.prefix = prefix
        self.tag = tag
        self.item_key = item_key
        self.id_key = id_key
        self.to_dict = to_dict
        self.get_all = get_all
        self.find_low_usage = find_low_usage
        self.get_by_name = get_by_name
        self.create = create
        self.update = update
        self.bulk_delete = bulk_delete
        self.get_documents = get_documents
        self.set_on_documents = set_on_documents
        self.has_color = has_color

        self.router = APIRouter(prefix=f"/api/{prefix}", tags=[prefix])
        self._register_routes()

    def _register_routes(self):
        """Register all routes on the router."""

        @self.router.get("")
        async def list_items(
            page: int = 1,
            page_size: int = 50,
            filter: str | None = None,
            settings: Settings = Depends(get_settings),
        ):
            """Get all items with document counts (paginated)."""
            async with PaperlessClient(
                settings.paperless_base_url,
                settings.paperless_api_token,
            ) as client:
                items = await self.get_all(client)

                if filter:
                    filter_lower = filter.lower()
                    items = [i for i in items if filter_lower in i.name.lower()]

                sorted_items = sorted(items, key=lambda x: x.name.lower())
                paginated, total, total_pages = paginate(sorted_items, page, page_size)

                return {
                    self.item_key: [self.to_dict(i) for i in paginated],
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "total_pages": total_pages,
                }

        @self.router.get("/all")
        async def list_all_items(
            settings: Settings = Depends(get_settings),
        ):
            """Get all items without pagination (for client-side processing)."""
            async with PaperlessClient(
                settings.paperless_base_url,
                settings.paperless_api_token,
            ) as client:
                items = await self.get_all(client)
                sorted_items = sorted(items, key=lambda x: x.name.lower())
                return {
                    self.item_key: [self.to_dict(i) for i in sorted_items],
                    "total": len(sorted_items),
                    "llm_enabled": settings.llm_enabled,
                }

        @self.router.post("/llm-groups")
        async def get_llm_groups(
            settings: Settings = Depends(get_settings),
        ):
            """Get semantic groupings using LLM."""
            if not settings.llm_enabled:
                raise HTTPException(
                    status_code=400,
                    detail="LLM is not configured. Set LLM_TYPE and LLM_API_TOKEN in environment.",
                )

            from app.llm_client import LLMClient

            async with PaperlessClient(
                settings.paperless_base_url,
                settings.paperless_api_token,
            ) as client:
                items = await self.get_all(client)
                item_names = [i.name for i in items]

                llm = LLMClient(
                    llm_type=settings.llm_type,
                    api_url=settings.llm_api_url,
                    api_token=settings.llm_api_token,
                    model=settings.llm_model,
                )

                try:
                    groups = await llm.get_semantic_groups(item_names, self.item_key)
                except Exception as e:
                    raise HTTPException(
                        status_code=500,
                        detail=f"LLM request failed: {str(e)}",
                    )

                import logging

                logger = logging.getLogger(__name__)
                logger.info(f"LLM returned {len(groups)} groups: {list(groups.keys())}")
                for gname, gnames in groups.items():
                    logger.info(f"  Group '{gname}': {gnames}")

                # Build response with item details
                item_map = {i.name: i for i in items}
                result = {}
                for group_name, names in groups.items():
                    group_items = []
                    for name in names:
                        if name in item_map:
                            group_items.append(self.to_dict(item_map[name]))
                        else:
                            logger.warning(f"  LLM returned name '{name}' not found in items")
                    if len(group_items) >= 2:
                        result[group_name] = {
                            self.item_key: group_items,
                            "total_documents": sum(i["document_count"] for i in group_items),
                            "suggested_name": group_name,
                            "group_type": "llm",
                        }

                return {
                    "groups": result,
                    "total_groups": len(result),
                }

        @self.router.get("/low-usage")
        async def list_low_usage_items(
            max_docs: int = 0,
            page: int = 1,
            page_size: int = 50,
            exclude_auto: bool = True,
            settings: Settings = Depends(get_settings),
        ):
            """Get items with low document counts (candidates for deletion, paginated)."""
            async with PaperlessClient(
                settings.paperless_base_url,
                settings.paperless_api_token,
            ) as client:
                all_items = await self.get_all(client)
                low_usage = self.find_low_usage(
                    all_items,
                    max_docs=max_docs,
                    exclude_patterns=settings.exclude_pattern_list,
                    exclude_auto=exclude_auto,
                )
                sorted_items = sorted(low_usage, key=lambda x: x.name.lower())
                paginated, total, total_pages = paginate(sorted_items, page, page_size)

                return {
                    self.item_key: [self.to_dict(i) for i in paginated],
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "total_pages": total_pages,
                }

        @self.router.patch("/{item_id}", response_model=OperationResponse)
        async def update_item(
            item_id: int,
            request: UpdateRequest,
            settings: Settings = Depends(get_settings),
        ):
            """Update an item."""
            try:
                async with PaperlessClient(
                    settings.paperless_base_url,
                    settings.paperless_api_token,
                ) as client:
                    update_data = {k: v for k, v in request.dict().items() if v is not None}
                    # Remove color for non-tag items
                    if not self.has_color and "color" in update_data:
                        del update_data["color"]
                    if not update_data:
                        raise HTTPException(status_code=400, detail="No fields to update")

                    await self.update(client, item_id, **update_data)
                    return OperationResponse(
                        success=True,
                        message=f"Updated {self.tag} successfully",
                        affected_count=1,
                    )
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to update {self.tag}: {str(e)}",
                )

        @self.router.post("/delete", response_model=OperationResponse)
        async def delete_items(
            request: DeleteRequest,
            settings: Settings = Depends(get_settings),
        ):
            """Delete multiple items."""
            if not request.ids:
                raise HTTPException(status_code=400, detail=f"No {self.tag} IDs provided")

            try:
                async with PaperlessClient(
                    settings.paperless_base_url,
                    settings.paperless_api_token,
                ) as client:
                    await self.bulk_delete(client, request.ids)
                    return OperationResponse(
                        success=True,
                        message=f"Deleted {len(request.ids)} {self.tag}s",
                        affected_count=len(request.ids),
                    )
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to delete {self.tag}s: {str(e)}",
                )

        @self.router.post("/merge/preview", response_model=MergePreviewResponse)
        async def preview_merge(
            request: MergeRequest,
            settings: Settings = Depends(get_settings),
        ):
            """Preview a merge operation before executing."""
            if not request.source_ids:
                raise HTTPException(status_code=400, detail=f"No source {self.tag} IDs provided")
            if not request.target_name:
                raise HTTPException(status_code=400, detail="No target name provided")

            async with PaperlessClient(
                settings.paperless_base_url,
                settings.paperless_api_token,
            ) as client:
                all_items = await self.get_all(client)
                item_map = {i.id: i for i in all_items}

                source_items = [item_map[sid] for sid in request.source_ids if sid in item_map]
                if not source_items:
                    raise HTTPException(
                        status_code=404, detail=f"No valid source {self.tag}s found"
                    )

                all_doc_ids = set()
                for item in source_items:
                    docs = await self.get_documents(client, item.id)
                    all_doc_ids.update(d.id for d in docs)

                return MergePreviewResponse(
                    source_items=[self.to_dict(i) for i in source_items],
                    target_name=request.target_name,
                    total_documents=len(all_doc_ids),
                    document_ids=list(all_doc_ids),
                )

        @self.router.post("/merge", response_model=OperationResponse)
        async def merge_items(
            request: MergeRequest,
            settings: Settings = Depends(get_settings),
        ):
            """Merge multiple items into a single target."""
            if not request.source_ids:
                raise HTTPException(status_code=400, detail=f"No source {self.tag} IDs provided")
            if not request.target_name:
                raise HTTPException(status_code=400, detail="No target name provided")

            async with PaperlessClient(
                settings.paperless_base_url,
                settings.paperless_api_token,
            ) as client:
                all_items = await self.get_all(client)
                item_map = {i.id: i for i in all_items}

                source_items = [item_map[sid] for sid in request.source_ids if sid in item_map]
                if not source_items:
                    raise HTTPException(
                        status_code=404, detail=f"No valid source {self.tag}s found"
                    )

                # Find or create target
                target = await self.get_by_name(client, request.target_name)
                if not target:
                    target = await self.create(client, request.target_name)

                # Collect all document IDs
                all_doc_ids = set()
                for item in source_items:
                    docs = await self.get_documents(client, item.id)
                    all_doc_ids.update(d.id for d in docs)

                # Set target on all documents
                if all_doc_ids:
                    await self.set_on_documents(client, list(all_doc_ids), target.id)

                # Delete source items (except target if it was one of the sources)
                items_to_delete = [i.id for i in source_items if i.id != target.id]
                if items_to_delete:
                    await self.bulk_delete(client, items_to_delete)

                return OperationResponse(
                    success=True,
                    message=f"Merged {len(source_items)} {self.tag}s into '{request.target_name}'",
                    affected_count=len(all_doc_ids),
                )
