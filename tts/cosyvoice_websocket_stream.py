import base64
import json
import queue
import threading

import websocket

from tts.cosyvoice_tts import build_stream_start_payload, split_cosyvoice_text
from utils import config_util as cfg
from utils import util


_manager = None
_manager_lock = threading.Lock()


def _websocket_url():
    configured = str(getattr(cfg, "cosyvoice_ws_url", "") or "").strip()
    if configured:
        return configured
    base_url = str(getattr(cfg, "cosyvoice_base_url", "") or "").rstrip("/")
    if base_url.startswith("https://"):
        return "wss://" + base_url[len("https://"): ] + "/ws/tts"
    return "ws://" + base_url.removeprefix("http://") + "/ws/tts"


class _WebSocketSession:
    def __init__(self, key, emit_audio, emit_end, emit_error, on_closed):
        self.key = key
        self.emit_audio = emit_audio
        self.emit_end = emit_end
        self.emit_error = emit_error
        self.on_closed = on_closed
        self.outgoing = queue.Queue()
        self.closed = threading.Event()
        self.first_audio = True
        self.first_text = ""
        self.pending_text = ""
        self.audio_seq = 0
        self.sample_rate = 24000
        self.worker = threading.Thread(target=self._run, name="cosyvoice-ws-{}".format(key[0]), daemon=True)
        self.worker.start()

    def submit(self, text, is_end):
        self.pending_text += str(text or "")
        pending = self.pending_text.strip()
        should_flush = bool(is_end) or (
            pending and (pending[-1] in "。！？；：.!?;:" or len(pending) >= 55)
        )
        if not should_flush:
            return
        self.pending_text = ""
        for chunk in split_cosyvoice_text(pending):
            self.outgoing.put({"type": "append", "text": chunk})
        if is_end:
            self.outgoing.put({"type": "finish"})

    def cancel(self):
        self.closed.set()
        self.outgoing.put({"type": "cancel"})

    def _run(self):
        connection = None
        try:
            connection = websocket.create_connection(
                _websocket_url(), timeout=int(getattr(cfg, "cosyvoice_timeout_seconds", 120) or 120)
            )
            connection.settimeout(0.1)
            connection.send(json.dumps(build_stream_start_payload(), ensure_ascii=False))
            while not self.closed.is_set():
                try:
                    outgoing = self.outgoing.get_nowait()
                    if outgoing.get("type") == "append" and not self.first_text:
                        self.first_text = str(outgoing.get("text") or "")
                    connection.send(json.dumps(outgoing, ensure_ascii=False))
                except queue.Empty:
                    pass
                try:
                    incoming = json.loads(connection.recv())
                except websocket.WebSocketTimeoutException:
                    continue
                message_type = incoming.get("type")
                if message_type in ("started", "cancelled"):
                    continue
                if message_type == "audio":
                    pcm = base64.b64decode(incoming["pcm_base64"], validate=True)
                    self.sample_rate = int(incoming.get("sample_rate", 24000))
                    self.emit_audio(
                        pcm,
                        self.sample_rate,
                        self.first_text if self.first_audio else "",
                        self.first_audio,
                        False,
                        self.audio_seq,
                    )
                    self.first_audio = False
                    self.audio_seq += 1
                elif message_type == "end":
                    self.emit_end(self.first_audio, self.audio_seq, self.sample_rate)
                    return
                elif message_type == "error":
                    self.emit_error(self.key, "[CosyVoice websocket] " + str(incoming.get("message") or "unknown server error"))
                    return
        except Exception as exc:
            if not self.closed.is_set():
                self.emit_error(self.key, "[CosyVoice websocket] connection failed: " + str(exc))
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
            self.on_closed(self.key, self)


class CosyVoiceWebSocketStreamManager:
    def __init__(self):
        self.sessions = {}
        self.lock = threading.Lock()

    def submit(self, key, text, is_first, is_end, emit_audio, emit_end, emit_error):
        with self.lock:
            if is_first:
                previous = self.sessions.pop(key, None)
                if previous:
                    previous.cancel()
            session = self.sessions.get(key)
            if session is None:
                session = _WebSocketSession(key, emit_audio, emit_end, emit_error, self._on_closed)
                self.sessions[key] = session
        session.submit(text, is_end)
        util.log(1, "[CosyVoice websocket] text accepted key={} end={} text={}".format(key, bool(is_end), str(text or "")[:50]))

    def _on_closed(self, key, session):
        with self.lock:
            if self.sessions.get(key) is session:
                self.sessions.pop(key, None)


def get_manager():
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = CosyVoiceWebSocketStreamManager()
        return _manager