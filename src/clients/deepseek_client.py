"""DeepSeek LLM client — thin, dependency-free wrapper over DeepSeek's
OpenAI-compatible Chat Completions API.

Uses `requests` (already a dependency) rather than the OpenAI SDK to keep the
footprint small. Every call fails soft: on missing key, timeout, or bad
response it returns None so the caller can degrade gracefully — the bot must
never break because an optional AI feature is unavailable.

Docs: https://api-docs.deepseek.com  (base https://api.deepseek.com, model
`deepseek-chat`).
"""

from __future__ import annotations

import requests
from typing import List, Dict, Optional

from src.core.config import Config
from src.core.logger import log_error, log_info


class DeepSeekClient:
    BASE_URL = "https://api.deepseek.com/chat/completions"

    def __init__(self, api_key: Optional[str] = None,
                 model: Optional[str] = None, timeout: int = 30):
        self.api_key = (api_key or Config.DEEPSEEK_API_KEY or "").strip()
        self.model = model or Config.DEEPSEEK_MODEL or "deepseek-chat"
        self.timeout = timeout

    def available(self) -> bool:
        """True when a key is configured. Callers check this before offering
        an AI feature so the UI can hide/soft-fail cleanly."""
        return bool(self.api_key)

    def chat(self, system: str, user: str,
             max_tokens: int = 400, temperature: float = 0.7) -> Optional[str]:
        """Single-turn completion. Returns the assistant text, or None on any
        failure (never raises)."""
        if not self.available():
            return None
        try:
            resp = requests.post(
                self.BASE_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "stream": False,
                },
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                log_error(f"DeepSeek HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            data = resp.json()
            text = (data.get("choices") or [{}])[0].get(
                "message", {}).get("content", "").strip()
            return text or None
        except Exception as exc:
            log_error(f"DeepSeek call failed: {exc}")
            return None

    def health(self) -> bool:
        """Cheap liveness probe used by /health-style checks."""
        if not self.available():
            return False
        out = self.chat("You are a health check.", "Reply with: OK",
                        max_tokens=5, temperature=0)
        if out:
            log_info("DeepSeek reachable.")
        return bool(out)
