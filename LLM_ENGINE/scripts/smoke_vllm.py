"""Verify exact model, basic chat, and native auto tool calls through our adapter."""

import argparse
import asyncio
import json
from dataclasses import asdict, replace
from pathlib import Path

from jsonschema import validate

from sparql_agent.config import Config
from sparql_agent.llm_client import LLMClient


async def main(output):
    config = replace(Config.from_env(), llm_max_tokens=256)
    schema = {
        "type": "object",
        "properties": {"gene": {"type": "string"}},
        "required": ["gene"],
        "additionalProperties": False,
    }
    record = {"config": config.public_settings(), "thinking": False}
    async with LLMClient(config) as llm:
        models = await llm.client.models.list()
        record["model_ids"] = [item.id for item in models.data]
        assert config.llm_model in record["model_ids"], record["model_ids"]
        record["chat"] = asdict(await llm.complete([{"role": "user", "content": "Reply with OK."}]))
        reply = await llm.complete(
            [{"role": "user", "content": "Call lookup_gene for gene LCT. Do not answer from memory."}],
            [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup_gene",
                        "description": "Look up information about a gene.",
                        "parameters": schema,
                    },
                }
            ],
        )
        record["tool_reply"] = asdict(reply)
        calls = reply.message.get("tool_calls", [])
        record["tool_valid"] = False
        output.write_text(json.dumps(record, indent=2), encoding="utf-8")
        assert calls, "No native tool call returned"
        assert calls[0]["function"]["name"] == "lookup_gene"
        arguments = json.loads(calls[0]["function"]["arguments"])
        validate(arguments, schema)
        assert arguments["gene"] == "LCT"
        record["tool_valid"] = True
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; use a new filename")
    asyncio.run(main(args.output))
