"""
Standalone narration worker for Parroty's low-memory (process-recycling) mode.

Why this exists: on a memory-tight machine, the surest way to flush RAM and the
Windows page file is to let a process EXIT — the OS then reclaims 100% of its
memory unconditionally, with none of the "Windows keeps it committed" or
"need free RAM to free RAM" problems of an in-process model reload. So this
worker narrates a small BATCH of chapters and then exits; the server respawns a
fresh one for the next batch. Resume is by content-hash ledger, so each batch
picks up exactly where the previous one stopped — nothing is re-narrated.

It prints progress as JSON lines to stdout (one event per line, flushed) which
the server forwards to the browser as SSE. Exit codes:
    0  -> the whole book is finished
    2  -> this batch is done but chapters remain (server should respawn)
    3  -> an error stopped this batch (server reports it; run is resumable)
"""

import os
import sys
import json
import time
import threading
import wave
import struct
import math

# Silence cosmetic progress bars before any model import (mirrors the main
# process). The server also routes this worker's stderr to a log file, but
# setting these up front keeps even that log clean and avoids any tqdm output.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TQDM_DISABLE", "1")


def _emit(ev):
    """Write one event as a JSON line to stdout and flush immediately."""
    try:
        sys.stdout.write(json.dumps(ev) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


class _FakeEngine:
    """A stand-in TTS engine used only when PARROTY_FAKE_TTS is set, so the whole
    recycle-and-resume flow can be tested without the real (heavy) model. Writes
    a short, valid WAV sized roughly to the text length and reports progress."""

    device = "fake"

    def synthesize(self, text, out_path, voice=None, speaker_wav=None,
                   progress_callback=None, **kwargs):
        # Test-only fault injection: if PARROTY_FAKE_FAIL is set and appears in
        # the chapter text, raise — to exercise the halt/resume error path.
        fail = os.environ.get("PARROTY_FAKE_FAIL")
        if fail and fail in (text or ""):
            raise RuntimeError("bad allocation (simulated)")
        out_path = os.path.splitext(out_path)[0] + ".wav"
        # ~1 second of audio per 200 characters, capped, so tests run fast.
        secs = max(0.2, min(2.0, len(text or "") / 4000.0))
        rate = 8000
        nframes = int(secs * rate)
        steps = 5
        with wave.open(out_path, "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            for s in range(steps):
                chunk = nframes // steps
                frames = b"".join(
                    struct.pack("<h", int(3000 * math.sin(2 * math.pi * 220 *
                                (i / rate)))) for i in range(chunk))
                w.writeframes(frames)
                if progress_callback:
                    progress_callback(s + 1, steps)
                time.sleep(0.02)
        # Mirror the real engine: write a one-cue timing sidecar for subtitles.
        try:
            with open(os.path.splitext(out_path)[0] + ".cues.json", "w",
                      encoding="utf-8") as cf:
                json.dump({"sr": rate, "cues": [
                    {"start_ms": 0, "end_ms": int(secs * 1000),
                     "text": (text or "").strip()}]}, cf)
        except Exception:
            pass
        return out_path


def main():
    if len(sys.argv) < 3:
        _emit({"type": "error", "message": "worker: missing job_id/params"})
        sys.exit(3)
    job_id = sys.argv[1]
    params_path = sys.argv[2]
    try:
        with open(params_path, encoding="utf-8") as f:
            P = json.load(f)
    except Exception as e:
        _emit({"type": "error", "message": f"worker: bad params ({e})"})
        sys.exit(3)

    batch = max(1, int(P.get("batch", 10)))

    # Import the server module (defines all the shared helpers). This does NOT
    # start the web server — that only happens under __main__ in server.py.
    from app import server as S

    # This worker is where the GPU work actually happens in low-memory mode, so
    # it must also opt out of Windows background throttling — otherwise the GPU
    # still drops to a crawl when the console loses focus, even though the main
    # process is exempt. (No-op on non-Windows.)
    try:
        S._keep_full_speed()
    except Exception:
        pass

    jd = os.path.join(S.OUTPUT, job_id)
    meta_path = os.path.join(jd, "meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except Exception as e:
        _emit({"type": "error", "message": f"worker: cannot read job ({e})"})
        sys.exit(3)

    chapters = meta.get("chapters") or []
    if not chapters:
        _emit({"type": "error", "message": "worker: no chapters in this job"})
        sys.exit(3)
    S._ensure_cids(chapters)
    ledger = S._migrate_ledger(jd, chapters)

    engine_name = P.get("engine_name") or "chatterbox"
    cfg = P.get("cfg") or {}
    voice = P.get("voice")
    nar_params = P.get("params") or {}
    speaker_wav = P.get("speaker_wav")

    # Spin up the engine (or the fake one for tests).
    fake = bool(os.environ.get("PARROTY_FAKE_TTS"))
    try:
        engine = _FakeEngine() if fake else S.get_engine(engine_name, **cfg)
    except Exception as e:
        _emit({"type": "error", "message": f"Engine init failed: {e}"})
        sys.exit(3)

    dev = getattr(engine, "device", None)
    dev_note = f" (using {dev.upper()})" if dev else ""
    _emit({"type": "loading",
           "message": f"Model ready{dev_note}. Narrating up to {batch} "
                      f"chapter(s) before flushing memory…", "device": dev})

    total_ch = len(chapters)
    sizes = [max(1, len((c.get("text") or ""))) for c in chapters]
    total_size = sum(sizes)
    # Progress already accounted for by chapters finished in earlier batches.
    done_size = sum(sizes[i] for i, c in enumerate(chapters)
                    if S._ledger_file_for(jd, ledger, c["cid"]))

    def out_path(idx, title):
        slug = S._slugify(title, 40)
        if slug and slug != "book":
            return os.path.join(jd, f"chapter_{idx+1:03d}_{slug}.mp3")
        return os.path.join(jd, f"chapter_{idx+1:03d}.mp3")

    narrated = 0
    batch_start = time.time()

    for i, ch in enumerate(chapters):
        cid = ch["cid"]
        title = ch["title"]

        # Already narrated in an earlier batch/run — recognise by identity and
        # skip SILENTLY. After a memory-flush restart, a fresh worker scans from
        # the top of the list to find where to resume; announcing every finished
        # chapter would re-print the whole done list each time. The browser
        # already shows these from when they were first narrated, and the
        # progress bar's position is preserved (done_size is pre-counted above),
        # so we just move on to the next unfinished chapter.
        if S._ledger_file_for(jd, ledger, cid):
            continue

        # Batch full → exit so the OS reclaims all memory; server respawns.
        if narrated >= batch:
            _emit({"type": "batch_done", "complete": False, "narrated": narrated})
            sys.exit(2)

        out = out_path(i, title)
        state = {"frac": 0.0, "done": False, "err": None, "actual": out}

        def cb(cur, tot):
            state["frac"] = (cur / tot) if tot else 0.0

        def work():
            try:
                written = engine.synthesize(ch["text"], out, voice=voice,
                                            speaker_wav=speaker_wav,
                                            progress_callback=cb, **nar_params)
                if written:
                    state["actual"] = written
            except Exception as e:
                state["err"] = str(e)
            finally:
                state["done"] = True

        def run_once():
            state["frac"] = 0.0
            state["done"] = False
            state["err"] = None
            state["actual"] = out
            t = threading.Thread(target=work, daemon=True)
            t.start()
            while not state["done"]:
                time.sleep(0.5)
                overall = (done_size + state["frac"] * sizes[i]) / total_size
                ms = S._mem_stats()
                _emit({"type": "progress", "chapter": i + 1,
                       "total_chapters": total_ch, "chapter_title": title,
                       "frac": round(state["frac"], 3),
                       "overall": round(overall, 3),
                       "mem_avail_gb": round(ms[0], 2) if ms else None,
                       "mem_pct": round(ms[2]) if ms else None})

        run_once()
        # One retry after a memory reclaim, mirroring the in-process path.
        if state["err"]:
            _emit({"type": "loading",
                   "message": f"Chapter {i+1} hit a problem ({state['err']}). "
                              f"Freeing memory and retrying once…"})
            S._reclaim_memory()
            time.sleep(1.0)
            S._reclaim_memory()
            run_once()

        if state["err"]:
            # Remove the broken stub so it isn't mistaken for a finished chapter,
            # log it, and stop this batch. The run stays resumable.
            for ext in (".wav", ".mp3"):
                stub = os.path.splitext(out)[0] + ext
                if os.path.exists(stub):
                    try:
                        os.remove(stub)
                    except OSError:
                        pass
            S._log_book_error(jd, f"Chapter {i+1} ({title}) failed after retry: "
                                  f"{state['err']}. Run halted; resume to continue.")
            _emit({"type": "error",
                   "message": f"Chapter {i+1} ({title}) failed to narrate "
                              f"({state['err']}). Stopped here — your finished "
                              f"chapters are saved. Close other apps to free RAM, "
                              f"then click Resume to continue from chapter {i+1}."})
            sys.exit(3)

        actual_name = os.path.basename(state["actual"])
        ledger[cid] = actual_name
        S._save_ledger(jd, ledger)
        done_size += sizes[i]
        narrated += 1
        _emit({"type": "chapter_done", "chapter": i + 1,
               "total_chapters": total_ch, "chapter_title": title,
               "overall": round(done_size / total_size, 3)})

    # Fell off the end of the list → the whole book is narrated.
    _emit({"type": "batch_done", "complete": True, "narrated": narrated})
    sys.exit(0)


if __name__ == "__main__":
    main()
