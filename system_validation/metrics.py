"""Binary malicious-request metrics and measured resource statistics."""
from collections import defaultdict
from math import sqrt
from statistics import mean, median, pstdev


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def distribution(values):
    values = sorted(values)
    if not values:
        return {"count": 0, "mean": None, "median": None, "p95": None, "min": None, "max": None}
    position = (len(values) - 1) * .95
    lower = int(position)
    p95 = values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * (position - lower)
    return {"count": len(values), "mean": mean(values), "median": median(values),
            "p95": p95, "min": values[0], "max": values[-1], "stddev": pstdev(values)}


def classification(rows):
    counts = {"tp": 0, "tn": 0, "fp": 0, "fn": 0}
    errors = {"malicious": 0, "benign": 0}
    for row in rows:
        expected, predicted = row["malicious"], row.get("predicted_malicious")
        if predicted is None:
            errors["malicious" if expected else "benign"] += 1
        else:
            key = ("tp" if predicted else "fn") if expected else ("fp" if predicted else "tn")
            counts[key] += 1
    tp, tn, fp, fn = (counts[key] for key in ("tp", "tn", "fp", "fn"))
    valid = tp + tn + fp + fn
    precision, recall = ratio(tp, tp + fp), ratio(tp, tp + fn)
    specificity = ratio(tn, tn + fp)
    return {"positive_class": "malicious", "cases": len(rows), "valid_verdicts": valid,
            "errors": errors, "confusion_matrix": counts,
            "accuracy": ratio(tp + tn, len(rows)), "accuracy_on_valid_verdicts": ratio(tp + tn, valid),
            "coverage": ratio(valid, len(rows)), "precision": precision, "recall": recall,
            "f1": ratio(2 * tp, 2 * tp + fp + fn), "specificity": specificity,
            "false_positive_rate": ratio(fp, fp + tn), "false_negative_rate": ratio(fn, fn + tp),
            "balanced_accuracy": (recall + specificity) / 2 if recall is not None and specificity is not None else None,
            "mcc": ratio(tp * tn - fp * fn, sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))),
            "malicious_detection_rate_all_attempts": ratio(tp, tp + fn + errors["malicious"]),
            "benign_acceptance_rate_all_attempts": ratio(tn, tn + fp + errors["benign"])}


def resources(rows):
    totals = [row.get("response", {}).get("tokens_consumed") for row in rows]
    models = defaultdict(lambda: {"calls_with_usage": 0, "known_input_tokens": 0, "known_output_tokens": 0,
        "known_cache_read_tokens": 0, "known_cache_write_tokens": 0, "known_reasoning_tokens": 0,
        "known_requests": 0, "missing_fields": defaultdict(int)})
    timing_values, output_rates = defaultdict(list), defaultdict(list)
    for row in rows:
        analytics = row.get("response", {}).get("analytics", {})
        stages = analytics.get("token_usage", {}).get("by_stage", {})
        timings = analytics.get("timings", {})
        for stage, seconds in timings.items():
            timing_values[stage].append(seconds)
        for stage, usage in stages.items():
            entry = models[usage.get("model") or f"unknown:{stage}"]
            entry["calls_with_usage"] += 1
            for field in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens", "requests"):
                value = usage.get(field)
                if value is None:
                    entry["missing_fields"][field] += 1
                else:
                    entry["known_" + field] += value
            if usage.get("output_tokens") is not None and timings.get(stage, 0) > 0:
                output_rates[stage].append(usage["output_tokens"] / timings[stage])
    known = [value for value in totals if value is not None]
    return {"total_tokens": sum(known) if len(known) == len(rows) else None,
            "known_total_tokens": sum(known), "calls_missing_token_usage": len(rows) - len(known),
            "calls_missing_detailed_analytics": sum("analytics" not in row.get("response", {}) for row in rows),
            "tokens_per_call": distribution(known), "by_model": dict(models),
            "api_seconds": distribution([row["api_seconds"] for row in rows]),
            "total_seconds": distribution([row["total_seconds"] for row in rows if "total_seconds" in row]),
            "effective_total_tokens_per_second": distribution([row["effective_total_tokens_per_second"] for row in rows
                if row.get("effective_total_tokens_per_second") is not None]),
            "stage_seconds": {key: distribution(values) for key, values in timing_values.items()},
            "effective_output_tokens_per_second": {key: distribution(values) for key, values in output_rates.items()},
            "virtuoso_seconds": distribution([seconds for row in rows for seconds in row.get("execution", {}).get("seconds", [])])}


def summarize(rows):
    measured = [row for row in rows if not row["warmup"]]
    categories = sorted({row.get("category", "uncategorized") for row in measured})
    return {"classification": classification(measured), "resources": resources(measured),
            "prompt_guard": classification([{**row, "predicted_malicious":
                (row["response"]["analytics"]["prompt_decision"] != "allow")
                if row.get("response", {}).get("analytics", {}).get("prompt_decision") in {"allow", "block", "review"} else None}
                for row in measured]),
            "prompt_decisions": {decision: sum(row.get("response", {}).get("analytics", {}).get("prompt_decision") == decision
                                               for row in measured) for decision in ("allow", "block", "review")},
            "warmup_resources": resources([row for row in rows if row["warmup"]]),
            "by_category": {category: classification([row for row in measured if row.get("category", "uncategorized") == category])
                            for category in categories},
            "by_case": {case_id: {"classification": classification([row for row in measured if row["id"] == case_id]),
                                  "resources": resources([row for row in measured if row["id"] == case_id])}
                        for case_id in sorted({row["id"] for row in measured})},
            "execution_statuses": {status: sum(row.get("execution", {}).get("status") == status for row in measured)
                                   for status in ("executed", "error", "not_eligible", "rejected_locally", "disabled")}}
