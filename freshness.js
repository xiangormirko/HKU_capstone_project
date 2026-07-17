// ════════════════════════════════════════════════════════════════
// Product Scout — data freshness UI (last-fetched + ETA + on-demand refresh)
// Reads /api/freshness, triggers /api/refresh, shows "Updated X ago · next
// refresh in Y" and a live ETA countdown while a fetch runs.
// ════════════════════════════════════════════════════════════════

function fmtAgo(s) {
  if (s == null) return 'unknown';
  s = Math.round(s);
  if (s < 60) return 'just now';
  const m = s / 60; if (m < 60) return Math.round(m) + ' min ago';
  const h = m / 60; if (h < 24) return Math.round(h) + ' hr ago';
  const d = Math.round(h / 24); return d + (d === 1 ? ' day ago' : ' days ago');
}
function fmtDur(s) {
  if (s == null) return '?';
  s = Math.round(s);
  if (s < 90) return '~' + s + 's';
  const m = s / 60; if (m < 90) return '~' + Math.round(m) + ' min';
  return '~' + Math.round(m / 60) + ' hr';
}

// Renders the freshness row for a source-status object (from /api/freshness)
window.freshBar = function (fr) {
  if (!fr) return '';
  const age = fmtAgo(fr.last_fetched_age_s);
  const next = fr.due_now ? 'refresh due' : ('next refresh ' + fmtDur(fr.next_due_in_s));
  return `<div class="fresh-bar" data-fsrc="${fr.source}">
    <span class="fresh-dot ${fr.due_now ? 'due' : ''}"></span>
    <span class="fresh-txt">Updated <strong>${age}</strong> · ${next}</span>
    <button class="fresh-btn" data-refresh="${fr.source}">Fetch latest</button>
    <span class="fresh-status"></span>
  </div>`;
};

// Delegated handler so it works for dynamically rendered modules
document.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-refresh]');
  if (btn) startRefresh(btn.dataset.refresh, btn.closest('.fresh-bar'), btn);
});

async function startRefresh(source, bar, btn) {
  if (!bar) return;
  const status = bar.querySelector('.fresh-status');
  btn.disabled = true;
  status.textContent = ' · starting…';
  let resp;
  try {
    resp = await fetch('/api/refresh', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source }),
    }).then(r => r.json());
  } catch (e) { status.textContent = ' · error'; btn.disabled = false; return; }

  const eta = resp.eta_remaining_s || resp.est_refresh_s || 30;
  const t0 = Date.now();

  const tick = async () => {
    let fr;
    try { fr = (await fetch('/api/freshness').then(r => r.json())).sources.find(s => s.source === source); }
    catch (e) { /* keep polling */ }
    if (fr && !fr.running) { done(fr); return; }
    const left = Math.max(1, Math.round(eta - (Date.now() - t0) / 1000));
    status.textContent = ' · fetching… ' + fmtDur(left) + ' left';
    setTimeout(tick, 1500);
  };

  function done(fr) {
    btn.disabled = false;
    const txt = bar.querySelector('.fresh-txt');
    if (fr.last_status === 'refreshed') {
      status.textContent = ' · updated';
      if (txt) txt.innerHTML = 'Updated <strong>just now</strong>';
      // reload the open category page so the new data shows
      if (window._currentCategory && window.openCategory) setTimeout(() => window.openCategory(window._currentCategory), 600);
      else if (typeof window.refreshSocialOverview === 'function') window.refreshSocialOverview();
    } else {
      if (txt) txt.innerHTML = 'Updated <strong>' + fmtAgo(fr.last_fetched_age_s) + '</strong>';
      const label = fr.last_status === 'credentials_required' ? 'live fetch needs API token'
        : fr.last_status === 'scheduled_only' ? 'runs on the weekly scheduler'
        : fr.last_status === 'reprocessed' ? 'reprocessed'
        : fr.last_status;
      status.textContent = ' · ' + label;
      if (fr.note) bar.title = fr.note;
    }
  }
  setTimeout(tick, 800);
}
