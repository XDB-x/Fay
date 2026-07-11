import base64
import os
import re
import time
from pathlib import Path

import requests
from pydub import AudioSegment

from utils import config_util as cfg
from utils import util


_ZH_VOICE_PATTERN = re.compile(r"^zh_(\d+)\.wav$", re.IGNORECASE)


def _configured_prompt_path():
    return Path(str(getattr(cfg, "moss_tts_prompt_audio", "") or "")).expanduser()


def get_voice_list():
    """Return only Chinese MOSS prompt voices beside the configured default."""
    configured_path = _configured_prompt_path()
    voices = []
    for path in configured_path.parent.glob("zh_*.wav"):
        match = _ZH_VOICE_PATTERN.match(path.name)
        if match:
            voices.append((int(match.group(1)), path.stem))
    voices.sort(key=lambda item: item[0])
    if voices:
        return [
            {"id": voice_id, "name": "MOSS 中文音色 {}".format(number)}
            for number, voice_id in voices
        ]
    return [{"id": "moss-default", "name": "MOSS 中文默认音色"}]


def _selected_voice_id():
    try:
        return str(cfg.config.get("attribute", {}).get("voice", "") or "").strip()
    except Exception:
        return ""


def _resolve_prompt_path():
    configured_path = _configured_prompt_path()
    selected_voice = _selected_voice_id()
    if selected_voice and selected_voice != "moss-default" and re.fullmatch(r"zh_\d+", selected_voice):
        candidate = configured_path.parent / (selected_voice + ".wav")
        if candidate.is_file():
            return candidate
        util.log(1, "[!] MOSS voice not found, fallback to default: " + str(candidate))
    return configured_path


class Speech:
    def __init__(self):
        self.session = requests.Session()

    def connect(self):
        return None

    def close(self):
        self.session.close()

    def to_sample(self, text, style):
        del style
        normalized_text = str(text or "").strip()
        if not normalized_text:
            return None

        prompt_path = _resolve_prompt_path().resolve()
        if not prompt_path.is_file():
            util.log(1, "[x] MOSS prompt audio not found: " + str(prompt_path))
            return None

        os.makedirs("./samples", exist_ok=True)
        stamp = str(int(time.time() * 1000))
        raw_path = os.path.abspath("./samples/sample-{}-moss-raw.wav".format(stamp))
        output_path = os.path.abspath("./samples/sample-{}-moss.wav".format(stamp))

        try:
            with open(prompt_path, "rb") as prompt_file:
                response = self.session.post(
                    cfg.moss_tts_base_url.rstrip("/") + "/api/generate",
                    data={
                        "text": normalized_text,
                        "cpu_threads": str(cfg.moss_tts_cpu_threads),
                        "enable_text_normalization": "1",
                        "enable_normalize_tts_text": "1",
                    },
                    files={"prompt_audio": (prompt_path.name, prompt_file, "audio/wav")},
                    timeout=(3, cfg.moss_tts_timeout_seconds),
                )
            response.raise_for_status()
            payload = response.json()
            audio_bytes = base64.b64decode(payload["audio_base64"], validate=True)
            with open(raw_path, "wb") as output:
                output.write(audio_bytes)
            (
                AudioSegment.from_file(raw_path, format="wav")
                .set_channels(1)
                .set_frame_rate(16000)
                .export(output_path, format="wav")
            )
            return output_path
        except Exception as exc:
            util.log(1, "[x] MOSS TTS failed: " + str(exc))
            return None
        finally:
            if os.path.isfile(raw_path):
                os.remove(raw_path)
