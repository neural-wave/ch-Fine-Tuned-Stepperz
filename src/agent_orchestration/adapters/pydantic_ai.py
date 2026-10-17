"""PydanticAI composition adapters accepting provider-configured agents."""
import json
import os
import inspect
import logging
from dataclasses import asdict
from typing import TYPE_CHECKING

from ..models import LLM, ModelResponse, SparqlLLM, SparqlRequest, SparqlResult, TokenUsage
from ..logging_setup import backend_log_level, configure_logging, log_block

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pydantic_ai import Agent


def agent_usage(agent, usage, *, complete=None):
    model = getattr(agent, "model", None)
    name = getattr(model, "model_name", None)
    tokens = TokenUsage.from_backend(usage, model=name, complete=complete)
    # SDK defaults cannot distinguish absent usage from a zero-token response.
    if tokens.input_tokens == 0 and tokens.output_tokens == 0:
        return TokenUsage(model=name)
    system = getattr(model, "system", None)
    if system in {"test", "function"} and tokens.source != "unavailable":
        from dataclasses import replace
        tokens = replace(tokens, source="simulated" if system == "test" else "estimated")
    return tokens


async def run_agent(agent, prompt, *, expected_type, usage_limits=None, token_counter=None,
                    request=None):
    """Keep a fresh SDK counter for every call, including retries and failures."""
    counter = None
    kwargs = {"usage_limits": usage_limits} if usage_limits is not None else {}
    if "usage" in inspect.signature(agent.run).parameters:
        from pydantic_ai.usage import RunUsage
        counter = RunUsage()
        kwargs["usage"] = counter
    tokens = None
    try:
        result = await agent.run(prompt, **kwargs)
        reported = getattr(result, "usage", None)
        if callable(reported) and not hasattr(reported, "input_tokens"):
            reported = reported()
        tokens = agent_usage(agent, reported if reported is not None else counter)
        if tokens.source == "unavailable" and token_counter is not None:
            tokens = token_counter(request if request is not None else prompt, result.output)
        if not isinstance(result.output, expected_type):
            raise TypeError(f"Expected output_type={expected_type.__name__}")
        if isinstance(result.output, SparqlResult) and not result.output.query.strip():
            raise ValueError("Generated SPARQL query is empty")
        return ModelResponse(result.output, tokens)
    except BaseException as error:
        error.token_usage = tokens if tokens is not None else agent_usage(agent, counter, complete=False)
        raise


class PydanticAILLM(LLM):
    def __init__(self, agent: "Agent[None, str]", *, token_counter=None) -> None:
        self.agent = agent
        self.token_counter = token_counter

    async def run(self, request: str) -> str:
        return (await self.run_with_usage(request)).output

    async def run_with_usage(self, request: str) -> ModelResponse[str]:
        return await run_agent(self.agent, request, expected_type=str, token_counter=self.token_counter)


class PydanticAISparqlLLM(SparqlLLM):
    """Use output_type=SparqlResult and trusted instructions on the Agent.

    Request fields are data; output needs independent SPARQL validation.
    """
    def __init__(self, agent: "Agent[None, SparqlResult]", *, usage_limits=None, token_counter=None) -> None:
        self.agent = agent
        self.usage_limits = usage_limits
        self.token_counter = token_counter

    async def run(self, request: SparqlRequest) -> SparqlResult:
        return (await self.run_with_usage(request)).output

    async def run_with_usage(self, request: SparqlRequest) -> ModelResponse[SparqlResult]:
        configure_logging()
        logger.log(backend_log_level(), "Generator request prompt=%r", request.prompt)
        # Stable context precedes the varying question so serving backends can
        # reuse shared prefixes. Field values and the output contract stay intact.
        fields = asdict(request)
        payload = json.dumps({key: fields[key] for key in ("policy", "permissions", "schema", "prompt")}, ensure_ascii=False)
        try:
            response = await run_agent(self.agent, payload, expected_type=SparqlResult,
                                       usage_limits=self.usage_limits, token_counter=self.token_counter,
                                       request=request)
        except Exception:
            logger.exception("Generator request failed")
            raise
        log_block(logger, "Generator response - SPARQL query", response.output.query, level=backend_log_level())
        log_block(logger, "Generator response - token usage", response.usage, level=backend_log_level())
        return response


def chat_model(name, base_url="http://localhost:11434/v1"):
    """Works with Ollama, llama.cpp or another compatible chat server."""
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    from pydantic_ai.profiles.openai import OpenAIModelProfile
    return OpenAIChatModel(name, provider=OpenAIProvider(
        base_url=base_url, api_key=os.getenv("MODEL_API_KEY", "local")),
        profile=OpenAIModelProfile(openai_supports_strict_tool_definition=False,
                                   openai_supports_tool_choice_required=False))


