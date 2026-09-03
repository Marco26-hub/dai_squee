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
