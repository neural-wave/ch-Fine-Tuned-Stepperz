"""Rigenera gli esempi JSON e il catalogo dal registro dei controlli."""

import json
from pathlib import Path

from sparql_analyzer.configuration.policy import CHECKS, DEFAULT_POLICY, Policy


def main():
    root = Path(__file__).resolve().parents[3]
    if not (root / "pyproject.toml").is_file() or not (root / "src" / "sparql_analyzer").is_dir():
        raise RuntimeError("L'export delle policy richiede il checkout del repository.")
    directory = root / "config" / "policies"
    directory.mkdir(exist_ok=True)
    for name, policy in (("default", DEFAULT_POLICY), ("adequacy", Policy.adequacy()), ("hardened", Policy.hardened()), ("unrestricted", Policy(enabled_checks=frozenset()))):
        (directory / (name + ".json")).write_text(json.dumps(policy.to_dict(), indent=2) + "\n", encoding="utf-8")
    catalog = ["# Catalogo dei controlli\n",
               "Generato dal registro `src/sparql_analyzer/configuration/policy.py`. Privacy e adeguatezza SHACL sono opt-in nel profilo predefinito e attive nel profilo hardened. Il profilo adequacy abilita i controlli SHACL senza le opzioni privacy.\n",
               "| Interruttore | Effetto | Richiede | Default |", "|---|---|---|---|"]
    for name, check in CHECKS.items():
        dependencies = ", ".join(f"`{r}`" for r in check.requires)
        catalog.append(f"| `{name}` | {check.description} | {dependencies} | {str(check.default_enabled).lower()} |")
    (root / "docs" / "policies" / "checks.md").write_text("\n".join(catalog) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
