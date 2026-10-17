"""Compatibility imports; offline models now live in models.fakes."""
from .models.fakes import FakeClassifier, FakeLLM, FakeSparqlLLM, by_keywords, random_choice, sequence

__all__ = ["FakeClassifier", "FakeLLM", "FakeSparqlLLM", "by_keywords", "random_choice", "sequence"]
