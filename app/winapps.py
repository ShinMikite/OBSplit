"""
Windows helpers (ctypes, standard library only):
  - list running app windows, flag which look like games
  - build OBS window-match strings ("title:class:exe")
  - list monitors (for screen-region capture)
"""
import ctypes
import os
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
GW_OWNER = 4
DWMWA_CLOAKED = 14
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MONITOR_DEFAULTTONEAREST = 2

GAME_DIR_HINTS = ("\\steamapps\\common\\", "\\epic games\\", "\\xboxgames\\", "\\gog galaxy\\games\\", "\\gog games\\",
                  "\\riot games\\", "\\ea games\\", "\\ubisoft game launcher\\games\\", "\\battle.net\\",
                  "\\windowsapps\\", "\\games\\")
NOT_GAMES = {"explorer.exe", "obs64.exe", "obs32.exe", "chrome.exe", "msedge.exe", "firefox.exe", "opera.exe",
             "brave.exe", "discord.exe", "steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe",
             "eadesktop.exe", "battle.net.exe", "galaxyclient.exe", "code.exe", "devenv.exe",
             "searchhost.exe", "shellexperiencehost.exe", "startmenuexperiencehost.exe", "textinputhost.exe",
             "applicationframehost.exe", "systemsettings.exe", "lockapp.exe", "snippingtool.exe",
             "streamdeck.exe", "spotify.exe", "vlc.exe", "notepad.exe", "taskmgr.exe", "wallpaper32.exe",
             "wallpaper64.exe", "pythonw.exe", "python.exe", "powershell.exe", "windowsterminal.exe",
             "cmd.exe", "conhost.exe", "nvidia app.exe", "nvcontainer.exe", "msiafterburner.exe",
             "rtss.exe", "parsecd.exe", "winword.exe", "excel.exe"}
GAME_LAUNCHER_SUBDIRS = ("\\epic games\\launcher\\", "\\steamapps\\common\\steamworks shared\\",
                         "\\steamapps\\common\\wallpaper_engine\\")


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", wintypes.DWORD),
                ("szDevice", wintypes.WCHAR * 32)]


user32.GetWindowLongW.restype = ctypes.c_long
user32.GetWindow.restype = wintypes.HWND
user32.MonitorFromWindow.restype = wintypes.HMONITOR
kernel32.OpenProcess.restype = wintypes.HANDLE


def _set_dpi_aware():
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass


_set_dpi_aware()


def _exe_path(pid):
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(h)


def _monitor_rect(hwnd):
    hm = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    mi = MONITORINFOEXW()
    mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
    user32.GetMonitorInfoW(hm, ctypes.byref(mi))
    r = mi.rcMonitor
    return (r.left, r.top, r.right, r.bottom)


def obs_encode(s):
    return s.replace("#", "#22").replace(":", "#3A")


def obs_window_string(title, cls, exe):
    return f"{obs_encode(title)}:{obs_encode(cls)}:{obs_encode(exe)}"


def obs_window_exe(window_setting):
    """Pull the exe name out of an OBS window string."""
    parts = (window_setting or "").split(":")
    return parts[-1].replace("#3A", ":").replace("#22", "#") if len(parts) >= 3 else ""


def list_windows():
    """Visible top-level app windows: [{title, cls, exe, path, game, fullscreen, window}] games first."""
    out, seen = [], set()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, GW_OWNER):
                return True
            ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if ex & WS_EX_TOOLWINDOW or ex & WS_EX_NOACTIVATE:
                return True
            cloaked = wintypes.DWORD(0)
            dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
            if cloaked.value:
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            tb = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, tb, n + 1)
            cb_ = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cb_, 256)
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            path = _exe_path(pid.value)
            exe = os.path.basename(path) if path else ""
            if not exe or exe.lower() in ("explorer.exe",) and cb_.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
                return True
            r = RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            if r.right - r.left < 120 or r.bottom - r.top < 80:
                return True
            mon = _monitor_rect(hwnd)
            full = r.left <= mon[0] and r.top <= mon[1] and r.right >= mon[2] and r.bottom >= mon[3]
            low = path.lower()
            in_game_dir = any(h in low for h in GAME_DIR_HINTS) and not any(h in low for h in GAME_LAUNCHER_SUBDIRS)
            is_game = exe.lower() not in NOT_GAMES and (in_game_dir or full)
            key = (tb.value, exe)
            if key in seen:
                return True
            seen.add(key)
            out.append({"title": tb.value, "cls": cb_.value, "exe": exe, "path": path, "game": is_game,
                        "fullscreen": full, "window": obs_window_string(tb.value, cb_.value, exe)})
        except Exception:
            pass
        return True

    user32.EnumWindows(cb, 0)
    out.sort(key=lambda w: (not w["game"], w["exe"].lower() in NOT_GAMES, w["title"].lower()))
    return out


def process_running(exe_name):
    exe_name = exe_name.lower()
    return any(w["exe"].lower() == exe_name for w in list_windows())


def list_monitors():
    """[{x, y, w, h, primary}] in physical pixels."""
    mons = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(RECT), wintypes.LPARAM)
    def cb(hm, hdc, rc, _):
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        user32.GetMonitorInfoW(hm, ctypes.byref(mi))
        r = mi.rcMonitor
        mons.append({"x": r.left, "y": r.top, "w": r.right - r.left, "h": r.bottom - r.top,
                     "primary": bool(mi.dwFlags & 1), "device": mi.szDevice})
        return True

    user32.EnumDisplayMonitors(None, None, cb, 0)
    return mons


if __name__ == "__main__":
    import json
    print(json.dumps(list_monitors(), indent=1))
    for w in list_windows():
        print(("GAME " if w["game"] else "     ") + ("FULL " if w["fullscreen"] else "     ") + f"{w['exe']:<28} {w['title'][:60]}")
