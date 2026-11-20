// J1: map of stations + station sheet. Data comes from the #map-data JSON in map.html.
(function () {
  const cfg = JSON.parse(document.getElementById('map-data').textContent);
  const you = cfg.you;
  const body = document.body;
  const detail = document.getElementById('detail');

  const map = L.map('map', { zoomControl: false, attributionControl: false }).setView(you, 17);
  L.control.attribution({ position: 'topright', prefix: false }).addTo(map);
  // OpenStreetMap tiles, muted with CSS (app.css .leaflet-tile-pane) to match the mockup.
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);

  L.marker(you, {
    icon: L.divIcon({ className: '', html: '<span class="you-dot"></span>', iconSize: null }),
    interactive: false, keyboard: false,
  }).addTo(map);

  const markers = {};
  let selected = null;
  let route = null;

  function pinIcon(s) {
    const label = s.free === 0 ? 'Full' : s.free + ' free';
    const cls = 'pin pin-' + s.level + (s.id === selected ? ' pin-selected' : '');
    return L.divIcon({ className: '', html: '<span class="' + cls + '">' + label + '</span>', iconSize: null });
  }

  function drawPins(stations) {
    stations.forEach(function (s) {
      if (markers[s.id]) {
        markers[s.id].setIcon(pinIcon(s));
        markers[s.id].station = s;
      } else {
        const m = L.marker([s.lat, s.lng], { icon: pinIcon(s), title: 'Parking space details' }).addTo(map);
        m.station = s;
        m.on('click', function () { openStation(s.id); });
        markers[s.id] = m;
      }
    });
  }

  function sheetHeight() {
    return Math.round(window.innerHeight * 0.56);
  }

  function showOverview() {
    const pts = [you].concat(Object.values(markers).map(function (m) { return m.getLatLng(); }));
    map.fitBounds(pts, { paddingTopLeft: [60, 60], paddingBottomRight: [60, 240], maxZoom: 17 });
  }

  function openStation(id) {
    selected = id;
    const s = markers[id].station;
    drawPins(Object.values(markers).map(function (m) { return m.station; }));
    htmx.ajax('GET', '/space/' + id + '/sheet', { target: '#detail', swap: 'innerHTML' });
    body.classList.add('detail-open');
    if (route) route.remove();
    route = L.polyline([you, [s.lat, s.lng]], { color: '#1D4ED8', weight: 4, dashArray: '2 10', lineCap: 'round' }).addTo(map);
    map.fitBounds([you, [s.lat, s.lng]], { paddingTopLeft: [60, 90], paddingBottomRight: [60, sheetHeight() + 40], maxZoom: 18 });
  }

  function closeStation() {
    selected = null;
    body.classList.remove('detail-open');
    detail.innerHTML = ''; // stops the sheet's 5 s polling
    if (route) { route.remove(); route = null; }
    drawPins(Object.values(markers).map(function (m) { return m.station; }));
    showOverview();
  }

  document.getElementById('back').addEventListener('click', closeStation);
  document.getElementById('locate').addEventListener('click', function () {
    if (selected) openStation(selected); else map.setView(you, 17);
  });

  drawPins(cfg.stations);
  // /#space1 opens that station's sheet directly (a link to one station).
  const linked = location.hash.slice(1);
  if (markers[linked]) openStation(linked); else showOverview();

  // Live free counts on the pins.
  setInterval(function () {
    fetch('/spaces.json').then(function (r) { return r.json(); }).then(drawPins).catch(function () {});
  }, 5000);
})();
