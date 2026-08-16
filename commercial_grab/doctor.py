"""Source-health checks for recovered recordings.

ddrescue'd DVD/VHS captures carry two container pathologies that break the
pipeline downstream, both invisible until something hangs or OOMs:

1. Bogus duration — a stray corrupt-PTS packet inflates the container
   duration (a "26-hour" file with 1.7 h of content). Detected by comparing
   header duration against the last contiguous packet timestamp.
2. Cluster fragmentation — remuxing streams with non-monotonic DTS writes
   one Matroska cluster per frame; seeking + encoding from such a file makes
   ffmpeg balloon to tens of GB and get OOM-killed. Detected by sampling the
   seek index density. Fix is a lossless `mkvmerge` rebuild.
"""

import json
import subprocess
from pathlib import Path


def packet_timeline(video: Path, jump_threshold: float = 5.0) -> dict:
    """Scan video packet PTS for discontinuities; return last contiguous time."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "packet=pts_time", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True,
    )
    prev = None
    jumps = []
    last_contiguous = 0.0
    for line in out.stdout.splitlines():
        line = line.strip().rstrip(",")
        if not line or line == "N/A":
            continue
        t = float(line)
        if prev is not None and abs(t - prev) > jump_threshold:
            jumps.append((prev, t))
        else:
            last_contiguous = max(last_contiguous, t)
        prev = t
    return {"jumps": jumps, "last_contiguous": last_contiguous}


def diagnose(video: Path) -> list[str]:
    problems = []
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(video)], capture_output=True, text=True, check=True).stdout)
    duration = float(probe["format"]["duration"])

    tl = packet_timeline(video)
    if tl["jumps"]:
        for a, b in tl["jumps"][:5]:
            problems.append(f"PTS discontinuity: {a:.2f}s -> {b:.2f}s (delta {b-a:+.0f}s)")
    if duration > tl["last_contiguous"] + 60:
        problems.append(
            f"Bogus container duration: header says {duration:.0f}s but contiguous "
            f"content ends at {tl['last_contiguous']:.0f}s. "
            f"Fix: ffmpeg -i in.mkv -t {tl['last_contiguous']:.1f} -map 0:v -map 0:a -c copy out.mkv"
        )

    # cluster pathology: healthy MKVs write a cluster every few hundred KB
    # (measured ~3/MB on a good DVD remux); pathological remuxes write one
    # per frame (~100/MB). Count Matroska cluster magic bytes (0x1F43B675)
    # in a 64 MB mid-file sample — non-Matroska files simply count ~0.
    SAMPLE = 64 * 1024 * 1024
    with open(video, "rb") as f:
        f.seek(max(0, video.stat().st_size // 2 - SAMPLE // 2))
        sample = f.read(SAMPLE)
    clusters = sample.count(b"\x1f\x43\xb6\x75")
    per_mb = clusters / max(1, len(sample) / 1e6)
    if per_mb > 10:
        problems.append(
            f"Fragmented container: ~{per_mb:.0f} clusters/MB (healthy is single digits). "
            f"Encoding clips from this file can balloon ffmpeg to tens of GB (OOM). "
            f"Fix: mkvmerge -o rebuilt.mkv {video.name}  (lossless, seconds)"
        )
    return problems
