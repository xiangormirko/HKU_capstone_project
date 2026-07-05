// ════════════════════════════════════════════════════════════════
// Product Scout — shared frontend helpers
// Loaded before every other view script so they can share one set of
// utilities (HTML escaping, sentiment classes, money formatting, and the
// Claude chat call) instead of each file redefining its own copy.
// ════════════════════════════════════════════════════════════════

// HTML-escape a value for safe insertion into innerHTML.
function esc(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : s;
  return d.innerHTML;
}

// Strip tags from an HTML string, returning its text content.
function stripHtml(s) {
  const d = document.createElement('div');
  d.innerHTML = s == null ? '' : s;
  return d.textContent;
}

// Map a sentiment label ("very positive" … "very negative") to a CSS class.
function sentClass(label) {
  const l = label || '';
  return l.includes('positive') ? 'sent-pos' : l.includes('negative') ? 'sent-neg' : 'sent-neu';
}

// Money formatters in $billions. fmtB = 2 dp (tables), sb = 1 dp (compact chips).
function fmtB(v) { return v == null ? 'N/A' : '$' + Number(v).toFixed(2) + 'B'; }
function sb(v) { return v == null ? 'n/a' : '$' + Number(v).toFixed(1) + 'B'; }

// Single entry point to the Claude agent. Returns the parsed JSON response
// ({ reply, tools_used, needs_key, error }). Callers own their own DOM rendering.
async function postChat(history) {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages: history }),
  });
  return res.json();
}
