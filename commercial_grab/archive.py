"""Archive-wide transcript index — the memory that makes dedupe global.

The filed archive (`~/Videos/commercials/<Brand>/*.mkv|mp4`) is the ground
truth of what's already on the channel. This transcribes every filed clip
once (cached in `.archive_index.json` at the archive root, keyed by relative
path and invalidated on size/mtime change) so `dedupe --archive` can compare a
freshly proposed recording against everything ever filed, not just against
its sibling workdirs.
"""

import json
import time
from pathlib import Path

from .dedupe import normalize

INDEX_NAME = ".archive_index.json"
CLIP_EXT = {".mkv", ".mp4"}


def index_path(root: Path) -> Path:
    return root / INDEX_NAME


def load_index(root: Path) -> dict:
    p = index_path(root)
    return json.loads(p.read_text()) if p.exists() else {"clips": {}}


def save_index(root: Path, index: dict):
    p = index_path(root)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(index, indent=1))
    tmp.replace(p)


def archive_clips(root: Path):
    """Filed clips only: brand folders, never the `_*` staging dirs."""
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith((".", "_")):
            continue
        for f in sorted(d.rglob("*")):
            if f.is_file() and f.suffix.lower() in CLIP_EXT:
                yield f


def stale(entry: dict | None, f: Path) -> bool:
    if not entry:
        return True
    st = f.stat()
    return entry.get("size") != st.st_size or abs(entry.get("mtime", 0) - st.st_mtime) > 1


def build_index(root: Path, model_name="large-v3", device="cuda", compute_type="float16",
                progress=print) -> dict:
    """Transcribe clips missing from (or changed since) the index. Incremental;
    saves every few clips so an interrupted run resumes where it stopped."""
    index = load_index(root)
    clips = index["clips"]
    todo = [f for f in archive_clips(root) if stale(clips.get(str(f.relative_to(root))), f)]
    # drop entries whose file is gone
    present = {str(f.relative_to(root)) for f in archive_clips(root)}
    for k in [k for k in clips if k not in present]:
        del clips[k]
    if not todo:
        save_index(root, index)
        return index

    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    t0 = time.time()
    for n, f in enumerate(todo, 1):
        segs, info = model.transcribe(str(f), language="en", vad_filter=True,
                                      vad_parameters={"min_silence_duration_ms": 500})
        text = normalize(" ".join(s.text for s in segs))
        st = f.stat()
        clips[str(f.relative_to(root))] = {
            "text": text, "words": len(text.split()),
            "duration": round(info.duration, 3),
            "size": st.st_size, "mtime": st.st_mtime,
        }
        progress(f"[{n}/{len(todo)}] {f.relative_to(root)} ({len(text.split())} words)")
        if n % 5 == 0:
            save_index(root, index)
    index["model"] = model_name
    index["updated"] = time.strftime("%Y-%m-%d %H:%M")
    save_index(root, index)
    progress(f"Indexed {len(todo)} clips in {time.time()-t0:.0f}s — {len(clips)} total.")
    return index


def archive_items(root: Path) -> list[dict]:
    """Index entries in dedupe's item shape (recording='archive')."""
    items = []
    for rel, e in load_index(root)["clips"].items():
        items.append({
            "workdir": str(root), "recording": "archive", "archive": True,
            "path": rel, "break": None, "spot": None,
            "start": 0.0, "end": e["duration"], "duration": e["duration"],
            "text": e["text"], "words": e["words"],
        })
    return items
