"""Fuse cut candidates + transcript into labeled segments and a review sheet.

Heuristic: cut candidates split the timeline into blocks. Blocks short enough
to be a single spot (<= max_spot seconds) are labeled `commercial`; longer
blocks are `show`. Adjacent commercials group into numbered breaks. The
proposal is written both as machine-readable segments.json (the EDL) and a
human/agent review sheet (breaks.md) with transcript excerpts per block, so
misclassifications (cold opens, teasers, promos) can be fixed by editing
segments.json before cutting.
"""

import json
from pathlib import Path

from .transcribe import fmt_ts, text_between


def build_segments(
    candidates: list[dict],
    duration: float,
    max_spot: float = 130.0,
    min_block: float = 1.0,
    merge_gap: float = 0.75,
) -> list[dict]:
    # Collapse candidate clusters (rapid black flickers) into single cut points.
    cuts = []
    for c in sorted(candidates, key=lambda c: c["time"]):
        if cuts and c["time"] - cuts[-1] < merge_gap:
            continue
        cuts.append(c["time"])

    bounds = [0.0] + cuts + [duration]
    segments = []
    for start, end in zip(bounds, bounds[1:]):
        if end - start < min_block:
            continue
        segments.append({
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
            "label": "commercial" if (end - start) <= max_spot else "show",
        })

    # Group adjacent commercials into numbered breaks; number spots within each.
    break_no = 0
    prev_label = None
    spot_no = 0
    for seg in segments:
        if seg["label"] == "commercial":
            if prev_label != "commercial":
                break_no += 1
                spot_no = 0
            spot_no += 1
            seg["break"] = break_no
            seg["spot"] = spot_no
        prev_label = seg["label"]
    return segments


def review_markdown(segments: list[dict], transcript: dict | None, video_name: str) -> str:
    lines = [
        f"# Proposed segments — {video_name}",
        "",
        "Labels are heuristic (block length only). Review each block below —",
        "especially short `show` blocks and long `commercial` blocks — then edit",
        "`segments.json` and run `cut`.",
        "",
    ]
    n_comm = sum(1 for s in segments if s["label"] == "commercial")
    n_breaks = max((s.get("break", 0) for s in segments), default=0)
    lines.append(f"**{len(segments)} blocks · {n_comm} commercial spots in {n_breaks} breaks**")
    lines.append("")
    for i, seg in enumerate(segments):
        tag = seg["label"].upper()
        if seg["label"] == "commercial":
            tag += f" (break {seg['break']}, spot {seg['spot']})"
        lines.append(
            f"### {i:03d} · `{fmt_ts(seg['start'])} → {fmt_ts(seg['end'])}` "
            f"· {seg['duration']:.1f}s · **{tag}**"
        )
        if transcript:
            excerpt = text_between(transcript, seg["start"], seg["end"], max_chars=400)
            lines.append(f"> {excerpt or '(no speech detected)'}")
        lines.append("")
    return "\n".join(lines)


def save_segments(segments: list[dict], path: Path) -> None:
    path.write_text(json.dumps(segments, indent=2) + "\n")


def load_segments(path: Path) -> list[dict]:
    return json.loads(path.read_text())
