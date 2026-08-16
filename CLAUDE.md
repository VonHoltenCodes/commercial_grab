# commercial_grab — agent playbook

This file is for an AI coding agent (Claude Code or similar) driving the
pipeline. The tool automates detection, transcription, and cutting; **the
review between `propose` and `cut` is your job**, and it is where the quality
comes from. Everything below was learned on real recovered broadcasts.

## Pipeline

```sh
python3 -m commercial_grab doctor     RECORDING   # ALWAYS first
python3 -m commercial_grab scan       RECORDING
python3 -m commercial_grab transcribe RECORDING   # GPU; run concurrently with scan
python3 -m commercial_grab captions   RECORDING   # Line 21 CC — run it; it's cheap
python3 -m commercial_grab propose    RECORDING
# >>> YOUR REVIEW PASS (below) <<<
python3 -m commercial_grab cut        RECORDING --precise
python3 -m commercial_grab dedupe     A.grab B.grab …
```

Always try `captions` before reviewing: recordings that passed through a DVD
recorder usually kept their EIA-608 captions, and even h264 re-encodes can
carry them (A53). CC text is verbatim — trust it over ASR for brand names
and product identification ("Heilig-Meyers", not "Highly Myers"). Trust ASR
word timestamps over CC cue timing for boundary work: captions lag or lead
the audio by seconds. When both exist, `propose` prints `ASR:` and `CC:`
lines per block.

`scan` (ffmpeg decode) and `transcribe` (GPU compute) can run in parallel.
All stage outputs land in `<video>.grab/` and are resumable.

## doctor first, always

If `doctor` reports a bogus duration or a fragmented container, **fix the file
before anything else** using the exact command it prints. A fragmented
container will OOM ffmpeg during `cut --precise` (observed: 22 GB RSS,
SIGKILL, and one full system freeze). Both fixes are lossless and take
seconds. Keep the broken original as `*.bak`.

## The review pass

`propose` writes `breaks.md`: every block with timestamps, duration, heuristic
label, and a transcript excerpt. Read the whole file. You are checking for
five specific failure modes:

1. **Fake spots at the head/tail.** Movie title sequences and credits chop
   into 3–10 s "commercials" (black between title cards, no speech). Verify
   with a frame grab; relabel the whole run as `show`.
2. **Breaks that start inside a "show" block.** Promos often slam-cut from
   program with no black frame. Symptom: a show block whose excerpt *ends* in
   ad copy. Find the true boundary (word timestamps + frames) and split.
3. **Glued ads.** Back-to-back spots with no black between them stay in one
   block (symptom: a 45–90 s block whose excerpt clearly changes product
   mid-stream). Split — see boundary verification below.
4. **Shattered ads.** Montage ads with black flashes between scenes fragment
   into 1–5 s shards (symptom: consecutive tiny blocks whose excerpts
   continue one another). Merge them into one spot.
5. **Bumpers and idents.** 3–10 s network bumpers ("...will return in a
   moment") are real broadcast artifacts — keep them as commercials, labeled
   as bumpers in your catalog.

Sanity check that confirms you got it right: **real spots come out at
standard lengths** (10/15/30/45/60 s). If your splits land on those numbers,
they're correct. A 33 s "spot" usually contains a 30 s ad plus bleed.

### Verifying a boundary (three independent signals)

For every split or moved boundary, use at least two of:

1. **Word timestamps** — find the last word of ad A and first word of ad B in
   `transcript.json`; the gap between them brackets the cut.
   Whisper drift warning: in music-heavy or sparse-speech stretches, word
   timestamps can drift several seconds. Frames are ground truth; words are
   hints.
2. **Scene detection** in a narrow window:
   `ffmpeg -ss A -to B -i src -vf "select='gt(scene,0.12)',metadata=print" -an -f null -`
   A strong scene score (>0.4) inside the word gap is the cut. Fades produce
   NO scene event — fall back to the word-gap midpoint.
3. **Frame grabs** on both sides of the candidate cut:
   `ffmpeg -ss T -i src -frames:v 1 out.jpg`
   Look at them. End cards linger 1–3 s after the last spoken word — cutting
   at the last word routinely clips the end card into the next ad.

Then edit `segments.json` directly (start/end/label per block; `duration`,
`break`, `spot` get recomputed — keep the recompute snippet from your edit
script) and run `cut`.

## Dedupe policy

One archived clip per unique commercial. After cutting, run `dedupe` across
all related workdirs and review `dedupe_report.md` before acting:

- **Keep the first airing** unless a later one is more complete (e.g. the
  first is missing its opening seconds).
- **False positive to watch:** a music/no-speech ad whose transcript only
  caught bumper bleed will group with bumpers. Rescue it.
- **Not duplicates:** different edits of the same campaign (different intro,
  different length cutdown). Keep both.
- Mark redundant segments `"label": "duplicate"` in `segments.json` — `cut`
  skips them and spot numbering keeps its gaps, which preserves each clip's
  true position in the broadcast.
- Near-misses land just under the 0.80 threshold when whisper hears the same
  ad slightly differently; if the report shows a suspicious singleton you
  remember seeing twice, compare its transcript manually.

## Dating the broadcast

The ads date the tape better than any label. Look for: theatrical trailers
("now playing" / release dates), "coming to [network]" premiere dates, sports
schedules (a named matchup pins an exact weekend), seasonal campaigns, and
promos for the *next* program. State the evidence in your catalog. Distrust
handwritten/inferred years on the source media — verify against content.

## Deliverables per recording

1. `catalog.md` in the workdir: broadcast identification (network, date,
   evidence), then one table per break — spot number, length, product/brand
   identification. Mark unidentifiable products honestly and note dupes with
   a pointer to the kept clip.
2. Clips via `cut --precise` (libx264 CRF 18) for distribution; keep the
   `-c copy` lossless set as archival master if disk allows.

## Environment notes

- faster-whisper `large-v3` on an 8 GB GPU handles a 2 h broadcast in ~10 min.
  Run ONE transcription at a time.
- Noisy VHS audio defeats silence detection (`silencedetect` finds nothing at
  -35 dB). Retry with `--silence-db -25 --silence-dur 0.2`; if silence still
  barely overlaps black events, black-only candidates segment fine.
- `cut` stream-copy mode snaps backward to keyframes: clips start up to a few
  seconds early but never lose content. `--precise` re-encodes frame-exact.
