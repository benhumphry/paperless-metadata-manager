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
        language: str = "English",
        custom_prompt: str | None = None,
    ):
        self.llm_type = llm_type.lower()
        self.api_token = api_token
        self.language = language
        self.custom_prompt = custom_prompt

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

        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                if self.llm_type == "openai":
                    return await self._call_openai(client, prompt)
                elif self.llm_type == "anthropic":
                    return await self._call_anthropic(client, prompt)
                elif self.llm_type == "ollama":
                    return await self._call_ollama(client, prompt)
        except httpx.TimeoutException as e:
            logger.error(f"LLM request timed out after 600s: {e}")
            raise
        except Exception as e:
            logger.error(f"LLM request failed: {type(e).__name__}: {e}")
            raise

        return {}

    def _build_prompt(self, item_names: list[str], item_type: str) -> str:
        """Build the prompt for semantic grouping."""
        items_str = "\n".join(f"- {name}" for name in item_names)

        if self.custom_prompt:
            # Use custom prompt with variable substitution
            return self.custom_prompt.format(
                language=self.language,
                item_type=item_type,
                item_type_upper=item_type.upper(),
                items=items_str,
            )

        return f"""Respond in {self.language}. Scan this list of {item_type} and identify obvious groups of related items that could be merged.

RULES:
- Use EXACT names from the list (copy verbatim)
- Only groups with 2+ items
- Respond in {self.language} only

{item_type.upper()}:
{items_str}

JSON response (group name -> array of exact item names):"""

    async def _call_openai(self, client: httpx.AsyncClient, prompt: str) -> dict[str, list[str]]:
        """Call OpenAI API."""
        import time

        logger.info(
            f"OpenAI request to {self.api_url}: model={self.model}, prompt_length={len(prompt)} chars"
        )
        start_time = time.time()
        response = await client.post(
            f"{self.api_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        elapsed = time.time() - start_time
        logger.info(f"OpenAI response received in {elapsed:.1f}s")
        if response.status_code != 200:
            logger.error(f"OpenAI error: {response.status_code} - {response.text}")
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

            # Remove control characters that can break JSON parsing
            import re

            content = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", content)

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
                    # Ensure all items are strings and deduplicate
                    seen = set()
                    items = []
                    for item in value:
                        if item and str(item) not in seen:
                            seen.add(str(item))
                            items.append(str(item))
                    if len(items) >= 2:
                        result[str(key)] = items

            return result
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error: {e}, attempting to recover partial response")
            # Try to recover partial JSON by finding complete groups
            return self._recover_partial_json(content)
        except (KeyError, IndexError) as e:
            logger.error(f"Parse error: {e}")
            return {}

    def _recover_partial_json(self, content: str) -> dict[str, list[str]]:
        """Attempt to recover groups from truncated JSON response."""
        import re

        result = {}

        # Look for complete group patterns: "GroupName": ["item1", "item2", ...]
        # This regex finds groups where the array is properly closed with ]
        pattern = r'"([^"]+)":\s*\[((?:[^\[\]]*|\[(?:[^\[\]]*)\])*)\]'

        for match in re.finditer(pattern, content):
            group_name = match.group(1)
            items_str = match.group(2)

            # Skip the outer "groups" key if present
            if group_name.lower() == "groups":
                continue

            # Extract quoted strings from the items
            items = re.findall(r'"([^"]+)"', items_str)

            if len(items) >= 2:
                result[group_name] = items
                logger.info(f"Recovered group '{group_name}' with {len(items)} items")

        logger.info(f"Recovered {len(result)} groups from partial JSON")
        return result
