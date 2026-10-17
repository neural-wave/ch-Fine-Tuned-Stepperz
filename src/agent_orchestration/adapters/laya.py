"""Native Laya loading and decision adapter, independent of chat/MCP clients."""
import asyncio
import json
import logging
from pathlib import Path
from threading import Lock
from .mcp import CONFIG
from .native import CallableSystemOneModel
from ..models import Decision, ModelResponse, TokenUsage
from ..logging_setup import backend_log_level, configure_logging
from ..validation import SystemOnePromptValidator

logger = logging.getLogger(__name__)

def laya_validator(agent, max_len=8192, *, model_id=None):
    lock = Lock()

    def predict(request):
        with lock:
            result = agent.predict(request.state, {"decision": {
                "type": "choice", "instructions": request.question,
                "criteria": dict(request.options),
            }}, max_len=max_len)
        usage = result.get("usage", {})
        tokens = TokenUsage.from_backend({**usage, "output_tokens": 0, "requests": 1}, model=model_id)
        try:
            if usage.get("truncated") or usage.get("state_tokens_dropped") or usage.get("options"):
                raise ValueError("Laya input or decision options were truncated")
            answer = result["answers"]["decision"]
            logger.log(backend_log_level(), "Classifier response choice=%s probability=%s low_confidence=%s usage=%r",
                        answer.get("choice"), answer.get("answer_confidence"), answer.get("low_confidence"), tokens)
            decision = (Decision("review") if answer.get("low_confidence") else
                        Decision(answer["choice"], answer.get("answer_confidence")))
            return ModelResponse(decision, tokens)
        except BaseException as error:
            error.token_usage = tokens
            raise

    return SystemOnePromptValidator(CallableSystemOneModel(predict))


async def load_classifier(config_path=CONFIG):
    """Load only the configured native classifier, without the generator or MCP."""
    configure_logging()
    logger.info("Classifier loading started config=%s", config_path)
    import laya

    config = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    settings = dict(config["laya"])
    model_id = settings.pop("model_id")
    max_len = settings.pop("max_len", 8192)
    logger.info("Classifier model=%s device=%s", model_id, settings.get("device", "default"))
    decision_model = await asyncio.to_thread(laya.load, model_id, **settings)
    logger.info("Classifier loaded model=%s", model_id)
    return laya_validator(decision_model, max_len, model_id=model_id)


