"""Attacchi di query: sintassi valida, blocco effettivo e controlli positivi."""

from tests.paths import FIXTURES

import json

import pytest
from rdflib.plugins.sparql.parser import parseQuery, parseUpdate

from sparql_analyzer.compliance import validate
from sparql_analyzer.execution.service import ResultBlocked, execute_checked
from tools.generate_synthetic_data import generate

ROOT = FIXTURES / "adversarial"
CASES = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_adversarial_case(case, monkeypatch):
    query = (ROOT / "queries" / case["file"]).read_text(encoding="utf-8")
    if case["kind"] == "query":
        parseQuery(query)  # Un test di sicurezza non passa per un refuso sintattico.
    elif case["kind"] == "update":
        parseUpdate(query)
    verdict = validate(query)
    dataset = generate()
    if case["stage"] == "static":
        assert not verdict["is_compliant"], verdict
        if case["kind"] != "dialect":
            assert not any(f["code"] == "SYNTAX" for f in verdict["findings"]), verdict

        def forbidden(*args, **kwargs):
            pytest.fail("La query bloccata non deve raggiungere il database")

        monkeypatch.setattr(dataset, "query", forbidden)
        with pytest.raises(ResultBlocked):
            execute_checked(dataset, query)
    elif case["expected"] == "blocked":
        assert verdict["is_compliant"], "Questo caso deve esercitare il runtime, non il blocco statico"
        with pytest.raises(ResultBlocked):
            execute_checked(dataset, query)
    else:
        result = execute_checked(dataset, query)
        assert result["results"]["bindings"][0][next(iter(result["head"]["vars"]))]["value"] == case.get("expected_value", "8")
