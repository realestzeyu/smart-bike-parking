// Small, non-interactive map at the top of the lot page: one pin for this lot.
(function () {
  const el = document.getElementById('mini-map');
  const at = [parseFloat(el.dataset.lat), parseFloat(el.dataset.lng)];
  const map = L.map(el, {
    zoomControl: false, attributionControl: false, dragging: false, scrollWheelZoom: false,
    doubleClickZoom: false, touchZoom: false, boxZoom: false, keyboard: false,
  }).setView(at, 18);
  L.control.attribution({ position: 'bottomright', prefix: false }).addTo(map);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);
  const pin = document.createElement('span');
  pin.className = 'pin pin-' + el.dataset.level;
  pin.textContent = el.dataset.label;
  L.marker(at, { icon: L.divIcon({ className: '', html: pin.outerHTML, iconSize: null }), interactive: false }).addTo(map);
})();
