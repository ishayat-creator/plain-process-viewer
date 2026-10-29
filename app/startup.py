"""Programs that start with Windows: Run keys and Startup folders, with their on/off state."""
import os
import re
import winreg

RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN32 = r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"


def _values(hive, key):
    try:
        with winreg.OpenKey(hive, key) as k:
            i = 0
            while True:
                try:
                    yield winreg.EnumValue(k, i)
                except OSError:
                    return
                i += 1
    except OSError:
        return


def _approved(hive, sub):
    return {name.lower(): data for name, data, _ in _values(hive, APPROVED + "\\" + sub) if isinstance(data, bytes)}


def _enabled(table, name):
    data = table.get(name.lower())
    return True if not data else data[0] % 2 == 0


def exe_from_command(cmd):
    cmd = os.path.expandvars((cmd or "").strip())
    m = re.match(r'"([^"]+)"', cmd)
    if m:
        return m.group(1)
    m = re.match(r"(.+?\.(exe|bat|cmd|com|vbs|ps1))\b", cmd, re.I)
    return m.group(1) if m else cmd.split(" ")[0]


def _shortcut_target(lnk):
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        sc = win32com.client.Dispatch("WScript.Shell").CreateShortcut(lnk)
        return sc.TargetPath, sc.Arguments
    except Exception:
        return "", ""


def status(path, found=None):
    """'on' or 'off' if this program is in the startup list, None if it isn't in the places checked
    (Run keys and Startup folders; scheduled tasks and services aren't checked)."""
    if not path:
        return None
    hits = [e for e in (entries() if found is None else found) if (e.get("path") or "").lower() == path.lower()]
    if not hits:
        return None
    return "on" if any(e["enabled"] for e in hits) else "off"


STATUS_TEXT = {
    "on": "yes, it's in the startup list and turned on",
    "off": "it's in the startup list but turned off",
    None: "not found in the Run keys or Startup folders (scheduled tasks and services weren't checked)",
}


def entries():
    hkcu, hklm = winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE
    out = []
    for hive, key, sub, who in ((hkcu, RUN, "Run", "Just you"), (hklm, RUN, "Run", "Everyone on this PC"), (hklm, RUN32, "Run32", "Everyone on this PC")):
        approved = _approved(hive, sub)
        for name, data, _ in _values(hive, key):
            if not isinstance(data, str) or not data.strip():
                continue
            out.append({"name": name, "command": data, "path": exe_from_command(data), "who": who,
                        "where": "Registry (Run key)", "enabled": _enabled(approved, name)})
    folders = (
        (hkcu, os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup"), "Just you"),
        (hklm, os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), r"Microsoft\Windows\Start Menu\Programs\StartUp"), "Everyone on this PC"),
    )
    for hive, folder, who in folders:
        approved = _approved(hive, "StartupFolder")
        try:
            files = os.listdir(folder)
        except OSError:
            continue
        for fname in files:
            if fname.lower() == "desktop.ini":
                continue
            full = os.path.join(folder, fname)
            if fname.lower().endswith(".lnk"):
                target, args = _shortcut_target(full)
                command = f'"{target}" {args}'.strip() if target else full
                path = target or full
            else:
                command, path = full, full
            out.append({"name": os.path.splitext(fname)[0], "command": command, "path": path, "who": who,
                        "where": "Startup folder", "enabled": _enabled(approved, fname)})
    return out
