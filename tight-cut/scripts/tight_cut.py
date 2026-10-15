"""tight-cut: dead-space cut for talking-head clips — cut ONLY between sentences.

Every clip is trimmed to where speech actually starts and stops, and the dead air
between sentences is collapsed to --gap seconds. Pauses inside a sentence are never
touched. Nothing else (no fillers, no retakes, no audio processing).

How it decides:
  * faster-whisper (local) gives words + punctuation -> where sentences END.
    Its word timings are sloppy (often off by 100ms-2s), so they are used ONLY to
    locate sentence breaks, never to place a cut.
  * The cut edges come from the audio itself, in 10 ms frames:
      - a frame louder than --voice-db is speech;
      - dips <=30 ms inside a word are bridged (so a word isn't split);
      - a run whose extent above -38 dB is <80 ms is a click/lip smack, not a word;
      - speech edges then grow through soft tails (<= --tail) and onsets (<= --onset)
        while louder than --edge-db, so "-ting" endings survive but inhales don't.
  * A sentence break = previous word ends in . ? !  OR a pause >= --long-pause
    (whisper sometimes drops the period). Every silent run >=0.12 s inside that
    break is cut down to --gap. Leading/trailing silence is trimmed to --gap/2.

  * --verify re-transcribes the output and diffs it against the source (catches lost words).
  * Every run also writes <out-dir>/.qa/<name>_edges.jpg: one row per kept clip showing its
    first 0.3 s and last 0.6 s. Read it to make sure no clip ends on you reaching to stop
    the recording or starts on you pulling your hand back from pressing record — that
    motion is nearly silent, so the audio pass can't see it.

Usage:
  python tools/tight_cut.py ~/Downloads/A.MP4 ~/Downloads/B.MP4
  python tools/tight_cut.py clip.MP4 --gap 0.1
  python tools/tight_cut.py clip.MP4 --verify      # re-transcribe output, list any lost words

Output: finished videos/<YYYY-MM-DD>/<name>_tight.mp4 (today's date; --out-dir overrides) (same resolution + fps, x264 crf 18, aac 192k).
"""
import argparse, difflib, os, re, subprocess, sys, tempfile
from datetime import date
import numpy as np

SR, HOP = 16000, 0.01
MID_DB, CLICK, BRIDGE, MIN_CUT = -38.0, 0.08, 0.03, 0.12


def load_audio(src):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-ac", "1", "-ar", str(SR),
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def transcribe(model, audio):
    # pass samples, not a path: faster-whisper's own decoder breaks on PyAV >= 19
    segs, _ = model.transcribe(audio, language="en", word_timestamps=True)
    return [dict(start=x.start, end=x.end, text=x.word.strip()) for s in segs for x in s.words]


def runs(mask, value):
    """(start, end) frame indices of runs where mask == value."""
    out, i, n = [], 0, len(mask)
    while i < n:
        if mask[i] == value:
            j = i
            while j < n and mask[j] == value: j += 1
            out.append((i, j)); i = j
        else: i += 1
    return out


def speech_mask(audio, a):
    n = int(SR * HOP); fr = audio[:len(audio) // n * n].reshape(-1, n)
    db = 20 * np.log10(np.sqrt((fr ** 2).mean(1)) + 1e-9)
    v = db > a.voice_db; N = len(v)
    for i, j in runs(v, False):                       # bridge tiny dips inside a word
        if (j - i) * HOP <= BRIDGE and i > 0 and j < N: v[i:j] = True
    for i, j in runs(v, True):                        # drop clicks
        lo, hi = i, j
        while lo > 0 and db[lo - 1] > MID_DB and i - lo < 25: lo -= 1
        while hi < N and db[hi] > MID_DB and hi - j < 25: hi += 1
        if (hi - lo) * HOP < CLICK and i > 0 and j < N: v[i:j] = False
    core, tail, onset = v.copy(), int(a.tail / HOP), int(a.onset / HOP)
    for i, j in runs(core, True):                     # grow through soft tails / onsets
        for k in range(j, min(N, j + tail)):
            if db[k] > a.edge_db: v[k] = True
            else: break
        for k in range(i - 1, max(-1, i - 1 - onset), -1):
            if db[k] > a.edge_db: v[k] = True
            else: break
    return v


def plan(v, words, a):
    N = len(v); dur = N * HOP; G = a.gap
    quiet = [(i * HOP, j * HOP) for i, j in runs(v, False)]
    voiced = np.flatnonzero(v)
    first, last = voiced[0] * HOP, (voiced[-1] + 1) * HOP
    cuts = [(0, max(0, first - G / 2)), (min(dur, last + G / 2), dur)]
    for i in range(len(words) - 1):
        lo = words[i]["start"]; hi = max(words[i + 1]["end"], words[i + 1]["start"] + 0.2)
        inside = [(max(s, lo), min(e, hi)) for s, e in quiet if e > lo and s < hi]
        if not inside: continue
        longest = max(e - s for s, e in inside)
        if words[i]["text"][-1:] in ".?!" or longest >= a.long_pause:
            cuts += [(s + G / 2, e - G / 2) for s, e in inside if e - s >= max(MIN_CUT, G)]
    keep, t = [], 0.0
    for s, e in sorted(cuts):
        if s > t: keep.append((t, s))
        t = max(t, e)
    if t < dur: keep.append((t, dur))
    return keep, dur


def render(src, keep, out):
    fc = "".join(f"[0:v]trim={s:.3f}:{e:.3f},setpts=PTS-STARTPTS[v{i}];"
                 f"[0:a]atrim={s:.3f}:{e:.3f},asetpts=PTS-STARTPTS[a{i}];" for i, (s, e) in enumerate(keep))
    fc += "".join(f"[v{i}][a{i}]" for i in range(len(keep))) + f"concat=n={len(keep)}:v=1:a=1[v][a]"
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f: f.write(fc)
    try:
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src,
                        "-filter_complex_script", f.name, "-map", "[v]", "-map", "[a]",
                        "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out], check=True)
    finally: os.remove(f.name)


def edge_sheet(src, keep, path):
    """One row per kept clip: 3 frames from its head, 5 from its tail."""
    try:
        import io
        from PIL import Image, ImageDraw
    except ImportError:
        print("   (pip install pillow for the .qa edge sheet)"); return
    W, H = 90, 160
    cols = [("h", 0.0), ("h", 0.15), ("h", 0.3), ("t", -0.6), ("t", -0.45), ("t", -0.3), ("t", -0.15), ("t", -0.03)]
    sheet = Image.new("RGB", (40 + W * len(cols) + 10, H * len(keep)), "black"); d = ImageDraw.Draw(sheet)
    for r, (s, e) in enumerate(keep):
        d.text((2, H * r + H // 2), f"{r}", fill="yellow")
        for c, (kind, off) in enumerate(cols):
            t = max(0.0, (s if kind == "h" else e) + off)
            png = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", src, "-frames:v", "1",
                                  "-vf", f"scale={W}:{H}", "-f", "image2pipe", "-vcodec", "png", "-"],
                                 capture_output=True).stdout
            if png: sheet.paste(Image.open(io.BytesIO(png)), (40 + W * c + (10 if kind == "t" else 0), H * r))
    os.makedirs(os.path.dirname(path), exist_ok=True); sheet.save(path, quality=80)
    print(f"   edge sheet -> {path}  (left 3 = clip start, right 5 = clip end)")


def verify(model, words, out):
    norm = lambda L: [re.sub(r"[^a-z0-9]", "", t.lower()) for t in L]
    new = transcribe(model, load_audio(out))
    sm = difflib.SequenceMatcher(None, norm([w["text"] for w in words]), norm([w["text"] for w in new]))
    print(f"   verify: {len(words)} -> {len(new)} words, match {sm.ratio():.3f}")
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "equal":
            print(f"     {op}: {' '.join(w['text'] for w in words[i1:i2])!r} -> "
                  f"{' '.join(w['text'] for w in new[j1:j2])!r}")
    print("   (whisper rewording like 'want to'->'wanna' or a merged repeat is noise; a missing phrase is not)")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("videos", nargs="+")
    p.add_argument("--out-dir", default=os.path.join("finished videos", date.today().isoformat()),
                   help="default: finished videos/<today, YYYY-MM-DD>")
    p.add_argument("--gap", type=float, default=0.0, help="silence left between sentences (s)")
    p.add_argument("--voice-db", type=float, default=-32, help="louder than this = speech")
    p.add_argument("--edge-db", type=float, default=-41, help="soft word edges down to this are kept")
    p.add_argument("--tail", type=float, default=0.2, help="max soft-tail growth after a word (s)")
    p.add_argument("--onset", type=float, default=0.05, help="max soft-onset growth before a word (s)")
    p.add_argument("--long-pause", type=float, default=0.7, help="unpunctuated pause this long = sentence break")
    p.add_argument("--model", default="small", help="faster-whisper model")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verify", action="store_true", help="re-transcribe output and diff against the source")
    a = p.parse_args()
    from faster_whisper import WhisperModel
    model = WhisperModel(a.model, compute_type="int8")
    os.makedirs(a.out_dir, exist_ok=True)
    for src in a.videos:
        audio = load_audio(src)
        words = transcribe(model, audio)
        if not words: print(f"{src}: no speech found, skipped"); continue
        keep, dur = plan(speech_mask(audio, a), words, a)
        kept = sum(e - s for s, e in keep)
        out = os.path.join(a.out_dir, os.path.splitext(os.path.basename(src))[0] + "_tight.mp4")
        print(f"{os.path.basename(src)}: {dur:.2f}s -> {kept:.2f}s, removed {dur - kept:.2f}s, {len(keep)} clips")
        if a.dry_run: continue
        render(src, keep, out)
        print(f"   -> {out}")
        edge_sheet(src, keep, os.path.join(a.out_dir, ".qa", os.path.splitext(os.path.basename(src))[0] + "_edges.jpg"))
        if a.verify: verify(model, words, out)


if __name__ == "__main__":
    sys.exit(main())
