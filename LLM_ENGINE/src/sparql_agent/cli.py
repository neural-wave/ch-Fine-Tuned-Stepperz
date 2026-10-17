"""Command line entry point and independent service diagnostics."""

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from jsonschema import validate

from .agent import error_text, parse_output, run_question
from .config import Config
from .llm_client import LLMClient
from .mcp_client import MCPClient
from .storage import append_jsonl, save_result

SMOKE_QUESTION = "Write a SPARQL query to retrieve human proteins encoded by the LCT gene from UniProt."


async def diagnose(config: Config, *, mcp_only: bool = False) -> dict:
    report = {
        "model": config.llm_model,
        "llm_base_url": config.llm_base_url,
        "mcp_url": config.mcp_url,
        "checks": {},
    }
    if not mcp_only:
        start = perf_counter()
        try:
            async with LLMClient(config) as llm:
                reply = await llm.complete([{"role": "user", "content": "Reply with OK."}])
            report["checks"]["llm"] = {
                "ok": bool(reply.message.get("content")),
                "response": reply.message.get("content"),
                "seconds": perf_counter() - start,
                "prompt_tokens": reply.prompt_tokens,
                "completion_tokens": reply.completion_tokens,
                "total_tokens": reply.total_tokens,
            }
        except Exception as exc:
            report["checks"]["llm"] = {
                "ok": False,
                "error": error_text(exc),
                "seconds": perf_counter() - start,
            }
    start = perf_counter()
    try:
        async with MCPClient(config) as mcp:
            specs = await mcp.discover()
            report["checks"]["discovery"] = {
                "ok": "search_sparql_examples" in specs,
                "tools": sorted(specs),
                "seconds": perf_counter() - start,
            }
            for name, arguments in (
                ("search_sparql_examples", {"question": SMOKE_QUESTION, "steps": []}),
                ("search_sparql_classes", {"classes": ["UniProt Protein", "UniProt Gene"]}),
            ):
                start_tool = perf_counter()
                try:
                    if name not in specs:
                        raise ValueError(f"Required retrieval tool is missing: {name}")
                    validate(arguments, specs[name].input_schema)
                    outcome = await mcp.call(name, arguments)
                    report["checks"][name] = {
                        "ok": not outcome.is_error and not outcome.empty,
                        "seconds": perf_counter() - start_tool,
                        "empty": outcome.empty,
                        "truncated": outcome.truncated,
                        "result": outcome.content,
                    }
                except Exception as exc:
                    report["checks"][name] = {
                        "ok": False,
                        "error": error_text(exc),
                        "seconds": perf_counter() - start_tool,
                    }
    except Exception as exc:
        report["checks"]["mcp_connection"] = {
            "ok": False,
            "error": error_text(exc),
            "seconds": perf_counter() - start,
        }
    report["ok"] = all(check["ok"] for check in report["checks"].values())
    return report


async def execute_saved(config: Config, query_path: Path) -> dict:
    """Explicit post-generation stage. No patient/query compliance is implemented."""
    if not config.enable_sparql_execution:
        raise ValueError("Execution is disabled. Explicitly set ENABLE_SPARQL_EXECUTION=true to use execute.")
    query = query_path.read_text(encoding="utf-8")
    _, endpoint, valid, issue = parse_output("```sparql\n" + query + "\n```", config.target_endpoint)
    if not valid or issue:
        raise ValueError(f"Cannot execute saved query: {issue}")
    started = perf_counter()
    async with MCPClient(config) as mcp:
        specs = await mcp.discover()
        if "execute_sparql_query" not in specs:
            raise ValueError("MCP server does not expose execute_sparql_query")
        arguments = {"sparql_query": query, "endpoint_url": endpoint}
        validate(arguments, specs["execute_sparql_query"].input_schema)
        outcome = await mcp.call("execute_sparql_query", arguments)
    return {
        "query_path": str(query_path),
        "endpoint": endpoint,
        "seconds": perf_counter() - started,
        "ok": not outcome.is_error,
        "result": outcome.content,
        "truncated": outcome.truncated,
        "compliance_checked": False,
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Generate SPARQL using a local LLM and actual SIB MCP retrieval"
    )
    root.add_argument("--env-file", default=".env")
    root.add_argument("--model", help="Override LLM_MODEL")
    root.add_argument("--fallback", action="store_true", help="Explicitly select LLM_FALLBACK_MODEL")
    sub = root.add_subparsers(dest="command", required=True)
    ask = sub.add_parser("ask")
    ask.add_argument("question")
    ask.add_argument("--mode", choices=["autonomous", "deterministic"], default="autonomous")
    ask.add_argument("--classes", nargs="+", help="Optional schema terms for deterministic retrieval")
    ask.add_argument("--json", action="store_true", help="Print complete result JSON")
    doctor = sub.add_parser("doctor", help="Test connectivity, discovery and both real retrieval tools")
    doctor.add_argument("--mcp-only", action="store_true")
    sub.add_parser("tools", help="Discover tool schemas from the selected server")
    execute = sub.add_parser(
        "execute", help="Separately execute a saved query; requires opt-in environment flag"
    )
    execute.add_argument("query_file", type=Path)
    return root


async def dispatch(args, config: Config) -> int:
    if args.command == "ask":

        def progress(message):
            print(message, file=sys.stderr, flush=True)

        result = await run_question(config, args.question, args.mode, args.classes, progress)
        paths = save_result(result, config.results_dir)
        if args.json:
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        else:
            if result.generated_query:
                print("```sparql\n" + result.generated_query + "\n```")
            print(f"Status: {result.status}; syntax valid: {result.syntax_valid}")
            print(
                f"Total: {result.end_to_end_seconds:.2f}s | retrieval: {result.retrieval_seconds:.2f}s | LLM requests: {result.llm_seconds:.2f}s"
            )
            print(
                f"Tokens: prompt={result.prompt_tokens}, completion={result.completion_tokens}, total={result.total_tokens}; complete usage={result.usage_complete}"
            )
            print(f"Iterations: {result.iterations}; invoked tools: {result.to_dict()['tool_names']}")
            for error in result.errors:
                print(f"Diagnostic: {error}", file=sys.stderr)
        print("Saved: " + json.dumps(paths), file=sys.stderr)
        return 0 if result.success else 1
    if args.command == "doctor":
        report = await diagnose(config, mcp_only=args.mcp_only)
        config.results_dir.mkdir(parents=True, exist_ok=True)
        path = config.results_dir / f"doctor-{uuid.uuid4().hex}.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        # Full retrieved records go to the artifact; terminal stays compact.
        summary = {
            **report,
            "checks": {
                name: {k: v for k, v in check.items() if k != "result"}
                for name, check in report["checks"].items()
            },
        }
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        print(f"Saved: {path}", file=sys.stderr)
        return 0 if report["ok"] else 1
    if args.command == "tools":
        async with MCPClient(config) as mcp:
            specs = await mcp.discover()
        print(json.dumps([tool.openai_schema() for tool in specs.values()], indent=2))
        return 0
    if args.command == "execute":
        report = await execute_saved(config, args.query_file)
        append_jsonl(config.results_dir / "executions.jsonl", report)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["ok"] else 1
    raise ValueError("Unknown command")


def main() -> None:
    args = parser().parse_args()
    try:
        config = Config.from_env(args.env_file)
        if args.model and args.fallback:
            raise ValueError("Use either --model or --fallback")
        if args.model or args.fallback:
            config = replace(config, llm_model=args.model or config.llm_fallback_model)
        code = asyncio.run(dispatch(args, config))
    except (Exception, KeyboardInterrupt) as exc:
        print(error_text(exc), file=sys.stderr)
        code = 130 if isinstance(exc, KeyboardInterrupt) else 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
