"""Screen-type classifier and troop-count reader from on-screen text (ADVISORY).

Uses macOS Vision OCR (vision_ocr binary built from vision_ocr.swift). Text is
scale- and position-independent, so it was first checked on stream captures.
Counts and screen type remain advisory: the agent still verifies the frame.

Offline results (test_screen_reader.py, test_screen_reader_all.py, 2026-11-03), stream captures only:
- all 942 by-eye-reviewed frames: 850/942 (90%), home 171/223, 0 non-battle frames called battle/scout.
- screen type: 92/95 on the labelled set, no non-battle frame called battle/scout
  (after adding "Spectators" as a replay cue; 3 battle frames now fall to the
  safe side as replay/unknown); 1,019/1,019 building crops -> unknown;
  by-eye sample of 56 predictions on 942 other full frames: battle 7/8 (the miss,
  a results screen, is now its own class), results 8/8, scout 8/8, replay 7/8,
  war_preview 6/8, home 5/8 (menus/popups over home), unknown 8/8.
- troop counts: 156/237 badges found (66%), 0 wrong values, over 23 bars. Misses
  are silent, and two-row bars come back as one left-to-right list.
Do NOT use read_counts for "all troops deployed" or spending decisions until
it is re-tested on controller screenshots and returns per-slot rows.
"""
from __future__ import annotations

import json
import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
OCR_BIN = os.path.join(HERE, "vision_ocr")


def ocr(paths: list[str]) -> dict[str, list[dict]]:
    out = subprocess.run([OCR_BIN, *paths], capture_output=True, text=True, timeout=120).stdout
    res = {}
    for line in out.splitlines():
        d = json.loads(line)
        res[d["path"]] = d.get("lines", [])
    return res


def _norm(t: str) -> str:
    # Vision returns mixed case/lookalike glyphs for the game font ("RetuRN", "Номе")
    t = t.lower().translate(str.maketrans("номерасхі", "homepacxi"))
    return re.sub(r"[^a-z0-9!: ]", "", t).strip()


# Exact short-label matches only: chat overlays contain phrases like
# "Attack on titan", so substring matching would misfire. French labels are
# included because some reference streams run the game in French.
LABELS = {
    "battle": {"surrender", "battle ends in", "battle ends in:", "capituler",
               "fin de la bataille dans", "fin de la bataille dans:", "finde la babaille dans:"},
    "end_battle": {"end battle", "terminer la", "terminer la bataille"},
    "scout": {"next", "battle starts in", "battle starts in:", "suivant",
              "la bataille commence dans", "la bataille commence dans:"},
    "war": {"war map", "return home", "return", "home", "attaquer", "carte de", "guerre", "carte de guerre"},
    "replay": {"live replay", "replay", "visionnage", "spectators", "spectators:", "spectateurs", "spectateurs:",
               "live rplay", "live repiay", "troops available", "troops available:", "troupes disponibles"},
    "results": {"victory", "defeat", "troops expended", "troops expended:", "victoire", "defaite"},
    "home": {"shop", "boutique", "magasin"},
    # panels that only open over the home village (army, chat, profile, layout)
    "home_overlay": {"my army", "saved recipes", "cookbook", "unplaced items", "coleader", "co-leader",
                     "member", "elder", "shared an army composition", "collect", "my profile",
                     "home village", "builder base", "clan capital", "mon armee", "village principal"},
    "attack": {"attack!", "attaquer"},
    # current home HUD (2026, BlueStacks live): bottom-left "Battle", bottom-right "Build"
    "home_buttons": {"battle", "build"},
    # Battle hub opened from the home "Battle" button; holds ranked "Find a Match"
    "battle_menu": {"multiplayer", "single player", "practice", "find a match", "ranked battle",
                    "edit army", "star bonus"},
}


def classify_screen(lines: list[dict]) -> dict:
    found = {k: sorted({_norm(l["text"]) for l in lines if _norm(l["text"]) in v}) for k, v in LABELS.items()}
    # home buttons count only in their bottom corners (a "Battle" word elsewhere is not the button)
    found["home_buttons"] = sorted({
        _norm(l["text"]) for l in lines
        if _norm(l["text"]) in LABELS["home_buttons"] and l["box"][1] > 0.85
        and ((_norm(l["text"]) == "battle" and l["box"][0] < 0.2) or (_norm(l["text"]) == "build" and l["box"][0] > 0.75))})
    returning = {"return home"} <= set(found["war"]) or {"return", "home"} <= set(found["war"])
    # Spectators can watch a live attack too. Only explicit replay labels
    # override an otherwise verified scout/battle; spectators alone do not.
    spectators = {"spectators", "spectators:", "spectateurs", "spectateurs:"}
    explicit_replay = set(found["replay"]) - spectators
    if explicit_replay or (found["replay"] and not (
            found["battle"] or found["scout"] or found["end_battle"] or found["results"])):
        label = "replay"
    elif found["results"] or (returning and not found["attack"] and (found["battle"] or found["end_battle"])):
        # results banner is drawn over the battle HUD, so it must outrank battle
        label = "results"
    elif found["battle"]:  # Surrender / "battle ends in" appear only once a battle started
        label = "battle"
    elif found["scout"]:  # scout also shows "End Battle", so Next wins over it
        label = "scout"
    elif found["end_battle"]:
        label = "battle"
    elif len(found["battle_menu"]) >= 2:  # contains ranked "Find a Match": never tap blindly here
        label = "battle_menu"
    elif found["war"] and (found["attack"] or {"war map", "carte de", "guerre", "carte de guerre"} & set(found["war"])):
        label = "war_preview"
    elif (found["home"] or (found["attack"] and found["home_overlay"]) or len(found["home_overlay"]) >= 2
          or len(found["home_buttons"]) == 2):
        # shop button alone is home-only; overlays hide it, so two overlay cues also count
        label = "home"
    else:
        label = "unknown"
    return {"screen": label, "evidence": {k: v for k, v in found.items() if v}}


COUNT_RE = re.compile(r"^[x×][o0-9isb]{1,3}$")
DIGIT_FIX = str.maketrans("oisb", "0158")  # common Vision misreads of the game font


def read_counts(lines: list[dict], bar_top: float = 0.70) -> list[dict]:
    """Troop/spell slot counts like 'x12' in the bottom bar, left to right.

    Returns positions (normalised) so the agent can match counts to slots.
    Lookalike letters are mapped to digits: o->0, i->1, s->5, b->8.
    """
    out = []
    for l in lines:
        t = l["text"].strip().lower().replace(" ", "")
        x, y, w, h = l["box"]
        if y >= bar_top and COUNT_RE.match(t):
            out.append({"count": int(t[1:].translate(DIGIT_FIX)), "x": round(x + w / 2, 4), "y": round(y + h / 2, 4),
                        "conf": round(l["conf"], 2)})
    return sorted(out, key=lambda c: c["x"])
