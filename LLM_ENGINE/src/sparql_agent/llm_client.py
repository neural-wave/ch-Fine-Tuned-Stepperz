"""One provider-agnostic Chat Completions adapter; no Ollama-specific HTTP calls."""

from dataclasses import dataclass
from time import perf_counter

from openai import AsyncOpenAI

from .config import Config


@dataclass
class ModelReply:
    message: dict
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    duration_seconds: float = 0.0
    provider_timings: dict | None = None


class LLMClient:
    def __init__(self, config: Config):
        self.config = config
        # Disable hidden retries: one agent iteration corresponds to one request.
        self.client = AsyncOpenAI(
            base_url=config.llm_base_url,
            api_key=config.llm_api_key,
            timeout=config.llm_timeout_seconds,
            max_retries=0,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.close()

    async def complete(self, messages: list[dict], tools: list[dict] | None = None) -> ModelReply:
        kwargs = dict(
            model=self.config.llm_model,
            messages=messages,
            temperature=self.config.llm_temperature,
            max_tokens=self.config.llm_max_tokens,
            stream=False,
        )
        if tools:
            kwargs.update(tools=tools, tool_choice="auto")
        if self.config.llm_reasoning_effort:
            kwargs["reasoning_effort"] = self.config.llm_reasoning_effort
        if self.config.llm_extra_body:
            kwargs["extra_body"] = self.config.llm_extra_body
        start = perf_counter()
        response = await self.client.chat.completions.create(**kwargs)
        elapsed = perf_counter() - start
        if not response.choices:
            raise ValueError("LLM returned no choices")
        choice = response.choices[0]
        message = {"role": "assistant", "content": choice.message.content or ""}
        if choice.message.tool_calls:
            message["tool_calls"] = [call.model_dump(exclude_none=True) for call in choice.message.tool_calls]
        # Preserve reasoning when a compatible provider requires it on replay.
        extra = choice.message.model_extra or {}
        if extra.get("reasoning_content") is not None:
            message["reasoning_content"] = extra["reasoning_content"]
        usage = response.usage
        timings = {
            key: value
            for key, value in (response.model_extra or {}).items()
            if key in {"total_duration", "load_duration", "prompt_eval_duration", "eval_duration"}
        }
        return ModelReply(
            message=message,
            finish_reason=choice.finish_reason,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
            total_tokens=usage.total_tokens if usage else None,
            duration_seconds=elapsed,
            provider_timings=timings or None,
        )
