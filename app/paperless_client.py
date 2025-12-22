"""Async client for Paperless-ngx REST API."""

import re
from dataclasses import dataclass
from typing import AsyncIterator

import httpx


@dataclass
class Tag:
    """Represents a Paperless-ngx tag."""

    id: int
    name: str
    slug: str
    color: str
    matching_algorithm: int
    match: str
    is_insensitive: bool
    document_count: int

    @property
    def match_type_name(self) -> str:
        """Human-readable matching algorithm name."""
        names = {
            0: "None",
            1: "Any",
            2: "All",
            3: "Literal",
            4: "Regex",
            5: "Fuzzy",
            6: "Auto",
        }
        return names.get(self.matching_algorithm, str(self.matching_algorithm))

    @property
    def is_auto(self) -> bool:
        """Check if tag uses automatic matching."""
        return self.matching_algorithm == 6


@dataclass
class Correspondent:
    """Represents a Paperless-ngx correspondent."""

    id: int
    name: str
    slug: str
    matching_algorithm: int
    match: str
    is_insensitive: bool
    document_count: int

    @property
    def match_type_name(self) -> str:
        """Human-readable matching algorithm name."""
        names = {
            0: "None",
            1: "Any",
            2: "All",
            3: "Literal",
            4: "Regex",
            5: "Fuzzy",
            6: "Auto",
        }
        return names.get(self.matching_algorithm, str(self.matching_algorithm))

    @property
    def is_auto(self) -> bool:
        """Check if correspondent uses automatic matching."""
        return self.matching_algorithm == 6


@dataclass
class Document:
    """Represents a Paperless-ngx document (minimal info)."""

    id: int
    title: str


@dataclass
class PaperlessInfo:
    """Paperless-ngx instance information."""

    version: str
    api_version: int


class PaperlessClient:
    """Async client for Paperless-ngx API operations."""

    def __init__(self, base_url: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Token {api_token}",
                "Content-Type": "application/json",
            },
            timeout=120.0,  # Increased timeout for bulk operations
        )

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def test_connection(self) -> PaperlessInfo:
        """Test connection and get Paperless info."""
        # Use /api/tags/ instead of /api/ to avoid redirect
        resp = await self.client.get("/api/tags/?page_size=1")
        resp.raise_for_status()
        # Return basic info since the tags endpoint doesn't provide version
        return PaperlessInfo(
            version="connected",
            api_version=1,
        )

    async def get_all_tags(self) -> list[Tag]:
        """Fetch all tags with document counts."""
        tags = []
        url = "/api/tags/?page_size=100"

        while url:
            resp = await self.client.get(url)
            resp.raise_for_status()
            data = resp.json()

            for t in data.get("results", []):
                tags.append(
                    Tag(
                        id=t["id"],
                        name=t["name"],
                        slug=t.get("slug", ""),
                        color=t.get("color", "#a6cee3"),
                        matching_algorithm=t.get("matching_algorithm", 0),
                        match=t.get("match", ""),
                        is_insensitive=t.get("is_insensitive", True),
                        document_count=t.get("document_count", 0),
                    )
                )

            # Handle pagination - next URL may be absolute or relative
            next_url = data.get("next")
            if next_url:
                if next_url.startswith("http"):
                    # Extract path from absolute URL
                    url = next_url.replace(self.base_url, "")
                else:
                    url = next_url
            else:
                url = None

        return tags

    async def get_documents_with_tag(self, tag_id: int) -> list[Document]:
        """Get all documents that have a specific tag."""
        docs = []
        url = f"/api/documents/?tags__id__in={tag_id}&page_size=100"

        while url:
            resp = await self.client.get(url)
            resp.raise_for_status()
            data = resp.json()

            for d in data.get("results", []):
                docs.append(Document(id=d["id"], title=d.get("title", "")))

            next_url = data.get("next")
            if next_url:
                if next_url.startswith("http"):
                    url = next_url.replace(self.base_url, "")
                else:
                    url = next_url
            else:
                url = None

        return docs

    async def add_tag_to_documents(self, doc_ids: list[int], tag_id: int) -> None:
        """Add a tag to multiple documents."""
        if not doc_ids:
            return

        resp = await self.client.post(
            "/api/documents/bulk_edit/",
            json={
                "documents": doc_ids,
                "method": "add_tag",
                "parameters": {"tag": tag_id},
            },
        )
        resp.raise_for_status()

    async def delete_tag(self, tag_id: int) -> None:
        """Delete a single tag."""
        resp = await self.client.delete(f"/api/tags/{tag_id}/")
        resp.raise_for_status()

    async def bulk_delete_tags(self, tag_ids: list[int]) -> None:
        """Delete multiple tags at once."""
        if not tag_ids:
            return

        # Try bulk delete first
        try:
            resp = await self.client.post(
                "/api/bulk_edit_objects/",
                json={
                    "objects": tag_ids,
                    "object_type": "tags",
                    "operation": "delete",
                },
            )
            resp.raise_for_status()
            return
        except httpx.HTTPStatusError as e:
            # If bulk endpoint doesn't exist (404), fall back to individual deletes
            if e.response.status_code == 404:
                # Delete in batches to avoid overwhelming the API
                batch_size = 10
                for i in range(0, len(tag_ids), batch_size):
                    batch = tag_ids[i : i + batch_size]
                    for tag_id in batch:
                        try:
                            await self.delete_tag(tag_id)
                        except Exception as delete_error:
                            # Log but continue with other deletions
                            print(f"Failed to delete tag {tag_id}: {delete_error}")
                return

            # For other errors, try to get details
            try:
                error_detail = e.response.json()
            except Exception:
                error_detail = e.response.text
            raise Exception(
                f"Paperless API error (status {e.response.status_code}): {error_detail}"
            )
        except httpx.TimeoutException:
            raise Exception(
                f"Operation timed out while deleting {len(tag_ids)} tags. "
                "The tags may still be deleted - please refresh to verify."
            )
        except Exception as e:
            if "bulk_delete_tags" not in str(e):
                raise Exception(f"Failed to delete tags: {str(e)}")
            raise

    async def create_tag(self, name: str, **kwargs) -> Tag:
        """Create a new tag."""
        data = {"name": name, **kwargs}
        resp = await self.client.post("/api/tags/", json=data)
        resp.raise_for_status()
        t = resp.json()
        return Tag(
            id=t["id"],
            name=t["name"],
            slug=t.get("slug", ""),
            color=t.get("color", "#a6cee3"),
            matching_algorithm=t.get("matching_algorithm", 0),
            match=t.get("match", ""),
            is_insensitive=t.get("is_insensitive", True),
            document_count=t.get("document_count", 0),
        )

    async def update_tag(self, tag_id: int, **kwargs) -> Tag:
        """Update an existing tag."""
        resp = await self.client.patch(f"/api/tags/{tag_id}/", json=kwargs)
        resp.raise_for_status()
        t = resp.json()
        return Tag(
            id=t["id"],
            name=t["name"],
            slug=t.get("slug", ""),
            color=t.get("color", "#a6cee3"),
            matching_algorithm=t.get("matching_algorithm", 0),
            match=t.get("match", ""),
            is_insensitive=t.get("is_insensitive", True),
            document_count=t.get("document_count", 0),
        )

    async def get_tag_by_name(self, name: str) -> Tag | None:
        """Find a tag by exact name (case-insensitive)."""
        resp = await self.client.get(f"/api/tags/?name__iexact={name}")
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if results:
            t = results[0]
            return Tag(
                id=t["id"],
                name=t["name"],
                slug=t.get("slug", ""),
                color=t.get("color", "#a6cee3"),
                matching_algorithm=t.get("matching_algorithm", 0),
                match=t.get("match", ""),
                is_insensitive=t.get("is_insensitive", True),
                document_count=t.get("document_count", 0),
            )
        return None

    async def get_all_correspondents(self) -> list[Correspondent]:
        """Fetch all correspondents with document counts."""
        correspondents = []
        url = "/api/correspondents/?page_size=100"

        while url:
            resp = await self.client.get(url)
            resp.raise_for_status()
            data = resp.json()

            for c in data.get("results", []):
                correspondents.append(
                    Correspondent(
                        id=c["id"],
                        name=c["name"],
                        slug=c.get("slug", ""),
                        matching_algorithm=c.get("matching_algorithm", 0),
                        match=c.get("match", ""),
                        is_insensitive=c.get("is_insensitive", True),
                        document_count=c.get("document_count", 0),
                    )
                )

            next_url = data.get("next")
            if next_url:
                if next_url.startswith("http"):
                    url = next_url.replace(self.base_url, "")
                else:
                    url = next_url
            else:
                url = None

        return correspondents

    async def get_documents_with_correspondent(self, correspondent_id: int) -> list[Document]:
        """Get all documents that have a specific correspondent."""
        docs = []
        url = f"/api/documents/?correspondent__id={correspondent_id}&page_size=100"

        while url:
            resp = await self.client.get(url)
            resp.raise_for_status()
            data = resp.json()

            for d in data.get("results", []):
                docs.append(Document(id=d["id"], title=d.get("title", "")))

            next_url = data.get("next")
            if next_url:
                if next_url.startswith("http"):
                    url = next_url.replace(self.base_url, "")
                else:
                    url = next_url
            else:
                url = None

        return docs

    async def delete_correspondent(self, correspondent_id: int) -> None:
        """Delete a single correspondent."""
        resp = await self.client.delete(f"/api/correspondents/{correspondent_id}/")
        resp.raise_for_status()

    async def bulk_delete_correspondents(self, correspondent_ids: list[int]) -> None:
        """Delete multiple correspondents at once."""
        if not correspondent_ids:
            return

        # Try bulk delete first
        try:
            resp = await self.client.post(
                "/api/bulk_edit_objects/",
                json={
                    "objects": correspondent_ids,
                    "object_type": "correspondents",
                    "operation": "delete",
                },
            )
            resp.raise_for_status()
            return
        except httpx.HTTPStatusError as e:
            # If bulk endpoint doesn't exist (404), fall back to individual deletes
            if e.response.status_code == 404:
                batch_size = 10
                for i in range(0, len(correspondent_ids), batch_size):
                    batch = correspondent_ids[i : i + batch_size]
                    for correspondent_id in batch:
                        try:
                            await self.delete_correspondent(correspondent_id)
                        except Exception as delete_error:
                            print(
                                f"Failed to delete correspondent {correspondent_id}: {delete_error}"
                            )
                return

            try:
                error_detail = e.response.json()
            except Exception:
                error_detail = e.response.text
            raise Exception(
                f"Paperless API error (status {e.response.status_code}): {error_detail}"
            )
        except httpx.TimeoutException:
            raise Exception(
                f"Operation timed out while deleting {len(correspondent_ids)} correspondents. "
                "The correspondents may still be deleted - please refresh to verify."
            )
        except Exception as e:
            if "bulk_delete_correspondents" not in str(e):
                raise Exception(f"Failed to delete correspondents: {str(e)}")
            raise

    async def create_correspondent(self, name: str, **kwargs) -> Correspondent:
        """Create a new correspondent."""
        data = {"name": name, **kwargs}
        resp = await self.client.post("/api/correspondents/", json=data)
        resp.raise_for_status()
        c = resp.json()
        return Correspondent(
            id=c["id"],
            name=c["name"],
            slug=c.get("slug", ""),
            matching_algorithm=c.get("matching_algorithm", 0),
            match=c.get("match", ""),
            is_insensitive=c.get("is_insensitive", True),
            document_count=c.get("document_count", 0),
        )

    async def update_correspondent(self, correspondent_id: int, **kwargs) -> Correspondent:
        """Update an existing correspondent."""
        resp = await self.client.patch(f"/api/correspondents/{correspondent_id}/", json=kwargs)
        resp.raise_for_status()
        c = resp.json()
        return Correspondent(
            id=c["id"],
            name=c["name"],
            slug=c.get("slug", ""),
            matching_algorithm=c.get("matching_algorithm", 0),
            match=c.get("match", ""),
            is_insensitive=c.get("is_insensitive", True),
            document_count=c.get("document_count", 0),
        )

    async def get_correspondent_by_name(self, name: str) -> Correspondent | None:
        """Find a correspondent by exact name (case-insensitive)."""
        resp = await self.client.get(f"/api/correspondents/?name__iexact={name}")
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if results:
            c = results[0]
            return Correspondent(
                id=c["id"],
                name=c["name"],
                slug=c.get("slug", ""),
                matching_algorithm=c.get("matching_algorithm", 0),
                match=c.get("match", ""),
                is_insensitive=c.get("is_insensitive", True),
                document_count=c.get("document_count", 0),
            )
        return None

    async def set_correspondent_on_documents(
        self, doc_ids: list[int], correspondent_id: int
    ) -> None:
        """Set a correspondent on multiple documents."""
        if not doc_ids:
            return

        resp = await self.client.post(
            "/api/documents/bulk_edit/",
            json={
                "documents": doc_ids,
                "method": "set_correspondent",
                "parameters": {"correspondent": correspondent_id},
            },
        )
        resp.raise_for_status()


def find_low_usage_correspondents(
    correspondents: list[Correspondent],
    max_docs: int = 0,
    exclude_patterns: list[str] | None = None,
) -> list[Correspondent]:
    """Find correspondents with document count <= max_docs, excluding specified patterns."""
    exclude_patterns = exclude_patterns or []
    low_usage = []

    for correspondent in correspondents:
        if correspondent.document_count > max_docs:
            continue

        excluded = False
        for pattern in exclude_patterns:
            if re.search(pattern, correspondent.name, re.IGNORECASE):
                excluded = True
                break

        if correspondent.is_auto:
            excluded = True

        if not excluded:
            low_usage.append(correspondent)

    return low_usage


def find_low_usage_tags(
    tags: list[Tag],
    max_docs: int = 1,
    exclude_patterns: list[str] | None = None,
) -> list[Tag]:
    """Find tags with document count <= max_docs, excluding specified patterns."""
    exclude_patterns = exclude_patterns or []
    low_usage = []

    for tag in tags:
        if tag.document_count > max_docs:
            continue

        # Check exclusions
        excluded = False
        for pattern in exclude_patterns:
            if re.search(pattern, tag.name, re.IGNORECASE):
                excluded = True
                break

        # Exclude auto-matching tags
        if tag.is_auto:
            excluded = True

        if not excluded:
            low_usage.append(tag)

    return low_usage


def group_tags_by_prefix(tags: list[Tag], min_prefix_length: int = 3) -> dict[str, list[Tag]]:
    """Group tags by common prefixes for merge suggestions."""
    from collections import defaultdict

    groups: dict[str, list[Tag]] = defaultdict(list)

    for tag in tags:
        name_lower = tag.name.lower()

        # Try to find the best prefix
        # First, split by common separators
        parts = re.split(r"[\s_\-]+", name_lower)
        if len(parts) > 1:
            prefix = parts[0]
        else:
            # Use first N characters as prefix
            prefix = (
                name_lower[:min_prefix_length]
                if len(name_lower) >= min_prefix_length
                else name_lower
            )

        if len(prefix) >= min_prefix_length:
            groups[prefix].append(tag)

    # Filter to groups with multiple tags
    return {
        k: sorted(v, key=lambda t: (-t.document_count, t.name.lower()))
        for k, v in groups.items()
        if len(v) > 1
    }


def group_correspondents_by_prefix(
    correspondents: list[Correspondent], min_prefix_length: int = 3
) -> dict[str, list[Correspondent]]:
    """Group correspondents by common prefixes for merge suggestions."""
    from collections import defaultdict

    groups: dict[str, list[Correspondent]] = defaultdict(list)

    for correspondent in correspondents:
        name_lower = correspondent.name.lower()

        # Try to find the best prefix
        # First, split by common separators
        parts = re.split(r"[\s_\-]+", name_lower)
        if len(parts) > 1:
            prefix = parts[0]
        else:
            # Use first N characters as prefix
            prefix = (
                name_lower[:min_prefix_length]
                if len(name_lower) >= min_prefix_length
                else name_lower
            )

        if len(prefix) >= min_prefix_length:
            groups[prefix].append(correspondent)

    # Filter to groups with multiple correspondents
    return {
        k: sorted(v, key=lambda c: (-c.document_count, c.name.lower()))
        for k, v in groups.items()
        if len(v) > 1
    }
