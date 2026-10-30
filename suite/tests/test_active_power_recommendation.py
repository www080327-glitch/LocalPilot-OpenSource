import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from localpilot_suite.product_control import hardware


CUSTOM='Battery Power:\n lowpowermode 1\nAC Power:\n lowpowermode 0\n'


class ActivePowerRecommendationTests(unittest.TestCase):
    def observe(self, source='AC Power', custom=CUSTOM, after=None):
        states=iter([source,after or source])
        def run(args,**kwargs):
            if args[0].endswith('system_profiler'):text=json.dumps({'SPDisplaysDataType':[]})
            elif args[-1]=='custom':text=custom
            else:text=f"Now drawing from '{next(states)}'\n"
            return subprocess.CompletedProcess(args,0,stdout=text,stderr='')
        with tempfile.TemporaryDirectory() as folder, patch('hardware.get_hardware',return_value={'os':'Darwin','arch':'arm64','chip':'Apple test'}), patch('psutil.virtual_memory',return_value=SimpleNamespace(total=64*1024**3,available=48*1024**3)), patch('recommender.recommend',return_value={'model':{'artifact_gb':3},'reason':'fixture'}), patch('localpilot_suite.product_control.subprocess.run',side_effect=run), patch('localpilot_suite.product_control.backend_settings',side_effect=ValueError('no model')), patch('localpilot_suite.product_control.installation_state',return_value='first_launch'):
            return hardware(Path(folder))

    def test_ac_recommendation_does_not_inherit_battery_low_power(self):
        value=self.observe()
        self.assertTrue(value['recommendation']['power_compatible'])
        self.assertEqual(value['hardware']['active_power_source'],'AC Power')
        self.assertIs(value['hardware']['active_low_power_mode'],False)

    def test_battery_profile_stays_constrained(self):
        self.assertFalse(self.observe('Battery Power')['recommendation']['power_compatible'])

    def test_ac_low_power_stays_constrained(self):
        self.assertFalse(self.observe(custom=CUSTOM.replace('lowpowermode 0','lowpowermode 1'))['recommendation']['power_compatible'])

    def test_unknown_source_and_missing_or_conflicting_profile_fail_closed(self):
        for source,custom in [('unrecognized',CUSTOM),('AC Power','Battery Power:\n lowpowermode 0\n'),('AC Power',CUSTOM+' lowpowermode 1\n')]:
            with self.subTest(source=source,custom=custom):
                self.assertFalse(self.observe(source,custom)['recommendation']['power_compatible'])

    def test_transition_during_observation_fails_closed(self):
        value=self.observe(after='Battery Power')
        self.assertFalse(value['recommendation']['power_compatible'])
        self.assertEqual(value['hardware']['active_power_source'],'UNKNOWN')
