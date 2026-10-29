"""Grouping and close labels, checked with made-up processes so the results don't depend on this PC."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
import knowledge  # noqa: E402

DL = r"C:\Users\someone\Downloads"
FF = r"C:\Program Files\Mozilla Firefox"
MB = r"C:\Program Files\Malwarebytes\Anti-Malware"


class NoEnrich:
    def get(self, path):
        return None


def build(rows, cmdlines=None, self_pids=()):
    """rows: (pid, parent pid, file name, full path or None). Processes start in the order given."""
    procs, paths = {}, {}
    for t, (pid, ppid, name, path) in enumerate(rows, 1):
        procs[pid] = {"pid": pid, "ppid": ppid, "name": name, "create": t, "private_ws": 10_000_000, "threads": 1, "handles": 1}
        paths[pid] = path
    old = knowledge.SELF_PIDS
    knowledge.SELF_PIDS = set(self_pids)
    try:
        groups = knowledge.Explainer(procs, {}, paths, {}, {}, NoEnrich(), admin=True, cmdlines=cmdlines).build()
    finally:
        knowledge.SELF_PIDS = old
    return groups


def find(groups, pid):
    return next(g for g in groups if pid in g["pids"])


BASE = [(10, 1, "explorer.exe", r"C:\Windows\explorer.exe"), (5, 1, "services.exe", r"C:\Windows\System32\services.exe")]


class Grouping(unittest.TestCase):
    def test_same_file_name_from_different_makers_stays_apart(self):
        groups = build(BASE + [
            (20, 10, "widget-agent.exe", r"C:\Program Files\Vendor A\widget-agent.exe"),
            (30, 10, "widget-agent.exe", r"C:\Program Files\Vendor B\widget-agent.exe"),
        ])
        a, b = find(groups, 20), find(groups, 30)
        self.assertIsNot(a, b)
        self.assertEqual(a["pids"], [20])  # so End task on one never ends the other
        self.assertEqual(b["pids"], [30])

    def test_each_script_copy_is_its_own_app(self):
        groups = build(BASE + [
            (20, 10, "node.exe", r"C:\Program Files\nodejs\node.exe"),
            (30, 10, "node.exe", r"C:\Program Files\nodejs\node.exe"),
        ], cmdlines={20: ["node", r"C:\proj\shop\bot.js"], 30: ["node", r"C:\proj\blog\build.js"]})
        a, b = find(groups, 20), find(groups, 30)
        self.assertIsNot(a, b)
        self.assertIn("bot.js", a["title"])
        self.assertIn("build.js", b["title"])

    def test_copies_that_look_the_same_are_numbered(self):
        groups = build(BASE + [
            (20, 10, "dllhost.exe", r"C:\Windows\System32\dllhost.exe"),
            (30, 10, "dllhost.exe", r"C:\Windows\System32\dllhost.exe"),
        ])
        self.assertEqual(sorted(g["title"] for g in groups if g["exe"] == "dllhost.exe"),
                         ["Add-on runner (copy 1 of 2)", "Add-on runner (copy 2 of 2)"])

    def test_one_apps_service_and_window_merge(self):
        groups = build(BASE + [
            (20, 5, "MBAMService.exe", MB + r"\MBAMService.exe"),
            (30, 10, "Malwarebytes.exe", MB + r"\Malwarebytes.exe"),
        ])
        self.assertIs(find(groups, 20), find(groups, 30))

    def test_program_opened_from_browser_is_its_own_app(self):
        groups = build(BASE + [
            (20, 10, "firefox.exe", FF + r"\firefox.exe"),
            (21, 20, "firefox.exe", FF + r"\firefox.exe"),
            (40, 20, "zz-setup.exe", DL + r"\zz-setup.exe"),
            (41, 40, "zz-helper.exe", DL + r"\zz-helper.exe"),
        ])
        ff, tool = find(groups, 20), find(groups, 40)
        self.assertEqual(sorted(ff["pids"]), [20, 21])
        self.assertEqual(sorted(tool["pids"]), [40, 41])
        self.assertTrue(tool["started_by"].startswith("Firefox"))
        self.assertEqual(ff["unusual"], [])

    def test_notes_name_the_part_and_never_repeat(self):
        groups = build(BASE + [
            (40, 10, "zz-setup.exe", DL + r"\zz-setup.exe"),
            (41, 40, "zz-helper.exe", DL + r"\zz-helper.exe"),
            (42, 40, "zz-helper.exe", DL + r"\zz-helper.exe"),
        ])
        notes = find(groups, 40)["unusual"]
        self.assertEqual(len(notes), 2)
        self.assertTrue(notes[0].startswith("It runs straight from your Downloads folder"))
        self.assertTrue(notes[1].startswith("zz-helper.exe runs straight from your Downloads folder"))

    def test_this_app_isnt_flagged_for_running_from_downloads(self):
        groups = build(BASE + [
            (30, 10, "PlainProcessViewer.exe", DL + r"\PlainProcessViewer.exe"),
            (31, 30, "PlainProcessViewer.exe", DL + r"\PlainProcessViewer.exe"),
        ], self_pids=(30, 31))
        self.assertEqual(find(groups, 30)["unusual"], [])


class CloseLabels(unittest.TestCase):
    def test_unknown_program_is_impact_unknown_not_safe(self):
        g = find(build(BASE + [(20, 10, "zz-mystery.exe", r"C:\Tools\zz-mystery.exe")]), 20)
        self.assertEqual(g["close"], "unknown")
        self.assertEqual(g["unlisted"], 1)

    def test_unknown_program_in_the_windows_folder_stays_cautious(self):
        g = find(build(BASE + [(20, 10, "zz-mystery.exe", r"C:\Windows\System32\zz-mystery.exe")]), 20)
        self.assertEqual(g["close"], "keep")

    def test_hidden_unknown_program_is_impact_unknown(self):
        g = find(build(BASE + [(20, 10, "zz-hidden.exe", None)]), 20)
        self.assertEqual(g["close"], "unknown")

    def test_part_windows_relies_on_raises_the_app(self):
        knowledge.KNOWN["zz-device-link.exe"] = {"title": "Device link", "what": "Test part.", "kind": "hardware",
                                                 "close": "keep", "note": "The device stops."}
        try:
            g = find(build(BASE + [
                (20, 10, "obsidian.exe", r"C:\Users\me\AppData\Local\Programs\Obsidian\obsidian.exe"),
                (21, 20, "zz-device-link.exe", r"C:\Program Files\Vendor\zz-device-link.exe"),
            ]), 20)
        finally:
            del knowledge.KNOWN["zz-device-link.exe"]
        self.assertEqual(g["close"], "keep")
        self.assertEqual(g["note"], "Device link: The device stops.")

    def test_helper_care_note_doesnt_raise_the_app(self):
        # A helper's "care" note is about its host app, which you're closing anyway.
        g = find(build(BASE + [
            (20, 10, "firefox.exe", FF + r"\firefox.exe"),
            (21, 20, "private_browsing.exe", FF + r"\private_browsing.exe"),
        ]), 20)
        self.assertEqual(g["close"], knowledge.KNOWN["firefox.exe"]["close"])

    def test_merged_programs_of_one_app_take_the_more_serious_label(self):
        groups = build(BASE + [
            (20, 5, "MBAMService.exe", MB + r"\MBAMService.exe"),
            (30, 10, "Malwarebytes.exe", MB + r"\Malwarebytes.exe"),
        ])
        labels = {knowledge.KNOWN["mbamservice.exe"]["close"], knowledge.KNOWN["malwarebytes.exe"]["close"]}
        self.assertEqual(find(groups, 20)["close"], max(labels, key=knowledge.SEVERITY.get))

    def test_unknown_part_doesnt_change_a_known_app(self):
        g = find(build(BASE + [
            (20, 10, "firefox.exe", FF + r"\firefox.exe"),
            (21, 20, "zz-plugin.exe", FF + r"\zz-plugin.exe"),
        ]), 20)
        self.assertEqual(g["close"], knowledge.KNOWN["firefox.exe"]["close"])
        self.assertEqual(g["unlisted"], 1)


class InstallRoot(unittest.TestCase):
    def test_roots(self):
        r = knowledge.install_root
        self.assertEqual(r(r"C:\Program Files\Vendor A\bin\x.exe"), r"c:\program files\vendor a")
        self.assertEqual(r(r"C:\Program Files\Common Files\Vendor\x.exe"), r"c:\program files\common files\vendor")
        self.assertEqual(r(r"C:\Program Files\WindowsApps\App_1.0_x64__abc\app\x.exe"), r"c:\program files\windowsapps\app_1.0_x64__abc")
        self.assertEqual(r(r"C:\Users\me\AppData\Local\Programs\Tool\x.exe"), r"c:\users\me\appdata\local\programs\tool")
        self.assertEqual(r(r"C:\Users\me\AppData\Roaming\Vendor\x.exe"), r"c:\users\me\appdata\roaming\vendor")
        self.assertIsNone(r(None))


if __name__ == "__main__":
    unittest.main()
