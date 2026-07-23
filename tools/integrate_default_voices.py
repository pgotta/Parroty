from __future__ import annotations

import re
import shutil
import wave
from pathlib import Path

from huggingface_hub import hf_hub_download

ROOT = Path(__file__).resolve().parents[1]
VOICE_DIR = ROOT / "app" / "assets" / "voices"
TTS_PATH = ROOT / "app" / "tts.py"

VOICES = [
    ("warm_female", "Warm female", "builtin_warm_female.wav", "p318", "audio/p318_021_pad.wav"),
    ("mature_female", "Mature female", "builtin_mature_female.wav", "p294", "audio/p294_006_pad.wav"),
    ("neutral_female", "Neutral female", "builtin_neutral_female.wav", "p300", "audio/p300_021_pad.wav"),
    ("british_female", "British female", "builtin_british_female.wav", "p276", "audio/p276_021_pad.wav"),
    ("warm_male", "Warm male", "builtin_warm_male.wav", "p311", "audio/p311_021_pad.wav"),
    ("mature_deep_male", "Mature/deep male", "builtin_mature_deep_male.wav", "p227", "audio/p227_011_pad.wav"),
    ("neutral_male", "Neutral male", "builtin_neutral_male.wav", "p345", "audio/p345_021_pad.wav"),
    ("british_male", "British male", "builtin_british_male.wav", "p232", "audio/p232_021_pad.wav"),
]


def download_voices() -> None:
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    for key, label, filename, speaker, source_path in VOICES:
        cached = hf_hub_download(
            repo_id="yfyeung/vctk",
            repo_type="dataset",
            filename=source_path,
        )
        destination = VOICE_DIR / filename
        shutil.copy2(cached, destination)
        with wave.open(str(destination), "rb") as audio:
            assert audio.getnchannels() == 1, filename
            assert audio.getsampwidth() == 2, filename
            assert audio.getframerate() == 16000, filename
            duration = audio.getnframes() / audio.getframerate()
            assert 9.5 <= duration <= 10.5, (filename, duration)
        print(f"Added {label}: anonymous VCTK {speaker}")

    for obsolete in ("builtin_female.wav", "builtin_male.wav"):
        (VOICE_DIR / obsolete).unlink(missing_ok=True)


def update_catalog() -> None:
    source = TTS_PATH.read_text(encoding="utf-8")
    replacement_lines = ['        "builtin_voices": {']
    for key, label, filename, _speaker, _source_path in VOICES:
        replacement_lines.extend([
            f'            "{key}": {{',
            f'                "label": "{label}",',
            f'                "file": "{filename}",',
            '            },',
        ])
    replacement_lines.append('        },')
    replacement = "\n".join(replacement_lines)

    updated, count = re.subn(
        r'        "builtin_voices": \{.*?\n        \},\n        # Model variant:',
        replacement + '\n        # Model variant:',
        source,
        count=1,
        flags=re.DOTALL,
    )
    if count != 1:
        raise RuntimeError("Could not locate Chatterbox builtin_voices catalog block")

    updated = re.sub(
        r'# Chatterbox is a cloning-only model:.*?# while still allowing a fully custom cloned voice if the user uploads a sample\.',
        '# Chatterbox is a cloning model. Its built-in voices use bundled, anonymous\n'
        '# CC BY 4.0 reference clips under app/assets/voices/, so they work fully\n'
        '# locally and offline. Custom uploaded samples remain supported.',
        updated,
        count=1,
        flags=re.DOTALL,
    )
    TTS_PATH.write_text(updated, encoding="utf-8")


def write_attribution() -> None:
    rows = "\n".join(
        f"| {label} | `{filename}` | {speaker} | `{Path(source).name}` |"
        for _key, label, filename, speaker, source in VOICES
    )
    text = f"""# Bundled Chatterbox voice references

Parroty's eight built-in Chatterbox voices use short, anonymous reference clips
from the **CSTR VCTK Corpus: English Multi-speaker Corpus for CSTR Voice Cloning
Toolkit** by Christophe Veaux, Junichi Yamagishi, and Kirsten MacDonald.

The source corpus is licensed under the **Creative Commons Attribution 4.0
International license (CC BY 4.0)**. These clips were obtained from the
`yfyeung/vctk` distribution on Hugging Face. Speaker IDs remain anonymous; do
not attempt to identify the speakers.

| Parroty label | File | VCTK speaker | Source clip |
|---|---|---:|---|
{rows}

The category labels are descriptive audition labels chosen for Parroty. They are
not claims about the speakers' identities or personal characteristics beyond
the anonymous corpus metadata.
"""
    (VOICE_DIR / "ATTRIBUTION.md").write_text(text, encoding="utf-8")


def verify_catalog() -> None:
    namespace: dict = {}
    exec(compile(TTS_PATH.read_text(encoding="utf-8"), str(TTS_PATH), "exec"), namespace)
    catalog = namespace["ENGINE_CATALOG"]["chatterbox"]["builtin_voices"]
    assert list(catalog) == [voice[0] for voice in VOICES]
    for key, _label, filename, _speaker, _source in VOICES:
        assert catalog[key]["file"] == filename
        assert (VOICE_DIR / filename).is_file()
    assert not (VOICE_DIR / "builtin_female.wav").exists()
    assert not (VOICE_DIR / "builtin_male.wav").exists()
    print("Verified eight default voices and removed the two old generic voices")


def main() -> None:
    download_voices()
    update_catalog()
    write_attribution()
    verify_catalog()


if __name__ == "__main__":
    main()
