# Orchestrazione degli agenti

Questo package e riservato al codice che coordinera modelli, strumenti e stato
delle richieste. Non contiene ancora agenti, chiamate LLM o un workflow eseguibile.

La dipendenza deve andare da `agent_orchestration` verso le API pubbliche di
`sparql_analyzer`. Il validatore non importa l'orchestrazione e non dipende da
un particolare framework per agenti.

Quando il flusso verra implementato, potra costruire query o piani strutturati,
ma il rilascio dei risultati dovra attraversare `execute_checked`. Identita,
ACL, storico e shape devono essere forniti dal servizio autenticato, non decisi
dal modello. La scelta del profilo compete all'applicazione.

Ruoli degli agenti, adattatori dei modelli e workflow andranno separati quando
esisteranno implementazioni concrete, senza introdurre classi vuote in anticipo.
