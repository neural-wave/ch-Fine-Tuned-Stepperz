"""Tampering del risultato al confine di restituzione, con soli dati fittizi."""

import json
from types import SimpleNamespace

import pytest

from sparql_analyzer.demo import EXAMPLE_QUERY
from sparql_analyzer.runtime import ResultBlocked, execute_checked
from tests.generate_synthetic_data import generate


@pytest.mark.parametrize("mutation", [
    "uri", "identifier", "numeric_identifier", "email", "fragment", "language",
    "head_link", "row_extra", "debug", "boolean", "scientific", "nan",
])
def test_backend_payload_is_checked_before_release(monkeypatch, mutation):
    dataset = generate()
    original = dataset.query
    calls = 0

    def tampered(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls != 2:
            return result
        payload = json.loads(result.serialize(format="json"))
        cell = payload["results"]["bindings"][0]["patients"]
        if mutation == "uri":
            cell.clear()
            cell.update(type="uri", value="urn:synthetic:patient-0000")
        elif mutation in {"identifier", "numeric_identifier", "email", "fragment", "scientific", "nan"}:
            cell["value"] = {
                "identifier": "SYNTH-0000", "numeric_identifier": "123456789",
                "email": "synthetic-0000@example.invalid", "fragment": "SYNTH",
                "scientific": "8e0", "nan": "NaN",
            }[mutation]
        elif mutation == "language":
            cell["xml:lang"] = "it"
        elif mutation == "head_link":
            payload["head"]["link"] = ["urn:synthetic:private-metadata"]
        elif mutation == "row_extra":
            payload["results"]["bindings"][0]["identifier"] = {"type": "literal", "value": "SYNTH-0000"}
        elif mutation == "debug":
            payload["debug"] = "SYNTH-0000"
        else:
            cell["value"] = True
        return SimpleNamespace(serialize=lambda **kwargs: json.dumps(payload))

    monkeypatch.setattr(dataset, "query", tampered)
    with pytest.raises(ResultBlocked) as error:
        execute_checked(dataset, EXAMPLE_QUERY)
    assert calls == 2  # Non si e fermato al parser: ha verificato il risultato.
    assert "SYNTH-0000" not in str(error.value)
    assert "example.invalid" not in str(error.value)
