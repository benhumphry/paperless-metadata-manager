"""Correspondent management endpoints."""

from app.paperless_client import (
    Correspondent,
    find_low_usage_correspondents,
)
from app.routers.base import MetadataRouter


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


# Create the router using the shared base
_metadata_router = MetadataRouter(
    prefix="correspondents",
    tag="correspondent",
    item_key="correspondents",
    id_key="correspondent_ids",
    to_dict=correspondent_to_dict,
    get_all=lambda client: client.get_all_correspondents(),
    find_low_usage=find_low_usage_correspondents,
    get_by_name=lambda client, name: client.get_correspondent_by_name(name),
    create=lambda client, name: client.create_correspondent(name),
    update=lambda client, id, **kwargs: client.update_correspondent(id, **kwargs),
    bulk_delete=lambda client, ids: client.bulk_delete_correspondents(ids),
    get_documents=lambda client, id: client.get_documents_with_correspondent(id),
    set_on_documents=lambda client, doc_ids, id: client.set_correspondent_on_documents(doc_ids, id),
    has_color=False,
)

router = _metadata_router.router
