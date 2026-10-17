import json
from dataclasses import replace

import pytest

from sparql_agent.agent import RunResult
from sparql_agent.benchmark import percentile, summarize
from sparql_agent.cli import execute_saved
from sparql_agent.config import Config
from sparql_agent.storage import save_result


@pytest.mark.parametrize(
    "values",
    [
        {"max_agent_iterations": 0},
        {"llm_temperature": float("nan")},
        {"llm_base_url": "file:///tmp"},
        {"llm_extra_body": []},
        {"llm_extra_body": {"tools": []}},
    ],
)
def test_configuration_rejects_invalid_values(values):
    with pytest.raises(ValueError):
        Config(**values)


def test_environment_overrides_dotenv_and_secret_not_recorded(tmp_path, monkeypatch):
    env = tmp_path / "settings.env"
    env.write_text("LLM_MODEL=from-file\nLLM_API_KEY=secret-value\n", encoding="utf-8")
    monkeypatch.setenv("LLM_MODEL", "from-shell")
    monkeypatch.setenv("LLM_API_KEY", "secret-value")
    config = Config.from_env(env)
    assert config.llm_model == "from-shell"
    assert "secret-value" not in str(config.public_settings()) and "secret-value" not in repr(config)


async def test_execution_disabled_before_file_or_network_access():
    with pytest.raises(ValueError, match="Execution is disabled"):
        await execute_saved(Config(), None)


def test_summary_keeps_failures_and_excludes_warmup():
    def row(seconds, success, phase="measured", tokens=10, complete=True):
        return dict(
            model="test",
            mode="autonomous",
            phase=phase,
            end_to_end_seconds=seconds,
            retrieval_seconds=1,
            llm_seconds=seconds - 1,
            success=success,
            tool_attempts=2,
            tool_successes=1,
            total_tokens=tokens,
            usage_complete=complete,
        )

    result = summarize([row(1000, True, "warmup"), row(2, True), row(4, False, tokens=None, complete=False)])[
        0
    ]
    assert result["mean_seconds"] == 3 and result["successful_query_generation_rate"] == 0.5
    assert result["tool_use_success_rate"] == 0.5 and result["average_total_tokens"] == 10
    assert result["runs_with_complete_token_usage"] == 1
    assert result["p95_seconds"] == pytest.approx(3.9)
    assert percentile([], 0.95) is None


def test_storage_preserves_failed_attempts_and_candidate_queries(tmp_path):
    config = replace(Config(), results_dir=tmp_path)
    result = RunResult("fixture", "test", "autonomous", status="max_iterations", generated_query="bad query")
    paths = save_result(result, config.results_dir)
    assert (tmp_path / f"{result.run_id}.rq").read_text().strip() == "bad query"
    saved = json.loads((tmp_path / "runs.jsonl").read_text())
    assert not saved["success"] and saved["status"] == "max_iterations"
    assert paths["record"]
