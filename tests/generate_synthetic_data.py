"""Genera una piccola fixture RDF completamente fittizia e riproducibile."""

import argparse
import random
from pathlib import Path

from rdflib import Dataset, Literal, Namespace, RDF, URIRef

SPHN = Namespace("https://biomedit.ch/rdf/sphn-schema/sphn#")
SYN = Namespace("urn:synthetic:")


def generate(patients=12, seed=42):
    if patients < 1:
        raise ValueError("patients deve essere positivo")
    rng = random.Random(seed)
    dataset = Dataset()
    for index in range(patients):
        graph = dataset.graph(URIRef(f"http://example.org/graph/synthetic-{index:04d}"))
        subject = SYN[f"patient-{index:04d}"]
        graph.add((subject, RDF.type, SPHN.SubjectPseudoIdentifier))
        graph.add((subject, SPHN.hasIdentifier, Literal(f"SYNTH-{index:04d}")))
        graph.add((subject, SYN.name, Literal(f"Persona fittizia {index:04d}")))
        graph.add((subject, SYN.email, Literal(f"synthetic-{index:04d}@example.invalid")))
        if index < max(1, patients * 2 // 3):
            for number in range(rng.randint(1, 3)):
                diagnosis = SYN[f"diagnosis-{index:04d}-{number}"]
                graph.add((diagnosis, RDF.type, SPHN.BilledDiagnosis))
                graph.add((diagnosis, SPHN.hasSubjectPseudoIdentifier, subject))
        if index == 0:
            graph.add((SYN["rare-diagnosis"], RDF.type, SPHN.OncologyDiagnosis))
            for number in range(10):
                graph.add((SYN[f"lab-{number}"], RDF.type, SPHN.LabTestEvent))
    return dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patients", type=int, default=12)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "data/synthetic/cohort.trig")
    args = parser.parse_args()
    dataset = generate(args.patients, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    dataset.serialize(destination=str(args.out), format="trig")
    print(f"Generati {args.patients} pazienti fittizi, {len(dataset)} triple: {args.out}")


if __name__ == "__main__":
    main()
