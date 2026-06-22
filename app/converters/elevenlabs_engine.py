"""ElevenLabs text-to-speech backend (cloud, paid, supports cloning)."""

from ..tts import TTSEngine

_MAX_CHARS = 5000


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


class ElevenLabsEngine(TTSEngine):
    supports_cloning = True
    builtin_voices = {
        "Rachel": "female", "Adam": "male",
        "Bella": "female", "Antoni": "male",
    }

    def __init__(self, api_key=None, model="eleven_multilingual_v2", **_):
        from elevenlabs.client import ElevenLabs
        self.client = ElevenLabs(api_key=api_key)
        self.model = model

    def _clone_voice(self, speaker_wav):
        """Create a temporary cloned voice from a sample, return its id."""
        voice = self.client.clone(
            name="audiobook_clone",
            files=[speaker_wav],
            description="Auto-created from user sample.",
        )
        return voice.voice_id

    def synthesize(self, text, out_path, voice="Rachel", speaker_wav=None,
                   progress_callback=None, **_):
        from pydub import AudioSegment
        import io

        voice_id = self._clone_voice(speaker_wav) if speaker_wav else voice

        combined = None
        for piece in _chunk(text):
            audio_iter = self.client.text_to_speech.convert(
                voice_id=voice_id, model_id=self.model,
                text=piece, output_format="mp3_44100_128",
            )
            data = b"".join(audio_iter)
            seg = AudioSegment.from_file(io.BytesIO(data), format="mp3")
            combined = seg if combined is None else combined + seg

        combined.export(out_path, format="mp3")
        if progress_callback:
            progress_callback(1, 1)
        return out_path
