"""Clip extraction. Default is stream copy (lossless, keyframe-snapped);
--precise re-encodes for frame-exact boundaries."""

import subprocess
from pathlib import Path

from .transcribe import fmt_ts


def clip_name(seg: dict, index: int) -> str:
    ts = fmt_ts(seg["start"]).replace(":", ".")
    if seg["label"] == "commercial":
        return f"break{seg['break']:02d}_spot{seg['spot']:02d}_{ts}.mkv"
    return f"show{index:03d}_{ts}.mkv"


def extract(
    video: Path,
    segments: list[dict],
    out_dir: Path,
    only: str | None = "commercial",
    precise: bool = False,
    pad: float = 0.0,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for i, seg in enumerate(segments):
        if only and seg["label"] != only:
            continue
        start = max(0.0, seg["start"] - pad)
        end = seg["end"] + pad
        out = out_dir / clip_name(seg, i)
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(video)]
        if precise:
            cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", "18",
                    "-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
        cmd += [str(out)]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        written.append(out)
    return written
