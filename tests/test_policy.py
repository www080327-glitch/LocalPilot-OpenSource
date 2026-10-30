import unittest
from agent.policy import LocalRunConfig


class LocalRunPolicyTests(unittest.TestCase):
    def test_local_first_no_arbitrary_64k_cloud_threshold(self):
        for context in (16, 32, 64, 128):
            self.assertEqual(LocalRunConfig("local_first", context).decision()["primary"], "local")

    def test_balanced_cannot_claim_optimal_route_without_task_evidence(self):
        self.assertEqual(LocalRunConfig("balanced").decision()["primary"], "undecided")

    def test_local_override_does_not_require_minimal(self):
        self.assertEqual(LocalRunConfig("balanced", local_primary_override=True).decision()["primary"], "local")

    def test_cloud_and_local_only_postures(self):
        self.assertEqual(LocalRunConfig("cloud_only").decision()["local_role"], "disabled")
        self.assertEqual(LocalRunConfig("local_only").decision()["primary"], "local")

    def test_strategy_values_are_validated(self):
        with self.assertRaises(ValueError):
            LocalRunConfig("mostly_local")
