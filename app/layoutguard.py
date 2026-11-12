"""
Layout lock: keep the user's OBS panel layout (positions, sizes, tabs, window) exactly as they saved it.

OBS only writes its layout to disk when it closes, and never says *why* it changed, so this follows OBS's own
View -> Docks -> Lock Docks setting to tell a deliberate change from an accidental one:
  - "Keep my layout": the layout OBS writes the next time it closes is saved as *the* layout.
  - Lock Docks on: every time OBS closes, the saved layout is checked and put back if anything changed it
    (a reset, a different YouTube/Twitch layout, the window being un-maximized, ...).
  - Lock Docks off: you're rearranging, so the layout OBS closes with becomes the saved layout.
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

def docks_locked():
    """OBS's Lock Docks setting as OBS last wrote it (it writes it when it closes)."""
    try:
        return (_get(_read(_window_ini())[0], "BasicWindow", "DocksLocked") or "").lower() == "true"
    except OSError:
        return False


def status():
    try:
        st = json.load(open(STATE_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    return {"mode": st.get("mode", "off"), "saved_at": st.get("saved_at"), "restored_at": st.get("restored_at"),
            "restores": st.get("restores", 0), "docks_locked": docks_locked()}


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


def apply_scene_orders(orders, log=print):
    """Make OBS's own Scenes list use the order arranged in Scenes+ (OBS can't reorder scenes remotely,
    so it's written to the scene collection file while OBS is closed). Only the order changes."""
    d = os.path.join(OBS, "basic", "scenes")
    if not orders or not os.path.isdir(d):
        return []
    done = []
    for f in os.listdir(d):
        if not f.endswith(".json"):
            continue
        path = os.path.join(d, f)
        try:
            data = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        want = orders.get(data.get("name"))
        cur = [x.get("name") for x in data.get("scene_order", [])]
        if not want or not cur:
            continue
        new = [n for n in want if n in cur] + [n for n in cur if n not in want]
        if new == cur:
            continue
        data["scene_order"] = [{"name": n} for n in new]
        tmp = path + ".obsplit-tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=4)
        json.load(open(tmp, encoding="utf-8"))   # make sure it's valid before replacing
        os.replace(tmp, path)
        done.append(data.get("name"))
        log("scene order applied to OBS for", data.get("name"))
    return done


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
            now = _capture()
            if now and (now.get("docks_locked") or "").lower() != "true":
                # Lock Docks is off: the user is rearranging, so what OBS closed with is the new layout
                if (now["dockstate"], now["geometry"]) != (st["layout"]["dockstate"], st["layout"].get("geometry")):
                    st.update(layout=now, saved_at=time.strftime("%Y-%m-%d %H:%M"))
                    _save(st)
                    log("layout lock: saved your new layout (Lock Docks is off)")
                _apply(st["layout"])         # window size fix + the same layout for connected accounts
                return ["saved"]
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
