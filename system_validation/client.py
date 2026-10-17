"""Only HTTP clients: no model loading, no database administration via HTTP."""
from time import perf_counter
import httpx


class Clients:
    def __init__(self, config, *, transport=None):
        self.config = config
        self.http = httpx.Client(timeout=config["timeout_seconds"], transport=transport, follow_redirects=False)

    def close(self):
        self.http.close()

    def translate(self, prompt):
        started = perf_counter()
        response = self.http.post(self.config["api_url"].rstrip("/") + "/nl-to-sparql",
                                  json={"text": prompt}, headers={"X-Include-Analytics": "true"})
        elapsed = perf_counter() - started
        response.raise_for_status()
        payload = response.json()
        if (type(payload.get("is_compliant")) is not bool or not isinstance(payload.get("sparql_query"), str)
                or type(payload.get("tokens_consumed")) is not int or payload["tokens_consumed"] < 0):
            raise ValueError("Invalid API response contract")
        return payload, elapsed

    def query(self, query):
        started = perf_counter()
        response = self.http.post(self.config["virtuoso_url"],
            data={"query": query, "format": "application/sparql-results+json"},
            headers={"Accept": "application/sparql-results+json"})
        elapsed = perf_counter() - started
        response.raise_for_status()
        # Virtuoso can return HTTP 200 with an incomplete anytime result.
        state = response.headers.get("X-SQL-State")
        if state and state != "00000":
            raise ValueError(f"Virtuoso returned an incomplete/error result ({state})")
        payload = response.json()
        if not isinstance(payload.get("head", {}).get("vars"), list) or not isinstance(payload.get("results", {}).get("bindings"), list):
            raise ValueError("Virtuoso did not return SELECT Results JSON")
        return payload, elapsed
