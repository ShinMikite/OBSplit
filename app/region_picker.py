"""
Full-screen overlay to pick a screen region (XSplit style).
  drag            = select a rectangle
  click a window  = snap to that window
  Esc / right-click = cancel
Prints JSON to stdout: {"x":..,"y":..,"w":..,"h":..} in physical desktop pixels, or {"cancel": true}.
"""
import ctypes
import json
import os
import sys
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import winapps  # noqa: E402  (also makes this process DPI-aware so Tk works in real pixels)
import tkinter as tk  # noqa: E402

user32 = ctypes.WinDLL("user32")


def window_rects():
    """Top-level visible app windows in front-to-back order with their rectangles."""
    rects = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        if user32.GetWindowLongW(hwnd, -20) & 0x80:  # tool window
            return True
        cloaked = wintypes.DWORD(0)
        ctypes.WinDLL("dwmapi").DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4)
        if cloaked.value or user32.GetWindowTextLengthW(hwnd) == 0:
            return True
        r = winapps.RECT()
        # DWMWA_EXTENDED_FRAME_BOUNDS (9) = the visible edges, without the invisible resize border
        if ctypes.WinDLL("dwmapi").DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
            user32.GetWindowRect(hwnd, ctypes.byref(r))
        if r.right - r.left > 50 and r.bottom - r.top > 50:
            rects.append((r.left, r.top, r.right, r.bottom))
        return True

    user32.EnumWindows(cb, 0)
    return rects


def main():
    mons = winapps.list_monitors()
    vx = min(m["x"] for m in mons)
    vy = min(m["y"] for m in mons)
    vw = max(m["x"] + m["w"] for m in mons) - vx
    vh = max(m["y"] + m["h"] for m in mons) - vy
    wins = window_rects()
    result = {"cancel": True}

    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry(f"{vw}x{vh}+{vx}+{vy}")
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.45)
    root.configure(bg="black", cursor="crosshair")
    cv = tk.Canvas(root, width=vw, height=vh, bg="black", highlightthickness=0)
    cv.pack()

    prim = next((m for m in mons if m["primary"]), mons[0])
    cx, cy = prim["x"] - vx + prim["w"] // 2, prim["y"] - vy + 70
    cv.create_rectangle(cx - 330, cy - 34, cx + 330, cy + 34, fill="#16171c", outline="#3d7bff", width=2)
    cv.create_text(cx, cy - 10, text="Drag to select an area, or click a window to capture it",
                   fill="white", font=("Segoe UI", 15, "bold"))
    cv.create_text(cx, cy + 16, text="Esc or right-click to cancel", fill="#b8bac4", font=("Segoe UI", 11))

    state = {"start": None, "rect": None, "hover": None, "label": None}

    def to_desktop(ex, ey):
        return ex + vx, ey + vy

    def draw_box(x0, y0, x1, y1, dash=None):
        for k in ("rect", "label"):
            if state[k]:
                cv.delete(state[k])
        state["rect"] = cv.create_rectangle(x0 - vx, y0 - vy, x1 - vx, y1 - vy, outline="#ff4d55", width=3,
                                            dash=dash, fill="#ffffff", stipple="gray12")
        state["label"] = cv.create_text(x0 - vx + 6, y0 - vy - 12 if y0 - vy > 20 else y1 - vy + 12,
                                        text=f"{abs(x1 - x0)} × {abs(y1 - y0)}", fill="white", anchor="w",
                                        font=("Segoe UI", 11, "bold"))

    def window_at(px, py):
        for r in wins:
            if r[0] <= px < r[2] and r[1] <= py < r[3]:
                return r
        return None

    def on_move(e):
        if state["start"]:
            return
        px, py = to_desktop(e.x, e.y)
        r = window_at(px, py)
        if r != state["hover"]:
            state["hover"] = r
            if r:
                draw_box(*r, dash=(6, 4))

    def on_press(e):
        state["start"] = to_desktop(e.x, e.y)

    def on_drag(e):
        if not state["start"]:
            return
        x0, y0 = state["start"]
        x1, y1 = to_desktop(e.x, e.y)
        if abs(x1 - x0) > 4 or abs(y1 - y0) > 4:
            draw_box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
            state["dragged"] = True

    def on_release(e):
        nonlocal result
        if not state["start"]:
            return
        x0, y0 = state["start"]
        x1, y1 = to_desktop(e.x, e.y)
        if state.get("dragged") and abs(x1 - x0) >= 16 and abs(y1 - y0) >= 16:
            result = {"x": min(x0, x1), "y": min(y0, y1), "w": abs(x1 - x0), "h": abs(y1 - y0)}
        else:
            r = window_at(x1, y1)
            if r:
                result = {"x": r[0], "y": r[1], "w": r[2] - r[0], "h": r[3] - r[1], "window": True}
            else:
                state["start"] = None
                return
        root.destroy()

    def cancel(_=None):
        root.destroy()

    cv.bind("<Motion>", on_move)
    cv.bind("<ButtonPress-1>", on_press)
    cv.bind("<B1-Motion>", on_drag)
    cv.bind("<ButtonRelease-1>", on_release)
    cv.bind("<ButtonPress-3>", cancel)
    root.bind("<Escape>", cancel)
    root.after(100, lambda: (root.focus_force(), root.lift()))
    root.after(1500 if "--selftest" in sys.argv else 120000, cancel)  # give up after 2 minutes
    root.mainloop()
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
