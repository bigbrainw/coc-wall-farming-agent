"""Keep live spectator badges from masking scout and battle controls."""
import unittest

from screen_reader import classify_screen


class LiveSpectatorTests(unittest.TestCase):
    def classify(self, *texts):
        return classify_screen([
            {"text": text, "conf": 1, "box": [.5, .5, .1, .1]}
            for text in texts
        ])["screen"]

    def test_live_scout(self):
        self.assertEqual(self.classify("Spectators:", "Battle starts in:", "Next", "End Battle"), "scout")

    def test_live_battle(self):
        self.assertEqual(self.classify("Spectators:", "Battle ends in:", "End Battle"), "battle")

    def test_settled_result(self):
        self.assertEqual(self.classify("Spectators:", "Victory", "Troops expended:"), "results")

    def test_explicit_replay_still_wins(self):
        for label in ("Replay", "Live replay", "Troops available:"):
            with self.subTest(label=label):
                self.assertEqual(self.classify(label, "Spectators:", "Battle ends in:"), "replay")

    def test_spectators_without_live_controls_remains_replay(self):
        self.assertEqual(self.classify("Spectators:"), "replay")


if __name__ == "__main__":
    unittest.main()
