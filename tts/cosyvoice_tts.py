import base64
import json
import os
import re
import time
import wave
import uuid
from pathlib import Path

import requests

from utils import config_util as cfg
from utils import util


_CHINESE_DIGITS = "零一二三四五六七八九"
_DATE_PATTERN = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")
_DATE_RANGE_SEPARATOR_PATTERN = re.compile(
    r"(?<=日)\s*(?:~|～|—|–|-|至|到)\s*(?=[零〇一二三四五六七八九]{4}年)"
)


def _to_chinese_date_number(value):
    value = int(value)
    if value < 10:
        return _CHINESE_DIGITS[value]
    if value == 10:
        return "十"
    if value < 20:
        return "十" + _CHINESE_DIGITS[value - 10]
    if value % 10 == 0:
        return _CHINESE_DIGITS[value // 10] + "十"
    return _CHINESE_DIGITS[value // 10] + "十" + _CHINESE_DIGITS[value % 10]


def normalize_cosyvoice_text(text):
    """Make numeric dates unambiguous for CosyVoice's Chinese frontend."""
    def replace_date(match):
        year, month, day = match.groups()
        spoken_year = "".join(_CHINESE_DIGITS[int(digit)] for digit in year)
        return "{}年{}月{}日".format(
            spoken_year,
            _to_chinese_date_number(month),
            _to_chinese_date_number(day),
        )

    normalized = _DATE_PATTERN.sub(replace_date, str(text or ""))
    return _DATE_RANGE_SEPARATOR_PATTERN.sub("至", normalized)


def split_cosyvoice_text(text, max_length=55):
    """Split long replies at natural sentence boundaries for lower first-audio latency."""
    normalized = normalize_cosyvoice_text(text).strip()
    if not normalized:
        return []

    sentences = re.findall(r"[^。！？；!?;]+[。！？；!?;]?", normalized)
    chunks = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if current and len(current) + len(sentence) > max_length:
            chunks.append(current)
            current = ""
        while len(sentence) > max_length:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(sentence[:max_length])
            sentence = sentence[max_length:]
        current += sentence
    if current:
        chunks.append(current)
    return chunks


def _resolve_project_path(configured):
    path = Path(str(configured or "")).expanduser()
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parent.parent / path


def _resolve_prompt_path(configured=None):
    if configured is None:
        configured = getattr(cfg, "cosyvoice_prompt_audio", "")
    return _resolve_project_path(configured)


def build_stream_start_payload():
    prompt_audio, prompt_text = _get_prompt_config()
    prompt_path = _resolve_prompt_path(prompt_audio)
    if not prompt_path.is_file():
        raise ValueError("CosyVoice prompt audio not found: {}".format(prompt_path))
    with prompt_path.open("rb") as prompt_file:
        encoded_audio = base64.b64encode(prompt_file.read()).decode("ascii")
    configured_mode = _get_cosyvoice_mode()
    mode = "zero_shot"
    if configured_mode == "instruct2":
        util.log(1, "[CosyVoice websocket] instruct2 is incompatible with streaming text; falling back to zero_shot")
    payload = {
        "type": "start",
        "mode": mode,
        "speed": _get_cosyvoice_speed(),
        "prompt_text": prompt_text,
        "prompt_wav_base64": encoded_audio,
    }
    if mode == "instruct2":
        payload["instruct_text"] = _get_cosyvoice_instruct_text()
    return payload

def get_available_voices():
    map_path = _resolve_project_path(getattr(cfg, "cosyvoice_voice_map", ""))
    try:
        payload = json.loads(map_path.read_text(encoding="utf-8"))
        voices = payload.get("voices", [])
        return [
            {"id": str(voice["id"]), "name": str(voice.get("name") or voice["id"])}
            for voice in voices
            if isinstance(voice, dict) and voice.get("id") and voice.get("prompt_audio") and voice.get("prompt_text")
        ]
    except (OSError, ValueError, TypeError, KeyError):
        return []


def _get_cosyvoice_mode():
    mode = str(getattr(cfg, "cosyvoice_mode", "zero_shot") or "zero_shot").strip().lower()
    return "instruct2" if mode == "instruct2" else "zero_shot"


def _get_cosyvoice_speed():
    try:
        speed = float(getattr(cfg, "cosyvoice_speed", 1.0) or 1.0)
    except (TypeError, ValueError):
        speed = 1.0
    return max(0.8, min(speed, 1.2))


def _get_cosyvoice_instruct_text():
    instruct_text = str(getattr(cfg, "cosyvoice_instruct_text", "") or "").strip()
    instruct_text = instruct_text.replace("<|endofprompt|>", "").strip()
    return instruct_text + "<|endofprompt|>" if instruct_text else ""

def _get_prompt_config():
    selected_voice = ""
    if isinstance(getattr(cfg, "config", None), dict):
        selected_voice = str(
            cfg.config.get("interact", {}).get("voice")
            or cfg.config.get("attribute", {}).get("voice")
            or ""
        ).strip()
    default_voice = str(getattr(cfg, "cosyvoice_default_voice", "") or "").strip()
    map_path = _resolve_project_path(getattr(cfg, "cosyvoice_voice_map", ""))
    try:
        payload = json.loads(map_path.read_text(encoding="utf-8"))
        voices = payload.get("voices", [])
        for voice_id in (selected_voice, default_voice):
            if not voice_id:
                continue
            for voice in voices:
                if not isinstance(voice, dict):
                    continue
                if str(voice.get("id") or "") != voice_id:
                    continue
                prompt_audio = str(voice.get("prompt_audio") or "").strip()
                prompt_text = str(voice.get("prompt_text") or "").strip()
                if prompt_audio and prompt_text:
                    return prompt_audio, prompt_text
    except (OSError, ValueError, TypeError):
        pass
    return (
        str(getattr(cfg, "cosyvoice_prompt_audio", "") or "").strip(),
        str(getattr(cfg, "cosyvoice_prompt_text", "") or "").strip(),
    )


class Speech:
    """Fay TTS adapter for the CosyVoice3 raw-PCM FastAPI endpoint."""

    split_cosyvoice_text = staticmethod(split_cosyvoice_text)

    def __init__(self):
        self.session = requests.Session()

    def connect(self):
        return None

    def close(self):
        self.session.close()

    def stream_to_samples(self, text, style):
        del style
        normalized_text = normalize_cosyvoice_text(text).strip()
        if not normalized_text:
            return

        prompt_audio, prompt_text = _get_prompt_config()
        prompt_path = _resolve_prompt_path(prompt_audio)
        if not prompt_path.is_file():
            util.log(1, "[x] CosyVoice prompt audio not found: " + str(prompt_path))
            return

        base_url = str(getattr(cfg, "cosyvoice_base_url", "") or "").rstrip("/")
        mode = _get_cosyvoice_mode()
        speed = _get_cosyvoice_speed()
        instruct_text = _get_cosyvoice_instruct_text() if mode == "instruct2" else ""
        timeout_seconds = int(getattr(cfg, "cosyvoice_timeout_seconds", 120) or 120)
        if not base_url or not prompt_text or (mode == "instruct2" and not instruct_text):
            util.log(1, "[x] CosyVoice base URL or prompt text is empty")
            return

        os.makedirs("./samples", exist_ok=True)
        response = None
        remainder = b""
        try:
            with prompt_path.open("rb") as prompt_file:
                response = self.session.post(
                    base_url + ("/inference_instruct2" if mode == "instruct2" else "/inference_zero_shot"),
                    data=(
                        {"tts_text": normalized_text, "instruct_text": instruct_text, "speed": str(speed)}
                        if mode == "instruct2"
                        else {"tts_text": normalized_text, "prompt_text": prompt_text, "speed": str(speed)}
                    ),
                    files={"prompt_wav": (prompt_path.name, prompt_file, "audio/wav")},
                    timeout=(3, timeout_seconds),
                    stream=True,
                )
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=None):
                pcm_bytes = remainder + (chunk or b"")
                if len(pcm_bytes) % 2:
                    remainder, pcm_bytes = pcm_bytes[-1:], pcm_bytes[:-1]
                else:
                    remainder = b""
                if not pcm_bytes:
                    continue
                output_path = os.path.abspath(
                    "./samples/sample-{}-cosyvoice-stream.wav".format(uuid.uuid4().hex)
                )
                with wave.open(output_path, "wb") as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(22050)
                    wav_file.writeframes(pcm_bytes)
                yield output_path
        except Exception as exc:
            util.log(1, "[x] CosyVoice stream TTS failed: " + str(exc))
        finally:
            if response is not None:
                response.close()
    def to_sample(self, text, style):
        del style
        normalized_text = normalize_cosyvoice_text(text).strip()
        if not normalized_text:
            return None

        prompt_audio, prompt_text = _get_prompt_config()
        prompt_path = _resolve_prompt_path(prompt_audio)
        if not prompt_path.is_file():
            util.log(1, "[x] CosyVoice prompt audio not found: " + str(prompt_path))
            return None

        base_url = str(getattr(cfg, "cosyvoice_base_url", "") or "").rstrip("/")
        mode = _get_cosyvoice_mode()
        speed = _get_cosyvoice_speed()
        instruct_text = _get_cosyvoice_instruct_text() if mode == "instruct2" else ""
        timeout_seconds = int(getattr(cfg, "cosyvoice_timeout_seconds", 120) or 120)
        if not base_url or not prompt_text or (mode == "instruct2" and not instruct_text):
            util.log(1, "[x] CosyVoice base URL or prompt text is empty")
            return None

        os.makedirs("./samples", exist_ok=True)
        output_path = os.path.abspath(
            "./samples/sample-{}-cosyvoice.wav".format(uuid.uuid4().hex)
        )

        try:
            with prompt_path.open("rb") as prompt_file:
                response = self.session.post(
                    base_url + ("/inference_instruct2" if mode == "instruct2" else "/inference_zero_shot"),
                    data=(
                        {"tts_text": normalized_text, "instruct_text": instruct_text, "speed": str(speed)}
                        if mode == "instruct2"
                        else {"tts_text": normalized_text, "prompt_text": prompt_text, "speed": str(speed)}
                    ),
                    files={
                        "prompt_wav": (prompt_path.name, prompt_file, "audio/wav"),
                    },
                    timeout=(3, timeout_seconds),
                )
            response.raise_for_status()
            pcm_bytes = response.content
            if not pcm_bytes or len(pcm_bytes) % 2 != 0:
                raise ValueError("CosyVoice returned invalid PCM length")

            with wave.open(output_path, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(22050)
                wav_file.writeframes(pcm_bytes)

            return output_path
        except Exception as exc:
            util.log(1, "[x] CosyVoice TTS failed: " + str(exc))
            if os.path.isfile(output_path):
                os.remove(output_path)
            return None