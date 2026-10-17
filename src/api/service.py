"""Translate and assess without executing queries or rewriting user intent."""
import asyncio
from dataclasses import replace
import logging

from agent_orchestration.models import SparqlRequest, SparqlResult
from agent_orchestration.models.usage import invoke_with_usage, summarize_usage
from agent_orchestration.logging_setup import active_workflow, log_block
from agent_orchestration.validation import PromptValidation
from sparql_analyzer.validation import validate

logger = logging.getLogger(__name__)


class TranslationService:
    def __init__(self, guard, generator, *, schema, policy, permissions=""):
        self.guard, self.generator = guard, generator
        self.template = SparqlRequest("", schema, policy, permissions)

    async def run(self, text):
        request = replace(self.template, prompt=text)
        context = active_workflow.set("api")
        try:
            logger.info("API request prompt=%r", text)
            prompt = await invoke_with_usage(self.guard, request)
            if not isinstance(prompt.output, PromptValidation):
                raise TypeError("Invalid prompt verdict")
            # The API returns the translated query also for non-compliant input.
            # Unlike the execution workflow, this service has no executor.
            generated = await invoke_with_usage(self.generator, request)
            if not isinstance(generated.output, SparqlResult) or not generated.output.query.strip():
                raise ValueError("No SPARQL query was generated")
            query = generated.output.query
            log_block(logger, "API generated SPARQL", query)
            analysis = await asyncio.to_thread(validate, query)
            compliant = analysis["is_compliant"] is True and prompt.output.decision == "allow"
            usage = summarize_usage({"prompt_validation": prompt.usage, "generation": generated.usage})
            log_block(logger, "API token usage", usage)
            if not usage["complete"] or usage["total_tokens"] is None or usage["estimated"]:
                raise ValueError("The API requires complete reported token usage")
            result = {"sparql_query": query, "tokens_consumed": usage["total_tokens"], "is_compliant": compliant}
            if not compliant:
                reasons = [finding["reason"] for finding in analysis.get("findings", []) if finding.get("reason")]
                if analysis.get("status") == "unsupported":
                    reasons.insert(0, "Query shape or syntax not supported by the standard SPARQL checker.")
                if prompt.output.decision != "allow":
                    reasons.insert(0, f"Prompt assessment: {prompt.output.decision}. {prompt.output.reason}")
                result["compliance_reason"] = " ".join(dict.fromkeys(reasons)) or "Query failed compliance assessment."
            logger.info("API assessment completed compliant=%s", compliant)
            return result
        finally:
            active_workflow.reset(context)
