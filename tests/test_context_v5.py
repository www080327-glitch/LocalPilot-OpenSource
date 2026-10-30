from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from agent.backends import Message, ToolCall
from agent.context import ContextTooSmall, context_units
from agent.context_v5 import transfer
from agent.engine_v5 import EngineV5Policy
from agent.persistence import snapshot_runtime, restore_runtime, PersistenceError, configuration
from agent.registry import create_default_registry
from agent.session import AgentSession, SessionBudgets
from tests.test_runtime_api import Backend, answer, call


class ContextV5Tests(unittest.TestCase):
    def test_balanced_compaction_retains_task_unknown_and_versions(self):
        state = {'original_task': 'original requirements', 'unknown': ['receipt-u'],
                 'approval': 'pending', 'versions': {'x': 'sha'}, 'verification': 'not_run'}
        history = [Message('system', 'fixed'), Message('user', 'old'*3000),
                   Message('assistant', tool_calls=[ToolCall('a','read_file','{"path":"x"}')]),
                   Message('tool', 'observed', tool_call_id='a')]
        before = deepcopy(history)
        view, info = transfer(history, [], 2300, 500, working_state=state)
        self.assertEqual(history, before)
        self.assertLessEqual(context_units(view, []), 1800)
        self.assertEqual([m.role for m in view], ['system', 'user', 'assistant', 'tool', 'user'])
        snapshot = json.loads(view[-1].content.split('\n',1)[1])
        for k,v in state.items(): self.assertEqual(snapshot[k], v)
        self.assertGreater(info['omitted_messages'], 0)

    def test_critical_overflow_never_truncates_authority(self):
        with self.assertRaises(ContextTooSmall):
            transfer([], [], 1000, 200, working_state={'original_task':'x'*10000})

    def test_finalization_keeps_observation_body(self):
        view, _ = transfer([Message('system','fixed'), Message('assistant',tool_calls=[ToolCall('a','read_file','{}')]),
                            Message('tool','important content', tool_call_id='a')], None, 5000, 500,
                           final_only=True, working_state={'original_task':'deliver'})
        self.assertTrue(any(m.role=='tool' and m.content=='important content' for m in view))

    def test_request_prefix_extends_history_without_snapshot_accumulation(self):
        messages = [Message('system', 'fixed'), Message('user','task')]
        first, _ = transfer(messages, [], 5000, 500, working_state={'budget': 1})
        messages.append(Message('assistant','more'))
        second, _ = transfer(messages, [], 5000, 500, working_state={'budget': 2})
        self.assertEqual(first[:-1], second[:len(first)-1])
        self.assertEqual(len(messages), 3)

    def test_checkpoint_engine_identity_and_stable_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def make(enabled):
                return AgentSession(create_default_registry(root), backend=Backend(answer('done')),
                    policy='cloud-only', streaming=False, engine_policy=EngineV5Policy() if enabled else None,
                    budgets=SessionBudgets(max_steps=5,max_token_units=500000))
            session=make(True); result=session.run_turn('synthetic task')
            self.assertEqual(result.status, 'completed')
            self.assertEqual(result.prompt_version,'localpilot-v5-v1')
            self.assertEqual(len([m for m in session.messages if m.role=='user']),1)
            snapshot=snapshot_runtime(session)
            restored=make(True); restore_runtime(restored,snapshot)
            self.assertEqual(restored.messages,session.messages)
            self.assertEqual(configuration(restored),configuration(session))
            with self.assertRaises(PersistenceError): restore_runtime(make(False),snapshot)
            session.close();restored.close()


if __name__=='__main__':unittest.main()
