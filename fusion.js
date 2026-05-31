// ════════════════════════════════════════════════════════════════
// Product Scout — Source-to-Sell (Trade × Social fusion)
// Links social brand demand/sentiment to country trade flows.
// ════════════════════════════════════════════════════════════════

window.fusionLoaded = false;

const ANGLE_CLS = { "Unmet need": "whitespace", "Room to differentiate": "differentiate", "Validated demand": "validated" };
const sb = v => (v == null ? "n/a" : "$" + Number(v).toFixed(1) + "B");

window.loadFusion = async function loadFusion() {
  window.fusionLoaded = true;
  let data;
  try {
    data = await fetch('/api/fusion').then(r => r.json());
  } catch (e) {
    document.getElementById('fusionContent').innerHTML =
      `<div style="color:var(--negative)">Failed to load fusion: ${esc(String(e))}</div>`;
    return;
  }
  renderFusion(data);
};

function renderFusion(d) {
  const origins = d.sourcing_origins || [];
  const markets = d.sell_to_markets || [];
  const maxMent = Math.max(...origins.map(o => o.social_mentions), 1);

  // headline
  let html = '';
  if (d.headline) {
    html += `<div class="fusion-headline"><span class="hl-ico">🎯</span><div>${esc(d.headline)}</div></div>`;
  }

  // two columns: source | sell
  html += `<div class="fusion-cols"><div>
    <div class="section-title"><div class="dot" style="background:var(--accent3)"></div> Where to SOURCE — origins shoppers love</div>`;
  html += origins.map(o => {
    const ex = o.export_b != null ? `${sb(o.export_b)}${o.export_rank ? ' · #' + o.export_rank + ' exporter' : ''}` : 'n/a';
    const cagr = o.export_cagr != null ? `${o.export_cagr >= 0 ? '+' : ''}${o.export_cagr.toFixed(1)}%/yr` : '';
    return `
      <div class="origin-card">
        <div class="oc-head">
          <div><span class="oc-name">${esc(o.origin)}</span> <span class="oc-tag">${esc(o.tagline)}</span></div>
          <span class="oc-signal">${esc(o.signal)}</span>
        </div>
        <div class="oc-stats">
          <div class="oc-stat"><div class="v">${o.social_mentions.toLocaleString()}</div><div class="l">social mentions</div></div>
          <div class="oc-stat"><div class="v ${sentClass(o.sentiment_label)}">${o.avg_sentiment >= 0 ? '+' : ''}${o.avg_sentiment.toFixed(2)}</div><div class="l">sentiment</div></div>
          <div class="oc-stat"><div class="v">${ex}</div><div class="l">exports ${cagr}</div></div>
        </div>
        <div class="bar-track"><div class="bar-fill" style="width:${(o.social_mentions / maxMent * 100).toFixed(0)}%"></div></div>
        <div class="oc-brands" style="margin-top:8px">Brands: ${o.top_brands.map(b => esc(b.name)).join(', ')}</div>
      </div>`;
  }).join('');

  html += `</div><div>
    <div class="section-title"><div class="dot" style="background:var(--accent4)"></div> Where to SELL — unmet-demand markets</div>`;
  html += markets.map(m => `
    <div class="market-row">
      <div>
        <div class="mr-name">${esc(m.country)}</div>
        <div class="mr-sub">imports ${sb(m.import_b)} · makes ${sb(m.export_b)}</div>
      </div>
      <div>
        <div class="mr-net">${sb(m.net_import_b)}</div>
        <div class="mr-yoy ${m.import_yoy == null ? '' : (m.import_yoy >= 0 ? 'sent-pos' : 'sent-neg')}" style="text-align:right">
          net imports ${m.import_yoy == null ? '' : (m.import_yoy >= 0 ? '↑' : '↓') + Math.abs(m.import_yoy).toFixed(0) + '%'}</div>
      </div>
    </div>`).join('');
  html += `<div style="font-size:11px;color:var(--text2);margin-top:8px;line-height:1.5">Net imports = cosmetics a country buys minus what it makes — a proxy for demand local supply can't meet.</div>`;
  html += `</div></div>`;

  // category source→sell routes
  html += `<div class="section-title" style="margin-top:26px"><div class="dot" style="background:var(--accent)"></div> Source → Sell routes by category</div>`;
  html += (d.category_opportunities || []).map(c => `
    <div class="route-card">
      <div class="route-head">
        <h4>${esc(c.category)}</h4>
        <span class="tag-angle ${ANGLE_CLS[c.angle] || 'differentiate'}">${esc(c.angle)}</span>
        <span style="font-size:11px;color:var(--text2)">${c.n_posts} conversations · <span class="${sentClass(c.sentiment_label)}">${c.sentiment_label}</span></span>
      </div>
      <div class="route-flow">
        <div class="route-box">
          <div class="rb-label">🏭 Source from</div>
          ${c.source_from.map(o => `<span class="chip-sm">${esc(o.origin)}${o.export_rank ? ' · #' + o.export_rank : ''}</span>`).join('') || '<span style="color:var(--text2);font-size:11px">—</span>'}
        </div>
        <div class="route-arrow">→</div>
        <div class="route-box">
          <div class="rb-label">🛒 Sell to</div>
          ${c.sell_to.map(s => `<span class="chip-sm">${esc(s.country)} · ${sb(s.net_import_b)}</span>`).join('')}
        </div>
      </div>
    </div>`).join('');

  // provenance note
  if (d.meta && d.meta.note) {
    html += `<div style="font-size:11px;color:var(--text2);margin-top:18px;padding:12px;background:var(--surface);border:1px solid var(--border);border-radius:9px;line-height:1.5">
      <strong>How this is built:</strong> ${esc(d.meta.note)}</div>`;
  }

  document.getElementById('fusionContent').innerHTML = html;
}
