"""Offline contract checks without inference or provider dependencies."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.offline_workflow

from agent_orchestration import (
    Decision, DecisionRequest, LLM, PydanticAILLM, PydanticAISparqlLLM,
    SparqlLLM, SparqlRequest, SparqlResult, SystemOneModel,
)


class ModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_delegation(self):
        agent = SimpleNamespace(run=AsyncMock(return_value=SimpleNamespace(output="answer")))
        self.assertEqual(await PydanticAILLM(agent).run("question"), "answer")
        agent.run.assert_awaited_once_with("question")

    async def test_sparql_context_preserved(self):
        query = SparqlResult("SELECT * WHERE { ?s ?p ?o }")
        agent = SimpleNamespace(run=AsyncMock(return_value=SimpleNamespace(output=query)))
        result = await PydanticAISparqlLLM(agent).run(SparqlRequest("request", "schema", "policy"))
        self.assertEqual(result, query)
        self.assertEqual(json.loads(agent.run.call_args.args[0]), {
            "prompt": "request", "schema": "schema", "policy": "policy", "permissions": "",
        })

    async def test_invalid_sparql_outputs_rejected(self):
        for output, error in [("raw text", TypeError), (SparqlResult(" "), ValueError)]:
            agent = SimpleNamespace(run=AsyncMock(return_value=SimpleNamespace(output=output)))
            with self.assertRaises(error):
                await PydanticAISparqlLLM(agent).run(SparqlRequest("p", "s", "policy"))

    async def test_backend_error_propagates(self):
        agent = SimpleNamespace(run=AsyncMock(side_effect=RuntimeError("offline")))
        with self.assertRaises(RuntimeError):
            await PydanticAILLM(agent).run("request")

    def test_contracts_are_abstract(self):
        for contract in (LLM, SparqlLLM, SystemOneModel):
            with self.assertRaises(TypeError):
                contract()

    def test_decision_validation(self):
        for probability in (-0.1, 1.1, float("nan")):
            with self.assertRaises(ValueError):
                Decision("block", probability)
        with self.assertRaises(ValueError):
            DecisionRequest("state", "question", {"only": "one option"})
