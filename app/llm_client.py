"""LLM client abstraction for semantic grouping."""

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class LLMClient:
    """Abstract LLM client supporting OpenAI, Anthropic, and Ollama."""

    def __init__(
        self,
        llm_type: str,
        api_url: str | None = None,
        api_token: str | None = None,
        model: str | None = None,
    ):
        self.llm_type = llm_type.lower()
        self.api_token = api_token

        # Set defaults based on type
        if self.llm_type == "openai":
            self.api_url = api_url or "https://api.openai.com/v1"
            self.model = model or "gpt-5-mini"
        elif self.llm_type == "anthropic":
            self.api_url = api_url or "https://api.anthropic.com"
            self.model = model or "claude-3-haiku-20240307"
        elif self.llm_type == "ollama":
            self.api_url = api_url or "http://localhost:11434"
            self.model = model or "llama3"
        else:
            raise ValueError(f"Unsupported LLM type: {llm_type}")

    async def get_semantic_groups(
        self, item_names: list[str], item_type: str = "tags"
    ) -> dict[str, list[str]]:
        """Get semantic groupings for a list of item names.

        Args:
            item_names: List of item names to group
            item_type: Type of items (tags, correspondents, document_types)

        Returns:
            Dictionary mapping group names to lists of item names
        """
        if not item_names:
            return {}

        prompt = self._build_prompt(item_names, item_type)

        async with httpx.AsyncClient(timeout=300.0) as client:
            if self.llm_type == "openai":
                return await self._call_openai(client, prompt)
            elif self.llm_type == "anthropic":
                return await self._call_anthropic(client, prompt)
            elif self.llm_type == "ollama":
                return await self._call_ollama(client, prompt)

        return {}

    def _build_prompt(self, item_names: list[str], item_type: str) -> str:
        """Build the prompt for semantic grouping."""
        items_str = "\n".join(f"- {name}" for name in item_names)

        return f"""You are helping organize {item_type} in a document management system.

Given the following list of {item_type}, identify groups of items that are semantically related (same concept, synonyms, or closely related topics). Only include groups with 2 or more items.

IMPORTANT: Use the EXACT names from the list - copy them verbatim, do not shorten or paraphrase.

{item_type.upper()}:
{items_str}

Respond with a JSON object where keys are group names and values are arrays of exact item names from the list.

Example format:
{{"Financial": ["Account", "Accounting", "Bank"], "Legal": ["Attorney", "Contract"]}}

JSON response:"""

    async def _call_openai(self, client: httpx.AsyncClient, prompt: str) -> dict[str, list[str]]:
        """Call OpenAI API."""
        response = await client.post(
            f"{self.api_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return self._parse_response(content)

    async def _call_anthropic(self, client: httpx.AsyncClient, prompt: str) -> dict[str, list[str]]:
        """Call Anthropic API."""
        response = await client.post(
            f"{self.api_url}/v1/messages",
            headers={
                "x-api-key": self.api_token,
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": self.model,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        data = response.json()
        content = data["content"][0]["text"]
        return self._parse_response(content)

    async def _call_ollama(self, client: httpx.AsyncClient, prompt: str) -> dict[str, list[str]]:
        """Call Ollama API."""
        request_body = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            # Don't force JSON format - let the model respond naturally and parse it
        }
        logger.info(
            f"Ollama request to {self.api_url}/api/generate: model={self.model}, prompt_length={len(prompt)} chars"
        )
        logger.info(f"Ollama prompt (first 500 chars):\n{prompt[:500]}...")
        response = await client.post(
            f"{self.api_url}/api/generate",
            json=request_body,
        )
        if response.status_code != 200:
            logger.error(f"Ollama error: {response.status_code} - {response.text}")
        response.raise_for_status()
        data = response.json()
        logger.info(f"Ollama response keys: {data.keys()}")
        content = data.get("response", "{}")
        logger.info(f"Ollama raw response ({len(content)} chars): {content[:1000]}")
        result = self._parse_response(content)
        logger.info(f"Parsed result: {len(result)} groups")
        return result

    def _parse_response(self, content: str) -> dict[str, list[str]]:
        """Parse LLM response to extract groups."""
        try:
            # Try to extract JSON from the response
            content = content.strip()

            # Handle qwen3 thinking tags - extract content after </think>
            if "<think>" in content:
                think_end = content.find("</think>")
                if think_end != -1:
                    content = content[think_end + 8 :].strip()
                    logger.info(f"Stripped thinking tags, content now {len(content)} chars")

            # Handle markdown code blocks
            if content.startswith("```"):
                lines = content.split("\n")
                # Remove first and last lines (```json and ```)
                content = "\n".join(lines[1:-1])
                logger.info(f"Stripped markdown, content now {len(content)} chars")

            # Try to find JSON object in the content
            if not content.startswith("{"):
                # Look for first { and last }
                start = content.find("{")
                end = content.rfind("}")
                if start != -1 and end != -1:
                    content = content[start : end + 1]
                    logger.info(f"Extracted JSON object, content now {len(content)} chars")

            groups = json.loads(content)

            # Validate structure
            if not isinstance(groups, dict):
                logger.warning(f"Parsed JSON is not a dict: {type(groups)}")
                return {}

            result = {}
            for key, value in groups.items():
                if isinstance(value, list) and len(value) >= 2:
                    # Ensure all items are strings
                    items = [str(item) for item in value if item]
                    if len(items) >= 2:
                        result[str(key)] = items

            return result
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            logger.error(f"Content preview: {content[:500]}...")
            return {}
        except (KeyError, IndexError) as e:
            logger.error(f"Parse error: {e}")
            return {}
