"""Secret hiding for the Ask-an-AI question."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
from redact import HOME, mask  # noqa: E402


class Hides(unittest.TestCase):
    def check(self, text, must_hide, keeps=()):
        out = mask(text)
        for secret in must_hide:
            self.assertNotIn(secret, out, f"{secret!r} leaked in {out!r}")
        for kept in keeps:
            self.assertIn(kept, out, f"{kept!r} was hidden in {out!r}")
        return out

    def test_quoted_password_with_spaces(self):
        out = self.check('tool --password "two words secret" --verbose', ["two", "words", "secret"], ["--verbose"])
        self.assertIn("--password [hidden]", out)

    def test_sign_in_inside_a_web_address(self):
        out = self.check("git clone https://alice:shortpass@example.invalid/repo", ["alice", "shortpass"], ["example.invalid/repo"])
        self.assertIn("https://[hidden]@example.invalid", out)
        self.check("https://ghp_abcdefghijklmnopqrstuvwxyz0123@github.com/x", ["ghp_abcdefghijklmnopqrstuvwxyz0123"])

    def test_flags_and_assignments(self):
        self.check("--token=abc123 --api-key xyz789 /secret:s3cr3t", ["abc123", "xyz789", "s3cr3t"])
        self.check("OPENAI_API_KEY=supersecretvalue run", ["supersecretvalue"], ["run"])
        self.check('{"token": "tok-value-1"}', ["tok-value-1"])
        self.check("https://site.invalid/cb?api_key=k123&page=2", ["k123"], ["page=2"])

    def test_headers_and_known_key_shapes(self):
        self.check('curl -H "Authorization: Bearer eyJhbGciOi.abc.def"', ["eyJhbGciOi.abc.def"])
        self.check("key sk-proj-ABCDEFGHIJKLMNOPQRST and AKIAABCDEFGHIJKLMNOP", ["sk-proj-ABCDEFGHIJKLMNOPQRST", "AKIAABCDEFGHIJKLMNOP"])

    def test_user_folders_and_email(self):
        out = self.check(HOME + r"\proj\a.py and " + HOME.replace("\\", "/") + "/b.py", [HOME, HOME.replace("\\", "/")])
        self.assertEqual(out.count("%USERPROFILE%"), 2)
        self.check(r"C:\Users\SomeoneElse\x.exe", ["SomeoneElse"], [r"C:\Users\[user]"])
        self.check("git config user.email me.name@example.com", ["me.name@example.com"])

    def test_long_random_strings(self):
        self.check("session 9f8e7d6c5b4a39281706f5e4d3c2b1a0ffeeddcc", ["9f8e7d6c5b4a39281706f5e4d3c2b1a0ffeeddcc"])


class LeavesPlainTextAlone(unittest.TestCase):
    def test_prose_and_labels(self):
        text = ("Name shown: Windows Security\nMade by: Microsoft\nSignature: signed by Microsoft Windows\n"
                "Handles sign-in authentication for apps.\nStarts with Windows: yes, it's in the startup list and turned on\n"
                "File: codex-windows-sandbox-service.exe")
        self.assertEqual(mask(text), text)


if __name__ == "__main__":
    unittest.main()
