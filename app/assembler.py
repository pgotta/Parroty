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
    """FFMETADATA1 chapter block so players get real chapter bookmarks."""
    lines = [";FFMETADATA1"]
    for i, (title, start_ms) in enumerate(markers):
        end_ms = markers[i + 1][1] if i + 1 < len(markers) else total_ms
        safe = title.replace("=", " ").replace("\n", " ")
        lines += [
            "[CHAPTER]", "TIMEBASE=1/1000",
            f"START={int(start_ms)}", f"END={int(end_ms)}", f"title={safe}",
        ]
    return "\n".join(lines) + "\n"


_DRIVE_PAGE_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ — Google Drive chapters</title>
<style>
  :root{ --paper:#efe7d6; --card:#e7ddc8; --ink:#2b2117; --muted:#7a6f5d;
         --rule:#d6c9af; --accent:#7c2d2d; --ok:#3f7d4f; }
  *{ box-sizing:border-box; }
  body{ margin:0; background:var(--paper); color:var(--ink);
        font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
  .wrap{ max-width:760px; margin:0 auto; padding:32px 20px 60px; }
  h1{ font-family:Georgia,"Times New Roman",serif; font-size:1.9rem; margin:0 0 2px; }
  .sub{ color:var(--muted); margin:0 0 22px; font-style:italic; }
  ol.how{ background:var(--card); border:1px solid var(--rule); border-radius:8px;
          padding:14px 14px 14px 34px; margin:0 0 18px; }
  ol.how li{ margin:4px 0; }
  .row{ display:flex; gap:8px; margin:0 0 8px; flex-wrap:wrap; }
  #link{ flex:1; min-width:240px; font-family:ui-monospace,Menlo,Consolas,monospace;
         font-size:.86rem; padding:11px 12px; border:1px solid var(--rule);
         border-radius:6px; background:#fbf7ec; color:var(--ink); }
  button{ font:inherit; font-weight:600; cursor:pointer; border-radius:6px;
          border:1px solid var(--accent); background:var(--accent); color:#fff;
          padding:11px 16px; }
  button.ghost{ background:transparent; color:var(--accent); }
  button:hover{ filter:brightness(1.06); }
  .status{ min-height:20px; font-size:.9rem; margin:6px 0 0; }
  .status.ok{ color:var(--ok); } .status.err{ color:var(--accent); }
  .toolbar{ display:flex; align-items:center; gap:12px; margin:16px 0 6px; }
  .muted{ color:var(--muted); font-size:.85rem; }
  ul.chapters{ list-style:none; margin:8px 0 0; padding:0;
               border:1px solid var(--rule); border-radius:8px; overflow:hidden; }
  ul.chapters li{ display:flex; align-items:baseline; gap:12px; padding:9px 14px;
                  border-top:1px solid var(--rule); background:var(--card); }
  ul.chapters li:first-child{ border-top:none; }
  .ts{ font-family:ui-monospace,Menlo,Consolas,monospace; font-size:.8rem;
       color:var(--muted); min-width:64px; }
  a.ti{ color:var(--accent); text-decoration:none; font-weight:600; }
  a.ti:hover{ text-decoration:underline; }
  span.ti{ color:var(--muted); }
  .foot{ color:var(--muted); font-size:.82rem; margin-top:22px; }
  code{ background:#fbf7ec; border:1px solid var(--rule); border-radius:4px; padding:0 4px; }
</style></head><body>
<div class="wrap">
  <h1>🔖 __TITLE__</h1>
  <p class="sub">Clickable chapters for playback from Google Drive</p>
  <ol class="how">
    <li>Upload your audiobook <strong>.mp4</strong> to Google Drive and let it finish processing.</li>
    <li>Right-click it → <strong>Share</strong> → <strong>Copy link</strong> (set "Anyone with the link" to view if you'll share it).</li>
    <li>Paste that link below. Each chapter turns into a link that opens the video at its start time.</li>
  </ol>
  <div class="row">
    <input id="link" type="text" autocomplete="off"
           placeholder="https://drive.google.com/file/d/.../view?usp=sharing">
    <button id="go">Build chapter links</button>
  </div>
  <div id="status" class="status"></div>
  <div class="toolbar" id="toolbar" hidden>
    <button id="copyall" class="ghost">Copy all links</button>
    <span class="muted" id="count"></span>
  </div>
  <ul id="list" class="chapters"></ul>
  <p class="foot">Made by Parroty. Google Drive's player has no chapter menu, so each chapter
    is a link that opens the video at its start time (the <code>?t=</code> in the URL). The same
    chapter marks are also embedded in the file itself, so a desktop player like VLC shows a real
    chapter menu if you download it.</p>
</div>
<script>
const CH = __DATA__;
const $ = id => document.getElementById(id);
function fmt(s){ const h=Math.floor(s/3600), m=Math.floor((s%3600)/60), x=s%60;
  return (h>0 ? h+":"+String(m).padStart(2,"0") : ""+m) + ":" + String(x).padStart(2,"0"); }
function extractId(u){
  u=(u||"").trim();
  let m=u.match(/\\/d\\/([A-Za-z0-9_-]{10,})/) || u.match(/[?&]id=([A-Za-z0-9_-]{10,})/);
  if(m) return m[1];
  if(/^[A-Za-z0-9_-]{20,}$/.test(u)) return u;
  return null;
}
let FILE_ID=null;
function linkFor(t){ return "https://drive.google.com/file/d/"+FILE_ID+"/view?t="+t; }
function render(){
  const ul=$("list"); ul.innerHTML="";
  CH.forEach((c,i)=>{
    const li=document.createElement("li");
    const ts=document.createElement("span"); ts.className="ts"; ts.textContent=fmt(c.t);
    let node;
    if(FILE_ID){ node=document.createElement("a"); node.href=linkFor(c.t);
      node.target="_blank"; node.rel="noopener"; }
    else { node=document.createElement("span"); }
    node.className="ti"; node.textContent=c.title || ("Chapter "+(i+1));
    li.appendChild(ts); li.appendChild(node); ul.appendChild(li);
  });
  $("count").textContent=CH.length+" chapters";
  $("toolbar").hidden=!FILE_ID;
}
function build(){
  const id=extractId($("link").value);
  if(!id){ $("status").className="status err";
    $("status").textContent="That doesn't look like a Google Drive link — paste the full 'Copy link' URL.";
    FILE_ID=null; render(); return; }
  FILE_ID=id; $("status").className="status ok";
  $("status").textContent="\\u2713 Linked. Click any chapter to open the video at that point.";
  render();
}
$("go").addEventListener("click", build);
$("link").addEventListener("keydown", e=>{ if(e.key==="Enter") build(); });
$("copyall").addEventListener("click", ()=>{
  if(!FILE_ID) return;
  const lines=CH.map((c,i)=>fmt(c.t)+"  "+(c.title||("Chapter "+(i+1)))+"  "+linkFor(c.t));
  navigator.clipboard.writeText(lines.join("\\n")).then(()=>{
    $("status").className="status ok"; $("status").textContent="\\u2713 All "+CH.length+" links copied.";
  });
});
render();
</script></body></html>
"""


def build_drive_chapter_page(markers: list, book_title: str = "",
                             total_ms: int = None) -> str:
    """A self-contained HTML page that turns a Google Drive video share link into
    a clickable chapter index.

    Google Drive's web player has no chapter menu, but its video URLs accept a
    ?t=<seconds> start time, so each chapter can be a link that opens the video
    at that point. The chapter titles/times are baked in; the user pastes their
    Drive share link once and every chapter becomes clickable. No external
    dependencies — it works opened straight from disk.
    """
    import json as _json
    import html as _html
    data = []
    for i, (title, start_ms) in enumerate(markers):
        data.append({"t": max(0, int(start_ms // 1000)),
                     "title": title or f"Chapter {i + 1}"})
    # Embed safely inside <script> (escape any "</" so it can't close the tag).
    data_js = _json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    title_txt = _html.escape(book_title or "Audiobook")
    return (_DRIVE_PAGE_TEMPLATE
            .replace("__TITLE__", title_txt)
            .replace("__DATA__", data_js))


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
                progress_callback=None, subtitle_path: str = None,
                subtitle_mode: str = "none") -> str:
    """Combine a static image + audio into an mp4 using ffmpeg.

    If markers are supplied, embeds chapter metadata into the file too.
    subtitle_mode: 'none' | 'soft' (toggleable track, like VLC) | 'burn'
    (rendered permanently into the picture). For 'burn' we raise the frame rate
    so cue timing isn't quantized to whole seconds.
    If progress_callback is given, it's called with a 0..1 fraction as the
    encode advances (parsed from ffmpeg's -progress output).
    Raises RuntimeError with ffmpeg's stderr if the encode fails.
    """
    work_dir = os.path.dirname(out_path)
    image_path = _prepare_cover(image_path, work_dir)

    burn = (subtitle_mode == "burn" and subtitle_path and os.path.exists(subtitle_path))
    soft = (subtitle_mode == "soft" and subtitle_path and os.path.exists(subtitle_path))
    fps = 10 if burn else 1            # smoother cue timing when burning

    meta_file = None
    if markers and total_ms is not None:
        meta_file = out_path + ".ffmeta.txt"
        with open(meta_file, "w", encoding="utf-8") as f:
            f.write(build_ffmetadata(markers, total_ms))

    cmd = [
        "ffmpeg", "-y",
        # A static cover needs only a very low frame rate. Encoding 1 fps
        # instead of the default ~25 cuts the work by ~25x with no visible
        # difference (the image never changes). Burned subtitles bump this up.
        "-loop", "1", "-framerate", str(fps), "-i", image_path,
        "-i", audio_path,
    ]
    idx = 2
    meta_idx = None
    if meta_file:
        cmd += ["-i", meta_file]
        meta_idx = idx
        idx += 1
    subs_idx = None
    if soft:
        cmd += ["-i", subtitle_path]
        subs_idx = idx
        idx += 1

    if meta_idx is not None:
        cmd += ["-map_metadata", str(meta_idx), "-map_chapters", str(meta_idx)]
    cmd += ["-map", "0:v", "-map", "1:a"]
    if subs_idx is not None:
        cmd += ["-map", f"{subs_idx}:s"]

    vf = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    if burn:
        # bare filename resolved via cwd=work_dir (avoids Windows path/colon
        # quirks in the subtitles filter)
        vf += f",subtitles=filename='{os.path.basename(subtitle_path)}'"

    cmd += [
        "-c:v", "libx264",
        "-preset", "ultrafast", "-tune", "stillimage",
        "-r", str(fps),
        "-pix_fmt", "yuv420p",
        "-vf", vf,
        "-c:a", "aac", "-b:a", "192k",
    ]
    if subs_idx is not None:
        cmd += ["-c:s", "mov_text"]
    cmd += [
        "-shortest",
        # Machine-readable progress on stdout so we can report a % + ETA.
        "-progress", "pipe:1", "-nostats",
        out_path,
    ]

    run_kw = dict(_no_window_kwargs())
    run_kw["cwd"] = work_dir            # so the subtitles filter finds the .srt

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
                                **run_kw)
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
    proc = subprocess.run(cmd, capture_output=True, **run_kw)
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