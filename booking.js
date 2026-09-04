(() => {
  const el = id => document.getElementById(id);
  const rooms = ['Suite Max','Michele','Rosa e Romeo'];
  const labels = {arrival:DaiLocale.t("All'arrivo"),card:DaiLocale.t('Carta adesso'),bank:DaiLocale.t('Bonifico bancario')};
  const money = cents => new Intl.NumberFormat(DaiLocale.locale,{style:'currency',currency:'EUR'}).format(cents/100);
  const day = date => [date.getFullYear(),String(date.getMonth()+1).padStart(2,'0'),String(date.getDate()).padStart(2,'0')].join('-');
  const today = day(new Date()), current = new Date(today+'T12:00:00');
  let month = new Date(current.getFullYear(),current.getMonth(),1), occupied = null, quote = null, directEnabled = false;
  let arrival = '', departure = '', requestKey = null, pendingPayload = null, refreshing = false, submitting = false, quoteVersion = 0;
  const params = new URLSearchParams(location.search);
  const roomSelect = el('calendarApartment');
  if (rooms.includes(params.get('apartment'))) roomSelect.value = params.get('apartment');
  const status = (message,error=false) => {
    const target = el('checkoutStatus') || el('calendarStatus');
    target.textContent=message; target.classList.toggle('error',error);
  };
  async function api(path,data,key) {
    if(location.protocol==='file:') throw new Error(DaiLocale.t('Aprire il sito online per consultare disponibilità e prenotare.'));
    const response=await fetch('/api/'+path,{method:data?'POST':'GET',headers:{'Content-Type':'application/json','Accept-Language':DaiLocale.language,...(key?{'Idempotency-Key':key}:{})},body:data?JSON.stringify(data):undefined,cache:'no-store',signal:AbortSignal.timeout(30000)});
    let result; try { result=await response.json(); } catch { throw new Error(DaiLocale.t('Servizio momentaneamente non disponibile. Riprovate o contattate la struttura.')); }
    if(!response.ok) { const error=new Error(result.error||DaiLocale.t('Operazione non completata.'));error.status=response.status;throw error; }
    return result;
  }
  const unavailable = date => occupied?.some(b=>b.apartment===roomSelect.value && b.checkin<=date && date<b.checkout);
  const conflict = (a,b) => occupied?.some(r=>r.apartment===roomSelect.value && r.checkin<b && r.checkout>a);
  function invalidate() {
    if(pendingPayload)return;
    quote=null; quoteVersion++; requestKey=null;
    if(el('quoteBox')) el('quoteBox').hidden=true;
  }
  function updateSelection() {
    if(el('arrivalDate')) { el('arrivalDate').value=arrival; el('departureDate').value=departure; }
    if(el('continueBooking')) el('continueBooking').href=DaiLocale.page('prenota.html')+'?'+new URLSearchParams({apartment:roomSelect.value,checkin:arrival,checkout:departure});
    render();
  }
  function render() {
    el('calendarTitle').textContent=month.toLocaleDateString(DaiLocale.locale,{month:'long',year:'numeric'});
    el('monthPrevious').disabled=month<=new Date(current.getFullYear(),current.getMonth(),1);
    el('monthNext').disabled=month>=new Date(current.getFullYear()+1,current.getMonth(),1);
    const grid=el('availabilityGrid'); grid.replaceChildren();
    for(const name of (DaiLocale.language==='en'?['Mon','Tue','Wed','Thu','Fri','Sat','Sun']:['Lun','Mar','Mer','Gio','Ven','Sab','Dom'])) { const label=document.createElement('span');label.textContent=name;grid.append(label); }
    for(let i=0;i<(month.getDay()+6)%7;i++) grid.append(document.createElement('span'));
    const count=new Date(month.getFullYear(),month.getMonth()+1,0).getDate();
    for(let i=1;i<=count;i++) {
      const date=day(new Date(month.getFullYear(),month.getMonth(),i)), busy=unavailable(date);
      // A booked arrival day may still be the previous guest's checkout date.
      const checkoutBoundary=arrival&&!departure&&date>arrival&&!conflict(arrival,date);
      const button=document.createElement('button');button.type='button';button.textContent=i;
      button.className='calendar-day'+(occupied===null?' unknown':busy?' unavailable':'')+(date===arrival||date===departure?' selected':date>arrival&&departure&&date<departure?' in-range':'');
      button.disabled=occupied===null||date<today||(busy&&!checkoutBoundary)||submitting||Boolean(pendingPayload);
      button.setAttribute('aria-label',new Date(date+'T12:00:00').toLocaleDateString(DaiLocale.locale,{day:'numeric',month:'long',year:'numeric'})+(checkoutBoundary?DaiLocale.t(' disponibile come partenza'):busy?DaiLocale.t(' occupato'):DaiLocale.t(' disponibile')));
      button.setAttribute('aria-pressed',String(date===arrival||date===departure));
      button.addEventListener('click',()=>{
        if(arrival&&!departure&&date>arrival) {
          if(conflict(arrival,date)){status(DaiLocale.t('Il periodo comprende notti occupate. Scegliete un altro intervallo.'),true);return;}
          departure=date;
        } else {arrival=date;departure='';}
        invalidate();updateSelection();
        status(departure?DaiLocale.t('Periodo selezionato: ')+arrival+' / '+departure:DaiLocale.t('Arrivo selezionato. Scegliete la data di partenza.'));
      });grid.append(button);
    }
  }
  async function refresh() {
    if(refreshing) return;
    refreshing=true;el('calendarRefresh').disabled=true;
    try {
      const data=await api('availability');
      if(!Array.isArray(data.unavailable) || data.unavailable.some(row => !rooms.includes(row.apartment) || !/^\d{4}-\d{2}-\d{2}$/.test(row.checkin) || !/^\d{4}-\d{2}-\d{2}$/.test(row.checkout) || row.checkout<=row.checkin)) throw new Error(DaiLocale.t('Disponibilità non verificabile.'));
      occupied=data.unavailable;
      directEnabled = data.direct_enabled === true;
      el('availabilityGrid').closest('section').classList.toggle('request-mode', !directEnabled);
      const legend=document.querySelector('.calendar-legend span');
      if(legend)legend.textContent=DaiLocale.t(directEnabled?'Disponibile':'Su richiesta');
      if(el('bookingGuests')) {
        const max=data.capacities?.[roomSelect.value]||2;
        [...el('bookingGuests').options].forEach(o=>o.disabled=Number(o.value)>max);
        if(Number(el('bookingGuests').value)>max) el('bookingGuests').value=String(max);
      }
      el('calendarStatus').textContent=DaiLocale.t('Disponibilità aggiornata alle ')+new Date().toLocaleTimeString(DaiLocale.locale,{hour:'2-digit',minute:'2-digit'})+'.';
      el('calendarStatus').classList.remove('error');
      if(!directEnabled) el('calendarStatus').textContent += ' '+DaiLocale.t('Disponibilità da confermare con la struttura. Prenotazione immediata non attiva.');
      if(arrival&&departure&&conflict(arrival,departure)) { invalidate();status(DaiLocale.t('Il periodo selezionato non è più disponibile.'),true); }
    } catch(error) {
      occupied=null;invalidate();el('calendarStatus').textContent=error.message+DaiLocale.t(' Nessuna disponibilità presunta.');el('calendarStatus').classList.add('error');
    } finally {refreshing=false;el('calendarRefresh').disabled=false;render();}
  }
  roomSelect.addEventListener('change',()=>{arrival='';departure='';invalidate();updateSelection();refresh();});
  el('calendarRefresh').addEventListener('click',refresh);
  el('monthPrevious').addEventListener('click',()=>{month=new Date(month.getFullYear(),month.getMonth()-1,1);render();});
  el('monthNext').addEventListener('click',()=>{month=new Date(month.getFullYear(),month.getMonth()+1,1);render();});
  for(const id of ['arrivalDate','departureDate','bookingGuests']) el(id)?.addEventListener('change',()=>{
    arrival=el('arrivalDate').value;departure=el('departureDate').value;invalidate();render();
  });
  if(el('arrivalDate')) {
    el('arrivalDate').min=today;el('departureDate').min=today;
    for(const [param,id] of [['checkin','arrivalDate'],['checkout','departureDate']]) if(/^\d{4}-\d{2}-\d{2}$/.test(params.get(param)||'')) el(id).value=params.get(param);
    arrival=el('arrivalDate').value;departure=el('departureDate').value;
    if(arrival>=today) month=new Date(arrival.slice(0,7)+'-01T12:00:00');
    if(params.get('guests')) el('bookingGuests').value=params.get('guests');
  }
  el('stayForm')?.addEventListener('submit',async event=>{
    event.preventDefault();invalidate();
    if(!arrival||!departure||departure<=arrival||arrival<today) {status(DaiLocale.t('Selezionate arrivo e partenza validi.'),true);return;}
    const version=quoteVersion;el('quoteButton').disabled=true;status(DaiLocale.t('Verifica del totale e della disponibilità…'));
    try {
      const result=await api('quote',{language:DaiLocale.language,apartment:roomSelect.value,checkin:arrival,checkout:departure,guests:Number(el('bookingGuests').value)});
      if(version!==quoteVersion)return;
      quote=result;el('quoteNights').textContent=result.quote.apartment+' · '+result.quote.nights+DaiLocale.t(' notti');el('quoteAmount').textContent=money(result.quote.amount_cents);el('quoteTerms').textContent=result.quote.terms;
      el('bankTerms').textContent=result.quote.methods.includes('bank')?DaiLocale.t('Bonifico: ')+result.quote.bank_instructions:'';
      el('paymentMethods').replaceChildren();
      result.quote.methods.forEach((method,i)=>{
        const label=document.createElement('label');label.className='payment-method';
        const radio=document.createElement('input');radio.type='radio';radio.name='payment_method';radio.value=method;radio.required=true;radio.checked=i===0;label.append(radio,document.createTextNode(labels[method]));el('paymentMethods').append(label);
        radio.addEventListener('change',paymentLabel);
      });
      el('directBookingForm').elements.terms_consent.checked=false;el('quoteBox').hidden=false;paymentLabel();status('');
    } catch(error) {if(version===quoteVersion)status(error.message,true);} finally {el('quoteButton').disabled=false;}
  });
  function paymentLabel() {
    el('reserveButton').textContent=el('directBookingForm').elements.payment_method.value==='card'?DaiLocale.t('Prenota e paga con carta'):DaiLocale.t('Conferma prenotazione con obbligo di pagamento');
  }
  function showResult(result) {
    const box=el('bookingResult');if(!box)return;
    box.hidden=false;box.replaceChildren();el('quoteBox').hidden=true;
    const add=text=>{const p=document.createElement('p');p.textContent=text;box.append(p);};
    const title=document.createElement('h2');
    title.textContent=result.status==='cancelled'?DaiLocale.t('Prenotazione annullata'):result.method==='card'&&!result.paid?DaiLocale.t('Pagamento da completare'):DaiLocale.t('Prenotazione confermata');box.append(title);
    add(DaiLocale.t('Riferimento: ')+result.reference);add(result.apartment+' · '+result.checkin+' / '+result.checkout);add(DaiLocale.t('Totale: ')+money(result.amount_cents)+' · '+labels[result.method]);
    if(result.paid)add(DaiLocale.t('Pagamento registrato.'));
    if(result.method==='bank'&&!result.paid&&result.status==='confirmed') { add(result.terms.bank_holder+' · IBAN '+result.terms.bank_iban);add(DaiLocale.t('Causale: ')+result.reference);add(result.terms.bank_instructions); }
    if(result.method==='arrival'&&!result.paid)add(DaiLocale.t("Importo da corrispondere all'arrivo."));
    if(result.url&&result.method==='card') {const link=document.createElement('a');link.className='primary-link';link.href=result.url;link.textContent=DaiLocale.t('Completa il pagamento');box.append(link);add(DaiLocale.t('Le date restano riservate fino all’esito o alla scadenza della sessione di pagamento.'));}
    add(result.terms.terms);
    if(result.email_error)add(DaiLocale.t('Conferma email non inviata o non verificata. Conservate questo riferimento; la prenotazione è registrata.'));
    const refreshButton=document.createElement('button');refreshButton.className='text-link';refreshButton.type='button';refreshButton.textContent=DaiLocale.t('Aggiorna stato');
    refreshButton.onclick=async()=>{refreshButton.disabled=true;try{showResult(await api('reservation?token='+encodeURIComponent(result.access_token)));}catch(error){status(error.message,true);refreshButton.disabled=false;}};box.append(refreshButton);
  }
  el('directBookingForm')?.addEventListener('submit',async event=>{
    event.preventDefault();if((!quote&&!pendingPayload)||submitting)return;
    const form=event.target,data=Object.fromEntries(new FormData(form));
    requestKey ||= crypto.randomUUID();
    const payload=pendingPayload||{...quote.quote,...data,expires:quote.expires,signature:quote.signature,consent:form.elements.consent.checked,terms_consent:form.elements.terms_consent.checked};
    pendingPayload=payload;
    submitting=true;el('reserveButton').disabled=true;roomSelect.disabled=true;el('quoteButton').disabled=true;
    form.querySelectorAll('input').forEach(input=>input.disabled=true);el('stayForm').querySelectorAll('input,select').forEach(input=>input.disabled=true);render();status(DaiLocale.t('Registrazione della prenotazione…'));
    try {
      const result=await api('reserve',payload,requestKey);
      history.replaceState(null,'',DaiLocale.page('prenota.html')+'?receipt='+result.access_token);quote=null;requestKey=null;pendingPayload=null;showResult(result);status('');
      if(result.method==='card'&&result.url) location.assign(result.url);
      refresh();
    } catch(error) {
      if(error.status&&error.status<500){pendingPayload=null;requestKey=null;}
      status(error.message+(pendingPayload?DaiLocale.t(' Riprovate la stessa prenotazione per verificarne l’esito, senza duplicarla.'):''),true);
    }
    finally {submitting=false;el('reserveButton').disabled=false;roomSelect.disabled=Boolean(pendingPayload);el('quoteButton').disabled=Boolean(pendingPayload);form.querySelectorAll('input').forEach(input=>input.disabled=Boolean(pendingPayload));el('stayForm').querySelectorAll('input,select').forEach(input=>input.disabled=Boolean(pendingPayload));render();}
  });
  render();refresh();
  setInterval(()=>{if(!document.hidden&&!submitting)refresh();},30000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
  if(params.get('receipt')&&el('bookingResult')) api('reservation?token='+encodeURIComponent(params.get('receipt'))).then(showResult).catch(error=>status(error.message,true));
})();
