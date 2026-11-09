import json
import os
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image

from coc_android import GuardError
from farming_cutoff import (CutoffSession, battle_end_point, configure_command_terminal,
                            confirm_end_point, deployment_rejected, parse_hud, parse_inventory_badges, read_commands,
                            recover_damage_percentage, recover_earthquake_zero, recover_valkyrie_count,
                            settled_result_numbers)


def line(text, x, y, w=.1, h=.03, conf=1):
    return {"text": text, "box": [x, y, w, h], "conf": conf}


BATTLE = [line("Battle ends in:", .45, .02), line("End Battle", .03, .68)]
DIALOG = BATTLE + [line("End Battle?", .39, .32, .22),
    line("Chief, are you sure you want to end the fight", .26, .43, .48),
    line("Cancel", .32, .60), line("Okay", .58, .60)]
RESULT = [line("Victory", .43, .27), line("Troops expended:", .43, .64)]


class FakeDevice:
    def __init__(self):
        self.inputs = []

    def run_batch(self, batch, path):
        self.inputs.extend(batch["actions"])
        Image.new("RGB", (1280, 960)).save(path)
        return {"issued": [{"issuedAtMs": 2000}], "observation": {
            "frameId": Path(path).stem, "capturedAtMs": 2100,
            "size": [1280, 960], "path": path}}


class CutoffTests(unittest.TestCase):
    def test_red_warning_above_dialog_is_checked_in_existing_hud_ocr(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "battle.png"
            frame = Image.new("RGB", (1280, 960))
            frame.paste("red", (320, 260, 960, 285))
            frame.save(path)
            calls = []
            def read(paths):
                calls.append(paths)
                warning = next(p for p in paths if Path(p).name == "deployment-warning-live.png")
                with Image.open(warning) as crop:
                    self.assertEqual(crop.size, (1580, 180))
                    self.assertEqual(crop.getpixel((200, 110)), 255)
                return {p: ([line("You cannot deploy troops on the red area!", .1, .1)]
                            if p == warning else []) for p in paths}
            s = CutoffSession(FakeDevice(), directory, read_ocr=read)
            hud = s.hud({"path": str(path), "frameId": "warning"})
            self.assertTrue(hud["deploymentRejected"])
            self.assertFalse(hud["blocked"])
            self.assertEqual(len(calls), 1)
        self.assertFalse(deployment_rejected([line("Overall Damage", .1, .1)]))
        self.assertFalse(deployment_rejected([line("Cannot deploy", .1, .1, conf=.4)]))
        self.assertTrue(deployment_rejected([line("You cannot deplóy troops ön the red;area!", .1, .1)]))

    def test_full_frame_end_button_requires_unique_exact_label_in_live_panel(self):
        button = line("End Battle", .02, .68, .12, .03)
        self.assertEqual(battle_end_point([button]), [102, 667])
        for lines in [[], [button, button], [dict(button, conf=.94)],
                      [line("End Battle?", .02, .68)],
                      [line("End Battle", .4, .3)], [line("Return Home", .02, .68)]]:
            self.assertIsNone(battle_end_point(lines))

    def test_threshold_with_missing_compact_button_ends_before_inventory_read(self):
        with tempfile.TemporaryDirectory() as directory:
            s, dev, obs = self.setup_session(directory)
            s.hud = lambda _: {"battle": True, "damage": 56, "endPoint": None}
            s.read_ocr = lambda paths: {p: BATTLE for p in paths}
            ended = []
            s.finish = lambda frame, hud: ended.append((frame, hud))
            s.check(obs)
            self.assertEqual(len(ended), 1)
            self.assertEqual(ended[0][1]["endPoint"], battle_end_point(BATTLE))

    def test_missing_compact_button_never_uses_full_frame_with_blocking_overlay(self):
        with tempfile.TemporaryDirectory() as directory:
            s, dev, obs = self.setup_session(directory)
            s.hud = lambda _: {"battle": True, "damage": 56, "endPoint": None}
            s.read_ocr = lambda paths: {p: BATTLE + [line("Connection lost", .3, .4)] for p in paths}
            s.finish = lambda *args: self.fail("Blocked frame must not end")
            self.assertIsNone(s.check(obs)["endPoint"])

    def test_result_signature_ignores_incidental_numbers_but_tracks_loot(self):
        values = [("56%", 640, 158), ("151 595", 595, 445),
                  ("417529", 595, 505), ("9198", 595, 570),
                  ("+322500", 1055, 488), ("+322500", 1055, 535),
                  ("+2386", 1055, 585)]
        lines = [line(t, x / 1280 - .025, y / 960 - .015, .05)
                 for t, x, y in values]
        expected = ("56%", "151595", "417529", "9198", "+322500", "+322500", "+2386")
        self.assertEqual(settled_result_numbers(lines), expected)
        for text in ["95", "94", "44", "43"]:
            self.assertEqual(settled_result_numbers(lines + [line(text, .2, .8)]), expected)
        changed = [dict(l) for l in lines]
        changed[1]["text"] = "151596"
        self.assertNotEqual(settled_result_numbers(changed), expected)
        for bad in [lines[:-1], lines + [lines[1]],
                    [dict(l, conf=.89) if i == 2 else l for i, l in enumerate(lines)]]:
            self.assertIsNone(settled_result_numbers(bad))

    def test_troop_recovery_requires_two_unconflicted_count_readings(self):
        missing = {"valkyries": None, "earthquakes": 0}
        def read(value): return {"valkyries": value, "earthquakes": None}
        self.assertEqual(recover_valkyrie_count(missing, list(map(read, [None, 36, 36]))),
                         {"valkyries": 36, "earthquakes": 0})
        for values in [[36, None, None], [36, 36, 35], [None, None, None]]:
            self.assertEqual(recover_valkyrie_count(missing, list(map(read, values))), missing)
        existing = {"valkyries": 37, "earthquakes": 0}
        self.assertEqual(recover_valkyrie_count(existing, [read(36), read(36)]), existing)
        self.assertEqual(missing["valkyries"], None)

    def test_troop_badge_recovery_reads_pixels_and_keeps_unknowns(self):
        with tempfile.TemporaryDirectory() as directory:
            frame = Path(directory) / "battle.png"
            Image.new("RGB", (1280, 960)).save(frame)
            def read(paths):
                return {p: ([line("×36", .2, .08)] if "-valk-threshold" in p
                            else [line("ХЗБ", .2, .08), line("XO", .3, .6)]) for p in paths}
            session = CutoffSession(FakeDevice(), directory, read_ocr=read)
            self.assertEqual(session.inventory_badges({"frameId": "recovery", "path": str(frame)}),
                             {"valkyries": 36, "earthquakes": 0})

    def test_zero_recovery_needs_two_readings_without_conflict(self):
        original = {"valkyries": 41, "earthquakes": None}
        def read(value): return {"valkyries": None, "earthquakes": value}
        self.assertEqual(recover_earthquake_zero(original, [read(None), read(0), read(0)]),
                         {"valkyries": 41, "earthquakes": 0})
        for values in [[0, None, None], [0, 0, 11], [None, None, None], [11, 11, 11]]:
            self.assertEqual(recover_earthquake_zero(original, list(map(read, values))), original)
        self.assertEqual(original["earthquakes"], None)
        positive = {"valkyries": None, "earthquakes": 11}
        self.assertEqual(recover_earthquake_zero(positive, [read(0), read(0)]), positive)

    def test_disabled_badge_recovery_preserves_missing_troop_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            frame = Path(directory) / "battle.png"
            Image.new("RGB", (1280, 960)).save(frame)
            def read(paths):
                return {p: ([line("XO", .3, .6)] if "threshold" in p else []) for p in paths}
            session = CutoffSession(FakeDevice(), directory, read_ocr=read)
            counts = session.inventory_badges({"frameId": "blank", "path": str(frame)})
            self.assertEqual(counts, {"valkyries": None, "earthquakes": 0})

    def test_inventory_missing_duplicate_or_low_confidence_stays_unknown(self):
        badges = [line("X21)", .2, .08, conf=1), line("XO", .3, .6, conf=1)]
        self.assertEqual(parse_inventory_badges(badges), {"valkyries": 21, "earthquakes": 0})
        self.assertIsNone(parse_inventory_badges(badges + [badges[0]])["valkyries"])
        self.assertIsNone(parse_inventory_badges([line("X21", .2, .08, conf=.9)])["valkyries"])
        self.assertIsNone(parse_inventory_badges([line("21", .2, .08)])["valkyries"])
        self.assertEqual(parse_inventory_badges([line("Х36", .2, .08)])["valkyries"], 36)
        self.assertIsNone(parse_inventory_badges([line("ХЗБ", .2, .08)])["valkyries"])

    def test_plan_cancels_later_steps_when_inventory_does_not_match(self):
        with tempfile.TemporaryDirectory() as directory:
            s, dev, obs = self.setup_session(directory)
            s.latest = obs
            s.check = lambda *args: {"battle": True, "damage": 0, "endPoint": [100, 670]}
            readings = iter([{"valkyries": 44, "earthquakes": 11},
                             {"valkyries": 42, "earthquakes": 0}])
            s.inventory_badges = lambda _: next(readings)
            steps = [{"batch": {"id": str(i), "deadline": {"seconds": 180, "capturedAtMs": 10**15},
                                "actions": [{"kind": "spell", "point": [100, 100]}]},
                      "expectedCounts": {"valkyries": 41, "earthquakes": 0}} for i in range(2)]
            result = s.deployment_plan({"id": "test-plan", "steps": steps,
                "initialExpectedCounts": {"valkyries": 44, "earthquakes": 11}})
            self.assertEqual(result["stopped"], "inventory_mismatch_or_unreadable")
            self.assertEqual(len(dev.inputs), 1)

    def test_plan_prechecks_initial_counts_before_any_input(self):
        with tempfile.TemporaryDirectory() as directory:
            s, dev, obs = self.setup_session(directory)
            s.latest = obs
            s.check = lambda *args: {"battle": True, "damage": 0, "endPoint": [100, 670]}
            s.inventory_badges = lambda _: {"valkyries": None, "earthquakes": 11}
            step = {"batch": {"id": "test", "deadline": {"seconds": 180},
                              "actions": [{"kind": "spell", "point": [100, 100]}]},
                    "expectedCounts": {"valkyries": 41, "earthquakes": 0}}
            result = s.deployment_plan({"id": "test-plan", "steps": [step],
                "initialExpectedCounts": {"valkyries": 44, "earthquakes": 11}})
            self.assertEqual(result["stopped"], "initial_inventory_mismatch_or_unreadable")
            self.assertEqual(dev.inputs, [])

    def test_expired_plan_deadline_cancels_input_but_keeps_cutoff_armed(self):
        with tempfile.TemporaryDirectory() as directory:
            s, dev, obs = self.setup_session(directory)
            s.latest = obs
            s.hud = lambda _: {"battle": True, "damage": 49, "endPoint": [100, 670]}
            s.check = lambda *args: s.hud(obs)
            s.inventory_badges = lambda _: {"valkyries": 7, "earthquakes": 0}
            step = {"batch": {"id": "expired", "deadline": {"seconds": 44, "capturedAtMs": 0},
                              "actions": [{"kind": "spawn", "point": [100, 100]}]},
                    "expectedCounts": {"valkyries": 0, "earthquakes": 0}}
            result = s.deployment_plan({"id": "expired-plan", "steps": [step],
                "initialExpectedCounts": {"valkyries": 7, "earthquakes": 0}})
            self.assertEqual(result["stopped"], "battle_deadline_fresh_observation_required")
            self.assertEqual(dev.inputs, [])
            self.assertTrue(s.armed)
            self.assertFalse(s.halted)
            # The next regular poll must still execute the normal 50% cutoff.
            del s.check
            s.hud = lambda _: {"battle": True, "damage": 50, "endPoint": [100, 670]}
            s.check(obs)
            self.assertEqual(len(dev.inputs), 2)
            self.assertEqual(s.cutoff["status"], "result")

    def test_plan_does_not_continue_after_cutoff_between_steps(self):
        with tempfile.TemporaryDirectory() as directory:
            s, dev, obs = self.setup_session(directory)
            s.latest = obs
            checks = []
            def check(*args):
                checks.append(1)
                if len(checks) == 3:  # after the first step's fresh observation
                    s.halted = True
                    s.armed = False
                    s.cutoff = {"damage": 50}
                return {"battle": True, "damage": 0, "endPoint": [100, 670]}
            s.check = check
            s.inventory_badges = lambda _: {"valkyries": 44, "earthquakes": 11}
            steps = [{"batch": {"id": str(i), "deadline": {"seconds": 180, "capturedAtMs": 10**15},
                                "actions": [{"kind": "spell", "point": [100, 100]}]},
                      "expectedCounts": {"valkyries": 41, "earthquakes": 0}} for i in range(2)]
            result = s.deployment_plan({"id": "test-plan", "steps": steps,
                "initialExpectedCounts": {"valkyries": 44, "earthquakes": 11}})
            self.assertEqual(result["stopped"], "cutoff_or_unexpected_screen")
            self.assertEqual(len(dev.inputs), 1)

    def test_long_command_survives_real_terminal_without_truncation(self):
        import pty
        import termios
        master, slave = pty.openpty()
        with os.fdopen(slave, "r", encoding="utf-8") as stream:
            original = configure_command_terminal(stream)
            requests = queue.Queue()
            reader = threading.Thread(target=read_commands, args=(stream, requests), daemon=True)
            reader.start()
            request = {"command": "status", "evidence": "x" * 12000}
            payload = (json.dumps(request) + '\n{"command":"close"}\n').encode()
            try:
                while payload:
                    written = os.write(master, payload)
                    payload = payload[written:]
                self.assertEqual(requests.get(timeout=3), request)
                self.assertEqual(requests.get(timeout=3), {"command": "close"})
                reader.join(timeout=3)
                self.assertFalse(reader.is_alive())
            finally:
                termios.tcsetattr(stream, termios.TCSANOW, original)
                os.close(master)

    def test_hud_uses_battle_header_button_and_only_damage_panel(self):
        lines = [line("Battle ends in:", .1, .12),
                 line("End Battle", .45, .35), line("50%", .88, .40)]
        self.assertEqual(parse_hud(lines)["damage"], 50)
        self.assertTrue(parse_hud(lines)["battle"])
        self.assertIsNotNone(parse_hud(lines)["endPoint"])
        self.assertIsNone(parse_hud([line("100% Bonus", .88, .4)])["damage"])
        self.assertIsNone(parse_hud([line("50%", .1, .4)])["damage"])
        self.assertIsNone(parse_hud([line("50%", .88, .4, conf=.7)])["damage"])

    def test_damage_crop_recovery_requires_two_strict_agreeing_values(self):
        def crop(text, conf=1):
            return [line(text, .1, .1, conf=conf)]
        self.assertEqual(recover_damage_percentage([crop("28%"), crop("28%")]), 28)
        self.assertEqual(recover_damage_percentage([crop("50%"), crop("50%")]), 50)
        for readings in ([crop("28%")], [crop("28%"), crop("29%")],
                         [crop("28%"), []], [crop("28%"), crop("28%", .9)],
                         [crop("100% Bonus"), crop("100% Bonus")],
                         [crop("W28%"), crop("W28%")],
                         [crop("101%"), crop("101%")],
                         [crop("28%") + crop("50%"), crop("28%")]):
            self.assertIsNone(recover_damage_percentage(readings))

    def test_only_the_real_end_dialog_can_be_confirmed(self):
        self.assertIsNotNone(confirm_end_point(DIALOG))
        unrelated = [line("Confirm Exit", .39, .32), line("Okay", .58, .60),
                     line("Cancel", .32, .6)]
        self.assertIsNone(confirm_end_point(unrelated))
        self.assertIsNone(confirm_end_point([l for l in DIALOG if l["text"] != "Cancel"]))

    def test_saved_end_title_question_mark_ocr_variant(self):
        dialog = [dict(l, text="End Battlez") if l["text"] == "End Battle?" else l
                  for l in DIALOG]
        self.assertIsNotNone(confirm_end_point(dialog))
        for missing in ["Cancel", "Okay", "Chief, are you sure you want to end the fight"]:
            self.assertIsNone(confirm_end_point([l for l in dialog if l["text"] != missing]))
        wrong_position = [dict(l, box=[.03, .68, .1, .03])
                          if l["text"] == "End Battlez" else l for l in dialog]
        self.assertIsNone(confirm_end_point(wrong_position))

    def setup_session(self, directory, dialog=DIALOG):
        dev = FakeDevice()
        def read(paths):
            result = {}
            for p in paths:
                name = Path(p).name
                result[p] = dialog if name == "cutoff-dialog.png" else (
                    RESULT if name == "cutoff-result.png" else BATTLE)
            return result
        session = CutoffSession(dev, directory, read_ocr=read, target_percent=50)
        path = Path(directory) / "battle.png"
        Image.new("RGB", (1280, 960)).save(path)
        obs = {"frameId": "test", "capturedAtMs": 1000, "size": [1280, 960], "path": str(path)}
        session.armed = True
        return session, dev, obs

    def test_49_waits_but_50_ends_and_verifies_okay_once(self):
        with tempfile.TemporaryDirectory() as directory:
            s, dev, obs = self.setup_session(directory)
            s.hud = lambda _: {"battle": True, "damage": 49, "endPoint": [100, 670]}
            s.check(obs)
            self.assertEqual(dev.inputs, [])
            s.hud = lambda _: {"battle": True, "damage": 50, "endPoint": [100, 670]}
            s.check(obs)
            self.assertEqual(len(dev.inputs), 2)
            self.assertIn("End Battle", dev.inputs[0]["label"])
            self.assertIn("Okay", dev.inputs[1]["label"])
            self.assertEqual(s.cutoff["status"], "result")
            s.check(obs)
            self.assertEqual(len(dev.inputs), 2)
            request = {"command": "batch", "batch": {"id": "late",
                       "actions": [{"kind": "spawn", "point": [10, 10]}]}}
            self.assertIn("cancelled", s.command(request))
            self.assertEqual(len(dev.inputs), 2)

    def test_queued_speed_click_is_cancelled_when_fresh_check_hits_cutoff(self):
        with tempfile.TemporaryDirectory() as directory:
            s, dev, obs = self.setup_session(directory)
            s.latest = obs
            s.observe = lambda *args: obs
            s.hud = lambda _: {"battle": True, "damage": 50, "endPoint": [100, 670]}
            response = s.command({"command": "batch", "batch": {"id": "speed",
                "actions": [{"kind": "speed", "label": "Visible 1x", "point": [1220, 525]}]}})
            self.assertEqual(response["cancelled"], "cutoff_or_unexpected_screen")
            self.assertEqual(len(dev.inputs), 2)  # End and confirmation only
            self.assertFalse(any(a["kind"] == "speed" for a in dev.inputs))

    def test_speed_needs_active_battle_and_readable_damage(self):
        with tempfile.TemporaryDirectory() as directory:
            s, dev, obs = self.setup_session(directory)
            s.latest = obs
            request = {"command": "batch", "batch": {"id": "speed",
                "actions": [{"kind": "speed", "point": [1220, 525]}]}}
            s.armed = False
            self.assertEqual(s.command(request)["cancelled"], "speed_needs_active_battle")
            s.armed = True
            s.check = lambda *args: {"battle": True, "damage": None, "endPoint": [100, 670]}
            self.assertEqual(s.command(request)["cancelled"], "damage_observation_required")
            self.assertEqual(dev.inputs, [])
            s.check = lambda *args: {"battle": True, "damage": 49, "endPoint": [100, 670]}
            self.assertIn("receipt", s.command(request))
            self.assertEqual(len(dev.inputs), 1)
            self.assertEqual(dev.inputs[0]["kind"], "speed")

    def test_unexpected_dialog_never_receives_okay_or_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            s, dev, obs = self.setup_session(directory, [line("Connection lost", .3, .4)])
            s.hud = lambda _: {"battle": True, "damage": 65, "endPoint": [100, 670]}
            s.check(obs)
            self.assertEqual(len(dev.inputs), 1)
            self.assertEqual(s.cutoff["status"], "confirmation_not_verified")
            s.check(obs)
            self.assertEqual(len(dev.inputs), 1)

    def test_delayed_end_dialog_is_confirmed_once_without_repeating_end(self):
        with tempfile.TemporaryDirectory() as directory:
            s, dev, obs = self.setup_session(directory, BATTLE)
            s.hud = lambda _: {"battle": True, "damage": 50, "endPoint": [100, 670]}
            s.check(obs)
            self.assertTrue(s.confirmation_pending())
            self.assertEqual(s.cutoff["detectionToEndMs"], 1000)
            self.assertEqual(len(dev.inputs), 1)
            # A black transition frame receives no click. Polling remains read-only.
            s.read_ocr = lambda paths: {p: [] for p in paths}
            s.check(obs)
            self.assertEqual(len(dev.inputs), 1)
            self.assertTrue(s.confirmation_pending())
            s.read_ocr = lambda paths: {p: RESULT if Path(p).name == "cutoff-result.png"
                                      else DIALOG for p in paths}
            s.check(obs)
            self.assertEqual(s.cutoff["status"], "result")
            self.assertEqual(len(dev.inputs), 2)
            s.check(obs)
            self.assertEqual(len(dev.inputs), 2)

    def test_pending_cutoff_accepts_natural_result_without_another_click(self):
        with tempfile.TemporaryDirectory() as directory:
            s, dev, obs = self.setup_session(directory, BATTLE)
            s.hud = lambda _: {"battle": True, "damage": 50, "endPoint": [100, 670]}
            s.check(obs)
            s.read_ocr = lambda paths: {p: RESULT for p in paths}
            s.check(obs)
            self.assertEqual(s.cutoff["status"], "natural_result")
            self.assertEqual(len(dev.inputs), 1)
            self.assertFalse(s.confirmation_pending())

    def test_uncertain_confirmation_is_never_reissued(self):
        with tempfile.TemporaryDirectory() as directory:
            s, dev, obs = self.setup_session(directory, BATTLE)
            s.hud = lambda _: {"battle": True, "damage": 50, "endPoint": [100, 670]}
            s.check(obs)
            s.read_ocr = lambda paths: {p: DIALOG for p in paths}
            def uncertain_input(batch, path):
                dev.inputs.extend(batch["actions"])
                raise RuntimeError("Input may have reached the device")
            dev.run_batch = uncertain_input
            with self.assertRaisesRegex(RuntimeError, "may have reached"):
                s.check(obs)
            self.assertEqual(s.cutoff["status"], "confirmation_input_issued")
            self.assertFalse(s.confirmation_pending())
            s.check(obs)
            self.assertEqual(len(dev.inputs), 2)

    def test_nonbattle_50_or_bonus_never_causes_input(self):
        with tempfile.TemporaryDirectory() as directory:
            s, dev, obs = self.setup_session(directory)
            s.hud = lambda _: {"battle": False, "damage": 100, "endPoint": None}
            s.check(obs)
            self.assertEqual(dev.inputs, [])
            self.assertTrue(s.halted)

    def test_header_miss_requires_full_battle_confirmation_before_cutoff(self):
        with tempfile.TemporaryDirectory() as directory:
            s, dev, obs = self.setup_session(directory)
            s.hud = lambda _: {"battle": False, "damage": 50, "endPoint": [100, 670]}
            s.check(obs)
            self.assertEqual(len(dev.inputs), 2)
            self.assertEqual(s.cutoff["status"], "result")
            self.assertTrue((Path(directory) / "header-fallback.json").exists())

    def test_missing_header_on_disconnect_cannot_use_battle_underlay(self):
        with tempfile.TemporaryDirectory() as directory:
            s, dev, obs = self.setup_session(directory)
            s.read_ocr = lambda paths: {p: BATTLE + [line("Connection lost", .3, .4)] for p in paths}
            s.hud = lambda _: {"battle": False, "damage": 50, "endPoint": [100, 670]}
            s.check(obs)
            self.assertEqual(dev.inputs, [])
            self.assertTrue(s.halted)
            self.assertFalse(s.armed)

    def test_blocking_overlay_over_readable_hud_cancels_deployment_and_cutoff(self):
        cases = [(damage, overlay) for damage in (47, 52) for overlay in
                 ("Connection lost", "Clash of Clans isn't responding",
                  "Clash of Clans is not responding")]
        for damage, overlay in cases:
            with self.subTest(damage=damage, overlay=overlay), tempfile.TemporaryDirectory() as directory:
                s, dev, obs = self.setup_session(directory)
                hud_lines = [line("Battle ends in:", .1, .12),
                             line("Surrender", .45, .35), line(f"{damage}%", .88, .40)]
                s.latest = obs
                s.observe = lambda label="watch": obs
                s.read_ocr = lambda paths: {
                    p: ([line(overlay, .1, .4)]
                        if Path(p).name == "overlay-live.png" else hud_lines) for p in paths}
                result = s.command({"command": "batch", "batch": {"id": "blocked-deploy",
                    "actions": [{"kind": "spawn", "point": [10, 10]}]}})
                self.assertTrue(s.halted)
                self.assertFalse(s.armed)
                self.assertIsNone(s.cutoff)
                self.assertEqual(dev.inputs, [])
                self.assertEqual(result["cancelled"], "cutoff_or_unexpected_screen")
                stopped = json.loads((Path(directory) / "watch-stopped.json").read_text())
                self.assertEqual(stopped["reason"], "blocking_overlay")

    def test_resume_never_rearms_a_completed_cutoff(self):
        with tempfile.TemporaryDirectory() as directory:
            s, dev, obs = self.setup_session(directory)
            s.hud = lambda _: {"battle": True, "damage": 50, "endPoint": [100, 670]}
            s.check(obs)
            with self.assertRaisesRegex(RuntimeError, "Cannot resume"):
                s.command({"command": "resume"})
            self.assertEqual(len(dev.inputs), 2)

    def test_unreadable_damage_defers_deployment_without_stopping_polls(self):
        with tempfile.TemporaryDirectory() as directory:
            s, dev, obs = self.setup_session(directory)
            s.check = lambda: {"battle": True, "damage": None, "endPoint": [100, 670]}
            response = s.command({"command": "batch", "batch": {"id": "unreadable",
                "actions": [{"kind": "spawn", "point": [10, 10]}]}})
            self.assertEqual(response["cancelled"], "damage_observation_required")
            self.assertTrue(s.armed)
            self.assertFalse(s.halted)
            self.assertEqual(dev.inputs, [])


class ScoutPinchTests(unittest.TestCase):
    class Dev:
        def __init__(self):
            self.pinches = []
            self.swipes = []
        def observe(self, path):
            Image.new("RGB", (1280, 960)).save(path)
            return {"frameId": Path(path).stem, "capturedAtMs": 1, "size": [1280, 960], "path": path}
        def pinch(self, direction, ms=400):
            self.pinches.append((direction, ms))
        def swipe(self, *points, ms=300):
            self.swipes.append((points, ms))

    def session(self, lines):
        dev = self.Dev()
        return dev, CutoffSession(dev, tempfile.mkdtemp(), read_ocr=lambda paths: {paths[0]: lines})

    def test_scout_pinch_on_verified_scout(self):
        dev, s = self.session([line("Next", .85, .63), line("Battle starts in:", .44, .02)])
        s.command({"command": "scout_pinch_out"})
        self.assertEqual(dev.pinches, [("out", 400)])

    def test_slow_scout_gestures_and_navigation_guards(self):
        scout = [line("Next", .85, .63), line("Battle starts in:", .44, .02)]
        dev, s = self.session(scout)
        s.command({"command": "scout_pinch_out", "durationMs": 1200})
        s.command({"command": "scout_pan", "start": [250, 400],
                   "end": [750, 400], "durationMs": 1200})
        self.assertEqual(dev.pinches, [("out", 1200)])
        self.assertEqual(dev.swipes, [((250, 400, 750, 400), 1200)])
        for request in [
                {"command": "scout_pan", "start": [95, 670], "end": [750, 400]},
                {"command": "scout_pan", "start": [250, 400], "end": [750, 400], "durationMs": 5000},
                {"command": "scout_pinch_out", "durationMs": True}]:
            with self.assertRaises(Exception):
                s.command(request)
        s.armed = True
        with self.assertRaises(Exception):
            s.command({"command": "scout_pan", "start": [250, 400], "end": [750, 400]})
        dev2, home = self.session([line("Shop", .9, .52)])
        with self.assertRaises(Exception):
            home.command({"command": "scout_pan", "start": [250, 400], "end": [750, 400]})
        self.assertEqual(len(dev.swipes), 1)
        self.assertEqual(dev2.swipes, [])

    def test_scout_pinch_refused_on_home_or_armed(self):
        dev, s = self.session([line("Shop", .9, .52)])
        with self.assertRaises(Exception):
            s.command({"command": "scout_pinch_out"})
        dev2, s2 = self.session([line("Next", .85, .63)])
        s2.armed = True
        with self.assertRaises(Exception):
            s2.command({"command": "scout_pinch_out"})
        self.assertEqual(dev.pinches + dev2.pinches, [])


class BuildingsListPanTests(unittest.TestCase):
    Dev = ScoutPinchTests.Dev
    session = ScoutPinchTests.session

    def test_list_scroll_requires_title_clear_panel_and_valid_geometry(self):
        request = {"command": "buildings_list_pan", "start": [1000, 760],
                   "end": [1000, 180], "durationMs": 200}
        title = [line("Buildings & Heroes", .69, .02, .23)]
        dev, s = self.session(title)
        result = s.command(request)
        self.assertEqual(dev.swipes, [((1000, 760, 1000, 180), 200)])
        self.assertIn("gestureReceipt", result)
        for labels in [[], BATTLE, title + [line("Cost Min", .3, .5)],
                       title + [line("Connection lost", .3, .5)]]:
            dev2, other = self.session(labels)
            with self.assertRaises(Exception):
                other.command(request)
            self.assertEqual(dev2.swipes, [])
        for patch in [{"start": [700, 760]}, {"end": [1100, 180]},
                      {"end": [1000, 700]}, {"durationMs": True}]:
            with self.assertRaises(Exception):
                s.command({**request, **patch})
        s.armed = True
        with self.assertRaises(Exception):
            s.command(request)
        s.armed = False
        s.cutoff = {"damage": 50}
        with self.assertRaises(Exception):
            s.command(request)
        self.assertEqual(len(dev.swipes), 1)


class ArmyPickerPanTests(unittest.TestCase):
    Dev = ScoutPinchTests.Dev
    session = ScoutPinchTests.session

    def test_army_picker_scroll_accepts_dialog_and_records_one_gesture(self):
        labels = [line("My Army", .1, .22), line("Saved Recipes", .4, .22),
                  line("Cookbook", .7, .22)]
        dev, s = self.session(labels)
        response = s.command({"command": "army_picker_pan", "start": [1130, 866],
                              "end": [410, 866], "durationMs": 500})
        self.assertEqual(dev.swipes, [((1130, 866, 410, 866), 500)])
        self.assertEqual(response["observation"]["size"], [1280, 960])
        self.assertIn("issuedAtMs", response["gestureReceipt"])

    def test_army_picker_scroll_refuses_other_screens_overlay_and_battle_state(self):
        labels = [line("My Army", .1, .22), line("Saved Recipes", .4, .22),
                  line("Cookbook", .7, .22)]
        request = {"command": "army_picker_pan", "start": [1130, 866], "end": [410, 866]}
        for lines in [[line("Shop", .9, .52)], BATTLE, RESULT,
                      labels + [line("Connection lost", .3, .4)]]:
            dev, s = self.session(lines)
            with self.assertRaisesRegex(Exception, "verified My Army"):
                s.command(request)
            self.assertEqual(dev.swipes, [])
        for state in ["armed", "cutoff"]:
            dev, s = self.session(labels)
            setattr(s, state, True if state == "armed" else {"damage": 50})
            with self.assertRaisesRegex(Exception, "between attacks"):
                s.command(request)
            self.assertEqual(dev.swipes, [])

    def test_army_picker_scroll_rejects_outside_short_vertical_and_invalid_duration(self):
        labels = [line("My Army", .1, .22), line("Saved Recipes", .4, .22),
                  line("Cookbook", .7, .22)]
        dev, s = self.session(labels)
        request = {"command": "army_picker_pan", "start": [1130, 866], "end": [410, 866]}
        for override in [{"start": [1130, 600]}, {"end": [410, 930]},
                         {"end": [410, 800]}, {"end": [1100, 866]},
                         {"durationMs": True}, {"durationMs": 5000}]:
            with self.assertRaises(Exception):
                s.command({**request, **override})
        self.assertEqual(dev.swipes, [])


class RecordingTests(unittest.TestCase):
    def test_missing_recording_drive_does_not_disarm_or_halt_play(self):
        with tempfile.TemporaryDirectory() as directory:
            dev = FakeDevice()
            dev.stream = object()
            session = CutoffSession(dev, directory)
            session.armed = True
            response = session.command({"command": "record_start", "raid": "r571",
                                        "root": directory + "/missing/footage"})
            self.assertIn("drive not mounted", response["recordError"])
            self.assertTrue(session.armed)
            self.assertFalse(session.halted)
            self.assertIsNone(session.recording)
            self.assertEqual(dev.inputs, [])

    class Stream:
        def __init__(self):
            self.started, self.stopped = [], 0
        def start_recording(self, path):
            self.started.append(path)
            return {"path": path, "leadInPackets": 3}
        def stop_recording(self):
            self.stopped += 1
            return {"frames": 10, "bytes": 1000, "durationMs": 700,
                    "videoStartPtsUs": 5, "videoStartHostMs": 6}

    def session(self):
        dev = FakeDevice()
        dev.stream = self.Stream()
        root = tempfile.mkdtemp()
        s = CutoffSession(dev, tempfile.mkdtemp(), read_ocr=lambda paths: {paths[0]: BATTLE})
        s.record_root = os.path.join(root, "attack-footage")
        return dev, s

    def test_record_cycle_writes_events_then_meta_last(self):
        dev, s = self.session()
        rec = s.command({"command": "record_start", "raid": "r9/x"})["recording"]
        self.assertTrue(rec["id"].endswith("-r9x"))
        self.assertFalse(os.path.exists(os.path.join(rec["dir"], "meta.json")))
        s.command({"command": "batch", "batch": {"id": "b1", "checkpoint": {"size": [1280, 960]},
                   "actions": [{"kind": "tap", "label": "t", "point": [1, 2]}]}})
        meta = s.command({"command": "record_stop", "meta": {"percent": 52}})["meta"]
        self.assertEqual((meta["frames"], meta["percent"], dev.stream.stopped), (10, 52, 1))
        events = [json.loads(l) for l in open(rec["events"])]
        self.assertEqual([e["type"] for e in events][:2], ["note", "batch"])
        self.assertEqual(events[1]["actions"][0]["point"], [1, 2])
        self.assertEqual(events[1]["actions"][0]["issuedAtMs"], 2000)
        self.assertTrue(os.path.exists(os.path.join(rec["dir"], "meta.json")))
        self.assertIsNone(s.recording)

    def test_record_needs_stream_and_no_double_start(self):
        dev, s = self.session()
        recording = s.command({"command": "record_start", "raid": "a"})["recording"]
        response = s.command({"command": "record_start", "raid": "b"})
        self.assertIn("Already recording", response["recordError"])
        self.assertEqual(response["recording"], recording)
        self.assertEqual(s.recording, recording)
        self.assertFalse(s.armed)
        self.assertFalse(s.halted)
        dev2 = FakeDevice()
        s2 = CutoffSession(dev2, tempfile.mkdtemp())
        response = s2.command({"command": "record_start", "raid": "c"})
        self.assertIn("needs the --stream", response["recordError"])
        self.assertIsNone(response["recording"])
        self.assertFalse(s2.armed)
        self.assertFalse(s2.halted)
        self.assertEqual(dev2.inputs, [])

    def test_stop_without_recording_is_noop(self):
        _, s = self.session()
        self.assertEqual(s.record_stop(), {"recording": None})


class RingDeployTests(unittest.TestCase):
    RING = [[330, 250], [560, 120], [820, 140], [1010, 300], [1000, 560],
            [760, 690], [470, 690], [200, 420]]

    def session(self):
        import time
        s = CutoffSession(FakeDevice(), tempfile.mkdtemp(), read_ocr=lambda paths: {})
        s.plans = []
        s.deployment_plan = lambda request: s.plans.append(request) or {"stopped": "stub"}
        self.now = int(time.time() * 1000)
        return s

    def request(self, **over):
        req = {"command": "ring_deploy", "id": "r1-ring", "anchors": self.RING,
               "boundaryCapturedAtMs": self.now, "valkyrieSelect": [150, 780],
               "checkpoint": {"frameId": "boundary-frame", "size": [1280, 960],
                              "legalSpawns": [{"point": p, "evidence": "Outside current red boundary by 40px"}
                                              for p in self.RING]},
               "valkyries": 44, "earthquakes": 0,
               "deadline": {"seconds": 150, "capturedAtMs": self.now, "rate": 1}}
        req.update(over)
        return req

    def test_spreads_all_valkyries_round_robin_in_bounded_steps(self):
        s = self.session()
        s.command(self.request())
        plan = s.plans[0]
        self.assertEqual(plan["initialExpectedCounts"], {"valkyries": 44, "earthquakes": 0})
        steps = plan["steps"]
        self.assertTrue(all(len(st["batch"]["actions"]) <= 20 for st in steps))
        self.assertEqual(steps[0]["batch"]["actions"][0]["kind"], "select")
        spawns = [a["point"] for st in steps for a in st["batch"]["actions"] if a["kind"] == "spawn"]
        self.assertEqual(len(spawns), 44)
        self.assertEqual(spawns[:8], self.RING)  # one per anchor around the ring, in order
        self.assertEqual([st["expectedCounts"]["valkyries"] for st in steps], [25, 5, 0])
        self.assertTrue(all(st["batch"]["deadline"] for st in steps))
        # Match the real Device guard: every generated spawn retains the agent's
        # current-frame evidence. Previously the stub plan hid this live failure.
        for step in steps:
            checkpoint = step["batch"]["checkpoint"]
            self.assertEqual(checkpoint["frameId"], "boundary-frame")
            self.assertEqual(checkpoint["size"], [1280, 960])
            for action in step["batch"]["actions"]:
                if action["kind"] == "spawn":
                    self.assertTrue(any(s["point"] == action["point"] and s["evidence"]
                                        for s in checkpoint["legalSpawns"]))

    def test_refuses_missing_or_incomplete_spawn_evidence(self):
        s = self.session()
        for checkpoint in [None, {}, {"frameId": "f", "size": [1280, 960], "legalSpawns": []}]:
            with self.assertRaises(GuardError):
                s.command(self.request(checkpoint=checkpoint))
        self.assertEqual(s.plans, [])
        self.assertEqual(s.device.inputs, [])

    def test_refuses_hud_points_bunched_or_stale_anchors(self):
        s = self.session()
        bad = [self.request(anchors=self.RING[:5]),                          # too few
               self.request(anchors=self.RING[:7] + [[100, 660]]),           # End Battle button
               self.request(anchors=self.RING[:7] + [[600, 800]]),           # troop bar
               self.request(anchors=self.RING[:7] + [[332, 252]]),           # duplicate
               self.request(boundaryCapturedAtMs=self.now - 120000),        # old frame
               self.request(valkyries=0)]
        for req in bad:
            with self.assertRaises(GuardError):
                s.command(req)
        s.camera_moved_ms = self.now + 1                                     # pinch after the read
        with self.assertRaises(GuardError):
            s.command(self.request())
        self.assertEqual(s.plans, [])
        self.assertEqual(s.device.inputs, [])


class FullDestructionTests(unittest.TestCase):
    setup_session = CutoffTests.setup_session

    def test_full_destruction_is_default(self):
        with tempfile.TemporaryDirectory() as directory:
            s = CutoffSession(FakeDevice(), directory)
            self.assertEqual(s.state()["targetPercent"], 100)

    def test_50_99_and_100_never_surrender(self):
        with tempfile.TemporaryDirectory() as directory:
            s, dev, obs = self.setup_session(directory)
            s.target_percent = 100
            for damage in (49, 50, 99, 100):
                s.hud = lambda _, d=damage: {"battle": True, "damage": d, "endPoint": [100, 670]}
                s.check(obs)
                self.assertTrue(s.armed)
                self.assertIsNone(s.cutoff)
                self.assertEqual(dev.inputs, [])
            with self.assertRaises(GuardError):
                s.finish(obs, {"damage": 100})

    def test_natural_results_cancel_queued_deployment_without_surrender(self):
        for percent in (76, 100):
            with self.subTest(percent=percent), tempfile.TemporaryDirectory() as directory:
                s, dev, obs = self.setup_session(directory)
                s.target_percent, s.latest = 100, obs
                s.hud = lambda _: {"battle": False, "damage": None, "endPoint": None}
                values = [(f"{percent}%", 640, 158), ("1", 595, 445), ("2", 595, 505),
                          ("3", 595, 570), ("+4", 1055, 488), ("+5", 1055, 535), ("+6", 1055, 585)]
                result_lines = RESULT + [line(t, x/1280-.025, y/960-.015, .05) for t, x, y in values]
                s.read_ocr = lambda paths: {p: result_lines for p in paths}
                s.observe = lambda label="watch": obs
                r = s.command({"command": "batch", "batch": {"id": "late-spawn",
                    "actions": [{"kind": "spawn", "point": [300, 400]}]}})
                self.assertEqual(r["cancelled"], "cutoff_or_unexpected_screen")
                self.assertFalse(s.armed)
                self.assertEqual(s.cutoff["completionReason"], "natural_result")
                self.assertEqual(s.cutoff["damage"], percent)
                self.assertNotIn("end", s.cutoff)
                self.assertEqual(dev.inputs, [])

    def test_natural_result_uses_auto_return_and_never_returns_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            s, dev, obs = self.setup_session(directory)
            s.target_percent, s.auto_return_home = 100, True
            s.hud = lambda _: {"battle": False, "damage": None, "endPoint": None}
            s.read_ocr = lambda paths: {p: RESULT for p in paths}
            returned = []
            def return_home():
                returned.append(1)
                s.cutoff["status"] = "returned_home"
            s.return_home_after_result = return_home
            s.check(obs)
            s.check(obs)
            self.assertEqual(returned, [1])
            with self.assertRaises(GuardError):
                s.command({"command": "return_home_after_result"})
            self.assertEqual(dev.inputs, [])

    def test_blocked_or_unknown_frame_cannot_become_natural_result(self):
        for lines, blocked in ((RESULT, True), ([], False),
                               (RESULT + [line("Connection lost", .3, .4)], False)):
            with tempfile.TemporaryDirectory() as directory:
                s, dev, obs = self.setup_session(directory)
                s.target_percent = 100
                s.hud = lambda _: {"battle": False, "damage": None, "endPoint": None, "blocked": blocked}
                s.read_ocr = lambda paths: {p: lines for p in paths}
                s.check(obs)
                self.assertTrue(s.halted)
                self.assertIsNone(s.cutoff)
                self.assertEqual(dev.inputs, [])

    def test_stable_natural_result_is_saved_before_one_return_home(self):
        with tempfile.TemporaryDirectory() as directory:
            s, dev, obs = self.setup_session(directory)
            s.target_percent, s.auto_return_home = 100, True
            values = [("100%", 640, 158), ("1", 595, 445), ("2", 595, 505),
                      ("3", 595, 570), ("+4", 1055, 488), ("+5", 1055, 535), ("+6", 1055, 585)]
            result = RESULT + [line(t, x/1280-.025, y/960-.015, .05) for t, x, y in values]
            result.append(line("Return Home", .44, .82, .12))
            home = {**obs, "frameId": "home", "path": str(Path(directory) / "home.png")}
            Image.new("RGB", (1280, 960)).save(home["path"])
            s.hud = lambda _: {"battle": False, "damage": None, "endPoint": None}
            s.read_ocr = lambda paths: {p: ([line("Shop", .9, .5)] if p == home["path"] else result) for p in paths}
            frames = iter([obs, obs, home])
            s.observe = lambda label="watch": next(frames)
            def tap(x, y):
                saved = json.loads((Path(directory) / "cutoff-latest.json").read_text())
                self.assertIn("settledResult", saved)
                self.assertEqual(saved["status"], "return_home_input_issued")
                dev.inputs.append([x, y])
            dev.tap = tap
            with patch("farming_cutoff.time.sleep"):
                s.check(obs)
            self.assertEqual(s.cutoff["status"], "returned_home")
            self.assertEqual(s.cutoff["damage"], 100)
            self.assertEqual(len(dev.inputs), 1)
            self.assertEqual(s.cutoff["homeObservation"]["frameId"], "home")


class SpamAttackTests(unittest.TestCase):
    RING = RingDeployTests.RING
    SLOTS = {"valkyries": [150, 780], "siege": [250, 780], "king": [345, 780],
             "queen": [345, 900], "warden": [430, 780], "duke": [430, 900],
             "earthquakes": [530, 780]}

    def session(self, counts_after=None, damage=None):
        import time
        s = CutoffSession(FakeDevice(), tempfile.mkdtemp(), read_ocr=lambda paths: {})
        s.observe = lambda label="watch": {"frameId": label, "size": [1280, 960], "path": "x"}
        seen = []
        def badges(obs):
            seen.append(obs)
            return ({"valkyries": 44, "earthquakes": 11} if len(seen) == 1
                    else counts_after or {"valkyries": 0, "earthquakes": 0})
        s.inventory_badges = badges
        s.batches = []
        def check(obs=None):
            s.batches.append(len(s.device.inputs))
            if damage is not None and len(s.batches) >= 2:
                s.armed, s.halted = False, True
                s.cutoff = {"status": "result"}
            return {"battle": True, "damage": 10, "endPoint": [100, 660], "blocked": False}
        s.check = check
        self.now = int(time.time() * 1000)
        return s

    def request(self, **over):
        req = {"command": "spam_attack", "id": "r9-spam", "anchors": self.RING,
               "boundaryCapturedAtMs": self.now, "slots": self.SLOTS,
               "checkpoint": {"frameId": "boundary-frame", "size": [1280, 960],
                              "legalSpawns": [{"point": p, "evidence": "Outside red boundary by 40px"}
                                              for p in self.RING]},
               "valkyries": 44, "earthquakes": 11, "quakeTargets": [[550, 285], [845, 400], [650, 615]],
               "deadline": {"seconds": 178, "capturedAtMs": self.now, "rate": 1}}
        req.update(over)
        return req

    def test_whole_army_in_back_to_back_bounded_batches(self):
        s = self.session()
        r = s.command(self.request())
        self.assertEqual(r["stopped"], "all_deployed_agent_verification_required")
        acts = s.device.inputs
        kinds = [a["kind"] for a in acts]
        self.assertEqual(kinds.count("spawn"), 5 + 44)            # siege + 4 heroes + 44 Valkyries
        self.assertEqual(kinds.count("spell"), 11)
        self.assertEqual(kinds.count("ability"), 4)
        self.assertTrue(all(b["inputs"] <= 20 for b in r["batches"]))
        # heroes and siege go out before any Valkyrie, on spread legal anchors
        first_valk = next(i for i, a in enumerate(acts) if a["label"].startswith("Spam Valkyrie "))
        unit_points = [a["point"] for a in acts[:first_valk] if a["kind"] == "spawn"]
        self.assertEqual(len(unit_points), 5)
        self.assertEqual(len({tuple(p) for p in unit_points}), 5)
        self.assertTrue(all(a["point"] in self.RING for a in acts if a["kind"] == "spawn"))
        self.assertTrue(s.armed)
        self.assertEqual(len(s.batches), len(r["batches"]) * 2 - 1)  # fresh check around every batch

    def test_cutoff_cancels_remaining_batches(self):
        s = self.session(damage=50)
        r = s.command(self.request())
        # 50% seen in the fresh check before batch 2: it is cancelled, nothing more issued
        self.assertEqual(r["stopped"], "cutoff_or_unexpected_screen")
        self.assertEqual([b["cancelled"] for b in r["batches"]], [None, "cutoff_or_unexpected_screen"])
        self.assertEqual(len(s.device.inputs), 20)

    def test_rejected_deployment_stops_spam_but_keeps_cutoff_armed(self):
        s = self.session()
        check = s.check
        def rejecting_check(obs=None):
            return {**check(obs), "deploymentRejected": len(s.device.inputs) >= 20}
        s.check = rejecting_check
        r = s.command(self.request())
        self.assertEqual(r["stopped"], "deployment_rejected_agent_inspection_required")
        self.assertEqual(len(s.device.inputs), 20)
        self.assertEqual(len(r["batches"]), 1)
        self.assertTrue(s.armed)
        self.assertFalse(s.halted)
        # A queued deployment also stops while the fresh warning remains visible.
        batch = {"id": "queued", "actions": [{"kind": "spawn", "point": self.RING[0]}]}
        retry = s.command({"command": "batch", "batch": batch})
        self.assertEqual(retry["cancelled"], "deployment_rejected_agent_inspection_required")
        self.assertEqual(len(s.device.inputs), 20)
        self.assertTrue(s.armed)

    def test_unreadable_start_and_late_earthquake_badge_are_reread(self):
        # r2083: EQ badge unreadable on the first scout frame; r2076-r2093:
        # the final frame showed 7 EQ that settled to 0 a few seconds later.
        s = self.session()
        reads = [{"valkyries": 44, "earthquakes": None}, {"valkyries": 44, "earthquakes": 11},
                 {"valkyries": 0, "earthquakes": 7}, {"valkyries": 0, "earthquakes": 1},
                 {"valkyries": 0, "earthquakes": 0}]
        s.inventory_badges = lambda obs: reads.pop(0)
        r = s.command(self.request())
        self.assertEqual(r["stopped"], "all_deployed_agent_verification_required")
        self.assertEqual((r["startReads"], r["finalReads"]), (2, 3))
        self.assertEqual([a["kind"] for a in s.device.inputs].count("spell"), 11)  # never replayed

    def test_wrong_start_counts_issue_no_input(self):
        s = self.session()
        r = s.command(self.request(valkyries=40))
        self.assertEqual(r["stopped"], "initial_inventory_mismatch_or_unreadable")
        self.assertEqual(s.device.inputs, [])

    def test_final_mismatch_is_reported_not_replayed(self):
        s = self.session(counts_after={"valkyries": 3, "earthquakes": 0})
        r = s.command(self.request())
        self.assertEqual(r["stopped"], "final_inventory_mismatch_or_unreadable")
        self.assertEqual([a["kind"] for a in s.device.inputs].count("spawn"), 49)

    def test_refusals(self):
        s = self.session()
        bad = [self.request(anchors=self.RING[:5]),
               self.request(slots={"king": [345, 780]}),                    # no Valkyrie slot
               self.request(quakeTargets=[]),
               self.request(quakeTargets=[[100, 660]]),                     # End Battle button
               self.request(deadline=None),
               self.request(boundaryCapturedAtMs=self.now - 120000)]
        for req in bad:
            with self.assertRaises(GuardError):
                s.command(req)
        s.armed = True
        with self.assertRaises(GuardError):
            s.command(self.request())
        self.assertEqual(s.device.inputs, [])


if __name__ == "__main__":
    unittest.main()
