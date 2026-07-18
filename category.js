// ════════════════════════════════════════════════════════════════
// Product Scout — Category detail page (Amazon reviews + Google Trends + Reddit)
// Opened when a product category is clicked in Social Discovery.
// ════════════════════════════════════════════════════════════════

window._catCharts = [];
window._trendChart = null;
function destroyCatCharts() {
  window._catCharts.forEach(c => c.destroy());
  window._catCharts = [];
  if (window._trendChart) { window._trendChart.destroy(); window._trendChart = null; }
}

const stars = r => { const n = Math.round(r || 0); return '★'.repeat(n) + '☆'.repeat(Math.max(0, 5 - n)); };
const negColor = v => v >= 40 ? '#EF4444' : v >= 25 ? '#F97316' : v >= 12 ? '#EAB308' : '#22C55E';

window.openCategory = async function openCategory(name) {
  window._currentCategory = name;
  const box = document.getElementById('socialCategory');
  document.getElementById('socialOverview').style.display = 'none';
  document.getElementById('socialResults').innerHTML = '';
  const ss = document.getElementById('socialSearchSection');   // hide title + search on detail page
  if (ss) ss.style.display = 'none';
  destroyCatCharts();
  box.style.display = 'block';
  box.innerHTML = `<button class="home-btn" onclick="goHome()">← All categories</button>
    <div style="text-align:center;color:var(--text2);padding:50px">Loading ${esc(name)} intelligence…</div>`;
  window.scrollTo({ top: 0, behavior: 'smooth' });
  let d;
  try { d = await fetch('/api/social/category?name=' + encodeURIComponent(name)).then(r => r.json()); }
  catch (e) { box.innerHTML = `<button class="home-btn" onclick="goHome()">← All categories</button><div style="color:var(--negative);padding:20px">Failed to load: ${esc(String(e))}</div>`; return; }
  renderCategoryPage(box, d);
};

function renderCategoryPage(box, d) {
  const s = d.social_summary || {};
  let html = `<button class="home-btn" onclick="goHome()">← All categories</button>
    <div class="cat-page-head">
      <h2>${esc(d.category)}</h2>
      <div class="cat-head-meta">
        <span class="sub-badge">${(s.n_posts || 0)} Reddit posts</span>
        <span class="sent-badge ${sentClass(s.sentiment_label)}">community mood: ${s.sentiment_label}</span>
      </div>
    </div>`;

  const fr = d.freshness || {};
  html += amazonModule(d.amazon, fr.amazon);
  html += trendsModule(d.trends, fr.trends);
  html += redditModule(d.reddit);

  box.innerHTML = html;

  // charts after DOM insert (aspect chart renders lazily on expand)
  if (d.amazon && d.amazon.available) setupAmazonToggle(d.amazon.category_aspects);
  setupTrends(d.trends);
}

// ───────────────────────── Amazon module ─────────────────────────
function amazonModule(a, fr) {
  if (!a || !a.available) {
    return `<div class="module">
      <div class="module-head"><h3>Amazon Reviews Intelligence</h3><span class="src-badge sample">not yet ingested</span></div>
      <div style="color:var(--text2);font-size:13px">Amazon review data for this category has not been ingested yet. Live scraping &amp; ingestion is planned; the three seeded categories (Sunscreen / SPF, Moisturizer &amp; Hydration, Cleanser &amp; Oil Control) are available now.</div>
    </div>`;
  }
  const sm = a.summary;
  const pp = sm.top_painpoint, best = sm.best_product;
  const summary = `
    <div class="amz-summary">
      <div class="amz-stat"><div class="v stars-amz">${sm.avg_rating_weighted}★</div><div class="l">avg rating (weighted)</div></div>
      <div class="amz-stat"><div class="v">${sm.n_products}</div><div class="l">products tracked</div></div>
      <div class="amz-stat"><div class="v">${(sm.total_ratings || 0).toLocaleString()}</div><div class="l">total ratings (reach)</div></div>
      ${pp ? `<div class="amz-stat"><div class="v" style="color:var(--negative);font-size:15px">${esc(pp.name)}</div><div class="l">top pain point</div><div class="s">${pp.neg_rate}% neg · ${(pp.mentions||0).toLocaleString()} mentions</div></div>` : ''}
      ${best ? `<div class="amz-stat"><div class="v" style="font-size:15px">${esc(best.brand)}</div><div class="l">best-in-class</div><div class="s">${best.avg_rating}★ · ${(best.total_ratings||0).toLocaleString()} ratings</div></div>` : ''}
    </div>`;

  const callout = `
    <div class="insight-callout">
      <div class="ic-title">Sourcer insights · compiled from the reviews</div>
      ${(sm.insights || []).map(i => `<div class="ic-row"><span class="ic-tag ${i.tone}">${esc(i.tag)}</span><span>${i.text}</span></div>`).join('')}
    </div>`;

  const rows = a.products.map(p => {
    const dn = p.dominant_negative;
    return `<tr>
      <td><div class="amz-brand">${esc(p.brand)}<small>${esc(p.title)}</small></div></td>
      <td style="white-space:nowrap"><span class="stars-amz">${stars(p.avg_rating)}</span> ${p.avg_rating}</td>
      <td>${(p.total_ratings || 0).toLocaleString()}</td>
      <td>${p.n_reviews}</td>
      <td><div class="negbar-wrap"><div class="negbar"><div style="width:${Math.min(p.overall_neg_rate, 100)}%;background:${negColor(p.overall_neg_rate)}"></div></div><span style="color:${negColor(p.overall_neg_rate)};font-weight:600">${p.overall_neg_rate}%</span></div></td>
      <td>${dn ? `<span class="aspect-chip">${esc(dn.name)} · ${dn.neg_rate}%</span>` : '—'}</td>
    </tr>`;
  }).join('');
  const table = `
    <div style="overflow-x:auto"><table class="amz-table">
      <thead><tr><th>Product</th><th>Rating</th><th>Total ratings</th><th>Reviews</th><th>Aspect neg. rate</th><th>Weakest aspect</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;

  const chart = `
    <div style="margin-top:20px">
      <div class="card-sub" style="font-size:12px;color:var(--text2);margin-bottom:8px">Aspect negative rate, category-wide — <strong>taller bars = bigger unmet need / sourcing opportunity</strong></div>
      <div class="amz-chart-wrap"><canvas id="amzAspectChart"></canvas></div>
    </div>`;

  const voc = a.voice_of_customer;
  const quoteCard = (q, color) => `
    <div class="quote-card" style="--qc:${color}">
      <div class="qc-top"><span class="qc-brand">${esc(q.brand)} ${'★'.repeat(q.rating || 0)}</span><span class="qc-meta">${q.helpful} helpful${q.verified ? ' · verified' : ''}</span></div>
      <div class="qc-text">“${esc(q.text)}”</div>
    </div>`;
  const vocBlock = `
    <div style="margin-top:20px">
      <div class="voc-grid">
        <div>
          <div class="voc-col-label" style="color:var(--negative)">What buyers complain about</div>
          ${(voc?.negative || []).map(q => quoteCard(q, 'var(--negative)')).join('') || '<div style="color:var(--text2);font-size:12px">No low-rating reviews in sample.</div>'}
        <div>
          <div class="voc-col-label" style="color:var(--positive)">What buyers love</div>
          ${(voc?.positive || []).map(q => quoteCard(q, 'var(--positive)')).join('') || '<div style="color:var(--text2);font-size:12px">No positive reviews in sample.</div>'}
        </div>
      </div>
    </div>`;

  // Keep the at-a-glance summary + insights visible; collapse the heavy detail.
  const toggle = `
    <button class="expand-btn" id="amzToggle">
      <span><span class="tg-ico">▸</span> Show product breakdown, aspect chart &amp; customer reviews</span>
      <span class="tg-count">${sm.n_products} products · ${sm.n_reviews} reviews</span>
    </button>
    <div class="amz-details" id="amzDetails" style="display:none">${table}${chart}${vocBlock}</div>`;

  return `<div class="module">
    <div class="module-head"><h3>Amazon Reviews Intelligence</h3><span class="src-badge sample">${esc(a.meta.source)}</span></div>
    ${window.freshBar ? window.freshBar(fr) : ''}
    ${summary}${callout}${toggle}
  </div>`;
}

function setupAmazonToggle(aspects) {
  const btn = document.getElementById('amzToggle');
  const details = document.getElementById('amzDetails');
  if (!btn || !details) return;
  let chartReady = false;
  btn.addEventListener('click', () => {
    const open = details.style.display === 'none';
    details.style.display = open ? 'block' : 'none';
    btn.querySelector('.tg-ico').textContent = open ? '▾' : '▸';
    btn.firstElementChild.lastChild.textContent = open
      ? ' Hide product breakdown' : ' Show product breakdown, aspect chart & customer reviews';
    if (open && !chartReady) { renderAspectChart(aspects); chartReady = true; }    // lazy: size correctly
    else if (open) { window._catCharts.forEach(c => c.canvas.id === 'amzAspectChart' && c.resize()); }
  });
}

function renderAspectChart(aspects) {
  const el = document.getElementById('amzAspectChart');
  if (!el || !aspects || !aspects.length) return;
  const data = aspects.slice(0, 9);
  const chart = new Chart(el.getContext('2d'), {
    type: 'bar',
    data: {
      labels: data.map(a => a.name),
      datasets: [{
        data: data.map(a => a.neg_rate),
        backgroundColor: data.map(a => negColor(a.neg_rate) + 'cc'),
        borderColor: data.map(a => negColor(a.neg_rate)), borderWidth: 1, borderRadius: 4,
      }],
    },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { backgroundColor: cssVar('--c-tip-bg'), borderColor: cssVar('--c-tip-border'), borderWidth: 1,
        callbacks: { label: c => ` ${c.raw}% negative · ${data[c.dataIndex].mentions.toLocaleString()} mentions` } } },
      scales: {
        x: { max: 100, grid: { color: cssVar('--c-grid') }, ticks: { color: cssVar('--c-axis'), font: { size: 10 }, callback: v => v + '%' } },
        y: { grid: { display: false }, ticks: { color: cssVar('--c-axis'), font: { size: 11 } } },
      },
    },
  });
  window._catCharts.push(chart);
}

// ───────────────────────── Google Trends module (real data) ─────────────────────────
const trendCls = l => l === 'rising' ? 't-rising' : l === 'declining' ? 't-declining'
  : l === 'stable' ? 't-stable' : 't-muted';
const pct = x => x == null ? '—' : (x >= 0 ? '+' : '') + Math.round(x * 100) + '%';

function trendsModule(t, fr) {
  if (!t || !t.available) {
    return `<div class="module">
      <div class="module-head"><h3>Google Trends — search interest</h3><span class="src-badge sample">no data yet</span></div>
      <div style="color:var(--text2);font-size:13px">Google Trends data is available for the three seeded categories (Sunscreen / SPF, Moisturizer &amp; Hydration, Cleanser &amp; Oil Control).</div>
    </div>`;
  }
  return `<div class="module">
    <div class="module-head"><h3>Google Trends — search interest</h3><span class="src-badge">${esc(t.source)} · to ${esc(t.latest_date)}</span></div>
    ${window.freshBar ? window.freshBar(fr) : ''}
    <div class="trend-tabs" id="trendCountryTabs">
      ${t.countries.map(c => `<button class="tcountry ${c.code === t.default_country ? 'active' : ''}" data-c="${c.code}">${esc(c.name)}</button>`).join('')}
    </div>
    <div id="trendBody"></div>
  </div>`;
}

function setupTrends(t) {
  if (!t || !t.available) return;
  renderTrendCountry(t, t.default_country);
  document.querySelectorAll('#trendCountryTabs .tcountry').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#trendCountryTabs .tcountry').forEach(b => b.classList.toggle('active', b === btn));
      renderTrendCountry(t, btn.dataset.c);
    });
  });
}

function renderTrendCountry(t, code) {
  const cb = t.by_country[code];
  if (!cb) return;
  const base = cb.baseline || {};
  const subRow = s => `<div class="rising-row">
      <span>${esc(s.keyword)}<span class="trend-badge sm ${trendCls(s.trend_label)}">${esc(s.trend_label)}</span></span>
      <span class="chg ${(s.momentum_3m || 0) < 0 ? 'neg' : ''}">${pct(s.momentum_3m)}</span></div>`;
  const brandRow = b => `<div class="rising-row">
      <span>${esc(b.keyword)}<span class="trend-badge sm ${trendCls(b.trend_label)}">${esc(b.trend_label)}</span></span>
      <span style="color:var(--text2)">avg ${b.avg_score ?? '—'} · <span class="${(b.momentum_3m || 0) < 0 ? 'sent-neg' : 'sent-pos'}">${pct(b.momentum_3m)}</span></span></div>`;

  document.getElementById('trendBody').innerHTML = `
    <div class="trend-summary">
      <span>Category “${esc(base.keyword || '')}” interest in ${esc(cb.country_name)}:</span>
      <span class="trend-badge ${trendCls(base.trend_label)}">${esc(base.trend_label || 'n/a')}</span>
      <span class="trend-metric">3-mo momentum <strong>${pct(base.momentum_3m)}</strong></span>
      <span class="trend-metric">YoY <strong>${pct(base.growth_yoy)}</strong></span>
      <span class="trend-metric">peak <strong>${base.peak_score ?? '—'}</strong>/100</span>
    </div>
    <div class="amz-chart-wrap" style="height:240px"><canvas id="trendsChart"></canvas></div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:16px">
      <div>
        <div class="voc-col-label">Rising sub-categories <span style="font-weight:400;color:var(--text2)">(3-mo momentum)</span></div>
        ${cb.rising_subcategories.length ? cb.rising_subcategories.map(subRow).join('') : '<div style="color:var(--text2);font-size:12px">No sub-category signal.</div>'}
      </div>
      <div>
        <div class="voc-col-label">Brand momentum</div>
        ${cb.brands.map(brandRow).join('')}
      </div>
    </div>`;
  renderTrendChart(cb.series);
}

const TREND_LINE_COLORS = ['#F97316', '#0EA5E9', '#EC4899', '#F59E0B'];
function renderTrendChart(series) {
  const el = document.getElementById('trendsChart');
  if (!el || !series) return;
  if (window._trendChart) { window._trendChart.destroy(); window._trendChart = null; }
  // thin x labels for readability (weekly over 2 years)
  const labels = series.dates.map(d => d.slice(0, 7));
  window._trendChart = new Chart(el.getContext('2d'), {
    type: 'line',
    data: {
      labels,
      datasets: series.lines.map((ln, i) => ({
        label: ln.name + (ln.role === 'category' ? ' (category)' : ''),
        data: ln.values,
        borderColor: TREND_LINE_COLORS[i % TREND_LINE_COLORS.length],
        backgroundColor: ln.role === 'category' ? 'rgba(249,115,22,.12)' : 'transparent',
        fill: ln.role === 'category', borderWidth: ln.role === 'category' ? 2.5 : 1.6,
        tension: 0.3, pointRadius: 0, pointHoverRadius: 3, borderDash: ln.role === 'brand' ? [4, 3] : [],
      })),
    },
    options: {
      responsive: true, maintainAspectRatio: false, spanGaps: true,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { position: 'bottom', labels: { color: cssVar('--c-axis'), boxWidth: 12, font: { size: 10 }, padding: 8 } },
        tooltip: { backgroundColor: cssVar('--c-tip-bg'), borderColor: cssVar('--c-tip-border'), borderWidth: 1,
          callbacks: { label: c => ` ${c.dataset.label}: ${c.raw ?? '–'}/100` } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: cssVar('--c-axis'), font: { size: 9 }, maxTicksLimit: 9, autoSkip: true } },
        y: { max: 100, grid: { color: cssVar('--c-grid') }, ticks: { color: cssVar('--c-axis'), font: { size: 10 } } },
      },
    },
  });
}

// ───────────────────────── Reddit module ─────────────────────────
function redditModule(r) {
  if (!r || !r.posts) return '';
  const sum = r.summary || {};
  const posts = r.posts.map(p => `
    <div class="result-card" style="padding:13px">
      <div class="rc-title" style="font-size:14px">${p.permalink ? `<a href="${esc(p.permalink)}" target="_blank" rel="noopener">${esc(p.title)}</a>` : esc(p.title)}</div>
      <div class="rc-sub">
        <span class="sub-badge">r/${esc(p.subreddit)}</span>
        <span>${p.n_comments}</span>
        <span class="sent-badge ${sentClass(p.post_sentiment_label)}">${p.post_sentiment_label}</span>
        ${p.brands.slice(0, 3).map(b => `<span class="tag brand">${esc(b)}</span>`).join('')}
      </div>
    </div>`).join('');
  return `<div class="module">
    <div class="module-head"><h3>Reddit conversation</h3><span class="src-badge">r/skincare communities · VADER sentiment</span></div>
    <div style="font-size:12px;color:var(--text2);margin-bottom:12px">Overall community mood for this category: <span class="${sentClass(sum.sentiment_label)}">${sum.sentiment_label || 'n/a'}</span> across the matched discussion. Top products mentioned: ${(sum.top_products || []).slice(0, 4).map(p => esc(p.name)).join(', ') || '—'}.</div>
    ${posts}
  </div>`;
}
