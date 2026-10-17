"""Clinical generation diagnostic using a local, retrieval-only MCP adapter.

Reuses the existing Agent, LLMClient, MCPClient, and artifact format. Retrieval is
lexical over the downloaded SPHN ontology and supplied examples, NOT public SIB
vector search. The evaluated example is always excluded from retrieval. No DB
client or execution tool is provided. A reserved .invalid URL is only an output
label, not an actual SPARQL endpoint. Gold queries are saved for later review.
"""

import argparse
import asyncio
import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import replace
from pathlib import Path

import uvicorn
from mcp.server.mcpserver import MCPServer
from rdflib import BNode, Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from sparql_agent.agent import run_question
from sparql_agent.benchmark import summarize
from sparql_agent.config import Config
from sparql_agent.storage import save_result

SPHN = "https://biomedit.ch/rdf/sphn-schema/sphn#"
TARGET = "http://example.invalid/sphn/sparql"
STOP = set(
    "the a an of in to for and or by with how what which is are do does it they we our patient patients".split()
)


def words(value):
    value = re.sub(r"([a-z])([A-Z])", r"\1 \2", value).lower()
    return set(re.findall(r"[a-z]{3,}", value)) - STOP


def rank(query, items, text):
    tokens = words(query)
    docs = [words(text(item)) for item in items]
    counts = Counter(word for doc in docs for word in doc)
    scores = [sum(math.log(1 + len(items) / counts[word]) for word in tokens & doc) for doc in docs]
    return [item for _, item in sorted(zip(scores, items, strict=True), key=lambda pair: -pair[0])]


def read_examples(path):
    text = path.read_text(encoding="utf-8-sig")
    pattern = r'^([0-9]+)\.\s+([^\n]+)\n"([^\n]+)"\s*\n(.*?)(?=^\d+\.\s|\Z)'
    rows = [
        {"id": int(n), "title": title, "question": question, "query": query.strip()}
        for n, title, question, query in re.findall(pattern, text, re.M | re.S)
    ]
    if [row["id"] for row in rows] != list(range(1, 16)):
        raise ValueError("Expected all 15 numbered examples")
    return rows


def schema_documents(path):
    graph = Graph().parse(path, format="turtle")
    ontology = URIRef(SPHN.rstrip("#"))
    version = str(graph.value(ontology, OWL.versionIRI))
    if version != "https://biomedit.ch/rdf/sphn-schema/sphn/2026/1":
        raise ValueError(f"Expected SPHN 2026.1, found {version}")

    def short(term):
        return graph.namespace_manager.normalizeUri(term)

    def nodes(root):
        pending, seen = [root], set()
        while pending:
            node = pending.pop()
            if node in seen:
                continue
            seen.add(node)
            # Descend class intersections/lists, not nested value restrictions:
            # e.g. hasTypeCode on a TimePattern is not a DrugAdministrationEvent property.
            for predicate, obj in graph.predicate_objects(node):
                if predicate in {RDFS.subClassOf, OWL.intersectionOf, RDF.first, RDF.rest} and isinstance(
                    obj, BNode
                ):
                    pending.append(obj)
        return seen

    docs = []
    for subject in sorted(set(graph.subjects(RDF.type, OWL.Class)), key=str):
        if not isinstance(subject, URIRef) or not str(subject).startswith(SPHN):
            continue
        label = str(graph.value(subject, RDFS.label) or str(subject).split("#")[-1])
        definition = str(graph.value(subject, SKOS.definition) or "")
        restrictions = nodes(subject)
        properties = sorted(
            {p for node in restrictions for p in graph.objects(node, OWL.onProperty)}, key=str
        )
        lines = [f"Class {short(subject)} ({label}): {definition[:450]}"]
        for prop in properties:
            ranges = {value for value in graph.objects(prop, RDFS.range) if isinstance(value, URIRef)}
            ranges.update(
                value
                for node in restrictions
                if graph.value(node, OWL.onProperty) == prop
                for value in graph.objects(node, OWL.someValuesFrom)
                if isinstance(value, URIRef)
            )
            lines.append(
                f"  {short(prop)} -> {', '.join(short(v) for v in sorted(ranges, key=str)) or 'range unspecified'}"
            )
        docs.append(
            {
                "label": label,
                "iri": str(subject),
                "shex": "\n".join(lines),
                "endpoint_url": TARGET,
                "definition": definition,
            }
        )
    return docs, version


def build_server(examples, docs, active):
    server = MCPServer("Local SPHN 2026.1 retrieval (no execution)", log_level="WARNING")

    @server.tool()
    def search_sparql_examples(question: str, steps: list[str]) -> dict:
        """Search local organizer SPHN examples, excluding the held-out test query. Not public SIB search."""
        eligible = [row for row in examples if row["id"] <= 10 and row["id"] != active["id"]]
        ordered = rank(
            question + " " + " ".join(steps), eligible, lambda row: row["question"] + " " + row["title"]
        )
        selected, length = [], 0
        for row in ordered:
            if length + len(row["query"]) > 6500 or len(selected) >= 2:
                continue
            selected.append(
                {
                    "question": row["question"],
                    "query": row["query"],
                    "endpoint_url": TARGET,
                    "source_example_id": row["id"],
                }
            )
            length += len(row["query"])
        return {"query_examples": selected}

    @server.tool()
    def search_sparql_classes(classes: list[str]) -> dict:
        """Search SPHN 2026.1 OWL class restrictions. The shex field contains a readable OWL summary, not formal ShEx. No data query is run."""
        selected = []
        for term in classes[:4]:
            best = rank(term, docs, lambda row: row["label"] + " " + row["iri"] + " " + row["definition"])[0]
            if best["iri"] not in {row["iri"] for row in selected}:
                selected.append({key: value for key, value in best.items() if key != "definition"})
        return {"classes_schemas": selected}

    return server


async def main(args):
    examples = read_examples(args.examples)
    docs, version = schema_documents(args.schema)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "references.json").write_text(json.dumps(examples, indent=2), encoding="utf-8")
    manifest = {
        "schema_version": version,
        "schema_sha256": hashlib.sha256(args.schema.read_bytes()).hexdigest(),
        "examples_sha256": hashlib.sha256(args.examples.read_bytes()).hexdigest(),
        "retrieval": "local lexical MCP; first 10 examples; current test excluded server-side",
        "target_endpoint_is_placeholder": True,
        "clinical_execution_enabled": False,
        "imports_loaded": False,
        "clinical_privacy_checker_implemented": False,
        "schema_classes": len(docs),
        "reference_ambiguity": "Example 3: any rank in question vs Principal in reference",
        "syntax_checker_limitation": "RDFLib SPARQL 1.1 rejects Virtuoso OPTION(inference ...)",
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    active = {"id": 1}
    mcp = build_server(examples, docs, active)
    app = mcp.streamable_http_app(json_response=True, stateless_http=True)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    records = []
    try:
        for _ in range(100):
            if server.started:
                break
            if task.done():
                await task
                raise RuntimeError("Local retrieval server exited before startup")
            await asyncio.sleep(0.1)
        if not server.started:
            raise RuntimeError("Local retrieval server did not start")
        config = replace(
            Config.from_env(),
            mcp_url=f"http://127.0.0.1:{args.port}/mcp",
            target_endpoint=TARGET,
            enable_sparql_execution=False,
            results_dir=args.output,
        )
        for item in examples[: args.limit]:
            active["id"] = item["id"]
            # Hints use only the natural-language question, never its gold query.
            hints = [
                row["label"]
                for row in rank(item["question"], docs, lambda row: row["label"] + " " + row["definition"])[
                    :3
                ]
            ]
            for mode in (
                ["deterministic", "autonomous"] if item["id"] % 2 else ["autonomous", "deterministic"]
            ):
                print(f"Example {item['id']}: {mode}", flush=True)
                result = await run_question(
                    config, item["question"], mode, hints if mode == "deterministic" else None, progress=print
                )
                metadata = {
                    "question_id": f"sphn_{item['id']:02}",
                    "title": item["title"],
                    "retrieval_backend": "local_sphn_lexical_mcp",
                    "held_out_id": item["id"],
                    "deterministic_class_hints": hints,
                    "schema_version": version,
                }
                save_result(result, args.output, jsonl=args.output / "benchmark.jsonl", metadata=metadata)
                records.append(result.to_dict())
                print(f"{result.status}: {result.end_to_end_seconds:.2f}s", flush=True)
    finally:
        server.should_exit = True
        await task
        (args.output / "summary.json").write_text(json.dumps(summarize(records), indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--examples", type=Path, required=True)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--port", type=int, default=18888)
    asyncio.run(main(parser.parse_args()))
