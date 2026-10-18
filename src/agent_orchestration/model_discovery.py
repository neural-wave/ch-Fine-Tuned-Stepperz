"""Resolve the model identifier advertised by an OpenAI-compatible server."""
import os

import httpx


def select_served_model(payload, configured_model=None):
    """Use the advertised ID, refusing to guess when several models are served."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Model endpoint returned an invalid /models response")
    ids = [row.get("id") for row in payload["data"] if isinstance(row, dict)]
    ids = list(dict.fromkeys(value for value in ids if isinstance(value, str) and value.strip()))
    if configured_model in ids:
        return configured_model
    if len(ids) == 1:
        return ids[0]
    if not ids:
        raise ValueError("Model endpoint returned no usable model ID")
    raise ValueError(f"Model endpoint advertises multiple IDs {ids!r}; configure one of them")


async def discover_served_model(base_url, configured_model=None):
    """GET /v1/models once at API startup, using the model server API key."""
    url = base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {os.getenv('MODEL_API_KEY', 'local')}"}
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
    return select_served_model(response.json(), configured_model)
