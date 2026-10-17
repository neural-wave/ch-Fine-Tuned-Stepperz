"""Provider-independent, per-invocation token accounting (no inference imports)."""
from dataclasses import asdict, dataclass
import json
from typing import Generic, Literal, TypeVar

OutputT = TypeVar("OutputT")


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    model: str | None = None
    source: Literal["reported", "estimated", "simulated", "unavailable"] = "unavailable"
    requests: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None
    complete: bool | None = None

    def __post_init__(self):
        for name in ("input_tokens", "output_tokens", "total_tokens", "requests",
                     "cache_read_tokens", "cache_write_tokens", "reasoning_tokens"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a nonnegative integer or None")
        if self.source not in {"reported", "estimated", "simulated", "unavailable"}:
            raise ValueError("Invalid token usage source")
        if self.input_tokens is not None and self.output_tokens is not None:
            total = self.input_tokens + self.output_tokens
            if self.total_tokens is not None and self.total_tokens != total:
                raise ValueError("total_tokens must equal input_tokens + output_tokens")
            object.__setattr__(self, "total_tokens", total)
        if self.complete is None:
            object.__setattr__(self, "complete", self.total_tokens is not None)
        if type(self.complete) is not bool or (self.complete and self.total_tokens is None):
            raise ValueError("Complete accounting requires a known total")
        if self.source == "unavailable" and any(getattr(self, name) is not None for name in
                                              ("input_tokens", "output_tokens", "total_tokens")):
            raise ValueError("Known counts require a reported, estimated or simulated source")

    @classmethod
    def from_backend(cls, usage, *, model=None, complete=None):
        """Accept SDK usage objects or common OpenAI/Ollama/native field names."""
        if usage is None:
            return cls(model=model)
        def get(*names):
            for name in names:
                value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
                if value is not None:
                    return value
            return None
        inputs = get("input_tokens", "prompt_tokens", "prompt_eval_count")
        outputs = get("output_tokens", "completion_tokens", "eval_count")
        total = get("total_tokens")
        if inputs is None and outputs is None and total is None:
            return cls(model=model)
        details = get("details") or {}
        prompt_details = get("prompt_tokens_details") or {}
        completion_details = get("completion_tokens_details") or {}
        def detail(value, name):
            return value.get(name) if isinstance(value, dict) else getattr(value, name, None)
        cache_read = get("cache_read_tokens")
        if cache_read is None:
            cache_read = detail(prompt_details, "cached_tokens")
        reasoning = get("reasoning_tokens")
        if reasoning is None:
            reasoning = detail(completion_details, "reasoning_tokens")
        if reasoning is None:
            reasoning = details.get("reasoning_tokens")
        return cls(inputs, outputs, total, model=model, source="reported",
                   requests=get("requests"), cache_read_tokens=cache_read,
                   cache_write_tokens=get("cache_write_tokens"),
                   reasoning_tokens=reasoning,
                   complete=complete)


@dataclass(frozen=True)
class ModelResponse(Generic[OutputT]):
    output: OutputT
    usage: TokenUsage

    def __post_init__(self):
        if not isinstance(self.usage, TokenUsage):
            raise TypeError("usage must be TokenUsage")


def summarize_usage(by_stage: dict[str, TokenUsage]) -> dict:
    """Never turn missing usage into zero; preserve known partial consumption."""
    usages = list(by_stage.values())
    complete = all(usage.complete for usage in usages)
    summary = {"complete": complete, "estimated": any(u.source == "estimated" for u in usages),
               "by_stage": {stage: asdict(usage) for stage, usage in by_stage.items()}}
    for name in ("input_tokens", "output_tokens", "total_tokens"):
        values = [getattr(usage, name) for usage in usages]
        summary[name] = sum(values) if complete and all(v is not None for v in values) else None
        summary[f"known_{name}"] = sum(v for v in values if v is not None)
    summary["known_total_tokens"] = sum(
        usage.total_tokens if usage.total_tokens is not None else
        (usage.input_tokens or 0) + (usage.output_tokens or 0) for usage in usages)
    return summary


def tokenizer_counter(tokenizer, *, input_text=None, output_text=None, model=None,
                      generates_text=True, add_special_tokens=True):
    """Opt-in estimate over caller-serialized text; does not load a tokenizer/model.

    Supply input_text to include the backend's chat template. Provider-only
    instructions/retries are not counted. Native heads use generates_text=False.
    """
    def serialize(value):
        if isinstance(value, str):
            return value
        if hasattr(value, "__dataclass_fields__"):
            return json.dumps(asdict(value), ensure_ascii=False)
        return str(value)

    def count(request, output):
        inputs = len(tokenizer.encode((input_text or serialize)(request), add_special_tokens=add_special_tokens))
        outputs = (len(tokenizer.encode((output_text or serialize)(output), add_special_tokens=False))
                   if generates_text else 0)
        return TokenUsage(inputs, outputs, model=model, source="estimated", requests=1)
    return count


def error_usage(error) -> TokenUsage:
    """asyncio.timeout chains the original cancellation carrying partial usage."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        usage = getattr(error, "token_usage", None)
        if isinstance(usage, TokenUsage):
            return usage
        error = error.__cause__ or error.__context__
    return TokenUsage()


async def invoke_with_usage(model, request):
    """Also support older duck-typed implementations without inventing counters."""
    method = getattr(model, "run_with_usage", None)
    response = await method(request) if method else ModelResponse(await model.run(request), TokenUsage())
    if not isinstance(response, ModelResponse) or not isinstance(response.usage, TokenUsage):
        raise TypeError("run_with_usage must return ModelResponse with TokenUsage")
    return response
