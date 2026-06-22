"""OpenAI text-to-speech backend (cloud, paid)."""

from ..tts import TTSEngine

# OpenAI TTS has a per-request character cap; we chunk long chapters.
_MAX_CHARS = 4000


def _chunk(text, size=_MAX_CHARS):
    chunks, buf = [], ""
    for para in text.split("\n\n"):
        if len(buf) + len(para) + 2 > size and buf:
            chunks.append(buf.strip())
            buf = ""
        buf += para + "\n\n"
    if buf.strip():
        chunks.append(buf.strip())
    return chunks or [text]


class OpenAIEngine(TTSEngine):
    supports_cloning = False
    builtin_voices = {
        "alloy": "neutral", "echo": "male", "fable": "male",
        "onyx": "male", "nova": "female", "shimmer": "female",
    }

    def __init__(self, api_key=None, model="tts-1-hd", **_):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key) if api_key else OpenAI()
        self.model = model

    def synthesize(self, text, out_path, voice="onyx", speaker_wav=None,
                   progress_callback=None, **_):
        from pydub import AudioSegment
        import io

        pieces = _chunk(text)
        combined = None
        for piece in pieces:
            resp = self.client.audio.speech.create(
                model=self.model, voice=voice, input=piece, response_format="mp3",
            )
            seg = AudioSegment.from_file(io.BytesIO(resp.read()), format="mp3")
            combined = seg if combined is None else combined + seg

        combined.export(out_path, format="mp3")
        if progress_callback:
            progress_callback(1, 1)
        return out_path
