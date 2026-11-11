"""
Connects OBSplit to OBS Studio (run by the installer), or removes it again.

    obs_integration.py install     add panels, scripts and websocket access
    obs_integration.py uninstall   remove them and restore the websocket setting

OBS must be closed (it rewrites its settings when it exits). A backup of every file touched is saved in
%APPDATA%\\obs-studio\\obsplit-backups\\<date-time>\\ before anything changes.
Standard library only.
"""
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time

APPDIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OBS = os.path.join(os.environ.get("APPDATA", ""), "obs-studio")
STATE = os.path.join(APPDIR, "app", "data", "obs_integration.json")
URL = "http://127.0.0.1:47821"
DOCKS = [("YT Chat", URL + "/chat"), ("YT Stream Info", URL + "/info"), ("YT Stats", URL + "/stats"),
         ("Scenes+", URL + "/scenes"), ("Sources+", URL + "/sources"), ("Audio+", URL + "/audio"),
         ("OBSplit Setup", URL + "/")]
SCRIPTS = [os.path.join(APPDIR, "obs-scripts", "obsplit-launcher.lua"),
           os.path.join(APPDIR, "obs-scripts", "auto-audio-setup.lua")]
QUIET = "--quiet" in sys.argv


# --------------------------------------------------------------------------- messages

def say(title, text, kind="info", ask=False):
    """Message box (tkinter if available), console otherwise. With ask=True returns True for OK/Retry."""
    if QUIET:
        print(f"[{title}] {text}")
        return True
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        if ask:
            r = messagebox.askretrycancel(title, text, parent=root)
        else:
            {"info": messagebox.showinfo, "warn": messagebox.showwarning, "error": messagebox.showerror}[kind](
                title, text, parent=root)
            r = True
        root.destroy()
        return r
    except Exception:
        print(f"[{title}] {text}")
        return True


def obs_running():
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq obs64.exe", "/NH"], capture_output=True, text=True,
                           creationflags=0x08000000)
        return "obs64.exe" in r.stdout.lower()
    except Exception:
        return False


def wait_for_obs_closed():
    if "--force" in sys.argv:  # testing against a copied settings folder
        return True
    while obs_running():
        if QUIET:
            print("OBS is running; close it and run again.")
            return False
        if not say("OBSplit", "Please close OBS Studio so OBSplit can finish setting it up.\n\n"
                              "Click Retry once OBS is closed.", ask=True):
            return False
        time.sleep(1)
    return True


# --------------------------------------------------------------------------- ini helpers (keep OBS's format)

def read_text(path):
    raw = open(path, "rb").read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    return text, bom, ("\r\n" if "\r\n" in text else "\n")


def write_text(path, text, bom):
    with open(path, "wb") as f:
        f.write((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))


def ini_get(lines, section, key):
    cur = None
    for line in lines:
        m = re.match(r"^\[(.+)\]$", line)
        if m:
            cur = m.group(1)
        elif cur == section and line.startswith(key + "="):
            return line[len(key) + 1:]
    return None


def ini_set(lines, section, key, value):
    cur, sec_end, sec_found = None, None, False
    for i, line in enumerate(lines):
        m = re.match(r"^\[(.+)\]$", line)
        if m:
            if cur == section:
                sec_end = i
            cur = m.group(1)
            if cur == section:
                sec_found = True
        elif cur == section and line.startswith(key + "="):
            lines[i] = f"{key}={value}"
            return lines
    if not sec_found:
        if lines and lines[-1] != "":
            lines.append("")
        lines += [f"[{section}]", f"{key}={value}"]
        return lines
    insert_at = sec_end if sec_end is not None else len(lines)
    while insert_at > 0 and lines[insert_at - 1] == "":
        insert_at -= 1
    lines.insert(insert_at, f"{key}={value}")
    return lines


def window_ini():
    """OBS 31+ keeps window/dock settings in user.ini; older versions in global.ini."""
    u = os.path.join(OBS, "user.ini")
    return u if os.path.exists(u) else os.path.join(OBS, "global.ini")


# --------------------------------------------------------------------------- steps

def backup(files):
    base = os.path.join(OBS, "obsplit-backups", time.strftime("%Y-%m-%d_%H-%M-%S"))
    dest, n = base, 2
    while os.path.exists(dest):
        dest, n = f"{base}_{n}", n + 1
    for f in files:
        if os.path.exists(f):
            rel = os.path.relpath(f, OBS)
            os.makedirs(os.path.dirname(os.path.join(dest, rel)), exist_ok=True)
            shutil.copy2(f, os.path.join(dest, rel))
    return dest


def scene_collections():
    d = os.path.join(OBS, "basic", "scenes")
    return [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".json")] if os.path.isdir(d) else []


def ws_config_path():
    return os.path.join(OBS, "plugin_config", "obs-websocket", "config.json")


def set_docks(add):
    path = window_ini()
    if not os.path.exists(path):
        if not add:
            return
        os.makedirs(OBS, exist_ok=True)
        write_text(path, "", False)
    text, bom, nl = read_text(path)
    lines = text.split(nl)
    cur = ini_get(lines, "BasicWindow", "ExtraBrowserDocks")
    try:
        docks = json.loads(cur) if cur else []
    except ValueError:
        docks = []
    docks = [d for d in docks if not str(d.get("url", "")).startswith(URL)]
    if add:
        for title, url in DOCKS:
            docks.append({"title": title, "url": url, "uuid": secrets.token_hex(16)})
    lines = ini_set(lines, "BasicWindow", "ExtraBrowserDocks", json.dumps(docks))
    write_text(path, nl.join(lines), bom)


def set_scripts(add):
    paths = [p.replace("\\", "/") for p in SCRIPTS]
    for sc in scene_collections():
        try:
            data = json.load(open(sc, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        mods = data.setdefault("modules", {})
        tool = [s for s in mods.get("scripts-tool", []) if "/obsplit/obs-scripts/" not in s.get("path", "").lower()]
        if add:
            have = {os.path.basename(s.get("path", "")).lower() for s in tool}
            tool += [{"path": p, "settings": {}} for p in paths if os.path.basename(p).lower() not in have]
        mods["scripts-tool"] = tool
        tmp = sc + ".obsplit-tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        json.load(open(tmp, encoding="utf-8"))
        os.replace(tmp, sc)


def enable_websocket():
    p = ws_config_path()
    before = None
    try:
        c = json.load(open(p, encoding="utf-8"))
        before = bool(c.get("server_enabled"))
    except (OSError, ValueError):
        c = {"alerts_enabled": False, "auth_required": True, "first_load": False, "server_port": 4455}
    c["server_enabled"] = True
    if c.get("auth_required", True) and not c.get("server_password"):
        c["auth_required"] = True
        c["server_password"] = secrets.token_urlsafe(12)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=4)
    return before


def restore_websocket(was_enabled):
    if was_enabled is None or was_enabled:
        return
    p = ws_config_path()
    try:
        c = json.load(open(p, encoding="utf-8"))
        c["server_enabled"] = False
        with open(p, "w", encoding="utf-8") as f:
            json.dump(c, f, indent=4)
    except (OSError, ValueError):
        pass


def install():
    if not os.path.isdir(OBS):
        say("OBSplit", "OBS Studio doesn't seem to be set up on this PC yet.\n\n"
                       "Install OBS Studio, open it once, close it, then run 'OBSplit - Connect to OBS' "
                       "from the Start menu.", "warn")
        return 1
    if not wait_for_obs_closed():
        say("OBSplit", "Setup was skipped. Run 'OBSplit - Connect to OBS' from the Start menu any time.", "warn")
        return 1
    files = [window_ini(), ws_config_path()] + scene_collections()
    where = backup(files)
    state = {}
    try:
        state = json.load(open(STATE, encoding="utf-8"))
    except (OSError, ValueError):
        pass
    was = enable_websocket()
    if "websocket_was_enabled" not in state:
        state["websocket_was_enabled"] = was
    set_docks(True)
    set_scripts(True)
    state["installed"] = time.strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(state, open(STATE, "w", encoding="utf-8"), indent=2)
    say("OBSplit", "OBSplit is connected to OBS.\n\n"
                   "Start OBS: the new panels are in the Docks menu (YT Chat, YT Stream Info, YT Stats, "
                   "Scenes+, Audio+, OBSplit Setup). Drag them where you like.\n\n"
                   f"A backup of your previous OBS settings is in:\n{where}")
    return 0


def uninstall():
    if not os.path.isdir(OBS):
        return 0
    if not wait_for_obs_closed():
        say("OBSplit", "OBS was left as it is. Remove the panels in Docks → Custom Browser Docks and the "
                       "scripts in Tools → Scripts if you want.", "warn")
        return 1
    backup([window_ini(), ws_config_path()] + scene_collections())
    try:
        state = json.load(open(STATE, encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    set_docks(False)
    set_scripts(False)
    restore_websocket(state.get("websocket_was_enabled"))
    return 0


if __name__ == "__main__":
    cmd = next((a for a in sys.argv[1:] if not a.startswith("--")), "install")
    sys.exit(install() if cmd == "install" else uninstall() if cmd == "uninstall" else 2)
