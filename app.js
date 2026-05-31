// ════════════════════════════════════════════════════════════════
// CosmoTrade Intelligence — frontend
// All data is REAL, fetched from the backend (/api/data) which serves
// UN Comtrade HS 3304 customs statistics. The AI panel talks to a real
// Claude agent (/api/chat) that has tool access to the same dataset.
// ════════════════════════════════════════════════════════════════

const CHART_COLORS = ['#F97316','#FB923C','#0EA5E9','#EC4899','#F59E0B',
                      '#FB7185','#16A34A','#38BDF8','#94A3B8','#CBD5E1'];
const fmtB = v => (v == null ? 'N/A' : '$' + Number(v).toFixed(2) + 'B');

let DATA = null;          // current payload
let WORLD = null;         // topojson features (loaded once)
let CHARTS = {};          // chart.js instances to destroy on re-render

// ───────────────────────── data loading ─────────────────────────
async function loadData(year) {
  const url = year ? `/api/data?year=${year}` : '/api/data';
  const res = await fetch(url);
  if (!res.ok) throw new Error('Failed to load data: ' + res.status);
  return res.json();
}

async function loadWorld() {
  if (WORLD) return WORLD;
  const topo = await fetch('https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json').then(r => r.json());
  WORLD = topojson.feature(topo, topo.objects.countries).features;
  return WORLD;
}

// ───────────────────────── KPIs ─────────────────────────
function renderKPIs(k) {
  const arrow = v => v == null ? '' :
    `<span class="${v >= 0 ? 'up' : 'down'}">${v >= 0 ? '▲' : '▼'} ${Math.abs(v).toFixed(1)}%</span>`;
  document.querySelector('.kpi-row').innerHTML = `
    <div class="kpi-card export">
      <div class="kpi-label">Global Exports</div>
      <div class="kpi-value">$${k.global_exports_b}B</div>
      <div class="kpi-sub">${arrow(k.exports_yoy)} vs ${k.year - 1}</div>
    </div>
    <div class="kpi-card import">
      <div class="kpi-label">Global Imports</div>
      <div class="kpi-value">$${k.global_imports_b}B</div>
      <div class="kpi-sub">${arrow(k.imports_yoy)} vs ${k.year - 1}</div>
    </div>
    <div class="kpi-card growth">
      <div class="kpi-label">${k.first_year}–${k.year} CAGR</div>
      <div class="kpi-value">${k.cagr_pct == null ? 'N/A' : k.cagr_pct + '%'}</div>
      <div class="kpi-sub">compound annual export growth</div>
    </div>
    <div class="kpi-card countries">
      <div class="kpi-label">Tracked Corridors</div>
      <div class="kpi-value">${k.tracked_corridors.toLocaleString()}</div>
      <div class="kpi-sub">exporter→importer pairs (${k.year})</div>
    </div>`;
}

// ───────────────────────── tables ─────────────────────────
function buildTable(tbodyId, data) {
  const tbody = document.getElementById(tbodyId);
  const maxVal = data.length ? data[0].value_b : 1;
  tbody.innerHTML = data.map((d, i) => `
    <tr>
      <td style="color:var(--text2)">${i + 1}</td>
      <td><div class="country-cell"><span class="country-flag">${d.flag || ''}</span>${d.country}</div></td>
      <td><strong>$${d.value_b.toFixed(2)}B</strong></td>
      <td style="color:var(--text2)">${d.share_pct}%</td>
      <td class="${d.yoy_pct == null ? '' : (d.yoy_pct >= 0 ? 'change-positive' : 'change-negative')}">
        ${d.yoy_pct == null ? '—' : (d.yoy_pct >= 0 ? '+' : '') + d.yoy_pct + '%'}</td>
      <td class="bar-cell"><div class="mini-bar"><div class="mini-bar-fill"
        style="width:${(d.value_b / maxVal * 100).toFixed(1)}%;background:${i < 3 ? 'var(--accent)' : 'var(--accent2)'}"></div></div></td>
    </tr>`).join('');
}

// ───────────────────────── charts ─────────────────────────
const axisColor = '#64748B';
const gridColor = 'rgba(226,232,240,.5)';

function destroy(id) { if (CHARTS[id]) { CHARTS[id].destroy(); delete CHARTS[id]; } }

function buildLineChart(canvasId, trendData, years) {
  destroy(canvasId);
  const ctx = document.getElementById(canvasId).getContext('2d');
  const datasets = Object.entries(trendData).map(([country, values], i) => ({
    label: country, data: values, borderColor: CHART_COLORS[i % CHART_COLORS.length],
    backgroundColor: CHART_COLORS[i % CHART_COLORS.length] + '22',
    borderWidth: 2, pointRadius: 2, pointHoverRadius: 5, tension: 0.3, spanGaps: true,
  }));
  CHARTS[canvasId] = new Chart(ctx, {
    type: 'line', data: { labels: years, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom', labels: { color: axisColor, boxWidth: 12, padding: 10, font: { size: 10 } } },
        tooltip: { mode: 'index', intersect: false, backgroundColor: '#FFFFFF', titleColor: '#1E293B',
          bodyColor: axisColor, borderColor: '#E2E8F0', borderWidth: 1, padding: 10,
          callbacks: { label: c => `${c.dataset.label}: $${(c.parsed.y ?? 0).toFixed(2)}B` } }
      },
      scales: {
        x: { grid: { color: gridColor }, ticks: { color: axisColor, font: { size: 11 } } },
        y: { grid: { color: gridColor }, ticks: { color: axisColor, font: { size: 11 }, callback: v => '$' + v + 'B' }, beginAtZero: true }
      },
      interaction: { mode: 'nearest', axis: 'x', intersect: false }
    }
  });
}

function buildGlobalVolumeChart(vol) {
  destroy('globalVolumeChart');
  const ctx = document.getElementById('globalVolumeChart').getContext('2d');
  CHARTS['globalVolumeChart'] = new Chart(ctx, {
    type: 'bar',
    data: { labels: vol.years, datasets: [
      { label: 'Exports', data: vol.exports, backgroundColor: '#F97316cc', borderRadius: 4, barPercentage: .7 },
      { label: 'Imports', data: vol.imports, backgroundColor: '#EC4899cc', borderRadius: 4, barPercentage: .7 },
    ] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom', labels: { color: axisColor, boxWidth: 12, font: { size: 11 } } },
        tooltip: { backgroundColor: '#FFFFFF', titleColor: '#1E293B', bodyColor: axisColor, borderColor: '#E2E8F0', borderWidth: 1,
          callbacks: { label: c => `${c.dataset.label}: $${(c.parsed.y ?? 0).toFixed(1)}B` } } },
      scales: {
        x: { grid: { display: false }, ticks: { color: axisColor, font: { size: 11 } } },
        y: { grid: { color: gridColor }, ticks: { color: axisColor, font: { size: 11 }, callback: v => '$' + v + 'B' }, beginAtZero: true }
      }
    }
  });
}

function buildRegionGrowthChart(regions) {
  destroy('regionGrowthChart');
  const data = regions.filter(r => r.cagr_pct != null).sort((a, b) => b.cagr_pct - a.cagr_pct);
  const ctx = document.getElementById('regionGrowthChart').getContext('2d');
  CHARTS['regionGrowthChart'] = new Chart(ctx, {
    type: 'bar',
    data: { labels: data.map(r => r.region), datasets: [{
      data: data.map(r => r.cagr_pct),
      backgroundColor: data.map(r => r.cagr_pct > 9 ? '#0EA5E9cc' : r.cagr_pct > 4 ? '#F97316cc' : r.cagr_pct >= 0 ? '#FB923Ccc' : '#EF4444cc'),
      borderRadius: 6, barPercentage: .7 }] },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { backgroundColor: '#FFFFFF', titleColor: '#1E293B', bodyColor: axisColor, borderColor: '#E2E8F0', borderWidth: 1,
        callbacks: { label: c => c.parsed.x.toFixed(1) + '% CAGR' } } },
      scales: {
        x: { grid: { color: gridColor }, ticks: { color: axisColor, font: { size: 11 }, callback: v => v + '%' } },
        y: { grid: { display: false }, ticks: { color: axisColor, font: { size: 11 } } }
      }
    }
  });
}

function buildCorridorChart(corridors) {
  destroy('corridorChart');
  const ctx = document.getElementById('corridorChart').getContext('2d');
  CHARTS['corridorChart'] = new Chart(ctx, {
    type: 'bar',
    data: { labels: corridors.map(c => `${c.from_flag} ${c.exporter} → ${c.to_flag} ${c.importer}`),
      datasets: [{ data: corridors.map(c => c.value_b),
        backgroundColor: corridors.map((_, i) => CHART_COLORS[i % CHART_COLORS.length] + 'cc'), borderRadius: 4, barPercentage: .75 }] },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { backgroundColor: '#FFFFFF', titleColor: '#1E293B', bodyColor: axisColor, borderColor: '#E2E8F0', borderWidth: 1,
        callbacks: { label: c => '$' + c.parsed.x.toFixed(2) + 'B' } } },
      scales: {
        x: { grid: { color: gridColor }, ticks: { color: axisColor, font: { size: 11 }, callback: v => '$' + v + 'B' }, beginAtZero: true },
        y: { grid: { display: false }, ticks: { color: axisColor, font: { size: 10 } } }
      }
    }
  });
}

// ───────────────────────── bilateral matrix ─────────────────────────
function buildBilateralMatrix(bil) {
  const table = document.getElementById('bilateralMatrix');
  const countries = bil.countries, M = bil.matrix;
  const maxVal = Math.max(...M.flat().filter(v => v != null && v > 0), 0.01);
  let html = '<thead><tr><th class="matrix-corner"></th>';
  countries.forEach(c => html += `<th>${c}</th>`);
  html += '</tr></thead><tbody>';
  countries.forEach((row, ri) => {
    html += `<tr><th style="text-align:right;padding-right:10px">${row}</th>`;
    countries.forEach((col, ci) => {
      const v = M[ri][ci];
      if (v == null) { html += '<td style="background:#F4F6FA;color:#94A3B8">—</td>'; return; }
      const t = v / maxVal;
      const r = Math.round(108 + (253 - 108) * t);
      const g = Math.round(92 + (121 - 92) * t * (t < .5 ? 1 : .3));
      const b = Math.round(231 + (168 - 231) * t);
      html += `<td style="background:rgba(${r},${g},${b},${(.12 + t * .5).toFixed(2)});color:${t > .4 ? '#fff' : 'var(--text2)'}"
        title="${row} → ${col}: $${v.toFixed(2)}B">$${v.toFixed(2)}B</td>`;
    });
    html += '</tr>';
  });
  table.innerHTML = html + '</tbody>';
}

// ───────────────────────── opportunities ─────────────────────────
function buildOpportunities(opps) {
  document.getElementById('opportunityList').innerHTML = opps.map(o => `
    <div class="opportunity-card">
      <div class="opp-header">
        <div class="opp-title">${o.title}</div>
        <span class="opp-tag ${o.tag}">${o.tag}</span>
      </div>
      <div class="opp-desc">${o.desc}</div>
      <div class="opp-metrics">${o.metrics.map(m => `<div class="opp-metric"><strong>${m.v}</strong> ${m.l}</div>`).join('')}</div>
    </div>`).join('') || '<div style="color:var(--text2)">No opportunities computed for this year.</div>';
}

// ───────────────────────── REAL MAP (D3 + TopoJSON) ─────────────────────────
async function buildMap(mapData) {
  const features = await loadWorld();
  const container = document.getElementById('mapContainer');
  const W = container.clientWidth || 900, H = 400;
  const svg = d3.select('#mapSvg').attr('viewBox', `0 0 ${W} ${H}`).attr('preserveAspectRatio', 'xMidYMid meet');
  svg.selectAll('*').remove();
  const flow = d3.select('#flowLines').attr('viewBox', `0 0 ${W} ${H}`);
  flow.selectAll('*').remove();

  const projection = d3.geoNaturalEarth1().fitSize([W, H], { type: 'Sphere' });
  const path = d3.geoPath(projection);

  // lookups by numeric id
  const byId = new Map(mapData.map(d => [d.iso_numeric, d]));
  const totals = mapData.map(d => d.export_b + d.import_b).filter(v => v > 0);
  const maxTotal = d3.max(totals) || 1;
  const color = d3.scaleSequentialSqrt(d3.interpolateRgb('#FFE9D5', '#EA580C')).domain([0, maxTotal]);

  // ocean / sphere
  svg.append('path').attr('d', path({ type: 'Sphere' })).attr('fill', '#EEF2F7').attr('stroke', '#E2E8F0');

  // countries
  svg.append('g').selectAll('path').data(features).join('path')
    .attr('d', path)
    .attr('fill', f => { const d = byId.get(+f.id); return d ? color(d.export_b + d.import_b) : '#EAEEF4'; })
    .attr('stroke', '#FFFFFF').attr('stroke-width', 0.4)
    .style('cursor', f => byId.get(+f.id) ? 'pointer' : 'default')
    .on('mousemove', function (ev, f) {
      const d = byId.get(+f.id);
      const tt = document.getElementById('mapTooltip');
      if (!d) { tt.classList.remove('visible'); return; }
      document.getElementById('ttCountry').textContent = `${d.flag || ''} ${d.country}`;
      document.getElementById('ttExport').textContent = d.export_b ? fmtB(d.export_b) : 'N/A';
      document.getElementById('ttImport').textContent = d.import_b ? fmtB(d.import_b) : 'N/A';
      const bal = d.export_b - d.import_b;
      const be = document.getElementById('ttBalance');
      be.textContent = `${bal >= 0 ? '+' : ''}$${bal.toFixed(2)}B`;
      be.style.color = bal >= 0 ? 'var(--positive)' : 'var(--negative)';
      tt.classList.add('visible');
      const rect = container.getBoundingClientRect();
      let x = ev.clientX - rect.left + 14, y = ev.clientY - rect.top + 14;
      x = Math.min(x, rect.width - 200);
      tt.style.left = x + 'px'; tt.style.top = y + 'px';
      d3.select(this).attr('stroke', 'var(--accent2)').attr('stroke-width', 1).raise();
    })
    .on('mouseleave', function () {
      document.getElementById('mapTooltip').classList.remove('visible');
      d3.select(this).attr('stroke', '#FFFFFF').attr('stroke-width', 0.4);
    });

  // flow arcs for top corridors (centroids from geometry)
  const centroidById = new Map();
  features.forEach(f => centroidById.set(+f.id, projection(d3.geoCentroid(f))));
  flow.append('defs').html('<marker id="arrowhead" markerWidth="6" markerHeight="6" refX="5" refY="2" orient="auto"><path d="M0,0 L6,2 L0,4" fill="rgba(251,146,60,.8)"/></marker>');
  const maxFlow = d3.max(DATA.corridors, c => c.value_b) || 1;
  DATA.corridors.slice(0, 8).forEach(c => {
    const a = centroidById.get(c.from_iso), b = centroidById.get(c.to_iso);
    if (!a || !b) return;
    const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2 - Math.abs(b[0] - a[0]) * 0.18 - 20;
    flow.append('path').attr('d', `M${a[0]},${a[1]} Q${mx},${my} ${b[0]},${b[1]}`)
      .attr('fill', 'none').attr('stroke', 'rgba(249,115,22,0.55)')
      .attr('stroke-width', 0.8 + (c.value_b / maxFlow) * 3.5)
      .attr('marker-end', 'url(#arrowhead)').attr('opacity', 0.85);
    flow.append('circle').attr('cx', a[0]).attr('cy', a[1]).attr('r', 2.5).attr('fill', 'var(--accent)');
  });
}

// ───────────────────────── render everything ─────────────────────────
function render(payload) {
  DATA = payload;
  const years = payload.meta.years;
  renderKPIs(payload.kpis);
  buildTable('exportTable', payload.top_exporters);
  buildTable('importTable', payload.top_importers);
  buildLineChart('exportTrendChart', payload.export_trends, years);
  buildLineChart('importTrendChart', payload.import_trends, years);
  buildGlobalVolumeChart(payload.global_volume);
  buildRegionGrowthChart(payload.regions);
  buildBilateralMatrix(payload.bilateral);
  buildCorridorChart(payload.corridors);
  buildOpportunities(payload.opportunities);
  buildMap(payload.map);
  // update the "est." badges to the real year
  document.querySelectorAll('.card-header .badge').forEach(b => {
    if (b.textContent.includes('est')) b.textContent = payload.kpis.year + ' actual';
  });
}

// ───────────────────────── year selector ─────────────────────────
function setupYearSelect(years, latest) {
  const sel = document.getElementById('yearSelect');
  sel.innerHTML = years.slice().reverse().map(y => `<option value="${y}" ${y == latest ? 'selected' : ''}>${y}</option>`).join('');
  sel.addEventListener('change', async () => {
    sel.disabled = true;
    try { render(await loadData(sel.value)); } catch (e) { console.error(e); }
    sel.disabled = false;
  });
}

// ───────────────────────── tabs ─────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
    document.getElementById('tab-' + btn.dataset.tab).style.display = 'block';
    if (btn.dataset.tab === 'overview' && DATA) buildMap(DATA.map); // re-fit map after being hidden
  });
});

// ════════════════════════════════════════════════════════════════
// AI CHAT — real Claude agent via /api/chat
// ════════════════════════════════════════════════════════════════
const chatHistory = [];

function addMessage(role, html) {
  const div = document.createElement('div');
  div.className = `ai-msg ${role}`;
  div.innerHTML = html;
  document.getElementById('aiMessages').appendChild(div);
  const box = document.getElementById('aiMessages');
  box.scrollTop = box.scrollHeight;
  return div;
}

function showTyping() {
  const div = document.createElement('div');
  div.className = 'ai-msg assistant';
  div.id = 'typingIndicator';
  div.innerHTML = '<div class="ai-typing"><span></span><span></span><span></span></div>';
  document.getElementById('aiMessages').appendChild(div);
  const box = document.getElementById('aiMessages');
  box.scrollTop = box.scrollHeight;
}
function removeTyping() { const el = document.getElementById('typingIndicator'); if (el) el.remove(); }

async function handleQuery(query) {
  addMessage('user', escapeHtml(query));
  const sq = document.getElementById('suggestedQueries');
  if (sq) sq.style.display = 'none';
  chatHistory.push({ role: 'user', content: query });
  showTyping();
  try {
    const res = await fetch('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: chatHistory }),
    });
    const data = await res.json();
    removeTyping();
    const reply = data.reply || 'No response.';
    const el = addMessage('assistant', reply);
    if (data.tools_used && data.tools_used.length) {
      const names = [...new Set(data.tools_used.map(t => t.tool))].join(', ');
      const note = document.createElement('div');
      note.style.cssText = 'font-size:10px;color:var(--text2);margin-top:8px;opacity:.7';
      note.textContent = '⚙ queried: ' + names;
      el.appendChild(note);
    }
    // only push to history if it was a real model reply (not a key-missing notice)
    if (!data.needs_key && !data.error) chatHistory.push({ role: 'assistant', content: stripHtml(reply) });
    else chatHistory.pop(); // drop the user turn so they can retry cleanly
  } catch (e) {
    removeTyping();
    addMessage('assistant', '<strong>Connection error.</strong> Is the server running? ' + escapeHtml(String(e)));
    chatHistory.pop();
  }
}

function escapeHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function stripHtml(s) { const d = document.createElement('div'); d.innerHTML = s; return d.textContent; }

document.getElementById('aiSend').addEventListener('click', () => {
  const input = document.getElementById('aiInput');
  const q = input.value.trim();
  if (!q) return;
  input.value = '';
  handleQuery(q);
});
document.getElementById('aiInput').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); document.getElementById('aiSend').click(); }
});
document.querySelectorAll('.suggested-q').forEach(el => el.addEventListener('click', () => handleQuery(el.dataset.q)));

// ───────────────────────── AI drawer toggle (global) ─────────────────────────
function openAI() {
  document.querySelector('.ai-panel').classList.add('open');
  document.getElementById('aiFab').classList.add('hidden');
  setTimeout(() => document.getElementById('aiInput').focus(), 300);
}
function closeAI() {
  document.querySelector('.ai-panel').classList.remove('open');
  document.getElementById('aiFab').classList.remove('hidden');
}
document.getElementById('aiFab').addEventListener('click', openAI);
document.getElementById('aiClose').addEventListener('click', closeAI);
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && document.querySelector('.ai-panel').classList.contains('open')) closeAI();
});

// ───────────────────────── init ─────────────────────────
(async function init() {
  try {
    const payload = await loadData();
    setupYearSelect(payload.meta.years, payload.kpis.year);
    render(payload);
  } catch (e) {
    console.error(e);
    document.querySelector('.kpi-row').innerHTML =
      `<div style="grid-column:1/-1;color:var(--negative);padding:20px">Failed to load data: ${escapeHtml(String(e))}.<br>Make sure the backend is running (<code>python server.py</code>) and data is fetched (<code>python fetch_data.py</code>).</div>`;
  }
  window.addEventListener('resize', () => { if (DATA) buildMap(DATA.map); });
})();
