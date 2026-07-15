import queue
import threading

from tts.cosyvoice_tts import Speech, split_cosyvoice_text
from utils import util


_manager = None
_manager_lock = threading.Lock()


class _CosyVoiceSession:
    def __init__(self, key, emit_audio, emit_end, emit_error, on_closed):
        self.key = key
        self.emit_audio = emit_audio
        self.emit_end = emit_end
        self.emit_error = emit_error
        self.on_closed = on_closed
        self.items = queue.Queue()
        self.lock = threading.Lock()
        self.first_audio = True
        self.pending_text = ""
        self.audio_seq = 0
        self.closed = False
        self.worker = threading.Thread(
            target=self._run,
            name="cosyvoice-stream-{}".format(key[0]),
            daemon=True,
        )
        self.worker.start()

    def submit(self, text, is_end):
        with self.lock:
            if self.closed:
                return
            self.pending_text += str(text or "")
            pending = self.pending_text.strip()
            should_flush = bool(is_end) or (
                pending and (pending[-1] in "。！？；：.!?;:" or len(pending) >= 55)
            )
            if not should_flush:
                return
            self.pending_text = ""

        chunks = split_cosyvoice_text(pending) if pending else []
        if not chunks and is_end:
            self.items.put(None)
            return
        for index, chunk in enumerate(chunks):
            self.items.put((chunk, bool(is_end and index == len(chunks) - 1)))

    def cancel(self):
        with self.lock:
            self.closed = True
        self.items.put(None)

    def _run(self):
        speech = Speech()
        try:
            while True:
                item = self.items.get()
                if item is None:
                    if not self.closed:
                        self.emit_end(self.first_audio, self.audio_seq)
                    return

                text, is_end = item
                for audio_path in speech.stream_to_samples(text, None):
                    if self.closed:
                        return
                    self.emit_audio(
                        audio_path,
                        text if self.first_audio else "",
                        self.first_audio,
                        False,
                        self.audio_seq,
                    )
                    self.first_audio = False
                    self.audio_seq += 1

                if is_end:
                    if not self.closed:
                        self.emit_end(self.first_audio, self.audio_seq)
                    return
        except Exception as exc:
            if not self.closed:
                self.emit_error(self.key, "[CosyVoice stream] audio worker failed: " + str(exc))
        finally:
            speech.close()
            self.on_closed(self.key, self)


class CosyVoiceStreamManager:
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
                session = _CosyVoiceSession(key, emit_audio, emit_end, emit_error, self._on_closed)
                self.sessions[key] = session

        session.submit(text, is_end)
        util.log(1, "[CosyVoice stream] text accepted key={} end={} text={}".format(
            key, bool(is_end), str(text or "")[:50]))

    def _on_closed(self, key, session):
        with self.lock:
            if self.sessions.get(key) is session:
                self.sessions.pop(key, None)


def get_manager():
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = CosyVoiceStreamManager()
        return _manager