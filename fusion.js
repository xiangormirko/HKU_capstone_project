// ════════════════════════════════════════════════════════════════
// Product Scout — Source-to-Sell (Trade × Social fusion)
// Links social brand demand/sentiment to country trade flows.
// ════════════════════════════════════════════════════════════════

window.fusionLoaded = false;

const ANGLE_CLS = { "Unmet need": "whitespace", "Room to differentiate": "differentiate", "Validated demand": "validated" };
// esc() and sb() are shared helpers from util.js (loaded first).

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
    html += `<div class="fusion-headline"><span class="hl-ico"></span><div>${d.headline}</div></div>`;
  }

  // two columns: source | sell
  html += `<div class="fusion-cols"><div>
    <div class="section-title"><div class="dot" style="background:var(--accent)"></div> Where to SOURCE — origins shoppers love</div>`;
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
    <div class="section-title"><div class="dot" style="background:var(--accent)"></div> Where to SELL — unmet-demand markets</div>`;
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
  html += `<div style="font-size:11px;color:var(--text2);margin:-4px 0 12px;line-height:1.5">Each route fuses up to five signals — Reddit demand, Amazon review pain points, Google Trends momentum, UN Comtrade trade and Statista skin-type sizing.</div>`;
  html += (d.category_opportunities || []).map(c => {
    const sellChips = (c.sell_to || []).map(s => {
      if (s.momentum_3m != null) {
        const up = s.momentum_3m >= 0;
        return `<span class="chip-sm">${esc(s.country)} <span class="${up ? 'sent-pos' : 'sent-neg'}">${up ? '↑' : '↓'}${Math.abs(s.momentum_3m).toFixed(0)}</span></span>`;
      }
      return `<span class="chip-sm">${esc(s.country)} · ${sb(s.net_import_b)}</span>`;
    }).join('') || '<span style="color:var(--text2);font-size:11px">—</span>';

    // unmet need (Amazon review pain point) = the product gap to solve
    let need = '';
    if (c.unmet_need) {
      const p = c.unmet_need;
      need = `<div class="route-need">
        <span class="need-ico">◎</span>
        <div><span class="need-lbl">Product gap to solve</span>
          <strong>${esc(p.name)}</strong> — ${p.neg_rate.toFixed(0)}% of Amazon reviews complain (${p.mentions.toLocaleString()} mentions)
          ${c.complaint ? `<div class="need-quote">“${esc(c.complaint)}”${c.complaint_brand ? ` <span style="opacity:.7">— on ${esc(c.complaint_brand)}</span>` : ''}</div>` : ''}
          ${c.best_in_class ? `
            <div class="need-bm">
              Benchmark to beat: <strong>${esc(c.best_in_class.brand || 'Unknown')}</strong> 
              (${c.best_in_class.avg_rating || 0}★, 
              (${(c.best_in_class.total_ratings ?? 0).toLocaleString()} ratings)
            </div>
          ` : ''}
        </div></div>`;
    }

    // meta chips: addressable segment + emerging formats + markets to avoid
    const metaChips = [];
    if (c.addressable_segment) metaChips.push(`<span class="chip-meta">Segment: ${esc(c.addressable_segment.skin_type)} skin ~${c.addressable_segment.pct}%</span>`);
    (c.emerging_formats || []).slice(0, 2).forEach(f => metaChips.push(`<span class="chip-meta accent">Rising format: ${esc(f.format)}</span>`));
    if (c.declining_markets && c.declining_markets.length) metaChips.push(`<span class="chip-meta warn">Avoid (declining): ${c.declining_markets.slice(0, 3).map(esc).join(', ')}</span>`);

    return `
    <div class="route-card">
      <div class="route-head">
        <h4>${esc(c.category)}</h4>
        <span class="tag-angle ${ANGLE_CLS[c.angle] || 'differentiate'}">${esc(c.angle)}</span>
        ${c.n_signals ? `<span class="chip-meta">${c.n_signals} signals aligned</span>` : ''}
        <span style="font-size:11px;color:var(--text2)">${c.n_posts} conversations · <span class="${sentClass(c.sentiment_label)}">${c.sentiment_label}</span></span>
      </div>
      ${need}
      <div class="route-flow">
        <div class="route-box">
          <div class="rb-label">Source from</div>
          ${c.source_from.map(o => `<span class="chip-sm">${esc(o.origin)}${o.export_rank ? ' · #' + o.export_rank : ''}</span>`).join('') || '<span style="color:var(--text2);font-size:11px">—</span>'}
        </div>
        <div class="route-arrow">→</div>
        <div class="route-box">
          <div class="rb-label">Sell to <span style="font-weight:400;opacity:.7">· ${esc(c.sell_basis || '')}</span></div>
          ${sellChips}
        </div>
      </div>
      ${metaChips.length ? `<div class="route-meta">${metaChips.join('')}</div>` : ''}
    </div>`;
  }).join('');

  // emerging formats — cross-market new-product whitespace
  const ef = d.emerging_formats || [];
  if (ef.length) {
    html += `<div class="section-title" style="margin-top:26px"><div class="dot" style="background:var(--accent)"></div> Emerging formats — new-product whitespace</div>`;
    html += `<div style="font-size:11px;color:var(--text2);margin:-4px 0 12px;line-height:1.5">Sub-categories whose search interest is rising across multiple markets at once — the literal new-product backlog, ranked by breadth and momentum.</div>`;
    html += `<div class="ef-grid">` + ef.map(f => `
      <div class="ef-card">
        <div class="ef-top"><strong>${esc(f.format)}</strong><span class="chip-meta accent">↑${f.avg_momentum.toFixed(0)}</span></div>
        <div class="ef-sub">${esc(f.category)}</div>
        <div class="ef-markets">Rising in ${f.n_markets} market${f.n_markets === 1 ? '' : 's'}: ${f.markets_rising.slice(0, 4).map(esc).join(', ')}${f.markets_rising.length > 4 ? '…' : ''}</div>
        ${f.pain_point ? `<div class="ef-need">Pairs with gap: ${esc(f.pain_point.name || 'Unknown')} (${(f.pain_point.neg_rate ?? 0).toFixed(0)}% neg)</div>` : ''}
      </div>`).join('') + `</div>`;
  }

  // provenance note
  if (d.meta && d.meta.note) {
    html += `<div style="font-size:11px;color:var(--text2);margin-top:18px;padding:12px;background:var(--surface);border:1px solid var(--border);border-radius:9px;line-height:1.5">
      <strong>How this is built:</strong> ${esc(d.meta.note)}</div>`;
  }

  document.getElementById('fusionContent').innerHTML = html;
}
