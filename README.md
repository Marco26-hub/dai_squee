# Dai Squee

Sito statico con pagine appartamento, amministrazione privata, richieste di prenotazione, pagamenti Stripe e invio di PDF di cortesia.

## Avvio locale

Richiede Python 3.9+ e Node 20+.

```sh
python3 server.py
```

Aprire http://127.0.0.1:8787 e /admin.html. La prima esecuzione genera una password in .local-data/admin-access.txt. Cambiarla in Impostazioni. SQLite locale e credenziali sono esclusi da Git e dalla pubblicazione.

## Vercel e PostgreSQL

Il progetto usa una funzione Python e PostgreSQL tramite DATABASE_URL. In Vercel il backend rifiuta di usare un database temporaneo se DATABASE_URL non è disponibile. ADMIN_INITIAL_PASSWORD serve solo alla prima inizializzazione. Le password vengono memorizzate con PBKDF2 e le sessioni sono HttpOnly.

Il database contiene anche i PDF di cortesia (massimo 2 MB), accessibili esclusivamente tramite API autenticata. Configurare backup e conservazione dei dati nel provider database. Le impostazioni riservate sono nel database, non nel browser né nei file pubblici.

Comandi:

```sh
npm run check
npm test
npm run build
vercel --prod
```

PUBLIC_SITE_URL, oppure VERCEL_PROJECT_PRODUCTION_URL, determina canonical e sitemap durante il build. Dopo un cambio di dominio ripubblicare il sito. Il dominio nelle Impostazioni determina i link di ritorno del pagamento.

## Configurazione operativa

Impostazioni: dati struttura, prezzi per notte di riferimento, URL esatti dei portali, SMTP con TLS, chiave Stripe e segreto webhook.

Stripe: endpoint /api/stripe/webhook; eventi checkout.session.completed e checkout.session.async_payment_succeeded. Le sessioni vengono create solo per prenotazioni confermate con importo positivo. I prezzi sono decisi dal server, non da dati inviati dal cliente. La pagina di ritorno non marca mai un pagamento come riuscito. Per i rimborsi usare la dashboard Stripe; il progetto non automatizza i rimborsi né la contabilità degli accrediti OTA.

Email: un invio viene registrato come accettato dal server SMTP soltanto dopo la sua risposta. Errori o esiti incerti sono visibili e auditati. Il PDF viene emesso dal gestionale della struttura; questo sito gestisce la copia di cortesia, non la trasmissione fiscale.

Portali: i link configurati sono semplici collegamenti. Le API Booking/Airbnb non sono attive e non si sincronizzano inserendo le password degli account host. Vedere ANALISI-PORTALI-E-CONCORRENZA.md.

## Dati e verifiche prima dell'uso

Confermare tariffe, condizioni, eventuali oneri, documenti legali, dati identificativi e titolarità del dominio. Il sito usa contenuti e fotografie del sito originale; recensioni e servizi non verificati non vengono inventati.

I test automatici usano dati temporanei e fornitori simulati. Non inviano email e non eseguono addebiti reali.

## Prenotazione immediata e calendario

`disponibilita.html` e `prenota.html` leggono la disponibilita dal medesimo database dell'admin, con aggiornamento ogni 30 secondi e controllo transazionale prima della conferma. Il checkout e' escluso dalle notti occupate. In caso di errore le date non vengono mostrate come disponibili per supposizione.

La prenotazione immediata resta DISABILITATA finche' il proprietario non configura e abilita tariffe finali per notte, capienze, condizioni e pagamenti in Impostazioni. Le tariffe sono per appartamento, non per persona. Nessuna tariffa commerciale viene inventata. Non sono implementati prezzi stagionali, calcolo automatico dell'imposta di soggiorno o sconti: impostare prezzi comprensivi dei costi obbligatori e dichiarare correttamente eventuali imposte locali riscosse sul posto. Le condizioni vanno verificate dalla struttura prima dell'attivazione.

- All'arrivo: prenotazione confermata, importo da riscuotere; incasso registrabile dall'admin con riferimento.
- Bonifico: prenotazione confermata, coordinate e scadenza visibili al cliente. Incasso e cancellazione per mancato versamento sono verificati manualmente dal proprietario.
- Carta: sessione Stripe ospitata, importo calcolato dal server e condizioni firmate. Le date restano riservate; il pagamento e' confermato solo dal webhook firmato o dalla verifica amministrativa Stripe. Aggiungere anche `checkout.session.expired` agli eventi webhook: libera le date solo dopo una scadenza verificata. Un esito di creazione incerto mantiene il blocco finche' viene riconciliato, per prevenire doppie prenotazioni.

Il riepilogo privato si apre con un token casuale. Le email fallite rimangono visibili nell'admin; non viene dichiarato l'invio quando SMTP non e' configurato. Pagamenti reali e consegna email devono essere collaudati con i servizi del proprietario prima dell'attivazione.

## Fotografie gestite

La scheda Foto appartamenti consente caricamento, scelta copertina, modifica didascalia e rimozione. Le immagini sono persistenti in PostgreSQL, pubbliche solo tramite identificativo; modifiche riservate all'admin con CSRF. Limite: 20 foto per appartamento, 3 MB per immagine JPG/PNG/WebP. In assenza di una galleria personalizzata rimangono le fotografie statiche originali.

`python3 scripts/import_original_photos.py` importa una sola volta 14 fotografie originali selezionate, terrazzo compreso. Non sovrascrive gallerie gia' personalizzate. Eseguire con le variabili del database desiderato; mai commettere `.env` o credenziali. I font sono ospitati localmente in `assets/fonts`, con le relative licenze OFL.

Le capienze iniziali del calendario sono 4/2/2, coerenti con gli annunci Airbnb individuati. Il sito originario descrive anche 2+2 per Michele e Rosa e Romeo: il proprietario deve verificare la capienza autorizzata prima di modificarla nell'admin.
