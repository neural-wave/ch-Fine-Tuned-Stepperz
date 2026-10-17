"""Tiny subprocess server used only by local-model integration tests."""
from mcp.server.fastmcp import FastMCP

server = FastMCP("native-test-schema")


@server.tool()
def get_classes_schema(classes: list[str]) -> str:
    return "sphn:BilledDiagnosis: each patient graph contains diagnosis events."


@server.tool()
def execute_sparql_query(query: str) -> str:
    raise AssertionError("Execution tool must never be exposed to the generator")


if __name__ == "__main__":
    server.run(transport="stdio")
