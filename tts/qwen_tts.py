import base64
import json
import os
import time
import wave
from array import array
from pathlib import Path
from urllib.parse import urlencode

import websocket

from utils import config_util as cfg
from utils import util


_INPUT_SAMPLE_RATE = 24000
_OUTPUT_SAMPLE_RATE = 16000


def _setting(attribute, environment, default):
    value = os.getenv(environment)
    if value is not None and value.strip():
        return value.strip()
    return getattr(cfg, attribute, default) or default


def _resample_mono_pcm(pcm_bytes, source_rate, target_rate):
    samples = array("h")
    samples.frombytes(pcm_bytes)
    if not samples or source_rate == target_rate:
        return samples.tobytes()

    output_count = max(1, round(len(samples) * target_rate / source_rate))
    output = array("h")
    for index in range(output_count):
        source_position = index * source_rate / target_rate
        left = min(int(source_position), len(samples) - 1)
        right = min(left + 1, len(samples) - 1)
        fraction = source_position - left
        value = round(samples[left] + (samples[right] - samples[left]) * fraction)
        output.append(max(-32768, min(32767, value)))
    return output.tobytes()


def _write_wav(path, pcm_bytes):
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(_OUTPUT_SAMPLE_RATE)
        wav_file.writeframes(pcm_bytes)


class Speech:
    def __init__(self):
        self.model = str(_setting("qwen_tts_model", "QWEN_TTS_MODEL", "qwen3-tts-flash-realtime"))
        self.voice = str(_setting("qwen_tts_voice", "QWEN_TTS_VOICE", "Neil"))
        self.api_key = str(_setting("qwen_tts_api_key", "QWEN_TTS_API_KEY", ""))
        self.workspace_id = str(_setting("qwen_tts_workspace_id", "QWEN_TTS_WORKSPACE_ID", ""))
        self.region = str(_setting("qwen_tts_region", "QWEN_TTS_REGION", "cn-beijing"))
        self.timeout = float(_setting("qwen_tts_timeout_seconds", "QWEN_TTS_TIMEOUT_SECONDS", "30"))
        self.output_dir = Path(str(_setting("qwen_tts_output_dir", "QWEN_TTS_OUTPUT_DIR", "./samples")))

    def connect(self):
        if not self.api_key:
            raise RuntimeError("Qwen TTS API key is not configured")
        host = "dashscope-intl.aliyuncs.com" if self.region in ("singapore", "ap-southeast-1") else "dashscope.aliyuncs.com"
        url = "wss://{}/api-ws/v1/realtime?{}".format(
            host,
            urlencode({"model": self.model}),
        )
        headers = ["Authorization: Bearer {}".format(self.api_key)]
        if self.workspace_id:
            headers.append("X-DashScope-WorkSpace: {}".format(self.workspace_id))
        return websocket.create_connection(url, header=headers, timeout=self.timeout)

    def to_sample(self, text, style):
        normalized_text = str(text or "").strip()
        if not normalized_text:
            return None

        socket = None
        try:
            socket = self.connect()
            socket.send(json.dumps({
                "type": "session.update",
                "session": {
                    "voice": self.voice,
                    "response_format": "pcm",
                    "sample_rate": _INPUT_SAMPLE_RATE,
                    "mode": "commit",
                },
            }, ensure_ascii=False))
            socket.send(json.dumps({
                "type": "input_text_buffer.append",
                "text": normalized_text,
            }, ensure_ascii=False))
            socket.send(json.dumps({"type": "input_text_buffer.commit"}))

            audio_chunks = []
            audio_done = False
            while not audio_done:
                event = json.loads(socket.recv())
                event_type = event.get("type")
                if event_type == "response.audio.delta":
                    audio_chunks.append(base64.b64decode(event["delta"], validate=True))
                elif event_type == "response.audio.done":
                    audio_done = True
                elif event_type == "error":
                    raise RuntimeError(str(event.get("error") or event))

            if not audio_chunks:
                raise RuntimeError("Qwen TTS returned no audio")

            socket.send(json.dumps({"type": "session.finish"}))
            while True:
                event_type = json.loads(socket.recv()).get("type")
                if event_type == "session.finished":
                    break
                if event_type == "error":
                    raise RuntimeError("Qwen TTS session finish failed")

            raw_pcm = b"".join(audio_chunks)
            output_pcm = _resample_mono_pcm(raw_pcm, _INPUT_SAMPLE_RATE, _OUTPUT_SAMPLE_RATE)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            output_path = self.output_dir / "sample-{}-qwen.wav".format(int(time.time() * 1000))
            _write_wav(output_path, output_pcm)
            return str(output_path)
        except Exception as exc:
            util.log(1, "[x] Qwen TTS failed: " + str(exc))
            return None
        finally:
            if socket is not None:
                try:
                    socket.close()
                except Exception:
                    pass

    def close(self):
        pass
