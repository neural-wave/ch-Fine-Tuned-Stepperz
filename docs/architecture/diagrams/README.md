# Sorgenti dei diagrammi

La [guida all'architettura](../overview.md) contiene i blocchi Mermaid da
modificare. Questa cartella raccoglie le copie autonome nello stesso ordine,
per aprirle in un renderer Mermaid:

1. [Mappa dei moduli](01-moduli.mmd)
2. [Sequenza di una richiesta hardened](02-richiesta.mmd)
3. [Scelta del valutatore](03-valutatore.mmd)
4. [Aggregazioni individuali intermedie](04-aggregazioni.mmd)
5. [Default e hardened sulla somma mascherata](05-contributi.mmd)
6. [Storico e conteggi complementari](06-storico.mmd)

I file `.mmd` sono sorgenti testuali. Dopo aver modificato la guida,
rigenerarli dalla radice del repository (il comando sovrascrive le sei copie):

```powershell
uv run python -m tools.export_diagrams
```

I diagrammi descrivono l'analizzatore e il runtime locale; il workflow dei
modelli e spiegato nella [guida agli agenti](../../guides/agent-workflow.md).
Non attestano un'integrazione del runtime con Virtuoso. Per provare la demo
numerica senza modelli o triplestore:

```powershell
uv run python -m examples.diagram_walkthrough
```
