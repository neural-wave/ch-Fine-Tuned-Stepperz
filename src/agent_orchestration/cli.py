"""Run a real-model prompt; --dataset also enables checked local execution."""
import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path

from rdflib import Dataset

from . import CheckedQueryExecutor, PromptRequest, SparqlWorkflow, StaticQueryAnalyzer
from .local_models import CONFIG, check_mcp, open_models


async def generate(args):
    
    directory = args.config.resolve().parent
    
    request = PromptRequest(args.prompt,
        args.schema_file.read_text(encoding="utf-8-sig") if args.schema_file else
        "SPHN clinical RDF. Retrieve class/property details from the schema MCP.",
        (args.policy_file or directory / "policy.txt").read_text(encoding="utf-8-sig"),
        (args.permissions_file or directory / "permissions.txt").read_text(encoding="utf-8-sig"))
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    
    if not (config.get("mcp_url") or config.get("mcp_settings")) and not args.schema_file:
        raise ValueError("Without MCP provide --schema-file")
    
    executor = None
    
    if args.dataset:
        dataset = Dataset()
        dataset.parse(args.dataset.resolve(strict=True).as_uri(), format=args.rdf_format)
        executor = CheckedQueryExecutor(dataset)
    async with open_models(args.config) as (guard, generator):
        workflow = SparqlWorkflow(guard, generator, StaticQueryAnalyzer(), executor, model_timeout_seconds=120)
        outcome = await workflow.run(request, execute=args.dataset is not None)
        return {**asdict(outcome), "executed": outcome.status == "released"}


def main():
    parser = argparse.ArgumentParser(prog="sparql-run", description=__doc__)
    parser.add_argument("--prompt")
    parser.add_argument("--check-mcp", action="store_true", help="Check MCP retrieval tools without loading models")
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--schema-file", type=Path)
    parser.add_argument("--policy-file", type=Path)
    parser.add_argument("--permissions-file", type=Path)
    parser.add_argument("--dataset", type=Path, help="Local RDF dataset to execute against (e.g. TriG with patient named graphs)")
    parser.add_argument("--rdf-format", help="RDFLib format; otherwise inferred from the dataset extension")
    args = parser.parse_args()
    if args.check_mcp:
        print(json.dumps(asyncio.run(check_mcp(args.config)), ensure_ascii=False, indent=2))
        return 0
    if not args.prompt:
        parser.error("Specify --prompt or --check-mcp")
    result = asyncio.run(generate(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"query_ready", "released"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
