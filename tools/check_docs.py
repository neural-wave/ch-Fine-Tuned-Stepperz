"""Verifica i percorsi locali nei link Markdown del repository."""
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def main():
    documents = [ROOT / "README.md", ROOT / "LLM_ENGINE" / "README.md"]
    for folder in ("docs", "tests", "tools", "examples", "infra", "src", "config", "schemas", "system_validation", "benchmark"):
        documents.extend((ROOT / folder).rglob("*.md"))
    broken, checked = [], 0
    for path in documents:
        for match in re.finditer(r"\[[^\]]*\]\(([^)\s]+)\)", path.read_text(encoding="utf-8")):
            target = match[1]
            if urlsplit(target).scheme or target.startswith("#"):
                continue
            local = unquote(target.split("#", 1)[0])
            if not local:
                continue
            checked += 1
            if not (path.parent / local).exists():
                line = path.read_text(encoding="utf-8")[:match.start()].count("\n") + 1
                broken.append(f"{path.relative_to(ROOT)}:{line}: {target}")
    for item in broken:
        print(item)
    print(f"{checked} link locali controllati; {len(broken)} non risolti.")
    return int(bool(broken))


if __name__ == "__main__":
    raise SystemExit(main())
