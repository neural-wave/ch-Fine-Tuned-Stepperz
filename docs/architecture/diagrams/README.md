# Sorgenti dei diagrammi

La guida da presentare ai compagni e [architettura.md](../overview.md).
I blocchi Mermaid di quella guida sono la sorgente principale. Qui si trovano
le copie autonome, nello stesso ordine, per aprirle in un renderer Mermaid:

1. [Mappa dei moduli](01-moduli.mmd)
2. [Sequenza di una richiesta hardened](02-richiesta.mmd)
3. [Scelta del valutatore](03-valutatore.mmd)
4. [Aggregazioni individuali intermedie](04-aggregazioni.mmd)
5. [Default e hardened sulla somma mascherata](05-contributi.mmd)
6. [Storico e conteggi complementari](06-storico.mmd)

I blocchi nella guida vengono visualizzati nei lettori Markdown con supporto
Mermaid. I file `.mmd` sono sorgenti testuali, non immagini gia esportate.
Per sincronizzarli dopo aver modificato la guida:

```powershell
uv run python -m tools.export_diagrams
```

I diagrammi mostrano il codice locale attuale e non descrivono un'integrazione
gia operativa tra il controllore e Virtuoso. La demo numerica si esegue con
`uv run python -m examples.diagram_walkthrough` dalla radice del repository.
