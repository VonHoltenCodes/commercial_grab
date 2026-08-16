"""ffmpeg-based signal scanning: black frames + silence in one decode pass.

Broadcast masters cut to black (often with a silent gap) between program and
spots, and between individual spots. Those black+silent moments are the cut
candidates everything downstream builds on.
"""

import json
import re
import subprocess
from pathlib import Path


def probe(video: Path) -> dict:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries",
            "format=duration,size,bit_rate:stream=index,codec_name,codec_type,width,height,avg_frame_rate",
            "-of", "json", str(video),
        ],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


BLACK_RE = re.compile(
    r"black_start:(?P<start>[\d.]+)\s+black_end:(?P<end>[\d.]+)\s+black_duration:(?P<dur>[\d.]+)"
)
SILENCE_START_RE = re.compile(r"silence_start:\s*(?P<start>[\d.]+)")
SILENCE_END_RE = re.compile(r"silence_end:\s*(?P<end>[\d.]+)\s*\|\s*silence_duration:\s*(?P<dur>[\d.]+)")


def scan(
    video: Path,
    black_min_dur: float = 0.05,
    black_pix_th: float = 0.10,
    silence_db: float = -35.0,
    silence_min_dur: float = 0.3,
    hwaccel: str = "auto",
) -> dict:
    """Single ffmpeg pass running blackdetect + silencedetect, parsed from stderr."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats"]
    if hwaccel == "auto":
        cmd += ["-hwaccel", "auto"]
    elif hwaccel != "none":
        cmd += ["-hwaccel", hwaccel]
    cmd += [
        "-i", str(video),
        "-vf", f"blackdetect=d={black_min_dur}:pix_th={black_pix_th}",
        "-af", f"silencedetect=n={silence_db}dB:d={silence_min_dur}",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg scan failed:\n{proc.stderr[-2000:]}")

    blacks, silences = [], []
    pending_silence = None
    for line in proc.stderr.splitlines():
        m = BLACK_RE.search(line)
        if m:
            blacks.append({
                "start": float(m["start"]),
                "end": float(m["end"]),
                "duration": float(m["dur"]),
            })
            continue
        m = SILENCE_START_RE.search(line)
        if m:
            pending_silence = float(m["start"])
            continue
        m = SILENCE_END_RE.search(line)
        if m and pending_silence is not None:
            silences.append({
                "start": pending_silence,
                "end": float(m["end"]),
                "duration": float(m["dur"]),
            })
            pending_silence = None

    return {
        "params": {
            "black_min_dur": black_min_dur,
            "black_pix_th": black_pix_th,
            "silence_db": silence_db,
            "silence_min_dur": silence_min_dur,
        },
        "black": blacks,
        "silence": silences,
    }


def cut_candidates(scan_data: dict, silence_slop: float = 0.5) -> list[dict]:
    """Fuse black intervals with silence into ranked cut candidates.

    A black interval that overlaps (or nearly touches) a silence interval is a
    high-confidence broadcast cut. Black without silence still counts — music
    beds often run through the fade — just at lower confidence.
    """
    candidates = []
    silences = scan_data["silence"]
    for b in scan_data["black"]:
        has_silence = any(
            s["start"] - silence_slop <= b["end"] and s["end"] + silence_slop >= b["start"]
            for s in silences
        )
        candidates.append({
            "time": round((b["start"] + b["end"]) / 2, 3),
            "black_start": b["start"],
            "black_end": b["end"],
            "black_duration": b["duration"],
            "silent": has_silence,
        })
    return candidates
