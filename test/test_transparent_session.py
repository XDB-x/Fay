import sys
import types
import unittest
from unittest.mock import patch

sys.modules.setdefault("fay_booter", types.SimpleNamespace(feiFei=None))

from core.stream_manager import StreamManager


class _StateManager:
    def get_session_info(self, username):
        return None

    def start_new_session(self, username, session_type, conversation_id):
        return conversation_id


class TransparentSessionTest(unittest.TestCase):
    def test_new_transparent_reply_resets_stop_state_and_uses_request_conversation(self):
        manager = StreamManager()
        manager.stop_generation_flags.clear()
        manager.conversation_ids.clear()
        manager.set_stop_generation("fay-user", True)

        state_module = types.SimpleNamespace(get_state_manager=lambda: _StateManager())
        with patch.dict(sys.modules, {"utils.stream_state_manager": state_module}):
            conversation_id = manager.begin_transparent_session(
                "fay-user", "conv-from-agent", session_type="transparent"
            )

        self.assertEqual("conv-from-agent", conversation_id)
        self.assertEqual("conv-from-agent", manager.get_conversation_id("fay-user"))
        self.assertFalse(manager.should_stop_generation("fay-user", "conv-from-agent"))


if __name__ == "__main__":
    unittest.main()
