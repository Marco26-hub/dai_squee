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
  form.elements.checkin.value=b.checkin; form.elements.checkout.value=b.checkout;
  $('manualPaymentRow').hidden=!['arrival','bank'].includes(b.payment_method)||Boolean(b.paid_at)||b.status!=='confirmed';
  $('acceptedTerms').textContent=b.accepted_terms?'Condizioni accettate: '+JSON.parse(b.accepted_terms).terms:'';
  ['apartment','status','amount','checkin','checkout'].forEach(name=>form.elements[name].disabled=Boolean(b.checkout_id||b.paid_at));
  $('paymentState').textContent=b.paid_at?'Pagamento verificato il '+new Date(b.paid_at).toLocaleString('it-IT'):b.checkout_id?'Link di pagamento creato. In attesa di pagamento verificato.':'Pagamento non richiesto.';
  if(b.payment_method) $('paymentState').textContent+=' Modalità: '+({arrival:"all'arrivo",bank:'bonifico',card:'carta'}[b.payment_method]);
  $('paymentLink').hidden=!b.checkout_url;
  if(b.checkout_url) $('paymentLink').href=b.checkout_url;
  $('createPayment').disabled=b.status!=='confirmed'||Boolean(b.paid_at);
  $('sendPayment').disabled=!b.checkout_url||Boolean(b.paid_at);
  $('syncPayment').disabled=!b.checkout_id;
  $('expirePayment').disabled=!b.checkout_id||Boolean(b.paid_at);
  $('sendConfirmation').disabled=b.status!=='confirmed'||(b.payment_method==='card'&&!b.paid_at);
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
  for(const [key,value] of Object.entries(conf)) if(form.elements.namedItem(key)) form.elements.namedItem(key).type==='checkbox' ? form.elements.namedItem(key).checked=Boolean(value) : form.elements.namedItem(key).value=value??'';
  for(const key of ['stripe_secret','stripe_webhook_secret','smtp_password']) {
    form.elements[key].value='';
    form.elements[key].placeholder=conf.configured[key]?'Configurato: lasciare vuoto per mantenere':'Non configurato';
  }
  form.elements.rate_max.value=conf.rates['Suite Max']??'';
  form.elements.rate_michele.value=conf.rates.Michele??'';
  form.elements.rate_rosa.value=conf.rates['Rosa e Romeo']??'';
  form.elements.capacity_max.value=conf.capacities['Suite Max'];
  form.elements.capacity_michele.value=conf.capacities.Michele;
  form.elements.capacity_rosa.value=conf.capacities['Rosa e Romeo'];
  for(const method of ['arrival','card','bank']) form.elements['pay_'+method].checked=conf.payment_methods.includes(method);
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
  if(button.dataset.tab==='photos') await loadPhotos();
  if(button.dataset.tab==='channels') await loadChannels();
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
    await api('bookings/'+selected.id,'PATCH',{apartment:f.apartment.value,status:f.status.value,amount_cents:f.amount.value===''?null:Math.round(Number(f.amount.value)*100),notes:f.notes.value,checkin:f.checkin.value,checkout:f.checkout.value});
    await refresh(); await openDetail(selected.id); notice('Prenotazione salvata.');
  });
});
for(const [id,action] of [['createPayment','checkout'],['sendPayment','send-payment'],['sendInvoice','send-invoice'],['sendConfirmation','send-confirmation'],['syncPayment','sync-payment'],['expirePayment','expire-payment']]) {
  $(id).addEventListener('click',event=>run(event.target,async()=>{
    const result=await api('bookings/'+selected.id+'/'+action,'POST',{});
    await refresh(); await openDetail(selected.id); notice(result.message||'Link di pagamento pronto.');
  }));
}
$('recordPayment').addEventListener('click',event=>run(event.target,async()=>{
  const reference=$('manualPaymentReference').value.trim();
  if(!reference) throw new Error('Inserire un riferimento dell’incasso verificato.');
  await api('bookings/'+selected.id+'/record-payment','POST',{reference});
  await refresh(); await openDetail(selected.id); notice('Incasso registrato.');
}));
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
    values.direct_enabled=event.target.elements.direct_enabled.checked;
    values.payment_methods=['arrival','card','bank'].filter(method=>event.target.elements['pay_'+method].checked);
    values.capacities={'Suite Max':Number(values.capacity_max),'Michele':Number(values.capacity_michele),'Rosa e Romeo':Number(values.capacity_rosa)};
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
const channelRooms = {'suite-max':'Suite Max','michele':'Michele','rosa-e-romeo':'Rosa e Romeo'};
let channelConfig = null, channelManagerVersion = 0;
async function loadChannels() {
  channelConfig = await api('channels');
  renderChannels();
  const form=$('channelManagerForm'), manager=channelConfig.manager;
  channelManagerVersion=manager.version;
  form.elements.provider.value=manager.provider;
  form.elements.account_ref.value=manager.account_ref;
  for(const [slug,room] of Object.entries(channelRooms))form.elements[slug].value=manager.mappings[room];
}
function renderChannels() {
  if(!channelConfig)return;
  const slug=$('channelApartment').value, room=channelRooms[slug];
  $('channelConnections').innerHTML=channelConfig.connections.filter(c=>c.apartment===room).map(c=>{
    const name=c.channel==='booking'?'Booking.com':'Airbnb';
    return '<form data-channel="'+c.channel+'"><fieldset><legend>'+name+'</legend><div class="connection-heading"><span class="badge '+(c.status==='prepared'?'pending':'')+'">'+(c.status==='prepared'?'Predisposto, importazione non attiva':'Non configurato')+'</span><span class="muted">Ultima sincronizzazione: mai</span></div><div class="fields"><label>ID annuncio / unita\'<input name="listing_id" value="'+esc(c.listing_id)+'" maxlength="120" autocomplete="off" /></label><label>Link calendario iCal del portale<input name="import_url" type="url" autocomplete="off" maxlength="2048" placeholder="'+(c.import_configured?'Salvato: lasciare vuoto per mantenere':'https://')+'" /></label></div><label class="check-label"><input name="clear_import" type="checkbox" '+(c.import_configured?'':'disabled')+' /> Rimuovi il calendario salvato</label><button class="primary" type="submit">Salva collegamento '+name+'</button></fieldset></form>';
  }).join('');
  const item=channelConfig.exports.find(e=>e.apartment===room);
  $('exportStatus').textContent=item.active?'Esportazione disponibile. Importazione dai portali non attiva.':'Nessun link di esportazione creato per questo appartamento.';
  if(!channelConfig.site_url_configured)$('exportStatus').textContent+=' Configurare il dominio HTTPS in Impostazioni.';
  $('exportUrl').value=item.url;
  $('exportUrlLabel').hidden=!item.url;
  $('createExport').hidden=item.active;
  $('createExport').disabled=!channelConfig.site_url_configured;
  for(const id of ['copyExport','rotateExport','revokeExport'])$(id).hidden=!item.active;
  $('copyExport').disabled=!item.url;
}
$('channelApartment').addEventListener('change',renderChannels);
$('refreshChannels').addEventListener('click',event=>run(event.target,loadChannels));
$('channelConnections').addEventListener('submit',event=>{
  event.preventDefault();
  run(event.submitter,async()=>{
    const form=event.target,slug=$('channelApartment').value,room=channelRooms[slug],channel=form.dataset.channel;
    const current=channelConfig.connections.find(c=>c.apartment===room&&c.channel===channel);
    const data={listing_id:form.elements.listing_id.value,import_url:form.elements.import_url.value,clear_import:form.elements.clear_import.checked,version:current.version};
    channelConfig=await api('channels/'+slug+'/'+channel,'PATCH',data);
    renderChannels();notice('Predisposizione salvata. Nessuna importazione dai portali attivata.');
  });
});
$('channelManagerForm').addEventListener('submit',event=>{
  event.preventDefault();
  run(event.submitter,async()=>{
    const form=event.target;
    await api('channels/manager','PATCH',{provider:form.elements.provider.value,account_ref:form.elements.account_ref.value,mappings:Object.fromEntries(Object.entries(channelRooms).map(([slug,room])=>[room,form.elements[slug].value])),version:channelManagerVersion});
    await loadChannels();notice('Dati del gestionale salvati. Il connettore API non e\' ancora attivo.');
  });
});
for(const [id,action] of [['createExport','create'],['rotateExport','rotate'],['revokeExport','revoke']]){
  $(id).addEventListener('click',event=>run(event.target,async()=>{
    if(action!=='create'&&!confirm(action==='rotate'?'Il vecchio link smettera\' di funzionare. Aggiornare anche i portali con il nuovo link. Continuare?':'Revocare il link? I portali non potranno piu\' leggere gli aggiornamenti di questo calendario.'))return;
    channelConfig=await api('channels/exports/'+$('channelApartment').value,'POST',{action});
    renderChannels();notice(action==='revoke'?'Link revocato. Verificare anche i calendari dei portali.':'Link iCal pronto. Contiene soltanto le occupazioni del sito.');
  }));
}
$('copyExport').addEventListener('click',event=>run(event.target,async()=>{
  try {await navigator.clipboard.writeText($('exportUrl').value);notice('Link iCal copiato. Condividerlo solo con i servizi autorizzati.');}
  catch { $('exportUrl').focus();$('exportUrl').select();notice('Copia automatica non disponibile: il link e\' selezionato.',true); }
}));
async function loadPhotos() {
  const data=await api('photos');
  const photos=data.photos.filter(p=>p.apartment===$('photoApartment').value);
  $('photoGrid').innerHTML=photos.map(p=>'<article data-photo="'+p.id+'"><img src="/api/photos/'+p.id+'" alt="'+esc(p.caption)+'" /><label>Descrizione<input data-caption value="'+esc(p.caption)+'" maxlength="240" /></label><label>Descrizione in inglese<input data-caption-en value="'+esc(p.caption_en||'')+'" maxlength="240" /></label><p>'+(p.role==='cover'?'Copertina':'Galleria')+'</p><div class="action-row"><button data-photo-action="caption" title="Salva descrizione" aria-label="Salva descrizione">Salva</button><button data-photo-action="cover">Usa come copertina</button><button data-photo-action="remove" title="Rimuovi foto" aria-label="Rimuovi foto">×</button></div></article>').join('')||'<p>Nessuna foto personalizzata. Il sito mostra le immagini originali.</p>';
}
$('photoApartment').addEventListener('change',()=>run(null,loadPhotos));
$('photoForm').addEventListener('submit',event=>{
  event.preventDefault();
  run(event.submitter,async()=>{
    const file=$('photoFile').files[0];
    if(!file||file.size>3*1024*1024||!['image/jpeg','image/png','image/webp'].includes(file.type)) throw new Error('Selezionare un JPG, PNG o WebP di massimo 3 MB.');
    const bitmap=await createImageBitmap(file);bitmap.close();
    const bytes=new Uint8Array(await file.arrayBuffer());let binary='';
    for(let i=0;i<bytes.length;i+=8192) binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
    const data=Object.fromEntries(new FormData(event.target));delete data.image;data.image=btoa(binary);
    await api('photos','POST',data);$('photoFile').value='';await loadPhotos();notice('Foto pubblicata sul sito.');
  });
});
$('photoGrid').addEventListener('click',event=>{
  const button=event.target.closest('[data-photo-action]');if(!button)return;
  const item=button.closest('[data-photo]'), action=button.dataset.photoAction;
  if(action==='remove'&&!confirm('Rimuovere questa foto dal sito?'))return;
  run(button,async()=>{
    const payload=action==='remove'?{remove:true}:action==='cover'?{role:'cover'}:{caption:item.querySelector('[data-caption]').value,caption_en:item.querySelector('[data-caption-en]').value};
    await api('photos/'+item.dataset.photo,'PATCH',payload);await loadPhotos();notice('Foto aggiornata.');
  });
});
(async()=>{
  try { const result=await api('session'); csrf=result.csrf; showApp(); await refresh(); }
  catch(error) { if(!error.message.includes('Accedere')) notice(error.message,true); }
})();
