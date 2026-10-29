"""Hides your user name and common secrets in text before it leaves the app (the Ask-an-AI question).
It catches common patterns, not every possible secret, so the app asks you to check the text before you share it."""
import os
import re

HOME = os.path.expanduser("~")
SECRET = r"(?:pass(?:word|wd|phrase)?|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|key|auth\w*|bearer|credential\w*|cookie|session)"
VALUE = r"""(?:"[^"]*"|'[^']*'|[^\s"'&]+)"""

RULES = [
    # Your own user folder, written with either kind of slash.
    (re.compile(r"(?i)" + r"[\\/]+".join(re.escape(p) for p in re.split(r"[\\/]+", HOME)) + r"(?![\w-])"), "%USERPROFILE%"),
    # Other people's user folders.
    (re.compile(r"(?i)\b([a-z]:[\\/]+users[\\/]+)(?!public\b|default\b|all users\b|%)[^\\/\s\"']+"), r"\1[user]"),
    # Sign-in details inside a web address: https://name:password@site or https://token@site.
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s/@\"']+@"), r"\1[hidden]@"),
    # "Bearer abc..." and "Basic abc..." sign-in headers.
    (re.compile(r"(?i)\b(bearer|basic)\s+[\w.~+/=-]{8,}"), r"\1 [hidden]"),
    # --password value, --password "two words", /token:value, -api-key=value.
    (re.compile(r"(?i)(?<!\w)((?:--?|/)[\w.-]*" + SECRET + r"[\w.-]*)(\s*[=:]\s*|\s+)" + VALUE), r"\1\2[hidden]"),
    # password=value, API_KEY=value, "token": "value", ?api_key=value in a web address.
    (re.compile(r"(?i)(?<![\w.-])([\w.-]*" + SECRET + r"[\w.-]*[\"']?)(\s*=\s*|:\s*)" + VALUE), r"\1\2[hidden]"),
    # Keys that announce themselves (OpenAI, GitHub, Slack, AWS, Google).
    (re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w{20,}|xox[abprs]-[\w-]{10,}|AKIA[0-9A-Z]{16}|AIza[\w-]{30,})"), "[hidden]"),
    # Email addresses.
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[email hidden]"),
    # Long random-looking strings (letters and digits mixed) are usually keys or tokens.
    (re.compile(r"\b(?=[A-Za-z0-9_\-]*\d)(?=[A-Za-z0-9_\-]*[A-Za-z])[A-Za-z0-9_\-]{32,}\b"), "[hidden]"),
]


def mask(text):
    if not text:
        return text
    for pattern, replacement in RULES:
        text = pattern.sub(replacement, text)
    return text
