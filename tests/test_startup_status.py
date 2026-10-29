"""Startup-list wording says only what was checked."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
import startup  # noqa: E402

FOUND = [
    {"path": r"C:\Apps\on.exe", "enabled": True},
    {"path": r"C:\Apps\off.exe", "enabled": False},
]


class Status(unittest.TestCase):
    def test_on_off_and_not_found(self):
        self.assertEqual(startup.status(r"c:\apps\ON.exe", FOUND), "on")
        self.assertEqual(startup.status(r"C:\Apps\off.exe", FOUND), "off")
        self.assertIsNone(startup.status(r"C:\Apps\other.exe", FOUND))
        self.assertIsNone(startup.status(None, FOUND))

    def test_not_found_doesnt_claim_no(self):
        text = startup.STATUS_TEXT[None]
        self.assertTrue(text.startswith("not found in"))
        self.assertIn("weren't checked", text)


if __name__ == "__main__":
    unittest.main()
