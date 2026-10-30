"""Permission, source and cost controls; fake backend outputs are MOCK_ONLY."""
import unittest

from companion.model.routing import TieredInference
from companion.model.reliability import evidence_class, host_gate


class Backend:
    def __init__(self, *results, available=True):
        self.results = list(results) or [{"status": "ok", "text": "简短说明。"}]
        self.calls = []
        self.is_available = available
        self.stopped = False
        self.unloaded = 0

    def available(self):
        return self.is_available

    def complete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return dict(self.results[min(len(self.calls) - 1, len(self.results) - 1)])

    def unload(self):
        self.unloaded += 1

    def request_stop(self):
        self.stopped = True

    def tick(self):
        pass

    def stats(self):
        return {"calls": len(self.calls)}


def prompt(question):
    return [{"role": "system", "content": "本地只读助手。"}, {"role": "user", "content": question}]


class RoutingBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.one, self.two = Backend(), Backend()
        self.router = TieredInference(self.one, self.two)

    def test_many_background_switches_never_call_stronger_model(self):
        for index in range(20):
            q = "分析普通应用切换"
            self.router.complete(prompt(q), question=q, force_deep=True, low_confidence=True,
                                 background=True, observations=[{"kind": "app_switch", "id": str(index)}])
        self.assertEqual(len(self.one.calls), 20)
        self.assertEqual(self.two.calls, [])

    def test_deep_local_understanding_is_not_tool_dispatch(self):
        result = self.router.complete(prompt("深入分析这些资料"), question="深入分析这些资料")
        self.assertEqual(result["routing"]["level"], 2)
        self.assertFalse(result["routing"]["requires_confirmation"])
        self.assertEqual(self.one.calls, [])
        self.assertEqual(len(self.two.calls), 1)

    def test_explicit_execution_prepares_confirmation_without_model_or_network(self):
        result = self.router.complete(prompt("帮我修改文件"), question="帮我修改文件")
        self.assertEqual(result["status"], "needs_confirmation")
        self.assertEqual(result["routing"]["level"], 3)
        self.assertEqual(result["routing"]["cloud_transfer"], "not_authorized_by_routing")
        self.assertEqual(self.one.calls + self.two.calls, [])

    def test_permission_gate_precedes_force_agent(self):
        result = self.router.complete(prompt("读取访问令牌"), question="读取访问令牌", requires_agent=True)
        self.assertEqual(result["status"], "denied")
        self.assertEqual(result["routing"]["level"], 0)
        self.assertEqual(self.one.calls + self.two.calls, [])

    def test_question_and_model_inference_do_not_unlock_unknown_work_fact(self):
        memories = [{"type": "conversation", "epistemic": "factual", "summary": "我的项目代号是幽灵吗？"},
                    {"type": "reflection", "epistemic": "inferred", "summary": "可能是幽灵"}]
        result = self.router.complete(prompt("我的项目代号是什么？"), question="我的项目代号是什么？", memories=memories)
        self.assertFalse(result["model_called"])
        self.assertEqual(self.one.calls + self.two.calls, [])
        self.assertEqual(evidence_class(memories[0]), "SPEECH_RECORD")

    def test_explicit_user_fact_is_preserved(self):
        memories = [{"id": "fact", "type": "user_fact", "epistemic": "factual", "summary": "代号为木兰"}]
        result = self.router.complete(prompt("我的项目代号是什么？"), question="我的项目代号是什么？", memories=memories)
        self.assertTrue(result["model_called"])
        self.assertIn("USER_CONFIRMED", self.one.calls[0][0][0]["content"])

    def test_l2_unavailable_degrades_visibly_without_cloud(self):
        self.two.is_available = False
        result = self.router.complete(prompt("深入分析资料"), question="深入分析资料")
        self.assertEqual(result["routing"]["requested_level"], 2)
        self.assertEqual(result["routing"]["level"], 1)
        self.assertTrue(result["routing"]["degraded"])
        self.assertEqual(len(self.one.calls), 1)
        self.assertEqual(self.two.calls, [])

    def test_multi_document_simple_fact_does_not_trigger_upgrade(self):
        memories = [{"type": "document", "id": "a"}, {"type": "document", "id": "b"}]
        self.assertEqual(self.router.plan("负责人是谁？", memories=memories).level, 1)
        self.assertEqual(self.router.plan("综合比较资料", memories=memories).level, 2)

    def test_bad_l1_uses_one_l2_attempt_and_never_l3(self):
        self.one.results = [{"status": "truncated", "text": "未结束"}]
        self.two.results = [{"status": "unavailable", "error": "offline"}]
        result = self.router.complete(prompt("介绍一个概念"), question="介绍一个概念")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual([row["level"] for row in result["attempts"]], [1, 2])
        self.assertEqual(result["routing"]["level"], 2)
        self.assertEqual(self.router.counts["l3_prepared"], 0)

    def test_invalid_structured_output_is_not_locally_rewritten(self):
        self.one.results = [{"status": "ok", "text": "nonsense"}]
        self.two.results = [{"status": "ok", "text": '{"route":"local","confidence":0.9}'}]
        result = self.router.complete(prompt("比较资料"), question="比较资料", schema="route")
        self.assertEqual(result["text"], self.two.results[0]["text"])
        self.assertEqual([r["level"] for r in result["attempts"]], [1, 2])

    def test_partial_disclosure_is_host_evidence_not_model_credit(self):
        observations = [{"id": "ax", "evidence_epistemic": "source_record", "evidence": {"read_status": "READ_PARTIAL"}}]
        result = self.router.complete(prompt("看到了什么"), question="看到了什么", observations=observations)
        self.assertIn("Host观察范围", result["text"])
        self.assertEqual(result["attempts"][0]["result"]["text"], "简短说明。")
        self.assertEqual(result["reliability"]["general_factual_accuracy"], "UNKNOWN")

    def test_unsupported_cause_is_withheld_and_retried(self):
        self.one.results = [{"status": "ok", "text": "因为网络配置错误导致连接失败。"}]
        self.two.results = [{"status": "ok", "text": "可以看到连接失败提示，无法确认原因。"}]
        result = self.router.complete(prompt("能确认原因吗"), question="能确认原因吗",
                                     observations=[{"id": "ax", "evidence": {"read_status": "READ_PARTIAL"}}])
        self.assertEqual(result["routing"]["level"], 2)
        self.assertEqual(result["attempts"][0]["reliability"]["issues"], ["unsupported_causal_or_difficulty_assertion"])
        self.assertNotIn("配置错误", result["text"])

    def test_submitted_task_is_not_completed(self):
        self.one.results = [{"status": "ok", "text": "任务已经完成。"}]
        self.two.results = [{"status": "ok", "text": "任务已完成。"}]
        result = self.router.complete(prompt("任务状态"), question="任务状态",
                                     observations=[{"source": "localpilot", "kind": "task_result", "evidence": {"task_status": "queued"}}])
        self.assertEqual(result["status"], "unverified")
        self.assertNotIn("已完成", result["text"])

    def test_stop_unload_reach_both_owned_backends(self):
        self.router.request_stop()
        self.router.unload()
        self.assertTrue(self.one.stopped and self.two.stopped)
        self.assertEqual((self.one.unloaded, self.two.unloaded), (1, 1))

    def test_background_instruction_text_never_prepares_task(self):
        plan = self.router.plan("帮我修改文件", requires_agent=True, background=True)
        self.assertEqual(plan.level, 1)
        self.assertFalse(plan.requires_confirmation)

    def test_string_provenance_is_not_a_type_crash_or_authority(self):
        self.assertEqual(evidence_class({"provenance": "validation-source"}), "UNKNOWN")

    def test_causal_assertion_is_not_hidden_by_later_uncertainty(self):
        self.one.results = [{"status": "ok", "text": "这通常表示文件未记录，因此无法证明用户遇到困难。"}]
        self.two.results = self.one.results
        result = self.router.complete(prompt("能判断原因吗"), question="能判断原因吗",
                                     observations=[{"id": "ax", "evidence": {"read_status": "UNKNOWN"}}])
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["attempts"][0]["reliability"]["issues"], ["unsupported_causal_or_difficulty_assertion"])

    def test_mixed_speaker_recall_triggers_l2_context_reasoning(self):
        memories = [{"type": "conversation", "metadata": {"role": "user"}},
                    {"type": "conversation", "metadata": {"role": "assistant"}}]
        plan = self.router.plan("我刚才说过什么？", memories=memories)
        self.assertEqual(plan.level, 2)
        self.assertEqual(plan.reason, "role_sensitive_history")

    def test_explaining_missing_evidence_is_not_a_causal_diagnosis(self):
        self.one.results = [{"status": "ok", "text": "无法确认具体故障原因，因为资料仅记录了该文字出现，未提供原因。"}]
        result = self.router.complete(prompt("原因是什么"), question="原因是什么",
                                     observations=[{"evidence": {"read_status": "READ_PARTIAL"}}])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.two.calls, [])

    def test_negative_consequence_does_not_hide_positive_causal_link(self):
        self.one.results = [{"status": "ok", "text": "这通常意味着网络请求未能完成。"}]
        self.two.results = self.one.results
        result = self.router.complete(prompt("观察到了什么"), question="观察到了什么",
                                     observations=[{"evidence": {"read_status": "READ_PARTIAL"}}])
        self.assertEqual(result["status"], "unverified")

    def test_execution_status_question_does_not_prepare_new_task(self):
        self.assertEqual(self.router.plan("你刚才帮我修改文件了吗？").level, 1)
        self.assertFalse(self.router.plan("你刚才帮我修改文件了吗？").requires_confirmation)

    def test_explanation_of_action_does_not_dispatch_action(self):
        self.assertEqual(self.router.plan("请解释如何修改文件").level, 1)
        self.assertEqual(self.router.plan("请解释这个问题，然后修改文件").level, 3)

    def test_pause_during_l1_failure_prevents_reload_into_l2(self):
        state = {"paused": False}
        def call(messages, **kwargs):
            state["paused"] = True
            return {"status": "unavailable", "error": "child terminated by privacy pause"}
        self.one.complete = call
        result = self.router.complete(prompt("观察摘要"), question="观察摘要", cancelled=lambda: state["paused"])
        self.assertEqual(result["reliability"]["reason"], "model_cancelled")
        self.assertEqual(self.two.calls, [])

    def test_pause_withholds_successful_inflight_response(self):
        state = {"paused": False}
        def call(messages, **kwargs):
            state["paused"] = True
            return {"status": "ok", "text": "暂停前的内容"}
        self.one.complete = call
        result = self.router.complete(prompt("观察摘要"), question="观察摘要", cancelled=lambda: state["paused"])
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("暂停前的内容", result["text"])
        self.assertEqual(self.two.calls, [])

    def test_failed_generation_preserves_host_partial_limits(self):
        self.one.results = [{"status": "truncated", "text": "不完整原始句子"}]
        self.two.is_available = False
        result = self.router.complete(prompt("总结观察"), question="总结观察",
                                     observations=[{"evidence": {"read_status": "READ_PARTIAL"}}])
        self.assertEqual(result["status"], "truncated")
        self.assertIn("Host观察范围", result["text"])
        self.assertNotIn("不完整原始句子", result["text"])
        self.assertEqual(result["attempts"][0]["result"]["text"], "不完整原始句子")

    def test_explicit_unknown_identity_remains_unknown(self):
        self.assertEqual(evidence_class({"type": "user_fact", "epistemic": "factual", "evidence_type": "UNKNOWN"}), "UNKNOWN")

    def test_denied_data_does_not_depend_on_model_availability(self):
        self.assertEqual(host_gate("总结这份资料", permission_denied=True)["reason"], "permission_boundary")


if __name__ == "__main__":
    unittest.main()
