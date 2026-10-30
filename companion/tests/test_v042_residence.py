"""Evidence accounting must not turn missing/restarted processes into full cost."""
import unittest

from companion.benchmark.v042_residence import run, summary


def sample(at, pid=1, created=10, cpu=0, rss=10*2**20):
    return {"elapsed_seconds":at,
            "processes":[{"pid":pid,"created":created,"cpu_seconds":cpu,"rss_bytes":rss}],
            "status":{"service_cpu_seconds":cpu,"service_rss_bytes":rss,
                "model":{"worker_rss_bytes":None,"inferences":0},"queue_depth":0,
                "totals":{},"db_bytes":4096,"notification_count":0}}


class ResidenceEvidenceTests(unittest.TestCase):
    def test_short_or_missing_samples_do_not_claim_resources(self):
        self.assertEqual(summary([]), {})
        self.assertEqual(summary([sample(0)]), {})
        self.assertEqual(summary([sample(0),sample(0)]), {})

    def test_cpu_has_one_core_units_and_stays_lower_bound_across_pid_reuse(self):
        a,b,c=sample(0,cpu=2),sample(10,cpu=3),sample(20,created=11,cpu=10)
        result=summary([a,b,c])
        self.assertEqual(result["sampled_owned_tree_cpu_percent_one_core_lower_bound"],5)
        self.assertEqual(result["process_identities_seen"],2)
        self.assertIsNone(result["power_watts"])

    def test_no_observation_does_not_produce_perfect_dedupe(self):
        result=summary([sample(0),sample(10)])
        self.assertIsNone(result["dedupe_ratio"])
        self.assertEqual(result["event_rate_per_second"],0)

    def test_invalid_duration_is_rejected_before_creating_process_or_evidence(self):
        for duration in (float("nan"),float("inf"),0,172801):
            with self.assertRaises(ValueError):
                run("/nonexistent/v042-should-never-create.json",seconds=duration)

    def test_ax_and_model_arms_fail_without_real_providers(self):
        with self.assertRaises(ValueError):
            run("/nonexistent/v042-should-never-create.json",arm="B")
        with self.assertRaises(ValueError):
            run("/nonexistent/v042-should-never-create.json",arm="C",helper="x",
                controlled_target={"bundle_id":"org.localpilot.test"})


if __name__ == "__main__":
    unittest.main()
