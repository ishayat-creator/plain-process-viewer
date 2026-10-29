# Plain Process Viewer

A Windows task manager that tells you, in plain words, what each running process is for, so you know what you're closing before you close it.

It is **not an antivirus**. It explains what's running; it can't tell you whether something is safe.

## What it does

- **Groups processes into apps.** 447 processes on a typical PC become about 110 rows: Firefox, Claude, Windows services and so on. Each app expands to show its parts.
- **Names every part.** "Firefox: Tabs", "Claude: Network helper", "Node.js · Runs reddit-mcp-buddy/cli.js", "BitLocker Drive Encryption Service" instead of `firefox.exe`, `claude.exe`, `node.exe`, `svchost.exe`.
- **Sorts apps by kind** with filter chips: Browsers, AI tools, Chat and calls, Work, Games and media, Developer tools, Drivers and hardware, Windows.
- **Says what happens if you close it**: Safe to close, Close with care, Don't close, or Windows needs it (ending those is blocked).
- **Shows who started what**, who made it, whether it's signed, where it lives, and where each name came from.
- **Notes unusual things** as information, never as a verdict: Notepad or Calculator starting other programs, Office starting PowerShell, Windows names running outside the Windows folder, names one letter off a Windows part, programs running from Downloads or Temp.
- **Startup apps** and **Services** tabs, explained the same way.
- Follows the Windows light or dark theme, with a toggle.

Nothing leaves your PC. The basic version uses no internet and no keys.

## Where names come from

In this order: the built-in plain-words list (`app/data/known.json`), Windows' service list, the file's own description, its product name, its app package name, then the file name. The details panel always says which one was used.

## Run it

Needs Windows 10 or 11 and Python 3.11+ ([uv](https://docs.astral.sh/uv/) makes setup one line).

```
uv venv .venv
uv pip install --python .venv\Scripts\python.exe flask psutil pywin32 pywebview
```

Then double-click **Plain Process Viewer.cmd**. It opens in its own window. To open it in your browser instead:

```
.venv\Scripts\python.exe main.py --browser
```

Windows hides some details unless the app runs as admin; the app offers a **Restart as admin** button when that's the case.

## How it's built

| File | Job |
| --- | --- |
| `app/sysinfo.py` | Reads every process in one system call (`NtQuerySystemInformation`): parent, CPU time, and the same private-memory figure Task Manager shows. Also file details and services. |
| `app/knowledge.py` | Groups processes into apps, names each part, picks the kind, close label and unusual notes. |
| `app/data/known.json` | The plain-words list. Written for this app; add entries here. |
| `app/enrich.py`, `enrich.ps1` | Signatures and icons, checked once per file in the background and cached in `%LOCALAPPDATA%\PlainProcessViewer`. |
| `app/startup.py` | Startup apps from the Run keys and Startup folders, with their on/off state. |
| `app/server.py` | Local server on 127.0.0.1 with a per-launch token. Ending a process re-checks it's the same process and refuses Windows-critical ones. |
| `app/static/` | The interface. |
| `main.py` | Opens the app window (pywebview, using Edge WebView2). |

## Planned

- Settings page with optional keys: EchoTrail (descriptions and usual-parent check) and Claude ("explain this in plain words"). Each user brings their own key.
- An open, community-improved plain-words list that the app updates from.
- Turning startup apps on and off from inside the app.
