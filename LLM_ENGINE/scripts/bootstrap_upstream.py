"""Fetch the inspected upstream revisions without modifying existing checkouts."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    sources = json.loads((ROOT / "upstream.lock.json").read_text(encoding="utf-8"))
    for name, source in sources.items():
        target = ROOT / "external" / name
        if target.exists():
            actual = subprocess.check_output(
                ["git", "-C", str(target), "rev-parse", "HEAD"], text=True
            ).strip()
            if actual != source["revision"]:
                raise SystemExit(
                    f"{target} is at {actual}; expected {source['revision']}. Existing checkout left intact."
                )
        else:
            subprocess.run(
                ["git", "clone", "--no-checkout", "--filter=blob:none", source["url"], str(target)],
                check=True,
            )
            subprocess.run(["git", "-C", str(target), "checkout", "--detach", source["revision"]], check=True)
        print(f"{name}: {source['revision']}")


if __name__ == "__main__":
    main()
