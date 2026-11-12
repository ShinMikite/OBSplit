"""
Streaming to YouTube and Twitch at the same time (the YouTube + Twitch button).

YouTube uses OBS's own stream (and its Stream quality choice); Twitch uses a second stream that the
obsplit-multistream.lua script builds inside OBS with its own encoder and bitrate. OBS's Start Streaming
starts both; OBS's Stop Streaming stops both; "Stop YouTube" / "Stop Twitch" stop just one.
"""
import json
import os
import queue
import threading
import time

import obslink
import quality

OUT = "obsplit_second"
TWITCH_SERVER = "rtmp://live.twitch.tv/app"


class MultistreamError(Exception):
    pass


class Multistream:
    def __init__(self, data_dir, config, obs, twitch, quality_, log):
        self.config, self.obs, self.twitch, self.quality, self.log = config, obs, twitch, quality_, log
        self.file = os.path.join(data_dir, "multistream.json")
        self.status_file = os.path.join(data_dir, "multistream_status.json")
        self.keep_second = False          # "Stop YouTube": OBS's stream stops but Twitch keeps going
        self.q = queue.Queue()
        obs.listeners.append(self._on_event)
        threading.Thread(target=self._worker, daemon=True, name="multistream").start()

    def enabled(self):
        return self.config.get("platform") == "both"

    # Twitch's bandwidth test: the stream goes to Twitch's servers but isn't broadcast. Saved, so it can't
    # quietly switch off (and go live for real) after a restart.
    @property
    def test_mode(self):
        return bool(self.config.get("multistream_test"))

    @test_mode.setter
    def test_mode(self, on):
        self.config.update(multistream_test=bool(on))

    # ------------------------------------------------------------------ settings for the second stream
    def _write(self, data):
        """Writes the settings only if they changed (the script rebuilds the stream on every change).
        Returns True if they changed."""
        try:
            with open(self.file, encoding="utf-8") as f:
                old = json.load(f)
            old.pop("rev", None)
            if old == data:
                return False
        except (OSError, ValueError):
            pass
        data = {**data, "rev": int(time.time() * 1000)}
        tmp = self.file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, self.file)
        return True

    def twitch_plan(self):
        preset = (self.quality.d.get("preset_by") or {}).get("twitch") or "recommended"
        cur = None
        try:
            cur = self.quality.current()
        except Exception:
            pass
        return self.quality.plan(preset, cur, platform="twitch")

    def prepare(self):
        """Writes the Twitch stream's settings (or turns it off). Returns a short note, or None."""
        if not self.enabled():
            self._write({"enabled": False})
            return None
        if not self.twitch.connected():
            self._write({"enabled": False})
            return "Connect Twitch in OBSplit Setup so OBS can stream to Twitch too."
        key = self.twitch.helix("GET", "/streams/key", {"broadcaster_id": self.twitch.uid()})["data"][0]["stream_key"]
        if self.test_mode:
            key += "?bandwidthtest=true"
        plan = self.twitch_plan()
        settings = self.quality._encoder_settings(plan["encoder"], plan["codec"], plan["bitrate"], {})
        self.changed = self._write({"enabled": True, "name": "Twitch", "server": TWITCH_SERVER, "key": key,
                                    "encoder": plan["encoder"], "encoder_settings": settings,
                                    "width": plan["width"], "height": plan["height"],
                                    "audio_bitrate": quality.AUDIO_KBPS})
        return None

    changed = False

    # ------------------------------------------------------------------ following OBS's own stream
    def _on_event(self, t, e):          # OBS's event thread: only queue work here
        if t == "StreamStateChanged":
            st = e.get("outputState")
            if st == "OBS_WEBSOCKET_OUTPUT_STARTED":
                self.q.put("start")
            elif st == "OBS_WEBSOCKET_OUTPUT_STOPPED":
                self.q.put("stop")

    def _worker(self):
        while True:
            job = self.q.get()
            try:
                if job == "start":
                    self.keep_second = False
                    if self.enabled():
                        note = self.prepare()          # fresh key and settings for this stream
                        if note:
                            self._note_status("stopped", note)
                            continue
                        if self.changed:
                            time.sleep(3)              # let the OBS script rebuild with the new settings
                        self.start_second()
                elif job == "stop":
                    if self.keep_second:
                        self.keep_second = False     # "Stop YouTube": leave Twitch running
                    elif self._second_active():
                        self.obs.request("StopOutput", {"outputName": OUT})
                        self.log("multistream: Twitch stopped with OBS's stream")
            except Exception as e:
                self.log("multistream", job, "failed:", repr(e)[:200])

    def start_second(self):
        for _ in range(10):               # the script needs a moment to (re)build after new settings
            try:
                if self._second_active():
                    return
                self.obs.request("StartOutput", {"outputName": OUT})
                self.log("multistream: Twitch started" + (" (bandwidth test, not broadcast)" if self.test_mode else ""))
                return
            except obslink.ObsError as e:
                last = e
                time.sleep(1)
        self._note_status("stopped", "the second stream isn't ready (is the OBSplit second stream script loaded?)",
                          str(last))

    def _second_active(self):
        try:
            return bool(self.obs.request("GetOutputStatus", {"outputName": OUT}).get("outputActive"))
        except obslink.ObsError:
            return False

    def _note_status(self, state, reason, detail=""):
        with open(self.status_file, "w", encoding="utf-8") as f:
            json.dump({"state": state, "code": -100, "reason": reason, "detail": detail, "at": int(time.time())}, f)

    # ------------------------------------------------------------------ the separate stop buttons
    def stop(self, platform):
        if platform == "twitch":
            if not self._second_active():
                raise MultistreamError("Twitch isn't streaming right now.")
            self.obs.request("StopOutput", {"outputName": OUT})
            self.log("multistream: Twitch stopped (YouTube keeps going)")
        elif platform == "youtube":
            if not self.obs.request("GetStreamStatus").get("outputActive"):
                raise MultistreamError("YouTube isn't streaming right now.")
            self.keep_second = self._second_active()
            self.obs.request("StopStream")
            self.log("multistream: YouTube stopped" + (" (Twitch keeps going)" if self.keep_second else ""))
        else:
            raise MultistreamError("Unknown platform.")

    # ------------------------------------------------------------------ status for the panels
    def status(self):
        out = {"enabled": self.enabled(), "test_mode": self.test_mode}
        try:
            m = self.obs.request("GetStreamStatus")
            out["youtube"] = self._fmt(m)
        except obslink.ObsError as e:
            out["youtube"] = {"active": False, "error": str(e)}
        try:
            s = self.obs.request("GetOutputStatus", {"outputName": OUT})
            out["twitch"] = self._fmt(s)
        except obslink.ObsError:
            out["twitch"] = {"active": False, "ready": False}
        else:
            out["twitch"]["ready"] = True
        try:
            with open(self.status_file, encoding="utf-8") as f:
                last = json.load(f)
            if last.get("state") == "stopped" and last.get("code", 0) != 0 and not out["twitch"]["active"]:
                out["twitch"]["problem"] = "Twitch stopped: " + last.get("reason", "") + "."
        except (OSError, ValueError):
            pass
        return out

    @staticmethod
    def _fmt(s):
        total = max(1, s.get("outputTotalFrames") or 0)
        return {"active": bool(s.get("outputActive")), "reconnecting": bool(s.get("outputReconnecting")),
                "duration_ms": s.get("outputDuration") or 0, "bytes": s.get("outputBytes") or 0,
                "dropped_pct": round(100 * (s.get("outputSkippedFrames") or 0) / total, 2),
                "congestion": round(float(s.get("outputCongestion") or 0), 2)}

    # ------------------------------------------------------------------ "should I even try this?"
    def readiness(self):
        """Upload speed and hardware check for streaming to both at once."""
        q = self.quality
        try:
            cur = q.current()
        except Exception:
            cur = None
        yt = q.plan((q.d.get("preset_by") or {}).get("youtube") or q.d.get("preset") or "recommended", cur,
                    platform="youtube")
        tw = self.twitch_plan()
        need = yt["bitrate"] + tw["bitrate"] + 2 * quality.AUDIO_KBPS
        up = q.d.get("upload_kbps")
        reasons, verdict = [], "good"
        hw = [e for e in quality.available_encoders() if any(k in e for k in ("nvenc", "amf", "qsv"))]
        if not hw:
            verdict = "no"
            reasons.append("Your PC has no graphics-card encoder OBS can use, so it would encode both streams on the "
                           "processor. That usually makes games and the streams stutter. Stream to one platform, "
                           "or use a service like Restream.")
        else:
            reasons.append(f"Your {quality._maker(hw[0])} graphics card can encode both streams at once.")
        if not up:
            verdict = "unknown" if verdict == "good" else verdict
            reasons.append(f"Both streams together need about {need / 1000:.0f} Mbps of upload; test your upload "
                           f"in Stream quality to be sure.")
        else:
            share = need / up
            if share > 0.8:
                verdict = "no"
                reasons.append(f"Both streams need about {need / 1000:.0f} Mbps, but your upload is "
                               f"{up / 1000:.0f} Mbps. Stream to one platform, or use a service like Restream, which "
                               "only needs one upload.")
            elif share > 0.6:
                verdict = "tight" if verdict == "good" else verdict
                reasons.append(f"Both streams need about {need / 1000:.0f} Mbps of your {up / 1000:.0f} Mbps upload. "
                               "It should work, but don't upload or download much while live.")
            else:
                reasons.append(f"Both streams need about {need / 1000:.0f} Mbps; your upload ({up / 1000:.0f} Mbps) "
                               "has plenty of room.")
        return {"verdict": verdict, "reasons": reasons, "need_kbps": need,
                "youtube": yt["summary"], "twitch": tw["summary"]}
