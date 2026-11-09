"""Offline test of search_to_scout on real recorded controller frames (real OCR, no device).

  python3 test_search_to_scout.py
"""
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from PIL import Image

from coc_android import GuardError
from farming_cutoff import CutoffSession
from screen_reader import ocr

FRAMES = Path(__file__).resolve().parents[2] / \
    "decision_traces/adb-farming-20261103/recorded-wall-farming-v10"
SEQ = ["r765-home.png", "r766-battle.png", "r766-search.png", "r766-attack.png"]


class ReplayDevice:
    """Serves the frame that the real game showed after N taps."""

    def __init__(self, seq):
        self.seq, self.taps, self.n = seq, [], 0

    def observe(self, path):
        src = self.seq[min(len(self.taps), len(self.seq) - 1)]
        shutil.copy(src, path)
        self.n += 1
        return {"frameId": f"replay-{self.n}", "capturedAtMs": self.n, "size": [1280, 960],
                "path": path}

    def tap(self, x, y):
        self.taps.append((x, y))


@unittest.skipUnless(all((FRAMES / f).exists() for f in SEQ), "recorded frames missing")
class SearchToScoutTests(unittest.TestCase):
    def session(self, seq):
        dev = ReplayDevice([str(FRAMES / f) if isinstance(f, str) else f for f in seq])
        return dev, CutoffSession(dev, tempfile.mkdtemp(), read_ocr=ocr)

    def test_three_grounded_clicks_reach_scout(self):
        dev, s = self.session(SEQ)
        r = s.search_to_scout({})
        self.assertEqual(r["stopped"], "scout_reached_agent_verification_required")
        self.assertEqual([st["label"] for st in r["steps"]], ["Battle", "Ordinary_FindMatch", "Attack"])
        (bx, by), (fx, fy), (ax, ay) = dev.taps
        self.assertTrue(bx < 200 and by > 880)              # home Battle, bottom-left
        self.assertTrue(abs(fx - 244) < 40 and abs(fy - 652) < 30)  # left (ordinary) Find a Match
        self.assertTrue(ax > 1000 and 700 < ay < 770)       # My Army Attack!
        self.assertFalse(s.armed)                           # deployment still needs the agent
        self.assertIn("352/352", r["armyCounts"])

    def test_ranked_find_a_match_is_never_clicked(self):
        tmp = Path(tempfile.mkdtemp())
        menu = Image.open(FRAMES / "r766-battle.png").convert("RGB")
        menu.paste((0, 0, 0), (100, 560, 420, 720))        # hide the ordinary column only
        menu.save(tmp / "menu.png")
        dev, s = self.session(["r765-home.png", str(tmp / "menu.png")])
        r = s.search_to_scout({})
        self.assertEqual(r["stopped"], "ordinary_find_a_match_not_verified")
        self.assertEqual(len(dev.taps), 1)                  # only the home Battle button

    def test_not_home_issues_no_input(self):
        dev, s = self.session(["r766-attack.png"])
        r = s.search_to_scout({})
        self.assertEqual(r["stopped"], "home_battle_button_not_verified")
        self.assertEqual(dev.taps, [])

    def test_refused_while_armed_or_after_cutoff(self):
        for attr, value in (("armed", True), ("cutoff", {"status": "x"})):
            dev, s = self.session(SEQ)
            setattr(s, attr, value)
            with self.assertRaises(GuardError):
                s.search_to_scout({})
            self.assertEqual(dev.taps, [])


RESULT, HOME = "01772-requested.png", "r776-home.png"


@unittest.skipUnless(all((FRAMES / f).exists() for f in (RESULT, HOME)), "recorded frames missing")
class AutoReturnHomeTests(unittest.TestCase):
    def session(self, seq):
        dev = ReplayDevice([str(FRAMES / f) for f in seq])
        s = CutoffSession(dev, tempfile.mkdtemp(), read_ocr=ocr)
        s.halted = True
        s.cutoff = {"trigger": {"frameId": "t1"}, "status": "result"}
        return dev, s

    def test_settled_result_saved_then_one_verified_return_home(self):
        dev, s = self.session([RESULT, HOME])
        s.return_home_after_result(settle_timeout=10, home_timeout=5)
        self.assertEqual(len(dev.taps), 1)
        x, y = dev.taps[0]
        self.assertTrue(abs(x - 640) < 20 and abs(y - 811) < 20)
        self.assertEqual(s.cutoff["status"], "returned_home")
        self.assertTrue(Path(s.cutoff["settledResult"]["path"]).exists())
        # a later agent Return Home tap is refused (would hit the village)
        r = s.command({"command": "batch", "batch": {"id": "x", "actions": [
            {"kind": "ui", "label": "Return Home", "point": [640, 811]}]}})
        self.assertEqual(r["cancelled"], "return_home_already_handled_by_watcher")
        # next search may start straight away: verified home is an implicit reset
        r = s.search_to_scout({})
        self.assertIsNone(s.cutoff)
        self.assertEqual(dev.taps[1][0] < 200, True)  # home Battle button

    def test_no_results_screen_means_no_tap(self):
        dev, s = self.session([HOME])
        s.return_home_after_result(settle_timeout=2, home_timeout=1)
        self.assertEqual(dev.taps, [])
        self.assertEqual(s.cutoff["status"], "result_not_settled_agent_return_required")
        with self.assertRaises(GuardError):
            s.search_to_scout({})


ZERO, LIVE_UNREADABLE = "r785-ring-3.png", "r750-remaining-main20.png"


@unittest.skipUnless(all((FRAMES / f).exists() for f in (ZERO, LIVE_UNREADABLE)), "recorded frames missing")
class ValkyrieZeroTests(unittest.TestCase):
    def counts(self, name):
        s = CutoffSession(object(), tempfile.mkdtemp(), read_ocr=ocr)
        return s.inventory_badges({"frameId": Path(name).stem, "path": str(FRAMES / name)})

    def test_grey_empty_card_reads_zero(self):
        self.assertEqual(self.counts(ZERO), {"valkyries": 0, "earthquakes": 11})

    def test_cyrillic_x16_reads_sixteen(self):
        # live r814: OCR returned "ХІБ" for x16 and halted the ring (2026-11-05)
        name = "spectator-fix-session/r814-ring1.png"
        if not (FRAMES / name).exists():
            self.skipTest("frame missing")
        self.assertEqual(self.counts(name)["valkyries"], 16)

    def test_coloured_card_never_becomes_zero(self):
        self.assertNotEqual(self.counts(LIVE_UNREADABLE)["valkyries"], 0)


if __name__ == "__main__":
    unittest.main()
