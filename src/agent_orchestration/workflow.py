"""Sequential workflow: PydanticAI generation, deterministic query enforcement.

No oracle is passed into the live workflow. Semantic evaluation is offline.
"""
import asyncio
from dataclasses import dataclass, field
import logging
from time import perf_counter
from typing import Literal, Protocol
from uuid import uuid4

from sparql_analyzer.configuration.policy import DEFAULT_POLICY, Policy
from sparql_analyzer.runtime import execute_checked, ResultBlocked
from sparql_analyzer.governance.privacy import snapshot_digest

from .models import SparqlLLM, SparqlRequest
from .logging_setup import configure_logging
from .validation import PromptRequest, PromptValidation, PromptValidator, StaticQueryAnalyzer

logger = logging.getLogger(__name__)


class QueryExecutor(Protocol):
    async def run(self, query: str) -> dict: ...


class CheckedQueryExecutor:
    """Local RDF execution using the existing runtime, including its limits.

    Synchronous RDF work runs on the caller thread: an asyncio timeout cannot
    preempt it. Use a separately bounded service/process for large datasets.
    Trusted ACL/SHACL contexts come from the service, never from prompt text.
    """
    def __init__(self, dataset, *, policy: Policy = DEFAULT_POLICY,
                 context=None, shacl_context=None):
        self.dataset = dataset
        self.policy = policy
        self.context = context
        self.shacl_context = shacl_context

    async def run(self, query: str) -> dict:
        return execute_checked(self.dataset, query, policy=self.policy,
                               context=self.context, shacl_context=self.shacl_context)

    def snapshot_id(self) -> str:
        """Expensive fingerprint for small offline evaluation fixtures only."""
        return snapshot_digest(self.dataset)


@dataclass(frozen=True)
class WorkflowResult:
    status: Literal["query_ready", "released", "blocked_prompt", "review_prompt", "blocked_query", "blocked_runtime", "error"]
    stage: str
    prompt_validation: PromptValidation | None = None
    query: str | None = None
    analysis: dict | None = None
    result: dict | None = None
    error_type: str | None = None
    timings: dict[str, float] = field(default_factory=dict)


class SparqlWorkflow:
    def __init__(self, prompt_validator: PromptValidator, generator: SparqlLLM,
                 analyzer: StaticQueryAnalyzer, executor: QueryExecutor | None = None,
                 *, model_timeout_seconds: float = 60):

        if model_timeout_seconds <= 0:
            raise ValueError("model_timeout_seconds must be positive")
        self.prompt_validator = prompt_validator
        self.generator = generator
        self.analyzer = analyzer
        self.executor = executor
        self.model_timeout_seconds = model_timeout_seconds

    async def run(self, request: PromptRequest, *, execute: bool = True) -> WorkflowResult:
        configure_logging()
        run_id = uuid4().hex[:12]
        logger.info("run=%s started execute=%s prompt=%r", run_id, execute, request.prompt)
        stage = "prompt_validation"
        verdict, query, analysis = None, None, None
        timings = {}
        started = perf_counter()

        def finish(status, *, result=None, error_type=None):
            timings[stage] = perf_counter() - started
            logger.info("run=%s completed status=%s stage=%s error_type=%s timings=%s result=%r",
                        run_id, status, stage, error_type, timings, result)
            return WorkflowResult(status, stage, verdict, query, analysis,
                                  result, error_type, dict(timings))

        try:
            logger.info("run=%s stage=%s started", run_id, stage)
            async with asyncio.timeout(self.model_timeout_seconds):
                verdict = await self.prompt_validator.run(request)

            if not isinstance(verdict, PromptValidation):
                raise TypeError("Invalid prompt verdict")
            logger.info("run=%s prompt_validation=%r", run_id, verdict)

            if verdict.decision != "allow":
                return finish("blocked_prompt" if verdict.decision == "block" else "review_prompt")

            timings[stage] = perf_counter() - started
            stage, started = "generation", perf_counter()
            logger.info("run=%s stage=%s started", run_id, stage)

            async with asyncio.timeout(self.model_timeout_seconds):

                generated = await self.generator.run(SparqlRequest(request.prompt, request.schema, request.policy, request.permissions))

            query = generated.query
            logger.info("run=%s generated_query=%r", run_id, query)

            if not isinstance(query, str) or not query.strip():
                raise ValueError("Empty or invalid query")

            timings[stage] = perf_counter() - started
            stage, started = "query_analysis", perf_counter()
            logger.info("run=%s stage=%s started", run_id, stage)
            analysis = self.analyzer.run(query)
            logger.info("run=%s query_analysis=%r", run_id, analysis)

            if analysis["is_compliant"] is not True:
                return finish("blocked_query")

            if not execute:
                return finish("query_ready")

            timings[stage] = perf_counter() - started
            stage, started = "execution", perf_counter()
            logger.info("run=%s stage=%s started", run_id, stage)

            if self.executor is None:
                raise ValueError("Execution requires a checked executor")

            result = await self.executor.run(query)

            return finish("released", result=result)

        except ResultBlocked:
            logger.info("run=%s stage=%s result blocked", run_id, stage)
            return finish("blocked_runtime" if stage == "execution" else "error", error_type="ResultBlocked")

        except Exception as error:
            logger.exception("run=%s stage=%s failed", run_id, stage)
            # A backend/parser crash is an error, not a successful security block.
            # Do not expose provider errors which may contain input or private data.
            return finish("error", error_type=type(error).__name__)
