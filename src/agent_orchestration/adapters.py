"""PydanticAI composition adapters accepting provider-configured agents."""
import json
import asyncio
import inspect
from dataclasses import asdict
from typing import TYPE_CHECKING, Awaitable, Callable

from .models import Decision, DecisionRequest, LLM, SparqlLLM, SparqlRequest, SparqlResult, SystemOneModel

if TYPE_CHECKING:
    from pydantic_ai import Agent


class PydanticAILLM(LLM):
    def __init__(self, agent: "Agent[None, str]") -> None:
        self.agent = agent

    async def run(self, request: str) -> str:
        result = await self.agent.run(request)
        if not isinstance(result.output, str):
            raise TypeError("Expected an Agent with output_type=str")
        return result.output


class PydanticAISparqlLLM(SparqlLLM):
    """Use output_type=SparqlResult and trusted instructions on the Agent.

    Request fields are data; output needs independent SPARQL validation.
    """
    def __init__(self, agent: "Agent[None, SparqlResult]", *, usage_limits=None) -> None:
        self.agent = agent
        self.usage_limits = usage_limits

    async def run(self, request: SparqlRequest) -> SparqlResult:
        payload = json.dumps(asdict(request), ensure_ascii=False)
        kwargs = {"usage_limits": self.usage_limits} if self.usage_limits is not None else {}
        result = await self.agent.run(payload, **kwargs)
        if not isinstance(result.output, SparqlResult):
            raise TypeError("Expected an Agent with output_type=SparqlResult")
        if not result.output.query.strip():
            raise ValueError("Generated SPARQL query is empty")
        return result.output


class CallableSystemOneModel(SystemOneModel):
    """Adapt a native inference function (e.g. Hugging Face) without chat APIs.

    The function receives DecisionRequest and returns Decision, directly or
    asynchronously. Synchronous inference is moved off the event loop; cancelling
    its await does not kill the underlying inference thread.
    """
    def __init__(self, predict: Callable[[DecisionRequest], Decision | Awaitable[Decision]]):
        self.predict = predict

    async def run(self, request: DecisionRequest) -> Decision:
        result = await asyncio.to_thread(self.predict, request)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, Decision):
            raise TypeError("Native backend must return Decision")
        if result.choice not in request.options:
            raise ValueError("Native backend returned an unknown choice")
        return result
