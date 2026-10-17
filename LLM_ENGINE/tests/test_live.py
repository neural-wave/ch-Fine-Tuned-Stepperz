"""Opt in with RUN_LIVE_TESTS=1; never mocks live service responses."""

import os

import pytest

from sparql_agent.agent import run_question
from sparql_agent.cli import SMOKE_QUESTION, diagnose
from sparql_agent.config import Config
from sparql_agent.storage import save_result

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE_TESTS") != "1", reason="Set RUN_LIVE_TESTS=1 to contact live services"
    ),
]


async def test_live_connectivity_discovery_and_retrieval():
    report = await diagnose(Config.from_env())
    assert report["ok"], report


@pytest.mark.parametrize("mode", ["autonomous", "deterministic"])
async def test_live_lct(mode):
    config = Config.from_env()
    result = await run_question(config, SMOKE_QUESTION, mode)
    save_result(result, config.results_dir)
    assert result.success, result.to_dict()
    assert result.syntax_valid and result.endpoint
