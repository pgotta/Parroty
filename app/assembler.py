"""
Assemble final outputs from per-chapter audio files:

  combine_chapters()  -> one continuous audiobook file (mp3/wav)
  build_youtube_timestamps() -> "00:00 Chapter 1" lines for the YT description
  build_video()       -> static image + audio -> mp4 (with chapter metadata)

YouTube auto-creates chapters from timestamps in the *description*, not the
file. The first stamp must be 00:00 and you need at least 3 chapters.
"""

import os
import subprocess

from pydub import AudioSegment


def _no_window_kwargs():
    """Subprocess flags that detach a child process (ffmpeg) from the parent
    console on Windows, so minimizing the console can't throttle or pause it.
    Returns an empty dict on non-Windows systems."""
    if os.name == "nt":
        return {"creationflags": (
            getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) |
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))}
    return {}


def _fmt_timestamp(ms: int) -> str:
    total = int(ms // 1000)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def combine_chapters(chapter_files: list, out_path: str, fmt: str = "mp3",
                     gap_ms: int = 800) -> dict:
    """Concatenate chapter audio files in order.

    chapter_files: list of (title, filepath) tuples, already in order.
    Returns dict with out_path, markers [(title, start_ms)], and total_ms.

    Uses ffmpeg's concat filter to stream the join on disk when ffmpeg is
    available, so the whole audiobook is never held in RAM (important for long
    books on low-memory machines). Falls back to an in-memory pydub join only
    if ffmpeg isn't available.
    """
    # First pass: measure each chapter's duration to build chapter markers.
    # mutagen-free: read duration via ffprobe if present, else pydub per file
    # (one file at a time, released immediately — low memory).
    markers = []
    cursor = 0
    durations = []
    for i, (title, path) in enumerate(chapter_files):
        markers.append((title, cursor))
        dur = _audio_duration_ms(path)
        durations.append(dur)
        cursor += dur
        if i < len(chapter_files) - 1:
            cursor += gap_ms
    total_ms = cursor

    if ensure_ffmpeg():
        try:
            _ffmpeg_concat_with_gaps(chapter_files, out_path, fmt, gap_ms)
            return {"out_path": out_path, "markers": markers,
                    "total_ms": total_ms}
        except Exception:
            pass  # fall back to in-memory

    # Fallback: in-memory concat (higher RAM use; only if ffmpeg missing).
    combined = AudioSegment.silent(duration=0)
    gap = AudioSegment.silent(duration=gap_ms)
    for i, (title, path) in enumerate(chapter_files):
        seg = AudioSegment.from_file(path)
        combined += seg
        if i < len(chapter_files) - 1:
            combined += gap
        del seg
    combined.export(out_path, format=fmt)
    return {"out_path": out_path, "markers": markers, "total_ms": len(combined)}


def _audio_duration_ms(path):
    """Duration of an audio file in ms. Uses ffprobe if available (no full
    decode, low memory), else falls back to loading via pydub."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True)
        if out.returncode == 0 and out.stdout.strip():
            return int(float(out.stdout.strip()) * 1000)
    except Exception:
        pass
    try:
        return len(AudioSegment.from_file(path))
    except Exception:
        return 0


def _ffmpeg_concat_with_gaps(chapter_files, out_path, fmt, gap_ms):
    """Concatenate chapters with a silent gap between each, using ffmpeg's
    concat filter. All inputs are decoded and re-encoded by ffmpeg in one pass,
    streaming on disk — so memory stays low regardless of book length."""
    inputs = []
    for _title, path in chapter_files:
        inputs += ["-i", path]

    n = len(chapter_files)
    gap_sec = gap_ms / 1000.0

    # Build a filter that inserts silence between chapters:
    #   [0:a] [silence] [1:a] [silence] ... [n-1:a] concat
    # Silence is generated with anullsrc, trimmed to gap length.
    filt = []
    concat_inputs = []
    for i in range(n):
        concat_inputs.append(f"[{i}:a]")
        if i < n - 1:
            filt.append(
                f"anullsrc=r=44100:cl=stereo,atrim=duration={gap_sec}[g{i}]")
            concat_inputs.append(f"[g{i}]")
    total_segments = n + (n - 1)
    filt.append("".join(concat_inputs) +
                f"concat=n={total_segments}:v=0:a=1[out]")
    filter_complex = ";".join(filt)

    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", filter_complex, "-map", "[out]"]
    if fmt == "mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", "192k"]
    cmd += [out_path]

    proc = subprocess.run(cmd, capture_output=True, **_no_window_kwargs())
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="ignore")[-500:])
    return out_path


def build_youtube_timestamps(markers: list) -> str:
    """Turn [(title, start_ms)] into newline timestamp text for YouTube."""
    lines = []
    for i, (title, start_ms) in enumerate(markers):
        stamp = "00:00" if i == 0 else _fmt_timestamp(start_ms)
        lines.append(f"{stamp} {title}")
    return "\n".join(lines)


def build_ffmetadata(markers: list, total_ms: int) -> str:
    """FFMETADATA1 chapter block so players (and M4B) get real bookmarks."""
    lines = [";FFMETADATA1"]
    for i, (title, start_ms) in enumerate(markers):
        end_ms = markers[i + 1][1] if i + 1 < len(markers) else total_ms
        safe = title.replace("=", " ").replace("\n", " ")
        lines += [
            "[CHAPTER]", "TIMEBASE=1/1000",
            f"START={int(start_ms)}", f"END={int(end_ms)}", f"title={safe}",
        ]
    return "\n".join(lines) + "\n"


def _prepare_cover(image_path: str, work_dir: str) -> str:
    """Convert any cover image to a clean even-dimensioned JPEG that ffmpeg can
    always read. Handles AVIF/WebP/PNG/etc via Pillow, and ensures width/height
    are even (required by yuv420p/libx264)."""
    import os as _os
    out = _os.path.join(work_dir, "_cover_prepared.jpg")
    try:
        from PIL import Image
        try:
            import pillow_avif  # noqa: F401  (enables AVIF if installed)
        except Exception:
            pass
        img = Image.open(image_path).convert("RGB")
        w, h = img.size
        # ffmpeg's yuv420p needs even dimensions.
        nw, nh = w - (w % 2), h - (h % 2)
        if (nw, nh) != (w, h):
            img = img.crop((0, 0, max(2, nw), max(2, nh)))
        img.save(out, "JPEG", quality=90)
        return out
    except Exception:
        # If Pillow can't handle it, fall back to the original and let ffmpeg try.
        return image_path


def build_video(audio_path: str, image_path: str, out_path: str,
                markers: list = None, total_ms: int = None,
                progress_callback=None) -> str:
    """Combine a static image + audio into an mp4 using ffmpeg.

    If markers are supplied, embeds chapter metadata into the file too.
    If progress_callback is given, it's called with a 0..1 fraction as the
    encode advances (parsed from ffmpeg's -progress output).
    Raises RuntimeError with ffmpeg's stderr if the encode fails.
    """
    work_dir = os.path.dirname(out_path)
    image_path = _prepare_cover(image_path, work_dir)

    meta_file = None
    if markers and total_ms is not None:
        meta_file = out_path + ".ffmeta.txt"
        with open(meta_file, "w", encoding="utf-8") as f:
            f.write(build_ffmetadata(markers, total_ms))

    cmd = [
        "ffmpeg", "-y",
        # A static cover needs only a very low frame rate. Encoding 1 fps
        # instead of the default ~25 cuts the work by ~25x with no visible
        # difference (the image never changes).
        "-loop", "1", "-framerate", "1", "-i", image_path,
        "-i", audio_path,
    ]
    if meta_file:
        cmd += ["-i", meta_file, "-map_metadata", "2", "-map_chapters", "2"]
    cmd += [
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264",
        # 'ultrafast' prioritizes encode speed (slightly larger file) — the
        # right trade for a single still image. '-tune stillimage' optimizes
        # for static content.
        "-preset", "ultrafast", "-tune", "stillimage",
        "-r", "1",                       # output frame rate (matches input)
        "-pix_fmt", "yuv420p",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        # Machine-readable progress on stdout so we can report a % + ETA.
        "-progress", "pipe:1", "-nostats",
        out_path,
    ]

    if progress_callback and total_ms:
        # Stream ffmpeg's progress output and report fraction done.
        # IMPORTANT: ffmpeg writes a lot to stderr. If we only read stdout and
        # let stderr's pipe buffer fill, ffmpeg BLOCKS waiting for stderr to be
        # drained — a deadlock that freezes the encode (and the progress bar).
        # So we drain stderr concurrently in a background thread.
        import threading

        # On Windows, run ffmpeg fully detached from the console window so that
        # minimizing the console can't throttle or pause it. CREATE_NO_WINDOW
        # gives ffmpeg no console of its own; CREATE_NEW_PROCESS_GROUP detaches
        # it from the parent console's control events.
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True,
                                **_no_window_kwargs())
        err_tail = []

        def _drain_stderr():
            try:
                for eline in proc.stderr:
                    err_tail.append(eline)
                    # Keep only the last ~40 lines to bound memory.
                    if len(err_tail) > 40:
                        del err_tail[0]
            except Exception:
                pass

        et = threading.Thread(target=_drain_stderr, daemon=True)
        et.start()

        try:
            for line in proc.stdout:
                line = line.strip()
                if line.startswith("out_time_ms="):
                    try:
                        us = int(line.split("=", 1)[1])
                        frac = max(0.0, min(1.0, (us / 1000.0) / total_ms))
                        progress_callback(frac)
                    except (ValueError, ZeroDivisionError):
                        pass
                elif line == "progress=end":
                    progress_callback(1.0)
        finally:
            proc.wait()
            et.join(timeout=2)
        if meta_file and os.path.exists(meta_file):
            os.unlink(meta_file)
        if proc.returncode != 0:
            raise RuntimeError("ffmpeg failed building the video:\n"
                               + "".join(err_tail)[-800:])
        return out_path

    # No progress callback: simple blocking run.
    proc = subprocess.run(cmd, capture_output=True, **_no_window_kwargs())
    if meta_file and os.path.exists(meta_file):
        os.unlink(meta_file)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="ignore")[-800:]
        raise RuntimeError(f"ffmpeg failed building the video:\n{err}")
    return out_path


def ensure_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
