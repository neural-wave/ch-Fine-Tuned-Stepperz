"""Generate and statically check a query; never execute it."""
import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path

from agent_orchestration import PromptRequest, SparqlRequest, StaticQueryAnalyzer
from agent_orchestration.local_models import CONFIG, open_models


async def generate(args):
    directory = args.config.resolve().parent
    request = PromptRequest(args.prompt,
        args.schema_file.read_text(encoding="utf-8-sig") if args.schema_file else
        "SPHN clinical RDF. Retrieve class/property details from the schema MCP.",
        (args.policy_file or directory / "policy.txt").read_text(encoding="utf-8-sig"),
        (args.permissions_file or directory / "permissions.txt").read_text(encoding="utf-8-sig"))
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    if not config.get("mcp_settings") and not args.schema_file:
        raise ValueError("Without MCP provide --schema-file")
    async with open_models(args.config) as (guard, generator):
        async with asyncio.timeout(120):
            verdict = await guard.run(request)
            if verdict.decision != "allow":
                return {"status": verdict.decision, "validation": asdict(verdict), "executed": False}
            result = await generator.run(SparqlRequest(
                request.prompt, request.schema, request.policy, request.permissions))
        analysis = StaticQueryAnalyzer().run(result.query)
        return {"status": "query_ready" if analysis["is_compliant"] else "blocked_query",
                "query": result.query, "analysis": analysis, "executed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--schema-file", type=Path)
    parser.add_argument("--policy-file", type=Path)
    parser.add_argument("--permissions-file", type=Path)
    args = parser.parse_args()
    result = asyncio.run(generate(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "query_ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
