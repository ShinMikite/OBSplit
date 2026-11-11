// Shared helpers for all panels.
const $ = (s, el = document) => el.querySelector(s);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

// Simple single-colour line icons (24x24, drawn with the text colour), in the spirit of OBS's own.
const ICONS = {
  eye: 'M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z M12 9a3 3 0 1 0 0 6 3 3 0 1 0 0-6z',
  eyeOff: 'M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z M12 9a3 3 0 1 0 0 6 3 3 0 1 0 0-6z M3 3l18 18',
  lock: 'M6 11h12v9H6z M8 11V8a4 4 0 0 1 8 0v3',
  unlock: 'M6 11h12v9H6z M8 11V8a4 4 0 0 1 7.7-1.5',
  up: 'M6 15l6-6 6 6', down: 'M6 9l6 6 6-6', right: 'M9 6l6 6-6 6',
  more: 'M5 12h.01 M12 12h.01 M19 12h.01',
  pin: 'M12 16v5 M8 4h8l-1 6 3 4H6l3-4z',
  game: 'M7 8h10a5 5 0 0 1 5 5v1a3 3 0 0 1-5.4 1.8L15 14H9l-1.6 1.8A3 3 0 0 1 2 14v-1a5 5 0 0 1 5-5z M7 11v3 M5.5 12.5h3 M16 12h.01 M18 13.5h.01',
  window: 'M3 5h18v14H3z M3 9h18',
  display: 'M3 4h18v12H3z M8 20h8 M12 16v4',
  region: 'M4 8V4h4 M16 4h4v4 M20 16v4h-4 M8 20H4v-4',
  camera: 'M3 7h12v10H3z M15 11l6-3v8l-6-3z',
  image: 'M3 5h18v14H3z M3 16l5-5 4 4 3-3 6 6 M15.5 8.5h.01',
  media: 'M7 5l12 7-12 7z',
  browser: 'M12 3a9 9 0 1 0 0 18 9 9 0 1 0 0-18z M3 12h18 M12 3c3 3 3 15 0 18 M12 3c-3 3-3 15 0 18',
  text: 'M5 6h14 M12 6v13',
  color: 'M5 5h14v14H5z',
  mic: 'M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z M5 11a7 7 0 0 0 14 0 M12 18v3',
  speaker: 'M4 9h4l5-4v14l-5-4H4z M16.5 9a4 4 0 0 1 0 6 M19 6.5a7.5 7.5 0 0 1 0 11',
  speakerOff: 'M4 9h4l5-4v14l-5-4H4z M17 9.5l5 5 M22 9.5l-5 5',
  headphones: 'M4 16v-4a8 8 0 0 1 16 0v4 M4 15h3v5H4z M17 15h3v5h-3z',
  scene: 'M3 5h18v14H3z M3 9h18 M8 5v4',
  group: 'M3 6h6l2 2h10v10H3z',
  gear: 'M12 9a3 3 0 1 0 0 6 3 3 0 1 0 0-6z M12 2v3 M12 19v3 M2 12h3 M19 12h3 M4.9 4.9l2.1 2.1 M17 17l2.1 2.1 M4.9 19.1L7 17 M17 7l2.1-2.1',
  trash: 'M4 7h16 M9 7V4h6v3 M6 7l1 13h10l1-13',
  clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 1 0 0-18z M12 7v5l3 2',
  ban: 'M12 3a9 9 0 1 0 0 18 9 9 0 1 0 0-18z M5.6 5.6l12.8 12.8',
  check: 'M5 12l5 5 9-10', x: 'M6 6l12 12 M18 6L6 18',
  refresh: 'M20 11a8 8 0 1 0-2.3 5.7 M20 4v7h-7',
  plus: 'M12 5v14 M5 12h14',
  record: 'M12 7a5 5 0 1 0 0 10 5 5 0 1 0 0-10z',
};
function ico(name, title) {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('class', 'ico');
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  p.setAttribute('d', ICONS[name] || ICONS.media); s.appendChild(p);
  if (title) { const t = document.createElementNS('http://www.w3.org/2000/svg', 'title'); t.textContent = title; s.appendChild(t); }
  return s;
}
// A small button with an icon and optional text.
function icoBtn(name, title, onclick, text, cls) {
  const b = el('button', 'ib' + (cls ? ' ' + cls : '')); b.title = title || '';
  b.appendChild(ico(name)); if (text) b.appendChild(document.createTextNode(' ' + text));
  if (onclick) b.onclick = e => { e.stopPropagation(); onclick(e); };
  return b;
}

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
