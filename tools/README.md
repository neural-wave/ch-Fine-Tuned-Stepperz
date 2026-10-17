# Tool di sviluppo

Eseguire dalla radice del repository dopo `uv sync --locked`.

| Comando | Output |
|---|---|
| `uv run python -m tools.generate_synthetic_data --patients 12 --seed 42` | `tests/fixtures/synthetic/cohort.trig`; `--out` permette un file diverso |
| `uv run python -m tools.export_test_results` | Alberi, verdetti e osservazioni avversarie in `artifacts/tests/` |
| `uv run python -m tools.export_adversarial` | Sottocorpus avversario in `artifacts/tests/adversarial/` |
| `uv run python -m sparql_analyzer.export_policy` | Profili JSON e catalogo dei controlli |
| `uv run python -m tools.export_diagrams` | Sei file Mermaid sincronizzati con la guida |
| `uv run python -m tools.check_docs` | Controllo dei collegamenti locali Markdown |

I comandi di export sono strumenti del checkout, non parti del servizio che
risponde alle richieste. Le osservazioni avversarie nel default possono
dimostrare un rischio: un esito atteso non significa sempre attacco bloccato.
