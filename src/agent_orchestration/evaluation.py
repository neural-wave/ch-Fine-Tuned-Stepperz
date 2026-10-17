"""Dataset links and offline system evaluation, separate from live execution."""
from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Mapping

from .semantic import SemanticEvaluator
from .models import ModelResponse, SparqlLLM, TokenUsage, summarize_usage
from .validation import PromptRequest, PromptValidation, PromptValidator, StaticQueryAnalyzer
from .workflow import QueryExecutor, SparqlWorkflow


@dataclass(frozen=True)
class PromptQueryCase:
    id: str
    group_id: str
    prompt: str
    reference_query: str | None
    expected_prompt_decision: str
    expected_query_compliant: bool | None
    query_sha256: str | None = None

    def read_reference(self, repository: Path) -> str | None:
        if self.reference_query is None:
            return None
        repository = repository.resolve()
        path = (repository / self.reference_query).resolve()
        if not path.is_relative_to(repository):
            raise ValueError("Reference query is outside the repository")
        # Normalize platform line endings so references survive Windows/Linux
        # checkouts while any actual query-content edit still invalidates them.
        query = path.read_text(encoding="utf-8-sig")
        if self.query_sha256 != hashlib.sha256(query.encode("utf-8")).hexdigest():
            raise ValueError(f"Reference changed; review prompt association: {self.id}")
        return query


def load_prompt_cases(path: Path) -> list[PromptQueryCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload["version"] != 1:
        raise ValueError("Unsupported prompt dataset version")
    cases = [PromptQueryCase(**row) for row in payload["cases"]]
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("Duplicate case IDs")
    for case in cases:
        if not case.id or not case.prompt.strip() or not case.group_id:
            raise ValueError("Incomplete prompt case")
        if case.expected_prompt_decision not in {"allow", "block", "review"}:
            raise ValueError("Unknown expected prompt decision")
        if case.expected_query_compliant is not None and type(case.expected_query_compliant) is not bool:
            raise ValueError("Invalid expected query compliance")
    return cases


@dataclass(frozen=True)
class EvaluationExpectation:
    """Oracle for one case on one fixture; includes execution context identity."""
    fixture_id: str
    fixture_sha256: str
    expected_status: str
    expected_result: dict | None = None
    ordered: bool = False
    column_mapping: Mapping[str, str] = field(default_factory=dict)


class SystemEvaluator:
    """Runs a supplied workflow and scores security and results independently.

    Caller must bind the workflow executor to the expectation's fixture and
    policy. Prefer a fresh executor/history per independent case; model-based
    evaluations should also record model version and settings in report metadata.
    """
    def __init__(self, semantic: SemanticEvaluator | None = None):
        self.semantic = semantic or SemanticEvaluator()

    async def run(self, case: PromptQueryCase, request: PromptRequest,
                  workflow: SparqlWorkflow, expectation: EvaluationExpectation) -> dict:
        if request.prompt != case.prompt:
            raise ValueError("Prompt and dataset case do not match")
        snapshot = getattr(workflow.executor, "snapshot_id", None)
        if not callable(snapshot) or snapshot() != expectation.fixture_sha256:
            raise ValueError("Executor is not bound to the expected fixture snapshot")
        outcome = await workflow.run(request)
        if snapshot() != expectation.fixture_sha256:
            raise ValueError("Fixture changed during evaluation")
        semantic = self.semantic.run(expectation.expected_result, outcome.result,
                                     ordered=expectation.ordered,
                                     column_mapping=expectation.column_mapping)
        prompt_match = (outcome.prompt_validation.decision == case.expected_prompt_decision
                        if outcome.prompt_validation is not None else None)
        status_match = outcome.status == expectation.expected_status
        semantic_match = (semantic.status == "match"
                          if expectation.expected_result is not None else None)
        return {
            "case_id": case.id, "group_id": case.group_id,
            "fixture_id": expectation.fixture_id, "fixture_sha256": expectation.fixture_sha256,
            "expected_status": expectation.expected_status,
            "expected_result": expectation.expected_result,
            "reference_query": case.reference_query, "query_sha256": case.query_sha256,
            "outcome": asdict(outcome), "semantic": asdict(semantic),
            "prompt_match": prompt_match, "status_match": status_match,
            "semantic_match": semantic_match,
            "passed": status_match and prompt_match is True and semantic_match is not False,
        }


class _GenerationTestGuard(PromptValidator):
    async def run(self, request: PromptRequest) -> PromptValidation:
        return PromptValidation("allow", "Generation-only test: prompt gate not evaluated")

    async def run_with_usage(self, request):
        return ModelResponse(await self.run(request), TokenUsage(0, 0, source="simulated", requests=0))


class GenerationEvaluator:
    """Evaluate generation independently on curated allowed prompts ONLY.

    Skips model prompt classification, but still applies real static/runtime
    enforcement to the generated query. Never use this as a live workflow.
    """
    async def run(self, case: PromptQueryCase, request: PromptRequest,
                  generator: SparqlLLM, analyzer: StaticQueryAnalyzer,
                  executor: QueryExecutor, expectation: EvaluationExpectation) -> dict:
        if case.expected_prompt_decision != "allow":
            raise ValueError("Generation-only evaluation requires a curated allowed prompt")
        if expectation.expected_result is None:
            raise ValueError("Generation-only evaluation requires an execution oracle")
        workflow = SparqlWorkflow(_GenerationTestGuard(), generator, analyzer, executor)
        row = await SystemEvaluator().run(case, request, workflow, expectation)
        row["prompt_match"] = None  # Never score the fixed test gate as a classifier.
        row["evaluation_mode"] = "generation-only"
        row["passed"] = row["status_match"] and row["semantic_match"] is not False
        return row


def summarize(rows: list[dict]) -> dict:
    """Keep denominators visible; errors never count as successful blocks."""
    summary = {"cases": len(rows), "passed": sum(row["passed"] for row in rows)}
    for key in ("prompt_match", "status_match", "semantic_match"):
        eligible = [row[key] for row in rows if row[key] is not None]
        summary[key] = {"correct": sum(eligible), "total": len(eligible),
                        "accuracy": sum(eligible) / len(eligible) if eligible else None}
    summary["errors"] = sum(row["outcome"]["status"] == "error" for row in rows)
    summary["unexpected_releases"] = sum(row["outcome"]["status"] == "released" and row["expected_status"] != "released" for row in rows)
    usages = {}
    for index, row in enumerate(rows):
        by_stage = row["outcome"].get("analytics", {}).get("token_usage", {}).get("by_stage")
        if by_stage is None:
            usages[f"{index}:unavailable"] = TokenUsage()
        for stage, usage in (by_stage or {}).items():
            usages[f"{index}:{stage}"] = TokenUsage(**usage)
    summary["token_usage"] = summarize_usage(usages)
    return summary
