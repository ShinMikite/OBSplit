// Shared helpers for all panels.
const $ = (s, el = document) => el.querySelector(s);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

async function api(path, body, opts = {}) {
  const init = body === undefined ? {} : {
    method: 'POST', headers: { 'X-Panel': '1', 'Content-Type': opts.type || 'application/json' },
    body: opts.raw ? body : JSON.stringify(body),
  };
  const r = await fetch(path, init);
  let d = {};
  try { d = await r.json(); } catch (e) { }
  if (!r.ok || d.error) throw new Error(d.error || ('HTTP ' + r.status));
  return d;
}

let toastTimer;
function toast(msg, err) {
  let t = $('#toast');
  if (!t) { t = el('div'); t.id = 'toast'; document.body.appendChild(t); }
  t.textContent = msg; t.className = err ? 'err' : ''; t.style.display = 'block';
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.style.display = 'none', err ? 6000 : 2500);
}

// Live connection to the helper over a WebSocket. (Not EventSource: OBS's panels share one browser, which
// allows only 6 ordinary connections per address; long-lived ones would use them up and make clicks wait.)
// onEvent(ev) gets every event; onDown() runs when the connection drops; it reconnects by itself.
function liveSocket(path, onEvent, onDown) {
  const open = () => {
    const ws = new WebSocket('ws://' + location.host + path);
    ws.onmessage = m => { try { onEvent(JSON.parse(m.data)); } catch (e) { console.error(e); } };
    ws.onclose = () => { if (onDown) onDown(); setTimeout(open, 1000); };
  };
  open();
}
function connect(onEvent) { liveSocket('/events', onEvent, () => onEvent({ type: 'disconnected' })); }

// Reload this panel by itself when the panel files are updated (never while typing or in a popup).
(function autoReload() {
  let build = null;
  const check = async () => {
    try {
      const d = await (await fetch('/api/ping', { cache: 'no-store' })).json();
      if (build === null) build = d.build;
      else if (d.build !== build) {
        const busy = document.querySelector('.modal-bg') ||
          [...document.querySelectorAll('input[type=text], input:not([type]), textarea')].some(i => i.value && i === document.activeElement) ||
          (document.querySelector('#save') && !document.querySelector('#save').disabled);
        if (!busy) location.reload();
      }
    } catch (e) { }
  };
  check(); setInterval(check, 30000);
})();

function statusPill(pill, st) {
  const map = {
    live: ['live', 'LIVE'], upcoming: ['upcoming', 'Upcoming'], watching: ['watching', 'Watching'],
    offline: ['', 'Offline'], ended: ['', 'Stream ended'], nochannel: ['', 'Setup needed'],
    error: ['reconnect', 'Reconnecting…'], starting: ['', 'Starting…'], disconnected: ['reconnect', 'Reconnecting…'],
  };
  const [cls, label] = map[st.state] || ['', st.state || '…'];
  pill.className = 'pill ' + cls;
  pill.innerHTML = '<span class="dot"></span>';
  pill.appendChild(document.createTextNode(label));
  pill.title = st.title || '';
}

function fmtNum(n) { return n == null ? '—' : Number(n).toLocaleString(); }
function fmtTime(ms) { return new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
function fmtDur(ms) {
  if (!ms || ms < 0) return '—';
  const s = Math.floor(ms / 1000), h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
  return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(x).padStart(2, '0');
}
