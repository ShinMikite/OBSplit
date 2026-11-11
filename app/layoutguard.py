"""
Layout lock: keep the user's OBS panel layout (positions, sizes, tabs, window) exactly as they saved it.

OBS only writes its layout to disk when it closes, so this works around that:
  - "Lock my layout": the layout OBS writes the next time it closes is saved as *the* layout.
  - From then on, every time OBS closes, the saved layout is checked and put back if anything changed it
    (a crash, a reset, a different YouTube/Twitch layout, the window being un-maximized, ...).
  - The locked layout is also written into OBS's per-service layouts (e.g. "YouTube - RTMPS"), which OBS
    loads instead when an account is connected, so connecting an account can't swap the layout.
Runs only while OBS is closed (the helper calls on_obs_closed() after OBS exits).
"""
import base64
import json
import os
import re
import struct
import time

OBS = os.path.join(os.environ.get("APPDATA", ""), "obs-studio")
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "data", "layout_lock.json")


# --------------------------------------------------------------------------- ini helpers (keep OBS's format)

def _window_ini():
    u = os.path.join(OBS, "user.ini")
    return u if os.path.exists(u) else os.path.join(OBS, "global.ini")


def _profile_ini():
    from obslink import profile_ini
    return profile_ini()


def _read(path):
    raw = open(path, "rb").read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    nl = "\r\n" if "\r\n" in text else "\n"
    return text.split(nl), bom, nl


def _write(path, lines, bom, nl):
    tmp = path + ".obsplit-tmp"
    with open(tmp, "wb") as f:
        f.write((b"\xef\xbb\xbf" if bom else b"") + nl.join(lines).encode("utf-8"))
    os.replace(tmp, path)


def _sections(lines):
    """{section: {key: line_index}}"""
    out, cur = {}, None
    for i, line in enumerate(lines):
        m = re.match(r"^\[(.+)\]$", line)
        if m:
            cur = m.group(1)
            out.setdefault(cur, {})
        elif cur is not None and "=" in line:
            out[cur][line.split("=", 1)[0]] = i
    return out


def _get(lines, section, key):
    i = _sections(lines).get(section, {}).get(key)
    return None if i is None else lines[i].split("=", 1)[1]


def _set(lines, section, key, value):
    secs = _sections(lines)
    if key in secs.get(section, {}):
        lines[secs[section][key]] = f"{key}={value}"
        return
    # add to the section (create it at the end if missing)
    for i, line in enumerate(lines):
        if line == f"[{section}]":
            lines.insert(i + 1, f"{key}={value}")
            return
    if lines and lines[-1] != "":
        lines.append("")
    lines += [f"[{section}]", f"{key}={value}"]


# --------------------------------------------------------------------------- window geometry

def _fix_geometry(b64):
    """When the window is saved maximized, make the 'restored' size the same as the maximized size.
    Otherwise OBS lays the panels out in the small window first and squeezes the side columns."""
    try:
        b = bytearray(base64.b64decode(b64))
        if len(b) >= 66 and b[44]:          # maximized
            b[24:40] = b[50:66]             # normalGeometry := current geometry
        return base64.b64encode(bytes(b)).decode()
    except Exception:
        return b64


# --------------------------------------------------------------------------- state

def status():
    try:
        st = json.load(open(STATE_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    return {"mode": st.get("mode", "off"), "saved_at": st.get("saved_at"), "restored_at": st.get("restored_at"),
            "restores": st.get("restores", 0)}


def _load():
    try:
        return json.load(open(STATE_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(st):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1)


def request_lock():
    """Save the layout OBS writes the next time it closes (that's when OBS writes it)."""
    st = _load()
    st["mode"] = "pending"
    _save(st)
    return status()


def unlock():
    st = _load()
    st["mode"] = "off"
    _save(st)
    return status()


# --------------------------------------------------------------------------- the work (OBS must be closed)

def _capture():
    win = _window_ini()
    lines, _, _ = _read(win)
    dock = _get(lines, "BasicWindow", "DockState")
    geo = _get(lines, "BasicWindow", "geometry")
    if not dock:
        return None
    return {"dockstate": dock, "geometry": _fix_geometry(geo) if geo else None,
            "docks_locked": _get(lines, "BasicWindow", "DocksLocked")}


def _apply(saved):
    """Write the saved layout back where OBS reads it. Returns the list of things that were changed."""
    changed = []
    win = _window_ini()
    lines, bom, nl = _read(win)
    if _get(lines, "BasicWindow", "DockState") != saved["dockstate"]:
        _set(lines, "BasicWindow", "DockState", saved["dockstate"])
        changed.append("panel layout")
    if saved.get("geometry") and _get(lines, "BasicWindow", "geometry") != saved["geometry"]:
        _set(lines, "BasicWindow", "geometry", saved["geometry"])
        changed.append("window size")
    if changed:
        _write(win, lines, bom, nl)
    # per-service layouts (used instead while an account like YouTube is connected)
    prof = _profile_ini()
    if os.path.exists(prof):
        plines, pbom, pnl = _read(prof)
        touched = False
        for sec, keys in _sections(plines).items():
            if "DockState" in keys and plines[keys["DockState"]] != "DockState=" + saved["dockstate"]:
                plines[keys["DockState"]] = "DockState=" + saved["dockstate"]
                touched = True
        if touched:
            _write(prof, plines, pbom, pnl)
            changed.append("account layouts")
    return changed


def on_obs_closed(log=print):
    """Called by the helper after OBS has exited."""
    st = _load()
    mode = st.get("mode", "off")
    try:
        if mode == "pending":
            saved = _capture()
            if not saved:
                log("layout lock: OBS hasn't saved a layout yet")
                return []
            st.update(mode="locked", layout=saved, saved_at=time.strftime("%Y-%m-%d %H:%M"))
            _save(st)
            _apply(saved)                    # also fixes the window size + account layouts right away
            log("layout lock: saved your layout")
            return ["saved"]
        if mode == "locked" and st.get("layout"):
            changed = _apply(st["layout"])
            if changed:
                st["restored_at"] = time.strftime("%Y-%m-%d %H:%M")
                st["restores"] = st.get("restores", 0) + 1
                _save(st)
                log("layout lock: put back " + ", ".join(changed))
            return changed
    except Exception as e:
        log("layout lock error", repr(e))
    return []
