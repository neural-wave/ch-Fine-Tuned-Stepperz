"""Run SIB's unchanged MCP app, binding its supported transport to the container interface."""

from sparql_llm.mcp_server import get_mcp_app, get_transport_security

if __name__ == "__main__":
    get_mcp_app().run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8888,
        stateless_http=True,
        json_response=True,
        transport_security=get_transport_security(),
    )
