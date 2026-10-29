"""Writes THIRD-PARTY-NOTICES.txt: the licences of everything packed into PlainProcessViewer.exe.
Run with the project's Python (.venv\\Scripts\\python.exe); build.ps1 does this before each build."""
import importlib.metadata as md
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "THIRD-PARTY-NOTICES.txt")

# Python packages inside the .exe, and which of their licence files apply to the parts that are packed.
PACKAGES = {
    "flask": None, "werkzeug": ["LICENSE.txt"], "jinja2": None, "markupsafe": None, "itsdangerous": None,
    "click": None, "blinker": None, "psutil": None, "pywebview": None, "bottle": None, "proxy-tools": None,
    "pythonnet": None, "clr-loader": None, "cffi": None, "pycparser": None, "typing-extensions": None,
    "pywin32": ["licenses/win32/License.txt", "licenses/com/License.txt"],
    "pyinstaller": None,
}

# The WebView2 files come inside pywebview without their licence text, so it's kept here (from nuget.org).
WEBVIEW2 = """Copyright (C) Microsoft Corporation. All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

   * Redistributions of source code must retain the above copyright
notice, this list of conditions and the following disclaimer.
   * Redistributions in binary form must reproduce the above
copyright notice, this list of conditions and the following disclaimer
in the documentation and/or other materials provided with the
distribution.
   * The name of Microsoft Corporation, or the names of its contributors
may not be used to endorse or promote products derived from this
software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

RULE = "=" * 78


def licence_texts(dist, wanted):
    files = [f for f in (dist.files or []) if any(k in f.name.upper() for k in ("LICEN", "COPYING", "NOTICE"))]
    if wanted:
        files = [f for f in files if any(str(f).replace("\\", "/").endswith(w) for w in wanted)]
    else:
        files = [f for f in files if ".dist-info" in str(f)]
    return [f.locate().read_text(encoding="utf-8", errors="replace").strip() for f in files]


def main():
    parts = [
        "Third-party notices for Plain Process Viewer",
        "",
        "PlainProcessViewer.exe packs the software below. Each keeps its own licence, reproduced here.",
        "Plain Process Viewer's own licence is in LICENSE.",
    ]

    def section(title, body):
        parts.extend(["", RULE, title, RULE, "", body.strip()])

    with open(os.path.join(sys.base_prefix, "LICENSE.txt"), encoding="utf-8", errors="replace") as f:
        section(f"Python {sys.version.split()[0]} (the Python runtime and its bundled libraries)", f.read())

    # Python's licence file doesn't cover OpenSSL (libcrypto-3.dll, libssl-3.dll), which comes with its ssl and hashlib parts.
    import ssl
    with open(os.path.join(ROOT, "packaging", "licenses", "Apache-2.0.txt"), encoding="utf-8") as f:
        section(f"{ssl.OPENSSL_VERSION.rsplit(' ', 3)[0]} (Apache License 2.0; https://www.openssl.org)", f.read())

    for name, wanted in PACKAGES.items():
        dist = md.distribution(name)
        meta = dist.metadata
        lic = (meta.get("License") or "").strip().splitlines()
        kind = meta.get("License-Expression") or (lic[0] if lic else "")
        texts = licence_texts(dist, wanted)
        body = "\n\n".join(texts) if texts else f"Licensed under {kind}. The package ships no licence text; see https://pypi.org/project/{meta['Name']}/"
        title = f"{meta['Name']} {dist.version}" + (f" ({kind})" if kind and len(kind) < 60 else "")
        if name == "pyinstaller":
            title += ": only its bootloader is inside the .exe, which the licence's exception allows in any program"
        section(title, body)

    section("Microsoft WebView2 SDK (Microsoft.Web.WebView2.Core.dll, .WinForms.dll, WebView2Loader.dll; inside pywebview)", WEBVIEW2)
    section("Microsoft Visual C++ runtime (VCRUNTIME140.dll, VCRUNTIME140_1.dll)",
            "Redistributed as allowed by Microsoft's Visual Studio licence terms for the Visual C++ Redistributable.")

    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(parts) + "\n")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
