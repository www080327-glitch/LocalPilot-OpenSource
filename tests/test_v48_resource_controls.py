"""Host resource controls, not real-model success measurements."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from benchmarks.v48_power import foreign_model_footprints,serve
from benchmarks.v48_runtime import cloud_ceiling


class V48ResourceControls(unittest.TestCase):
    def test_compressed_metal_footprint_is_used_instead_of_rss(self):
        from types import SimpleNamespace
        with patch('benchmarks.v48_power.subprocess.check_output',return_value='42 omlx-server\n'),patch('benchmarks.v48_power.subprocess.run',return_value=SimpleNamespace(stdout='Physical footprint: 27.9G\n',returncode=0)):
            row=foreign_model_footprints()[0]
        self.assertEqual(row['physical_bytes'],27.9*1024**3)

    def test_large_foreign_model_refuses_another_load_without_stopping_it(self):
        with tempfile.TemporaryDirectory() as d,patch('benchmarks.v48_power.require'),patch('benchmarks.v48_power.foreign_model_footprints',return_value=[{'pid':42,'physical_bytes':28*1024**3}]),patch('benchmarks.v48_power.subprocess.Popen') as launch:
            with self.assertRaisesRegex(RuntimeError,'non-owned large model'):serve(Path(d))
            launch.assert_not_called()
            self.assertTrue((Path(d)/'foreign-model-prestart-check.json').exists())

    def test_unmeasured_foreign_model_refuses_load(self):
        with tempfile.TemporaryDirectory() as d,patch('benchmarks.v48_power.require'),patch('benchmarks.v48_power.foreign_model_footprints',return_value=[{'pid':42,'physical_bytes':None}]):
            with self.assertRaises(RuntimeError):serve(Path(d))

    def test_comparison_budget_cannot_be_raised_by_spec_fields(self):
        self.assertEqual(cloud_ceiling({'split':'final_evaluation','cloud_cost_upper_usd':.6}),.12)

    def test_only_declared_bounded_long_budget_is_accepted(self):
        self.assertEqual(cloud_ceiling({'split':'long_engineering','long_scenario':'integration','cloud_cost_upper_usd':.6}),.6)
        with self.assertRaises(ValueError):cloud_ceiling({'split':'long_engineering','long_scenario':'integration','cloud_cost_upper_usd':1})


if __name__=='__main__':unittest.main()
