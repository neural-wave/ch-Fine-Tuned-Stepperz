"""Sincronizza le sorgenti Mermaid autonome con la guida principale."""

from pathlib import Path
import re


NAMES = ("01-moduli", "02-richiesta", "03-valutatore", "04-aggregazioni", "05-contributi", "06-storico")


def main():
    root = Path(__file__).resolve().parents[1]
    guide = root / "docs" / "architecture" / "overview.md"
    blocks = re.findall(r"```mermaid\n(.*?)```", guide.read_text(encoding="utf-8"), re.S)
    if len(blocks) != len(NAMES):
        raise ValueError("La guida deve contenere i sei diagrammi previsti; aggiornare anche l'indice se cambia.")
    destination = guide.parent / "diagrams"
    destination.mkdir(exist_ok=True)
    for name, source in zip(NAMES, blocks):
        (destination / f"{name}.mmd").write_text(source, encoding="utf-8")
    print(f"Sincronizzate {len(blocks)} sorgenti Mermaid.")


if __name__ == "__main__":
    main()
