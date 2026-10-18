"""Readiness probes; inference and database inventory checks are opt-in."""
import asyncio
from datetime import datetime, timezone
import json
import logging
import os
from time import perf_counter

from agent_orchestration.adapters.mcp import CONFIG, RETRIEVAL_TOOLS, schema_server
from agent_orchestration.model_discovery import select_served_model
from .virtuoso import ready

logger = logging.getLogger(__name__)
PROMPT = "How many patients are in the database?"


async def check_retrieval(models):
    server = schema_server(models)
    if server is None:
        raise ValueError("No MCP configured")
    async with server:
        names = {tool.name for tool in await server.list_tools()}
        required = {"search_sparql_examples", "search_sparql_classes"}
        if not required <= names:
            raise ValueError(f"Missing SPHN retrieval tools: {sorted(required - names)}")
        examples = await server.direct_call_tool("search_sparql_examples", {"question": PROMPT, "steps": []})
        if (not isinstance(examples, dict) or not isinstance(examples.get("query_examples"), list)
                or not examples["query_examples"]):
            raise ValueError("MCP returned no examples for the patient-count probe; check schema and server version")
        schema = await server.direct_call_tool("search_sparql_classes", {"classes": [PROMPT]})
        if (not isinstance(schema, dict) or not isinstance(schema.get("classes_schemas"), list)
                or not schema["classes_schemas"]):
            raise ValueError("MCP returned no schema for the patient-count probe; check schema and server version")
        return {"url": models["mcp_url"], "tools": sorted(names & RETRIEVAL_TOOLS),
                "examples": len(examples["query_examples"]), "classes": len(schema["classes_schemas"])}


def check(config, clients, *, inference=False, with_virtuoso=False):
    models = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "models_config": str(CONFIG),
              "checks": {}, "inference_requested": inference, "virtuoso_requested": with_virtuoso}

    def probe(name, operation):
        started = perf_counter()
        try:
            details = operation()
            row = {"ok": True, "details": details}
            logger.info("[OK] %s: %s", name, json.dumps(details, ensure_ascii=False))
        except Exception as error:
            row = {"ok": False, "error": {"type": type(error).__name__, "message": str(error)}}
            logger.exception("[FAIL] %s: %s", name, error)
        row["seconds"] = perf_counter() - started
        report["checks"][name] = row

    def api():
        url = config["api_url"].rstrip("/") + "/health"
        response = clients.http.get(url, timeout=10)
        response.raise_for_status()
        if response.json().get("status") != "ok":
            raise ValueError("API /health did not report ready")
        return {"url": url, "status": "ok"}

    def generator():
        url = models["base_url"].rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {os.getenv('MODEL_API_KEY', 'local')}"}
        response = clients.http.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        served_model = select_served_model(response.json(), models.get("model"))
        return {"url": url, "model": served_model, "configured_model": models.get("model")}

    def exercise():
        response, seconds = clients.translate(PROMPT)
        analytics = response.get("analytics", {})
        if analytics.get("prompt_decision") not in {"allow", "block", "review"}:
            raise ValueError("API did not return a prompt classifier decision")
        if not response["sparql_query"].strip():
            raise ValueError("API returned an empty query")
        return {"seconds": seconds, "tokens_consumed": response["tokens_consumed"],
                "prompt_decision": analytics["prompt_decision"], "is_compliant": response["is_compliant"],
                "analytics": analytics, "query": response["sparql_query"]}

    probe("api", api)
    probe("generator", generator)
    probe("mcp", lambda: asyncio.run(check_retrieval(models)))
    if inference:
        probe("inference", exercise)
    if with_virtuoso:
        probe("virtuoso", lambda: {"url": config["virtuoso_url"], "database": ready(config, clients)["database"]})
    report["ok"] = all(row["ok"] for row in report["checks"].values())
    config["out_dir"].mkdir(parents=True, exist_ok=True)
    path = config["out_dir"] / ("health-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + ".json")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {path}", flush=True)
    return report
