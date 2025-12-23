"""Document type management endpoints."""

from app.paperless_client import (
    DocumentType,
    find_low_usage_document_types,
)
from app.routers.base import MetadataRouter


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


# Create the router using the shared base
_metadata_router = MetadataRouter(
    prefix="document_types",
    tag="document type",
    item_key="document_types",
    id_key="document_type_ids",
    to_dict=document_type_to_dict,
    get_all=lambda client: client.get_all_document_types(),
    find_low_usage=find_low_usage_document_types,
    get_by_name=lambda client, name: client.get_document_type_by_name(name),
    create=lambda client, name: client.create_document_type(name),
    update=lambda client, id, **kwargs: client.update_document_type(id, **kwargs),
    bulk_delete=lambda client, ids: client.bulk_delete_document_types(ids),
    get_documents=lambda client, id: client.get_documents_with_document_type(id),
    set_on_documents=lambda client, doc_ids, id: client.set_document_type_on_documents(doc_ids, id),
    has_color=False,
)

router = _metadata_router.router
