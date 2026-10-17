"""Sonde mirate a ottenere dati non anonimi con operatori ammessi.

Le osservazioni dei bypass sono dimostrazioni di rischio; i requisiti di blocco
sono test separati xfail strict. Nessun database remoto viene interrogato.
"""

from decimal import Decimal

import pytest
from rdflib.plugins.sparql.parser import parseQuery

from sparql_analyzer.runtime import ResultBlocked, execute_checked
from tests.complex_attacks import CASES, observe, prepare


PARAMETERS = [pytest.param(case, id=case["id"],
                           marks=pytest.mark.risk_demonstration if case["expected"] == "leak" else ())
              for case in CASES]


@pytest.mark.parametrize("case", PARAMETERS)
def test_complex_attack_observation(case):
    _, query = prepare(case)
    parseQuery(query)  # Non si considera una query malformata un attacco sventato.
    result = observe(case)
    assert result["observed"] != "controller_error", result
    if case["expected"] == "blocked":
        assert result["observed"] in {"blocked_static", "blocked_runtime"}, result
    else:
        assert result["static_verdict"]["is_compliant"], result
        assert result["observed"] == "released", result
        actual = Decimal(result["result"]["results"]["bindings"][0]["summary"]["value"])
        assert actual == Decimal(case["expected_value"]), result


@pytest.mark.security_gap
@pytest.mark.parametrize("case", [
    pytest.param(case, id=case["id"], marks=pytest.mark.xfail(
        strict=True, raises=pytest.fail.Exception,
        reason="BYPASS-COMPLEX: " + case["reason"],
    ))
    for case in CASES if case["expected"] == "leak"
])
def test_complex_privacy_leak_must_be_blocked(case):
    dataset, query = prepare(case)
    # Un crash inatteso non soddisfa il requisito e non diventa xfail.
    # Un blocco introdotto in futuro genera XPASS strict: aggiornare il corpus.
    with pytest.raises(ResultBlocked):
        execute_checked(dataset, query)
