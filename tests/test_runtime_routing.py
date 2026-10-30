import unittest
from types import SimpleNamespace

from agent.routing import (
    EligibilityConfig, FallbackReason, ModelSwitchRequest, RoutingPolicy,
    local_main_eligible, parse_policy, switch_allowed,
)


class RuntimeRoutingTests(unittest.TestCase):
    def test_policy_names_accept_hyphen_and_underscore(self):
        self.assertEqual(parse_policy("local-first"), RoutingPolicy.LOCAL_FIRST)
        self.assertEqual(parse_policy("local_first"), RoutingPolicy.LOCAL_FIRST)

    def test_local_eligibility_requires_health_and_model_metadata(self):
        def backend(size="12B", context=65536, healthy=True):
            return SimpleNamespace(
                is_local=True,
                health_check=lambda: healthy,
                model_info=SimpleNamespace(size_class=size, effective_context=context),
            )
        self.assertTrue(local_main_eligible(backend()))
        self.assertFalse(local_main_eligible(backend(size="4B")))
        self.assertFalse(local_main_eligible(backend(context=65535)))
        self.assertFalse(local_main_eligible(backend(healthy=False)))
        self.assertFalse(local_main_eligible(SimpleNamespace(health_check=lambda: True)))

    def test_eligibility_config_can_change_heuristics(self):
        candidate = SimpleNamespace(
            is_local=True,
            health_check=lambda: True,
            model_info=SimpleNamespace(size_class="4B", effective_context=4096),
        )
        config = EligibilityConfig(excluded_size_classes=(), min_context=4096)
        self.assertTrue(local_main_eligible(candidate, config))

    def test_cloud_backend_and_invalid_configuration_are_ineligible_or_rejected(self):
        backend = SimpleNamespace(
            is_local=False,
            health_check=lambda: True,
            model_info=SimpleNamespace(size_class="12B", effective_context=65536),
        )
        self.assertFalse(local_main_eligible(backend))
        with self.assertRaises(ValueError):
            EligibilityConfig(min_context=True)
        with self.assertRaises(ValueError):
            EligibilityConfig(excluded_size_classes=["4B"])

    def test_local_only_and_cloud_only_cannot_cross_boundary(self):
        self.assertFalse(switch_allowed("local_only", "local", "cloud", "complex", True, 0)[0])
        self.assertFalse(switch_allowed("cloud_only", "cloud", "local", "simple", True, 0)[0])

    def test_complexity_rules_and_local_eligibility_apply(self):
        self.assertTrue(switch_allowed("balanced", "cloud", "local", "simple", True, 0)[0])
        self.assertFalse(switch_allowed("balanced", "cloud", "local", "complex", True, 0)[0])
        self.assertTrue(switch_allowed("cloud_first", "cloud", "local", "very_simple", True, 0)[0])
        self.assertFalse(switch_allowed("cloud_first", "cloud", "local", "simple", True, 0)[0])
        self.assertFalse(switch_allowed("balanced", "cloud", "local", "simple", False, 0)[0])

    def test_local_first_fallback_and_switch_limit(self):
        allowed, reason = switch_allowed("local_first", "local", "cloud", "complex", False, 0)
        self.assertTrue(allowed)
        self.assertEqual(reason, FallbackReason.MODEL_CAPABILITY_ESCALATION.value)
        self.assertFalse(switch_allowed("local_first", "local", "cloud", "complex", False, 1)[0])

    def test_switch_request_is_data_only(self):
        request = ModelSwitchRequest("local", "cloud", "failure", data_boundary_change=("private",))
        self.assertTrue(request.requires_user_confirmation)
        self.assertEqual(request.scope, "turn")


if __name__ == "__main__":
    unittest.main()
