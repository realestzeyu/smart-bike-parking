// J7: map of parking spaces on the officer console. Pin = donut ring of the space's lots
// (red tamper, orange to clear, green in use, grey free) with "used/total" in the middle; hover = breakdown.
(function () {
  const map = L.map('console-map', { zoomControl: true, attributionControl: false, scrollWheelZoom: false });
  L.control.attribution({ position: 'bottomright', prefix: false }).addTo(map);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);

  const markers = {};

  // Tooltip rows; colours match RING_COLOURS in pages/officer.py.
  const PARTS = [
    ['tamper', '#B91C1C', 'Tamper'],
    ['clear', '#FF6E00', 'To clear'],
    ['in_use', '#0F766E', 'In use'],
    ['free', '#D9D7D0', 'Free'],
  ];

  function esc(t) {
    return String(t).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; });
  }

  // s.ring (counter-clockwise donut) is built on the server: ring_css() in pages/officer.py.
  function icon(s) {
    const html = '<span class="ring-pin" style="background: ' + s.ring + '"><span>' + s.used + '/' + s.total + '</span></span>';
    return L.divIcon({ className: '', html: html, iconSize: null });
  }

  function tip(s) {
    const rows = PARTS.map(function (p) {
      return '<li><span class="dot" style="background:' + p[1] + '"></span>' + p[2] + '<b>' + s[p[0]] + '</b></li>';
    }).join('');
    return '<div class="ring-tip"><strong>' + esc(s.address) + '</strong><ul>' + rows + '</ul>' +
      '<p>' + s.used + ' of ' + s.total + ' lots used (' + s.pct + '%)</p></div>';
  }

  function draw(stations) {
    stations.forEach(function (s) {
      if (markers[s.id]) {
        markers[s.id].setIcon(icon(s));
        markers[s.id].setTooltipContent(tip(s));
      } else {
        markers[s.id] = L.marker([s.lat, s.lng], { icon: icon(s), keyboard: false })
          .bindTooltip(tip(s), { direction: 'top', offset: [0, -30] })
          .addTo(map);
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

// Last-24-h charts: one shared tooltip for any [data-tip] inside an svg.chart, plus a crosshair on the line chart.
// Listeners sit on document, so they keep working when HTMX swaps the charts in.
(function () {
  const tip = document.createElement('div');
  tip.className = 'chart-tip';
  tip.hidden = true;
  document.body.appendChild(tip);

  function crosshair(svg, x, y) {
    const line = svg.querySelector('.xhair');
    const dot = svg.querySelector('.xdot');
    if (!line) return;
    const show = x == null ? 'hidden' : 'visible';
    line.setAttribute('visibility', show);
    dot.setAttribute('visibility', show);
    if (x != null) {
      line.setAttribute('x1', x); line.setAttribute('x2', x);
      dot.setAttribute('cx', x); dot.setAttribute('cy', y);
    }
  }

  document.addEventListener('mousemove', function (e) {
    const t = e.target.closest && e.target.closest('svg.chart [data-tip]');
    if (!t) {
      tip.hidden = true;
      document.querySelectorAll('svg.chart').forEach(function (svg) { crosshair(svg, null); });
      return;
    }
    tip.textContent = t.dataset.tip;
    tip.hidden = false;
    tip.style.left = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8) + 'px';
    tip.style.top = (e.clientY - tip.offsetHeight - 12) + 'px';
    if (t.dataset.x) crosshair(t.ownerSVGElement, t.dataset.x, t.dataset.y);
  });
})();
