const header = document.getElementById('siteHeader');
const menuButton = document.getElementById('menuButton');
const mobileMenu = document.getElementById('mobileMenu');
const bookingModal = document.getElementById('bookingModal');
const serviceModal = document.getElementById('serviceModal');
const toast = document.getElementById('toast');
const quickSearch = document.getElementById('quickSearch');
const bookingForm = document.getElementById('bookingForm');
let toastTimer;

function setMenu(open) {
  menuButton.setAttribute('aria-expanded', String(open));
  mobileMenu.classList.toggle('open', open);
  mobileMenu.setAttribute('aria-hidden', String(!open));
  document.body.classList.toggle('menu-open', open);
}

function showToast(title, message) {
  toast.querySelector('strong').textContent = title;
  toast.querySelector('small').textContent = message;
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toast.classList.remove('show'), 4200);
}

function openBooking(property) {
  setMenu(false);
  if (property) document.getElementById('modalStayType').value = property;
  const selectedApartment = document.getElementById('stayType')?.value;
  const selectedChannel = document.getElementById('bookingChannel')?.value;
  if (!property && selectedApartment) document.getElementById('modalStayType').value = selectedApartment;
  if (selectedChannel) document.getElementById('modalChannel').value = selectedChannel;
  document.getElementById('modalCheckin').value = document.getElementById('checkin').value;
  document.getElementById('modalCheckout').value = document.getElementById('checkout').value;
  bookingModal.hidden = false;
  document.body.classList.add('modal-open');
  bookingModal.querySelector('.modal-close').focus();
}

function closeBooking() {
  bookingModal.hidden = true;
  document.body.classList.remove('modal-open');
}

function openService(name) {
  setMenu(false);
  document.getElementById('serviceTitle').textContent = name || 'Servizio incluso';
  serviceModal.hidden = false;
  document.body.classList.add('modal-open');
  serviceModal.querySelector('.modal-close').focus();
}

function closeService() {
  serviceModal.hidden = true;
  document.body.classList.remove('modal-open');
}

function updateHeader() {
  header.classList.toggle('scrolled', window.scrollY > 36);
}

function setDefaultDates() {
  const today = new Date();
  const checkin = new Date(today);
  checkin.setDate(today.getDate() + 14);
  const checkout = new Date(checkin);
  checkout.setDate(checkin.getDate() + 3);
  const toDate = (date) => date.toISOString().slice(0, 10);
  document.getElementById('checkin').value = toDate(checkin);
  document.getElementById('checkout').value = toDate(checkout);
}

menuButton.addEventListener('click', () => setMenu(menuButton.getAttribute('aria-expanded') !== 'true'));
mobileMenu.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => setMenu(false)));
document.querySelectorAll('[data-open-booking]').forEach((button) => button.addEventListener('click', () => openBooking(button.dataset.property)));
document.querySelectorAll('[data-close-modal]').forEach((element) => element.addEventListener('click', closeBooking));
document.querySelectorAll('[data-close-service]').forEach((element) => element.addEventListener('click', closeService));
document.querySelectorAll('[data-service]').forEach((button) => button.addEventListener('click', () => openService(button.dataset.service)));
document.querySelectorAll('[data-property]').forEach((button) => button.addEventListener('click', () => openBooking(button.dataset.property)));

quickSearch.addEventListener('submit', (event) => {
  event.preventDefault();
  openBooking();
});

bookingForm.addEventListener('submit', (event) => {
  event.preventDefault();
  closeBooking();
  showToast('Richiesta ricevuta', 'Dai Squee vi contatterà a breve.');
  bookingForm.reset();
});

window.addEventListener('scroll', updateHeader, { passive: true });
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    if (!bookingModal.hidden) closeBooking();
    if (!serviceModal.hidden) closeService();
    setMenu(false);
  }
});

const observer = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (!entry.isIntersecting) return;
    entry.target.classList.add('visible');
    observer.unobserve(entry.target);
  });
}, { threshold: 0.12 });

document.querySelectorAll('.reveal').forEach((element) => observer.observe(element));
setDefaultDates();
updateHeader();
