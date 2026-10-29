"""Opens Plain Process Viewer in its own window. Use --browser to open it in your web browser instead."""
import ctypes
import os
import sys
import time
import traceback
import webbrowser
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "app"))

LOG_DIR = os.path.join(os.environ.get("LOCALAPPDATA", HERE), "PlainProcessViewer")
MB_OK, MB_ICONERROR, MB_ICONINFO = 0x0, 0x10, 0x40
WIDTH, HEIGHT, MIN_WIDTH, MIN_HEIGHT = 1320, 840, 760, 520
SMALL_SCREEN = (1100, 700)  # below this (a tablet, a folded laptop, a big zoom), the window fills the screen

user32 = ctypes.windll.user32


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = ctypes.c_void_p
user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, wintypes.DWORD]
user32.MonitorFromWindow.restype = ctypes.c_void_p
user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
MONITOR_DEFAULTTONEAREST = 2
SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x4, 0x10


def message(text, icon=MB_ICONINFO):
    user32.MessageBoxW(None, text, "Plain Process Viewer", MB_OK | icon)


def work_rect(hmon):
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(hmon, ctypes.byref(info))
    return info.rcWork


def screen_space():
    """Usable size (screen minus taskbar) of the screen under the mouse, where the window opens, in the units window sizes use."""
    try:
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        hmon = user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
        r = work_rect(hmon)
        dpi, _ = ctypes.c_uint(96), ctypes.c_uint()
        ctypes.windll.shcore.GetDpiForMonitor(ctypes.c_void_p(hmon), 0, ctypes.byref(dpi), ctypes.byref(_))
        scale = (dpi.value or 96) / 96  # sizes and DPI come back in the same units, so this gives the zoomed size
        return (r.right - r.left) / scale, (r.bottom - r.top) / scale
    except Exception:
        return None


def window_plan():
    """Width, height, smallest size, and whether to fill the screen, so the window always fits."""
    space = screen_space()
    if not space:
        return WIDTH, HEIGHT, (MIN_WIDTH, MIN_HEIGHT), False
    sw, sh = space
    w, h = min(WIDTH, int(sw * 0.94)), min(HEIGHT, int(sh * 0.92))
    return w, h, (min(MIN_WIDTH, w), min(MIN_HEIGHT, h)), sw < SMALL_SCREEN[0] or sh < SMALL_SCREEN[1]


def keep_on_screen(window):
    """Safety net. Windows staggers each new window down and right, and scaling can enlarge it, so part of it can land off
    the screen. Move it back if it fits; fill the screen if it's simply too big."""
    try:
        hwnd = ctypes.c_void_p(window.native.Handle.ToInt64())
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        work = work_rect(user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST))
        edge = 16  # Windows draws invisible resize borders a few pixels outside the window
        w, h = r.right - r.left, r.bottom - r.top
        ww, wh = work.right - work.left, work.bottom - work.top
        if w > ww or h > wh:  # Windows trims an oversized window to about screen size, so "bigger than the screen" is enough
            window.maximize()
        elif r.left < work.left - edge or r.top < work.top - edge or r.right > work.right + edge or r.bottom > work.bottom + edge:
            user32.SetWindowPos(hwnd, None, work.left + (ww - w) // 2, work.top + (wh - h) // 2, 0, 0,
                                SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
    except Exception:
        pass


def main():
    import server
    port = server.serve(0)
    url = f"http://127.0.0.1:{port}/"
    if "--browser" not in sys.argv:
        try:
            import webview
            w, h, min_size, fill = window_plan()
            window = webview.create_window("Plain Process Viewer", url, width=w, height=h, min_size=min_size,
                                           maximized=fill, background_color="#F3F4F8")
            if not fill:
                window.events.shown += lambda: keep_on_screen(window)
            webview.start(icon=os.path.join(server.HERE, "static", "app.ico"))
            return
        except Exception as e:  # no WebView2 or pywebview: fall back to the browser
            print(f"Couldn't open the app window ({e}). Opening it in your browser instead.")
    webbrowser.open(url)
    if sys.stdout is None:  # no console to close (the .exe, or pythonw): a message box keeps it stoppable
        message(f"Plain Process Viewer is open in your browser at {url}\n\nClick OK when you're done to stop it.")
        return
    print(f"Plain Process Viewer is running at {url}. Close this window to stop it.")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log = os.path.join(LOG_DIR, "error.log")
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            with open(log, "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + traceback.format_exc() + "\n")
        except OSError:
            log = "(couldn't save the details)"
        reason = traceback.format_exception_only(*sys.exc_info()[:2])[-1].strip()
        message(f"Plain Process Viewer couldn't start.\n\n{reason}\n\nDetails were saved to {log}", MB_ICONERROR)
        sys.exit(1)
