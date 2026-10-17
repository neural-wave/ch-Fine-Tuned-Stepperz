import copy

import pytest

from tools.generate_system_dataset import build, equivalent, expected_count


def test_comparator_preserves_duplicates():
    first = expected_count(8)
    duplicated = copy.deepcopy(first)
    duplicated["results"]["bindings"] *= 2
    assert not equivalent(first, duplicated)


def test_comparator_ignores_row_order_but_preserves_term_types():
    first = expected_count(8)
    first["results"]["bindings"] += expected_count(9)["results"]["bindings"]
    reordered = copy.deepcopy(first)
    reordered["results"]["bindings"].reverse()
    assert equivalent(first, reordered)
    reordered["results"]["bindings"][0]["patients"]["datatype"] = "http://www.w3.org/2001/XMLSchema#string"
    assert not equivalent(first, reordered)


def test_comparator_ask_and_empty_results():
    assert equivalent({"boolean": False}, {"boolean": False})
    assert not equivalent({"boolean": True}, {"boolean": False})
    empty = {"head": {"vars": ["x"]}, "results": {"bindings": []}}
    assert equivalent(empty, empty)
    assert not equivalent(empty, {"head": {"vars": ["y"]}, "results": {"bindings": []}})


def test_blank_nodes_require_explicit_comparator():
    payload = {"head": {"vars": ["x"]}, "results": {"bindings": [{"x": {"type": "bnode", "value": "a"}}]}}
    with pytest.raises(ValueError, match="Blank-node"):
        equivalent(payload, payload)


def test_benchmark_ground_truth_and_security_are_separate(tmp_path):
    rows = build(tmp_path)
    assert len(rows) == 24
    assert len({row["id"] for row in rows}) == 24
    for row in rows:
        assert (tmp_path / row["fixture"]).exists()
        assert row["expected_result_match"] == row["observed"]["result_match"]
        assert row["expected_security_outcome"] == row["observed"]["security_outcome"]
    assert any(row["expected_result_match"] is True and row["expected_security_outcome"] == "blocked" for row in rows)
    assert any(row["expected_result_match"] is False and row["expected_security_outcome"] == "released" for row in rows)
