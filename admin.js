const $ = id => document.getElementById(id);
const rooms = ['Suite Max','Michele','Rosa e Romeo'];
const labels = {pending:'Da valutare',confirmed:'Confermata',declined:'Rifiutata',cancelled:'Annullata',blocked:'Blocco date'};
let csrf = '', bookings = [], selected = null;
const euro = value => value == null ? 'Da definire' : new Intl.NumberFormat('it-IT',{style:'currency',currency:'EUR'}).format(value/100);
const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function notice(message,error=false) {
  const el=$('bookingDialog').open ? $('detailNotice') : $('manualDialog').open ? $('manualNotice') : $('notice');
  el.textContent=message; el.classList.toggle('error',error);
}
async function api(path,method='GET',data) {
  if(location.protocol==='file:') throw new Error("Aprire l'admin dall'indirizzo del sito attivo, non dal file locale.");
  const response=await fetch('/api/admin/'+path,{
    method,credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},
    body:data===undefined?undefined:JSON.stringify(data),signal:AbortSignal.timeout(30000)
  });
  const result=await response.json();
  if(!response.ok) {
    if(response.status===401) { $('app').hidden=true; $('loginView').hidden=false; $('logout').hidden=true; }
    throw new Error(result.error || 'Operazione non riuscita.');
  }
  return result;
}
async function run(button,action) {
  if(button) button.disabled=true;
  try { await action(); } catch(error) { notice(error.name==='TimeoutError' ? "Esito non ricevuto. Aggiornare e verificare prima di ripetere l'operazione." : error.message,true); }
  finally { if(button) button.disabled=false; }
}
function showApp() { $('app').hidden=false; $('loginView').hidden=true; $('logout').hidden=false; }
async function refresh() {
  bookings=(await api('bookings')).bookings;
  renderBookings(); renderCalendar();
}
function renderBookings() {
  const query=$('search').value.trim().toLowerCase(), filter=$('statusFilter').value;
  const visible=bookings.filter(b=>(!filter || b.status===filter) && [b.name,b.email,b.id].join(' ').toLowerCase().includes(query));
  $('stats').innerHTML=[
    ['Da valutare',bookings.filter(b=>b.status==='pending').length],
    ['Confermate',bookings.filter(b=>b.status==='confirmed').length],
    ['Pagamenti verificati',bookings.filter(b=>b.paid_at).length],
    ['Incassato',euro(bookings.filter(b=>b.paid_at).reduce((s,b)=>s+(b.amount_cents||0),0))]
  ].map(([label,value])=>'<div><span>'+label+'</span><strong>'+value+'</strong></div>').join('');
  $('bookingRows').innerHTML=visible.map(b=>'<tr><td><strong>'+esc(b.name)+'</strong><small>'+esc(b.id)+'</small></td><td>'+esc(b.apartment)+'</td><td>'+esc(b.checkin)+'<small>'+esc(b.checkout)+' · '+b.guests+' ospiti</small></td><td><span class="badge '+esc(b.status)+'">'+labels[b.status]+'</span></td><td>'+euro(b.amount_cents)+'</td><td>'+(b.paid_at?'Verificato':b.checkout_id?'Link creato':'Non richiesto')+'</td><td><button data-booking="'+b.id+'">Apri</button></td></tr>').join('');
  $('emptyState').hidden=visible.length!==0;
}
function renderCalendar() {
  const [year,month]=$('calendarMonth').value.split('-').map(Number);
  if(!year||!month) return;
  const days=new Date(year,month,0).getDate();
  const dayString=d=>year+'-'+String(month).padStart(2,'0')+'-'+String(d).padStart(2,'0');
  $('calendarGrid').innerHTML='<table class="calendar-table"><thead><tr><th>Appartamento</th>'+Array.from({length:days},(_,i)=>'<th>'+String(i+1)+'</th>').join('')+'</tr></thead><tbody>'+rooms.map(room=>'<tr><th>'+room+'</th>'+Array.from({length:days},(_,i)=>{
    const day=dayString(i+1);
    const b=bookings.find(b=>b.apartment===room && ['confirmed','blocked'].includes(b.status) && b.checkin<=day && b.checkout>day);
    return '<td>'+(b?'<button class="'+b.status+'" data-booking="'+b.id+'" title="'+esc(labels[b.status]+' '+b.id)+'" aria-label="'+esc(room+' '+day+' '+labels[b.status])+'">●</button>':'<span aria-label="Libero">·</span>')+'</td>';
  }).join('')+'</tr>').join('')+'</tbody></table>';
}
async function openDetail(id) {
  selected=bookings.find(b=>b.id===id);
  if(!selected) return;
  const b=selected, form=$('detailForm');
  $('detailReference').textContent=b.id;
  $('detailName').textContent=b.name;
  $('detailContact').textContent=[b.email,b.phone].filter(Boolean).join(' · ');
  $('detailStay').textContent=b.checkin+' / '+b.checkout+' · '+b.guests+' ospiti · '+(b.channel||'Diretto');
  $('detailMessage').textContent=b.message||'Nessun messaggio.';
  form.elements.apartment.value=b.apartment;
  form.elements.status.value=b.status;
  form.elements.amount.value=b.amount_cents==null?'':(b.amount_cents/100).toFixed(2);
  form.elements.notes.value=b.notes||'';
  ['apartment','status','amount'].forEach(name=>form.elements[name].disabled=Boolean(b.checkout_id));
  $('paymentState').textContent=b.paid_at?'Pagamento verificato il '+new Date(b.paid_at).toLocaleString('it-IT'):b.checkout_id?'Link di pagamento creato. In attesa di pagamento verificato.':'Pagamento non richiesto.';
  $('paymentLink').hidden=!b.checkout_url;
  if(b.checkout_url) $('paymentLink').href=b.checkout_url;
  $('createPayment').disabled=b.status!=='confirmed'||Boolean(b.paid_at);
  $('sendPayment').disabled=!b.checkout_url||Boolean(b.paid_at);
  $('syncPayment').disabled=!b.checkout_id;
  $('expirePayment').disabled=!b.checkout_id||Boolean(b.paid_at);
  $('sendConfirmation').disabled=b.status!=='confirmed';
  $('sendInvoice').disabled=!b.has_invoice||!b.email;
  $('downloadInvoice').hidden=!b.has_invoice;
  $('downloadInvoice').href='/api/admin/bookings/'+b.id+'/invoice';
  $('invoiceState').textContent=(b.has_invoice?b.invoice_name:'Nessun PDF caricato.')+(b.invoice_sent_at?' · Invio accettato da SMTP: '+new Date(b.invoice_sent_at).toLocaleString('it-IT'):'')+(b.email_error?' · '+b.email_error:'');
  $('invoiceFile').value='';
  $('detailNotice').textContent='';
  if(!$('bookingDialog').open) $('bookingDialog').showModal();
  const data=await api('bookings/'+id+'/events');
  $('eventList').innerHTML=data.events.map(e=>'<li>'+esc(new Date(e.created_at).toLocaleString('it-IT'))+' · '+esc(e.action)+'</li>').join('');
}
async function loadSettings() {
  const conf=await api('settings'), form=$('settingsForm');
  for(const [key,value] of Object.entries(conf)) if(form.elements.namedItem(key)) form.elements.namedItem(key).value=value??'';
  for(const key of ['stripe_secret','stripe_webhook_secret','smtp_password']) {
    form.elements[key].value='';
    form.elements[key].placeholder=conf.configured[key]?'Configurato: lasciare vuoto per mantenere':'Non configurato';
  }
  form.elements.rate_max.value=conf.rates['Suite Max']??'';
  form.elements.rate_michele.value=conf.rates.Michele??'';
  form.elements.rate_rosa.value=conf.rates['Rosa e Romeo']??'';
  $('storageStatus').textContent=conf.storage;
  $('paymentMode').textContent=conf.payment_mode;
  $('webhookUrl').textContent=(conf.site_url||location.origin)+'/api/stripe/webhook';
}
$('loginForm').addEventListener('submit',event=>{
  event.preventDefault();
  run(event.submitter,async()=>{
    const result=await api('login','POST',Object.fromEntries(new FormData(event.target)));
    csrf=result.csrf; showApp(); event.target.elements.password.value=''; notice('');
    await refresh();
  });
});
$('logout').addEventListener('click',event=>run(event.target,async()=>{
  await api('logout','POST',{}); location.reload();
}));
document.querySelectorAll('[data-tab]').forEach(button=>button.addEventListener('click',()=>run(button,async()=>{
  document.querySelectorAll('.tab-view').forEach(view=>view.hidden=view.id!==button.dataset.tab);
  document.querySelectorAll('[data-tab]').forEach(b=>b.removeAttribute('aria-current'));
  button.setAttribute('aria-current','page');
  notice('');
  if(button.dataset.tab==='settings') await loadSettings();
})));
$('refresh').addEventListener('click',event=>run(event.target,async()=>{await refresh();notice('Elenco aggiornato.');}));
$('search').addEventListener('input',renderBookings);
$('statusFilter').addEventListener('change',renderBookings);
$('calendarMonth').value=new Date().toISOString().slice(0,7);
$('calendarMonth').addEventListener('change',renderCalendar);
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-booking]');
  if(button) run(button,()=>openDetail(button.dataset.booking));
});
$('closeDetail').addEventListener('click',()=>$('bookingDialog').close());
$('detailForm').addEventListener('submit',event=>{
  event.preventDefault();
  run(event.submitter,async()=>{
    const f=event.target.elements;
    await api('bookings/'+selected.id,'PATCH',{apartment:f.apartment.value,status:f.status.value,amount_cents:f.amount.value===''?null:Math.round(Number(f.amount.value)*100),notes:f.notes.value});
    await refresh(); await openDetail(selected.id); notice('Prenotazione salvata.');
  });
});
for(const [id,action] of [['createPayment','checkout'],['sendPayment','send-payment'],['sendInvoice','send-invoice'],['sendConfirmation','send-confirmation'],['syncPayment','sync-payment'],['expirePayment','expire-payment']]) {
  $(id).addEventListener('click',event=>run(event.target,async()=>{
    const result=await api('bookings/'+selected.id+'/'+action,'POST',{});
    await refresh(); await openDetail(selected.id); notice(result.message||'Link di pagamento pronto.');
  }));
}
$('uploadInvoice').addEventListener('click',event=>run(event.target,async()=>{
  const file=$('invoiceFile').files[0];
  if(!file||file.size>2*1024*1024||!file.name.toLowerCase().endsWith('.pdf')) throw new Error('Selezionare un PDF di massimo 2 MB.');
  const bytes=new Uint8Array(await file.arrayBuffer());
  let binary=''; for(let i=0;i<bytes.length;i+=8192) binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
  await api('bookings/'+selected.id+'/invoice','POST',{filename:file.name,pdf:btoa(binary)});
  await refresh(); await openDetail(selected.id); notice('PDF caricato. Non ancora inviato al cliente.');
}));
$('blockForm').addEventListener('submit',event=>{
  event.preventDefault();
  run(event.submitter,async()=>{
    await api('blocks','POST',Object.fromEntries(new FormData(event.target)));
    event.target.reset(); await refresh(); notice('Periodo bloccato.');
  });
});
$('newBooking').addEventListener('click',()=>$('manualDialog').showModal());
$('closeManual').addEventListener('click',()=>$('manualDialog').close());
$('manualForm').addEventListener('submit',event=>{
  event.preventDefault();
  run(event.submitter,async()=>{
    const data=Object.fromEntries(new FormData(event.target)); data.guests=Number(data.guests);
    const result=await api('manual','POST',data);
    event.target.reset(); $('manualDialog').close(); await refresh(); await openDetail(result.reference);
  });
});
$('settingsForm').addEventListener('submit',event=>{
  event.preventDefault();
  run(event.submitter,async()=>{
    const values=Object.fromEntries(new FormData(event.target));
    values.smtp_port=Number(values.smtp_port);
    values.rates={'Suite Max':values.rate_max?Number(values.rate_max):null,'Michele':values.rate_michele?Number(values.rate_michele):null,'Rosa e Romeo':values.rate_rosa?Number(values.rate_rosa):null};
    const changePassword=Boolean(values.new_password);
    await api('settings','PATCH',values);
    if(changePassword) { location.reload(); return; }
    await loadSettings(); notice('Impostazioni salvate.');
  });
});
$('testEmail').addEventListener('click',event=>run(event.target,async()=>{
  const result=await api('test-email','POST',{}); notice(result.message);
}));
$('exportCsv').addEventListener('click',()=>{
  const protect=value=>'"'+String(value??'').replace(/^[=+@-]/,"'"+String(value??'').charAt(0)).replaceAll('"','""')+'"';
  const rows=[['Riferimento','Nome','Email','Appartamento','Arrivo','Partenza','Stato','Importo EUR'],...bookings.map(b=>[b.id,b.name,b.email,b.apartment,b.checkin,b.checkout,labels[b.status],b.amount_cents==null?'':b.amount_cents/100])];
  const blob=new Blob(['\ufeff'+rows.map(row=>row.map(protect).join(';')).join('\r\n')],{type:'text/csv;charset=utf-8'});
  const url=URL.createObjectURL(blob), a=document.createElement('a'); a.href=url; a.download='dai-squee-prenotazioni.csv'; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
});
(async()=>{
  try { const result=await api('session'); csrf=result.csrf; showApp(); await refresh(); }
  catch(error) { if(!error.message.includes('Accedere')) notice(error.message,true); }
})();
