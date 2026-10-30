import subprocess
import unittest
from unittest.mock import patch

from companion.config import Config
from companion.runtime.power import LowPowerPolicy


CUSTOM = 'Battery Power:\n lowpowermode 1\nAC Power:\n lowpowermode 0\n'


class ActiveSystemPowerTests(unittest.TestCase):
    def policy(self):
        return LowPowerPolicy(Config(low_power_policy='system'))

    def run_source(self, source, custom=CUSTOM, after=None):
        sequence = [f"Now drawing from '{source}'\n", custom,
                    f"Now drawing from '{after or source}'\n"]
        with patch('companion.runtime.power.sys.platform', 'darwin'), patch(
                'companion.runtime.power.subprocess.check_output', side_effect=sequence):
            return self.policy().active()

    def test_ac_profile_does_not_inherit_battery_low_power(self):
        self.assertFalse(self.run_source('AC Power'))

    def test_battery_profile_keeps_its_low_power_guard(self):
        self.assertTrue(self.run_source('Battery Power'))

    def test_ac_low_power_is_respected(self):
        self.assertTrue(self.run_source('AC Power', CUSTOM.replace('lowpowermode 0', 'lowpowermode 1')))

    def test_missing_or_conflicting_current_profile_fails_closed(self):
        for custom in ['Battery Power:\n lowpowermode 0\n', CUSTOM + ' lowpowermode 1\n',
                       'AC Power:\nUnknown Power:\n lowpowermode 0\n']:
            with self.subTest(custom=custom):
                self.assertTrue(self.run_source('AC Power', custom))

    def test_unknown_power_source_fails_closed(self):
        with patch('companion.runtime.power.sys.platform', 'darwin'), patch(
                'companion.runtime.power.subprocess.check_output', return_value='unrecognized source'):
            self.assertTrue(self.policy().active())

    def test_source_transition_during_read_fails_closed(self):
        self.assertTrue(self.run_source('AC Power', after='Battery Power'))

    def test_source_transition_invalidates_cached_ac_observation(self):
        policy = self.policy()
        sequence = ["Now drawing from 'AC Power'\n", CUSTOM, "Now drawing from 'AC Power'\n",
                    "Now drawing from 'Battery Power'\n", CUSTOM, "Now drawing from 'Battery Power'\n"]
        with patch('companion.runtime.power.sys.platform', 'darwin'), patch(
                'companion.runtime.power.subprocess.check_output', side_effect=sequence):
            self.assertFalse(policy.active())
            self.assertTrue(policy.active())

    def test_unavailable_system_query_fails_closed(self):
        with patch('companion.runtime.power.sys.platform', 'darwin'), patch(
                'companion.runtime.power.subprocess.check_output', side_effect=subprocess.TimeoutExpired('pmset', 2)):
            self.assertTrue(self.policy().active())
