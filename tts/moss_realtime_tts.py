import os
import time
import uuid
import wave

import requests
from pydub import AudioSegment

from utils import config_util as cfg
from utils import util


class Speech:
    """MOSS-TTS-Realtime adapter using Fay's existing to_sample contract."""

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

        base_url = str(cfg.moss_tts_base_url or "").rstrip("/")
        prompt_audio = str(cfg.moss_tts_prompt_audio or "")
        session_id = "fay-{}-{}".format(int(time.time() * 1000), uuid.uuid4().hex[:8])
        pcm_path = None
        pcm_wav_path = None

        try:
            start = self.session.post(
                base_url + "/tts/session/start",
                json={
                    "session_id": session_id,
                    "assistant_text": normalized_text,
                    "prompt_audio": prompt_audio,
                    "new_turn": True,
                },
                timeout=(3, cfg.moss_tts_timeout_seconds),
            )
            start.raise_for_status()

            audio_response = self.session.get(
                base_url + "/tts/session/{}/audio".format(session_id),
                stream=True,
                timeout=(3, cfg.moss_tts_timeout_seconds),
            )
            audio_response.raise_for_status()

            finish = self.session.post(
                base_url + "/tts/session/push",
                json={
                    "session_id": session_id,
                    "text": "",
                    "is_final": True,
                },
                timeout=(3, cfg.moss_tts_timeout_seconds),
            )
            finish.raise_for_status()
            pcm_bytes = audio_response.content

            os.makedirs("./samples", exist_ok=True)
            stamp = str(int(time.time() * 1000))
            pcm_path = os.path.abspath("./samples/sample-{}-moss-realtime.pcm".format(stamp))
            pcm_wav_path = pcm_path + ".wav"
            output_path = os.path.abspath("./samples/sample-{}-moss-realtime.wav".format(stamp))
            with open(pcm_path, "wb") as pcm_file:
                pcm_file.write(pcm_bytes)
            with wave.open(pcm_wav_path, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(24000)
                wav_file.writeframes(pcm_bytes)
            (
                AudioSegment.from_file(pcm_wav_path, format="wav")
                .set_channels(1)
                .set_frame_rate(16000)
                .export(output_path, format="wav")
            )
            return output_path
        except Exception as exc:
            util.log(1, "[x] MOSS Realtime TTS failed: " + str(exc))
            return None
        finally:
            try:
                self.session.post(
                    base_url + "/tts/session/close",
                    json={"session_id": session_id},
                    timeout=5,
                )
            except Exception:
                pass
            for temporary_path in (pcm_path, pcm_wav_path):
                if temporary_path and os.path.isfile(temporary_path):
                    os.remove(temporary_path)
