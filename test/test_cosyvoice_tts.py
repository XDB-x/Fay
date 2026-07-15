import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

from tts import cosyvoice_tts
from utils import config_util as cfg


class CosyVoiceTtsTest(unittest.TestCase):
    def setUp(self):
        self.prompt = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        self.prompt.close()
        with wave.open(self.prompt.name, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(b'\x00\x00' * 1600)
        self.output_dir = tempfile.TemporaryDirectory()
        self.original = {
            'cosyvoice_base_url': cfg.cosyvoice_base_url,
            'cosyvoice_prompt_audio': cfg.cosyvoice_prompt_audio,
            'cosyvoice_prompt_text': cfg.cosyvoice_prompt_text,
            'cosyvoice_timeout_seconds': cfg.cosyvoice_timeout_seconds,
        }
        cfg.cosyvoice_base_url = 'http://127.0.0.1:50000'
        cfg.cosyvoice_prompt_audio = self.prompt.name
        cfg.cosyvoice_prompt_text = 'You are a helpful assistant.<|endofprompt|>测试参考音频。'
        cfg.cosyvoice_timeout_seconds = 120

    def tearDown(self):
        for name, value in self.original.items():
            setattr(cfg, name, value)
        os.unlink(self.prompt.name)
        self.output_dir.cleanup()

    def _resolve_output(self, path):
        if path.startswith('./samples/'):
            return str(Path(self.output_dir.name) / Path(path).name)
        return os.path.abspath(path)

    def test_converts_raw_pcm_response_to_wav(self):
        response = Mock()
        response.content = b'\x01\x02' * 22050
        response.raise_for_status.return_value = None
        session = Mock()
        session.post.return_value = response

        with patch.object(cosyvoice_tts.os.path, 'abspath', side_effect=self._resolve_output), \
                patch.object(cosyvoice_tts.requests, 'Session', return_value=session):
            output = cosyvoice_tts.Speech().to_sample('测试 CosyVoice3', None)

        self.assertIsNotNone(output)
        try:
            with wave.open(output, 'rb') as wav_file:
                self.assertEqual(wav_file.getnchannels(), 1)
                self.assertEqual(wav_file.getsampwidth(), 2)
                self.assertEqual(wav_file.getframerate(), 22050)
                self.assertEqual(wav_file.getnframes(), 22050)
            session.post.assert_called_once()
            self.assertEqual(
                session.post.call_args.args[0],
                'http://127.0.0.1:50000/inference_zero_shot',
            )
            self.assertEqual(session.post.call_args.kwargs['data']['tts_text'], '测试 CosyVoice3')
        finally:
            if output and Path(output).exists():
                Path(output).unlink()

    def test_normalizes_numeric_date_range_for_cosyvoice(self):
        response = Mock()
        response.content = b'\x01\x02' * 100
        response.raise_for_status.return_value = None
        session = Mock()
        session.post.return_value = response

        with patch.object(cosyvoice_tts.os.path, 'abspath', side_effect=self._resolve_output), \
                patch.object(cosyvoice_tts.requests, 'Session', return_value=session):
            output = cosyvoice_tts.Speech().to_sample('2026-07-08 ~ 2026-07-15', None)

        try:
            self.assertEqual(
                session.post.call_args.kwargs['data']['tts_text'],
                '二零二六年七月八日至二零二六年七月十五日',
            )
        finally:
            if output and Path(output).exists():
                Path(output).unlink()
    def test_splits_long_text_at_sentence_boundaries(self):
        text = '第一句内容用于测试。第二句内容用于测试。第三句内容用于测试。第四句内容用于测试。'

        chunks = cosyvoice_tts.Speech().split_cosyvoice_text(text, max_length=20)

        self.assertEqual(chunks, ['第一句内容用于测试。第二句内容用于测试。', '第三句内容用于测试。第四句内容用于测试。'])
    def test_uses_selected_cosyvoice_voice_mapping(self):
        voice_map = Path(self.output_dir.name) / 'cosyvoice_voices.json'
        voice_map.write_text(
            '{"voices": [{"id": "cosy-zh-1", "name": "测试音色", '
            '"prompt_audio": "' + self.prompt.name.replace('\\', '\\\\') + '", '
            '"prompt_text": "You are a helpful assistant.<|endofprompt|>参考音频台词。"}]}',
            encoding='utf-8',
        )
        response = Mock()
        response.content = b'\x01\x02' * 100
        response.raise_for_status.return_value = None
        session = Mock()
        session.post.return_value = response
        original_map = getattr(cfg, 'cosyvoice_voice_map', None)
        original_default = getattr(cfg, 'cosyvoice_default_voice', None)
        original_config = cfg.config
        try:
            cfg.cosyvoice_voice_map = str(voice_map)
            cfg.cosyvoice_default_voice = 'cosy-zh-1'
            cfg.config = {'interact': {'voice': 'cosy-zh-1'}}
            with patch.object(cosyvoice_tts.os.path, 'abspath', side_effect=self._resolve_output), \
                    patch.object(cosyvoice_tts.requests, 'Session', return_value=session):
                output = cosyvoice_tts.Speech().to_sample('测试音色映射。', None)
            self.assertEqual(
                'You are a helpful assistant.<|endofprompt|>参考音频台词。',
                session.post.call_args.kwargs['data']['prompt_text'],
            )
        finally:
            cfg.cosyvoice_voice_map = original_map
            cfg.cosyvoice_default_voice = original_default
            cfg.config = original_config
            if 'output' in locals() and output and Path(output).exists():
                Path(output).unlink()
    def test_empty_text_does_not_call_cosyvoice(self):
        session = Mock()
        with patch.object(cosyvoice_tts.requests, 'Session', return_value=session):
            output = cosyvoice_tts.Speech().to_sample('  ', None)
        self.assertIsNone(output)
        session.post.assert_not_called()


if __name__ == '__main__':
    unittest.main()