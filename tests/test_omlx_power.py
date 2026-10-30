"""Current power profile governs large-model admission; never changes power."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from agent.omlx import OMLXBackend
from agent.local_http import LocalBackendError

class OmlxPowerTests(unittest.TestCase):
    def backend(self):
        b=OMLXBackend(base_url='http://127.0.0.1:8020/v1',model='fixture')
        b.inspect_service=lambda:{'models':[{'id':'fixture','loaded':True,'deployment_status':'ready','size_bytes':3*1024**3}]}
        return b
    @patch('agent.omlx.sys.platform','darwin')
    def test_current_ac_profile_is_used_instead_of_inactive_battery_profile(self):
        def pmset(argv,**kwargs):
            self.assertEqual(argv,['/usr/bin/pmset','-g'])
            return SimpleNamespace(stdout='Currently in use:\n lowpowermode 0\n')
        with patch('agent.omlx.subprocess.run',side_effect=pmset):self.backend()._admit()
    @patch('agent.omlx.sys.platform','darwin')
    def test_current_low_power_or_unknown_profile_still_blocks_large_models(self):
        for output in ('Currently in use:\n lowpowermode 1\n','unavailable'):
            with patch('agent.omlx.subprocess.run',return_value=SimpleNamespace(stdout=output)):
                with self.assertRaises(LocalBackendError):self.backend()._admit()
