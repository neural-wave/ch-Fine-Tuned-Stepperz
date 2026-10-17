"""Percorsi delle fixture e degli artefatti, indipendenti dalla posizione dei test."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
RESULTS = ROOT / "artifacts" / "tests"
