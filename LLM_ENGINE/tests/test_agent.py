import pytest

from sparql_agent.agent import Agent, RunResult, parse_output
from sparql_agent.config import Config
from sparql_agent.mcp_client import ToolResult

from .conftest import ENDPOINT, FINAL, FakeLLM, FakeMCP, model_reply, tool_call


async def generate(llm, mcp=None, mode="autonomous", config=None, classes=None):
    config = config or Config()
    result = RunResult("test question", config.llm_model, mode)
    return await Agent(config, llm, mcp or FakeMCP()).generate(result, classes)


async def test_autonomous_real_message_sequence_and_allowlist(fake_mcp):
    llm = FakeLLM([model_reply(calls=[tool_call()]), model_reply(FINAL)])
    result = await generate(llm, fake_mcp)
    assert result.success and result.syntax_valid
    assert result.iterations == 2 and result.total_tokens == 30
    assert result.to_dict()["tool_count"] == 1
    assert set(result.exposed_tools) == {"search_sparql_examples", "search_sparql_classes"}
    messages, schemas = llm.requests[1]
    assert messages[-2]["tool_calls"][0]["id"] == "call_1"
    assert messages[-1]["role"] == "tool" and messages[-1]["tool_call_id"] == "call_1"
    assert "Synthetic unit fixture" in messages[-1]["content"]
    assert {t["function"]["name"] for t in schemas} == set(result.exposed_tools)


async def test_deterministic_retrieves_before_single_model_call(fake_mcp):
    llm = FakeLLM([model_reply(FINAL)])
    result = await generate(llm, fake_mcp, "deterministic", classes=["Protein"])
    assert result.success and result.iterations == 1
    assert [call[0] for call in fake_mcp.calls] == ["search_sparql_examples", "search_sparql_classes"]
    messages, schemas = llm.requests[0]
    assert schemas is None
    assert "Actual SIB MCP example retrieval" in messages[2]["content"]


@pytest.mark.parametrize("arguments", ["{broken", "[]", '{"question": 42, "steps": []}', "{}"])
async def test_bad_arguments_are_returned_as_tool_errors_then_recover(arguments):
    mcp = FakeMCP()
    llm = FakeLLM(
        [
            model_reply(calls=[tool_call(arguments=arguments)]),
            model_reply(calls=[tool_call(call_id="fixed")]),
            model_reply(FINAL),
        ]
    )
    result = await generate(llm, mcp)
    assert result.success and len(mcp.calls) == 1
    assert not result.tools[0].invoked and result.tools[0].error
    assert "error" in llm.requests[1][0][-1]["content"]


async def test_models_without_tools_fail_at_exact_iteration_limit():
    llm = FakeLLM([model_reply(FINAL) for _ in range(3)])
    result = await generate(llm, config=Config(max_agent_iterations=3))
    assert not result.success and result.status == "max_iterations"
    assert result.iterations == len(llm.requests) == 3
    assert not result.tools and result.generated_query is None
    assert "without successful" in result.errors[0]


async def test_repeated_tool_calls_cannot_trigger_extra_model_iteration():
    llm = FakeLLM([model_reply(calls=[tool_call()]) for _ in range(2)])
    result = await generate(llm, config=Config(max_agent_iterations=2))
    assert result.status == "max_iterations" and len(llm.requests) == 2
    assert result.to_dict()["tool_count"] == 2


@pytest.mark.parametrize(
    "outcome",
    [
        ToolResult('{"query_examples": []}', empty=True),
        ToolResult("server failed", is_error=True),
        RuntimeError("offline"),
    ],
)
async def test_deterministic_retrieval_failure_never_invents_context(outcome):
    llm = FakeLLM([])
    result = await generate(llm, FakeMCP([outcome]), "deterministic")
    assert not result.success and result.status == "retrieval_failed"
    assert llm.requests == [] and result.errors


async def test_empty_autonomous_result_is_not_grounding():
    llm = FakeLLM([model_reply(calls=[tool_call()]), model_reply(FINAL)])
    result = await generate(
        llm, FakeMCP([ToolResult("[]", empty=True)]), config=Config(max_agent_iterations=2)
    )
    assert not result.success and result.status == "max_iterations"
    assert result.tools[0].empty


async def test_execution_tool_denied_even_if_execution_feature_enabled():
    llm = FakeLLM([model_reply(calls=[tool_call("execute_sparql_query")])])
    mcp = FakeMCP()
    result = await generate(llm, mcp, config=Config(enable_sparql_execution=True, max_agent_iterations=1))
    assert mcp.calls == [] and not result.tools[0].invoked
    assert "not an allowed" in result.tools[0].error


async def test_missing_example_tool_is_clear_failure(fake_mcp):
    del fake_mcp.specs["search_sparql_examples"]
    result = await generate(FakeLLM([]), fake_mcp)
    assert result.status == "missing_tools"


async def test_llm_failure_records_attempt_and_unknown_tokens():
    result = await generate(FakeLLM([RuntimeError("unavailable")]), mode="deterministic")
    assert result.status == "llm_error" and result.iterations == 1
    assert result.total_tokens is None and not result.usage_complete
    assert result.llm_calls[0]["error"]


async def test_missing_token_usage_is_not_reported_as_zero():
    result = await generate(FakeLLM([model_reply(FINAL, tokens=False)]), mode="deterministic")
    assert result.success and not result.usage_complete
    assert result.total_tokens is None


async def test_truncated_completion_is_not_success():
    result = await generate(
        FakeLLM([model_reply(FINAL, finish_reason="length")]),
        mode="deterministic",
        config=Config(max_agent_iterations=1),
    )
    assert not result.success and "LLM_MAX_TOKENS" in result.errors[0]


async def test_output_syntax_repair():
    bad = f"```sparql\n#+ endpoint: {ENDPOINT}\nSELECT WHERE {{\n```"
    result = await generate(FakeLLM([model_reply(bad), model_reply(FINAL)]), mode="deterministic")
    assert result.success and result.errors and result.iterations == 2


async def test_multiple_tool_calls_preserve_each_call_id():
    llm = FakeLLM(
        [
            model_reply(
                calls=[
                    tool_call(call_id="a"),
                    tool_call("search_sparql_classes", {"classes": ["Protein"]}, "b"),
                ]
            ),
            model_reply(FINAL),
        ]
    )
    result = await generate(llm)
    assert result.success
    assert [m["tool_call_id"] for m in llm.requests[1][0] if m["role"] == "tool"] == ["a", "b"]


async def test_tool_call_batch_bound():
    llm = FakeLLM([model_reply(calls=[tool_call(call_id="a"), tool_call(call_id="b")]), model_reply(FINAL)])
    mcp = FakeMCP()
    result = await generate(llm, mcp, config=Config(max_tools_per_iteration=1))
    assert result.success and len(mcp.calls) == 1 and len(result.tools) == 2
    assert result.tools[1].error


def test_syntax_checker_detects_undefined_prefix_and_endpoint_mismatch():
    missing_prefix = f"```sparql\n#+ endpoint: {ENDPOINT}\nSELECT ?s WHERE {{?s a madeup:Thing}}\n```"
    assert parse_output(missing_prefix, ENDPOINT)[2] is False
    assert parse_output(FINAL, "https://example.org/sparql")[3]
    assert parse_output(FINAL + FINAL, ENDPOINT)[0] is None
