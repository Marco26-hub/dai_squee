const $ = (id) => document.getElementById(id);
const menuButton = $('menuButton'), mobileMenu = $('mobileMenu');
const bookingModal = $('bookingModal'), serviceModal = $('serviceModal');
let returnFocus, pendingRequestKey;
function setMenu(open) {
  menuButton?.setAttribute('aria-expanded', String(open));
  mobileMenu?.classList.toggle('open', open);
  mobileMenu?.setAttribute('aria-hidden', String(!open));
  if (mobileMenu) mobileMenu.inert = !open;
  document.body.classList.toggle('menu-open', open);
}
function openDialog(dialog) {
  returnFocus = document.activeElement;
  setMenu(false);
  dialog.hidden = false;
  document.body.classList.add('modal-open');
  dialog.querySelector('button').focus();
}
function closeDialog(dialog) {
  if (!dialog || dialog.hidden) return;
  dialog.hidden = true;
  document.body.classList.remove('modal-open');
  returnFocus?.focus();
}
function dateString(date) {
  return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('-');
}
const today = dateString(new Date());
document.querySelectorAll('input[type="date"]').forEach((input) => { input.min = today; });
function datesValid(arrival, departure) { return arrival >= today && departure > arrival; }
function openBooking(property) {
  $('modalStayType').value = property || $('stayType')?.value || document.body.dataset.apartment || 'Tutti gli appartamenti';
  $('modalChannel').value = $('bookingChannel')?.value || 'Prenotazione diretta';
  if ($('checkin')) $('modalCheckin').value = $('checkin').value;
  if ($('checkout')) $('modalCheckout').value = $('checkout').value;
  if ($('guests')) $('modalGuests').value = $('guests').value.charAt(0);
  openDialog(bookingModal);
}
function status(message, state = '') {
  $('bookingStatus').textContent = message;
  $('bookingStatus').dataset.state = state;
}
for (const [a,b] of [['checkin','checkout'],['modalCheckin','modalCheckout']]) {
  $(a)?.addEventListener('change', () => {
    const next = new Date($(a).value + 'T12:00:00');
    next.setDate(next.getDate() + 1);
    $(b).min = Number.isNaN(next.getTime()) ? today : dateString(next);
    $(b).setCustomValidity('');
  });
  $(b)?.addEventListener('input', () => $(b).setCustomValidity(''));
}
menuButton?.addEventListener('click', () => setMenu(menuButton.getAttribute('aria-expanded') !== 'true'));
mobileMenu?.querySelectorAll('a').forEach((a) => a.addEventListener('click', () => setMenu(false)));
document.querySelectorAll('[data-open-booking], [data-property]').forEach((button) => button.addEventListener('click', () => openBooking(button.dataset.property)));
document.querySelectorAll('[data-close-modal]').forEach((el) => el.addEventListener('click', () => closeDialog(bookingModal)));
document.querySelectorAll('[data-close-service]').forEach((el) => el.addEventListener('click', () => closeDialog(serviceModal)));
document.querySelectorAll('[data-service]').forEach((button) => button.addEventListener('click', () => {
  $('serviceTitle').textContent = button.dataset.service;
  serviceModal.querySelector('.service-panel > p:not(.eyebrow)').textContent = button.closest('article').querySelector('p').textContent;
  openDialog(serviceModal);
}));
$('quickSearch')?.addEventListener('submit', (event) => {
  event.preventDefault();
  $('checkout').setCustomValidity(datesValid($('checkin').value, $('checkout').value) ? '' : "La partenza deve essere successiva all'arrivo.");
  if ($('quickSearch').reportValidity()) openBooking();
});
$('bookingForm')?.addEventListener('input', () => { pendingRequestKey = null; });
$('bookingForm')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!datesValid($('modalCheckin').value, $('modalCheckout').value)) {
    status("Controllate le date: l'arrivo non può essere nel passato e la partenza deve essere successiva.", 'error');
    return;
  }
  const data = {
    name: $('guestName').value.trim(), email: $('guestEmail').value.trim(),
    phone: $('guestPhone').value.trim(), apartment: $('modalStayType').value,
    channel: $('modalChannel').value, checkin: $('modalCheckin').value,
    checkout: $('modalCheckout').value, guests: Number($('modalGuests').value),
    message: $('guestMessage').value.trim(), consent: $('privacyConsent').checked
  };
  const body = [data.name, data.email, data.phone, data.apartment, data.checkin + ' / ' + data.checkout, data.guests + ' ospiti', data.message].join('\n');
  $('bookingEmail').href = 'mailto:info@daisquee.it?subject=' + encodeURIComponent('Richiesta soggiorno - ' + data.apartment) + '&body=' + encodeURIComponent(body);
  const submit = event.target.querySelector('[type="submit"]');
  submit.disabled = true;
  status('Invio della richiesta in corso...');
  pendingRequestKey ||= window.crypto?.randomUUID?.() || String(Date.now()) + Math.random().toString(36).slice(2);
  try {
    if (location.protocol === 'file:') throw new Error('La richiesta online richiede il sito attivo. Potete inviarci le stesse informazioni tramite il link email qui sotto.');
    const response = await fetch('/api/bookings', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': pendingRequestKey },
      body: JSON.stringify(data), signal: AbortSignal.timeout(15000)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Invio non riuscito. Riprovate o contattateci via email.');
    status('Richiesta registrata: ' + result.reference + '. La prenotazione sarà confermata dalla struttura dopo la verifica.', 'success');
    event.target.reset();
    pendingRequestKey = null;
  } catch (error) {
    status(error.name === 'TimeoutError' ? "Non abbiamo ricevuto l'esito. Riprovate: la stessa richiesta non verrà duplicata, oppure contattateci." : (error.message === 'Failed to fetch' ? 'Connessione non disponibile. I dati restano nel modulo: riprovate oppure usate email o telefono.' : error.message), 'error');
  } finally { submit.disabled = false; }
});
document.addEventListener('keydown', (event) => {
  const dialog = [bookingModal, serviceModal].find((el) => el && !el.hidden);
  if (event.key === 'Escape') { if (dialog) closeDialog(dialog); setMenu(false); }
  if (event.key === 'Tab' && dialog) {
    const focusable = [...dialog.querySelectorAll('a[href], button, input, select, textarea')].filter((el) => !el.disabled && el.getClientRects().length);
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
});
function updateHeader() { $('siteHeader')?.classList.toggle('scrolled', window.scrollY > 36); }
window.addEventListener('scroll', updateHeader, { passive: true });
if ('IntersectionObserver' in window && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) { entry.target.classList.add('visible'); observer.unobserve(entry.target); }
    });
  }, { threshold: .08 });
  document.documentElement.classList.add('motion-ready');
  document.querySelectorAll('.reveal').forEach((el) => observer.observe(el));
}
document.querySelectorAll('img').forEach((img) => img.addEventListener('error', () => {
  const note = document.createElement('span');
  note.className = 'image-error';
  note.textContent = 'Foto non disponibile: ' + img.alt;
  img.replaceWith(note);
}));
setMenu(false);
updateHeader();
if (location.protocol !== 'file:') {
  fetch('/api/config').then(response => {
    if (!response.ok) return null;
    return response.json();
  }).then(config => {
    if (!config) return;
    const portals = {'https://www.booking.com/':'booking_url','https://www.airbnb.it/':'airbnb_url','https://www.vrbo.com/':'vrbo_url'};
    document.querySelectorAll('a[href]').forEach(link => {
      const key = portals[link.getAttribute('href')];
      if (key && config[key] && new URL(config[key]).protocol === 'https:') link.href = config[key];
    });
  }).catch(() => {
    // Static contact and portal links remain available when configuration is unreachable.
  });
}
