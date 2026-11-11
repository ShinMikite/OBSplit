"""
Talks to OBS through its built-in obs-websocket server (v5) for the Scenes+ and Audio+ panels.
Standard library only (includes a tiny websocket client).
"""
import base64
import hashlib
import json
import math
import os
import queue
import socket
import struct
import threading
import time
import uuid

OBS_WS_CONFIG = os.path.join(os.environ.get("APPDATA", ""), "obs-studio", "plugin_config", "obs-websocket",
                             "config.json")
OBS_DIR = os.path.join(os.environ.get("APPDATA", ""), "obs-studio")


def _ini_value(path, section, key):
    cur = None
    try:
        for line in open(path, encoding="utf-8-sig"):
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                cur = line[1:-1]
            elif cur == section and line.startswith(key + "="):
                return line.split("=", 1)[1]
    except OSError:
        pass
    return None


def profile_ini():
    """basic.ini of the OBS profile in use (OBS 31+ keeps this in user.ini, older versions in global.ini)."""
    d = None
    for f in ("user.ini", "global.ini"):
        d = d or _ini_value(os.path.join(OBS_DIR, f), "Basic", "ProfileDir")
    return os.path.join(OBS_DIR, "basic", "profiles", d or "Untitled", "basic.ini")

# event subscriptions: General|Config|Scenes|Inputs|Transitions|Filters|Outputs|SceneItems|MediaInputs|Vendors|Ui
SUBS = 0x7FF | (1 << 16)  # + InputVolumeMeters (high volume)


class ObsError(Exception):
    pass


# --------------------------------------------------------------------------- minimal websocket client

class WS:
    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET / HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                           f"Sec-WebSocket-Protocol: obswebsocket.json\r\n\r\n").encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("OBS closed the connection during handshake")
            resp += chunk
        head, rest = resp.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise ConnectionError("OBS refused the websocket connection")
        self.buf = bytearray(rest)
        self.sock.settimeout(None)
        self.wlock = threading.Lock()

    def _exact(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(262144)
            if not chunk:
                raise ConnectionError("connection closed")
            self.buf += chunk
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def recv(self):
        msg = bytearray()
        while True:
            b1, b2 = self._exact(2)
            op, ln = b1 & 0x0F, b2 & 0x7F
            if ln == 126:
                ln = struct.unpack(">H", self._exact(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", self._exact(8))[0]
            mask = self._exact(4) if b2 & 0x80 else None
            data = self._exact(ln)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if op == 0x9:
                self._send(0xA, data)
                continue
            if op == 0xA:
                continue
            if op == 0x8:
                raise ConnectionError("OBS closed the connection")
            msg += data
            if b1 & 0x80:
                return msg.decode("utf-8")

    def _send(self, op, payload):
        n = len(payload)
        head = bytearray([0x80 | op])
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head.append(0x80 | 126)
            head += struct.pack(">H", n)
        else:
            head.append(0x80 | 127)
            head += struct.pack(">Q", n)
        mask = os.urandom(4)
        head += mask
        mk = (mask * (n // 4 + 1))[:n]
        body = (int.from_bytes(payload, "big") ^ int.from_bytes(mk, "big")).to_bytes(n, "big") if n else b""
        with self.wlock:
            self.sock.sendall(bytes(head) + body)

    def send(self, obj):
        self._send(0x1, json.dumps(obj).encode())

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


# --------------------------------------------------------------------------- helpers

def mul_to_db(m):
    return -100.0 if m <= 0 else max(-100.0, 20 * math.log10(m))


def png_darkness(data_uri):
    """Decode a tiny PNG screenshot and say whether it's (nearly) all black.
    Returns (is_dark, mean_brightness)."""
    import zlib
    data = base64.b64decode(data_uri.split(",", 1)[1])
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return False, -1
    pos, idat, w, h, ctype = 8, b"", 0, 0, 6
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        typ, chunk = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", chunk[:10])
            if depth != 8:
                return False, -1
        elif typ == b"IDAT":
            idat += chunk
        elif typ == b"IEND":
            break
    bpp = {6: 4, 2: 3, 0: 1, 4: 2}.get(ctype)
    if not bpp or not w:
        return False, -1
    raw, stride = zlib.decompress(idat), w * bpp
    prev, i, total, bright = bytearray(stride), 0, 0.0, 0
    for _ in range(h):
        f, line = raw[i], bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b, c = prev[x], (prev[x - bpp] if x >= bpp else 0)
            if f == 1:
                line[x] = (line[x] + a) & 255
            elif f == 2:
                line[x] = (line[x] + b) & 255
            elif f == 3:
                line[x] = (line[x] + ((a + b) >> 1)) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = line
        for x in range(w):
            px = line[x * bpp:(x + 1) * bpp]
            lum = px[0] * 0.3 + px[1] * 0.59 + px[2] * 0.11 if bpp >= 3 else px[0]
            total += lum
            bright += lum > 40
    mean = total / (w * h)
    return (mean < 10 and bright / (w * h) < 0.03), round(mean, 1)


AUDIO_EXT = {".mp3", ".aac", ".wav", ".flac", ".ogg", ".opus", ".m4a", ".wma", ".aiff", ".aif"}
MP4_EXT = {".mp4", ".mov", ".m4v", ".3gp"}
_probe_cache = {}


def file_has_audio(path):
    """True/False if we can tell whether a media file has a sound track, None if unknown."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (path, st.st_mtime, st.st_size)
    if key in _probe_cache:
        return _probe_cache[key]
    ext = os.path.splitext(path)[1].lower()
    result = None
    if ext in AUDIO_EXT:
        result = True
    elif ext in MP4_EXT:
        try:
            with open(path, "rb") as f:
                pos, size = 0, st.st_size
                while pos + 8 <= size:
                    f.seek(pos)
                    sz, typ = struct.unpack(">I4s", f.read(8))
                    if sz == 1:
                        sz = struct.unpack(">Q", f.read(8))[0]
                    elif sz == 0:
                        sz = size - pos
                    if typ == b"moov":
                        data = f.read(min(sz, 64 * 1024 * 1024))
                        result = False
                        i = data.find(b"hdlr")
                        while i != -1:
                            if data[i + 12:i + 16] == b"soun":  # MP4 handler_type / QuickTime component subtype
                                result = True
                                break
                            i = data.find(b"hdlr", i + 4)
                        break
                    if sz < 8:
                        break
                    pos += sz
        except (OSError, struct.error):
            result = None
    _probe_cache[key] = result
    return result


def can_make_sound(kind, settings):
    """Whether a source can actually put sound into OBS (vs. just having the audio controls)."""
    s = settings or {}
    if kind == "ffmpeg_source":
        if s.get("is_local_file", True) is False:
            return True
        r = file_has_audio(s.get("local_file") or "")
        return True if r is None else r
    if kind == "browser_source":
        return bool(s.get("reroute_audio"))
    if kind in ("game_capture", "window_capture"):
        return bool(s.get("capture_audio"))
    if kind == "dshow_input":
        return s.get("audio_output_mode", 0) != 2  # 2 = send to desktop audio instead
    return True


def read_rec_tracks():
    """Which tracks go into recordings (from the OBS profile). Returns e.g. [2, 3, 4]."""
    mask, section = 0, None
    try:
        for line in open(profile_ini(), encoding="utf-8-sig"):
            line = line.strip()
            if line.startswith("["):
                section = line
            elif section == "[AdvOut]" and line.startswith("RecTracks="):
                mask = int(line.split("=", 1)[1])
    except (OSError, ValueError):
        pass
    return [i + 1 for i in range(6) if mask & (1 << i)] or [1]


# --------------------------------------------------------------------------- OBS link

class ObsLink:
    def __init__(self, config, log):
        self.config, self.log = config, log
        self.ws = None
        self.lock = threading.Lock()
        self.pending = {}
        self.subs = []
        self.state = {"connected": False, "error": "", "scenes": [], "program": None, "preview": None,
                      "studio": False, "inputs": {}, "specials": [], "members": [], "rec_tracks": [2, 3, 4]}
        self.thumbs = {}          # scene -> {"img", "stale", "dark"} as shown in Scenes+
        self.last_live = self._load_last_live()   # scene -> last good picture while live/previewed
        self._last_saved = 0
        self.meters = {}
        self.heard = self._load_heard()   # name -> {"silent": bool}: learned by listening while a source plays
        self._listen = {}                 # name -> [seconds active, loudest dB]
        self.tasks = queue.Queue()
        self.thumb_due = {}
        threading.Thread(target=self._run, daemon=True, name="obs-link").start()
        threading.Thread(target=self._worker, daemon=True, name="obs-worker").start()
        threading.Thread(target=self._thumbs_loop, daemon=True, name="obs-thumbs").start()
        threading.Thread(target=self._meters_loop, daemon=True, name="obs-meters").start()

    # ----- pub/sub for panels
    def subscribe(self):
        q = queue.Queue(maxsize=500)
        with self.lock:
            self.subs.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.subs:
                self.subs.remove(q)

    def publish(self, ev):
        with self.lock:
            subs = list(self.subs)
        for q in subs:
            try:
                q.put_nowait(ev)
            except queue.Full:
                pass

    def snapshot(self):
        with self.lock:
            st = json.loads(json.dumps(self.state))
        st["rules"] = self.config.get("scene_audio") or {}
        st["track_names"] = self.track_names(st)
        return st

    def push_state(self):
        self.publish({"type": "state", **self.snapshot()})

    @staticmethod
    def track_names(st):
        """Name recording tracks after what's on them, e.g. {2: 'Mic/Aux', 3: 'Fullscreen Apps +2'}."""
        cat = {"wasapi_input_capture": "Mic", "game_capture": "Game", "window_capture": "Game",
               "wasapi_output_capture": "Game", "dshow_input": "Capture card", "ffmpeg_source": "Media",
               "vlc_source": "Media", "browser_source": "Alerts"}
        out = {}
        for t in st["rec_tracks"]:
            labels = []
            for n, i in st["inputs"].items():
                tr = i.get("tracks", {})
                if not tr.get(str(t)) or sum(1 for v in tr.values() if v) >= 6:
                    continue  # sources sent to every track don't tell us what the track is for
                lab = cat.get(i.get("kind"), n)
                if i.get("kind") == "wasapi_process_output_capture":
                    lab = n
                if lab not in labels:
                    labels.append(lab)
            out[t] = " + ".join(labels[:3]) if labels else f"Track {t}"
        return out

    # ----- connection
    def _password(self):
        try:
            c = json.load(open(OBS_WS_CONFIG, encoding="utf-8"))
        except (OSError, ValueError):
            return None, 4455, False, False
        return c.get("server_password", ""), int(c.get("server_port", 4455)), bool(c.get("auth_required")), \
            bool(c.get("server_enabled"))

    def _set_conn(self, ok, error=""):
        with self.lock:
            changed = self.state["connected"] != ok or self.state["error"] != error
            self.state["connected"], self.state["error"] = ok, error
        if changed:
            self.push_state()

    def _run(self):
        while True:
            try:
                pw, port, auth, enabled = self._password()
                if not enabled:
                    self._set_conn(False, "OBS's websocket server is turned off (Tools → WebSocket Server Settings).")
                    time.sleep(5)
                    continue
                ws = WS("127.0.0.1", port)
                hello = json.loads(ws.recv())
                ident = {"rpcVersion": 1, "eventSubscriptions": SUBS}
                a = (hello.get("d") or {}).get("authentication")
                if a:
                    secret = base64.b64encode(hashlib.sha256((pw + a["salt"]).encode()).digest()).decode()
                    ident["authentication"] = base64.b64encode(
                        hashlib.sha256((secret + a["challenge"]).encode()).digest()).decode()
                ws.send({"op": 1, "d": ident})
                resp = json.loads(ws.recv())
                if resp.get("op") != 2:
                    raise ConnectionError("OBS didn't accept the connection (wrong websocket password?)")
                self.ws = ws
                self.log("connected to OBS websocket")
                with self.lock:
                    self.state["rec_tracks"] = read_rec_tracks()
                self._set_conn(True)
                self.tasks.put(("sync", None))
                self._reader(ws)
            except (OSError, ConnectionError, ValueError) as e:
                err = str(e)
                if isinstance(e, ConnectionRefusedError) or "10061" in err:
                    err = "OBS isn't running."
                self._set_conn(False, err)
            finally:
                if self.ws:
                    self.ws.close()
                self.ws = None
                with self.lock:
                    for ev in self.pending.values():
                        ev[1] = {"error": "disconnected"}
                        ev[0].set()
                    self.pending.clear()
            time.sleep(3)

    def _reader(self, ws):
        while True:
            m = json.loads(ws.recv())
            op, d = m.get("op"), m.get("d") or {}
            if op == 7:
                with self.lock:
                    p = self.pending.pop(d.get("requestId"), None)
                if p:
                    p[1] = d
                    p[0].set()
            elif op == 5:
                try:
                    self._event(d.get("eventType"), d.get("eventData") or {})
                except Exception as e:
                    self.log("obs event error", d.get("eventType"), repr(e))

    def request(self, rtype, data=None, timeout=5):
        ws = self.ws
        if not ws:
            raise ObsError("OBS isn't connected.")
        rid = uuid.uuid4().hex
        slot = [threading.Event(), None]
        with self.lock:
            self.pending[rid] = slot
        ws.send({"op": 6, "d": {"requestType": rtype, "requestId": rid, "requestData": data or {}}})
        if not slot[0].wait(timeout):
            with self.lock:
                self.pending.pop(rid, None)
            raise ObsError("OBS didn't answer in time.")
        d = slot[1]
        if "error" in d:
            raise ObsError("OBS disconnected.")
        st = d.get("requestStatus") or {}
        if not st.get("result"):
            raise ObsError(st.get("comment") or f"OBS error {st.get('code')}")
        return d.get("responseData") or {}

    # ----- events (reader thread: never call request() here)
    def _event(self, t, e):
        if t == "InputSettingsChanged" and e.get("inputName") in self.heard:
            self.heard.pop(e["inputName"], None)  # new file/settings: listen again
        if t == "InputVolumeMeters":
            for i in e.get("inputs", []):
                lv = i.get("inputLevelsMul") or []
                peak = max((c[1] for c in lv if len(c) > 1), default=0.0)
                self.meters[i["inputName"]] = round(mul_to_db(peak), 1)
            return
        upd = None
        with self.lock:
            st = self.state
            if t == "CurrentProgramSceneChanged":
                st["program"] = e.get("sceneName")
                upd = "program"
            elif t == "CurrentPreviewSceneChanged":
                st["preview"] = e.get("sceneName")
                self.thumb_due[e.get("sceneName")] = time.time() + 3
                upd = "state"
            elif t == "StudioModeStateChanged":
                st["studio"] = e.get("studioModeEnabled", False)
                upd = "studio"
            elif t in ("InputMuteStateChanged", "InputVolumeChanged", "InputAudioMonitorTypeChanged",
                       "InputAudioTracksChanged"):
                inp = st["inputs"].get(e.get("inputName"))
                if inp is not None:
                    if t == "InputMuteStateChanged":
                        inp["muted"] = e.get("inputMuted")
                    elif t == "InputVolumeChanged":
                        inp["db"] = round(e.get("inputVolumeDb", 0), 1)
                    elif t == "InputAudioMonitorTypeChanged":
                        inp["monitor"] = e.get("monitorType")
                    else:
                        inp["tracks"] = e.get("inputAudioTracks") or {}
                    upd = "input"
            elif t in ("SceneListChanged", "SceneCreated", "SceneRemoved", "SceneNameChanged",
                       "CurrentSceneCollectionChanged", "CurrentProfileChanged"):
                upd = "sync"
            elif t in ("InputCreated", "InputRemoved", "InputNameChanged", "SceneItemCreated", "SceneItemRemoved",
                       "InputSettingsChanged"):
                upd = "sync"
        if upd == "program":
            self.tasks.put(("program", e.get("sceneName")))
        elif upd == "sync":
            self.tasks.put(("sync", None))
        elif upd == "studio":
            self.tasks.put(("studio", None))
        elif upd:
            self.push_state()

    # ----- background work
    def _worker(self):
        while True:
            task, arg = self.tasks.get()
            try:
                if task == "sync":
                    while not self.tasks.empty() and self.tasks.queue[0][0] == "sync":
                        self.tasks.get_nowait()
                    self.sync()
                elif task == "program":
                    self.apply_rules(arg)
                    self.refresh_members()
                    self.thumb_due[arg] = time.time() + 3  # one snapshot once any fade-in is over
                    self.push_state()
                elif task == "studio":
                    r = self.request("GetCurrentPreviewScene") if self.state["studio"] else {}
                    with self.lock:
                        self.state["preview"] = r.get("sceneName") if self.state["studio"] else None
                    self.push_state()
            except ObsError as e:
                self.log("obs task error", task, str(e))
                if task == "sync" and self.ws:
                    # OBS still starting up (or busy switching collections): try again shortly
                    threading.Timer(2.0, lambda: self.tasks.put(("sync", None))).start()
            except Exception as e:
                self.log("obs task crash", task, repr(e))

    def sync(self):
        sl = self.request("GetSceneList")
        scenes = [s["sceneName"] for s in sorted(sl.get("scenes", []), key=lambda s: -s.get("sceneIndex", 0))]
        studio = self.request("GetStudioModeEnabled").get("studioModeEnabled", False)
        specials = [v for v in self.request("GetSpecialInputs").values() if v]
        inputs = {}
        for i in self.request("GetInputList").get("inputs", []):
            name = i["inputName"]
            try:
                tracks = self.request("GetInputAudioTracks", {"inputName": name}).get("inputAudioTracks", {})
            except ObsError:
                continue  # no audio
            try:
                kind = i.get("unversionedInputKind") or i.get("inputKind")
                settings = self.request("GetInputSettings", {"inputName": name}).get("inputSettings", {})
                by_file = can_make_sound(kind, settings)
                learned_silent = (self.heard.get(name) or {}).get("silent") is True
                inputs[name] = {
                    "kind": kind,
                    "audible_file": by_file,
                    "audible": name in specials or (by_file and not learned_silent),
                    "settings_window": settings.get("window", ""),
                    "muted": self.request("GetInputMute", {"inputName": name}).get("inputMuted"),
                    "db": round(self.request("GetInputVolume", {"inputName": name}).get("inputVolumeDb", 0), 1),
                    "monitor": self.request("GetInputAudioMonitorType", {"inputName": name}).get("monitorType"),
                    "tracks": tracks, "global": name in specials,
                }
            except ObsError:
                continue
        with self.lock:
            self.state.update(scenes=scenes, program=sl.get("currentProgramSceneName"),
                              preview=sl.get("currentPreviewSceneName") if studio else None,
                              studio=studio, inputs=inputs, specials=[s for s in specials if s in inputs],
                              rec_tracks=read_rec_tracks())
            for s in list(self.thumbs):
                if s not in scenes:
                    self.thumbs.pop(s, None)
        self.refresh_members()
        self.push_state()

    def _scene_inputs(self, scene, seen):
        if scene in seen:
            return set()
        seen.add(scene)
        out = set()
        try:
            items = self.request("GetSceneItemList", {"sceneName": scene}).get("sceneItems", [])
        except ObsError:
            return out
        for it in items:
            name = it.get("sourceName")
            if it.get("sourceType") == "OBS_SOURCE_TYPE_SCENE" or it.get("isGroup"):
                if it.get("isGroup"):
                    try:
                        for g in self.request("GetGroupSceneItemList", {"sceneName": name}).get("sceneItems", []):
                            out.add(g.get("sourceName"))
                    except ObsError:
                        pass
                else:
                    out |= self._scene_inputs(name, seen)
            else:
                out.add(name)
        return out

    def refresh_members(self):
        prog = self.state.get("program")
        members = self._scene_inputs(prog, set()) if prog else set()
        with self.lock:
            self.state["members"] = sorted(n for n in members if n in self.state["inputs"])

    def apply_rules(self, scene):
        rules = (self.config.get("scene_audio") or {}).get(scene) or {}
        for name, val in rules.items():
            if val in ("on", "off") and name in self.state["inputs"]:
                try:
                    self.request("SetInputMute", {"inputName": name, "inputMuted": val == "off"})
                except ObsError as e:
                    self.log("rule failed", scene, name, str(e))

    LAST_LIVE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "last_live_thumbs.json")

    def _load_last_live(self):
        try:
            return json.load(open(self.LAST_LIVE_FILE, encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_last_live(self, force=False):
        if not force and time.time() - self._last_saved < 15:
            return
        self._last_saved = time.time()
        tmp = self.LAST_LIVE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.last_live, f)
        os.replace(tmp, self.LAST_LIVE_FILE)

    def _thumbs_loop(self):
        """Scene thumbnails, only while a Scenes+ panel is open.
        Off-air scenes that render black (videos that only play when live, capture cards that switch off
        when hidden) show the last good picture from when they were live or in the Studio Mode preview."""
        while True:
            time.sleep(0.25)
            if not self.ws or not self.state["connected"]:
                continue
            with self.lock:
                watching = any(getattr(q, "thumbs", False) for q in self.subs)
                scenes = list(self.state["scenes"])
                live = {self.state.get("program"), self.state.get("preview")} - {None}
            if not watching or not scenes:
                continue
            now = time.time()
            for s in scenes:
                if self.thumb_due.get(s, 0) <= now:
                    # Still pictures: live scene refreshed once a minute, others every 2 minutes
                    self.thumb_due[s] = now + (60.0 if s in live else 120.0)
                    try:
                        img = self.request("GetSourceScreenshot", {"sourceName": s, "imageFormat": "jpg",
                                                                   "imageWidth": 320, "imageCompressionQuality": 65},
                                           timeout=4).get("imageData")
                        probe = self.request("GetSourceScreenshot", {"sourceName": s, "imageFormat": "png",
                                                                     "imageWidth": 32, "imageHeight": 18},
                                             timeout=4).get("imageData")
                    except ObsError:
                        continue
                    if not img:
                        break
                    try:
                        dark, _ = png_darkness(probe) if probe else (False, -1)
                    except Exception:
                        dark = False
                    if s in live and not dark:
                        self.last_live[s] = img
                        self._save_last_live(force=True)
                    elif s in live and dark:
                        self.thumb_due[s] = now + 2.0  # still fading in or loading: try again shortly
                    if dark and s not in live and s in self.last_live:
                        shown = {"img": self.last_live[s], "stale": True, "dark": False}
                    else:
                        shown = {"img": img, "stale": False, "dark": dark}
                    if self.thumbs.get(s) != shown:
                        self.thumbs[s] = shown
                        self.publish({"type": "thumb", "scene": s, **shown})
                    break  # one scene per tick keeps OBS load tiny

    HEARD_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "audio_heard.json")

    def _load_heard(self):
        try:
            return json.load(open(self.HEARD_FILE, encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_heard(self):
        tmp = self.HEARD_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.heard, f, indent=1)
        os.replace(tmp, self.HEARD_FILE)

    def _learn(self, dt):
        """Listen to sources in the live scene: one that plays 15 s without any sound is marked silent;
        one that makes sound is marked audible. Only media/browser sources are judged this way."""
        with self.lock:
            members = set(self.state.get("members") or [])
            inputs = self.state["inputs"]
            judged = {n for n in members if n in inputs and inputs[n]["kind"] in
                      ("ffmpeg_source", "vlc_source", "browser_source") and not inputs[n].get("muted")}
        changed = False
        for n in judged:
            secs, loud = self._listen.get(n, [0.0, -100.0])
            secs += dt
            loud = max(loud, self.meters.get(n, -100.0))
            self._listen[n] = [secs, loud]
            verdict = None
            if loud > -60:
                verdict = False
            elif secs >= 15 and inputs[n]["kind"] != "browser_source":  # alerts are silent between alerts
                verdict = True
            if verdict is not None and (self.heard.get(n) or {}).get("silent") != verdict:
                self.heard[n] = {"silent": verdict}
                with self.lock:
                    if n in inputs:
                        inputs[n]["audible"] = inputs[n].get("audible_file", True) and not verdict
                changed = True
        for n in list(self._listen):
            if n not in judged:
                self._listen.pop(n)
        if changed:
            self._save_heard()
            self.push_state()

    def _meters_loop(self):
        last = time.time()
        while True:
            time.sleep(0.1)
            now = time.time()
            if self.meters and self.state["connected"]:
                self.publish({"type": "meters", "m": dict(self.meters)})
                try:
                    self._learn(now - last)
                except Exception as e:
                    self.log("learn error", repr(e))
            last = now

    # ----- actions from panels
    def set_scene(self, scene):
        if self.state.get("studio"):
            self.request("SetCurrentPreviewScene", {"sceneName": scene})
        else:
            self.request("SetCurrentProgramScene", {"sceneName": scene})

    def transition(self):
        self.request("TriggerStudioModeTransition")

    def set_input(self, b):
        name = b.get("name")
        if name not in self.state["inputs"]:
            raise ObsError("That audio source wasn't found. It may have been renamed.")
        if "muted" in b:
            self.request("SetInputMute", {"inputName": name, "inputMuted": bool(b["muted"])})
        if "db" in b:
            self.request("SetInputVolume", {"inputName": name, "inputVolumeDb": max(-100.0, min(26.0, float(b["db"])))})
        if "monitor" in b:
            if b["monitor"] not in ("OBS_MONITORING_TYPE_NONE", "OBS_MONITORING_TYPE_MONITOR_ONLY",
                                    "OBS_MONITORING_TYPE_MONITOR_AND_OUTPUT"):
                raise ObsError("bad monitor type")
            self.request("SetInputAudioMonitorType", {"inputName": name, "monitorType": b["monitor"]})
        if "track" in b:
            t = str(int(b["track"]))
            self.request("SetInputAudioTracks", {"inputName": name, "inputAudioTracks": {t: bool(b["on"])}})

    # ----- one-click helpers: games, Discord, screen regions
    def _unique_name(self, base):
        names = {i["inputName"] for i in self.request("GetInputList").get("inputs", [])}
        names |= set(self.state.get("scenes") or [])
        if base not in names:
            return base
        n = 2
        while f"{base} {n}" in names:
            n += 1
        return f"{base} {n}"

    def _canvas(self):
        v = self.request("GetVideoSettings")
        return v.get("baseWidth", 1920), v.get("baseHeight", 1080)

    def target_scene(self, scene=None):
        if scene and scene in self.state.get("scenes", []):
            return scene
        return self.state.get("preview") if self.state.get("studio") else self.state.get("program")

    def _track_for(self, label, fallback):
        names = self.track_names(self.snapshot())
        for t, n in names.items():
            if n == label:
                return int(t)
        return fallback

    def _set_tracks(self, name, on_tracks):
        self.request("SetInputAudioTracks", {"inputName": name, "inputAudioTracks":
                                             {str(t): t in on_tracks for t in range(1, 7)}})

    def _place_below_overlays(self, scene, item_id):
        """Put a new game/screen item under alerts and other browser overlays, not on top of them."""
        items = self.request("GetSceneItemList", {"sceneName": scene}).get("sceneItems", [])
        overlay_idx = [it["sceneItemIndex"] for it in items
                       if it.get("inputKind") in ("browser_source",) and it["sceneItemId"] != item_id]
        if overlay_idx:
            self.request("SetSceneItemIndex", {"sceneName": scene, "sceneItemId": item_id,
                                               "sceneItemIndex": min(overlay_idx)})

    def game_sources(self):
        out = []
        for i in self.request("GetInputList", {"inputKind": "game_capture"}).get("inputs", []):
            s = self.request("GetInputSettings", {"inputName": i["inputName"]}).get("inputSettings", {})
            from winapps import obs_window_exe
            out.append({"name": i["inputName"], "mode": s.get("capture_mode", "any_fullscreen"),
                        "exe": obs_window_exe(s.get("window", "")), "audio": bool(s.get("capture_audio"))})
        return out

    def add_game(self, b):
        window = b.get("window") or ""
        if window.count(":") < 2:
            raise ObsError("Pick a game from the list.")
        settings = {"capture_mode": "window", "window": window, "priority": 2, "capture_audio": True}
        if b.get("replace"):
            self.request("SetInputSettings", {"inputName": b["replace"], "inputSettings": settings})
            return {"name": b["replace"], "replaced": True}
        scene = self.target_scene(b.get("scene"))
        title = (b.get("title") or "Game").strip()[:32]
        name = self._unique_name(f"Game - {title}")
        r = self.request("CreateInput", {"sceneName": scene, "inputName": name, "inputKind": "game_capture",
                                         "inputSettings": settings, "sceneItemEnabled": True})
        cw, ch = self._canvas()
        self.request("SetSceneItemTransform", {"sceneName": scene, "sceneItemId": r["sceneItemId"],
                                               "sceneItemTransform": {"boundsType": "OBS_BOUNDS_SCALE_INNER",
                                                                      "boundsWidth": cw, "boundsHeight": ch,
                                                                      "boundsAlignment": 0, "alignment": 5,
                                                                      "positionX": 0, "positionY": 0}})
        self._place_below_overlays(scene, r["sceneItemId"])
        self._set_tracks(name, {1, self._track_for("Game", 3)})
        self.request("SetInputAudioMonitorType", {"inputName": name, "monitorType": "OBS_MONITORING_TYPE_NONE"})
        return {"name": name, "scene": scene}

    def discord_status(self):
        import winapps
        wins = [w for w in winapps.list_windows() if w["exe"].lower() == "discord.exe"]
        srcs = []
        for i in self.request("GetInputList", {"inputKind": "wasapi_process_output_capture"}).get("inputs", []):
            s = self.request("GetInputSettings", {"inputName": i["inputName"]}).get("inputSettings", {})
            if winapps.obs_window_exe(s.get("window", "")).lower() == "discord.exe":
                scenes = [sc for sc in self.state.get("scenes", [])
                          if i["inputName"] in self._scene_inputs(sc, set())]
                srcs.append({"name": i["inputName"], "priority": s.get("priority", 0), "scenes": scenes})
        return {"running": bool(wins), "window": wins[0]["window"] if wins else "", "sources": srcs,
                "scene": self.target_scene()}

    def add_discord(self, b):
        st = self.discord_status()
        scene = self.target_scene(b.get("scene"))
        for s in st["sources"]:  # fix matching on every Discord source
            fix = {"priority": 2}
            if st["window"]:
                fix["window"] = st["window"]
            self.request("SetInputSettings", {"inputName": s["name"], "inputSettings": fix})
        if st["sources"]:
            src = st["sources"][0]
            if scene not in src["scenes"]:
                self.request("CreateSceneItem", {"sceneName": scene, "sourceName": src["name"]})
                return {"name": src["name"], "scene": scene, "added": True}
            return {"name": src["name"], "scene": scene, "added": False}
        if not st["window"]:
            raise ObsError("Open Discord first, then try again.")
        name = self._unique_name("Discord")
        self.request("CreateInput", {"sceneName": scene, "inputName": name,
                                     "inputKind": "wasapi_process_output_capture",
                                     "inputSettings": {"window": st["window"], "priority": 2},
                                     "sceneItemEnabled": True})
        self._set_tracks(name, {1, self._track_for("Discord", 4)})
        return {"name": name, "scene": scene, "added": True, "created": True}

    def add_region(self, b):
        """Run the drag-to-select overlay, then add (or update) a cropped Display Capture."""
        import subprocess
        import sys as _sys
        import winapps
        here = os.path.dirname(os.path.abspath(__file__))
        exe = _sys.executable
        if exe.lower().endswith("pythonw.exe"):
            alt = exe[:-11] + "python.exe"
            exe = alt if os.path.exists(alt) else exe
        if isinstance(b.get("selection"), dict):  # area already chosen (used for testing / re-applying)
            sel = b["selection"]
        else:
            p = subprocess.run([exe, os.path.join(here, "region_picker.py")], capture_output=True, text=True,
                               timeout=130, creationflags=0x08000000)
            try:
                sel = json.loads((p.stdout or "").strip().splitlines()[-1])
            except (ValueError, IndexError):
                raise ObsError("The region picker didn't start: " + (p.stderr or "")[-200:])
        if sel.get("cancel"):
            return {"cancelled": True}
        mons = winapps.list_monitors()

        def overlap(m):
            ox = max(0, min(sel["x"] + sel["w"], m["x"] + m["w"]) - max(sel["x"], m["x"]))
            oy = max(0, min(sel["y"] + sel["h"], m["y"] + m["h"]) - max(sel["y"], m["y"]))
            return ox * oy
        mon = max(mons, key=overlap)
        x0, y0 = max(sel["x"], mon["x"]), max(sel["y"], mon["y"])
        x1 = min(sel["x"] + sel["w"], mon["x"] + mon["w"])
        y1 = min(sel["y"] + sel["h"], mon["y"] + mon["h"])
        rw, rh = x1 - x0, y1 - y0
        crop = {"cropLeft": x0 - mon["x"], "cropTop": y0 - mon["y"],
                "cropRight": mon["x"] + mon["w"] - x1, "cropBottom": mon["y"] + mon["h"] - y1}
        scene = self.target_scene(b.get("scene"))
        if b.get("replace"):
            name = b["replace"]
            items = [it for it in self.request("GetSceneItemList", {"sceneName": scene}).get("sceneItems", [])
                     if it["sourceName"] == name]
            if not items:
                raise ObsError(f"'{name}' isn't in the scene '{scene}'.")
            item_id = items[0]["sceneItemId"]
        else:
            name = self._unique_name("Screen Region")
            r = self.request("CreateInput", {"sceneName": scene, "inputName": name, "inputKind": "monitor_capture",
                                             "inputSettings": {"capture_cursor": True, "method": 0},
                                             "sceneItemEnabled": True})
            item_id = r["sceneItemId"]
        # point the capture at the right monitor ("... @ x,y" in OBS's monitor list)
        opts = self.request("GetInputPropertiesListPropertyItems",
                            {"inputName": name, "propertyName": "monitor_id"}).get("propertyItems", [])
        want = f"@ {mon['x']},{mon['y']}"
        pick = next((o for o in opts if want in o.get("itemName", "")), None) or \
            next((o for o in opts if mon.get("primary") and "Primary" in o.get("itemName", "")), None)
        if pick:
            self.request("SetInputSettings", {"inputName": name, "inputSettings": {"monitor_id": pick["itemValue"]}})
        cw, ch = self._canvas()
        scale = min(1.0, cw / rw, ch / rh)
        self.request("SetSceneItemTransform", {"sceneName": scene, "sceneItemId": item_id, "sceneItemTransform": {
            **crop, "boundsType": "OBS_BOUNDS_NONE", "alignment": 5, "rotation": 0,
            "scaleX": scale, "scaleY": scale,
            "positionX": round((cw - rw * scale) / 2), "positionY": round((ch - rh * scale) / 2)}})
        if not b.get("replace"):
            self._place_below_overlays(scene, item_id)
        regions = dict(self.config.get("regions") or {})
        regions[name] = {"x": x0, "y": y0, "w": rw, "h": rh}
        self.config.update(regions=regions)
        return {"name": name, "scene": scene, "w": rw, "h": rh, "monitor": mon["device"]}

    def region_sources(self, scene=None):
        scene = self.target_scene(scene)
        items = self.request("GetSceneItemList", {"sceneName": scene}).get("sceneItems", [])
        return [it["sourceName"] for it in items if it.get("inputKind") == "monitor_capture"]

    def set_rule(self, scene, name, val):
        rules = dict(self.config.get("scene_audio") or {})
        sc = dict(rules.get(scene) or {})
        if val in ("on", "off"):
            sc[name] = val
        else:
            sc.pop(name, None)
        if sc:
            rules[scene] = sc
        else:
            rules.pop(scene, None)
        self.config.update(scene_audio=rules)
        if scene == self.state.get("program"):
            self.apply_rules(scene)
        self.push_state()
