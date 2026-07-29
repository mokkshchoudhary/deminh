"""Model backends.

Three implementations behind one interface:

  OllamaBackend   - what you will actually run the experiment on (8B, 4-bit).
  OpenAICompatBackend - any llama.cpp / vLLM server exposing /v1/chat/completions.
  MockBackend     - deterministic, no weights, no GPU. Use it for unit tests and
                    for developing the graph on a machine that cannot hold the
                    model. Every result in the dissertation must come from a real
                    backend; the mock exists so the plumbing can be tested cheaply.

The `seed` and `temperature` are pinned by default. For a controlled comparison
across three configurations, non-determinism in the generator is a confound: if
version 1 and version 3 see different generations, you are no longer isolating
the verifier.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import requests


@dataclass
class GenerationConfig:
    temperature: float = 0.0
    top_p: float = 1.0
    max_tokens: int = 1024
    seed: int = 42


class LLMBackend(ABC):
    """Minimal chat interface."""

    name: str = "abstract"

    @abstractmethod
    def chat(self, system: str, user: str, config: Optional[GenerationConfig] = None) -> str:
        ...

    def chat_json(self, system: str, user: str, config: Optional[GenerationConfig] = None) -> dict:
        """Chat, then extract the first JSON object from the reply.

        Small quantised models wrap JSON in prose and code fences with depressing
        regularity. Fail loudly rather than silently returning {} — a silent
        empty parse looks identical to "the model found no figures", which would
        quietly corrupt your extraction recall numbers.
        """
        raw = self.chat(system, user, config)
        return extract_json(raw)


def extract_json(raw: str) -> dict:
    text = raw.strip()
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:]
            part = part.strip()
            if part.startswith("{"):
                text = part
                break
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON object in model output: {raw[:300]!r}")
    return json.loads(text[start : end + 1])


class OllamaBackend(LLMBackend):
    def __init__(self, model: str = "llama3.1:8b-instruct-q4_K_M",
                 host: str = "http://localhost:11434", timeout: int = 300):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout
        self.name = f"ollama:{model}"

    def chat(self, system: str, user: str, config: Optional[GenerationConfig] = None) -> str:
        cfg = config or GenerationConfig()
        response = requests.post(
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "stream": False,
                "think": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "options": {
                    "temperature": cfg.temperature,
                    "top_p": cfg.top_p,
                    "num_predict": cfg.max_tokens,
                    "seed": cfg.seed,
                },
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()["message"]["content"]


class OpenAICompatBackend(LLMBackend):
    def __init__(self, model: str, base_url: str = "http://localhost:8000/v1",
                 api_key: str = "not-needed", timeout: int = 300):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.name = f"openai-compat:{model}"

    def chat(self, system: str, user: str, config: Optional[GenerationConfig] = None) -> str:
        cfg = config or GenerationConfig()
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": cfg.temperature,
                "top_p": cfg.top_p,
                "max_tokens": cfg.max_tokens,
                "seed": cfg.seed,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


class MockBackend(LLMBackend):
    """Deterministic stand-in. Returns canned responses keyed by prompt hash."""

    name = "mock"

    def __init__(self, responses: Optional[dict[str, str]] = None, default: str = "{}"):
        self.responses = responses or {}
        self.default = default
        self.calls: list[tuple[str, str]] = []

    def chat(self, system: str, user: str, config: Optional[GenerationConfig] = None) -> str:
        self.calls.append((system, user))
        for needle, reply in self.responses.items():
            if needle in user or needle in system:
                return reply
        return self.default

    @staticmethod
    def fingerprint(system: str, user: str) -> str:
        return hashlib.sha256((system + user).encode()).hexdigest()[:12]


def build_backend(spec: dict) -> LLMBackend:
    kind = spec.get("kind", "mock")
    if kind == "ollama":
        return OllamaBackend(model=spec.get("model", "llama3.1:8b-instruct-q4_K_M"),
                             host=spec.get("host", "http://localhost:11434"))
    if kind == "openai_compat":
        return OpenAICompatBackend(model=spec["model"],
                                   base_url=spec.get("base_url", "http://localhost:8000/v1"))
    if kind == "mock":
        return MockBackend()
    raise ValueError(f"Unknown backend kind: {kind}")
