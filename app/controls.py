"""
Controls+: Go Live that says where it goes, a check before going live, a row per platform while live (with
its own Stop), recording, Virtual Camera and Studio Mode.
"""
import threading
import time

import obslink


class ControlsError(Exception):
    pass


class Controls:
    def __init__(self, app, log):
        self.app, self.log = app, log
        self.lock = threading.Lock()
        self._yt = (0, None)      # (when, info) cached for a minute: which YouTube stream is waiting on OBS's key
        self._tw = (0, None)

    # ------------------------------------------------------------------ what viewers will see
    def youtube_target(self):
        when, info = self._yt
        if time.time() - when < 60:
            return info
        a = self.app
        info = {"connected": a.google.connected()}
        try:
            if info["connected"]:
                sid = a.config.get("yt_stream_id") or (a.config.get("last_broadcast") or {}).get("streamId")
                found = None
                for status in ("active", "upcoming"):
                    r = a.google.request("GET", "/liveBroadcasts", {"part": "snippet,status,contentDetails",
                                                                     "broadcastStatus": status, "broadcastType": "all",
                                                                     "maxResults": 25}, cost=1)
                    for b in r.get("items") or []:
                        if sid and (b.get("contentDetails") or {}).get("boundStreamId") == sid:
                            found = b
                            break
                    if found:
                        break
                if found:
                    info.update(title=found["snippet"].get("title"), privacy=found["status"].get("privacyStatus"),
                                state=found["status"].get("lifeCycleStatus"),
                                auto_start=(found.get("contentDetails") or {}).get("enableAutoStart"))
                info["key_known"] = bool(sid)
        except Exception as e:
            info["error"] = str(e)[:120]
        self._yt = (time.time(), info)
        return info

    def twitch_target(self):
        when, info = self._tw
        if time.time() - when < 60:
            return info
        tw = self.app.twitch
        info = {"connected": tw.connected()}
        try:
            if info["connected"]:
                c = tw.get_channel()
                info.update(title=c.get("title"), category=c.get("game_name"))
        except Exception as e:
            info["error"] = str(e)[:120]
        self._tw = (time.time(), info)
        return info

    def forget(self):
        self._yt = self._tw = (0, None)

    # ------------------------------------------------------------------ status
    def status(self):
        a, obs = self.app, self.app.obs
        plat = a.platform()
        out = {"platform": plat, "obs": bool(obs.ws)}
        if not obs.ws:
            out["warnings"] = [{"text": "OBS isn't connected."}]
            return out
        try:
            m = a.multi.status()
            rec = obs.request("GetRecordStatus")
            vc = obs.request("GetVirtualCamStatus")
            studio = obs.request("GetStudioModeEnabled")
            svc = obs.request("GetStreamServiceSettings").get("streamServiceSettings") or {}
        except obslink.ObsError as e:
            out["warnings"] = [{"text": str(e)}]
            return out
        out.update(youtube=m["youtube"], twitch=m["twitch"], test_mode=m["test_mode"],
                   recording={"active": bool(rec.get("outputActive")), "paused": bool(rec.get("outputPaused")),
                              "duration_ms": rec.get("outputDuration") or 0},
                   virtualcam=bool(vc.get("outputActive")), studio=bool(studio.get("studioModeEnabled")))
        # in YouTube-only or Twitch-only mode, OBS's own stream is that platform
        if plat == "twitch":
            out["twitch"], out["youtube"] = m["youtube"], {"active": False}
        out["live"] = bool(m["youtube"].get("active") or m["twitch"].get("active"))
        out["targets"] = {}
        if plat in ("youtube", "both"):
            out["targets"]["youtube"] = self.youtube_target()
        if plat in ("twitch", "both"):
            out["targets"]["twitch"] = self.twitch_target()
        out["warnings"] = [] if out["live"] else self.checks(plat, out, svc)
        return out

    def checks(self, plat, st, svc):
        """Things worth knowing before going live. Each is a warning you can still go past."""
        a, w = self.app, []
        service = (svc.get("service") or "").lower()
        if plat in ("youtube", "both"):
            yt = st["targets"].get("youtube") or {}
            if not yt.get("connected"):
                w.append({"text": "YouTube isn't connected, so OBSplit can't check your YouTube stream."})
            elif "youtube" not in service:
                w.append({"text": "OBS isn't set to stream to YouTube.", "fix": "repoint", "fix_label": "Point OBS at YouTube"})
            elif yt.get("key_known") and not yt.get("title") and not yt.get("error"):
                w.append({"text": "No YouTube stream is waiting for this stream key, so nothing will go live on "
                                  "YouTube. Set one up with + New in Stream Info."})
            elif yt.get("privacy") == "private":
                w.append({"text": "Your YouTube stream is set to Private: only you can see it."})
        if plat == "twitch":
            if not a.twitch.connected():
                w.append({"text": "Twitch isn't connected, so OBSplit can't check your Twitch stream."})
            elif "twitch" not in service:
                w.append({"text": "OBS isn't set to stream to Twitch.", "fix": "repoint", "fix_label": "Point OBS at Twitch"})
        if plat == "both":
            if not a.twitch.connected():
                w.append({"text": "Twitch isn't connected, so only YouTube will go live."})
            elif st.get("test_mode"):
                w.append({"text": "Twitch is in test mode: it streams to Twitch's servers but viewers won't see it.",
                          "fix": "test_off", "fix_label": "Turn off test mode"})
            elif not (st.get("twitch") or {}).get("ready"):
                w.append({"text": "The Twitch stream isn't set up in OBS yet (the OBSplit second stream script "
                                  "may not be loaded)."})
        try:
            q = a.quality.status()
            if q.get("restart_needed"):
                w.append({"text": "OBS needs a restart to use the new video format.", "fix": "restart",
                          "fix_label": "Restart OBS now"})
            for i in q.get("issues") or []:
                w.append({"text": i})
        except Exception:
            pass
        inputs = a.obs.state.get("inputs") or {}
        live_inputs = set(a.obs.state.get("members") or []) | set(a.obs.state.get("specials") or [])
        for name, i in inputs.items():
            if i.get("kind") == "wasapi_input_capture" and i.get("muted") and name in live_inputs:
                w.append({"text": f"Your mic \"{name}\" is muted.", "fix": "unmute:" + name, "fix_label": "Unmute"})
        return w

    # ------------------------------------------------------------------ actions
    def act(self, b):
        a, obs = self.app, self.app.obs
        what = b.get("action") or ""
        try:
            if what == "go_live":
                if obs.request("GetStreamStatus").get("outputActive"):
                    raise ControlsError("You're already live.")
                self.forget()
                obs.request("StartStream")         # in YouTube + Twitch mode, Twitch follows automatically
            elif what == "stop":
                p = b.get("platform")
                if a.platform() == "both" and p in ("youtube", "twitch"):
                    a.multi.stop(p)
                else:
                    obs.request("StopStream")
            elif what == "stop_all":
                if a.multi._second_active():
                    obs.request("StopOutput", {"outputName": "obsplit_second"})
                if obs.request("GetStreamStatus").get("outputActive"):
                    obs.request("StopStream")
            elif what == "record":
                r = obs.request("GetRecordStatus")
                op = b.get("op")
                if op == "start" and not r.get("outputActive"):
                    obs.request("StartRecord")
                elif op == "stop" and r.get("outputActive"):
                    obs.request("StopRecord")
                elif op == "pause" and r.get("outputActive") and not r.get("outputPaused"):
                    obs.request("PauseRecord")
                elif op == "resume" and r.get("outputPaused"):
                    obs.request("ResumeRecord")
            elif what == "virtualcam":
                obs.request("ToggleVirtualCam")
            elif what == "studio":
                on = obs.request("GetStudioModeEnabled").get("studioModeEnabled")
                obs.request("SetStudioModeEnabled", {"studioModeEnabled": not on})
            elif what == "unmute":
                obs.request("SetInputMute", {"inputName": b.get("name"), "inputMuted": False})
            elif what == "test_off":
                a.multi.test_mode = False
                a.multi.prepare()
            else:
                raise ControlsError("Unknown action.")
        except obslink.ObsError as e:
            raise ControlsError(str(e))
        return self.status()
