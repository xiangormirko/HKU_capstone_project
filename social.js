// ════════════════════════════════════════════════════════════════
// Product Scout — Social Discovery view
// Talks to /api/social/* (Reddit now; Google Trends / others later).
// ════════════════════════════════════════════════════════════════

const sentClass = label =>
  (label || '').includes('positive') ? 'sent-pos' :
  (label || '').includes('negative') ? 'sent-neg' : 'sent-neu';

const esc = s => { const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; };

let SOCIAL_OV = null;
let socialLoaded = false;

// ───────────────────────── view switching ─────────────────────────
document.querySelectorAll('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => {
    const view = btn.dataset.view;
    document.querySelectorAll('.nav-item').forEach(b => b.classList.toggle('active', b === btn));
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.getElementById('view-' + view).classList.add('active');
    // year/HS controls only belong to the Trade view
    document.getElementById('tradeControls').style.display = view === 'trade' ? 'flex' : 'none';
    if (view === 'trade') {
      window.dispatchEvent(new Event('resize'));   // refit the map
    } else if (view === 'social' && !socialLoaded) {
      loadSocialOverview();
    } else if (view === 'fusion' && window.loadFusion && !window.fusionLoaded) {
      window.loadFusion();
    }
  });
});

// ───────────────────────── overview ─────────────────────────
async function loadSocialOverview() {
  socialLoaded = true;
  try {
    SOCIAL_OV = await fetch('/api/social/overview').then(r => r.json());
  } catch (e) { console.error(e); return; }
  // example chips
  document.getElementById('exampleChips').innerHTML =
    SOCIAL_OV.example_queries.map(q => `<div class="chip" data-q="${esc(q)}">${esc(q)}</div>`).join('');
  document.querySelectorAll('#exampleChips .chip').forEach(c =>
    c.addEventListener('click', () => runSearch(c.dataset.q)));

  renderOverview();
}

function pill(name, label, cls) {
  return `<span class="product-pill"><span class="dot ${sentClass(label)}"></span>${esc(name)}
            <span class="${sentClass(label)}" style="font-size:10px">${label && label !== 'n/a' ? label : ''}</span></span>`;
}

const ANGLE_CLASS = { "Unmet need": "whitespace", "Room to differentiate": "differentiate", "Validated demand": "validated" };

function renderInsights(ins) {
  if (!ins || !ins.opportunities || !ins.opportunities.length) return '';
  const h = ins.headline;
  const cards = ins.opportunities.map(o => `
    <div class="opp-launch">
      <span class="tag-angle ${ANGLE_CLASS[o.angle] || 'differentiate'}">${esc(o.angle)}</span>
      <h4>${esc(o.category)}</h4>
      <div class="meta">${o.n_posts} conversations</div>
      <div class="why">${esc(o.rationale)}</div>
      <div class="incumbents">Incumbents to beat: <strong>${o.incumbents.map(esc).join(', ') || '—'}</strong></div>
      <button class="cta-btn" data-q="${esc(o.category)}">Explore demand →</button>
    </div>`).join('');
  return `
    <div class="insights-panel">
      <div class="insights-head">
        <div>
          <h3>Launch Opportunities</h3>
          <p>Trending categories ranked by conversation volume and unmet need — where social demand signals a clear opening to launch new products.</p>
        </div>
        <div class="insights-stats">
          <div class="stat"><div class="v">${(h.n_posts || 0).toLocaleString()}</div><div class="l">posts analyzed</div></div>
          <div class="stat"><div class="v">${h.n_categories || 0}</div><div class="l">categories</div></div>
        </div>
      </div>
      <div class="opp-cards">${cards}</div>
    </div>`;
}

function renderOverview() {
  const ov = SOCIAL_OV;
  const card = c => `
    <div class="ov-card" data-q="${esc(c.category)}">
      <h4>${esc(c.category)}</h4>
      <div class="ov-meta">
        <span>${c.n_posts} posts</span>
      </div>
    </div>`;
  const TOP_N = 8;
  const topCards = ov.categories.slice(0, TOP_N).map(card).join('');
  const restCount = Math.max(0, ov.categories.length - TOP_N);
  const restCards = ov.categories.slice(TOP_N).map(card).join('');
  const catCards = `<div class="ov-grid">${topCards}</div>` + (restCount ? `
    <div class="ov-grid" id="ovGridRest" style="display:none;margin-top:14px">${restCards}</div>
    <button class="home-btn" id="ovMoreBtn" style="margin-top:14px">▸ Show ${restCount} more categories</button>` : '');

  document.getElementById('socialOverview').innerHTML = `
    <div class="section-title" style="margin-top:8px"><div class="dot" style="background:var(--accent)"></div> Browse by product category <span style="font-size:11px;color:var(--text2);font-weight:400">— click a category for Amazon reviews & search trends</span></div>
    ${catCards}

    ${renderInsights(ov.insights)}

    <div class="section-title" style="margin-top:28px"><div class="dot" style="background:var(--accent)"></div> Most-discussed products</div>
    <div class="ent-list">${ov.top_brands.map(b => pill(b.entity, label(b.avg_sentiment))).join('')}</div>

    <div class="section-title" style="margin-top:24px"><div class="dot" style="background:var(--accent)"></div> Trending ingredients</div>
    <div class="ent-list">${ov.top_ingredients.map(i => pill(i.entity, label(i.avg_sentiment))).join('')}</div>`;

  // category cards & launch-opportunity CTAs open the category detail page;
  // free-text pills/chips still run a search.
  document.querySelectorAll('#socialOverview .ov-card, #socialOverview .cta-btn').forEach(c =>
    c.addEventListener('click', () => window.openCategory ? window.openCategory(c.dataset.q) : runSearch(c.dataset.q)));

  // show more / fewer categories
  const moreBtn = document.getElementById('ovMoreBtn');
  if (moreBtn) {
    const rest = document.getElementById('ovGridRest');
    const n = rest.querySelectorAll('.ov-card').length;
    moreBtn.addEventListener('click', () => {
      const open = rest.style.display === 'none';
      rest.style.display = open ? 'grid' : 'none';
      moreBtn.textContent = open ? '▾ Show fewer categories' : `▸ Show ${n} more categories`;
    });
  }
}

// return to the categories home view
function goHome() {
  document.getElementById('socialSearch').value = '';
  document.getElementById('socialResults').innerHTML = '';
  const cat = document.getElementById('socialCategory');
  if (cat) { cat.style.display = 'none'; cat.innerHTML = ''; }
  const ss = document.getElementById('socialSearchSection');   // restore title + search
  if (ss) ss.style.display = '';
  document.getElementById('socialOverview').style.display = 'block';
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
window.goHome = goHome;

// client-side sentiment label (mirror of server thresholds) for overview numbers
function label(v) {
  if (v == null) return 'n/a';
  if (v >= 0.4) return 'very positive';
  if (v >= 0.1) return 'positive';
  if (v > -0.1) return 'neutral';
  if (v > -0.4) return 'negative';
  return 'very negative';
}

// ───────────────────────── search ─────────────────────────
async function runSearch(q) {
  const input = document.getElementById('socialSearch');
  input.value = q;
  const resBox = document.getElementById('socialResults');
  const ovBox = document.getElementById('socialOverview');
  resBox.innerHTML = `<div style="text-align:center;color:var(--text2);padding:30px">Analyzing posts for “${esc(q)}”…</div>`;
  ovBox.style.display = 'none';
  let data;
  try {
    data = await fetch('/api/social/search?q=' + encodeURIComponent(q) + '&limit=25').then(r => r.json());
  } catch (e) { resBox.innerHTML = `<div style="color:var(--negative)">Search failed: ${esc(String(e))}</div>`; return; }
  renderResults(data);
}

function tagRow(p) {
  const t = [];
  p.categories.slice(0, 4).forEach(c => t.push(`<span class="tag cat">${esc(c)}</span>`));
  p.brands.slice(0, 4).forEach(b => t.push(`<span class="tag brand">${esc(b)}</span>`));
  p.ingredients.slice(0, 4).forEach(i => t.push(`<span class="tag ing">${esc(i)}</span>`));
  return t.join('');
}

function sentBadge(val, label, prefix) {
  if (val == null) return '';
  return `<span class="sent-badge ${sentClass(label)}">${prefix} ${label} (${val >= 0 ? '+' : ''}${val.toFixed(2)})</span>`;
}

function renderResults(data) {
  const s = data.summary;
  const resolvedBits = Object.entries(data.resolved).flatMap(([t, names]) =>
    names.map(n => `<span class="tag ${t === 'category' ? 'cat' : t === 'brand' ? 'brand' : 'ing'}">${esc(n)}</span>`)).join(' ');

  const backBtn = `<button class="home-btn" id="socialBackBtn">← Back to categories</button>`;

  let html = backBtn;
  if (!data.results.length) {
    html += `<div class="result-card">No posts matched “${esc(data.query)}”. Try a broader term like “acne” or “moisturizer”.</div>`;
    const box = document.getElementById('socialResults');
    box.innerHTML = html;
    box.querySelector('#socialBackBtn').addEventListener('click', goHome);
    return;
  }

  // summary strip
  html += `
    <div class="summary-strip">
      <div>
        <div class="blk-label">Overall sentiment</div>
        <div class="big-sent ${sentClass(s.sentiment_label)}">${s.avg_sentiment >= 0 ? '+' : ''}${(s.avg_sentiment ?? 0).toFixed(2)}</div>
        <div class="${sentClass(s.sentiment_label)}" style="font-size:12px">${s.sentiment_label} · ${s.n_results} posts${resolvedBits ? ' · matched ' + resolvedBits : ''}</div>
      </div>
      <div>
        <div class="blk-label">Top products mentioned</div>
        <div>${s.top_products.length ? s.top_products.map(p => pill(`${p.name} ·${p.mentions_in_results}`, p.sentiment_label)).join('') : '<span style="color:var(--text2);font-size:12px">none detected</span>'}</div>
      </div>
      <div>
        <div class="blk-label">Top ingredients mentioned</div>
        <div>${s.top_ingredients.length ? s.top_ingredients.map(p => pill(`${p.name} ·${p.mentions_in_results}`, p.sentiment_label)).join('') : '<span style="color:var(--text2);font-size:12px">none detected</span>'}</div>
      </div>
    </div>
    <div class="section-title"><div class="dot" style="background:var(--accent)"></div> ${data.results.length} relevant posts</div>`;

  // result cards
  html += data.results.map(p => {
    const link = p.permalink ? `<a href="${esc(p.permalink)}" target="_blank" rel="noopener">${esc(p.title)}</a>` : esc(p.title);
    const comment = p.top_comment ? `
      <div class="rc-comment">“${esc(p.top_comment.body)}”
        <div class="cm-meta">▲ ${p.top_comment.ups} · <span class="${sentClass(p.top_comment.label)}">${p.top_comment.label}</span></div>
      </div>` : '';
    return `
      <div class="result-card">
        <div class="rc-head">
          <div>
            <div class="rc-title">${link}</div>
            <div class="rc-sub">
              <span class="sub-badge">r/${esc(p.subreddit)}</span>
              <span>${p.n_comments} comments</span>
              ${sentBadge(p.post_sentiment, p.post_sentiment_label, 'post:')}
              ${sentBadge(p.discussion_sentiment, p.discussion_label, 'discussion:')}
            </div>
          </div>
        </div>
        ${p.snippet ? `<div class="rc-snippet">${esc(p.snippet)}</div>` : ''}
        <div class="rc-tags">${tagRow(p)}</div>
        ${comment}
      </div>`;
  }).join('');

  const box = document.getElementById('socialResults');
  box.innerHTML = html;
  box.querySelector('#socialBackBtn').addEventListener('click', goHome);
}

// reset to overview when search cleared
document.getElementById('socialSearchBtn').addEventListener('click', () => {
  const q = document.getElementById('socialSearch').value.trim();
  if (q) runSearch(q);
});
document.getElementById('socialSearch').addEventListener('keydown', e => {
  if (e.key === 'Enter') { const q = e.target.value.trim(); if (q) runSearch(q); }
  if (e.key === 'Escape') {
    e.target.value = '';
    document.getElementById('socialResults').innerHTML = '';
    document.getElementById('socialOverview').style.display = 'block';
  }
});
