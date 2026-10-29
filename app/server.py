"""Local web server behind the app window. Listens on 127.0.0.1 only and requires a per-launch token."""
import base64
import ctypes
import hashlib
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser

import psutil
from flask import Flask, Response, abort, jsonify, request

import startup
import sysinfo
from enrich import Enricher
from knowledge import GENERIC_TITLES, KINDS, KNOWN, Explainer, classify, folder_label, made_by, plain_service

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = secrets.token_urlsafe(24)
CRITICAL = {k for k, v in KNOWN.items() if v.get("close") == "critical"} | {"system idle process"}

app = Flask(__name__, static_folder=os.path.join(HERE, "static"), static_url_path="/static")
enricher = Enricher()
sampler = sysinfo.CpuSampler()
_lock = threading.Lock()
_state = {"t": 0, "snapshot": None, "procs": {}, "paths": {}}
ALLOWED_HOSTS = set()


@app.before_request
def guard():
    host = (request.host or "").lower()
    if ALLOWED_HOSTS and host not in ALLOWED_HOSTS:
        abort(403)
    if request.path.startswith("/api/") and request.headers.get("X-PPV-Token") != TOKEN:
        abort(403)


# Icons are served by short key so the 2-second refresh doesn't resend them.
_icons = {}


def iconize(node):
    b64 = node.get("icon")
    if b64:
        key = hashlib.sha1(b64.encode()).hexdigest()[:16]
        _icons[key] = b64
        node["icon"] = key
    for child in node.get("children", []) + node.get("parts", []):
        iconize(child)


@app.get("/icon/<key>.png")
def icon(key):
    b64 = _icons.get(key)
    if not b64:
        abort(404)
    resp = Response(base64.b64decode(b64), mimetype="image/png")
    resp.headers["Cache-Control"] = "max-age=86400"
    return resp


@app.after_request
def no_cache(resp):
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Frame-Options"] = "DENY"
    return resp


@app.get("/")
def index():
    with open(os.path.join(HERE, "static", "index.html"), encoding="utf-8") as f:
        return f.read().replace("__TOKEN__", TOKEN)


def _paths_for(procs):
    paths = {}
    for pid, p in procs.items():
        key = (pid, p["create"])
        cached = _state["paths"].get(key)
        if cached is None:
            cached = sysinfo.exe_path(pid) or ""
        paths[key] = cached
    _state["paths"] = paths
    return {pid: paths[(pid, p["create"])] or None for pid, p in procs.items()}


_cmd_cache = {}


def _cmdlines_for(procs):
    """Start commands, read once per process. Used only to name parts; never sent anywhere."""
    out, keep = {}, {}
    for pid, p in procs.items():
        key = (pid, p["create"])
        args = _cmd_cache.get(key)
        if args is None:
            try:
                args = psutil.Process(pid).cmdline() if pid > 4 else []
            except Exception:
                args = []
        keep[key] = args
        out[pid] = args
    _cmd_cache.clear()
    _cmd_cache.update(keep)
    return out


def snapshot():
    with _lock:
        if _state["snapshot"] and time.time() - _state["t"] < 1.2:
            return _state["snapshot"]
        procs = sysinfo.list_processes()
        cpu = sampler.sample(procs)
        paths = _paths_for(procs)
        cmdlines = _cmdlines_for(procs)
        svc_by_pid = sysinfo.services_by_pid()
        svc_cfg = sysinfo.service_config()
        admin = sysinfo.is_admin()
        groups = Explainer(procs, cpu, paths, svc_by_pid, svc_cfg, enricher, admin, cmdlines).build()
        for g in groups:
            iconize(g)
        vm = psutil.virtual_memory()
        hidden = 0
        for g in groups:
            stack = list(g["parts"])
            while stack:
                n = stack.pop()
                hidden += n["pid"] != 4 and not n["path"]
                stack.extend(n["children"])
        counts = {k: 0 for k, _ in KINDS}
        for g in groups:
            counts[g["kind"]] = counts.get(g["kind"], 0) + 1
        snap = {
            "summary": {
                "cpu": round(min(100.0, sum(v for pid, v in cpu.items() if pid != 0)), 1),
                "mem_used": vm.total - vm.available, "mem_total": vm.total, "mem_pct": vm.percent,
                "processes": len(procs) - 1, "apps": len(groups), "hidden": hidden, "admin": admin,
                "checking": enricher.busy,
            },
            "kinds": [{"id": k, "label": label, "count": counts.get(k, 0)} for k, label in KINDS],
            "groups": groups,
        }
        _state.update(t=time.time(), snapshot=snap, procs=procs)
        return snap


@app.get("/api/processes")
def api_processes():
    return jsonify(snapshot())


@app.get("/api/process/<int:pid>")
def api_process(pid):
    try:
        p = psutil.Process(pid)
        cmd = p.cmdline()
        cmdline = subprocess.list2cmdline(cmd) if cmd else ""
    except Exception:
        cmdline = ""
    return jsonify({"pid": pid, "cmdline": cmdline})


@app.post("/api/end")
def api_end():
    body = request.get_json(force=True) or {}
    pids = [int(x) for x in body.get("pids", [])][:500]
    procs = _state["procs"] or sysinfo.list_processes()
    ended, failed = [], []
    # Children first, so parents don't restart them.
    order = sorted(pids, key=lambda pid: procs.get(pid, {}).get("create", 0), reverse=True)
    for pid in order:
        info = procs.get(pid)
        if not info or pid in (0, 4):
            continue
        name = info["name"]
        if name.lower() in CRITICAL:
            failed.append({"pid": pid, "name": name, "reason": "Windows needs this one, so it can't be ended."})
            continue
        try:
            p = psutil.Process(pid)
            if p.create_time() and abs(p.create_time() * 1e7 + 116444736000000000 - info["create"]) > 2e7:
                continue  # PID was reused by a different process
            p.terminate()
            ended.append(pid)
        except psutil.NoSuchProcess:
            ended.append(pid)
        except psutil.AccessDenied:
            failed.append({"pid": pid, "name": name, "reason": "Windows didn't allow it. Try again as admin."})
        except Exception as e:
            failed.append({"pid": pid, "name": name, "reason": str(e)})
    _state["t"] = 0
    return jsonify({"ended": len(ended), "failed": failed})


def _known_path(path):
    if not path or not os.path.isfile(path):
        return False
    low = path.lower()
    snap = _state["snapshot"] or {}
    for g in snap.get("groups", []):
        stack = list(g["parts"])
        while stack:
            n = stack.pop()
            if (n.get("path") or "").lower() == low:
                return True
            stack.extend(n["children"])
    for e in _startup_cache.get("data", []):
        if (e.get("path") or "").lower() == low:
            return True
    for s in _services_cache.get("data", []):
        if (s.get("path") or "").lower() == low:
            return True
    return False


@app.post("/api/open-location")
def api_open_location():
    path = (request.get_json(force=True) or {}).get("path", "")
    if not _known_path(path):
        return jsonify({"ok": False, "reason": "That file can't be found."}), 400
    subprocess.Popen(["explorer.exe", "/select,", os.path.normpath(path)])
    return jsonify({"ok": True})


HOME = os.path.expanduser("~")
SECRET_ARG = re.compile(r"(?i)((?:key|token|secret|password|passwd|pwd|auth|bearer)[=: ]+)\S+")
LONG_RANDOM = re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")
AI_SITES = {"chatgpt": "https://chatgpt.com/", "claude": "https://claude.ai/new", "kimi": "https://www.kimi.com/"}


def _mask(text):
    """Hide your user name and anything that looks like a password or key before it leaves the app."""
    if not text:
        return text
    text = re.sub(re.escape(HOME), "%USERPROFILE%", text, flags=re.I)
    text = SECRET_ARG.sub(r"\1[hidden]", text)
    return LONG_RANDOM.sub("[hidden]", text)


def _connections(pids):
    """(internet addresses, count of links to other programs on this PC or the home network)."""
    import ipaddress
    internet, local = set(), 0
    try:
        for c in psutil.net_connections(kind="inet"):
            if c.pid in pids and c.raddr and c.status == psutil.CONN_ESTABLISHED:
                ip = ipaddress.ip_address(c.raddr.ip.split("%")[0])
                if ip.is_loopback or ip.is_private or ip.is_link_local:
                    local += 1
                else:
                    internet.add(f"{c.raddr.ip}:{c.raddr.port}")
    except Exception:
        pass
    return sorted(internet), local


def _in_startup(path):
    if not path:
        return False
    try:
        return any((e.get("path") or "").lower() == path.lower() for e in startup.entries())
    except Exception:
        return False


@app.post("/api/ask")
def api_ask():
    """Builds a ready-to-paste question about one app or part, for any AI chat."""
    body = request.get_json(force=True) or {}
    snap = snapshot()
    target, group = None, None
    for g in snap["groups"]:
        if body.get("group") and g["id"] == body["group"]:
            target, group = g, g
        stack = list(g["parts"])
        while stack and body.get("pid") and target is None:
            n = stack.pop()
            if n["pid"] == body["pid"]:
                target, group = n, g
            stack.extend(n["children"])
        if target:
            break
    if not target:
        return jsonify({"text": ""}), 404

    pids = set(group["pids"]) if target is group else {target["pid"]}
    names = []
    stack = list(group["parts"]) if target is group else [target]
    while stack:
        n = stack.pop()
        names.append(n["name"])
        stack.extend(n["children"])
    first_pid = target["pid"] if target is not group else group["pids"][0]
    try:
        cmd = subprocess.list2cmdline(psutil.Process(first_pid).cmdline())
    except Exception:
        cmd = ""
    conns = _connections(pids)
    services = target.get("services") or []
    sig = {"Valid": f"signed by {target.get('signer')}", "NotSigned": "not signed"}.get(target.get("signature"), target.get("signature") or "unknown")
    lines = [
        "I'm looking at a program running on my Windows PC. In plain everyday words (no jargon), please tell me:",
        "what it is, who makes it, why it might be running, and what happens if I close it.",
        "If you don't recognise it, say so instead of guessing.",
        "",
        f"Name shown: {target['title']}",
        f"File: {group['exe'] if target is group else target['name']}",
        f"Folder: {_mask(target.get('path')) or 'hidden by Windows'}",
        f"Made by: {group.get('company') or 'not stated in the file'}",
        f"Signature: {sig}",
        f"Started by: {group.get('started_by')}" if target is group else f"Part of: {group['title']} ({group['exe']})",
        f"Start command: {_mask(cmd)[:600] or 'not visible'}",
    ]
    if target is group and group["count"] > 1:
        common = ", ".join(f"{n} x{names.count(n)}" if names.count(n) > 1 else n for n in dict.fromkeys(names))
        lines.append(f"Made of {group['count']} processes: {common}")
    if services:
        lines.append("Windows services inside: " + ", ".join(s["display"] for s in services))
    lines.append(f"Starts with Windows: {'yes' if _in_startup(target.get('path')) else 'no'}")
    internet, local = conns
    lines.append(f"Internet connections: {', '.join(internet[:10])}" + (f" and {len(internet) - 10} more" if len(internet) > 10 else "")
                 if internet else "Internet connections: none open right now")
    if local:
        lines.append(f"Links to other programs on this PC or home network: {local}")
    lines.append(f"Using: {target['cpu']}% CPU, {round(target['mem'] / 1048576)} MB memory")
    if target.get("unusual"):
        lines.append("Noticed: " + " ".join(target["unusual"]))
    lines.append(f"My process viewer's current description: {target['what']}")
    return jsonify({"text": "\n".join(lines)})


@app.post("/api/copy")
def api_copy():
    import win32clipboard
    text = (request.get_json(force=True) or {}).get("text", "")
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()
    return jsonify({"ok": True})


@app.post("/api/open-ai")
def api_open_ai():
    url = AI_SITES.get((request.get_json(force=True) or {}).get("site"))
    if url:
        webbrowser.open(url)
    return jsonify({"ok": bool(url)})


@app.post("/api/search-web")
def api_search_web():
    q = (request.get_json(force=True) or {}).get("q", "")[:200]
    webbrowser.open("https://duckduckgo.com/?q=" + urllib.parse.quote(q))
    return jsonify({"ok": True})


@app.post("/api/open-startup-settings")
def api_open_startup_settings():
    os.startfile("ms-settings:startupapps")
    return jsonify({"ok": True})


@app.post("/api/elevate")
def api_elevate():
    args = subprocess.list2cmdline(sys.argv)
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, args, os.getcwd(), 1)
    if rc <= 32:
        return jsonify({"ok": False, "reason": "Admin access wasn't given."})
    threading.Timer(1.0, lambda: os._exit(0)).start()
    return jsonify({"ok": True})


_startup_cache = {"t": 0, "data": []}


@app.get("/api/startup")
def api_startup():
    snap = snapshot()
    running = set()
    for g in snap["groups"]:
        stack = list(g["parts"])
        while stack:
            n = stack.pop()
            if n.get("path"):
                running.add(n["path"].lower())
            stack.extend(n["children"])
    rows = []
    for e in startup.entries():
        path = e["path"]
        lname = os.path.basename(path).lower() if path else ""
        info = sysinfo.file_info(path) if path and os.path.isfile(path) else {}
        known = KNOWN.get(lname)
        rich = enricher.get(path) if path and os.path.isfile(path) else None
        desc = info.get("FileDescription") or info.get("ProductName")
        if desc and desc.strip().lower() in GENERIC_TITLES:
            desc = None
        title = (known or {}).get("title") or desc or e["name"]
        what = (known or {}).get("what") or (info.get("FileDescription") if info.get("FileDescription") not in (None, title) else "") \
            or (made_by(info["CompanyName"]) if info.get("CompanyName") else "No description in the file.")
        rows.append({**e, "id": "startup:" + e["name"], "title": title, "what": what, "file": os.path.basename(path) if path else "",
                     "kind": classify(lname, path, info), "company": info.get("CompanyName"),
                     "folder": folder_label(path), "exists": bool(path and os.path.isfile(path)),
                     "running": bool(path and path.lower() in running), "icon": (rich or {}).get("icon"),
                     "signer": (rich or {}).get("signer"), "signature": (rich or {}).get("status")})
        iconize(rows[-1])
    rows.sort(key=lambda r: r["title"].lower())
    _startup_cache.update(t=time.time(), data=rows)
    return jsonify({"items": rows, "checking": enricher.busy})


_services_cache = {"t": 0, "data": []}


@app.get("/api/services")
def api_services():
    snap = snapshot()
    owner = {}
    for g in snap["groups"]:
        for pid in g["pids"]:
            owner[pid] = g["title"]
    cfg = sysinfo.service_config()
    rows = []
    for s in sysinfo.service_status(max_age=5):
        c = cfg.get(s["name"], {})
        binary = c.get("binary", "")
        path = startup.exe_from_command(binary) if binary else ""
        windows = path.lower().startswith(sysinfo.WINDIR)
        info = sysinfo.file_info(path) if path and not windows else {}
        desc = (c.get("description") or "").strip()
        plain = plain_service(s["name"], s["display"], desc)
        rows.append({
            "id": "svc:" + s["name"], "name": s["name"], "title": plain["title"], "what": plain["what"],
            "display": s["display"], "description": desc, "plain": plain["plain"],
            "state": s["state"], "start": c.get("start", "Unknown"), "pid": s["pid"] or None,
            "runs_in": owner.get(s["pid"]) if s["pid"] else None, "path": path, "folder": folder_label(path),
            "made_by": "Microsoft (part of Windows)" if windows else (info.get("CompanyName") or "Not stated"),
            "windows": windows,
        })
    rows.sort(key=lambda r: r["title"].lower())
    _services_cache.update(t=time.time(), data=rows)
    return jsonify({"items": rows})


def serve(port=0):
    import logging
    from werkzeug.serving import make_server
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    srv = make_server("127.0.0.1", port, app, threaded=True)
    real = srv.server_port
    ALLOWED_HOSTS.update({f"127.0.0.1:{real}", f"localhost:{real}"})
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    snapshot()  # first CPU sample
    return real


if __name__ == "__main__":
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8765
    real = serve(port)
    print(f"Plain Process Viewer on http://127.0.0.1:{real}", flush=True)
    while True:
        time.sleep(3600)
