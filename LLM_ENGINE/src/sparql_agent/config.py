"""Environment configuration shared by the CLI and benchmark."""

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "qwen3:1.7b"
    llm_fallback_model: str = "qwen2.5:1.5b"
    llm_api_key: str = field(default="ollama", repr=False)
    llm_temperature: float = 0.0
    llm_max_tokens: int = 2048
    llm_timeout_seconds: float = 180.0
    llm_reasoning_effort: str = "none"
    llm_extra_body: dict = field(default_factory=dict)
    mcp_url: str = "https://chat.expasy.org/mcp/"
    mcp_timeout_seconds: float = 90.0
    max_agent_iterations: int = 5
    enable_sparql_execution: bool = False
    target_endpoint: str = "https://sparql.uniprot.org/sparql/"
    results_dir: Path = Path("results")
    max_tool_result_chars: int = 12000
    max_tools_per_iteration: int = 4

    def __post_init__(self):
        for name in ("llm_base_url", "mcp_url", "target_endpoint"):
            parsed = urlparse(getattr(self, name))
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
                raise ValueError(f"{name} must be an HTTP(S) URL without embedded credentials")
        for name in (
            "llm_max_tokens",
            "llm_timeout_seconds",
            "mcp_timeout_seconds",
            "max_agent_iterations",
            "max_tool_result_chars",
            "max_tools_per_iteration",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        if not math.isfinite(self.llm_temperature) or not 0 <= self.llm_temperature <= 2:
            raise ValueError("LLM_TEMPERATURE must be between 0 and 2")
        if not self.llm_model.strip():
            raise ValueError("LLM_MODEL cannot be empty")
        if not isinstance(self.llm_extra_body, dict):
            raise ValueError("LLM_EXTRA_BODY must be a JSON object")
        reserved = {"model", "messages", "tools", "tool_choice", "temperature", "max_tokens", "stream"}
        if reserved & self.llm_extra_body.keys():
            raise ValueError("LLM_EXTRA_BODY cannot override core request fields")

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> "Config":
        load_dotenv(env_file, override=False)
        values = {}
        integer_fields = {
            "llm_max_tokens",
            "max_agent_iterations",
            "max_tool_result_chars",
            "max_tools_per_iteration",
        }
        float_fields = {"llm_temperature", "llm_timeout_seconds", "mcp_timeout_seconds"}
        for name in cls.__dataclass_fields__:
            raw = os.getenv(name.upper())
            if raw is None:
                continue
            if name in integer_fields:
                values[name] = int(raw)
            elif name in float_fields:
                values[name] = float(raw)
            elif name == "enable_sparql_execution":
                if raw.lower() not in {"true", "false"}:
                    raise ValueError("ENABLE_SPARQL_EXECUTION must be true or false")
                values[name] = raw.lower() == "true"
            elif name == "llm_extra_body":
                values[name] = json.loads(raw)
            elif name == "results_dir":
                values[name] = Path(raw)
            else:
                values[name] = raw
        return cls(**values)

    def public_settings(self) -> dict:
        """Record reproducibility settings without API keys or provider extension values."""
        return {
            name: str(getattr(self, name)) if name == "results_dir" else getattr(self, name)
            for name in self.__dataclass_fields__
            if name not in {"llm_api_key", "llm_extra_body"}
        }
