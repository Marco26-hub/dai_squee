# Verifica live Dai Squee
Data: 4 settembre 2026. Sito: https://dai-squee.vercel.app

## Esito
**Pronto come sito pubblico bilingue e raccolta richieste. NON ancora pronto per vendita automatica con incasso e inventario sincronizzato sui portali.**

Questa distinzione e' basata sul codice e su letture dell'admin in produzione, non sull'aspetto grafico.

## Stato reale rilevato
- PostgreSQL persistente: collegato.
- Admin autenticato: funzionante.
- Disponibilita': deriva dalle prenotazioni confermate e dai blocchi registrati nel nostro database; non conosce le prenotazioni OTA.
- Prenotazione immediata: disabilitata.
- Tariffe dei tre appartamenti: non impostate.
- Metodi di pagamento: nessuno abilitato.
- Stripe e segreto webhook: non configurati.
- SMTP e mittente: non configurati.
- Condizioni IT/EN e bonifico: da compilare.
- Annunci Booking, Airbnb, Vrbo: URL generici, non annunci verificati. Ora non esposti al pubblico.
- Channel manager: non identificato dal proprietario, nessuna integrazione attiva.
- Fattura: caricamento PDF e invio di copia di cortesia implementati; nessuna emissione fiscale automatica.

## Logica implementata
1. Il calendario legge le occupazioni dal backend, non da un array dimostrativo.
2. Il preventivo viene calcolato sul server con tariffa per notte, ospiti e condizioni configurati; firma e scadenza ne proteggono l'integrita'.
3. La prenotazione ricontrolla sovrapposizioni dentro una transazione e usa una chiave di idempotenza.
4. Arrivo e bonifico riservano le date. Il pagamento non viene marcato incassato automaticamente.
5. La carta usa Stripe Checkout. Il ritorno del browser non prova il pagamento: importo e firma del webhook sono verificati lato server.
6. Il proprietario puo' confermare, annullare, bloccare date e registrare incassi manuali verificati.
7. La lingua EN viene conservata per le prenotazioni, il checkout e i messaggi email. Le condizioni inglesi devono essere approvate e inserite dal proprietario.

Il codice runtime non usa provider di pagamento simulati. Le simulazioni di Stripe/SMTP esistono esclusivamente nei test isolati. Questo NON equivale a dire che i servizi reali siano stati configurati o collaudati.

## Test eseguiti
| Verifica | Ambiente | Esito |
| --- | --- | --- |
| 19 test backend e pagine: autenticazione, CSRF, date, conflitti, firma preventivo, idempotenza, PDF privati, foto, lingua, webhook | Database temporaneo; Stripe/SMTP simulati | Superati |
| 26 pagine inglesi a 320, 768 e 1440 px | Browser sul sito pubblicato | Nessun overflow o errore JS rilevato |
| Richiesta dal modulo inglese, accesso admin, conferma, occupazione calendario | Produzione reale | Superato |
| Richiesta sovrapposta | Produzione reale | Rifiutata con HTTP 409 |
| Annullamento e rilascio date | Produzione reale | Superato |
| Blocco della rete verso disponibilita' | Browser in produzione, guasto simulato localmente | Messaggio visibile; giorni non selezionabili |
| Blocco API foto/configurazione | Browser in produzione, guasto simulato localmente | Foto originali conservate; link non verificati nascosti |
| 116 URL, risorse e riferimenti interni | Produzione, richieste HTTP HEAD | Nessun errore interno; FlyVenice esterno non verificabile |
| Pagamento reale, consegna email, invio PDF al destinatario, sincronizzazione OTA | Non eseguiti | Mancano account/configurazione |

Record E2E: DS-47FE543B, **annullato** dopo il test. Nessun addebito e nessuna email inviata. Il record e lo storico restano distinguibili dai clienti reali.

Il link FlyVenice non raggiungibile e' stato sostituito con un contatto alla struttura per informazioni aggiornate, senza inventare un partner alternativo. Un HTTP 200 dei siti esterni non certifica disponibilita', rapporto commerciale o validita' dei loro contenuti.

## Correzioni apportate durante il controllo
- Versione inglese statica di 26 pagine, selettore IT/EN, URL dedicati, canonical, hreflang e sitemap.
- Calendario, moduli, messaggi, checkout ed email adattati alla lingua.
- Condizioni e didascalie inglesi modificabili dall'admin.
- Eliminati i collegamenti pubblici alle homepage generiche dei portali e il selettore che suggeriva una prenotazione OTA senza integrazione.
- Calendario in modalita' "su richiesta" quando la vendita diretta e' disabilitata.
- Controllo del formato delle occupazioni: risposte malformate non vengono interpretate come date libere.
- Guasti non essenziali a foto/configurazione segnalati in console; originali reali conservati. Foto gestite mancanti hanno un messaggio visibile.
- Regola CSS esplicita per rispettare gli elementi hidden, anche quando altre regole impostano display.

## Come collegare le prenotazioni dei portali
Prima chiedere al proprietario se ha gia' un gestionale o channel manager. In caso positivo, integrare quel fornitore tramite API autorizzate e gli ID dei tre alloggi. Non memorizzare le password personali di Booking o Airbnb.

Se non esiste un fornitore, scegliere un channel manager compatibile con i portali utilizzati e verificare accesso API, permessi, costi e supporto prima di implementare l'adattatore. Per una struttura di tre appartamenti, usare un connettore gia' riconosciuto evita di assumere che un comune account host dia accesso diretto alle API OTA.

La sequenza da collaudare:
1. Mappatura univoca dei tre appartamenti e degli ID alloggio sui canali.
2. Importazione iniziale di prenotazioni e periodi chiusi.
3. Un'unica fonte autorevole per disponibilita' e tariffe.
4. Creazione, modifica e cancellazione con webhook autenticati, deduplicazione e riconciliazione periodica.
5. Blocco o passaggio esplicito a richiesta quando la sincronizzazione non e' verificabile.
6. Pagamenti diretti separati da incassi, commissioni e accrediti dei portali.

**iCal non e' equivalente a una sincronizzazione completa:** Airbnb documenta aggiornamenti automatici ogni tre ore. Non offre da solo la gestione completa di ordini, prezzi e pagamenti.

Fonti ufficiali:
- [Booking Connectivity](https://developers.booking.com/connectivity/docs)
- [Booking Reservations](https://developers.booking.com/connectivity/docs/reservations-api/reservations-overview)
- [Airbnb: sincronizzazione calendari](https://www.airbnb.com/help/article/99)
- [Stripe: conferma tramite webhook](https://docs.stripe.com/checkout/fulfillment)

## Condizioni prima del via libera agli incassi
- Il proprietario approva capienze, tariffe, costi inclusi, imposte, soggiorni minimi ed eventuali depositi. Il calcolo attuale e' una tariffa per notte: non comprende un motore tariffario stagionale, caparre o extra automatici.
- Si sceglie e collauda la fonte dell'inventario. Fino ad allora i portali vanno gestiti separatamente e non promettiamo assenza di overbooking multicanale.
- Stripe e webhook sono configurati e provati con transazioni test riuscite, fallite, abbandonate e duplicate prima dell'attivazione reale.
- Si collauda la riconciliazione quando Stripe non risponde dopo l'avvio: attualmente un esito incerto puo' lasciare le date prudentemente bloccate e richiedere intervento amministrativo; manca un processo automatico periodico di recupero.
- SMTP, dominio mittente e consegna delle email/PDF vengono provati su caselle autorizzate. SMTP accettato non prova la consegna.
- Si approvano privacy e condizioni del nuovo servizio, anche in inglese. I collegamenti legali pubblici rimandano ancora al sito originale italiano.
- Si verificano dominio definitivo, identificativi obbligatori, backup/ripristino e monitoraggio operativo.
- Solo dopo questi controlli si abilita la prenotazione immediata in admin.

## Ripetere i controlli
- `npm run check`
- `npm test`
- `python3 scripts/build_english.py` dopo aver aggiornato i testi IT o `translations/en.json`.
- `npm run build`
- `TEST_URL=https://dai-squee.vercel.app python3 scripts/check_links.py`
- I test browser richiedono Playwright installato oppure `PLAYWRIGHT_MODULE` impostato al modulo disponibile.
- `scripts/production_e2e.mjs` crea un record sintetico chiaramente etichettato e lo annulla; eseguirlo solo con autorizzazione. Non avvia pagamenti o email.

