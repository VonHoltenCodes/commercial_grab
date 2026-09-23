"""Snap reviewed ad-to-ad boundaries to the nearest hard cut.

Word timestamps drift ~0.3-1s from the true frame cut (whisper hears speech
early; end cards outlast their audio), so boundaries placed from the
transcript land a beat off. For every commercial/duplicate -> commercial/
duplicate boundary in segments.json, this finds black-frame ends and scene
cuts within a small window and moves the boundary to the nearest one
(black preferred). Run AFTER the review pass writes segments.json and
BEFORE `cut` — skipping it is how end-card bleed reaches clips.
"""

import json
import re
import subprocess
from pathlib import Path


def _candidates(video: Path, t: float, window: float):
    out = []
    base = ["ffmpeg", "-hide_banner", "-ss", str(t - window), "-t", str(2 * window), "-i", str(video)]
    p = subprocess.run(base + ["-vf", "blackdetect=d=0.02:pix_th=0.13", "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    for m in re.finditer(r"black_end:([\d.]+)", p.stderr):
        out.append((t - window + float(m.group(1)), "black"))
    p = subprocess.run(base + ["-vf", "select='gt(scene,0.22)',showinfo", "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    for m in re.finditer(r"pts_time:([\d.]+)", p.stderr):
        out.append((t - window + float(m.group(1)), "scene"))
    return out


def refit(video: Path, segments: list[dict], window: float = 1.6,
          black_pref: float = 1.2, min_move: float = 0.04, progress=print) -> int:
    moved = 0
    for i in range(len(segments) - 1):
        a, b = segments[i], segments[i + 1]
        if a["label"] not in ("commercial", "duplicate"):
            continue
        if b["label"] not in ("commercial", "duplicate"):
            continue
        t = b["start"]
        cands = _candidates(video, t, window)
        if not cands:
            continue
        blacks = [c for c in cands if c[1] == "black" and abs(c[0] - t) <= black_pref]
        pick = min(blacks, key=lambda c: abs(c[0] - t)) if blacks else min(cands, key=lambda c: abs(c[0] - t))
        nt = round(pick[0], 3)
        if abs(nt - t) > min_move and a["start"] + 2 < nt < b["end"] - 2:
            progress(f"  {t:.2f} -> {nt:.2f} ({pick[1]})")
            a["end"] = nt
            b["start"] = nt
            a["duration"] = round(a["end"] - a["start"], 3)
            b["duration"] = round(b["end"] - b["start"], 3)
            moved += 1
    return moved
