import ast
import queue
import unittest
from pathlib import Path


SERVER_PATH = Path(r"C:\Users\SFJT\Desktop\fsdownload\server.py")


class CosyVoiceServerContractTest(unittest.TestCase):
    def _load_collect_text_batch(self):
        tree = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "collect_text_batch"
        )
        namespace = {"queue": queue, "MAX_STREAM_TEXT_CHARS": 200}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(SERVER_PATH), "exec"), namespace)
        return namespace["collect_text_batch"]

    def test_first_text_is_not_delayed_for_batching(self):
        collect_text_batch = self._load_collect_text_batch()
        text_queue = queue.Queue()
        text_queue.put("第二段。")
        text_queue.put(None)

        text, deferred, finish_seen = collect_text_batch(text_queue, "第一段。", False)

        self.assertEqual("第一段。", text)
        self.assertIsNone(deferred)
        self.assertFalse(finish_seen)
        self.assertEqual(2, text_queue.qsize())

    def test_queued_followup_text_is_combined_without_losing_finish(self):
        collect_text_batch = self._load_collect_text_batch()
        text_queue = queue.Queue()
        text_queue.put("第三段。")
        text_queue.put(None)

        text, deferred, finish_seen = collect_text_batch(text_queue, "第二段。", True)

        self.assertEqual("第二段。第三段。", text)
        self.assertIsNone(deferred)
        self.assertTrue(finish_seen)

    def test_overflow_text_is_deferred_in_original_order(self):
        collect_text_batch = self._load_collect_text_batch()
        text_queue = queue.Queue()
        text_queue.put("乙" * 60)
        text_queue.put("丙" * 20)

        text, deferred, finish_seen = collect_text_batch(text_queue, "甲" * 150, True)

        self.assertEqual("甲" * 150, text)
        self.assertEqual("乙" * 60, deferred)
        self.assertFalse(finish_seen)
        self.assertEqual("丙" * 20, text_queue.get_nowait())
    def test_exposes_websocket_tts_session_endpoint(self):
        tree = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
        functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef)}

        self.assertIn("websocket_tts", functions)
        decorators = [ast.unparse(item) for item in functions["websocket_tts"].decorator_list]
        self.assertTrue(any('/ws/tts' in decorator for decorator in decorators))

    def test_validates_base64_prompt_and_stream_message_types(self):
        source = SERVER_PATH.read_text(encoding="utf-8")

        self.assertIn("decode_prompt_audio", source)
        self.assertIn('"start"', source)
        self.assertIn('"append"', source)
        self.assertIn('"finish"', source)
        self.assertIn('"cancel"', source)


    def test_defaults_to_local_cosyvoice3_model(self):
        source = SERVER_PATH.read_text(encoding="utf-8")
        self.assertIn("default='pretrained_models/Fun-CosyVoice3-0.5B'", source)

    def test_stops_streaming_when_websocket_client_disconnects(self):
        source = SERVER_PATH.read_text(encoding="utf-8")
        self.assertIn("if not emit({", source)
        self.assertIn("return False", source)

    def test_websocket_stream_uses_unistream_for_each_text_chunk(self):
        tree = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
        stream_function = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "stream_model_audio"
        )
        inference_calls = [
            node
            for node in ast.walk(stream_function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("inference_zero_shot", "inference_instruct2")
        ]

        self.assertEqual(2, len(inference_calls))
        for call in inference_calls:
            self.assertIsInstance(call.args[0], ast.Name)
            self.assertEqual("text", call.args[0].id)
    def test_websocket_stream_bypasses_unstable_ttsfrd_frontend(self):
        tree = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
        stream_function = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "stream_model_audio"
        )
        inference_calls = [
            node
            for node in ast.walk(stream_function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("inference_zero_shot", "inference_instruct2")
        ]

        self.assertEqual(2, len(inference_calls))
        for call in inference_calls:
            keywords = {keyword.arg: keyword.value for keyword in call.keywords}
            self.assertIn("text_frontend", keywords)
            self.assertIsInstance(keywords["text_frontend"], ast.Constant)
            self.assertIs(False, keywords["text_frontend"].value)
if __name__ == "__main__":
    unittest.main()