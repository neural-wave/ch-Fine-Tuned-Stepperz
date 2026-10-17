"""Same questions, alternating mode order, separately recorded warm-up runs."""

import argparse
import asyncio
import json
import math
import statistics
import sys
import uuid
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

from .agent import error_text, run_question
from .config import Config
from .storage import save_result


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * fraction
    low, high = math.floor(index), math.ceil(index)
    return values[low] + (values[high] - values[low]) * (index - low)


def summarize(records: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for row in records:
        if row.get("phase") == "measured":
            groups[(row["model"], row["mode"])].append(row)
    summaries = []
    for (model, mode), rows in sorted(groups.items()):
        latencies = [row["end_to_end_seconds"] for row in rows]
        tokens = [
            row["total_tokens"]
            for row in rows
            if row.get("usage_complete") and row.get("total_tokens") is not None
        ]
        attempts = sum(row["tool_attempts"] for row in rows)
        successes = sum(row["tool_successes"] for row in rows)
        summaries.append(
            {
                "model": model,
                "mode": mode,
                "runs": len(rows),
                "mean_seconds": statistics.mean(latencies),
                "median_seconds": statistics.median(latencies),
                "p95_seconds": percentile(latencies, 0.95),
                "successful_query_generation_rate": sum(row["success"] for row in rows) / len(rows),
                "tool_use_success_rate": successes / attempts if attempts else None,
                "tool_attempts": attempts,
                "tool_successes": successes,
                "average_total_tokens": statistics.mean(tokens) if tokens else None,
                "runs_with_complete_token_usage": len(tokens),
                "mean_retrieval_seconds": statistics.mean(row["retrieval_seconds"] for row in rows),
                "mean_llm_seconds": statistics.mean(row["llm_seconds"] for row in rows),
            }
        )
    return summaries


async def benchmark(
    config: Config,
    questions: list[dict],
    modes: list[str],
    repeats: int,
    warmups: int,
    output: Path,
    *,
    with_classes=False,
) -> list[dict]:
    records = []
    for phase, repetitions in (("warmup", warmups), ("measured", repeats)):
        selected = questions[:1] if phase == "warmup" else questions
        for repeat in range(repetitions):
            for index, item in enumerate(selected):
                # Alternate which mode runs first to reduce systematic order effects.
                ordered = modes if (repeat + index) % 2 == 0 else list(reversed(modes))
                for mode in ordered:
                    print(f"{phase} {repeat + 1}: {item['id']} / {mode}", file=sys.stderr, flush=True)
                    result = await run_question(
                        config,
                        item["question"],
                        mode,
                        item.get("classes") if with_classes else None,
                        progress=lambda text: print(f"  {text}", file=sys.stderr, flush=True),
                        phase=phase,
                    )
                    metadata = {
                        "question_id": item["id"],
                        "source": item.get("source"),
                        "repeat": repeat + 1,
                        "with_classes": with_classes,
                    }
                    save_result(result, config.results_dir, jsonl=output, metadata=metadata)
                    records.append(result.to_dict())
                    print(f"  {result.status}: {result.end_to_end_seconds:.2f}s", file=sys.stderr, flush=True)
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=Path("tests/questions.json"))
    parser.add_argument(
        "--modes", nargs="+", choices=["autonomous", "deterministic"], default=["autonomous", "deterministic"]
    )
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--warmups", type=int, default=1, help="Warm-up runs per mode, excluded from summary")
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--with-classes", action="store_true", help="Use question class hints in deterministic mode"
    )
    parser.add_argument("--model")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.repeats < 1 or args.warmups < 0 or (args.limit is not None and args.limit < 1):
            raise ValueError("repeats/limit must be positive and warmups must be non-negative")
        config = Config.from_env(args.env_file)
        if args.model:
            config = replace(config, llm_model=args.model)
        questions = json.loads(args.questions.read_text(encoding="utf-8"))
        if (
            not isinstance(questions, list)
            or not questions
            or any(
                not isinstance(item, dict)
                or not item.get("id")
                or not isinstance(item.get("question"), str)
                or not item["question"].strip()
                for item in questions
            )
        ):
            raise ValueError("Questions must be a non-empty list of objects with id and question")
        if len({item["id"] for item in questions}) != len(questions):
            raise ValueError("Question IDs must be unique")
        questions = questions[: args.limit]
        output = args.output or config.results_dir / f"benchmark-{uuid.uuid4().hex}.jsonl"
        if output.exists():
            raise ValueError(f"Refusing to mix runs with an existing benchmark file: {output}")
        records = asyncio.run(
            benchmark(
                config,
                questions,
                list(dict.fromkeys(args.modes)),
                args.repeats,
                args.warmups,
                output,
                with_classes=args.with_classes,
            )
        )
        summary = summarize(records)
        summary_path = output.with_suffix(".summary.json")
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print("Model | Mode | N | Mean / Median / p95 seconds | Generation | Tool success | Avg tokens")
        for row in summary:
            tools = (
                f"{row['tool_use_success_rate']:.0%}" if row["tool_use_success_rate"] is not None else "n/a"
            )
            tokens = (
                f"{row['average_total_tokens']:.0f}" if row["average_total_tokens"] is not None else "n/a"
            )
            print(
                f"{row['model']} | {row['mode']} | {row['runs']} | {row['mean_seconds']:.2f} / "
                f"{row['median_seconds']:.2f} / {row['p95_seconds']:.2f} | "
                f"{row['successful_query_generation_rate']:.0%} | {tools} | {tokens}"
            )
        print(f"Results: {output}\nSummary: {summary_path}")
        # Failures stay in the denominator; a partial benchmark returns nonzero.
        code = 0 if all(row["success"] for row in records) else 1
    except (Exception, KeyboardInterrupt) as exc:
        print(error_text(exc), file=sys.stderr)
        code = 130 if isinstance(exc, KeyboardInterrupt) else 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
