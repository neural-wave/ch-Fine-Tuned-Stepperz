"""Translate and assess without executing queries or rewriting user intent."""
import asyncio
from dataclasses import asdict, replace
import logging
from time import perf_counter

from agent_orchestration.models import SparqlRequest, SparqlResult
from agent_orchestration.models.usage import error_usage, invoke_with_usage, summarize_usage
from agent_orchestration.logging_setup import active_workflow, log_block
from agent_orchestration.validation import PromptValidation
from agent_orchestration.query_retry import attempt_for_log, repair_request, validate_query_retries
from sparql_analyzer.validation import validate

logger = logging.getLogger(__name__)


class TranslationService:
    def __init__(self, guard, generator, *, schema, policy, permissions="", query_retries=0):
        self.guard, self.generator = guard, generator
        self.template = SparqlRequest("", schema, policy, permissions)
        self.query_retries = validate_query_retries(query_retries)

    async def run(self, text):
        request = replace(self.template, prompt=text)
        context = active_workflow.set("api")
        started = perf_counter()
        stages, timings = {}, {}
        assessment, analysis, generation_metadata = None, None, {}
        prompt_metadata = {}
        query = None
        attempts = []
        stop_reason = None
        stage, stage_started = "prompt_validation", started

        def analytics(status, failed_stage=None):
            return {"status": status, "executed": False,
                    "token_usage": summarize_usage(stages),
                    "timings": {**timings, "total": perf_counter() - started},
                    "prompt_decision": assessment.decision if assessment else None,
                    "prompt_assessment": asdict(assessment) if assessment else None,
                    "prompt_metadata": prompt_metadata,
                    "query_analysis": analysis, "generation_metadata": generation_metadata,
                    "query_attempts": attempts,
                    "query_retry": {"configured_retries": self.query_retries,
                                    "retries_used": max(0, len(attempts) - 1),
                                    "stop_reason": "error" if failed_stage else stop_reason},
                    "effective_output_tokens_per_second": {
                        name: usage.output_tokens / timings[name]
                        if usage.output_tokens is not None and timings.get(name, 0) > 0 else None
                        for name, usage in stages.items()},
                    **({"failed_stage": failed_stage} if failed_stage else {})}

        try:
            logger.info("API request prompt=%r", text)
            prompt = await invoke_with_usage(self.guard, request)
            timings[stage] = perf_counter() - stage_started
            stages[stage] = prompt.usage
            prompt_metadata = prompt.metadata
            if not isinstance(prompt.output, PromptValidation):
                raise TypeError("Invalid prompt verdict")
            assessment = prompt.output
            # The API returns the translated query also for non-compliant input.
            # Unlike the execution workflow, this service has no executor.
            for index in range(self.query_retries + 1):
                suffix = f"_retry_{index}" if index else ""
                generation_stage, analysis_stage = "generation" + suffix, "analysis" + suffix
                attempt = {"attempt": index + 1, "query": None, "analysis": None,
                           "failed_checks": [], "status": "running", "timings": {}}
                attempts.append(attempt)
                stage, stage_started = generation_stage, perf_counter()
                generation_metadata = {}
                generated = await invoke_with_usage(self.generator, request)
                timings[stage] = perf_counter() - stage_started
                stages[stage] = generated.usage
                generation_metadata = generated.metadata
                attempt.update(token_usage=asdict(generated.usage), generation_metadata=generated.metadata)
                attempt["timings"]["generation"] = timings[stage]
                if not isinstance(generated.output, SparqlResult) or not generated.output.query.strip():
                    raise ValueError("No SPARQL query was generated")
                query = generated.output.query
                attempt["query"] = query
                log_block(logger, f"API generated SPARQL attempt={index + 1}", query)
                stage, stage_started = analysis_stage, perf_counter()
                analysis = await asyncio.to_thread(validate, query)
                timings[stage] = perf_counter() - stage_started
                attempt["timings"]["analysis"] = timings[stage]
                attempt.update(analysis=analysis, status=analysis.get("status", "compliant" if analysis["is_compliant"] is True else "unsupported"),
                               failed_checks=list(dict.fromkeys(f.get("check") or f["code"]
                                   for f in analysis.get("findings", []))))
                log_block(logger, "API query attempt", attempt_for_log(attempt))
                if assessment.decision != "allow":
                    stop_reason = "prompt_not_allowed"
                    break
                if analysis["is_compliant"] is True:
                    stop_reason = "accepted"
                    break
                stop_reason = "retry_limit"
                request = repair_request(request, attempts)
            compliant = analysis["is_compliant"] is True and prompt.output.decision == "allow"
            usage = summarize_usage(stages)
            stage = "accounting"
            if not usage["complete"] or usage["total_tokens"] is None or usage["estimated"]:
                raise ValueError("The API requires complete reported token usage")
            result = {"sparql_query": query, "tokens_consumed": usage["total_tokens"], "is_compliant": compliant,
                      "analytics": analytics("complete")}
            if self.query_retries:
                result["query_attempts"] = attempts
            log_block(logger, "API token usage and execution analytics", {
                **result["analytics"], "query_attempts": [attempt_for_log(row) for row in attempts]})
            if not compliant:
                reasons = [finding["reason"] for finding in analysis.get("findings", []) if finding.get("reason")]
                if analysis.get("status") == "unsupported":
                    reasons.insert(0, "Query shape or syntax not supported by the standard SPARQL checker.")
                if prompt.output.decision != "allow":
                    reasons.insert(0, f"Prompt assessment: {prompt.output.decision}. {prompt.output.reason}")
                result["compliance_reason"] = " ".join(dict.fromkeys(reasons)) or "Query failed compliance assessment."
            logger.info("API assessment completed compliant=%s", compliant)
            return result
        except BaseException as error:
            if stage.startswith("generation") and hasattr(error, "model_metadata"):
                generation_metadata = error.model_metadata
            if stage not in timings and (stage == "prompt_validation" or stage.startswith(("generation", "analysis"))):
                timings[stage] = perf_counter() - stage_started
            if (stage == "prompt_validation" or stage.startswith("generation")) and stage not in stages:
                stages[stage] = error_usage(error)
            if attempts and attempts[-1]["status"] == "running":
                attempts[-1]["status"] = "error"
                if stage.startswith("generation"):
                    attempts[-1]["token_usage"] = asdict(stages[stage])
                    attempts[-1]["generation_metadata"] = generation_metadata
                attempts[-1]["timings"]["generation" if stage.startswith("generation") else "analysis"] = timings.get(stage, 0)
            error.execution_analytics = analytics("error", failed_stage=stage)
            error.generated_query = query
            log_block(logger, "API partial execution analytics", {
                **error.execution_analytics, "query_attempts": [attempt_for_log(row) for row in attempts]})
            raise
        finally:
            active_workflow.reset(context)
