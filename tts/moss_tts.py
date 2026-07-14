import base64
import os
import time
from pathlib import Path

import requests
from pydub import AudioSegment

from utils import config_util as cfg
from utils import util


def _configured_prompt_path():
    return Path(str(getattr(cfg, "moss_tts_prompt_audio", "") or "")).expanduser()


def _resolve_prompt_path():
    return _configured_prompt_path()


def build_stream_audio_message(audio_path, text, base_url, username,
                               conversation_id, seq, first, end):
    """Build the WebSocket audio contract consumed by the Flood frontend."""
    try:
        sequence = int(seq)
    except (TypeError, ValueError):
        sequence = 0
    normalized_base_url = str(base_url or "").rstrip("/")
    audio_name = os.path.basename(str(audio_path))
    return {
        "Topic": "human",
        "Data": {
            "Key": "audio",
            "Value": os.path.abspath(str(audio_path)),
            "HttpValue": normalized_base_url + "/audio/" + audio_name,
            "Text": str(text or ""),
            "Time": 5,
            "Type": 1,
            "IsFirst": 1 if first else 0,
            "IsEnd": 1 if end else 0,
            "CONV_ID": str(conversation_id or ""),
            "CONV_MSG_NO": sequence,
        },
        "Username": str(username or "User"),
        "robot": normalized_base_url + "/robot/Speaking.jpg",
    }


def build_stream_pcm_message(pcm_bytes, text, username, conversation_id, seq, first, end):
    """Build the continuous PCM contract used only by MOSS Realtime."""
    try:
        sequence = int(seq)
    except (TypeError, ValueError):
        sequence = 0
    return {
        "Topic": "human",
        "Data": {
            "Key": "audio_pcm",
            "PcmBase64": base64.b64encode(bytes(pcm_bytes or b"")).decode("ascii"),
            "SampleRate": 24000,
            "Channels": 1,
            "SampleWidth": 2,
            "Text": str(text or ""),
            "Type": 1,
            "IsFirst": 1 if first else 0,
            "IsEnd": 1 if end else 0,
            "CONV_ID": str(conversation_id or ""),
            "CONV_MSG_NO": sequence,
        },
        "Username": str(username or "User"),
    }

def build_stream_end_message(base_url, username, conversation_id, seq, first):
    """Build the final WebSocket marker when no final audio chunk exists."""
    try:
        sequence = int(seq)
    except (TypeError, ValueError):
        sequence = 0
    normalized_base_url = str(base_url or "").rstrip("/")
    return {
        "Topic": "human",
        "Data": {
            "Key": "audio",
            "Value": "",
            "HttpValue": "",
            "Text": "",
            "Time": 0,
            "Type": 1,
            "IsFirst": 1 if first else 0,
            "IsEnd": 1,
            "CONV_ID": str(conversation_id or ""),
            "CONV_MSG_NO": sequence,
        },
        "Username": str(username or "User"),
        "robot": normalized_base_url + "/robot/Normal.jpg",
    }


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
