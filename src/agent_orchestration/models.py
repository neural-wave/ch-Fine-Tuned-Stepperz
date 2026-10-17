"""Backend-independent async contracts for generation and decisions."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, Mapping, TypeVar

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class Model(ABC, Generic[InputT, OutputT]):
    @abstractmethod
    async def run(self, request: InputT) -> OutputT:
        """Evaluate input without executing generated queries or actions."""
        raise NotImplementedError


class LLM(Model[str, str]):
    """Generative text model."""


@dataclass(frozen=True)
class SparqlRequest:
    prompt: str
    schema: str
    policy: str
    permissions: str = ""


@dataclass(frozen=True)
class SparqlResult:
    """Generated query; this does not certify syntax or security."""
    query: str


class SparqlLLM(Model[SparqlRequest, SparqlResult]):
    """Generate SPARQL against an explicit schema and policy."""


@dataclass(frozen=True)
class DecisionRequest:
    """State includes the prompt/query and any permissions and policy.

    Options map allowed answer keys to their descriptions.
    """
    state: str
    question: str
    options: Mapping[str, str]

    def __post_init__(self) -> None:
        if len(self.options) < 2 or any(not key.strip() for key in self.options):
            raise ValueError("Provide at least two options with nonempty keys")


@dataclass(frozen=True)
class Decision:
    """Probability is optional and does not constitute a safety guarantee."""
    choice: str
    probability: float | None = None

    def __post_init__(self) -> None:
        if not self.choice.strip():
            raise ValueError("choice must not be empty")
        if self.probability is not None and not 0 <= self.probability <= 1:
            raise ValueError("probability must be between zero and one")


class SystemOneModel(Model[DecisionRequest, Decision]):
    """Native decision backend, independently of chat/generation APIs.

    Implementations must return a choice in request.options and raise on
    backend failures rather than implicitly allowing a request.
    """
