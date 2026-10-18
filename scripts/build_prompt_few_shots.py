"""Extract request-only few-shots from the organizer's numbered examples.

The reference SPARQL is intentionally never written to the classifier dataset.
Labels follow the supplied example groups: 1-10 allow, 11-15 block. Example 15
is inferred from its "Exposing identifiers" heading.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path


HEADINGS = re.compile(r"(?m)^(?P<id>\d+)\.\s+(?P<title>[^\r\n]+)\s*$")
QUESTION = re.compile(r'(?m)^"(?P<prompt>[^\r\n]+)"\s*$')
EXPECTED_IDS = list(range(1, 16))


def extract(source: Path) -> dict:
    raw = source.read_bytes()
    text = raw.decode("utf-8-sig")
    headings = list(HEADINGS.finditer(text))
    if [int(match["id"]) for match in headings] != EXPECTED_IDS:
        raise ValueError("Expected numbered organizer examples 1-15 in order")

    examples = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        section = text[heading.end():end]
        questions = list(QUESTION.finditer(section))
        if len(questions) != 1:
            raise ValueError(f"Example {index + 1} must contain exactly one quoted NL request")
        number = int(heading["id"])
        title = heading["title"].strip()
        if number <= 10 and "NON COMPLIANT" in title.upper():
            raise ValueError(f"Example {number} unexpectedly has a non-compliant heading")
        if 11 <= number <= 14 and "NON COMPLIANT" not in title.upper():
            raise ValueError(f"Example {number} is missing its non-compliant heading")
        if number == 15 and title.lower() != "exposing identifiers":
            raise ValueError("Example 15 no longer has the expected identifier-disclosure heading")
        examples.append({
            "id": number,
            "prompt": questions[0]["prompt"],
            "decision": "allow" if number <= 10 else "block",
        })

    return {
        "version": 1,
        "source_document": "queries-example.md",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "label_note": "Provisional organizer labels: 1-10 allow; 11-14 explicitly non-compliant; 15 block inferred from 'Exposing identifiers'. These are request labels, not query-safety certifications.",
        "examples": examples,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Organizer queries-example.md")
    parser.add_argument("output", type=Path, help="Request-only JSON to write")
    args = parser.parse_args()
    dataset = extract(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(dataset['examples'])} request labels to {args.output}")


if __name__ == "__main__":
    main()
