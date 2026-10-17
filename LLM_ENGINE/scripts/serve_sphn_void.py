"""Serve SPHN-only VoID retrieval over loopback MCP; no SPARQL execution tool."""

import argparse
from pathlib import Path

from sparql_agent.sphn_retrieval import SphnVoidRetrieval, build_server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--void-file", type=Path, default=Path("metadata/sphn-schema-void.ttl"))
    parser.add_argument("--ontology", type=Path, default=Path("data/sphn/sphn-2026.1.ttl"))
    parser.add_argument("--port", type=int, default=18888)
    args = parser.parse_args()
    retrieval = SphnVoidRetrieval(args.void_file, args.ontology)
    print(f"Loaded {len(retrieval.classes)} SPHN classes and {len(retrieval.examples)} VoID patterns", flush=True)
    build_server(retrieval).run(transport="streamable-http", host="127.0.0.1",
                                port=args.port, stateless_http=True, json_response=True)


if __name__ == "__main__":
    main()
