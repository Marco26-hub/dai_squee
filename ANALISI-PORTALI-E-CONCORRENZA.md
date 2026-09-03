# Dai Squee: portali, concorrenza e priorità

Analisi del 4 settembre 2026. Le funzionalità dei concorrenti sono osservate sulle pagine pubbliche; i loro risultati commerciali e sistemi interni non sono verificabili dall'esterno.

## Decisione consigliata

Mantenere il sito personalizzato e collegarlo al channel manager già usato dalla struttura, se presente. Se non esiste, valutare Smoobu, Beds24 e Lodgify con una prova su un appartamento. Il collegamento non richiede di custodire le password personali di Booking o Airbnb nel nostro sito.

Booking.com documenta accessi per Connectivity Partner e autorizzazioni concesse dalla struttura. Airbnb presenta un ecosistema di software partner. Un account host ordinario non equivale a credenziali API utilizzabili dal nostro sito.

Fonti: [Booking Connectivity](https://developers.booking.com/connectivity/docs), [autorizzazione delle connessioni](https://developers.booking.com/connectivity/docs/connections-api/connections-overview), [Airbnb software partner](https://www.airbnb.com/software-partners).

## Collegamenti possibili

| Collegamento | Cosa consente | Limiti |
| --- | --- | --- |
| Link agli annunci | Aprire l'annuncio sul portale | Nessuna importazione di ordini o disponibilità |
| iCal | Scambio di calendari e periodi occupati | Non è una contabilità né un'integrazione completa delle prenotazioni; aggiornamenti non istantanei |
| API di un channel manager | Prenotazioni, modifiche, cancellazioni e inventario secondo il contratto e gli endpoint | Richiede account, autorizzazioni, corrispondenza degli alloggi e test del fornitore |
| API dirette dei portali | Funzioni concesse dai programmi di connettività | Accesso controllato; non basta registrare un account proprietario |

Airbnb indica aggiornamenti automatici del calendario ogni tre ore: iCal non deve essere presentato come una garanzia di sincronizzazione immediata. [Fonte Airbnb](https://www.airbnb.it/help/article/99).

I pagamenti OTA devono restare distinti da quelli diretti. Importo della prenotazione, commissione, stato di incasso e accredito al proprietario sono dati diversi. Vanno importati solo quando il gestore li fornisce; un ordine Booking non può essere considerato automaticamente pagato su Stripe. [Booking Payments](https://developers.booking.com/connectivity/docs/payments-api/understanding-the-payments-api).

## Fornitori da valutare

| Fornitore | Motivo per valutarlo | Verifica necessaria |
| --- | --- | --- |
| Smoobu | API documentate per disponibilità, prenotazioni, aggiornamenti e webhook | Accesso API dell'account e autenticazione HMAC; la documentazione annuncia il ritiro della vecchia autenticazione il 25 settembre 2026 |
| Beds24 | API v2 con operazioni su prenotazioni, canali e integrazione Stripe | Mappatura alloggi, diritti API e procedura esatta per inventario/prezzi |
| Lodgify | Booking engine integrabile in un sito già esistente e channel manager | Piano necessario, accesso API rispetto al solo widget, costi e funzioni richieste |

Fonti: [Smoobu API](https://docs.smoobu.com/), [requisiti e webhook Smoobu](https://support.smoobu.com/hc/en-us/articles/360003170740-Use-the-Smoobu-API-get-an-API-key-set-up-webhooks-and-sign-your-requests), [Beds24 v2](https://wiki.beds24.com/index.php/API_V2.0), [Lodgify](https://www.lodgify.com/pricing/).

Non è stato acquistato nessun abbonamento e nessun account OTA è stato collegato. L'accesso alle API e il fornitore vanno verificati con il titolare.

## Confronto locale

| Struttura | Elementi osservati | Indicazione per Dai Squee |
| --- | --- | --- |
| Residenza Dante, Asolo | Date e ospiti, disponibilità, galleria, mappa, offerte e collegamento al checkout Lodgify; piattaforma dichiarata nel footer | Ridurre la distanza tra scelta dell'alloggio e prezzo prenotabile |
| Residence Cristoforo Colombo, Bassano | Versione inglese, tour virtuale, condizioni dettagliate, orari, recensioni e proposte per soggiorni diversi | Rendere facile capire spazi, regole e motivi per prenotare direttamente |
| Progress Asolo Apartments | Dall'indicizzazione emergono schede distinte per sei appartamenti e capienze, ricerca date e territorio | Conferma dell'utilità di pagine dedicate; la riapertura diretta non è riuscita, quindi non è stato verificato il checkout |

Fonti: [Residenza Dante](https://visit-asolo.com/), [Residence Cristoforo Colombo](https://www.residencecristoforocolombo.it/en/), [Progress Asolo Apartments](https://progressasoloapartments.com/).

## Stato del nostro progetto

Implementati: fotografie originali e sezioni territorio/partner, storia della casa, tre pagine appartamento, collegamenti interni, layout responsive, metadati e dati strutturati, FAQ visibili, sitemap, gestione delle richieste, database persistente, calendario locale con blocchi, stati e importi, upload privato PDF e invio via SMTP, integrazione checkout Stripe con verifica server del pagamento.

Le richieste dirette non sono prenotazioni istantanee. La conferma amministrativa occupa le date nel nostro database. Il calendario locale non conosce ancora le prenotazioni dei portali.

Email e pagamenti richiedono credenziali della struttura e una prova effettiva in modalità test. Il PDF di cortesia non emette e non sostituisce la fattura del gestionale.

## Priorità prima della vendita automatica

1. Collegare il channel manager scelto e associare i tre ID alloggio. Una sola fonte deve governare l'inventario.
2. Provare creazione, modifica, cancellazione, duplicazione webhook e indisponibilità del fornitore. Se non è verificabile la disponibilità, passare esplicitamente a richiesta da confermare.
3. Definire tariffe, pulizie, eventuali oneri, caparra/saldo, soggiorno minimo e condizioni di cancellazione prima di esporre un totale acquistabile.
4. Configurare SMTP con dominio mittente verificato; provare consegna, rimbalzi e reinvio. Lo stato SMTP accettato non dimostra la consegna nella casella del cliente.
5. Configurare Stripe test, provare pagamento riuscito, fallito, abbandonato e rimborso; poi abilitare la modalità reale con l'account del titolare.
6. Verificare dati identificativi, privacy del nuovo servizio, termini e dominio finale con il titolare. I link legali attuali rimandano al sito originale.

## Evoluzione moderna

- Versioni inglese e tedesca curate, con URL e hreflang distinti, non traduzioni automatiche non revisionate.
- Prezzo totale trasparente e disponibilità unificata; filtri delle date leggibili da telefono.
- Recensioni con fonte verificabile, fotografie organizzate per ambiente e una planimetria reale per ogni alloggio.
- Area ospite protetta per riepilogo, condizioni accettate, pagamento, documenti e informazioni d'arrivo.
- Messaggi pre-arrivo e post-soggiorno, calendario pulizie, report per canale e riconciliazione degli accrediti.
- Monitoraggio degli errori di sincronizzazione, backup e prova di ripristino; nessun errore operativo nascosto.

## SEO, GEO e AEO

Le basi utili sono contenuti originali e leggibili, pagine distinte, indirizzo e contatti coerenti, link interni, velocità mobile e risposte concrete alle domande degli ospiti. Google dichiara che le sue funzioni AI non richiedono ottimizzazioni speciali ulteriori rispetto alle buone pratiche SEO. Il file llms.txt è un supporto sperimentale, non una garanzia di citazione.

I dati strutturati devono descrivere ciò che è davvero visibile. Non inserire prezzi inventati, recensioni aggregate non verificabili, coordinate non confermate o servizi non presenti. Nessun markup garantisce risultati arricchiti o posizionamenti.

[Google: AI features and your website](https://developers.google.com/search/docs/appearance/ai-features).
