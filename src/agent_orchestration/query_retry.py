"""Feedback for bounded query repair, without changing the original request."""
from dataclasses import replace


def validate_query_retries(value):
    if type(value) is not int or value < 0:
        raise ValueError("query_retries must be a nonnegative integer (0 disables repair)")
    return value


def attempt_for_log(attempt):
    """The formatted query is already logged separately, once per attempt."""
    return {key: value for key, value in attempt.items() if key != "query"}


def repair_request(request, attempts):
    history = tuple({"attempt": row["attempt"], "query": row["query"],
                     "status": row["analysis"].get("status", row.get("status", "unsupported")),
                     "findings": [dict(finding) for finding in row["analysis"].get("findings", [])],
                     "forbidden_operators": list(row["analysis"].get("forbidden_operators", []))}
                    for row in attempts if row.get("analysis") is not None)
    return replace(request, feedback=history)
