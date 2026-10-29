"""Opens Plain Process Viewer in its own window. Use --browser to open it in your web browser instead."""
import ctypes
import os
import sys
import time
import traceback
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "app"))

LOG_DIR = os.path.join(os.environ.get("LOCALAPPDATA", HERE), "PlainProcessViewer")
MB_OK, MB_ICONERROR, MB_ICONINFO = 0x0, 0x10, 0x40


def message(text, icon=MB_ICONINFO):
    ctypes.windll.user32.MessageBoxW(None, text, "Plain Process Viewer", MB_OK | icon)


def main():
    import server
    port = server.serve(0)
    url = f"http://127.0.0.1:{port}/"
    if "--browser" not in sys.argv:
        try:
            import webview
            webview.create_window("Plain Process Viewer", url, width=1320, height=840, min_size=(760, 520), background_color="#F3F4F8")
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
