"""Red no-deploy zone helper (ADVISORY ONLY).

Finds the red-tinted no-deployment overlay in a battle screenshot and checks
whether a spawn point is outside it with a margin. It never authorises a drop
by itself: AGENTS.md still requires the agent to confirm the boundary on the
current image and record evidence.

Use red_zone_mask_diff (frame before vs after the overlay appears). The
single-frame red_zone_mask is for debugging only: on 95 real stream frames
with no red zone it reported a false zone on 17 (lava ground, brown dirt
bases), which could make a point inside the real zone look legal. Diff mode
refuses pairs that are not the same view (phase correlation), but on 556
stream frame pairs it still drew false zones on 51 of the 513 it compared:
those pairs are seconds apart, with menus opening, buildings turning to rubble
and a fixed stream overlay that makes them look aligned. Intended use is two
device screenshots ~0.1 s apart, which stream data cannot reproduce. Never let
a mask alone authorise a drop. Both are tested only on synthetic
red overlays; recalibrate on real controller screenshots before relying on it.
"""
from __future__ import annotations

import cv2
import numpy as np


def red_zone_mask(bgr: np.ndarray, min_area_frac: float = 0.05) -> np.ndarray:
    """DEBUG ONLY, not for legality (18% false zones on real frames).

    Return uint8 mask (255 = red overlay).

    A semi-transparent red tint over green grass shifts toward orange (hue ~30
    deg), so accept red-to-orange hues where red clearly dominates green.
    Keep only the single largest red region, and only if it covers at least
    min_area_frac of the screen; troops and red UI buttons are smaller.
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    b, g, r = (bgr[..., i].astype(np.int16) for i in range(3))
    hue_red = (h <= 20) | (h >= 165)  # OpenCV hue is 0-180
    mask = (hue_red & (s >= 80) & (v >= 60) & (r - g >= 30) & (r - b >= 30)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask)
    keep = np.zeros_like(mask)
    if n > 1:
        i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        if stats[i, cv2.CC_STAT_AREA] >= min_area_frac * mask.size:
            keep[lab == i] = 255
    # fill holes: interior of the zone may contain non-red buildings
    contours, _ = cv2.findContours(keep, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(keep)
    cv2.drawContours(filled, contours, -1, 255, thickness=cv2.FILLED)
    return filled


def frames_comparable(before: np.ndarray, after: np.ndarray, max_shift_px: float = 3.0,
                      min_response: float = 0.3) -> float | None:
    """Phase-correlation peak if the frames are the same view, else None.

    A tint does not move the picture; a pan shifts it (large measured shift)
    and a menu or new screen decorrelates it (low peak response).
    """
    if before.shape != after.shape:
        return None
    g = [np.float32(cv2.cvtColor(cv2.resize(x, (480, 270)), cv2.COLOR_BGR2GRAY)) for x in (before, after)]
    (dx, dy), resp = cv2.phaseCorrelate(g[0], g[1])
    if resp < min_response or (dx * dx + dy * dy) ** 0.5 * 4 > max_shift_px:  # *4: back to 1920 px
        return None
    return float(resp)


def red_zone_mask_diff(before: np.ndarray, after: np.ndarray, min_area_frac: float = 0.05,
                       min_shift: int = 18) -> np.ndarray:
    """Mask from two frames: same camera, before and after the overlay appears.

    Works for faint tints: a red overlay raises (R - G) noticeably even when
    the result is still greenish. Camera or scene motion between frames
    breaks this; the agent must use frames taken back to back without panning.
    """
    if frames_comparable(before, after) is None:
        # different view: return an empty mask, which check_spawn treats as
        # "cannot judge" (never as legal)
        return np.zeros(before.shape[:2], np.uint8)
    b0, g0, r0 = (before[..., i].astype(np.int16) for i in range(3))
    b1, g1, r1 = (after[..., i].astype(np.int16) for i in range(3))
    shift = (r1 - g1) - (r0 - g0)
    mask = (shift >= min_shift).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask)
    keep = np.zeros_like(mask)
    if n > 1:
        i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        if stats[i, cv2.CC_STAT_AREA] >= min_area_frac * mask.size:
            keep[lab == i] = 255
    contours, _ = cv2.findContours(keep, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(keep)
    cv2.drawContours(filled, contours, -1, 255, thickness=cv2.FILLED)
    return filled


def check_spawn(mask: np.ndarray, point: tuple[int, int], margin_px: int = 40) -> dict:
    """Legal only if outside the mask AND at least margin_px from it."""
    x, y = map(int, point)
    hgt, wid = mask.shape
    if not (0 <= x < wid and 0 <= y < hgt):
        return {"legal": False, "reason": "off-screen", "distance_px": None}
    if not mask.any():
        return {"legal": False, "reason": "no red zone detected; cannot judge", "distance_px": None}
    if mask[y, x]:
        return {"legal": False, "reason": "inside red zone", "distance_px": 0.0}
    dist = cv2.distanceTransform((mask == 0).astype(np.uint8), cv2.DIST_L2, 5)
    d = float(dist[y, x])
    if d < margin_px:
        return {"legal": False, "reason": f"only {d:.0f}px from red zone (< {margin_px})", "distance_px": d}
    return {"legal": True, "reason": f"{d:.0f}px outside red zone", "distance_px": d}


def evidence(mask: np.ndarray, point, margin_px: int = 40) -> str:
    """Evidence text for legalSpawns; still requires the agent's visual check."""
    r = check_spawn(mask, point, margin_px)
    return f"red_zone.py advisory: {r['reason']} at {tuple(point)}; agent visually confirmed boundary on current frame"
