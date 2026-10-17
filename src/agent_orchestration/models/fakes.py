"""Small offline models for controlled tests, not security classifiers."""
import asyncio
import inspect
import math
import random

from .contracts import Decision, LLM, SparqlLLM, SparqlResult, SystemOneModel
from .usage import ModelResponse, TokenUsage


def sequence(responses, *, repeat=False):
    """Consume one response per call; fail when exhausted, or cycle explicitly."""
    responses = tuple(responses)
    if not responses:
        raise ValueError("Provide at least one response")
    index = 0

    def respond(request):
        nonlocal index
        if not repeat and index >= len(responses):
            raise RuntimeError("Fake response sequence exhausted")
        response = responses[index % len(responses)]
        index += 1
        return response

    return respond


def by_keywords(rules, default, *, text=None):
    """First matching keyword wins, ignoring case; classify state or generate from prompt.

    For a JSON decision state, supply text=lambda r: json.loads(r.state)['prompt']
    to match only the prompt rather than policy/permissions too.
    """
    rules = [(word.casefold(), response) for word, response in rules.items()]
    if any(not word for word, _ in rules):
        raise ValueError("Keywords must not be empty")

    def respond(request):
        value = text(request) if text else (
            request if isinstance(request, str) else
            request.prompt if hasattr(request, "prompt") else request.state)
        return next((response for word, response in rules if word in value.casefold()), default)

    return respond


def random_choice(responses, *, seed=0):
    """Reproducible local randomness; never assigns a confidence probability."""
    responses = tuple(responses)
    if not responses:
        raise ValueError("Provide at least one response")
    rng = random.Random(seed)
    return lambda request: rng.choice(responses)


class _Fake:
    def __init__(self, response, *, delay=0, usage=None):
        if not math.isfinite(delay) or delay < 0:
            raise ValueError("delay must be finite and nonnegative")
        self.response, self.delay = response, delay
        self.calls = []
        self.usage = usage if usage is not None else TokenUsage(0, 0, source="simulated", requests=0)
        if not isinstance(self.usage, TokenUsage):
            raise TypeError("usage must be TokenUsage")

    async def run_with_usage(self, request):
        try:
            return ModelResponse(await self.run(request), self.usage)
        except BaseException as error:
            error.token_usage = self.usage
            raise

    async def _respond(self, request):
        self.calls.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        response = self.response(request) if callable(self.response) else self.response
        if inspect.isawaitable(response):
            response = await response
        if isinstance(response, Exception):
            raise response
        return response


class FakeLLM(_Fake, LLM):
    async def run(self, request):
        response = await self._respond(request)
        if not isinstance(response, str):
            raise TypeError("FakeLLM expects a text response")
        return response


class FakeSparqlLLM(_Fake, SparqlLLM):
    async def run(self, request):
        response = await self._respond(request)
        if isinstance(response, str):
            response = SparqlResult(response)
        if not isinstance(response, SparqlResult):
            raise TypeError("FakeSparqlLLM expects text or SparqlResult")
        return response


class FakeClassifier(_Fake, SystemOneModel):
    async def run(self, request):
        response = await self._respond(request)
        if isinstance(response, str):
            response = Decision(response)
        if not isinstance(response, Decision):
            raise TypeError("FakeClassifier expects a choice or Decision")
        if response.choice not in request.options:
            raise ValueError("Fake choice is not in request.options")
        return response
