"""Cross-recording duplicate detection via transcript similarity.

Repeat airings of the same spot — within one broadcast or across tapes from
the same era — produce near-identical transcripts. This walks the commercial
segments of one or more .grab workdirs, pulls each segment's transcript text,
and groups segments whose normalized text is nearly identical. The first
(longest-text) member of each group is the keeper.

No-speech segments (bumpers, music-only ads) can't be compared this way and
are always kept.
"""

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

MIN_WORDS = 8          # too little speech to fingerprint
SIM_THRESHOLD = 0.80   # SequenceMatcher ratio on normalized text


def normalize(text: str) -> str:
    text = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def gather(workdirs: list[Path]) -> list[dict]:
    """Collect every commercial segment with its transcript text."""
    from .transcribe import text_between

    items = []
    for wd in workdirs:
        segs = json.loads((wd / "segments.json").read_text())
        transcript = json.loads((wd / "transcript.json").read_text())
        for s in segs:
            if s.get("label") != "commercial":
                continue
            text = normalize(text_between(transcript, s["start"], s["end"]))
            items.append({
                "workdir": str(wd),
                "recording": wd.stem.replace(".grab", ""),
                "break": s.get("break"),
                "spot": s.get("spot"),
                "start": s["start"],
                "end": s["end"],
                "duration": s.get("duration"),
                "text": text,
                "words": len(text.split()),
            })
    return items


def find_groups(items: list[dict], threshold: float = SIM_THRESHOLD) -> list[list[int]]:
    """Group indexes of near-identical transcripts (union-find over pairs)."""
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        parent[find(a)] = find(b)

    comparable = [i for i, it in enumerate(items) if it["words"] >= MIN_WORDS]
    for x, i in enumerate(comparable):
        for j in comparable[x + 1:]:
            a, b = items[i], items[j]
            # cheap length gate before the quadratic matcher
            if min(a["words"], b["words"]) / max(a["words"], b["words"]) < 0.5:
                continue
            if SequenceMatcher(None, a["text"], b["text"]).ratio() >= threshold:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in comparable:
        groups.setdefault(find(i), []).append(i)
    def order(g):
        # keeper: archive members first (already published); otherwise the
        # FIRST airing, unless a later one is clearly more complete (>10% more words)
        top = max(items[i]["words"] for i in g)
        return sorted(g, key=lambda i: (not items[i].get("archive"),
                                        items[i]["words"] < 0.9 * top,
                                        items[i]["start"]))
    return [order(g) for g in groups.values() if len(g) > 1]


def _label(it: dict) -> str:
    if it.get("archive"):
        return f"archive {it['path']}"
    return f"{it['recording']} break{it['break']:02d}/spot{it['spot']:02d}"


def report(items: list[dict], groups: list[list[int]]) -> str:
    lines = ["# Duplicate report", ""]
    if not groups:
        lines.append("No duplicates found.")
    archive_only = [g for g in groups if all(items[i].get("archive") for i in g)]
    live = [g for g in groups if g not in archive_only]
    for n, g in enumerate(live, 1):
        keeper = items[g[0]]
        lines.append(f"## Group {n} — keep `{_label(keeper)}`")
        for i in g:
            it = items[i]
            tag = "KEEP" if i == g[0] else "DUP "
            lines.append(f"- {tag} {_label(it)} ({it['duration']:.0f}s): {it['text'][:110]}…")
        lines.append("")
    if archive_only:
        lines += ["# Already-filed duplicates (archive vs archive — audit, not new work)", ""]
        for g in archive_only:
            for i in g:
                lines.append(f"- {_label(items[i])} ({items[i]['duration']:.0f}s)")
            lines.append("")
    return "\n".join(lines)


def apply_labels(items: list[dict], groups: list[list[int]]) -> dict[str, int]:
    """Mark every non-keeper new-recording segment `duplicate` in its segments.json."""
    from .propose import load_segments, save_segments

    changed: dict[str, int] = {}
    per_wd: dict[str, dict[tuple, str]] = {}
    for g in groups:
        keeper = items[g[0]]
        for i in g[1:]:
            it = items[i]
            if it.get("archive"):
                continue
            per_wd.setdefault(it["workdir"], {})[(it["break"], it["spot"])] = _label(keeper)
    for wd, marks in per_wd.items():
        path = Path(wd) / "segments.json"
        segs = load_segments(path)
        n = 0
        for s in segs:
            key = (s.get("break"), s.get("spot"))
            if key in marks and s.get("label") == "commercial":
                s["label"] = "duplicate"
                s["dup_of"] = marks[key]
                n += 1
        if n:
            save_segments(segs, path)
        changed[wd] = n
    return changed
