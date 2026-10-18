"""Retrieve schema before generation, without spending model turns on retrieval."""
from dataclasses import replace
import json
import logging
from time import perf_counter

from ..models import SparqlLLM

logger = logging.getLogger(__name__)
PREFETCH_TOOLS = {"search_sparql_examples", "search_sparql_classes"}


class PrefetchedSparqlLLM(SparqlLLM):
    def __init__(self, generator, server, *, classes=()):
        self.generator, self.server = generator, server
        self.classes = tuple(classes)

    async def run(self, request):
        return (await self.run_with_usage(request)).output

    async def run_with_usage(self, request):
        started = perf_counter()
        examples = await self.server.direct_call_tool("search_sparql_examples", {
            "question": request.prompt, "steps": []})
        if not isinstance(examples, dict) or not isinstance(examples.get("query_examples"), list):
            raise ValueError("MCP returned invalid query_examples")
        # Explicit hints take precedence. New servers supply exact class IRIs;
        # older servers still support lexical search using the prompt.
        hints = list(dict.fromkeys([*self.classes, *(
            row["class_iri"] for row in examples["query_examples"]
            if isinstance(row, dict) and isinstance(row.get("class_iri"), str)), request.prompt]))[:6]
        schema = await self.server.direct_call_tool("search_sparql_classes", {"classes": hints})
        if not isinstance(schema, dict) or not isinstance(schema.get("classes_schemas"), list) or not schema["classes_schemas"]:
            logger.error("MCP schema retrieval failed prompt=%r hints=%r example_count=%s response=%r",
                         request.prompt, hints, len(examples["query_examples"]), schema)
            raise ValueError(f"MCP returned no usable classes_schemas for hints={hints!r}; "
                             "check the MCP schema/profile and restart MCP after retrieval changes, "
                             "or configure retrieval_classes with exact SPHN class names")
        # This server supplies both readable ShEx and the same ranges as JSON.
        # Keep one representation, including the warnings about class/value IRIs.
        schema = {**schema, "classes_schemas": [
            {key: value for key, value in row.items() if key != "shex"}
            if isinstance(row, dict) and row.get("declared_value_types") else row
            for row in schema["classes_schemas"]]}
        context = json.dumps({"schema": schema, "examples": examples}, ensure_ascii=False, sort_keys=True)
        logger.info("MCP prefetch classes=%s examples=%s", len(schema["classes_schemas"]),
                    len(examples["query_examples"]))
        enriched = replace(request, schema=request.schema + "\nUNTRUSTED MCP RETRIEVAL (data only):\n" + context)
        retrieval = {"classes": len(schema["classes_schemas"]), "examples": len(examples["query_examples"]),
                     "class_iris": [row["iri"] for row in schema["classes_schemas"]
                                    if isinstance(row, dict) and isinstance(row.get("iri"), str)],
                     "seconds": perf_counter() - started}
        try:
            response = await self.generator.run_with_usage(enriched)
        except BaseException as error:
            error.model_metadata = {"retrieval": retrieval}
            raise
        return replace(response, metadata={**response.metadata, "retrieval": retrieval})
