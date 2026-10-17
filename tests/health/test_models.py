"""Explicit real-inference smoke tests; never execute the generated query."""
import asyncio
from pathlib import Path
from time import perf_counter

import pytest
from rdflib.plugins.sparql.parser import parseQuery

from agent_orchestration.local_models import load_classifier, open_generator
from agent_orchestration.models import SparqlRequest

pytestmark = pytest.mark.model_health

REQUEST = SparqlRequest(
    prompt="Return the total number of patients as ?patients in a single SELECT query.",
    schema="PREFIX ex: <urn:health:>\nPatient instances have rdf:type ex:Patient.",
    policy="Only aggregate counts are authorized. Never disclose individual records.",
    permissions="The user may request the total patient count.",
)


@pytest.fixture
def model_config(pytestconfig):
    path = Path(pytestconfig.getoption("--model-config")).resolve()
    assert path.is_file(), f"Model configuration not found: {path}"
    return path


def test_classifier_health(model_config, record_property):
    """Load the real configured classifier and check its decision contract."""
    async def exercise():
        guard = await load_classifier(model_config)
        return await guard.run(REQUEST)

    started = perf_counter()
    verdict = asyncio.run(exercise())
    record_property("elapsed_seconds", round(perf_counter() - started, 3))
    record_property("decision", verdict.decision)
    assert verdict.decision in {"allow", "block", "review"}
    assert verdict.reason.strip()
    assert verdict.probability is None or 0 <= verdict.probability <= 1


def test_generator_health(model_config, record_property):
    """Use the production generator/MCP wiring and require parseable SELECT output."""
    async def exercise():
        async with open_generator(model_config) as generator:
            return await generator.run(REQUEST)

    started = perf_counter()
    result = asyncio.run(exercise())
    record_property("elapsed_seconds", round(perf_counter() - started, 3))
    assert result.query.strip()
    parsed = parseQuery(result.query)
    assert parsed[1].name == "SelectQuery", result.query
