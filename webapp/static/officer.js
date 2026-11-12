// J7: stations map on the officer console. Pin = number of suspected abandoned + unregistered bikes.
(function () {
  const map = L.map('console-map', { zoomControl: true, attributionControl: false, scrollWheelZoom: false });
  L.control.attribution({ position: 'bottomright', prefix: false }).addTo(map);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);

  const markers = {};

  function icon(s) {
    const n = s.abandoned + s.unregistered;
    const html = n
      ? '<span class="count-pin">' + n + '</span>'
      : '<span class="station-dot"></span>';
    return L.divIcon({ className: '', html: html, iconSize: null });
  }

  function draw(stations) {
    stations.forEach(function (s) {
      if (markers[s.id]) {
        markers[s.id].setIcon(icon(s));
      } else {
        markers[s.id] = L.marker([s.lat, s.lng], { icon: icon(s), title: s.address, keyboard: false }).addTo(map);
      }
    });
  }

  const stations = JSON.parse(document.getElementById('console-stations').textContent);
  draw(stations);
  if (stations.length === 1) map.setView([stations[0].lat, stations[0].lng], 17);
  else if (stations.length) map.fitBounds(stations.map(function (s) { return [s.lat, s.lng]; }), { padding: [40, 40] });

  setInterval(function () {
    fetch('/officer/stations.json').then(function (r) { return r.json(); }).then(draw).catch(function () {});
  }, 5000);
})();
