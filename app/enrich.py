"""Signatures and icons, looked up once per file in the background and saved to disk."""
import json
import os
import subprocess
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()), "PlainProcessViewer")
CACHE_FILE = os.path.join(CACHE_DIR, "file-cache.json")
BATCH = 40


def _stamp(path):
    try:
        st = os.stat(path)
        return f"{st.st_size}:{int(st.st_mtime)}"
    except OSError:
        return None


class Enricher:
    def __init__(self):
        self.lock = threading.Lock()
        self.cache = {}
        self.pending = set()
        self.wake = threading.Event()
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                self.cache = json.load(f)
        except Exception:
            self.cache = {}
        threading.Thread(target=self._worker, daemon=True).start()

    def get(self, path):
        """Return cached details for a path, or None (and queue it) if not known yet."""
        if not path:
            return None
        key = path.lower()
        with self.lock:
            hit = self.cache.get(key)
            if hit and hit.get("stamp") == _stamp(path):
                return hit
            self.pending.add(path)
        self.wake.set()
        return None

    @property
    def busy(self):
        with self.lock:
            return len(self.pending)

    def _worker(self):
        while True:
            self.wake.wait()
            with self.lock:
                batch = list(self.pending)[:BATCH]
            if not batch:
                self.wake.clear()
                continue
            results = self._run(batch)
            with self.lock:
                for path in batch:
                    r = results.get(path.lower(), {"status": "Unknown", "signer": "", "icon": ""})
                    self.cache[path.lower()] = {
                        "stamp": _stamp(path), "status": r.get("status") or "Unknown",
                        "signer": r.get("signer") or "", "icon": r.get("icon") or "",
                    }
                    self.pending.discard(path)
                snapshot = dict(self.cache)
            try:
                os.makedirs(CACHE_DIR, exist_ok=True)
                tmp = CACHE_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(snapshot, f)
                os.replace(tmp, CACHE_FILE)
            except Exception:
                pass

    def _run(self, paths):
        fd, list_file = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(paths, f)
            proc = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", os.path.join(HERE, "enrich.ps1"), list_file],
                capture_output=True, timeout=180, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            text = proc.stdout.decode("utf-8", "replace").strip().lstrip("﻿")
            rows = json.loads(text) if text else []
            if isinstance(rows, dict):
                rows = [rows]
            return {r["path"].lower(): r for r in rows if r.get("path")}
        except Exception:
            return {}
        finally:
            try:
                os.remove(list_file)
            except OSError:
                pass
