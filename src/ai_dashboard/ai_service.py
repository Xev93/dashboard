"""Shared LLM service for AI features (filtering, summaries, sentiment)."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from importlib import import_module
from typing import Any

from ai_dashboard.config import AppConfig

logger = logging.getLogger(__name__)


@dataclass
class AIService:
    model: str
    api_key: str
    api_base: str
    temperature: float
    max_tokens: int
    timeout: int
    _enabled: bool = True

    @classmethod
    def from_config(cls, config: AppConfig) -> "AIService":
        """Create from AIConfig. Returns a disabled instance if AI is not configured."""
        ai = config.ai
        if not ai.enabled or not ai.api_key:
            logger.info("AI features disabled (no api_key or enabled=false)")
            return cls(
                model="",
                api_key="",
                api_base="",
                temperature=0,
                max_tokens=0,
                timeout=0,
                _enabled=False,
            )
        return cls(
            model=ai.model,
            api_key=ai.api_key,
            api_base=ai.api_base,
            temperature=ai.temperature,
            max_tokens=ai.max_tokens,
            timeout=ai.timeout,
        )

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Send a chat completion request via LiteLLM. Returns the response text."""
        if not self._enabled:
            return ""
        try:
            litellm = import_module("litellm")

            setattr(litellm, "suppress_debug_info", True)

            kwargs = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "timeout": self.timeout,
                "api_key": self.api_key,
            }
            if self.api_base:
                kwargs["api_base"] = self.api_base

            response = await asyncio.to_thread(litellm.completion, **kwargs)
            return response.choices[0].message.content or ""
        except Exception as exc:
            logger.warning("AI completion failed: %s", exc)
            return ""

    async def complete_json(
        self, system_prompt: str, user_prompt: str
    ) -> dict[str, object]:
        """Send a completion and parse the response as JSON."""
        text = await self.complete(system_prompt, user_prompt)
        if not text:
            return {}
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("AI returned non-JSON: %.100s", text)
            return {}
        return parsed if isinstance(parsed, dict) else {}
