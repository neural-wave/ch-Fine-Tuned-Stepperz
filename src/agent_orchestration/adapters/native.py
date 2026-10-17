"""Adapters for native classifiers, including arbitrary Hugging Face predictors."""
import asyncio
import inspect
from typing import Awaitable, Callable

from ..models import Decision, DecisionRequest, ModelResponse, SystemOneModel


class CallableSystemOneModel(SystemOneModel):
    """Wrap Decision or ModelResponse[Decision], optionally with a tokenizer.

    Sync inference runs in a thread. Cancelling the await does not stop that
    thread; its eventual consumption remains unavailable to the cancelled call.
    """
    def __init__(self, predict: Callable[[DecisionRequest],
                 Decision | ModelResponse[Decision] | Awaitable], *, token_counter=None):
        self.predict = predict
        self.token_counter = token_counter

    async def run(self, request: DecisionRequest) -> Decision:
        return (await self.run_with_usage(request)).output

    async def run_with_usage(self, request: DecisionRequest) -> ModelResponse[Decision]:
        response = None
        try:
            result = await asyncio.to_thread(self.predict, request)
            if inspect.isawaitable(result):
                result = await result
            response = result if isinstance(result, ModelResponse) else ModelResponse(
                result, self.count_tokens(request, result))
            if not isinstance(response.output, Decision):
                raise TypeError("Native backend must return Decision")
            if response.output.choice not in request.options:
                raise ValueError("Native backend returned an unknown choice")
            return response
        except BaseException as error:
            if response is not None:
                error.token_usage = response.usage
            raise
