#!/usr/bin/env python3
"""Score screen_reader on all 942 unlabelled stream frames against the by-eye review.

Needs the OCR cache from a full run (ocr_all.json) and sets.json; see plan file.
Usage: python3 test_screen_reader_all.py SCRATCH_DIR
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from screen_reader import classify_screen  # noqa: E402

S = sys.argv[1]
full = json.load(open(os.path.join(S, "sets.json")))["full"]
ocr = json.load(open(os.path.join(S, "ocr_all.json")))
review = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "review_942.json")))
base = json.load(open(os.path.join(S, "review", "index.json")))["pred"]  # predictions the review was done on
truth = list(base)
for label, idx in review["corrections"].items():
    for i in idx:
        truth[i] = label
pred = [classify_screen(ocr[f])["screen"] for f in full]
act = {"battle", "scout"}
ok = sum(p == t for p, t in zip(pred, truth))
unsafe = [i for i, (p, t) in enumerate(zip(pred, truth)) if p in act and t not in act]
missed = [i for i, (p, t) in enumerate(zip(pred, truth)) if t in act and p not in act]
print(f"all 942: correct {ok}/{len(full)} ({ok / len(full):.0%})")
print(f"unsafe (non-battle called battle/scout): {len(unsafe)} {unsafe}")
print(f"battle/scout missed (safe side): {len(missed)}")
per = collections.defaultdict(lambda: [0, 0])
for p, t in zip(pred, truth):
    per[t][1] += 1
    per[t][0] += p == t
for k, (a, n) in sorted(per.items()):
    print(f"  {k:12s} {a}/{n}")
