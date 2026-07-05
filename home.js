// ════════════════════════════════════════════════════════════════
// Product Scout — Home / landing dashboard
// Blue-ocean whitespace (Google Trends) + consumer pain points (Amazon),
// served live from /api/home (recomputed on every data ingest), plus an
// embedded AI chat wired to the real Claude agent at /api/chat.
// ════════════════════════════════════════════════════════════════

let homeLoaded = false;

const hEsc = s => { const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; };
const hStrip = s => { const d = document.createElement('div'); d.innerHTML = s; return d.textContent; };

// ───────────────────────── load + render ─────────────────────────
async function loadHome() {
  homeLoaded = true;
  let d;
  try {
    d = await fetch('/api/home').then(r => r.json());
  } catch (e) {
    document.getElementById('blueList').innerHTML =
      `<div class="hp-empty" style="color:var(--negative)">Failed to load: ${hEsc(String(e))}</div>`;
    return;
  }
  renderHome(d);
}
window.refreshHome = function () { homeLoaded = false; loadHome(); };

function renderHome(d) {
  const blue = d.blue_ocean || [];
  const pain = d.pain_points || [];

  // AI brief
  if (d.brief) {
    document.getElementById('homeBrief').style.display = 'flex';
    document.getElementById('homeBriefText').innerHTML = d.brief;  // server-built, trusted
  }

  // freshness bars (amazon + trends)
  const fr = d.freshness || {};
  const bars = ['trends', 'amazon'].map(k => (fr[k] && window.freshBar) ? window.freshBar(fr[k]) : '').join('');
  document.getElementById('homeFresh').innerHTML = bars;

  // lists
  document.getElementById('blueCount').textContent =
    blue.length ? `${blue.length} opportunit${blue.length === 1 ? 'y' : 'ies'}` : 'none yet';
  document.getElementById('redCount').textContent =
    pain.length ? `${pain.length} issue${pain.length === 1 ? '' : 's'}` : 'none yet';

  document.getElementById('blueList').innerHTML = blue.length
    ? blue.map((x, i) => itemHTML(x, i, 'blue')).join('')
    : `<div class="hp-empty">No rising whitespace detected yet — connect Google Trends data to populate.</div>`;
  document.getElementById('redList').innerHTML = pain.length
    ? pain.map((x, i) => itemHTML(x, i, 'red')).join('')
    : `<div class="hp-empty">No pain points yet — ingest review data to populate.</div>`;

  // wire the per-item "Ask AI" buttons
  document.querySelectorAll('#blueList .hp-ask, #redList .hp-ask').forEach(b =>
    b.addEventListener('click', () => {
      const q = b.dataset.q;
      hcSwitchToChat();
      hcSend(q);
    }));

  // data-driven chat suggestions
  const sugg = [];
  if (blue[0]) sugg.push(`Give me a launch brief for "${blue[0].title}"`);
  if (pain[0]) sugg.push(`How do I solve the "${pain[0].title}" pain point?`);
  sugg.push("What's the single biggest opportunity right now?");
  document.getElementById('hcSuggest').innerHTML =
    sugg.map(s => `<button class="hc-chip">${hEsc(s)}</button>`).join('');
  document.querySelectorAll('#hcSuggest .hc-chip').forEach(c =>
    c.addEventListener('click', () => hcSend(c.textContent)));

  if (d.meta && d.meta.note)
    document.getElementById('homeNote').innerHTML = `<strong>How this is built:</strong> ${hEsc(d.meta.note)}`;
}

function itemHTML(x, i, cls) {
  const ask = cls === 'blue'
    ? `Give me a launch brief for "${x.title}" — a rising blue-ocean opportunity in ${x.category}.`
    : `How can a new product solve the "${x.title}" pain point? What do consumers complain about and how do I differentiate?`;
  return `
    <div class="hp-item ${i === 0 ? 'r1' : ''}">
      <div class="hp-rank">${i + 1}</div>
      <div class="hp-body">
        <div class="hp-name">${hEsc(x.title)}</div>
        <div class="hp-meta">${hEsc(x.meta)}</div>
        <button class="hp-ask" data-q="${hEsc(ask)}">Ask AI →</button>
      </div>
      <div class="hp-metric">
        <div class="hp-val ${cls}">${hEsc(x.metric)}</div>
        <span class="hp-tag">${hEsc(x.label)}</span>
      </div>
    </div>`;
}

// ───────────────────────── embedded chat ─────────────────────────
const homeChatHistory = [];

function hcAdd(role, html) {
  const box = document.getElementById('hcMessages');
  const div = document.createElement('div');
  div.className = `hc-msg ${role}`;
  div.innerHTML = `<div class="hc-avatar">${role === 'user' ? 'You' : 'PS'}</div><div class="hc-bubble">${html}</div>`;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
  return div;
}
function hcTyping() {
  const box = document.getElementById('hcMessages');
  const div = document.createElement('div');
  div.className = 'hc-msg ai';
  div.id = 'hcTyping';
  div.innerHTML = `<div class="hc-avatar">PS</div><div class="hc-bubble"><div class="hc-typing"><span></span><span></span><span></span></div></div>`;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}
function hcRemoveTyping() { const t = document.getElementById('hcTyping'); if (t) t.remove(); }

function hcSwitchToChat() {
  document.querySelector('.home-chat').scrollIntoView({ behavior: 'smooth', block: 'center' });
}

async function hcSend(text) {
  text = (text || '').trim();
  if (!text) return;
  const sendBtn = document.getElementById('hcSend');
  document.getElementById('hcSuggest').style.display = 'none';
  hcAdd('user', hEsc(text));
  homeChatHistory.push({ role: 'user', content: text });
  sendBtn.disabled = true;
  hcTyping();
  try {
    const res = await fetch('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: homeChatHistory }),
    });
    const data = await res.json();
    hcRemoveTyping();
    const reply = data.reply || 'No response.';
    const el = hcAdd('ai', reply);
    if (data.tools_used && data.tools_used.length) {
      const names = [...new Set(data.tools_used.map(t => t.tool))].join(', ');
      const note = document.createElement('div');
      note.className = 'tool-note';
      note.textContent = '⚙ queried: ' + names;
      el.querySelector('.hc-bubble').appendChild(note);
    }
    if (!data.needs_key && !data.error) homeChatHistory.push({ role: 'assistant', content: hStrip(reply) });
    else homeChatHistory.pop();
  } catch (e) {
    hcRemoveTyping();
    hcAdd('ai', '<strong>Connection error.</strong> Is the server running? ' + hEsc(String(e)));
    homeChatHistory.pop();
  }
  sendBtn.disabled = false;
}

// ───────────────────────── wiring ─────────────────────────
document.getElementById('hcSend').addEventListener('click', () => {
  const input = document.getElementById('hcInput');
  const q = input.value.trim();
  if (!q) return;
  input.value = ''; input.style.height = 'auto';
  hcSend(q);
});
document.getElementById('hcInput').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); document.getElementById('hcSend').click(); }
});
document.getElementById('hcInput').addEventListener('input', e => {
  e.target.style.height = 'auto';
  e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px';
});

// lazy-load when the Home tab is (re)selected
document.querySelectorAll('.nav-item[data-view="home"]').forEach(btn =>
  btn.addEventListener('click', () => { if (!homeLoaded) loadHome(); }));

// Home is the default landing view — load immediately
loadHome();
