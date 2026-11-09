#!/usr/bin/env python3
"""Offline check of screen_reader on the 95 stream frames (needs macOS Vision; see vision_ocr.swift).

These are stream captures, not device screenshots: results show the method
works on real game text, not final accuracy on controller frames.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from screen_reader import classify_screen, ocr, read_counts  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FRAMES = "/Users/elijah/program/coc/pretraining_preparation/2026-10-12/reviewed_dataset_staging_v19/native"
spec = json.load(open(os.path.join(HERE, "screen_truth_v19.json")))
truth = {i: k for k, v in spec["labels"].items() for i in v}
counts_truth = {int(k): v for k, v in spec.get("counts", {}).items()}
fs = sorted(os.path.join(FRAMES, f) for f in os.listdir(FRAMES) if f.endswith(".png"))
res = ocr(fs)

wrong, unsafe = [], []
for i, f in enumerate(fs):
    p = classify_screen(res[f])["screen"]
    if p != truth[i]:
        wrong.append((i, truth[i], p))
        if p in ("battle", "scout") and truth[i] not in ("battle", "scout"):
            unsafe.append((i, truth[i], p))
acc = 1 - len(wrong) / len(fs)
print(f"screen accuracy {len(fs) - len(wrong)}/{len(fs)} ({acc:.0%}); errors: {wrong}")
print(f"non-battle frames called battle/scout: {unsafe}")

from collections import Counter  # noqa: E402

items = [(f"v19#{i}", fs[i], want) for i, want in counts_truth.items()]
other = spec.get("counts_other_sets", {})
other_res = ocr(list(other)) if other else {}
res.update(other_res)
items += [(os.path.basename(f)[:40], f, want) for f, want in other.items()]
found = wrong = total = 0
for name, f, want in items:
    got = Counter(c["count"] for c in read_counts(res[f]))
    w = Counter(want)
    hit = sum((got & w).values())
    bad = sum((got - w).values())
    found, wrong, total = found + hit, wrong + bad, total + len(want)
    print(f"counts {name}: {hit}/{len(want)} badges found, {bad} wrong values")
print(f"badges found {found}/{total} ({found / total:.0%}), wrong values {wrong}")
