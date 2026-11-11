"""
Twitch: sign-in (device code, no secret needed), chat (Twitch's chat server over a WebSocket), channel info,
stream key, moderation and stats. Standard library only.

Chat can be read without signing in (anonymously, like a logged-out viewer). Sending, moderation, stream info
and stats need the sign-in.
"""
import json
import os
import re
import secrets
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from quality import _ws_frame, _ws_read_frame

CLIENT_ID = "761h9p99wtedjaiaafac7u3g1i8877"   # OBSplit's public Twitch app (public client: no secret)
SCOPES = " ".join([
    "chat:read", "chat:edit",
    "channel:manage:broadcast", "channel:read:stream_key",
    "moderator:manage:banned_users", "moderator:manage:chat_messages", "channel:manage:moderators",
    "moderator:read:followers", "channel:read:subscriptions",
])
ID_API = "https://id.twitch.tv/oauth2"
HELIX = "https://api.twitch.tv/helix"
IRC = ("irc-ws.chat.twitch.tv", 443)
EMOTE_URL = "https://static-cdn.jtvnw.net/emoticons/v2/{}/default/dark/1.0"
UA = "OBSplit"


class TwitchError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def _form(url, fields, timeout=15):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(), method="POST",
                                 headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read() or b"{}")
        except ValueError:
            body = {}
        raise TwitchError(e.code, body.get("message") or str(e))


# --------------------------------------------------------------------------- chat message parsing

_TAG_ESC = {"\\s": " ", "\\:": ";", "\\\\": "\\", "\\r": "\r", "\\n": "\n"}


def _unescape(v):
    return re.sub(r"\\[s:\\rn]", lambda m: _TAG_ESC[m.group(0)], v)


def parse_line(line):
    """'@tags :prefix COMMAND params :trailing' -> (tags, prefix, command, params, trailing)."""
    tags = {}
    if line.startswith("@"):
        raw, line = line[1:].split(" ", 1)
        for kv in raw.split(";"):
            k, _, v = kv.partition("=")
            tags[k] = _unescape(v)
    prefix = ""
    if line.startswith(":"):
        prefix, line = line[1:].split(" ", 1)
    trailing = None
    if " :" in line:
        line, trailing = line.split(" :", 1)
    parts = line.split()
    return tags, prefix, (parts[0] if parts else ""), parts[1:], trailing


def emote_segs(text, emotes_tag):
    """Message text + the 'emotes' tag ('id:0-4,6-10/id2:12-15') -> segments with emote images."""
    spans = []
    for group in (emotes_tag or "").split("/"):
        if ":" not in group:
            continue
        eid, ranges = group.split(":", 1)
        for r in ranges.split(","):
            a, _, b = r.partition("-")
            if a.isdigit() and b.isdigit():
                spans.append((int(a), int(b), eid))
    spans.sort()
    segs, pos = [], 0
    for a, b, eid in spans:
        if a < pos or b >= len(text):
            continue
        if a > pos:
            segs.append({"t": text[pos:a]})
        segs.append({"e": EMOTE_URL.format(urllib.parse.quote(eid)), "alt": text[a:b + 1]})
        pos = b + 1
    if pos < len(text):
        segs.append({"t": text[pos:]})
    out = []
    for s in segs:     # make links clickable like on YouTube
        if "t" not in s:
            out.append(s)
            continue
        for part in re.split(r"(https?://\S+)", s["t"]):
            if part:
                out.append({"t": part, "u": part} if re.match(r"https?://", part) else {"t": part})
    return out


def parse_badges(tags):
    out = []
    info = dict(x.split("/", 1) for x in (tags.get("badge-info") or "").split(",") if "/" in x)
    for b in (tags.get("badges") or "").split(","):
        name, _, ver = b.partition("/")
        if name == "broadcaster":
            out.append({"k": "owner", "tip": "Broadcaster"})
        elif name == "moderator":
            out.append({"k": "mod", "tip": "Moderator"})
        elif name == "vip":
            out.append({"k": "vip", "tip": "VIP"})
        elif name in ("partner", "verified"):
            out.append({"k": "verified", "tip": "Verified"})
        elif name in ("subscriber", "founder"):
            months = info.get("subscriber") or info.get("founder")
            out.append({"k": "sub", "tip": ("Founder" if name == "founder" else "Subscriber")
                        + (f" ({months} months)" if months else "")})
    return out


def _base_event(tags, prefix):
    login = prefix.split("!", 1)[0] if prefix else (tags.get("login") or "")
    uid = tags.get("user-id") or ""
    return {"type": "msg", "plat": "tw", "id": tags.get("id") or secrets.token_hex(8),
            "ts": int(tags.get("tmi-sent-ts") or time.time() * 1000),
            "ch": ("tw:" + uid) if uid else "", "login": login,
            "name": tags.get("display-name") or login, "photo": None, "badges": parse_badges(tags),
            "first": tags.get("first-msg") == "1"}


def event_from(tags, prefix, cmd, params, trailing):
    """One chat line -> ('msg', event) | ('delete', {...}) | (None, None)."""
    if cmd == "PRIVMSG":
        text = trailing or ""
        action = text.startswith("\x01ACTION ") and text.endswith("\x01")
        if action:
            text = text[8:-1]
        ev = _base_event(tags, prefix)
        ev["segs"] = emote_segs(text, tags.get("emotes"))
        if tags.get("bits"):
            ev.update(kind="superchat", amount=f"{int(tags['bits']):,} bits", color="#9146ff", hcolor="#772ce8")
        else:
            ev["kind"] = "text"
        if tags.get("msg-id") == "highlighted-message":
            ev["hl"] = True
        return "msg", ev
    if cmd == "USERNOTICE":
        mid = tags.get("msg-id", "")
        ev = _base_event(tags, prefix)
        ev["first"] = False
        system = tags.get("system-msg") or ""
        ev["segs"] = emote_segs(trailing or "", tags.get("emotes")) if trailing else []
        if mid in ("sub", "resub"):
            ev.update(kind="member", header=system or "Subscribed")
        elif mid in ("subgift", "submysterygift", "anonsubgift", "anonsubmysterygift"):
            ev.update(kind="gift", header=system or "Gifted a sub")
        elif mid == "raid":
            ev.update(kind="raid", header=system or "Raid!")
        elif mid in ("announcement",):
            ev.update(kind="text", hl=True)
        else:
            ev.update(kind="system", segs=[{"t": system or mid}], ch="", name="")
        return "msg", ev
    if cmd == "CLEARMSG":
        return "delete", {"id": tags.get("target-msg-id")}
    if cmd == "CLEARCHAT" and tags.get("target-user-id"):
        return "delete", {"ch": "tw:" + tags["target-user-id"]}
    return None, None


# --------------------------------------------------------------------------- the Twitch connection

class Twitch:
    def __init__(self, data_dir, config, log, hub, obs):
        self.config, self.log, self.hub, self.obs = config, log, hub, obs
        self.file = os.path.join(data_dir, "twitch.json")
        self.lock = threading.Lock()
        try:
            with open(self.file, encoding="utf-8") as f:
                self.t = json.load(f)
        except (OSError, ValueError):
            self.t = {}
        self.login_state = None          # {"code", "uri", "expires"} while waiting, or {"error": ...}
        self.wake = threading.Event()    # channel or sign-in changed: reconnect chat
        self.ws, self.ws_lock = None, threading.Lock()
        self.userstate = {}
        self.known_followers = None
        self.peak = 0
        self.stats = {}

    # ------------------------------------------------------------------ sign-in
    def _save(self):
        tmp = self.file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.t, f)
        os.replace(tmp, self.file)

    def connected(self):
        return bool(self.t.get("refresh_token") and self.t.get("user_id"))

    def info(self):
        ls = self.login_state or {}
        return {"connected": self.connected(), "login": self.t.get("login"), "name": self.t.get("display_name"),
                "user_id": self.t.get("user_id"), "channel": self.channel(),
                "signing_in": {"code": ls.get("code"), "uri": ls.get("uri")} if ls.get("code") else None,
                "sign_in_error": ls.get("error")}

    def channel(self):
        return (self.t.get("login") if self.connected() else (self.config.get("twitch_channel") or "")).lower()

    def start_login(self):
        d = _form(ID_API + "/device", {"client_id": CLIENT_ID, "scopes": SCOPES})
        self.login_state = {"code": d["user_code"], "uri": d["verification_uri"],
                            "expires": time.time() + int(d.get("expires_in", 1800))}
        threading.Thread(target=self._poll_login, args=(d["device_code"], int(d.get("interval", 5))),
                         daemon=True, name="twitch-login").start()
        return {"code": d["user_code"], "uri": d["verification_uri"]}

    def _poll_login(self, device_code, interval):
        while self.login_state and time.time() < self.login_state.get("expires", 0):
            time.sleep(interval)
            try:
                tok = _form(ID_API + "/token", {"client_id": CLIENT_ID, "scopes": SCOPES, "device_code": device_code,
                                                "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
            except TwitchError as e:
                if "pending" in e.message.lower() or "slow_down" in e.message.lower():
                    continue
                self.login_state = {"error": "Twitch sign-in didn't finish (" + e.message + "). Try again."}
                self.hub.publish({"type": "settings"})
                return
            with self.lock:
                self.t.update(access_token=tok["access_token"], refresh_token=tok.get("refresh_token"),
                              expires_at=time.time() + int(tok.get("expires_in", 3600)) - 120)
            try:
                v = self._validate()
                self.t.update(login=v["login"], user_id=v["user_id"])
                u = self.helix("GET", "/users", {"id": v["user_id"]})["data"][0]
                self.t["display_name"] = u.get("display_name") or v["login"]
                self._save()
            except Exception as e:
                self.login_state = {"error": "Signed in, but couldn't read your Twitch account: " + str(e)[:120]}
                return
            self.login_state = None
            self.log("twitch connected as", self.t.get("login"))
            self.known_followers = None
            self.wake.set()
            self.hub.publish({"type": "settings"})
            return
        if self.login_state and not self.login_state.get("error"):
            self.login_state = {"error": "The Twitch sign-in code expired. Click Connect Twitch again."}
            self.hub.publish({"type": "settings"})

    def cancel_login(self):
        self.login_state = None

    def disconnect(self):
        tok = self.t.get("access_token")
        if tok:
            try:
                _form(ID_API + "/revoke", {"client_id": CLIENT_ID, "token": tok})
            except Exception:
                pass
        with self.lock:
            self.t = {}
            self._save()
        self.stats, self.known_followers = {}, None
        self.wake.set()

    def _validate(self):
        req = urllib.request.Request(ID_API + "/validate", headers={"Authorization": "OAuth " + self.t["access_token"],
                                                                     "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise TwitchError(e.code, "Twitch sign-in is no longer valid.")

    def _token(self, force=False):
        with self.lock:
            if not self.connected():
                raise TwitchError(401, "Connect Twitch on the Setup panel first.")
            if force or time.time() >= self.t.get("expires_at", 0):
                try:
                    tok = _form(ID_API + "/token", {"client_id": CLIENT_ID, "grant_type": "refresh_token",
                                                    "refresh_token": self.t["refresh_token"]})
                except TwitchError as e:
                    if e.status in (400, 401):
                        self.t = {}
                        self._save()
                        raise TwitchError(401, "Your Twitch sign-in expired. Connect Twitch again on the Setup panel.")
                    raise
                self.t.update(access_token=tok["access_token"],
                              refresh_token=tok.get("refresh_token") or self.t["refresh_token"],
                              expires_at=time.time() + int(tok.get("expires_in", 3600)) - 120)
                self._save()
            return self.t["access_token"]

    def helix(self, method, path, params=None, body=None, _retry=True):
        url = HELIX + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": "Bearer " + self._token(), "Client-Id": CLIENT_ID, "User-Agent": UA,
            **({"Content-Type": "application/json"} if data is not None else {})})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read() or b"{}").get("message") or str(e)
            except ValueError:
                msg = str(e)
            if e.code == 401 and _retry:
                self._token(force=True)
                return self.helix(method, path, params, body, _retry=False)
            raise TwitchError(e.code, msg)

    # ------------------------------------------------------------------ channel, key, moderation
    def uid(self):
        if not self.connected():
            raise TwitchError(401, "Connect Twitch on the Setup panel first.")
        return self.t["user_id"]

    def get_channel(self):
        c = self.helix("GET", "/channels", {"broadcaster_id": self.uid()})["data"][0]
        return {"title": c.get("title", ""), "game_id": c.get("game_id", ""), "game_name": c.get("game_name", ""),
                "tags": c.get("tags") or [], "language": c.get("broadcaster_language", "")}

    def set_channel(self, b):
        title = (b.get("title") or "").strip()
        if not title:
            raise TwitchError(400, "The title can't be empty.")
        if len(title) > 140:
            raise TwitchError(400, "Twitch titles can be up to 140 characters.")
        tags = [re.sub(r"[^\w]", "", t)[:25] for t in (b.get("tags") or []) if t.strip()][:10]
        body = {"title": title, "tags": tags}
        if b.get("game_id") is not None:
            body["game_id"] = str(b["game_id"])
        self.helix("PATCH", "/channels", {"broadcaster_id": self.uid()}, body)
        self.hub.set_status(title=title)
        return self.get_channel()

    def search_categories(self, q):
        if not (q or "").strip():
            return []
        d = self.helix("GET", "/search/categories", {"query": q.strip(), "first": 10})
        return [{"id": c["id"], "name": c["name"], "art": c.get("box_art_url", "").replace("{width}x{height}", "52x72")}
                for c in d.get("data") or []]

    def use_stream_key(self):
        try:
            if self.obs.request("GetStreamStatus").get("outputActive"):
                raise TwitchError(400, "Stop streaming first, then switch the stream key.")
        except TwitchError:
            raise
        except Exception:
            raise TwitchError(400, "OBS isn't connected.")
        key = self.helix("GET", "/streams/key", {"broadcaster_id": self.uid()})["data"][0]["stream_key"]
        self.obs.request("SetStreamServiceSettings", {"streamServiceType": "rtmp_common", "streamServiceSettings": {
            "service": "Twitch", "server": "auto", "key": key}})
        self.log("OBS stream key set from Twitch")   # never log the key itself
        return {"ok": True}

    def stream_key_in_obs(self):
        try:
            s = self.obs.request("GetStreamServiceSettings").get("streamServiceSettings") or {}
            return (s.get("service") or "").lower() == "twitch" and bool(s.get("key"))
        except Exception:
            return False

    def _user_id(self, ch):
        if not (ch or "").startswith("tw:"):
            raise TwitchError(400, "That isn't a Twitch user.")
        return ch[3:]

    def ban(self, ch, seconds):
        data = {"user_id": self._user_id(ch)}
        if seconds:
            data["duration"] = int(seconds)
        self.helix("POST", "/moderation/bans", {"broadcaster_id": self.uid(), "moderator_id": self.uid()},
                   {"data": data})

    def unban(self, ch):
        self.helix("DELETE", "/moderation/bans", {"broadcaster_id": self.uid(), "moderator_id": self.uid(),
                                                  "user_id": self._user_id(ch)})

    def delete_message(self, msg_id):
        self.helix("DELETE", "/moderation/chat", {"broadcaster_id": self.uid(), "moderator_id": self.uid(),
                                                  "message_id": msg_id})

    def add_mod(self, ch):
        self.helix("POST", "/moderation/moderators", {"broadcaster_id": self.uid(), "user_id": self._user_id(ch)})

    # ------------------------------------------------------------------ chat
    def start(self):
        threading.Thread(target=self._chat_loop, daemon=True, name="twitch-chat").start()
        threading.Thread(target=self._stats_loop, daemon=True, name="twitch-stats").start()

    def _send_raw(self, line):
        with self.ws_lock:
            if not self.ws:
                raise TwitchError(503, "Twitch chat isn't connected right now.")
            self.ws.sendall(_ws_frame(1, (line + "\r\n").encode()))

    def send(self, text):
        text = (text or "").strip()[:500]
        if not text:
            raise TwitchError(400, "Type a message first.")
        if not self.connected():
            raise TwitchError(401, "Connect Twitch on the Setup panel to chat.")
        if not self.authed:
            raise TwitchError(503, "Twitch chat is still connecting with your account. Try again in a moment.")
        self._send_raw(f"PRIVMSG #{self.channel()} :{text}")
        # Twitch doesn't echo your own messages back, so show it ourselves
        us = self.userstate
        tags = {"display-name": us.get("display-name") or self.t.get("display_name"), "badges": us.get("badges", ""),
                "badge-info": us.get("badge-info", ""), "user-id": self.t.get("user_id"), "emotes": "",
                "tmi-sent-ts": str(int(time.time() * 1000))}
        _, ev = event_from(tags, self.t.get("login", ""), "PRIVMSG", [], text)
        ev["first"] = False
        self.hub.add(self.session_key(), ev)

    def session_key(self):
        return "tw:" + self.channel() + ":" + time.strftime("%Y-%m-%d")

    authed = False
    _joined_chan = None

    def _chat_loop(self):
        backoff = 2
        while True:
            chan = self.channel()
            if not chan:
                self.hub.set_status(state="nochannel", video=None, title="", own=False)
                self.wake.wait(30)
                self.wake.clear()
                continue
            sock = None
            try:
                sock = self._open_chat(chan)
                backoff = 2
                self._read_chat(sock, chan)
            except Exception as e:
                if not isinstance(e, (OSError, ConnectionError, TwitchError, ssl.SSLError)):
                    self.log("twitch chat error", repr(e)[:200])
            finally:
                with self.ws_lock:
                    self.ws = None
                self.authed = False
                if sock:
                    try:
                        sock.close()
                    except OSError:
                        pass
            if self.wake.wait(backoff):
                self.wake.clear()
            backoff = min(backoff * 2, 60)

    def _open_chat(self, chan):
        import base64
        raw = socket.create_connection(IRC, timeout=15)
        sock = ssl.create_default_context().wrap_socket(raw, server_hostname=IRC[0])
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall((f"GET / HTTP/1.1\r\nHost: {IRC[0]}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            c = sock.recv(4096)
            if not c:
                raise ConnectionError("Twitch chat closed the connection")
            resp += c
        if b" 101 " not in resp.split(b"\r\n", 1)[0]:
            raise ConnectionError("Twitch chat refused the connection")
        with self.ws_lock:
            self.ws = sock
        self._send_raw("CAP REQ :twitch.tv/tags twitch.tv/commands")
        if self.connected() and self.channel() == chan:
            self._send_raw("PASS oauth:" + self._token())
            self._send_raw("NICK " + self.t["login"])
        else:
            self._send_raw(f"NICK justinfan{secrets.randbelow(80000) + 10000}")
        self._send_raw("JOIN #" + chan)
        return sock

    def _read_chat(self, sock, chan):
        sock.settimeout(1)
        buf, last = "", time.time()
        joined = False
        while not self.wake.is_set():
            try:
                op, data = _ws_read_frame(sock)
            except socket.timeout:
                if time.time() - last > 360:     # Twitch pings every ~5 minutes
                    raise ConnectionError("Twitch chat went quiet")
                continue
            last = time.time()
            if op == 8:
                raise ConnectionError("Twitch chat closed")
            if op == 9:
                sock.sendall(_ws_frame(10, data))
                continue
            if op != 1:
                continue
            buf += data.decode("utf-8", "replace")
            *lines, buf = buf.split("\r\n")
            for line in lines:
                if not line:
                    continue
                tags, prefix, cmd, params, trailing = parse_line(line)
                if cmd == "PING":
                    self._send_raw("PONG :" + (trailing or "tmi.twitch.tv"))
                elif cmd == "NOTICE" and trailing and "authentication failed" in trailing.lower():
                    raise TwitchError(401, "Twitch chat sign-in failed")
                elif cmd == "RECONNECT":
                    raise ConnectionError("Twitch asked to reconnect")
                elif cmd == "GLOBALUSERSTATE":
                    self.authed = True
                elif cmd == "USERSTATE":
                    self.userstate = tags
                elif cmd == "ROOMSTATE" and not joined:
                    joined = True
                    if self._joined_chan != chan:      # a different channel: start a fresh chat
                        self._joined_chan = chan
                        self.hub.clear()
                    st = self.hub.status.get("state")
                    if not self.connected():
                        st = "chat"                    # reading chat only; no live status without signing in
                    elif st not in ("live", "offline"):
                        st = "offline"
                    self.hub.set_status(state=st, video="tw:" + chan, own=self.connected())
                else:
                    kind, ev = event_from(tags, prefix, cmd, params, trailing)
                    if kind == "msg":
                        self.hub.add(self.session_key(), ev)
                    elif kind == "delete":
                        self.hub._mark_deleted(id_=ev.get("id"), ch=ev.get("ch"))
        self.wake.clear()

    # ------------------------------------------------------------------ stats (every 30 s while signed in)
    def _stats_loop(self):
        while True:
            try:
                if self.connected():
                    self._stats_tick()
            except TwitchError as e:
                self.stats["error"] = e.message
            except Exception as e:
                self.log("twitch stats error", repr(e)[:200])
            time.sleep(30)

    def _stats_tick(self):
        uid, chan = self.uid(), self.channel()
        s = (self.helix("GET", "/streams", {"user_id": uid}).get("data") or [None])[0]
        out = {"updated": int(time.time() * 1000)}
        if s:
            v = int(s.get("viewer_count") or 0)
            self.peak = max(self.peak, v)
            started = s.get("started_at")
            from datetime import datetime
            ts = int(datetime.fromisoformat(started.replace("Z", "+00:00")).timestamp() * 1000) if started else None
            out.update(viewers=v, peak=self.peak, started=ts, title=s.get("title"), game=s.get("game_name"))
            self.hub.set_status(state="live", video="tw:" + chan, title=s.get("title") or "", own=True)
        else:
            self.peak = 0
            ch = self.get_channel()
            self.hub.set_status(state="offline", video="tw:" + chan, title=ch.get("title") or "", own=True)
        f = self.helix("GET", "/channels/followers", {"broadcaster_id": uid, "first": 20})
        out["followers"] = f.get("total")
        ids = [x["user_id"] for x in f.get("data") or []]
        if self.known_followers is None:
            self.known_followers = set(ids)
        else:
            for x in reversed(f.get("data") or []):
                if x["user_id"] not in self.known_followers:
                    self.known_followers.add(x["user_id"])
                    self.hub.add(self.session_key(), {
                        "type": "msg", "plat": "tw", "id": "follow-" + x["user_id"], "kind": "follow",
                        "ts": int(time.time() * 1000), "ch": "tw:" + x["user_id"], "login": x.get("user_login"),
                        "name": x.get("user_name"), "badges": [], "segs": [], "header": "Followed"})
                    self.hub.session["follows"] = self.hub.session.get("follows", 0) + 1
        try:
            sub = self.helix("GET", "/subscriptions", {"broadcaster_id": uid, "first": 1})
            out["subs_total"] = sub.get("total")
        except TwitchError:
            pass   # only Affiliates and Partners have subscriptions
        out["key_in_obs"] = self.stream_key_in_obs()
        self.stats = out
        self.hub.stats = out
