"""Turns raw process data into named, grouped, explained apps."""
import json
import os
import re

from sysinfo import WINDIR, file_info, package_name

HERE = os.path.dirname(os.path.abspath(__file__))
def _load_process_lists():
    """known.json plus every processes-*.json. Keys ending in * match by prefix."""
    exact, prefixes, clashes = {}, [], []
    files = ["known.json"] + sorted(f for f in os.listdir(os.path.join(HERE, "data")) if f.startswith("processes-") and f.endswith(".json"))
    for name in files:
        with open(os.path.join(HERE, "data", name), encoding="utf-8") as f:
            for k, v in json.load(f).items():
                if k.startswith("_"):
                    continue
                if k.endswith("*"):
                    prefixes.append((k[:-1], v))
                elif k in exact:
                    clashes.append(f"{k} ({name})")
                else:
                    exact[k] = v
    prefixes.sort(key=lambda p: -len(p[0]))
    return exact, prefixes, clashes


KNOWN, KNOWN_PREFIXES, CLASHES = _load_process_lists()


def lookup(lname):
    """Plain-words entry for a lowercase file name, or None."""
    hit = KNOWN.get(lname)
    if hit:
        return hit
    return next((v for p, v in KNOWN_PREFIXES if lname.startswith(p)), None)
with open(os.path.join(HERE, "data", "services.json"), encoding="utf-8") as f:
    _svc = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
SERVICES = {k: v for k, v in _svc.items() if not k.endswith("*")}
SERVICE_PREFIXES = [(k[:-1], v) for k, v in _svc.items() if k.endswith("*")]


def plain_service(name, display, description=""):
    """Everyday title and explanation for a Windows service, with where it came from."""
    key = re.sub(r"_[0-9a-f]{4,8}$", "", name.lower())
    hit = SERVICES.get(key) or next((v for p, v in SERVICE_PREFIXES if key.startswith(p)), None)
    if hit:
        return {"title": hit["title"], "what": hit["what"], "display": display, "name": name, "plain": True}
    first = description.strip().split(". ")[0].rstrip(".") + "." if description.strip() else ""
    return {"title": display, "what": first or "Windows gives no description for this one.", "display": display, "name": name, "plain": False}

# Section order: things you opened first, Windows last.
KINDS = [
    ("browser", "Browsers"), ("ai", "AI tools"), ("chat", "Chat and calls"), ("work", "Work and everyday"),
    ("media", "Games and media"), ("dev", "Developer tools"), ("other", "Other apps"),
    ("hardware", "Drivers and hardware"), ("windows", "Windows"),
]

KIND_RULES = [
    ("ai", ["anthropic", "claude", "openai", "moonshot", "x.ai", "xai", "perplexity", "ollama", "lm studio", "copilot", "gemini", "kimi", "grok"]),
    ("browser", ["mozilla", "google chrome", "brave", "opera", "vivaldi", "browser"]),
    ("chat", ["whatsapp", "telegram", "discord", "slack", "zoom", "teams", "signal", "viber", "messenger"]),
    ("hardware", ["nvidia", "intel", "asus", "asustek", "realtek", "advanced micro devices", "amd ", "dolby", "logitech",
                  "synaptics", "elan micro", "qualcomm", "mediatek", "conexant", "waves audio", "dell", "hp inc",
                  "lenovo", "acer", "micro-star", "razer", "corsair", "steelseries", "nahimic", "a-volute"]),
    ("dev", ["python software foundation", "openjs", "node.js", "jetbrains", "docker", "github", "git for windows", "astral"]),
    ("media", ["spotify", "valve", "epic games", "videolan", "wondershare", "obs project", "xbox"]),
    ("work", ["adobe", "upwork", "notion", "dropbox", "zoho", "google drive", "onedrive", "microsoft office"]),
]
KIND_PATTERNS = [(kind, re.compile("|".join(r"\b" + re.escape(w.strip()) + r"\b" for w in words))) for kind, words in KIND_RULES]

DEFAULT_CLOSE = {"windows": "keep", "hardware": "care", "dev": "care"}
DEFAULT_NOTE = {
    "safe": "It closes. Unsaved work in it may be lost.",
    "care": "Something else may depend on it. Save your work first.",
    "keep": "Part of Windows or a device may stop working until you restart.",
    "critical": "Windows can't run without it. Ending it is blocked.",
}

# Parents we never climb past when deciding which app a process belongs to.
BOUNDARY = {"system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe", "svchost.exe",
            "explorer.exe", "userinit.exe", "sihost.exe", "taskhostw.exe", "lsass.exe", "dllhost.exe",
            "runtimebroker.exe", "applicationframehost.exe"}

STARTED_BY = {
    "explorer.exe": "You, from the desktop, Start menu or taskbar",
    "services.exe": "Windows, as a background service",
    "svchost.exe": "Windows, through one of its services",
    "wininit.exe": "Windows, at start-up", "winlogon.exe": "Windows, at sign-in", "smss.exe": "Windows, at start-up",
    "system": "Windows, at start-up", "userinit.exe": "Windows, at sign-in", "sihost.exe": "Windows, at sign-in",
}

CORE_NAMES = ["svchost.exe", "lsass.exe", "csrss.exe", "services.exe", "winlogon.exe", "explorer.exe", "smss.exe",
              "spoolsv.exe", "dllhost.exe", "taskhostw.exe", "rundll32.exe", "conhost.exe", "wininit.exe", "runtimebroker.exe"]
QUIET_PARENTS = {"calc.exe", "calculatorapp.exe", "notepad.exe", "mspaint.exe", "winver.exe", "minesweeper.exe", "write.exe"}
QUIET_OK_CHILDREN = {"conhost.exe", "werfault.exe", "wermgr.exe", "notepad.exe"}
DOC_PARENTS = {"winword.exe", "excel.exe", "powerpnt.exe", "outlook.exe", "mshta.exe", "wscript.exe", "cscript.exe", "acrord32.exe"}
SHELL_CHILDREN = {"powershell.exe", "pwsh.exe", "cmd.exe", "rundll32.exe", "regsvr32.exe", "mshta.exe", "certutil.exe", "bitsadmin.exe"}

GENERIC_DESCRIPTIONS = {"host process for windows services"}


def _near_miss(a, b):
    """True when a and b differ by exactly one edit."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        return len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


CHROMIUM_TYPES = {
    "renderer": ("Page", "Draws one page, tab or window's content."),
    "gpu-process": ("Graphics helper", "Uses the graphics card to draw the app smoothly."),
    "crashpad-handler": ("Crash reporter", "Waits in case the app crashes, to save a report."),
    "broker": ("Security broker", "Hands out permissions to the app's sandboxed parts."),
    "zygote": ("Process starter", "Starts the app's other parts quickly."),
}
UTILITY_SUBTYPES = {
    "node.mojom": ("Extension runner", "Runs the app's extensions or plugins."),
    "network": ("Network helper", "Handles the app's internet connections."),
    "storage": ("Storage helper", "Reads and writes the app's saved data."),
    "audio": ("Audio helper", "Plays the app's sound."),
    "video_capture": ("Camera helper", "Talks to your camera."),
    "data_decoder": ("Data decoder", "Safely unpacks images and data the app downloads."),
    "unzip": ("Unzip helper", "Unpacks downloaded files."),
    "printing": ("Printing helper", "Prepares pages for printing."),
}
FIREFOX_TYPES = {
    "tab": ("Tabs", "Runs a group of your open tabs."),
    "gpu": ("Graphics helper", "Uses the graphics card to draw Firefox smoothly."),
    "socket": ("Network helper", "Handles Firefox's internet connections."),
    "rdd": ("Media decoder", "Decodes video and audio safely."),
    "utility": ("Utility helper", "Does a background job for Firefox, such as audio or file access."),
    "gmplugin": ("Media plugin", "Plays protected video, such as Netflix."),
}
JAVA_ROLES = [
    ("GradleDaemon", "Gradle build helper", "Keeps Gradle loaded so Java and Android builds are faster."),
    ("GradleWrapperMain", "Gradle build", "Building a Java or Android project."),
    ("org.jetbrains.kotlin.daemon", "Kotlin compiler helper", "Keeps the Kotlin compiler loaded so builds are faster."),
    ("org.codehaus.plexus.classworlds", "Maven build", "Building a Java project with Maven."),
    ("org.eclipse.jdt.ls", "Java code helper", "Gives your editor autocomplete and error checking for Java."),
    ("org.elasticsearch", "Elasticsearch", "Search database running on your PC."),
    ("org.apache.catalina", "Tomcat web server", "Java web server running on your PC."),
    ("kafka.Kafka", "Kafka", "Message system running on your PC."),
    ("org.apache.zookeeper", "ZooKeeper", "Coordination service running on your PC."),
    ("org.neo4j", "Neo4j database", "Graph database running on your PC."),
    ("net.minecraft", "Minecraft", "The Minecraft game."),
    ("sonarlint", "SonarLint", "Checks your code for problems in the editor."),
    ("jenkins", "Jenkins", "Build server running on your PC."),
    ("burpsuite", "Burp Suite", "Web security testing tool."),
    ("com.charlesproxy", "Charles Proxy", "Records web traffic for developers."),
]
PYTHON_MODULES = {
    "azure.cli": "Azure command line", "jupyterlab": "JupyterLab", "notebook": "Jupyter Notebook",
    "ipykernel_launcher": "Jupyter notebook kernel", "ipykernel": "Jupyter notebook kernel",
    "uvicorn": "Uvicorn web server", "gunicorn": "Gunicorn web server", "flask": "Flask web server",
    "http.server": "simple web server", "streamlit": "Streamlit app", "celery": "Celery worker",
    "pytest": "pytest tests", "pylsp": "Python code helper", "debugpy": "Python debugger", "pip": "pip installer",
    "mypy": "mypy type checker", "black": "Black code formatter", "ruff": "Ruff code checker",
}
NODE_PACKAGES = {
    "typescript": ("TypeScript code helper", "Gives your editor autocomplete and error checking for TypeScript."),
    "@anthropic-ai/claude-code": ("Claude Code", "Anthropic's AI coding assistant in the terminal."),
    "@openai/codex": ("Codex CLI", "OpenAI's AI coding assistant in the terminal."),
    "@google/gemini-cli": ("Gemini CLI", "Google's AI coding assistant in the terminal."),
    "@playwright/mcp": ("Playwright browser tool", "Lets an AI assistant control a web browser."),
    "next": ("Next.js dev server", "Runs a Next.js website on your PC while you build it."),
    "vite": ("Vite dev server", "Runs a website on your PC while you build it."),
    "webpack": ("webpack", "Bundles a website's code."),
    "eslint": ("ESLint", "Checks JavaScript code for problems."),
    "prettier": ("Prettier", "Tidies code formatting."),
    "jest": ("Jest tests", "Runs JavaScript tests."),
    "nodemon": ("nodemon", "Restarts a program when its files change."),
    "vercel": ("Vercel command line", "Deploys websites to Vercel."),
    "netlify-cli": ("Netlify command line", "Deploys websites to Netlify."),
    "firebase-tools": ("Firebase command line", "Works with Google Firebase."),
    "wrangler": ("Cloudflare Wrangler", "Builds and deploys Cloudflare Workers."),
}
GENERIC_SCRIPTS = {"index.js", "main.js", "cli.js", "server.js", "app.js", "run.js", "index.mjs", "cli.mjs", "main.py", "server.py", "__main__.py", "app.py"}


def _script_label(path):
    base = os.path.basename(path)
    if base.lower() in GENERIC_SCRIPTS:
        parent = os.path.basename(os.path.dirname(path))
        if parent.lower() in ("dist", "build", "lib", "bin", "src", "out"):
            parent = os.path.basename(os.path.dirname(os.path.dirname(path)))
        return f"{parent}/{base}"
    return base


def part_role(lname, args):
    """Work out what one part of an app does from its start command. Returns (label, what) or None."""
    if not args:
        return None
    rest = args[1:]
    joined = " ".join(rest)
    m = re.search(r"--type=([\w-]+)", joined)
    if m:
        kind = m.group(1)
        if kind == "utility":
            sub = re.search(r"--utility-sub-type=([\w.]+)", joined)
            sub = (sub.group(1) if sub else "").lower()
            for key, val in UTILITY_SUBTYPES.items():
                if key in sub:
                    return val
            return ("Utility helper", "Does one background job for the app.")
        return CHROMIUM_TYPES.get(kind, (kind.replace("-", " ").capitalize(), "A helper part of the app."))
    if lname == "firefox.exe":
        if "-contentproc" in rest:
            last = rest[-1].lower() if rest else ""
            return FIREFOX_TYPES.get(last, ("Helper", "A helper part of Firefox."))
        return ("Main window", "The main Firefox program. Closing it closes all its parts.")
    if lname in ("java.exe", "javaw.exe"):
        for needle, label, what in JAVA_ROLES:
            if needle.lower() in joined.lower():
                return (label, what)
        if "-jar" in rest:
            i = rest.index("-jar")
            if i + 1 < len(rest):
                jar = os.path.basename(rest[i + 1])
                return (f"Runs {jar}", f"Runs the Java program {jar}.")
        main = next((a for a in reversed(rest) if not a.startswith("-") and "." in a and "\\" not in a and "/" not in a), None)
        return (f"Runs {main.split('.')[-1]}", f"Runs the Java program {main}.") if main else None
    if lname == "dotnet.exe":
        if rest and rest[0] in ("run", "build", "test", "watch", "publish", "restore"):
            return (f"dotnet {rest[0]}", f"Running \"dotnet {rest[0]}\" on a .NET project.")
        if "vbcscompiler" in joined.lower():
            return ("C# compiler (kept ready)", "Keeps the C# compiler loaded so builds are faster.")
        if "msbuild" in joined.lower():
            return ("Build worker", "Builds part of a .NET project.")
        dll = next((a for a in rest if a.lower().endswith(".dll")), None)
        if dll:
            return (f"Runs {os.path.basename(dll)}", f"Runs the .NET program {os.path.basename(dll)}.")
        return None
    if lname == "msbuild.exe" and "/nodemode:" in joined.lower():
        return ("Build worker", "One of MSBuild's helpers, building part of a project in parallel.")
    if lname in ("python.exe", "pythonw.exe"):
        if "-m" in rest:
            i = rest.index("-m")
            if i + 1 < len(rest):
                mod = rest[i + 1]
                friendly = PYTHON_MODULES.get(mod) or PYTHON_MODULES.get(mod.split(".")[0])
                if friendly:
                    return (friendly, f"Runs {friendly} (Python module {mod}).")
                return (f"Runs {mod}", f"Runs the Python module {mod}.")
        for a in rest:
            if a.lower().endswith((".py", ".pyw")):
                label = _script_label(a)
                return (f"Runs {label}", f"Runs the Python script {label}.")
        return None
    if lname == "node.exe":
        for i, a in enumerate(rest):
            base = os.path.basename(a).lower()
            if base in ("npx-cli.js", "npm-cli.js"):
                pkg = next((x for x in rest[i + 1:] if not x.startswith("-")), None)
                if pkg:
                    bare = re.sub(r"(?<=.)@[^/]*$", "", pkg)
                    if bare in NODE_PACKAGES:
                        return NODE_PACKAGES[bare]
                    return (f"Runs {pkg}", f"Runs the JavaScript tool {pkg}, downloaded with npx.")
            if base.endswith((".js", ".mjs", ".cjs")):
                if base == "tsserver.js":
                    return NODE_PACKAGES["typescript"]
                m = re.search(r"node_modules[\\/]((?:@[^\\/]+[\\/])?[^\\/]+)", a)
                if m:
                    pkg = m.group(1).replace("\\", "/")
                    if pkg in NODE_PACKAGES:
                        return NODE_PACKAGES[pkg]
                    return (f"Runs {pkg}", f"Runs the JavaScript tool {pkg}.")
                label = _script_label(a)
                return (f"Runs {label}", f"Runs the JavaScript file {label}.")
        return None
    if lname in ("uvx.exe", "npx.exe", "npx.cmd"):
        pkg = next((x for x in rest if not x.startswith("-")), None)
        if pkg:
            return (f"Starts {pkg}", f"Downloads if needed, then starts the tool {pkg}.")
    if lname in ("powershell.exe", "pwsh.exe"):
        for i, a in enumerate(rest):
            if a.lower() == "-file" and i + 1 < len(rest):
                return (f"Runs {os.path.basename(rest[i + 1])}", f"Runs the PowerShell script {os.path.basename(rest[i + 1])}.")
    return None


GENERIC_TITLES = {"update", "updater", "launcher", "helper", "setup", "service", "app", "application", "host", "agent"}


def made_by(company):
    return f"Made by {company.rstrip('. ')}."


def pretty_name(exe):
    base = re.sub(r"\.exe$", "", exe, flags=re.I)
    base = re.sub(r"[_\-.]+", " ", base)
    return base[:1].upper() + base[1:]


def in_windows_dir(path):
    return bool(path) and path.lower().startswith(WINDIR)


def classify(lname, path, info):
    known = lookup(lname)
    if known and known.get("kind"):
        return known["kind"]
    hay = " ".join([lname, (info.get("CompanyName") or ""), (info.get("ProductName") or ""), (path or "")]).lower()
    for kind, pattern in KIND_PATTERNS:
        if pattern.search(hay):
            return kind
    company = (info.get("CompanyName") or "").lower()
    if in_windows_dir(path) or "microsoft" in company:
        return "windows"
    return "other"


def folder_label(path):
    if not path:
        return None
    low = path.lower()
    home = os.path.expanduser("~").lower()
    if low.startswith(WINDIR):
        return "Windows system folder"
    if "\\windowsapps\\" in low:
        return "Microsoft Store apps folder"
    if low.startswith(home + "\\appdata"):
        return "Your AppData folder (per-user apps and tools)"
    if low.startswith(home + "\\downloads"):
        return "Your Downloads folder"
    if low.startswith(home):
        return "Your user folder"
    if "\\program files" in low:
        return "Program Files (installed apps)"
    if "\\programdata\\" in low:
        return "ProgramData (shared app data)"
    return os.path.dirname(path)


class Explainer:
    def __init__(self, procs, cpu, paths, svc_by_pid, svc_cfg, enricher, admin, cmdlines=None):
        self.cmdlines = cmdlines or {}
        self.procs = procs
        self.cpu = cpu
        self.paths = paths
        self.svc_by_pid = svc_by_pid
        self.svc_cfg = svc_cfg
        self.enricher = enricher
        self.admin = admin

    # ---------------------------------------------------------- per process

    def path_for(self, pid):
        path = self.paths.get(pid)
        if path:
            return path, "process"
        for s in self.svc_by_pid.get(pid, []):
            binary = (self.svc_cfg.get(s["name"]) or {}).get("binary", "")
            m = re.match(r'\s*"([^"]+)"|\s*(\S+\.exe)', binary, re.I)
            if m:
                return os.path.expandvars(m.group(1) or m.group(2)), "service"
        return None, None

    def parent_of(self, p):
        par = self.procs.get(p["ppid"])
        if par and par["pid"] != p["pid"] and par["create"] <= p["create"] and p["pid"] not in (0, 4):
            return par
        return None

    def describe(self, p):
        lname = p["name"].lower()
        path, path_source = self.path_for(p["pid"])
        info = file_info(path) if path else {}
        known = lookup(lname)
        services = [plain_service(s["name"], s["display"], (self.svc_cfg.get(s["name"]) or {}).get("description", ""))
                    for s in self.svc_by_pid.get(p["pid"], []) if s["state"] == "Running"]
        desc = info.get("FileDescription")
        if desc and desc.lower() in GENERIC_DESCRIPTIONS:
            desc = None
        pkg = package_name(path)

        if lname == "svchost.exe" and services:
            first = services[0]
            titles = list(dict.fromkeys(s["title"] for s in services))
            title = titles[0] + (f" and {len(titles) - 1} more" if len(titles) > 1 else "")
            what = first["what"] if len(titles) == 1 else "Holds these Windows helpers: " + ", ".join(titles) + "."
            source = "Built-in plain-words list" if all(s["plain"] for s in services) else "Windows service list"
        elif known:
            title, what, source = known["title"], known["what"], "Built-in plain-words list"
        elif desc:
            title, source = desc, "The file's own description"
            what = ""
        elif info.get("ProductName"):
            title, what, source = info["ProductName"], "", "The file's product name"
        elif pkg:
            title, what, source = pkg, "", "Its app package name"
        else:
            title, what, source = pretty_name(p["name"]), "", "File name only"

        if services and source != "Built-in plain-words list" and services[0]["plain"]:
            title, what, source = services[0]["title"], services[0]["what"], "Built-in plain-words list"
        if not what:
            if services:
                what = " ".join(s["what"] for s in services[:2])
            elif desc and desc != title:
                what = desc
            elif info.get("CompanyName"):
                what = made_by(info["CompanyName"])
            elif path:
                where = folder_label(path) or "an unusual folder"
                what = f"No description inside the file. It lives in {where[0].lower() + where[1:]}."
            elif self.admin:
                what = "Windows protects this one, so its details can't be read."
            else:
                what = "Windows hides this one's details. Restart as admin to see what it is."

        rich = self.enricher.get(path) if path else None
        kind = classify(lname, path, info)
        close = (known or {}).get("close") or DEFAULT_CLOSE.get(kind, "safe")
        role = part_role(lname, self.cmdlines.get(p["pid"]))
        return {
            "role": role[0] if role else None, "role_what": role[1] if role else None,
            "pid": p["pid"], "name": p["name"], "lname": lname, "title": title, "what": what, "kind": kind,
            "source": source, "path": path, "path_from_service": path_source == "service",
            "folder": folder_label(path), "company": info.get("CompanyName"),
            "signer": (rich or {}).get("signer"), "signature": (rich or {}).get("status") if rich else ("Checking" if path else None),
            "icon": (rich or {}).get("icon") or None,
            "services": services, "close": close,
            "note": (known or {}).get("note") or DEFAULT_NOTE[close],
            "cpu": round(self.cpu.get(p["pid"], 0.0), 1), "mem": p["private_ws"],
            "threads": p["threads"], "handles": p["handles"], "hidden": not path and not known,
        }

    # ---------------------------------------------------------- unusual notes

    def unusual(self, d, parent):
        notes = []
        ln, path = d["lname"], d["path"]
        pn = parent["name"].lower() if parent else None
        if pn in QUIET_PARENTS and ln not in QUIET_OK_CHILDREN:
            notes.append(f"{pretty_name(parent['name'])} normally doesn't start other programs, but it started {d['name']}.")
        if pn in DOC_PARENTS and ln in SHELL_CHILDREN:
            notes.append(f"{pretty_name(parent['name'])} started {d['name']}. Documents and scripts starting command tools is a common trick.")
        if path and ln in CORE_NAMES and not in_windows_dir(path):
            notes.append(f"It's named like a Windows part ({d['name']}) but runs from outside the Windows folder.")
        if path and not in_windows_dir(path):
            for core in CORE_NAMES:
                if _near_miss(ln, core):
                    notes.append(f"Its name is one letter off a Windows part ({core}).")
                    break
        if ln == "svchost.exe" and parent and pn != "services.exe":
            notes.append(f"Windows service hosts are normally started by services.exe, but this one was started by {parent['name']}.")
        if path:
            low = path.lower()
            if "\\appdata\\local\\temp\\" in low or "\\downloads\\" in low:
                notes.append("It runs straight from your Downloads or Temp folder. Installers do this; most apps don't.")
        return notes

    # ---------------------------------------------------------- grouping

    def build(self):
        live = {pid: p for pid, p in self.procs.items() if pid != 0}
        described = {pid: self.describe(p) for pid, p in live.items()}
        parents = {pid: self.parent_of(p) for pid, p in live.items()}
        children = {}
        for pid, par in parents.items():
            if par:
                children.setdefault(par["pid"], []).append(pid)

        def root_of(pid):
            seen = set()
            cur = pid
            while cur not in seen:
                seen.add(cur)
                par = parents.get(cur)
                if not par or par["name"].lower() in BOUNDARY:
                    return cur
                cur = par["pid"]
            return cur

        groups = {}
        for pid in live:
            r = root_of(pid)
            if r != pid:
                continue
            gid = described[pid]["lname"]
            groups.setdefault(gid, []).append(pid)

        out = []
        for gid, roots in groups.items():
            first = described[roots[0]]
            members = []

            def tree(pid, depth):
                d = dict(described[pid])
                par = parents.get(pid)
                d["unusual"] = self.unusual(d, par)
                d["depth"] = depth
                members.append(d)
                kids = [c for c in children.get(pid, []) if c in described and root_of(c) != c]
                node = {k: d[k] for k in ("pid", "name", "title", "what", "cpu", "mem", "unusual", "kind", "signature", "signer", "path", "folder", "source", "services", "icon")}
                if d["role"]:
                    node["title"] = f"{d['title']}: {d['role']}" if d["role"][0].isupper() and not d["role"].startswith(("Runs", "Starts")) else f"{d['title']} · {d['role']}"
                    node["what"] = d["role_what"]
                node["children"] = [tree(c, depth + 1) for c in sorted(kids, key=lambda c: described[c]["title"].lower())]
                return node

            parts = [tree(r, 0) for r in sorted(roots, key=lambda r: live[r]["create"])]
            starter = parents.get(roots[0])
            if starter is None:
                started_by = "Windows, at start-up" if first["lname"] in ("system", "registry", "secure system", "memory compression") else "A program that has already closed"
            else:
                started_by = STARTED_BY.get(starter["name"].lower()) or described.get(starter["pid"], {}).get("title") or starter["name"]

            is_services = gid == "svchost.exe"
            title = "Windows services" if is_services else first["title"]
            what = ("Windows' built-in background helpers: Wi-Fi, sound, updates, printing and more. Open it to see each one."
                    if is_services else first["what"])
            notes = [n for m in members for n in m["unusual"]]
            icon = next((m["icon"] for m in members if m["icon"] and m["lname"] == first["lname"]), None)
            out.append({
                "id": gid, "title": title, "what": what, "kind": first["kind"], "close": first["close"],
                "note": first["note"], "cpu": round(sum(m["cpu"] for m in members), 1),
                "mem": sum(m["mem"] for m in members), "count": len(members), "icon": icon,
                "path": first["path"], "folder": first["folder"], "company": first["company"],
                "signer": first["signer"], "signature": first["signature"], "source": first["source"],
                "started_by": started_by, "hidden": first["hidden"], "unusual": notes,
                "pids": [m["pid"] for m in members], "parts": parts, "exe": first["name"],
            })

        # One row per app: helpers with the same name and kind (e.g. a service and its tray part) merge.
        merged = {}
        for g in out:
            key = (g["title"].lower(), g["kind"])
            m = merged.get(key)
            if m is None:
                merged[key] = g
                continue
            m["cpu"] = round(m["cpu"] + g["cpu"], 1)
            m["mem"] += g["mem"]
            m["count"] += g["count"]
            m["pids"] += g["pids"]
            m["parts"] += g["parts"]
            m["unusual"] += g["unusual"]
            m["icon"] = m["icon"] or g["icon"]
        return list(merged.values())
