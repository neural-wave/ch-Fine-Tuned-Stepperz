"""Real model inference requires explicit opt-in, including in Test Explorer."""
import pytest


def pytest_addoption(parser):
    parser.addoption("--run-model-health", action="store_true", default=False,
                     help="Load real models and run inference health checks")
    parser.addoption("--model-config", default="config/agents/models.json",
                     help="Model configuration used by real health checks")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-model-health"):
        skip = pytest.mark.skip(reason="Real inference disabled; use --run-model-health")
        for item in items:
            if item.get_closest_marker("model_health"):
                item.add_marker(skip)
