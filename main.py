"""Opens Plain Process Viewer in its own window. Use --browser to open it in your web browser instead."""
import os
import sys
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "app"))

import server  # noqa: E402


def main():
    port = server.serve(0)
    url = f"http://127.0.0.1:{port}/"
    if "--browser" not in sys.argv:
        try:
            import webview
            webview.create_window("Plain Process Viewer", url, width=1320, height=840, min_size=(760, 520), background_color="#F3F4F8")
            webview.start()
            return
        except Exception as e:  # no WebView2 or pywebview: fall back to the browser
            print(f"Couldn't open the app window ({e}). Opening it in your browser instead.")
    webbrowser.open(url)
    print(f"Plain Process Viewer is running at {url}. Close this window to stop it.")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
