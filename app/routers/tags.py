"""Tag management endpoints."""

from app.paperless_client import (
    Tag,
    find_low_usage_tags,
)
from app.routers.base import MetadataRouter


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


# Create the router using the shared base
_metadata_router = MetadataRouter(
    prefix="tags",
    tag="tag",
    item_key="tags",
    id_key="tag_ids",
    to_dict=tag_to_dict,
    get_all=lambda client: client.get_all_tags(),
    find_low_usage=find_low_usage_tags,
    get_by_name=lambda client, name: client.get_tag_by_name(name),
    create=lambda client, name: client.create_tag(name),
    update=lambda client, id, **kwargs: client.update_tag(id, **kwargs),
    bulk_delete=lambda client, ids: client.bulk_delete_tags(ids),
    get_documents=lambda client, id: client.get_documents_with_tag(id),
    set_on_documents=lambda client, doc_ids, id: client.add_tag_to_documents(doc_ids, id),
    has_color=True,
)

router = _metadata_router.router
