#!/usr/bin/env python3
"""
OBSplit - a small local companion server that adds XSplit-style panels to OBS Studio.

Panels (add as OBS custom browser docks):
  http://127.0.0.1:47821/chat    chat with badges, highlights, user cards, send + moderation
  http://127.0.0.1:47821/info    title / description / category / privacy / thumbnail editor
  http://127.0.0.1:47821/stats   viewers, likes, uptime, chat speed, stream health
  http://127.0.0.1:47821/scenes  scene thumbnails, per-scene audio, one-click game/Discord/screen region
  http://127.0.0.1:47821/audio   simple mixer with Stream / Rec / monitor switches
  http://127.0.0.1:47821/        setup + settings

Chat is READ the same way YouTube's own popout chat reads it (no API quota).
Actions (send, delete, timeout, ban, mod, title/thumbnail, stats) use the official
YouTube Data API with the user's own Google OAuth client.
Standard library only.
"""
import base64
import hashlib
import http.server
import json
import os
import queue
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import deque
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import obslink  # noqa: E402

APP_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(APP_DIR, "web")
DATA_DIR = os.path.join(APP_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

VERSION = "0.1.0"
HOST, PORT = "127.0.0.1", 47821
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3"
REDIRECT = f"http://127.0.0.1:{PORT}/oauth/callback"

CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
TOKENS_FILE = os.path.join(DATA_DIR, "tokens.json")
CLIENT_FILE = os.path.join(DATA_DIR, "client_secret.json")
QUOTA_FILE = os.path.join(DATA_DIR, "quota.json")
DB_FILE = os.path.join(DATA_DIR, "chat.db")
LOG_FILE = os.path.join(DATA_DIR, "server.log")
READY_FILE = os.path.join(DATA_DIR, "ready")

DEFAULT_CONFIG = {
    "channel_id": "",
    "channel_title": "",
    "channel_handle": "",
    "watch_override": "",
    "highlight_words": [],
    "font_size": 14,
    "show_timestamps": True,
    "show_avatars": False,
    "timeout_default": 300,
    "scene_audio": {},
    "regions": {},
    "mix": {"auto": False, "gap": 10, "skip": [], "user_levels": {}},
    "game_volumes": {},
}

# --------------------------------------------------------------------------- utils

_log_lock = threading.Lock()


def log(*parts):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(str(p) for p in parts)
    with _log_lock:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
    if sys.stdout:
        try:
            print(line, flush=True)
        except Exception:
            pass


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def http_get(url, headers=None, timeout=15):
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def http_post_json(url, body, timeout=15):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"User-Agent": UA, "Content-Type": "application/json",
                                          "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def now_ms():
    return int(time.time() * 1000)


def parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|/live/|/shorts/|/embed/)([\w-]{11})")


def extract_video_id(s):
    s = (s or "").strip()
    if re.fullmatch(r"[\w-]{11}", s):
        return s
    m = VIDEO_ID_RE.search(s)
    return m.group(1) if m else None


def resolve_channel(text):
    """'@handle', a channel link or a UC... id -> (channel_id, title). Uses the public channel page."""
    t = (text or "").strip()
    m = re.search(r"(UC[\w-]{22})", t)
    if m:
        return m.group(1), ""
    m = re.search(r"@([\w.\-]+)", t)
    if not m:
        raise ApiError(400, "Enter your channel as @handle or paste your channel link.")
    try:
        html = http_get(f"https://www.youtube.com/@{m.group(1)}", headers={"Cookie": "CONSENT=YES+1"})
    except Exception:
        raise ApiError(400, "Couldn't reach YouTube to look up that channel.")
    cid = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"', html)
    if not cid:
        raise ApiError(400, "Couldn't find that channel. Check the @handle.")
    title = re.search(r'<meta property="og:title" content="([^"]*)"', html)
    return cid.group(1), (title.group(1) if title else "")


# --------------------------------------------------------------------------- config

class Config:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = dict(DEFAULT_CONFIG)
        self.data.update(load_json(CONFIG_FILE, {}))

    def get(self, k):
        with self.lock:
            return self.data.get(k)

    def update(self, **kw):
        with self.lock:
            self.data.update(kw)
            save_json(CONFIG_FILE, self.data)

    def public(self):
        with self.lock:
            return dict(self.data)


# --------------------------------------------------------------------------- quota

class Quota:
    """Rough tracker. YouTube quota resets at midnight Pacific time."""

    def __init__(self):
        self.lock = threading.Lock()
        self.data = load_json(QUOTA_FILE, {"day": "", "used": 0})

    @staticmethod
    def _day():
        return (datetime.now(timezone.utc) - timedelta(hours=8)).strftime("%Y-%m-%d")

    def add(self, cost):
        with self.lock:
            d = self._day()
            if self.data.get("day") != d:
                self.data = {"day": d, "used": 0}
            self.data["used"] += cost
            save_json(QUOTA_FILE, self.data)

    def used(self):
        with self.lock:
            return self.data["used"] if self.data.get("day") == self._day() else 0


# --------------------------------------------------------------------------- Google API

class ApiError(Exception):
    def __init__(self, status, message, reason=""):
        super().__init__(message)
        self.status, self.message, self.reason = status, message, reason


FRIENDLY = {
    "quotaExceeded": "You've used today's YouTube API allowance (resets at midnight Pacific).",
    "forbidden": "YouTube says you're not allowed to do that on this stream.",
    "liveChatEnded": "That chat has ended.",
    "liveChatDisabled": "Chat is turned off for this stream.",
    "liveChatNotFound": "Couldn't find this stream's chat.",
    "rateLimitExceeded": "Too fast. Wait a few seconds and try again.",
    "uploadRateLimitExceeded": "Too many thumbnail uploads. Try again later.",
    "mediaBodyRequired": "No image was uploaded.",
    "invalidImage": "That image wasn't accepted. Use a JPG or PNG under 2 MB (1280x720 works best).",
    "forbiddenCustomThumbnails": "Custom thumbnails need a verified YouTube account (youtube.com/verify).",
    "insufficientPermissions": "Your sign-in is missing permission. Reconnect on the Setup page.",
    "authError": "Your YouTube sign-in expired. Reconnect on the Setup page.",
}


class Google:
    def __init__(self, config, quota):
        self.config, self.quota = config, quota
        self.lock = threading.Lock()
        self.tokens = load_json(TOKENS_FILE, {})
        self.pending = None  # (state, verifier)

    # --- client / tokens
    def client(self):
        d = load_json(CLIENT_FILE, None)
        if not d:
            return None
        c = d.get("installed") or d.get("web")
        if c and c.get("client_id") and c.get("client_secret"):
            return c
        return None

    def connected(self):
        return bool(self.tokens.get("refresh_token")) and self.client() is not None

    def save_client(self, raw):
        d = json.loads(raw)
        c = d.get("installed") or d.get("web")
        if not c or not c.get("client_id") or not c.get("client_secret"):
            raise ValueError("That file isn't a Google OAuth client file. Download the JSON for a 'Desktop app' client.")
        if "installed" not in d:
            raise ValueError("That client is a 'Web application'. Create a 'Desktop app' client instead.")
        save_json(CLIENT_FILE, d)

    def start_auth(self):
        c = self.client()
        if not c:
            raise ApiError(400, "Add your Google API client file first.")
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        self.pending = (state, verifier)
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
            "client_id": c["client_id"], "redirect_uri": REDIRECT, "response_type": "code",
            "scope": SCOPE, "access_type": "offline", "prompt": "consent select_account",
            "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
        })
        webbrowser.open(url)
        return url

    def finish_auth(self, code, state):
        if not self.pending or state != self.pending[0]:
            raise ApiError(400, "Sign-in session didn't match. Start again from the Setup page.")
        c = self.client()
        verifier = self.pending[1]
        self.pending = None
        tok = self._token_request({
            "client_id": c["client_id"], "client_secret": c["client_secret"], "code": code,
            "code_verifier": verifier, "redirect_uri": REDIRECT, "grant_type": "authorization_code",
        })
        if "refresh_token" not in tok:
            raise ApiError(400, "Google didn't return a long-lived sign-in. Try connecting again.")
        with self.lock:
            self.tokens = {"refresh_token": tok["refresh_token"], "access_token": tok["access_token"],
                           "expires_at": time.time() + tok.get("expires_in", 3600) - 60}
            save_json(TOKENS_FILE, self.tokens)
        r = self.request("GET", "/channels", {"part": "snippet", "mine": "true"}, cost=1)
        items = r.get("items") or []
        if not items:
            raise ApiError(400, "That Google account has no YouTube channel. Reconnect and pick your channel.")
        sn = items[0]["snippet"]
        self.config.update(channel_id=items[0]["id"], channel_title=sn.get("title", ""),
                           channel_handle=sn.get("customUrl", ""))
        log("connected channel", items[0]["id"], sn.get("title"))

    def disconnect(self):
        with self.lock:
            rt = self.tokens.get("refresh_token")
            self.tokens = {}
            save_json(TOKENS_FILE, {})
        if rt:
            try:
                urllib.request.urlopen(urllib.request.Request(
                    "https://oauth2.googleapis.com/revoke", data=urllib.parse.urlencode({"token": rt}).encode(),
                    method="POST"), timeout=10)
            except Exception:
                pass

    def _token_request(self, form):
        req = urllib.request.Request("https://oauth2.googleapis.com/token",
                                     data=urllib.parse.urlencode(form).encode(), method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            log("token error", e.code, body[:500])
            if "invalid_grant" in body:
                with self.lock:
                    self.tokens = {}
                    save_json(TOKENS_FILE, {})
                raise ApiError(401, FRIENDLY["authError"], "authError")
            raise ApiError(e.code, "Google sign-in failed: " + body[:200])

    def access_token(self):
        with self.lock:
            if self.tokens.get("access_token") and self.tokens.get("expires_at", 0) > time.time():
                return self.tokens["access_token"]
            rt = self.tokens.get("refresh_token")
        if not rt:
            raise ApiError(401, "Connect your YouTube account on the Setup page first.", "authError")
        c = self.client()
        if not c:
            raise ApiError(401, "Add your Google API client file on the Setup page first.", "authError")
        tok = self._token_request({"client_id": c["client_id"], "client_secret": c["client_secret"],
                                   "refresh_token": rt, "grant_type": "refresh_token"})
        with self.lock:
            self.tokens["access_token"] = tok["access_token"]
            self.tokens["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
            save_json(TOKENS_FILE, self.tokens)
            return self.tokens["access_token"]

    def request(self, method, path, params=None, body=None, cost=1, raw=None, content_type=None,
                base=API, _retry=True):
        url = base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        headers = {"Authorization": "Bearer " + self.access_token(), "Accept": "application/json"}
        data = None
        if raw is not None:
            data = raw
            headers["Content-Type"] = content_type or "application/octet-stream"
        elif body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        self.quota.add(cost)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                txt = r.read()
                return json.loads(txt) if txt else {}
        except urllib.error.HTTPError as e:
            txt = e.read().decode("utf-8", "replace")
            if e.code == 401 and _retry:
                with self.lock:
                    self.tokens["expires_at"] = 0
                return self.request(method, path, params, body, cost, raw, content_type, base, False)
            reason, msg = "", txt[:300]
            try:
                err = json.loads(txt)["error"]
                msg = err.get("message", msg)
                if err.get("errors"):
                    reason = err["errors"][0].get("reason", "")
            except Exception:
                pass
            log("API error", method, path, e.code, reason, msg[:300])
            raise ApiError(e.code, FRIENDLY.get(reason, msg), reason)


# --------------------------------------------------------------------------- chat parsing (YouTube web chat)

ALLOWED_IMG = re.compile(r"^https://([\w-]+\.)*(ggpht\.com|ytimg\.com|gstatic\.com|googleusercontent\.com|youtube\.com)/")


def safe_img(url):
    if not url:
        return None
    if url.startswith("//"):
        url = "https:" + url
    return url if ALLOWED_IMG.match(url) else None


def last_thumb(obj):
    th = (obj or {}).get("thumbnails") or []
    return safe_img(th[-1]["url"]) if th else None


def runs_to_segs(obj):
    if not obj:
        return []
    if "simpleText" in obj:
        return [{"t": obj["simpleText"]}]
    segs = []
    for r in obj.get("runs", []):
        if "text" in r:
            seg = {"t": r["text"]}
            ep = r.get("navigationEndpoint") or {}
            url = (ep.get("urlEndpoint") or {}).get("url")
            if url:
                if "youtube.com/redirect" in url:
                    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("q")
                    url = q[0] if q else url
                if url.startswith("http"):
                    seg["u"] = url
            elif (ep.get("watchEndpoint") or {}).get("videoId"):
                seg["u"] = "https://www.youtube.com/watch?v=" + ep["watchEndpoint"]["videoId"]
            if r.get("bold"):
                seg["b"] = 1
            segs.append(seg)
        elif "emoji" in r:
            e = r["emoji"]
            if e.get("isCustomEmoji"):
                alt = (e.get("shortcuts") or [e.get("emojiId", "")])[0]
                url = last_thumb(e.get("image"))
                segs.append({"e": url, "alt": alt} if url else {"t": alt})
            else:
                segs.append({"t": e.get("emojiId", "")})
    return segs


def segs_text(segs):
    return "".join(s.get("t") or s.get("alt", "") for s in segs)


def parse_badges(it):
    out = []
    for b in it.get("authorBadges") or []:
        r = b.get("liveChatAuthorBadgeRenderer") or {}
        icon = (r.get("icon") or {}).get("iconType")
        if icon == "OWNER":
            out.append({"k": "owner", "tip": "Channel owner"})
        elif icon == "MODERATOR":
            out.append({"k": "mod", "tip": "Moderator"})
        elif icon == "VERIFIED":
            out.append({"k": "verified", "tip": "Verified"})
        elif r.get("customThumbnail"):
            out.append({"k": "member", "img": last_thumb(r["customThumbnail"]), "tip": r.get("tooltip", "Member")})
    return out


def argb(v):
    if not isinstance(v, int):
        return None
    a, r, g, b = (v >> 24) & 255, (v >> 16) & 255, (v >> 8) & 255, v & 255
    return f"rgba({r},{g},{b},{a / 255:.2f})"


def parse_item(item):
    """Turn one YouTube chat item into our event dict (or None)."""
    kind_key = next(iter(item), None)
    it = item.get(kind_key) or {}
    base = {
        "type": "msg", "id": it.get("id"),
        "ts": int(int(it.get("timestampUsec", 0)) / 1000) or now_ms(),
        "ch": it.get("authorExternalChannelId", ""),
        "name": (it.get("authorName") or {}).get("simpleText", ""),
        "photo": last_thumb(it.get("authorPhoto")),
        "badges": parse_badges(it),
    }
    if not base["id"]:
        return None
    if kind_key == "liveChatTextMessageRenderer":
        base.update(kind="text", segs=runs_to_segs(it.get("message")))
    elif kind_key == "liveChatPaidMessageRenderer":
        base.update(kind="superchat", segs=runs_to_segs(it.get("message")),
                    amount=(it.get("purchaseAmountText") or {}).get("simpleText", ""),
                    color=argb(it.get("bodyBackgroundColor")), hcolor=argb(it.get("headerBackgroundColor")))
    elif kind_key == "liveChatPaidStickerRenderer":
        base.update(kind="sticker", segs=[],
                    amount=(it.get("purchaseAmountText") or {}).get("simpleText", ""),
                    sticker=last_thumb(it.get("sticker")), color=argb(it.get("backgroundColor")))
    elif kind_key == "liveChatMembershipItemRenderer":
        if it.get("headerPrimaryText"):
            base.update(kind="milestone", header=segs_text(runs_to_segs(it["headerPrimaryText"])),
                        segs=runs_to_segs(it.get("message")))
        else:
            base.update(kind="member", header=segs_text(runs_to_segs(it.get("headerSubtext"))) or "New member",
                        segs=[])
    elif kind_key == "liveChatSponsorshipsGiftPurchaseAnnouncementRenderer":
        h = ((it.get("header") or {}).get("liveChatSponsorshipsHeaderRenderer") or {})
        base.update(kind="gift", name=(h.get("authorName") or {}).get("simpleText", ""),
                    photo=last_thumb(h.get("authorPhoto")), badges=parse_badges(h),
                    header=segs_text(runs_to_segs(h.get("primaryText"))), segs=[])
    elif kind_key == "liveChatSponsorshipsGiftRedemptionAnnouncementRenderer":
        base.update(kind="giftrecv", header=segs_text(runs_to_segs(it.get("message"))), segs=[])
    elif kind_key in ("liveChatViewerEngagementMessageRenderer", "liveChatModeChangeMessageRenderer"):
        txt = segs_text(runs_to_segs(it.get("message") or it.get("text")))
        sub = segs_text(runs_to_segs(it.get("subtext")))
        base.update(kind="system", segs=[{"t": (txt + (" — " + sub if sub else "")).strip()}], ch="", name="")
    else:
        return None
    return base


class ChatEnded(Exception):
    pass


class WebChat:
    """Reads one video's live chat the way the YouTube popout does."""

    def __init__(self, video_id):
        self.video_id = video_id
        page = http_get(f"https://www.youtube.com/live_chat?is_popout=1&v={video_id}",
                        headers={"Cookie": "CONSENT=YES+1"})
        ver = re.search(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"', page)
        vis = re.search(r'"VISITOR_DATA":"([^"]+)"', page)
        self.client = {"clientName": "WEB", "clientVersion": ver.group(1) if ver else "2.20250101.00.00",
                       "hl": "en", "gl": "US"}
        if vis:
            self.client["visitorData"] = vis.group(1)
        m = re.search(r'(?:window\["ytInitialData"\]|var ytInitialData)\s*=\s*(\{.+?\});\s*</script>', page, re.S)
        if not m:
            raise ChatEnded("no chat on this video")
        data = json.loads(m.group(1))
        lcr = (data.get("contents") or {}).get("liveChatRenderer")
        if not lcr:
            raise ChatEnded("chat unavailable")
        # Prefer "Live chat" (every message) over the default "Top chat" (filtered).
        cont = None
        try:
            items = (lcr["header"]["liveChatHeaderRenderer"]["viewSelector"]
                     ["sortFilterSubMenuRenderer"]["subMenuItems"])
            cont = items[-1]["continuation"]["reloadContinuationData"]["continuation"]
        except (KeyError, IndexError, TypeError):
            pass
        if not cont:
            cont = next(iter(lcr["continuations"][0].values()))["continuation"]
        self.continuation = cont
        self.first = True

    def poll(self):
        """Returns (actions, wait_seconds)."""
        resp = http_post_json("https://www.youtube.com/youtubei/v1/live_chat/get_live_chat?prettyPrint=false",
                              {"context": {"client": self.client}, "continuation": self.continuation})
        lcc = (resp.get("continuationContents") or {}).get("liveChatContinuation")
        if not lcc:
            raise ChatEnded("chat ended")
        conts = lcc.get("continuations") or []
        if not conts:
            raise ChatEnded("chat ended")
        c = next(iter(conts[0].values()))
        self.continuation = c.get("continuation") or self.continuation
        timeout = c.get("timeoutMs", 2000) / 1000
        actions = lcc.get("actions") or []
        hist = self.first
        self.first = False
        return actions, hist, max(1.0, min(timeout, 3.0))


# --------------------------------------------------------------------------- store (sqlite)

class Store:
    def __init__(self):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users(channel_id TEXT PRIMARY KEY, name TEXT, first_seen INTEGER,
            last_seen INTEGER, msg_count INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY, video_id TEXT, channel_id TEXT, name TEXT,
            ts INTEGER, kind TEXT, text TEXT, amount TEXT);
        CREATE INDEX IF NOT EXISTS ix_msg_ch ON messages(channel_id, ts);
        """)

    def record(self, video_id, ev):
        """Store a message. Returns True if this is the first message EVER from this person."""
        if not ev.get("ch"):
            return False
        with self.lock:
            cur = self.db.execute("INSERT OR IGNORE INTO messages VALUES(?,?,?,?,?,?,?,?)",
                                  (ev["id"], video_id, ev["ch"], ev["name"], ev["ts"], ev["kind"],
                                   segs_text(ev.get("segs", [])) or ev.get("header", ""), ev.get("amount")))
            if cur.rowcount == 0:
                return False
            row = self.db.execute("SELECT msg_count FROM users WHERE channel_id=?", (ev["ch"],)).fetchone()
            if row is None:
                self.db.execute("INSERT INTO users VALUES(?,?,?,?,1)", (ev["ch"], ev["name"], ev["ts"], ev["ts"]))
            else:
                self.db.execute("UPDATE users SET name=?, last_seen=?, msg_count=msg_count+1 WHERE channel_id=?",
                                (ev["name"], ev["ts"], ev["ch"]))
            self.db.commit()
            return row is None

    def user(self, ch):
        with self.lock:
            u = self.db.execute("SELECT name, first_seen, last_seen, msg_count FROM users WHERE channel_id=?",
                                (ch,)).fetchone()
            hist = self.db.execute("SELECT ts, kind, text, amount, video_id, id FROM messages WHERE channel_id=? "
                                   "ORDER BY ts DESC LIMIT 300", (ch,)).fetchall()
            streams = self.db.execute("SELECT COUNT(DISTINCT video_id) FROM messages WHERE channel_id=?",
                                      (ch,)).fetchone()[0]
        return {
            "name": u[0] if u else "", "first_seen": u[1] if u else None, "last_seen": u[2] if u else None,
            "msg_count": u[3] if u else 0, "streams": streams,
            "history": [{"ts": h[0], "kind": h[1], "text": h[2], "amount": h[3], "video": h[4], "id": h[5]}
                        for h in hist],
        }


# --------------------------------------------------------------------------- hub (state + live events)

class Hub:
    def __init__(self, config, google, store):
        self.config, self.google, self.store = config, google, store
        self.lock = threading.Lock()
        self.subs = []
        self.recent = deque(maxlen=600)
        self.by_id = {}
        self.status = {"state": "starting", "video": None, "title": "", "own": False}
        self.reset_session()
        self.stats = {}
        self.chat_ids = {}       # video_id -> liveChatId
        self.api_ids = {}        # our msg id -> API msg id
        self.bans = {}           # channel_id -> ban id (this session)

    def reset_session(self):
        self.session = {"started": now_ms(), "messages": 0, "chatters": set(), "times": deque(),
                        "superchats": {}, "members": 0, "gifts": 0, "first_timers": 0}

    # --- pub/sub
    def subscribe(self):
        q = queue.Queue(maxsize=2000)
        with self.lock:
            self.subs.append(q)
            snap = list(self.recent)
        return q, snap

    def unsubscribe(self, q):
        with self.lock:
            if q in self.subs:
                self.subs.remove(q)

    def publish(self, ev):
        with self.lock:
            if ev.get("type") == "msg":
                self.recent.append(ev)
                self.by_id[ev["id"]] = ev
                if len(self.by_id) > 5000:
                    for k in list(self.by_id)[:1000]:
                        self.by_id.pop(k, None)
            subs = list(self.subs)
        for q in subs:
            try:
                q.put_nowait(ev)
            except queue.Full:
                pass

    def set_status(self, **kw):
        with self.lock:
            self.status.update(kw)
            st = dict(self.status)
        self.publish({"type": "status", **st})

    def clear(self):
        with self.lock:
            self.recent.clear()
            self.by_id.clear()
            self.api_ids.clear()
            self.reset_session()
        self.publish({"type": "clear"})

    # --- incoming chat actions
    def handle_actions(self, video_id, actions, hist):
        for a in actions:
            try:
                self._handle_action(video_id, a, hist)
            except Exception:
                log("action parse error", traceback.format_exc()[-600:])

    def _handle_action(self, video_id, a, hist):
        if "addChatItemAction" in a:
            ev = parse_item(a["addChatItemAction"].get("item") or {})
            if not ev:
                return
            with self.lock:
                if ev["id"] in self.by_id:
                    return
            first = self.store.record(video_id, ev)
            ev["first"] = bool(first and not hist)
            ev["hist"] = hist
            s = self.session
            if ev["kind"] != "system":
                s["messages"] += 1
                s["chatters"].add(ev["ch"])
                if not hist:
                    s["times"].append(time.time())
                if ev["first"]:
                    s["first_timers"] += 1
            if ev["kind"] in ("superchat", "sticker") and ev.get("amount"):
                m = re.match(r"^\s*([^\d\s.,]*)\s*([\d.,]+)\s*([^\d\s.,]*)", ev["amount"])
                if m:
                    cur = (m.group(1) or m.group(3) or "?").strip()
                    try:
                        val = float(m.group(2).replace(",", ""))
                        s["superchats"][cur] = round(s["superchats"].get(cur, 0) + val, 2)
                    except ValueError:
                        pass
            if ev["kind"] == "member":
                s["members"] += 1
            if ev["kind"] == "gift":
                s["gifts"] += 1
            self.publish(ev)
        elif "markChatItemAsDeletedAction" in a or "removeChatItemAction" in a:
            d = a.get("markChatItemAsDeletedAction") or a.get("removeChatItemAction")
            self._mark_deleted(id_=d.get("targetItemId"))
        elif "markChatItemsByAuthorAsDeletedAction" in a or "removeChatItemByAuthorAction" in a:
            d = a.get("markChatItemsByAuthorAsDeletedAction") or a.get("removeChatItemByAuthorAction")
            self._mark_deleted(ch=d.get("externalChannelId"))
        elif "replaceChatItemAction" in a:
            d = a["replaceChatItemAction"]
            ev = parse_item(d.get("replacementItem") or {})
            if ev:
                ev["id"] = d.get("targetItemId") or ev["id"]
                ev["type"] = "replace"
                self.publish(ev)

    def _mark_deleted(self, id_=None, ch=None):
        with self.lock:
            for ev in self.recent:
                if (id_ and ev["id"] == id_) or (ch and ev.get("ch") == ch):
                    ev["deleted"] = True
        self.publish({"type": "delete", "id": id_, "ch": ch})

    def chat_rate(self):
        t = self.session["times"]
        cutoff = time.time() - 60
        while t and t[0] < cutoff:
            t.popleft()
        return len(t)

    # --- API helpers for actions
    def live_chat_id(self, video_id):
        if video_id in self.chat_ids:
            return self.chat_ids[video_id]
        r = self.google.request("GET", "/videos", {"part": "liveStreamingDetails", "id": video_id}, cost=1)
        items = r.get("items") or []
        cid = items and (items[0].get("liveStreamingDetails") or {}).get("activeLiveChatId")
        if not cid:
            raise ApiError(404, "This stream has no active chat.", "liveChatNotFound")
        self.chat_ids[video_id] = cid
        return cid

    def api_message_id(self, msg_id):
        if msg_id in self.api_ids:
            return self.api_ids[msg_id]
        ev = self.by_id.get(msg_id)
        if not ev:
            raise ApiError(404, "That message is too old to find.")
        vid = self.status.get("video")
        cid = self.live_chat_id(vid)
        r = self.google.request("GET", "/liveChat/messages",
                                {"liveChatId": cid, "part": "id,snippet,authorDetails", "maxResults": 2000}, cost=5)
        want = re.sub(r"\s+", " ", segs_text(ev.get("segs", []))).strip()
        best, best_score = None, None
        for it in r.get("items") or []:
            if (it.get("authorDetails") or {}).get("channelId") != ev["ch"]:
                continue
            sn = it.get("snippet") or {}
            pub = parse_iso(sn.get("publishedAt"))
            dt = abs(pub.timestamp() * 1000 - ev["ts"]) if pub else 10 ** 9
            txt = re.sub(r"\s+", " ", sn.get("displayMessage") or "").strip()
            score = dt + (0 if txt == want else 60_000)
            if best_score is None or score < best_score:
                best, best_score = it["id"], score
        if not best or best_score > 120_000:
            raise ApiError(404, "Couldn't match that message on YouTube (it may already be gone).")
        self.api_ids[msg_id] = best
        return best


# --------------------------------------------------------------------------- background workers

class ChatWorker(threading.Thread):
    daemon = True

    def __init__(self, hub, config):
        super().__init__(name="chat")
        self.hub, self.config = hub, config
        self.wake = threading.Event()

    def find_live_video(self):
        """Free check of the channel's /live page. Returns (video_id, state, title) or (None, ...)."""
        ch = self.config.get("channel_id")
        if not ch:
            return None, "nochannel", ""
        html = http_get(f"https://www.youtube.com/channel/{ch}/live", headers={"Cookie": "CONSENT=YES+1"})
        m = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/watch\?v=([\w-]{11})"', html)
        if not m:
            return None, "offline", ""
        title = re.search(r'<meta name="title" content="([^"]*)"', html)
        title = title.group(1) if title else ""
        if '"isLiveNow":true' in html or '"isLive":true' in html:
            return m.group(1), "live", title
        if '"isUpcoming":true' in html:
            return m.group(1), "upcoming", title
        return None, "offline", ""

    def run(self):
        current = None
        chat = None
        while True:
            try:
                override = extract_video_id(self.config.get("watch_override"))
                if override:
                    vid, state, title, own = override, "watching", "", False
                else:
                    vid, state, title = self.find_live_video()
                    own = True
                if not vid:
                    if current:
                        current, chat = None, None
                    self.hub.set_status(state=state, video=None, title="", own=False)
                    self.wake.wait(20)
                    self.wake.clear()
                    continue
                if vid != current:
                    self.hub.clear()
                    current = vid
                    chat = WebChat(vid)
                    log("attached to chat", vid, state)
                self.hub.set_status(state=state, video=vid, title=title, own=own)
                # poll until chat ends or target changes
                last_check = time.time()
                while True:
                    actions, hist, wait = chat.poll()
                    if actions:
                        self.hub.handle_actions(vid, actions, hist)
                    if self.wake.wait(wait):
                        self.wake.clear()
                        break  # settings changed -> re-evaluate target
                    if not override and time.time() - last_check > 60:
                        last_check = time.time()
                        v2, st2, t2 = self.find_live_video()
                        if v2 != vid:
                            break
                        if st2 != state or (t2 and t2 != title):
                            state, title = st2, t2
                            self.hub.set_status(state=state, title=title)
            except ChatEnded as e:
                log("chat ended", current, e)
                current, chat = None, None
                self.hub.set_status(state="ended", video=None, own=False)
                self.wake.wait(20)
                self.wake.clear()
            except Exception as e:
                log("chat worker error", repr(e), traceback.format_exc()[-800:])
                current, chat = None, None
                self.hub.set_status(state="error", error=str(e)[:200])
                self.wake.wait(10)
                self.wake.clear()


class StatsWorker(threading.Thread):
    daemon = True

    def __init__(self, hub, google):
        super().__init__(name="stats")
        self.hub, self.google = hub, google
        self.bound = {}
        self.peak = {}

    def run(self):
        while True:
            try:
                self.tick()
            except ApiError as e:
                self.hub.stats["error"] = e.message
            except Exception as e:
                log("stats error", repr(e))
            time.sleep(30)

    def tick(self):
        st = self.hub.status
        vid = st.get("video")
        out = {"video": vid, "updated": now_ms()}
        if not vid or not self.google.connected():
            self.hub.stats = out
            return
        r = self.google.request("GET", "/videos", {"part": "liveStreamingDetails,statistics,snippet", "id": vid},
                                cost=1)
        items = r.get("items") or []
        if items:
            lsd = items[0].get("liveStreamingDetails") or {}
            stt = items[0].get("statistics") or {}
            viewers = int(lsd["concurrentViewers"]) if lsd.get("concurrentViewers") else None
            if viewers is not None:
                self.peak[vid] = max(self.peak.get(vid, 0), viewers)
            start = parse_iso(lsd.get("actualStartTime"))
            out.update(viewers=viewers, peak=self.peak.get(vid), likes=int(stt["likeCount"]) if stt.get("likeCount") else None,
                       views=int(stt["viewCount"]) if stt.get("viewCount") else None,
                       started=int(start.timestamp() * 1000) if start else None,
                       title=items[0]["snippet"].get("title"))
            if st.get("own"):
                if items[0]["snippet"].get("title") and items[0]["snippet"]["title"] != st.get("title"):
                    self.hub.set_status(title=items[0]["snippet"]["title"])
                if vid not in self.bound:
                    b = self.google.request("GET", "/liveBroadcasts", {"part": "contentDetails", "id": vid}, cost=1)
                    bi = b.get("items") or []
                    self.bound[vid] = (bi[0].get("contentDetails") or {}).get("boundStreamId") if bi else None
                sid = self.bound.get(vid)
                if sid:
                    s = self.google.request("GET", "/liveStreams", {"part": "status", "id": sid}, cost=1)
                    si = s.get("items") or []
                    if si:
                        hs = (si[0].get("status") or {}).get("healthStatus") or {}
                        out["health"] = hs.get("status")
                        out["issues"] = [{"sev": i.get("severity"), "text": i.get("description") or i.get("reason")}
                                         for i in hs.get("configurationIssues") or []][:5]
        self.hub.stats = out


def obs_watchdog():
    """When started by OBS, exit after OBS closes."""
    misses = 0
    while True:
        time.sleep(30)
        try:
            r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq obs64.exe", "/NH"], capture_output=True,
                               text=True, creationflags=0x08000000)
            running = "obs64.exe" in r.stdout.lower()
        except Exception:
            running = True
        misses = 0 if running else misses + 1
        if misses >= 2:
            log("OBS closed; exiting")
            os._exit(0)


# --------------------------------------------------------------------------- HTTP

PAGES = {"/": "setup.html", "/setup": "setup.html", "/chat": "chat.html", "/info": "info.html",
         "/stats": "stats.html", "/scenes": "scenes.html", "/audio": "audio.html"}
MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}


class App:
    def __init__(self):
        self.config = Config()
        self.quota = Quota()
        self.google = Google(self.config, self.quota)
        self.store = Store()
        self.hub = Hub(self.config, self.google, self.store)
        self.chat = ChatWorker(self.hub, self.config)
        self.stats = StatsWorker(self.hub, self.google)
        self.categories = None
        self.obs = obslink.ObsLink(self.config, log)


APP = None


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "OBSplit/" + VERSION

    def log_message(self, fmt, *args):
        pass

    # --- helpers
    def _host_ok(self):
        return self.headers.get("Host", "") in ALLOWED_HOSTS

    def send_json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def send_text(self, text, code=200, ctype="text/html; charset=utf-8"):
        b = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def body(self, limit=6 * 1024 * 1024):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ApiError(413, "File too large (YouTube thumbnails must be under 2 MB).")
        return self.rfile.read(n) if n else b""

    def jbody(self):
        raw = self.body()
        return json.loads(raw) if raw else {}

    # --- GET
    def do_GET(self):
        if not self._host_ok():
            return self.send_text("forbidden", 403, "text/plain")
        u = urllib.parse.urlparse(self.path)
        p, qs = u.path, urllib.parse.parse_qs(u.query)
        try:
            if p in PAGES:
                return self.serve_file(PAGES[p])
            if p.startswith("/static/"):
                return self.serve_file(os.path.basename(p))
            if p == "/events":
                return self.sse()
            if p == "/obs-events":
                return self.obs_sse((qs.get("view") or [""])[0])
            if p == "/api/mixcheck/file":
                return self.serve_mixcheck()
            if p.startswith("/api/obs/"):
                import winapps
                try:
                    if p == "/api/obs/windows":
                        return self.send_json({"windows": winapps.list_windows(), "games": APP.obs.game_sources(),
                                               "scene": APP.obs.target_scene(),
                                               "scenes": APP.obs.state.get("scenes", [])})
                    if p == "/api/obs/discord":
                        return self.send_json(APP.obs.discord_status())
                    if p == "/api/obs/regions":
                        return self.send_json({"regions": APP.obs.region_sources(), "scene": APP.obs.target_scene()})
                except obslink.ObsError as e:
                    return self.send_json({"error": str(e)}, 400)
            if p == "/api/ping":
                build = int(max((os.path.getmtime(os.path.join(WEB_DIR, f)) for f in os.listdir(WEB_DIR)),
                                default=0))
                return self.send_json({"ok": True, "app": "obsplit", "version": VERSION, "build": build})
            if p == "/api/state":
                return self.send_json(self.state())
            if p == "/api/user":
                ch = (qs.get("ch") or [""])[0]
                d = APP.store.user(ch)
                cur_vid = APP.hub.status.get("video")
                with APP.hub.lock:
                    sess = [e for e in APP.hub.recent if e.get("ch") == ch]
                    live = dict(APP.hub.by_id)
                session = []
                for h in reversed([h for h in d["history"] if h["video"] == cur_vid]):
                    e = live.get(h["id"])
                    session.append({"id": h["id"], "ts": h["ts"], "kind": h["kind"], "amount": h["amount"],
                                    "segs": e.get("segs", []) if e else [{"t": h["text"] or ""}],
                                    "deleted": bool(e and e.get("deleted")), "can_delete": e is not None})
                d["session"] = session
                d["history"] = [h for h in d["history"] if h["video"] != cur_vid]
                last = sess[-1] if sess else None
                d.update(ch=ch, photo=last and last.get("photo"), badges=last and last.get("badges"),
                         name=(last and last.get("name")) or d["name"], banned=ch in APP.hub.bans)
                return self.send_json(d)
            if p == "/api/stats":
                s = APP.hub.session
                return self.send_json({**APP.hub.stats, "messages": s["messages"],
                                       "chatters": len(s["chatters"]), "rate": APP.hub.chat_rate(),
                                       "superchats": s["superchats"], "members": s["members"], "gifts": s["gifts"],
                                       "first_timers": s["first_timers"], "quota": APP.quota.used(),
                                       "status": APP.hub.status})
            if p == "/api/broadcasts":
                return self.send_json(self.broadcasts())
            if p == "/api/video":
                return self.send_json(self.video((qs.get("id") or [""])[0]))
            if p == "/oauth/callback":
                return self.oauth_callback(qs)
            return self.send_text("not found", 404, "text/plain")
        except ApiError as e:
            return self.send_json({"error": e.message, "reason": e.reason}, 400)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception as e:
            log("GET error", p, traceback.format_exc()[-800:])
            try:
                return self.send_json({"error": str(e)}, 500)
            except Exception:
                return

    def serve_file(self, name):
        path = os.path.join(WEB_DIR, name)
        if not os.path.isfile(path):
            return self.send_text("not found", 404, "text/plain")
        with open(path, "rb") as f:
            b = f.read()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(os.path.splitext(name)[1], "application/octet-stream"))
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(b)

    def state(self):
        c = APP.config.public()
        return {"status": APP.hub.status, "config": c, "has_client": APP.google.client() is not None,
                "connected": APP.google.connected(), "quota": APP.quota.used()}

    def sse(self):
        q, snap = APP.hub.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            hello = {"type": "hello", **self.state(), "recent": snap[-400:]}
            self.wfile.write(b"data: " + json.dumps(hello, ensure_ascii=False).encode() + b"\n\n")
            self.wfile.flush()
            while True:
                try:
                    ev = q.get(timeout=15)
                    if ev.get("type") in ("status", "settings"):
                        ev = {**ev, **{"connected": APP.google.connected()}}
                    self.wfile.write(b"data: " + json.dumps(ev, ensure_ascii=False).encode() + b"\n\n")
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            APP.hub.unsubscribe(q)
            self.close_connection = True

    def serve_mixcheck(self):
        """The 15-second check recording, with Range support so the panel's player can seek."""
        path = (APP.obs.mixcheck or {}).get("file")
        if not path or not os.path.isfile(path):
            return self.send_text("not found", 404, "text/plain")
        size = os.path.getsize(path)
        start, end = 0, size - 1
        rng = self.headers.get("Range", "")
        m = re.match(r"bytes=(\d*)-(\d*)", rng)
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else end
            else:
                start = max(0, size - int(m.group(2)))
            end = min(end, size - 1)
        ctype = "video/quicktime" if path.lower().endswith(".mov") else "video/mp4"
        self.send_response(206 if m else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if m:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(262144, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    def obs_sse(self, view):
        want_thumbs = view == "scenes"
        q = APP.obs.subscribe()
        q.thumbs = want_thumbs
        q.view = view
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            hello = {"type": "state", **APP.obs.snapshot()}
            if want_thumbs:
                th = {s: {"img": img, "stale": True, "dark": False} for s, img in APP.obs.last_live.items()}
                th.update(APP.obs.thumbs)
                hello["thumbs"] = th
            self.wfile.write(b"data: " + json.dumps(hello, ensure_ascii=False).encode() + b"\n\n")
            self.wfile.flush()
            while True:
                try:
                    ev = q.get(timeout=15)
                    if ev.get("type") == "thumb" and not want_thumbs:
                        continue
                    if ev.get("type") in ("meters", "mix") and want_thumbs:
                        continue
                    self.wfile.write(b"data: " + json.dumps(ev, ensure_ascii=False).encode() + b"\n\n")
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            APP.obs.unsubscribe(q)
            self.close_connection = True

    def oauth_callback(self, qs):
        if "error" in qs:
            return self.send_text(f"<h2>Sign-in cancelled</h2><p>{qs['error'][0]}</p><p>You can close this tab.</p>")
        try:
            APP.google.finish_auth(qs.get("code", [""])[0], qs.get("state", [""])[0])
        except ApiError as e:
            return self.send_text(f"<h2>Couldn't connect</h2><p>{e.message}</p>")
        APP.chat.wake.set()
        APP.hub.publish({"type": "settings", **self.state()})
        title = APP.config.get("channel_title")
        return self.send_text(
            "<body style='font-family:Segoe UI;background:#16171c;color:#e6e6ea;padding:40px'>"
            f"<h2>Connected to {title or 'YouTube'}</h2><p>You can close this tab and go back to OBS.</p></body>")

    def broadcasts(self):
        out = []
        for status in ("active", "upcoming"):
            r = APP.google.request("GET", "/liveBroadcasts", {"part": "snippet,status", "broadcastStatus": status,
                                                              "broadcastType": "all", "maxResults": 10}, cost=1)
            for it in r.get("items") or []:
                sn = it.get("snippet") or {}
                out.append({"id": it["id"], "title": sn.get("title"), "state": "live" if status == "active" else "upcoming",
                            "scheduled": sn.get("scheduledStartTime"),
                            "thumb": last_thumb({"thumbnails": list((sn.get("thumbnails") or {}).values())})})
        if APP.categories is None:
            r = APP.google.request("GET", "/videoCategories", {"part": "snippet", "regionCode": "US", "hl": "en_US"},
                                   cost=1)
            APP.categories = [{"id": c["id"], "title": c["snippet"]["title"]} for c in r.get("items") or []
                              if c["snippet"].get("assignable")]
        return {"broadcasts": out, "categories": APP.categories, "current": APP.hub.status.get("video")}

    def video(self, vid):
        r = APP.google.request("GET", "/videos", {"part": "snippet,status", "id": vid}, cost=1)
        items = r.get("items") or []
        if not items:
            raise ApiError(404, "Couldn't find that stream on your channel.")
        sn, st = items[0]["snippet"], items[0]["status"]
        thumbs = sn.get("thumbnails") or {}
        best = None
        for k in ("maxres", "standard", "high", "medium", "default"):
            if k in thumbs:
                best = thumbs[k]["url"]
                break
        return {"id": vid, "title": sn.get("title", ""), "description": sn.get("description", ""),
                "categoryId": sn.get("categoryId"), "tags": sn.get("tags", []),
                "privacy": st.get("privacyStatus"), "thumb": best, "channel": sn.get("channelTitle")}

    # --- POST
    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-Panel") != "1":
            return self.send_text("forbidden", 403, "text/plain")
        p = urllib.parse.urlparse(self.path).path
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        try:
            if p == "/api/client":
                APP.google.save_client(self.body(200_000).decode("utf-8", "replace"))
                APP.hub.publish({"type": "settings", **self.state()})
                return self.send_json({"ok": True})
            if p == "/api/connect":
                return self.send_json({"ok": True, "url": APP.google.start_auth()})
            if p == "/api/disconnect":
                APP.google.disconnect()
                APP.hub.publish({"type": "settings", **self.state()})
                return self.send_json({"ok": True})
            if p == "/api/settings":
                b = self.jbody()
                allowed = {k: b[k] for k in ("highlight_words", "font_size", "show_timestamps", "show_avatars",
                                             "timeout_default", "channel_id") if k in b}
                if "watch_override" in b:
                    w = (b["watch_override"] or "").strip()
                    if w and not extract_video_id(w):
                        raise ApiError(400, "That doesn't look like a YouTube video link.")
                    allowed["watch_override"] = w
                if "channel_id" in allowed and not re.fullmatch(r"UC[\w-]{22}", allowed["channel_id"] or ""):
                    raise ApiError(400, "Channel ID should start with UC and be 24 characters.")
                if b.get("channel"):
                    cid, title = resolve_channel(b["channel"])
                    allowed.update(channel_id=cid, channel_title=title)
                APP.config.update(**allowed)
                APP.chat.wake.set()
                APP.hub.publish({"type": "settings", **self.state()})
                return self.send_json({"ok": True})
            if p == "/api/open":
                url = self.jbody().get("url") or ""
                if not re.match(r"^https://(console\.cloud\.google\.com|studio\.youtube\.com|www\.youtube\.com)/", url):
                    raise ApiError(400, "That link can't be opened from here.")
                webbrowser.open(url)
                return self.send_json({"ok": True})
            if p.startswith("/api/obs/"):
                b = self.jbody()
                try:
                    if p == "/api/obs/scene":
                        APP.obs.set_scene(b.get("scene"))
                    elif p == "/api/obs/transition":
                        APP.obs.transition()
                    elif p == "/api/obs/input":
                        APP.obs.set_input(b)
                    elif p == "/api/obs/rule":
                        APP.obs.set_rule(b.get("scene"), b.get("name"), b.get("value"))
                    elif p == "/api/obs/add-game":
                        return self.send_json({"ok": True, **APP.obs.add_game(b)})
                    elif p == "/api/obs/discord":
                        return self.send_json({"ok": True, **APP.obs.add_discord(b)})
                    elif p == "/api/obs/region":
                        return self.send_json({"ok": True, **APP.obs.add_region(b)})
                    elif p == "/api/obs/mix":
                        return self.send_json({"ok": True, "auto": APP.obs.set_mix(b)})
                    elif p == "/api/obs/duck":
                        APP.obs.set_duck(b.get("name"), bool(b.get("on")))
                        APP.obs.push_state()
                    elif p == "/api/obs/mixcheck":
                        APP.obs.mixcheck_start(int(b.get("seconds") or 15))
                    elif p == "/api/obs/mixcheck/open":
                        f = (APP.obs.mixcheck or {}).get("file")
                        if not f or not os.path.isfile(f):
                            return self.send_json({"error": "No check recording to open."}, 400)
                        os.startfile(f)
                    elif p == "/api/obs/mixcheck/delete":
                        APP.obs.mixcheck_delete()
                    else:
                        return self.send_text("not found", 404, "text/plain")
                except obslink.ObsError as e:
                    return self.send_json({"error": str(e)}, 400)
                return self.send_json({"ok": True})
            if p == "/api/refresh":
                APP.chat.wake.set()
                return self.send_json({"ok": True})
            # ---- actions needing YouTube API
            vid = APP.hub.status.get("video")
            if p == "/api/send":
                text = (self.jbody().get("text") or "").strip()[:200]
                if not text:
                    raise ApiError(400, "Type a message first.")
                cid = APP.hub.live_chat_id(vid)
                APP.google.request("POST", "/liveChat/messages", {"part": "snippet"}, {"snippet": {
                    "liveChatId": cid, "type": "textMessageEvent", "textMessageDetails": {"messageText": text}}},
                                   cost=20)
                return self.send_json({"ok": True})
            if p == "/api/delete":
                mid = APP.hub.api_message_id(self.jbody().get("id"))
                APP.google.request("DELETE", "/liveChat/messages", {"id": mid}, cost=20)
                return self.send_json({"ok": True})
            if p == "/api/ban":
                b = self.jbody()
                ch, secs = b.get("ch"), int(b.get("seconds") or 0)
                cid = APP.hub.live_chat_id(vid)
                snip = {"liveChatId": cid, "type": "temporary" if secs else "permanent",
                        "bannedUserDetails": {"channelId": ch}}
                if secs:
                    snip["banDurationSeconds"] = secs
                r = APP.google.request("POST", "/liveChat/bans", {"part": "snippet"}, {"snippet": snip}, cost=200)
                if not secs and r.get("id"):
                    APP.hub.bans[ch] = r["id"]
                return self.send_json({"ok": True})
            if p == "/api/unban":
                ch = self.jbody().get("ch")
                bid = APP.hub.bans.get(ch)
                if not bid:
                    raise ApiError(400, "Only bans made from this panel during this session can be undone here. "
                                        "Use YouTube Studio > Community > Hidden users for older bans.")
                APP.google.request("DELETE", "/liveChat/bans", {"id": bid}, cost=200)
                APP.hub.bans.pop(ch, None)
                return self.send_json({"ok": True})
            if p == "/api/mod":
                ch = self.jbody().get("ch")
                cid = APP.hub.live_chat_id(vid)
                APP.google.request("POST", "/liveChat/moderators", {"part": "snippet"},
                                   {"snippet": {"liveChatId": cid, "moderatorDetails": {"channelId": ch}}}, cost=200)
                return self.send_json({"ok": True})
            if p == "/api/video":
                return self.send_json(self.update_video(self.jbody()))
            if p == "/api/thumbnail":
                vid2 = (qs.get("id") or [""])[0]
                data = self.body()
                if len(data) > 2 * 1024 * 1024:
                    raise ApiError(400, "Thumbnails must be under 2 MB.")
                ctype = self.headers.get("Content-Type", "image/jpeg")
                if ctype not in ("image/jpeg", "image/png"):
                    raise ApiError(400, "Use a JPG or PNG image.")
                r = APP.google.request("POST", "/thumbnails/set", {"videoId": vid2, "uploadType": "media"},
                                       raw=data, content_type=ctype, cost=50, base=UPLOAD_API)
                items = r.get("items") or [{}]
                return self.send_json({"ok": True, "thumb": last_thumb({"thumbnails": list(items[0].values())})})
            return self.send_text("not found", 404, "text/plain")
        except ApiError as e:
            return self.send_json({"error": e.message, "reason": e.reason}, 400)
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        except Exception as e:
            log("POST error", p, traceback.format_exc()[-800:])
            return self.send_json({"error": "Something went wrong: " + str(e)[:200]}, 500)

    def update_video(self, b):
        vid = b.get("id")
        r = APP.google.request("GET", "/videos", {"part": "snippet,status", "id": vid}, cost=1)
        items = r.get("items") or []
        if not items:
            raise ApiError(404, "Couldn't find that stream on your channel.")
        sn, st = items[0]["snippet"], items[0]["status"]
        title = (b.get("title") or "").strip()
        if not title:
            raise ApiError(400, "The title can't be empty.")
        if len(title) > 100 or "<" in title or ">" in title:
            raise ApiError(400, "Titles can be up to 100 characters and can't contain < or >.")
        new_sn = {"title": title, "description": b.get("description", sn.get("description", ""))[:5000],
                  "categoryId": b.get("categoryId") or sn.get("categoryId"),
                  "tags": b["tags"] if isinstance(b.get("tags"), list) else sn.get("tags", [])}
        for k in ("defaultLanguage", "defaultAudioLanguage"):
            if k in sn:
                new_sn[k] = sn[k]
        body, parts = {"id": vid, "snippet": new_sn}, ["snippet"]
        if b.get("privacy") and b["privacy"] != st.get("privacyStatus"):
            keep = {k: st[k] for k in ("privacyStatus", "embeddable", "license", "publicStatsViewable",
                                       "selfDeclaredMadeForKids", "containsSyntheticMedia") if k in st}
            keep["privacyStatus"] = b["privacy"]
            body["status"], parts = keep, parts + ["status"]
        APP.google.request("PUT", "/videos", {"part": ",".join(parts)}, body, cost=50)
        if vid == APP.hub.status.get("video"):
            APP.hub.set_status(title=title)
        return self.video(vid)


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


def already_running():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/ping", timeout=2) as r:
            return b"obsplit" in r.read()
    except Exception:
        return False


def main():
    global APP
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 2_000_000:
            os.replace(LOG_FILE, LOG_FILE + ".old")
    except OSError:
        pass
    try:
        httpd = Server((HOST, PORT), Handler)
    except OSError:
        if already_running():
            log("already running; nothing to do")
            open(READY_FILE, "w").close()
            return
        raise
    APP = App()
    APP.chat.start()
    APP.stats.start()
    if "--with-obs" in sys.argv:
        threading.Thread(target=obs_watchdog, daemon=True, name="watchdog").start()
    open(READY_FILE, "w").close()
    log(f"listening on http://{HOST}:{PORT}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
