"""
Subtitle (.srt) generation for the finished audiobook.

The timing comes straight from the narrator: as Chatterbox renders each chapter
it writes a `<chapter>.cues.json` sidecar listing every spoken chunk with its
exact start/end (in milliseconds) inside that chapter. Here we offset those by
each chapter's start time in the combined audiobook and split long chunks into
short, readable cues. The result lines up with the MP3 to the chunk, because the
times are measured from the actual generated audio — not estimated.

If a chapter has no sidecar (e.g. it was made with a cloud TTS engine, or by an
older version), that chapter is simply skipped; everything else still lines up.
"""

import json
import os
import re

_WORDS_PER_CUE = 10
_SENTENCE_END = re.compile(r"[.!?][\"')\u201d\u2019]?$")


def _fmt_ts(ms: float) -> str:
    ms = max(0, int(round(ms)))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _cue_chunks(text: str):
    """Split a spoken chunk into short on-screen cues (~10 words), breaking
    early at sentence ends so cues read naturally."""
    words = (text or "").split()
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= _WORDS_PER_CUE or _SENTENCE_END.search(w):
            if len(cur) >= 4 or _SENTENCE_END.search(w):
                chunks.append(" ".join(cur))
                cur = []
    if cur:
        if chunks and len(cur) < 3:
            chunks[-1] += " " + " ".join(cur)
        else:
            chunks.append(" ".join(cur))
    return chunks


def _wrap(line: str, width: int = 42) -> str:
    if len(line) <= width:
        return line
    words = line.split()
    a, b, n = [], [], 0
    for w in words:
        if n + len(w) + 1 <= width and not b:
            a.append(w); n += len(w) + 1
        else:
            b.append(w)
    out = " ".join(a)
    if b:
        out += "\n" + " ".join(b)
    return out


def _emit_window(out, idx, a, b, text):
    """Split `text` across the time window [a, b] (ms) into short cues by word
    count, appending SRT blocks to `out`. Returns the next cue index."""
    text = (text or "").strip()
    if not text or b <= a:
        return idx
    chunks = _cue_chunks(text)
    if not chunks:
        return idx
    weights = [max(1, len(c.split())) for c in chunks]
    total = sum(weights)
    span = b - a
    t = a
    for c, wt in zip(chunks, weights):
        dur = span * (wt / total)
        start, end = t, t + dur
        t = end
        out.append(f"{idx}\n{_fmt_ts(start)} --> {_fmt_ts(end)}\n{_wrap(c)}\n")
        idx += 1
    return idx


def build_srt(chapters) -> str:
    """chapters: list of dicts {path, start_ms}. Reads each chapter's
    .cues.json sidecar (written by the narrator) and produces the full .srt.
    Chapters without a sidecar are skipped."""
    out = []
    idx = 1
    for ch in chapters:
        base = os.path.splitext(ch["path"])[0]
        cues_path = base + ".cues.json"
        if not os.path.exists(cues_path):
            continue
        try:
            with open(cues_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        off = float(ch.get("start_ms", 0))
        for cue in data.get("cues", []):
            a = off + float(cue.get("start_ms", 0))
            b = off + float(cue.get("end_ms", 0))
            idx = _emit_window(out, idx, a, b, cue.get("text", ""))
    return "\n".join(out)


def write_srt(chapters, out_path: str):
    """Build the .srt and write it. Returns the basename if anything was
    written, else None (e.g. no cue sidecars present)."""
    srt = build_srt(chapters)
    if not srt.strip():
        return None
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(srt)
    return os.path.basename(out_path)
