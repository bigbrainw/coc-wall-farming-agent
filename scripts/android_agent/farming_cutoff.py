#!/usr/bin/env python3
"""Single-owner ADB session targeting full destruction by default.

Commands arrive as JSON lines on stdin. Only the main thread owns Device or
sends game input; the reader thread only queues commands. Deployment remains
in the existing guarded <=20-input batches. While armed, the same controller
checks the live HUD between batches and while waiting for the next command.
Full-destruction mode never surrenders at a damage threshold. It watches for
natural results and optionally returns home. Historical 50% mode is explicit.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import re
import shutil
import sys
import threading
import time
import unicodedata

from PIL import Image, ImageChops

from coc_android import Device, GuardError
from screen_reader import _norm, classify_screen, ocr

DEFAULT_RECORD_ROOT = Path.home() / "coc-footage-outbox"  # shipped to the mini's T7

BLOCKING_OVERLAY_TERMS = ("connection lost", "lost connection", "confirm exit",
                          "maintenance", "anyone there", "disconnected due to inactivity",
                          "isnt responding", "is not responding")


def blocking_overlay(lines):
    return any(term in norm(line["text"]) for line in lines for term in BLOCKING_OVERLAY_TERMS)


def deployment_rejected(lines):
    return any(line.get("conf", 0) >= .7 and any(
        term in norm(unicodedata.normalize("NFKD", line["text"]).encode("ascii", "ignore").decode())
        for term in ("cannot deploy", "cant deploy", "red area"))
        for line in lines)


def norm(text):
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def text_center(line, width=1280, height=960):
    x, y, w, h = line["box"]
    return [round((x + w / 2) * width), round((y + h / 2) * height)]


def return_home_point(lines):
    """Centre of the results-screen Return Home button (OCR may split the words)."""
    sure = [l for l in lines if l.get("conf", 0) >= .9]
    for l in sure:
        if _norm(l["text"]) == "return home":
            return text_center(l)
    for r in sure:
        if _norm(r["text"]) != "return":
            continue
        rx, ry = text_center(r)
        for h in sure:
            hx, hy = text_center(h)
            beside = abs(hy - ry) < 25 and 0 < hx - rx < 220
            below = abs(hx - rx) < 40 and 8 < hy - ry < 50  # two-line button label
            if _norm(h["text"]) == "home" and (beside or below):
                return [round((rx + hx) / 2), round((ry + hy) / 2)]
    return None


def settled_result_numbers(lines):
    """Read result values only; background levels and troop badges can flicker."""
    regions = [(550, 120, 730, 195),
               (500, 420, 690, 470), (500, 480, 690, 530), (500, 540, 690, 600),
               (980, 465, 1130, 510), (980, 515, 1130, 555), (980, 560, 1130, 610)]
    values = []
    for left, top, right, bottom in regions:
        matches = []
        for line in lines:
            x, y = text_center(line)
            value = re.sub(r"\s", "", line["text"])
            if (line.get("conf", 0) >= .9 and left <= x <= right and top <= y <= bottom
                    and re.fullmatch(r"\+?\d+%?", value)):
                matches.append(value)
        if len(matches) != 1:
            return None
        values.append(matches[0])
    return tuple(values)


def parse_hud(lines):
    """Read only the three known panels of the compact 800x110 HUD image."""
    battle = False
    button = None
    damage = None
    for line in lines:
        if line.get("conf", 0) < .9:
            continue
        x, y = text_center(line, 800, 110)
        text = norm(line["text"])
        if x < 320 and y < 45 and text == "battle ends in":
            battle = True
        if 330 < x < 545 and text in {"end battle", "surrender"}:
            button = [x - 330, y + 620]
        if x >= 550:
            match = re.fullmatch(r"\s*(\d{1,3})\s*%\s*", line["text"])
            if match and 0 <= int(match[1]) <= 100:
                damage = int(match[1])
    return {"battle": battle, "damage": damage, "endPoint": button}


def recover_damage_percentage(readings):
    """Require two agreeing strict readings of the fixed damage-number crop."""
    values = []
    for lines in readings:
        matches = []
        for line in lines:
            match = re.fullmatch(r"\s*(\d{1,3})\s*%\s*", line["text"])
            if match and line.get("conf", 0) >= .95 and 0 <= int(match[1]) <= 100:
                matches.append(int(match[1]))
        if len(matches) != 1:
            return None
        values.append(matches[0])
    return values[0] if len(values) >= 2 and len(set(values)) == 1 else None


def battle_end_point(lines):
    """Recover an exact End/Surrender label only in the live button panel."""
    matches = []
    for line in lines:
        x, y = text_center(line)
        if (line.get("conf", 0) >= .95 and 0 < x < 215 and 620 < y < 714
                and " ".join(line["text"].casefold().split()) in {"end battle", "surrender"}):
            matches.append([x, y])
    return matches[0] if len(matches) == 1 else None


def confirm_end_point(lines):
    # Vision reads the question mark as 'z' on raid579's real End dialog.
    # Keep the title position, full question and both buttons mandatory.
    title = any(norm(l["text"]) in {"end battle", "end battlez", "surrender"}
                and .25 < l["box"][0] < .65 and .2 < l["box"][1] < .42
                for l in lines)
    question = any("are you sure" in norm(l["text"]) for l in lines)
    cancel = any(norm(l["text"]) == "cancel" for l in lines)
    okay = [l for l in lines if norm(l["text"]) == "okay"
            and l.get("conf", 0) >= .9 and .5 < l["box"][0] < .75
            and .5 < l["box"][1] < .72]
    return text_center(okay[0]) if title and question and cancel and len(okay) == 1 else None


def parse_inventory_badges(lines):
    """Two fixed, enlarged badge crops; missing/ambiguous readings stay unknown."""
    found = {"valkyries": [], "earthquakes": []}
    for line in lines:
        if line.get("conf", 0) < .95:
            continue
        # Cyrillic х is a lookalike of the quantity prefix only. Ambiguous
        # Cyrillic digits (e.g. ЗБ) remain unreadable and need pixel re-reads.
        match = re.fullmatch(r"[x×х]([0-9oi]{1,2})[)\]]?", line["text"].lower().replace(" ", ""))
        if not match:
            continue
        value = int(match[1].translate(str.maketrans("oi", "01")))
        _, y = text_center(line, 400, 320)
        key = "valkyries" if y < 160 else "earthquakes"
        if value <= (44 if key == "valkyries" else 11):
            found[key].append(value)
    return {key: values[0] if len(values) == 1 else None for key, values in found.items()}


def recover_earthquake_zero(counts, variants):
    """Recover only a missing disabled EQ badge with two agreeing OCR views."""
    result = dict(counts)
    values = [v.get("earthquakes") for v in variants
              if v.get("earthquakes") is not None]
    if result.get("earthquakes") is None and values.count(0) >= 2 and set(values) == {0}:
        result["earthquakes"] = 0
    return result


def recover_valkyrie_count(counts, variants):
    """Recover a missing count only from two agreeing, unconflicted OCR views."""
    result = dict(counts)
    values = [v.get("valkyries") for v in variants
              if v.get("valkyries") is not None]
    if result.get("valkyries") is None and len(values) >= 2 and len(set(values)) == 1:
        result["valkyries"] = values[0]
    return result


def configure_command_terminal(stream):
    """Accept complete JSON lines beyond the terminal's canonical line limit."""
    if not stream.isatty():
        return None
    import termios
    original = termios.tcgetattr(stream)
    updated = termios.tcgetattr(stream)
    updated[3] &= ~(termios.ECHO | termios.ICANON)
    updated[6][termios.VMIN] = 1
    updated[6][termios.VTIME] = 0
    termios.tcsetattr(stream, termios.TCSANOW, updated)
    return original


def read_commands(stream, requests):
    """Transport only: this reader never observes or operates the device."""
    for line in stream:
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("Command must be a JSON object")
            requests.put(request)
            if request.get("command") == "close":
                return
        except ValueError as error:
            requests.put({"command": "invalid", "error": str(error)})
    requests.put({"command": "close"})


class CutoffSession:
    def __init__(self, device, out_dir, poll_seconds=.15, read_ocr=ocr, target_percent=100):
        if target_percent not in (50, 100):
            raise ValueError("Supported destruction targets: 50 or 100")
        self.target_percent = target_percent
        self.device = device
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.poll_seconds = poll_seconds
        self.read_ocr = read_ocr
        self.armed = False
        self.halted = False
        self.sequence = 0
        self.latest = None
        self.last_below = None
        self.cutoff = None
        self.last_check = 0
        self.recording = None  # {"id", "dir", "events", "startedAtMs", "raid"}
        self.record_root = None
        self.shipper = None  # footage_shipper.Shipper: moves finished recordings to the mini
        self.camera_moved_ms = 0
        self.auto_return_home = False

    # -- attack footage (training data) ------------------------------------
    def rec_event(self, kind, **fields):
        if not self.recording:
            return
        row = {"t": int(time.time() * 1000), "type": kind, **fields}
        with open(self.recording["events"], "a") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    def record_start(self, request):
        stream = getattr(self.device, "stream", None)
        if stream is None:
            raise GuardError("Recording needs the --stream video source")
        if self.recording:
            raise GuardError("Already recording " + self.recording["id"])
        root = Path(request.get("root") or self.record_root or DEFAULT_RECORD_ROOT).expanduser()
        if self.shipper is not None:
            root.mkdir(parents=True, exist_ok=True)  # laptop outbox; the shipper moves it on
            if shutil.disk_usage(root).free < 3 * 1024 ** 3:
                raise GuardError(f"Less than 3 GB free for the footage outbox: {root}")
        if not root.parent.exists():
            raise GuardError(f"Footage root parent missing (drive not mounted?): {root.parent}")
        raid = re.sub(r"[^A-Za-z0-9_-]", "", str(request.get("raid", "raid")))[:40] or "raid"
        rec_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + raid
        folder = root / "incoming" / rec_id
        folder.mkdir(parents=True, exist_ok=False)
        info = stream.start_recording(str(folder / "video.mkv"))
        self.recording = {"id": rec_id, "dir": str(folder), "events": str(folder / "events.jsonl"),
                          "startedAtMs": int(time.time() * 1000), "raid": raid}
        self.rec_event("note", text="recording started", leadInPackets=info["leadInPackets"])
        return {"recording": self.recording}

    def record_stop(self, request=None, reason="record_stop"):
        if not self.recording:
            return {"recording": None}
        rec = self.recording
        self.rec_event("note", text="recording stopped", reason=reason)
        self.recording = None
        info = self.device.stream.stop_recording() if getattr(self.device, "stream", None) else None
        meta = {"recordingId": rec["id"], "raid": rec["raid"], "startedAtMs": rec["startedAtMs"],
                "endedAtMs": int(time.time() * 1000), "size": [1280, 960],
                "controller": "farming_cutoff.py --stream", "stopReason": reason,
                "targetPercent": self.target_percent,
                "videoStartPtsUs": (info or {}).get("videoStartPtsUs"),
                "videoStartHostMs": (info or {}).get("videoStartHostMs"),
                "frames": (info or {}).get("frames"), "bytes": (info or {}).get("bytes"),
                "durationMs": (info or {}).get("durationMs"), "recordError": (info or {}).get("error"),
                "cutoff": {k: (self.cutoff or {}).get(k) for k in ("status", "damage", "detectionToEndMs")}}
        meta.update((request or {}).get("meta") or {})  # agent-supplied: opponent, loot, percent, stars
        path = Path(rec["dir"]) / "meta.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        os.replace(temp, path)  # written last: marks the recording complete for the uploader
        if self.shipper is not None:
            self.shipper.kick()  # background copy to the mini; never blocks play
        return {"recording": None, "meta": meta}

    def save(self, name, value):
        if name == "cutoff-latest" and isinstance(value, dict):
            self.rec_event("cutoff", status=value.get("status"), damage=value.get("damage"))
        path = self.out / (name + ".json")
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
        os.replace(temp, path)

    def state(self):
        value = {"armed": self.armed, "halted": self.halted,
                 "latest": self.latest, "cutoff": self.cutoff,
                 "targetPercent": self.target_percent}
        self.save("controller-state", value)
        return value

    def observe(self, label="watch"):
        self.sequence += 1
        # Ordinary below-threshold polls reuse one file; retain every HUD/time
        # in JSONL and copy the triggering frame before any End input.
        name = "watch-live" if label == "watch" else f"{self.sequence:05d}-{label}"
        obs = self.device.observe(str(self.out / (name + ".png")))
        if obs["size"] != [1280, 960]:
            raise GuardError("Battle HUD requires the verified 1280x960 layout")
        self.latest = obs
        return obs

    def hud(self, obs):
        path = self.out / "hud-live.png"
        overlay_path = self.out / "overlay-live.png"
        warning_path = self.out / "deployment-warning-live.png"
        with Image.open(obs["path"]) as frame:
            hud = Image.new("RGB", (800, 110), "black")
            hud.paste(frame.crop((480, 0, 800, 105)), (0, 0))
            hud.paste(frame.crop((0, 620, 215, 714)), (330, 0))
            hud.paste(frame.crop((1030, 620, 1280, 714)), (550, 0))
            hud.save(path)
            # A disconnect leaves the battle header/button/damage visible
            # underneath it. Check the dialog area on every poll, including
            # when the compact battle header is perfectly readable.
            frame.crop((320, 300, 960, 615)).save(overlay_path)
            # Red text at y~270 is hard to read over the village. Isolate its
            # colour and scale it in this same OCR pass, without inventory OCR.
            red, green, _ = frame.convert("RGB").crop((250, 210, 1040, 300)).split()
            warning = ImageChops.logical_and(
                red.point(lambda v: 255 if v > 140 else 0, "1"),
                ImageChops.subtract(red, green).point(lambda v: 255 if v > 65 else 0, "1"))
            warning.convert("L").resize((1580, 180)).save(warning_path)
        readings = self.read_ocr([str(path), str(overlay_path), str(warning_path)])
        value = parse_hud(readings.get(str(path), []))
        value["blocked"] = blocking_overlay(readings.get(str(overlay_path), []))
        value["deploymentRejected"] = deployment_rejected(readings.get(str(warning_path), []))
        if value["damage"] is None and value["endPoint"] and not value["blocked"]:
            # Scenery lettering behind the HUD can merge with the percentage
            # in the compact composite. Re-read only its fixed number region;
            # both differently cropped views of this same frame must agree.
            damage_paths = [self.out / "damage-number-wide.png",
                            self.out / "damage-number-tight.png"]
            with Image.open(obs["path"]) as frame:
                for target, box in zip(damage_paths, [(1160, 650, 1270, 695),
                                                      (1180, 650, 1270, 695)]):
                    frame.crop(box).resize((500, 200)).save(target)
            damage_readings = self.read_ocr([str(p) for p in damage_paths])
            value["damage"] = recover_damage_percentage(
                [damage_readings.get(str(p), []) for p in damage_paths])
            value["damageCropRecovery"] = value["damage"] is not None
        with (self.out / "damage-polls.jsonl").open("a") as stream:
            stream.write(json.dumps({**obs, **value, "readAtMs": int(time.time()*1000)}) + "\n")
        self.rec_event("damage", damage=value["damage"], battle=value["battle"],
                       frameId=obs["frameId"], capturedAtMs=obs.get("capturedAtMs"))
        return value

    def check(self, obs=None):
        if not self.armed:
            if self.confirmation_pending():
                self.check_cutoff_confirmation(obs or self.observe("cutoff-wait"))
                self.last_check = time.monotonic()
            return None
        obs = obs or self.observe()
        self.last_check = time.monotonic()
        hud = self.hud(obs)
        if hud.get("blocked"):
            self.armed = False
            self.halted = True
            self.save("watch-stopped", {"reason": "blocking_overlay", "observation": obs})
            return hud
        recover_header = not hud["battle"] and hud["endPoint"] and hud["damage"] is not None
        recover_button = (self.target_percent == 50 and hud["battle"]
                          and hud["damage"] is not None and hud["damage"] >= 50
                          and not hud["endPoint"])
        if recover_header or recover_button:
            # The compact OCR can miss the header or End label on an animated
            # frame. Re-read that same full frame before delaying the cutoff.
            lines = self.read_ocr([obs["path"]]).get(obs["path"], [])
            if classify_screen(lines)["screen"] == "battle" and not blocking_overlay(lines):
                hud["battle"] = True
                if recover_button:
                    hud["endPoint"] = battle_end_point(lines)
                self.save("header-fallback", {"observation": obs, "hud": hud})
        if not hud["battle"]:
            lines = self.read_ocr([obs["path"]]).get(obs["path"], [])
            if classify_screen(lines)["screen"] == "results" and not blocking_overlay(lines):
                self.complete_natural_result(obs, lines)
                return hud
            # A normal result, disconnect or unknown screen must not receive
            # blind deployment or a confirmation click.
            self.armed = False
            self.halted = True
            self.save("watch-stopped", {"reason": "battle_HUD_missing", "observation": obs})
        elif hud["damage"] is not None and hud["damage"] < self.target_percent:
            below = self.out / f"last-below{self.target_percent}.png"
            below.write_bytes(Path(obs["path"]).read_bytes())
            self.last_below = {**obs, "path": str(below), "damage": hud["damage"]}
        elif (self.target_percent == 50 and hud["damage"] is not None
              and hud["damage"] >= 50 and hud["endPoint"]):
            self.finish(obs, hud)
        return hud

    def complete_natural_result(self, obs, lines):
        """Cancel queued combat on a verified result, without End/Okay inputs."""
        self.armed, self.halted = False, True
        keep = self.out / f"natural-result-{obs['frameId']}.png"
        keep.write_bytes(Path(obs["path"]).read_bytes())
        numbers = settled_result_numbers(lines)
        self.cutoff = {"trigger": {**obs, "path": str(keep)},
                       "completionReason": "natural_result", "targetPercent": self.target_percent,
                       "damage": int(numbers[0].rstrip("%")) if numbers else None,
                       "remainingDeploymentCancelled": True, "status": "natural_result"}
        self.save("cutoff-latest", self.cutoff)
        if self.auto_return_home:
            self.return_home_after_result()

    def finish(self, obs, hud):
        if self.target_percent != 50:
            raise GuardError("Full-destruction mode must wait for the natural result")
        # Consume the trigger once, even if the following input is ineffective.
        self.armed = False
        self.halted = True
        trigger = self.out / f"cutoff-{obs['frameId']}.png"
        trigger.write_bytes(Path(obs["path"]).read_bytes())
        if self.last_below:
            below = self.out / f"cutoff-{obs['frameId']}-below.png"
            below.write_bytes(Path(self.last_below["path"]).read_bytes())
            self.last_below = {**self.last_below, "path": str(below)}
        self.cutoff = {"trigger": {**obs, "path": str(trigger)},
                       "targetPercent": self.target_percent,
                       "damage": hud["damage"], "lastBelow": self.last_below,
                       "remainingDeploymentCancelled": True, "status": "checking_trigger"}
        self.save("cutoff-latest", self.cutoff)
        lines = self.read_ocr([str(trigger)]).get(str(trigger), [])
        if classify_screen(lines)["screen"] != "battle" or blocking_overlay(lines):
            self.cutoff["status"] = "unexpected_trigger_screen"
            self.save("cutoff-latest", self.cutoff)
            return
        end = self.device.run_batch({"id": "cutoff-end-" + obs["frameId"],
            "checkpoint": obs, "settleSeconds": .55,
            "actions": [{"kind": "tap", "label": "50% cutoff End Battle", "point": hud["endPoint"]}]},
            str(self.out / "cutoff-dialog.png"))
        self.cutoff["end"] = end
        self.cutoff["detectionToEndMs"] = end["issued"][0]["issuedAtMs"] - obs["capturedAtMs"]
        self.latest = end["observation"]
        self.check_cutoff_confirmation(self.latest)

    def confirmation_pending(self):
        return bool(self.cutoff and self.cutoff.get("status") == "awaiting_confirmation"
                    and self.cutoff.get("end") and not self.cutoff.get("confirm"))

    def check_cutoff_confirmation(self, obs):
        """Observe a delayed End response; never repeat End or an uncertain Okay."""
        self.latest = obs
        path = obs["path"]
        lines = self.read_ocr([path]).get(path, [])
        blocked = blocking_overlay(lines)
        point = None if blocked else confirm_end_point(lines)
        if point is None:
            screen = classify_screen(lines)["screen"]
            self.cutoff["status"] = ("confirmation_not_verified" if blocked else
                                     "natural_result" if screen == "results" else
                                     "awaiting_confirmation")
            self.cutoff.setdefault("confirmationObservations", []).append(
                {"observation": obs, "screen": screen, "blocked": blocked})
            self.save("cutoff-latest", self.cutoff)
            return
        # Persist intent before issuing Okay. If transport fails after input,
        # this phase cannot be polled into another confirmation click.
        self.cutoff["status"] = "confirmation_input_issued"
        self.cutoff["verifiedConfirmationObservation"] = obs
        self.save("cutoff-latest", self.cutoff)
        trigger_id = self.cutoff["trigger"]["frameId"]
        confirm = self.device.run_batch({"id": "cutoff-confirm-" + trigger_id,
            "checkpoint": self.latest, "settleSeconds": 1.4,
            "actions": [{"kind": "tap", "label": "50% cutoff verified Okay", "point": point}]},
            str(self.out / "cutoff-result.png"))
        self.cutoff["confirm"] = confirm
        self.latest = confirm["observation"]
        path = self.latest["path"]
        result_lines = self.read_ocr([path]).get(path, [])
        self.cutoff["status"] = ("result" if classify_screen(result_lines)["screen"] == "results"
                                 else "result_observation_required")
        self.save("cutoff-latest", self.cutoff)
        self.save("cutoff-" + trigger_id, self.cutoff)
        if self.auto_return_home:
            self.return_home_after_result()

    def return_home_after_result(self, settle_timeout=15, home_timeout=15):
        """Save the settled result frame, then tap its verified Return Home once.

        Settled = two consecutive results frames with identical damage and loot.
        Return Home is tapped only on such a frame (no blocking overlay); the
        agent reads loot from cutoff.settledResult and must not tap it again.
        """
        trigger_id = self.cutoff["trigger"]["frameId"]
        previous, settled = None, None
        end = time.time() + settle_timeout
        while time.time() < end:
            obs = self.observe("result-poll")
            lines = self.read_ocr([obs["path"]]).get(obs["path"], [])
            if blocking_overlay(lines):
                self.cutoff["status"] = "return_home_blocked_overlay"
                break
            if classify_screen(lines)["screen"] != "results":
                previous = None
                time.sleep(.5)
                continue
            numbers = settled_result_numbers(lines)
            button = return_home_point(lines)
            if numbers is not None and previous is not None and numbers == previous and button:
                settled = (obs, lines, button)
                break
            previous = numbers
            time.sleep(.7)
        if settled is None:
            if not self.cutoff["status"].startswith("return_home"):
                self.cutoff["status"] = "result_not_settled_agent_return_required"
            self.save("cutoff-latest", self.cutoff)
            return
        obs, lines, button = settled
        keep = self.out / f"result-settled-{trigger_id}.png"
        keep.write_bytes(Path(obs["path"]).read_bytes())
        result = {**obs, "path": str(keep), "text": [l["text"] for l in lines]}
        if obs.get("viewPath"):
            view = self.out / f"result-settled-{trigger_id}.view.jpg"
            view.write_bytes(Path(obs["viewPath"]).read_bytes())
            result["viewPath"] = str(view)
        self.cutoff["settledResult"] = result
        self.cutoff["damage"] = int(settled_result_numbers(lines)[0].rstrip("%"))
        self.cutoff["status"] = "return_home_input_issued"  # persisted before the tap
        self.save("cutoff-latest", self.cutoff)
        issued = round(time.time() * 1000)
        self.device.tap(*button)
        self.cutoff["returnHome"] = {"point": button, "issuedAtMs": issued,
                                     "groundedFrameId": obs["frameId"]}
        self.rec_event("batch", id="auto-return-home", actions=[
            {"kind": "ui", "label": "Return Home", "point": button, "issuedAtMs": issued}])
        end = time.time() + home_timeout
        status = "return_home_unverified"
        while time.time() < end:
            time.sleep(.8)
            home = self.observe("after-return-home")
            home_lines = self.read_ocr([home["path"]]).get(home["path"], [])
            if classify_screen(home_lines)["screen"] == "home" and not blocking_overlay(home_lines):
                self.cutoff["homeObservation"] = home
                status = "returned_home"
                break
        self.cutoff["status"] = status
        self.save("cutoff-latest", self.cutoff)
        self.save("cutoff-" + trigger_id, self.cutoff)

    def command(self, request):
        cmd = request.get("command")
        if cmd == "status":
            return self.state()
        if cmd == "observe":
            obs = self.observe("requested")
            self.check(obs)
            return {"observation": self.latest, "state": self.state()}
        if cmd == "disarm":
            self.armed = False
            return self.state()
        if cmd == "return_home_after_result":
            if (self.armed or not self.cutoff or self.cutoff.get("status") not in
                    {"natural_result", "result", "result_not_settled_agent_return_required"}):
                raise GuardError("Return retry needs a result with no previous Return input")
            self.return_home_after_result()
            return self.state()
        if cmd == "resume":
            if self.cutoff is not None or self.armed:
                raise GuardError("Cannot resume after cutoff or while already armed")
            self.armed = True
            self.halted = False
            self.check(self.observe("resume"))
            return self.state()
        if cmd == "home_pinch_out":
            if self.armed:
                raise GuardError("Home gesture refused while watching a battle")
            obs = self.observe("before-home-pinch")
            lines = self.read_ocr([obs["path"]]).get(obs["path"], [])
            if classify_screen(lines)["screen"] != "home" or blocking_overlay(lines):
                raise GuardError("Home gesture needs verified home")
            self.device.pinch("out")
            time.sleep(1)
            obs = self.observe("after-home-pinch")
            return {"observation": obs, "state": self.state()}
        if cmd == "record_start":
            try:
                return self.record_start(request)
            except Exception as error:
                # A missing footage drive must not poison the battle state.
                return {"recording": self.recording, "recordError": str(error)}
        if cmd == "record_stop":
            return self.record_stop(request)
        if cmd == "buildings_list_pan":
            if self.armed or self.cutoff is not None:
                raise GuardError("Building list scroll only between attacks")
            points = [request.get("start"), request.get("end")]
            if any(not isinstance(p, list) or len(p) != 2 or any(
                    not isinstance(v, int) or isinstance(v, bool) for v in p)
                    or not 780 <= p[0] <= 1200 or not 120 <= p[1] <= 800
                    for p in points):
                raise GuardError("Building list scroll needs points inside the right list")
            if abs(points[0][0] - points[1][0]) > 25 or abs(points[0][1] - points[1][1]) < 150:
                raise GuardError("Building list scroll must be vertical and at least150px")
            duration = request.get("durationMs", 700)
            if (not isinstance(duration, int) or isinstance(duration, bool)
                    or not 200 <= duration <= 2000):
                raise GuardError("Building list scroll duration must be200..2000ms")
            obs = self.observe("before-buildings-list-pan")
            lines = self.read_ocr([obs["path"]]).get(obs["path"], [])
            title = any(norm(l["text"]).replace(" ", "") == "buildingsheroes"
                        and l.get("conf", 0) >= .9 and l["box"][0] > .6
                        and l["box"][1] < .08 for l in lines)
            filters = any(norm(l["text"]).replace(" ", "") in {"costmin", "costmax"}
                          for l in lines)
            if obs.get("size") != [1280, 960] or not title or filters or blocking_overlay(lines):
                raise GuardError("Building list scroll needs a verified Buildings & Heroes list")
            issued = round(time.time() * 1000)
            self.device.swipe(*points[0], *points[1], ms=duration)
            input_ms = round(time.time() * 1000) - issued
            time.sleep(.8)
            after = self.observe("after-buildings-list-pan")
            receipt = {"issuedAtMs": issued, "inputMs": input_ms,
                       "before": obs, "observation": after}
            self.save("buildings-list-" + after["frameId"],
                      {"gestureRequest": request, "gestureReceipt": receipt})
            return {"observation": after, "gestureReceipt": receipt, "state": self.state()}
        if cmd == "army_picker_pan":
            # Agent-grounded navigation inside the home army dialog only.
            # Never drag home buildings or allow this during a live battle.
            if self.armed or self.cutoff is not None:
                raise GuardError("Army picker scroll only between attacks")
            points = [request.get("start"), request.get("end")]
            if any(not isinstance(p, list) or len(p) != 2 or any(
                    not isinstance(v, int) or isinstance(v, bool) for v in p)
                    or not 80 <= p[0] <= 1180 or not 700 <= p[1] <= 915
                    for p in points):
                raise GuardError("Army picker scroll needs two points inside the bottom picker")
            if abs(points[0][1] - points[1][1]) > 25 or abs(points[0][0] - points[1][0]) < 150:
                raise GuardError("Army picker scroll must be horizontal and at least150px")
            duration = request.get("durationMs", 500)
            if (not isinstance(duration, int) or isinstance(duration, bool)
                    or not 200 <= duration <= 2000):
                raise GuardError("Army picker scroll duration must be200..2000ms")
            obs = self.observe("before-army-picker-pan")
            lines = self.read_ocr([obs["path"]]).get(obs["path"], [])
            labels = {norm(l["text"]).replace(" ", "") for l in lines if l.get("conf", 0) >= .9}
            if (obs.get("size") != [1280, 960] or blocking_overlay(lines)
                    or not {"myarmy", "savedrecipes", "cookbook"}.issubset(labels)):
                raise GuardError("Army picker scroll needs a verified My Army dialog")
            issued = round(time.time() * 1000)
            self.device.swipe(*points[0], *points[1], ms=duration)
            input_ms = round(time.time() * 1000) - issued
            time.sleep(.8)
            after = self.observe("after-army-picker-pan")
            receipt = {"issuedAtMs": issued, "inputMs": input_ms,
                       "before": obs, "observation": after}
            self.save("army-picker-" + after["frameId"],
                      {"gestureRequest": request, "gestureReceipt": receipt})
            return {"observation": after, "gestureReceipt": receipt, "state": self.state()}
        if cmd in {"scout_pinch_out", "scout_pan"}:
            # Zoom out on the scout view to find legal ground. Battle/scout drags
            # cannot move buildings; refused once a battle is armed or ended.
            if self.armed or self.cutoff is not None:
                raise GuardError("Scout zoom only before deployment")
            obs = self.observe("before-scout-pinch")
            lines = self.read_ocr([obs["path"]]).get(obs["path"], [])
            if classify_screen(lines)["screen"] != "scout" or blocking_overlay(lines):
                raise GuardError("Scout zoom needs a verified scout screen")
            duration = request.get("durationMs", 400)
            if (not isinstance(duration, int) or isinstance(duration, bool)
                    or not 200 <= duration <= 2000):
                raise GuardError("Scout gesture duration must be 200..2000 ms")
            if cmd == "scout_pan":
                points = [request.get("start"), request.get("end")]
                if any(not isinstance(p, list) or len(p) != 2 or any(
                        not isinstance(v, int) or isinstance(v, bool) for v in p)
                        or not 200 <= p[0] <= 1000 or not 220 <= p[1] <= 600
                        for p in points):
                    raise GuardError("Scout pan needs two points within the clear map area")
                self.device.swipe(*points[0], *points[1], ms=duration)
            else:
                self.device.pinch("out", ms=duration)
            time.sleep(.8)
            self.camera_moved_ms = round(time.time() * 1000)  # anchors read before this are stale
            obs = self.observe("after-scout-pinch")
            return {"observation": obs, "state": self.state()}
        if cmd == "search_to_scout":
            return self.search_to_scout(request)
        if cmd == "ring_deploy":
            return self.ring_deploy(request)
        if cmd == "spam_attack":
            return self.spam_attack(request)
        if cmd == "deployment_plan":
            return self.deployment_plan(request)
        if cmd != "batch":
            raise GuardError("Unknown command")
        batch = request["batch"]
        if (self.cutoff and str(self.cutoff.get("status", "")).startswith("return")
                and any("return" in str(a.get("label", "")).lower() for a in batch["actions"])):
            return {"cancelled": "return_home_already_handled_by_watcher", "state": self.state()}
        speed = any(a.get("kind") == "speed" for a in batch["actions"])
        if speed and not self.armed:
            return {"cancelled": "speed_needs_active_battle", "state": self.state()}
        # Speed is a battle-only input too: a queued click must be cancelled if
        # this fresh check ends the battle before the batch is delivered.
        deployment = any(a.get("kind") in {"spawn", "spell", "ability", "speed"}
                         for a in batch["actions"])
        if self.confirmation_pending():
            self.check()
            return {"cancelled": "cutoff_confirmation_pending", "state": self.state()}
        if self.armed:
            hud = self.check()  # cancel stale combat after a result or explicit cutoff
            if deployment and hud and hud.get("deploymentRejected"):
                return {"cancelled": "deployment_rejected_agent_inspection_required",
                        "state": self.state()}
            if deployment and not self.halted and (not hud or hud["damage"] is None):
                return {"cancelled": "damage_observation_required", "state": self.state()}
        if deployment and self.halted:
            return {"cancelled": "cutoff_or_unexpected_screen", "state": self.state()}
        deadline = batch.get("deadline")
        if deadline:
            remaining = deadline["seconds"] - (time.time()*1000-deadline["capturedAtMs"])/1000*deadline.get("rate", 1)
            if remaining < 45:
                # An expired deployment deadline cancels input, not battle
                # monitoring. Raising here makes serve() disarm the cutoff.
                return {"cancelled": "battle_deadline_fresh_observation_required",
                        "state": self.state()}
        result = self.device.run_batch(batch, str(self.out / (batch["id"] + ".png")))
        self.latest = result["observation"]
        self.rec_event("batch", id=batch["id"],
                       # issued[i] belongs to actions[i]; a time-capped batch issues fewer
                       actions=[{**{k: a.get(k) for k in ("kind", "label", "point")},
                                 "issuedAtMs": (result.get("issued") or [])[i]["issuedAtMs"]
                                 if i < len(result.get("issued") or []) else None}
                                for i, a in enumerate(batch["actions"])],
                       issued=result.get("issued"), inputMs=result.get("inputMs"),
                       observationFrameId=result["observation"].get("frameId"))
        self.save(batch["id"], {"request": batch, "receipt": result})
        if request.get("armCutoff"):
            # Explicit new attack only; never silently rearm after a cutoff.
            if self.armed or self.halted:
                raise GuardError("New attack needs reset before arming")
            self.armed = True
        hud = self.check(self.latest)
        return {"receipt": result, "state": self.state(),
                "deploymentRejected": bool(hud and hud.get("deploymentRejected"))}

    def inventory_badges(self, obs):
        path = self.out / ("inventory-" + obs["frameId"] + ".png")
        with Image.open(obs["path"]) as frame:
            if frame.size != (1280, 960):
                raise GuardError("Inventory badge layout changed")
            panel = Image.new("RGB", (400, 320))
            panel.paste(frame.crop((125, 724, 195, 756)).resize((350, 160)), (0, 0))
            panel.paste(frame.crop((510, 724, 576, 756)).resize((330, 160)), (0, 160))
            panel.save(path)
            # The Valkyrie card turns grey when none are left (its x0 badge is
            # grey-on-grey and unreadable). Recorded frames: live cards had mean
            # saturation >=148, empty cards <=29 (2026-11-05, 46 frames).
            # Empty cards also had value mean 63-65 and std 25-27: a black,
            # blank or loading frame must never look like "no Valkyries left".
            card = frame.convert("HSV").crop((110, 730, 188, 828))
            sat = list(card.getchannel("S").getdata())
            val = list(card.getchannel("V").getdata())
            valk_saturation = sum(sat) / len(sat)
            v_mean = sum(val) / len(val)
            v_std = (sum((v - v_mean) ** 2 for v in val) / len(val)) ** .5
            grey_card = valk_saturation < 60 and 45 <= v_mean <= 90 and v_std >= 15
        lines = self.read_ocr([str(path)]).get(str(path), [])
        counts = parse_inventory_badges(lines)
        variants = []
        troop_variants = []
        if counts["valkyries"] is None:
            # The bright x36 badge is sometimes returned as Cyrillic ХЗБ.
            # Re-read thresholded pixels; never translate ambiguous digits or
            # infer a count from the expected inventory or issued inputs.
            paths = []
            for threshold in (180, 200, 220):
                alternate = path.with_stem(path.stem + "-valk-threshold" + str(threshold))
                panel.convert("L").point(lambda p, t=threshold: 255 if p > t else 0).save(alternate)
                paths.append(str(alternate))
            # x16 is often read as Cyrillic "ХІБ" at full confidence. An
            # inverted and a 2x-scaled binarized view of the same badge read it
            # in Latin on every recorded frame (r808-r818, 2026-11-05); they
            # are only extra views, two agreeing readings are still required.
            badge = panel.crop((0, 0, 350, 160)).convert("L")
            inverted = Image.new("L", (400, 320), 255)
            inverted.paste(badge.point(lambda p: 0 if p > 200 else 255), (0, 0))
            scaled = Image.new("L", (800, 640), 0)
            scaled.paste(badge.resize((700, 320)).point(lambda p: 255 if p > 200 else 0), (0, 0))
            for name, image in (("inv200", inverted), ("big200", scaled)):
                alternate = path.with_stem(path.stem + "-valk-" + name)
                image.save(alternate)
                paths.append(str(alternate))
            readings = self.read_ocr(paths)
            troop_variants =[{"path": p, "lines": readings.get(p, []),
                              "counts": parse_inventory_badges(readings.get(p, []))} for p in paths]
            counts = recover_valkyrie_count(counts, [v["counts"] for v in troop_variants])
            if (counts["valkyries"] is None and grey_card
                    and all(v["counts"]["valkyries"] in (None, 0) for v in troop_variants)):
                counts = {**counts, "valkyries": 0}  # grey card, no conflicting reading
        if counts["earthquakes"] is None:
            # Disabled x0 is dark grey on grey. Never infer zero from absence;
            # require two high-confidence binarized readings on this same frame.
            paths = []
            for threshold in (60, 70, 80):
                alternate = path.with_stem(path.stem + "-threshold" + str(threshold))
                panel.convert("L").point(lambda p, t=threshold: 255 if p > t else 0).save(alternate)
                paths.append(str(alternate))
            readings = self.read_ocr(paths)
            variants = [{"path": p, "lines": readings.get(p, []),
                         "counts": parse_inventory_badges(readings.get(p, []))} for p in paths]
            counts = recover_earthquake_zero(counts, [v["counts"] for v in variants])
        self.save("inventory-" + obs["frameId"], {"observation": obs, "counts": counts,
                  "lines": lines, "zeroRecovery": variants, "troopRecovery": troop_variants,
                  "valkyrieCardSaturation": round(valk_saturation, 1)})
        return counts

    # -- ordinary search: home -> Battle -> ordinary Find a Match -> Attack! -> scout
    def _wait_screen(self, label, accept, timeout):
        """Observe + OCR until accept(lines) returns a value (or timeout -> None)."""
        end = time.time() + timeout
        while True:
            obs = self.observe(label)
            lines = self.read_ocr([obs["path"]]).get(obs["path"], [])
            if blocking_overlay(lines):
                raise GuardError("Blocking overlay during search: " + label)
            found = accept(lines)
            if found is not None:
                return obs, lines, found
            if time.time() >= end:
                return obs, lines, None
            time.sleep(.3)

    def search_to_scout(self, request):
        """Three grounded clicks, each on a freshly verified screen; ends on the scout.

        Only the ordinary (left, non-ranked) Find a Match is accepted. Nothing is
        deployed and the cutoff is not armed: the agent still reads the scout and
        the red boundary, starts recording and sends the armed deployment batch.
        """
        if (not self.armed and self.cutoff is not None
                and self.cutoff.get("status") == "returned_home" and not self.recording):
            # verified home after the watcher's own Return Home: same as reset
            self.halted, self.cutoff, self.last_below = False, None, None
        if self.armed or self.halted or self.cutoff is not None:
            raise GuardError("Search only from a reset controller between attacks")
        started = round(time.time() * 1000)
        steps = []

        def click(label, point, obs):
            issued = round(time.time() * 1000)
            self.device.tap(*point)
            steps.append({"label": label, "point": point, "issuedAtMs": issued,
                          "groundedFrameId": obs["frameId"]})
            self.rec_event("batch", id="search_to_scout", actions=[
                {"kind": "ui", "label": label, "point": point, "issuedAtMs": issued}])

        def home_battle(lines):
            if classify_screen(lines)["screen"] != "home":
                return None
            for l in lines:
                x, y, w, h = l["box"]
                if norm(l["text"]) == "battle" and l.get("conf", 0) >= .9 and x < .2 and y > .85:
                    return text_center(l)
            return None

        def ordinary_find(lines):
            if classify_screen(lines)["screen"] != "battle_menu":
                return None
            heads = [text_center(l) for l in lines
                     if norm(l["text"]) == "battle" and l.get("conf", 0) >= .9]
            for l in lines:
                if norm(l["text"]) != "find a match" or l.get("conf", 0) < .9:
                    continue
                x, y = text_center(l)
                # left column only, directly under its own "Battle" header (ranked is right)
                if x < 420 and any(abs(hx - x) < 90 and 20 < y - hy < 120 for hx, hy in heads):
                    return [x, y]
            return None

        def army_attack(lines):
            labels = {norm(l["text"]) for l in lines if l.get("conf", 0) >= .9}
            if "my army" not in labels:
                return None
            for l in lines:
                x, y, w, h = l["box"]
                if (re.fullmatch(r"a[rt]{1,2}ack", norm(l["text"])) and l.get("conf", 0) >= .9
                        and x > .75 and .7 < y < .85):
                    return text_center(l)
            return None

        def scout(lines):
            return True if classify_screen(lines)["screen"] == "scout" else None

        def fail(where, obs, lines):
            response = {"stopped": where, "steps": steps, "observation": obs,
                        "screen": classify_screen(lines), "state": self.state()}
            self.save("search-to-scout-" + str(started), response)
            return response

        obs, lines, point = self._wait_screen("search-home", home_battle, 0)
        if point is None:
            return fail("home_battle_button_not_verified", obs, lines)
        click("Battle", point, obs)
        obs, lines, point = self._wait_screen("search-menu", ordinary_find, 8)
        if point is None:
            return fail("ordinary_find_a_match_not_verified", obs, lines)
        click("Ordinary_FindMatch", point, obs)
        obs, lines, point = self._wait_screen("search-army", army_attack, 8)
        if point is None:
            return fail("army_attack_button_not_verified", obs, lines)
        army = sorted({l["text"] for l in lines if re.fullmatch(r"\d+/\d+", l["text"].strip())})
        click("Attack", point, obs)
        obs, lines, ok = self._wait_screen("search-scout", scout, float(request.get("scoutTimeout", 30)))
        if ok is None:
            return fail("scout_not_reached", obs, lines)
        response = {"stopped": "scout_reached_agent_verification_required", "steps": steps,
                    "armyCounts": army, "elapsedMs": round(time.time() * 1000) - started,
                    "observation": obs, "screen": classify_screen(lines), "state": self.state()}
        self.save("search-to-scout-" + obs["frameId"], response)
        return response

    # Screen areas where a tap hits HUD, never ground (1280x960).
    HUD_RECTS = ((0, 0, 340, 215), (520, 0, 760, 90), (950, 0, 1280, 180),
                 (0, 620, 430, 705), (1030, 610, 1280, 705), (0, 705, 1280, 960))

    def ring_deploy(self, request):
        """Spread all Valkyries round-robin over agent-verified legal anchors around the base.

        The agent reads the red boundary on a fresh frame (after any camera move)
        and supplies 6..16 anchors with a visible margin outside it, in ring order.
        This only builds the bounded steps; deployment_plan's guards still apply
        (armed battle, deadline, <=20 inputs/step, inventory checked after each).
        """
        anchors, checkpoint = self._ring_anchors(request)
        select = request.get("valkyrieSelect")
        if (not isinstance(select, list) or len(select) != 2
                or not (705 < select[1] < 960)):
            raise GuardError("valkyrieSelect must be the Valkyrie slot in the bottom bar")
        count, quakes = request.get("valkyries"), request.get("earthquakes")
        if (not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 60
                or not isinstance(quakes, int) or isinstance(quakes, bool) or quakes < 0):
            raise GuardError("Current valkyries (1..60) and earthquakes counts required")
        deadline = request.get("deadline")
        now = round(time.time() * 1000)
        steps, left, k = [], count, 0
        while left:
            actions = [] if steps else [{"kind": "select", "label": "Valkyries ring", "point": select}]
            while left and len(actions) < 20:
                actions.append({"kind": "spawn", "label": f"Valkyrie ring {k + 1}",
                                "point": anchors[k % len(anchors)]})
                k += 1
                left -= 1
            steps.append({"batch": {"id": f"{request.get('id', 'ring')}-{len(steps) + 1}",
                                    "checkpoint": checkpoint,
                                    "deadline": deadline, "actions": actions, "settleSeconds": 1},
                          "expectedCounts": {"valkyries": left, "earthquakes": quakes}})
        return self.deployment_plan({"id": request.get("id", "ring-" + str(now)),
                                     "initialExpectedCounts": {"valkyries": count, "earthquakes": quakes},
                                     "steps": steps})

    def _ring_anchors(self, request):
        """Validate 6..16 agent-read legal anchors from a fresh boundary frame."""
        anchors = request.get("anchors")
        if (not isinstance(anchors, list) or not 6 <= len(anchors) <= 16 or any(
                not isinstance(p, list) or len(p) != 2
                or any(not isinstance(v, int) or isinstance(v, bool) for v in p) for p in anchors)):
            raise GuardError("Ring needs 6..16 integer [x, y] anchors")
        for x, y in anchors:
            if not (40 <= x <= 1240 and 95 <= y <= 700) or any(
                    a <= x <= c and b <= y <= d for a, b, c, d in self.HUD_RECTS):
                raise GuardError(f"Anchor {[x, y]} is on HUD or off the map view")
        if any(abs(p[0] - q[0]) + abs(p[1] - q[1]) < 30
               for i, p in enumerate(anchors) for q in anchors[i + 1:]):
            raise GuardError("Ring anchors must be spread (>=30 px apart)")
        read_at = request.get("boundaryCapturedAtMs")
        now = round(time.time() * 1000)
        if (not isinstance(read_at, int) or read_at < self.camera_moved_ms
                or now - read_at > 90000):
            raise GuardError("Anchors must come from a boundary frame after the last camera move (<90 s old)")
        checkpoint = request.get("checkpoint")
        if (not isinstance(checkpoint, dict) or not checkpoint.get("frameId")
                or checkpoint.get("size") != [1280, 960]
                or any(not any(s.get("point") == anchor and s.get("evidence")
                               for s in checkpoint.get("legalSpawns", []))
                       for anchor in anchors)):
            raise GuardError("Ring needs a boundary checkpoint with legalSpawns evidence for every anchor")
        return anchors, checkpoint

    SPAM_HEROES = ("king", "queen", "warden", "duke")

    def spam_attack(self, request):
        """User request 2026-11-07: "just spam the army when we got an opponent".

        One command from the scout: heroes + own siege + all Valkyries (ring over
        the same agent-read legal anchors) + every Earthquake + hero abilities,
        issued back to back in <=20-input batches. Each batch still gets the
        fresh battle/objective check of the batch command (completion cancels the rest);
        the slow multi-OCR inventory count runs once before and once at the end.
        """
        if self.armed or self.halted or self.cutoff is not None:
            raise GuardError("Spam attack starts a new attack from the scout only")
        anchors, checkpoint = self._ring_anchors(request)
        slots = request.get("slots")
        names = ("valkyries", "earthquakes", "siege") + self.SPAM_HEROES
        if not isinstance(slots, dict) or any(
                not isinstance(slots.get(n), list) or len(slots[n]) != 2
                or any(not isinstance(v, int) or isinstance(v, bool) for v in slots[n])
                or not (0 <= slots[n][0] <= 1280 and 705 < slots[n][1] < 960)
                for n in names if n in slots or n in ("valkyries",)):
            raise GuardError("slots need bottom-bar [x, y] points (valkyries required)")
        count, quakes = request.get("valkyries"), request.get("earthquakes")
        if (not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 60
                or not isinstance(quakes, int) or isinstance(quakes, bool) or not 0 <= quakes <= 20):
            raise GuardError("Current valkyries (1..60) and earthquakes (0..20) counts required")
        targets = request.get("quakeTargets") or []
        if quakes and "earthquakes" not in slots:
            raise GuardError("Earthquakes need their bottom-bar slot")
        if quakes and (not isinstance(targets, list) or not 1 <= len(targets) <= quakes or any(
                not isinstance(p, list) or len(p) != 2
                or any(not isinstance(v, int) or isinstance(v, bool) for v in p)
                or not (40 <= p[0] <= 1240 and 95 <= p[1] <= 700)
                or any(a <= p[0] <= c and b <= p[1] <= d for a, b, c, d in self.HUD_RECTS)
                for p in targets)):
            raise GuardError("quakeTargets: 1..earthquakes map points off the HUD")
        deadline = request.get("deadline")
        if not isinstance(deadline, dict) or not deadline.get("seconds") or not deadline.get("capturedAtMs"):
            raise GuardError("Spam attack needs the live battle deadline")
        rid = request.get("id") or "spam-" + str(round(time.time() * 1000))

        # Units: heroes and siege first, each on its own anchor spread around the ring.
        units = [n for n in ("siege",) + self.SPAM_HEROES if n in slots]
        actions = []
        for i, name in enumerate(units):
            point = anchors[(i * len(anchors)) // max(len(units), 1)]
            actions += [{"kind": "select", "label": f"Spam {name}", "point": slots[name]},
                        {"kind": "spawn", "label": f"Spam {name} legal edge", "point": point}]
        actions.append({"kind": "select", "label": "Spam Valkyries", "point": slots["valkyries"]})
        actions += [{"kind": "spawn", "label": f"Spam Valkyrie {k + 1}",
                     "point": anchors[k % len(anchors)]} for k in range(count)]
        if quakes:
            actions.append({"kind": "select", "label": "Spam Earthquakes", "point": slots["earthquakes"]})
            actions += [{"kind": "spell", "label": f"Spam Earthquake {k + 1}",
                         "point": targets[k % len(targets)]} for k in range(quakes)]
        actions += [{"kind": "ability", "label": f"Spam {name} ability", "point": slots[name]}
                    for name in self.SPAM_HEROES if name in slots and request.get("abilities", True)]
        batches = [actions[i:i + 20] for i in range(0, len(actions), 20)]

        response = {"id": rid, "planned": len(actions), "batches": [], "stopped": None}
        # The Earthquake badge is sometimes unreadable on one frame (r2083):
        # re-read up to two fresh frames before refusing. No input yet.
        wanted = {"valkyries": count, "earthquakes": quakes}
        for attempt in range(3):
            obs = self.observe("spam-start")
            before = self.inventory_badges(obs)
            if before == wanted:
                break
            time.sleep(.3)
        response["countsBefore"] = before
        response["startReads"] = attempt + 1
        if before != wanted:
            response["stopped"] = "initial_inventory_mismatch_or_unreadable"
            self.save(rid, response)
            return {**response, "state": self.state()}
        for n, chunk in enumerate(batches):
            batch = {"id": f"{rid}-{n + 1}", "checkpoint": checkpoint, "deadline": deadline,
                     "actions": chunk, "settleSeconds": .25}
            result = self.command({"command": "batch", "batch": batch, "armCutoff": n == 0})
            response["batches"].append({"id": batch["id"], "inputs": len(chunk),
                                        "cancelled": result.get("cancelled"),
                                        "inputMs": (result.get("receipt") or {}).get("inputMs")})
            if "receipt" not in result:
                response["stopped"] = result.get("cancelled", "batch_not_issued")
                break
            if result.get("deploymentRejected"):
                # Leave the watcher armed: the agent must inspect fresh ground
                # and inventory; result/explicit-cutoff monitoring continues.
                response["stopped"] = "deployment_rejected_agent_inspection_required"
                response["rejectedObservation"] = result["receipt"]["observation"]
                break
            if self.cutoff is not None or self.halted or not self.armed:
                response["stopped"] = "cutoff_or_unexpected_screen"
                break
        else:
            # Earthquakes are cast one after another and the badges render late
            # (r2076-r2093: an immediate frame read 7 or 11 EQ, settling to 0 a
            # few seconds later). Poll fresh frames for up to ~6 s; each frame
            # also goes through the objective check, so completion stops input.
            after = self.inventory_badges(self.latest)
            reads, end = 1, time.time() + 6
            while (after != {"valkyries": 0, "earthquakes": 0} and time.time() < end
                   and self.armed and self.cutoff is None and not self.halted):
                time.sleep(.4)
                obs = self.observe()
                self.check(obs)
                if self.cutoff is not None or self.halted or not self.armed:
                    break
                after = self.inventory_badges(obs)
                reads += 1
            response["countsAfter"] = after
            response["finalReads"] = reads
            if self.cutoff is not None or self.halted or not self.armed:
                response["stopped"] = "cutoff_or_unexpected_screen"
                self.save(rid, response)
                return {**response, "state": self.state()}
            response["stopped"] = ("all_deployed_agent_verification_required"
                                   if after == {"valkyries": 0, "earthquakes": 0}
                                   else "final_inventory_mismatch_or_unreadable")
        self.save(rid, response)
        return {**response, "state": self.state()}

    def deployment_plan(self, request):
        """Agent-prepared steps only; every <=20 inputs is observed and checked."""
        steps = request.get("steps", [])
        if not self.armed or self.halted or self.cutoff is not None:
            return {"stopped": "not_active_battle", "state": self.state()}
        if not 1 <= len(steps) <= 5:
            raise GuardError("Expected 1..5 bounded deployment steps")
        for step in steps:
            batch = step["batch"]
            if not batch.get("deadline") or not 1 <= len(batch.get("actions", [])) <= 20:
                raise GuardError("Every deployment step needs a deadline and <=20 inputs")
            if set(step.get("expectedCounts", {})) != {"valkyries", "earthquakes"}:
                raise GuardError("Every step needs both expected inventory counts")
            if any(a.get("kind") not in {"select", "spawn", "spell", "ability"}
                   for a in batch["actions"]):
                raise GuardError("Deployment plan contains a navigation action")
        self.check()
        if self.halted or self.cutoff is not None or not self.armed:
            return {"stopped": "cutoff_or_unexpected_screen", "state": self.state()}
        expected = request.get("initialExpectedCounts")
        if (not isinstance(expected, dict) or set(expected) != {"valkyries", "earthquakes"}
                or self.inventory_badges(self.latest) != expected):
            return {"stopped": "initial_inventory_mismatch_or_unreadable", "state": self.state()}
        results = []
        for step in steps:
            result = self.command({"command": "batch", "batch": step["batch"]})
            results.append(result)
            if self.halted or self.cutoff is not None or not self.armed or "receipt" not in result:
                stopped = result.get("cancelled", "cutoff_or_unexpected_screen")
                break
            counts = self.inventory_badges(result["receipt"]["observation"])
            if counts != step["expectedCounts"]:
                stopped = "inventory_mismatch_or_unreadable"
                break
        else:
            stopped = "steps_complete_agent_verification_required"
        response = {"stopped": stopped, "stepsIssued": len(results), "results": results, "state": self.state()}
        self.save(request["id"], response)
        return response


def serve(args):
    device = Device()
    if device.input_backend != "scrcpy":
        device.close()
        raise GuardError("Live cutoff requires the approved scrcpy input backend")
    stream_info = None
    if args.stream:
        # Frames from the scrcpy video stream; Device.observe falls back to
        # screencap on any stream error (receipt field "streamFallback").
        try:
            stream_info = device.attach_stream()
        except Exception as error:
            stream_info = {"stream": False, "error": str(error)}
    session = CutoffSession(device, args.out, target_percent=args.target_percent)
    session.record_root = args.record_root
    if args.ship_to:
        from footage_shipper import Shipper
        session.shipper = Shipper(args.record_root, args.ship_to).start()
    session.auto_return_home = args.auto_return_home
    device.view_jpeg = args.view_jpeg
    requests = queue.Queue()
    old_term = configure_command_terminal(sys.stdin)
    threading.Thread(target=read_commands, args=(sys.stdin, requests), daemon=True).start()
    print(json.dumps({"event": "ready", "info": device.info(), "stream": stream_info}), flush=True)
    try:
        while True:
            try:
                request = requests.get(timeout=.1)
            except queue.Empty:
                if (session.armed or session.confirmation_pending()) and time.monotonic()-session.last_check >= session.poll_seconds:
                    before = (session.armed, session.cutoff.get("status") if session.cutoff else None)
                    try:
                        session.check()
                    except Exception as error:
                        session.armed = False
                        session.halted = True
                        if session.confirmation_pending():
                            session.cutoff["status"] = "confirmation_observation_error"
                            session.save("cutoff-latest", session.cutoff)
                        session.save("watch-error", {"error": str(error)})
                    after = (session.armed, session.cutoff.get("status") if session.cutoff else None)
                    if before != after:
                        print(json.dumps({"event": "watch_stopped", "state": session.state()}), flush=True)
                continue
            if request.get("command") == "close":
                session.record_stop(reason="close")
                print(json.dumps({"event": "closed", "state": session.state()}), flush=True)
                break
            try:
                if request.get("command") == "reset":
                    if session.armed:
                        raise GuardError("Disarm before resetting between attacks")
                    session.record_stop(reason="reset_at_home")
                    session.halted = False
                    session.cutoff = None
                    session.last_below = None
                    response = session.state()
                else:
                    response = session.command(request)
                print(json.dumps({"id": request.get("id"), "response": response}), flush=True)
            except Exception as error:
                session.armed = False
                session.halted = True
                print(json.dumps({"id": request.get("id"), "error": str(error), "state": session.state()}), flush=True)
    finally:
        device.close()
        if old_term is not None:
            import termios
            termios.tcsetattr(sys.stdin, termios.TCSANOW, old_term)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--stream", action="store_true",
                        help="observe from the scrcpy video stream (falls back to screencap)")
    parser.add_argument("--record-root", default=str(DEFAULT_RECORD_ROOT),
                        help="attack footage root (record_start writes incoming/<id>/ here)")
    parser.add_argument("--ship-to", default="mini:/Volumes/T7/coc/attack-footage",
                        help="move finished recordings here over ssh ('' = keep them local)")
    parser.add_argument("--auto-return-home", action="store_true",
                        help="after a natural result or explicit cutoff, save settled results and Return Home")
    parser.add_argument("--target-percent", type=int, choices=(50, 100), default=100,
                        help="100 (default): natural completion; 50: historical immediate cutoff")
    parser.add_argument("--view-jpeg", action="store_true",
                        help="also write <frame>.view.jpg (small copy for the agent to view)")
    serve(parser.parse_args())
