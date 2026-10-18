"""Model selection follows the OpenAI-compatible /models response."""
import asyncio

import httpx
import pytest

from agent_orchestration import model_discovery


def test_select_served_model_prefers_live_id_over_stale_configuration():
    assert model_discovery.select_served_model(
        {"data": [{"id": "new-model"}]}, "old-model") == "new-model"
    assert model_discovery.select_served_model(
        {"data": [{"id": "base"}, {"id": "adapter"}]}, "adapter") == "adapter"


@pytest.mark.parametrize("payload", [None, {}, {"data": []}, {"data": [{"id": "a"}, {"id": "b"}]}])
def test_select_served_model_rejects_missing_or_ambiguous_ids(payload):
    with pytest.raises(ValueError):
        model_discovery.select_served_model(payload, "old-model")


def test_discover_served_model_uses_models_endpoint_and_api_key(monkeypatch):
    real_client = httpx.AsyncClient

    def respond(request):
        assert request.url == "http://model.test/v1/models"
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"data": [{"id": "served-model"}]})

    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    monkeypatch.setattr(model_discovery.httpx, "AsyncClient",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs))
    assert asyncio.run(model_discovery.discover_served_model(
        "http://model.test/v1", "stale-model")) == "served-model"
