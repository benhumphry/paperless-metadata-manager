"""Tests for the Paperless API client."""

import pytest
from app.paperless_client import (
    Tag,
    find_low_usage_tags,
    group_tags_by_prefix,
)


def make_tag(id: int, name: str, doc_count: int = 0, algorithm: int = 0) -> Tag:
    """Helper to create a Tag for testing."""
    return Tag(
        id=id,
        name=name,
        slug=name.lower().replace(" ", "-"),
        color="#a6cee3",
        matching_algorithm=algorithm,
        match="",
        is_insensitive=True,
        document_count=doc_count,
    )


class TestFindLowUsageTags:
    """Tests for find_low_usage_tags function."""

    def test_finds_zero_doc_tags(self):
        tags = [
            make_tag(1, "empty", 0),
            make_tag(2, "has docs", 5),
        ]
        result = find_low_usage_tags(tags, max_docs=0)
        assert len(result) == 1
        assert result[0].name == "empty"

    def test_finds_low_doc_tags(self):
        tags = [
            make_tag(1, "zero", 0),
            make_tag(2, "one", 1),
            make_tag(3, "many", 10),
        ]
        result = find_low_usage_tags(tags, max_docs=1)
        assert len(result) == 2

    def test_excludes_patterns(self):
        tags = [
            make_tag(1, "inbox", 0),
            make_tag(2, "new document", 0),
            make_tag(3, "orphan", 0),
        ]
        result = find_low_usage_tags(tags, max_docs=1, exclude_patterns=["inbox", "new"])
        assert len(result) == 1
        assert result[0].name == "orphan"

    def test_excludes_auto_matching_tags(self):
        tags = [
            make_tag(1, "auto tag", 0, algorithm=6),  # Auto matching
            make_tag(2, "normal tag", 0, algorithm=0),
        ]
        result = find_low_usage_tags(tags, max_docs=1)
        assert len(result) == 1
        assert result[0].name == "normal tag"


class TestGroupTagsByPrefix:
    """Tests for group_tags_by_prefix function."""

    def test_groups_by_word_prefix(self):
        tags = [
            make_tag(1, "account balance", 5),
            make_tag(2, "account statement", 3),
            make_tag(3, "invoice", 10),
        ]
        result = group_tags_by_prefix(tags)
        assert "account" in result
        assert len(result["account"]) == 2

    def test_ignores_single_tags(self):
        tags = [
            make_tag(1, "unique tag", 5),
            make_tag(2, "another unique", 3),
        ]
        result = group_tags_by_prefix(tags)
        assert len(result) == 0

    def test_sorts_by_document_count(self):
        tags = [
            make_tag(1, "test low", 1),
            make_tag(2, "test high", 100),
            make_tag(3, "test medium", 50),
        ]
        result = group_tags_by_prefix(tags)
        assert result["test"][0].document_count == 100
        assert result["test"][1].document_count == 50
        assert result["test"][2].document_count == 1


class TestTag:
    """Tests for Tag dataclass."""

    def test_match_type_name(self):
        tag = make_tag(1, "test", algorithm=6)
        assert tag.match_type_name == "Auto"

    def test_is_auto(self):
        auto_tag = make_tag(1, "auto", algorithm=6)
        normal_tag = make_tag(2, "normal", algorithm=1)
        assert auto_tag.is_auto is True
        assert normal_tag.is_auto is False
