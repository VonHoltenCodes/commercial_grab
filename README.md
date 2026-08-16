# commercial_grab

Pull vintage commercials out of off-air broadcast recordings — locally, losslessly, no cloud APIs.

Point it at a capture of an old broadcast (VHS rip, DVR recovery, DVD remux) and it
finds the commercial breaks, labels every spot with a transcript excerpt, and
stream-copies each commercial out as its own clip.

## How it works

The design borrows the transcript-first architecture of
[browser-use/video-use](https://github.com/browser-use/video-use), rebuilt for
archival work: no re-encoding by default, no cloud transcription.

1. **`doctor`** — pre-flight container checks. Recovered sources (ddrescue'd
   DVDs, aging tapes) carry pathologies that break every later stage; run this
   first, every time.
2. **`scan`** — one ffmpeg pass runs `blackdetect` + `silencedetect`. Broadcasts
   cut to black between program and spots; black intervals that coincide with
   silence are high-confidence cut points.
3. **`transcribe`** — faster-whisper on the local GPU produces a word-timestamped
   transcript (`transcript.json` / `transcript.md`).
4. **`propose`** — cut points split the timeline into blocks. Blocks short enough
   to be a single spot (≤130 s by default) are labeled `commercial` and grouped
   into numbered breaks; longer blocks are `show`. Output: `segments.json` (the
   edit list) plus `breaks.md`, a review sheet with a transcript excerpt per
   block so a human — or an agent like Claude Code — can fix labels before
   cutting (see `CLAUDE.md` for the full agent review playbook).
5. **`cut`** — extracts clips per `segments.json`. Default is `-c copy`
   (lossless, keyframe-snapped); `--precise` re-encodes for frame-exact bounds.
6. **`dedupe`** — compares transcripts across recordings so repeat airings of
   the same spot yield one archived clip.

All stage outputs land in `<video>.grab/` next to the source, so every stage is
resumable and re-runnable independently.

## Install

```sh
pip install faster-whisper click   # plus ffmpeg on the system
git clone https://github.com/VonHoltenCodes/commercial_grab
cd commercial_grab
```

Requires an NVIDIA GPU + CUDA for transcription (`--device cpu` works, slowly).

## Use

```sh
python3 -m commercial_grab doctor     recording.mkv   # ALWAYS run first on recovered sources
python3 -m commercial_grab scan       recording.mkv
python3 -m commercial_grab transcribe recording.mkv
python3 -m commercial_grab propose    recording.mkv
# review recording.grab/breaks.md, edit recording.grab/segments.json if needed
python3 -m commercial_grab cut        recording.mkv            # commercials only
python3 -m commercial_grab cut       recording.mkv --only all  # everything
python3 -m commercial_grab dedupe    a.grab b.grab c.grab      # cross-recording repeats
```

Clips land in `recording.grab/clips/` named `break03_spot02_1.02.45.mkv`.

### doctor — check recovered sources first

ddrescue'd DVD/VHS captures carry container pathologies that break everything
downstream: a stray corrupt-PTS packet can inflate a 1.7-hour recording to a
"26-hour" container, and remuxes of non-monotonic-DTS streams get one Matroska
cluster per frame — encoding clips from such a file makes ffmpeg balloon to
20+ GB and get OOM-killed (it can freeze the whole machine). `doctor` detects
both and prints the exact fix (`-t <end> -c copy` trim / `mkvmerge` rebuild —
both lossless and fast).

### dedupe — one clip per commercial

Repeat airings of the same spot produce near-identical transcripts. `dedupe`
compares every commercial segment across the given workdirs (SequenceMatcher
on normalized transcript text, 0.80 threshold) and writes `dedupe_report.md`
grouping the repeats. Review the report — montage ads with sparse speech can
false-positive against bumpers, and different edits of the same campaign are
NOT duplicates — then mark redundant segments `"label": "duplicate"` in
`segments.json`; `cut` skips them and spot numbering keeps its gaps, so clip
names stay position-accurate to the broadcast.

### The review step

`propose`'s labels are heuristics — the intended workflow is that an agent
(or a patient human) reviews `breaks.md` against the transcript, pulls frames
at suspicious boundaries (`ffmpeg -ss T -frames:v 1`), and hand-edits
`segments.json` before cutting. Things the heuristics get wrong every time:
movie title sequences chop into fake "spots" (black between title cards);
back-to-back ads with no black between them stay glued (split via word-gap
timestamps + `select='gt(scene,0.12)'` scene detection); silent montage ads
fragment into 2-second shards (merge them). VHS-noisy audio may need
`scan --silence-db -25`; black-only candidates still segment fine.

### Tuning

- `scan --black-dur/--black-th/--silence-db` — detection thresholds. Noisy VHS
  sources may need `--black-th 0.15` and a hotter `--silence-db -30`.
- `propose --max-spot` — longest block still considered a single commercial
  (default 130 s covers 15/30/60/120 s spots with slop).
- `cut --pad 0.25` — pad clips if stream-copy keyframe snapping clips too tight.

Note on stream copy: `-c copy` cuts snap backward to the nearest keyframe, so a
clip can start a few seconds *early* (carrying the previous spot's tail) but
never late — no commercial content is ever lost. Use `--precise` when you need
frame-exact boundaries.

## Working with an AI agent

The review step was designed to be driven by a coding agent (Claude Code or
similar): the agent reads `breaks.md`, pulls frames at suspicious boundaries,
consults word timestamps, and edits `segments.json` before cutting. `CLAUDE.md`
in this repo is a ready-made playbook an agent can follow end to end —
including the boundary-verification techniques and every failure mode we've
hit on real recordings.

## License

GPL-3.0 — see [LICENSE](LICENSE).

## Provenance

Built on devbase1 for the VonHolten fleet's broadcast archiving projects.
