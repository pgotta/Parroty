"""
Chatterbox backend (local, free, voice cloning from a sample).

Requires:  pip install chatterbox-tts   (which pulls in torch/torchaudio)
GPU strongly recommended; runs on CPU but slowly. Chatterbox is a cloning
model — it always narrates from a reference clip (`speaker_wav`). When no
sample is supplied it falls back to the model's default voice.

Supported tunables (passed through from the UI):
    exaggeration  - emotional intensity (neutral 0.5)
    cfg_weight    - classifier-free guidance / pacing
    temperature   - sampling variety
"""

import os
import re
import contextlib

# Ask PyTorch's CUDA allocator to return freed blocks to the driver instead of
# holding a large cache. This lowers peak GPU/host memory on constrained
# machines (set before torch is imported anywhere). Harmless on CPU-only setups.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

from ..tts import TTSEngine


@contextlib.contextmanager
def _tqdm_progress(on_frac):
    """Temporarily wrap tqdm so Chatterbox's internal sampling loop reports
    fractional progress (0..1) to `on_frac`.

    Chatterbox shows a "Sampling: N/1000" tqdm bar during generation. We patch
    tqdm.__init__/update/__iter__ to call on_frac(n/total) as it advances, then
    restore the original tqdm on exit. If tqdm isn't present or the internal
    API differs, this is a harmless no-op.
    """
    try:
        import tqdm as _tqdm_mod
    except Exception:
        yield
        return

    Orig = _tqdm_mod.std.tqdm if hasattr(_tqdm_mod, "std") else _tqdm_mod.tqdm

    class _PatchedTqdm(Orig):
        def __init__(self, *a, **k):
            # Disable tqdm's console rendering entirely. It still lets us count
            # internally (we track n ourselves below), but writes nothing to the
            # terminal. This prevents the constant console output that can BLOCK
            # the process on Windows when the window is minimized — which was
            # stalling GPU work. Progress is shown in the browser instead.
            k["disable"] = True
            self._count = 0
            self._total = k.get("total")
            # If total wasn't passed but an iterable was, infer its length.
            if self._total is None and a:
                try:
                    self._total = len(a[0])
                except Exception:
                    self._total = None
            super().__init__(*a, **k)
            self._report()

        def _report(self):
            try:
                if self._total:
                    on_frac(min(1.0, self._count / self._total))
            except Exception:
                pass

        def update(self, n=1):
            r = super().update(n)
            self._count += n
            self._report()
            return r

        def __iter__(self):
            # Support `for x in tqdm(iterable)` usage too.
            for obj in super().__iter__():
                self._count += 1
                self._report()
                yield obj

    # Patch the names Chatterbox is likely to import.
    patched = []
    targets = []
    try:
        targets.append((_tqdm_mod, "tqdm", _tqdm_mod.tqdm))
        _tqdm_mod.tqdm = _PatchedTqdm
    except Exception:
        pass
    if hasattr(_tqdm_mod, "std"):
        try:
            targets.append((_tqdm_mod.std, "tqdm", _tqdm_mod.std.tqdm))
            _tqdm_mod.std.tqdm = _PatchedTqdm
        except Exception:
            pass
    # Some libs do `from tqdm.auto import tqdm`
    try:
        import tqdm.auto as _auto
        targets.append((_auto, "tqdm", _auto.tqdm))
        _auto.tqdm = _PatchedTqdm
    except Exception:
        pass

    try:
        yield
    finally:
        for mod, name, orig in targets:
            try:
                setattr(mod, name, orig)
            except Exception:
                pass


def _sentences(text):
    parts = re.split(r"(?<=[.!?])\s+", text.replace("\n", " "))
    return [p.strip() for p in parts if p.strip()]


def _split_long(sentence, max_chars):
    """Break a single over-long sentence into <=max_chars pieces.

    Chatterbox's text encoder has a fixed maximum input length. Handing it a
    sentence longer than that triggers a CUDA *device-side assert* (an
    out-of-range index inside the kernel), which kills the whole CUDA context —
    the run can't be retried, it has to be restarted. Books hit this with
    unpunctuated run-ons, long list-like sentences, tables of contents, and
    citation blocks, which sentence-splitting alone never breaks up.

    Split at the most natural boundary available, in order of preference:
    clause punctuation, then any whitespace, then (last resort) a hard cut.
    """
    out = []
    rest = sentence.strip()
    while len(rest) > max_chars:
        window = rest[:max_chars]
        cut = -1
        # 1) Prefer a clause boundary (semicolon, colon, comma, dash).
        for sep in ("; ", ": ", ", ", " — ", " - "):
            idx = window.rfind(sep)
            if idx > cut:
                cut = idx + len(sep) - 1
        # 2) Otherwise break at the last space.
        if cut <= 0:
            cut = window.rfind(" ")
        # 3) Otherwise hard-cut (a single unbroken token longer than the limit).
        if cut <= 0:
            cut = max_chars - 1
        piece = rest[:cut + 1].strip()
        if piece:
            out.append(piece)
        rest = rest[cut + 1:].strip()
    if rest:
        out.append(rest)
    return out


def _batch(sentences, max_chars=280):
    """Group sentences into chunks of at most `max_chars` characters.

    Any single sentence longer than max_chars is split first — without that,
    an over-long sentence sails through as one oversized chunk and asserts
    inside the model's CUDA kernel.
    """
    out, buf = [], ""
    for s in sentences:
        for part in (_split_long(s, max_chars) if len(s) > max_chars else [s]):
            if len(buf) + len(part) + 1 > max_chars and buf:
                out.append(buf.strip())
                buf = ""
            buf += " " + part
    if buf.strip():
        out.append(buf.strip())
    return out


def _write_wav(path, tensor, sample_rate):
    """Write a float audio tensor to a 16-bit PCM WAV using the stdlib `wave`
    module. Avoids torchaudio's save backend (TorchCodec) and ffmpeg entirely,
    so it works on any torch version with no extra dependencies.

    `tensor` is shaped [channels, samples] with float values in roughly [-1, 1].
    """
    import wave

    data = tensor.detach().to("cpu")
    if data.dim() == 1:
        data = data.unsqueeze(0)
    channels, _ = data.shape

    # Interleave channels and clamp to [-1, 1], then scale to int16.
    interleaved = data.transpose(0, 1).reshape(-1)        # [samples*channels]
    interleaved = interleaved.clamp(-1.0, 1.0)
    int_samples = (interleaved * 32767.0).round().to("cpu").to(dtype=__import__("torch").int16)
    raw = int_samples.numpy().tobytes()

    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)            # 16-bit
        wf.setframerate(int(sample_rate))
        wf.writeframes(raw)


class _StreamingWavWriter:
    """Append audio chunks to a WAV file one at a time so we never hold a whole
    chapter in RAM. Each chunk's int16 bytes are written immediately and then
    released, keeping memory flat regardless of chapter length."""

    def __init__(self, path, sample_rate, channels=1):
        import wave
        self.wf = wave.open(path, "wb")
        self.wf.setnchannels(channels)
        self.wf.setsampwidth(2)
        self.wf.setframerate(int(sample_rate))
        self.channels = channels

    def append(self, tensor):
        data = tensor.detach().to("cpu")
        if data.dim() == 1:
            data = data.unsqueeze(0)
        interleaved = data.transpose(0, 1).reshape(-1).clamp(-1.0, 1.0)
        int_samples = (interleaved * 32767.0).round().to(
            dtype=__import__("torch").int16)
        self.wf.writeframes(int_samples.numpy().tobytes())

    def close(self):
        try:
            self.wf.close()
        except Exception:
            pass


def gpu_diagnostics():
    """Explain the CUDA/GPU situation so the UI can tell the user what's wrong.

    Returns {cuda_available, torch_built_with_cuda, torch_version, message, fix}.
    The common failure on new GPUs (e.g. RTX 50-series / Blackwell) is that the
    installed torch is the CPU-only wheel, OR a CUDA wheel too old to support
    the card — in both cases is_available() is False and we fall back to CPU.
    """
    info = {"cuda_available": False, "torch_built_with_cuda": False,
            "torch_version": None, "message": "", "fix": ""}
    try:
        import torch
        info["torch_version"] = getattr(torch, "__version__", "?")
        built = getattr(getattr(torch, "version", None), "cuda", None)
        info["torch_built_with_cuda"] = bool(built)
        info["cuda_available"] = bool(torch.cuda.is_available())

        if info["cuda_available"]:
            try:
                info["message"] = (f"GPU detected: "
                                   f"{torch.cuda.get_device_name(0)}.")
            except Exception:
                info["message"] = "GPU detected."
        elif not built:
            # CPU-only wheel installed.
            info["message"] = (
                "Your installed PyTorch is the CPU-only build, so the GPU "
                "can't be used — narration will run on CPU.")
            info["fix"] = (
                "Install a CUDA build of PyTorch. In your venv run:\n"
                "  pip uninstall -y torch torchaudio\n"
                "  pip install torch torchaudio --index-url "
                "https://download.pytorch.org/whl/cu124\n"
                "(For an RTX 50-series / very new GPU you may need the latest "
                "CUDA build — see https://pytorch.org/get-started/locally/ and "
                "pick the newest CUDA option.)")
        else:
            # CUDA wheel present but card not usable (often too-new GPU).
            info["message"] = (
                f"PyTorch was built with CUDA {built}, but no usable GPU was "
                f"found. Your GPU may be newer than this PyTorch build "
                f"supports, so it falls back to CPU.")
            info["fix"] = (
                "Update to the newest PyTorch CUDA build (RTX 50-series needs "
                "a recent one):\n"
                "  pip uninstall -y torch torchaudio\n"
                "  pip install --pre torch torchaudio --index-url "
                "https://download.pytorch.org/whl/nightly/cu126\n"
                "See https://pytorch.org/get-started/locally/ for the current "
                "recommended command.")
    except Exception as e:
        info["message"] = f"PyTorch not installed or failed to load: {e}"
        info["fix"] = ("Install PyTorch — see "
                       "https://pytorch.org/get-started/locally/")
    return info


def detect_devices():
    """Return the list of usable torch devices on this machine, best first.

    Each item: {id, label, available}. 'auto' is always offered.
    Only devices PyTorch can actually use for Chatterbox are reported:
    CUDA (NVIDIA), MPS (Apple Silicon), and CPU. Integrated Intel/AMD GPUs
    are NOT usable by standard PyTorch and are intentionally not listed.
    """
    devices = [{"id": "auto", "label": "Auto (use GPU if available)",
                "available": True}]
    try:
        import torch
        if torch.cuda.is_available():
            try:
                name = torch.cuda.get_device_name(0)
            except Exception:
                name = "NVIDIA GPU"
            devices.append({"id": "cuda", "label": f"NVIDIA GPU — {name}",
                            "available": True})
        mps = getattr(getattr(torch, "backends", None), "mps", None)
        if mps is not None and torch.backends.mps.is_available():
            devices.append({"id": "mps", "label": "Apple GPU (Metal)",
                            "available": True})
    except Exception:
        # torch not installed yet; only CPU/auto can be offered.
        pass
    devices.append({"id": "cpu", "label": "CPU only (slow)", "available": True})
    return devices


def _resolve_device(requested):
    """Map a requested device id ('auto'/'cuda'/'mps'/'cpu') to a real torch
    device string, falling back safely if the choice isn't available."""
    import torch
    has_cuda = torch.cuda.is_available()
    has_mps = bool(getattr(getattr(torch, "backends", None), "mps", None)
                   and torch.backends.mps.is_available())

    req = (requested or "auto").lower()
    if req == "cuda":
        return "cuda" if has_cuda else "cpu"
    if req == "mps":
        return "mps" if has_mps else "cpu"
    if req == "cpu":
        return "cpu"
    # auto: prefer CUDA, then MPS, then CPU
    if has_cuda:
        return "cuda"
    if has_mps:
        return "mps"
    return "cpu"


class ChatterboxEngine(TTSEngine):
    supports_cloning = True

    def __init__(self, use_gpu=None, device=None, variant="standard", **_):
        # `device` (new) takes precedence; `use_gpu` kept for back-compat.
        if device is None:
            device = "auto" if (use_gpu is None or use_gpu) else "cpu"
        resolved = _resolve_device(device)
        self.device = resolved
        self.variant = (variant or "standard").lower()

        if self.variant == "turbo":
            # Turbo: ~350M params, distilled to 1 sampling step — much faster,
            # purpose-built for narration. Ignores cfg/exaggeration.
            try:
                from chatterbox.tts_turbo import ChatterboxTurboTTS
                self.model = ChatterboxTurboTTS.from_pretrained(device=resolved)
            except ImportError as e:
                raise RuntimeError(
                    "The Turbo model isn't available in your installed "
                    "chatterbox-tts version. Update it with "
                    "'pip install -U chatterbox-tts', or use the Standard "
                    "model instead."
                ) from e
        else:
            from chatterbox.tts import ChatterboxTTS
            self.model = ChatterboxTTS.from_pretrained(device=resolved)

    def synthesize(self, text, out_path, voice=None, speaker_wav=None,
                   exaggeration=0.5, cfg_weight=0.5, temperature=0.8,
                   progress_callback=None, **_):
        import torch

        # Only pass kwargs the installed version supports, to stay compatible
        # across chatterbox-tts releases. Turbo ignores cfg/exaggeration, so we
        # don't send them (avoids warnings).
        gen_kwargs = {}
        if self.variant != "turbo":
            try:
                exaggeration = float(exaggeration)
                cfg_weight = float(cfg_weight)
                temperature = float(temperature)
                gen_kwargs = {
                    "exaggeration": exaggeration,
                    "cfg_weight": cfg_weight,
                    "temperature": temperature,
                }
            except (TypeError, ValueError):
                gen_kwargs = {}

        chunks = _batch(_sentences(text))
        total = len(chunks)

        import gc
        import json
        sr = int(self.model.sr)
        wav_path = os.path.splitext(out_path)[0] + ".wav"
        writer = _StreamingWavWriter(wav_path, sr, channels=1)
        gap = torch.zeros(1, int(sr * 0.25))   # silence between chunks
        gap_samples = int(sr * 0.25)
        cues = []                              # exact subtitle timing per chunk
        cur_samples = 0

        try:
            for idx, chunk in enumerate(chunks):
                kwargs = dict(gen_kwargs)
                if speaker_wav:
                    kwargs["audio_prompt_path"] = speaker_wav

                # Report fine-grained progress *within* this chunk by watching
                # Chatterbox's internal tqdm sampling loop ("Sampling N/1000").
                def chunk_progress(frac_in_chunk):
                    if progress_callback:
                        overall = (idx + max(0.0, min(1.0, frac_in_chunk))) / total
                        progress_callback(overall, 1.0)

                with _tqdm_progress(chunk_progress):
                    try:
                        wav = self.model.generate(chunk, **kwargs)
                    except TypeError:
                        safe = {}
                        if speaker_wav:
                            safe["audio_prompt_path"] = speaker_wav
                        wav = self.model.generate(chunk, **safe)

                # Exact cue timing: this chunk's spoken audio spans
                # [cur_samples, cur_samples + n] before the trailing gap.
                try:
                    n = int(wav.shape[-1])
                except Exception:
                    n = 0
                if n > 0:
                    cues.append({
                        "start_ms": round(cur_samples / sr * 1000.0),
                        "end_ms": round((cur_samples + n) / sr * 1000.0),
                        "text": chunk,
                    })
                    cur_samples += n + gap_samples

                # Write this chunk straight to disk, then release it so memory
                # stays flat no matter how long the chapter is.
                writer.append(wav)
                writer.append(gap)
                del wav

                # Reclaim memory only PERIODICALLY, not every chunk. Calling
                # torch.cuda.empty_cache() after every chunk forces the GPU to
                # release and re-allocate its work memory constantly, which
                # stalls it between chunks and tanks utilization. Streaming each
                # chunk to disk (above) already keeps memory flat, so a light gc
                # every several chunks is plenty.
                if (idx + 1) % 8 == 0:
                    gc.collect()

                if progress_callback:
                    progress_callback((idx + 1) / total, 1.0)
        finally:
            writer.close()

        # Sidecar of exact spoken-chunk timings, so the binder can build a
        # frame-accurate .srt later (it's offset by each chapter's start time).
        try:
            with open(os.path.splitext(out_path)[0] + ".cues.json", "w",
                      encoding="utf-8") as cf:
                json.dump({"sr": sr, "cues": cues}, cf)
        except Exception:
            pass

        # One cleanup at the end of the chapter (including the GPU cache). Doing
        # it here rather than per-chunk lets the GPU stay saturated during the
        # chapter, while still releasing memory between chapters.
        gc.collect()
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

        return wav_path
