import os
import threading
import time
import uuid
import wave

import requests

from utils import config_util as cfg
from utils import util


_manager = None
_manager_lock = threading.Lock()


class _RealtimeSession:
    def __init__(self, key, emit_audio, emit_error, on_closed):
        self.key = key
        self.emit_audio = emit_audio
        self.emit_error = emit_error
        self.on_closed = on_closed
        self.http = requests.Session()
        self.session_id = "fay-{}-{}".format(int(time.time() * 1000), uuid.uuid4().hex[:8])
        self.audio_response = None
        self.reader_thread = None
        self.push_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.pending_text = ""
        self.last_text = ""
        self.final_requested = False
        self.first_audio = True
        self.first_audio_ready = threading.Event()
        self.audio_seq = 0
        self.closed = False

    def start(self):
        base_url = str(cfg.moss_tts_base_url or "").rstrip("/")
        prompt_audio = str(cfg.moss_tts_prompt_audio or "")
        start = self.http.post(
            base_url + "/tts/session/start",
            json={
                "session_id": self.session_id,
                "assistant_text": "",
                "prompt_audio": prompt_audio,
                "new_turn": True,
            },
            timeout=(3, cfg.moss_tts_timeout_seconds),
        )
        start.raise_for_status()
        self.audio_response = self.http.get(
            base_url + "/tts/session/{}/audio".format(self.session_id),
            stream=True,
            timeout=(3, cfg.moss_tts_timeout_seconds),
        )
        self.audio_response.raise_for_status()
        self.reader_thread = threading.Thread(
            target=self._read_audio,
            name="moss-realtime-audio-{}".format(self.session_id),
            daemon=True,
        )
        self.reader_thread.start()
        util.log(1, "[MOSS Realtime] session started: " + self.session_id)

    def push(self, text, is_final):
        base_url = str(cfg.moss_tts_base_url or "").rstrip("/")
        util.log(1, "[MOSS Realtime] push session={} final={} text={}".format(
            self.session_id, bool(is_final), str(text or "")))
        with self.push_lock:
            response = self.http.post(
                base_url + "/tts/session/push",
                json={
                    "session_id": self.session_id,
                    "text": str(text or ""),
                    "is_final": bool(is_final),
                },
                timeout=(3, cfg.moss_tts_timeout_seconds),
            )
            response.raise_for_status()
            if not is_final and self.first_audio:
                self.first_audio_ready.wait(timeout=3)
            if is_final:
                with self.state_lock:
                    self.final_requested = True

    def _read_audio(self):
        buffer = bytearray()
        # Fay queues each WAV as a separate playback item. Keep each item long enough
        # to avoid audible breaks inside a short sentence while retaining realtime output.
        chunk_bytes = int(24000 * 2 * 1.2)
        try:
            for chunk in self.audio_response.iter_content(chunk_size=4096):
                if not chunk:
                    continue
                buffer.extend(chunk)
                while len(buffer) >= chunk_bytes:
                    audio_bytes = bytes(buffer[:chunk_bytes])
                    del buffer[:chunk_bytes]
                    self._emit(audio_bytes, end=False)
            if buffer:
                self._emit(bytes(buffer), end=True)
            else:
                with self.state_lock:
                    final_requested = self.final_requested
                if final_requested:
                    self.emit_audio(None, "", self.first_audio, True, self.audio_seq)
        except Exception as exc:
            self.emit_error(self.key, "[MOSS Realtime] audio reader failed: " + str(exc))
        finally:
            self.close()

    def _emit(self, pcm_bytes, end):
        if self.first_audio:
            self.first_audio_ready.set()
        text = self.last_text if self.first_audio else ""
        self.emit_audio(bytes(pcm_bytes), text, self.first_audio, end, self.audio_seq)
        self.first_audio = False
        self.audio_seq += 1

    def _write_wav(self, pcm_bytes):
        os.makedirs("./samples", exist_ok=True)
        stamp = "{}-{}".format(int(time.time() * 1000), self.audio_seq)
        path = os.path.abspath("./samples/sample-{}-moss-realtime.wav".format(stamp))
        with wave.open(path, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(24000)
            wav_file.writeframes(pcm_bytes)
        return path

    def close(self):
        with self.state_lock:
            if self.closed:
                return
            self.closed = True
        try:
            base_url = str(cfg.moss_tts_base_url or "").rstrip("/")
            self.http.post(
                base_url + "/tts/session/close",
                json={"session_id": self.session_id},
                timeout=5,
            )
        except Exception:
            pass
        self.http.close()
        self.on_closed(self.key, self)


class RealtimeStreamManager:
    def __init__(self):
        self.sessions = {}
        self.lock = threading.Lock()

    def submit(self, key, text, is_first, is_end, emit_audio, emit_error):
        with self.lock:
            if is_first and key in self.sessions:
                self.sessions.pop(key).close()
            session = self.sessions.get(key)
            if session is None:
                session = _RealtimeSession(key, emit_audio, emit_error, self._on_closed)
                self.sessions[key] = session
                try:
                    session.start()
                except Exception:
                    self.sessions.pop(key, None)
                    session.close()
                    raise

        if text:
            session.pending_text += str(text)
            session.last_text = str(text)

        pending = session.pending_text.strip()
        should_flush = bool(is_end)
        if not should_flush and pending:
            punctuation = "。！？；：.!?;:"
            should_flush = (
                pending[-1] in punctuation
            ) or len(pending) >= 60
        if should_flush and pending:
            session.pending_text = ""
            session.push(pending, is_end)
        elif is_end:
            session.push("", True)

        return session.session_id

    def _on_closed(self, key, session):
        with self.lock:
            if self.sessions.get(key) is session:
                self.sessions.pop(key, None)

    def forget(self, key):
        with self.lock:
            session = self.sessions.pop(key, None)
        if session:
            session.close()


def get_manager():
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = RealtimeStreamManager()
        return _manager
