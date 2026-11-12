"""
Stream quality: picks good YouTube settings for this PC and connection, applies them to OBS, and checks every stream
afterwards (dropped frames, encoder overload, YouTube's stream health) to adjust the bitrate for next time.

Only ever changes OBS while nothing is streaming or recording. The settings from before the first change are kept
so they can be put back with Undo.
"""
import glob
import json
import os
import threading
import time
import urllib.request

import obslink

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "data", "quality.json")
LOG_DIR = os.path.join(obslink.OBS_DIR, "logs")

# encoder ids OBS uses, best first within each codec (hardware before software)
ENCODERS = {
    "av1": ["obs_nvenc_av1_tex", "jim_av1_nvenc", "av1_texture_amf", "obs_qsv11_av1"],
    "hevc": ["obs_nvenc_hevc_tex", "jim_hevc_nvenc", "h265_texture_amf", "obs_qsv11_hevc"],
    "h264": ["obs_nvenc_h264_tex", "jim_nvenc", "h264_texture_amf", "obs_qsv11_v2", "obs_x264"],
}
CODEC_NAMES = {"av1": "AV1", "hevc": "HEVC", "h264": "H.264"}
MAKERS = {"nvenc": "NVIDIA", "amf": "AMD", "qsv": "Intel", "x264": "your processor"}
# Simple output mode uses short names
SIMPLE_IDS = {"obs_nvenc_av1_tex": "nvenc_av1", "jim_av1_nvenc": "nvenc_av1", "obs_nvenc_hevc_tex": "nvenc_hevc",
              "jim_hevc_nvenc": "nvenc_hevc", "obs_nvenc_h264_tex": "nvenc", "jim_nvenc": "nvenc",
              "av1_texture_amf": "amd_av1", "h265_texture_amf": "amd_hevc", "h264_texture_amf": "amd",
              "obs_qsv11_av1": "qsv_av1", "obs_qsv11_hevc": "qsv_hevc", "obs_qsv11_v2": "qsv", "obs_x264": "x264"}

# Bitrates (kbps) for 60 fps, from YouTube's live encoder table: what we aim for, and YouTube's minimum.
# AV1/HEVC need far less than H.264 for the same picture.
TARGET = {"efficient": {720: 5000, 1080: 10000, 1440: 18000}, "h264": {720: 6000, 1080: 12000, 1440: 24000}}
MINIMUM = {"efficient": {720: 2000, 1080: 4000, 1440: 6000}, "h264": {720: 3000, 1080: 6000, 1440: 8000}}
PRESETS = {
    "recommended": {"height": 1080, "label": "Recommended for my PC"},
    "sharp": {"height": 1440, "label": "Sharper on YouTube (1440p)"},
    "light": {"height": 720, "label": "Light (720p)"},
}
# Twitch takes H.264 only through OBS's normal stream output and caps most channels at about 6 Mbps / 1080p
TWITCH_TARGET = {720: 4500, 1080: 6000}
UPLOAD_SHARE = 0.7       # use at most this much of the measured upload, leaving room for everything else
AUDIO_KBPS = 160         # OBS's YouTube service maximum


def _family(codec):
    return "h264" if codec == "h264" else "efficient"


def _maker(enc_id):
    for k, v in MAKERS.items():
        if k in enc_id:
            return v
    return ""


def _codec_of(enc_id):
    for codec, ids in ENCODERS.items():
        if enc_id in ids:
            return codec
    e = (enc_id or "").lower()
    return "av1" if "av1" in e else "hevc" if ("hevc" in e or "265" in e) else "h264"


def _latest_obs_log():
    logs = sorted(glob.glob(os.path.join(LOG_DIR, "*.txt")), key=os.path.getmtime)
    return logs[-1] if logs else None


def available_encoders():
    """Video encoders OBS lists as available in its newest log (only ones that actually work on this PC)."""
    path, found, inside = _latest_obs_log(), [], False
    if not path:
        return found
    try:
        for line in open(path, encoding="utf-8", errors="replace"):
            text = line.split(": ", 1)[-1].rstrip("\n")
            if "Video Encoders:" in text:
                inside = True
                continue
            if inside:
                s = text.strip()
                if s.startswith("- "):
                    found.append(s[2:].split(" ", 1)[0])
                elif s:   # next section
                    break
    except OSError:
        pass
    return found


def _load():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(d):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, STATE_FILE)


class QualityError(Exception):
    pass


# --------------------------------------------------------------------------- M-Lab upload test (ndt7)
# Protocol: https://github.com/m-lab/ndt-server/blob/main/spec/ndt7-protocol.md
# One WebSocket to a nearby M-Lab server; the client sends binary messages for up to 10 seconds and the server
# replies with JSON measurements of what it actually received (more accurate than counting what we sent).
MLAB_LOCATE = "https://locate.measurementlab.net/v2/nearest/ndt/ndt7"
NDT7_PROTOCOL = "net.measurementlab.ndt.v7"


def _ws_frame(opcode, payload):
    """A masked client frame. Masking 1 MB in pure Python is slow, so each payload size is masked once and the frame
    is reused: the mask only protects plain-HTTP proxies, and this connection is TLS end to end."""
    n = len(payload)
    head = bytes([0x80 | opcode])
    if n < 126:
        head += bytes([0x80 | n])
    elif n < 65536:
        head += bytes([0x80 | 126]) + n.to_bytes(2, "big")
    else:
        head += bytes([0x80 | 127]) + n.to_bytes(8, "big")
    mask = os.urandom(4)
    m = int.from_bytes((mask * (n // 4 + 1))[:n], "big")
    masked = (int.from_bytes(payload, "big") ^ m).to_bytes(n, "big") if n else b""
    return head + mask + masked


def _ws_read_frame(sock):
    def need(k):
        b = b""
        while len(b) < k:
            c = sock.recv(k - len(b))
            if not c:
                raise ConnectionError("server closed the connection")
            b += c
        return b
    h = need(2)
    op, n = h[0] & 0x0F, h[1] & 0x7F
    if n == 126:
        n = int.from_bytes(need(2), "big")
    elif n == 127:
        n = int.from_bytes(need(8), "big")
    if h[1] & 0x80:
        need(4)   # servers don't mask; skip if one does
    return op, need(n) if n else b""


def mlab_upload(seconds=10.0, version="0.1"):
    """Returns (kbps, "server city") measured by the M-Lab server."""
    import socket
    import ssl
    import urllib.parse
    q = urllib.parse.urlencode({"client_name": "obsplit", "client_version": version})
    req = urllib.request.Request(MLAB_LOCATE + "?" + q, headers={"User-Agent": "OBSplit/" + version})
    with urllib.request.urlopen(req, timeout=10) as r:
        loc = json.load(r)
    results = loc.get("results") or []
    if not results:
        raise QualityError("M-Lab didn't offer a test server right now. Try again in a minute.")
    target = results[0]
    url = (target.get("urls") or {}).get("wss:///ndt/v7/upload")
    if not url:
        raise QualityError("M-Lab's answer had no upload test address.")
    city = ", ".join(x for x in ((target.get("location") or {}).get("city"),
                                 (target.get("location") or {}).get("country")) if x)
    u = urllib.parse.urlsplit(url)
    path = u.path + "?" + u.query + "&" + q
    raw = socket.create_connection((u.hostname, u.port or 443), timeout=10)
    sock = ssl.create_default_context().wrap_socket(raw, server_hostname=u.hostname)
    try:
        import base64
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {u.hostname}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                      f"Sec-WebSocket-Protocol: {NDT7_PROTOCOL}\r\nUser-Agent: OBSplit/{version}\r\n\r\n").encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            c = sock.recv(4096)
            if not c:
                raise ConnectionError("no answer from the test server")
            resp += c
        if b" 101 " not in resp.split(b"\r\n", 1)[0]:
            raise ConnectionError("test server refused: " + resp.split(b"\r\n", 1)[0].decode(errors="replace"))
        import select
        size, sent, frames = 1 << 13, 0, {}
        best = None            # latest server-side measurement: (bytes received, microseconds)
        start = time.time()

        def drain():
            nonlocal best
            while sock.pending() or select.select([sock], [], [], 0)[0]:
                op, data = _ws_read_frame(sock)
                if op == 1:   # text: a measurement
                    try:
                        m = json.loads(data)
                    except ValueError:
                        continue
                    t = m.get("TCPInfo") or {}
                    a = m.get("AppInfo") or {}
                    if t.get("BytesReceived") and t.get("ElapsedTime"):
                        best = (t["BytesReceived"], t["ElapsedTime"])
                    elif a.get("NumBytes") and a.get("ElapsedTime"):
                        best = (a["NumBytes"], a["ElapsedTime"])
                elif op == 8:
                    raise StopIteration

        try:
            while time.time() - start < seconds:
                f = frames.get(size) or frames.setdefault(size, _ws_frame(2, os.urandom(size)))
                sock.sendall(f)
                sent += size
                if size < (1 << 20) and sent >= 16 * size:   # grow messages as the connection proves fast
                    size <<= 1
                drain()
            sock.sendall(_ws_frame(8, (1000).to_bytes(2, "big")))
            end = time.time() + 3
            sock.settimeout(1)
            while time.time() < end:
                drain()
                time.sleep(0.05)
        except (StopIteration, socket.timeout, ssl.SSLError, ConnectionError):
            pass
        elapsed = time.time() - start
    finally:
        try:
            sock.close()
        except OSError:
            pass
    if best:
        return int(best[0] * 8 / (best[1] / 1e6) / 1000), city
    if sent:
        return int(sent * 8 / max(0.1, elapsed) / 1000), city
    raise QualityError("The upload test didn't send anything.")


class Quality:
    def __init__(self, obs, log, youtube_health, platform=lambda: "youtube"):
        self.obs, self.log, self.youtube_health, self.platform = obs, log, youtube_health, platform
        self.lock = threading.Lock()
        self.d = _load()
        self.d.setdefault("auto", True)
        self.watch = None          # stats of the stream in progress
        self.testing = False

    # ------------------------------------------------------------------ reading OBS
    def _param(self, cat, name):
        try:
            return self.obs.request("GetProfileParameter", {"parameterCategory": cat, "parameterName": name}
                                    ).get("parameterValue")
        except obslink.ObsError:
            return None

    def _set_param(self, cat, name, value):
        # None removes the setting again (OBS then uses its default), so Undo leaves no trace
        self.obs.request("SetProfileParameter", {"parameterCategory": cat, "parameterName": name,
                                                 "parameterValue": None if value is None else str(value)})

    def _encoder_param(self):
        mode = self._param("Output", "Mode") or "Simple"
        return (self._param("AdvOut", "Encoder") if mode == "Advanced" else self._param("SimpleOutput", "StreamEncoder")) or ""

    def _session_encoder(self):
        """The stream encoder this OBS session started with. OBS only switches encoders when it starts (or when its
        Settings window is saved), so a different saved encoder means a restart is needed."""
        session = os.path.basename(_latest_obs_log() or "")
        with self.lock:
            if self.d.get("session") != session:
                self.d["session"], self.d["running_encoder"] = session, self._encoder_param()
                _save(self.d)
            return self.d.get("running_encoder") or ""

    def restart_needed(self):
        try:
            return self._encoder_param() != self._session_encoder()
        except obslink.ObsError:
            return False

    @staticmethod
    def _encoder_json_path():
        return os.path.join(os.path.dirname(obslink.profile_ini()), "streamEncoder.json")

    def _encoder_json(self):
        try:
            with open(self._encoder_json_path(), encoding="utf-8-sig") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _write_encoder_json(self, data):
        path = self._encoder_json_path()
        tmp = path + ".obsplit.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)

    def busy(self):
        """What's running that settings can't be changed under (None = free)."""
        try:
            if self.obs.request("GetStreamStatus").get("outputActive"):
                return "streaming"
            if self.obs.request("GetRecordStatus").get("outputActive"):
                return "recording"
            if self.obs.request("GetVirtualCamStatus").get("outputActive"):
                return "the virtual camera"
        except obslink.ObsError as e:
            raise QualityError(str(e))
        return None

    def current(self):
        mode = self._param("Output", "Mode") or "Simple"
        adv = mode == "Advanced"
        enc = self._param("AdvOut", "Encoder") if adv else self._param("SimpleOutput", "StreamEncoder")
        ej = self._encoder_json() if adv else {}
        kbps = int(ej.get("bitrate") or 0) if adv else int(self._param("SimpleOutput", "VBitrate") or 0)
        try:
            v = self.obs.request("GetVideoSettings")
        except obslink.ObsError as e:
            raise QualityError(str(e))
        fps = v.get("fpsNumerator", 0) / max(1, v.get("fpsDenominator", 1))
        return {"mode": mode, "encoder": enc or "", "codec": _codec_of(enc or ""), "bitrate": kbps,
                "keyint": ej.get("keyint_sec") if adv else 2, "rate_control": ej.get("rate_control", "CBR") if adv else "CBR",
                "base": [v.get("baseWidth"), v.get("baseHeight")], "output": [v.get("outputWidth"), v.get("outputHeight")],
                "fps": round(fps, 2), "color_range": self._param("Video", "ColorRange") or "Partial",
                "dynamic": (self._param("Output", "DynamicBitrate") or "false").lower() == "true"}

    # ------------------------------------------------------------------ planning
    def best_encoder(self, prefer=("av1", "hevc", "h264")):
        have = set(available_encoders())
        for codec in prefer:
            for e in ENCODERS[codec]:
                if e in have:
                    return e, codec
        return "obs_x264", "h264"

    def plan(self, preset, cur=None):
        p = PRESETS[preset]
        h = p["height"]
        notes = []
        if self.platform() == "twitch":
            enc, codec = self.best_encoder(prefer=("h264",))
            if h > 1080:
                h = 1080
                notes.append("Twitch doesn't take 1440p from OBS's normal stream, so this is the same as Recommended.")
            kbps = TWITCH_TARGET[h]
        else:
            enc, codec = self.best_encoder()
            kbps = TARGET[_family(codec)][h]
        fam = _family(codec)
        up = self.d.get("upload_kbps")
        if up:
            cap = int(up * UPLOAD_SHARE / 500) * 500
            if cap < kbps:
                kbps = cap
                notes.append(f"Limited to {kbps / 1000:g} Mbps by your upload speed.")
        floor = MINIMUM[fam][h]
        too_slow = bool(up) and kbps < floor
        if too_slow:
            notes = [f"Your upload is too slow for {h}p: it needs at least {floor / 1000:g} Mbps, "
                     f"and only about {int(up * UPLOAD_SHARE / 500) * 500 / 1000:g} Mbps is safe on your connection."]
            kbps = floor
        if preset == "recommended" and self.d.get("adjusted_kbps") and self.d.get("preset") == "recommended":
            kbps = min(kbps, self.d["adjusted_kbps"])
        elif preset == self.d.get("preset") and self.d.get("adjusted_kbps"):
            kbps = min(kbps, self.d["adjusted_kbps"])
        bw, bh = (cur or {}).get("base") or [1920, 1080]
        bw, bh = bw or 1920, bh or 1080
        ow = int(round(h * bw / bh / 2)) * 2
        twitch = self.platform() == "twitch"
        if preset == "sharp" and not up and not twitch:
            notes.append("Needs roughly 20 Mbps or more of upload. Test your upload first if you're not sure.")
        if preset == "sharp" and codec == "h264" and not twitch:
            notes.append("Your graphics card can't send AV1 or HEVC, so 1440p needs a lot of upload with H.264.")
        return {"preset": preset, "label": p["label"], "encoder": enc, "codec": codec,
                "codec_name": CODEC_NAMES[codec], "maker": _maker(enc), "width": ow, "height": h, "fps": 60,
                "bitrate": kbps, "notes": notes, "too_slow": too_slow,
                "summary": f"{h}p60 · {CODEC_NAMES[codec]} · {kbps / 1000:g} Mbps"}

    def status(self):
        try:
            cur = self.current()
            busy = self.busy()
            err = None
        except QualityError as e:
            cur, busy, err = None, None, str(e)
        restart = self.restart_needed() if cur else False
        with self.lock:
            d = dict(self.d)
        issues = []
        plans = {k: self.plan(k, cur) for k in PRESETS} if cur else {}
        preset = d.get("preset")
        if cur:
            site = "Twitch" if self.platform() == "twitch" else "YouTube"
            if cur["color_range"].lower() == "full":
                issues.append(f"Color range is Full. {site} expects Limited, so dark and bright areas can look wrong.")
            if cur["keyint"] not in (None, 0, 1, 2, "1", "2") or cur["keyint"] in (0, "0"):
                issues.append(f"Keyframes aren't every 2 seconds, which {site} asks for.")
            if cur["rate_control"] != "CBR":
                issues.append(f"Bitrate isn't constant (CBR), which {site} asks for.")
            if site == "Twitch" and cur["codec"] != "h264":
                issues.append(f"Twitch only takes H.264 from OBS, but OBS is set to {CODEC_NAMES[cur['codec']]}. "
                              "Apply a choice below (then restart OBS) before streaming to Twitch.")
            # a choice applied for the other platform doesn't count as "in use" here
            p = plans.get(preset)
            if p and (p["encoder"] != cur["encoder"] or (cur["bitrate"] or 0) > p["bitrate"]):
                preset = None
        return {"error": err, "busy": busy, "current": cur, "issues": issues,
                "current_label": self._describe(cur) if cur else "",
                "plans": plans,
                "preset": preset, "upload_kbps": d.get("upload_kbps"), "upload_at": d.get("upload_at"),
                "upload_source": d.get("upload_source") or ("test" if d.get("upload_kbps") else None),
                "auto": d.get("auto", True), "has_backup": bool(d.get("backup")),
                "restart_needed": restart, "report": d.get("report"),
                "testing": self.testing, "platform": self.platform()}

    @staticmethod
    def _describe(cur):
        ow, oh = cur["output"]
        return (f"{oh}p{int(cur['fps']) if cur['fps'] == int(cur['fps']) else cur['fps']} · "
                f"{CODEC_NAMES[cur['codec']]} ({_maker(cur['encoder']) or cur['encoder']}) · "
                f"{(cur['bitrate'] or 0) / 1000:g} Mbps")

    # ------------------------------------------------------------------ applying
    def _snapshot(self, cur):
        return {"mode": cur["mode"], "adv_encoder": self._param("AdvOut", "Encoder"),
                "simple_encoder": self._param("SimpleOutput", "StreamEncoder"),
                "simple_vbitrate": self._param("SimpleOutput", "VBitrate"),
                "adv_track1": self._param("AdvOut", "Track1Bitrate"),
                "simple_abitrate": self._param("SimpleOutput", "ABitrate"),
                "dynamic": self._param("Output", "DynamicBitrate"),
                "color_range": self._param("Video", "ColorRange"),
                "color_space": self._param("Video", "ColorSpace"),
                "fps_fields": {k: self._param("Video", k) for k in ("FPSType", "FPSCommon", "FPSInt", "FPSNum", "FPSDen")},
                "encoder_json": self._encoder_json(),
                "video": self.obs.request("GetVideoSettings"), "at": time.strftime("%Y-%m-%d %H:%M")}

    def _encoder_settings(self, enc, codec, kbps, old):
        s = dict(old or {})
        s.update({"rate_control": "CBR", "bitrate": int(kbps), "keyint_sec": 2})
        if "nvenc" in enc:
            s.update({"preset2": s.get("preset2") or "p5", "tune": "hq", "multipass": "qres",
                      "profile": "high" if codec == "h264" else "main"})
        elif "amf" in enc:
            s.update({"preset": "quality", "profile": "high" if codec == "h264" else "main"})
        elif "qsv" in enc:
            s.update({"target_usage": s.get("target_usage") or "TU4", "profile": "high" if codec == "h264" else "main"})
        elif enc == "obs_x264":
            s.update({"preset": s.get("preset") or "veryfast", "profile": "high"})
        return s

    def _set_bitrate(self, cur, kbps, enc=None, codec=None):
        if cur["mode"] == "Advanced":
            enc = enc or cur["encoder"]
            self._write_encoder_json(self._encoder_settings(enc, codec or cur["codec"], kbps, self._encoder_json()))
        else:
            self._set_param("SimpleOutput", "VBitrate", int(kbps))

    def apply(self, preset):
        if preset not in PRESETS:
            raise QualityError("Unknown choice.")
        busy = self.busy()
        if busy:
            raise QualityError(f"Stop {busy} first, then apply.")
        cur = self.current()
        plan = self.plan(preset, cur)
        self._session_encoder()            # remember what this session runs before changing anything
        with self.lock:
            if not self.d.get("backup"):
                self.d["backup"] = self._snapshot(cur)
                _save(self.d)
        if cur["mode"] == "Advanced":
            if (self._param("AdvOut", "Encoder") or "") != plan["encoder"]:
                self._set_param("AdvOut", "Encoder", plan["encoder"])
            self._set_param("AdvOut", "Track1Bitrate", AUDIO_KBPS)
        else:
            simple = SIMPLE_IDS.get(plan["encoder"], "x264")
            if (self._param("SimpleOutput", "StreamEncoder") or "") != simple:
                self._set_param("SimpleOutput", "StreamEncoder", simple)
            self._set_param("SimpleOutput", "ABitrate", AUDIO_KBPS)
        self._set_bitrate(cur, plan["bitrate"], plan["encoder"], plan["codec"])
        self._set_param("Output", "DynamicBitrate", "true")    # OBS lowers the bitrate itself if the connection struggles
        self._set_param("Video", "ColorRange", "Partial")       # "Limited", what YouTube expects
        self._set_param("Video", "ColorSpace", "709")
        self.obs.request("SetVideoSettings", {      # also makes OBS reload the color settings now
            "baseWidth": cur["base"][0], "baseHeight": cur["base"][1],
            "outputWidth": plan["width"], "outputHeight": plan["height"], "fpsNumerator": 60, "fpsDenominator": 1})
        # OBS's websocket stores the frame rate as a fraction; keep it as plain "60" in OBS's Settings window
        self._set_param("Video", "FPSType", 0)
        self._set_param("Video", "FPSCommon", 60)
        restart = self.restart_needed()
        with self.lock:
            self.d.update(preset=preset, applied=plan, adjusted_kbps=None, applied_at=time.strftime("%Y-%m-%d %H:%M"))
            _save(self.d)
        self.log("stream quality applied", plan["summary"], "(restart OBS to switch encoder)" if restart else "")
        return {"plan": plan, "restart_needed": restart}

    def undo(self):
        b = self.d.get("backup")
        if not b:
            raise QualityError("Nothing to undo.")
        busy = self.busy()
        if busy:
            raise QualityError(f"Stop {busy} first, then undo.")
        self._session_encoder()
        if b.get("adv_encoder") and (self._param("AdvOut", "Encoder") or "") != b["adv_encoder"]:
            self._set_param("AdvOut", "Encoder", b["adv_encoder"])
        if b.get("simple_encoder") and (self._param("SimpleOutput", "StreamEncoder") or "") != b["simple_encoder"]:
            self._set_param("SimpleOutput", "StreamEncoder", b["simple_encoder"])
        for cat, name, key in (("SimpleOutput", "VBitrate", "simple_vbitrate"), ("AdvOut", "Track1Bitrate", "adv_track1"),
                               ("SimpleOutput", "ABitrate", "simple_abitrate"), ("Output", "DynamicBitrate", "dynamic"),
                               ("Video", "ColorRange", "color_range"), ("Video", "ColorSpace", "color_space")):
            if key in b:
                self._set_param(cat, name, b[key])
        if b.get("encoder_json") is not None:
            self._write_encoder_json(b["encoder_json"])
        v = b.get("video") or {}
        if v:
            self.obs.request("SetVideoSettings", {k: v[k] for k in ("baseWidth", "baseHeight", "outputWidth",
                                                                     "outputHeight", "fpsNumerator", "fpsDenominator")
                                                  if k in v})
        for k, val in (b.get("fps_fields") or {}).items():   # put the frame-rate fields back exactly as they were
            self._set_param("Video", k, val)
        restart = self.restart_needed()
        with self.lock:
            self.d.update(backup=None, preset=None, applied=None, adjusted_kbps=None)
            _save(self.d)
        self.log("stream quality: put back the settings from", b.get("at"))
        return {"restart_needed": restart}

    def set_upload(self, mbps):
        """Upload speed the user typed in from a speed test they trust (e.g. their provider's or speedtest.net)."""
        try:
            mbps = float(mbps)
        except (TypeError, ValueError):
            raise QualityError("Enter your upload speed in Mbps, for example 35.")
        if not 0.5 <= mbps <= 10000:
            raise QualityError("That upload speed doesn't look right. Enter it in Mbps, for example 35.")
        with self.lock:
            self.d.update(upload_kbps=int(mbps * 1000), upload_at=time.strftime("%Y-%m-%d %H:%M"), upload_source="you")
            _save(self.d)
        return {"upload_kbps": int(mbps * 1000)}

    def set_auto(self, on):
        with self.lock:
            self.d["auto"] = bool(on)
            _save(self.d)

    # ------------------------------------------------------------------ upload test
    def test_upload(self):
        """Measures upload speed with M-Lab's ndt7 test (the one Google Search's speed test uses), against a nearby
        M-Lab server. A speed the user typed in is kept unless the test finds more."""
        if self.busy() == "streaming":
            raise QualityError("Stop streaming first: the test would slow your stream down.")
        if self.testing:
            raise QualityError("A test is already running.")
        self.testing = True
        try:
            kbps, where = mlab_upload()
        except QualityError:
            raise
        except Exception as e:
            raise QualityError("The upload test couldn't finish (" + str(e)[:100] + ").")
        finally:
            self.testing = False
        with self.lock:
            typed = self.d.get("upload_source") == "you" and (self.d.get("upload_kbps") or 0) > kbps
            if not typed:
                self.d.update(upload_kbps=kbps, upload_at=time.strftime("%Y-%m-%d %H:%M"), upload_source="test")
            self.d["upload_tested_kbps"] = kbps
            self.d["upload_server"] = where
            _save(self.d)
        self.log("upload test", kbps, "kbps via M-Lab", where)
        return {"upload_kbps": kbps, "kept_typed": typed, "server": where}

    # ------------------------------------------------------------------ watching streams
    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="quality").start()

    def _loop(self):
        while True:
            try:
                self._tick()
            except Exception as e:   # never let the watcher die
                if not isinstance(e, obslink.ObsError):
                    self.log("quality watch error", repr(e))
            time.sleep(10)

    def _tick(self):
        s = self.obs.request("GetStreamStatus")
        live = s.get("outputActive")
        if live:
            st = self.obs.request("GetStats")
            if self.watch is None:
                self.watch = {"start": time.time(), "enc0": st.get("outputSkippedFrames", 0),
                              "encT0": st.get("outputTotalFrames", 0), "cong": [], "health": [],
                              "bitrate": self.d.get("applied", {}).get("bitrate") if self.d.get("applied") else None}
            w = self.watch
            w["drop"], w["total"] = s.get("outputSkippedFrames", 0), s.get("outputTotalFrames", 0)
            w["enc"] = st.get("outputSkippedFrames", 0) - w["enc0"]
            w["encT"] = st.get("outputTotalFrames", 0) - w["encT0"]
            w["cong"].append(float(s.get("outputCongestion") or 0))
            h = self.youtube_health()
            if h:
                w["health"].append(h)
            w["reconnecting"] = w.get("reconnecting", 0) + (1 if s.get("outputReconnecting") else 0)
        elif self.watch is not None:
            w, self.watch = self.watch, None
            self._finish(w)

    def _finish(self, w):
        mins = (time.time() - w["start"]) / 60
        if mins < 2:   # too short to judge
            return
        total, enc_total = max(1, w.get("total", 0)), max(1, w.get("encT", 0))
        drop_pct = 100 * w.get("drop", 0) / total
        enc_pct = 100 * max(0, w.get("enc", 0)) / enc_total
        cong = sorted(w["cong"])
        cong_hi = cong[int(len(cong) * 0.9)] if cong else 0
        order = {"good": 0, "ok": 1, "bad": 2, "noData": 1}
        worst = max(w["health"], key=lambda x: order.get(x, 0)) if w["health"] else None
        try:
            cur = self.current()
        except QualityError:
            return
        fam = _family(cur["codec"])
        height = min(MINIMUM[fam], key=lambda k: abs(k - (cur["output"][1] or 1080)))
        floor, target = MINIMUM[fam][height], (self.d.get("applied") or {}).get("bitrate") or cur["bitrate"]
        msg, new = None, None
        struggling = drop_pct > 1 or cong_hi > 0.5 or w.get("reconnecting", 0) > 1 or worst == "bad"
        if struggling:
            new = max(floor, int(cur["bitrate"] * 0.8 / 500) * 500)
            msg = (f"Your connection struggled ({drop_pct:.1f}% of frames dropped). "
                   + (f"Lowered to {new / 1000:g} Mbps for next time." if new < cur["bitrate"] and self.d.get("auto")
                      else "Try a lower setting or test your upload."))
        elif enc_pct > 1:
            msg = (f"Your PC couldn't keep up encoding ({enc_pct:.1f}% of frames skipped). "
                   "Try Light (720p), or close other programs while streaming.")
        else:
            msg = f"Smooth: {drop_pct:.2f}% dropped frames" + (", YouTube health good." if worst == "good" else ".")
            if cur["bitrate"] < target:   # we lowered it before; creep back up after a smooth stream
                new = min(target, int(cur["bitrate"] * 1.1 / 500) * 500 + 500)
                if self.d.get("auto"):
                    msg += f" Raised back to {new / 1000:g} Mbps."
        changed = False
        if new and new != cur["bitrate"] and self.d.get("auto") and not self.busy():
            self._set_bitrate(cur, new)
            changed = True
        with self.lock:
            if changed:
                self.d["adjusted_kbps"] = new
            self.d["report"] = {"at": time.strftime("%Y-%m-%d %H:%M"), "minutes": round(mins),
                                "dropped_pct": round(drop_pct, 2), "encoder_pct": round(enc_pct, 2),
                                "health": worst, "bitrate": cur["bitrate"], "message": msg,
                                "changed_to": new if changed else None}
            _save(self.d)
        self.log("stream quality report:", msg)
