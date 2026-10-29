"""Low-level Windows data: every running process (one system call), file details and services.

NtQuerySystemInformation returns all processes with their parent, CPU times and the
private working set (the "Memory" number Task Manager shows) without needing admin.
"""
import ctypes
import ctypes.wintypes as wt
import os
import struct
import threading
import time

import psutil
import win32api
import win32service

ntdll = ctypes.WinDLL("ntdll")
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

SystemProcessInformation = 5
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

ntdll.NtQuerySystemInformation.argtypes = [ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
ntdll.NtQuerySystemInformation.restype = ctypes.c_ulong
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wt.BOOL
kernel32.CloseHandle.argtypes = [wt.HANDLE]

WINDIR = os.environ.get("SystemRoot", r"C:\Windows").lower() + "\\"


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _query_processes():
    size = 1 << 20
    while True:
        buf = ctypes.create_string_buffer(size)
        needed = ctypes.c_ulong(0)
        status = ntdll.NtQuerySystemInformation(SystemProcessInformation, buf, size, ctypes.byref(needed))
        if status == STATUS_INFO_LENGTH_MISMATCH:
            size = max(size * 2, needed.value + 65536)
            continue
        if status != 0:
            raise OSError(f"NtQuerySystemInformation failed: 0x{status:08X}")
        return buf


def list_processes():
    """Return {pid: dict} for every process. Times are in 100 ns units."""
    buf = _query_processes()
    base = ctypes.addressof(buf)
    raw = buf.raw
    out = {}
    offset = 0
    while True:
        (next_off,) = struct.unpack_from("<I", raw, offset)
        threads = struct.unpack_from("<I", raw, offset + 4)[0]
        private_ws = struct.unpack_from("<q", raw, offset + 8)[0]
        create, user, kern = struct.unpack_from("<qqq", raw, offset + 32)
        name_len, _, name_ptr = struct.unpack_from("<HHxxxxQ", raw, offset + 56)
        pid, ppid = struct.unpack_from("<QQ", raw, offset + 80)
        handles, session = struct.unpack_from("<II", raw, offset + 96)
        ws = struct.unpack_from("<Q", raw, offset + 144)[0]
        if name_ptr and name_len:
            name = raw[name_ptr - base: name_ptr - base + name_len].decode("utf-16-le", "replace")
        else:
            name = "System Idle Process" if pid == 0 else "Unknown"
        out[pid] = {
            "pid": pid, "ppid": ppid, "name": name, "threads": threads,
            "private_ws": max(private_ws, 0), "ws": ws, "create": create,
            "cpu_time": user + kern, "handles": handles, "session": session,
        }
        if not next_off:
            break
        offset += next_off
    return out


def exe_path(pid):
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        size = wt.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return None
    finally:
        kernel32.CloseHandle(h)


_version_cache = {}


def file_info(path):
    """FileDescription, CompanyName and ProductName from the file's version resource."""
    if not path:
        return {}
    if path in _version_cache:
        return _version_cache[path]
    info = {}
    try:
        langs = win32api.GetFileVersionInfo(path, "\\VarFileInfo\\Translation") or []
        candidates = ["%04x%04x" % (lang, cp) for lang, cp in langs] + ["040904b0", "040904e4", "000004b0"]
        for key in ("FileDescription", "CompanyName", "ProductName"):
            for code in candidates:
                try:
                    val = win32api.GetFileVersionInfo(path, f"\\StringFileInfo\\{code}\\{key}")
                except Exception:
                    val = None
                if val and val.strip():
                    info[key] = val.strip()
                    break
    except Exception:
        pass
    _version_cache[path] = info
    return info


def package_name(path):
    """'...\\WindowsApps\\5319275A.WhatsAppDesktop_2.26...\\x.exe' -> 'WhatsAppDesktop'."""
    if not path:
        return None
    low = path.lower()
    for marker in ("\\windowsapps\\", "\\systemapps\\"):
        i = low.find(marker)
        if i >= 0:
            folder = path[i + len(marker):].split("\\", 1)[0]
            folder = folder.split("_", 1)[0]
            return folder.split(".")[-1] if "." in folder else folder
    return None


class CpuSampler:
    """Turns cumulative CPU times into a percentage between two refreshes."""

    def __init__(self):
        self.prev = {}
        self.prev_t = None
        self.ncpu = psutil.cpu_count() or 1

    def sample(self, procs):
        now = time.perf_counter()
        result = {}
        if self.prev_t is not None:
            wall = (now - self.prev_t) * 1e7 * self.ncpu
            for pid, p in procs.items():
                key = (pid, p["create"])
                before = self.prev.get(key)
                if before is not None and wall > 0:
                    result[pid] = max(0.0, (p["cpu_time"] - before) / wall * 100)
        self.prev = {(pid, p["create"]): p["cpu_time"] for pid, p in procs.items()}
        self.prev_t = now
        return result


# ---------------------------------------------------------------- services

START_TYPES = {0: "Boot", 1: "System", 2: "Automatic", 3: "Manual", 4: "Disabled"}
STATES = {1: "Stopped", 2: "Starting", 3: "Stopping", 4: "Running", 5: "Continuing", 6: "Pausing", 7: "Paused"}

_svc_lock = threading.Lock()
_svc_status = {"t": 0, "data": []}
_svc_config = {"t": 0, "data": {}}


def service_status(max_age=10):
    """Fast: name, display name, state and PID for every service."""
    with _svc_lock:
        if time.time() - _svc_status["t"] < max_age:
            return _svc_status["data"]
        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ENUMERATE_SERVICE)
        try:
            rows = win32service.EnumServicesStatusEx(scm, win32service.SERVICE_WIN32, win32service.SERVICE_STATE_ALL, None)
        finally:
            win32service.CloseServiceHandle(scm)
        data = [{
            "name": r["ServiceName"], "display": r["DisplayName"], "pid": r["ProcessId"],
            "state": STATES.get(r["CurrentState"], "Unknown"),
        } for r in rows]
        _svc_status.update(t=time.time(), data=data)
        return data


def service_config(max_age=300):
    """Slower: start type, program and description for every service."""
    with _svc_lock:
        if time.time() - _svc_config["t"] < max_age and _svc_config["data"]:
            return _svc_config["data"]
    scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ENUMERATE_SERVICE)
    data = {}
    try:
        for r in win32service.EnumServicesStatusEx(scm, win32service.SERVICE_WIN32, win32service.SERVICE_STATE_ALL, None):
            name = r["ServiceName"]
            entry = {"start": "Unknown", "binary": "", "description": ""}
            try:
                h = win32service.OpenService(scm, name, win32service.SERVICE_QUERY_CONFIG)
                try:
                    cfg = win32service.QueryServiceConfig(h)
                    entry["start"] = START_TYPES.get(cfg[1], "Unknown")
                    entry["binary"] = cfg[3] or ""
                    try:
                        entry["description"] = win32service.QueryServiceConfig2(h, win32service.SERVICE_CONFIG_DESCRIPTION) or ""
                    except Exception:
                        pass
                    try:
                        delayed = win32service.QueryServiceConfig2(h, win32service.SERVICE_CONFIG_DELAYED_AUTO_START_INFO)
                        if delayed and entry["start"] == "Automatic":
                            entry["start"] = "Automatic (delayed)"
                    except Exception:
                        pass
                finally:
                    win32service.CloseServiceHandle(h)
            except Exception:
                pass
            data[name] = entry
    finally:
        win32service.CloseServiceHandle(scm)
    with _svc_lock:
        _svc_config.update(t=time.time(), data=data)
    return data


def services_by_pid():
    out = {}
    for s in service_status():
        if s["pid"]:
            out.setdefault(s["pid"], []).append(s)
    return out
