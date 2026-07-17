"""
Audiobook Converter — local Flask app.

Run:  python -m app.server   (from the project root)
Then open http://127.0.0.1:5000

Flow:
  1. Upload .epub            -> POST /upload
  2. Review / edit chapters  -> in the browser (rename, merge, re-split)
  3. Pick engine + voice     -> POST /synthesize  (one mp3 per chapter)
  4. Combine + make video    -> POST /assemble
"""

import os
import json
import uuid
import glob
import threading
import hashlib
import re


def _silence_progress_bars():
    """Stop the TTS model's progress bars from spilling into the console.

    Chatterbox (via tqdm) prints a per-chapter 'iteration' progress bar to
    stderr, and HuggingFace prints model-download bars — both purely cosmetic.
    In the console they scroll endlessly and look like errors. This silences
    them everywhere they could appear in the MAIN process (Preview, Estimate,
    and in-process narration); the recycled worker already routes its output to
    a log file. Must run before torch/transformers/chatterbox are imported, so
    the environment flags take effect and tqdm is patched up front.
    """
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("TQDM_DISABLE", "1")
    try:
        # Force every tqdm bar to be disabled, regardless of how the calling
        # library constructs it (setting the kwarg overrides any value it
        # passes). Patching the base class covers tqdm, tqdm.auto and tqdm.std.
        import tqdm.std as _tqs
        _orig_init = _tqs.tqdm.__init__

        def _quiet_init(self, *a, **k):
            k["disable"] = True
            _orig_init(self, *a, **k)

        _tqs.tqdm.__init__ = _quiet_init
    except Exception:
        pass


_silence_progress_bars()

from flask import (Flask, request, jsonify, render_template,
                   send_from_directory, abort, Response)
from werkzeug.utils import secure_filename

from .epub_parser import parse_epub, Chapter
from .document_parser import parse_document, SUPPORTED_EXTENSIONS as SUPPORTED_DOC_EXTENSIONS
from .tts import get_engine, ENGINE_CATALOG
from .assembler import (combine_chapters, build_youtube_timestamps,
                        build_video, ensure_ffmpeg, build_drive_chapter_page)
from .subtitles import write_srt as write_subtitles

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOADS = os.path.join(BASE, "uploads")
OUTPUT = os.path.join(BASE, "output")
os.makedirs(UPLOADS, exist_ok=True)
os.makedirs(OUTPUT, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200 MB

# In-memory project store. For a single-user local app this is fine; swap for
# SQLite if you want persistence across restarts.
PROJECTS = {}


def _fmt_secs(sec):
    """Human-friendly duration: '2h 14m 30s', '8m 12s', '45s'."""
    if sec is None:
        return "—"
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _format_report(r):
    """Build the plain-text status report saved to the output folder."""
    import datetime
    lines = []
    lines.append("PARROTY — STATUS REPORT")
    lines.append("=" * 40)
    lines.append(f"Title       : {r.get('title') or '—'}")
    if r.get("author"):
        lines.append(f"Author      : {r['author']}")
    lines.append(f"Finished    : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append(f"Chapters    : {r.get('chapters')}")
    lines.append(f"Characters  : {r.get('characters'):,}" if r.get("characters")
                 else "Characters  : —")
    if r.get("audio_length_seconds"):
        lines.append(f"Audiobook   : {_fmt_secs(r.get('audio_length_seconds'))} long")
    eng = r.get("engine") or "—"
    if r.get("variant"):
        eng += f" ({r['variant']})"
    lines.append(f"Engine      : {eng}")
    if r.get("device"):
        lines.append(f"Device      : {r['device'].upper()}")
    lines.append("")
    lines.append("TIMINGS")
    lines.append("-" * 40)
    lines.append(f"Narration   : {_fmt_secs(r.get('narrate_seconds'))}")
    if r.get("combine_seconds") is not None:
        lines.append(f"Combining   : {_fmt_secs(r.get('combine_seconds'))}")
    if r.get("video_seconds") is not None:
        lines.append(f"Video (MP4) : {_fmt_secs(r.get('video_seconds'))}")
    lines.append(f"Total       : {_fmt_secs(r.get('total_seconds'))}")
    # Throughput hint, useful for estimating future books.
    chars = r.get("characters")
    nsec = r.get("narrate_seconds")
    if chars and nsec:
        cps = chars / nsec
        lines.append("")
        lines.append(f"Speed       : {cps:.0f} characters/sec during narration")
    lines.append("")
    return "\n".join(lines)


def _enough_commit_for_reload(needed_gb=7.0, ram_headroom_gb=3.0):
    """Return True only if there's enough memory to safely absorb the reload
    SPIKE. Reloading is meant to FREE memory, but it briefly spikes higher
    first: a fresh model is loaded while the old one's pages haven't been fully
    reclaimed by the OS yet. So we must reserve room for that spike before
    reloading — otherwise the very act of freeing memory triggers the crash.

    We check TWO things, and require both:
      1. Commit headroom (RAM + page file) > needed_gb — covers os error 1455
         / "paging file too small" and a hard process kill.
      2. Physical-RAM headroom > ram_headroom_gb — covers "bad allocation",
         which can fail when free *physical* RAM is exhausted even if the page
         file still has room (a large contiguous allocation can't be satisfied).

    If either is too tight, we skip the reload and keep using the current model
    (per-chapter streaming already keeps memory flat). Returns True only if we
    genuinely can't measure, so behavior is unchanged on unmeasurable systems."""
    try:
        import psutil
        vm = psutil.virtual_memory()
        sm = psutil.swap_memory()
        free_commit = vm.available + (sm.total - sm.used)
        enough_commit = free_commit > needed_gb * (1024 ** 3)
        enough_ram = vm.available > ram_headroom_gb * (1024 ** 3)
        return enough_commit and enough_ram
    except Exception:
        pass
    try:
        if os.name == "nt":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            enough_commit = stat.ullAvailPageFile > needed_gb * (1024 ** 3)
            enough_ram = stat.ullAvailPhys > ram_headroom_gb * (1024 ** 3)
            return enough_commit and enough_ram
    except Exception:
        pass
    return True


def _memory_low(threshold_gb=2.0):
    """Return True if available system RAM is below threshold_gb. Used to
    trigger a model reload before memory runs out. Uses psutil if available;
    otherwise tries the OS directly, and returns False if it can't tell (so it
    never falsely blocks work)."""
    try:
        import psutil
        return psutil.virtual_memory().available < threshold_gb * (1024 ** 3)
    except Exception:
        pass
    # Fallback for Windows without psutil: query via ctypes.
    try:
        if os.name == "nt":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullAvailPhys < threshold_gb * (1024 ** 3)
    except Exception:
        pass
    return False


def _is_fatal_cuda_error(msg):
    """True if this error means the CUDA context is dead and retrying in this
    same process is pointless.

    A device-side assert (an out-of-range index inside a GPU kernel) poisons the
    CUDA context: every later CUDA call in the process fails too, no matter how
    much memory is freed. It must be handled by restarting the process, not by
    retrying in place — unlike an out-of-memory error, which a retry genuinely
    can fix. Telling the two apart stops us wasting a retry and, worse, giving
    "close other apps to free RAM" advice for a problem that has nothing to do
    with RAM.
    """
    m = (msg or "").lower()
    return ("device-side assert" in m
            or "cuda error" in m
            or "cudaerrorassert" in m
            or "an illegal memory access" in m
            or "unspecified launch failure" in m
            or "cuda kernel errors" in m)


def _reclaim_memory():
    """Release memory back to the OS between chapters. Runs Python GC, clears
    the CUDA cache if a GPU is in use, and (on Linux/glibc) trims the malloc
    arena so freed RAM actually returns to the system. Best-effort and safe to
    call anywhere."""
    import gc
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        pass
    # On Linux, ask glibc to return freed heap to the OS (no-op elsewhere).
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


def _mem_stats():
    """Return (available_gb, total_gb, used_percent) for system RAM, or None if
    it can't be measured. Cheap enough to poll frequently during narration."""
    try:
        import psutil
        vm = psutil.virtual_memory()
        return (vm.available / (1024 ** 3), vm.total / (1024 ** 3),
                float(vm.percent))
    except Exception:
        pass
    try:
        if os.name == "nt":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            s = MEMORYSTATUSEX()
            s.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
            return (s.ullAvailPhys / (1024 ** 3),
                    s.ullTotalPhys / (1024 ** 3), float(s.dwMemoryLoad))
    except Exception:
        pass
    return None


def _reload_safety(needed_commit_gb=7.0, ram_headroom_gb=3.0):
    """Decide whether it's safe to reload the model right now, and if not, give a
    plain-language reason (with numbers). A reload briefly needs a chunk of free
    PHYSICAL RAM — for a moment the old and new model coexist — and a large
    contiguous RAM allocation can fail even when the page file has tons of room.
    So a big page file does NOT, on its own, make a reload safe; free physical
    RAM is usually the binding constraint. Returns (ok, reason)."""
    ms = _mem_stats()  # (avail_gb, total_gb, percent)
    free_commit_gb = None
    try:
        import psutil
        sm = psutil.swap_memory()
        if ms is not None:
            free_commit_gb = ms[0] + (sm.total - sm.used) / (1024 ** 3)
    except Exception:
        free_commit_gb = None
    if ms is None:
        return (True, "")  # can't measure → don't block (behaviour unchanged)
    if ms[0] <= ram_headroom_gb:
        return (False, f"{ms[0]:.1f} GB physical RAM free; a reload needs about "
                       f"{ram_headroom_gb:.0f} GB of real-RAM headroom for its "
                       f"brief spike (a big page file doesn't help here)")
    if free_commit_gb is not None and free_commit_gb <= needed_commit_gb:
        return (False, f"{free_commit_gb:.1f} GB commit headroom (RAM + page "
                       f"file); a reload needs about {needed_commit_gb:.0f} GB")
    return (True, "")


def _job_dir(job_id):
    d = os.path.join(OUTPUT, job_id)
    os.makedirs(d, exist_ok=True)
    return d


@app.route("/")
def index():
    return render_template("index.html",
                           catalog=ENGINE_CATALOG,
                           ffmpeg_ok=ensure_ffmpeg())


@app.route("/engines")
def engines():
    return jsonify(ENGINE_CATALOG)


@app.route("/devices")
def devices():
    """Report which compute devices Chatterbox can use, plus GPU diagnostics."""
    try:
        from .converters.chatterbox_engine import detect_devices, gpu_diagnostics
        return jsonify({"devices": detect_devices(),
                        "gpu": gpu_diagnostics()})
    except Exception:
        # Chatterbox/torch not installed — only CPU/auto are meaningful.
        return jsonify({"devices": [
            {"id": "auto", "label": "Auto (use GPU if available)", "available": True},
            {"id": "cpu", "label": "CPU only (slow)", "available": True},
        ], "gpu": {"cuda_available": False,
                   "message": "PyTorch not installed yet.",
                   "fix": ""}})


def _log_book_error(job_dir, message):
    """Append a timestamped line to this book's own error log (errors.log in the
    job folder). Gives a per-book record of any chapter failures, truncated
    files, or reload problems, so issues can be diagnosed after the fact.
    Best-effort: never raises."""
    try:
        import datetime
        line = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"
        with open(os.path.join(job_dir, "errors.log"), "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _slugify(text, maxlen=40):
    """Make a filesystem-safe slug from a title (letters/digits/dashes)."""
    import re as _re
    s = _re.sub(r"[^\w\s-]", "", (text or "").strip().lower())
    s = _re.sub(r"[\s_-]+", "-", s).strip("-")
    return s[:maxlen] or "book"


def _output_basename(title, maxlen=40):
    """Build a short, descriptive base for output filenames:
    <book-slug>-<YYYYMMDD-HHMM>. Used for audiobook/MP4 files."""
    import datetime
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    return f"{_slugify(title, maxlen)}-{stamp}"


# ---- Chapter identity + narration ledger --------------------------------
#
# Resume used to recognise an already-narrated chapter purely by its numeric
# position (chapter_005_*.mp3 == "chapter 5 is done"). That breaks the moment
# the chapter list is reordered or a chapter is deleted: stale files match the
# wrong position, so chapters get re-narrated and duplicated. Instead we give
# every chapter a STABLE identity derived from its text, and keep a small
# ledger mapping that identity -> the file we narrated for it. Resume then asks
# "have I narrated THIS chapter?" by identity, which survives reordering,
# deletion of other chapters, renames, and server restarts.

def _chapter_cid(text):
    """A stable short id for a chapter, derived from its text. Identical text
    always yields the same id; whitespace/casing differences are ignored."""
    norm = re.sub(r"\s+", " ", (text or "")).strip().lower()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


def _ensure_cids(chapters):
    """Make sure every chapter dict has a 'cid'. Mutates in place and returns
    the list. (Chapters with identical text intentionally share a cid — they'd
    narrate to identical audio, so reusing one file for both is correct.)"""
    for c in chapters:
        if not c.get("cid"):
            c["cid"] = _chapter_cid(c.get("text", ""))
    return chapters


def _ledger_path(jd):
    return os.path.join(jd, "narration_state.json")


def _load_ledger(jd):
    """Return the cid -> filename map for a job (empty dict if none)."""
    p = _ledger_path(jd)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("files"), dict):
                return d["files"]
        except Exception:
            pass
    return {}


def _save_ledger(jd, files):
    try:
        with open(_ledger_path(jd), "w", encoding="utf-8") as f:
            json.dump({"version": 1, "files": files}, f,
                      ensure_ascii=False, indent=2)
    except Exception:
        pass


def _ledger_file_for(jd, files, cid):
    """Absolute path of the narrated file recorded for this cid, but only if it
    still exists on disk and is non-trivial; otherwise None."""
    name = files.get(cid)
    if not name:
        return None
    p = os.path.join(jd, name)
    if os.path.exists(p) and os.path.getsize(p) > 1024:
        return p
    return None


def _migrate_ledger(jd, chapters):
    """Build (and persist) the cid -> file map for a job that doesn't have one
    yet, by matching existing chapter_NNN_<slug> files to the current chapter
    list. Title slug is the strong signal; a slug-less legacy file is matched by
    its position. Files that match nothing are left untouched on disk (we never
    auto-delete) and simply aren't reused. Returns the map."""
    _ensure_cids(chapters)
    files = _load_ledger(jd)
    if files:
        return files

    import glob as _g
    existing = (_g.glob(os.path.join(jd, "chapter_*.wav")) +
                _g.glob(os.path.join(jd, "chapter_*.mp3")))
    by_slug = {}      # slug -> [(index, basename)]
    by_index = {}     # index -> basename  (slug-less legacy files only)
    for fp in existing:
        try:
            if os.path.getsize(fp) <= 1024:
                continue
        except OSError:
            continue
        base = os.path.basename(fp)
        m = re.match(r"chapter_(\d+)(?:_(.*))?\.(?:wav|mp3)$", base)
        if not m:
            continue
        idx = int(m.group(1))
        slug = (m.group(2) or "").lower()
        if slug:
            by_slug.setdefault(slug, []).append((idx, base))
        else:
            by_index[idx] = base

    claimed = set()
    # Pass 1: match each chapter to a file whose slug equals its title slug.
    for pos, c in enumerate(chapters, start=1):
        cid = c["cid"]
        if cid in files:
            continue
        want = _slugify(c.get("title", ""))
        cands = [(i, b) for (i, b) in by_slug.get(want, []) if b not in claimed]
        if cands:
            # Prefer the candidate sitting at this position, else the first.
            i, b = next((t for t in cands if t[0] == pos), cands[0])
            files[cid] = b
            claimed.add(b)
    # Pass 2: slug-less legacy files (chapter_NNN.ext) — match by position only.
    for pos, c in enumerate(chapters, start=1):
        cid = c["cid"]
        if cid in files:
            continue
        b = by_index.get(pos)
        if b and b not in claimed:
            files[cid] = b
            claimed.add(b)

    _save_ledger(jd, files)
    return files


def _bindable_chapters(job_id):
    """The chapters that can be bound, in the CURRENT list's order, each mapped
    to its narrated audio via the ledger. Chapters not yet narrated are skipped.
    Each item carries its 1-based position in the FULL chapter list as 'index'
    so selection/redo stay consistent across the app. Falls back to filename
    order for very old jobs that have audio but no saved chapter list."""
    jd = os.path.join(OUTPUT, job_id)
    chapters = None
    proj = PROJECTS.get(job_id)
    if proj and proj.get("chapters"):
        chapters = proj["chapters"]
    else:
        meta_path = os.path.join(jd, "meta.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, encoding="utf-8") as mf:
                    chapters = json.load(mf).get("chapters")
            except Exception:
                chapters = None

    if chapters:
        _ensure_cids(chapters)
        ledger = _migrate_ledger(jd, chapters)
        out = []
        for pos, c in enumerate(chapters, start=1):
            fp = _ledger_file_for(jd, ledger, c["cid"])
            if fp:
                out.append({"index": pos, "title": c["title"], "file": fp,
                            "cid": c["cid"], "chars": len((c.get("text") or ""))})
        if out:
            return out

    # Legacy fallback: no chapter list available — use filename order.
    import glob as _g
    files = (_g.glob(os.path.join(jd, "chapter_*.wav")) or
             _g.glob(os.path.join(jd, "chapter_*.mp3")))
    files = _natural_chapter_sort(files)
    return [{"index": i + 1, "title": f"Chapter {i + 1}", "file": fp,
             "cid": None, "chars": 0} for i, fp in enumerate(files)]


def _persist_chapters(job_id):
    """Write the current in-memory chapter list back to meta.json so a later
    Resume (after a restart) sees exactly the list the user last had — order,
    titles, edits and all. Without this, edits live only in memory and a restart
    silently reverts to the original parse, desyncing the list from the files on
    disk (the cause of chapters appearing to re-narrate)."""
    proj = PROJECTS.get(job_id)
    if not proj or not proj.get("chapters"):
        return
    jd = os.path.join(OUTPUT, job_id)
    if not os.path.isdir(jd):
        return
    _ensure_cids(proj["chapters"])
    meta_path = os.path.join(jd, "meta.json")
    meta = {}
    if os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as mf:
                meta = json.load(mf)
        except Exception:
            meta = {}
    meta["chapter_titles"] = [c["title"] for c in proj["chapters"]]
    meta["chapters"] = [{"title": c["title"], "text": c.get("text", ""),
                         "cid": c["cid"]} for c in proj["chapters"]]
    try:
        with open(meta_path, "w", encoding="utf-8") as mf:
            json.dump(meta, mf, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _youtube_basename(title, maxlen=40):
    """Build the YouTube chapters filename base:
    youtube-chapters-<book-slug>-<YYYYMMDD-HHMM>."""
    import datetime
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    return f"youtube-chapters-{_slugify(title, maxlen)}-{stamp}"


@app.route("/upload", methods=["POST"])
def upload():
    # Accept the file under "epub" (legacy field name) or "file".
    f = request.files.get("epub") or request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "Please choose a file to upload."}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    allowed = {".epub"} | SUPPORTED_DOC_EXTENSIONS
    if ext not in allowed:
        nice = "EPUB, TXT, MD, PDF, DOC, DOCX, RTF, HTML"
        return jsonify({"error": f"Unsupported file type ({ext or 'none'}). "
                                 f"Supported formats: {nice}."}), 400

    # Save to a temporary spot first so we can read the title before naming
    # the final folder after the book.
    import tempfile, datetime
    tmpdir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmpdir, secure_filename(f.filename))
    f.save(tmp_path)

    try:
        if ext == ".epub":
            book = parse_epub(tmp_path)
        else:
            book = parse_document(tmp_path)
    except Exception as e:
        return jsonify({"error": f"Could not read that file: {e}"}), 400

    # Build a readable, unique job id: <title-slug>_<date>_<short-id>.
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    short = uuid.uuid4().hex[:6]
    job_id = f"{_slugify(book.title)}_{stamp}_{short}"

    jd = _job_dir(job_id)
    path = os.path.join(jd, secure_filename(f.filename))
    import shutil
    shutil.move(tmp_path, path)
    try:
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass

    chapter_dicts = _ensure_cids(
        [{"title": c.title, "text": c.text} for c in book.chapters])

    PROJECTS[job_id] = {
        "title": book.title,
        "author": book.author,
        "chapters": chapter_dicts,
        "epub_path": path,
    }

    # Persist a small metadata file so finished runs can be identified later
    # (e.g. in the "Bind existing files" recovery picker after a restart).
    try:
        import datetime
        meta = {
            "title": book.title,
            "author": book.author,
            "epub_filename": os.path.basename(path),
            "created": datetime.datetime.now().isoformat(timespec="seconds"),
            "chapter_titles": [c.title for c in book.chapters],
            # Store full chapter text so a stopped run can be resumed even
            # after the server restarts (the in-memory project is gone then).
            # 'cid' is the stable identity used by resume to recognise an
            # already-narrated chapter regardless of its position.
            "chapters": chapter_dicts,
        }
        with open(os.path.join(jd, "meta.json"), "w", encoding="utf-8") as mf:
            json.dump(meta, mf, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return jsonify({
        "job_id": job_id,
        "title": book.title,
        "author": book.author,
        "chapters": [
            {"index": i, "title": c.title,
             "preview": c.text[:200], "char_count": len(c.text)}
            for i, c in enumerate(book.chapters)
        ],
    })


@app.route("/chapters/<job_id>", methods=["POST"])
def update_chapters(job_id):
    """Replace the chapter list after manual edits in the UI.

    Body: {"chapters": [{"title": ..., "text": ...}, ...]}
    """
    proj = PROJECTS.get(job_id)
    if not proj:
        return jsonify({"error": "Unknown job."}), 404
    data = request.get_json(force=True)
    chapters = data.get("chapters", [])
    if not chapters:
        return jsonify({"error": "No chapters supplied."}), 400
    proj["chapters"] = [
        {"title": c.get("title", f"Chapter {i+1}"), "text": c.get("text", "")}
        for i, c in enumerate(chapters)
    ]
    _ensure_cids(proj["chapters"])
    _persist_chapters(job_id)
    return jsonify({"ok": True, "count": len(proj["chapters"])})


def _chapter_summary(proj):
    return [
        {"index": i, "title": c["title"],
         "preview": c["text"][:200], "char_count": len(c["text"])}
        for i, c in enumerate(proj["chapters"])
    ]


@app.route("/chapters/<job_id>/titles", methods=["POST"])
def update_titles(job_id):
    """Update just the titles (text is preserved by index)."""
    proj = PROJECTS.get(job_id)
    if not proj:
        return jsonify({"error": "Unknown job."}), 404
    data = request.get_json(force=True)
    for t in data.get("titles", []):
        i = t.get("index")
        if i is not None and 0 <= i < len(proj["chapters"]):
            proj["chapters"][i]["title"] = t.get("title", proj["chapters"][i]["title"])
    _persist_chapters(job_id)
    return jsonify({"ok": True, "chapters": _chapter_summary(proj)})


@app.route("/chapters/<job_id>/delete", methods=["POST"])
def delete_chapter(job_id):
    proj = PROJECTS.get(job_id)
    if not proj:
        return jsonify({"error": "Unknown job."}), 404
    i = request.get_json(force=True).get("index")
    if i is not None and 0 <= i < len(proj["chapters"]):
        proj["chapters"].pop(i)
    _persist_chapters(job_id)
    return jsonify({"ok": True, "chapters": _chapter_summary(proj)})


@app.route("/chapters/<job_id>/append", methods=["POST"])
def append_chapter(job_id):
    proj = PROJECTS.get(job_id)
    if not proj:
        return jsonify({"error": "Unknown job."}), 404
    proj["chapters"].append({"title": f"Chapter {len(proj['chapters'])+1}",
                             "text": ""})
    _ensure_cids(proj["chapters"])
    _persist_chapters(job_id)
    return jsonify({"ok": True, "chapters": _chapter_summary(proj)})


@app.route("/sample/<job_id>", methods=["POST"])
def upload_sample(job_id):
    """Store a voice sample (.wav) for cloning engines."""
    proj = PROJECTS.get(job_id)
    if not proj:
        return jsonify({"error": "Unknown job."}), 404
    f = request.files.get("sample")
    if not f:
        return jsonify({"error": "No sample file."}), 400
    jd = _job_dir(job_id)
    path = os.path.join(jd, "voice_sample.wav")
    f.save(path)
    proj["speaker_wav"] = path
    return jsonify({"ok": True})


@app.route("/sample/<job_id>/clear", methods=["POST"])
def clear_sample(job_id):
    """Remove the uploaded voice sample so narration reverts to the built-in
    voice selected in the dropdown."""
    proj = PROJECTS.get(job_id)
    if not proj:
        return jsonify({"error": "Unknown job."}), 404
    path = proj.pop("speaker_wav", None)
    if path:
        try:
            os.remove(path)
        except OSError:
            pass
    return jsonify({"ok": True})


ASSETS_VOICES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "assets", "voices")


def _builtin_reference_path(builtin_key, spec):
    """Return the bundled reference clip path for a Chatterbox built-in voice.

    These ship with the app (app/assets/voices/), so built-in voices work
    fully offline with no API key.
    """
    fname = spec.get("file")
    if not fname:
        raise RuntimeError(f"Built-in voice '{builtin_key}' has no reference file.")
    path = os.path.join(ASSETS_VOICES, fname)
    if not os.path.exists(path):
        raise RuntimeError(
            f"Bundled voice file missing: {fname}. Re-download the project, or "
            f"upload your own voice sample instead."
        )
    return path


def _resolve_voice(proj, data):
    """Shared: work out engine config + speaker_wav from a request body.
    Returns (engine_name, voice, params, cfg, speaker_wav) or raises."""
    engine_name = data.get("engine")
    voice = data.get("voice")
    api_key = data.get("api_key")
    language = data.get("language", "en")
    builtin_voice = data.get("builtin_voice")
    params = data.get("params") or {}
    speaker_wav = proj.get("speaker_wav")

    if engine_name == "chatterbox" and builtin_voice and not speaker_wav:
        spec = (ENGINE_CATALOG["chatterbox"]["builtin_voices"]
                .get(builtin_voice))
        if spec:
            speaker_wav = _builtin_reference_path(builtin_voice, spec)

    cfg = {}
    if engine_name in ("openai", "elevenlabs"):
        if api_key:
            cfg["api_key"] = api_key
        if language:
            cfg["language"] = language
    elif engine_name == "chatterbox":
        # Compute device choice: 'auto' | 'cuda' | 'mps' | 'cpu'
        cfg["device"] = data.get("device") or "auto"
        # Model variant: 'standard' | 'turbo'
        cfg["variant"] = data.get("variant") or "standard"

    return engine_name, voice, params, cfg, speaker_wav


def _sse(event):
    """Format a dict as a Server-Sent Event line."""
    return f"data: {json.dumps(event)}\n\n"


def _bind_and_finish(jd, proj, data, *, report, results, start,
                     failed_chapters=None):
    """Shared finish for both the in-process and recycling narration paths:
    optional combine + MP4 bind (the combine streams through ffmpeg on disk, so
    it stays low-memory even for a 12-hour book), then write the status report
    and emit the final 'done' event. Yields SSE strings. The caller should
    already have released the TTS model before calling this."""
    import time
    bind = data.get("bind") or {}
    if bind.get("enabled"):
        try:
            yield _sse({"type": "bind_progress", "stage": "combine",
                        "message": "Combining chapters into one audiobook…"})
            audio_fmt = bind.get("format", "mp3")
            base = _output_basename(proj.get("title"))
            yt_base = _youtube_basename(proj.get("title"))
            audio_out = os.path.join(jd, f"{base}.{audio_fmt}")
            t_combine = time.time()
            combo = combine_chapters(proj["chapter_files"], audio_out,
                                     fmt=audio_fmt)
            report["combine_seconds"] = round(time.time() - t_combine, 1)
            report["audio_length_seconds"] = round(
                combo.get("total_ms", 0) / 1000.0)

            timestamps = build_youtube_timestamps(combo["markers"])
            ts_name = f"{yt_base}.txt"
            with open(os.path.join(jd, ts_name), "w", encoding="utf-8") as f:
                f.write(timestamps)

            # Exact subtitles (.srt) from the narrator's per-chunk timing.
            # Off => skip; Soft/Burned-in => write the file (and embed below).
            sub_mode = (bind.get("subtitles") or "none").lower()
            sub_name = None
            sub_path = None
            if sub_mode in ("soft", "burn"):
                try:
                    subs = [{"path": p, "start_ms": combo["markers"][i][1]}
                            for i, (t, p) in enumerate(proj["chapter_files"])]
                    srt_path = os.path.join(
                        jd, yt_base.replace("youtube-chapters-", "subtitles-", 1) + ".srt")
                    sub_name = write_subtitles(subs, srt_path)
                    if sub_name:
                        sub_path = srt_path
                except Exception:
                    sub_name = None

            # Clickable chapter index for playing the video from Google Drive.
            drive_name = yt_base.replace("youtube-chapters-",
                                         "drive-chapters-", 1) + ".html"
            try:
                with open(os.path.join(jd, drive_name), "w",
                          encoding="utf-8") as f:
                    f.write(build_drive_chapter_page(
                        combo["markers"], proj.get("title"),
                        combo.get("total_ms")))
            except Exception:
                drive_name = None

            payload = {"type": "bind_done",
                       "audio_file": os.path.basename(audio_out),
                       "timestamps": timestamps, "timestamps_file": ts_name,
                       "drive_chapters_file": drive_name,
                       "subtitles_file": sub_name}

            if bind.get("make_video"):
                image = proj.get("cover_image")
                if not image:
                    import glob as _glob
                    covers = _glob.glob(os.path.join(jd, "cover.*"))
                    covers = [c for c in covers
                              if not c.endswith("_prepared.jpg")]
                    image = covers[0] if covers else None
                if not ensure_ffmpeg():
                    payload["video_error"] = "ffmpeg not found on PATH."
                elif not image:
                    payload["video_error"] = "No cover image was uploaded."
                else:
                    video_out = os.path.join(jd, f"{base}.mp4")
                    t_video = time.time()
                    vstate = {"frac": 0.0, "done": False, "err": None}

                    def vcb(frac):
                        vstate["frac"] = frac

                    def vwork():
                        try:
                            build_video(audio_out, image, video_out,
                                        markers=combo["markers"],
                                        total_ms=combo["total_ms"],
                                        progress_callback=vcb,
                                        subtitle_path=sub_path,
                                        subtitle_mode=sub_mode)
                        except Exception as e:
                            vstate["err"] = str(e)
                        finally:
                            vstate["done"] = True

                    vt = threading.Thread(target=vwork, daemon=True)
                    vt.start()
                    yield _sse({"type": "bind_progress", "stage": "video",
                                "message": "Building the MP4 video…", "frac": 0.0})
                    while not vstate["done"]:
                        time.sleep(1.0)
                        elapsed = time.time() - t_video
                        f = vstate["frac"]
                        eta = (elapsed / f - elapsed) if f > 0.01 else None
                        yield _sse({"type": "bind_progress", "stage": "video",
                                    "message": "Building the MP4 video…",
                                    "frac": round(f, 3),
                                    "eta_sec": round(eta) if eta else None})
                    if vstate["err"]:
                        payload["video_error"] = vstate["err"]
                    else:
                        report["video_seconds"] = round(time.time() - t_video, 1)
                        payload["video_file"] = os.path.basename(video_out)

            yield _sse(payload)
        except Exception as be:
            yield _sse({"type": "bind_error", "message": f"Binding failed: {be}"})

    report["total_seconds"] = round(time.time() - start, 1)
    report_text = _format_report(report)
    try:
        with open(os.path.join(jd, "status_report.txt"), "w",
                  encoding="utf-8") as rf:
            rf.write(report_text)
    except Exception:
        pass
    has_errlog = os.path.exists(os.path.join(jd, "errors.log"))
    yield _sse({"type": "done", "chapters": results,
                "report": report, "report_text": report_text,
                "report_file": "status_report.txt",
                "failed_chapters": failed_chapters or [],
                "errors_log": "errors.log" if has_errlog else None})


def _orchestrate_recycled_narration(job_id, jd, total_ch, worker_params, batch,
                                    start):
    """Narrate by repeatedly spawning a short-lived worker process that does up
    to `batch` chapters and then exits — which hands all of its memory (model,
    buffers, fragmentation, everything) straight back to the OS, the one cleanup
    Windows always honours. Respawn until the whole book is done. Yields SSE
    strings; returns {"error": str|None}."""
    import subprocess
    import sys
    import time
    pf = os.path.join(jd, "_worker_params.json")
    try:
        with open(pf, "w", encoding="utf-8") as f:
            json.dump(worker_params, f)
    except Exception as e:
        yield _sse({"type": "error", "message": f"Couldn't start narration: {e}"})
        return {"error": str(e)}

    env = os.environ.copy()
    errlog = os.path.join(jd, "_worker_errors.log")
    passes = 0
    while True:
        done_before = len(_bindable_chapters(job_id))
        if done_before >= total_ch:
            return {"error": None}
        passes += 1
        if passes > 1:
            ms = _mem_stats()
            free = f" · RAM {round(ms[0], 1)} GB free" if ms else ""
            yield _sse({"type": "loading",
                        "message": f"Flushed memory — {done_before}/{total_ch} "
                                   f"done. Restarting for the next {batch} "
                                   f"chapter(s){free}…"})

        try:
            ef = open(errlog, "w", encoding="utf-8")
        except Exception:
            ef = subprocess.DEVNULL
        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", "-m", "app.narrate_worker", job_id, pf],
                cwd=BASE, stdout=subprocess.PIPE, stderr=ef, text=True, env=env)
        except Exception as e:
            try:
                ef.close()
            except Exception:
                pass
            yield _sse({"type": "error",
                        "message": f"Couldn't start narration worker: {e}"})
            return {"error": str(e)}

        worker_error = None
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                etype = ev.get("type")
                if etype == "batch_done":
                    continue  # internal signal to the parent; don't forward
                if etype == "error":
                    worker_error = ev.get("message")
                # Attach a live overall ETA from total elapsed time, which
                # includes the per-batch restart overhead — so the estimate the
                # user sees already accounts for the recycling.
                if etype in ("progress", "chapter_done"):
                    ov = ev.get("overall")
                    if ov and ov > 0.01:
                        elapsed = time.time() - start
                        ev["eta_sec"] = round(elapsed / ov - elapsed)
                yield _sse(ev)
        finally:
            proc.wait()
            try:
                ef.close()
            except Exception:
                pass

        code = proc.returncode
        if code == 0:
            return {"error": None}                 # whole book finished
        if code == 2:
            done_after = len(_bindable_chapters(job_id))
            if done_after <= done_before:
                # Safety net: a batch that made no progress would loop forever.
                msg = ("Narration didn't advance — stopping to avoid a loop. "
                       "Your finished chapters are saved; click Resume to retry.")
                yield _sse({"type": "error", "message": msg})
                return {"error": msg}
            continue                               # progress made; next batch
        # Any other exit code: an error stopped this batch.
        # A fatal CUDA error (device-side assert) kills that worker's CUDA
        # context — but the worker is a SEPARATE process, so the next one starts
        # with a clean context. If the batch made progress, just carry on: this
        # is the one case where process recycling can recover automatically from
        # an otherwise unrecoverable GPU error.
        if worker_error and _is_fatal_cuda_error(worker_error):
            done_after = len(_bindable_chapters(job_id))
            if done_after > done_before:
                yield _sse({"type": "loading",
                            "message": "A GPU error ended that batch early. "
                                       "Starting a fresh process with a clean "
                                       "GPU context and continuing…"})
                continue
            # No progress: the very first chapter of the batch fails every time,
            # so retrying would loop forever. Stop with an honest explanation.
            msg = ("Narration hit a GPU error it couldn't get past "
                   f"({worker_error}). Your finished chapters are saved. This "
                   "usually means one chapter's text upsets the model — try "
                   "Resume; if it stops on the same chapter again, that "
                   "chapter is the culprit.")
            yield _sse({"type": "error", "message": msg})
            return {"error": msg}
        if not worker_error:
            tail = ""
            try:
                with open(errlog, encoding="utf-8") as lf:
                    lines = lf.read().strip().splitlines()
                    tail = lines[-1] if lines else ""
            except Exception:
                tail = ""
            worker_error = ("Narration stopped unexpectedly"
                            + (f": {tail}" if tail else "")
                            + ". Your finished chapters are saved — click Resume "
                              "to continue.")
            yield _sse({"type": "error", "message": worker_error})
        return {"error": worker_error or "stopped"}


@app.route("/synthesize/<job_id>", methods=["POST"])
def synthesize(job_id):
    """Render every chapter to its own file, streaming progress via SSE.

    Emits events: {type:'progress', chapter, total_chapters, chapter_title,
                   frac, overall, eta_sec} and finally {type:'done', chapters}
    or {type:'error', message}.
    """
    proj = PROJECTS.get(job_id)
    if not proj:
        return jsonify({"error": "Unknown job."}), 404

    data = request.get_json(force=True)
    try:
        engine_name, voice, params, cfg, speaker_wav = _resolve_voice(proj, data)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    chapters = list(proj["chapters"])
    jd = _job_dir(job_id)

    # Stable identity for every chapter + the cid->file ledger that records what
    # we've narrated. Resume keys off this (not numeric position), so reordering
    # or deleting chapters can't cause re-narration or duplicate files.
    _ensure_cids(chapters)
    ledger = _migrate_ledger(jd, chapters)

    # "Re-narrate selected chapters" mode: when only_chapters is given (a list of
    # 1-based positions in the chapter list), delete THAT chapter's own narrated
    # file (located by identity, so we never nuke an unrelated file that happens
    # to share a number) so it re-narrates fresh, and skip every other chapter.
    only_chapters = data.get("only_chapters")
    only_set = set(int(x) for x in only_chapters) if only_chapters else None
    if only_set:
        for idx in sorted(only_set):
            if 1 <= idx <= len(chapters):
                cid = chapters[idx - 1]["cid"]
                old = _ledger_file_for(jd, ledger, cid)
                if old:
                    try:
                        os.remove(old)
                    except OSError:
                        pass
                ledger.pop(cid, None)
        _save_ledger(jd, ledger)

    # Save the chosen voice settings into meta.json so a later "Resume" can
    # reuse the exact same voice/engine without re-asking (and without risking
    # a mismatch between already-narrated chapters and resumed ones).
    try:
        meta_path = os.path.join(jd, "meta.json")
        meta = {}
        if os.path.exists(meta_path):
            with open(meta_path, encoding="utf-8") as mf:
                meta = json.load(mf)
        meta["voice_settings"] = {
            "engine": engine_name,
            "voice": voice,
            "builtin_voice": data.get("builtin_voice"),
            "params": params,
            "device": data.get("device"),
            "variant": data.get("variant"),
            "language": data.get("language", "en"),
        }
        with open(meta_path, "w", encoding="utf-8") as mf:
            json.dump(meta, mf, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # Low-memory (process-recycling) mode: narrate in short-lived worker
    # processes that exit every `recycle_batch` chapters, fully returning their
    # memory to the OS, so RAM and the page file never climb across a long book.
    recycle = bool(data.get("recycle"))
    recycle_batch = max(1, int(data.get("recycle_batch", 10) or 10))
    worker_params = {
        "engine_name": engine_name, "cfg": cfg, "voice": voice,
        "params": params, "speaker_wav": speaker_wav, "batch": recycle_batch,
    }

    def _looks_truncated(path, text):
        """A chapter file is 'truncated' if it has substantial text but its
        audio is implausibly short for that text — the tell-tale sign of a
        narration that died partway (e.g. a memory error), leaving a few-second
        stub. Real narration is on the order of 12–18 characters of text per
        second of audio; we flag anything under ~40 chars/sec (i.e. far too
        little audio for the text) so it gets re-narrated rather than kept."""
        n = len((text or "").strip())
        if n < 500:
            return False           # short chapters are legitimately short
        try:
            from pydub import AudioSegment
            dur_sec = len(AudioSegment.from_file(path)) / 1000.0
        except Exception:
            return False           # can't measure → don't second-guess
        if dur_sec < 1:
            return True
        chars_per_sec = n / dur_sec
        # Normal speech ≈ 12–18 chars/sec. >40 chars/sec means there's nowhere
        # near enough audio for the text → it was cut off.
        return chars_per_sec > 40

    def _existing_chapter_file(idx, text=None):
        """Return the path of an already-rendered chapter file, or None. Matches
        by the chapter_NNN prefix so a descriptive title suffix doesn't break
        resume detection. NOTE: we do NOT auto-delete or re-do short files here —
        a genuinely short chapter is valid, and the user decides what to re-do
        via the explicit 'Re-narrate selected chapters' button. Resume only
        narrates chapters that are actually missing."""
        import glob as _g
        for ext in (".wav", ".mp3"):
            p = os.path.join(jd, f"chapter_{idx+1:03d}{ext}")
            if os.path.exists(p) and os.path.getsize(p) > 1024:
                return p
        for ext in (".wav", ".mp3"):
            for p in _g.glob(os.path.join(jd, f"chapter_{idx+1:03d}_*{ext}")):
                if os.path.getsize(p) > 1024:
                    return p
        return None

    def _chapter_out_path(idx, title):
        """Build the output path for a chapter: chapter_NNN_<title-slug>.mp3.
        The numeric prefix keeps ordering/sorting/resume working; the slug makes
        the file human-readable. Title slug capped at 40 chars."""
        slug = _slugify(title, 40)
        if slug and slug != "book":
            return os.path.join(jd, f"chapter_{idx+1:03d}_{slug}.mp3")
        return os.path.join(jd, f"chapter_{idx+1:03d}.mp3")

    # How many chapters to narrate before reloading the model to release
    # memory. Lower = lower peak memory (better for 16 GB machines), at the
    # cost of an occasional model reload. 0 disables reloading.
    RELOAD_EVERY = int(data.get("reload_every", 10) or 0)
    # Reload the model (the only way to release its RAM) once free RAM drops
    # below this. It's set ABOVE the reload safety gate's ~3 GB headroom on
    # purpose: we want to reload while ~3–4.5 GB is still free, so there's room
    # to absorb the brief reload spike — not after RAM is already critically low,
    # when reloading would itself risk a crash and gets skipped. Mid-chapter, if
    # RAM dips below the floor we do a lighter reclaim (cache/garbage) on the spot.
    MEM_RELOAD_GB = float(data.get("mem_reload_gb", 4.5) or 4.5)
    MEM_FLOOR_GB = float(data.get("mem_floor_gb", 1.5) or 1.5)

    def stream():
        import time

        # ---- Low-memory mode: narrate via recycled worker processes ----
        # Each worker narrates `recycle_batch` chapters, then exits so the OS
        # fully reclaims its memory; we respawn until the book is done, then bind.
        # The parent (here) never loads the model in this mode, so it stays tiny.
        if recycle and only_set is None:
            start = time.time()
            total_ch = len(chapters)
            yield _sse({"type": "loading",
                        "message": f"Low-memory mode: narrating in bursts of "
                                   f"{recycle_batch}, fully flushing memory "
                                   f"between each. Loading the model…"})
            res = yield from _orchestrate_recycled_narration(
                job_id, jd, total_ch, worker_params, recycle_batch, start)
            if res.get("error"):
                return
            bindable = _bindable_chapters(job_id)
            proj["chapter_files"] = [(b["title"], b["file"]) for b in bindable]
            results = [{"index": b["index"] - 1, "title": b["title"],
                        "file": os.path.basename(b["file"])} for b in bindable]
            total_chars = sum(len((c.get("text") or "")) for c in chapters)
            report = {
                "title": proj.get("title"), "author": proj.get("author"),
                "chapters": len(results), "characters": total_chars,
                "engine": engine_name, "device": None,
                "variant": (cfg.get("variant") if isinstance(cfg, dict)
                            else None),
                "narrate_seconds": round(time.time() - start, 1),
                "combine_seconds": None, "video_seconds": None,
            }
            yield from _bind_and_finish(jd, proj, data, report=report,
                                        results=results, start=start)
            return

        try:
            engine = get_engine(engine_name, **cfg)
        except Exception as e:
            yield _sse({"type": "error", "message": f"Engine init failed: {e}"})
            return

        dev = getattr(engine, "device", None)
        dev_note = f" (using {dev.upper()})" if dev else ""
        yield _sse({"type": "loading",
                    "message": f"Model ready{dev_note}. Starting narration…",
                    "device": dev})

        total_ch = len(chapters)
        results = []
        start = time.time()
        # Weight progress by character count so the bar/ETA track real work.
        sizes = [max(1, len(c["text"])) for c in chapters]
        total_size = sum(sizes)
        done_size = 0
        since_reload = 0
        failed_chapters = []   # chapters that couldn't be narrated even on retry

        # Shared mutable state updated by the worker thread's callback.
        state = {"frac": 0.0, "err": None, "done": False}
        # Throttle for mid-chapter memory relief so we reclaim at most once every
        # few seconds rather than every poll.
        mem_state = {"last_reclaim": 0.0, "reclaims": 0, "last_skip_note": -10**9}

        for i, ch in enumerate(chapters):
            cid = ch.get("cid") or _chapter_cid(ch.get("text", ""))
            ch["cid"] = cid
            out = _chapter_out_path(i, ch["title"])

            # Re-narrate mode: only narrate the selected chapters; leave the
            # rest exactly as they are (don't even report them).
            if only_set is not None and (i + 1) not in only_set:
                continue

            # Resume support: skip this chapter only if THIS chapter's own audio
            # already exists, matched by identity (not by numeric position). That
            # way a reordered or edited list never mistakes a leftover file for a
            # different chapter — so nothing is re-narrated or duplicated. We
            # NEVER auto-redo an existing file here; a short chapter may be
            # legitimate, and redo is always the explicit button.
            already = _ledger_file_for(jd, ledger, cid)
            if already:
                done_size += sizes[i]
                results.append({"index": i, "title": ch["title"],
                                "file": os.path.basename(already)})
                yield _sse({
                    "type": "chapter_done",
                    "chapter": i + 1,
                    "total_chapters": total_ch,
                    "chapter_title": ch["title"] + " (already done)",
                    "overall": round(done_size / total_size, 3),
                })
                continue

            # Reload the model to release accumulated memory when EITHER the
            # chapter count threshold is hit OR free RAM is getting low. The
            # memory check prevents running out before the scheduled reload.
            #
            # BUT only reload if there's enough free virtual memory (commit
            # headroom) to load a fresh model — otherwise the reload itself can
            # fail with "paging file too small" (os error 1455). If headroom is
            # tight we skip the reload and keep using the current model; the
            # per-chapter streaming already keeps memory from growing.
            # Trigger a reload when EITHER the scheduled chapter count is hit OR
            # free RAM has dropped below the proactive threshold. The low-RAM
            # trigger fires even outside low-memory mode (it's a safety net), and
            # at a generous threshold so the reload happens while there's still
            # room for its spike. The safety check below still holds the reload
            # off (with a clear reason) if free physical RAM or commit headroom is
            # genuinely too tight to reload without risking a crash.
            low_mem = _memory_low(MEM_RELOAD_GB)
            reload_ok, reload_reason = _reload_safety()
            scheduled_reload = bool(RELOAD_EVERY and since_reload >= RELOAD_EVERY)
            # Only pursue a low-RAM reload if it could actually succeed right now.
            # On a machine that sits low on RAM, a reload can't run safely, so
            # there's nothing to gain by trying every chapter — that would just
            # thrash and spam the log. The scheduled reload is still attempted so
            # we can tell the user (once in a while) when it's being held off.
            lowram_reload = low_mem and since_reload >= 1 and reload_ok
            want_reload = scheduled_reload or lowram_reload
            if want_reload and not reload_ok:
                # Reachable only via a scheduled reload that can't run safely now.
                # Keeping the current model is fine — per-chapter streaming holds
                # memory flat — so this is informational, not an error. Show it
                # the first time, then at most every ~10 chapters, not every one.
                if (i - mem_state["last_skip_note"]) >= 10:
                    mem_state["last_skip_note"] = i
                    yield _sse({"type": "loading",
                                "message": f"Keeping the current model loaded for "
                                           f"now — {reload_reason}. This is fine; "
                                           f"narration continues normally."})
                _log_book_error(jd, f"Held off model reload before chapter {i+1}: "
                                    f"{reload_reason}.")
                want_reload = False
                since_reload = 0
            if want_reload:
                _ms = _mem_stats()
                _free = f" — {round(_ms[0], 1)} GB RAM free" if _ms else ""
                why = "low memory" if low_mem else "scheduled"
                yield _sse({"type": "loading",
                            "message": f"Releasing memory ({why}, reloading "
                                       f"model){_free}…"})
                # Fully free the old model FIRST (don't hold two models at once,
                # which would raise the memory peak), then load fresh.
                try:
                    del engine
                except Exception:
                    pass
                engine = None
                _reclaim_memory()
                import time as _t
                _t.sleep(0.5)            # let the OS reclaim before reloading
                _reclaim_memory()

                engine = None
                last_err = None
                for attempt in range(2):
                    try:
                        engine = get_engine(engine_name, **cfg)
                        break
                    except Exception as e:
                        last_err = e
                        _reclaim_memory()
                        _t.sleep(1.5)   # wait and retry once
                if engine is None:
                    _log_book_error(jd, f"Model reload FAILED before chapter "
                                        f"{i+1}: {last_err}. Run halted; "
                                        f"resumable.")
                    yield _sse({"type": "error",
                                "message": f"Model reload failed: {last_err}. "
                                f"Your chapters so far are saved — this run can "
                                f"be resumed. (If this is a 'paging file too "
                                f"small' error, see the README memory tips.)"})
                    return
                since_reload = 0

            def cb(cur, tot):
                state["frac"] = (cur / tot) if tot else 0.0

            def _narrate_once():
                """Narrate this chapter once, yielding SSE progress strings.
                Sets state['err'] if it fails."""
                state["frac"] = 0.0
                state["done"] = False
                state["err"] = None
                state["actual"] = out

                def work():
                    try:
                        written = engine.synthesize(ch["text"], out, voice=voice,
                                                    speaker_wav=speaker_wav,
                                                    progress_callback=cb, **params)
                        if written:
                            state["actual"] = written
                    except Exception as e:
                        state["err"] = str(e)
                    finally:
                        state["done"] = True

                t = threading.Thread(target=work, daemon=True)
                t.start()
                while not state["done"]:
                    time.sleep(0.5)
                    # Live memory + on-the-spot relief. If free RAM dips below the
                    # floor WHILE this chapter is narrating, reclaim cache/garbage
                    # right now (throttled) instead of waiting for the chapter to
                    # finish — this is the "release when it's getting low, now"
                    # behaviour. The model itself can only be unloaded at a chapter
                    # boundary, so the big release still happens between chapters.
                    ms = _mem_stats()
                    mem_avail = round(ms[0], 2) if ms else None
                    mem_pct = round(ms[2]) if ms else None
                    mem_note = None
                    if (ms and ms[0] < MEM_FLOOR_GB and
                            (time.time() - mem_state["last_reclaim"]) > 8):
                        _reclaim_memory()
                        mem_state["last_reclaim"] = time.time()
                        mem_state["reclaims"] += 1
                        ms2 = _mem_stats()
                        if ms2:
                            mem_avail = round(ms2[0], 2)
                            mem_pct = round(ms2[2])
                        mem_note = (f"Low RAM — reclaimed memory "
                                    f"({mem_avail} GB free)")
                    overall = (done_size + state["frac"] * sizes[i]) / total_size
                    elapsed = time.time() - start
                    eta = (elapsed / overall - elapsed) if overall > 0.01 else None
                    ev = {
                        "type": "progress",
                        "chapter": i + 1,
                        "total_chapters": total_ch,
                        "chapter_title": ch["title"],
                        "frac": round(state["frac"], 3),
                        "overall": round(overall, 3),
                        "eta_sec": round(eta) if eta else None,
                        "mem_avail_gb": mem_avail,
                        "mem_pct": mem_pct,
                    }
                    if mem_note:
                        ev["mem_note"] = mem_note
                    yield _sse(ev)

            yield from _narrate_once()

            # If narration failed, retry ONCE — but only for errors a retry can
            # actually fix (e.g. a transient "bad allocation" memory error). A
            # CUDA device-side assert kills the whole CUDA context, so every
            # further GPU call in this process fails too: retrying just burns
            # time and produces a second identical error.
            if state["err"] and not _is_fatal_cuda_error(state["err"]):
                yield _sse({"type": "loading",
                            "message": f"Chapter {i+1} hit a problem "
                                       f"({state['err']}). Freeing memory and "
                                       f"retrying once…"})
                _reclaim_memory()
                import time as _t
                _t.sleep(1.5)
                _reclaim_memory()
                yield from _narrate_once()

            if state["err"]:
                # Failed (after a retry, unless the error was unrecoverable).
                # HALT here rather than advancing past it. Advancing tends to
                # cascade — the same memory pressure that broke this chapter
                # usually breaks the next ones too, producing a string of
                # truncated chapters. Stopping lets memory fully clear; you then
                # Resume (fresh, low memory) and it re-narrates this chapter and
                # continues. The broken stub is removed so it isn't mistaken for
                # a finished chapter.
                for ext in (".wav", ".mp3"):
                    stub = os.path.splitext(out)[0] + ext
                    if os.path.exists(stub):
                        try:
                            os.remove(stub)
                        except OSError:
                            pass
                failed_chapters.append(i + 1)
                fatal_cuda = _is_fatal_cuda_error(state["err"])
                _log_book_error(jd, f"Chapter {i+1} ({ch['title']}) failed: "
                                    f"{state['err']}. Run HALTED"
                                    + (" (CUDA context lost — restart required)"
                                       if fatal_cuda else
                                       "; resume to continue from here."))
                if fatal_cuda:
                    msg = (f"Chapter {i+1} ({ch['title']}) hit a GPU error that "
                           f"ends this run: the CUDA context can't recover, so "
                           f"narration has to restart. Your finished chapters "
                           f"are saved. Please STOP Parroty and start it again, "
                           f"then click Resume to continue from chapter {i+1}. "
                           f"(This isn't a RAM problem — freeing memory won't "
                           f"help.)")
                else:
                    msg = (f"Chapter {i+1} ({ch['title']}) failed to narrate "
                           f"({state['err']}). Stopped here so memory can "
                           f"clear — chapters up to {i} are saved. Close other "
                           f"apps to free RAM, then click Resume to continue "
                           f"from chapter {i+1}.")
                yield _sse({"type": "error", "message": msg})
                return

            done_size += sizes[i]
            since_reload += 1
            actual_name = os.path.basename(state["actual"])
            # Record this chapter's audio against its identity so future resumes
            # recognise it instantly, even if the list is later reordered.
            ledger[cid] = actual_name
            _save_ledger(jd, ledger)
            results.append({"index": i, "title": ch["title"],
                            "file": actual_name})
            yield _sse({
                "type": "chapter_done",
                "chapter": i + 1,
                "total_chapters": total_ch,
                "chapter_title": ch["title"],
                "overall": round(done_size / total_size, 3),
            })

            # Reclaim memory between chapters so long books don't slowly
            # exhaust RAM/VRAM over many chapters.
            _reclaim_memory()

        proj["chapter_files"] = [
            (chapters[r["index"]]["title"], os.path.join(jd, r["file"]))
            for r in results
        ]

        # Narration timing (chapters only, before the bind phase).
        narrate_sec = time.time() - start
        narrated_count = sum(
            1 for r in results
            if "already done" not in chapters[r["index"]]["title"])
        total_chars = sum(len(c["text"]) for c in chapters)
        device_used = getattr(engine, "device", None)

        report = {
            "title": proj.get("title"),
            "author": proj.get("author"),
            "chapters": len(results),
            "characters": total_chars,
            "engine": engine_name,
            "device": device_used,
            "variant": params and None,  # placeholder, set below
            "narrate_seconds": round(narrate_sec, 1),
            "combine_seconds": None,
            "video_seconds": None,
        }
        # variant for chatterbox
        report["variant"] = (cfg.get("variant") if isinstance(cfg, dict)
                             else None)

        # ---- Free the model, then bind + finish (shared with low-mem mode)
        try:
            del engine
        except Exception:
            pass
        _reclaim_memory()
        yield from _bind_and_finish(jd, proj, data, report=report,
                                    results=results, start=start,
                                    failed_chapters=failed_chapters)

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


_PREVIEW_TEXT = (
    "This is a short preview of how your audiobook will sound with the "
    "current voice and settings."
)


@app.route("/preview/<job_id>", methods=["POST"])
def preview(job_id):
    """Render one short sentence, streaming progress via SSE, then return the
    audio URL in a final 'done' event."""
    proj = PROJECTS.get(job_id)
    if not proj:
        return jsonify({"error": "Unknown job."}), 404

    data = request.get_json(force=True)
    try:
        engine_name, voice, params, cfg, speaker_wav = _resolve_voice(proj, data)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    jd = _job_dir(job_id)
    out = os.path.join(jd, "preview.mp3")

    def stream():
        import time
        try:
            engine = get_engine(engine_name, **cfg)
        except Exception as e:
            yield _sse({"type": "error", "message": f"Engine init failed: {e}"})
            return

        dev = getattr(engine, "device", None)
        dev_note = f" (using {dev.upper()})" if dev else ""
        yield _sse({"type": "loading",
                    "message": f"Model ready{dev_note}. Rendering…",
                    "device": dev})

        state = {"frac": 0.0, "err": None, "done": False, "actual": out}
        start = time.time()

        def cb(cur, tot):
            state["frac"] = (cur / tot) if tot else 0.0

        def work():
            try:
                written = engine.synthesize(_PREVIEW_TEXT, out, voice=voice,
                                            speaker_wav=speaker_wav,
                                            progress_callback=cb, **params)
                if written:
                    state["actual"] = written
            except Exception as e:
                state["err"] = str(e)
            finally:
                state["done"] = True

        t = threading.Thread(target=work, daemon=True)
        t.start()

        while not state["done"]:
            time.sleep(0.4)
            elapsed = time.time() - start
            frac = state["frac"]
            eta = (elapsed / frac - elapsed) if frac > 0.01 else None
            yield _sse({"type": "progress", "overall": round(frac, 3),
                        "eta_sec": round(eta) if eta else None})

        if state["err"]:
            yield _sse({"type": "error",
                        "message": f"Preview failed: {state['err']}"})
            return

        fname = os.path.basename(state["actual"])
        yield _sse({"type": "done",
                    "url": f"/audio/{job_id}/{fname}?t={int(time.time())}"})

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


_CALIBRATION_TEXT = (
    "This is a calibration sample used to measure how quickly this computer "
    "can generate speech, so the time estimate reflects your actual hardware."
)


@app.route("/estimate/<job_id>", methods=["POST"])
def estimate(job_id):
    """Estimate total narration time by rendering one short calibration clip,
    measuring this machine's chars/second, and scaling to the whole book.

    Self-calibrating: the result reflects the user's actual GPU/CPU speed and
    the chosen model (Standard vs Turbo), not a generic guess.
    """
    proj = PROJECTS.get(job_id)
    if not proj:
        return jsonify({"error": "Unknown job."}), 404

    data = request.get_json(force=True)
    try:
        engine_name, voice, params, cfg, speaker_wav = _resolve_voice(proj, data)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    total_chars = sum(max(1, len(c["text"])) for c in proj["chapters"])
    jd = _job_dir(job_id)
    out = os.path.join(jd, "_calib.wav")

    import time
    _t_load = time.time()
    try:
        engine = get_engine(engine_name, **cfg)
    except Exception as e:
        return jsonify({"error": f"Engine init failed: {e}"}), 400
    # Cold model-load time ≈ the per-batch overhead in low-memory mode, where a
    # fresh worker loads the model for each batch. (If the engine was cached from
    # an earlier action this reads low; the live ETA self-corrects during the run.)
    model_load_sec = time.time() - _t_load

    t0 = time.time()
    try:
        actual = engine.synthesize(_CALIBRATION_TEXT, out, voice=voice,
                                   speaker_wav=speaker_wav, **params)
    except Exception as e:
        return jsonify({"error": f"Calibration failed: {e}"}), 500
    elapsed = time.time() - t0

    # Measure the calibration clip's actual AUDIO duration so we can project
    # how long the finished audiobook will be (real spoken length, not just
    # how long it takes to generate). This is far more accurate than a generic
    # words-per-minute guess because it uses this exact voice/engine.
    calib_audio_sec = None
    calib_path = actual if (actual and os.path.exists(actual)) else None
    if not calib_path:
        for ext in (".wav", ".mp3"):
            p = os.path.splitext(out)[0] + ext
            if os.path.exists(p):
                calib_path = p
                break
    if calib_path:
        try:
            from pydub import AudioSegment
            calib_audio_sec = len(AudioSegment.from_file(calib_path)) / 1000.0
        except Exception:
            calib_audio_sec = None

    # Clean up the calibration file.
    for ext in (".wav", ".mp3"):
        p = os.path.splitext(out)[0] + ext
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass

    calib_chars = len(_CALIBRATION_TEXT)
    chars_per_sec = (calib_chars / elapsed) if elapsed > 0 else 0
    est_sec = (total_chars / chars_per_sec) if chars_per_sec > 0 else None

    # In low-memory mode the model is reloaded once per batch (each fresh worker
    # cold-starts it), so add that overhead to the estimate.
    import math as _math
    recycle = bool(data.get("recycle"))
    recycle_batch = max(1, int(data.get("recycle_batch", 10) or 10))
    n_chapters = len(proj["chapters"])
    recycle_overhead_sec = 0
    if recycle and est_sec is not None:
        n_batches = max(1, _math.ceil(n_chapters / recycle_batch))
        recycle_overhead_sec = round(n_batches * model_load_sec)
        est_sec = est_sec + recycle_overhead_sec

    # Project finished audiobook length from the calibration clip's real audio
    # duration: audio_seconds_per_char * total_chars. Fall back to a typical
    # narration rate (~15 chars/sec of speech) if we couldn't measure it.
    if calib_audio_sec and calib_chars > 0:
        audio_sec_per_char = calib_audio_sec / calib_chars
    else:
        audio_sec_per_char = 1.0 / 15.0
    est_audio_sec = total_chars * audio_sec_per_char

    return jsonify({
        "ok": True,
        "total_chars": total_chars,
        "calib_seconds": round(elapsed, 1),
        "chars_per_sec": round(chars_per_sec, 1),
        "est_seconds": round(est_sec) if est_sec else None,
        "est_audio_seconds": round(est_audio_sec) if est_audio_sec else None,
        "recycle": recycle,
        "recycle_overhead_seconds": recycle_overhead_sec,
        "model_load_seconds": round(model_load_sec, 1),
        "device": getattr(engine, "device", None),
    })


def _natural_chapter_sort(files):
    """Sort chapter_NNN.* files by their numeric index."""
    import re as _re
    def key(p):
        m = _re.search(r"chapter_(\d+)", os.path.basename(p))
        return int(m.group(1)) if m else 0
    return sorted(files, key=key)


@app.route("/chapters/<job_id>", methods=["GET"])
def list_chapters(job_id):
    """List the narrated chapters for a job — in the CURRENT chapter list's
    order, each mapped to its own audio by identity — with titles and durations.
    Used by the UI to let the user pick which chapters to include when binding
    (e.g. to drop chapters and fit under YouTube's 12-hour limit). 'index' is the
    chapter's position in the full list, so selection and re-narrate stay
    consistent everywhere."""
    jd = os.path.join(OUTPUT, job_id)
    if not os.path.isdir(jd):
        return jsonify({"error": "No output folder for that job id."}), 404

    bindable = _bindable_chapters(job_id)
    if not bindable:
        return jsonify({"error": "No chapter files found."}), 404

    from pydub import AudioSegment
    chapters = []
    total_ms = 0
    suspicious_count = 0
    for b in bindable:
        fp = b["file"]
        dur_ms = 0
        try:
            dur_ms = len(AudioSegment.from_file(fp))
        except Exception:
            dur_ms = 0
        total_ms += dur_ms
        # Suspicious = substantial text but far too little audio (>40 chars/sec):
        # the tell-tale sign of a chapter cut off by a memory error mid-run.
        suspicious = False
        n = b.get("chars", 0)
        if n >= 500 and dur_ms > 0:
            if (n / (dur_ms / 1000.0)) > 40:
                suspicious = True
        elif n >= 500 and dur_ms == 0:
            suspicious = True
        if suspicious:
            suspicious_count += 1
        chapters.append({
            "index": b["index"],
            "title": b["title"],
            "file": os.path.basename(fp),
            "duration_ms": dur_ms,
            "suspicious": suspicious,
        })

    return jsonify({"ok": True, "chapters": chapters,
                    "total_ms": total_ms, "count": len(chapters),
                    "suspicious_count": suspicious_count})


@app.route("/recover/<job_id>", methods=["POST"])
def recover(job_id):
    """Bind chapter files already on disk for this job, without re-narrating.
    Streams progress via SSE (combine, then video with a live % + ETA).

    Chapters are bound in the CURRENT chapter list's order, each mapped to its
    own audio by identity — so the audiobook follows the list, not whatever the
    files happen to be numbered. 'selected_chapters' are positions in that list
    (the same indices the include panel shows)."""
    jd = os.path.join(OUTPUT, job_id)
    if not os.path.isdir(jd):
        return jsonify({"error": "No output folder for that job id."}), 404

    bindable = _bindable_chapters(job_id)
    if not bindable:
        return jsonify({"error": "No chapter files found in that job folder."}), 404

    proj = PROJECTS.get(job_id)

    data = request.get_json(force=True) if request.data else {}
    make_video = data.get("make_video", False)
    audio_fmt = data.get("format", "mp3")
    sub_mode = (data.get("subtitles") or "none").lower()

    # Optional: only include a subset of chapters (by their 1-based position in
    # the full list). Lets the user drop chapters (e.g. to fit YouTube's 12-hour
    # limit) before binding. Filtering by the chapter's own index — not its order
    # among narrated files — keeps these in step with the include panel.
    selected = data.get("selected_chapters")
    if selected:
        sel = set(int(x) for x in selected)
        bindable = [b for b in bindable if b["index"] in sel]
        if not bindable:
            return jsonify({"error": "No chapters selected."}), 400

    chapter_files = [(b["title"], b["file"]) for b in bindable]

    # Book title for descriptive output filenames (from project or meta.json).
    rec_title = (proj or {}).get("title")
    if not rec_title:
        meta_path = os.path.join(jd, "meta.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, encoding="utf-8") as mf:
                    rec_title = json.load(mf).get("title")
            except Exception:
                rec_title = None
    rec_base = _output_basename(rec_title)
    rec_yt = _youtube_basename(rec_title)

    def stream():
        import time
        audio_out = os.path.join(jd, f"{rec_base}.{audio_fmt}")
        yield _sse({"type": "bind_progress", "stage": "combine",
                    "message": "Combining existing chapter files…"})
        try:
            result = combine_chapters(chapter_files, audio_out, fmt=audio_fmt)
        except Exception as e:
            yield _sse({"type": "bind_error", "message": f"Combine failed: {e}"})
            return

        timestamps = build_youtube_timestamps(result["markers"])
        ts_name = f"{rec_yt}.txt"
        with open(os.path.join(jd, ts_name), "w",
                  encoding="utf-8") as f:
            f.write(timestamps)

        # Exact subtitles (.srt) from the narrator's per-chunk timing.
        sub_name = None
        sub_path = None
        if sub_mode in ("soft", "burn"):
            try:
                subs = [{"path": p, "start_ms": result["markers"][i][1]}
                        for i, (t, p) in enumerate(chapter_files)]
                srt_path = os.path.join(
                    jd, rec_yt.replace("youtube-chapters-", "subtitles-", 1) + ".srt")
                sub_name = write_subtitles(subs, srt_path)
                if sub_name:
                    sub_path = srt_path
            except Exception:
                sub_name = None

        # Clickable chapter index for playing the video from Google Drive.
        drive_name = rec_yt.replace("youtube-chapters-",
                                    "drive-chapters-", 1) + ".html"
        try:
            with open(os.path.join(jd, drive_name), "w",
                      encoding="utf-8") as f:
                f.write(build_drive_chapter_page(
                    result["markers"], rec_title, result.get("total_ms")))
        except Exception:
            drive_name = None

        payload = {
            "type": "bind_done",
            "audio_file": os.path.basename(audio_out),
            "timestamps": timestamps,
            "timestamps_file": ts_name,
            "drive_chapters_file": drive_name,
            "subtitles_file": sub_name,
            "chapters_found": len(chapter_files),
        }

        if make_video:
            if not ensure_ffmpeg():
                payload["video_error"] = "ffmpeg not found on PATH."
            else:
                image = (proj or {}).get("cover_image")
                if not image:
                    covers = glob.glob(os.path.join(jd, "cover.*"))
                    covers = [c for c in covers
                              if not c.endswith("_prepared.jpg")]
                    image = covers[0] if covers else None
                if not image:
                    payload["video_error"] = "No cover image found. Upload one and retry."
                else:
                    video_out = os.path.join(jd, f"{rec_base}.mp4")
                    vstate = {"frac": 0.0, "done": False, "err": None}

                    def vcb(frac):
                        vstate["frac"] = frac

                    def vwork():
                        try:
                            build_video(audio_out, image, video_out,
                                        markers=result["markers"],
                                        total_ms=result["total_ms"],
                                        progress_callback=vcb,
                                        subtitle_path=sub_path,
                                        subtitle_mode=sub_mode)
                        except Exception as e:
                            vstate["err"] = str(e)
                        finally:
                            vstate["done"] = True

                    t_video = time.time()
                    vt = threading.Thread(target=vwork, daemon=True)
                    vt.start()
                    yield _sse({"type": "bind_progress", "stage": "video",
                                "message": "Building the MP4 video…", "frac": 0.0})
                    while not vstate["done"]:
                        time.sleep(1.0)
                        elapsed = time.time() - t_video
                        fr = vstate["frac"]
                        eta = (elapsed / fr - elapsed) if fr > 0.01 else None
                        yield _sse({"type": "bind_progress", "stage": "video",
                                    "message": "Building the MP4 video…",
                                    "frac": round(fr, 3),
                                    "eta_sec": round(eta) if eta else None})
                    if vstate["err"]:
                        payload["video_error"] = vstate["err"]
                    else:
                        payload["video_file"] = os.path.basename(video_out)

        yield _sse(payload)
        yield _sse({"type": "done"})

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


def _undouble_text(text):
    """If a chapter's text is exactly its content twice over, return the single
    copy. Otherwise return the text unchanged.

    An older parser bug emitted every block twice (a container element and its
    children each contributed the same words), so chapters got narrated twice.
    Runs created before that fix have the doubled text baked into their saved
    meta.json, so resuming them would keep reading everything twice. This
    detects that exact shape and repairs it.

    Deliberately conservative: it only strips when the two halves match after
    whitespace normalisation, so a book that legitimately repeats a passage
    (a refrain, a quoted epigraph) is left alone.
    """
    t = (text or "").strip()
    if len(t) < 80:            # too short to judge safely
        return text
    norm = re.sub(r"\s+", " ", t)
    n = len(norm)
    if n % 2:
        # Odd length: the split point falls between the halves' separator.
        # Try both roundings before giving up.
        candidates = (n // 2, n // 2 + 1)
    else:
        candidates = (n // 2,)
    for half in candidates:
        a, b = norm[:half].strip(), norm[half:].strip()
        if a and a == b:
            # The halves match. Now cut the RAW text (not the normalised copy)
            # so paragraph breaks survive — they affect narration pacing. Walk
            # the raw text accumulating non-space characters until we've seen as
            # many as the first half contains; that's the true split point.
            target = len(re.sub(r"\s+", "", a))
            seen = 0
            for i, chpos in enumerate(t):
                if not chpos.isspace():
                    seen += 1
                if seen == target:
                    first = t[:i + 1].strip()
                    # Only trust the cut if the remainder really is the same
                    # text again (guards against an unlucky match).
                    rest = t[i + 1:].strip()
                    if (re.sub(r"\s+", " ", first) ==
                            re.sub(r"\s+", " ", rest)):
                        return first
                    break
            return a
    return text


def _repair_doubled_chapters(chapters):
    """De-duplicate any chapter whose text was doubled by the old parser bug.

    Returns (fixed_count, cid_remap) where cid_remap maps each repaired
    chapter's OLD cid -> its NEW cid. The remap matters: a chapter's identity is
    a hash of its text, so repairing the text changes the cid. Without carrying
    the old cid across, every already-narrated chapter would look unnarrated and
    the whole book would be re-recorded.
    """
    fixed = 0
    remap = {}
    for c in chapters:
        original = c.get("text") or ""
        repaired = _undouble_text(original)
        if repaired and repaired != original:
            old_cid = c.get("cid") or _chapter_cid(original)
            c["text"] = repaired
            c["cid"] = _chapter_cid(repaired)
            remap[old_cid] = c["cid"]
            fixed += 1
    return fixed, remap


@app.route("/restore/<job_id>", methods=["POST"])
def restore(job_id):
    """Load a previous run's chapters back into memory from its meta.json so it
    can be resumed (narrate skips chapters already on disk) or bound. Returns
    the job's title, chapter count, and how many are already rendered."""
    import glob
    jd = os.path.join(OUTPUT, job_id)
    meta_path = os.path.join(jd, "meta.json")
    if not os.path.isdir(jd) or not os.path.exists(meta_path):
        return jsonify({"error": "That run can't be restored (no metadata "
                                 "saved). You can still bind its chapters."}), 404
    try:
        with open(meta_path, encoding="utf-8") as mf:
            meta = json.load(mf)
    except Exception as e:
        return jsonify({"error": f"Could not read run metadata: {e}"}), 400

    chapters = meta.get("chapters")
    if not chapters:
        return jsonify({"error": "This run predates resume support, so its "
                                 "chapter text wasn't saved. You can still "
                                 "bind the chapters already narrated."}), 400

    PROJECTS[job_id] = {
        "title": meta.get("title"),
        "author": meta.get("author"),
        "chapters": chapters,
    }
    # Give every chapter its stable identity (older runs predate cids) so resume
    # can recognise what's already narrated regardless of position.
    _ensure_cids(PROJECTS[job_id]["chapters"])

    # Runs created before the parser fix have every chapter's text saved TWICE,
    # so resuming them would narrate everything twice over. Repair the saved
    # text here, and carry the ledger across to the new cids so the chapters
    # already on disk still count as done (repairing the text changes the cid).
    repaired, remap = _repair_doubled_chapters(PROJECTS[job_id]["chapters"])
    if repaired:
        ledger = _load_ledger(jd)
        if ledger:
            for old_cid, new_cid in remap.items():
                if old_cid in ledger and new_cid not in ledger:
                    ledger[new_cid] = ledger[old_cid]
            _save_ledger(jd, ledger)
        # Persist the repaired text so the job stays fixed from now on.
        try:
            meta["chapters"] = PROJECTS[job_id]["chapters"]
            meta["chapter_titles"] = [c.get("title") for c
                                      in PROJECTS[job_id]["chapters"]]
            with open(meta_path, "w", encoding="utf-8") as mf:
                json.dump(meta, mf, ensure_ascii=False)
        except Exception:
            pass

    # Build/refresh the ledger from whatever files are already on disk.
    _migrate_ledger(jd, PROJECTS[job_id]["chapters"])
    # If the run saved its voice settings, restore the speaker reference too so
    # narration can resume with the identical voice.
    vs = meta.get("voice_settings") or {}
    if vs.get("builtin_voice"):
        spec = (ENGINE_CATALOG.get("chatterbox", {})
                .get("builtin_voices", {}).get(vs["builtin_voice"]))
        if spec:
            PROJECTS[job_id]["speaker_wav"] = _builtin_reference_path(
                vs["builtin_voice"], spec)
    # A user-uploaded voice sample, if present on disk.
    sample = os.path.join(jd, "voice_sample.wav")
    if os.path.exists(sample):
        PROJECTS[job_id]["speaker_wav"] = sample

    # "Already done" = chapters whose narration is recognised by identity, not
    # merely how many files sit in the folder (which may include orphans from a
    # reordered/edited list). This is what drives the "stopped partway" message.
    done = len(_bindable_chapters(job_id))
    return jsonify({"ok": True, "job_id": job_id, "title": meta.get("title"),
                    "total_chapters": len(chapters), "already_done": done,
                    "repaired_chapters": repaired,
                    "voice_settings": vs})


@app.route("/jobs")
def list_jobs():
    """List job folders on disk that have rendered chapter files, so a user
    can recover a finished-but-unbound run after a restart. Includes the book
    title, original filename, and creation time from each folder's meta.json
    when available, so the picker is human-readable."""
    import glob
    jobs = []
    if os.path.isdir(OUTPUT):
        for name in os.listdir(OUTPUT):
            jd = os.path.join(OUTPUT, name)
            if not os.path.isdir(jd) or name.startswith("_"):
                continue
            chs = glob.glob(os.path.join(jd, "chapter_*.wav")) or \
                  glob.glob(os.path.join(jd, "chapter_*.mp3"))
            if not chs:
                continue

            title = author = epub_filename = created = None
            total_chapters = None
            has_text = False
            meta_path = os.path.join(jd, "meta.json")
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, encoding="utf-8") as mf:
                        m = json.load(mf)
                    title = m.get("title")
                    author = m.get("author")
                    epub_filename = m.get("epub_filename")
                    created = m.get("created")
                    # Total chapters expected, and whether resume is possible.
                    if m.get("chapter_titles"):
                        total_chapters = len(m["chapter_titles"])
                    if m.get("chapters"):
                        has_text = True
                        total_chapters = len(m["chapters"])
                except Exception:
                    pass
            # Fallbacks if meta is missing (older runs): use the .epub on disk.
            if not epub_filename:
                epubs = glob.glob(os.path.join(jd, "*.epub"))
                if epubs:
                    epub_filename = os.path.basename(epubs[0])
            if not created:
                try:
                    import datetime
                    ts = os.path.getmtime(chs[0])
                    created = datetime.datetime.fromtimestamp(ts).isoformat(
                        timespec="seconds")
                except Exception:
                    created = None

            done = len(chs)
            # "Complete" if we know the total and have rendered them all (or we
            # don't know the total but something is bound already).
            # The combined audiobook now uses a descriptive name (<book>-<date>),
            # so detect any non-chapter audio/video output rather than a fixed
            # "audiobook.*" name.
            bound_files = []
            for pat in ("*.mp3", "*.mp4", "*.m4a", "*.wav"):
                for fp in glob.glob(os.path.join(jd, pat)):
                    bn = os.path.basename(fp).lower()
                    if (bn.startswith("chapter_") or bn.startswith("voice_sample")
                            or bn.startswith("_calib")):
                        continue
                    bound_files.append(fp)
            already_bound = bool(bound_files)
            complete = (total_chapters is not None and done >= total_chapters)

            jobs.append({
                "job_id": name,
                "chapters": done,
                "total_chapters": total_chapters,
                "complete": complete,
                "can_resume": has_text and not complete,
                "already_bound": already_bound,
                "title": title,
                "author": author,
                "epub_filename": epub_filename,
                "created": created,
                "folder": jd,
            })

    # Newest first so the most recent run is at the top of the picker.
    jobs.sort(key=lambda j: j.get("created") or "", reverse=True)
    return jsonify({"jobs": jobs, "output_dir": OUTPUT})


@app.route("/cover/<job_id>", methods=["POST"])
def upload_cover(job_id):
    f = request.files.get("cover")
    if not f:
        return jsonify({"error": "No image."}), 400
    # Save to the job folder on disk. Works even if the job isn't loaded in
    # memory (e.g. a restored run being bound), since binding looks for cover.*
    # on disk. Updates the in-memory project too if it exists.
    jd = _job_dir(job_id)
    ext = os.path.splitext(f.filename)[1] or ".jpg"
    path = os.path.join(jd, f"cover{ext}")
    f.save(path)
    proj = PROJECTS.get(job_id)
    if proj:
        proj["cover_image"] = path
    return jsonify({"ok": True})


@app.route("/download/<job_id>/<path:filename>")
def download(job_id, filename):
    jd = os.path.join(OUTPUT, job_id)
    if not os.path.isdir(jd):
        abort(404)
    return send_from_directory(jd, filename, as_attachment=True)


@app.route("/audio/<job_id>/<path:filename>")
def audio(job_id, filename):
    """Serve audio inline (not as a download) for in-browser playback."""
    jd = os.path.join(OUTPUT, job_id)
    if not os.path.isdir(jd):
        abort(404)
    return send_from_directory(jd, filename, as_attachment=False)


def _open_chrome(url):
    """Open the app in Chrome (falls back to the default browser)."""
    import sys
    import shutil
    import subprocess
    import webbrowser

    # Common Chrome locations / commands per OS.
    candidates = []
    if sys.platform == "darwin":
        candidates = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    elif sys.platform.startswith("win"):
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
    else:  # linux
        candidates = ["google-chrome", "google-chrome-stable", "chromium",
                      "chromium-browser"]

    for c in candidates:
        path = c if os.path.exists(c) else shutil.which(c)
        if path:
            try:
                subprocess.Popen([path, url])
                return
            except Exception:
                pass

    # Fallback: whatever the system default browser is.
    webbrowser.open(url)


def _keep_full_speed():
    """Stop Windows from throttling Parroty when its window isn't focused.

    The classic symptom — GPU drops to ~10% the moment the console loses focus,
    snaps back to full speed when you click it — is Windows applying *Power
    Throttling* (EcoQoS) to background processes. EcoQoS caps the CPU's
    execution speed, and because a CPU thread is what launches the GPU's work,
    the GPU starves between kernels. Raising priority alone doesn't fix it; the
    process has to explicitly opt OUT of execution-speed throttling. We also
    raise priority, hold a high timer resolution, and tell Windows the system
    must stay awake.

    IMPORTANT: in low-memory mode the actual GPU work runs in the narration
    *worker* process, so this must be called there too (it is). Best-effort;
    a clean no-op on non-Windows.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        hproc = kernel32.GetCurrentProcess()

        # (1) THE FIX: opt out of EcoQoS power throttling. ControlMask selects
        # the throttle to manage; StateMask=0 turns it OFF (run full speed).
        # Two separate calls so the critical execution-speed opt-out still
        # applies even on Windows builds that don't know the newer timer bit.
        class _PPTS(ctypes.Structure):
            _fields_ = [("Version", wintypes.ULONG),
                        ("ControlMask", wintypes.ULONG),
                        ("StateMask", wintypes.ULONG)]
        try:
            kernel32.SetProcessInformation.argtypes = [
                wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            kernel32.SetProcessInformation.restype = wintypes.BOOL
        except Exception:
            pass
        PROCESS_POWER_THROTTLING = 4
        VERSION = 1
        EXECUTION_SPEED = 0x1
        IGNORE_TIMER_RESOLUTION = 0x4
        for ctrl in (EXECUTION_SPEED, IGNORE_TIMER_RESOLUTION):
            try:
                st = _PPTS(VERSION, ctrl, 0)
                kernel32.SetProcessInformation(
                    hproc, PROCESS_POWER_THROTTLING,
                    ctypes.byref(st), ctypes.sizeof(st))
            except Exception:
                pass

        # (2) Raise scheduling priority so background scheduling can't starve it.
        try:
            kernel32.SetPriorityClass(hproc, 0x00000080)  # HIGH_PRIORITY_CLASS
        except Exception:
            pass

        # (3) Hold a 1 ms timer resolution so background timer coalescing doesn't
        # slow the loop that feeds the GPU.
        try:
            ctypes.WinDLL("winmm").timeBeginPeriod(1)
        except Exception:
            pass

        # (4) Keep the system (and display logic) from idling the work down.
        try:
            ES_CONTINUOUS = 0x80000000
            ES_SYSTEM_REQUIRED = 0x00000001
            kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        except Exception:
            pass
    except Exception:
        pass


# Backwards-compatible alias (older name used elsewhere).
_boost_process_priority = _keep_full_speed


def _disable_windows_quickedit():
    """On Windows, turn off the console's QuickEdit Mode. With QuickEdit on
    (the default), clicking in the window — or it losing focus when minimized —
    puts the console into a selection state that PAUSES the running process
    until a key is pressed. That freezes narration (GPU drops to zero) whenever
    the window is minimized. Disabling it keeps the process running regardless
    of window focus. No-op on non-Windows systems."""
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        STD_INPUT_HANDLE = -10
        ENABLE_QUICK_EDIT_MODE = 0x0040
        ENABLE_EXTENDED_FLAGS = 0x0080
        ENABLE_MOUSE_INPUT = 0x0010
        h = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        mode = wintypes.DWORD()
        if kernel32.GetConsoleMode(h, ctypes.byref(mode)):
            new_mode = (mode.value | ENABLE_EXTENDED_FLAGS) & ~ENABLE_QUICK_EDIT_MODE
            new_mode &= ~ENABLE_MOUSE_INPUT
            kernel32.SetConsoleMode(h, new_mode)
    except Exception:
        pass


if __name__ == "__main__":
    import sys
    import threading

    # When launched windowless (pythonw.exe via run_hidden.bat) there is no
    # console: sys.stdout/stderr can be None and any print would crash. Send all
    # output to parroty.log — the same file run.bat's Tee writes for the visible
    # console — so hidden mode logs identically and never dies on a print.
    if os.environ.get("PARROTY_HIDDEN") == "1" or sys.stdout is None:
        try:
            _logf = open(os.path.join(BASE, "parroty.log"), "a",
                         buffering=1, encoding="utf-8", errors="replace")
            sys.stdout = _logf
            sys.stderr = _logf
        except Exception:
            pass

    # Prevent the Windows console from pausing the app when minimized/clicked.
    _disable_windows_quickedit()
    # Keep running at full speed in the background (opt out of EcoQoS throttling,
    # raise priority, hold timer resolution, keep the system awake).
    _keep_full_speed()

    url = "http://127.0.0.1:5000"
    # Auto-open Chrome once the server is up. Set PARROTY_NO_BROWSER=1 to
    # skip this (e.g. if you prefer to open the page yourself).
    suppress = os.environ.get("PARROTY_NO_BROWSER") == "1"
    if not suppress and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        threading.Timer(1.2, _open_chrome, args=[url]).start()

    # Reloader and debug off: we run detached/in the background (pythonw), where
    # the debugger/reloader can misbehave without a console. Errors still go to
    # the log file. threaded=True keeps SSE streaming responsive.
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False,
            threaded=True)
