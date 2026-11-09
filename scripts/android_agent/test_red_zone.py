#!/usr/bin/env python3
"""Synthetic tests for red_zone.py: geometry and margin logic only, not real-game accuracy."""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from red_zone import check_spawn, red_zone_mask, red_zone_mask_diff  # noqa: E402

rng = np.random.default_rng(7)
W, H = 1920, 1080
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


def grass():
    img = np.zeros((H, W, 3), np.uint8)
    img[:] = (40, 150, 70)  # BGR green
    noise = rng.integers(-25, 25, (H, W, 1))
    return np.clip(img.astype(int) + noise, 0, 255).astype(np.uint8)


def diamond(cx=960, cy=540, rx=520, ry=360):
    return np.array([[cx, cy - ry], [cx + rx, cy], [cx, cy + ry], [cx - rx, cy]], np.int32)


def scene(red_alpha=0.45, buildings=True, red_units=True, return_before=False):
    img = grass()
    poly = diamond()
    truth = np.zeros((H, W), np.uint8)
    cv2.fillPoly(truth, [poly], 255)
    if buildings:  # grey/brown buildings inside the base
        for _ in range(40):
            x, y = rng.integers(700, 1220), rng.integers(330, 750)
            cv2.rectangle(img, (int(x), int(y)), (int(x) + 40, int(y) + 40), (90, 110, 130), -1)
    if red_units:  # small red things outside: troops, UI, must be ignored
        for _ in range(25):
            x, y = int(rng.integers(20, 300)), int(rng.integers(20, 1000))
            cv2.circle(img, (x, y), 8, (20, 20, 240), -1)
        cv2.rectangle(img, (1700, 950), (1880, 1040), (20, 20, 220), -1)  # red "End Battle"-like button
    before = img.copy()
    overlay = img.copy()
    overlay[truth > 0] = (30, 30, 230)  # red tint over the no-deploy area
    img = cv2.addWeighted(overlay, red_alpha, img, 1 - red_alpha, 0)
    return (before, img, truth) if return_before else (img, truth)


def iou(a, b):
    a, b = a > 0, b > 0
    return (a & b).sum() / max(1, (a | b).sum())


img, truth = scene()
m = red_zone_mask(img)
check("mask matches zone (IoU >= 0.95)", iou(m, truth) >= 0.95, f"IoU={iou(m, truth):.3f}")
check("small red units ignored", m[20:1000, 20:300].sum() == 0)
check("red UI button ignored", m[950:1040, 1700:1880].sum() == 0,
      "(it is large; ignored only because of the size threshold)")

check("inside zone -> illegal", not check_spawn(m, (960, 540))["legal"])
check("on boundary -> illegal", not check_spawn(m, (960 - 520, 540))["legal"])
r = check_spawn(m, (960 - 520 - 20, 540))
check("20px outside, margin 40 -> illegal", not r["legal"], r["reason"])
r = check_spawn(m, (960 - 520 - 80, 540))
check("80px outside, margin 40 -> legal", r["legal"], r["reason"])
check("off-screen -> illegal", not check_spawn(m, (5000, 10))["legal"])

empty = red_zone_mask(grass())
check("no red overlay -> no zone", not empty.any())
check("no zone -> refuses to judge", not check_spawn(empty, (100, 100))["legal"])

img2, t2 = scene(red_alpha=0.6)
check("single frame, strong tint 0.6", iou(red_zone_mask(img2), t2) >= 0.9)
# Known limit: one frame cannot see faint tints (pixel stays greener than red).
# Required: fail safe, i.e. no zone found -> refuse, never a wrong zone that
# makes an inside point look legal.
for alpha in (0.25, 0.35):
    img2, t2 = scene(red_alpha=alpha)
    m2 = red_zone_mask(img2)
    inside_ok = check_spawn(m2, (960, 540))["legal"]
    check(f"single frame, faint tint {alpha}: fails safe", not inside_ok,
          f"zone found={bool(m2.any())}, inside point legal={inside_ok}")

for alpha in (0.15, 0.25, 0.35):
    b, a, t = scene(red_alpha=alpha, return_before=True)
    v = iou(red_zone_mask_diff(b, a), t)
    check(f"before/after diff, tint alpha {alpha}", v >= 0.9, f"IoU={v:.3f}")
b, a, t = scene(return_before=True)
check("diff: identical frames -> no zone", not red_zone_mask_diff(b, b).any())
noisy = np.clip(b.astype(int) + rng.integers(-10, 10, b.shape), 0, 255).astype(np.uint8)
check("diff: noise only -> no zone", not red_zone_mask_diff(b, noisy).any())

shifted = np.roll(a, 120, axis=1)  # camera pan between frames
check("diff: panned frames -> refused", not red_zone_mask_diff(b, shifted).any())

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
