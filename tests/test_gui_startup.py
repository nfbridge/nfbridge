# SPDX-License-Identifier: GPL-3.0-only
"""The main window must start its event polling and honour --demo without user input."""
import os
import sys
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for name in ('app', 'mac-client', 'mac-connection'):
    sys.path.insert(0, str(ROOT / name))

import gui  # noqa: E402


_ROOT = None
_ROOT_ERROR = None


def _shared_root():
    """Create the Tk root once per process. Some Tcl/Tk 9 builds crash when a
    second root is created after the first was destroyed, so it is never destroyed here."""
    global _ROOT, _ROOT_ERROR
    if _ROOT is None and _ROOT_ERROR is None:
        try:
            _ROOT = tk.Tk()
            _ROOT.withdraw()
        except tk.TclError as exc:
            _ROOT_ERROR = exc
    return _ROOT


@unittest.skipUnless(_shared_root() is not None, 'no display for Tk')
class StartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = _shared_root()

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        for child in self.root.winfo_children():
            child.destroy()

    def tearDown(self):
        self.home.cleanup()

    def _pump(self, rounds=60):
        for _ in range(rounds):
            self.root.update()
            time.sleep(0.02)

    def test_polling_starts_and_demo_loads(self):
        app = gui.App(self.root, self.home.name, demo=True)
        self.root.update()
        pending = self.root.tk.call('after', 'info')
        self.assertTrue(pending, 'poll loop must be scheduled at startup')
        self.assertEqual(len(app.store.entries()), 1, '--demo must load the synthetic roll')

    def test_background_result_reaches_main_thread(self):
        app = gui.App(self.root, self.home.name)
        seen = []
        app.run(lambda: 'ok', seen.append)
        for _ in range(60):
            self.root.update()
            if seen:
                break
            time.sleep(0.02)
        self.assertEqual(seen, ['ok'])
        self.assertFalse(app.busy)

    def test_header_hover_has_no_side_effects(self):
        app = gui.App(self.root, self.home.name)
        self.root.update()
        app.frames.identify_region = lambda x, y: 'heading'
        app.frames.identify_column = lambda x: '#1'
        app.frame_header_motion(type('E', (), {'x': 3, 'y': 3})())
        self.assertEqual(len(app.store.entries()), 0)


if __name__ == '__main__':
    unittest.main()
